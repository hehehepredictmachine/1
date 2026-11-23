"""1.46 audit, group B_research_2 (Chronos-2 / Granite TTM / TiRex-2 service, validation and settings) - regression tests.

chunk_38#4  ledger: a Granite TTM fine-tune has its own ledger key (+checkpoint), an identical re-forecast of the same bar resolves to the
            stored forecast id, a different one is marked REFORECAST_NOT_RECORDED (the first, stored-before-outcome row is kept),
            refresh() forces only the requested model, the scorecard counts only the current model artefact.
chunk_38#5  a one-off exception of the scheduler tick no longer leaves every worker in ERROR/TICK until a restart.
chunk_38#9  an unloadable settings.json is copied (byte for byte) before the first change overwrites it.
chunk_38#2  the walk-forward validation sends the live request (configured profile + covariates, context cut to the lookback window) and
            uses the live neutral band rule max(k x ATR14, min_points x point).
chunk_38#6  the Memory Governor does not release a model process in the middle of the validation (last_used + heavy slot).
chunk_38#10 public() copies the job queue under the queue lock.
Test doubles only (stub worker process from tests/tsfm_stub_worker.py - its numbers are not forecasts)."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
import time
import unittest
from pathlib import Path

import _env  # noqa: F401
from _env import TempData

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kronos_testkit as K
from test_tsfm_bot import WED_1200, fixture_weights, stub_python


class _Svc(unittest.TestCase):
    """The TestService pattern of test_tsfm_bot: real TsfmService, stub model processes, fake MT5 bridge, isolated data dir."""

    def setUp(self):
        self.td = TempData()
        self.dir = Path(self.td.dir)
        os.environ["MQ_TSFM_ALLOW_FIXTURE"] = "1"
        self.bridge = K.FakeBridge({("XAUUSD-", "M5"): K.make_bars(300, WED_1200, 20)})
        self.cfg = K.FakeCfgStore(K.FakeCfg({"XAUUSD": K.FakeMapping("XAUUSD-")}))
        self.svc = None

    def tearDown(self):
        os.environ.pop("MQ_TSFM_ALLOW_FIXTURE", None)
        if self.svc is not None:
            self.svc.stop()
        self.td.close()

    def make(self, models: dict | None = None, **top):
        from masterquo.db.database import Database
        from masterquo.tsfm.service import TsfmService
        from masterquo.tsfm.settings import SettingsStore
        st = SettingsStore(self.dir / "tsfm" / "settings.json")
        root = self.dir / "w"
        fixture_weights(root, "chronos2")
        fixture_weights(root, "granite_ttm")
        py = stub_python(self.dir, "ok")
        mc = {m: {"python_path": py, "timeframes": ["M5"], "instruments": ["XAUUSD"], "request_timeout_s": 5.0, **(models or {}).get(m, {})}
              for m in ("chronos2", "granite_ttm", "tirex2")}
        st.update({"weights_root": str(root), "models": mc, **top})
        self.svc = TsfmService(self.cfg, self.bridge, Database(self.dir / "t.sqlite"), K.Bus(), K.Log(), clock=lambda: WED_1200, settings=st)
        return self.svc

    def run_queue(self):
        out = []
        while self.svc.queue:
            _k, job = self.svc.queue.popitem(last=False)
            out.append(self.svc.run_job(job))
        return out


class TestLedgerReforecast(_Svc):
    """chunk_38#4"""

    def test_reforecast_of_the_same_bar_resolves_to_the_ledger(self):
        svc = self.make()
        svc.tick()
        self.run_queue()
        k = ("chronos2", "XAUUSD", "M5")
        first = svc.latest[k]["id"]
        r = svc.refresh(*k)
        self.assertTrue(r["ok"], r)
        self.assertEqual(set(svc.queue), {k})                  # only the requested model is re-forecast (was: every model of XAUUSD M5)
        self.run_queue()
        fc = svc.latest[k]
        self.assertIsNotNone(svc.db.one("SELECT id FROM tsfm_forecasts WHERE forecast_id=?", (fc["id"],)))   # the id used everywhere is stored
        self.assertEqual((fc["id"], fc["ledger"]["status"]), (first, "SAME_AS_RECORDED"))
        self.assertEqual(svc.db.one("SELECT COUNT(*) AS n FROM tsfm_forecasts WHERE model_id='chronos2'")["n"], 1)   # no double count

    def test_different_reforecast_is_marked_and_the_first_row_is_kept(self):
        svc = self.make()
        svc.tick()
        self.run_queue()
        fc = svc.latest[("chronos2", "XAUUSD", "M5")]
        stored = svc.db.one("SELECT * FROM tsfm_forecasts WHERE forecast_id=?", (fc["id"],))
        other = json.loads(json.dumps(fc))
        other["id"] = "reforecast00001"
        other["path"][-1]["point"] += 1.0
        other["pred_close_h"] += 1.0
        self.assertFalse(svc.record(other))
        self.assertEqual(other["ledger"]["status"], "REFORECAST_NOT_RECORDED")
        self.assertEqual(other["ledger"]["recorded_forecast_id"], fc["id"])
        self.assertEqual(svc.db.one("SELECT * FROM tsfm_forecasts WHERE forecast_id=?", (fc["id"],)), stored)   # never overwritten

    def test_granite_checkpoint_has_its_own_ledger_rows_and_scorecard(self):
        from tsfm_runtime import lock as L
        svc = self.make()
        svc.tick()
        self.run_queue()
        base = svc.latest[("granite_ttm", "XAUUSD", "M5")]
        gtr = json.loads(json.dumps(base))
        gtr.update(id="gtrforecast0001", checkpoint="GTR-test01")
        self.assertTrue(svc.record(gtr))                         # was dropped by INSERT OR IGNORE (same base fingerprint, same bar)
        rows = svc.db.query("SELECT fingerprint, settings_json FROM tsfm_forecasts WHERE model_id='granite_ttm' ORDER BY id")
        fp = L.fingerprint("granite_ttm")
        self.assertEqual([r["fingerprint"] for r in rows], [fp, f"{fp}+GTR-test01"])
        self.assertEqual([json.loads(r["settings_json"])["checkpoint"] for r in rows], ["BASE", "GTR-test01"])
        later = K.make_bars(300, WED_1200 + 3 * 3600, 20)
        svc.settle("XAUUSD", "M5", [b for b in later if b["closed"]])
        sc = svc.scorecard("granite_ttm", "XAUUSD", "M5")
        self.assertEqual((sc["REAL"]["settled"], sc["REAL"]["fingerprint"]), (1, fp))   # BASE only (was 2: BASE + fine-tune mixed)
        svc.settings.update({"models": {"granite_ttm": {"checkpoint": "GTR-test01"}}})
        sc = svc.scorecard("granite_ttm", "XAUUSD", "M5")
        self.assertEqual((sc["REAL"]["settled"], sc["REAL"]["fingerprint"]), (1, f"{fp}+GTR-test01"))


