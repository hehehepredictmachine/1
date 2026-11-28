"""Run state, three-axis statuses, frozen plan, locks and child processes of the training orchestrator.

Status of every task has THREE independent axes (an exit code 0, a COMPLETED job, a .pkl on disk or an HTTP 200 never mean
"good model"):
  execution:   NIE_URUCHOMIONE | W_TOKU | UKONCZONE | POMINIETE | BLAD_TECHNICZNY | ANULOWANE
  quality:     NIE_DOTYCZY | BRAK_PRZESLANEK (za mało danych / zdarzeń) | ODRZUCONY | NIEZWALIDOWANY | CZESCIOWO_ZWALIDOWANY
               | ZWALIDOWANY_SHADOW | TEST_TECHNICZNY (dane syntetyczne / profil testowy)
  integration: NIEZAPISANY | ZAPISANY_DO_BADAN | AKTYWNY_W_REJESTRZE | ZALADOWANY_DO_SHADOW | ROLLBACK

Exit codes of `masterquo training run` (documented in START_TUTAJ_TRENING_PL.md):
  0 every requested task executed (quality may still be REJECTED / BRAK_PRZESLANEK - see the report)
  1 at least one task ended with a technical error
  2 blocked before training (no MT5 / no symbol / no data / another run in progress)
  3 cancelled by the user (resume: menu -> Wznów)
  4 executed with skipped tasks (missing environment, commission, RAM ...)
"""
from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .. import locks as _LOCKS
from .. import paths

EXEC = ("NIE_URUCHOMIONE", "W_TOKU", "UKONCZONE", "POMINIETE", "BLAD_TECHNICZNY", "ANULOWANE")
# 1.46: DO_OCENY_NA_DEV (trained on dev, holdout not opened) and RAPORT_WALIDACJI (sh_pack verdict report) are written by the runner -
# they were missing on the axes (raw codes in the report and in the training center)
QUAL = ("NIE_DOTYCZY", "BRAK_PRZESLANEK", "ODRZUCONY", "NIEZWALIDOWANY", "CZESCIOWO_ZWALIDOWANY", "ZWALIDOWANY_SHADOW", "TEST_TECHNICZNY",
        "DO_OCENY_NA_DEV")
INTEG = ("NIEZAPISANY", "ZAPISANY_DO_BADAN", "AKTYWNY_W_REJESTRZE", "ZALADOWANY_DO_SHADOW", "ROLLBACK", "RAPORT_WALIDACJI")
STATE_SCHEMA = "mq-training-run-1"


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def training_dir() -> Path:
    d = paths.data_dir() / "training"
    d.mkdir(parents=True, exist_ok=True)
    return d


def runs_dir() -> Path:
    d = training_dir() / "runs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def profiles() -> dict:
    return json.loads((paths.ROOT_DIR / "config" / "training_profiles_v1.json").read_text(encoding="utf-8"))["profiles"]


def new_run_id() -> str:
    return "TR-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:4]


def write_json_atomic(path: Path, payload) -> None:
    """1.46 (I0063): unique temporary file + os.replace (registry_io) - the fixed '<name>.tmp' was shared by every process: two writers
    (runner, training center, a second run starting) replaced each other's half-written file or failed on its rename."""
    from ..registry_io import write_json_atomic as _write
    _write(Path(path), payload)


class Run:
    """state.json of one run: frozen plan + tasks. Written atomically after every change (resume after a crash/cancel)."""

    def __init__(self, run_id: str, state: dict):
        self.run_id, self.state = run_id, state
        self.dir = runs_dir() / run_id

    @classmethod
    def create(cls, plan: dict, tasks: list[dict]) -> "Run":
        rid = plan["run_id"]
        st = {"schema": STATE_SCHEMA, "run_id": rid, "created_at": now(), "plan": plan, "tasks": tasks, "events": [], "status": "PLANNED"}
        r = cls(rid, st)
        r.save()
        return r

    @classmethod
    def load(cls, run_id: str) -> "Run":
        p = runs_dir() / run_id / "state.json"
        return cls(run_id, json.loads(p.read_text(encoding="utf-8")))

    @staticmethod
    def latest() -> str | None:
        runs = sorted(p.parent.name for p in runs_dir().glob("*/state.json"))
        return runs[-1] if runs else None

    def save(self) -> None:
        self.state["updated_at"] = now()
        write_json_atomic(self.dir / "state.json", self.state)

    def task(self, tid: str) -> dict:
        return next(t for t in self.state["tasks"] if t["id"] == tid)

    def set(self, tid: str, **kw) -> dict:
        t = self.task(tid)
        t.update(kw)
        t["updated_at"] = now()
        self.save()
        return t

    def event(self, msg: str, **kw) -> None:
        self.state["events"].append({"at": now(), "msg": msg, **kw})
        self.state["events"] = self.state["events"][-500:]
        self.save()
        print(f"[TRENING] {msg}", flush=True)

    def cancel_requested(self) -> bool:
        return (self.dir / "CANCEL").exists()


