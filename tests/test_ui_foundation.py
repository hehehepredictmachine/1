"""1.37 "Modele prognoz" (Kronos-base · Chronos-2 · Granite TTM; 1.40: FinCast retired) - real server process on the SYNTHETIC terminal (--demo) + Chromium.

Without weights for Chronos-2 / Granite TTM (an empty weights root): the API says so (no forecast is invented), every model stays SHADOW
without order permission, the role can be changed only through /use (settings PUT with "use" is refused), ASSIST / REQUIRED is refused
without confirmation and without a positive walk-forward report, the contract rows carry no result and a reason, the comparison has no
comparable rows. The panel (collapsed section on the "Wykresy bota" page) renders the status table, the three line toggles, the
install / verify / refresh buttons and the honest "no forecast" message without page errors."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

import _env

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_ui_kronos import CHROMIUM, HAVE_PW, SHOTS, Server  # noqa: E402


@unittest.skipUnless(HAVE_PW, "playwright not installed")
class TestFoundationUI(unittest.TestCase):
    def test_not_installed_honest_state_guards_and_panel(self):
        empty = tempfile.mkdtemp(prefix="tsfm_empty_")
        srv = Server(8817, extra_env={"MQ_KRONOS_PYTHON": ""})
        os.makedirs(os.path.join(srv.dir, "tsfm"), exist_ok=True)
        try:
            c, r = srv.call("/api/v1/models/foundation/settings", {"weights_root": empty}, method="PUT")
            self.assertEqual(c, 200, r)
            c, st = srv.call("/api/v1/models/foundation")
            self.assertEqual((c, st["mode"], st["execution_permission"]), (200, "SHADOW", False))
            self.assertEqual(set(st["models"]), {"chronos2", "granite_ttm"})
            self.assertEqual(st["kronos"]["name"], "Kronos-base")
            for m in ("chronos2", "granite_ttm"):
                self.assertFalse(st["models"][m]["env"]["weights_installed"])
                self.assertNotEqual(st["models"][m]["status"], "READY")
            # role only through /use; ASSIST / REQUIRED need confirmation AND a positive report
            c, r = srv.call("/api/v1/models/foundation/settings", {"models": {"granite_ttm": {"use": {"ACTIVE": {"use": "REQUIRED"}}}}}, method="PUT")
            self.assertEqual(c, 400)
            c, r = srv.call("/api/v1/models/foundation/use", {"model": "chronos2", "path": "SCALPING", "use": "ASSIST"})
            self.assertEqual(c, 409)
            self.assertIn("CONFIRMATION_REQUIRED", r.get("detail", ""))
            c, r = srv.call("/api/v1/models/foundation/use", {"model": "granite_ttm", "path": "ACTIVE", "use": "REQUIRED", "confirm": True})
            self.assertEqual(c, 409)
            self.assertIn("VALIDATION_REQUIRED", r.get("detail", ""))
            self.assertEqual(srv.call("/api/v1/models/foundation/forecast?model=kronos-large&instrument=XAUUSD&tf=M5")[0], 400)
            c, f = srv.call("/api/v1/models/foundation/forecast?model=granite_ttm&instrument=XAUUSD&tf=M5")
            self.assertEqual((c, f["forecast"]), (200, None))
            c, cmp = srv.call("/api/v1/models/foundation/compare?instrument=XAUUSD&tf=M5")
            self.assertEqual(c, 200)
            self.assertFalse(any(r["comparable"] for r in cmp["rows"]))
            self.assertIsNone(cmp["summary"])
            preds = {x["model_key"]: x for x in srv.call("/api/v1/models/predictions?instrument=XAUUSD")[1]["items"] if x.get("model_key")}
            for m in ("chronos2_M5", "chronos2_M15", "granite_ttm_M5", "granite_ttm_M15"):
                self.assertIn(m, preds)
                self.assertIsNone(preds[m]["result"])
                self.assertTrue(preds[m]["unavailable_reason"])
            # 1.40 FinCast retired: no forecast / role / install any more, its history id stays readable
            self.assertEqual(srv.call("/api/v1/models/foundation/forecast?model=fincast&instrument=XAUUSD&tf=M5")[0], 400)
            self.assertEqual(srv.call("/api/v1/models/foundation/install", {"model": "fincast"})[0], 400)
            self.assertEqual(srv.call("/api/v1/models/foundation/history?model=fincast&instrument=XAUUSD")[0], 200)
            self.assertIn("fincast", st["retired"])
            # 1.40 Granite training + Memory Governor API
            c, gr = srv.call("/api/v1/models/foundation/granite")
            self.assertEqual((c, gr["checkpoint"], gr["runs"]), (200, "BASE", []))
            self.assertEqual(srv.call("/api/v1/models/foundation/granite/activate", {"run_id": "../x"})[0], 400)
            self.assertEqual(srv.call("/api/v1/models/foundation/granite/activate", {"run_id": "GTR-NOTHERE"})[0], 409)
            c, r = srv.call("/api/v1/models/foundation/granite/train", {"instrument": "XAUUSD", "tf": "M5"})
            self.assertEqual(c, 409)                                              # no .venv_granite / no exported history in the demo
            c, res = srv.call("/api/v1/resources")
            self.assertEqual((c, res["profile"], res["settings"]["heavy_parallelism"]), (200, "LOW_MEMORY_16GB", 1))
            self.assertIsNotNone(res["system"]["total_mb"])
            self.assertIn("bot", res["processes"])
            c, res = srv.call("/api/v1/resources/profile", {"profile": "ECO"}, method="PUT")
            self.assertEqual((c, res["profile"]), (200, "ECO"))
            self.assertEqual(srv.call("/api/v1/resources/profile", {"profile": "TURBO"}, method="PUT")[0], 400)
            self.assertEqual(srv.call("/api/v1/models/foundation/settings", {"models": {"granite_ttm": {"checkpoint": "GTR-ABCDEF"}}}, method="PUT")[0], 400)
            ui = self._browse(srv)
            self.assertEqual(ui["errors"], [])
            self.assertEqual(ui["rows"], [1, 1, 1])
            self.assertEqual(ui["buttons"], [1, 1, 1, 1, 1, 1])
            self.assertEqual(ui["toggles"], [1, 1, 1])
            self.assertEqual(ui["no_forecast"], 1)
            self.assertIn("zgoda na zlecenia: NIE", ui["text"])
            self.assertNotIn("prawdopodobie", ui["status_text"].lower())
            self.assertEqual((ui["granite_section"], ui["resources"]), (1, 1))
        finally:
            srv.stop()

    def _browse(self, srv):
        from playwright.sync_api import sync_playwright
        SHOTS.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as pw:
            br = pw.chromium.launch(**({"executable_path": CHROMIUM} if os.path.exists(CHROMIUM) else {}))
            p = br.new_page(viewport={"width": 1600, "height": 1100})
            errors = []
            p.on("pageerror", lambda e: errors.append(str(e)))
            p.goto(srv.base + "/#/wykresy")
            p.wait_for_selector("[data-testid=sec-foundation]", timeout=60000)
            p.locator("[data-testid=sec-foundation] > summary").click()
            p.wait_for_selector("[data-testid=fm-status]", timeout=30000)
            p.wait_for_timeout(2500)
            out = {"errors": errors, "text": p.locator("[data-testid=fm-panel]").inner_text(),
                   "status_text": p.locator("[data-testid=fm-status]").inner_text(),
                   "rows": [p.locator(f"[data-testid=fm-row-{m}]").count() for m in ("kronos", "chronos2", "granite_ttm")],
                   "buttons": [p.locator(f"[data-testid=fm-{b}-{m}]").count() for m in ("chronos2", "granite_ttm") for b in ("install", "verify", "refresh")],
                   "toggles": [p.locator(f"[data-testid=fm-toggle-{m}]").count() for m in ("kronos", "chronos2", "granite_ttm")],
                   "no_forecast": p.locator("[data-testid=fm-no-forecast]").count(),
                   "granite_section": p.locator("[data-testid=fm-granite]").count(), "resources": p.locator("[data-testid=fm-resources]").count()}
            p.locator("[data-testid=sec-foundation]").screenshot(path=str(SHOTS / "foundation_not_installed.png"))
            br.close()
        return out


if __name__ == "__main__":
    unittest.main()
