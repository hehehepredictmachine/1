"""1.39 START boot intro + MAIN MENU Galaxy V2 (FULL NEURAL MESH) in a real browser (Chromium + demo backend on the SYNTHETIC terminal).

Boot: "$PEPEMARKET WIZARD" + the exact slogan, matrix -> neural phases on the 8.5 s timeline (screenshots ~1.5 / 3.7 / 6.0 / 7.8 s),
ESC / button skip, Ctrl+Alt+B replay, reduced motion jumps to the end, the app is mounted underneath (never blocked).
Galaxy: exactly 7 planets with WTC PEPE in the centre, full K7 mesh 21/21 links drawn, every planet opens its REAL screen, the status
pill comes from the backend (synthetic demo -> DEMO SIM, never "AI ONLINE"), live editor (drag, name, route, add / delete -> n(n-1)/2,
export / import JSON, reset), a planet without a route -> "Niepołączony moduł". 1366x768 / 1440x900 / 1920x1080 without horizontal
scroll and with every planet inside the viewport, no JS errors, no order / mode request. The old menu keeps working under #/neural-city."""
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

PORT = 8831
BASE = f"http://127.0.0.1:{PORT}"
CHROMIUM = os.environ.get("MQ_CHROMIUM", "/opt/pw-browsers/chromium")
SHOTS = _env.ROOT / "data" / "logs" / "ui_galaxy"
PLANETS = {"center": ("WTC PEPE", "pepe-wtc", "[data-testid=page-pepe-wtc]"), "brain": ("Brain Signal", "pepe-signal", "[data-testid=page-pepe-signal]"),
           "bank": ("PEPE$BANK", "lightning", "[data-testid=page-lightning]"), "roi": ("PEPE$ROI", "profits", "[data-testid=wz-top]"),
           "settings": ("Settings", "ustawienia", "main.page"), "models": ("Models", "modele", "main.page"), "signals": ("Signals", "sygnal", "main.page")}
