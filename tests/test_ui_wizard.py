"""1.26 PepeMarketWizard main menu (three towers) and the tower views in a real browser (Chromium with the SwiftShader software
WebGL + demo backend on the SYNTHETIC terminal - clearly marked data):
- first start = main menu; three towers with the exact names Precision / Dyscypline / Profits; the menu background asset;
- each tower opens its own view (click, Enter, arrow keys), each view has its own background asset; Back / refresh / logo -> menu;
- the decorative layers never take clicks; hover highlights the tower and shows its description;
- no WebGL (`?webgl=0`) -> the same buttons with drawn silhouettes, navigation works; reduced motion -> no camera move / portal;
- the views show real data or say explicitly that it is missing (charts, regime, zones; setups with states, details, chart;
  balance, net result, ROI with method, deposits not counted as profit, equity curve, history);
- the two model-flow maps: tooltip, list, details, filters; impulses only from real WebSocket events; offline -> no impulses;
- ONE WebSocket and no growing telemetry subscriptions after many view switches; no order / mode request from navigation;
  the risk strip (mode, STOP, Execution Lock state) stays visible; "LIVE" is never shown on the simulator;
- no horizontal scroll at 1920x1080 / 1366x768 / 390 px, all three towers and labels visible without scrolling on desktop;
- FPS of the 3D scene measured (software renderer - written to fps.json, not a GPU figure).
Screenshots: data/logs/ui_wizard/. Skipped (never "passed") without Playwright/Chromium."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import unittest
import urllib.request

import _env
from _env import TempData, wait_for

PORT = 8789
BASE = f"http://127.0.0.1:{PORT}"
CHROMIUM = os.environ.get("MQ_CHROMIUM", "/opt/pw-browsers/chromium")
GL_ARGS = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]
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
        cls.browser = cls.pw.chromium.launch(args=GL_ARGS, **kw)
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
        cls.page.goto(BASE + "/")
        cls.page.wait_for_selector("[data-testid=page-menu]", timeout=60000)
        cls.first_url = cls.page.url

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

    def menu(self, page=None, forced=True):
        """Main menu in a fresh document. SwiftShader (CPU) renders the scene below 5 FPS, which switches 3D off by itself
        (test_12) - the 3D checks therefore force it with `?webgl=1`."""
        p = page or self.page
        p.goto(BASE + ("/#/menu?webgl=1" if forced else "/#/menu"))
        p.reload()
        p.wait_for_selector("[data-testid=page-menu]", timeout=30000)

    def gl_ready(self, page=None):
        p = page or self.page
        ok = wait_for(lambda: p.locator("[data-testid=wz-towers]").count() == 1
                      and p.locator("[data-testid=wz-towers]").get_attribute("data-webgl") in ("on", "off"), 60, 0.25)
        if not ok:
            print("gl_ready failed:", p.url, p.evaluate("() => document.getElementById('root')?.innerHTML.slice(0, 600)"))
        return ok

    def img_loaded(self, sel, page=None):
        p = page or self.page
        return wait_for(lambda: p.evaluate(f"() => {{ const i = document.querySelector('{sel} img'); return !!i && i.complete && i.naturalWidth > 0; }}"), 20, 0.2)

    def no_hscroll(self, page=None):
        return (page or self.page).evaluate("() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")

    def state(self):
        return self.page.request.get(BASE + "/api/v1/state").json()

    def real_errors(self):
        return [e for e in self.errors if "WebSocket" not in e and "favicon" not in e and "Failed to load resource" not in e]

    # ------------------------------------------------------------ 1. first start, three towers, background, hover
    def test_01_first_start_is_menu_with_three_towers(self):
        p = self.page
        self.assertTrue(self.first_url.endswith("#/menu"), self.first_url)
        self.menu()
        self.assertTrue(self.gl_ready())
        self.assertEqual(p.locator("[data-testid=wz-towers]").get_attribute("data-webgl"), "on")       # SwiftShader WebGL
        names = [p.locator(f"[data-testid=wz-tower-{t}] .wz-tower-name").inner_text() for t in TOWERS]
        self.assertEqual(names, ["Precision", "Dyscypline", "Profits"])                               # exact, "Dyscypline" kept
        self.assertEqual(p.locator("[data-testid=wz-menu-bg]").get_attribute("data-asset"), "menu-tower-lightning.webp")
        self.assertTrue(self.img_loaded("[data-testid=wz-menu-bg]"))
        self.assertEqual(p.locator("[data-testid=wz-logo]").get_attribute("href"), "#/menu")
        for t in TOWERS:                                                                               # all labels on screen, no scroll
            self.assertTrue(wait_for(lambda: p.locator(f"[data-testid=wz-tower-{t}]").is_visible(), 20, 0.2), t)
            box = p.locator(f"[data-testid=wz-tower-{t}]").bounding_box()
            self.assertLessEqual(box["y"] + box["height"], 1080, t)
            self.assertGreaterEqual(box["x"], 0, t)
        self.assertTrue(self.no_hscroll())
        # decorative layers (background, fx canvas, 3D canvas) never take the click meant for a tower button
        hit = p.evaluate("""() => { const b = document.querySelector('[data-testid=wz-tower-precision]').getBoundingClientRect();
            const e = document.elementFromPoint(b.x + b.width / 2, b.y + b.height / 2); return !!e?.closest('[data-testid=wz-tower-precision]'); }""")
        self.assertTrue(hit)
        self.assertEqual(p.evaluate("() => getComputedStyle(document.querySelector('.wz-fx')).pointerEvents"), "none")
        p.hover("[data-testid=wz-tower-dyscypline]")
        self.assertTrue(wait_for(lambda: p.locator("[data-testid=page-menu]").get_attribute("data-hover") == "dyscypline", 5, 0.1))
        self.assertIn("Setupy silnika", p.locator("[data-testid=wz-tower-desc]").inner_text())
        self.shot("01_menu_1920_hover")
        p.mouse.move(5, 600)
        self.assertEqual(self.real_errors(), [])

    # ------------------------------------------------------------ 2. each tower opens its own view with its own background
    def test_02_each_tower_opens_its_view_with_own_background(self):
        p = self.page
        seen = set()
        for t, (name, asset) in TOWERS.items():
            self.menu()
            self.gl_ready()
            p.click(f"[data-testid=wz-tower-{t}]")
            p.wait_for_selector(f"[data-testid=page-{t}]", timeout=30000)
            self.assertTrue(p.url.endswith(f"#/{t}"), p.url)
            self.assertEqual(p.locator("[data-testid=wz-view-bg]").get_attribute("data-asset"), asset)
            self.assertTrue(self.img_loaded("[data-testid=wz-view-bg]"), t)
            self.assertIn(name, p.locator(f"[data-testid=wz-head-{t}]").inner_text())
            self.assertEqual(p.locator(f"[data-testid=wz-tab-{t}]").get_attribute("aria-current"), "page")
            seen.add(asset)
            p.go_back()                                                                               # Back -> menu
            p.wait_for_selector("[data-testid=page-menu]", timeout=20000)
        self.assertEqual(len(seen), 3)
        # keyboard: focus, arrows between towers, Enter opens
        self.gl_ready()
        p.focus("[data-testid=wz-tower-precision]")
        p.keyboard.press("ArrowRight")
        self.assertEqual(p.evaluate("() => document.activeElement?.dataset.tower"), "dyscypline")
        p.keyboard.press("Enter")
        p.wait_for_selector("[data-testid=page-dyscypline]", timeout=20000)
        p.reload()                                                                                    # refresh keeps the view
        p.wait_for_selector("[data-testid=page-dyscypline]", timeout=30000)
        p.click("[data-testid=wz-logo]")                                                              # logo -> menu
        p.wait_for_selector("[data-testid=page-menu]", timeout=20000)
        self.assertEqual(self.real_errors(), [])

    # ------------------------------------------------------------ 3. navigation only: no order / mode request, mode unchanged
    def test_03_navigation_never_sends_orders_or_changes_mode(self):
        p = self.page
        before = self.state().get("mode")
        self.posts.clear()
        for t in TOWERS:
            self.menu()
            self.gl_ready()
            p.click(f"[data-testid=wz-tower-{t}]")
            p.wait_for_selector(f"[data-testid=page-{t}]", timeout=30000)
            p.wait_for_timeout(800)
        self.assertEqual([u for u in self.posts if ORDER_URL.search(u)], [])
        after = self.state().get("mode")
        self.assertEqual((before or {}).get("mode"), (after or {}).get("mode"))
        self.assertEqual((before or {}).get("kill_switch"), (after or {}).get("kill_switch"))

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

    # ------------------------------------------------------------ 7. side maps: tooltip, list, details, filters, real impulses
    def test_07_flow_maps_interaction_and_real_impulses(self):
        p = self.page
        self.menu()
        for kind in ("data", "models"):
            self.assertGreater(int(p.locator(f"[data-testid=wz-flow-{kind}]").get_attribute("data-nodes")), 5)
        self.assertTrue(wait_for(lambda: int(p.locator("[data-testid=wz-flow-data]").get_attribute("data-impulses") or 0) > 0, 30, 0.3),
                        "no impulse from real WebSocket events")
        box = p.locator("[data-testid=wz-flow-canvas-data]").bounding_box()
        p.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)                       # the eye core
        self.assertTrue(wait_for(lambda: p.locator("[data-testid=wz-flow-tip-data]").is_visible(), 10, 0.1))
        tip = p.locator("[data-testid=wz-flow-tip-data]").inner_text()
        self.assertIn("Ostatnia praca", tip)
        p.mouse.move(5, 600)
        p.click("[data-testid=wz-flow-list-models]")
        p.locator("[data-testid=wz-flow-listbox-models] button").first.click()
        self.assertTrue(p.locator("[data-testid=wz-flow-detail-models]").is_visible())
        p.locator("[data-testid=wz-flow-detail-models] button").first.click()
        p.click("[data-testid=wz-flow-filter-models-problems]")
        self.assertEqual(p.locator("[data-testid=wz-flow-filter-models-problems]").get_attribute("aria-pressed"), "true")
        p.click("[data-testid=wz-flow-filter-models-all]")
        p.click("[data-testid=wz-flow-list-models]")
        self.shot("07_menu_maps_1920")

    # ------------------------------------------------------------ 8. one WebSocket, no growing subscriptions after many switches
    def test_08_single_socket_and_no_subscription_growth(self):
        p = self.page
        self.menu()
        self.gl_ready()
        p.wait_for_timeout(1500)
        base = p.evaluate("() => window.__mqTelemetry.subscribers()")
        sockets = len(self.routes)
        for _ in range(3):
            for t in TOWERS:
                p.click(f"[data-testid=wz-tab-{t}]")
                p.wait_for_selector(f"[data-testid=page-{t}]", timeout=30000)
                p.wait_for_timeout(300)
            p.click("[data-testid=wz-logo]")
            p.wait_for_selector("[data-testid=page-menu]", timeout=20000)
            p.wait_for_timeout(500)
        self.assertEqual(p.evaluate("() => window.__mqTelemetry.subscribers()"), base)
        self.assertEqual(len(self.routes), sockets)                                                  # no new WebSocket
        self.assertEqual(self.real_errors(), [])

    # ------------------------------------------------------------ 9. backend stopped -> visible, no impulses; back after restart
    def test_09_offline_is_visible_and_stops_impulses(self):
        p = self.page
        self.menu()
        self.assertTrue(wait_for(lambda: int(p.locator("[data-testid=wz-flow-data]").get_attribute("data-impulses") or 0) > 0, 30, 0.3))
        type(self).stop_server()                                                                     # the bot process is gone
        try:
            self.assertTrue(wait_for(lambda: p.locator("[data-testid=wz-backend]").count() > 0, 30, 0.2))
            self.assertTrue(wait_for(lambda: p.locator("[data-testid=wz-flow-data]").get_attribute("data-link") != "OPEN", 20, 0.2))
            self.assertIn("brak łącza", p.locator("[data-testid=wz-bot]").inner_text())
            self.assertIsNone(re.search(r"\bLIVE\b", p.locator("[data-testid=wz-top]").inner_text()))
            n0 = p.locator("[data-testid=wz-flow-data]").get_attribute("data-impulses")
            p.wait_for_timeout(3000)
            self.assertEqual(p.locator("[data-testid=wz-flow-data]").get_attribute("data-impulses"), n0)   # offline: no impulses
            self.shot("09_menu_offline_1920")
            p.evaluate("location.hash = '#/profits'")                                                # the views say it too
            p.wait_for_selector("[data-testid=page-profits]", timeout=30000)
            self.assertTrue(p.locator("[data-testid=wz-backend]").is_visible())
            self.shot("09_profits_offline_1920")
        finally:
            type(self).start_server()
        # after the restart the client gets a new session by itself (reload on the unknown session) and the warning disappears
        self.assertTrue(wait_for(lambda: p.locator("[data-testid=wz-backend]").count() == 0
                                 and p.locator("[data-testid=page-profits]").count() == 1, 90, 0.5), "no reconnect")

    # ------------------------------------------------------------ 10. no WebGL, reduced motion, 1366 and narrow layouts
    def test_10_fallbacks_and_layouts(self):
        ctx = self.browser.new_context(viewport={"width": 1366, "height": 768})
        p = ctx.new_page()
        try:
            p.goto(BASE + "/#/menu?webgl=0")
            p.wait_for_selector("[data-testid=wz-nowebgl]", timeout=30000)
            self.assertEqual(p.locator("[data-testid=wz-towers]").get_attribute("data-webgl"), "off")
            self.assertEqual(p.locator("[data-testid=wz-canvas]").count(), 0)
            self.assertEqual(p.locator(".wz-sil").count(), 3)
            self.shot("10_menu_nowebgl_1366", p)
            p.click("[data-testid=wz-tower-profits]")
            p.wait_for_selector("[data-testid=page-profits]", timeout=30000)
            self.menu(p)                                                                             # 1366 with WebGL: towers visible
            self.assertTrue(self.gl_ready(p))
            for t in TOWERS:
                self.assertTrue(wait_for(lambda: p.locator(f"[data-testid=wz-tower-{t}]").is_visible(), 20, 0.2), t)
                box = p.locator(f"[data-testid=wz-tower-{t}]").bounding_box()
                self.assertLessEqual(box["y"] + box["height"], 768, t)
            self.assertTrue(self.no_hscroll(p))
            self.shot("10_menu_1366", p)
        finally:
            ctx.close()
        ctx = self.browser.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True, reduced_motion="reduce")
        p = ctx.new_page()
        try:
            p.goto(BASE + "/#/menu")
            p.wait_for_selector("[data-testid=page-menu]", timeout=30000)
            self.assertTrue(self.no_hscroll(p))
            for kind in ("data", "models"):                                                          # maps collapsed on a phone
                self.assertIsNone(p.locator(f"[data-testid=wz-side-{kind}]").get_attribute("open"))
                self.assertTrue(p.locator(f"[data-testid=wz-side-{kind}] summary").is_visible())
            self.shot("10_menu_390", p, full=True)
            t0 = time.monotonic()
            p.tap("[data-testid=wz-tower-precision]")                                                # touch, no hover needed
            p.wait_for_selector("[data-testid=page-precision]", timeout=30000)
            self.assertLess(time.monotonic() - t0, 5)                                                # reduced motion: no camera move
            for t in TOWERS:
                p.goto(BASE + f"/#/{t}")
                p.wait_for_selector(f"[data-testid=page-{t}]", timeout=30000)
                p.wait_for_timeout(1500)
                self.assertTrue(self.no_hscroll(p), t)
                self.shot(f"10_{t}_390", p, full=True)
        finally:
            ctx.close()

    # ------------------------------------------------------------ 11. FPS of the 3D scene (measured, software renderer)
    def test_11_measure_fps(self):
        p = self.page
        self.menu()
        self.assertTrue(self.gl_ready())
        ok = wait_for(lambda: p.locator("[data-testid=wz-scene]").get_attribute("data-fps") is not None, 90, 0.5)
        fps = p.locator("[data-testid=wz-scene]").get_attribute("data-fps")
        dpr = p.locator("[data-testid=wz-scene]").get_attribute("data-dpr")
        (SHOTS / "fps.json").write_text(json.dumps({"viewport": "1920x1080", "renderer": "SwiftShader (CPU, headless Chromium)", "fps": fps,
                                                    "pixel_ratio": dpr, "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, indent=1))
        self.assertTrue(ok, "the scene never reported FPS")
        self.assertGreater(float(fps), 0)


    # ------------------------------------------------------------ 12. too slow for 3D (software rendering) -> buttons, by itself
    def test_12_auto_fallback_when_rendering_is_too_slow(self):
        p = self.page
        self.menu(forced=False)
        renderer = p.evaluate("""() => { const g = document.createElement('canvas').getContext('webgl');
            const x = g && g.getExtension('WEBGL_debug_renderer_info'); return x ? String(g.getParameter(x.UNMASKED_RENDERER_WEBGL)) : ''; }""")
        if "swiftshader" not in renderer.lower():
            self.skipTest(f"hardware renderer ({renderer}) - no automatic fallback expected")
        towers = p.locator("[data-testid=wz-towers]")
        self.assertTrue(wait_for(lambda: towers.get_attribute("data-webgl") == "off", 120, 0.5), "3D not switched off on SwiftShader")
        self.assertEqual(towers.get_attribute("data-webgl-reason"), "slow")
        note = p.locator("[data-testid=wz-nowebgl]").inner_text()
        self.assertIn("kl./s", note)
        self.assertIn("webgl=1", note)
        self.shot("12_menu_auto_fallback_1920")
        p.click("[data-testid=wz-tower-dyscypline]")
        p.wait_for_selector("[data-testid=page-dyscypline]", timeout=30000)


if __name__ == "__main__":
    unittest.main()
