"""1.29 charts (§3 of the update package) in Chromium on the demo bot (terminal simulator, SYNTHETIC data - only the mechanics are
tested, nothing about market quality):
 1. "Wyznacz strefy" in the main chart area (Wykresy bota): scope M1+M5+M15, several clicks = one job, zones drawn only on the chart of
    their own TF and instrument, M30 untouched, LIVE on/off, the analysis sends no other POST than /market-zones/*, changes neither the
    configuration nor the execution mode and opens nothing;
 2. geometry: drawn boxes stay glued to their candle time / price after zoom, pan and window resize;
 3. per-chart settings: colours / grid / text size / layers survive a reload, other charts are not affected, reset, templates;
 4. the layer menu hides FVG / OB / S&D / S/R / liquidity / labels;
 5. NO_DATA / stale result / reconnect / foreign symbol - the UI reaction to such backend answers (the answer of the real backend is
    altered with page.route; the backend behaviour itself is covered by test_market_zones.py);
 6. the "Strefy rynkowe" page charts have their own settings and layer menu.
Screenshots: data/logs/ui_chart_prefs/. Skipped (never "passed") without Playwright/Chromium."""
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
SHOTS = _env.ROOT / "data" / "logs" / "ui_chart_prefs"
PORT = 8801
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


@unittest.skipUnless(HAVE_PW, "playwright not installed")
class TestChartPrefsUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (_env.ROOT / "frontend" / "dist" / "index.html").exists():
            raise unittest.SkipTest("frontend not built")
        SHOTS.mkdir(parents=True, exist_ok=True)
        cls.td = TempData()
        with open(os.path.join(cls.td.dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"server": {"port": PORT, "open_browser": False}, "news": {"enabled": False}, "clock": {"reference_url": None},
                       "first_run_completed": True,
                       "assets": {"active": "XAUUSD", "mappings": {"XAUUSD": {"broker_symbol": "XAUUSD-", "status": "USER_SPECIFIED"},
                                                                   "BTC": {"broker_symbol": "BTCUSD-", "status": "USER_SPECIFIED"}}}}, f)
        cls.env = dict(os.environ, MASTERQUO_DATA_DIR=cls.td.dir, PYTHONPATH=str(_env.ROOT / "backend"))
        cls.env.pop("ANTHROPIC_API_KEY", None)
        cls.proc = subprocess.Popen([sys.executable, "-m", "masterquo", "serve", "--demo", "--no-browser"], env=cls.env, cwd=str(_env.ROOT / "backend"),
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not wait_for(lambda: up(PORT), 90, 0.5):
            cls.proc.kill()
            raise RuntimeError("bot did not start")
        cls.pw = sync_playwright().start()
        kw = {"executable_path": CHROMIUM} if os.path.exists(CHROMIUM) else {}
        cls.browser = cls.pw.chromium.launch(**kw)
        # one browser profile for the whole class: localStorage survives reloads like in the desktop window
        cls.ctx = cls.browser.new_context(viewport={"width": 1600, "height": 1000})

    @classmethod
    def tearDownClass(cls):
        try:
            cls.ctx.close()
            cls.browser.close()
            cls.pw.stop()
        finally:
            subprocess.run([sys.executable, "-m", "masterquo", "stop"], env=cls.env, cwd=str(_env.ROOT / "backend"), timeout=60)
            try:
                cls.proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                cls.proc.kill()
            cls.td.close()

    def api(self, p, path):
        return p.evaluate("async (u) => (await fetch(u, {credentials: 'same-origin'})).json()", path)

    def chart(self, p, cid, what):
        return p.evaluate(f"() => {{ const c = window.__mqCharts && window.__mqCharts[{json.dumps(cid)}]; return c ? c.{what} : null; }}")

    def open_bot(self, p):
        p.goto(f"http://127.0.0.1:{PORT}/#/wykresy")
        p.wait_for_selector("[data-testid=mzbar]", timeout=60000)
        for tf in ("M1", "M5", "M15"):
            self.assertTrue(wait_for(lambda tf=tf: (self.chart(p, f"bot-{tf}", "bars()") or 0) > 20, 60, 0.3), tf)

    def test_01_zones_button_main_chart_scope_isolation(self):
        p = self.ctx.new_page()
        errors, posts = [], []
        p.on("pageerror", lambda e: errors.append(str(e)))
        p.on("request", lambda r: r.method == "POST" and posts.append(r.url.split(str(PORT), 1)[-1]))
        try:
            self.open_bot(p)
            self.assertTrue(wait_for(lambda: self.api(p, "/api/v1/market-zones/bars?instrument=XAUUSD&tf=M1&count=30")["bars"], 60, 0.5))
            cfg0 = self.api(p, "/api/v1/config")
            st0 = self.api(p, "/api/v1/state")
            self.assertEqual(p.locator("[data-testid=mzbar-scope]").input_value(), "M1-M5-M15")      # default: all three
            p.click("[data-testid=mzbar-compute]")
            p.click("[data-testid=mzbar-compute]")
            p.click("[data-testid=mzbar-compute]")                                                    # several clicks = one job
            p.wait_for_selector("[data-testid=mzbar-job][data-status=DONE]", timeout=60000)
            v = self.api(p, "/api/v1/market-zones?instrument=XAUUSD")
            self.assertEqual(v["counters"]["jobs"], 1)
            self.assertGreaterEqual(v["counters"]["deduplicated_clicks"], 1)
            for tf in ("M1", "M5", "M15"):
                self.assertEqual(v["timeframes"][tf]["status"]["status"], "CONNECTED", tf)
            self.assertEqual(v["timeframes"]["M30"]["status"]["status"], "IDLE")                    # not in the chosen scope
            self.assertNotEqual(p.locator("[data-testid=mzbar-last]").inner_text(), "—")
            for tf in ("M1", "M5", "M15"):
                n = len(v["timeframes"][tf]["zones"])
                self.assertTrue(wait_for(lambda tf=tf: len(self.chart(p, f"bot-{tf}", "mz()") or []) > 0 or n == 0, 20, 0.3), tf)
                drawn = self.chart(p, f"bot-{tf}", "mz()")
                self.assertTrue(all(b["label"].startswith(tf + " ") for b in drawn), tf)           # only this chart's own TF
            self.assertTrue(any(self.chart(p, f"bot-{tf}", "mz()") for tf in ("M1", "M5", "M15")))
            for cid in ("bot-M30", "bot-H1"):
                self.assertFalse(self.chart(p, cid, "mz()"), cid)                                     # nothing computed / not a zone TF
            p.screenshot(path=str(SHOTS / "01_bot_charts_zones.png"))
            # LIVE on / off from the main chart area
            p.check("[data-testid=mzbar-live]")
            self.assertTrue(wait_for(lambda: self.api(p, "/api/v1/market-zones?instrument=XAUUSD")["live"]["enabled"], 20, 0.3))
            p.uncheck("[data-testid=mzbar-live]")
            self.assertTrue(wait_for(lambda: not self.api(p, "/api/v1/market-zones?instrument=XAUUSD")["live"]["enabled"], 20, 0.3))
            # isolation from orders and trading settings
            self.assertTrue(posts)
            self.assertTrue(all(u.startswith("/api/v1/market-zones/") for u in posts), posts)
            self.assertEqual(self.api(p, "/api/v1/config"), cfg0)
            st1 = self.api(p, "/api/v1/state")
            self.assertEqual(st1.get("execution_mode"), st0.get("execution_mode"))
            self.assertEqual(len(st1.get("positions") or []), len(st0.get("positions") or []))
            self.assertEqual(errors, [])
        finally:
            p.close()

    def test_02_geometry_follows_zoom_pan_resize(self):
        p = self.ctx.new_page()
        try:
            self.open_bot(p)
            if not self.api(p, "/api/v1/market-zones?instrument=XAUUSD")["timeframes"]["M5"].get("computed"):
                p.click("[data-testid=mzbar-compute]")
                p.wait_for_selector("[data-testid=mzbar-job][data-status=DONE]", timeout=60000)
            self.assertTrue(wait_for(lambda: len(self.chart(p, "bot-M5", "mz()") or []) > 0, 30, 0.3))
            js = """() => { const c = window.__mqCharts['bot-M5']; const g = c.mzGeom();
              const ts = c.chart.timeScale(); return g.map((b) => ({ ...b, cx: ts.timeToCoordinate(b.from) })); }"""

            def check(stage):
                g = p.evaluate(js)
                vis = [b for b in g if b["x1"] is not None and b["y1"] is not None]
                self.assertTrue(vis, f"{stage}: no visible box")
                for b in vis:
                    self.assertAlmostEqual(b["x1"], b["cx"], delta=0.5, msg=stage)     # left edge = x of the origin candle
                    self.assertLess(b["y1"], b["y2"] + 0.01, stage)                    # high above low on screen
                return vis[0]
            p.evaluate("() => window.__mqCharts['bot-M5'].chart.timeScale().fitContent()")
            p.wait_for_timeout(300)
            a = check("fit")
            p.locator("[data-chart-id=bot-M5] [data-act=zoom-in]").click()
            p.wait_for_timeout(300)
            b = check("zoom")
            self.assertNotAlmostEqual(a["x1"], b["x1"], delta=0.5)                     # the box moved with the time scale
            p.evaluate("() => { const ts = window.__mqCharts['bot-M5'].chart.timeScale(); const r = ts.getVisibleLogicalRange();"
                       " ts.setVisibleLogicalRange({ from: r.from - 8, to: r.to - 8 }); }")
            p.wait_for_timeout(300)
            check("pan")
            p.set_viewport_size({"width": 1180, "height": 760})
            p.wait_for_timeout(600)
            check("resize")
            p.screenshot(path=str(SHOTS / "02_geometry_after_resize.png"))
        finally:
            p.close()

    def test_03_settings_persist_isolated_reset_templates(self):
        p = self.ctx.new_page()
        errors = []
        p.on("pageerror", lambda e: errors.append(str(e)))
        try:
            self.open_bot(p)
            p.locator("[data-chart-id=bot-M5] [data-act=settings]").click()
            p.wait_for_selector("[data-testid=chart-settings]")
            p.locator("[data-testid=cs-font]").fill("13")
            p.uncheck("[data-testid=cs-grid]")
            p.uncheck("[data-testid=cs-volume]")
            p.locator("[data-testid=cs-upColor]").evaluate("(el) => { const s = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;"
                                                           " s.call(el, '#123456'); el.dispatchEvent(new Event('input', { bubbles: true })); }")
            p.locator("[data-testid=cs-opacity-SR]").fill("40")
            p.screenshot(path=str(SHOTS / "03_settings_dialog.png"))
            p.locator("[data-testid=cs-tpl-name]").fill("Mój szablon")
            p.click("[data-testid=cs-tpl-save]")
            p.click("[data-testid=cs-close]")
            opts = self.chart(p, "bot-M5", "options()")
            self.assertEqual(opts["layout"]["fontSize"], 13)
            self.assertFalse(opts["grid"]["vertLines"]["visible"])
            # reload = restart of the window: the settings come back, other charts untouched
            p.reload()
            self.open_bot(p)
            pr = self.chart(p, "bot-M5", "prefs()")
            self.assertEqual((pr["fontSize"], pr["showGrid"], pr["showVolume"], pr["upColor"]), (13, False, False, "#123456"))
            self.assertAlmostEqual(pr["zones"]["SR"]["opacity"], 0.40, places=2)
            self.assertEqual(self.chart(p, "bot-M5", "options()")["layout"]["fontSize"], 13)
            other = self.chart(p, "bot-M15", "prefs()")
            self.assertEqual((other["fontSize"], other["showGrid"], other["upColor"]), (10, True, None))
            self.assertEqual(self.chart(p, "bot-M15", "options()")["layout"]["fontSize"], 10)
            # template applied to another chart
            p.locator("[data-chart-id=bot-M15] [data-act=settings]").click()
            p.select_option("[data-testid=cs-tpl-apply]", "Mój szablon")
            p.click("[data-testid=cs-close]")
            self.assertEqual(self.chart(p, "bot-M15", "prefs()")["fontSize"], 13)
            # reset of one chart only
            p.locator("[data-chart-id=bot-M5] [data-act=settings]").click()
            p.click("[data-testid=cs-reset]")
            p.click("[data-testid=cs-close]")
            pr = self.chart(p, "bot-M5", "prefs()")
            self.assertEqual((pr["fontSize"], pr["showGrid"], pr["upColor"]), (10, True, None))
            self.assertTrue(self.chart(p, "bot-M5", "options()")["grid"]["vertLines"]["visible"])
            self.assertEqual(self.chart(p, "bot-M15", "prefs()")["fontSize"], 13)
            # corrupted storage never breaks a chart
            p.evaluate("() => localStorage.setItem('mq.chartprefs.v1', '{broken')")
            p.reload()
            self.open_bot(p)
            self.assertEqual(self.chart(p, "bot-M15", "prefs()")["fontSize"], 10)
            self.assertEqual(errors, [])
        finally:
            p.close()

    def test_04_layer_menu_hides_types_and_labels(self):
        p = self.ctx.new_page()
        try:
            self.open_bot(p)
            if not self.api(p, "/api/v1/market-zones?instrument=XAUUSD")["timeframes"]["M1"].get("computed"):
                p.click("[data-testid=mzbar-compute]")
                p.wait_for_selector("[data-testid=mzbar-job][data-status=DONE]", timeout=60000)
            cid = next((c for c in ("bot-M1", "bot-M5", "bot-M15") if wait_for(lambda c=c: len(self.chart(p, c, "mz()") or []) > 1, 10, 0.3)), None)
            self.assertIsNotNone(cid, "no chart with zones")
            before = self.chart(p, cid, "mz()")
            types = {b["label"].split(" ", 1)[1] for b in before}
            menu = f"[data-chart-id={cid}] [data-testid=layers-btn]"
            p.click(menu)
            for layer in ("FVG", "OB", "SD", "SR", "LIQ"):
                p.locator(f"[data-chart-id={cid}] .layer-pop input[data-layer={layer}]").uncheck()
            self.assertTrue(wait_for(lambda: self.chart(p, cid, "mz()") == [], 5, 0.2), types)
            p.locator(f"[data-chart-id={cid}] .layer-pop input[data-layer=SR]").check()
            p.locator(f"[data-chart-id={cid}] .layer-pop input[data-layer=LABELS]").uncheck()
            after = self.chart(p, cid, "mz()")
            self.assertTrue(all(b.get("label") is None for b in after))
            sr = [b for b in before if "wsparci" in b["label"].lower() or "opór" in b["label"].lower() or "S/R" in b["label"]]
            self.assertEqual(len(after), len(sr), (types, len(after)))
            self.assertIn("(−5)", p.locator(menu).inner_text())                     # 4 layers + labels hidden
            p.locator(f"[data-chart-id={cid}] .layer-pop button.link").click()       # show all
            self.assertEqual(len(self.chart(p, cid, "mz()")), len(before))
            p.keyboard.press("Escape")
        finally:
            p.close()

    def test_05_no_data_stale_reconnect_foreign_symbol(self):
        p = self.ctx.new_page()
        mode = {"m": "nodata"}

        def handle(route):
            if mode["m"] == "down":
                return route.abort()
            r = route.fetch()
            v = r.json()
            if mode["m"] == "nodata":
                t = v["timeframes"]["M5"]
                t["status"] = {"status": "NO_DATA", "status_pl": "brak danych", "reason": "terminal nie zwrócił zamkniętych świec"}
                t["stale"] = True
            elif mode["m"] == "foreign":
                v["symbol"] = "XAUUSD.other"
            return route.fulfill(response=r, body=json.dumps(v), headers={**r.headers, "content-type": "application/json"})
        try:
            self.open_bot(p)
            if not self.api(p, "/api/v1/market-zones?instrument=XAUUSD")["timeframes"]["M5"].get("computed"):
                p.click("[data-testid=mzbar-compute]")
                p.wait_for_selector("[data-testid=mzbar-job][data-status=DONE]", timeout=60000)
            p.route("**/api/v1/market-zones?instrument=XAUUSD*", handle)
            p.reload()
            self.open_bot(p)
            p.wait_for_selector("[data-testid=mzbar-src-M5][data-status=NO_DATA]", timeout=20000)
            hint = p.locator("[data-chart-id=bot-M5] [data-testid=chart-mz-hint]")
            self.assertIn("ostatni udany wynik", hint.inner_text())
            drawn = self.chart(p, "bot-M5", "mz()")
            self.assertTrue(drawn and all(b["border"] == "#8a8a8a" and "nieakt." in b["label"] for b in drawn))   # stale: grey + marked
            p.screenshot(path=str(SHOTS / "05_no_data_stale.png"))
            # connection to the bot lost -> error shown, last view kept; back -> refreshed
            mode["m"] = "down"
            p.click("[data-testid=mzbar-compute]")                                   # POST passes, the refresh GET fails
            p.wait_for_selector("[data-testid=mzbar-err]", timeout=20000)
            mode["m"] = "ok"
            p.click("[data-testid=mzbar-compute]")
            self.assertTrue(wait_for(lambda: p.locator("[data-testid=mzbar-err]").count() == 0, 20, 0.3))
            self.assertTrue(wait_for(lambda: p.locator("[data-testid=mzbar-src-M5]").get_attribute("data-status") == "CONNECTED", 20, 0.3))
            # zones of another broker symbol are never drawn on this chart
            mode["m"] = "foreign"
            p.click("[data-testid=mzbar-compute]")
            p.wait_for_selector("[data-testid=mzbar-mismatch]", timeout=20000)
            self.assertTrue(wait_for(lambda: all(not self.chart(p, c, "mz()") for c in ("bot-M1", "bot-M5", "bot-M15")), 10, 0.3))
            p.unroute("**/api/v1/market-zones?instrument=XAUUSD*")
        finally:
            p.close()

    def test_06_zone_page_charts_have_own_settings(self):
        p = self.ctx.new_page()
        try:
            p.goto(f"http://127.0.0.1:{PORT}/#/strefy")
            p.wait_for_selector("[data-testid=page-strefy]", timeout=60000)
            p.click("[data-testid=mz-compute]")
            p.wait_for_selector("[data-testid=mz-job][data-status=DONE]", timeout=60000)
            self.assertTrue(wait_for(lambda: int(p.locator("[data-testid=mz-chart-M5]").get_attribute("data-drawn") or 0) > 0, 20, 0.2))
            n_m15 = p.locator("[data-testid=mz-chart-M15]").get_attribute("data-drawn")
            p.click("[data-testid=mz-layers-M5]")
            for layer in ("FVG", "OB", "SD", "SR", "LIQ"):
                p.locator(".mz-tf .layer-pop input[data-layer=%s]" % layer).uncheck()
            self.assertTrue(wait_for(lambda: p.locator("[data-testid=mz-chart-M5]").get_attribute("data-drawn") == "0", 5, 0.2))
            self.assertEqual(p.locator("[data-testid=mz-chart-M15]").get_attribute("data-drawn"), n_m15)            # other TF untouched
            p.keyboard.press("Escape")
            p.click("[data-testid=mz-settings-M15]")
            p.select_option("[data-testid=cs-tz]", "LOCAL")
            p.locator("[data-testid=cs-font]").fill("12")
            p.click("[data-testid=cs-close]")
            p.reload()
            p.wait_for_selector("[data-testid=page-strefy]", timeout=60000)
            self.assertTrue(wait_for(lambda: p.evaluate("() => window.__mqZoneCharts && window.__mqZoneCharts['XAUUSD-M15'] ? "
                                                        "window.__mqZoneCharts['XAUUSD-M15'].prefs().fontSize : null") == 12, 20, 0.3))
            self.assertEqual(p.locator("[data-testid=mz-chart-M5]").get_attribute("data-drawn"), "0")
            self.assertIn("lokalny", p.locator(".mz-tf", has=p.locator("[data-testid=mz-chart-M15]")).inner_text())
            p.screenshot(path=str(SHOTS / "06_zone_page_settings.png"), full_page=True)
        finally:
            p.close()


if __name__ == "__main__":
    unittest.main()
