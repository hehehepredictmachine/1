"""ONE lock service of training and export (PMW-LOCKS-1, 1.46 arch Etap 4 - docs/arch146/ETAP2_PROJEKT.md §3, §5 "locks").

Before Etap 4 every lock of training and export had its own code (diagnosis trening#6, "7 mechanisms"): RUNNING.lock of the runner
(training/core), PMW-LOCK-1 of the Studio (studio/lock - also taken by marketdata/export and forecast/export, an import from the data and
model layers into the Studio), the registry lock of TrainHub (trainhub/registry.reg_lock), the activation-pointer locks (Quant MetaModel,
lab, mm, Monte Carlo) and the in-process job lock of the ML service. Each of them is now ONE of the mechanisms below, implemented once
here. The old places are thin wrappers: the same lock files, the same owner records, the same expiry and the same answers.
training/core.py is the documented entry of the service (`training.core.LOCKS`); the implementation is this L0 leaf (stdlib + paths +
registry_io) so that marketdata, forecast, trainhub, ml and quant take a lock without importing the Studio or the training orchestrator
(layer guard, tools/cycles.py).

  name              mechanism        lock file (unchanged)                               owner record / expiry (unchanged)
  train[:<inst>]    RUN_OWNER        <data>/training/RUNNING.lock (+ RUNNING.lock.lck    {run_id, pid, started, at}; held while that process
                                     guard: OS lock around read -> check -> write)       (pid + start time) lives - no TTL
  export[:<inst>]   OWNER_HEARTBEAT  <data>/locks/pmw_export.lock (PMW-LOCK-1, O_EXCL)   {pid, app, job, host, acquired_at, heartbeat}; stale
                                                                                         when the pid is dead or the heartbeat is older than
                                                                                         120 s; a stale lock is taken over atomically
  registry:<file>   OS_FILE          <file stem>.lock next to the registry / pointer     fcntl.flock / msvcrt.locking + a thread lock,
                                     (trainhub models/<inst>/registry.lock, Quant ACTIVE) re-entrant per thread, released by the OS
  job:<name>        IN_PROCESS       -                                                   non-blocking thread lock of one service object
                                                                                         (ML training in the bot: JOB_LOCKED)

The instrument in 'train:<inst>' / 'export:<inst>' names WHO holds the lock (owner record, job id 'export:<inst>' /
'export_candles:<inst>' / Studio job id) - it does not split the file: today ONE training runner and ONE MT5 history export run at a time
for every instrument, and that stays (a per-instrument split would change behaviour).

Not locks, kept where they are (listed so that the inventory is complete): the TrainHub queue runs one job at a time in the bot's worker
thread (trainhub/jobs.py), the model families start at most FamilyService.MAX_PARALLEL processes and one job per family+instrument
(modelhub/families/service.py), Quant MetaModel training (`quant train`) takes no training lock - only its activation pointer takes
registry:<ACTIVE.json>. Adding exclusivity where there is none would change behaviour (separate decision, not this step).
"""
from __future__ import annotations

import contextlib
import json
import os
import socket
import threading
import time
from pathlib import Path

from . import registry_io as RIO

VERSION = "PMW-LOCKS-1"
RUN_OWNER, OWNER_HEARTBEAT, OS_FILE, IN_PROCESS = "RUN_OWNER", "OWNER_HEARTBEAT", "OS_FILE", "IN_PROCESS"
RUN_GUARD_TIMEOUT_S = 30.0          # training.core.LOCK_GUARD_TIMEOUT_S
EXPORT_STALE_S = 120.0              # PMW-LOCK-1: a heartbeat older than this = dead owner (studio.lock.Lock stale_s)
REGISTRY_TIMEOUT_S = 60.0           # registry_io.file_lock / trainhub reg_lock (Windows: wait before TimeoutError)
EXPORT_APP_BOT = "PepeMarketWizard-export"      # owner `app` ids of the export lock - identifiers, unchanged (display: marketdata/export)
EXPORT_APP_STUDIO = "PepeTrainingStudio"

