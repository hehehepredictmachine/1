"""1.37 "Modele prognoz" (Kronos-base · Chronos-2 · FinCast) - real server process on the SYNTHETIC terminal (--demo) + Chromium.

Without weights for Chronos-2 / FinCast (an empty weights root): the API says so (no forecast is invented), every model stays SHADOW
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
            self.assertEqual(set(st["models"]), {"chronos2", "fincast"})
            self.assertEqual(st["kronos"]["name"], "Kronos-base")
            for m in ("chronos2", "fincast"):
                self.assertFalse(st["models"][m]["env"]["weights_installed"])
                self.assertNotEqual(st["models"][m]["status"], "READY")
            # role only through /use; ASSIST / REQUIRED need confirmation AND a positive report
            c, r = srv.call("/api/v1/models/foundation/settings", {"models": {"fincast": {"use": {"ACTIVE": {"use": "REQUIRED"}}}}}, method="PUT")
            self.assertEqual(c, 400)
            c, r = srv.call("/api/v1/models/foundation/use", {"model": "chronos2", "path": "SCALPING", "use": "ASSIST"})
            self.assertEqual(c, 409)
            self.assertIn("CONFIRMATION_REQUIRED", r.get("detail", ""))
            c, r = srv.call("/api/v1/models/foundation/use", {"model": "fincast", "path": "ACTIVE", "use": "REQUIRED", "confirm": True})
            self.assertEqual(c, 409)
            self.assertIn("VALIDATION_REQUIRED", r.get("detail", ""))
            self.assertEqual(srv.call("/api/v1/models/foundation/forecast?model=kronos-large&instrument=XAUUSD&tf=M5")[0], 400)
            c, f = srv.call("/api/v1/models/foundation/forecast?model=fincast&instrument=XAUUSD&tf=M5")
            self.assertEqual((c, f["forecast"]), (200, None))
            c, cmp = srv.call("/api/v1/models/foundation/compare?instrument=XAUUSD&tf=M5")
            self.assertEqual(c, 200)
            self.assertFalse(any(r["comparable"] for r in cmp["rows"]))
            self.assertIsNone(cmp["summary"])
            preds = {x["model_key"]: x for x in srv.call("/api/v1/models/predictions?instrument=XAUUSD")[1]["items"] if x.get("model_key")}
            for m in ("chronos2_M5", "chronos2_M15", "fincast_M5", "fincast_M15"):
                self.assertIn(m, preds)
                self.assertIsNone(preds[m]["result"])
                self.assertTrue(preds[m]["unavailable_reason"])
            ui = self._browse(srv)
            self.assertEqual(ui["errors"], [])
            self.assertEqual(ui["rows"], [1, 1, 1])
            self.assertEqual(ui["buttons"], [1, 1, 1, 1, 1, 1])
            self.assertEqual(ui["toggles"], [1, 1, 1])
            self.assertEqual(ui["no_forecast"], 1)
            self.assertIn("zgoda na zlecenia: NIE", ui["text"])
            self.assertNotIn("prawdopodobie", ui["status_text"].lower())
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
                   "rows": [p.locator(f"[data-testid=fm-row-{m}]").count() for m in ("kronos", "chronos2", "fincast")],
                   "buttons": [p.locator(f"[data-testid=fm-{b}-{m}]").count() for m in ("chronos2", "fincast") for b in ("install", "verify", "refresh")],
                   "toggles": [p.locator(f"[data-testid=fm-toggle-{m}]").count() for m in ("kronos", "chronos2", "fincast")],
                   "no_forecast": p.locator("[data-testid=fm-no-forecast]").count()}
            p.locator("[data-testid=sec-foundation]").screenshot(path=str(SHOTS / "foundation_not_installed.png"))
            br.close()
        return out


if __name__ == "__main__":
    unittest.main()