def task(tid: str, instrument: str, kind: str, title: str, **kw) -> dict:
    return {"id": tid, "instrument": instrument, "kind": kind, "title": title, "execution": "NIE_URUCHOMIONE", "quality": "NIE_DOTYCZY",
            "integration": "NIEZAPISANY", "detail": None, "reasons": [], "artifacts": [], **kw}


# ------------------------------------------------------------------ the one lock service of training and export (1.46 arch Etap 4)
# PMW-LOCKS-1 (masterquo/locks.py): names 'train[:<inst>]' (RUNNING.lock below), 'export[:<inst>]' (data/locks/pmw_export.lock, PMW-LOCK-1),
# 'registry:<file>' (OS lock of a registry / activation pointer, trainhub reg_lock), 'job:<name>' (in-process job lock, ML in the bot).
# The implementation is the L0 leaf masterquo/locks.py so that the data / model layers take the same lock without importing this
# orchestrator; this module is the entry of the service and keeps its functions as thin wrappers (same files, records and answers).
LOCKS = _LOCKS


def lock_spec(name: str) -> dict:
    """Description of a named lock of the service ('train:XAUUSD', 'export:BTC', 'registry:<file>', 'job:ml:train')."""
    return _LOCKS.spec(name)


# ------------------------------------------------------------------ single runner lock ('train[:<inst>]' - one runner for all instruments)
def lock_path() -> Path:
    return training_dir() / "RUNNING.lock"


# process identity of a lock owner - moved to masterquo/locks.py (alias zgodności: panel, training center, export_job, Studio, families)
_pid_alive = _LOCKS.pid_alive
_proc_start = _LOCKS.proc_start
pid_alive_as = _LOCKS.pid_alive_as
lock_owner_alive = _LOCKS.owner_alive

LOCK_GUARD_TIMEOUT_S = 30.0


def _run_lock() -> _LOCKS.RunLock:
    """RUNNING.lock through the lock service (locks.RunLock - moved from here, same code). The functions of THIS module are late-bound:
    callers and tests that replace write_json_atomic / lock_owner_alive / _proc_start / now on training.core keep doing so."""
    return _LOCKS.RunLock(lock_path(), guard_timeout_s=LOCK_GUARD_TIMEOUT_S, write=lambda p, d: write_json_atomic(p, d),
                          owner_alive_fn=lambda cur: lock_owner_alive(cur), proc_start_fn=lambda pid: _proc_start(pid), now_fn=lambda: now())


def _lock_guard():
    """1.46 (I0063): OS file lock (registry_io.file_lock: fcntl.flock / msvcrt.locking, released by the OS when a process dies) around the
    read -> check -> write of RUNNING.lock. Without it two runners starting at the same moment both read "free" and both wrote themselves
    as the owner (both trained). The owner record stays in RUNNING.lock (readers: panel, training center, API) - unchanged format."""
    return _run_lock().guard()


def acquire_lock(run_id: str) -> str | None:
    """Returns None when acquired, otherwise the id of the run in progress ('BLOKADA_TRENINGU_ZAJETA' when the guard stays taken)."""
    return _run_lock().acquire(run_id)


def release_lock(run_id: str) -> None:
    _run_lock().release(run_id)


# ------------------------------------------------------------------ resources
def free_ram_mb() -> float | None:
    try:
        if os.name == "nt":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MS()
            m.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return round(m.ullAvailPhys / 1024 / 1024)
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                return round(int(line.split()[1]) / 1024)
    except Exception:  # noqa: BLE001
        return None
    return None


