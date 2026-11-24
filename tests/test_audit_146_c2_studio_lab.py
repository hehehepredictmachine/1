"""1.46 audit, cross-file group C2_studio_lab: studio/jobrun.py, studio/registry.py, lab/si_service.py, marketdata/export.py.
The earlier groups fixed their part of each finding; these tests cover the patch that was still needed in THIS group's files. Each test
fails with the HEAD (pre-fix) version of the file. No HTTP server; the Studio job runner is called in-process with run_task patched."""
from __future__ import annotations

import json
import math
import os
import shutil
import tempfile
import threading
import time
import types
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

import _env  # noqa: F401
import numpy as np
from _env import TempData


def _ts(x) -> float:
    return datetime.fromisoformat(str(x)).timestamp()


def gapped(segments, step_min: int, seed: int = 5) -> list[dict]:
    """Synthetic bars in contiguous segments; each segment starts after `gap` minutes without data (weekend / history hole)."""
    rng = np.random.default_rng(seed)
    t, c, out = datetime(2026, 3, 2, tzinfo=UTC), 2000.0, []
    for n, gap in segments:
        t += timedelta(minutes=gap)
        for _ in range(n):
            o = c
            c = o + rng.normal(0, 0.4 * math.sqrt(step_min))
            out.append({"open_utc": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "o": o, "h": max(o, c) + abs(rng.normal(0, 0.2)),
                        "l": min(o, c) - abs(rng.normal(0, 0.2)), "c": c, "tv": 50.0, "spread": 12.0})
            t += timedelta(minutes=step_min)
    return out


class StudioEnv(unittest.TestCase):
    """Isolated Studio + bot data dirs (as test_audit_146_b_studio_th_1)."""

    def setUp(self):
        self.td = Path(tempfile.mkdtemp(prefix="studio146c2_"))
        self.studio, self.bot = self.td / "studio", self.td / "bot"
        self.studio.mkdir()
        self.bot.mkdir()
        self.old = {k: os.environ.get(k) for k in ("MQ_STUDIO_DATA_DIR", "MQ_BOT_DATA_DIR", "MASTERQUO_DATA_DIR")}
        os.environ.update(MQ_STUDIO_DATA_DIR=str(self.studio), MQ_BOT_DATA_DIR=str(self.bot), MASTERQUO_DATA_DIR=str(self.studio))

    def tearDown(self):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.td, ignore_errors=True)

    def queue(self):
        from masterquo.studio.queue import Queue
        q = Queue(self.td / "q.sqlite", lock_path=self.td / "locks" / "x.lock")
        self.addCleanup(q.db.close)
        return q

    @staticmethod
    def key(model: str, inst: str = "XAUUSD") -> str:
        from masterquo.studio import registry as R
        return next(t["task_key"] for t in R.tasks() if t["model_id"] == model and t["instrument"] == inst)

    def run_job(self, model: str, op: str):
        """Queue one job and execute it with studio.jobrun.main in-process; run_task is replaced by a recorder."""
        from masterquo.studio import jobrun
        from masterquo.studio import pipeline as P
        q = self.queue()
        jid = q.submit(self.key(model), op, source={"mode": "SYNTHETIC", "days": 5})["job_id"]
        seen = []

        def fake_run(task, pkg, op_, ctx):
            seen.append((task, ctx))
            return {"status": "EXPORTED", "stages": [], "package": str(pkg.dir)}
        with mock.patch.object(P, "run_task", side_effect=fake_run):
            rc = jobrun.main([str(q.path), jid])
        return rc, seen, q.job(jid)

    def write_bot_config(self):
        from masterquo.config import ConfigStore
        os.environ["MASTERQUO_DATA_DIR"] = str(self.bot)
        try:
            ConfigStore(self.bot / "config.json").update({"mt5": {"symbol": "GOLD.pro"}, "assets": {"mappings": {
                "XAUUSD": {"broker_symbol": "GOLD.pro", "status": "USER_SPECIFIED"},
                "BTC": {"broker_symbol": "BTCUSD.pro", "status": "USER_SPECIFIED"}}}})
        finally:
            os.environ["MASTERQUO_DATA_DIR"] = str(self.studio)
        return (self.bot / "config.json").read_bytes()


