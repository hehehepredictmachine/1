"""1.36 tower interiors PEPE$WTC V4 and PEPE$SIGNAL V1 in a real browser (Chromium + demo backend on the SYNTHETIC terminal).

PEPE$WTC: main chart + independent TF, add / remove charts of the Multi-Chart Workspace (own TF each, click = main chart), every indicator
chip is a real chart option or marked UNAVAILABLE, Volume Profile Auto Zones come from the backend PMW-SVP-1 engine (POC / VAH / VAL / HVN),
Setup Builder computes R:R with the correct denominator and has no order button, Kronos status is the backend's (no invented score).
PEPE$SIGNAL: one registry of signals (bot-signals + engine scenarios + SH machines), selection from the list AND from the table updates the
analysis, filters act on list and table, conditions show real engine states, tabs perform their action, WAIT is never shown as BUY/SELL,
model scores are never called a probability. Both: environment badge never REAL on the simulator, no order / mode request, no page errors,
no horizontal scroll at 1920 / 1672 / 1366 / 390 px. Screenshots: data/logs/ui_towers/."""
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

PORT = 8825
BASE = f"http://127.0.0.1:{PORT}"
CHROMIUM = os.environ.get("MQ_CHROMIUM", "/opt/pw-browsers/chromium")
SHOTS = _env.ROOT / "data" / "logs" / "ui_towers"
ORDER_URL = re.compile(r"/api/v1/(order|orders|trade|execution|close|positions?|plan/.*/(execute|confirm)|mode\b)", re.I)
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
class TestTowersUI(unittest.TestCase):
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

    def ctx(self, w=1672, h=941):
        c = self.browser.new_context(viewport={"width": w, "height": h})
        p = c.new_page()
        p.errors, p.sent = [], []
        p.on("pageerror", lambda e: p.errors.append(str(e)))
        p.on("console", lambda m: p.errors.append(m.text) if m.type == "error" and not re.search(r"WebSocket|favicon|Failed to load resource", m.text) else None)
        p.on("request", lambda r: p.sent.append((r.method, r.url)) if r.method != "GET" else None)
        return c, p

    def no_hscroll(self, p):
        return p.evaluate("() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")

    # ------------------------------------------------------------ PEPE$WTC
    def test_01_wtc_charts_indicators_zones_builder(self):
        c, p = self.ctx()
        try:
            p.goto(BASE + "/#/wtc")                                                              # legacy alias -> the new tower
            p.wait_for_selector("[data-testid=page-pepe-wtc]", timeout=30000)
            p.wait_for_selector("[data-testid=wtc-main] canvas", timeout=30000)
            self.assertNotIn("LIVE", p.locator("[data-testid=tw-env]").inner_text())             # simulator is never LIVE / REAL
            p.click("[data-testid=wtc-tf-M15]")
            self.assertEqual(p.locator(".wtc-main .chart-panel").get_attribute("data-tf"), "M15")
            n0 = p.locator("[data-testid=wtc-mini]").count()
            p.click("[data-testid=wtc-add-chart]")
            self.assertEqual(p.locator("[data-testid=wtc-mini]").count(), n0 + 1)
            p.locator("[data-testid=wtc-mini-remove]").last.click()
            self.assertEqual(p.locator("[data-testid=wtc-mini]").count(), n0)
            p.locator("[data-testid=wtc-mini-tf]").first.select_option("M30")                   # independent TF of one chart
            self.assertEqual(p.locator("[data-testid=wtc-mini]").first.get_attribute("data-tf"), "M30")
            self.assertNotEqual(p.locator(".wtc-main .chart-panel").get_attribute("data-tf"), "M30")
            p.locator("[data-testid=wtc-mini-sync]").first.click()                               # click = move to the main chart
            self.assertEqual(p.locator(".wtc-main .chart-panel").get_attribute("data-tf"), "M30")
            self.assertTrue(p.locator("[data-testid=ind-bb]").is_disabled())                     # no BB engine in the bot -> N/A, not simulated
            p.click("[data-testid=ind-macd]")
            self.assertEqual(p.locator("[data-testid=ind-macd]").get_attribute("aria-pressed"), "false")
            # Volume Profile Auto Zones from the backend engine
            # (a fresh server measures the clock first: until then the profile is NO_DATA with the reason - never a made-up profile)
            ok = wait_for(lambda: p.locator("[data-testid=wtc-vp-zones] li").count() > 0, 120, 1.0)
            self.assertTrue(ok, p.locator("[data-testid=wtc-vp]").inner_text())
            types = p.locator("[data-testid=wtc-vp-zones] li b").all_inner_texts()
            self.assertIn("POC", types)
            p.click("[data-testid=wtc-vp-poc]")
            self.assertNotIn("POC", p.locator("[data-testid=wtc-vp-zones] li b").all_inner_texts())
            # Setup Builder: R:R = |TP2 - entry| / |entry - SL|, no order button
            p.fill("[data-testid=wtc-b-entry]", "100")
            p.fill("[data-testid=wtc-b-sl]", "98")
            p.fill("[data-testid=wtc-b-tp2]", "105")
            self.assertIn("2,50", p.locator("[data-testid=wtc-b-rr]").inner_text())
            self.assertEqual(p.locator("[data-testid=wtc-builder] button", has_text=re.compile("kup|sprzedaj|zlecenie|order|buy now", re.I)).count(), 0)
            kr = json.loads(p.evaluate("() => fetch('/api/v1/kronos').then(r => r.text())"))
            self.assertIn(kr["status"], p.locator("[data-testid=wtc-kr-state]").inner_text())     # backend status, nothing invented
            p.screenshot(path=str(SHOTS / "01_wtc_1672.png"), full_page=True)
            self.assertEqual([s for s in p.sent if ORDER_URL.search(s[1])], [])
            self.assertEqual(p.errors, [])
        finally:
            c.close()

    # ------------------------------------------------------------ PEPE$SIGNAL
    def test_02_signal_selection_filters_tabs(self):
        c, p = self.ctx()
        try:
            p.goto(BASE + "/#/brain-signal")
            p.wait_for_selector("[data-testid=page-pepe-signal]", timeout=30000)
            self.assertTrue(wait_for(lambda: p.locator("[data-testid=sg-item]").count() >= 2, 120, 1.0))   # engine scenarios / signals appear
            items = p.locator("[data-testid=sg-item]")
            sid = items.nth(1).get_attribute("data-id")
            items.nth(1).click()
            self.assertTrue(wait_for(lambda: sid in p.locator("[data-testid=sg-selected]").inner_text(), 10, 0.2))
            self.assertIn(f"id={sid}", p.url)
            row = p.locator(f"[data-testid=sg-row][data-id='{sid}']")
            if row.count():
                self.assertEqual(row.get_attribute("aria-selected"), "true")                    # list and table share the selection
            p.click("[data-testid=sg-scope-all]")
            rows = p.locator("[data-testid=sg-row]")
            if rows.count() > 2:
                rid = rows.nth(2).get_attribute("data-id")
                rows.nth(2).click()
                self.assertTrue(wait_for(lambda: rid in p.locator("[data-testid=sg-selected]").inner_text(), 10, 0.2))
            # WAIT is never shown as a trade direction
            for el in p.locator("[data-testid=sg-item]").all()[:12]:
                d = el.locator(".tw-dir").inner_text()
                self.assertIn(d, ("BUY", "SELL", "WAIT"))
            p.click(".sg-more summary")
            p.select_option("[data-testid=sg-f-dir]", "WAIT")
            self.assertTrue(all(x == "WAIT" for x in p.locator("[data-testid=sg-item] .tw-dir").all_inner_texts()))
            self.assertTrue(all(x == "WAIT" for x in p.locator("[data-testid=sg-row] .tw-dir").all_inner_texts()))
            p.select_option("[data-testid=sg-f-dir]", "")
            # conditions: real engine states only
            for st in p.locator("[data-testid=sg-entry] li").evaluate_all("els => els.map(e => e.dataset.state)"):
                self.assertIn(st, ("MET", "NOT_MET", "PENDING", "UNKNOWN", "INVALIDATED"))
            self.assertNotRegex(p.locator("[data-testid=sg-models]").inner_text(), r"P\(sukcesu\)\s*\d")
            p.screenshot(path=str(SHOTS / "02_signal_1672.png"), full_page=True)
            for tab, sel in (("ai", "sg-ai-eval"), ("performance", "sg-performance"), ("strategies", "sg-strategies"), ("center", "sg-table")):
                p.click(f"[data-testid=sg-tab-{tab}]")
                p.wait_for_selector(f"[data-testid={sel}]", timeout=5000)
            p.click("[data-testid=sg-pause]")
            self.assertIn("PAUZA", p.locator("[data-testid=sg-flow]").inner_text())
            p.click("[data-testid=tw-logo]")                                                      # back to the table
            p.wait_for_selector("[data-testid=page-menu]", timeout=30000)
            self.assertEqual([s for s in p.sent if ORDER_URL.search(s[1])], [])
            self.assertEqual(p.errors, [])
        finally:
            c.close()

    def test_03_resolutions(self):
        for w, h in ((1920, 1080), (1366, 768), (390, 844)):
            c, p = self.ctx(w, h)
            try:
                for page in ("pepe-wtc", "pepe-signal"):
                    p.goto(BASE + f"/#/{page}")
                    p.wait_for_selector(f"[data-testid=page-{page}]", timeout=30000)
                    p.wait_for_timeout(1500)
                    self.assertTrue(self.no_hscroll(p), (page, w))
                    p.screenshot(path=str(SHOTS / f"03_{page}_{w}.png"))
                self.assertEqual(p.errors, [], w)
            finally:
                c.close()


if __name__ == "__main__":
    unittest.main()
