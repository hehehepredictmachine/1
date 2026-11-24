"""1.40.3: every screen of the monitor opens without JS errors (demo backend), and an error in one screen never blanks the window:
the global boundary shows the error with "Menu główne" / "Odśwież", resets when the user leaves the screen, and a screen chunk that cannot
be fetched (application updated while the window was open) reloads the page once instead of staying empty."""
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


def all_pages() -> list[str]:
    src = (_env.ROOT / "frontend" / "src" / "router.ts").read_text(encoding="utf-8")
    block = src[src.index("export const PAGES"):]
    return sorted(set(re.findall(r'\{ id: "([a-z0-9-]+)"', block)))


@unittest.skipUnless(HAVE_PW, "playwright not installed")
class TestErrorBoundaryUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (_env.ROOT / "frontend" / "dist" / "index.html").exists():
            raise unittest.SkipTest("frontend not built")
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

    def page(self):
        c = self.browser.new_context(viewport={"width": 1600, "height": 950})
        c.add_init_script("try{localStorage.setItem('pmw.boot.seen','1')}catch(e){}")
        p = c.new_page()
        p.errors, p.loads = [], [0]
        p.on("pageerror", lambda e: p.errors.append("PAGEERROR " + str(e)))
        p.on("console", lambda m: p.errors.append(m.text) if m.type == "error" else None)
        p.on("load", lambda: p.loads.__setitem__(0, p.loads[0] + 1))
        return c, p

    def test_01_every_screen_opens_without_js_errors(self):
        c, p = self.page()
        try:
            p.goto(BASE + "/#/menu")
            p.wait_for_timeout(2500)
            broken = {}
            for pg in all_pages():
                p.errors.clear()
                p.evaluate("h => { location.hash = h; }", "#/" + pg)
                p.wait_for_timeout(1800)
                errs = [e for e in p.errors if "WebSocket" not in e and "favicon" not in e and "Failed to load resource" not in e]
                if p.query_selector(".pmw-crash") or errs:
                    broken[pg] = errs[:3] or ["boundary shown"]
            self.assertEqual(broken, {})
        finally:
            c.close()

    def test_02_broken_screen_shows_the_boundary_and_recovers(self):
        c, p = self.page()
        try:
            p.route(re.compile(r"/assets/StrategyLab-.*\.js$"),
                    lambda r: r.fulfill(content_type="text/javascript", body='throw new Error("test: ekran zepsuty")'))
            p.goto(BASE + "/#/menu")
            p.wait_for_timeout(2000)
            p.evaluate("() => { location.hash = '#/strategy-lab'; }")
            p.wait_for_selector(".pmw-crash", timeout=10000)
            txt = p.inner_text(".pmw-crash")
            self.assertIn("Ten ekran napotkał błąd", txt)
            self.assertIn("test: ekran zepsuty", txt)
            self.assertIn("Menu główne", txt)
            p.click("text=Menu główne")
            p.wait_for_timeout(1500)
            self.assertIsNone(p.query_selector(".pmw-crash"))
            self.assertTrue(p.evaluate("() => location.hash.startsWith('#/menu')"))
        finally:
            c.close()

    def test_03_missing_chunk_reloads_once_then_explains(self):
        c, p = self.page()
        try:
            p.route(re.compile(r"/assets/StrategyLab-.*\.js$"), lambda r: r.abort())
            p.goto(BASE + "/#/menu")
            p.wait_for_timeout(2000)
            p.evaluate("() => { location.hash = '#/strategy-lab'; }")
            p.wait_for_selector(".pmw-crash", timeout=15000)
            self.assertEqual(p.loads[0], 2)          # one automatic reload, no loop
            p.wait_for_timeout(2500)
            self.assertEqual(p.loads[0], 2)
        finally:
            c.close()


if __name__ == "__main__":
    unittest.main()
