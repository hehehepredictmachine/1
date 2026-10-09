"""12A checklist built from strategy output: four sections, no direction words, explicit 'no scenario'."""
import unittest

import _env  # noqa: F401


class TestChecklist(unittest.TestCase):
    def row(self, stage="EARLY"):
        return {"setup_id": "MQA-1", "version": 2, "stage": stage, "status": "ACTIVE", "stale": 0, "expires_at": "2026-10-09T20:00:00Z",
                "record": {"strategy_id": "S01", "strategy_name": "TREND_PULLBACK", "timeframe": "M15", "direction": "SHORT", "setup_score": 61.0,
                           "reason_codes": ["TREND_ER_0.40"], "facts": {"depth_atr": 1.8, "er": None}, "score": {"points": {"structure": 20}},
                           "missing_confirmations": ["REACTION_BAR_CLOSE_BELOW_PRIOR_LOW", "SCORE_BELOW_CONFIRMED_70"],
                           "entry_plan": {"trigger": "zamknięcie poniżej low poprzedniej świecy", "trigger_level": 3450.1, "zone": [3451, 3455],
                                          "max_distance_atr": 1.0, "max_wait_bars": 3},
                           "invalidation_level": 3460.0, "expires_bars": 12, "stop_loss": 3461.0, "targets": [{"price": 3440.0}]}}

    def decision(self, data="PASS"):
        return {"decision_tree": [{"node": "DATA", "status": data, "reason_codes": [] if data == "PASS" else ["QUOTE_STALE"], "unmet": []},
                                  {"node": "RISK", "status": "FAIL", "reason_codes": ["RISK_LIMITS_NOT_CONFIGURED"], "unmet": []}]}

    def test_four_sections_from_strategy(self):
        from masterquo.engine import checklist
        c = checklist.build(self.decision(), self.row())
        self.assertEqual(c["status"], "SCENARIO")
        met = {m["id"] for m in c["met"]}
        self.assertIn("FACT_depth_atr", met)
        self.assertIn("GATE_DATA", met)
        miss = {m["id"]: m for m in c["missing"]}
        self.assertEqual(miss["FACT_er"]["status"], "NO_DATA")                      # missing data shown as "brak danych"
        self.assertIn("REACTION_BAR_CLOSE_BELOW_PRIOR_LOW", miss)
        self.assertIn("70", miss["SCORE_BELOW_CONFIRMED_70"]["required"])
        self.assertIn("GATE_RISK", miss)
        self.assertEqual((c["trigger"]["level"], c["trigger"]["timeframe"], c["trigger"]["closed_bar_required"]), (3450.1, "M15", True))
        self.assertEqual((c["invalidation"]["level"], c["invalidation"]["time"]), (3460.0, "2026-10-09T20:00:00Z"))
        text = str(c).upper()
        for w in ("'BUY", "'SELL", "LONG'", "'SHORT'"):
            self.assertNotIn(w, text)

    def test_no_scenario_is_explicit(self):
        from masterquo.engine import checklist
        c = checklist.build(self.decision("FAIL"), None, no_setup_reasons=["Dane: STALE"])
        self.assertEqual(c["status"], "NO_SCENARIO")
        self.assertIn("Brak aktualnego scenariusza", c["no_scenario_reason"])
        self.assertEqual(c["why"], ["Dane: STALE"])


if __name__ == "__main__":
    unittest.main()
