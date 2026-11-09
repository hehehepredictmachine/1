"""Tower views Precision / Dyscypline / Profits and the two module maps in a real browser (Chromium + demo backend on the SYNTHETIC
terminal - clearly marked data). 1.32: the three-tower main menu of 1.26 was replaced by the CULT Main Menu (six towers, its own
tests in test_ui_cult.py); the module maps moved from its sides into the Wind Portal (NEURAL DATA FLOW -> "Mapy przepływu").
- the views show real data or say explicitly that it is missing (charts, regime, zones; setups with states, details, chart;
  balance, net result, ROI with method, deposits not counted as profit, equity curve, history);
- the two module maps: tooltip, list, details, filters; impulses only from real WebSocket events; offline -> no impulses;
- ONE WebSocket and no growing telemetry subscriptions after many view switches;
  the risk strip (mode, STOP, Execution Lock state) stays visible; "LIVE" is never shown on the simulator;
- no horizontal scroll at 1920x1080 / 1366x768 / 390 px.
Screenshots: data/logs/ui_wizard/. Skipped (never "passed") without Playwright/Chromium."""
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

PORT = 8789
BASE = f"http://127.0.0.1:{PORT}"
CHROMIUM = os.environ.get("MQ_CHROMIUM", "/opt/pw-browsers/chromium")
SHOTS = _env.ROOT / "data" / "logs" / "ui_wizard"
TOWERS = {"precision": ("Precision", "precision-observatory.webp"), "dyscypline": ("Dyscypline", "dyscypline-citadel.webp"),
          "profits": ("Profits", "profits-vault.webp")}
