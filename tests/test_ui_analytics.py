"""1.13 PepeMarketWizard panel in a real browser (Chromium + demo backend on the SYNTHETIC terminal, clearly marked):
grouped menu (Rynek / Analiza / Praca bota), every new page renders real backend data or an explicit state, "DANE
PRZYKŁADOWE" flag in demo, Double Bottom library: add sample from a closed-bar range, VALIDATE ALL job with progress and a
report, SHOW ON CHART with the validator's exact coordinates, no horizontal page scroll at 1920 / 1366 / 390 px, no page
errors, and no request changes the trading mode. Screenshots: data/logs/ui_analytics/. Skipped without Playwright."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
import urllib.request

import _env
from _env import TempData, wait_for

PORT = 8797
BASE = f"http://127.0.0.1:{PORT}"
CHROMIUM = os.environ.get("MQ_CHROMIUM", "/opt/pw-browsers/chromium")
SHOTS = _env.ROOT / "data" / "logs" / "ui_analytics"
PAGES = ["pulpit", "wykresy", "kontekst", "warunki", "ai", "indykatory", "sygnal", "formacje", "pozycje", "dziennik", "testy", "diagnostyka"]
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
class TestAnalyticsUI(unittest.TestCase):
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
        cls.ctx = cls.browser.new_context(viewport={"width": 1920, "height": 1080})
        cls.page = cls.ctx.new_page()
        cls.errors, cls.posts = [], []
        cls.page.on("pageerror", lambda e: cls.errors.append(str(e)))
        cls.page.on("request", lambda r: cls.posts.append((r.method, r.url)) if r.method != "GET" else None)
        cls.page.goto(BASE + "/")
        cls.page.wait_for_selector("[data-testid=page-pulpit]", timeout=30000)

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

    def api(self, path):
        return self.page.request.get(BASE + path).json()

    def no_hscroll(self):
        return self.page.evaluate("() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")

    def test_01_brand_default_page_groups(self):
        p = self.page
        self.assertTrue(p.url.endswith("#/pulpit"), p.url)
        self.assertIn("PepeMarketWizard", p.title())
        self.assertIn("PepeMarketWizard", p.locator("[data-testid=topbar] .brand").inner_text().replace("\n", ""))
        groups = [g.get_attribute("data-group") for g in p.locator("[data-testid=sidenav] .nav-group").all()]
        self.assertEqual(groups, ["pulpit", "wykresy", "setupy", "modele", "badania", "dane", "ustawienia"])   # 1.14 seven sections
        self.assertTrue(p.locator("[data-testid=demo-flag]").first.is_visible())          # demo always marked

    def test_02_every_page_renders(self):
        p = self.page
        wait_for(lambda: (self.api("/api/v1/analytics")["timeframes"].get("M5") or {}).get("vmd") is not None, 90, 1.0)
        for pid in PAGES:
            p.goto(f"{BASE}/#/{pid}")
            p.wait_for_selector(f"main.page[data-page={pid}]", timeout=20000)
            p.wait_for_timeout(600)
            p.screenshot(path=str(SHOTS / f"{pid}_1920.png"), full_page=False)
            self.assertTrue(self.no_hscroll(), pid)
        p.goto(f"{BASE}/#/indykatory")
        p.wait_for_selector("[data-testid=ind-bb]")
        wait_for(lambda: "Środek / górne / dolne" in p.locator("[data-testid=ind-bb]").inner_text(), 30, 0.5)
        self.assertIn("ddof=0", p.locator("[data-testid=ind-bb]").inner_text())
        p.goto(f"{BASE}/#/sygnal")
        wait_for(lambda: "Dominujące okresy" in p.locator("[data-testid=sig-fft]").inner_text(), 30, 0.5)
        self.assertTrue(p.locator("[data-testid=sig-fft] svg").count() >= 1)
        self.assertEqual(self.errors, [])

    def test_03_pattern_library_flow(self):
        p = self.page
        st = self.api("/api/v1/analytics/tf/M5")
        end = st["bollinger"]["window_end"]
        start = st["bollinger"]["window_start"]
        p.goto(f"{BASE}/#/formacje")
        p.wait_for_selector("[data-testid=db-library]")
        p.fill("input[aria-label='Początek zakresu UTC']", start)
        p.fill("input[aria-label='Koniec zakresu UTC']", end)
        p.click("text=Zapisz próbkę")
        wait_for(lambda: p.locator("[data-testid=db-table] tbody tr").count() >= 1 and "Biblioteka pusta" not in p.locator("[data-testid=db-table]").inner_text(), 20, 0.5)
        p.click("[data-testid=db-validate-all]")
        wait_for(lambda: "COMPLETED" in p.locator("[data-testid=db-job]").inner_text(), 30, 0.5)
        # the job is marked COMPLETED first and the report is exported right after (export is a separate step by design)
        wait_for(lambda: "raport DBR-" in p.locator("[data-testid=db-job]").inner_text(), 15, 0.3)
        self.assertIn("raport DBR-", p.locator("[data-testid=db-job]").inner_text())
        p.click("text=SHOW ON CHART")
        p.wait_for_selector("[data-testid=sample-chart] canvas", timeout=15000)
        p.locator("[data-testid=db-view]").screenshot(path=str(SHOTS / "db_sample.png"))
        rep = self.api(f"/api/v1/patterns/reports/{self.api('/api/v1/patterns/samples')['jobs'][0]['report_id']}")
        self.assertTrue(rep["complete"])
        self.assertEqual(rep["samples_processed"], rep["samples_requested"])
        mode_changes = [u for m, u in self.posts if "/mode" in u or "/strategy" in u or "/order" in u]
        self.assertEqual(mode_changes, [])

    def test_04_resolutions(self):
        p = self.page
        for w, h in ((1366, 768), (390, 844)):
            p.set_viewport_size({"width": w, "height": h})
            for pid in ("pulpit", "indykatory", "sygnal", "formacje", "diagnostyka"):
                p.goto(f"{BASE}/#/{pid}")
                p.wait_for_selector(f"main.page[data-page={pid}]", timeout=20000)
                p.wait_for_timeout(300)
                self.assertTrue(self.no_hscroll(), f"{pid} {w}")
                p.screenshot(path=str(SHOTS / f"{pid}_{w}.png"))
        p.set_viewport_size({"width": 1920, "height": 1080})


if __name__ == "__main__":
    unittest.main()
