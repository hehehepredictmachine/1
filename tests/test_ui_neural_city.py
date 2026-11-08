"""1.36 Main Menu V2 (Neural Table, EIGHT towers) + JOIN THE CULT launcher (1.34 TASK 001) (TASK 001) in a real browser (Chromium + demo backend on the SYNTHETIC
terminal; the launcher window of the Windows app as a page with a stand-in bridge).

Launcher: shown at the start of a session on the bare address (the panel is not mounted before the click); the delivered image is the
background with its proportions kept; JOIN THE CULT in the lower centre, disabled until the bot is ready, hover / click animation;
engine not answering -> the start error with the instruction (never SYSTEM READY); JOIN -> neural intro -> main menu; reload / direct link skip it.
Windows launcher page (desktop/splash.html): ready / progress / error / data choice, JOIN calls the app exactly once, nothing overflows.
Menu: exactly the eight names, no information panels and no buttons at the bottom; tower geometry and top navigation call the same controller and open the same EXISTING panel; the state
machine IDLE -> SELECTED -> STOP_ROTATION -> PEPE_REACH -> CONTACT -> PORTAL -> NAVIGATE; Esc cancels; RETURN restores the focus;
double click = one navigation; Performance / pause / reduced motion -> direct navigation, no intro; the menu fetches no MT5 data;
1280x720 / 1920x1080 / 390 px without horizontal scroll; legacy route aliases; no order, no mode change, one
WebSocket. Screenshot comparison with the reference (honest numbers in data/logs/ui_neural_city/compare.json)."""
from __future__ import annotations

import base64
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

PORT = 8823
BASE = f"http://127.0.0.1:{PORT}"
CHROMIUM = os.environ.get("MQ_CHROMIUM", "/opt/pw-browsers/chromium")
SHOTS = _env.ROOT / "data" / "logs" / "ui_neural_city"
NAMES = ["PEPE$WTC", "PEPE$SIGNAL", "PEPE$BANK", "PEPE$ROI", "STRATEGIES", "MARKET NEWS", "TRAINING LAB", "SETTINGS"]
OLD = ["WTC PEPE", "BRAIN SIGNAL", "AI AGENT", "LEADERBOARD"]
# tower key -> (route, selector of the EXISTING panel it opens)
TOWERS = {"wtc": ("pepe-wtc", "[data-testid=page-pepe-wtc]"), "signal": ("pepe-signal", "[data-testid=page-pepe-signal]"),
          "bank": ("lightning", "[data-testid=page-lightning]"), "roi": ("profits", "[data-testid=wz-top]"),
          "strategies": ("strategy-lab", "[data-testid=page-strategy-lab]"), "news": ("kontekst", "[data-testid=ctx-news]"),
          "training": ("trening", "main.page"), "settings": ("ustawienia", "main.page")}
