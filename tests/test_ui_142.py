"""1.42 interface in a real browser (Chromium + demo backend on the SYNTHETIC terminal) - E8 §5 (a)-(g), S6 §4.

(a) "/" -> #/menu with the cinematic menu; (b) three planet buttons FOREX / CRYPTO / OTC; (c) CRYPTO / OTC -> "in preparation" without any
write request; (d) #/forex with 4 planets and 2 panels (MODEL A / MODEL B); (e) every planet screen opens [data-testid=forex-*] and closes;
(f) the four system panels open from the menu and from FOREX, ESC closes, opening sends GET only; (g) every LEGACY_REDIRECTS row.
WebGL runs on SwiftShader (software) - the test waits on engine states (window.__PMW_TEST__, webdriver only), never on fixed frames."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
import urllib.request

import _env
from _env import TempData, wait_for

PORT = 8842
BASE = f"http://127.0.0.1:{PORT}"
CHROMIUM = os.environ.get("MQ_CHROMIUM", "/opt/pw-browsers/chromium")
GL_ARGS = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"]
REDIRECTS = {"#/wykresy": "#/forex?s=charts", "#/pepe-signal": "#/forex?s=signals", "#/trening": "#/forex?s=models",
             "#/profits": "#/forex?s=roi", "#/ustawienia": "#/system?p=settings", "#/system-control": "#/system?p=mode",
             "#/diagnostyka": "#/system?p=diagnostics", "#/galaxy": "#/menu", "#/neural-city": "#/menu", "#/cokolwiek": "#/menu"}
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
class TestUI142(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (_env.ROOT / "frontend" / "dist" / "index.html").exists():
            raise unittest.SkipTest("frontend not built")
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
        kw = {"args": GL_ARGS}
        if os.path.exists(CHROMIUM):
            kw["executable_path"] = CHROMIUM
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

    def page(self, reduced=True):
        c = self.browser.new_context(viewport={"width": 1600, "height": 900})
        # intro seen + reduced motion: the menu is shown at once (the film itself is covered by the cinematic gate tests)
        c.add_init_script("try{sessionStorage.setItem('pmw.cinematic.seen','1');" + ("localStorage.setItem('pmw.motion','reduced')" if reduced else "") + "}catch(e){}")
        p = c.new_page()
        p.errors, p.sent = [], []
        p.on("pageerror", lambda e: p.errors.append(str(e)))
        p.on("request", lambda r: p.sent.append((r.method, r.url)) if r.method != "GET" else None)
        self.addCleanup(c.close)
        return p

    def menu(self, p):
        p.goto(BASE + "/")
        p.wait_for_selector("[data-testid=page-menu] [data-testid=cinematic-menu]", timeout=30000)
        p.wait_for_function("() => document.querySelector('[data-testid=page-menu]').dataset.state === 'menu'", timeout=60000)

    def forex(self, p):
        p.goto(BASE + "/#/forex")
        p.wait_for_selector("[data-testid=page-forex]", timeout=30000)
        p.wait_for_function("() => window.__PMW_TEST__ && window.__PMW_TEST__.forex && window.__PMW_TEST__.forex.state().phase === 'forex'", timeout=90000)

    # (a) (b) (c)
    def test_a_menu_planets_and_modes_in_preparation(self):
        p = self.page()
        self.menu(p)
        self.assertTrue(p.evaluate("location.hash").startswith("#/menu"))
        for k in ("forex", "crypto", "otc"):
            self.assertTrue(p.is_visible(f"[data-testid=menu-{k}]"), k)
        for k in ("crypto", "otc"):
            p.click(f"[data-testid=menu-{k}]")
            p.wait_for_selector("[data-testid=menu-return]", state="visible", timeout=30000)
            p.click("[data-testid=menu-return]")
            p.wait_for_function("() => document.querySelector('[data-testid=page-menu]').dataset.state === 'menu'", timeout=60000)
        self.assertEqual(p.sent, [])                                    # no profile switch, no write
        self.assertEqual(p.errors, [])

    # (d) (e)
    def test_b_forex_planets_panels_and_screens(self):
        p = self.page()
        self.forex(p)
        for k in ("charts", "signals", "models", "roi"):
            self.assertEqual(p.locator(f"[data-testid=planet-{k}]").count(), 1)
        self.assertEqual(p.locator("[data-testid=panel-model-a]").count(), 1)
        self.assertEqual(p.locator("[data-testid=panel-model-b]").count(), 1)
        for k in ("charts", "signals", "models", "roi"):
            p.click(f"[data-testid=planet-{k}]")
            p.wait_for_function("() => window.__PMW_TEST__.forex.state().sub === 'on'", timeout=90000)
            p.wait_for_selector(f"[data-testid=forex-{k}]", timeout=30000)
            self.assertIn(f"s={k}", p.evaluate("location.hash"))
            p.click("[data-testid=forex-back]")
            p.wait_for_function("() => window.__PMW_TEST__.forex.state().sub === 'none'", timeout=90000)
            self.assertEqual(p.evaluate("location.hash"), "#/forex")
        self.assertEqual(p.sent, [])                                    # opening screens = GET only
        self.assertEqual(p.errors, [])

    # (f)
    def test_c_system_panels_from_menu_and_forex(self):
        p = self.page()
        for opener in (self.menu, self.forex):
            opener(p)
            base = p.evaluate("location.hash")
            for k in ("settings", "mode", "diagnostics"):
                p.click(f"[data-testid=open-{k}]")
                p.wait_for_selector(f"[data-testid=system-{k}]", timeout=30000)
                self.assertIn(f"p={k}", p.evaluate("location.hash"))
                p.keyboard.press("Escape")
                p.wait_for_selector("[data-testid=system-drawer]", state="detached", timeout=30000)
                self.assertEqual(p.evaluate("location.hash"), base)
            for t in ("stop-button", "chip-exec", "chip-mode"):
                self.assertEqual(p.locator(f"[data-testid={t}]").count(), 1, t)
            p.click("[data-testid=stop-button]")
            p.wait_for_selector("[data-testid=system-stop]", timeout=30000)
            p.keyboard.press("Escape")
            p.wait_for_selector("[data-testid=system-drawer]", state="detached", timeout=30000)
        self.assertEqual(p.sent, [])                                    # STOP panel opened, nothing confirmed -> no POST
        self.assertEqual(p.errors, [])

    # (g)
    def test_d_legacy_redirects(self):
        p = self.page()
        for old, new in REDIRECTS.items():
            p.goto(BASE + "/" + old)
            p.wait_for_function(f"() => location.hash !== {json.dumps(old)}", timeout=30000)
            self.assertEqual(p.evaluate("location.hash"), new, old)
        self.assertEqual(p.sent, [])


if __name__ == "__main__":
    unittest.main()
