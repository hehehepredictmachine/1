"""Stage 1 of docs/PEPE_UI_IMPLEMENTATION_PLAN.md in a real browser (Chromium + demo backend on the SYNTHETIC terminal): the new terminal
shell and its three routes, the header fed only by backend state (environment, MT5 + details, freshness, instrument, mode, lock,
notifications), the collapsible sidebar, the link back to every existing view and from the old shell to the new panels, ONE WebSocket
across old and new routes, no fabricated values, the disconnected state, keyboard focus and no horizontal scroll at four widths.
Checklist: docs/PEPE_UI_TEST_PLAN.md §2 (F1-F11). Screenshots: data/logs/ui_terminal/. Skipped (never "passed") without Playwright."""
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

PORT = 8793
BASE = f"http://127.0.0.1:{PORT}"
CHROMIUM = os.environ.get("MQ_CHROMIUM", "/opt/pw-browsers/chromium")
SHOTS = _env.ROOT / "data" / "logs" / "ui_terminal"
ROUTES = {"trading-intelligence": "page-trading-intelligence", "ai-neural-lab": "page-ai-neural-lab", "system-control": "page-system-control"}
INTEGRATED = {"trading-intelligence": ["ti-account", "ti-market", "ti-signals", "ti-positions", "ti-banner"],
              "ai-neural-lab": ["nl-banner", "nl-models", "nl-canvas", "nl-details", "nl-cycle"],
              "system-control": ["sc-banner", "sc-status", "sc-mode", "sc-stop", "sc-mt5", "sc-app"]}
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


# Replaces the browser WebSocket for /api/v1/ws with one that fails to connect, so the page sees a lost backend link.
DEAD_WS = """(() => {
  const Real = window.WebSocket;
  window.WebSocket = function (url, protocols) {
    if (!String(url).endsWith("/api/v1/ws")) return new Real(url, protocols);
    const ws = { readyState: 0, send() {}, close() {}, onopen: null, onmessage: null, onerror: null, onclose: null };
    setTimeout(() => { ws.readyState = 3; ws.onerror && ws.onerror({}); ws.onclose && ws.onclose({ code: 1006 }); }, 30);
    return ws;
  };
})();"""


