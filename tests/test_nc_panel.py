"""Neural Cyberpunk panel (handoff V1, 11 screens) in a real browser against a REAL server process on the SYNTHETIC terminal (--demo):
every screen renders backend data, the market feed is labelled DEMO (never VERIFIED) on the simulator, the pattern library maps
36 names to the bot's detectors and marks the missing ones NOT_IMPLEMENTED, no page errors, no horizontal scroll at 1440 / 390 px,
the panel never changes the trading mode and sends no order. Screenshots: data/logs/ui_nc/. Skipped without Playwright."""
from __future__ import annotations

import os
import unittest

import _env
from _env import wait_for
import test_sh_api as T
from test_sh_api import CHROMIUM, HAVE_PW, call

SHOTS = _env.ROOT / "data" / "logs" / "ui_nc"
PAGES = ["dashboard", "market", "pattern", "validation", "training", "decision", "mt5", "liquidity", "statistics", "operations", "settings"]


@unittest.skipUnless(HAVE_PW, "playwright not installed")
class TestNeuralCyberpunk(T.TestSHApi):
    test_endpoints = test_config_change_and_rollback = test_panels_in_browser = None    # reuse only the server fixture

    def test_eleven_screens(self):
        if not (_env.ROOT / "frontend" / "dist" / "index.html").exists():
            self.skipTest("frontend not built")
        from playwright.sync_api import sync_playwright
        SHOTS.mkdir(parents=True, exist_ok=True)
        self.assertTrue(wait_for(lambda: bool(call("/api/v1/sh")[1].get("last_eval")), 120, 1.0))
        mode0 = call("/api/v1/sh")[1]["mode"]
        c, v = call("/api/v1/sh/validation?instrument=XAUUSD")
        self.assertEqual((c, v["strategies"]["SCALPING"]["status"]), (200, "NOT_RUN"))
        with sync_playwright() as pw:
            br = pw.chromium.launch(**({"executable_path": CHROMIUM} if os.path.exists(CHROMIUM) else {}))
            errors: list = []
            for w, h in ((1440, 900), (390, 844)):
                ctx = br.new_context(viewport={"width": w, "height": h})
                p = ctx.new_page()
                p.on("pageerror", lambda e: errors.append(str(e)))
                p.on("dialog", lambda d: d.accept())
                p.goto(BASE_URL() + "/#/nc?p=dashboard")
                p.wait_for_selector("[data-testid=nc-root]", timeout=30000)
                self.assertEqual(p.locator("[data-testid=nc-nav] button").count(), 11)
                for pid in PAGES:
                    p.click(f"[data-testid=nc-nav] [data-nc={pid}]")
                    p.wait_for_selector(f"[data-testid=nc-page-{pid}]", timeout=20000)
                    p.wait_for_timeout(900)
                    self.assertLessEqual(p.evaluate("document.querySelector('.nc').scrollWidth"), w + 1, f"horizontal scroll {pid} @ {w}")
                    p.screenshot(path=str(SHOTS / f"{pid}_{w}.png"), full_page=False)
                    if pid == "dashboard":
                        p.wait_for_selector("[data-testid=nc-neural] canvas")
                        self.assertNotIn("VERIFIED", p.locator("[data-testid=nc-root] header").inner_text().replace("EXECUTION", ""))
                        self.assertIn("DEMO", p.locator("[data-testid=nc-root] header").inner_text())
                    if pid == "market":
                        p.wait_for_selector("[data-testid=nc-main-chart] canvas", timeout=20000)
                        p.click("[data-testid=nc-tf-H1]")
                        self.assertEqual(p.locator("[data-testid=nc-tf]").input_value(), "H1")
                    if pid == "pattern":
                        self.assertEqual(p.locator("[data-testid=nc-patterns] .nc-pattern").count(), 36)
                        self.assertEqual(p.locator("[data-testid=nc-patterns] .nc-pattern[data-impl='0']").count(), 4)
                    if pid == "validation":
                        self.assertIn("NOT_RUN", p.locator("[data-testid=nc-val-SCALPING]").inner_text())
                    if pid == "decision" and w == 1440:
                        p.click("[data-testid=nc-dry]")
                        self.assertIn("Żadne zlecenie nie zostało wysłane", p.locator("[data-testid=nc-dry-msg]").inner_text())
                    if pid == "mt5" and w == 1440:
                        p.click("[data-testid=nc-kill]")                                   # STOP new entries (no order)
                        self.assertTrue(wait_for(lambda: "Wznów" in p.locator("[data-testid=nc-kill]").inner_text(), 15, 0.3))
                        p.click("[data-testid=nc-kill]")
                        self.assertTrue(wait_for(lambda: "STOP" in p.locator("[data-testid=nc-kill]").inner_text(), 15, 0.3))
                ctx.close()
            br.close()
        self.assertEqual(errors, [])
        self.assertEqual(call("/api/v1/sh")[1]["mode"], mode0)
        self.assertTrue(all(x["exec_mode"] == "PAPER" for x in call("/api/v1/sh/plans")[1]["items"]))     # no terminal order


def BASE_URL():
    return T.BASE


if __name__ == "__main__":
    unittest.main()
