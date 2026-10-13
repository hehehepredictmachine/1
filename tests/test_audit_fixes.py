"""1.10 - regression tests for the audit findings A-J (audit/AUDYT_MASTERQUO_1_9_0_PL.md). Every reproduction of
audit/repro/repro_audit.py must report NOT_REPRODUCED, plus targeted checks of the shared exit policy, settlement,
labels, costs and model comparison. No terminal, no real orders (atrapy / FakeMT5-free fakes, temporary data)."""
from __future__ import annotations

import importlib.util
import unittest
from datetime import datetime, timedelta, timezone

import _env

UTC = timezone.utc
_spec = importlib.util.spec_from_file_location("repro_audit", _env.ROOT / "audit" / "repro" / "repro_audit.py")
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)


def iso(t):
    return t.isoformat().replace("+00:00", "Z")


class TestAuditReproductionsFixed(unittest.TestCase):
    def check(self, fn):
        import os
        prev = os.environ.get("MASTERQUO_DATA_DIR")
        try:
            r = fn()
        finally:
            if prev is not None:
                os.environ["MASTERQUO_DATA_DIR"] = prev
        self.assertEqual(r["status"], "NOT_REPRODUCED", r)
        return r

    def test_ml_cost_same_source_as_execution(self):
        r = self.check(R.case_A)
        self.assertAlmostEqual(r["observed"]["ml_commission_price_units"], 0.035)

    def test_paper_partial_not_in_statistics(self):
        self.check(R.case_B)

    def test_labels_tp1_then_be_uses_cursor(self):
        r = self.check(R.case_C)
        self.assertEqual((r["observed"]["remaining"], r["observed"]["stop"]), (0.5, 100.0))

    def test_s11_none_time_exit_and_rr_from_fill(self):
        r = self.check(R.case_D)
        self.assertIsNone(r["observed"]["make_spec"]["horizon_minutes"])

    def test_policy_stored_at_open(self):
        self.check(R.case_E)

    def test_tp1_state_from_execution(self):
        r = self.check(R.case_F)
        self.assertEqual(r["observed"]["tp1_state"], "REJECTED")

    def test_champion_same_ids(self):
        self.check(R.case_G)

    def test_paper_unsettled_not_zero(self):
        self.check(R.case_J)


class TestPolicyAndLabels(unittest.TestCase):
    def test_policy_rr_from_fill_and_no_time_exit(self):
        from masterquo.execution import policy as P
        pol = P.from_plan(side="LONG", stop_loss=1990.0, targets=[{"price": 2025.0, "weight": 1.0}],
                          exit_rules={"tp_rule": "RR_FROM_FILL", "rr": 2.5, "be_after_tp1": False, "time_exit_bars": None}, timeframe="M15",
                          entry=2001.0)
        self.assertAlmostEqual(pol["targets"][0]["price"], 2001.0 + 2.5 * 11.0)
        self.assertIsNone(pol["time_exit_minutes"])
        self.assertEqual(pol["time_exit_source"], "SETUP_NO_TIME_EXIT")
        self.assertFalse(pol["be_after_tp1"])

    def test_policy_time_exit_and_weights(self):
        from masterquo.execution import policy as P
        pol = P.from_plan(side="SHORT", stop_loss=2010.0, targets=[{"price": 1980.0, "weight": 2}, {"price": 1990.0, "weight": 1}],
                          exit_rules={"time_exit_bars": 24}, timeframe="M15", be_default=True)
        self.assertEqual([t["price"] for t in pol["targets"]], [1990.0, 1980.0])          # nearest first
        self.assertAlmostEqual(sum(t["weight"] for t in pol["targets"]), 1.0)
        self.assertEqual(pol["time_exit_minutes"], 360)
        self.assertEqual(pol["be_source"], "CONFIG_AT_OPEN")

    def test_label_without_quotes_after_tp1_is_ambiguous_not_breakeven(self):
        from masterquo.ml import labels as lb
        t0 = datetime(2026, 10, 13, 10, tzinfo=UTC)
        spec = {"direction": "LONG", "asof_utc": iso(t0), "stop_loss": 90.0, "targets": [{"price": 105.0, "weight": 0.5}, {"price": 110.0, "weight": 0.5}],
                "be_after_tp1": True, "horizon_minutes": 60, "entry_window_minutes": 5, "spread": 0.0, "slippage": 0.0, "commission": 0.0}
        bars = [{"open_utc": iso(t0), "o": 100.0, "h": 100.0, "l": 100.0, "c": 100.0},
                {"open_utc": iso(t0 + timedelta(minutes=1)), "o": 100.0, "h": 106.0, "l": 99.0, "c": 106.0}]
        _, res = lb.step(spec, lb.new_state(spec), bars, [], t0 + timedelta(minutes=3))
        self.assertEqual(res["status"], "AMBIGUOUS")

    def test_label_post_tp1_quote_hits_be(self):
        from masterquo.ml import labels as lb
        t0 = datetime(2026, 10, 13, 10, tzinfo=UTC)
        spec = {"direction": "LONG", "asof_utc": iso(t0), "stop_loss": 90.0, "targets": [{"price": 105.0, "weight": 0.5}, {"price": 110.0, "weight": 0.5}],
                "be_after_tp1": True, "horizon_minutes": 60, "entry_window_minutes": 5, "spread": 0.0, "slippage": 0.0, "commission": 0.0}
        bars = [{"open_utc": iso(t0), "o": 100.0, "h": 100.0, "l": 100.0, "c": 100.0},
                {"open_utc": iso(t0 + timedelta(minutes=1)), "o": 100.0, "h": 106.0, "l": 99.0, "c": 101.0}]
        tb = (t0 + timedelta(minutes=1)).timestamp()
        ticks = [(tb + 5, 105.5, 105.5), (tb + 30, 99.0, 99.0), (tb + 50, 101.0, 101.0)]
        _, res = lb.step(spec, lb.new_state(spec), bars, ticks, t0 + timedelta(minutes=3))
        self.assertEqual((res["status"], res["exit_reason"]), ("LABELED", "BREAKEVEN_STOP"))
        self.assertAlmostEqual(res["outcome_r"], 0.25)

    def test_replay_s11_and_policy(self):
        import sys
        sys.path.insert(0, str(_env.ROOT / "tools"))
        import replay_strategies as rp
        t0 = datetime(2026, 10, 13, 10, tzinfo=UTC)
        m5 = [{"open_utc": iso(t0 + timedelta(minutes=5 * i)), "o": 2000.0 + i, "h": 2001.0 + i, "l": 1999.5 + i, "c": 2000.5 + i} for i in range(40)]
        idx = {"times": [t0 + timedelta(minutes=5 * i) for i in range(40)]}
        rec = {"direction": "LONG", "stop_loss": 1995.0, "targets": [{"price": 2010.0, "weight": 1.0}], "timeframe": "M15",
               "exit_rules": {"tp_rule": "RR_FROM_FILL", "rr": 2.5, "be_after_tp1": False, "time_exit_bars": None}}
        r = rp.simulate(rec, t0, m5, idx, {"spread": 0.2, "slip": 0.0, "commission": 0.0})
        self.assertEqual(r["status"], "CLOSED")
        self.assertTrue(r["tp_rebased_on_fill"])
        self.assertAlmostEqual(r["r"], 2.5, places=3)


