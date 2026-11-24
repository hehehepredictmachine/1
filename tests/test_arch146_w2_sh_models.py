"""1.46 arch, fala 2 – grupa sh_models: rejestr modeli SH (sh/models.py), katalog, sondy MM, panel treningu, pakiet SH (engine / policies),
kontekst i replay SH. Każdy test nie przechodzi na kodzie sprzed poprawki (klucze pozycji w nazwach klas).

* I0271 / I0303 / I0624 / I0352 / I0356: sonda nie raportuje SHADOW_ONLY, gdy nic nie jest w obserwacji ani nie liczy predykcji.
* I0318 / I0569 / I0586 / I0591 / I0593: udział w macierzy SH odpowiada temu, co sh/setup.py naprawdę czyta (bramka / wejście / informacja).
* I0005: oś use (OBSERVE / ASSIST / REQUIRED, ml.mode) jest widoczna w macierzy i katalogu – tylko prezentacja.
* I0014: pole runner_step to klucz training.runner.STEPS albo None (właściciel treningu poza runnerem).
* I0563 / I0660: opisy rejestru zgodne z kodem.
* I0055: legacy replay SH dostaje progi wieku danych z konfiguracji SH (jak live).
* I0861: notowanie bez znacznika czasu = BLOCK (nie świeże).
* I0743 / I0819 / I0820 / I0821 / I0822: pakiet SH – wyłącznie zaostrzenia (mniej wejść / aktywacji hedge niż dziś).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace

import _env  # noqa: F401
from _env import TempData

INST = "XAUUSD"


def _item(mid: str) -> dict:
    from masterquo.sh import models as SM
    return next(i for i in SM.REGISTRY if i["id"] == mid)


def _write(p: Path, obj: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")


class _Data(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.addCleanup(self.td.close)
        self.base = Path(self.td.dir)


# ================================================================================================ sondy SH (sh/models.probe)
class TestI0271ProbeNoSelection(_Data):
    """Rejestr ma runy, ale wskaźnik wyboru jest pusty -> nic nie jest w obserwacji: NOT_CONNECTED, udział NONE (było SHADOW_ONLY / INFO)."""

    def test_runs_without_selection_is_not_shadow_only(self):
        import mq_instruments as mi
        from masterquo.sh import models as SM
        _write(self.base / "nss" / INST / "registry.json", {"runs": {"R1": {}}, "selected": None})
        _write(self.base / "ml_scalp" / INST / "registry.json", {"runs": {"R1": {}}, "selected": {}})
        _write(self.base / "structure_intelligence" / INST / "registry.json", {"runs": {"R1": {}}, "shadow": {}})
        _write(self.base / "indicator_context" / INST / "registry.json", {"runs": {"R1": {}}, "active": None})
        _write(mi.root("forecast", INST) / "registry.json", {"runs": {"R1": {}}, "active": None})
        for mid in ("nss", "ml_scalp", "si_move", "indicator_context", "gold_forecast"):
            st = SM.probe(_item(mid), None, INST)
            self.assertEqual(st["status"], "NOT_CONNECTED", (mid, st))
            self.assertIn("żaden nie wybrany", st["reason"])
            for strat in ("SCALPING", "HEDGING"):
                self.assertEqual(SM.participation(_item(mid), st, strat)["use"], "NONE", mid)

    def test_no_runs_is_not_trained(self):
        from masterquo.sh import models as SM
        _write(self.base / "nss" / INST / "registry.json", {"runs": {}, "selected": None})
        self.assertEqual(SM.probe(_item("nss"), None, INST)["status"], "NOT_TRAINED")

    def test_si_setup_shadow_only_is_not_live(self):
        from masterquo.sh import models as SM
        p = self.base / "structure_intelligence" / INST / "registry.json"
        _write(p, {"runs": {"R1": {}}, "shadow": {"SCALP_STRUCTURE_CONTEXT_V1": {"candidate_id": "C1", "dir": "x"}}})
        st = SM.probe(_item("si_move"), None, INST)
        self.assertEqual(st["status"], "NOT_CONNECTED", st)                  # Forecaster reads only shadow[STRUCTURE_MOVE_M1_V1]
        self.assertIn("SCALP_STRUCTURE_CONTEXT_V1", st["reason"])
        _write(p, {"runs": {"R1": {}}, "shadow": {"STRUCTURE_MOVE_M1_V1": {"candidate_id": "C2", "dir": "y"}}})
        self.assertEqual(SM.probe(_item("si_move"), None, INST)["status"], "SHADOW_ONLY")


class TestI0303ProbeFlowReaction(_Data):
    def test_selected_shadow_without_live_path_is_not_connected(self):
        from masterquo.sh import models as SM
        _write(self.base / "flow_context" / INST / "registry.json",
               {"runs": {"R1": {}}, "shadow": {"FLOW_CONTEXT_MOVE_M1_V1": {"candidate_id": "C1", "dir": "x", "model_hash": "h"}}})
        st = SM.probe(_item("flow_reaction"), None, INST)
        self.assertEqual(st["status"], "NOT_CONNECTED", st)                  # nothing loads the reaction model live (Markov3 only)
        self.assertIn("C1", st["reason"])
        self.assertIn("bez ścieżki inferencji na żywo", st["reason"])
        self.assertEqual(SM.participation(_item("flow_reaction"), st, "SCALPING")["use"], "NONE")


class TestI0624ProbeScalpB(_Data):
    def test_active_run_without_setup_model_is_not_trained(self):
        import mq_instruments as mi
        from masterquo.sh import models as SM
        p = mi.root("scalp", INST) / "registry.json"
        _write(p, {"runs": {"R1": {"task_b_status": "INSUFFICIENT"}}, "active": "R1"})
        st = SM.probe(_item("scalp_B"), None, INST)
        self.assertEqual(st["status"], "NOT_TRAINED", st)                   # worker answers NO_SETUP_MODEL for this run
        self.assertIn("INSUFFICIENT", st["reason"])
        self.assertEqual(SM.probe(_item("scalp_A"), None, INST)["status"], "SHADOW_ONLY")
        _write(p, {"runs": {"R1": {"task_b_status": "OK", "setup_model": {"file": "setup_model_LR.json", "threshold": 0.6}}}, "active": "R1"})
        st = SM.probe(_item("scalp_B"), None, INST)
        self.assertEqual(st["status"], "SHADOW_ONLY")
        self.assertEqual(st["detail"]["task_b_status"], "OK")


class TestI0352I0356MMShadowStatusHonest(_Data):
    def _promote(self, mid: str) -> str:
        from masterquo.mm import artifacts as MA
        aid = MA.save(INST, mid, {"w": [1.0, 2.0]}, {"status": "VALIDATED_SHADOW"})
        MA.promote_shadow(INST, mid, aid, "test")
        return aid

    def test_validated_pointer_without_live_inference_is_not_connected(self):
        from masterquo.sh import models as SM
        for mid, sid in (("hdc_dir3", "mm_hdc"), ("ste_flownet_ret", "mm_ste_flownet")):
            aid = self._promote(mid)
            st = SM.probe(_item(sid), None, INST)
            self.assertEqual(st["status"], "NOT_CONNECTED", (sid, st))
            self.assertIn(aid, st["reason"])
            self.assertNotIn("obserwacja", st["reason"])
            self.assertEqual(SM.participation(_item(sid), st, "SCALPING")["use"], "NONE")

    def test_event_engine_follows_the_quant_live_path(self):
        from masterquo.sh import models as SM
        self._promote("event_engine_dir3")
        self.assertEqual(SM.probe(_item("mm_event_engine"), None, INST)["status"], "SHADOW_ONLY")   # Quant EventGRU serves it
        gru = SimpleNamespace(latest={INST: {"state": "BLOCKED_DATA", "unavailable_reason": "za mało zamkniętych świec M1"}})
        rt = SimpleNamespace(quant=SimpleNamespace(event_gru=gru))
        st = SM.probe(_item("mm_event_engine"), rt, INST)
        self.assertEqual(st["status"], "DATA_MISSING", st)
        self.assertIn("za mało", st["reason"])
        gru.latest[INST] = {"state": "READY"}
        self.assertEqual(SM.probe(_item("mm_event_engine"), rt, INST)["status"], "SHADOW_ONLY")

    def test_gpr_pointer_not_claimed_as_live_source(self):
        from masterquo.mm import artifacts as MA
        from masterquo.mm import service as MS
        from masterquo.sh import models as SM
        aid = self._promote("gpr_logret")
        st = SM.probe(_item("mm_gpr"), None, INST)
        self.assertIn("nie jest wczytywany", st["reason"])
        self.assertIn(aid, st["reason"])
        self.assertNotIn("zwalidowany na danych rzeczywistych", st["reason"])
        self._promote("hdc_dir3")
        tm = MS._trained_models(MA.read_pointer(INST))
        self.assertFalse(tm["gpr_logret"].startswith("SHADOW:"), tm)
        self.assertIn("dopasowanie", tm["gpr_logret"])
        self.assertIn("brak inferencji na żywo", tm["hdc_dir3"])
        self.assertTrue(tm["ste_flownet_ret"].startswith("brak artefaktu"))

    def test_inventory_callers_match_the_code(self):
        from masterquo.mm import inventory as MI
        mods = {m["id"]: m for m in MI.MODULES}
        self.assertNotIn("mm.service", mods["hdc"]["callers"])                 # the service only lists the pointer
        self.assertTrue(any("EventGRU" in c for c in mods["event_engine"]["callers"]))

if __name__ == "__main__":
    unittest.main()
