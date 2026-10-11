"""Presentation model of the signal card (engine/signal_view.py): every display state, levels from the engine only,
missing values with a reason, AI never upgrades a state, the execution-mode gate is not a confirmation condition."""
from __future__ import annotations

import unittest

import _env  # noqa: F401
from test_signal_contract import QUOTE, build, decision  # noqa: E402

from masterquo.engine import signal_contract as sc  # noqa: E402
from masterquo.engine import signal_view as sv  # noqa: E402

CHECKLIST = {"status": "SCENARIO", "met": [{"id": "STRATEGY_RULE", "label": "x", "reading": "EMA20>EMA50, ADX_25"}],
             "missing": [{"id": "CONFIRMATION_CLOSE_ABOVE_EMA20_ON_LATER_BAR", "label": "Zamknięcie powyżej EMA20", "required": "na późniejszej świecy",
                          "status": "MISSING"},
                         {"id": "GATE_PERMISSION", "label": "Tryb", "required": "", "status": "MISSING"}],
             "trigger": {"description": "zamknięcie powyżej EMA20", "met": False},
             "gates": [{"id": "DATA", "status": "MET"}, {"id": "RISK", "status": "MET"}, {"id": "PERMISSION", "status": "MISSING", "reasons": ["MODE_SIGNALS"]}]}


def view(d, sig, **kw):
    d = {**d, "checklist": kw.pop("checklist", CHECKLIST)}
    return sv.present(d, sig, symbol="XAUUSD-", digits=2, execution_mode=kw.pop("mode", "SIGNALS"))


class TestSignalView(unittest.TestCase):
    def test_buy_and_sell_only_for_confirmed_current_signals(self):
        v = view(decision(), build(decision()))
        self.assertEqual((v["state"], v["plan_side"], v["intent"]), ("BUY", "BUY", "OTWARCIE"))
        self.assertEqual(v["levels"]["entry"]["value"], QUOTE["ask"])                # planned entry from the engine (Ask)
        self.assertEqual(v["levels"]["entry"]["kind"], "PLANOWANE")
        self.assertIsNone(v["levels"]["fill"]["value"])                               # executed price only after a fill
        self.assertEqual(v["levels"]["sl"]["value"], 2390.0)
        self.assertEqual(v["levels"]["tp"]["value"], 2425.0)
        self.assertEqual(v["levels"]["rr"]["net"], 2.31)
        self.assertIn("potwierdziła setup", v["reason"])
        self.assertIsNone(v["execution_note"])
        d = decision(permission="BLOCKED_BY_MODE")
        v = view(d, build(d))
        self.assertEqual(v["state"], "BUY")                                         # the execution mode does not change BUY
        self.assertIn("SIGNALS", v["execution_note"])
        d = decision()
        d["setup"] = {**d["setup"], "direction": "SHORT"}
        d["levels"] = {"stop_loss": 2410.0, "targets": [{"price": 2380.0, "weight": 1.0}]}
        v = view(d, build(d))
        self.assertEqual(v["state"], "SELL")
        self.assertEqual(v["levels"]["entry"]["value"], QUOTE["bid"])

    def test_waiting_shows_plan_and_missing(self):
        d = decision(stage="EARLY_SETUP", decision="WAIT")
        v = view(d, build(d))
        self.assertEqual((v["state"], v["plan_side"]), ("OCZEKIWANIE", "BUY"))
        self.assertEqual(v["levels"]["entry"]["kind"], "POZIOM_WYZWALACZA")
        self.assertIn("Zamknięcie powyżej EMA20", v["missing_summary"])
        self.assertNotIn("Tryb", v["missing_summary"])                                # execution mode is not a confirmation condition
        d2 = {**d, "risk": {}}
        v = view(d2, build(d2))
        self.assertIsNone(v["risk"]["volume"])
        self.assertTrue(v["risk"]["note"])                                           # missing value has a reason

    def test_block_expired_no_data_no_signal(self):
        d = decision(decision="NO_TRADE", nodes={"RISK": "FAIL"})
        v = view(d, build(d))
        self.assertEqual(v["state"], "BLOKADA")
        self.assertIn("RISK:RISK_X", v["block_reasons"])
        v = view(decision(), sc.ttl_status(build(decision()), "2026-10-11T12:00:00Z"))
        self.assertEqual(v["state"], "NIEAKTUALNY")
        d = decision(nodes={"DATA": "FAIL"})
        self.assertEqual(view(d, build(d))["state"], "BRAK_DANYCH")
        d = decision()
        d["setup"] = None
        nos = {"status": "NO_SCENARIO", "why": ["S01: brak impulsu"], "gates": [{"id": "DATA", "status": "MET"}]}
        v = view(d, None, checklist=nos)
        self.assertEqual((v["state"], v["plan_side"], v["levels"]), ("BRAK_SYGNALU", None, None))
        self.assertEqual(v["why"], ["S01: brak impulsu"])
        d = decision(nodes={"DATA": "FAIL"})
        d["setup"] = None
        self.assertEqual(view(d, None, checklist={**nos, "gates": [{"id": "DATA", "status": "MISSING"}]})["state"], "BRAK_DANYCH")

    def test_ai_never_upgrades_and_stale_ai_is_marked(self):
        d = decision(stage="EARLY_SETUP", decision="WAIT")
        rec = {"setup_id": "S11-X", "proposed_action": "BUY", "explanation_pl": "AI uważa, że warto"}
        v = view(d, build(d, agent_result={"status": "OK", "record": rec, "setup_state_changed_at": "2026-10-11T09:59:00Z"}))
        self.assertEqual(v["state"], "OCZEKIWANIE")                                   # an AI "BUY" idea does not make BUY
        late = build(decision(), agent_result={"status": "OK", "record": rec, "setup_state_changed_at": "2026-10-11T08:00:00Z"})
        v = view(decision(), late)
        self.assertEqual((v["ai"]["status"], v["ai"]["verdict"], v["source"]), ("NIEAKTUALNA", None, "STRATEGIA"))
        v = view(decision(), build(decision(), agent_status={"state": "AI_UNAVAILABLE_NO_KEY"}))
        self.assertEqual(v["ai"]["status"], "AI_NIEDOSTEPNE")

    def test_same_decision_ids(self):
        d = decision()
        d["decision_id"] = "MQD-1"
        sig = build(d)
        v = view(d, sig)
        self.assertEqual((v["snapshot_id"], v["decision_id"], v["signal_id"]), (d["snapshot_id"], "MQD-1", sig["signal_id"]))

    def test_tf_overview_conflict_and_forming(self):
        bars = []
        for i in range(120):
            bars.append({"open_utc": f"2026-10-10T{i // 60:02d}:{i % 60:02d}:00Z", "c": 2500 - i, "closed": True})
        bars.append({"open_utc": "2026-10-10T02:00:00Z", "c": 2380, "closed": False})
        rows = sv.tf_overview({"H8": bars, "H4": bars}, {"H8": {"status": "OK"}}, entry_tf="M30", plan_side="BUY", h8_filter=True)
        h8 = next(r for r in rows if r["tf"] == "H8")
        self.assertEqual((h8["direction"], h8["forming"], h8["conflict"]), ("DOWN", True, True))
        self.assertIn("blokuje", h8["conflict_impact"])
        h4 = next(r for r in rows if r["tf"] == "H4")
        self.assertIn("informacyjnie", h4["conflict_impact"])
        m1 = next(r for r in rows if r["tf"] == "M1")
        self.assertEqual((m1["direction"], m1["data"]), (None, "BRAK_DANYCH"))
        self.assertEqual(len(rows), 8)


if __name__ == "__main__":
    unittest.main()
