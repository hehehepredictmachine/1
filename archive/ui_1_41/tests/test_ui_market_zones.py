"""'Strefy rynkowe' in the panel (Chromium on the demo bot = terminal simulator, SYNTHETIC data - only the mechanics are tested):
the button computes and draws zones on M1 / M5 / M15 / M30, a double click is one job, a zone opens its details with the checklist,
TF toggles change the charts, an instrument switch (XAUUSD -> BTC) never shows the other instrument's zones, live on / stop, and the
analysis changes neither the execution mode nor the configuration and opens no position.
Screenshots: data/logs/ui_market_zones/. Skipped (never "passed") without Playwright/Chromium."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
import urllib.request

import _env
from _env import TempData, wait_for

CHROMIUM = os.environ.get("MQ_CHROMIUM", "/opt/pw-browsers/chromium")
SHOTS = _env.ROOT / "data" / "logs" / "ui_market_zones"
PORT = 8791
try:
    from playwright.sync_api import sync_playwright
    HAVE_PW = True
except ImportError:  # pragma: no cover
    HAVE_PW = False


def up(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


@unittest.skipUnless(HAVE_PW, "playwright not installed")
class TestMarketZonesUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (_env.ROOT / "frontend" / "dist" / "index.html").exists():
            raise unittest.SkipTest("frontend not built")
        SHOTS.mkdir(parents=True, exist_ok=True)
        cls.td = TempData()
        with open(os.path.join(cls.td.dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"server": {"port": PORT, "open_browser": False}, "news": {"enabled": False}, "clock": {"reference_url": None},
                       "first_run_completed": True,
                       "assets": {"active": "XAUUSD", "mappings": {"XAUUSD": {"broker_symbol": "XAUUSD-", "status": "USER_SPECIFIED"},
                                                                   "BTC": {"broker_symbol": "BTCUSD-", "status": "USER_SPECIFIED"}}}}, f)
        cls.env = dict(os.environ, MASTERQUO_DATA_DIR=cls.td.dir, PYTHONPATH=str(_env.ROOT / "backend"))
        cls.env.pop("ANTHROPIC_API_KEY", None)
        cls.proc = subprocess.Popen([sys.executable, "-m", "masterquo", "serve", "--demo", "--no-browser"], env=cls.env, cwd=str(_env.ROOT / "backend"),
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not wait_for(lambda: up(PORT), 90, 0.5):
            cls.proc.kill()
            raise RuntimeError("bot did not start")
        cls.pw = sync_playwright().start()
        kw = {"executable_path": CHROMIUM} if os.path.exists(CHROMIUM) else {}
        cls.browser = cls.pw.chromium.launch(**kw)

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

    def api(self, p, path):
        return p.evaluate("async (u) => (await fetch(u, {credentials: 'same-origin'})).json()", path)

    def test_zones_button_charts_details_switch_live(self):
        ctx = self.browser.new_context(viewport={"width": 1600, "height": 1000})
        p = ctx.new_page()
        errors = []
        p.on("pageerror", lambda e: errors.append(str(e)))
        try:
            p.goto(f"http://127.0.0.1:{PORT}/#/strefy")
            p.wait_for_selector("[data-testid=page-strefy]", timeout=60000)
            self.assertTrue(wait_for(lambda: self.api(p, "/api/v1/market-zones?instrument=XAUUSD")["symbol"] == "XAUUSD-", 30, 0.5))
            before = self.api(p, "/api/v1/config")
            st0 = self.api(p, "/api/v1/state")
            # the terminal clock offset must be measured before candles carry UTC times
            self.assertTrue(wait_for(lambda: self.api(p, "/api/v1/market-zones/bars?instrument=XAUUSD&tf=M1&count=30")["bars"], 60, 0.5))
            p.click("[data-testid=mz-compute]")
            p.click("[data-testid=mz-compute]")                                   # double click = the same job
            p.wait_for_selector("[data-testid=mz-job][data-status=DONE]", timeout=60000)
            v = self.api(p, "/api/v1/market-zones?instrument=XAUUSD")
            self.assertGreaterEqual(v["counters"]["deduplicated_clicks"], 1)
            self.assertEqual(v["counters"]["jobs"], 1)
            for tf in ("M1", "M5", "M15", "M30"):
                self.assertEqual(v["timeframes"][tf]["status"]["status"], "CONNECTED", tf)
                self.assertTrue(v["timeframes"][tf]["zones"], tf)
                self.assertTrue(wait_for(lambda tf=tf: int(p.locator(f"[data-testid=mz-chart-{tf}]").get_attribute("data-zones") or 0) > 0
                                         and int(p.locator(f"[data-testid=mz-chart-{tf}]").get_attribute("data-bars") or 0) > 0, 20, 0.2), tf)
                for z in v["timeframes"][tf]["zones"]:                          # full zone record
                    for k in ("id", "instrument", "timeframe", "type", "lower", "upper", "origin_time", "detectable_from", "direction", "state",
                              "tests", "reason", "invalidation_rule", "quality", "confluence", "algo_version"):
                        self.assertIn(k, z)
                    self.assertLess(z["lower"], z["upper"])
                    self.assertIsNone(z["probability"])
            self.assertNotEqual(p.locator("[data-testid=mz-last-compute]").inner_text(), "—")
            p.screenshot(path=str(SHOTS / "01_xauusd_4tf.png"), full_page=True)
            p.locator("[data-testid=mz-zone]").first.click()
            p.wait_for_selector("[data-testid=mz-detail] [data-testid=mz-checklist] li", timeout=20000)
            self.assertIn("Wykrywalna od", p.locator("[data-testid=mz-detail]").inner_text())
            p.screenshot(path=str(SHOTS / "02_zone_detail.png"), full_page=True)
            # timeframe toggles: M1 off -> three charts
            p.click("[data-testid=mz-tf-M1]")
            self.assertTrue(wait_for(lambda: p.locator("[data-testid=mz-chart-M1]").count() == 0, 10, 0.2))
            self.assertEqual(p.locator("[data-testid^=mz-chart-M]").count(), 3)
            p.click("[data-testid=mz-tf-M1]")
            # instrument switch: never shows XAUUSD zones as BTC
            p.select_option("[data-testid=mz-instrument]", "BTC")
            self.assertTrue(wait_for(lambda: p.locator("[data-testid=mz-status-M5]").get_attribute("data-status") == "IDLE", 20, 0.2))
            p.click("[data-testid=mz-compute]")
            p.wait_for_selector("[data-testid=mz-job][data-status=DONE]", timeout=60000)
            vb = self.api(p, "/api/v1/market-zones?instrument=BTC")
            self.assertEqual(vb["symbol"], "BTCUSD-")
            self.assertTrue(all(z["instrument"] == "BTC" for r in vb["timeframes"].values() for z in r["zones"]))
            p.screenshot(path=str(SHOTS / "03_btc.png"), full_page=True)
            # live on, stop
            p.check("[data-testid=mz-live]")
            self.assertTrue(wait_for(lambda: self.api(p, "/api/v1/market-zones?instrument=BTC")["live"]["enabled"], 20, 0.3))
            p.click("[data-testid=mz-stop]")
            self.assertTrue(wait_for(lambda: not self.api(p, "/api/v1/market-zones?instrument=BTC")["live"]["enabled"], 20, 0.3))
            # the zones button changes no trading setting and opens nothing
            self.assertEqual(self.api(p, "/api/v1/config"), before)
            st1 = self.api(p, "/api/v1/state")
            self.assertEqual(st1.get("execution_mode"), st0.get("execution_mode"))
            self.assertEqual(errors, [])
        finally:
            ctx.close()


if __name__ == "__main__":
    unittest.main()
