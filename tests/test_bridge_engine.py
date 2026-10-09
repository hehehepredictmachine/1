"""Bridge on the synthetic terminal, lifecycle rules, look-ahead protection, vendored engines."""
import hashlib
import json
import unittest
from datetime import datetime, timedelta

import _env
from _env import UTC, TempData, bar, core, wait_for


class TestBridge(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_connect_six_timeframes_exact_symbol(self):
        cfg, db, bus, log, fake, worker, b = core()
        b.start()
        try:
            self.assertTrue(wait_for(lambda: b.state == "CONNECTED" and b.clock.verified, 40))
            meta = b.tf_meta()
            self.assertEqual(set(meta), {"M1", "M5", "M15", "H1", "H4", "D1"})
            for tf, m in meta.items():
                self.assertTrue(m["loaded"], tf)
                self.assertGreater(m["closed"], 200, tf)
            q = b.quote_status()
            self.assertEqual(q["symbol"], "XAUUSD-")
            self.assertEqual(b.clock.offset, 3 * 3600)
            m1 = b.bars("M1")
            self.assertFalse(m1[-1]["closed"])                  # current bar is visible but not closed
            self.assertTrue(all(x["closed"] for x in m1[:-1]))
            self.assertEqual(m1[-2]["close_confirmed_utc"], m1[-1]["open_utc"])  # closed only by observed next bar
            self.assertEqual(b.account["trade_mode"], "DEMO")
        finally:
            b.stop()
            worker.stop()

    def test_symbol_not_found_no_substitution(self):
        cfg, db, bus, log, fake, worker, b = core(symbol="XAUUSD")  # broker only has XAUUSD-
        b.start()
        try:
            self.assertTrue(wait_for(lambda: b.symbol_status == "NOT_FOUND", 20))
            self.assertIn("XAUUSD-", b.symbol_candidates)
            self.assertNotEqual(b.state, "CONNECTED")
            self.assertEqual(cfg.get().mt5.symbol, "XAUUSD")  # never changed automatically
        finally:
            b.stop()
            worker.stop()

    def test_disconnect_reconnect_and_account_change(self):
        cfg, db, bus, log, fake, worker, b = core()
        events = []
        b.add_listener(lambda k, d: events.append(k))
        b.start()
        try:
            self.assertTrue(wait_for(lambda: b.state == "CONNECTED", 40))
            epoch = b.session_epoch
            fake.terminal_connected = False
            self.assertTrue(wait_for(lambda: b.state in ("RECONNECTING", "DISCONNECTED"), 30))
            self.assertIsNone(b.quote)
            fake.terminal_connected = True
            b.next_retry = 0
            self.assertTrue(wait_for(lambda: b.state == "CONNECTED", 60))
            self.assertGreater(b.session_epoch, epoch)
            epoch = b.session_epoch
            fake.switch_account(7770001)
            self.assertTrue(wait_for(lambda: b.account_key and b.account_key.endswith(":7770001"), 30))
            self.assertGreater(b.session_epoch, epoch)
            self.assertTrue(wait_for(lambda: "account_changed" in events, 30))
        finally:
            b.stop()
            worker.stop()

    def test_gap_fill_after_missed_polls(self):
        from masterquo.mt5.bridge import Bar, TFState
        cfg, db, bus, log, fake, worker, b = core()
        try:
            st = TFState()
            base = 1_791_000_000 - 1_791_000_000 % 60
            st.bars = [Bar(base + i * 60, 1, 2, 0.5, 1.5, 1, 0, 0, closed=True) for i in range(10)]
            st.bars[-1].closed = False
            fetched = []
            b._fetch = lambda sym, tf, n: fetched.append(n) or [Bar(base + i * 60, 1, 2, 0.5, 1.5, 1, 0, 0) for i in range(9, 20)]
            tail = [Bar(base + i * 60, 1, 2, 0.5, 1.5, 1, 0, 0) for i in (17, 18, 19)]
            closed = b._merge_tail(st, "M1", tail, "XAUUSD-")
            self.assertTrue(fetched)                                  # refetched from the terminal
            self.assertEqual(len(closed), 10)                         # bar 9..18 newly closed, none skipped
            self.assertEqual([x.t_raw for x in st.bars][-11:], [base + i * 60 for i in range(9, 20)])
        finally:
            worker.stop()


PLAN = {
    "strategy_id": "XAU-S01", "version": "1.0.0-RESEARCH", "profile_name": "MVP", "setup_tf": "M15", "intended_direction": "SHORT",
    "frozen_plan_hash": "h1", "spec_hash": "s1", "created_event_id": "M03:FVG:M15:X",
    "lifecycle_rules": {
        "qualification": {"timeframe": "M15", "field": "close", "operator": "<", "level": 100.0, "requires_closed_bar": True, "reference_evidence_id": "x"},
        "arming": {"timeframe": "M15", "field": "low", "operator": "<", "level": 99.5, "requires_closed_bar": True, "reference_evidence_id": "x"},
        "trigger": {"timeframe": "M15", "field": "low", "operator": "<", "level": 99.0, "requires_closed_bar": True, "reference_evidence_id": "x"},
        "confirmation": {"timeframe": "M15", "field": "close", "operator": "<", "level": 98.5, "requires_closed_bar": True, "reference_evidence_id": "x"}},
    "invalidation": {"timeframe": "M15", "condition": {"timeframe": "M15", "field": "close", "operator": ">", "level": 102.0,
                                                       "requires_closed_bar": True, "reference_evidence_id": "x"}, "rule": "CLOSED_BAR"},
}


class TestLifecycle(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.db.database import Database
        from masterquo.engine.lifecycle import LifecycleStore
        self.store = LifecycleStore(Database())
        self.t0 = datetime(2026, 10, 8, 10, 0, tzinfo=UTC)

    def tearDown(self):
        self.td.close()

    def _reg(self, plan=PLAN, ttl=24):
        detected = (self.t0 + timedelta(minutes=15)).isoformat().replace("+00:00", "Z")
        rec, created = self.store.register(plan, account_key="srv:1", symbol="XAUUSD-", detected_at=detected,
                                           last_closed_open=self.t0.isoformat().replace("+00:00", "Z"), ttl_bars=ttl, synthetic=True)
        self.assertTrue(created)
        return rec

    def _b(self, k, o, h, l, c):
        t = self.t0 + timedelta(minutes=15 * k)
        return bar(t, o, h, l, c, available=t + timedelta(minutes=15, seconds=2))

    def test_full_progression_one_stage_per_bar(self):
        rec = self._reg()
        bars = [self._b(1, 100.2, 100.3, 99.6, 99.8),   # qualifies (close<100); low 99.6 not <99.5 yet in same bar anyway
                self._b(2, 99.8, 99.9, 98.0, 98.2),     # would satisfy arm/trigger/confirm, but only one stage per bar -> ARMED
                self._b(3, 98.2, 98.4, 97.9, 98.0),     # TRIGGERED
                self._b(4, 98.0, 98.1, 97.5, 97.6)]     # CONFIRMED on a later distinct bar
        rec, trs = self.store.evaluate(rec["setup_id"], bars)
        self.assertEqual([t["state"] for t in trs], ["QUALIFIED", "ARMED", "TRIGGERED", "CONFIRMED"])
        rec, trs = self.store.evaluate(rec["setup_id"], bars)  # replay is idempotent
        self.assertEqual(trs, [])

    def test_invalidation_before_advancement(self):
        rec = self._reg()
        rec, trs = self.store.evaluate(rec["setup_id"], [self._b(1, 101, 103, 99.0, 102.5)])  # low would arm, close invalidates
        self.assertEqual(rec["state"], "INVALIDATED")

    def test_bars_known_at_detection_do_not_advance(self):
        rec = self._reg()
        early = bar(self.t0, 100, 100.1, 98, 98.2, available=self.t0 + timedelta(minutes=15))  # available == detected
        rec, trs = self.store.evaluate(rec["setup_id"], [early])
        self.assertEqual(rec["state"], "EARLY_SETUP")
        self.assertEqual(trs, [])

    def test_ttl_and_missed_entry(self):
        rec = self._reg(ttl=3)
        flat = [self._b(k, 100.5, 100.8, 100.2, 100.4) for k in range(1, 5)]
        rec, _ = self.store.evaluate(rec["setup_id"], flat)
        self.assertEqual(rec["state"], "EXPIRED")
        plan2 = dict(PLAN, frozen_plan_hash="h2")
        rec = self._reg(plan2)
        bars = [self._b(1, 100.2, 100.3, 99.6, 99.8), self._b(2, 99.8, 99.9, 99.4, 99.6), self._b(3, 99.6, 99.6, 98.9, 99.0),
                self._b(4, 99, 99, 98.0, 98.2), self._b(5, 98.2, 98.4, 98.1, 98.3), self._b(6, 98.3, 98.4, 98.1, 98.2)]
        rec, trs = self.store.evaluate(rec["setup_id"], bars)
        self.assertEqual(rec["state"], "MISSED_ENTRY")

    def test_confirmed_window_configurable(self):
        bars = [self._b(1, 100.2, 100.3, 99.6, 99.8), self._b(2, 99.8, 99.9, 99.4, 99.6), self._b(3, 99.6, 99.6, 98.9, 99.0),
                self._b(4, 99, 99, 98.0, 98.2), self._b(5, 98.2, 98.4, 98.1, 98.3), self._b(6, 98.3, 98.4, 98.1, 98.2)]
        rec = self._reg(dict(PLAN, frozen_plan_hash="h-win3"))
        rec, _ = self.store.evaluate(rec["setup_id"], bars, confirmed_window_bars=3)
        self.assertEqual(rec["state"], "CONFIRMED")                      # 2 window bars < 3
        rec, _ = self.store.evaluate(rec["setup_id"], bars + [self._b(7, 98.2, 98.3, 98.1, 98.2)], confirmed_window_bars=3)
        self.assertEqual(rec["state"], "MISSED_ENTRY")

    def test_contradictory_rules_rejected(self):
        bad = json.loads(json.dumps(PLAN))
        bad["frozen_plan_hash"] = "h3"
        bad["lifecycle_rules"]["trigger"]["operator"] = ">"
        rec = self._reg(bad)
        self.assertEqual(rec["state"], "CANCELLED")


class TestNoLookahead(unittest.TestCase):
    def test_pivot_available_only_after_right_bars(self):
        from masterquo.engine.legacy import modules
        m02 = modules()["m02"]
        t0 = datetime(2026, 10, 8, 0, 0, tzinfo=UTC)
        bars = []
        for i, hi in enumerate([1, 2, 5, 2, 1, 1, 1]):
            o = (t0 + timedelta(hours=i)).isoformat()
            c = (t0 + timedelta(hours=i + 1)).isoformat()
            bars.append({"high": hi, "low": 0.5, "bar_open_utc": o, "close_confirmed_at": c})
        pv = m02.pivots(bars, 2, 2)
        self.assertEqual(len(pv["highs"]), 1)
        p = pv["highs"][0]
        self.assertEqual(p["pivot_time"], bars[2]["bar_open_utc"])
        self.assertEqual(p["available_at"], bars[4]["close_confirmed_at"])  # known only after 2 right bars closed

    def test_snapshot_excludes_forming_and_keeps_availability(self):
        from masterquo.engine.legacy import build_snapshot
        t = datetime(2026, 10, 8, 10, 0, tzinfo=UTC)
        b1 = bar(t, 1, 2, 0.5, 1.5)
        s = build_snapshot(snapshot_id="S", analysis_id="A", as_of="2026-10-08T11:00:00Z", symbol="XAUUSD-", alias="XAUUSD",
                           closed_bars={"M15": [b1]}, analysis_status="PASS_WITH_LIMITATIONS", reason_codes=[])
        row = s["candles_by_tf"]["M15"][0]
        self.assertEqual(row["exact_symbol"], "XAUUSD-")
        self.assertEqual(row["instrument_id"], "XAUUSD")  # analytical alias for unchanged legacy engines
        self.assertGreaterEqual(row["available_at"], row["close_confirmed_at"])


class TestVendoredEnginesUnchanged(unittest.TestCase):
    def test_manifest(self):
        man = json.loads((_env.ROOT / "backend" / "vendor" / "VENDOR_MANIFEST.json").read_text(encoding="utf-8"))
        for rel, info in man["files"].items():
            p = _env.ROOT / rel
            self.assertTrue(p.exists(), rel)
            self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(), info["sha256"], rel)
            self.assertTrue(info["identical_to_source"], rel)

    def test_macd_signal_is_sma_in_profile(self):
        from masterquo.engine.legacy import Profiles
        p = Profiles().m02i["timeframe_profiles"]["H1"]["enabled"]["macd"]
        self.assertEqual(p["signal_ma"], "SMA")


if __name__ == "__main__":
    unittest.main()
