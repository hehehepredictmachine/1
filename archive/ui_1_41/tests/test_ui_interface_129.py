"""One interface in the style of the three towers (1.29, §2 of the update package; 1.30: license system removed), Chromium on the demo
bot (terminal simulator):
 1. the side menu is grouped by tower areas (Precision, Dyscypline, Profits, Modele i trening, Ustawienia i diagnostyka); the status
    (instrument, broker symbol, MT5, last data time, DEMO/LIVE/SYNTETYCZNE, mode, STOP) is visible in all three frames (AppShell, tower
    views, terminal);
 2. every old hash link still opens its screen (the map old -> new is on the Ustawienia page); #/licencje (1.27-1.29) opens Ustawienia;
 3. 1280x720 and 1920x1080 without horizontal scrolling, a high-DPI (2x) render, keyboard focus visible, prefers-reduced-motion
    switches animations off;
 4. 1.30: nothing of the license system is left - no KEY FOR MAGIC window, no license / edition chip, no Licencje area, the license API
    answers 404, a leftover edition.json pointed to by MASTERQUO_EDITION_FILE changes nothing.
Screenshots: data/logs/ui_interface_129/. Skipped (never "passed") without Playwright/Chromium."""
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
SHOTS = _env.ROOT / "data" / "logs" / "ui_interface_129"
PORT = 8802
AREAS = ["precision", "dyscypline", "profits", "modele", "ustawienia"]
OLD_LINKS = {   # hash -> selector of the screen (unchanged ids since 1.10-1.28)
    "#/pulpit": "main.page[data-page=pulpit]", "#/wykresy": "main.page[data-page=wykresy]", "#/strefy": "[data-testid=page-strefy]",
    "#/scalp-mtf": "main.page[data-page=scalp-mtf]", "#/kontekst": "main.page[data-page=kontekst]", "#/indykatory": "main.page[data-page=indykatory]",
    "#/sygnal": "main.page[data-page=sygnal]", "#/setupy": "main.page[data-page=setupy]", "#/warunki": "main.page[data-page=warunki]",
    "#/strategie": "main.page[data-page=strategie]", "#/ai": "[data-testid=page-ai]", "#/pozycje": "main.page[data-page=pozycje]",
    "#/dziennik": "main.page[data-page=dziennik]", "#/modele": "main.page[data-page=modele]", "#/trening": "main.page[data-page=trening]",
    "#/neural": "main.page[data-page=neural]", "#/struktura": "main.page[data-page=struktura]", "#/testy": "main.page[data-page=testy]",
    "#/badania": "main.page[data-page=badania]", "#/formacje": "main.page[data-page=formacje]", "#/dane": "main.page[data-page=dane]",
    "#/diagnostyka": "main.page[data-page=diagnostyka]", "#/ustawienia": "main.page[data-page=ustawienia]",
    "#/menu": "[data-testid=galaxy-menu]", "#/precision": "[data-testid=wizard-shell][data-page=precision]",
    "#/dyscypline": "[data-testid=wizard-shell][data-page=dyscypline]", "#/profits": "[data-testid=wizard-shell][data-page=profits]",
    "#/trading-intelligence": "[data-testid=terminal-shell]", "#/ai-neural-lab": "[data-testid=terminal-shell]", "#/system-control": "[data-testid=terminal-shell]",
}
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


