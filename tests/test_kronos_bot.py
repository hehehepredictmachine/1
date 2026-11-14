"""Kronos integration - bot side (no torch needed): calendar, data quality, settings, PMW-PRED-1, strategy gate (fail-closed, never a
permission), service with a STUB worker process (queue, dedup, timeout, crash + recovery, load failure, MT5 disconnect, stale data,
symbol mapping, M30, ledger + settlement from real closed bars), REQUIRED only after a positive walk-forward on real data, walk-forward
mechanics. The stub worker is a test double (kronos_stub_worker.py) - its numbers are not forecasts."""
from __future__ import annotations

import json
import os
import sys
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

import _env
from _env import TempData

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kronos_testkit as K  # noqa: E402
from masterquo.kronos import calendar as CAL  # noqa: E402
from masterquo.kronos import predictions as KP  # noqa: E402
from masterquo.kronos import quality as Q  # noqa: E402
from masterquo.modelhub import contract as C  # noqa: E402

POSIX = os.name != "nt"
FRI_2300_SERVER = datetime(2026, 10, 30, 21, 0, tzinfo=timezone.utc).timestamp()      # Friday 23:00 server (UTC+2)
WED_1200 = datetime(2026, 10, 28, 12, 0, 30, tzinfo=timezone.utc).timestamp()


