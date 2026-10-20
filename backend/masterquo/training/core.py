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

import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .. import paths

EXEC = ("NIE_URUCHOMIONE", "W_TOKU", "UKONCZONE", "POMINIETE", "BLAD_TECHNICZNY", "ANULOWANE")
QUAL = ("NIE_DOTYCZY", "BRAK_PRZESLANEK", "ODRZUCONY", "NIEZWALIDOWANY", "CZESCIOWO_ZWALIDOWANY", "ZWALIDOWANY_SHADOW", "TEST_TECHNICZNY")
INTEG = ("NIEZAPISANY", "ZAPISANY_DO_BADAN", "AKTYWNY_W_REJESTRZE", "ZALADOWANY_DO_SHADOW", "ROLLBACK")
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
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    os.replace(tmp, path)


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


# ------------------------------------------------------------------ single runner lock
def lock_path() -> Path:
    return training_dir() / "RUNNING.lock"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)       # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return code.value == 259                                        # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def acquire_lock(run_id: str) -> str | None:
    """Returns None when acquired, otherwise the id of the run in progress."""
    p = lock_path()
    try:
        cur = json.loads(p.read_text(encoding="utf-8"))
        if _pid_alive(int(cur.get("pid", 0))) and cur.get("run_id") != run_id:
            return cur.get("run_id")
    except (OSError, ValueError):
        pass
    write_json_atomic(p, {"run_id": run_id, "pid": os.getpid(), "at": now()})
    return None


def release_lock(run_id: str) -> None:
    p = lock_path()
    try:
        if json.loads(p.read_text(encoding="utf-8")).get("run_id") == run_id:
            p.unlink()
    except (OSError, ValueError):
        pass


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
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return round(int(line.split()[1]) / 1024)
    except Exception:  # noqa: BLE001
        return None
    return None


def child_env(plan: dict, instrument: str | None = None) -> dict:
    """Environment of every child: thread limits, instrument space, training flag (no order path), UTF-8."""
    th = str(plan["threads"])
    env = dict(os.environ, PYTHONPATH=str(paths.ROOT_DIR / "backend"), MASTERQUO_DATA_DIR=str(paths.data_dir()), PYTHONIOENCODING="utf-8",
               OMP_NUM_THREADS=th, MKL_NUM_THREADS=th, OPENBLAS_NUM_THREADS=th, NUMEXPR_NUM_THREADS=th, MQ_TRAINING="1")
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
        p = subprocess.Popen(cmd, cwd=str(paths.ROOT_DIR / "backend"), env=env, stdout=lf, stderr=subprocess.STDOUT, **kw)
        while p.poll() is None:
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
    run.set(tid, seconds=round(time.monotonic() - t0, 1))
    return p.returncode, child_reason(log_p.read_text(encoding="utf-8", errors="replace")[-6000:], log_p)


def child_reason(text: str, log_p: Path | None = None) -> str:
    """What the child said, without our own '=== <time> <command>' echo (it pushed the real [BLAD] line out of the summary).
    [BLAD] lines and the last traceback line first; the log path last so the user can open the full output."""
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip() and not ln.startswith("=== ")]
    key = [ln for ln in lines if "[BLAD]" in ln or "BLOCKED" in ln or ln.startswith(("Traceback", "Error", "Exception")) or "Error:" in ln]
    body = " | ".join((key or lines)[-4:]) if lines else "proces nie wypisał nic (sprawdź log)"
    return body[-1500:] + (f" (log: {log_p})" if log_p else "")


def bot_python() -> str:
    return sys.executable


def candles_python() -> str | None:
    env = os.environ.get("MQ_CANDLES_PYTHON")
    if env and Path(env).exists():
        return env
    for p in (paths.ROOT_DIR / ".venv_candles" / "Scripts" / "python.exe", paths.ROOT_DIR / ".venv_candles" / "bin" / "python"):
        if p.exists():
            return str(p)
    return None
