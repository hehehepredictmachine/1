"""1.29 one interface in the style of the three towers (§2 of the update package), Chromium on the demo bot (terminal simulator):
 1. OWNER: the side menu is grouped by tower areas (Precision, Dyscypline, Profits, Modele i trening, Ustawienia i diagnostyka,
    Licencje); the status (instrument, broker symbol, MT5, last data time, DEMO/LIVE/SYNTETYCZNE, mode, STOP, edition / licence) is
    visible in all three frames (AppShell, tower views, terminal); the edition is in the window title;
 2. every old hash link still opens its screen (the map old -> new is on the Ustawienia page);
 3. 1280x720 and 1920x1080 without horizontal scrolling, a high-DPI (2x) render, keyboard focus visible, prefers-reduced-motion
    switches animations off;
 4. CLIENT (MASTERQUO_EDITION_FILE = unstamped CLIENT file): no Licencje area anywhere, #/licencje leads to Ustawienia, title CLIENT.
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
PORT_OWNER, PORT_CLIENT = 8802, 8803
AREAS_OWNER = ["precision", "dyscypline", "profits", "modele", "ustawienia", "licencje"]
OLD_LINKS = {   # hash -> selector of the screen (unchanged ids since 1.10-1.28)
    "#/pulpit": "main.page[data-page=pulpit]", "#/wykresy": "main.page[data-page=wykresy]", "#/strefy": "[data-testid=page-strefy]",
    "#/scalp-mtf": "main.page[data-page=scalp-mtf]", "#/kontekst": "main.page[data-page=kontekst]", "#/indykatory": "main.page[data-page=indykatory]",
    "#/sygnal": "main.page[data-page=sygnal]", "#/setupy": "main.page[data-page=setupy]", "#/warunki": "main.page[data-page=warunki]",
    "#/strategie": "main.page[data-page=strategie]", "#/ai": "[data-testid=page-ai]", "#/pozycje": "main.page[data-page=pozycje]",
    "#/dziennik": "main.page[data-page=dziennik]", "#/modele": "main.page[data-page=modele]", "#/trening": "main.page[data-page=trening]",
    "#/neural": "main.page[data-page=neural]", "#/struktura": "main.page[data-page=struktura]", "#/testy": "main.page[data-page=testy]",
    "#/badania": "main.page[data-page=badania]", "#/formacje": "main.page[data-page=formacje]", "#/dane": "main.page[data-page=dane]",
    "#/diagnostyka": "main.page[data-page=diagnostyka]", "#/ustawienia": "main.page[data-page=ustawienia]", "#/licencje": "main.page[data-page=licencje]",
    "#/menu": "[data-testid=wizard-shell][data-page=menu]", "#/precision": "[data-testid=wizard-shell][data-page=precision]",
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


def start(port, edition_file=None):
    td = TempData()
    with open(os.path.join(td.dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump({"server": {"port": port, "open_browser": False}, "news": {"enabled": False}, "clock": {"reference_url": None},
                   "first_run_completed": True}, f)
    env = dict(os.environ, MASTERQUO_DATA_DIR=td.dir, PYTHONPATH=str(_env.ROOT / "backend"))
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("MASTERQUO_EDITION_FILE", None)
    if edition_file:
        env["MASTERQUO_EDITION_FILE"] = edition_file
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
        cls.procs = []
        cls.td_o, cls.env_o, p1 = start(PORT_OWNER)
        cls.client_file = os.path.join(cls.td_o.dir, "client_edition.json")
        with open(cls.client_file, "w", encoding="utf-8") as f:
            json.dump({"edition": "CLIENT"}, f)                        # not stamped: no server address yet (the honest state of this repo)
        cls.td_c, cls.env_c, p2 = start(PORT_CLIENT, cls.client_file)
        cls.procs = [(p1, cls.env_o, cls.td_o), (p2, cls.env_c, cls.td_c)]
        if not (wait_for(lambda: up(PORT_OWNER), 90, 0.5) and wait_for(lambda: up(PORT_CLIENT), 90, 0.5)):
            for p, _, _ in cls.procs:
                p.kill()
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
            for p, env, td in cls.procs:
                subprocess.run([sys.executable, "-m", "masterquo", "stop"], env=env, cwd=str(_env.ROOT / "backend"), timeout=60)
                try:
                    p.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    p.kill()
                td.close()

    def page(self, port, **kw):
        ctx = self.browser.new_context(viewport=kw.pop("viewport", {"width": 1920, "height": 1080}), **kw)
        p = ctx.new_page()
        p.errors = []
        p.on("pageerror", lambda e: p.errors.append(str(e)))
        p.goto(f"http://127.0.0.1:{port}/#/pulpit")
        p.wait_for_selector("[data-testid=topbar]", timeout=60000)
        self.assertTrue(wait_for(lambda: p.locator("[data-testid=chip-edition]").count() == 1, 30, 0.3))
        return ctx, p

    def no_hscroll(self, p):
        return p.evaluate("() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")

    def test_01_owner_areas_status_title(self):
        ctx, p = self.page(PORT_OWNER)
        try:
            areas = [g.get_attribute("data-group") for g in p.locator("[data-testid=sidenav] .nav-group").all()]
            self.assertEqual(areas, AREAS_OWNER)
            self.assertTrue(p.locator("[data-testid=nav-menu]").is_visible())
            self.assertIn("OWNER", p.title())
            # status in the AppShell: instrument, symbol, MT5, last data time, kind of data, mode, STOP, edition
            self.assertTrue(p.locator("[data-testid=asset-switch] .asset-btn.on").count() == 1)
            for tid in ("chip-exec", "chip-mt5", "chip-data-time", "chip-env", "chip-mode", "chip-edition", "stop-button"):
                self.assertTrue(p.locator(f"[data-testid={tid}]").is_visible(), tid)
            self.assertEqual(p.locator("[data-testid=chip-env]").get_attribute("data-env"), "SYNTHETIC")
            self.assertIn("SYNTETYCZNE", p.locator("[data-testid=chip-env]").inner_text())
            self.assertEqual(p.locator("[data-testid=chip-edition]").get_attribute("data-edition"), "OWNER")
            self.assertTrue(wait_for(lambda: p.locator("[data-testid=chip-data-time] b").inner_text() != "—", 30, 0.5))
            p.screenshot(path=str(SHOTS / "01_owner_appshell_1920.png"))
            # tower views: areas incl. Licencje, data time, licence chip
            p.goto(f"http://127.0.0.1:{PORT_OWNER}/#/precision")
            p.wait_for_selector("[data-testid=wz-top]", timeout=30000)
            for tid in ("wz-area-modele", "wz-area-ustawienia", "wz-area-licencje", "wz-mt5", "wz-fresh", "wz-bot", "license-chip"):
                self.assertTrue(p.locator(f"[data-testid={tid}]").count() == 1, tid)
            self.assertTrue(wait_for(lambda: p.locator("[data-testid=wz-data-time]").count() == 1, 20, 0.3))
            self.assertIn("SYMULATOR", p.locator("[data-testid=wz-bot]").inner_text())
            # terminal frame
            p.goto(f"http://127.0.0.1:{PORT_OWNER}/#/system-control")
            p.wait_for_selector("[data-testid=t-header]", timeout=30000)
            for tid in ("t-env", "t-mt5", "t-fresh", "t-mode", "t-entries", "t-instrument", "t-edition"):
                self.assertTrue(p.locator(f"[data-testid={tid}]").count() == 1, tid)
            self.assertEqual([a.get_attribute("data-section") for a in p.locator("[data-testid=t-existing] [data-section]").all()], AREAS_OWNER)
            self.assertEqual(p.errors, [])
        finally:
            ctx.close()

    def test_02_old_links_and_screen_map(self):
        ctx, p = self.page(PORT_OWNER)
        try:
            for h, sel in OLD_LINKS.items():
                p.goto(f"http://127.0.0.1:{PORT_OWNER}/{h}")
                p.wait_for_selector(sel, timeout=30000)
                hh = p.evaluate("() => location.hash")
                self.assertTrue(hh == h or hh.startswith(h + "/"), (h, hh))        # #/warunki opens the bot's setup: #/warunki/<id>
            p.goto(f"http://127.0.0.1:{PORT_OWNER}/#/warunki/S01")          # deep link with a setup id
            p.wait_for_selector("main.page[data-page=warunki]", timeout=30000)
            p.goto(f"http://127.0.0.1:{PORT_OWNER}/#/ustawienia")
            p.wait_for_selector("[data-testid=screen-map]")
            p.locator("[data-testid=screen-map] summary").click()
            txt = p.locator("[data-testid=screen-map]").inner_text()
            for h in ("#/wykresy", "#/licencje", "#/badania", "#/pozycje"):
                self.assertIn(h, txt)
            # the active page keeps its area highlighted in the side menu and the sub-tabs carry the area
            p.goto(f"http://127.0.0.1:{PORT_OWNER}/#/dziennik")
            p.wait_for_selector("main.page[data-page=dziennik]")
            self.assertEqual(p.locator("[data-testid=sidenav] .nav-group.cur").get_attribute("data-group"), "profits")
            self.assertEqual(p.locator("[data-testid=subtabs]").get_attribute("data-area"), "profits")
            self.assertEqual(p.errors, [])
        finally:
            ctx.close()

    def test_03_resolutions_dpi_focus_reduced_motion(self):
        for vp, dpr in (({"width": 1280, "height": 720}, 1), ({"width": 1920, "height": 1080}, 1), ({"width": 1280, "height": 720}, 2)):
            ctx, p = self.page(PORT_OWNER, viewport=vp, device_scale_factor=dpr)
            try:
                for h in ("#/pulpit", "#/wykresy", "#/strefy", "#/trening", "#/licencje", "#/ustawienia", "#/menu", "#/precision", "#/profits"):
                    p.goto(f"http://127.0.0.1:{PORT_OWNER}/{h}")
                    p.wait_for_selector(OLD_LINKS[h], timeout=30000)
                    p.wait_for_timeout(400)
                    self.assertTrue(self.no_hscroll(p), f"{vp} x{dpr} {h}: horizontal scroll")
                    if h in ("#/wykresy", "#/menu"):
                        p.screenshot(path=str(SHOTS / f"{h.strip('#/')}_{vp['width']}x{vp['height']}@{dpr}x.png"))
                self.assertEqual(p.errors, [])
            finally:
                ctx.close()
        # keyboard: Tab reaches the menu with a visible focus ring
        ctx, p = self.page(PORT_OWNER, viewport={"width": 1280, "height": 720})
        try:
            p.goto(f"http://127.0.0.1:{PORT_OWNER}/#/wykresy")
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
        ctx, p = self.page(PORT_OWNER, viewport={"width": 1280, "height": 720}, reduced_motion="reduce")
        try:
            dur = p.evaluate("() => { const b = document.querySelector('.chip') || document.body; const cs = getComputedStyle(b);"
                             " return [cs.transitionDuration, cs.animationDuration]; }")
            for d in dur:
                self.assertTrue(all(float(x.strip().rstrip("ms").rstrip("s") or 0) < 0.05 for x in d.split(",")), dur)
            p.goto(f"http://127.0.0.1:{PORT_OWNER}/#/menu")
            p.wait_for_selector(OLD_LINKS["#/menu"], timeout=30000)
            self.assertEqual(p.evaluate("() => matchMedia('(prefers-reduced-motion: reduce)').matches"), True)
        finally:
            ctx.close()

    def test_04_client_has_no_license_manager(self):
        ctx, p = self.page(PORT_CLIENT)
        try:
            self.assertEqual(p.locator("[data-testid=chip-edition]").get_attribute("data-edition"), "CLIENT")
            self.assertIn("CLIENT", p.title())
            areas = [g.get_attribute("data-group") for g in p.locator("[data-testid=sidenav] .nav-group").all()]
            self.assertEqual(areas, AREAS_OWNER[:-1])                    # no Licencje
            self.assertEqual(p.locator("[data-testid=sidenav] [data-page=licencje]").count(), 0)
            p.goto(f"http://127.0.0.1:{PORT_CLIENT}/#/licencje")
            self.assertTrue(wait_for(lambda: p.evaluate("() => location.hash") == "#/ustawienia", 20, 0.2))
            p.wait_for_selector("main.page[data-page=ustawienia]")
            p.goto(f"http://127.0.0.1:{PORT_CLIENT}/#/precision")
            p.wait_for_selector("[data-testid=wz-top]", timeout=30000)
            self.assertEqual(p.locator("[data-testid=wz-area-licencje]").count(), 0)
            p.goto(f"http://127.0.0.1:{PORT_CLIENT}/#/system-control")
            p.wait_for_selector("[data-testid=t-header]", timeout=30000)
            self.assertEqual(p.locator("[data-testid=t-edition]").get_attribute("data-edition"), "CLIENT")
            self.assertEqual([a.get_attribute("data-section") for a in p.locator("[data-testid=t-existing] [data-section]").all()], AREAS_OWNER[:-1])
            p.screenshot(path=str(SHOTS / "04_client_terminal.png"))
            self.assertEqual(p.errors, [])
        finally:
            ctx.close()


if __name__ == "__main__":
    unittest.main()
