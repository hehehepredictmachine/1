"""Less restrictive defaults: structure policy, config migration, macro calendar, AI/RR wiring in the decision tree."""
import json
import unittest

import _env  # noqa: F401
from _env import TempData


def m02(h4, h1, structural="UNKNOWN"):
    tf = lambda d: {"status": "PASS", "direction": d}  # noqa: E731
    return {"structural_direction": structural, "timeframes": {"H4": tf(h4), "H1": tf(h1), "D1": tf("NEUTRAL")}}


class TestStructurePolicy(unittest.TestCase):
    def test_policies(self):
        from masterquo.engine.legacy import resolve_structure as rs
        # agreeing H4/H1: unchanged under every policy
        for pol in ("STRICT_H4_H1", "H1_H4_NOT_OPPOSING", "H1_LEAD"):
            self.assertEqual(rs(m02("BEARISH", "BEARISH", "BEARISH"), "SCALP", pol)["structural_direction"], "BEARISH")
        # H4 range, H1 trend
        self.assertEqual(rs(m02("NEUTRAL", "BULLISH"), "SCALP", "STRICT_H4_H1")["structural_direction"], "UNKNOWN")
        r = rs(m02("NEUTRAL", "BULLISH"), "SCALP", "H1_H4_NOT_OPPOSING")
        self.assertEqual((r["structural_direction"], r["structural_direction_m02"]), ("BULLISH", "UNKNOWN"))
        self.assertIn("STRUCTURE_H1_LEADS_H4_NEUTRAL", r["structure_notes"])
        # H4 opposite
        self.assertEqual(rs(m02("BEARISH", "BULLISH"), "SCALP", "H1_H4_NOT_OPPOSING")["structural_direction"], "UNKNOWN")
        r = rs(m02("BEARISH", "BULLISH"), "SCALP", "H1_LEAD")
        self.assertEqual(r["structural_direction"], "BULLISH")
        self.assertIn("STRUCTURE_COUNTER_H4", r["structure_notes"])
        # H1 without a trend never invents a direction
        self.assertEqual(rs(m02("BULLISH", "NEUTRAL"), "SCALP", "H1_LEAD")["structural_direction"], "UNKNOWN")
        # H1 data not valid -> no direction
        bad = m02("NEUTRAL", "BULLISH")
        bad["timeframes"]["H1"]["status"] = "FAIL"
        self.assertEqual(rs(bad, "SCALP", "H1_LEAD")["structural_direction"], "UNKNOWN")

    def test_vendor_output_not_mutated(self):
        from masterquo.engine.legacy import resolve_structure
        src = m02("NEUTRAL", "BEARISH")
        resolve_structure(src, "SCALP", "H1_LEAD")
        self.assertEqual(src["structural_direction"], "UNKNOWN")


class TestConfigMigration(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def _store(self, raw):
        from pathlib import Path
        from masterquo.config import ConfigStore
        p = Path(self.td.dir) / "config.json"
        p.write_text(json.dumps(raw), encoding="utf-8")
        return ConfigStore(p), p

    def test_v1_defaults_upgraded_custom_values_kept(self):
        st, p = self._store({"config_version": 1, "risk": {"rr_block_below": 1.5, "rr_pass_from": 2.5, "risk_per_trade_pct": 1.0},
                             "costs": {"slippage_stress_points": None}, "agent": {"required_for_entry": True}})
        c = st.get()
        self.assertEqual(c.config_version, 3)
        self.assertEqual(c.risk.rr_block_below, 1.0)          # old default -> new default
        self.assertEqual(c.risk.rr_pass_from, 2.5)            # user's own value kept
        self.assertEqual(c.risk.risk_per_trade_pct, 1.0)
        self.assertEqual(c.costs.slippage_stress_points, 20.0)
        self.assertEqual(c.agent.gate_policy, "VETO")
        self.assertEqual(json.loads(p.read_text(encoding="utf-8"))["config_version"], 3)  # persisted

    def test_v1_ai_not_required_becomes_advisory(self):
        st, _ = self._store({"config_version": 1, "agent": {"required_for_entry": False}})
        self.assertEqual(st.get().agent.gate_policy, "ADVISORY")

    def test_v2_untouched(self):
        st, _ = self._store({"config_version": 2, "risk": {"rr_block_below": 1.5}})
        self.assertEqual(st.get().risk.rr_block_below, 1.5)


class TestDecisionRelaxed(unittest.TestCase):
    def build(self, macro, risk_over=None, structure_notes=None):
        from masterquo.config import AppConfig
        from masterquo.engine import decision
        cfg = AppConfig.model_validate({"risk": risk_over or {}})
        dq = {"analysis_allowed": True, "entries_allowed": True, "reason_codes": [], "market_state": "OPEN", "data_quality": "GOOD"}
        setup = {"setup_id": "MQS-1", "state": "CONFIRMED", "signal_stage": "CONFIRMED", "direction": "LONG", "strategy_id": "XAU-S01",
                 "profile": "MVP", "setup_tf": "M15"}
        return decision.build(snapshot_id="S", as_of="2026-10-08T12:00:00Z", symbol="XAUUSD-", account_key="a", session_epoch=1, dq=dq,
                              legacy={"m02": {"structural_direction": "BULLISH", "structure_notes": structure_notes or [], "timeframes": {}}},
                              setup=setup, levels={}, risk={"risk_gate": "PASS", "reason_codes": []},
                              agent_gate={"status": "NOT_REQUIRED", "reason_codes": ["AI_NO_VETO_AI_UNAVAILABLE_NO_KEY"]},
                              mode_gate={"mode": "PAPER", "allowed": True, "reason_codes": []},
                              macro=macro, strategy_cfg=cfg.strategy, risk_cfg=cfg.risk, dxy_status="NOT_CONFIGURED", synthetic=True)

    def test_missing_calendar_does_not_block_by_default(self):
        d = self.build({"status": "UNAVAILABLE"})
        self.assertEqual((d["decision"], d["execution_permission"]), ("BUY", "ALLOWED"))
        d = self.build({"status": "UNAVAILABLE"}, {"macro_calendar_required": True})
        self.assertEqual(d["execution_permission"], "BLOCKED")
        self.assertIn("MACRO_CALENDAR_UNAVAILABLE", d["reason_codes"])

    def test_high_impact_window_still_blocks(self):
        d = self.build({"status": "OK", "risk_level": "HIGH"})
        self.assertEqual(d["execution_permission"], "BLOCKED")
        self.assertIn("MACRO_EVENT_WINDOW", d["reason_codes"])

    def test_counter_h4_is_reported_not_blocking(self):
        d = self.build({"status": "OK", "risk_level": "NONE"}, structure_notes=["STRUCTURE_COUNTER_H4"])
        self.assertEqual(d["execution_permission"], "ALLOWED")
        strat = [n for n in d["decision_tree"] if n["node"] == "STRATEGY"][0]
        self.assertIn("STRUCTURE_COUNTER_H4", strat["reason_codes"])


if __name__ == "__main__":
    unittest.main()