ALIASES = {"wtc": "page-pepe-wtc", "pepe-signal": "page-pepe-signal", "brain-signal": "page-pepe-signal", "pepe-bank": "page-lightning", "ai-agent": "page-lightning",
           "market-news": "ctx-news", "leaderboard": "wz-top", "pepe-roi": "wz-top", "strategies": "page-strategy-lab", "trading-intelligence": "terminal-shell",
           "wind": "page-wind"}
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
class TestNeuralCityUI(unittest.TestCase):
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
        cls.api_ctx = cls.browser.new_context()
        cls.api_page = cls.api_ctx.new_page()
        cls.api_page.goto(BASE + "/#/pulpit")
        cls.api_page.wait_for_selector("main.page, [data-testid=topbar]", timeout=60000)

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

    # ------------------------------------------------------------ helpers
    def ctx(self, **kw):
        c = self.browser.new_context(viewport=kw.pop("viewport", {"width": 1920, "height": 1080}), **kw)
        p = c.new_page()
        p.errors, p.sent = [], []
        p.on("pageerror", lambda e: p.errors.append(str(e)))
        p.on("console", lambda m: p.errors.append(m.text) if m.type == "error" else None)
        p.on("request", lambda r: p.sent.append((r.method, r.url)) if r.method != "GET" else None)
        return c, p

    def api(self, path):
        r = self.api_page.request.get(BASE + path)
        self.assertEqual(r.status, 200, (path, r.text()[:200]))
        return r.json()

    def menu(self, p, extra=""):
        p.goto(BASE + "/#/menu" + extra)
        p.wait_for_selector("[data-testid=page-menu][data-phase=IDLE]", timeout=30000)
        p.wait_for_timeout(300)                                                              # debounce window of a fresh mount

    def real_errors(self, p):
        return [e for e in p.errors if "WebSocket" not in e and "favicon" not in e and "Failed to load resource" not in e]

    def no_hscroll(self, p):
        return p.evaluate("() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")

    def shot(self, p, name, full=False):
        p.screenshot(path=str(SHOTS / f"{name}.png"), full_page=full)

    # ------------------------------------------------------------ 1. launcher (browser session)
    def test_01_launcher_gate_background_join_intro(self):
        c, p = self.ctx()
        try:
            p.goto(BASE + "/")
            p.wait_for_selector("[data-testid=cult-launcher]", timeout=30000)
            self.assertEqual(p.locator("[data-testid=page-menu]").count(), 0)                    # the panel is not mounted before JOIN
            bg = p.locator(".lj-bg")
            self.assertIn("launcher-speech.webp", bg.get_attribute("src"))
            fit = p.evaluate("() => { const i = document.querySelector('.lj-bg'); return [getComputedStyle(i).objectFit, i.naturalWidth, i.naturalHeight]; }")
            self.assertEqual(fit[0], "cover")                                                    # proportions kept, never stretched
            self.assertEqual(fit[1:], [1199, 675])                                               # the delivered image, unchanged size
            join = p.locator("[data-testid=cult-join]")
            self.assertEqual(join.inner_text().replace("»", "").strip(), "JOIN THE CULT")
            p.wait_for_selector("[data-testid=cult-join]:not([disabled])", timeout=30000)
            self.assertIn("SYSTEM READY", p.locator("[data-testid=cult-status]").inner_text())
            b = join.bounding_box()
            self.assertLess(abs(b["x"] + b["width"] / 2 - 960), 20)                              # lower centre
            self.assertGreater(b["y"], 1080 * 0.7)
            self.assertIn(str(self.api("/api/v1/state")["app_version"]), p.locator("[data-testid=cult-launcher-ver]").inner_text())
            p.wait_for_timeout(1300)
            self.shot(p, "01_launcher_1920")
            before = join.evaluate("e => getComputedStyle(e).transform")
            join.hover()
            p.wait_for_timeout(400)
            self.assertNotEqual(before, join.evaluate("e => getComputedStyle(e).transform"))    # hover animation
            join.click()
            p.wait_for_selector("[data-testid=nc-intro]", timeout=10000)                         # neural intro after JOIN
            self.assertEqual(p.evaluate("() => location.hash"), "#/menu")
            self.shot(p, "01_intro")
            p.wait_for_selector("[data-testid=page-menu][data-phase=IDLE]", timeout=10000)       # ends by itself
            self.assertEqual(p.locator("[data-testid=cult-launcher]").count(), 0)
            p.reload()
            p.wait_for_selector("[data-testid=page-menu][data-phase=IDLE]", timeout=30000)       # same session: no launcher, no intro
            self.assertEqual(p.locator("[data-testid=cult-launcher]").count(), 0)
            self.assertEqual(self.real_errors(p), [])
        finally:
            c.close()
        for url in (BASE + "/?pmw_joined=1#/menu", BASE + "/#/lightning"):                     # Windows app / direct link: no launcher
            c, p = self.ctx()
            try:
                p.goto(url)
                p.wait_for_selector("[data-testid=page-menu], [data-testid=page-lightning]", timeout=30000)
                self.assertEqual(p.locator("[data-testid=cult-launcher]").count(), 0, url)
            finally:
                c.close()

    def test_02_engine_not_answering_never_looks_ready(self):
        """The engine does not answer: no launcher pretending SYSTEM READY, no panel - the existing start error with the instruction."""
        c, p = self.ctx()
        p.route(re.compile(r".*/api/v1/(state|session)(\?.*)?$"), lambda r: r.abort())
        try:
            p.goto(BASE + "/")
            self.assertTrue(wait_for(lambda: "Nie można połączyć się z lokalnym backendem" in p.evaluate("() => document.body.innerText"), 30, 0.3))
            self.assertEqual(p.locator("[data-testid=cult-join]:not([disabled])").count(), 0)
            self.assertEqual(p.locator("[data-testid=page-menu]").count(), 0)
            self.shot(p, "02_engine_down")
        finally:
            p.unroute_all(behavior="ignoreErrors")
            c.close()

    def test_03_windows_launcher_page(self):
        scene = "data:image/webp;base64," + base64.b64encode((_env.ROOT / "desktop" / "assets" / "launcher-speech.webp").read_bytes()).decode()
        states = {"ready": {"phase": "ready", "message": "silnik bota działa", "version": "1.34.0", "scene": scene},
                  "progress": {"phase": "progress", "message": "Instalowanie (2/5)", "version": "1.34.0", "scene": scene, "lines": ["pip … OK"]},
                  "error": {"phase": "error", "error": "Silnik nie odpowiedział", "log_path": "C:\\logs", "version": "1.34.0", "scene": scene},
                  "choose": {"phase": "choose", "candidates": ["C:\\stare\\data"], "version": "1.34.0", "scene": scene}}
        for vp in ({"width": 960, "height": 660}, {"width": 716, "height": 618}):
            for k, st in states.items():
                c, p = self.ctx(viewport=vp)
                try:
                    p.add_init_script("(() => { const st = " + json.dumps(st) + "; window.__calls = []; window.pmw = (a) => { window.__calls.push(a); "
                                      "return Promise.resolve(a === 'state' ? st : {}); }; })();")
                    p.goto((_env.ROOT / "desktop" / "splash.html").as_uri())
                    p.wait_for_timeout(1200)
                    self.assertTrue(p.evaluate("() => document.getElementById('sceneImg').naturalWidth") > 0, k)
                    over = p.evaluate("() => [...document.querySelectorAll('.win *')].filter(e => { const r = e.getBoundingClientRect();"
                                      " return r.width && (r.right > innerWidth + 1 || r.bottom > innerHeight + 1); }).length")
                    self.assertEqual(over, 0, (k, vp))
                    j = p.locator("#btnJoin")
                    if k in ("ready", "progress"):
                        b = j.bounding_box()
                        self.assertLess(abs(b["x"] + b["width"] / 2 - vp["width"] / 2), 12, (k, vp))
                        self.assertGreater(b["y"], vp["height"] * 0.6, (k, vp))
                        self.assertEqual(j.is_disabled(), k != "ready")
                    else:
                        self.assertFalse(j.is_visible(), k)
                    self.shot(p, f"03_splash_{vp['width']}_{k}")
                    if k == "ready":
                        j.click()
                        j.click(force=True)                                                       # double click: one join
                        p.wait_for_timeout(300)
                        self.assertEqual(p.evaluate("() => window.__calls.filter(a => a === 'join').length"), 1)
                    self.assertEqual(self.real_errors(p), [])
                finally:
                    c.close()

    # ------------------------------------------------------------ 4. seven names, one controller, existing panels
    def test_04_eight_towers_and_navigation(self):
        c, p = self.ctx()
        try:
            before = (self.api("/api/v1/state").get("mode") or {})
            self.menu(p)
            plates = [x.inner_text().strip() for x in p.locator("[data-plate] b").all()]
            self.assertEqual(sorted(plates), sorted(NAMES))
            nav = [x.inner_text().strip() for x in p.locator("[data-testid^=nc-nav-]:not([data-testid=nc-nav-home])").all()]
            self.assertEqual(nav, NAMES)                                                          # top navigation of all eight modules
            self.assertEqual(p.locator("[data-testid=nc-hud], .nc-quote, [data-testid=nc-stat-eq]").count(), 0)   # no information panels
            tools = p.locator("[data-testid=page-menu] button:visible").all()
            low = [b.get_attribute("data-testid") for b in tools if (bb := b.bounding_box()) and bb["y"] > 1080 * 0.9]
            self.assertEqual(low, [], low)                                                        # no buttons at the bottom of the menu
            logo = p.locator("[data-testid=nc-logo]").bounding_box()
            self.assertLess(logo["x"] + logo["y"], 80)                                            # small logo top-left
            visible = p.evaluate("() => document.querySelector('[data-testid=nc-stage]').innerText")
            for o in OLD:
                self.assertNotIn(o, visible)                                                      # old names only in titles / info
            self.shot(p, "04_menu_1920")
            for key, (route, sel) in TOWERS.items():
                self.menu(p)
                hit = p.locator(f"[data-testid=nc-tower-{key}]")
                self.assertEqual(hit.get_attribute("data-page"), route)
                self.assertEqual(p.locator(f"[data-testid=nc-nav-{key}]").get_attribute("data-page"), route)   # same target
                b = p.locator(f"[data-plate={key}]").bounding_box()
                top = p.evaluate("([x, y]) => document.elementFromPoint(x, y)?.dataset?.testid || ''", [b["x"] + b["width"] / 2, b["y"] + b["height"] / 2])
                self.assertEqual(top, f"nc-tower-{key}")                                          # the plate area takes the click
                hit.hover()
                self.assertTrue(wait_for(lambda: key in (p.locator("[data-testid=page-menu]").get_attribute("data-selected") or "") or
                                         NAMES[list(TOWERS).index(key)] in p.locator("[data-testid=nc-tip]").inner_text(), 5, 0.1), key)
                phases = []
                p.evaluate("() => { window.__ph = []; new MutationObserver(() => { const v = document.querySelector('[data-testid=page-menu]')?.dataset.phase;"
                           " if (v && window.__ph[window.__ph.length - 1] !== v) window.__ph.push(v); }).observe(document, { subtree: true, attributes: true,"
                           " attributeFilter: ['data-phase'] }); }")
                (hit if key != "news" else p.locator(f"[data-testid=nc-nav-{key}]")).click()
                p.wait_for_selector(sel, timeout=30000)
                self.assertIn(f"#/{route}", p.url, key)
                phases = p.evaluate("() => window.__ph")
                self.assertEqual(phases, ["SELECTED", "STOP_ROTATION", "PEPE_REACH", "CONTACT", "PORTAL", "NAVIGATE"], (key, phases))
            self.assertEqual([s for s in p.sent if ORDER_URL.search(s[1]) or MODE_URL.search(s[1])], [])
            after = (self.api("/api/v1/state").get("mode") or {})
            self.assertEqual((before.get("mode"), before.get("kill_switch")), (after.get("mode"), after.get("kill_switch")))
            self.assertEqual(self.real_errors(p), [])
        finally:
            c.close()

    def test_05_keyboard_escape_return_focus_debounce(self):
        c, p = self.ctx()
        p.add_init_script("(() => { window.__hc = 0; window.addEventListener('hashchange', () => window.__hc++); })();")
        try:
            self.menu(p)
            p.focus("[data-testid=nc-tower-signal]")
            p.keyboard.press("Enter")
            p.wait_for_selector("[data-testid=page-menu][data-phase=PEPE_REACH]", timeout=3000)
            p.keyboard.press("Escape")                                                            # cancel -> back to IDLE, still on the menu
            p.wait_for_selector("[data-testid=page-menu][data-phase=IDLE]", timeout=3000)
            p.wait_for_timeout(2200)
            self.assertTrue(p.url.endswith("#/menu"))
            self.assertEqual(p.evaluate("() => document.activeElement?.dataset?.testid"), "nc-tower-signal")
            self.menu(p)
            n0 = p.evaluate("() => window.__hc")
            p.dblclick("[data-testid=nc-tower-bank]")                                             # double click -> one navigation
            p.wait_for_selector("[data-testid=page-lightning]", timeout=30000)
            p.wait_for_timeout(500)
            self.assertEqual(p.evaluate("() => window.__hc") - n0, 1)
            p.go_back()                                                                           # back to the city: RETURN, focus restored
            p.wait_for_selector("[data-testid=page-menu]", timeout=30000)
            p.wait_for_selector("[data-testid=page-menu][data-phase=IDLE]", timeout=5000)
            self.assertTrue(wait_for(lambda: p.evaluate("() => document.activeElement?.dataset?.testid") == "nc-tower-bank", 5, 0.1))
            self.assertEqual(self.real_errors(p), [])
        finally:
            c.close()

    def test_06_menu_fetches_no_market_data(self):
        c, p = self.ctx()
        got: list = []
        p.on("request", lambda r: got.append(r.url) if "/api/v1/" in r.url else None)
        try:
            p.goto(BASE + "/#/menu")
            p.wait_for_selector("[data-testid=page-menu][data-phase=IDLE]", timeout=30000)
            got.clear()                                                                           # the shell (state, WebSocket) is loaded once for the app
            p.wait_for_timeout(4000)
            market = [u for u in got if re.search(r"/api/v1/(candles|stats|bot-signals|markets|models|kronos|svp|setups)", u)]
            self.assertEqual(market, [])                                                          # the animation never pulls MT5 / bot data
            p.click("[data-testid=nc-pepe-center]")                                               # Pepe impulse: visual only
            self.assertEqual(p.locator("[data-testid=page-menu]").get_attribute("data-phase"), "IDLE")
            self.assertTrue(p.url.endswith("#/menu"))
        finally:
            c.close()

    def test_07_quality_pause_reduced_motion(self):
        c, p = self.ctx()
        try:
            self.menu(p)
            p.click("[data-testid=nc-settings]")
            p.click("[data-quality=performance]")
            self.assertEqual(p.locator("[data-testid=page-menu]").get_attribute("data-motion"), "performance")
            t0 = time.monotonic()
            p.click("[data-testid=nc-tower-strategies]")
            p.wait_for_selector("[data-testid=page-strategy-lab]", timeout=30000)
            self.assertLess(time.monotonic() - t0, 3)
            self.menu(p)
            p.click("[data-testid=nc-settings]")
            p.click("[data-quality=cinematic]")
            p.click("[data-testid=nc-pause]")
            self.assertEqual(p.locator("[data-testid=page-menu]").get_attribute("data-motion"), "paused")
            self.shot(p, "07_paused")
        finally:
            c.close()
        c, p = self.ctx(reduced_motion="reduce")
        try:
            self.menu(p, "?intro=1")                                                              # no intro with reduced motion
            self.assertEqual(p.locator("[data-testid=nc-intro]").count(), 0)
            self.assertEqual(p.locator("[data-testid=page-menu]").get_attribute("data-motion"), "reduced")
            t0 = time.monotonic()
            p.click("[data-testid=nc-tower-settings]")
            p.wait_for_selector("main.page", timeout=30000)
            self.assertIn("#/ustawienia", p.url)
            self.assertLess(time.monotonic() - t0, 3)
        finally:
            c.close()

    def test_08_resolutions_aliases_single_socket(self):
        for vp in ({"width": 1920, "height": 1080}, {"width": 1280, "height": 720}, {"width": 390, "height": 844}):
            c, p = self.ctx(viewport=vp)
            try:
                self.menu(p)
                self.assertTrue(self.no_hscroll(p), vp)
                for key in TOWERS:
                    b = p.locator(f"[data-plate={key}]").bounding_box()
                    self.assertTrue(b and b["x"] >= 0 and b["x"] + b["width"] <= vp["width"] + 1, (key, vp))
                if vp["width"] < 600:
                    self.assertEqual(p.locator("[data-testid^=nc-list-]").count(), 8)            # list for small screens
                    self.assertTrue(p.locator("[data-testid=nc-list-roi]").is_visible())
                self.shot(p, f"08_menu_{vp['width']}", full=vp["width"] < 600)
                self.assertEqual(self.real_errors(p), [], vp)
            finally:
                c.close()
        c, p = self.ctx()
        p.add_init_script("""(() => { const W = window.WebSocket, s = window.__ws = { opened: 0, open: 0, maxOpen: 0 };
            window.WebSocket = class extends W { constructor(...a) { super(...a); s.opened++; s.open++; s.maxOpen = Math.max(s.maxOpen, s.open);
              this.addEventListener('close', () => { s.open--; }); } }; })();""")
        try:
            for alias, sel in ALIASES.items():                                                  # legacy / new route names
                p.goto(BASE + f"/#/{alias}")
                p.wait_for_selector(f"[data-testid={sel}]", timeout=30000)
            for _ in range(3):
                self.menu(p)
                p.click("[data-testid=nc-tower-bank]")
                p.wait_for_selector("[data-testid=page-lightning]", timeout=30000)
            ws = p.evaluate("() => window.__ws")
            self.assertEqual(ws["maxOpen"], 1, ws)
        finally:
            c.close()

    # ------------------------------------------------------------ 9. screenshot vs the approved reference (honest numbers)
    def test_09_screenshot_vs_reference(self):
        from PIL import Image, ImageChops, ImageStat
        ref_dir = os.environ.get("MQ_NC_REFERENCE")
        c, p = self.ctx(viewport={"width": 1672, "height": 941}, reduced_motion="reduce")
        try:
            self.menu(p)
            p.wait_for_timeout(800)
            p.locator("[data-testid=nc-stage]").screenshot(path=str(SHOTS / "09_stage_1672.png"))
        finally:
            c.close()
        got = Image.open(SHOTS / "09_stage_1672.png").convert("RGB").resize((1672, 941))
        clean = Image.open(_env.ROOT / "frontend" / "public" / "assets" / "neural" / "neural-table-scene.webp").convert("RGB")
        tower_area = (0, 80, 1672, 941)                                                           # everything under the top navigation
        mae_clean = sum(ImageStat.Stat(ImageChops.difference(got.crop(tower_area), clean.crop(tower_area))).mean) / 3
        out = {"viewport": [1672, 941], "mae_vs_clean_scene_towers_area": round(mae_clean, 2)}
        if ref_dir and os.path.exists(os.path.join(ref_dir, "neural-city-reference.png")):
            ref = Image.open(os.path.join(ref_dir, "neural-city-reference.png")).convert("RGB")
            out["mae_vs_reference_towers_area"] = round(sum(ImageStat.Stat(ImageChops.difference(got.crop(tower_area), ref.crop(tower_area))).mean) / 3, 2)
            side = Image.new("RGB", (1672, 941 * 2))
            side.paste(ref, (0, 0))
            side.paste(got, (0, 941))
            side.resize((836, 941)).save(SHOTS / "09_reference_vs_app.png")
        (SHOTS / "compare.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
        self.assertLess(mae_clean, 14, out)                                                       # the composition is the approved one


if __name__ == "__main__":
    unittest.main()
