"""Signal contract (engine/signal_contract.py): statuses, levels vs live price, AI qualification, TTL, probability."""
from __future__ import annotations

import unittest

import _env  # noqa: F401

from masterquo.engine import signal_contract as sc  # noqa: E402

PASS = {"status": "PASS"}


def decision(stage="CONFIRMED", decision="BUY", nodes=None, permission="ALLOWED", sl=2390.0, tp=2425.0):
    tree = [{"node": n, "status": "PASS"} for n in ("DATA", "MARKET", "STRATEGY", "RISK", "AI", "ML", "PERMISSION")]
    for n, st in (nodes or {}).items():
        for x in tree:
            if x["node"] == n:
                x.update({"status": st, "reason_codes": [f"{n}_X"]})
    return {"symbol": "XAUUSD-", "snapshot_id": "SNP-1", "as_of_utc": "2026-10-11T10:00:00Z", "decision": decision, "decision_id": "D-1",
            "execution_permission": permission, "decision_tree": tree, "data_quality": "OK", "market_state": "OPEN",
            "setup": {"setup_id": "S11-X", "version": 2, "strategy_id": "S11", "strategy_version": "1.1.0", "direction": "LONG", "state": stage,
                      "state_changed_at": "2026-10-11T09:59:00Z", "setup_tf": "M30", "setup_score": 71,
                      "entry_plan": {"reference_price": 2400.0, "trigger_level": 2400.5, "order_type": "MARKET_ON_CONFIRMATION"},
                      "invalidation_level": sl},
            "levels": {"stop_loss": sl, "targets": [{"price": tp, "weight": 1.0}]},
            "risk": {"modeled_loss": 50.0, "equity": 10000.0, "lots": 0.05, "rr_net": 2.31, "currency": "USD", "rr_complete": True},
            "checklist": {"met": [{"label": "EMA20>EMA50"}], "missing": []}}


QUOTE = {"bid": 2400.0, "ask": 2400.3, "time_utc": "2026-10-11T10:00:00Z", "age_seconds": 0.4}


def build(d, **kw):
    args = dict(quote=QUOTE, row={"status": "ACTIVE", "expires_at": "2026-10-11T11:00:00Z"}, agent_result=None,
                agent_status={"state": "IDLE"}, context=None, costs={"per_lot_per_side": 3.5, "source": "USER"}, attempts=[], ml=None,
                data_source="MT5")
    args.update(kw)
    return sc.build(d, **args)