class TestTickErrorRecovers(_Svc):
    """chunk_38#5"""

    def test_one_off_tick_exception_does_not_stick(self):
        svc = self.make()
        svc.tick()
        self.run_queue()
        self.assertEqual(svc.workers["chronos2"].state["status"], "READY")
        real_tick = svc.tick

        def boom(*a, **k):
            svc._stop.set()                                      # one iteration of _loop only
            raise sqlite3.OperationalError("database is locked")
        svc.tick = boom
        with self.assertLogs("masterquo.tsfm", "ERROR"):
            svc._loop()
        self.assertEqual({(w.state["status"], w.state["code"]) for w in svc.workers.values()}, {("ERROR", "TICK")})
        svc.tick = real_tick
        svc._stop.clear()
        svc.tick()                                               # the next tick works -> the scheduler error is gone
        self.assertEqual(svc.workers["chronos2"].state["status"], "READY")        # process loaded
        self.assertEqual(svc.workers["granite_ttm"].state["status"], "READY")
        self.assertEqual(svc.workers["tirex2"].state["status"], "NO_WEIGHTS")     # its own state, not the scheduler error
        svc.tick = boom
        with self.assertLogs("masterquo.tsfm", "ERROR"):
            svc._loop()                                          # a failure that repeats is reported again
        self.assertEqual(svc.workers["chronos2"].state["code"], "TICK")


class TestInvalidSettingsKept(unittest.TestCase):
    """chunk_38#9"""

    def test_unloadable_file_is_copied_before_the_first_write(self):
        from masterquo.tsfm.settings import SettingsStore
        td = TempData()
        try:
            p = Path(td.dir) / "tsfm" / "settings.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            user = {"models": {"chronos2": {"instruments": ["XAUUSD", "BTC"], "timeframes": ["M5", "M15", "H1"], "context_len": 1024,
                                            "use": {"SCALPING": {"use": "REQUIRED", "timeframe": "M5", "validation_report": "R1"}}}},
                    "quantiles": [0.05, 0.5, 0.95], "horizon_bars": {"M5": 20}}           # 0.05 / 0.95: not a supported level -> invalid
            raw = json.dumps(user, indent=1).encode("utf-8")
            p.write_bytes(raw)
            st = SettingsStore(p)
            self.assertIsNotNone(st.load_error)
            self.assertEqual(st.get().models["chronos2"].use["SCALPING"].use, "OBSERVE")   # a broken file never enables anything
            st.update({"queue_max": 8})
            kept = list(p.parent.glob("settings.invalid-*.json"))
            self.assertEqual(len(kept), 1, list(p.parent.iterdir()))
            self.assertEqual(kept[0].read_bytes(), raw)                                     # the user's values are not lost
            self.assertEqual(json.loads(p.read_text(encoding="utf-8"))["queue_max"], 8)
            self.assertEqual([h["who"] for h in st.history()][-2:], ["invalid_file_kept", "panel"])
            st.update({"queue_max": 9})                                                    # the next change: a valid file, no new copy
            self.assertEqual(len(list(p.parent.glob("settings.invalid-*.json"))), 1)
            p.write_text(json.dumps({"queue_max": 5}), encoding="utf-8")                   # a valid file is never copied
            st2 = SettingsStore(p)
            self.assertIsNone(st2.load_error)
            st2.update({"queue_max": 6})
            self.assertEqual(len(list(p.parent.glob("settings.invalid-*.json"))), 1)
        finally:
            td.close()