# ------------------------------------------------------------------ chunk_35#8 (jobrun.py)
class TestJobrunReadsBotConfig(StudioEnv):
    def test_job_process_uses_bot_mappings_read_only(self):
        """The job process (where export / training really run) built ConfigStore() in the Studio data dir: a default <studio>/config.json
        was created and the bot's broker symbol mappings / MT5 terminal / family pairs were ignored ('XAUUSD-' instead of 'GOLD.pro')."""
        before = self.write_bot_config()
        rc, seen, job = self.run_job("IND_SEMIVAR", "FULL_EXPORT")
        self.assertEqual(rc, 0, job)
        self.assertEqual(len(seen), 1)
        task, ctx = seen[0]
        self.assertEqual(task["broker_symbol"], "GOLD.pro")
        self.assertIsNotNone(ctx.cfg_store)
        cfg = ctx.cfg_store.get()
        self.assertEqual(cfg.assets.mappings["XAUUSD"].broker_symbol, "GOLD.pro")
        self.assertEqual(cfg.mt5.symbol, "GOLD.pro")
        self.assertFalse((self.studio / "config.json").exists())                 # no default Studio config
        self.assertEqual((self.bot / "config.json").read_bytes(), before)       # the bot's file is never rewritten

    def test_job_without_bot_config_has_no_guessed_symbol(self):
        rc, seen, job = self.run_job("IND_SEMIVAR", "FULL_EXPORT")
        self.assertEqual(rc, 0, job)
        task, ctx = seen[0]
        self.assertIsNone(task["broker_symbol"])                                # UNAVAILABLE, never 'XAUUSD-'
        self.assertIsNone(ctx.cfg_store)
        self.assertFalse((self.studio / "config.json").exists())


# ------------------------------------------------------------------ chunk_35#10 (registry.py)
class TestMultiSeriesTasksNotOffered(StudioEnv):
    MULTI = ("BARS_MULTI", "BARS_DXY")

    def test_pair_basket_dxy_tasks_are_not_implemented(self):
        """PAIR_COINT / STATARB (pair / basket series) and IND_XAU_DXY (DXY series, also offered for BTC) were SUPPORTED with export /
        train buttons, although Studio exports only the task's own instrument - they could never succeed."""
        from masterquo.studio import registry as R
        ts = R.tasks()
        multi = [t for t in ts if any(s.get("kind") in self.MULTI for s in t.get("sources") or [])]
        self.assertTrue({"PAIR_COINT", "STATARB", "IND_XAU_DXY"} <= {t["model_id"] for t in multi})
        for t in multi:
            with self.subTest(model=t["model_id"], inst=t["instrument"]):
                self.assertEqual(t["state"], "NOT_IMPLEMENTED")
                self.assertTrue(t["reason"])
                self.assertEqual(R.operations(t), [])                          # no export / train button in the UI
                # task keys do not depend on state / reason: jobs queued by 1.45.0 still resolve
                self.assertEqual(R._key(dict(t, state="SUPPORTED", reason=None)), t["task_key"].rsplit(":", 1)[1])
        rows = {r["task_key"]: r for r in R.matrix()["rows"]}
        self.assertTrue(all(rows[t["task_key"]]["operations"] == [] for t in multi))
        self.assertEqual(len(ts), len({t["task_key"] for t in ts}))
        # single-series tasks are untouched
        semi = next(t for t in ts if t["model_id"] == "IND_SEMIVAR")
        self.assertEqual((semi["state"], R.operations(semi)), ("SUPPORTED", ["FULL_EXPORT", "VALIDATE", "EXPORT_FEATURES"]))

    def test_queued_dxy_job_ends_with_reason_without_running(self):
        rc, seen, job = self.run_job("IND_XAU_DXY", "FULL_EXPORT")
        self.assertEqual(seen, [])                                             # no export started
        self.assertEqual(rc, 3)
        self.assertNotIn(job["state"], ("QUEUED", "EXPORTED"))
        self.assertIn("DXY", job["error"])


