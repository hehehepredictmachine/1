"""Etap 4 (Apollo23 1.46 arch) - trening: jedna usługa blokad (PMW-LOCKS-1, masterquo/locks.py, wejście training.core.LOCKS), DatasetRef,
jedna polityka promocji (D6).

Ruch jest NEUTRALNY: dotychczasowe blokady (RUNNING.lock runnera, PMW-LOCK-1 Studio / eksportu, reg_lock TrainHub, wskaźnik MetaModelu
Quant, blokada zadania ML w bocie) są cienkimi wrapperami na usługę - te same pliki, rekordy właściciela, TTL i odpowiedzi. Dowód: testy
równości ze ZAMROŻONĄ kopią kodu sprzed przeniesienia (stan gałęzi cf5d941) na >= 200 losowych scenariuszach ze stałym ziarnem."""
from __future__ import annotations

import ast
import contextlib
import json
import os
import random
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import _env
from _env import TempData

SEED = 146_4


# ============================================================================================ frozen copy of the code before Etap 4
# training/core.py (cf5d941): _pid_alive, _proc_start, pid_alive_as, lock_owner_alive, _lock_guard, acquire_lock, release_lock
def _old_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not h:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return code.value == 259
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _old_proc_start(pid: int) -> int | None:
    if pid <= 0:
        return None
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            k = ctypes.windll.kernel32
            k.OpenProcess.restype = wintypes.HANDLE
            h = k.OpenProcess(0x1000, False, pid)
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
        return int(txt.rsplit(")", 1)[1].split()[19])
    except Exception:  # noqa: BLE001
        return None


def _old_pid_alive_as(pid: int, started) -> bool:
    if not _old_pid_alive(pid):
        return False
    if started is None:
        return True
    cur = _old_proc_start(pid)
    return cur is None or str(cur) == str(started)


def _old_lock_owner_alive(cur) -> bool:
    try:
        return bool(cur) and _old_pid_alive_as(int(cur.get("pid") or 0), cur.get("started"))
    except (AttributeError, TypeError, ValueError):
        return False


def _old_lock_guard(lock_p: Path):
    from masterquo.registry_io import file_lock
    return file_lock(lock_p.with_name("RUNNING.lock.lck"), timeout_s=30.0)


def _old_acquire_lock(lock_p: Path, run_id: str, now_s: str) -> str | None:
    from masterquo.registry_io import write_json_atomic
    p = lock_p

    def locked() -> str | None:
        try:
            cur = json.loads(p.read_text(encoding="utf-8"))
            pid = int(cur.get("pid", 0))
            if _old_lock_owner_alive(cur) and (pid != os.getpid() or cur.get("run_id") != run_id):
                return cur.get("run_id")
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        write_json_atomic(p, {"run_id": run_id, "pid": os.getpid(), "started": _old_proc_start(os.getpid()), "at": now_s})
        return None
    with contextlib.ExitStack() as stack:
        try:
            stack.enter_context(_old_lock_guard(p))
        except TimeoutError:
            return "BLOKADA_TRENINGU_ZAJETA"
        return locked()


def _old_release_lock(lock_p: Path, run_id: str) -> None:
    p = lock_p
    try:
        with _old_lock_guard(p):
            if json.loads(p.read_text(encoding="utf-8")).get("run_id") == run_id:
                p.unlink()
    except (OSError, ValueError, TimeoutError):
        pass


# studio/lock.py (cf5d941): _alive + Lock (PMW-LOCK-1)
def _old_alive(pid) -> bool:
    try:
        return _old_pid_alive(int(pid))
    except (OSError, ValueError, TypeError):
        return False


class _OldLock:
    def __init__(self, path: Path, *, app: str, stale_s: float = 120.0):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.app, self.stale_s = app, stale_s
        self.held = False
        self.job = None

    def owner(self):
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _write(self, fd, job):
        rec = {"pid": os.getpid(), "app": self.app, "job": job, "host": socket.gethostname(), "acquired_at": time.time(), "heartbeat": time.time()}
        os.write(fd, json.dumps(rec).encode())
        os.close(fd)

    def stale(self, o) -> bool:
        if not o:
            return True
        return (not _old_alive(o.get("pid"))) or (time.time() - float(o.get("heartbeat") or 0) > self.stale_s)

    def acquire(self, job=None):
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
                        pass
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


# ============================================================================================ helpers
DEAD_PID = 99_999_999                     # above pid_max: never a live process


def _victim() -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])


def _snap(p: Path, drop=("at",)):
    """Normalised content of a lock file after an operation (the ISO 'at' of RUNNING.lock is the wall clock)."""
    if not p.exists():
        return "MISSING"
    raw = p.read_text(encoding="utf-8")
    try:
        d = json.loads(raw)
    except ValueError:
        return "RAW:" + raw
    if isinstance(d, dict):
        return {k: v for k, v in d.items() if k not in drop}
    return d


