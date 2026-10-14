"""1.11 - gold_candles integration on the bot side (bot venv, no pandas): Double Retest v2 research state machine,
forecast config (SHADOW only, no execution switches), service without the candle environment, history export on the
simulated terminal (clearly SYNTHETIC_TEST), shadow scoring. No real account, no order, no notification."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import _env
from _env import TempData

T0 = datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)          # Tuesday


def iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def m30_bars(mirror: float | None = None):
    rows = []
    for i in range(54):
        b = 4084 + i
        rows.append((b - .3, b + 1, b - 1, b + .3))
    rows += [(4140.5, 4142, 4140.6, 4141.5), (4141.5, 4142.5, 4140.7, 4141.8), (4141.8, 4142.2, 4140.05, 4141.0),
             (4141.0, 4143, 4140.8, 4142.5), (4142.5, 4143.5, 4141.0, 4143.0), (4143, 4144, 4141, 4143.2)]
    out = []
    for i, (o, h, l, c) in enumerate(rows):
        if mirror:
            o, h, l, c = mirror - o, mirror - l, mirror - h, mirror - c
        out.append({"open_utc": iso(T0 + timedelta(minutes=30 * i)), "o": o, "h": h, "l": l, "c": c, "tv": 100})
    return out


SEQ = [(4143, 4146, 4140, 4143)] * 14 + [
    (4143, 4144, 4134.6, 4135.5),      # 14 contact with the deep zone 4132.5-4135
    (4135.5, 4138, 4134.8, 4137),      # 15 close > zone+bounce -> episode 1
    (4137, 4140, 4136, 4139),          # 16 reset 1
    (4139, 4141, 4137, 4138),          # 17 reset 2
    (4138, 4138.5, 4134.7, 4135.2),    # 18 new contact
    (4135.2, 4141, 4135, 4140.6),      # 19 episode 2 + reclaim of L=4140 in the same closed bar
    (4140.6, 4141.5, 4140.1, 4141),    # 20 retest of L, trigger candle
    (4141, 4142, 4140.8, 4141.5)]      # 21


def m5_bars(seq=SEQ, mirror: float | None = None, skip: int | None = None):
    start = T0 + timedelta(minutes=30 * 60)
    out = []
    for i, (o, h, l, c) in enumerate(seq):
        if i == skip:
            continue
        if mirror:
            o, h, l, c = mirror - o, mirror - l, mirror - h, mirror - c
        out.append({"open_utc": iso(start + timedelta(minutes=5 * i)), "o": o, "h": h, "l": l, "c": c, "tv": 50})
    return out


def flags_at(i: int, names: list[str]):
    return {iso(T0 + timedelta(minutes=30 * 60 + 5 * i)): names}


class TestDoubleRetest(unittest.TestCase):
    def run_dr(self, m5, m30, flags):
        from masterquo.forecast.double_retest import DoubleRetest
        return DoubleRetest().update(m5, m30, flags, 0.01)

    def test_buy_full_sequence_is_research_only(self):
        r = self.run_dr(m5_bars(), m30_bars(), flags_at(20, ["lower_wick_rejection"]))
        done = r["states"]["BUY"]["recent"]
        self.assertTrue(done, r["states"]["BUY"])
        s = done[0]
        self.assertEqual((s["state"], s["L"], s["trigger"]["family"], len(s["episodes"])), ("RESEARCH_SETUP_COMPLETE", 4140, "REJECTION", 2))
        self.assertEqual(s["deep_zone"], [4132.5, 4135.0])
        self.assertEqual(s["targets_hypothetical"], [4145, 4150])
        self.assertEqual((r["EXECUTION_STATE"], r["can_submit_order"]), ("BLOCKED", False))
        self.assertNotIn("READY", json.dumps(r))
        self.assertEqual(r["states"]["SELL"]["recent"], [])                    # no BUY does not create a SELL

    def test_sell_is_the_exact_mirror(self):
        mir = 8280.0
        r = self.run_dr(m5_bars(mirror=mir), m30_bars(mirror=mir), flags_at(20, ["upper_wick_rejection"]))
        s = r["states"]["SELL"]["recent"][0]
        self.assertEqual((s["state"], s["L"], s["direction"]), ("RESEARCH_SETUP_COMPLETE", 4140, "SELL"))
        self.assertEqual(s["deep_zone"], [4145.0, 4147.5])
        self.assertEqual(s["targets_hypothetical"], [4135, 4130])
        self.assertEqual(r["states"]["BUY"]["recent"], [])

    def test_deterministic_and_future_bars_do_not_rewrite_history(self):
        a = self.run_dr(m5_bars(), m30_bars(), flags_at(20, ["lower_wick_rejection"]))
        b = self.run_dr(m5_bars(), m30_bars(), flags_at(20, ["lower_wick_rejection"]))
        self.assertEqual(a, b)                                                  # restart / reload: same setups, no duplicates
        longer = SEQ + [(4141.5, 4143, 4141, 4142)] * 6
        c = self.run_dr(m5_bars(longer), m30_bars(), flags_at(20, ["lower_wick_rejection"]))
        done = [x for x in c["states"]["BUY"]["recent"] if x["setup_id"] == a["states"]["BUY"]["recent"][0]["setup_id"]]
        self.assertEqual(done[0], a["states"]["BUY"]["recent"][0])

    def test_no_trigger_candle_ends_the_window(self):
        r = self.run_dr(m5_bars(), m30_bars(), {})                            # same bars, no pattern family on the retest
        s = r["states"]["BUY"]["recent"][0]
        self.assertEqual(s["state"], "INVALIDATED")
        self.assertIn("2 M5", s["end_reason"])

    def test_gap_and_deep_probe_invalidate(self):
        r = self.run_dr(m5_bars(skip=16), m30_bars(), flags_at(20, ["lower_wick_rejection"]))
        self.assertIn("DATA_GAP", r["states"]["BUY"]["recent"][0]["end_reason"])
        seq = list(SEQ)
        seq[14] = (4143, 4144, 4130.5, 4133.0)                                  # wick below zone - probe allowance
        r = self.run_dr(m5_bars(seq), m30_bars(), flags_at(20, ["lower_wick_rejection"]))
        self.assertEqual(r["states"]["BUY"]["recent"][0]["state"], "INVALIDATED")

    def test_continuation_family_and_doji_is_not_a_trigger(self):
        r = self.run_dr(m5_bars(), m30_bars(), flags_at(20, ["bullish_engulfing"]))
        self.assertEqual(r["states"]["BUY"]["recent"][0]["trigger"]["family"], "CONTINUATION")
        r = self.run_dr(m5_bars(), m30_bars(), flags_at(20, ["doji", "inside_bar", "nr4"]))
        self.assertEqual(r["states"]["BUY"]["recent"][0]["state"], "INVALIDATED")


class TestForecastConfigAndService(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self._py = os.environ.get("MQ_CANDLES_PYTHON")

    def tearDown(self):
        if self._py is None:
            os.environ.pop("MQ_CANDLES_PYTHON", None)
        else:
            os.environ["MQ_CANDLES_PYTHON"] = self._py          # the runner still needs it for the candle suite
        self.td.close()

    def test_config_is_shadow_only(self):
        from pydantic import ValidationError
        from masterquo.config import ForecastConfig
        c = ForecastConfig()
        self.assertEqual((c.mode, c.ml_execution, c.module_order_permission), ("SHADOW", False, False))
        for bad in ({"mode": "LIVE"}, {"ml_execution": True}, {"module_order_permission": True}):
            with self.assertRaises(ValidationError):
                ForecastConfig(**bad)

    def test_missing_candle_env_is_a_status_not_a_crash(self):
        cfg, db, bus, log, fake, worker, bridge = _env.core()
        try:
            db.migrate()
            from masterquo.forecast import service as fs
            os.environ["MQ_CANDLES_PYTHON"] = "/nonexistent/python"
            svc = fs.ForecastService(cfg, bridge, db, bus, log)
            orig = fs.candle_python
            fs.candle_python = lambda c: None
            try:
                bridge.connect()
                bridge.poll(0.0) if hasattr(bridge, "poll") else None
                svc.tick()
            finally:
                fs.candle_python = orig
            self.assertIn(svc.state["status"], ("NO_CANDLE_ENV", "NO_DATA"))
            self.assertFalse(svc.state["execution_permission"])
            self.assertEqual(db.query("SELECT * FROM order_attempts") if db.one("SELECT name FROM sqlite_master WHERE name='order_attempts'") else [], [])
        finally:
            worker.stop()

    def test_shadow_scoring_uses_exact_continuous_target(self):
        cfg, db, bus, log, fake, worker, bridge = _env.core()
        try:
            db.migrate()
            from masterquo.forecast.service import ForecastService
            svc = ForecastService(cfg, bridge, db, bus, log)
            ft = T0 + timedelta(hours=10)
            for h, p in ((5, (0.1, 0.2, 0.7)), (15, (0.6, 0.3, 0.1))):
                db.execute("""INSERT INTO forecast_shadow(created_at, run_id, feature_time_utc, horizon_minutes, target_time_utc, close_now, neutral_band,
                              p_down, p_flat, p_up, q10, q50, q90, outcome_status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, 'PENDING')""",
                           (iso(ft), "R1", iso(ft), h, iso(ft + timedelta(minutes=h)), 4000.0, 0.5, *p, 3998.0, 4000.0, 4002.0))
            bars = [{"open_utc": iso(ft - timedelta(minutes=5)), "c": 4000.0}, {"open_utc": iso(ft), "c": 4001.0}]   # only +5 min known
            svc.score_due(bars)
            rows = {r["horizon_minutes"]: r for r in db.query("SELECT * FROM forecast_shadow")}
            self.assertEqual((rows[5]["outcome_status"], rows[5]["outcome_class"], rows[5]["outcome_close"]), ("SCORED", "UP", 4001.0))
            self.assertEqual(rows[15]["outcome_status"], "PENDING")             # target not reached yet: never guessed
            bars += [{"open_utc": iso(ft + timedelta(minutes=10)), "c": 3999.0}]  # +10 min missing -> not continuous
            svc.score_due(bars)
            self.assertEqual(db.one("SELECT outcome_status FROM forecast_shadow WHERE horizon_minutes=15")["outcome_status"], "NO_CONTINUOUS_DATA")
            s = svc.shadow_summary()
            self.assertEqual(s["5"]["scored"], 1)
            self.assertAlmostEqual(s["5"]["brier"], round(0.1 ** 2 + 0.2 ** 2 + 0.3 ** 2, 4))
        finally:
            worker.stop()


class TestCandleExport(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        sys.modules.pop("MetaTrader5", None)
        self.td.close()

    def test_export_on_simulator_is_marked_synthetic_and_checked(self):
        from masterquo.mt5.fake import FakeMT5
        fake = FakeMT5()
        orig = fake.copy_rates_range
        state = {"n": 0}

        def broken(*a):                                                          # one bar with impossible geometry
            r = orig(*a)
            if r is not None and len(r) and state["n"] == 0:
                r = r.copy()
                r["high"][len(r) // 2] = r["low"][len(r) // 2] - 1
                state["n"] += 1
            return r
        fake.copy_rates_range = broken
        sys.modules["MetaTrader5"] = fake
        from masterquo.forecast.export import export_candles
        out = tempfile.mkdtemp(prefix="mq_candles_")
        self.assertEqual(export_candles(2, out), 0)
        meta = json.loads(Path(out, "source_metadata.json").read_text(encoding="utf-8"))
        dq = json.loads(Path(out, "DATA_QUALITY_REPORT.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["data_kind"], "SYNTHETIC_TEST")                    # simulator data is never REAL_USER_DATA
        self.assertEqual((meta["symbol"], meta["m30_source"], meta["time_basis"]), ("XAUUSD-", "BROKER_M30", "SERVER_TIME_CONVERTED_TO_UTC"))
        self.assertGreater(meta["tick_size"], 0)
        self.assertGreaterEqual(dq["timeframes"]["M5"]["invalid_geometry_count"] + dq["timeframes"]["M30"]["invalid_geometry_count"], 1)
        self.assertEqual(dq["timeframes"]["M5"]["conflicting_revisions_count"], 0)
        head = Path(out, "XAUUSD_M5.csv").read_text(encoding="utf-8").splitlines()
        self.assertTrue(head[0].startswith("time_open_utc,open,high,low,close,tick_volume,symbol"))
        last = datetime.fromisoformat(head[-1].split(",")[0].replace("Z", "+00:00"))
        self.assertLessEqual(last + timedelta(minutes=5), datetime.fromisoformat(meta["cutoff_utc"].replace("Z", "+00:00")))   # closed bars only
        self.assertTrue(fake.connected is False or not getattr(fake, "connected", False))               # own connection closed


if __name__ == "__main__":
    unittest.main()