class TestSignalContract(unittest.TestCase):
    def test_no_setup_no_signal(self):
        d = decision()
        d["setup"] = None
        self.assertIsNone(build(d))

    def test_confirmed_signal_prices_and_rr(self):
        s = build(decision())
        self.assertEqual(s["schema"], "MQ-SIGNAL-1.0.0")
        self.assertEqual(s["status"], "POTWIERDZONY")
        self.assertEqual(s["entry_price"], 2400.3)                   # LONG plans on Ask
        self.assertIsNone(s["fill_price"])                           # filled price only after a real fill
        self.assertEqual(s["decision_source"], "STRATEGIA")          # no AI verdict -> never labelled AI
        self.assertAlmostEqual(s["rr_gross"], (2425 - 2400.3) / (2400.3 - 2390), places=3)
        self.assertEqual(s["rr_net"], 2.31)
        self.assertAlmostEqual(s["spread"]["pct_of_sl_distance"], round(100 * 0.3 / 10.3, 2))
        self.assertEqual(s["risk_pct"], 0.5)
        self.assertIsNone(s["probability_win"])
        self.assertEqual(s["execution_state"], "BRAK")
        self.assertIn("gross", s["rr_definitions"])

    def test_waiting_and_blocked_and_no_data(self):
        s = build(decision(stage="EARLY_SETUP", decision="WAIT"))
        self.assertEqual(s["status"], "OCZEKIWANIE")
        self.assertIsNone(s["entry_price"])
        self.assertEqual(s["ai"]["status"], "OCENA_TYLKO_PO_POTWIERDZENIU")
        s = build(decision(decision="NO_TRADE", nodes={"RISK": "FAIL"}))
        self.assertEqual(s["status"], "ZABLOKOWANY")
        self.assertIn("RISK:RISK_X", s["block_reasons"])
        s = build(decision(nodes={"DATA": "FAIL"}))
        self.assertEqual(s["status"], "BRAK_DANYCH")

    def test_levels_inconsistent_with_live_price_blocks(self):
        s = build(decision(tp=2400.1))                               # Ask already beyond TP
        self.assertEqual(s["status"], "ZABLOKOWANY")
        self.assertIn("LEVELS_INCONSISTENT_WITH_LIVE_PRICE", s["block_reasons"])

    def test_terminal_states_and_execution_state(self):
        s = build(decision(), row={"status": "EXPIRED", "terminal_reason": "EXPIRED"})
        self.assertEqual(s["status"], "WYGASŁY")
        s = build(decision(), row={"status": "INVALIDATED", "terminal_reason": "INVALIDATED"})
        self.assertEqual(s["status"], "UNIEWAŻNIONY")
        s = build(decision(), attempts=[{"setup_id": "S11-X", "state": "FILLED"}])
        self.assertEqual(s["execution_state"], "WYKONANO")
        self.assertEqual(s["status"], "POTWIERDZONY")                # execution state is separate from the signal status

    def test_ai_unavailable_stale_and_current(self):
        s = build(decision(), agent_status={"state": "AI_UNAVAILABLE_NO_KEY"})
        self.assertEqual(s["ai"]["status"], "AI_NIEDOSTEPNE")
        self.assertEqual(s["decision_source"], "STRATEGIA")
        rec = {"setup_id": "S11-X", "proposed_action": "BUY", "explanation_pl": "zgodne", "model_id": "m"}
        stale = {"status": "OK", "record": rec, "setup_state_changed_at": "2026-10-11T09:00:00Z"}   # assessed an older state
        s = build(decision(), agent_result=stale)
        self.assertEqual(s["ai"]["status"], "NIEAKTUALNA")
        self.assertIsNone(s["ai"]["verdict"])                        # a late answer never overrides the current setup
        self.assertEqual(s["decision_source"], "STRATEGIA")
        cur = {"status": "OK", "record": rec, "setup_state_changed_at": "2026-10-11T09:59:00Z"}
        s = build(decision(), agent_result=cur)
        self.assertEqual((s["ai"]["status"], s["ai"]["verdict"], s["decision_source"]), ("AKTUALNA", "ZGODA", "STRATEGIA + AI"))
        s = build(decision(), agent_result={**cur, "record": {**rec, "proposed_action": "NO_TRADE"}})
        self.assertEqual(s["ai"]["verdict"], "BRAK_ZGODY")
        s = build(decision(), agent_result={"status": "TIMEOUT"})
        self.assertEqual(s["ai"]["status"], "AI_BLAD")

    def test_probability_only_from_validated_model(self):
        s = build(decision(), ml={"calibrated_probability": 0.41, "calibration_status": "NONE", "readiness": "READY"})
        self.assertIsNone(s["probability_win"])
        s = build(decision(), ml={"calibrated_probability": 0.41, "calibration_status": "ISOTONIC", "readiness": "COLLECTING"})
        self.assertIsNone(s["probability_win"])
        s = build(decision(), ml={"calibrated_probability": 0.41, "calibration_status": "ISOTONIC", "readiness": "READY", "model_id": "M1"})
        self.assertEqual(s["probability_win"]["value"], 0.41)

    def test_ttl(self):
        s = build(decision())
        self.assertEqual(sc.ttl_status(s, "2026-10-11T10:30:00Z")["status"], "POTWIERDZONY")
        e = sc.ttl_status(s, "2026-10-11T11:00:00Z")
        self.assertEqual(e["status"], "WYGASŁY")
        self.assertIn("TTL", e["block_reasons"])

    def test_short_levels(self):
        self.assertTrue(sc.levels_consistent("SHORT", 2400.0, 2410.0, [{"price": 2380.0}]))
        self.assertFalse(sc.levels_consistent("SHORT", 2400.0, 2395.0, [{"price": 2380.0}]))
        self.assertFalse(sc.levels_consistent("LONG", 2400.0, None, [{"price": 2420.0}]))


if __name__ == "__main__":
    unittest.main()
