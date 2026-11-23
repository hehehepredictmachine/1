"""1.46 audit, group B_analytics_2 - regression tests (SYNTHETIC_TEST data only).

chunk_02#8   analytics-heavy worker survives an exception from publish/summary; views iterate copies of the shared state
chunk_02#9 / focus_X4#6  candle countdown anchored on the broker SERVER clock (H4/H8/D1), not on the UTC grid
focus_X4#5   expected session slots follow the bar grid, not the window start (LAB_XAU NEW_YORK 08:20 on M15)
chunk_02#1   FFT: UNSTABLE_DOMINANT_PERIOD is set (np.bool_ vs `is False`), lagged window uses the same peak rule
chunk_02#14  ma_analysis 'crosses' = the 10 most recent crosses, chronological
chunk_02#19  dead helper signal._round_list removed
"""
from __future__ import annotations

import math
import sys
import threading
import time
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

import _env  # noqa: F401

sys.path.insert(0, str(Path(__file__).resolve().parent / "analytics"))

import fixtures as F
import numpy as np


def _wait(pred, timeout):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.05)
    return False


# ---------------------------------------------------------------------------------------------------------- chunk_02#8
class _Cfg:
    def get(self):
        from masterquo.config import AppConfig
        c = AppConfig()
        c.analytics.timeframes = ["M5", "H1"]
        c.analytics.signal_timeframes = ["M5"]
        return c


class _NoDb:
    def execute(self, *a, **k):
        return None


def _bare_service(bus=None):
    """AnalyticsService without the DB-backed pattern library (only the state / worker / views are exercised)."""
    from masterquo.analytics.service import AnalyticsService
    svc = AnalyticsService.__new__(AnalyticsService)
    svc.cfg_store, svc.bridge, svc.db, svc.bus, svc.log = _Cfg(), None, _NoDb(), bus, None
    svc.state, svc.keys, svc.pending = {}, {}, {}
    svc._cv, svc._stop = threading.Condition(), threading.Event()
    svc.lat, svc.errors, svc.cache = {}, [], {}
    svc.counters = {"computed": 0, "discarded_stale": 0, "cache_hits": 0, "timeouts": 0}
    return svc


class TestAnalyticsWorkerAndViews(unittest.TestCase):
    def test_worker_survives_publish_error(self):
        """A RuntimeError from summary()/publish (e.g. 'dictionary changed size during iteration') ended the analytics-heavy thread
        silently: no error entry, FFT/EMD/VMD never computed again until restart."""
        published: list[int] = []

        class Bus:
            def publish(self, topic, payload):
                published.append(1)
                if len(published) == 1:
                    raise RuntimeError("dictionary changed size during iteration")

        svc = _bare_service(Bus())
        bars1 = F.from_path([2000.0 + math.sin(i / 3) for i in range(40)])       # short window: modules answer WARMUP instantly
        bars2 = F.from_path([2000.0 + math.sin(i / 3) for i in range(41)])
        cfg = {"window": 256, "min_window": 128}
        svc.keys["M5"] = "k1"
        svc.pending["M5"] = ("k1", bars1, "XAUUSD", cfg, 10.0)
        th = threading.Thread(target=svc._worker, daemon=True)
        th.start()
        try:
            self.assertTrue(_wait(lambda: len(published) >= 1, 60))
            time.sleep(0.2)
            with svc._cv:                                                         # the next closed bar arrives
                svc.keys["M5"] = "k2"
                svc.pending["M5"] = ("k2", bars2, "XAUUSD", cfg, 10.0)
                svc._cv.notify()
            self.assertTrue(_wait(lambda: len(published) >= 2, 30), "worker thread died after the publish error")
            self.assertTrue(th.is_alive())
            self.assertEqual(svc.state["M5"]["fft"]["samples"], 41)
            self.assertTrue(any("dictionary changed size" in e["error"] for e in svc.errors), svc.errors)
        finally:
            svc._stop.set()
            with svc._cv:
                svc._cv.notify_all()
            th.join(5)

    def test_views_iterate_copies_of_shared_state(self):
        """support()/tf_state() iterated the live dicts the tick / worker threads mutate. The interleaving is simulated
        deterministically: reading a value adds a key to the dict being iterated (what the other thread does at that moment)."""
        svc = _bare_service()

        class TfState(dict):                                                     # per-TF dict: reading status = tick adds a TF
            def get(self, k, d=None):
                if k == "status":
                    svc.state.setdefault(f"T{len(svc.state)}", {})
                return super().get(k, d)

        tf_st: dict = {}

        class Result(dict):                                                      # module result: reading it = worker adds a module
            def get(self, k, d=None):
                if k == "values":
                    tf_st.setdefault(f"mod{len(tf_st)}", "x")
                return super().get(k, d)

        tf_st.update(status="ready", extra_module=Result(values={"a": 1}))
        svc.state["M5"] = tf_st
        svc.state["H1"] = TfState(status="stale")
        s = svc.summary()                                                         # tf_state() for M5/H1 + support()
        self.assertIn("M5", s["timeframes"])
        self.assertIn("H1", s["support"]["groups"][-1]["detail"])
        self.assertIsInstance(svc.diagnostics()["keys"], dict)