def _call(fn, *a):
    """Result or the exception type (the old code raised AttributeError on a JSON list in RUNNING.lock - the new code must do the same)."""
    try:
        return fn(*a)
    except Exception as exc:  # noqa: BLE001
        return ("EXC", type(exc).__name__)


class _Clock:
    def __init__(self, t0: float):
        self.t = t0

    def __call__(self) -> float:
        self.t += 1.0
        return self.t


class _Victim(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v = _victim()
        time.sleep(0.2)
        cls.vs = _old_proc_start(cls.v.pid)

    @classmethod
    def tearDownClass(cls):
        cls.v.kill()
        cls.v.wait(10)


# ============================================================================================ process identity
class TestProcessIdentityEqualsOld(_Victim):
    def test_random_pids_same_answers(self):
        from masterquo import locks as LK
        from masterquo.training import core
        self.assertIs(core._pid_alive, LK.pid_alive)                       # alias zgodności - one implementation
        self.assertIs(core._proc_start, LK.proc_start)
        self.assertIs(core.pid_alive_as, LK.pid_alive_as)
        self.assertIs(core.lock_owner_alive, LK.owner_alive)
        rnd = random.Random(SEED)
        me = os.getpid()
        pids = [me, self.v.pid, DEAD_PID, 0, -1, 1, os.getppid()] + [rnd.randint(-5, 4_000_000) for _ in range(260)]
        n = 0
        for pid in pids:
            st = _old_proc_start(pid)
            self.assertEqual(LK.pid_alive(pid), _old_pid_alive(pid), pid)
            self.assertEqual(LK.proc_start(pid), st, pid)
            for started in (None, st, (st or 0) + 1, str(st), "x"):
                self.assertEqual(LK.pid_alive_as(pid, started), _old_pid_alive_as(pid, started), (pid, started))
                n += 1
            for cur in ({"pid": pid}, {"pid": pid, "started": st}, {"pid": str(pid)}, {"pid": "abc"}, {}, None, [], {"pid": None},
                        {"pid": pid, "started": (st or 0) + 3}):
                self.assertEqual(LK.owner_alive(cur), _old_lock_owner_alive(cur), (pid, cur))
                n += 1
        self.assertGreaterEqual(n, 200)


# ============================================================================================ RUN_OWNER: RUNNING.lock
class TestRunLockEqualsOld(_Victim):
    RUNS = ("TR-A", "TR-B", "TR-C")

    def _states(self):
        me, ms = os.getpid(), _old_proc_start(os.getpid())
        v, vs = self.v.pid, self.vs
        return [None, "RAW:{nie json", [], {}, {"run_id": "TR-A", "pid": me, "started": ms}, {"run_id": "TR-B", "pid": me, "started": ms},
                {"run_id": "TR-A", "pid": me, "started": (ms or 0) + 7}, {"run_id": "TR-A", "pid": v, "started": vs},
                {"run_id": "TR-C", "pid": v}, {"run_id": "TR-B", "pid": v, "started": (vs or 0) + 1},
                {"run_id": "TR-A", "pid": DEAD_PID, "started": 5}, {"run_id": "TR-A", "pid": "abc"}, {"run_id": "TR-A", "pid": None},
                {"run_id": "TR-B", "pid": v, "started": str(vs)}]

    @staticmethod
    def _put(p: Path, st) -> None:
        p.parent.mkdir(parents=True, exist_ok=True)
        if st is None:
            p.unlink(missing_ok=True)
        elif isinstance(st, str):
            p.write_text(st[4:], encoding="utf-8")
        else:
            p.write_text(json.dumps(st), encoding="utf-8")

    def test_random_sequences_same_results_and_files(self):
        from masterquo import locks as LK
        from masterquo.training import core
        rnd = random.Random(SEED)
        states = self._states()
        td = TempData()
        old_dir = Path(tempfile.mkdtemp(prefix="mq_e4_old_"))
        svc_dir = Path(tempfile.mkdtemp(prefix="mq_e4_svc_"))
        try:
            cases = 0
            for _ in range(240):
                st = rnd.choice(states)
                ops = [(rnd.choice(("acquire", "acquire", "release")), rnd.choice(self.RUNS)) for _ in range(rnd.randint(1, 4))]
                p_old, p_core, p_svc = old_dir / "RUNNING.lock", core.lock_path(), svc_dir / "RUNNING.lock"
                for p in (p_old, p_core, p_svc):
                    self._put(p, st)
                svc = LK.RunLock(p_svc)
                for op, rid in ops:
                    if op == "acquire":
                        r = (_call(_old_acquire_lock, p_old, rid, "T"), _call(core.acquire_lock, rid), _call(svc.acquire, rid))
                    else:
                        r = (_call(_old_release_lock, p_old, rid), _call(core.release_lock, rid), _call(svc.release, rid))
                    self.assertEqual(r[0], r[1], (st, ops, op, rid))
                    self.assertEqual(r[0], r[2], (st, ops, op, rid))
                    s = (_snap(p_old), _snap(p_core), _snap(p_svc))
                    self.assertEqual(s[0], s[1], (st, ops, op, rid))
                    self.assertEqual(s[0], s[2], (st, ops, op, rid))
                cases += 1
            self.assertGreaterEqual(cases, 200)
            # same lock files as before: RUNNING.lock + the guard RUNNING.lock.lck in data/training
            self.assertEqual(core.lock_path(), Path(td.dir) / "training" / "RUNNING.lock")
            self.assertTrue((Path(td.dir) / "training" / "RUNNING.lock.lck").exists())
            self.assertEqual(Path(LK.spec("train:XAUUSD")["path"]), core.lock_path())
            self.assertEqual(Path(LK.spec("train")["path"]), core.lock_path())
        finally:
            td.close()
            import shutil
            shutil.rmtree(old_dir, ignore_errors=True)
            shutil.rmtree(svc_dir, ignore_errors=True)

    def test_core_hooks_stay_late_bound(self):
        """Callers / tests that replace training.core.write_json_atomic keep doing so (I0063 tests widen the race window this way)."""
        from masterquo.training import core
        td = TempData()
        try:
            seen = []
            real = core.write_json_atomic
            with mock.patch.object(core, "write_json_atomic", lambda p, d: (seen.append(Path(p).name), real(p, d))):
                self.assertIsNone(core.acquire_lock("TR-HOOK"))
            self.assertEqual(seen, ["RUNNING.lock"])
            with mock.patch.object(core, "lock_owner_alive", lambda cur: True):
                self.assertEqual(core.acquire_lock("TR-OTHER"), "TR-HOOK")
            core.release_lock("TR-HOOK")
            self.assertFalse(core.lock_path().exists())
        finally:
            td.close()


# ============================================================================================ OWNER_HEARTBEAT: PMW-LOCK-1
class TestOwnerLockEqualsOld(_Victim):
    JOBS = (None, "J1", "J2")

    def _states(self, now: float):
        me, v = os.getpid(), self.v.pid
        return [None, "RAW:{zepsuty", [], {"pid": me, "app": "X", "job": "J1", "heartbeat": now},
                {"pid": me, "app": "X", "job": "J2", "heartbeat": now}, {"pid": v, "app": "PepeTrainingStudio", "job": "S1", "heartbeat": now},
                {"pid": v, "app": "PepeTrainingStudio", "job": "S1", "heartbeat": now - 500}, {"pid": DEAD_PID, "job": "D", "heartbeat": now},
                {"pid": v, "job": "N"}, {"pid": "x", "heartbeat": now}, {"pid": me, "job": None, "heartbeat": now - 200}]

    def test_random_sequences_same_results_and_files(self):
        from masterquo import locks as LK
        from masterquo.studio import lock as SL
        rnd = random.Random(SEED)
        base = Path(tempfile.mkdtemp(prefix="mq_e4_lock_"))
        try:
            cases = 0
            for i in range(240):
                t0 = 1_800_000_000.0 + i * 10_000
                st = rnd.choice(self._states(t0))
                stale_s = rnd.choice((120.0, 120.0, 30.0))
                ops = [rnd.choice(("acquire", "acquire", "heartbeat", "release", "owner", "stale")) for _ in range(rnd.randint(1, 5))]
                jobs = [rnd.choice(self.JOBS) for _ in ops]
                results, files = [], []
                for k, cls in enumerate((_OldLock, LK.OwnerLock, SL.Lock)):
                    p = base / f"c{i}_{k}" / "pmw_export.lock"
                    p.parent.mkdir(parents=True, exist_ok=True)
                    if st is not None:
                        p.write_text(st[4:] if isinstance(st, str) else json.dumps(st), encoding="utf-8")
                    out = []
                    with mock.patch("time.time", _Clock(t0)):
                        lk = cls(p, app="APP", stale_s=stale_s)
                        for op, job in zip(ops, jobs):
                            if op == "acquire":
                                out.append(lk.acquire(job))
                            elif op == "heartbeat":
                                out.append(lk.heartbeat())
                            elif op == "release":
                                out.append(lk.release())
                            elif op == "owner":
                                out.append(lk.owner())
                            else:
                                out.append(lk.stale(lk.owner()))
                            out.append((lk.held, lk.job))
                    results.append(out)
                    files.append((_snap(p, drop=()), sorted(x.name for x in p.parent.iterdir())))
                self.assertEqual(results[0], results[1], (st, ops, jobs))
                self.assertEqual(results[0], results[2], (st, ops, jobs))
                self.assertEqual(files[0], files[1], (st, ops, jobs))
                self.assertEqual(files[0], files[2], (st, ops, jobs))
                cases += 1
            self.assertGreaterEqual(cases, 200)
        finally:
            import shutil
            shutil.rmtree(base, ignore_errors=True)

    def test_studio_lock_is_a_thin_alias(self):
        from masterquo import locks as LK
        from masterquo.studio import lock as SL
        self.assertTrue(issubclass(SL.Lock, LK.OwnerLock))
        self.assertEqual(set(vars(SL.Lock)) - {"__module__", "__doc__", "__qualname__", "__firstlineno__", "__static_attributes__"},
                         {"_owner_alive"})                                  # nothing but the liveness hook (studio.lock._alive, patchable)
        with tempfile.TemporaryDirectory() as d, mock.patch("masterquo.training.core._pid_alive", return_value=False):
            self.assertTrue(SL.Lock(Path(d) / "x.lock", app="A").stale({"pid": os.getpid(), "heartbeat": time.time()}))


# ============================================================================================ the service: names, files, wrappers
class TestLockServiceNamesAndWrappers(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_names_map_to_todays_files(self):
        from masterquo import locks as LK
        from masterquo.paths import data_dir
        from masterquo.training import core
        self.assertIs(core.LOCKS, LK)
        d = data_dir()
        for name, kind, scope, mech, path in (
                ("train", "train", None, LK.RUN_OWNER, d / "training" / "RUNNING.lock"),
                ("train:BTC", "train", "BTC", LK.RUN_OWNER, d / "training" / "RUNNING.lock"),        # one runner for every instrument
                ("export:XAUUSD", "export", "XAUUSD", LK.OWNER_HEARTBEAT, d / "locks" / "pmw_export.lock"),
                ("export:BTC", "export", "BTC", LK.OWNER_HEARTBEAT, d / "locks" / "pmw_export.lock"),  # one MT5 export for every instrument
                ("registry:" + str(d / "models" / "XAUUSD" / "registry.json"), "registry", str(d / "models" / "XAUUSD" / "registry.json"),
                 LK.OS_FILE, d / "models" / "XAUUSD" / "registry.lock")):
            s = core.lock_spec(name)
            self.assertEqual((s["kind"], s["scope"], s["mechanism"], Path(s["path"])), (kind, scope, mech, path), name)
        self.assertEqual(core.lock_spec("export:XAUUSD")["ttl_s"], 120.0)
        self.assertIsNone(core.lock_spec("train")["ttl_s"])
        self.assertEqual(core.lock_spec("job:ml:train:XAUUSD")["mechanism"], LK.IN_PROCESS)
        with self.assertRaises(KeyError):
            core.lock_spec("nieznana:XAUUSD")

    def test_studio_export_lock_path_is_the_service_file(self):
        from masterquo import locks as LK
        from masterquo.studio import settings as S
        s = {"bot_data_dir": self.td.dir}
        self.assertEqual(S.export_lock_path(s), S.bot_data_dir(s) / "locks" / "pmw_export.lock")      # before (cf5d941)
        self.assertEqual(S.export_lock_path(s), LK.export_lock_path(S.bot_data_dir(s)))

    def test_trainhub_reg_lock_same_file_and_reentrant(self):
        from masterquo import registry_io as RIO
        from masterquo.trainhub import registry as R
        with R.reg_lock("XAUUSD"), R.reg_lock("XAUUSD"):
            key = str(R._reg_path("XAUUSD").with_name("registry.lock").resolve())                   # before: this exact file
            self.assertEqual(RIO._HELD.__dict__["n"].get(key), 2)

    def test_quant_pointer_lock_same_file(self):
        from masterquo import registry_io as RIO
        from masterquo.quant import metamodel as M
        with M._ptr_lock("XAUUSD"):
            key = str(RIO.lock_for(M._ptr("XAUUSD")).resolve())
            self.assertEqual(RIO._HELD.__dict__["n"].get(key), 1)
            self.assertTrue(key.endswith("ACTIVE.lock"))

    def test_ml_job_lock_same_semantics(self):
        from masterquo import locks as LK
        jl = LK.job_lock("ml:train:XAUUSD")                 # service name job:ml:train:<inst>
        self.assertTrue(jl.acquire(blocking=False))
        self.assertFalse(jl.acquire(blocking=False))                       # a second start answers JOB_LOCKED (as threading.Lock)
        self.assertTrue(jl.locked())
        jl.release()
        with jl:
            self.assertTrue(jl.locked())
        self.assertFalse(jl.locked())
        src = (Path(_env.ROOT) / "backend" / "masterquo" / "ml" / "service.py").read_text(encoding="utf-8")
        self.assertIn('self._job_lock = LK.job_lock(f"ml:train:{self.inst}")', src)

    def test_export_lock_interop_with_studio(self):
        """marketdata/export.run and the Studio queue still exclude each other on the same file (the lock now comes from the service)."""
        from masterquo import locks as LK
        from masterquo.marketdata import export as MD
        from masterquo.paths import data_dir
        from masterquo.studio.lock import Lock
        held = Lock(data_dir() / "locks" / "pmw_export.lock", app=LK.EXPORT_APP_STUDIO)
        self.assertTrue(held.acquire("studio-job-1")[0])
        try:
            with self.assertRaises(MD.ExportBusy) as cm:
                MD.run(None, None, "XAUUSD", "XAUUSD-")
            self.assertIn("studio-job-1", str(cm.exception))
        finally:
            held.release()
        seen = {}

        def spy(*a, **k):
            seen["owner"] = json.loads((data_dir() / "locks" / "pmw_export.lock").read_text(encoding="utf-8"))
            return {"status": "COMPLETE"}
        with mock.patch.object(MD, "_run", spy):
            self.assertEqual(MD.run(None, None, "XAUUSD", "XAUUSD-"), {"status": "COMPLETE"})
        self.assertEqual((seen["owner"]["app"], seen["owner"]["job"]), ("PepeMarketWizard-export", "export:XAUUSD"))
        self.assertFalse((data_dir() / "locks" / "pmw_export.lock").exists())
        ok, _owner = LK.export_lock().acquire("export:BTC")
        self.assertTrue(ok)
        try:
            self.assertFalse(Lock(data_dir() / "locks" / "pmw_export.lock", app=LK.EXPORT_APP_STUDIO).acquire("S2")[0])
        finally:
            LK.export_lock().release()


# ============================================================================================ layer guard
class TestLockServiceLayers(unittest.TestCase):
    REMOVED = ("masterquo.forecast.export -> masterquo.studio.lock", "masterquo.marketdata.export -> masterquo.studio.lock",
               "masterquo.forecast.dataset_state -> masterquo.training.core", "masterquo.modelhub.families.base -> masterquo.training.core",
               "masterquo.procs -> masterquo.training.core")

    def test_upward_edges_removed(self):
        import importlib
        sys.path.insert(0, str(Path(_env.ROOT) / "tools"))
        import cycles
        C = importlib.reload(cycles)
        self.assertEqual(C.LAYERS.get("locks"), 0)
        up = C.upward(C.edges())
        for k in self.REMOVED:
            self.assertNotIn(k, up)
        self.assertFalse([k for k in up if k.endswith("-> masterquo.locks") or k.startswith("masterquo.locks ->")])

    def test_locks_is_a_leaf(self):
        src = (Path(_env.ROOT) / "backend" / "masterquo" / "locks.py").read_text(encoding="utf-8")
        internal = set()
        for n in ast.walk(ast.parse(src)):
            if isinstance(n, ast.ImportFrom) and n.level:
                internal |= {n.module} if n.module else {a.name for a in n.names}
        self.assertEqual(internal, {"registry_io", "paths"})
        for f in ("forecast/export.py", "marketdata/export.py"):
            src = (Path(_env.ROOT) / "backend" / "masterquo" / f).read_text(encoding="utf-8")
            self.assertNotIn("from ..studio.lock import", src, f)
            self.assertIn("LK.export_lock(LK.EXPORT_APP_BOT)", src, f)



# ============================================================================================ frozen copy: training/promotion.py (cf5d941)
def _old_block(role, event, reason):
    return {"allow_promotion": False, "role": role, "event": event, "reason": reason}


def _old_ml_champion_policy(*, approx, synthetic, activate=True):
    if synthetic is None or approx is None:
        return _old_block("PROVENANCE_UNKNOWN", "NOT_PROMOTED_PROVENANCE_UNKNOWN",
                          "nieznane pochodzenie danych treningu (APPROX / syntetyczne) – model tylko do badań, champion bez zmian")
    if synthetic:
        return _old_block("FIXTURE_ONLY", "NOT_PROMOTED_SYNTHETIC", "dane syntetyczne (symulator terminala) – model techniczny, nigdy champion")
    if approx:
        return _old_block("RESEARCH_APPROX", "NOT_PROMOTED_APPROX", "trening na etykietach APPROX (backfill OHLC) – tylko do badań")
    if not activate:
        return _old_block("ELIGIBLE_NOT_ACTIVATED", "NOT_PROMOTED_NO_ACTIVATE",
                          "plan treningu bez aktywacji (TEST_INSTALACJI / --no-activate) – champion bez zmian")
    return {"allow_promotion": True, "role": "ELIGIBLE_FOR_CHAMPION", "event": None, "reason": None}


def _old_approx_rows_in_snapshot(db, manifest):
    if not manifest.get("include_approx"):
        return 0
    r = db.one("SELECT COUNT(*) AS n FROM ml_samples WHERE status='LABELED' AND quality NOT IN ('HIGH','COST_UNKNOWN') AND synthetic=? "
               "AND label_known_utc <= ?", (1 if manifest.get("synthetic") else 0, manifest["cutoff_utc"]))
    return int((r or {}).get("n") or 0)


# ============================================================================================ frozen copy: training/dataset_ref.py (cf5d941)
def _old_read(p):
    try:
        d = json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def _old_sha_of(obj):
    import hashlib
    if not obj:
        return None
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def _old_make(*, instrument, source, sha256, data_kind, range_utc=None, symbol=None, location=None, quality=None, rows=None, files=None):
    return {"version": "PMW-DATASET-REF-1", "instrument": instrument, "symbol": symbol, "source": source, "location": location,
            "range_utc": list(range_utc) if range_utc else None, "sha256": sha256, "data_kind": data_kind,
            "quality": quality or {"report": None, "status": None}, "rows": rows, "files": files}


def _old_from_export_dir(ds):
    ds = Path(ds)
    meta = _old_read(ds / "source_metadata.json")
    if not meta:
        return None
    dq = _old_read(ds / "DATA_QUALITY_REPORT.json") or {}
    files = meta.get("files_sha256") if isinstance(meta.get("files_sha256"), dict) else None
    suff = (dq.get("sufficiency") or {}).get("status") if isinstance(dq.get("sufficiency"), dict) else None
    return _old_make(instrument=meta.get("instrument"), symbol=meta.get("symbol"), source="MT5_EXPORT_RUN", location=str(ds),
                     range_utc=meta.get("range_utc"), sha256=_old_sha_of(files) or meta.get("dataset_id"), data_kind=meta.get("data_kind"),
                     quality={"report": str(ds / "DATA_QUALITY_REPORT.json") if dq else None, "status": suff}, files=files)


def _old_from_store(inst, store_manifest, *, sha256, quality_path=None, range_utc=None, rows=None):
    q = _old_read(quality_path) if quality_path else None
    st = None
    if q:
        bad = [tf for tf, r in (q.get("timeframes") or {}).items() if isinstance(r, dict) and r.get("status") != "OK"]
        st = "OK" if not bad else "BŁĘDY: " + ", ".join(bad)
    return _old_make(instrument=inst, symbol=(store_manifest or {}).get("symbol"), source="MARKETDATA_STORE",
                     location=str(quality_path.parent) if quality_path else None, range_utc=range_utc, sha256=sha256,
                     data_kind=(store_manifest or {}).get("data_kind"), quality={"report": str(quality_path) if q else None, "status": st},
                     rows=rows)


def _old_from_bars(inst, *, source, symbol, data_kind, sha256, range_utc=None, rows=None, quality_path=None):
    q = _old_read(quality_path) if quality_path else None
    st = None
    if q:
        bad = [tf for tf, r in (q.get("timeframes") or {}).items() if isinstance(r, dict) and r.get("status") != "OK"]
        st = "OK" if not bad else "BŁĘDY: " + ", ".join(bad)
    return _old_make(instrument=inst, symbol=symbol, source=source, location=str(quality_path.parent) if q else None, range_utc=range_utc,
                     sha256=sha256, data_kind=data_kind, quality={"report": str(quality_path) if q else None, "status": st}, rows=rows)


class _FakeDb:
    def __init__(self, n):
        self.n, self.calls = n, []

    def one(self, sql, params):
        self.calls.append((sql, params))
        return None if self.n is None else {"n": self.n}


# ============================================================================================ D6: one promotion policy
class TestPromotionPolicyOneSource(unittest.TestCase):
    def test_alias_and_leaf_are_one_policy(self):
        from masterquo.contracts import promotion as CP
        from masterquo.training import promotion as TP
        for name in ("ELIGIBLE", "_block", "approx_rows_in_snapshot", "ml_champion_policy"):
            self.assertIs(getattr(TP, name), getattr(CP, name), name)

    def test_policy_equals_old_on_every_input(self):
        from masterquo.training import promotion as TP
        n = 0
        for approx in (None, False, True, 0, 1, ""):
            for synthetic in (None, False, True, 0, 1, ""):
                for activate in (False, True, 0, 1):
                    self.assertEqual(TP.ml_champion_policy(approx=approx, synthetic=synthetic, activate=activate),
                                     _old_ml_champion_policy(approx=approx, synthetic=synthetic, activate=activate))
                    n += 1
        self.assertGreaterEqual(n, 144)

    def test_approx_rows_equals_old_on_random_manifests(self):
        from masterquo.contracts.promotion import approx_rows_in_snapshot
        rnd = random.Random(SEED)
        for _ in range(240):
            man = {"cutoff_utc": f"2026-{rnd.randint(1, 12):02d}-{rnd.randint(1, 28):02d}T00:00:00Z"}
            for k in ("include_approx", "synthetic"):
                v = rnd.choice((None, True, False, 0, 1, "x", "MISSING"))
                if v != "MISSING":
                    man[k] = v
            n = rnd.choice((None, 0, 3, 250, "7"))
            a, b = _FakeDb(n), _FakeDb(n)
            self.assertEqual(approx_rows_in_snapshot(a, dict(man)), _old_approx_rows_in_snapshot(b, dict(man)), man)
            self.assertEqual(a.calls, b.calls, man)

    def test_every_ml_promotion_path_uses_the_policy(self):
        """Registry.register (the only champion promotion of the ML registry) is called from the bot's job and the offline training -
        both with policy= from the one D6 policy; no caller passes allow_promotion on its own."""
        pkg = Path(_env.ROOT) / "backend" / "masterquo"
        callers = {}
        for p in pkg.rglob("*.py"):
            if "vendor" in p.parts:
                continue
            tree = ast.parse(p.read_text(encoding="utf-8"))
            for n in ast.walk(tree):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "register" and \
                        any(k.arg == "policy" or k.arg == "allow_promotion" for k in n.keywords):
                    callers.setdefault(str(p.relative_to(pkg)), []).append(sorted(k.arg for k in n.keywords if k.arg))
        self.assertEqual(sorted(callers), ["ml/offline.py", "ml/service.py"])
        for f, kws in callers.items():
            for kw in kws:
                self.assertIn("policy", kw, f)
                self.assertNotIn("allow_promotion", kw, f)
        for f in ("ml/offline.py", "ml/service.py"):
            src = (pkg / f).read_text(encoding="utf-8")
            self.assertIn("from ..contracts.promotion import", src, f)
            self.assertNotIn("from ..training.promotion import", src, f)

    def test_sh_tp_model_rule_is_the_same_policy(self):
        """sh/train_cli: allow_promotion = real and live_write - the same answer as the one policy (no APPROX labels in SH, synthetic =
        not REAL_USER_DATA, activate = live_write). Documented equivalence; the SH call is not rewired (protected SH area)."""
        from masterquo.training.promotion import ml_champion_policy
        for real in (False, True):
            for live_write in (False, True):
                self.assertEqual(ml_champion_policy(approx=False, synthetic=not real, activate=live_write)["allow_promotion"],
                                 real and live_write)
        src = (Path(_env.ROOT) / "backend" / "masterquo" / "sh" / "train_cli.py").read_text(encoding="utf-8")
        self.assertIn("allow_promotion=real and live_write", src)


# ============================================================================================ I0064: DatasetRef
class TestDatasetRefOneSource(unittest.TestCase):
    NAMES = ("VERSION", "_read", "_sha_of", "make", "from_export_dir", "from_store", "from_bars")

    def test_alias_and_leaf_are_one_module(self):
        from masterquo.contracts import dataset_ref as CD
        from masterquo.training import dataset_ref as TD
        for name in self.NAMES:
            self.assertIs(getattr(TD, name), getattr(CD, name), name)

    def test_equals_old_on_random_inputs(self):
        from masterquo.contracts import dataset_ref as DR
        rnd = random.Random(SEED)
        base = Path(tempfile.mkdtemp(prefix="mq_e4_dr_"))

        def put(p: Path, v):
            if v == "MISSING":
                p.unlink(missing_ok=True)
            elif isinstance(v, str):
                p.write_text(v, encoding="utf-8")
            else:
                p.write_text(json.dumps(v), encoding="utf-8")
        try:
            metas = ["MISSING", "{zepsuty", [], {}, {"instrument": "XAUUSD", "symbol": "XAUUSD-", "range_utc": ["a", "b"], "data_kind": "REAL_USER_DATA",
                                                    "files_sha256": {"M1.csv": "ab", "M5.csv": "cd"}, "dataset_id": "DS1"},
                     {"instrument": "BTC", "files_sha256": "nie-słownik", "dataset_id": "DS2"}, {"instrument": "BTC", "files_sha256": {}}]
            dqs = ["MISSING", "x", {"sufficiency": {"status": "OK"}}, {"sufficiency": "OK"}, {"sufficiency": None}, {}]
            qrs = ["MISSING", "[]", {"timeframes": {"M1": {"status": "OK"}, "M5": {"status": "GAPS"}}}, {"timeframes": {"M1": {"status": "OK"}}},
                   {"timeframes": {"M1": "OK"}}, {}, {"timeframes": None}]
            n = 0
            for i in range(240):
                d = base / f"c{i}"
                d.mkdir()
                put(d / "source_metadata.json", rnd.choice(metas))
                put(d / "DATA_QUALITY_REPORT.json", rnd.choice(dqs))
                qp = d / "quality_report.json"
                put(qp, rnd.choice(qrs))
                qpath = rnd.choice((qp, None, d / "brak.json"))
                man = rnd.choice(({}, None, {"symbol": "X", "data_kind": "SYNTHETIC_TEST"}, {"symbol": "Y"}))
                rng = rnd.choice((None, [], ("2026-01-01", "2026-02-01"), ["a"]))
                sha = rnd.choice((None, "abc", ""))
                rows = rnd.choice((None, 0, 1234))
                self.assertEqual(DR.from_export_dir(d), _old_from_export_dir(d))
                self.assertEqual(DR.from_store("XAUUSD", man, sha256=sha, quality_path=qpath, range_utc=rng, rows=rows),
                                 _old_from_store("XAUUSD", man, sha256=sha, quality_path=qpath, range_utc=rng, rows=rows))
                kw = {"source": rnd.choice(("MARKETDATA_STORE", "MT5_LIVE_BRIDGE")), "symbol": rnd.choice((None, "S")),
                      "data_kind": rnd.choice((None, "REAL")), "sha256": sha, "range_utc": rng, "rows": rows, "quality_path": qpath}
                self.assertEqual(DR.from_bars("BTC", **kw), _old_from_bars("BTC", **kw))
                obj = rnd.choice((None, {}, {"b": 1, "a": [1, 2]}, [1, "ż"], "x"))
                self.assertEqual(DR._sha_of(obj), _old_sha_of(obj))
                n += 1
            self.assertGreaterEqual(n, 200)
        finally:
            import shutil
            shutil.rmtree(base, ignore_errors=True)

    def test_coverage_of_manifests(self):
        """I0064 coverage (verified, Etap 4): runner run state (export + model tasks), TrainHub data_manifest.json, model-family
        manifest.json write a DatasetRef; Legacy ML, Quant MetaModel, SDformer, Granite and the per-trainer manifests of the runner tasks do
        not (documented gap - adding the field changes artifacts in data/, a separate item)."""
        pkg = Path(_env.ROOT) / "backend" / "masterquo"
        covered = {"training/runner.py": "DR.from_export_dir", "trainhub/pipeline.py": "DR.from_store", "trainhub/registry.py": "DR.from_store",
                   "modelhub/families/run.py": "DR.from_bars"}
        for f, call in covered.items():
            self.assertIn(call, (pkg / f).read_text(encoding="utf-8"), f)
        src_reg = (pkg / "trainhub" / "registry.py").read_text(encoding="utf-8")
        self.assertIn('"dataset_ref": dataset_ref', src_reg)                               # into data_manifest.json of the package
        self.assertIn('man["dataset_ref"] = _dataset_ref(', (pkg / "modelhub" / "families" / "run.py").read_text(encoding="utf-8"))
        writers = {str(p.relative_to(pkg)) for p in pkg.rglob("*.py") if "dataset_ref" in p.read_text(encoding="utf-8")
                   and p.name != "dataset_ref.py"}
        self.assertEqual(writers, set(covered))
        from masterquo.contracts import dataset_ref as DR
        for gap in ("Legacy ML", "Quant", "SDformer", "Granite", "per-trainer manifests"):
            self.assertIn(gap, DR.__doc__)


class TestContractsLeavesLayers(unittest.TestCase):
    REMOVED = ("masterquo.ml.offline -> masterquo.training.promotion", "masterquo.ml.service -> masterquo.training.promotion",
               "masterquo.modelhub.families.run -> masterquo.training.dataset_ref", "masterquo.trainhub.pipeline -> masterquo.training.dataset_ref",
               "masterquo.trainhub.registry -> masterquo.training.dataset_ref")

    def test_upward_edges_removed_and_leaves_stdlib_only(self):
        import importlib
        sys.path.insert(0, str(Path(_env.ROOT) / "tools"))
        import cycles
        C = importlib.reload(cycles)
        up = C.upward(C.edges())
        for k in self.REMOVED + TestLockServiceLayers.REMOVED:
            self.assertNotIn(k, up)
        for f in ("promotion.py", "dataset_ref.py"):
            tree = ast.parse((Path(_env.ROOT) / "backend" / "masterquo" / "contracts" / f).read_text(encoding="utf-8"))
            self.assertFalse([n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.level], f)     # stdlib only (contracts rule)


if __name__ == "__main__":
    unittest.main()