def start(port):
    td = TempData()
    with open(os.path.join(td.dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump({"server": {"port": port, "open_browser": False}, "news": {"enabled": False}, "clock": {"reference_url": None},
                   "first_run_completed": True}, f)
    with open(os.path.join(td.dir, "edition.json"), "w", encoding="utf-8") as f:
        json.dump({"edition": "CLIENT"}, f)                     # leftover of 1.27-1.29: must change nothing any more
    env = dict(os.environ, MASTERQUO_DATA_DIR=td.dir, PYTHONPATH=str(_env.ROOT / "backend"),
               MASTERQUO_EDITION_FILE=os.path.join(td.dir, "edition.json"))
    env.pop("ANTHROPIC_API_KEY", None)
    proc = subprocess.Popen([sys.executable, "-m", "masterquo", "serve", "--demo", "--no-browser"], env=env, cwd=str(_env.ROOT / "backend"),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return td, env, proc


@unittest.skipUnless(HAVE_PW, "playwright not installed")
class TestInterface129(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (_env.ROOT / "frontend" / "dist" / "index.html").exists():
            raise unittest.SkipTest("frontend not built")
        SHOTS.mkdir(parents=True, exist_ok=True)
        cls.td, cls.env, cls.proc = start(PORT)
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

    def page(self, port=PORT, **kw):
        ctx = self.browser.new_context(viewport=kw.pop("viewport", {"width": 1920, "height": 1080}), **kw)
        p = ctx.new_page()
        p.errors = []
        p.on("pageerror", lambda e: p.errors.append(str(e)))
        p.goto(f"http://127.0.0.1:{port}/#/pulpit")
        p.wait_for_selector("[data-testid=topbar]", timeout=60000)
        self.assertTrue(wait_for(lambda: p.locator("[data-testid=chip-mt5]").count() == 1, 30, 0.3))
        return ctx, p

    def no_hscroll(self, p):
        return p.evaluate("() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")

    def test_01_areas_status_title(self):
        ctx, p = self.page(PORT)
        try:
            areas = [g.get_attribute("data-group") for g in p.locator("[data-testid=sidenav] .nav-group").all()]
            self.assertEqual(areas, AREAS)
            self.assertTrue(p.locator("[data-testid=nav-menu]").is_visible())
            self.assertTrue(p.title().startswith("PepeMarketWizard – "), p.title())
            # status in the AppShell: instrument, symbol, MT5, last data time, kind of data, mode, STOP
            self.assertTrue(p.locator("[data-testid=asset-switch] .asset-btn.on").count() == 1)
            for tid in ("chip-exec", "chip-mt5", "chip-data-time", "chip-env", "chip-mode", "stop-button"):
                self.assertTrue(p.locator(f"[data-testid={tid}]").is_visible(), tid)
            self.assertEqual(p.locator("[data-testid=chip-env]").get_attribute("data-env"), "SYNTHETIC")
            self.assertIn("SYNTETYCZNE", p.locator("[data-testid=chip-env]").inner_text())
            self.assertTrue(wait_for(lambda: p.locator("[data-testid=chip-data-time] b").inner_text() != "—", 30, 0.5))
            p.screenshot(path=str(SHOTS / "01_owner_appshell_1920.png"))
            # tower views: areas, data time
            p.goto(f"http://127.0.0.1:{PORT}/#/precision")
            p.wait_for_selector("[data-testid=wz-top]", timeout=30000)
            for tid in ("wz-area-modele", "wz-area-ustawienia", "wz-mt5", "wz-fresh", "wz-bot"):
                self.assertTrue(p.locator(f"[data-testid={tid}]").count() == 1, tid)
            self.assertTrue(wait_for(lambda: p.locator("[data-testid=wz-data-time]").count() == 1, 20, 0.3))
            self.assertIn("SYMULATOR", p.locator("[data-testid=wz-bot]").inner_text())
            # terminal frame
            p.goto(f"http://127.0.0.1:{PORT}/#/system-control")
            p.wait_for_selector("[data-testid=t-header]", timeout=30000)
            for tid in ("t-env", "t-mt5", "t-fresh", "t-mode", "t-entries", "t-instrument"):
                self.assertTrue(p.locator(f"[data-testid={tid}]").count() == 1, tid)
            self.assertEqual([a.get_attribute("data-section") for a in p.locator("[data-testid=t-existing] [data-section]").all()], AREAS)
            self.assertEqual(p.errors, [])
        finally:
            ctx.close()

    def test_02_old_links_and_screen_map(self):
        ctx, p = self.page(PORT)
        try:
            for h, sel in OLD_LINKS.items():
                p.goto(f"http://127.0.0.1:{PORT}/{h}")
                p.wait_for_selector(sel, timeout=30000)
                hh = p.evaluate("() => location.hash")
                self.assertTrue(hh == h or hh.startswith(h + "/"), (h, hh))        # #/warunki opens the bot's setup: #/warunki/<id>
            p.goto(f"http://127.0.0.1:{PORT}/#/warunki/S01")          # deep link with a setup id
            p.wait_for_selector("main.page[data-page=warunki]", timeout=30000)
            p.goto(f"http://127.0.0.1:{PORT}/#/ustawienia")
            p.wait_for_selector("[data-testid=screen-map]")
            p.locator("[data-testid=screen-map] summary").click()
            txt = p.locator("[data-testid=screen-map]").inner_text()
            for h in ("#/wykresy", "#/licencje", "#/badania", "#/pozycje"):            # #/licencje: "usunięte w 1.30"
                self.assertIn(h, txt)
            # the active page keeps its area highlighted in the side menu and the sub-tabs carry the area
            p.goto(f"http://127.0.0.1:{PORT}/#/dziennik")
            p.wait_for_selector("main.page[data-page=dziennik]")
            self.assertEqual(p.locator("[data-testid=sidenav] .nav-group.cur").get_attribute("data-group"), "profits")
            self.assertEqual(p.locator("[data-testid=subtabs]").get_attribute("data-area"), "profits")
            self.assertEqual(p.errors, [])
        finally:
            ctx.close()

    def test_03_resolutions_dpi_focus_reduced_motion(self):
        for vp, dpr in (({"width": 1280, "height": 720}, 1), ({"width": 1920, "height": 1080}, 1), ({"width": 1280, "height": 720}, 2)):
            ctx, p = self.page(PORT, viewport=vp, device_scale_factor=dpr)
            try:
                for h in ("#/pulpit", "#/wykresy", "#/strefy", "#/trening", "#/ustawienia", "#/menu", "#/precision", "#/profits"):
                    p.goto(f"http://127.0.0.1:{PORT}/{h}")
                    p.wait_for_selector(OLD_LINKS[h], timeout=30000)
                    p.wait_for_timeout(400)
                    self.assertTrue(self.no_hscroll(p), f"{vp} x{dpr} {h}: horizontal scroll")
                    if h in ("#/wykresy", "#/menu"):
                        p.screenshot(path=str(SHOTS / f"{h.strip('#/')}_{vp['width']}x{vp['height']}@{dpr}x.png"))
                self.assertEqual(p.errors, [])
            finally:
                ctx.close()
        # keyboard: Tab reaches the menu with a visible focus ring
        ctx, p = self.page(PORT, viewport={"width": 1280, "height": 720})
        try:
            p.goto(f"http://127.0.0.1:{PORT}/#/wykresy")
            p.wait_for_selector("main.page[data-page=wykresy]")
            seen = None
            for _ in range(40):
                p.keyboard.press("Tab")
                info = p.evaluate("() => { const e = document.activeElement; if (!e) return null; const cs = getComputedStyle(e);"
                                  " return { nav: !!e.closest('[data-testid=sidenav]'), outline: cs.outlineStyle, width: cs.outlineWidth,"
                                  " fv: e.matches(':focus-visible') }; }")
                if info and info["nav"]:
                    seen = info
                    break
            self.assertIsNotNone(seen, "Tab never reached the side menu")
            self.assertTrue(seen["fv"])
            self.assertNotEqual(seen["outline"], "none")
            p.keyboard.press("Enter")                                       # a menu link works from the keyboard
            p.wait_for_timeout(500)
            self.assertNotEqual(p.url.split("#")[-1], "/wykresy")
        finally:
            ctx.close()
        # prefers-reduced-motion: animations / transitions switched off
        ctx, p = self.page(PORT, viewport={"width": 1280, "height": 720}, reduced_motion="reduce")
        try:
            dur = p.evaluate("() => { const b = document.querySelector('.chip') || document.body; const cs = getComputedStyle(b);"
                             " return [cs.transitionDuration, cs.animationDuration]; }")
            for d in dur:
                self.assertTrue(all(float(x.strip().rstrip("ms").rstrip("s") or 0) < 0.05 for x in d.split(",")), dur)
            p.goto(f"http://127.0.0.1:{PORT}/#/menu")
            p.wait_for_selector(OLD_LINKS["#/menu"], timeout=30000)
            self.assertEqual(p.evaluate("() => matchMedia('(prefers-reduced-motion: reduce)').matches"), True)
        finally:
            ctx.close()

    def test_04_no_license_system_left(self):
        ctx, p = self.page()
        try:
            p.wait_for_timeout(1500)
            for sel in ("[data-testid=chip-edition]", "[data-testid=license-chip]", "[data-testid=key-for-magic]", "[data-testid=sidenav] [data-page=licencje]",
                        "[data-testid=sidenav] [data-group=licencje]"):
                self.assertEqual(p.locator(sel).count(), 0, sel)
            self.assertNotIn("KEY FOR MAGIC", p.locator("body").inner_text())
            self.assertNotIn("OWNER", p.title())
            self.assertNotIn("CLIENT", p.title())
            for path in ("/api/v1/license", "/api/v1/owner/license-server", "/api/v1/owner/licenses"):
                st = p.evaluate("async (u) => (await fetch(u, {credentials: 'same-origin'})).status", path)
                self.assertEqual(st, 404, path)
            self.assertNotIn("license", p.evaluate("async () => Object.keys(await (await fetch('/api/v1/state')).json())"))
            p.goto(f"http://127.0.0.1:{PORT}/#/licencje")                  # the 1.27-1.29 link opens Ustawienia
            p.wait_for_selector("main.page[data-page=ustawienia]", timeout=20000)
            p.goto(f"http://127.0.0.1:{PORT}/#/precision")
            p.wait_for_selector("[data-testid=wz-top]", timeout=30000)
            self.assertEqual(p.locator("[data-testid=wz-area-licencje]").count(), 0)
            p.goto(f"http://127.0.0.1:{PORT}/#/system-control")
            p.wait_for_selector("[data-testid=t-header]", timeout=30000)
            self.assertEqual(p.locator("[data-testid=t-edition]").count(), 0)
            self.assertEqual([a.get_attribute("data-section") for a in p.locator("[data-testid=t-existing] [data-section]").all()], AREAS)
            p.screenshot(path=str(SHOTS / "04_no_license.png"))
            self.assertEqual(p.errors, [])
        finally:
            ctx.close()


if __name__ == "__main__":
    unittest.main()