# ---------------------------------------------------------------------------------------------------------- chunk_02#9 / focus_X4#6
class TestCandleServerClock(unittest.TestCase):
    AS_OF = datetime(2026, 11, 23, 21, 30, tzinfo=UTC)

    def test_d1_h4_anchored_on_verified_server_offset(self):
        from masterquo.analytics import session_context as SC
        d1 = SC.candle("D1", self.AS_OF, server_offset_seconds=7200)               # server UTC+2: D1 opens at 22:00 UTC
        self.assertEqual((d1["open_utc"], d1["close_utc"], d1["seconds_remaining"]), ("2026-11-22T22:00:00Z", "2026-11-23T22:00:00Z", 1800))
        h4 = SC.candle("H4", self.AS_OF, server_offset_seconds=7200)
        self.assertEqual((h4["open_utc"], h4["close_utc"]), ("2026-11-23T18:00:00Z", "2026-11-23T22:00:00Z"))
        self.assertEqual(h4["time_basis"], "BROKER_SERVER_CLOCK_VERIFIED")
        m15 = SC.candle("M15", self.AS_OF, server_offset_seconds=7200)               # whole-hour offset: same grid as before
        self.assertEqual((m15["open_utc"], m15["seconds_remaining"]), ("2026-11-23T21:30:00Z", 900))

    def test_last_mt5_bar_anchors_without_verified_offset(self):
        from masterquo.analytics import session_context as SC
        h4 = SC.candle("H4", self.AS_OF, last_bar_open_utc=datetime(2026, 11, 23, 18, 0, tzinfo=UTC))
        self.assertEqual((h4["open_utc"], h4["close_utc"], h4["seconds_remaining"]), ("2026-11-23T18:00:00Z", "2026-11-23T22:00:00Z", 1800))

    def test_no_server_time_evidence_is_flagged_for_h4_h8_d1(self):
        from masterquo.analytics import session_context as SC
        for tf in ("H4", "H8", "D1"):
            self.assertEqual(SC.candle(tf, self.AS_OF)["quality"], "TIME_MAPPING_UNVERIFIED", tf)
        self.assertEqual(SC.candle("M5", self.AS_OF)["quality"], "CONFIGURED_UNVERIFIED")

    def test_snapshot_uses_only_verified_clock_evidence(self):
        from masterquo.analytics import session_context as SC
        ok = SC.snapshot(instrument="X", timeframe="D1", as_of=self.AS_OF, clock_evidence={"status": "VERIFIED", "offset_seconds": 7200})
        self.assertEqual(ok["candle"]["close_utc"], "2026-11-23T22:00:00Z")
        unv = SC.snapshot(instrument="X", timeframe="D1", as_of=self.AS_OF, clock_evidence={"status": "STORED_UNVERIFIED", "offset_seconds": 7200})
        self.assertEqual(unv["candle"]["quality"], "TIME_MAPPING_UNVERIFIED")


# ---------------------------------------------------------------------------------------------------------- focus_X4#5
class TestSessionSlotsOnBarGrid(unittest.TestCase):
    @staticmethod
    def _m15(t0, n):
        return [{"open_utc": (t0 + timedelta(minutes=15 * k)).isoformat(), "h": 2001.0 + (k % 7), "l": 1999.0 - (k % 5), "c": 2000.0}
                for k in range(n)]

    def test_ny_0820_box_final_on_m15(self):
        from masterquo.analytics import session_engine as SE
        t0 = datetime(2026, 11, 23, 0, 0, tzinfo=UTC)
        boxes = SE.build(self._m15(t0, 96), 900, "LAB_XAU_REFERENCE_V1", "XAUUSD", t0 + timedelta(days=1), days=0)
        ny = [b for b in boxes if b["session"] == "NEW_YORK"][-1]                 # 08:20-13:30 New York = 13:20-18:30 UTC
        self.assertEqual((ny["state"], ny["expected_slots"], ny["observed_slots"], ny["missing_slots"]), ("FINAL", 20, 20, 0))
        self.assertEqual(ny["coverage_ratio"], 1.0)
        self.assertIsNotNone(ny["final_high"])
        hole = [b for b in self._m15(t0, 96) if not b["open_utc"].startswith("2026-11-23T14:30")]
        ny2 = [b for b in SE.build(hole, 900, "LAB_XAU_REFERENCE_V1", "XAUUSD", t0 + timedelta(days=1), days=0) if b["session"] == "NEW_YORK"][-1]
        self.assertEqual((ny2["state"], ny2["missing_slots"]), ("INCOMPLETE", 1))  # a real gap is still reported

    def test_on_grid_start_unchanged(self):
        from masterquo.analytics import session_engine as SE
        t0 = datetime(2026, 1, 15, 8, 0, tzinfo=UTC)
        bars = [{"open_utc": (t0 + timedelta(minutes=5 * k)).isoformat(), "h": 101.0, "l": 99.0, "c": 100.0} for k in range(48)]
        b = [x for x in SE.build(bars, 300, "SCALP_OPENING_V1", "XAUUSD", datetime(2026, 1, 15, 12, 5, tzinfo=UTC), days=0)
             if x["session"] == "LONDON"][-1]
        self.assertEqual((b["state"], b["expected_slots"], b["observed_slots"]), ("FINAL", 48, 48))


