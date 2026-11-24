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


if __name__ == "__main__":
    unittest.main()