class TestCostsValidationStats(unittest.TestCase):
    def test_commission_tariff_open_only(self):
        from masterquo.risk.costs import commission_from_history
        deals = [{"symbol": "X", "type": 0, "entry": 0, "volume": 1.0, "commission": -7.0} for _ in range(3)] + \
                [{"symbol": "X", "type": 1, "entry": 1, "volume": 1.0, "commission": 0.0} for _ in range(3)]
        r = commission_from_history(deals, "X")
        self.assertEqual((r["per_lot_per_side"], r["round_turn_per_lot"], r["tariff"]), (3.5, 7.0, "AT_OPEN"))

    def test_purge_when_middle_block_empty(self):
        from masterquo.ml import validation as V
        t0 = datetime(2026, 1, 1, tzinfo=UTC)
        rows = [{"sample_id": f"S{i}", "group_id": f"G{i}", "event_id": f"E{i}", "asof_utc": iso(t0 + timedelta(hours=i)),
                 "label_end_utc": iso(t0 + timedelta(hours=i + 30)), "label": i % 2} for i in range(40)]
        info, _ = V.split(rows, embargo_minutes=0, min_block=0, min_class=0)
        later_start = min(datetime.fromisoformat(r["asof_utc"].replace("Z", "+00:00")) for b in ("tune", "calib", "test") for r in info["blocks"][b])
        self.assertTrue(all(datetime.fromisoformat(r["label_end_utc"].replace("Z", "+00:00")) <= later_start for r in info["blocks"]["fit"]))

    def test_roi_credit_is_external_flow(self):
        from masterquo import stats
        from masterquo.db.database import Database
        td = _env.TempData()
        try:
            db = Database()
            t0 = datetime.now(UTC) - timedelta(hours=2)
            for i, eq in enumerate((1000.0, 1500.0)):
                db.execute("INSERT INTO equity_snapshots(ts, mode, account_key, balance, equity) VALUES (?,?,?,?,?)",
                           (iso(t0 + timedelta(hours=i)), "ACCOUNT", "A:1", eq, eq))
            deals = [{"type": 6, "profit": 500.0, "time": (t0 + timedelta(minutes=30)).timestamp()}]       # bonus, not profit
            r = stats.account_roi(db, "A:1", deals, 0)
            self.assertAlmostEqual(r["roi_pct"], 0.0, places=3)
            db.close()
        finally:
            td.close()


if __name__ == "__main__":
    unittest.main()