# name -> (mechanism, file relative to the bot's data folder or None, expiry, description)
SERVICE: dict[str, dict] = {
    "train": {"mechanism": RUN_OWNER, "file": "training/RUNNING.lock", "ttl_s": None,
              "scope": "jeden runner treningu naraz dla wszystkich instrumentów; właściciel = żywy proces (pid + czas startu)"},
    "export": {"mechanism": OWNER_HEARTBEAT, "file": "locks/pmw_export.lock", "ttl_s": EXPORT_STALE_S,
               "scope": "jeden eksport historii MT5 naraz dla wszystkich instrumentów (bot, runner, Studio)"},
    "registry": {"mechanism": OS_FILE, "file": None, "ttl_s": None,
                 "scope": "odczyt-zmiana-zapis jednego rejestru / wskaźnika aktywacji (plik <nazwa>.lock obok)"},
    "job": {"mechanism": IN_PROCESS, "file": None, "ttl_s": None, "scope": "jedno zadanie naraz w jednym obiekcie usługi (w procesie)"},
}


# ------------------------------------------------------------------ process identity of an owner (moved from training/core - aliases stay)
def pid_alive(pid: int) -> bool:
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


def proc_start(pid: int) -> int | None:
    """1.46: creation time of a live process (Windows: FILETIME from GetProcessTimes; Linux: start ticks from /proc/<pid>/stat). Together
    with the pid it identifies the process - a pid reused by another program after a crash / restart has another start. None = unreadable."""
    if pid <= 0:
        return None
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            k = ctypes.windll.kernel32
            k.OpenProcess.restype = wintypes.HANDLE
            h = k.OpenProcess(0x1000, False, pid)                       # PROCESS_QUERY_LIMITED_INFORMATION
            if not h:
                return None
            try:
                c, e, kt, ut = (wintypes.FILETIME() for _ in range(4))
                if not k.GetProcessTimes(wintypes.HANDLE(h), ctypes.byref(c), ctypes.byref(e), ctypes.byref(kt), ctypes.byref(ut)):
                    return None
                return (int(c.dwHighDateTime) << 32) | int(c.dwLowDateTime)
            finally:
                k.CloseHandle(wintypes.HANDLE(h))
        txt = Path(f"/proc/{int(pid)}/stat").read_text(encoding="ascii", errors="replace")
        return int(txt.rsplit(")", 1)[1].split()[19])                   # field 22 (starttime); the name in (...) may hold spaces
    except Exception:  # noqa: BLE001 - no /proc (macOS) or no access: identity unknown
        return None


def pid_alive_as(pid: int, started) -> bool:
    """1.46: `pid` lives AND is the process that recorded `started` (proc_start). Without a recorded start (files of older versions) or when
    the start cannot be read, only the pid is checked (as before)."""
    if not pid_alive(pid):
        return False
    if started is None:
        return True
    cur = proc_start(pid)
    return cur is None or str(cur) == str(started)


def owner_alive(cur: dict | None) -> bool:
    """1.46: a RUN_OWNER lock is held only by its LIVE owner - a lock left by a killed runner (closed console, hard kill after 120 s,
    restart) whose pid now belongs to another program no longer blocks training (and the training center does not wait up to 12 h)."""
    try:
        return bool(cur) and pid_alive_as(int(cur.get("pid") or 0), cur.get("started"))
    except (AttributeError, TypeError, ValueError):
        return False


def _alive(pid) -> bool:
    """Owner check of PMW-LOCK-1 (OpenProcess + STILL_ACTIVE on Windows - os.kill(pid, 0) there is a console Ctrl+C, see pid_alive)."""
    try:
        return pid_alive(int(pid))
    except (OSError, ValueError, TypeError):
        return False


# ------------------------------------------------------------------ OS_FILE: registries and activation pointers
file_lock = RIO.file_lock            # one implementation (moved from trainhub/registry.reg_lock in 1.46 - registry_io)
lock_for = RIO.lock_for


def registry_lock(path: Path, timeout_s: float = REGISTRY_TIMEOUT_S):
    """'registry:<file>': OS lock <file stem>.lock next to the registry / pointer (trainhub registry.json -> registry.lock, Quant
    MetaModel ACTIVE.json -> ACTIVE.lock) for one re-read -> change -> save."""
    return RIO.file_lock(RIO.lock_for(Path(path)), timeout_s=timeout_s)