class TestCalendar(unittest.TestCase):
    def test_24x7_future_is_contiguous(self):
        bars = K.make_bars(300, WED_1200, 10)
        cal = CAL.Calendar([b["t_raw"] for b in bars if b["closed"]], 300)
        last = [b for b in bars if b["closed"]][-1]["t_raw"]
        y, info = cal.future(last, 300, 12)
        self.assertEqual(info["status"], "OK")
        self.assertEqual(y, [last + 300 * (i + 1) for i in range(12)])
        self.assertFalse(info["crosses_break"])

    def test_gold_skips_daily_break_and_weekend(self):
        bars = K.make_bars(300, FRI_2300_SERVER, 14, session="XAU")
        closed = [b for b in bars if b["closed"]]
        last = closed[-1]["t_raw"]
        self.assertEqual(datetime.fromtimestamp(last, tz=timezone.utc).strftime("%a %H:%M"), "Fri 22:55")      # server time
        cal = CAL.Calendar([b["t_raw"] for b in closed], 300)
        y, info = cal.future(last, 300, 3)
        self.assertEqual(info["status"], "OK")
        self.assertTrue(info["crosses_break"])
        self.assertEqual([datetime.fromtimestamp(t, tz=timezone.utc).strftime("%a %H:%M") for t in y], ["Mon 00:00", "Mon 00:05", "Mon 00:10"])
        miss = cal.expected_missing([b["t_raw"] for b in closed], 300)
        self.assertEqual(miss["missing_open_slots"], 0)                       # weekends / daily breaks are not gaps

    def test_short_history_and_ambiguous_slot_suspend(self):
        bars = K.make_bars(300, WED_1200, 3)
        cal = CAL.Calendar([b["t_raw"] for b in bars if b["closed"]], 300)
        y, info = cal.future(bars[-2]["t_raw"], 300, 4)
        self.assertIsNone(y)
        self.assertEqual(info["status"], "CALENDAR_INSUFFICIENT")
        bars = [b for b in K.make_bars(300, WED_1200, 14) if b["closed"]]
        last = bars[-1]["t_raw"]
        slot = (last + 600) % 86400
        days = sorted({b["t_raw"] // 86400 for b in bars})
        drop = set(days[::2])                                                  # the next-but-one slot traded only on half of the days
        keep = [b["t_raw"] for b in bars if not (b["t_raw"] % 86400 == slot and b["t_raw"] // 86400 in drop) or b["t_raw"] == last]
        cal = CAL.Calendar(keep, 300)
        y, info = cal.future(last, 300, 5)
        self.assertIsNone(y)
        self.assertEqual(info["status"], "CALENDAR_UNCERTAIN")
        self.assertEqual(CAL.slot_seconds(60), 300)


class TestQuality(unittest.TestCase):
    def setUp(self):
        self.bars = K.make_bars(300, WED_1200, 10)
        self.cal = CAL.Calendar([b["t_raw"] for b in self.bars if b["closed"]], 300)

    def chk(self, bars, **kw):
        return Q.check(bars, 300, now_utc=kw.pop("now", WED_1200), lookback=400, min_context=128, calendar=self.cal, **kw)

    def test_clean_input_forming_excluded_tick_volume(self):
        q = self.chk(self.bars)
        self.assertEqual(q["status"], "OK", q["issues"])
        self.assertEqual(q["forming_excluded"], 1)
        self.assertTrue(all(b["closed"] for b in q["bars"]))
        self.assertEqual(q["volume_source"], "TICK_VOLUME")
        self.assertIn("NIE wolumen obrotu", q["volume_source_pl"])
        self.assertEqual(q["amount_source"], "SYNTHETIC_PROXY")

    def test_bad_ohlc_missing_value_and_conflicting_duplicate_block(self):
        b = [dict(x) for x in self.bars]
        b[-5]["h"] = b[-5]["l"] - 1
        self.assertEqual(self.chk(b)["status"], "BLOCK")
        b = [dict(x) for x in self.bars]
        b[-7]["c"] = None
        self.assertEqual(self.chk(b)["status"], "BLOCK")
        b = [dict(x) for x in self.bars]
        b.insert(-3, {**b[-4], "c": b[-4]["c"] + 5, "h": b[-4]["h"] + 5})
        self.assertEqual(self.chk(b)["status"], "BLOCK")
        b = [dict(x) for x in self.bars]
        b.insert(-3, dict(b[-4]))
        q = self.chk(b)
        self.assertEqual((q["status"], q["duplicates_dropped"]), ("OK", 1))

    def test_gaps_stale_warmup_and_volume_sources(self):
        b = [x for i, x in enumerate(self.bars) if not (len(self.bars) - 90 < i < len(self.bars) - 30)]
        self.assertEqual(self.chk(b)["status"], "BLOCK")                     # 59 missing open slots in the 400-bar window (>10 %)
        b = [x for i, x in enumerate(self.bars) if not (len(self.bars) - 40 < i < len(self.bars) - 20)]
        self.assertEqual(self.chk(b)["status"], "DEGRADED")                  # 19 missing (about 5 % of the window)
        self.assertEqual(self.chk(self.bars, now=WED_1200 + 3600)["status"], "STALE")
        self.assertEqual(self.chk(self.bars[-50:])["status"], "WARMUP")
        rv = [dict(x, rv=7) for x in self.bars]
        self.assertEqual(self.chk(rv)["volume_source"], "REAL_VOLUME")
        self.assertEqual(self.chk(self.bars, volume_setting="NONE")["volume_source"], "NONE")
        q = self.chk([dict(x, tv=0) for x in self.bars])
        self.assertEqual((q["volume_source"], q["status"]), ("NONE", "DEGRADED"))


class TestSettings(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_defaults_observe_and_validation(self):
        from masterquo.kronos.settings import KronosSettings, SettingsStore
        s = KronosSettings()
        self.assertEqual((s.timeframes, s.lookback, s.max_context), (["M5", "M15"], 400, 512))
        self.assertEqual({k: v.use for k, v in s.strategy_use.items()}, {"SCALPING": "OBSERVE", "HEDGING": "OBSERVE"})
        for bad in ({"paths": 1}, {"lookback": 600}, {"horizon_bars": {"M5": 0}}, {"unknown": 1}, {"timeframes": ["H4"]}):
            with self.assertRaises(Exception, msg=bad):
                KronosSettings.model_validate({**s.model_dump(mode="json"), **bad})
        p = Path(self.td.dir) / "kronos" / "settings.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('{"strategy_use": {"SCALPING": {"use": "MAYBE"}}}', encoding="utf-8")
        st = SettingsStore(p)
        self.assertIsNotNone(st.load_error)
        self.assertEqual(st.get().strategy_use["SCALPING"].use, "OBSERVE")       # a broken file never enables anything


def _ctx(direction="UP", available=True, use="REQUIRED", side="BUY"):
    fc = {"id": "x", "direction": direction, "direction_pl": direction, "delta_price": 1.0 if direction == "UP" else -1.0,
          "delta_pct": 0.1, "last_close": 1.0, "pred_close_h": 2.0, "horizon_bars": 12, "last_bar_open_utc": "t", "created_at": "t",
          "neutral_band": 0.1, "data_source": "x"} if available else None
    rel = "BRAK" if not available else ("NEUTRALNY" if direction == "FLAT" else ("ZGODNY" if (direction == "UP") == (side == "BUY") else "PRZECIWNY"))
    return {"model": "Kronos-small", "timeframe": "M5", "use": use, "use_pl": KP.USE_PL[use], "available": available, "state": "READY" if available else "ERROR",
            "reason": None if available else "brak prognozy", "forecast": fc, "setup_side": side, "relation": rel, "vs_models": [], "vs_structure": None,
            "knows_only": KP.KNOWS_ONLY, "independence": KP.INDEPENDENCE, "validation_report": None}


class TestStrategyGate(unittest.TestCase):
    def su(self, status="READY", side="BUY"):
        return {"status": status, "status_reason": "ok", "side": side, "checklist": [{"id": "plan", "status": "PASS"}]}

    def test_observe_never_changes_the_evaluation(self):
        for ctx in (_ctx("DOWN", use="OBSERVE"), _ctx(available=False, use="OBSERVE"), _ctx("FLAT", use="OBSERVE")):
            su = KP.apply_to_setup(self.su(), ctx)
            self.assertEqual((su["status"], su["status_reason"]), ("READY", "ok"))
            self.assertEqual(su["checklist"][-1]["status"], "INFO")
            self.assertIs(su["kronos"], ctx)

    def test_required_is_fail_closed_and_never_a_permission(self):
        self.assertEqual(KP.apply_to_setup(self.su(), _ctx(available=False))["status"], "WAIT")
        self.assertEqual(KP.apply_to_setup(self.su(), _ctx("FLAT"))["status"], "WAIT")
        self.assertEqual(KP.apply_to_setup(self.su(), _ctx("DOWN"))["status"], "WAIT")
        self.assertEqual(KP.apply_to_setup(self.su(side="SELL"), _ctx("UP", side="SELL"))["status"], "WAIT")
        ok = KP.apply_to_setup(self.su(), _ctx("UP"))
        self.assertEqual((ok["status"], ok["checklist"][-1]["status"]), ("READY", "PASS"))
        for st in ("WAIT", "NO_TRADE", "INVALIDATED"):                          # an agreeing forecast never creates a setup
            self.assertEqual(KP.apply_to_setup(self.su(status=st), _ctx("UP"))["status"], st)
        for d in ("masterquo/kronos", "kronos_runtime"):                           # no path from Kronos code to orders or positions
            for f in (_env.ROOT / "backend" / d).rglob("*.py"):
                t = f.read_text(encoding="utf-8")
                for word in ("order_send", "execution.gateway", "open_plan(", "positions_get", "MetaTrader5"):
                    self.assertNotIn(word, t, f"{f.name} references {word}")


@unittest.skipUnless(POSIX, "stub worker uses a POSIX shell script")
class TestServiceWithStub(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        os.environ["MQ_KRONOS_ALLOW_FIXTURE"] = "1"
        self.dir = Path(self.td.dir)
        self.now = [WED_1200]
        self.m5 = K.make_bars(300, WED_1200, 10)
        self.m15 = K.make_bars(900, WED_1200, 20)
        self.btc = K.make_bars(300, WED_1200, 10, price=64000.0)
        self.bridge = K.FakeBridge({("XAUUSD-", "M5"): self.m5, ("XAUUSD-", "M15"): self.m15, ("BTCUSD-", "M5"): self.btc,
                                    ("XAUUSD-", "M30"): K.make_bars(1800, WED_1200, 30)})
        self.cfg = K.FakeCfgStore(K.FakeCfg({"XAUUSD": K.FakeMapping("XAUUSD-"), "BTC": K.FakeMapping("BTCUSD-", "PROPOSED")}))

    def tearDown(self):
        os.environ.pop("MQ_KRONOS_ALLOW_FIXTURE", None)
        if getattr(self, "svc", None):
            self.svc.stop()
        self.td.close()

    def make(self, mode="ok", weights=True, **settings):
        from masterquo.db.database import Database
        from masterquo.kronos.service import KronosService
        from masterquo.kronos.settings import SettingsStore
        st = SettingsStore(self.dir / "kronos" / "settings.json")
        wd = self.dir / ("w" if weights else "w_empty")
        if weights:
            K.fixture_weights(wd)
        st.update({"python_path": K.stub_python(self.dir, mode) if mode else str(self.dir / "missing_python"), "weights_dir": str(wd),
                   "timeframes": ["M5"], "instruments": ["XAUUSD"], **settings})
        self.svc = KronosService(self.cfg, self.bridge, Database(self.dir / "t.sqlite"), K.Bus(), K.Log(), clock=lambda: self.now[0], settings=st)
        return self.svc

    def run_queue(self):
        out = []
        while self.svc.queue:
            k, job = self.svc.queue.popitem(last=False)
            out.append(self.svc.run_job(job))
        return out

    def test_not_installed_no_weights_and_no_terminal_reads(self):
        os.environ.pop("MQ_KRONOS_PYTHON", None)
        from unittest import mock
        svc = self.make(mode=None)
        with mock.patch("masterquo.kronos.service.find_python", return_value=None):   # independent of a real .venv_kronos on this machine
            svc.tick()
        self.assertEqual(svc.state["status"], "NOT_INSTALLED")
        self.assertEqual(self.bridge.calls, [])
        p = KP.contract_predictions(svc, "XAUUSD")[0]
        self.assertEqual((p["state"], p["result"]), ("DISABLED", None))
        svc.stop()
        svc = self.make(weights=False)
        svc.tick()
        self.assertEqual(svc.state["status"], "NO_WEIGHTS")
        self.assertEqual(self.bridge.calls, [])

    def test_forecast_contract_ledger_and_settlement(self):
        svc = self.make()
        svc.tick()
        self.assertEqual(svc.targets[("XAUUSD", "M5")]["state"], "QUEUED")
        fc = self.run_queue()[0]
        self.assertIsNotNone(fc, svc.targets)
        self.assertEqual(svc.state["status"], "READY")
        self.assertEqual((fc["mode"], fc["execution_permission"], fc["data_kind"]), ("SHADOW", False, "MT5_DEMO"))
        self.assertEqual(len(fc["pred"]), 12)
        self.assertEqual(fc["last_bar_open_utc"], [b for b in self.m5 if b["closed"]][-1]["open_utc"])        # forming bar never used
        self.assertEqual(fc["direction"], "UP")
        p = [x for x in KP.contract_predictions(svc, "XAUUSD") if x["timeframe"] == "M5"][0]
        C.validate(p)
        self.assertEqual((p["state"], p["task_type"], p["unit"], p["calibration"]["status"]), ("READY", "REGRESSION", "price", "NOT_APPLICABLE"))
        self.assertAlmostEqual(p["result"]["delta_price"], 1.2, places=6)
        self.assertEqual(svc.history("XAUUSD", "M5")[0]["outcome_status"], "PENDING")
        # 12 more real bars close -> the forecast is settled from them (and a new forecast is queued for the new last bar)
        self.now[0] = WED_1200 + 12 * 300
        more = K.make_bars(300, self.now[0], 10)
        self.bridge.bars_by[("XAUUSD-", "M5")] = more
        svc.targets[("XAUUSD", "M5")]["next_check"] = 0
        svc.tick()
        h = svc.history("XAUUSD", "M5")
        settled = [r for r in h if r["outcome_status"] == "SETTLED"]
        self.assertEqual(len(settled), 1)
        actual = {b["open_utc"]: b["c"] for b in more}[fc["pred"][-1]["t_utc"]]
        self.assertAlmostEqual(settled[0]["actual_close_h"], actual)
        self.assertAlmostEqual(settled[0]["abs_err_h"], abs(fc["pred_close_h"] - actual))
        self.assertAlmostEqual(settled[0]["naive_abs_err_h"], abs(fc["last_close"] - actual))
        sc = svc.scorecard("XAUUSD", "M5")
        self.assertEqual(sc["REAL"]["settled"], 1)
        self.assertEqual(sc["SYNTHETIC"]["settled"], 0)
        self.assertFalse(svc.forecast("XAUUSD", "M5")["is_current"])            # a new bar closed: the old forecast is not current

    def test_disconnect_stale_and_symbol_mapping(self):
        svc = self.make(instruments=["XAUUSD", "BTC"])
        svc.tick()
        self.run_queue()
        self.assertEqual(svc.targets[("BTC", "M5")]["state"], "NO_SYMBOL")
        self.assertIn("potwierdź", svc.targets[("BTC", "M5")]["reason"])
        self.assertFalse(any(c[0] == "BTCUSD-" for c in self.bridge.calls))      # never read a symbol the user did not confirm
        self.assertEqual([p["state"] for p in KP.contract_predictions(svc, "BTC")], ["DISABLED"])
        self.bridge.connected = False
        svc.tick()
        self.assertEqual(svc.targets[("XAUUSD", "M5")]["state"], "MT5_DISCONNECTED")
        p = KP.contract_predictions(svc, "XAUUSD")[0]
        self.assertEqual((p["state"], p["result"]), ("ERROR", None))
        self.assertIn("NIE jest aktualna", svc.forecast("XAUUSD", "M5")["stale_note"])
        self.bridge.connected = True
        self.now[0] = WED_1200 + 4 * 3600                                       # no new bars for hours (market closed / no ticks)
        svc.targets[("XAUUSD", "M5")]["next_check"] = 0
        svc.tick()
        self.assertEqual(svc.targets[("XAUUSD", "M5")]["state"], "STALE")
        self.assertFalse(svc.queue)

    def test_timeout_crash_recovery_and_load_failure(self):
        svc = self.make(mode="timeout", request_timeout_s=5.0)
        svc.tick()
        t0 = time.time()
        self.assertIsNone(self.run_queue()[0])
        self.assertLess(time.time() - t0, 20)
        self.assertIn("WORKER_TIMEOUT", svc.targets[("XAUUSD", "M5")]["reason"])
        self.assertEqual(svc.counters["timeouts"], 1)
        self.assertIsNone(svc.proc)                                            # killed, restarted on the next job
        svc.settings.update({"python_path": K.stub_python(self.dir, "crash")})
        svc.retry_at = 0
        svc.refresh("XAUUSD", "M5")
        self.assertIsNone(self.run_queue()[0])
        self.assertIn("WORKER_EXITED", svc.targets[("XAUUSD", "M5")]["reason"])
        svc.settings.update({"python_path": K.stub_python(self.dir, "ok")})       # recovery: next job works again
        svc.retry_at = 0
        svc.refresh("XAUUSD", "M5")
        self.assertIsNotNone(self.run_queue()[0])
        self.assertEqual(svc.state["status"], "READY")
        svc.stop()
        svc = self.make(mode="load_fail")
        svc.tick()
        self.run_queue()
        self.assertEqual((svc.state["status"], svc.state["code"]), ("ERROR", "CHECKSUM"))
        self.assertEqual(KP.contract_predictions(svc, "XAUUSD")[0]["state"], "INCOMPATIBLE")
        self.assertGreater(svc.retry_at, time.monotonic())                      # back-off, not a restart loop

    def test_queue_dedup_bound_and_m30(self):
        svc = self.make(timeframes=["M5", "M30"], queue_max=1)
        job = {"instrument": "XAUUSD", "timeframe": "M5", "symbol": "XAUUSD-", "bar_key": "a", "bars": [], "quality": {}, "calendar": None}
        self.assertTrue(svc.enqueue(job))
        self.assertTrue(svc.enqueue({**job, "bar_key": "b"}))
        self.assertEqual((len(svc.queue), svc.counters["deduplicated"], svc.queue[("XAUUSD", "M5")]["bar_key"]), (1, 1, "b"))
        self.assertFalse(svc.enqueue({**job, "timeframe": "M30"}))
        self.assertEqual(svc.counters["dropped_queue_full"], 1)
        svc.queue.clear()
        svc.settings.update({"queue_max": 8})
        svc.tick()
        fcs = [f for f in self.run_queue() if f]
        m30 = [f for f in fcs if f["timeframe"] == "M30"]
        self.assertEqual(len(m30), 1)
        steps = [datetime.fromisoformat(s["t_utc"].replace("Z", "+00:00")).timestamp() for s in m30[0]["pred"]]
        self.assertTrue(all(b - a == 1800 for a, b in zip(steps, steps[1:])))
        self.assertIn(("XAUUSD-", "M30", 460), self.bridge.calls)                 # M30 read natively through the bridge

    def test_required_needs_positive_real_validation_and_confirmation(self):
        from masterquo.kronos import validation as V
        svc = self.make()
        self.assertIn("CONFIRMATION_REQUIRED", svc.set_strategy_use("SCALPING", "REQUIRED")["reason"])
        self.assertIn("VALIDATION_REQUIRED", svc.set_strategy_use("SCALPING", "REQUIRED", confirm=True)["reason"])
        rep = {"report_id": "XAUUSD_M5_x", "instrument": "XAUUSD", "timeframe": "M5", "data_kind": "SYNTHETIC",
               "verdict": {"positive": False, "reason": "dane SYNTETYCZNE"}}
        (V.reports_dir() / "XAUUSD_M5_20260101T000000Z.json").write_text(json.dumps(rep), encoding="utf-8")
        r = svc.set_strategy_use("SCALPING", "REQUIRED", confirm=True)
        self.assertFalse(r["ok"])
        self.assertIn("SYNTETYCZNE", r["reason"])
        rep.update(report_id="XAUUSD_M5_y", data_kind="MT5_DEMO", verdict={"positive": True, "reason": "ok"})
        (V.reports_dir() / "XAUUSD_M5_20260102T000000Z.json").write_text(json.dumps(rep), encoding="utf-8")
        r = svc.set_strategy_use("SCALPING", "REQUIRED", confirm=True)          # 1.33: a report without a binding is stale
        self.assertFalse(r["ok"])
        self.assertIn("VALIDATION_STALE", r["reason"])
        rep.update(binding=V.binding(svc, "XAUUSD", "M5"), dev={"chosen_band_k": svc.settings.get().direction_band_atr})
        (V.reports_dir() / "XAUUSD_M5_20260102T000000Z.json").write_text(json.dumps(rep), encoding="utf-8")
        r = svc.set_strategy_use("SCALPING", "REQUIRED", confirm=True)
        self.assertTrue(r["ok"], r)
        self.assertEqual(svc.settings.get().strategy_use["SCALPING"].use, "REQUIRED")
        self.assertTrue(svc.set_strategy_use("SCALPING", "OBSERVE")["ok"])
        self.assertEqual(svc.settings.get().strategy_use["SCALPING"].use, "OBSERVE")


    def test_required_approval_invalid_after_binding_change(self):
        """1.33 (AUD 3.3): an approval is valid only for the exact symbol / horizon / settings / weights it was validated on."""
        from masterquo.kronos import validation as V
        svc = self.make()
        rep = {"report_id": "XAUUSD_M5_b", "instrument": "XAUUSD", "timeframe": "M5", "data_kind": "MT5_DEMO", "verdict": {"positive": True},
               "binding": V.binding(svc, "XAUUSD", "M5"), "dev": {"chosen_band_k": 0.5}}
        (V.reports_dir() / "XAUUSD_M5_20260103T000000Z.json").write_text(json.dumps(rep), encoding="utf-8")
        r = svc.set_strategy_use("SCALPING", "REQUIRED", confirm=True)        # validated band 0.5 != settings 0.25
        self.assertFalse(r["ok"])
        self.assertIn("pasmo neutralne", r["reason"])
        svc.settings.update({"direction_band_atr": 0.5})
        rep["binding"] = V.binding(svc, "XAUUSD", "M5")
        (V.reports_dir() / "XAUUSD_M5_20260103T000000Z.json").write_text(json.dumps(rep), encoding="utf-8")
        self.assertTrue(svc.set_strategy_use("SCALPING", "REQUIRED", confirm=True)["ok"])
        orig = KP._state
        KP._state = lambda _svc, _k: ("READY", None)
        try:
            svc.latest[("XAUUSD", "M5")] = {"id": "f1", "direction": "UP", "direction_pl": "wzrost", "delta_price": 1.0, "delta_pct": 0.04,
                                            "last_close": 2650.0, "pred_close_h": 2651.0, "horizon_bars": 12, "last_bar_open_utc": "x",
                                            "created_at": "x", "neutral_band": 0.2, "data_source": "MT5"}
            ok = KP.context(svc, "XAUUSD", "SCALPING", side="BUY")
            self.assertTrue(ok["available"], ok)
            svc.settings.update({"horizon_bars": {**svc.settings.get().horizon_bars, "M5": 6}})     # the approval no longer matches
            ctx = KP.context(svc, "XAUUSD", "SCALPING", side="BUY")
            self.assertFalse(ctx["available"])
            self.assertEqual(ctx["state"], "STALE_APPROVAL")
            su = KP.apply_to_setup({"status": "READY", "side": "BUY"}, ctx)
            self.assertEqual(su["status"], "WAIT")                                     # REQUIRED may only hold the setup
        finally:
            KP._state = orig


class _InProcStub:
    """Test double of the worker for the walk-forward mechanics: forecast = last close (no model)."""
    def ask(self, req, timeout):
        if req["cmd"] == "load":
            return {"ok": True, "info": {"device": "cpu"}}
        if req["cmd"] == "predict":
            last = req["candles"]["close"][-1]
            return {"ok": True, "pred": {"close": [last + 0.01] * req["pred_len"]}, "ms": 1.0}
        return {"ok": True}

    def close(self):
        pass


class TestValidation(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_walk_forward_split_and_synthetic_never_positive(self):
        from masterquo.db.database import Database
        from masterquo.kronos import validation as V
        from masterquo.kronos.service import KronosService
        from masterquo.kronos.settings import SettingsStore
        self.assertAlmostEqual(V.binom_p_greater(60, 100), 0.0284, places=3)
        bars = K.make_bars(300, WED_1200, 20)
        br = K.FakeBridge({("XAUUSD-", "M5"): bars}, synthetic=True)
        st = SettingsStore(Path(self.td.dir) / "kronos" / "settings.json")
        svc = KronosService(K.FakeCfgStore(K.FakeCfg({"XAUUSD": K.FakeMapping("XAUUSD-")})), br, Database(Path(self.td.dir) / "t.sqlite"), K.Bus(),
                            K.Log(), settings=st)
        rep = V.run(svc, "XAUUSD", "M5", max_origins=60, client_factory=_InProcStub)
        self.assertEqual(rep["status"], "DONE")
        self.assertFalse(rep["verdict"]["positive"])
        self.assertIn("SYNTETYCZNE", rep["verdict"]["reason"])
        rows = rep["rows"]
        dev = [r["t"] for r in rows if r["split"] == "DEV"]
        test = [r["t"] for r in rows if r["split"] == "TEST"]
        self.assertTrue(dev and test and max(dev) < min(test))                     # chronological, test strictly after dev
        ts = [datetime.fromisoformat(r["t"].replace("Z", "+00:00")).timestamp() for r in rows]
        self.assertTrue(all(b - a >= 12 * 300 for a, b in zip(ts, ts[1:])))         # horizons never overlap
        self.assertIsNotNone(rep["test"]["mae_kronos"])
        self.assertIsNotNone(rep["test"]["mae_naive_last_price"])
        self.assertIn("pretreningu", rep["caveat"])
        self.assertEqual(V.latest_report("XAUUSD", "M5")["report_id"], rep["report_id"])


if __name__ == "__main__":
    unittest.main()
