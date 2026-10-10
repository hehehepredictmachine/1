"""Monitor UI in a real browser (Chromium via Playwright) on the synthetic demo backend.

Covers: independent zoom per chart, no view reset on data refresh / ticks / theme change / resize, persistence after
reload, per-panel buttons, theme import validation, entry checklist and ML panel. Skipped (never "passed") when
Playwright or Chromium is not available.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import unittest

import _env
from _env import TempData, wait_for

PORT = 8797
BASE = f"http://127.0.0.1:{PORT}"
CHROMIUM = os.environ.get("MQ_CHROMIUM", "/opt/pw-browsers/chromium")

try:
    from playwright.sync_api import sync_playwright
    HAVE_PW = True
except ImportError:  # pragma: no cover
    HAVE_PW = False


def _health() -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(BASE + "/api/v1/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


@unittest.skipUnless(HAVE_PW, "playwright not installed")
class TestMonitorUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (_env.ROOT / "frontend" / "dist" / "index.html").exists():
            raise unittest.SkipTest("frontend not built (npm run build)")
        cls.td = TempData()
        with open(os.path.join(cls.td.dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"server": {"port": PORT, "open_browser": False}, "news": {"enabled": False}, "clock": {"reference_url": None}, "first_run_completed": True}, f)
        cls.env = dict(os.environ, MASTERQUO_DATA_DIR=cls.td.dir, PYTHONPATH=str(_env.ROOT / "backend"))
        cls.env.pop("ANTHROPIC_API_KEY", None)
        cls.proc = subprocess.Popen([sys.executable, "-m", "masterquo", "serve", "--demo", "--no-browser"], env=cls.env, cwd=str(_env.ROOT / "backend"),
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not wait_for(_health, 60, 0.5):
            cls.proc.kill()
            raise RuntimeError("server did not start")
        cls.pw = sync_playwright().start()
        kw = {"executable_path": CHROMIUM} if os.path.exists(CHROMIUM) else {}
        try:
            cls.browser = cls.pw.chromium.launch(**kw)
        except Exception as exc:
            cls.pw.stop()
            subprocess.run([sys.executable, "-m", "masterquo", "stop"], env=cls.env, cwd=str(_env.ROOT / "backend"), timeout=60)
            raise unittest.SkipTest(f"chromium not available: {exc}")
        cls.ctx = cls.browser.new_context(viewport={"width": 1700, "height": 1000})
        cls.page = cls.ctx.new_page()
        cls.page.goto(BASE + "/")
        cls.page.wait_for_function("() => window.__mqCharts && ['panel1','panel2','panel3','panel4'].every(k => window.__mqCharts[k] && window.__mqCharts[k].bars() > 50)",
                                   timeout=90000)
        time.sleep(1.0)

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
    def logical(self, cid):
        return self.page.evaluate(f"() => window.__mqCharts['{cid}'].logical()")

    def trange(self, cid):
        return self.page.evaluate(f"() => window.__mqCharts['{cid}'].range()")

    def view(self, cid):
        return self.page.evaluate(f"() => window.__mqCharts['{cid}'].view()")

    def wheel(self, cid, dy, times=4):
        box = self.page.locator(f"[data-chart-id='{cid}'] .chart-box").bounding_box()
        self.page.mouse.move(box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.4)
        for _ in range(times):
            self.page.mouse.wheel(0, dy)
            time.sleep(0.08)
        time.sleep(0.6)

    def width(self, r):
        return r["to"] - r["from"]

    # ------------------------------------------------------------ 1. independent zoom
    def test_01_wheel_zoom_changes_only_that_chart(self):
        before = {c: self.logical(c) for c in ("panel1", "panel2", "panel3", "panel4")}
        self.wheel("panel2", -300)
        after = {c: self.logical(c) for c in ("panel1", "panel2", "panel3", "panel4")}
        self.assertLess(self.width(after["panel2"]), self.width(before["panel2"]) * 0.9, (before["panel2"], after["panel2"]))
        for c in ("panel1", "panel3", "panel4"):
            self.assertAlmostEqual(self.width(after[c]), self.width(before[c]), delta=0.5, msg=c)
        # drag the zoomed chart to the left (manual view, no longer following)
        box = self.page.locator("[data-chart-id='panel2'] .chart-box").bounding_box()
        self.page.mouse.move(box["x"] + box["width"] * 0.4, box["y"] + box["height"] * 0.4)
        self.page.mouse.down()
        self.page.mouse.move(box["x"] + box["width"] * 0.8, box["y"] + box["height"] * 0.4, steps=8)
        self.page.mouse.up()
        time.sleep(0.6)
        self.assertFalse(self.view("panel2")["follow"])
        self.assertAlmostEqual(self.width(self.logical("panel1")), self.width(before["panel1"]), delta=0.5)

    # ------------------------------------------------------------ 2. data refresh / ticks / reconnect-like reload keep the view
    def test_02_full_refresh_and_ticks_do_not_reset_view(self):
        if self.view("panel2")["follow"]:
            self.test_01_wheel_zoom_changes_only_that_chart()
        r0 = self.trange("panel2")
        w0 = self.width(self.logical("panel2"))
        creations = self.page.evaluate("() => window.__mqCharts['panel2'].creations")
        for _ in range(3):
            self.page.evaluate("() => window.__mqRefresh()")          # same path as reconnect/resync: reload of ALL charts
            time.sleep(1.2)
        time.sleep(3)                                                  # live ticks keep arriving meanwhile
        r1 = self.trange("panel2")
        self.assertEqual((r0["from"], r0["to"]), (r1["from"], r1["to"]))
        self.assertAlmostEqual(self.width(self.logical("panel2")), w0, delta=0.5)
        self.assertEqual(self.page.evaluate("() => window.__mqCharts['panel2'].creations"), creations)   # never re-created
        self.assertFalse(self.view("panel2")["follow"])

    # ------------------------------------------------------------ 3. buttons act on one panel only
    def test_03_buttons_per_panel(self):
        w1 = self.width(self.logical("panel1"))
        w3 = self.width(self.logical("panel3"))
        self.page.locator("[data-chart-id='panel3'] [data-act='zoom-in']").click()
        time.sleep(0.5)
        self.assertLess(self.width(self.logical("panel3")), w3)
        self.assertAlmostEqual(self.width(self.logical("panel1")), w1, delta=0.5)
        self.page.locator("[data-chart-id='panel3'] [data-act='zoom-out']").click()
        self.page.locator("[data-chart-id='panel3'] [data-act='latest']").click()
        time.sleep(0.5)
        self.assertTrue(self.view("panel3")["follow"])
        n = self.page.evaluate("() => window.__mqCharts['panel3'].bars()")
        self.assertGreaterEqual(self.logical("panel3")["to"], n - 1)
        self.page.locator("[data-chart-id='panel3'] [data-act='autoscale']").click()
        self.assertFalse(self.view("panel3")["autoScale"])
        self.page.locator("[data-chart-id='panel3'] [data-act='autoscale']").click()
        self.assertTrue(self.view("panel3")["autoScale"])

    # ------------------------------------------------------------ 4. theme change: charts updated in place, view kept
    def test_04_theme_change_keeps_view(self):
        if self.view("panel2")["follow"]:
            self.test_01_wheel_zoom_changes_only_that_chart()
        r0 = self.trange("panel2")
        creations = self.page.evaluate("() => window.__mqCharts['panel2'].creations")
        bg0 = self.page.evaluate("() => getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()")
        self.page.locator("button[title^='Wygląd']").click()
        dlg = self.page.locator(".theme-dialog")
        dlg.locator("select").first.select_option("light")
        time.sleep(0.4)
        dlg.get_by_role("button", name="Zastosuj").click()
        time.sleep(0.8)
        bg1 = self.page.evaluate("() => getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()")
        self.assertNotEqual(bg0, bg1)
        self.assertEqual(self.page.evaluate("() => window.__mqCharts['panel2'].creations"), creations)
        r1 = self.trange("panel2")
        self.assertEqual((r0["from"], r0["to"]), (r1["from"], r1["to"]))
        stored = self.page.evaluate("() => JSON.parse(localStorage.getItem('mq.theme.v1'))")
        self.assertEqual((stored["version"], stored["preset"]), (1, "light"))

    # ------------------------------------------------------------ 5. resize keeps the manual view
    def test_05_resize_keeps_manual_view(self):
        if self.view("panel2")["follow"]:
            self.test_01_wheel_zoom_changes_only_that_chart()
        v0 = self.view("panel2")
        self.page.set_viewport_size({"width": 1400, "height": 900})
        time.sleep(1.0)
        self.page.set_viewport_size({"width": 1700, "height": 1000})
        time.sleep(1.0)
        v1 = self.view("panel2")
        self.assertEqual((v0["from"], v0["to"], v0["follow"]), (v1["from"], v1["to"], v1["follow"]))   # saved state untouched

    # ------------------------------------------------------------ 6. persistence after reload (refresh / restart of the page)
    def test_06_view_and_theme_persist_after_reload(self):
        if self.view("panel2")["follow"]:
            self.test_01_wheel_zoom_changes_only_that_chart()
        time.sleep(0.6)
        v0 = self.view("panel2")
        self.page.reload()
        self.page.wait_for_function("() => window.__mqCharts && window.__mqCharts['panel2'] && window.__mqCharts['panel2'].bars() > 50", timeout=60000)
        time.sleep(1.5)
        v1 = self.view("panel2")
        self.assertFalse(v1["follow"])
        r = self.trange("panel2")
        self.assertLessEqual(abs(r["from"] - v0["from"]), 120)          # within ~one M5 bar of the saved range
        self.assertTrue(self.view("panel1")["follow"])                  # other panels keep their own (default) state
        self.assertEqual(self.page.evaluate("() => document.documentElement.dataset.theme"), "light")

    # ------------------------------------------------------------ 7. theme import validation
    def test_07_theme_import_rejects_foreign_keys(self):
        bad = json.dumps({"schema": "masterquo-theme", "version": 1, "tokens": {"bg": "#000"}, "execution_mode": "AUTO_LIVE"})
        p = os.path.join(self.td.dir, "bad_theme.json")
        with open(p, "w", encoding="utf-8") as f:
            f.write(bad)
        self.page.locator("button[title^='Wygląd']").click()
        dlg = self.page.locator(".theme-dialog")
        dlg.locator("input[type=file]").set_input_files(p)
        self.page.wait_for_selector(".theme-dialog .note.bad")
        self.assertIn("execution_mode", dlg.locator(".note.bad").inner_text())
        dlg.get_by_role("button", name="Anuluj").click()
        st = json.loads(self.page.evaluate("() => fetch('/api/v1/state').then(r => r.text())"))
        self.assertNotEqual(st["mode"]["mode"], "AUTO_LIVE")

    # ------------------------------------------------------------ 8. checklist instead of BUY/SELL, ML panel
    def test_08_checklist_and_ml_panel(self):
        panel = self.page.locator("[data-testid='entry-checklist']")
        panel.wait_for(timeout=30000)
        txt = panel.inner_text()
        for word in ("BUY", "SELL", "LONG", "SHORT"):
            self.assertNotIn(word, txt.upper().replace("LONGER", ""), word)
        self.assertTrue(any(k in txt for k in ("Spełnione", "Brak aktualnego scenariusza")))
        ml = self.page.locator("[data-testid='ml-panel']")
        ml.wait_for(timeout=30000)
        mt = ml.inner_text()
        self.assertTrue(any(s in mt for s in ("COLLECTING", "WAITING_FOR_LABELS", "SHADOW", "ACTIVE")), mt[:300])
        for b in ("Zbieraj dane", "Trenuj teraz", "Wstrzymaj trening", "Historia modeli", "Przywróć poprzedni model"):
            self.assertIn(b, mt)
        ml.get_by_role("button", name="Trenuj teraz").click()
        self.page.wait_for_function("() => document.querySelector(\"[data-testid='ml-panel']\").innerText.includes('ETYKIET')", timeout=15000)


if __name__ == "__main__":
    unittest.main()