# ------------------------------------------------------------------ chunk_17#1 / chunk_17#14 (si_service.py)
class _Cfg:
    def __init__(self):
        self.v = types.SimpleNamespace(mt5=types.SimpleNamespace(symbol="XAUUSD-"), assets=types.SimpleNamespace(active="XAUUSD", symbols={}))

    def get(self):
        return self.v


def si_service():
    from masterquo.lab.si_service import StructureIntelligenceService
    bridge = types.SimpleNamespace(state="CONNECTED", symbol_info=None)
    return StructureIntelligenceService(_Cfg(), bridge, None, None, None)


class TestFlowJobDevCut(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_flow_calibrate_and_markov_jobs_never_read_holdout(self):
        """The UI job (flow_calibrate / flow_markov) cut DEV as m1[:80 % of bars]; the FLOW_CONTEXT_MOVE_M1_V1 holdout is time-based
        (structure_task.split over rows >= WARM) - across a history gap the calibration read holdout bars (holdout_read=False was false)."""
        from masterquo.lab import structure_task as T
        from masterquo.lab.flow_context import cli as FCLI
        from masterquo.lab.flow_context import task as FT
        from test_structure_intelligence import write_export
        m1 = gapped([(2000, 0), (1000, 60 * 24 * 10)], 1)
        fe = FT.features(m1, 0.01, 0.01)
        rows = np.where((np.arange(len(m1)) >= FT.WARM) & np.isfinite(fe["atr"]) & np.isfinite(fe["F"]).all(axis=1))[0]
        sp = T.split({"fe": {"t": fe["t"]}, "rows_idx": rows, "manifest": {"task": T.TASK_MOVE}})
        t_hold = float(fe["t"][rows[sp["hold"][0]]])
        ds = write_export(Path(self.td.dir) / "exp", m1)
        got = {}

        def cap(name):
            def f(inst, dev, *a, **kw):
                got[name] = dev
                return {"status": "OK"}
            return f
        si = si_service()
        with mock.patch("masterquo.extind.cli._latest_real", return_value=ds), \
                mock.patch.object(FCLI, "calibrate", side_effect=cap("flow_calibrate")), \
                mock.patch.object(FCLI, "train_markov", side_effect=cap("flow_markov")):
            for kind in ("flow_calibrate", "flow_markov"):
                job = {"job_id": "J", "kind": kind, "params": {"asset": "XAUUSD"}, "status": "RUNNING", "log": [], "cancel": threading.Event()}
                si._run_job(job)
                self.assertEqual(job["status"], "COMPLETED", job.get("error"))
        for name in ("flow_calibrate", "flow_markov"):
            with self.subTest(job=name):
                self.assertGreater(len(got[name]), 1500)
                self.assertLess(max(_ts(b["open_utc"]) for b in got[name]), t_hold)
                self.assertEqual(len(got[name]), len(FT.dev_bars(m1)))          # the same rule as the CLI path


class TestContextUnsupportedTf(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_m30_cell_is_not_supported_not_warming_up(self):
        """The SI snapshot has M30, context_ind computes only M1/M5/M15/H1: the M30 context cell said WARMING_UP forever."""
        si = si_service()
        m30 = gapped([(200, 0)], 30, seed=7)
        cell = si.cell("M30", m30, 0.01, [], "XAUUSD")
        self.assertEqual(cell["status"], "OK")
        self.assertEqual(cell["context"]["status"], "NOT_SUPPORTED_TF")
        self.assertEqual(cell["context"]["tf"], "M30")
        m5 = gapped([(200, 0)], 5, seed=7)
        self.assertNotEqual(si.cell("M5", m5, 0.01, [], "XAUUSD")["context"]["status"], "NOT_SUPPORTED_TF")


# ------------------------------------------------------------------ focus_X5#7 / chunk_36#6 (marketdata/export.py)
class TestExportBusyDisplayName(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.prev = os.environ.pop("MQ_STUDIO_DATA_DIR", None)          # outside a Studio job: the bot's export takes the lock itself

    def tearDown(self):
        if self.prev is not None:
            os.environ["MQ_STUDIO_DATA_DIR"] = self.prev
        self.td.close()

    def _lock(self):
        from masterquo.paths import data_dir
        return data_dir() / "locks" / "pmw_export.lock"

    def test_busy_message_uses_display_names(self):
        from masterquo.marketdata import export as EX
        from masterquo.marketdata.store import Store
        p = self._lock()
        p.parent.mkdir(parents=True, exist_ok=True)
        for app, want in (("PepeTrainingStudio", "Apollo23 Data & Training Studio"), ("PepeMarketWizard-export", "Apollo23")):
            with self.subTest(app=app):
                now = time.time()
                p.write_text(json.dumps({"pid": os.getpid(), "app": app, "job": "JOB-1", "host": "h", "acquired_at": now, "heartbeat": now}))
                with self.assertRaises(EX.ExportBusy) as cm:
                    EX.run(object(), Store(), "XAUUSD", "XAUUSD-")
                msg = str(cm.exception)
                self.assertIn(want, msg)
                self.assertIn("JOB-1", msg)
                self.assertNotIn("Pepe", msg)
        p.write_text(json.dumps({"pid": os.getpid(), "app": "SomeOtherTool", "job": "J9", "heartbeat": time.time()}))
        with self.assertRaises(EX.ExportBusy) as cm:
            EX.run(object(), Store(), "XAUUSD", "XAUUSD-")
        self.assertIn("SomeOtherTool", str(cm.exception))                    # unknown owner: shown as recorded

    def test_lock_owner_id_unchanged(self):
        """Display text only - the lock's app id (read by Studio and older versions) stays 'PepeMarketWizard-export'."""
        from masterquo.marketdata import export as EX
        from masterquo.marketdata.store import Store
        p = self._lock()
        with mock.patch.object(EX, "_run", side_effect=lambda *a, **k: json.loads(p.read_text())["app"]):
            self.assertEqual(EX.run(object(), Store(), "XAUUSD", "XAUUSD-"), "PepeMarketWizard-export")
        self.assertFalse(p.exists())                                         # released


class _NoInfoSource:
    """symbol_info fails (terminal busy / disconnected at the end of an export) - or returns None."""

    def __init__(self, raise_=True):
        self.raise_ = raise_

    def call(self, fn):
        if self.raise_:
            raise RuntimeError("terminal busy")
        return fn(types.SimpleNamespace(symbol_info=lambda s: None))

    def describe(self):
        return {"mode": "TEST"}

    def synthetic(self):
        return False


class TestFinishKeepsKnownSymbolSpec(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def _store(self):
        from masterquo.marketdata.store import Store
        st = Store()
        st.write_manifest("XAUUSD", {"symbol": "XAUUSD-", "symbol_spec": {"digits": 2, "point": 0.01, "trade_contract_size": 100.0},
                                     "costs": {"spread": {"status": "MEASURED_PER_BAR", "point": 0.01, "contract_size": 100.0}}})
        return st

    def _finish(self, st, src, symbol):
        from masterquo.marketdata import export as EX
        EX._finish(src, st, "XAUUSD", symbol, ["M5"], {"time_model": {"model": "UNIFORM"}, "ranges": {}}, {"status": "FAILED", "timeframes": {}},
                   None)
        return st.manifest("XAUUSD")

    def test_failed_symbol_info_keeps_values_of_same_symbol(self):
        """chunk_36#6 (export side): a failed symbol_info at the end of an export overwrote the measured point / contract size / spec of
        the store with None / {} - every later family fit / inference then had no point."""
        for raise_ in (True, False):
            with self.subTest(raise_=raise_):
                man = self._finish(self._store(), _NoInfoSource(raise_), "XAUUSD-")
                self.assertEqual(man["costs"]["spread"]["point"], 0.01)
                self.assertEqual(man["costs"]["spread"]["contract_size"], 100.0)
                self.assertEqual(man["symbol_spec"]["point"], 0.01)

    def test_values_of_another_symbol_are_never_carried_over(self):
        man = self._finish(self._store(), _NoInfoSource(True), "GOLD.pro")
        self.assertIsNone(man["costs"]["spread"]["point"])                      # UNAVAILABLE, never the old symbol's spec
        self.assertIsNone(man["costs"]["spread"]["contract_size"])
        self.assertEqual(man["symbol_spec"], {})
        self.assertEqual(man["symbol"], "GOLD.pro")


if __name__ == "__main__":
    unittest.main()