UI_STATES = {"OBSERWACJA", "FORMUJE_SIE", "GOTOWY", "AKTYWNY", "UNIEWAZNIONY", "WYGASLY", "ZAKONCZONY"}
ORDER_URL = re.compile(r"/api/v1/(mode|order|orders|trade|execution|kill|close|positions?|plan/.*/(execute|confirm))", re.I)
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
class TestWizardUI(unittest.TestCase):
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
        cls.start_server()
        cls.pw = sync_playwright().start()
        kw = {"executable_path": CHROMIUM} if os.path.exists(CHROMIUM) else {}
        cls.browser = cls.pw.chromium.launch(**kw)
        cls.ctx = cls.browser.new_context(viewport={"width": 1920, "height": 1080})
        cls.page = cls.ctx.new_page()
        cls.errors, cls.posts, cls.routes = [], [], []
        cls.page.on("pageerror", lambda e: cls.errors.append(str(e)))
        cls.page.on("console", lambda m: cls.errors.append(m.text) if m.type == "error" else None)
        cls.page.on("request", lambda r: cls.posts.append(r.url) if r.method != "GET" else None)

        def on_ws(ws):                                       # counts the page's WebSocket connections; traffic passes unchanged
            cls.routes.append(ws)
            server = ws.connect_to_server()
            server.on_message(lambda msg: ws.send(msg))
        cls.page.route_web_socket(re.compile(r".*/api/v1/ws$"), on_ws)
        cls.page.goto(BASE + "/#/precision")                 # a direct link skips the JOIN THE CULT launcher (test_ui_cult covers it)
        cls.page.wait_for_selector("[data-testid=page-precision]", timeout=60000)

    @classmethod
    def start_server(cls):
        cls.proc = subprocess.Popen([sys.executable, "-m", "masterquo", "serve", "--demo", "--no-browser"], env=cls.env, cwd=str(_env.ROOT / "backend"),
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not wait_for(health, 60, 0.5):
            cls.proc.kill()
            raise RuntimeError("server did not start")

    @classmethod
    def stop_server(cls):
        subprocess.run([sys.executable, "-m", "masterquo", "stop"], env=cls.env, cwd=str(_env.ROOT / "backend"), timeout=60)
        try:
            cls.proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            cls.proc.kill()
        wait_for(lambda: not health(), 20, 0.5)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.browser.close()
            cls.pw.stop()
        finally:
            cls.stop_server()
            cls.td.close()

    # ------------------------------------------------------------ helpers
    def shot(self, name, page=None, full=False):
        # SwiftShader (CPU) draws one 3D frame in ~1 s; a full-page capture re-renders the scene at the new size - give it time
        (page or self.page).screenshot(path=str(SHOTS / f"{name}.png"), full_page=full, timeout=120000)

    def maps(self, page=None):
        """1.32: the two module maps of the former main menu live in the Wind Portal (NEURAL DATA FLOW -> "Mapy przepływu")."""
        p = page or self.page
        p.goto(BASE + "/#/wind")
        p.wait_for_selector("[data-testid=page-wind]", timeout=30000)
        if p.locator("[data-testid=wp-maps]").count() == 0:
            p.click("[data-testid=wp-maps-toggle]")
        p.wait_for_selector("[data-testid=wz-flow-data]", timeout=30000)
        p.wait_for_selector("[data-testid=wz-flow-models]", timeout=30000)

    def img_loaded(self, sel, page=None):
        p = page or self.page
        return wait_for(lambda: p.evaluate(f"() => {{ const i = document.querySelector('{sel} img'); return !!i && i.complete && i.naturalWidth > 0; }}"), 20, 0.2)

    def no_hscroll(self, page=None):
        return (page or self.page).evaluate("() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")

    def state(self):
        return self.page.request.get(BASE + "/api/v1/state").json()

    def real_errors(self):
        return [e for e in self.errors if "WebSocket" not in e and "favicon" not in e and "Failed to load resource" not in e]

    # ------------------------------------------------------------ 4. Precision: real charts, regime, zones, source state
    def test_04_precision_view(self):
        p = self.page
        p.goto(BASE + "/#/precision")
        p.wait_for_selector("[data-testid=page-precision]", timeout=30000)
        self.assertTrue(wait_for(lambda: p.locator("[data-testid=page-precision] .chart-panel canvas").count() > 0, 30, 0.3))
        for part in ("wz-quote", "wz-regime", "wz-zones", "wz-fact-symbol", "wz-fact-updated", "wz-layers"):
            self.assertTrue(wait_for(lambda: p.locator(f"[data-testid={part}]").first.is_visible(), 30, 0.3), part)
        self.assertNotIn("{\"", p.locator("[data-testid=wz-zones]").inner_text())                      # no raw JSON
        self.assertIn("SYMULATOR", p.locator("[data-testid=wz-head-precision]").inner_text())
        self.assertEqual(p.locator("[data-testid=wizard-shell]").get_attribute("data-env"), "SYNTHETIC")
        self.assertIsNone(re.search(r"\bLIVE\b", p.locator("[data-testid=wz-top]").inner_text()))      # never "LIVE" on the simulator
        self.assertTrue(p.locator("[data-testid=wz-synthetic]").is_visible())
        self.assertTrue(self.no_hscroll())
        self.shot("04_precision_1920")

    # ------------------------------------------------------------ 5. Dyscypline: setups, states, details, chart, risk strip
    def test_05_dyscypline_view(self):
        p = self.page
        p.goto(BASE + "/#/dyscypline")
        p.wait_for_selector("[data-testid=page-dyscypline]", timeout=30000)
        risk = p.locator("[data-testid=wz-risk]").inner_text()
        for word in ("Tryb:", "Nowe wejścia", "Ścieżka główna", "Execution Lock"):
            self.assertIn(word, risk)
        self.assertTrue(wait_for(lambda: p.locator("[data-testid=wz-setup]").count() > 0, 40, 0.3))
        states = {p.locator("[data-testid=wz-setup]").nth(i).get_attribute("data-state") for i in range(p.locator("[data-testid=wz-setup]").count())}
        self.assertTrue(states <= UI_STATES, states)
        first = p.locator("[data-testid=wz-setup]").first
        title = first.locator(".wz-setup-main b").inner_text()
        first.click()
        self.assertTrue(wait_for(lambda: "setup=" in p.url, 10, 0.1), p.url)
        detail = p.locator("[data-testid=wz-setup-detail]")
        # setups come and go with every evaluation; a selected one that is no longer reported keeps its last state, marked stale
        self.assertTrue(wait_for(lambda: title.split()[0] in detail.inner_text(), 10, 0.2), detail.inner_text()[:300])
        text = detail.inner_text()
        for word in ("Powstał", "Wejście", "SL", "TP", "Trigger", "Unieważnienie", "Ocena setupu", "Prawdopodobieństwo", "Warunki", "Ryzyko"):
            self.assertIn(word, text)
        self.assertNotRegex(text, r"Ocena setupu\s+\d+[,.]?\d*\s*%")                                   # a score is never a percentage
        self.assertTrue(wait_for(lambda: p.locator("[data-testid=wz-setup-chart] .chart-panel canvas").count() > 0
                                 or "aktywnego instrumentu" in p.locator("[data-testid=wz-setup-chart]").inner_text(), 30, 0.3))
        self.shot("05_dyscypline_detail_1920", full=True)
        url = p.url
        p.reload()                                                                                    # selection kept in the URL
        p.wait_for_selector("[data-testid=page-dyscypline]", timeout=30000)
        self.assertEqual(p.url, url)
        self.assertTrue(wait_for(lambda: title.split()[0] in p.locator("[data-testid=wz-setup-detail]").inner_text(), 30, 0.3))

    # ------------------------------------------------------------ 6. Profits: account, net, ROI with method, flows, equity, history
    def test_06_profits_view(self):
        p = self.page
        p.goto(BASE + "/#/profits")
        p.wait_for_selector("[data-testid=page-profits]", timeout=30000)
        for part in ("wz-balance", "wz-net", "wz-roi", "wz-winrate", "wz-flows"):
            self.assertTrue(wait_for(lambda: p.locator(f"[data-testid={part}]").first.is_visible(), 30, 0.3), part)
        self.assertTrue(wait_for(lambda: p.locator("[data-testid=wz-history], [data-testid=wz-history-empty]").first.is_visible(), 30, 0.3))
        # the account history arrives with the next statistics poll (every 20 s) - until then the card says "brak danych"
        self.assertTrue(wait_for(lambda: "nie są zyskiem" in p.locator("[data-testid=wz-flows]").inner_text(), 45, 0.5),
                        p.locator("[data-testid=wz-flows]").inner_text())                             # deposits are not profit
        self.assertIn("Dietz", p.locator("[data-testid=wz-roi]").inner_text())                          # ROI with its method
        self.assertTrue(wait_for(lambda: p.locator("[data-testid=wz-equity], [data-testid=wz-equity-empty]").count() > 0, 30, 0.3))
        wr = p.locator("[data-testid=wz-winrate]").inner_text()
        self.assertTrue("brak danych" in wr or "%" in wr, wr)                                          # missing data said explicitly
        self.assertTrue(self.no_hscroll())
        self.shot("06_profits_1920")

    # ------------------------------------------------------------ 7. module maps (Wind Portal): tooltip, list, details, filters, real impulses
    def test_07_flow_maps_interaction_and_real_impulses(self):
        p = self.page
        self.maps()
        for kind in ("data", "models"):
            self.assertGreater(int(p.locator(f"[data-testid=wz-flow-{kind}]").get_attribute("data-nodes")), 5)
        self.assertTrue(wait_for(lambda: int(p.locator("[data-testid=wz-flow-data]").get_attribute("data-impulses") or 0) > 0, 30, 0.3),
                        "no impulse from real WebSocket events")
        box = p.locator("[data-testid=wz-flow-canvas-data]").bounding_box()
        p.locator("[data-testid=wz-flow-canvas-data]").scroll_into_view_if_needed()
        box = p.locator("[data-testid=wz-flow-canvas-data]").bounding_box()
        p.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)                       # the eye core
        self.assertTrue(wait_for(lambda: p.locator("[data-testid=wz-flow-tip-data]").is_visible(), 10, 0.1))
        tip = p.locator("[data-testid=wz-flow-tip-data]").inner_text()
        self.assertIn("Ostatnia praca", tip)
        p.mouse.move(box["x"] - 40 if box["x"] > 60 else 5, box["y"] - 30 if box["y"] > 40 else 5)
        p.click("[data-testid=wz-flow-list-models]")
        p.locator("[data-testid=wz-flow-listbox-models] button").first.click()
        self.assertTrue(p.locator("[data-testid=wz-flow-detail-models]").is_visible())
        p.locator("[data-testid=wz-flow-detail-models] button").first.click()
        p.click("[data-testid=wz-flow-filter-models-problems]")
        self.assertEqual(p.locator("[data-testid=wz-flow-filter-models-problems]").get_attribute("aria-pressed"), "true")
        p.click("[data-testid=wz-flow-filter-models-all]")
        p.click("[data-testid=wz-flow-list-models]")
        self.shot("07_wind_maps_1920")

    # ------------------------------------------------------------ 8. one WebSocket, no growing subscriptions after many switches
    def test_08_single_socket_and_no_subscription_growth(self):
        p = self.page
        p.goto(BASE + "/#/precision")
        p.wait_for_selector("[data-testid=page-precision]", timeout=30000)
        p.wait_for_timeout(1500)
        base = p.evaluate("() => window.__mqTelemetry.subscribers()")
        sockets = len(self.routes)
        self.posts.clear()
        for _ in range(3):
            for t in TOWERS:
                p.click(f"[data-testid=wz-tab-{t}]")
                p.wait_for_selector(f"[data-testid=page-{t}]", timeout=30000)
                p.wait_for_timeout(300)
            p.click("[data-testid=wz-logo]")                                                     # logo -> CULT Main Menu
            p.wait_for_selector("[data-testid=galaxy-menu]", timeout=20000)
            p.wait_for_timeout(500)
            p.evaluate("location.hash = '#/precision'")
            p.wait_for_selector("[data-testid=page-precision]", timeout=30000)
            p.wait_for_timeout(300)
        self.assertEqual(p.evaluate("() => window.__mqTelemetry.subscribers()"), base)
        self.assertEqual(len(self.routes), sockets)                                                  # no new WebSocket
        self.assertEqual([u for u in self.posts if ORDER_URL.search(u)], [])                         # navigation never sends an order
        self.assertEqual(self.real_errors(), [])

    # ------------------------------------------------------------ 9. backend stopped -> visible, no impulses; back after restart
    def test_09_offline_is_visible_and_stops_impulses(self):
        p = self.page
        self.maps()
        self.assertTrue(wait_for(lambda: int(p.locator("[data-testid=wz-flow-data]").get_attribute("data-impulses") or 0) > 0, 30, 0.3))
        type(self).stop_server()                                                                     # the bot process is gone
        try:
            self.assertTrue(wait_for(lambda: p.locator("[data-testid=cu-backend]").count() > 0, 30, 0.2))       # CULT frame says it
            self.assertTrue(wait_for(lambda: p.locator("[data-testid=wz-flow-data]").get_attribute("data-link") != "OPEN", 20, 0.2))
            self.assertIn("STALE", p.locator("[data-testid=cu-backend]").inner_text())
            n0 = p.locator("[data-testid=wz-flow-data]").get_attribute("data-impulses")
            p.wait_for_timeout(3000)
            self.assertEqual(p.locator("[data-testid=wz-flow-data]").get_attribute("data-impulses"), n0)   # offline: no impulses
            self.shot("09_wind_offline_1920")
            p.evaluate("location.hash = '#/profits'")                                                # the views say it too
            p.wait_for_selector("[data-testid=page-profits]", timeout=30000)
            self.assertTrue(wait_for(lambda: p.locator("[data-testid=wz-backend]").count() > 0, 20, 0.2))
            self.assertIn("brak łącza", p.locator("[data-testid=wz-bot]").inner_text())
            self.assertIsNone(re.search(r"\bLIVE\b", p.locator("[data-testid=wz-top]").inner_text()))
            self.shot("09_profits_offline_1920")
        finally:
            type(self).start_server()
        # after the restart the client gets a new session by itself (reload on the unknown session) and the warning disappears
        self.assertTrue(wait_for(lambda: p.locator("[data-testid=wz-backend]").count() == 0
                                 and p.locator("[data-testid=page-profits]").count() == 1, 90, 0.5), "no reconnect")

    # ------------------------------------------------------------ 10. 1366 and a phone: the tower views without horizontal scroll
    def test_10_layouts(self):
        ctx = self.browser.new_context(viewport={"width": 1366, "height": 768})
        p = ctx.new_page()
        try:
            for t in TOWERS:
                p.goto(BASE + f"/#/{t}")
                p.wait_for_selector(f"[data-testid=page-{t}]", timeout=30000)
                p.wait_for_timeout(800)
                self.assertTrue(self.no_hscroll(p), t)
            self.shot("10_profits_1366", p)
        finally:
            ctx.close()
        ctx = self.browser.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True, reduced_motion="reduce")
        p = ctx.new_page()
        try:
            for t in TOWERS:
                p.goto(BASE + f"/#/{t}")
                p.wait_for_selector(f"[data-testid=page-{t}]", timeout=30000)
                p.wait_for_timeout(1500)
                self.assertTrue(self.no_hscroll(p), t)
                self.shot(f"10_{t}_390", p, full=True)
        finally:
            ctx.close()


if __name__ == "__main__":
    unittest.main()