def ram_budget_mb(plan: dict | None = None) -> int:
    """Memory one training child may use (user setting; default runtimes.DEFAULT_RAM_BUDGET_MB = 8 GB). MQ_RAM_BUDGET_MB overrides the
    profile. arch146 I0069: ONE source for every training child of the bot - runner steps (the plan's profile), TrainHub (was a literal
    6144), model families, the ML trainer and Studio jobs (no cap before): MQ_RAM_BUDGET_MB -> the plan's profile -> profile
    PELNY_TRENING -> runtimes.DEFAULT_RAM_BUDGET_MB (1.46 arch I0117: the one default)."""
    from ..runtimes import DEFAULT_RAM_BUDGET_MB
    try:
        env = os.environ.get("MQ_RAM_BUDGET_MB")
        if env:
            return max(512, int(env))
        if plan is not None:
            v = (plan.get("profile_params") or {}).get("ram_budget_mb")
        else:
            try:
                v = (profiles().get("PELNY_TRENING") or {}).get("ram_budget_mb")
            except (OSError, ValueError, KeyError):
                v = None
        return max(512, int(v or DEFAULT_RAM_BUDGET_MB))
    except (ValueError, TypeError):
        return DEFAULT_RAM_BUDGET_MB


def limit_child(proc: subprocess.Popen, plan: dict | None = None) -> None:
    """arch146 I0069: the per-process memory cap of the one RAM budget (ram_budget_mb) for a training child that had none (model families,
    ML trainer, Studio jobs). Memory cap ONLY: the Job Object handle is closed at once (no KILL_ON_JOB_CLOSE) - the child's lifetime and
    its cancel / stop paths are unchanged. Windows only (best effort, never fatal); elsewhere nothing."""
    _job_limit(proc, ram_budget_mb(plan), kill_on_close=False)


def ram_gate(plan: dict, wait_s: float = 180.0, step_s: float = 10.0, sleep=time.sleep) -> tuple[float, str | None]:
    """(scale, note). scale 1.0 = full data; 0 < scale < 1 = run on a proportionally smaller sample (never below 25 %);
    0 = skip (only below hard_min_free_ram_mb after waiting up to wait_s for other programs to release memory)."""
    pp = plan["profile_params"]
    want = min(int(pp.get("min_free_ram_mb") or 2000), ram_budget_mb(plan))
    hard = int(pp.get("hard_min_free_ram_mb") or 600)
    ram = free_ram_mb()
    waited = 0.0
    while ram is not None and ram < want and waited < wait_s:
        sleep(step_s)
        waited += step_s
        ram = free_ram_mb()
    if ram is None or ram >= want:
        return 1.0, None
    if ram < hard:
        return 0.0, f"za mało wolnej pamięci RAM ({ram} MB < {hard} MB) także po {waited:.0f} s oczekiwania – zamknij inne programy"
    scale = max(0.25, ram / want)
    return scale, f"mniej wolnej pamięci ({ram} MB < {want} MB) – zadanie na {scale:.0%} danych"


def _job_limit(proc: subprocess.Popen, mb: int, *, kill_on_close: bool = True) -> None:
    """Windows: put the child in a Job Object with a per-process memory cap (the user's RAM budget). Best effort, never fatal.
    kill_on_close=False (arch146 I0069, limit_child): memory cap only - the handle is closed right away, the job lives with its processes."""
    if os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes

        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in ("r", "w", "o", "rb", "wb", "ob")]

        class BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong), ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

        class EXT(ctypes.Structure):
            _fields_ = [("Basic", BASIC), ("Io", IO), ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]
        k = ctypes.windll.kernel32
        k.CreateJobObjectW.restype = wintypes.HANDLE
        k.OpenProcess.restype = wintypes.HANDLE
        job = k.CreateJobObjectW(None, None)
        info = EXT()
        info.Basic.LimitFlags = 0x100 | (0x2000 if kill_on_close else 0)   # PROCESS_MEMORY | KILL_ON_JOB_CLOSE
        info.ProcessMemoryLimit = mb * 1024 * 1024
        k.SetInformationJobObject(wintypes.HANDLE(job), 9, ctypes.byref(info), ctypes.sizeof(info))
        h = k.OpenProcess(0x1F0FFF, False, proc.pid)
        k.AssignProcessToJobObject(wintypes.HANDLE(job), wintypes.HANDLE(h))
        if h:
            k.CloseHandle(wintypes.HANDLE(h))                      # 1.46: the process handle leaked (one per child, also in the bot - TrainHub)
        if kill_on_close:
            proc._mq_job = job                                     # keep the handle alive as long as the child (close_job after it ended)
        elif job:
            k.CloseHandle(wintypes.HANDLE(job))                    # the job object stays while it has processes; the cap stays with it
    except Exception:  # noqa: BLE001
        pass