# ---------------------------------------------------------------------------------------------------------- chunk_02#1
class TestFftStability(unittest.TestCase):
    def test_unstable_dominant_period_flagged(self):
        """The lagged window's dominant is far from the current one -> UNSTABLE_DOMINANT_PERIOD, quality_ok False."""
        from masterquo.analytics import signal as SG
        orig = SG.periodogram
        n_full = []

        def fake(x, detrend, window="hann"):
            f = np.linspace(0, 0.5, 129)
            p = np.ones_like(f)
            if not n_full:
                n_full.append(len(x))
            p[10 if len(x) == n_full[0] else 40] = 100.0                         # full window: period 25.6; lagged: period 6.4
            return f, p
        try:
            SG.periodogram = fake
            r = SG.fft_analysis(F.from_path([2000.0 + math.sin(i / 3) for i in range(300)]), "M5")
        finally:
            SG.periodogram = orig
        self.assertFalse(r["values"]["dominant_stable"])
        self.assertIn("UNSTABLE_DOMINANT_PERIOD", r["quality_flags"])
        self.assertFalse(r["values"]["quality_ok"])

    def test_lagged_window_uses_same_peak_rule(self):
        """A bar-to-bar alternation puts the global maximum of the lagged spectrum on the Nyquist edge bin; the current dominant
        is a local peak (edge bins excluded) - the lagged one must use the same rule, or every such series is 'unstable'."""
        from masterquo.analytics import signal as SG
        rng = np.random.default_rng(1)
        p = [2000.0]
        for i in range(300):
            p.append(p[-1] * math.exp(0.002 * math.sin(2 * math.pi * i / 20) + (0.003 if i % 2 else -0.003) + rng.normal(0, 0.0005)))
        r = SG.fft_analysis(F.from_path(p), "M5")
        self.assertAlmostEqual(r["values"]["dominant"][0]["period_bars"], 20, delta=1.5)
        self.assertIs(r["values"]["dominant_stable"], True)
        self.assertNotIn("UNSTABLE_DOMINANT_PERIOD", r["quality_flags"])


# ---------------------------------------------------------------------------------------------------------- chunk_02#14
class TestMaCrossesRecent(unittest.TestCase):
    def test_crosses_are_the_most_recent_chronological(self):
        from masterquo.analytics import ta
        prices = [2000.0 + 0.02 * i + 3.0 * math.sin(i / 25) + 0.8 * math.sin(i * 1.3) for i in range(300)]
        bars = F.from_path(prices)
        mas = [{"id": "EMA3", "type": "EMA", "period": 3}, {"id": "EMA5", "type": "EMA", "period": 5},
               {"id": "SMA30", "type": "SMA", "period": 30}, {"id": "SMA40", "type": "SMA", "period": 40}]
        r = ta.ma_analysis(bars, mas, tf="M5")
        cr = r["values"]["crosses"]
        times = [e["bar_open_utc"] for e in cr]
        self.assertEqual(times, sorted(times))                                    # chronological
        e3, e5 = ta.ema([b["c"] for b in bars], 3), ta.ema([b["c"] for b in bars], 5)
        d = [a - b for a, b in zip(e3[4:], e5[4:])]
        last_fast = 4 + max(j for j in range(1, len(d)) if d[j - 1] <= 0 < d[j] or d[j - 1] >= 0 > d[j])
        self.assertIn(bars[last_fast]["open_utc"], times)                         # the newest EMA3/EMA5 cross is kept
        self.assertEqual(len(cr), 10)


# ---------------------------------------------------------------------------------------------------------- chunk_02#19
class TestDeadCode(unittest.TestCase):
    def test_round_list_removed(self):
        from masterquo.analytics import signal as SG
        self.assertFalse(hasattr(SG, "_round_list"))


if __name__ == "__main__":
    unittest.main()