# ------------------------------------------------------------------ OWNER_HEARTBEAT: PMW-LOCK-1 (moved from studio/lock.Lock - alias there)
class OwnerLock:
    """Cross-process lock (PMW-LOCK-1) shared by Studio instances and the bot's export: lock file created with O_EXCL holding the owner
    (pid, app, job, host) and a heartbeat. A lock is stale when its pid is dead or the heartbeat is older than `stale_s`; a stale lock is
    taken over atomically (rename + re-create). Only the owner releases it."""

    def __init__(self, path: Path, *, app: str, stale_s: float = EXPORT_STALE_S):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.app, self.stale_s = app, stale_s
        self.held = False
        self.job = None

    def _owner_alive(self, pid) -> bool:
        """Liveness of the recorded owner pid (hook: studio.lock.Lock keeps its module-level _alive)."""
        return _alive(pid)

    def owner(self) -> dict | None:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _write(self, fd, job):
        rec = {"pid": os.getpid(), "app": self.app, "job": job, "host": socket.gethostname(), "acquired_at": time.time(), "heartbeat": time.time()}
        os.write(fd, json.dumps(rec).encode())
        os.close(fd)

    def stale(self, o: dict | None) -> bool:
        if not o:
            return True
        return (not self._owner_alive(o.get("pid"))) or (time.time() - float(o.get("heartbeat") or 0) > self.stale_s)

    def acquire(self, job: str | None = None) -> tuple[bool, dict | None]:
        for _ in range(2):
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                self._write(fd, job)
                self.held, self.job = True, job
                return True, None
            except FileExistsError:
                o = self.owner()
                if o and o.get("pid") == os.getpid() and o.get("job") == job:
                    self.held = True
                    return True, None
                if not self.stale(o):
                    return False, o
                tomb = self.path.with_suffix(f".stale-{os.getpid()}")
                try:
                    os.replace(self.path, tomb)
                except OSError:
                    continue
                # 1.46: the takeover was not atomic - between reading `o` and the rename another process could take the stale lock over
                # itself and create a FRESH lock file; the rename then moved THAT lock away and both processes held the lock. Only the
                # record judged stale is removed: anything else is put back (while the path is still free) and the lock stays taken.
                try:
                    data = tomb.read_bytes()
                except OSError:
                    data = b""
                try:
                    moved = json.loads(data.decode("utf-8"))
                except ValueError:
                    moved = None
                if moved != o:
                    try:
                        fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                        os.write(fd, data)
                        os.close(fd)
                    except OSError:
                        pass                                       # the path was taken again meanwhile - that owner holds the lock
                    tomb.unlink(missing_ok=True)
                    return False, moved if isinstance(moved, dict) else self.owner()
                tomb.unlink(missing_ok=True)
        return False, self.owner()

    def heartbeat(self) -> None:
        if not self.held:
            return
        o = self.owner() or {}
        if o.get("pid") != os.getpid():
            self.held = False
            return
        o["heartbeat"] = time.time()
        tmp = self.path.with_suffix(".hb")
        tmp.write_text(json.dumps(o), encoding="utf-8")
        os.replace(tmp, self.path)

    def release(self) -> None:
        o = self.owner()
        if o and o.get("pid") == os.getpid():
            self.path.unlink(missing_ok=True)
        self.held = False


def export_lock_path(data_dir: Path | None = None) -> Path:
    """'export[:<inst>]': <data>/locks/pmw_export.lock - ONE file for every instrument (the Studio reaches it through the bot's data folder,
    studio/settings.export_lock_path)."""
    if data_dir is None:
        from .paths import data_dir as _dd
        data_dir = _dd()
    return Path(data_dir) / SERVICE["export"]["file"]


def export_lock(app: str = EXPORT_APP_BOT, *, path: Path | None = None, stale_s: float = EXPORT_STALE_S) -> OwnerLock:
    """The MT5 history export lock of the bot (marketdata/export.run, forecast/export.export_candles) - `app` and the job id passed to
    acquire() are what other processes see as the owner."""
    return OwnerLock(path if path is not None else export_lock_path(), app=app, stale_s=stale_s)