def close_job(proc) -> None:
    """1.46: closes the Job Object of a FINISHED child. _job_limit kept the handle as a plain int (never closed by GC): one kernel object
    leaked per child in a long-lived process (menu runner, TrainHub in the bot). KILL_ON_JOB_CLOSE also ends leftovers of that child."""
    job = getattr(proc, "_mq_job", None)
    if not job or os.name != "nt":
        return
    proc._mq_job = None
    import ctypes
    from ctypes import wintypes
    with contextlib.suppress(Exception):
        ctypes.windll.kernel32.CloseHandle(wintypes.HANDLE(job))


def _end_child(p: subprocess.Popen) -> None:
    if p.poll() is not None:
        return
    p.terminate()
    try:
        p.wait(20)
    except subprocess.TimeoutExpired:
        p.kill()
        try:
            p.wait(10)
        except subprocess.TimeoutExpired:
            pass


def child_env(plan: dict, instrument: str | None = None) -> dict:
    """Environment of every child: thread limits, instrument space, MQ_TRAINING=1 marker, UTF-8.

    1.46: MQ_TRAINING is only a marker (no module reads it) - it does NOT block an order path. Training children have no order path of
    their own; the export's MT5 connection is wrapped by forecast.export.NoOrders (order functions raise)."""
    th = str(plan["threads"])
    env = dict(os.environ, PYTHONPATH=str(paths.ROOT_DIR / "backend"), MASTERQUO_DATA_DIR=str(paths.data_dir()), PYTHONIOENCODING="utf-8",
               OMP_NUM_THREADS=th, MKL_NUM_THREADS=th, OPENBLAS_NUM_THREADS=th, NUMEXPR_NUM_THREADS=th, MQ_TRAINING="1",
               MQ_RAM_BUDGET_MB=str(ram_budget_mb(plan)))
    if instrument:
        env["MQ_INSTRUMENT"] = instrument
    if plan.get("synthetic"):
        env["MQ_FORECAST_TEST_ALLOW_SYNTHETIC"] = "0"           # synthetic runs are never activatable
    return env


def run_child(run: Run, tid: str, cmd: list[str], env: dict, timeout_s: float, log_name: str) -> tuple[int | None, str]:
    """Child process with a lower priority, its own log file and cancel/timeout handling. Returns (returncode|None, tail)."""
    log_p = run.dir / "logs" / f"{log_name}.log"
    log_p.parent.mkdir(parents=True, exist_ok=True)
    kw: dict = {}
    if os.name == "nt":
        kw["creationflags"] = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        kw["preexec_fn"] = lambda: os.nice(10)
    run.set(tid, execution="W_TOKU", started_at=now(), log=str(log_p), command=[Path(cmd[0]).name] + cmd[1:])
    t0 = time.monotonic()
    with open(log_p, "a", encoding="utf-8") as lf:
        lf.write(f"\n=== {now()} {' '.join(cmd)}\n")
        lf.flush()
        env = dict(env, PYTHONPATH=paths.child_pythonpath(cmd[0]))   # 1.42.11: Python bota dostaje biblioteki aplikacji (DESKTOP)
        p = subprocess.Popen(cmd, cwd=str(paths.ROOT_DIR / "backend"), env=env, stdout=lf, stderr=subprocess.STDOUT, **kw)
        from ..runtimes import DEFAULT_RAM_BUDGET_MB
        _job_limit(p, int(env.get("MQ_RAM_BUDGET_MB") or DEFAULT_RAM_BUDGET_MB))
        try:
            beat = time.monotonic()
            while p.poll() is None:
                if time.monotonic() - beat >= 120:                 # heartbeat: long tasks must not look frozen
                    beat = time.monotonic()
                    print(f"[TRENING] {tid}: w toku {int((beat - t0) // 60)} min – {_last_line(log_p)} (nie zamykaj okna)", flush=True)
                if run.cancel_requested():
                    p.terminate()
                    try:
                        p.wait(20)
                    except subprocess.TimeoutExpired:
                        p.kill()
                    return None, "ANULOWANE"
                if time.monotonic() - t0 > timeout_s:
                    p.kill()
                    p.wait()
                    return 124, f"TIMEOUT {timeout_s / 60:.0f} min"
                time.sleep(1.0)
        except BaseException:
            # 1.46: Ctrl+C in the menu (KeyboardInterrupt in time.sleep) left the child training unsupervised - on Windows it has no console
            # (CREATE_NO_WINDOW) and never gets Ctrl+C - while execute() released RUNNING.lock: "Wznów" started a second process on the same files
            _end_child(p)
            raise
        finally:
            close_job(p)                                           # 1.46: Job Object handle of the finished child (leak)
    run.set(tid, seconds=round(time.monotonic() - t0, 1))
    return p.returncode, child_reason(log_p.read_text(encoding="utf-8", errors="replace")[-6000:], log_p)