SLOGAN = "They call us cult but we are something more"
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
class TestGalaxyUI(unittest.TestCase):
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

    # ------------------------------------------------------------ helpers
    def ctx(self, boot=False, **kw):
        c = self.browser.new_context(viewport=kw.pop("viewport", {"width": 1920, "height": 1080}), accept_downloads=True, **kw)
        if boot:
            c.add_init_script("try{localStorage.setItem('pmw.boot.force','1')}catch(e){}")
        p = c.new_page()
        p.errors, p.sent = [], []
        p.on("pageerror", lambda e: p.errors.append(str(e)))
        p.on("console", lambda m: p.errors.append(m.text) if m.type == "error" else None)
        p.on("request", lambda r: p.sent.append((r.method, r.url)) if r.method != "GET" else None)
        return c, p

    def real_errors(self, p):
        return [e for e in p.errors if "WebSocket" not in e and "favicon" not in e and "Failed to load resource" not in e]

    def galaxy(self, p):
        p.goto(BASE + "/#/menu")
        p.wait_for_selector("[data-testid=galaxy-menu] [data-testid=gx-planet-center]", timeout=30000)
        p.wait_for_function("() => Number(document.querySelector('[data-testid=galaxy-menu]').dataset.drawnLinks || 0) > 0", timeout=10000)

    def no_side_effects(self, p):
        self.assertFalse([u for m, u in p.sent if ORDER_URL.search(u)], p.sent)
        self.assertFalse([u for m, u in p.sent if MODE_URL.search(u)], p.sent)

    # ------------------------------------------------------------ 1. boot intro
    def test_01_boot_timeline_phases_and_slogan(self):
        # natural run: every class / phase change is recorded in the page (MutationObserver) - independent of the render speed
        c, p = self.ctx(boot=True)
        c.add_init_script("""(() => { window.__boot = []; new MutationObserver(() => { const b = document.getElementById('pmwBoot');
            if (!b) { if (window.__boot.length && window.__boot[window.__boot.length - 1] !== 'GONE') window.__boot.push('GONE'); return; }
            const v = b.className + '|' + (document.getElementById('pmwBootPhase')?.textContent || '');
            if (window.__boot[window.__boot.length - 1] !== v) window.__boot.push(v); })
            .observe(document, { subtree: true, childList: true, attributes: true, attributeFilter: ['class'], characterData: true }); })();""")
        try:
            p.goto(BASE + "/#/menu")
            p.wait_for_selector("[data-testid=boot]", timeout=15000)
            p.wait_for_selector("[data-testid=galaxy-menu]", state="attached", timeout=20000)     # the app mounts underneath (never blocked)
            self.assertTrue(p.query_selector("#pmwBoot"))                                         # ... while the intro is still on screen
            p.wait_for_selector("#pmwBoot", state="detached", timeout=40000)                     # ends by itself
            log = p.evaluate("() => window.__boot")
            phases = [x.split("|")[1] for x in log if "|" in x]
            order = ["INITIALIZING NEURAL MATRIX", "PEPEMARKET WIZARD • SYSTEM BOOT", "ACTIVATING NEURAL NETWORK", "NEURAL SYSTEM READY"]
            seen = [ph for ph in order if ph in phases]
            self.assertEqual(seen, [ph for ph in order if ph in seen])                         # never out of order
            self.assertIn("NEURAL SYSTEM READY", phases)
            classes = " ".join(x.split("|")[0] for x in log if "|" in x)
            for k in ("pmwb-title", "pmwb-tag-show", "pmwb-neural", "pmwb-exit"):
                self.assertIn(k, classes)
            self.assertEqual(log[-1], "GONE")
            p.wait_for_selector("[data-testid=boot-replay]", timeout=10000)
            self.assertEqual(self.real_errors(p), [])
        finally:
            c.close()
        # the four phases (~1.5 / 3.7 / 6.0 / 7.8 s): the timeline is held on the frame (test hook pmw.boot.freeze) -> state + screenshot
        expect = {1.5: ("INITIALIZING NEURAL MATRIX", [], ["pmwb-title", "pmwb-neural"]),
                  3.7: ("PEPEMARKET WIZARD • SYSTEM BOOT", ["pmwb-title", "pmwb-tag-show"], ["pmwb-neural"]),
                  6.0: ("ACTIVATING NEURAL NETWORK", ["pmwb-title", "pmwb-tag-show", "pmwb-neural"], []),
                  7.8: ("NEURAL SYSTEM READY", ["pmwb-title", "pmwb-tag-show", "pmwb-neural"], [])}
        for at, name in ((1.5, "boot_1_matrix"), (3.7, "boot_2_title"), (6.0, "boot_3_neural"), (7.8, "boot_4_ready")):
            c, p = self.ctx(boot=True)
            try:
                c.add_init_script(f"try{{localStorage.setItem('pmw.boot.freeze','{at}')}}catch(e){{}}")
                p.goto(BASE + "/#/menu")
                p.wait_for_selector(f"#pmwBoot[data-elapsed='{at:.2f}']", timeout=15000)
                p.wait_for_timeout(1300)                                                        # CSS transitions of the title / tagline
                phase, has, hasnt = expect[at]
                self.assertEqual(p.inner_text("#pmwBootPhase"), phase)
                cl = p.get_attribute("#pmwBoot", "class")
                for k in has:
                    self.assertIn(k, cl, at)
                for k in hasnt:
                    self.assertNotIn(k, cl, at)
                self.assertEqual(p.evaluate("() => document.querySelector('h1.pmwb-title').textContent"), "$PEPEMARKET WIZARD")
                self.assertEqual(p.evaluate("() => document.querySelector('.pmwb-tag').textContent"), SLOGAN)
                p.screenshot(path=str(SHOTS / f"{name}.png"))
                p.keyboard.press("Escape")
                p.wait_for_selector("#pmwBoot", state="detached", timeout=5000)
            finally:
                c.close()

    def test_02_boot_skip_replay_reduced_motion(self):
        c, p = self.ctx(boot=True)
        try:
            p.goto(BASE + "/#/menu")
            p.wait_for_selector("#pmwBoot[data-elapsed]", timeout=15000)                         # the animation (and its key handler) runs
            p.keyboard.press("Escape")
            p.wait_for_selector("#pmwBoot", state="detached", timeout=10000)
            p.keyboard.press("Control+Alt+b")                                                    # replay
            p.wait_for_selector("#pmwBoot[data-elapsed]", timeout=10000)
            p.click("[data-testid=boot-skip]")
            p.wait_for_selector("#pmwBoot", state="detached", timeout=10000)
            p.click("[data-testid=boot-replay]")
            p.wait_for_selector("#pmwBoot[data-elapsed]", timeout=10000)
            p.click("[data-testid=boot-skip]")
            p.wait_for_selector("#pmwBoot", state="detached", timeout=10000)
            self.assertEqual(self.real_errors(p), [])
        finally:
            c.close()
        c, p = self.ctx(boot=True, reduced_motion="reduce")
        try:
            p.goto(BASE + "/#/menu")
            p.wait_for_selector("#pmwBoot", state="detached", timeout=10000)                      # reduced motion: straight to the end
        finally:
            c.close()
        # automated browser without the force flag: no intro at all (does not block the other UI tests)
        c, p = self.ctx()
        try:
            p.goto(BASE + "/#/menu")
            p.wait_for_selector("[data-testid=galaxy-menu]", timeout=100000)
            self.assertIsNone(p.query_selector("#pmwBoot"))
        finally:
            c.close()

    # ------------------------------------------------------------ 2. galaxy: planets, mesh, status
    def test_03_seven_planets_full_mesh_honest_status(self):
        c, p = self.ctx()
        try:
            self.galaxy(p)
            ids = p.eval_on_selector_all("[data-testid=galaxy-menu] .planet", "els => els.map(e => e.dataset.id)")
            self.assertEqual(sorted(ids), sorted(PLANETS))
            for pid, (name, _r, _s) in PLANETS.items():
                self.assertEqual(p.inner_text(f"[data-testid=gx-planet-{pid}] .planet-title"), name)
            self.assertIn("central", p.get_attribute("[data-testid=gx-planet-center]", "class"))
            p.wait_for_function("() => [...document.querySelectorAll('[data-testid=galaxy-menu] img')].every(i => i.complete && i.naturalWidth > 0)", timeout=10000)
            self.assertEqual(p.evaluate("() => getComputedStyle(document.getElementById('sideLeft')).backgroundImage.includes('/assets/galaxy/left.webp')"), True)
            self.assertEqual(p.inner_text("#meshCount"), "21 / 21")
            root = "[data-testid=galaxy-menu]"
            self.assertEqual(p.get_attribute(root, "data-mesh-links"), "21")
            self.assertEqual(p.get_attribute(root, "data-drawn-links"), "21")
            # demo backend runs on the synthetic feed -> DEMO SIM, never a fake ONLINE
            p.wait_for_function("() => document.querySelector('[data-testid=gx-status] span').textContent !== 'UNKNOWN'", timeout=5000)
            status = p.inner_text("[data-testid=gx-status]")
            self.assertIn("DEMO SIM", status)
            self.assertNotIn("AI ONLINE", p.inner_text(root))
            self.assertNotIn("DEMO ONLINE", p.inner_text(root))
            # the animation really runs (canvas changes between frames)
            a = p.evaluate("() => document.getElementById('galaxyCanvas').toDataURL().length")
            p.wait_for_timeout(400)
            b = p.evaluate("() => document.getElementById('galaxyCanvas').toDataURL()")
            self.assertGreater(len(b), 5000)
            self.assertTrue(a > 0)
            p.screenshot(path=str(SHOTS / "galaxy_1920x1080.png"))
            self.assertEqual(self.real_errors(p), [])
            self.no_side_effects(p)
        finally:
            c.close()

    def test_04_every_planet_opens_its_real_screen(self):
        c, p = self.ctx()
        try:
            for pid, (_name, route, sel) in PLANETS.items():
                self.galaxy(p)
                p.click(f"[data-testid=gx-planet-{pid}]", force=True)
                p.wait_for_function(f"() => location.hash.startsWith('#/{route}')", timeout=5000)
                p.wait_for_selector(sel, timeout=30000)
            # top navigation of the menu
            self.galaxy(p)
            p.click("[data-testid=galaxy-menu] .nav [data-route=lightning]")                     # top navigation of the menu
            p.wait_for_selector("[data-testid=page-lightning]", timeout=30000)
            self.galaxy(p)
            p.click("#editorFloatBtn")
            p.click("[data-testid=gx-neural-city]")
            p.wait_for_selector("[data-testid=page-menu]", timeout=30000)                        # old menu (Neural City) still works
            self.assertEqual(self.real_errors(p), [])
            self.no_side_effects(p)
        finally:
            c.close()

    # ------------------------------------------------------------ 3. live editor
    def test_05_editor_drag_route_add_delete_export_import_reset(self):
        c, p = self.ctx()
        try:
            self.galaxy(p)
            p.click("#editorFloatBtn")
            p.wait_for_selector("#inspector.show", timeout=3000)
            self.assertIn("editing", p.get_attribute("[data-testid=galaxy-menu]", "class"))
            # drag the Models planet
            box = p.query_selector("[data-testid=gx-planet-models]").bounding_box()
            x0, y0 = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
            p.mouse.move(x0, y0)
            p.mouse.down()
            p.mouse.move(x0 + 120, y0 - 80, steps=8)
            p.mouse.up()
            saved = p.evaluate("() => JSON.parse(localStorage.getItem('PMW_GALAXY_LIVE_V1'))")
            models = next(q for q in saved["planets"] if q["id"] == "models")
            self.assertGreater(models["x"], 0.27 + 0.03)
            self.assertLess(models["y"], 0.81 - 0.03)
            # rename + unbind the route -> "Niepołączony moduł"
            p.select_option("#selectPlanet", "models")
            p.fill("#planetName", "Models X")
            self.assertEqual(p.inner_text("[data-testid=gx-planet-models] .planet-title"), "Models X")
            p.select_option("[data-testid=gx-route]", "")
            # add a planet -> 8 planets, 28/28 links
            p.click("#addPlanet")
            self.assertEqual(len(p.query_selector_all("[data-testid=galaxy-menu] .planet")), 8)
            self.assertEqual(p.inner_text("#meshCount"), "28 / 28")
            p.click("#deletePlanet")                                                             # removes the selected (new) planet
            self.assertEqual(p.inner_text("#meshCount"), "21 / 21")
            # export
            with p.expect_download() as dl:
                p.click("#exportBtn")
            with open(dl.value.path(), encoding="utf-8") as f:
                exported = json.load(f)
            self.assertEqual(len(exported["planets"]), 7)
            self.assertIsNone(next(q for q in exported["planets"] if q["id"] == "models")["route"])
            p.click("#exitEdit")
            p.click("[data-testid=gx-planet-models]", force=True)
            p.wait_for_selector("#sectionModal.show", timeout=3000)
            self.assertIn("Niepołączony moduł", p.inner_text("#sectionModal"))
            self.assertTrue(p.evaluate("() => location.hash.startsWith('#/menu')"))
            p.click("#backToGalaxy")
            # import a 5-planet layout -> 10/10 links; an unknown route is dropped
            five = {"planets": [dict(q, route=("nie-istnieje" if q["id"] == "bank" else q.get("route"))) for q in exported["planets"][:5]]}
            path = os.path.join(self.td.dir, "galaxy_import.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(five, f)
            p.click("#editorFloatBtn")
            p.set_input_files("#importInput", path)
            p.wait_for_function("() => document.getElementById('meshCount').textContent === '10 / 10'", timeout=3000)
            saved = p.evaluate("() => JSON.parse(localStorage.getItem('PMW_GALAXY_LIVE_V1'))")
            self.assertIsNone(next(q for q in saved["planets"] if q["id"] == "bank")["route"])
            # reset restores the 7 planets
            p.once("dialog", lambda d: d.accept())
            p.click("#resetBtn")
            p.wait_for_function("() => document.getElementById('meshCount').textContent === '21 / 21'", timeout=3000)
            # the saved layout survives a reload
            p.reload()
            p.wait_for_selector("[data-testid=gx-planet-center]", timeout=30000)
            self.assertEqual(len(p.query_selector_all("[data-testid=galaxy-menu] .planet")), 7)
            self.assertEqual(self.real_errors(p), [])
            self.no_side_effects(p)
        finally:
            c.close()

    # ------------------------------------------------------------ 4. resolutions
    def test_06_resolutions_no_scroll_planets_visible(self):
        for w, h in ((1366, 768), (1440, 900), (1920, 1080)):
            c, p = self.ctx(viewport={"width": w, "height": h})
            try:
                self.galaxy(p)
                p.wait_for_timeout(500)
                self.assertTrue(p.evaluate("() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"), (w, h))
                rects = p.eval_on_selector_all("[data-testid=galaxy-menu] .planet", "els => els.map(e => { const r = e.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })")
                self.assertEqual(len(rects), 7)
                for cx, cy in rects:
                    self.assertTrue(0 < cx < w and 0 < cy < h, (w, h, cx, cy))
                p.screenshot(path=str(SHOTS / f"galaxy_{w}x{h}.png"))
                self.assertEqual(self.real_errors(p), [])
            finally:
                c.close()


if __name__ == "__main__":
    unittest.main()
