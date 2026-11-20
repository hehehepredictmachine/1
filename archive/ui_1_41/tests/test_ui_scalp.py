"""1.12 scalp panel in a real browser (Chromium + demo backend on the SYNTHETIC terminal): the section on "Wykresy bota",
six views (MTF, Setup, Wskaźniki, Prognozy, Hedge/ryzyko, Trening), separate validity statuses with EXECUTION_AUTHORIZED
false, adapters without values (PAL02M = UNDOCUMENTED_EXTERNAL), forecasts UNAVAILABLE without a model, the API never
reports an order permission, no POST from the panel, no horizontal scroll at 390 px. Screenshots: data/logs/ui_scalp/.
Skipped (never "passed") without Playwright/Chromium."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
import urllib.request

import _env
from _env import TempData, wait_for

PORT = 8796
BASE = f"http://127.0.0.1:{PORT}"
CHROMIUM = os.environ.get("MQ_CHROMIUM", "/opt/pw-browsers/chromium")
SHOTS = _env.ROOT / "data" / "logs" / "ui_scalp"
try:
    from playwright.sync_api import sync_playwright
    HAVE_PW = True
except ImportError:  # pragma: no cover
    HAVE_PW = False


def health():
    try:
        with urllib.request.urlopen(BASE + "/api/v1/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


@unittest.skipUnless(HAVE_PW, "playwright not installed")
class TestScalpUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (_env.ROOT / "frontend" / "dist" / "index.html").exists():
            raise unittest.SkipTest("frontend not built")
        SHOTS.mkdir(parents=True, exist_ok=True)
        cls.td = TempData()
        with open(os.path.join(cls.td.dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"server": {"port": PORT, "open_browser": False}, "news": {"enabled": False}, "clock": {"reference_url": None},
                       "first_run_completed": True}, f)
        cls.env = dict(os.environ, MASTERQUO_DATA_DIR=cls.td.dir, PYTHONPATH=str(_env.ROOT / "backend"))
        cls.env.pop("ANTHROPIC_API_KEY", None)
        cls.proc = subprocess.Popen([sys.executable, "-m", "masterquo", "serve", "--demo", "--no-browser"], env=cls.env, cwd=str(_env.ROOT / "backend"),
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not wait_for(health, 60, 0.5):
            cls.proc.kill()
            raise RuntimeError("server did not start")
        cls.pw = sync_playwright().start()
        kw = {"executable_path": CHROMIUM} if os.path.exists(CHROMIUM) else {}
        cls.browser = cls.pw.chromium.launch(**kw)
        cls.ctx = cls.browser.new_context(viewport={"width": 1366, "height": 900})
        cls.page = cls.ctx.new_page()
        cls.errors, cls.posts = [], []
        cls.page.on("pageerror", lambda e: cls.errors.append(str(e)))
        cls.page.on("request", lambda r: cls.posts.append(r.url) if r.method == "POST" else None)
        cls.page.goto(BASE + "/#/wykresy")
        cls.page.wait_for_selector("[data-testid=scalp-panel]", timeout=30000)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.browser.close()
            cls.pw.stop()
        finally:
            subprocess.run([sys.executable, "-m", "masterquo", "stop"], env=cls.env, cwd=str(_env.ROOT / "backend"), timeout=60)
            try:
                cls.proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                cls.proc.kill()
            cls.td.close()

    def test_01_api_shadow_no_permission(self):
        p = self.page
        wait_for(lambda: p.request.get(BASE + "/api/v1/scalp").json().get("status") == "SHADOW", 60, 1.0)
        d = p.request.get(BASE + "/api/v1/scalp").json()
        self.assertEqual(d["status"], "SHADOW", d.get("reason"))
        self.assertFalse(d["execution_permission"])
        self.assertEqual(d["config"]["mode"], "SHADOW")
        self.assertFalse(d["config"]["live_trading"] or d["config"]["ml_execution"] or d["config"]["hedge_execution"])
        self.assertFalse(d["statuses"]["EXECUTION_AUTHORIZED"]["value"])
        self.assertEqual({a["adapter"]: a["status"] for a in d["adapters"]}["PAL02M"], "UNDOCUMENTED_EXTERNAL")
        self.assertEqual(d["forecasts"]["status"], "UNAVAILABLE")
        self.assertEqual(len(d["mtf"]), 5)

    def test_02_six_views(self):
        p = self.page
        wait_for(lambda: "SHADOW" in (p.locator("[data-testid=scalp-status]").inner_text() or ""), 60, 1.0)
        self.assertIn("EXECUTION_AUTHORIZED: false", p.locator("[data-testid=scalp-validity]").inner_text())
        for tab, sel in (("mtf", "scalp-mtf"), ("setup", "scalp-setup"), ("ind", "scalp-adapters"), ("fc", "scalp-forecast"),
                         ("hedge", "scalp-hedge"), ("train", "scalp-training")):
            p.locator(f"[data-testid=scalp-tab-{tab}]").click()
            p.wait_for_selector(f"[data-testid={sel}]", timeout=10000)
            p.locator("[data-testid=sec-scalp]").screenshot(path=str(SHOTS / f"scalp_{tab}.png"))
        p.locator("[data-testid=scalp-tab-ind]").click()
        self.assertIn("UNDOCUMENTED_EXTERNAL", p.locator("[data-testid=scalp-adapters]").inner_text())
        p.locator("[data-testid=scalp-tab-train]").click()
        self.assertIn("BLOCKED_NO_REAL_DATA", p.locator("[data-testid=scalp-training]").inner_text())
        self.assertIn("Brak porównania", p.locator("[data-testid=scalp-variants]").inner_text())
        self.assertIn("Nie trenowano", p.locator("[data-testid=scalp-model-b]").inner_text())
        p.locator("[data-testid=scalp-tab-mtf]").click()
        self.assertEqual(p.locator("[data-testid=scalp-mtf] tbody tr").count(), 5)
        self.assertFalse([u for u in self.posts if "/scalp" in u])
        self.assertEqual(self.errors, [])

    def test_03_mobile_no_horizontal_scroll(self):
        p = self.page
        p.set_viewport_size({"width": 390, "height": 844})
        for tab in ("mtf", "setup", "ind", "fc", "hedge", "train"):
            p.locator(f"[data-testid=scalp-tab-{tab}]").click()
            p.wait_for_timeout(200)
            self.assertTrue(p.evaluate("() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"), tab)
        p.locator("[data-testid=sec-scalp]").screenshot(path=str(SHOTS / "scalp_mobile.png"))
        p.set_viewport_size({"width": 1366, "height": 900})


if __name__ == "__main__":
    unittest.main()