def _last_line(log_p: Path) -> str:
    try:
        with open(log_p, "rb") as fh:
            fh.seek(max(0, fh.seek(0, 2) - 4000))
            lines = [ln for ln in fh.read().decode("utf-8", "replace").splitlines() if ln.strip() and not ln.startswith("=== ")]
        return (lines[-1].strip()[:140]) if lines else "obliczenia trwają"
    except OSError:
        return "obliczenia trwają"


def child_reason(text: str, log_p: Path | None = None) -> str:
    """What the child said, without our own '=== <time> <command>' echo (it pushed the real [BLAD] line out of the summary).
    [BLAD] lines and the last traceback line first; the log path last so the user can open the full output."""
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip() and not ln.startswith("=== ")]
    key = [ln for ln in lines if "[BLAD]" in ln or "BLOCKED" in ln or ln.startswith(("Traceback", "Error", "Exception")) or "Error:" in ln]
    body = " | ".join((key or lines)[-4:]) if lines else "proces nie wypisał nic (sprawdź log)"
    return body[-1500:] + (f" (log: {log_p})" if log_p else "")


def bot_python() -> str:
    return sys.executable


_CANDLES_OK: dict = {}     # process cache: interpreter -> import probe result; reset_candles_cache() is the hook (1.46 arch I0104)
_CANDLES_AT: dict = {}                      # 1.46 (I0074): time of the check per interpreter (max_age_s)


def reset_candles_cache() -> None:
    """Forget the import probes (tests; the installer clears it itself after an installation)."""
    _CANDLES_OK.clear()
    _CANDLES_AT.clear()


def candles_healthy(py: str, max_age_s: float | None = None) -> bool:
    """The interpreter exists AND its pinned packages import (a half-installed venv is treated as missing). Cached per process;
    max_age_s re-checks an older result (the training center polls it - an environment installed meanwhile is seen)."""
    if max_age_s is not None and time.time() - _CANDLES_AT.get(py, 0.0) > max_age_s:
        _CANDLES_OK.pop(py, None)
    if py not in _CANDLES_OK:
        _CANDLES_AT[py] = time.time()
        try:
            r = subprocess.run([py, "-c", "import numpy, pandas, sklearn"], capture_output=True, timeout=120)
            _CANDLES_OK[py] = r.returncode == 0
        except (OSError, subprocess.SubprocessError):
            _CANDLES_OK[py] = False
    return _CANDLES_OK[py]


def ensure_candles(run: "Run") -> tuple[str | None, str | None]:
    """(python, reason). Missing or broken .venv_candles is installed ONCE per run with 10_PROGNOZY_INSTALUJ.bat (no pause) on
    Windows, instead of skipping forecast / scalp tasks. The installer only creates the isolated venv with hashed packages."""
    py = candles_python()
    if py and candles_healthy(py):
        return py, None
    if run.state.get("candles_install_tried"):
        return None, run.state.get("candles_install_reason") or "brak sprawnego .venv_candles"
    run.state["candles_install_tried"] = True
    bat = paths.ROOT_DIR / "10_PROGNOZY_INSTALUJ.bat"
    if os.name != "nt" or not bat.exists():
        reason = "brak sprawnego .venv_candles – uruchom INSTALUJ_TRENING.bat"
    else:
        run.event("brak sprawnego .venv_candles – instaluję automatycznie (10_PROGNOZY_INSTALUJ.bat, kilka minut)")
        env = dict(os.environ, MQ_NO_PAUSE="1")
        try:
            r = subprocess.run(["cmd.exe", "/c", str(bat)], cwd=str(paths.ROOT_DIR), env=env, capture_output=True, text=True, timeout=3600,
                               errors="replace")
            out = (r.stdout or "") + (r.stderr or "")
        except (OSError, subprocess.SubprocessError) as exc:
            out = str(exc)
        _CANDLES_OK.clear()
        py = candles_python()
        if py and candles_healthy(py):
            run.event(".venv_candles zainstalowane")
            run.save()
            return py, None
        reason = "instalacja .venv_candles nie powiodła się: " + child_reason(out[-3000:]) + " – log w data\\logs\\instalacja_prognoz_*.log"
    run.state["candles_install_reason"] = reason
    run.save()
    return None, reason


def candles_python() -> str | None:
    # 1.46 arch (I0117): MQ_CANDLES_PYTHON -> .venv_candles (exists), as before
    from .. import runtimes
    return runtimes.find_python("candles", check=Path.exists)
