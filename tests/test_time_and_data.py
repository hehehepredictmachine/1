"""Time contract, data quality, symbol handling, history requirements."""
import unittest
from datetime import datetime, timedelta

import _env  # noqa: F401
from _env import UTC, TempData


class TestClock(unittest.TestCase):
    def test_offset_measured_and_verified(self):
        from masterquo.mt5.clock import ServerClock
        c = ServerClock()
        now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
        for i in range(6):
            t = now + timedelta(seconds=i)
            c.observe_tick(int((t.timestamp() + 3 * 3600 - 0.4) * 1000), t)
        self.assertEqual(c.evidence.status, "VERIFIED")
        self.assertEqual(c.offset, 10800)
        self.assertEqual(c.raw_to_utc(now.timestamp() + 10800), now)

    def test_misaligned_delta_is_inconsistent_not_rounded_blindly(self):
        from masterquo.mt5.clock import ServerClock
        c = ServerClock()
        now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
        for i in range(6):  # PC clock wrong by 7 minutes -> not on a 15 min grid
            t = now + timedelta(seconds=i)
            c.observe_tick(int((t.timestamp() + 3 * 3600 + 420) * 1000), t)
        self.assertEqual(c.evidence.status, "INCONSISTENT")
        self.assertIn("DELTA_NOT_ALIGNED_TO_TIMEZONE_GRID_CHECK_PC_CLOCK", c.evidence.reasons)

    def test_stale_repeated_tick_does_not_count(self):
        from masterquo.mt5.clock import ServerClock
        c = ServerClock()
        now = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)  # weekend: same tick repeated
        for i in range(20):
            c.observe_tick(1_791_000_000_000, now + timedelta(seconds=i))
        self.assertNotEqual(c.evidence.status, "VERIFIED")
        self.assertLessEqual(c.evidence.samples, 1)

    def test_dst_change_detected(self):
        from masterquo.mt5.clock import ServerClock
        c = ServerClock(window=5)
        now = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
        for i in range(6):
            t = now + timedelta(seconds=i)
            c.observe_tick(int((t.timestamp() + 3 * 3600) * 1000), t)
        for i in range(6, 12):
            t = now + timedelta(seconds=i)
            c.observe_tick(int((t.timestamp() + 2 * 3600) * 1000), t)
        # the newest window holds only +2h samples
        self.assertEqual(c.offset, 7200)
        self.assertEqual(c.changes[-1]["from"], 10800)
        self.assertEqual(c.changes[-1]["to"], 7200)

    def test_epoch_seconds_vs_milliseconds(self):
        from masterquo.timeutil import epoch_seconds, from_epoch
        self.assertEqual(epoch_seconds(1_791_000_000), 1_791_000_000.0)
        with self.assertRaises(ValueError):
            epoch_seconds(1_791_000_000_000)
        self.assertEqual(from_epoch(0).year, 1970)