# ------------------------------------------------------------------ RUN_OWNER: the training runner (moved from training/core - wrappers there)
class RunLock:
    """RUNNING.lock: the owner record {run_id, pid, started, at} written under an OS guard lock (<lock>.lck) around read -> check -> write
    (1.46, I0063: two runners starting at the same moment both read "free" and both wrote themselves as the owner). Held while its owner
    process (pid + start time) lives; re-entrant only for the SAME run in the SAME process. The owner record stays in RUNNING.lock (readers:
    panel, training center, API) - unchanged format.

    write / owner_alive_fn / proc_start_fn / now_fn: the functions of training/core (late-bound there, so callers and tests that replace
    them on training.core keep doing so)."""

    def __init__(self, path: Path, *, guard_timeout_s: float = RUN_GUARD_TIMEOUT_S, write=None, owner_alive_fn=None, proc_start_fn=None,
                 now_fn=None):
        self.path = Path(path)
        self.guard_timeout_s = guard_timeout_s
        self._write = write or RIO.write_json_atomic
        self._owner_alive = owner_alive_fn or owner_alive
        self._proc_start = proc_start_fn or proc_start
        self._now = now_fn or (lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    def guard(self):
        return RIO.file_lock(self.path.with_name(self.path.name + ".lck"), timeout_s=self.guard_timeout_s)

    def acquire(self, run_id: str, *, busy: str = "BLOKADA_TRENINGU_ZAJETA") -> str | None:
        """Returns None when acquired, otherwise the id of the run in progress (`busy` when the guard itself stays taken > timeout)."""
        p = self.path

        def locked() -> str | None:
            try:
                cur = json.loads(p.read_text(encoding="utf-8"))
                pid = int(cur.get("pid", 0))
                # 1.46: ANY other live process holds the lock - also for the same run_id (1.45.0 handed the lock of a running run to a
                # second process resuming the same run: two processes wrote one run folder / state.json)
                if self._owner_alive(cur) and (pid != os.getpid() or cur.get("run_id") != run_id):   # re-entrant: SAME run, SAME process
                    return cur.get("run_id")
            except (OSError, ValueError, TypeError, AttributeError):
                pass
            # 1.46: + start time of the owner (the pid alone was taken for a live owner after pid reuse)
            self._write(p, {"run_id": run_id, "pid": os.getpid(), "started": self._proc_start(os.getpid()), "at": self._now()})
            return None
        with contextlib.ExitStack() as stack:
            try:
                stack.enter_context(self.guard())
            except TimeoutError:                        # Windows: another process is inside the guard for > timeout
                return busy
            return locked()

    def release(self, run_id: str) -> None:
        p = self.path
        try:
            with self.guard():                          # 1.46 (I0063): never removes a lock another runner has just written
                if json.loads(p.read_text(encoding="utf-8")).get("run_id") == run_id:
                    p.unlink()
        except (OSError, ValueError, TimeoutError):
            pass


def train_lock_path(data_dir: Path | None = None) -> Path:
    if data_dir is None:
        from .paths import data_dir as _dd
        data_dir = _dd()
    return Path(data_dir) / SERVICE["train"]["file"]


# ------------------------------------------------------------------ IN_PROCESS: one job per service object
class JobLock:
    """'job:<name>': a plain non-blocking thread lock of one service object (ML training in the bot: start_training / resume_interrupted
    answer JOB_LOCKED). Same interface as threading.Lock (acquire(blocking, timeout) / release / locked / with)."""

    def __init__(self, name: str):
        self.name = name
        self._lk = threading.Lock()

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        return self._lk.acquire(blocking, timeout)

    def release(self) -> None:
        self._lk.release()

    def locked(self) -> bool:
        return self._lk.locked()

    def __enter__(self):
        self._lk.acquire()
        return self

    def __exit__(self, *exc):
        self._lk.release()
        return False


def job_lock(name: str) -> JobLock:
    return JobLock(name)


# ------------------------------------------------------------------ names
def parse(name: str) -> tuple[str, str | None]:
    """'train:XAUUSD' -> ('train', 'XAUUSD'); 'export' -> ('export', None). Unknown kind -> KeyError."""
    kind, _, scope = str(name).partition(":")
    if kind not in SERVICE:
        raise KeyError(f"LOCK_KIND_UNKNOWN: {name!r} (znane: {', '.join(SERVICE)})")
    return kind, (scope or None)


def spec(name: str, *, data_dir: Path | None = None) -> dict:
    """Description of a named lock: kind, scope (instrument / file / job name), mechanism, the lock file it uses (unchanged), expiry."""
    kind, scope = parse(name)
    s = SERVICE[kind]
    if kind == "train":
        path = train_lock_path(data_dir)
    elif kind == "export":
        path = export_lock_path(data_dir)
    elif kind == "registry":
        path = RIO.lock_for(Path(scope)) if scope else None
    else:
        path = None
    return {"version": VERSION, "name": name, "kind": kind, "scope": scope, "mechanism": s["mechanism"], "path": str(path) if path else None,
            "ttl_s": s["ttl_s"], "description": s["scope"]}