class TestValidationMirrorsLive(_Svc):
    """chunk_38#2 (+ chunk_38#6 with the Memory Governor)"""

    def _asks(self, svc, mid, hook=None):
        w = svc.workers[mid]
        orig = w.ask
        seen = []

        def ask(req, timeout):
            if req.get("cmd") == "predict":
                seen.append(req)
                if hook:
                    hook(w)
            return orig(req, timeout)
        w.ask = ask
        return seen

    def test_request_profile_context_and_band_match_the_live_rule(self):
        from masterquo.tsfm import validation as V
        svc = self.make({"chronos2": {"profile": "CLOSE_OHLCV_PAST_V1", "context_len": 1024}, "granite_ttm": {"enabled": False},
                         "tirex2": {"enabled": False}}, lookback=560, direction_band_min_points=500.0)
        seen = self._asks(svc, "chronos2")
        rep = V.run(svc, "XAUUSD", "M5", max_origins=24, include_kronos=False)
        self.assertEqual(rep["status"], "DONE", rep.get("reason"))
        self.assertTrue(seen)
        self.assertEqual({r["profile"] for r in seen}, {"CLOSE_OHLCV_PAST_V1"})          # was always CLOSE_V1
        self.assertTrue(all(r.get("covariates") and len(r["covariates"]["open"]) == 560 for r in seen))
        self.assertEqual({(len(r["close"]), r["context_len"]) for r in seen}, {(560, 560)})   # live: min(context_len, lookback window)
        self.assertEqual(rep["models"]["chronos2"]["request"], {"profile": "CLOSE_OHLCV_PAST_V1", "context_bars": 560})
        for row in rep["rows"]:                                  # live band max(0.25 x ATR14, 500 x point 0.01) = 5.0 here
            self.assertAlmostEqual(row["band"], max(0.25 * row["atr"], 5.0))
        self.assertEqual(rep["models"]["chronos2"]["test_own"]["direction_n"], 0)   # stub moves 0.2 x 12 = 2.4 < band 5.0 -> FLAT

    def test_governor_never_releases_the_model_during_validation(self):
        from masterquo.resources.governor import Governor
        from masterquo.tsfm import validation as V
        from test_resources_governor import Cfg, Store
        svc = self.make({"granite_ttm": {"enabled": False}, "tirex2": {"enabled": False}})
        g = Governor(Store(Cfg("MANUAL", {"idle_release_s": 0})), memory=lambda: {"total_mb": 16384, "used_pct": 50.0, "process_mb": 300.0},
                     proc_mem=lambda pid: (None, None))
        svc.governor = g
        w = svc.workers["chronos2"]
        # registered exactly as runtime._wire_governor does
        g.register("chronos2", "heavy", lambda: w.proc.pid if (w.proc and w.proc.poll() is None) else None,
                   release=lambda: (svc.running is None or svc.running[0] != "chronos2") and w.kill(),
                   idle=lambda: 0.0 if (svc.running and svc.running[0] == "chronos2") else time.monotonic() - w.last_used)
        w.last_used = time.monotonic() - 10_000                  # long idle before the validation starts
        idles = []

        def tick_governor(worker):                               # the governor thread runs while the validation asks
            idles.append(g.sources["chronos2"]["idle"]())
            g.maintain()
        seen = self._asks(svc, "chronos2", tick_governor)
        rep = V.run(svc, "XAUUSD", "M5", max_origins=24, include_kronos=False)
        self.assertEqual(rep["status"], "DONE", rep.get("reason"))
        self.assertEqual(g.counters["released"], 0)
        self.assertEqual(rep["models"]["chronos2"]["coverage"]["errors"], 0)
        self.assertGreaterEqual(len(seen), 20)
        self.assertLess(max(idles), 60.0)                        # every request counts as use of the process
        self.assertIsNotNone(w.proc)


class TestPublicQueueLock(_Svc):
    """chunk_38#10"""

    def test_public_copies_the_queue_under_the_lock(self):
        svc = self.make()
        svc.tick()
        self.assertTrue(svc.queue)
        held, release = threading.Event(), threading.Event()

        def holder():
            with svc._qlock:                                     # the exec / sched thread mutating the queue
                held.set()
                release.wait(10)
        th = threading.Thread(target=holder, daemon=True)
        th.start()
        self.assertTrue(held.wait(5))
        out = {}
        pub = threading.Thread(target=lambda: out.setdefault("p", svc.public()), daemon=True)
        pub.start()
        pub.join(1.0)
        waited = pub.is_alive()
        release.set()
        pub.join(10)
        th.join(10)
        self.assertTrue(waited, "public() read the queue without the queue lock")
        self.assertEqual(sorted(map(tuple, out["p"]["queue"])), sorted(svc.queue))


if __name__ == "__main__":
    unittest.main()