class TestQuality(unittest.TestCase):
    def _bars(self, start_raw, n, step=60, skip=()):
        out = []
        t = start_raw
        i = 0
        while len(out) < n:
            if i not in skip:
                out.append({"t_raw": t, "o": 2000.0, "h": 2001.0, "l": 1999.0, "c": 2000.5, "tv": 5, "closed": True})
            t += step
            i += 1
        out[-1]["closed"] = False
        return out

    def _assess(self, bars_m1, offset=10800, now=None, quote_age=0.5):
        from masterquo.data.quality import assess
        now = now or datetime.fromtimestamp(bars_m1[-1]["t_raw"] - offset + 30, UTC)
        bars = {tf: bars_m1 for tf in ("M1", "M5", "M15", "H1", "H4", "D1")}
        clock = {"status": "VERIFIED", "offset_seconds": offset}
        q = {"bid": 1, "ask": 1.1, "age_seconds": quote_age, "source_age_seconds": quote_age}
        return assess(symbol="XAUUSD-", bars_by_tf={"M1": bars_m1, **{k: v for k, v in bars.items() if k != "M1"}},
                      required={"M1": 10}, quote=q, clock=clock, connection_state="CONNECTED", now=now, max_quote_age=10,
                      symbol_status="OK")

    def test_good_data(self):
        start = int(datetime(2026, 10, 7, 9, 0, tzinfo=UTC).timestamp())
        r = self._assess(self._bars(start, 50))
        self.assertTrue(r["analysis_allowed"])
        self.assertEqual(r["timeframes"]["M1"]["status"], "OK")

    def test_future_bar_with_wrong_offset_blocks(self):
        start = int(datetime(2026, 10, 7, 9, 0, tzinfo=UTC).timestamp())
        bars = self._bars(start, 50)
        now = datetime.fromtimestamp(bars[-1]["t_raw"] - 10800 + 30, UTC)
        r = self._assess(bars, offset=0, now=now)  # offset 0 -> bars look 3 h in the future
        self.assertEqual(r["timeframes"]["M1"]["status"], "TIME_ERROR")
        self.assertFalse(r["analysis_allowed"])

    def test_duplicates_and_invalid_ohlc(self):
        start = int(datetime(2026, 10, 7, 9, 0, tzinfo=UTC).timestamp())
        bars = self._bars(start, 50)
        bars[10] = dict(bars[9])
        r = self._assess(bars)
        self.assertEqual(r["timeframes"]["M1"]["status"], "INVALID")
        bars = self._bars(start, 50)
        bars[5]["h"] = 1990.0
        self.assertIn("INVALID_OHLC", self._assess(bars)["timeframes"]["M1"]["reasons"])

    def test_unexplained_recent_gap_degrades_and_blocks_entries(self):
        start = int(datetime(2026, 10, 7, 9, 0, tzinfo=UTC).timestamp())
        bars = self._bars(start, 60, skip=(50, 51, 52, 53, 54, 55))
        r = self._assess(bars)
        self.assertEqual(r["timeframes"]["M1"]["status"], "DEGRADED")
        self.assertFalse(r["entries_allowed"])

    def test_weekend_gap_is_recognised(self):
        from masterquo.data.quality import SessionModel
        fri = int(datetime(2026, 10, 9, 22, 59, tzinfo=UTC).timestamp())
        mon = int(datetime(2026, 10, 12, 1, 0, tzinfo=UTC).timestamp())
        self.assertEqual(SessionModel([]).classify_gap(fri, mon, 60), "WEEKEND")

    def test_insufficient_history_reports_warming_up_with_hint(self):
        start = int(datetime(2026, 10, 7, 9, 0, tzinfo=UTC).timestamp())
        from masterquo.data.quality import assess
        bars = self._bars(start, 50)
        now = datetime.fromtimestamp(bars[-1]["t_raw"] - 10800 + 30, UTC)
        r = assess(symbol="XAUUSD-", bars_by_tf={tf: bars for tf in ("M1", "M5", "M15", "H1", "H4", "D1")}, required={"D1": 230},
                   quote={"bid": 1, "ask": 1.1, "age_seconds": 0.1, "source_age_seconds": 0.1},
                   clock={"status": "VERIFIED", "offset_seconds": 10800}, connection_state="CONNECTED", now=now, max_quote_age=10, symbol_status="OK")
        self.assertEqual(r["timeframes"]["D1"]["status"], "INSUFFICIENT_HISTORY")
        self.assertIn("XAUUSD-", r["timeframes"]["D1"]["fix_hint"])
        self.assertIn("D1", r["warming_up"])
        self.assertFalse(r["entries_allowed"])

    def test_stale_quote_blocks_entries_but_not_analysis(self):
        start = int(datetime(2026, 10, 7, 9, 0, tzinfo=UTC).timestamp())
        r = self._assess(self._bars(start, 50), quote_age=60)
        self.assertTrue(r["analysis_allowed"])
        self.assertFalse(r["entries_allowed"])
        self.assertIn("QUOTE_STALE", r["reason_codes"])


class TestSymbolAndConfig(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_exact_symbol_kept(self):
        from masterquo.config import ConfigStore
        c = ConfigStore()
        self.assertEqual(c.get().mt5.symbol, "XAUUSD-")
        self.assertEqual(c.update({"mt5": {"symbol": "XAUUSD-"}}).mt5.symbol, "XAUUSD-")
        with self.assertRaises(Exception):
            c.update({"mt5": {"symbol": "XAU USD"}})

    def test_defaults_safe(self):
        from masterquo.config import ConfigStore
        cfg = ConfigStore().get()
        self.assertIsNone(cfg.risk.risk_per_trade_pct)
        self.assertFalse(cfg.execution.allow_live_execution)
        self.assertEqual(cfg.costs.spread_40pct_rule, "REQUIRES_DEFINITION")
        self.assertFalse(cfg.telegram.enabled)
        self.assertEqual(cfg.server.host, "127.0.0.1")

    def test_history_requirements_from_profiles(self):
        from masterquo.engine.legacy import Profiles
        req = Profiles().required_closed_bars()
        self.assertEqual(set(req), {"M1", "M5", "M15", "H1", "H4", "D1"})
        self.assertGreaterEqual(req["D1"], 230)  # not one fixed 90-bar limit

    def test_no_wrong_default_symbol_in_active_code(self):
        import re
        root = _env.ROOT / "backend" / "masterquo"
        for f in root.rglob("*.py"):
            txt = f.read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"default=['\"]XAUUSD['\"]", txt), f)


if __name__ == "__main__":
    unittest.main()
