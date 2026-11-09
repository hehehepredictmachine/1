"""1.39 WTC PEPE 2.1 Chart Lab + Session Volume Profile in a real browser (Chromium + demo backend on the SYNTHETIC MT5 terminal).

The lab draws the REAL bars of /api/v1/candles (the same feed as every chart of the bot - in the demo that is the synthetic terminal, labelled
so): CUSTOMIZE CHART opens the configurator, the five chart types switch, RSI / MACD / ATR get their own panes, a period change is persisted,
the SVP shows POC / VAH / VAL of the window or of a session, the biggest impulse for 3 / 5 / 8 / 12 bars, presets save / load / export /
import (a foreign JSON is rejected) / reset. No order, no mode change, no JS errors."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unittest
import urllib.request

import _env
from _env import TempData, wait_for

PORT = 8833
BASE = f"http://127.0.0.1:{PORT}"
CHROMIUM = os.environ.get("MQ_CHROMIUM", "/opt/pw-browsers/chromium")
SHOTS = _env.ROOT / "data" / "logs" / "ui_wtc_chartlab"
ORDER_URL = re.compile(r"/api/v1/(order|orders|trade|execution|close|positions?|plan/.*/(execute|confirm))", re.I)
MODE_URL = re.compile(r"/api/v1/mode\b", re.I)
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
class TestWtcChartLab(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (_env.ROOT / "frontend" / "dist" / "index.html").exists():
            raise unittest.SkipTest("frontend not built")
        SHOTS.mkdir(parents=True, exist_ok=True)
        cls.td = TempData()
        with open(os.path.join(cls.td.dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"server": {"port": PORT, "open_browser": False}, "news": {"enabled": False}, "clock": {"reference_url": None},
                       "first_run_completed": True}, f)
        cls.env = dict(os.environ, MASTERQUO_DATA_DIR=cls.td.dir, PYTHONPATH=str(_env.ROOT / "backend"), MQ_FAKE_MARKET_ALWAYS_OPEN="1")
        cls.env.pop("ANTHROPIC_API_KEY", None)
        cls.proc = subprocess.Popen([sys.executable, "-m", "masterquo", "serve", "--demo", "--no-browser"], env=cls.env, cwd=str(_env.ROOT / "backend"),
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not wait_for(health, 60, 0.5):
            cls.proc.kill()
            raise RuntimeError("server did not start")
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(**({"executable_path": CHROMIUM} if os.path.exists(CHROMIUM) else {}))

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

    def test_chart_lab_types_indicators_svp_presets(self):
        c = self.browser.new_context(viewport={"width": 1920, "height": 1080}, accept_downloads=True)
        p = c.new_page()
        errors, sent = [], []
        p.on("pageerror", lambda e: errors.append(str(e)))
        p.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        p.on("request", lambda r: sent.append((r.method, r.url)) if r.method != "GET" else None)
        lab = "[data-testid=wtc-lab-chart]"
        try:
            p.goto(BASE + "/#/pepe-wtc")
            p.wait_for_selector("[data-testid=wtc-chartlab]", timeout=60000)
            p.select_option("[data-testid=wtc-lab-tf]", "M5")
            p.wait_for_function(f"() => Number(document.querySelector('{lab}').dataset.bars || 0) > 50", timeout=60000)
            self.assertIn("/api/v1/candles", p.inner_text("[data-testid=wtc-lab-foot]"))
            # SVP of the whole window: POC between VAL and VAH, the same value as the price line of the chart
            poc = p.inner_text("[data-testid=wtc-lab-poc]")
            self.assertEqual(poc.replace("\u00a0", "").replace(" ", "").replace(",", "."), p.get_attribute(lab, "data-poc"))
            self.assertIn("IMPULS", p.inner_text("[data-testid=wtc-lab-impulse]").upper())
            # toolbar button opens the configurator
            p.click("[data-testid=wtc-customize]")
            p.wait_for_selector("[data-testid=wtc-lab-panel]", timeout=3000)
            for t in ("HOLLOW", "HEIKIN_ASHI", "LINE", "AREA", "CANDLES"):
                p.click(f"[data-testid=wtc-lab-type-{t}]")
                p.wait_for_function(f"() => document.querySelector('{lab}').dataset.type === '{t}'", timeout=3000)
            p.select_option("[data-testid=wtc-lab-theme]", "LIGHT")
            p.wait_for_function(f"() => document.querySelector('{lab}').dataset.theme === 'LIGHT'", timeout=3000)
            # indicators: RSI (default on) + MACD + ATR -> 4 panes; period persisted
            p.click("[data-testid=wtc-lab-tab-ind]")
            for k in ("macd", "atr", "vwap", "bb", "smc"):
                p.check(f"[data-testid=wtc-lab-ind-{k}]")
            p.wait_for_function(f"() => document.querySelector('{lab}').dataset.panes === '4'", timeout=3000)
            p.fill("[data-testid=wtc-lab-per-rsi]", "7")
            cur = p.evaluate("() => JSON.parse(localStorage.getItem('mq.wtc.chartlab.current'))")
            self.assertEqual(cur["ind"]["rsi"]["period"], 7)
            self.assertTrue(cur["ind"]["macd"]["on"] and cur["ind"]["atr"]["on"])
            p.uncheck("[data-testid=wtc-lab-ind-macd]")
            p.wait_for_function(f"() => document.querySelector('{lab}').dataset.panes === '3'", timeout=3000)
            # SVP: sessions and impulse windows
            p.click("[data-testid=wtc-lab-tab-svp]")
            for sess in ("LONDON", "NEWYORK", "ASIA", "ALL"):
                p.select_option("[data-testid=wtc-lab-session]", sess)
                p.wait_for_selector("[data-testid=wtc-lab-poc], [data-testid=wtc-lab-svp-na]", timeout=3000)
            for n in (3, 5, 8, 12):
                p.click(f"[data-testid=wtc-lab-imp-{n}]")
                p.wait_for_function(f"() => (document.querySelector('[data-testid=wtc-lab-impulse]')?.textContent || '').includes('({n} św.)')", timeout=3000)
            p.locator("[data-testid=wtc-chartlab]").screenshot(path=str(SHOTS / "chartlab_1920.png"))
            # presets
            p.click("[data-testid=wtc-lab-tab-presets]")
            p.fill("[data-testid=wtc-lab-pname]", "Scalp M5")
            p.click("[data-testid=wtc-lab-psave]")
            self.assertIn("Scalp M5", p.inner_text("[data-testid=wtc-lab-presets]"))
            with p.expect_download() as dl:
                p.click("[data-testid=wtc-lab-export]")
            with open(dl.value.path(), encoding="utf-8") as f:
                exported = json.load(f)
            self.assertEqual(exported["schema"], "PMW-CHARTLAB-1")
            self.assertEqual(exported["theme"], "LIGHT")
            p.click("[data-testid=wtc-lab-reset]")
            p.wait_for_function(f"() => document.querySelector('{lab}').dataset.theme === 'NEON'", timeout=3000)
            p.click("[data-testid=wtc-lab-pload]")
            p.wait_for_function(f"() => document.querySelector('{lab}').dataset.theme === 'LIGHT'", timeout=3000)
            p.click("[data-testid=wtc-lab-reset]")
            good = os.path.join(self.td.dir, "lab_ok.json")
            with open(good, "w", encoding="utf-8") as f:
                json.dump(exported, f)
            p.set_input_files("[data-testid=wtc-lab-import]", good)
            p.wait_for_function(f"() => document.querySelector('{lab}').dataset.theme === 'LIGHT'", timeout=3000)
            bad = os.path.join(self.td.dir, "lab_bad.json")
            with open(bad, "w", encoding="utf-8") as f:
                json.dump({"planets": []}, f)
            p.set_input_files("[data-testid=wtc-lab-import]", bad)
            p.wait_for_selector("[data-testid=wtc-lab-note]:has-text('Import odrzucony')", timeout=3000)
            self.assertEqual(p.get_attribute(lab, "data-theme"), "LIGHT")
            self.assertEqual([e for e in errors if "WebSocket" not in e and "favicon" not in e and "Failed to load resource" not in e], [])
            self.assertFalse([u for m, u in sent if ORDER_URL.search(u) or MODE_URL.search(u)], sent)
        finally:
            c.close()


if __name__ == "__main__":
    unittest.main()
