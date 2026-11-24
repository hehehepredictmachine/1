"""1.46 audit, group B_mq_training (masterquo/training + train_all): training orchestrator, panel export/import, export job and the
Pepe training center queue.

Covered: the console wizard crashing on a commission typo, Ctrl+C leaving a training child running, a training lock identified by the PID
alone, export cancel killing a reused PID, resume_dir accepting any folder, the export.log handle leak, malformed packages giving 500,
whole files / ZIP read into RAM (+ orphan .tmp), "ZATRZYMAJ" cancelling a foreign console run, the queue-thread race, scalp_B/scalp_C
training nothing, resume not repeating activation, Scalp B status mapping, E[R] formatting, quality/integration values outside the axes,
Job Object handle leaks and user-facing texts with the old brand. Everything runs offline on synthetic files in a temporary data folder;
nothing here touches MT5, orders, risk or execution."""
from __future__ import annotations

import ctypes
import hashlib
import io
import json
import os
import pathlib
import subprocess
import sys
import threading
import time
import types
import typing
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import _env  # noqa: F401
from _env import TempData

PY = sys.executable


class _Data(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.data = Path(self.td.dir)
        self._env = mock.patch.dict(os.environ, {"MQ_NO_BROWSER": "1"})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self.td.close()

    def plan_run(self, tasks=None, insts=("XAUUSD",)):
        from masterquo.training import core, runner
        plan, ts = runner.build_plan(instruments=list(insts), profile="PELNY_TRENING", symbols={i: f"{i}-" for i in insts}, commissions={},
                                     months=1, synthetic=False, tasks=tasks)
        return core.Run.create(plan, ts)

    def ready_run(self, inst="XAUUSD", dataset_id="D1"):
        """A run whose export + quality are done (dataset folder with source_metadata.json)."""
        run = self.plan_run(insts=(inst,))
        ds = self.data / "ds" / inst / run.run_id
        ds.mkdir(parents=True)
        (ds / "source_metadata.json").write_text(json.dumps({"dataset_id": dataset_id, "instrument": inst, "costs": {}}), encoding="utf-8")
        run.set(f"{inst}:export", execution="UKONCZONE", dataset_dir=str(ds), data_kind="REAL_USER_DATA")
        run.set(f"{inst}:quality", execution="UKONCZONE", quality="NIE_DOTYCZY")
        return run, ds


def _victim() -> subprocess.Popen:
    """An unrelated live process in its OWN process group (a reused PID; HEAD's killpg must not reach the test runner)."""
    return subprocess.Popen([PY, "-c", "import time; time.sleep(60)"], start_new_session=True)


def _end(p: subprocess.Popen) -> None:
    if p.poll() is None:
        p.kill()
    p.wait(10)


# ---------------------------------------------------------------- chunk_37#12 cli: commission typo in the wizard
class TestWizardCommission(_Data):
    def test_typo_is_asked_again_not_traceback(self):
        from masterquo.training import cli, runner
        seen = {}

        def fake_execute(run):
            seen["comm"] = run.state["plan"]["commissions"]
            return 0
        answers = iter(["7$", "brak", "0.5 USD", "-1", "1e9", "7,5"])
        ns = cli.parser().parse_args(["run", "--instruments", "XAUUSD", "--interactive", "--no-detect", "--profile", "TEST_INSTALACJI",
                                      "--months", "1", "--symbol-xauusd", "XAUUSD-"])
        with mock.patch("builtins.input", lambda *_: next(answers)), mock.patch.object(runner, "execute", fake_execute), \
                mock.patch("sys.stdout", io.StringIO()):
            rc = cli.cmd_run(ns)
        self.assertEqual(rc, 0)
        self.assertEqual(seen["comm"], {"XAUUSD": 7.5})

    def test_enter_means_unknown(self):
        from masterquo.training import cli
        with mock.patch("builtins.input", lambda *_: ""):
            self.assertIsNone(cli._ask_commission("BTC"))


# ---------------------------------------------------------------- chunk_37#5 core.run_child: Ctrl+C must not leave the child running
class TestRunChildInterrupt(_Data):
    def test_keyboard_interrupt_terminates_child(self):
        from masterquo.training import core
        run = core.Run.create({"run_id": "TR-ki"}, [core.task("X:t", "X", "t", "test")])
        started: list[subprocess.Popen] = []
        real = subprocess.Popen

        class Rec(real):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                started.append(self)

        def ctrl_c(_s):
            raise KeyboardInterrupt
        fake_time = types.SimpleNamespace(monotonic=time.monotonic, sleep=ctrl_c)
        try:
            with mock.patch.object(core.subprocess, "Popen", Rec), mock.patch.object(core, "time", fake_time), \
                    self.assertRaises(KeyboardInterrupt):
                core.run_child(run, "X:t", [PY, "-c", "import time; time.sleep(60)"], dict(os.environ), 3600, "ki")
            self.assertEqual(len(started), 1)
            self.assertIsNotNone(started[0].poll(), "dziecko treningu dalej działa po Ctrl+C")
        finally:
            for p in started:
                _end(p)


# ---------------------------------------------------------------- chunk_37#6 lock identity (pid + process start time)
class TestLockIdentity(_Data):
    def test_reused_pid_does_not_hold_the_lock(self):
        from masterquo.training import core, panel, pepe_center
        me = core._proc_start(os.getpid())
        if me is None:
            self.skipTest("czas startu procesu nieczytelny na tej platformie")
        # stale lock of a killed runner whose PID now belongs to another (live) process: same pid, different start time
        core.write_json_atomic(core.lock_path(), {"run_id": "TR-OLD", "pid": os.getpid(), "started": me + 12345})
        self.assertFalse(panel.lock_holder()["alive"])
        self.assertIsNone(pepe_center._lock_alive())
        self.assertIsNone(core.acquire_lock("TR-NEW"))
        cur = json.loads(core.lock_path().read_text(encoding="utf-8"))
        self.assertEqual((cur["run_id"], cur["pid"], cur["started"]), ("TR-NEW", os.getpid(), me))
        core.release_lock("TR-NEW")

    def test_live_owner_still_holds_and_old_format_kept(self):
        from masterquo.training import core
        v = _victim()
        try:
            core.write_json_atomic(core.lock_path(), {"run_id": "TR-LIVE", "pid": v.pid, "started": core._proc_start(v.pid)})
            self.assertEqual(core.acquire_lock("TR-NEW"), "TR-LIVE")
            core.write_json_atomic(core.lock_path(), {"run_id": "TR-145", "pid": v.pid})          # lock file of 1.45 (no start time)
            self.assertEqual(core.acquire_lock("TR-NEW"), "TR-145")
        finally:
            _end(v)
        self.assertIsNone(core.acquire_lock("TR-NEW"))                                             # owner gone -> acquired


# ---------------------------------------------------------------- export_job (#9 cancel identity, #10 resume_dir, #11 handle leak)
class FakePopen:
    instances: typing.ClassVar[list] = []

    def __init__(self, cmd, **kw):
        self.cmd, self.kw, self.pid, self.returncode = cmd, kw, 4_000_000 + len(FakePopen.instances), 0
        FakePopen.instances.append(self)

    def poll(self):
        return 0


class TestExportJob(_Data):
    def setUp(self):
        super().setUp()
        from masterquo.training import export_job as EJ
        self.EJ = EJ
        FakePopen.instances = []
        self._procs = mock.patch.dict(EJ._PROCS, clear=True)
        self._procs.start()
        self.addCleanup(self._procs.stop)

    def start(self, **body):
        with mock.patch.object(self.EJ.subprocess, "Popen", FakePopen):
            return self.EJ.start({"instrument": "XAUUSD", "symbol": "XAUUSD-", **body})

    # -- #11
    def test_log_handle_closed_and_finished_children_dropped(self):
        r = self.start()
        self.assertTrue(r["started"])
        log = FakePopen.instances[-1].kw["stdout"]
        self.assertTrue(log.closed, "uchwyt export.log zostaje otwarty w procesie bota")
        self.EJ.status()
        self.assertNotIn(r["pid"], self.EJ._PROCS)

    def test_popen_failure_closes_log(self):
        opened = []
        real_open = open

        def spy_open(*a, **k):
            fh = real_open(*a, **k)
            opened.append(fh)
            return fh

        def boom(*a, **k):
            raise OSError("brak pythona")
        with mock.patch.object(self.EJ.subprocess, "Popen", boom), mock.patch("builtins.open", spy_open), self.assertRaises(OSError):
            self.EJ.start({"instrument": "XAUUSD", "symbol": "XAUUSD-"})
        logs = [f for f in opened if str(getattr(f, "name", "")).endswith("export.log")]
        self.assertTrue(logs and all(f.closed for f in logs))

    # -- #10
    def _prev(self, folder: Path, status: str, **req):
        folder.mkdir(parents=True, exist_ok=True)
        request = {"instrument": "XAUUSD", "symbol": "XAUUSD-", "timeframes": ["M1", "M5", "M15", "M30", "H1", "H4", "D1"], "kind": "training",
                   "date_from": None, "date_to": None, "months": 12, "tick_days": 0.0, "dst_model_requested": "AUTO", **req}
        (folder / "EXPORT_STATUS.json").write_text(json.dumps({"status": status, "pid": 0, "request": request, "frozen": {"x": 1}}), encoding="utf-8")
        return folder

    def test_resume_dir_only_unfinished_same_request_in_datasets(self):
        base = self.data / "training" / "datasets" / "XAUUSD"
        other = self._prev(self.data / "training" / "runs" / "TR-X", "CANCELLED")                      # under data_dir, not a dataset
        with self.assertRaises(ValueError):
            self.start(resume_dir=str(other))
        btc = self._prev(self.data / "training" / "datasets" / "BTC" / "EXP-1", "CANCELLED", instrument="BTC")
        with self.assertRaises(ValueError):
            self.start(resume_dir=str(btc))                                                             # other instrument's folder
        done = self._prev(base / "EXP-DONE", "COMPLETE")
        with self.assertRaises(ValueError):
            self.start(resume_dir=str(done))                                                            # complete export never overwritten
        diff = self._prev(base / "EXP-SYM", "CANCELLED", symbol="GOLD")
        with self.assertRaises(ValueError):
            self.start(resume_dir=str(diff))                                                            # different request
        self.assertEqual(FakePopen.instances, [])
        ok = self._prev(base / "EXP-OK", "CANCELLED")
        r = self.start(resume_dir=str(ok))
        self.assertTrue(r["started"])
        self.assertEqual(Path(r["out"]), ok.resolve())

    # -- #9
    def _job(self, pid, status, **extra):
        out = self.data / "training" / "datasets" / "XAUUSD" / "EXP-1"
        out.mkdir(parents=True, exist_ok=True)
        (out / "EXPORT_STATUS.json").write_text(json.dumps({"status": status, "pid": pid}), encoding="utf-8")
        from masterquo.training import core
        core.write_json_atomic(self.EJ._job_path(), {"pid": pid, "out": str(out), **extra})
        return out

    def test_cancel_never_kills_a_reused_pid(self):
        if os.name == "nt":
            self.skipTest("POSIX")
        from masterquo.training import core
        v = _victim()
        try:
            self._job(v.pid, "COMPLETE")                                                   # job file of 1.45, export finished long ago
            self.EJ.cancel()
            time.sleep(0.3)
            self.assertIsNone(v.poll(), "cancel() zabił obcy proces o tym samym PID")
            self._job(v.pid, "IN_PROGRESS", pid_started=(core._proc_start(v.pid) or 0) + 999)   # same pid, other process start
            self.EJ.cancel()
            time.sleep(0.3)
            self.assertIsNone(v.poll(), "cancel() zabił obcy proces o tym samym PID")
        finally:
            _end(v)

    def test_cancel_still_stops_the_real_export(self):
        if os.name == "nt":
            self.skipTest("POSIX")
        from masterquo.training import core
        v = _victim()
        try:
            out = self._job(v.pid, "IN_PROGRESS", pid_started=core._proc_start(v.pid))
            threading.Thread(target=v.wait, daemon=True).start()            # reaped at once (after a bot restart the export is not our child)
            self.assertTrue(self.EJ.cancel()["ok"])
            v.wait(10)
            self.assertEqual(json.loads((out / "EXPORT_STATUS.json").read_text(encoding="utf-8"))["status"], "CANCELLED")
        finally:
            _end(v)


# ---------------------------------------------------------------- panel: #13 malformed packages, #14 streaming + .tmp
def _zip(entries: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for k, v in entries.items():
            z.writestr(k, v if isinstance(v, (bytes, str)) else json.dumps(v))
    return buf.getvalue()


class TestImportMalformed(_Data):
    def test_bad_manifest_is_value_error(self):
        from masterquo.training import panel
        for man in ([1, 2], {"files": [{"sha256": "x"}]}, {"files": ["a"]}, {"files": "x"}):
            with self.subTest(man=man), self.assertRaises(ValueError):
                panel.import_package(_zip({"MANIFEST.json": man}))

    def test_registry_run_without_run_id_is_skipped(self):
        from masterquo.training import panel
        reg = {"runs": [{"verdict": "HOLDOUT_PASSED"}, "x", {"run_id": 5}]}
        r = panel.import_package(_zip({"MANIFEST.json": {"instrument": "XAUUSD", "files": []},
                                       "models/sh_tp_model/XAUUSD/SCALPING/registry.json": reg}))
        self.assertEqual(r["imported"], [])
        self.assertEqual(len(r["skipped"]), 3)

    def test_registry_not_an_object_is_value_error(self):
        from masterquo.training import panel
        for reg in ([1], {"runs": "x"}):
            with self.subTest(reg=reg), self.assertRaises(ValueError):
                panel.import_package(_zip({"MANIFEST.json": {"instrument": "XAUUSD", "files": []},
                                           "models/sh_tp_model/XAUUSD/HEDGING/registry.json": reg}))


class TestExportPackageStreaming(_Data):
    def setUp(self):
        super().setUp()
        d = self.data / "sh" / "models" / "XAUUSD" / "SCALPING"
        d.mkdir(parents=True)
        self.blob = os.urandom(3 * 2**20 + 17)
        (d / "R1.npz").write_bytes(self.blob)
        (d / "registry.json").write_text(json.dumps({"runs": [], "active": None}), encoding="utf-8")

    def test_files_and_zip_hashed_without_reading_whole_files(self):
        from masterquo.training import panel

        def no_read_bytes(self_):
            raise AssertionError(f"read_bytes({self_}) – cały plik w RAM procesu bota")
        with mock.patch.object(pathlib.Path, "read_bytes", no_read_bytes):
            r = panel.export_package("XAUUSD", "sh_tp_model")
        raw = Path(r["path"]).read_bytes()
        self.assertEqual(r["sha256"], hashlib.sha256(raw).hexdigest())
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            man = json.loads(z.read("MANIFEST.json"))
            for f in man["files"]:
                data = z.read(f["path"])
                self.assertEqual((f["bytes"], f["sha256"]), (len(data), hashlib.sha256(data).hexdigest()), f["path"])
            self.assertEqual(z.read("models/sh_tp_model/XAUUSD/SCALPING/R1.npz"), self.blob)
        self.assertEqual(list(panel.exports_dir().glob("*.tmp")), [])

    def test_error_leaves_no_tmp(self):
        from masterquo.training import panel
        with mock.patch.object(panel, "code_version", side_effect=RuntimeError("x")), self.assertRaises(RuntimeError):
            panel.export_package("XAUUSD", "sh_tp_model")
        self.assertEqual(list(panel.exports_dir().glob("*")), [])


# ---------------------------------------------------------------- pepe_center: #3 foreign run cancel, #8 queue race, texts
class FakeTrainhub:
    def list(self, n):
        return []


class _Center(_Data):
    def setUp(self):
        super().setUp()
        from masterquo.training import pepe_center as P
        self.P = P
        self._candles = mock.patch.object(P.PepeTrainingCenter, "_candles_ok", staticmethod(lambda: True))
        self._candles.start()
        self.addCleanup(self._candles.stop)
        self.c = P.PepeTrainingCenter(types.SimpleNamespace(demo=True, trainhub=FakeTrainhub(), families=None, research=None, tsfm=None))

    def wait(self, pred, t=10.0):
        end = time.monotonic() + t
        while time.monotonic() < end:
            if pred():
                return True
            time.sleep(0.02)
        return False


class TestCenterCancelOwnRunOnly(_Center):
    def test_stop_while_waiting_does_not_cancel_console_run(self):
        from masterquo.training import core
        x = core.runs_dir() / "TR-20990101T000000Z-cons"
        core.write_json_atomic(x / "state.json", {"run_id": x.name, "status": "RUNNING", "plan": {"origin": "menu"}, "tasks": []})
        core.write_json_atomic(core.lock_path(), {"run_id": x.name, "pid": os.getpid()})           # console training in progress
        self.c.enqueue(["forecast"], ["XAUUSD"])
        self.assertTrue(self.wait(lambda: self.c.current and "innego treningu" in (self.c.current.get("detail") or "")))
        self.c.cancel()
        self.assertTrue(self.wait(lambda: self.c.current is None and self.c.history))
        self.assertEqual(self.c.history[-1]["state"], "CANCELLED")
        self.assertFalse((x / "CANCEL").exists(), "ZATRZYMAJ w Centrum anulował cudzy (konsolowy) trening")

    def test_stop_targets_own_run_or_own_process(self):
        from masterquo.training import core
        x = core.runs_dir() / "TR-20990101T000000Z-cons"
        core.write_json_atomic(x / "state.json", {"run_id": x.name, "plan": {"origin": "menu"}, "tasks": []})
        before = {p.name for p in core.runs_dir().iterdir()}
        proc = mock.Mock()
        proc.poll.return_value = None
        q = {"unit": "pipeline", "instruments": ["XAUUSD"], "_before": before, "_proc": proc}
        self.c._stop(q)                                                     # own run not created yet -> own process stopped, nothing written
        proc.terminate.assert_called_once()
        self.assertFalse((x / "CANCEL").exists())
        own = core.runs_dir() / "TR-20990101T000001Z-pepe"
        core.write_json_atomic(own / "state.json", {"run_id": own.name, "plan": {"origin": "pepe-center"}, "tasks": []})
        self.c._stop(q)
        self.assertTrue((own / "CANCEL").exists())
        self.assertFalse((x / "CANCEL").exists())


class _HookLock:
    """RLock that runs `hook` right AFTER the queue thread released the lock on its 'queue empty -> return' path (the race window)."""

    def __init__(self, center):
        self._l, self.c, self.hook, self._tl = threading.RLock(), center, None, threading.local()

    def __enter__(self):
        self._l.acquire()
        st = getattr(self._tl, "st", None) or []
        st.append(threading.current_thread().name == "pepe-training" and not self.c.queue and self.c.current is None)
        self._tl.st = st
        return self

    def __exit__(self, *a):
        fire = self._tl.st.pop()
        self._l.release()
        if fire and self.hook:
            h, self.hook = self.hook, None
            h()
        return False


class TestQueueThreadRace(_Center):
    def test_item_added_in_exit_window_is_run(self):
        self.c._run = lambda q: {"state": "DONE", "detail": "ok"}
        lk = self.c._lock = _HookLock(self.c)
        lk.hook = lambda: self.c.enqueue(["trainhub"], ["BTC"])
        self.c.enqueue(["trainhub"], ["XAUUSD"])
        self.assertTrue(self.wait(lambda: len(self.c.history) == 2, 5.0), f"element utknął w kolejce: {self.c.queue}")
        self.assertEqual(self.c.queue, [])

    def test_queued_text_without_old_brand(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        self.c._run = lambda q: (gate.wait(5), {"state": "DONE", "detail": "ok"})[1]
        self.c.enqueue(["trainhub"], ["XAUUSD"])
        self.c.enqueue(["trainhub"], ["BTC"])
        self.assertTrue(self.wait(lambda: self.c.current is not None))
        row = {u["id"]: u for u in self.c.status()["units"]}["trainhub"]["status"]["BTC"]
        self.assertEqual(row["state"], "QUEUED")
        self.assertNotIn("Pepe", row["detail"])
        gate.set()


# ---------------------------------------------------------------- runner: #2 scalp_B/C, #4 resume activation, #7 status B, #15 E[R]
def _recorder(calls):
    from masterquo.training import runner

    def mk(kind):
        def step(run, inst):
            calls.append(kind)
            run.set(f"{inst}:{kind}", execution="UKONCZONE")
        return step
    return {k: mk(k) for k in runner.STEPS}


class TestScalpBCRequest(_Data):
    def test_scalp_b_alone_trains_scalp(self):
        from masterquo.training import runner
        for k in ("scalp_B", "scalp_C"):
            with self.subTest(k=k):
                run = self.plan_run(tasks=[k])
                self.assertNotEqual(run.task("XAUUSD:scalp_A")["execution"], "POMINIETE")
                calls = []
                with mock.patch.dict(runner.STEPS, _recorder(calls)), mock.patch("sys.stdout", io.StringIO()):
                    self.assertEqual(runner.execute(run), 0)
                self.assertIn("scalp_A", calls)


class TestResumeActivation(_Data):
    def test_resume_repeats_activation_after_model_task_rerun(self):
        from masterquo.training import cli, runner
        run = self.plan_run()
        for t in run.state["tasks"]:
            t["execution"] = "UKONCZONE"
        run.task("XAUUSD:forecast").update(execution="BLAD_TECHNICZNY", detail="TIMEOUT")
        run.task("XAUUSD:activate").update(detail="nic nie aktywowano")
        run.state["status"] = "FINISHED"
        run.save()
        calls = []
        with mock.patch.dict(runner.STEPS, _recorder(calls)), mock.patch("sys.stdout", io.StringIO()):
            rc = cli.cmd_resume(types.SimpleNamespace(run_id=run.run_id))
        self.assertEqual(rc, 0)
        self.assertEqual(calls, ["forecast", "activate", "bot"])

    def test_resume_without_model_rerun_keeps_activation(self):
        from masterquo.training import cli, runner
        run = self.plan_run()
        for t in run.state["tasks"]:
            t["execution"] = "UKONCZONE"
        run.task("XAUUSD:bot").update(execution="BLAD_TECHNICZNY")
        run.save()
        calls = []
        with mock.patch.dict(runner.STEPS, _recorder(calls)), mock.patch("sys.stdout", io.StringIO()):
            cli.cmd_resume(types.SimpleNamespace(run_id=run.run_id))
        self.assertEqual(calls, ["bot"])


class TestScalpStatusMapping(_Data):
    def _scalp(self, tb, inst="XAUUSD"):
        import mq_instruments
        from masterquo.training import core, runner
        run, _ds = self.ready_run(inst)
        rd = self.data / "scalp_run"
        rd.mkdir(exist_ok=True)
        (rd / "report.json").write_text("{}", encoding="utf-8")
        reg = {"runs": {"S1": {"run_id": "S1", "dataset_id": "D1", "created_at_utc": "2026-01-01", "run_dir": str(rd), "task_a_status": "SHADOW_UNVALIDATED",
                               "task_b_status": tb, "task_c_status": "EVALUATED", "horizon_status": {},
                               "costs": {"commission_per_lot_side": 3.0, "commission_source": "user"}}}}
        (mq_instruments.root("scalp", inst) / "registry.json").write_text(json.dumps(reg), encoding="utf-8")
        with mock.patch.object(core, "ensure_candles", lambda r: ("py", None)), mock.patch.object(core, "candles_python", lambda: "py"), \
                mock.patch.object(core, "run_child", lambda *a, **k: (0, "")), mock.patch("sys.stdout", io.StringIO()):
            runner.t_scalp(run, inst)
        return run

    def test_task_b_statuses(self):
        exp = {"FILTER_HELPS_IN_HOLDOUT": "ZWALIDOWANY_SHADOW", "FILTER_NOT_HELPING_IN_HOLDOUT": "ODRZUCONY", "NO_USEFUL_THRESHOLD": "ODRZUCONY",
               "REJECTED": "ODRZUCONY", "INSUFFICIENT_DATA": "BRAK_PRZESLANEK", "SOMETHING_NEW": "NIEZWALIDOWANY", None: "NIEZWALIDOWANY"}
        for tb, q in exp.items():
            with self.subTest(tb=tb):
                run = self._scalp(tb)
                self.assertEqual(run.task("XAUUSD:scalp_B")["quality"], q)

    def test_unknown_commission_text_without_old_brand(self):
        from masterquo.training import runner
        run, _ = self.ready_run("BTC")
        with mock.patch.object(runner.core, "ensure_candles", lambda r: ("py", None)), mock.patch("sys.stdout", io.StringIO()):
            runner.t_scalp(run, "BTC")
        det = run.task("BTC:scalp_A")["detail"]
        self.assertIn("nieznana prowizja", det)
        self.assertNotIn("Pepe", det)


class TestShModelsExpectancyText(_Data):
    def test_expectancy_keeps_exponent(self):
        from masterquo.training import core, runner
        run, _ = self.ready_run()
        rep = {"strategies": {"SCALPING": {"setups_ready": 10, "model": {"verdict": "REJECTED", "run_id": "R1"},
                                           "metrics": {"expectancy": 1.2345678e-05}, "baseline": {"expectancy": 12345678.9}},
                              "HEDGING": {"setups_ready": 0, "model": {"verdict": "INSUFFICIENT_DATA"}, "metrics": {}, "baseline": {"expectancy": -3.2e-05}}}}

        def child(run_, tid, cmd, env, timeout, log):
            Path(cmd[cmd.index("--out") + 1]).write_text(json.dumps(rep), encoding="utf-8")
            return 0, ""
        with mock.patch.object(core, "run_child", child), mock.patch("sys.stdout", io.StringIO()):
            runner.t_sh_models(run, "XAUUSD")
        det = run.task("XAUUSD:sh_models")["detail"]
        self.assertIn("E[R] 1.235e-05 (baseline 1.235e+07)", det)
        self.assertIn("E[R] brak (baseline -3.2e-05)", det)


# ---------------------------------------------------------------- #16 axis values, #17 docstring
class TestAxesAndLabels(_Data):
    def test_values_written_by_runner_are_on_the_axes(self):
        from masterquo.training import core, pepe_center
        self.assertIn("DO_OCENY_NA_DEV", core.QUAL)
        self.assertIn("RAPORT_WALIDACJI", core.INTEG)
        run = self.plan_run(tasks=["flow_context"])
        run.set("XAUUSD:flow_context", execution="UKONCZONE", quality="DO_OCENY_NA_DEV", integration="ZAPISANY_DO_BADAN")
        st = pepe_center.pipeline_status()[("flow_context", "XAUUSD")]
        self.assertEqual(st["state"], "DONE")
        self.assertNotEqual(st["detail"], "do_oceny_na_dev")
        self.assertIn("holdout", st["detail"])

    def test_child_env_docstring_does_not_claim_order_protection(self):
        from masterquo.training import core
        self.assertNotIn("(no order path)", core.child_env.__doc__)


# ---------------------------------------------------------------- #18 Windows handles (simulated kernel32)
class _K32:
    def __init__(self):
        self.closed = []
        for n in ("CreateJobObjectW", "OpenProcess", "SetInformationJobObject", "AssignProcessToJobObject", "CloseHandle"):
            setattr(self, n, self._fn(n))

    def _fn(self, name):
        ret = {"CreateJobObjectW": 11, "OpenProcess": 22}.get(name, 1)

        def f(*a):
            if name == "CloseHandle":
                self.closed.append(getattr(a[0], "value", a[0]))
            return ret
        return f


class TestJobHandles(unittest.TestCase):
    def test_process_handle_and_job_closed(self):
        from masterquo.training import core
        k = _K32()
        proc = types.SimpleNamespace(pid=1234)
        with mock.patch.object(ctypes, "windll", types.SimpleNamespace(kernel32=k), create=True), \
                mock.patch.object(core, "os", types.SimpleNamespace(name="nt", environ=os.environ)):
            core._job_limit(proc, 100)
            self.assertEqual(proc._mq_job, 11)
            self.assertIn(22, k.closed, "uchwyt procesu z OpenProcess nie jest zamykany")
            core.close_job(proc)
        self.assertIn(11, k.closed)
        self.assertIsNone(proc._mq_job)


if __name__ == "__main__":
    unittest.main()
