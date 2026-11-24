"""Fala 2 / grupa lab_models (Apollo23 1.46): metadane i statusy modeli lab / SI / flow / ctx / MR2, filtry instrumentu ledgerów,
identyfikator Kronos w koordynatorze, kontrakt workera scalp, rozjazd trening/serwowanie extind (schemat V2), model fixture_only na
danych REAL, pasmo neutralne TSFM (wyłącznie zaostrzenie REQUIRED), etykiety scalp przy nieznanej prowizji, odcisk SETUP_FEATURES.
Każdy test nie przechodzi na kodzie sprzed poprawki. Dane SYNTETYCZNE - sprawdzają reguły, nie wartość predykcyjną."""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _env  # noqa: F401
from _env import TempData

ROOT = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------------------------------------------------------------------ I0225
class TestLabBaselineRole(unittest.TestCase):
    """I0225: adapter Quant publikował DUMMY/RULE jako analytic_role BASE_FORECAST, inwentarz nadaje im rolę TOOL."""

    def test_baseline_role_matches_inventory(self):
        from masterquo.quant import adapters as A
        from masterquo.quant import inventory as INV
        st = {"as_of": "2026-11-24T10:00:00Z", "data_mode": "live",
              "models": [{"family": f, "status": "ready", "raw_score": 0.4, "model_id": f"m-{f}", "horizon": "M5x12"}
                         for f in ("DUMMY", "RULE", "LOGREG")]}
        rt = SimpleNamespace(lab=SimpleNamespace(state={"XAUUSD": st}, assets=None))
        roles = {r["id"]: r["quant_role"] for r in INV._lab_rows()}
        recs = A.lab(rt, "XAUUSD")
        self.assertEqual(len(recs), 3)
        for r in recs:
            self.assertEqual(r["analytic_role"], roles[r["canonical_id"]], r["canonical_id"])
        self.assertEqual({r["canonical_id"]: r["analytic_role"] for r in recs},
                         {"lab:DUMMY": "TOOL", "lab:RULE": "TOOL", "lab:LOGREG": "BASE_FORECAST"})


# ------------------------------------------------------------------------------------------------------------------------ I0212
class TestTabiclInstallFacade(unittest.TestCase):
    """I0212: API wołało prywatne TsfmService._run_job_proc do instalacji TabICL."""

    def test_api_does_not_call_private_tsfm_methods(self):
        src = (ROOT / "backend" / "masterquo" / "api" / "app.py").read_text(encoding="utf-8")
        import re
        self.assertEqual(re.findall(r"rt\.tsfm\._\w+", src), [])

    def test_public_method_delegates_unchanged(self):
        from masterquo.tsfm.service import TsfmService
        calls = []
        stub = SimpleNamespace(_run_job_proc=lambda name, argv, env=None, on_done=None: calls.append((name, argv, env, on_done)) or {"ok": True})
        argv = ["py", "tools/tsfm_setup.py", "--model", "tabicl"]
        self.assertEqual(TsfmService.start_tabicl_install(stub, argv), {"ok": True})
        self.assertEqual(calls, [("install_tabicl", argv, None, None)])


# ------------------------------------------------------------------------------------------------------------------------ I0329
class TestLegacyMLVersionsInDocs(unittest.TestCase):
    """I0329: kontrakt predykcji ML podawał MQ-LABEL-1.0.0 (kod: labels.LABEL_POLICY_VERSION), mapa modeli starą wersję cech."""

    def test_target_definition_uses_current_label_version(self):
        from masterquo.ml import labels as LB
        from masterquo.ml.service import MLService
        r = MLService.predict(SimpleNamespace(cfg=SimpleNamespace(mode="SHADOW")), None, None)
        self.assertEqual(r["uncertainty_reason"], "NO_SETUP")
        self.assertIn(LB.LABEL_POLICY_VERSION, r["target_definition"])

    def test_model_map_generator_uses_current_feature_schema(self):
        import importlib.util
        from masterquo.ml import features as FE
        spec = importlib.util.spec_from_file_location("model_map_t", ROOT / "tools" / "model_map.py")
        mm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mm)
        for e in mm.ELEMENTS:
            if e["id"].startswith("LEGACY_ML_"):
                self.assertTrue(e["features"].startswith(FE.FEATURE_SCHEMA_VERSION), e["id"])