@unittest.skipUnless(HAVE_PW, "playwright not installed")
class TestTerminalShell(unittest.TestCase):
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
        cls.ctx = cls.browser.new_context(viewport={"width": 1600, "height": 1000})
        cls.page = cls.ctx.new_page()
        cls.errors, cls.sockets, cls.posts = [], [], []
        cls.page.on("console", lambda m: cls.errors.append(m.text) if m.type == "error" else None)
        cls.page.on("pageerror", lambda e: cls.errors.append(str(e)))
        cls.page.on("websocket", lambda ws: cls.sockets.append(ws.url))
        cls.page.on("request", lambda r: cls.posts.append(r.url) if r.method != "GET" else None)
        cls.page.goto(BASE + "/#/trading-intelligence")
        cls.page.wait_for_selector("[data-testid=terminal-shell] [data-testid=page-trading-intelligence]", timeout=30000)
        wait_for(lambda: cls.page.locator("[data-testid=t-mt5]").get_attribute("data-mt5") == "CONNECTED", 60, 0.5)

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

    def state(self):
        return self.page.request.get(BASE + "/api/v1/state").json()

    def go(self, route: str):
        self.page.goto(BASE + f"/#/{route}")
        self.page.wait_for_selector(f"[data-testid=terminal-shell] [data-testid={ROUTES[route]}]", timeout=20000)

    def no_hscroll(self) -> bool:
        return self.page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1")

    # ------------------------------------------------------------------ F1, F2
    def test_01_new_routes_render_in_the_new_shell_only(self):
        for route, tid in ROUTES.items():
            self.go(route)
            self.assertEqual(self.page.locator("[data-testid=topbar]").count(), 0, route)             # the old shell is not mixed in
            self.assertEqual(self.page.locator(f"[data-testid=t-sidebar] [data-page={route}]").get_attribute("aria-current"), "page")
            if route in INTEGRATED:                                                                     # 1.24: panels on real data
                for part in INTEGRATED[route]:
                    self.assertTrue(self.page.locator(f"[data-testid={part}]").first.is_visible(), f"{route}: {part}")
                self.assertEqual(self.page.locator(f"[data-testid={tid}] [data-integration=NOT_INTEGRATED]").count(), 0, route)
            else:
                sections = self.page.locator(f"[data-testid={tid}] [data-integration=NOT_INTEGRATED]")
                self.assertGreater(sections.count(), 0, route)                                       # not integrated yet - said honestly
            self.page.screenshot(path=str(SHOTS / f"{route}_1600.png"))
        self.assertEqual(self.errors, [])

    def test_02_existing_views_stay_and_link_both_ways(self):
        self.go("trading-intelligence")
        self.page.locator("[data-testid=t-existing] [data-section=pulpit]").click()
        self.page.wait_for_selector("[data-testid=page-pulpit]", timeout=20000)
        self.assertEqual(self.page.locator("[data-testid=terminal-shell]").count(), 0)
        self.assertTrue(self.page.locator("[data-testid=topbar]").is_visible())                    # old shell, unchanged
        for old, sel in (("wykresy", "main.page[data-page=wykresy]"), ("ai", "[data-testid=page-ai]"), ("diagnostyka", "[data-testid=page-diagnostyka]")):
            self.page.goto(BASE + f"/#/{old}")
            self.page.wait_for_selector(sel, timeout=20000)
        self.page.locator("[data-testid=nav-terminal]").click()                                     # old shell -> new panels
        self.page.wait_for_selector("[data-testid=terminal-shell] [data-testid=page-trading-intelligence]", timeout=20000)
        self.page.goto(BASE + "/#/nc")
        self.page.wait_for_timeout(1500)
        self.assertEqual(self.page.locator("[data-testid=terminal-shell]").count(), 0)

    # ------------------------------------------------------------------ F4, F5, F7, I6
    def test_03_header_only_shows_what_the_backend_confirms(self):
        self.go("system-control")
        st = self.state()
        self.assertTrue(st["synthetic"])
        self.assertEqual(self.page.locator("[data-testid=t-env]").get_attribute("data-env"), "SYNTHETIC")
        self.assertTrue(self.page.locator("[data-testid=t-synthetic]").is_visible())
        con = st["connection"]["state"]
        self.assertEqual(self.page.locator("[data-testid=t-mt5]").get_attribute("data-mt5"), "CONNECTED" if con == "CONNECTED" else "DISCONNECTED")
        self.assertIn(st["assets"]["active"], self.page.locator("[data-testid=t-instrument]").inner_text())
        self.assertIn("STOP" if st["mode"]["kill_switch"] else "AKTYWNE", self.page.locator("[data-testid=t-entries]").inner_text())
        want = lambda: {"GOOD": "FRESH", "DEGRADED": "DEGRADED", "STALE": "STALE", "BAD": "STALE", "NO_DATA": "STALE"}.get(
            (self.state().get("decision") or {}).get("data_quality"), "UNKNOWN")
        got = lambda: self.page.locator("[data-testid=t-fresh]").get_attribute("data-fresh")
        wait_for(lambda: got() == want(), 15, 0.5)                                                  # the store follows the backend verdict
        self.assertEqual(got(), want())
        self.page.goto(BASE + "/#/trading-intelligence?as_of=2026-10-26T10:00:00Z")
        wait_for(lambda: self.page.locator("[data-testid=t-env]").get_attribute("data-env") == "HISTORY", 10, 0.2)
        self.assertEqual(self.page.locator("[data-testid=t-env]").get_attribute("data-env"), "HISTORY")

    def test_04_mt5_details_and_notifications_popovers(self):
        self.go("trading-intelligence")
        self.page.locator("[data-testid=t-mt5]").click()
        det = self.page.locator("[data-testid=t-mt5-details]")
        self.assertTrue(det.is_visible())
        text = det.inner_text()
        self.assertIn(self.state()["connection"]["state"], text)
        for bad in ("undefined", "null", "NaN"):
            self.assertNotIn(bad, text)                                                              # unknown -> N/A, never a raw value
        self.page.screenshot(path=str(SHOTS / "mt5_details.png"))
        self.page.keyboard.press("Escape")
        self.assertEqual(det.count(), 0)
        btn = self.page.locator("[data-testid=t-alerts]")
        self.assertRegex(btn.inner_text(), r"\d+")
        btn.click()
        self.assertTrue(self.page.locator("[data-testid=t-alerts-list]").is_visible())
        self.page.mouse.click(800, 600)                                                              # outside click closes
        self.assertEqual(self.page.locator("[data-testid=t-alerts-list]").count(), 0)

    # ------------------------------------------------------------------ F3
    def test_05_sidebar_collapse_is_remembered(self):
        self.go("ai-neural-lab")
        nav = self.page.locator("[data-testid=t-sidebar]")
        if nav.get_attribute("data-collapsed") == "1":
            self.page.locator("[data-testid=t-collapse]").click()
        self.page.locator("[data-testid=t-collapse]").click()
        self.assertEqual(nav.get_attribute("data-collapsed"), "1")
        self.assertEqual(self.page.locator("[data-testid=t-collapse]").get_attribute("aria-expanded"), "false")
        self.page.reload()
        self.page.wait_for_selector("[data-testid=t-sidebar]", timeout=20000)
        self.assertEqual(self.page.locator("[data-testid=t-sidebar]").get_attribute("data-collapsed"), "1")
        self.page.locator("[data-testid=t-collapse]").click()
        self.assertEqual(self.page.locator("[data-testid=t-sidebar]").get_attribute("data-collapsed"), "0")

    # ------------------------------------------------------------------ F7: no fabricated numbers in stage-1 views
    def test_06_no_fabricated_values(self):
        n0 = len(self.posts)
        for route, tid in ROUTES.items():
            self.go(route)
            text = self.page.locator(f"[data-testid={tid}]").inner_text()
            if route not in INTEGRATED:
                self.assertIsNone(re.search(r"\d+[.,]\d+", text), route)                             # no prices / metrics invented
            for bad in ("undefined", "null", "NaN"):
                self.assertNotIn(bad, self.page.locator("[data-testid=terminal-shell]").inner_text(), route)
        self.assertEqual([u for u in self.posts[n0:] if "/api/" in u], [])                          # navigation never changes bot state

    def test_06b_trading_intelligence_shows_backend_values(self):
        self.go("trading-intelligence")
        st = self.state()
        acc = st["account"]
        num = lambda t: float(re.sub(r"[^0-9,\-]", "", t.split("USD")[0]).replace(",", "."))
        wait_for(lambda: self.page.locator("[data-testid=ti-balance] b").inner_text() != "—", 20, 0.3)
        self.assertAlmostEqual(num(self.page.locator("[data-testid=ti-balance] b").inner_text()), acc["balance"], delta=0.01)
        self.assertAlmostEqual(num(self.page.locator("[data-testid=ti-equity] b").inner_text()), self.state()["account"]["equity"], delta=50)
        sig = self.page.locator("[data-testid=ti-signals]")
        dec = self.state()["decision"]
        self.assertTrue(self.page.locator("[data-testid=ti-why-signal]").is_visible())               # signal and order answered separately
        self.assertTrue(self.page.locator("[data-testid=ti-why-order]").is_visible())
        if dec.get("setup"):
            side = {"LONG": "BUY", "SHORT": "SELL"}.get(dec["setup"]["direction"], dec["setup"]["direction"])
            self.assertIn(side, sig.locator("[data-testid=ti-direction]").inner_text())
        self.assertIn(dec["symbol"], self.page.locator("[data-testid=ti-market]").inner_text())
        # layout 1/4/6 + save: remembered after a reload
        self.page.locator("[data-testid=ti-layout-6]").click()
        wait_for(lambda: self.page.locator("[data-testid=ti-chart]").count() == 6, 10, 0.2)
        self.assertTrue(self.page.locator("[data-testid=ti-layout-dirty]").is_visible())
        self.page.locator("[data-testid=ti-layout-save]").click()
        self.page.reload()
        self.page.wait_for_selector("[data-testid=ti-charts]", timeout=20000)
        self.assertEqual(self.page.locator("[data-testid=ti-charts]").get_attribute("data-n"), "6")
        self.page.locator("[data-testid=ti-layout-4]").click()
        self.page.locator("[data-testid=ti-layout-save]").click()

    def test_06c_look_dialog_changes_only_this_client(self):
        self.go("trading-intelligence")
        n0 = len(self.posts)
        self.page.locator("[data-testid=t-look-open]").first.click()
        self.assertTrue(self.page.locator("[data-testid=t-look]").is_visible())
        self.page.locator("[data-testid=t-look-preset]").select_option("contrast")
        style = self.page.locator("[data-testid=terminal-shell]").get_attribute("style")
        self.assertIn("--t-bg: #000000", style)
        self.assertEqual(self.page.locator("[data-testid=t-look-contrast] [data-contrast=low]").count(), 0)   # high-contrast preset passes
        self.page.locator("[data-testid=t-look-reset]").click()
        self.page.locator("[data-testid=t-look-close]").click()
        self.assertEqual(self.page.locator("[data-testid=t-look]").count(), 0)
        self.assertEqual([u for u in self.posts[n0:] if "/api/" in u], [])                          # appearance never reaches the bot

    # ------------------------------------------------------------------ F8
    def test_07_keyboard_skip_link_and_focus(self):
        self.go("trading-intelligence")
        self.page.reload()                                       # fresh document: sequential focus starts at the top, not where earlier tests left it
        self.page.wait_for_selector("[data-testid=page-trading-intelligence]", timeout=20000)
        self.page.keyboard.press("Tab")
        self.assertEqual(self.page.evaluate("() => document.activeElement.dataset.testid"), "t-skip")
        self.assertGreaterEqual(self.page.locator("[data-testid=t-skip]").bounding_box()["x"], 0)    # visible when focused
        self.page.keyboard.press("Enter")
        self.assertEqual(self.page.evaluate("() => document.activeElement.id"), "terminal-main")
        for _ in range(40):                    # keyboard focus -> :focus-visible; the header sits before main, so walk backwards
            if self.page.evaluate("() => document.activeElement.dataset.testid") == "t-mt5":
                break
            self.page.keyboard.press("Shift+Tab")
        self.assertEqual(self.page.evaluate("() => document.activeElement.dataset.testid"), "t-mt5")
        outline = self.page.evaluate("() => getComputedStyle(document.activeElement).outlineStyle")
        self.assertNotEqual(outline, "none")

    # ------------------------------------------------------------------ F9
    def test_08_responsive_without_horizontal_scroll(self):
        for w, h in ((1600, 1000), (1366, 768), (760, 900), (390, 844)):
            self.page.set_viewport_size({"width": w, "height": h})
            for route in ROUTES:
                self.go(route)
                self.assertTrue(self.no_hscroll(), f"{route} {w}x{h}")
            if w <= 1000:                                        # the sidebar width is animated (0.15 s) - wait for it to settle
                sb = self.page.locator("[data-testid=t-sidebar]")
                self.assertTrue(wait_for(lambda: sb.bounding_box()["width"] <= 60, 5, 0.1), f"sidebar {sb.bounding_box()['width']} at {w}")
            if w >= 1366:                                                                           # header fits one row
                self.assertLessEqual(self.page.locator("[data-testid=t-header]").bounding_box()["height"], 56, f"{w}x{h}")
            self.go("trading-intelligence")
            self.page.screenshot(path=str(SHOTS / f"trading-intelligence_{w}.png"))
        self.page.set_viewport_size({"width": 1600, "height": 1000})

    # ------------------------------------------------------------------ F11 (runs after many route changes above)
    def test_09_single_websocket_across_old_and_new_routes(self):
        self.go("trading-intelligence")
        n0 = len([u for u in self.sockets if u.endswith("/api/v1/ws")])
        self.assertGreaterEqual(n0, 1)
        for r in ("trading-intelligence", "pulpit", "ai-neural-lab", "wykresy", "system-control"):
            self.page.evaluate(f"() => {{ location.hash = '#/{r}' }}")
            self.page.wait_for_timeout(400)
        live = [u for u in self.sockets if u.endswith("/api/v1/ws")]
        self.assertEqual(len(live), n0, live)                                                        # switching pages never opens a socket
        self.assertEqual(self.errors, [])

    # ------------------------------------------------------------------ F6: disconnected
    def test_10_backend_link_lost_is_shown_not_hidden(self):
        ctx = self.browser.new_context(viewport={"width": 1366, "height": 768})
        p = ctx.new_page()
        try:
            p.add_init_script(DEAD_WS)                       # the backend WebSocket never opens (route_web_socket hung the sync driver)
            p.goto(BASE + "/#/trading-intelligence")
            p.wait_for_selector("[data-testid=terminal-shell]", timeout=30000)
            wait_for(lambda: p.locator("[data-testid=t-backend]").count() > 0, 20, 0.3)
            self.assertTrue(p.locator("[data-testid=t-backend]").is_visible())
            self.assertEqual(p.locator("[data-testid=t-fresh]").get_attribute("data-fresh"), "DISCONNECTED")
            self.assertEqual(p.locator("[data-testid=t-mt5]").get_attribute("data-mt5"), "UNKNOWN")             # last known != current
            self.assertIn("Brak połączenia z lokalnym backendem", p.locator("[data-testid=t-warnings]").inner_text())
            self.assertEqual(p.locator("main#terminal-main").get_attribute("data-stale"), "1")
            p.screenshot(path=str(SHOTS / "disconnected.png"))
        finally:
            ctx.close()


if __name__ == "__main__":
    unittest.main()