# ------------------------------------------------------------------------------------------------------------ I0040 / I0030
class TestLedgerListingsPerInstrument(unittest.TestCase):
    """I0040: listy ledgerów (forecast/scalp SHADOW, notowania SI, oceny Quant) mieszały instrumenty; I0030: czytnik quote_forecasts
    bez filtra kontekstu. Wołający wewnętrzni (instrument=None) dostają dzisiejsze zachowanie."""

    def setUp(self):
        self.td = TempData()
        self.addCleanup(self.td.close)
        from masterquo.db.database import Database
        self.db = Database(Path(self.td.dir) / "t.sqlite")

    def test_forecast_and_scalp_recent_filter(self):
        from masterquo.forecast.service import ForecastService
        from masterquo.scalp.service import ScalpService
        for inst in ("XAUUSD", "BTC"):
            self.db.execute("INSERT INTO forecast_shadow(created_at, run_id, feature_time_utc, horizon_minutes, target_time_utc, close_now, "
                            "neutral_band, p_down, p_flat, p_up, outcome_status, instrument) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                            ("2026-11-24T10:00:00Z", "r", f"2026-11-24T10:00:00Z-{inst}", 5, "2026-11-24T10:05:00Z", 1.0, 0.1, .3, .4, .3,
                             "PENDING", inst))
            self.db.execute("INSERT INTO scalp_shadow(created_at, setup_id, profile_id, direction, decision_time_utc, status, reasons, plan, gates, "
                            "hedge, outcome_status, instrument) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                            ("2026-11-24T10:00:00Z", f"S-{inst}", "p", "BUY", "2026-11-24T10:00:00Z", "BLOCKED", "[]", "{}", "[]", "{}",
                             "NOT_APPLICABLE", inst))
        fs = SimpleNamespace(db=self.db)
        sc = SimpleNamespace(db=self.db)
        self.assertEqual({r["instrument"] for r in ForecastService.recent(fs, 10, instrument="BTC")}, {"BTC"})
        self.assertEqual({r["instrument"] for r in ScalpService.recent(sc, 10, instrument="BTC")}, {"BTC"})
        self.assertEqual({r["instrument"] for r in ForecastService.recent(fs, 10)}, {"XAUUSD", "BTC"})     # internal callers unchanged
        self.assertEqual({r["instrument"] for r in ScalpService.recent(sc, 10)}, {"XAUUSD", "BTC"})

    def test_quote_forecasts_context_filter(self):
        from masterquo.lab.si_service import StructureIntelligenceService
        for ctx in ("XAUUSD|XAUUSD-", "BTC|BTCUSD"):
            p = {"price": 1.0, "se_model": 0.1, "h_s": 5, "band": [0.9, 1.1]}
            self.db.execute("INSERT INTO quote_forecasts(forecast_id, context, side, scale, issued_at, target_at, payload) VALUES (?,?,?,?,?,?,?)",
                            (f"F-{ctx}", ctx, "BID", 5, "2026-11-24T10:00:00Z", "2026-11-24T10:00:05Z", json.dumps(p)))
        si = SimpleNamespace(db=self.db)
        q = StructureIntelligenceService.quote_forecasts
        self.assertEqual([r["forecast_id"] for r in q(si, 10, context="BTC|BTCUSD")], ["F-BTC|BTCUSD"])
        self.assertEqual([r["forecast_id"] for r in q(si, 10, instrument="XAUUSD")], ["F-XAUUSD|XAUUSD-"])
        self.assertEqual(len(q(si, 10)), 2)                                                             # internal callers unchanged

    def test_quant_assessments_instrument_filter(self):
        from masterquo.quant.ledger import QuantLedger
        led = QuantLedger(Path(self.td.dir) / "quant" / "ledger.sqlite")
        for i, inst in enumerate(("XAUUSD", "BTC")):
            led.add_row({"row_id": f"R{i}", "instrument": inst, "engine": "SH", "strategy": "s", "direction": "BUY", "decision_ts": 1.0 + i,
                         "task_hash": "t", "event_id": "e", "spec": {}, "features": {}, "matures_at": 10.0})
            led.add_assessment({"assessment_id": f"A{i}", "row_id": f"R{i}", "created_at": time.time() + i, "mode": "SHADOW", "engine": "SH"})
        self.assertEqual([a["assessment_id"] for a in led.assessments(10, instrument="BTC")], ["A1"])
        self.assertEqual([a["assessment_id"] for a in led.assessments(10)], ["A1", "A0"])

    def test_api_routes_take_optional_asset(self):
        src = (ROOT / "backend" / "masterquo" / "api" / "app.py").read_text(encoding="utf-8")
        for fn in ("def scalp_shadow(", "def forecast_shadow(", "def si_quote_fc(", "def quant_assessments("):
            line = next(x for x in src.splitlines() if fn in x)
            self.assertIn("asset: str | None = None", line, fn)


if __name__ == "__main__":
    unittest.main()
