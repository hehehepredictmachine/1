"""Monitor UI in a real browser (Chromium via Playwright) on the synthetic demo backend (1.10: three pages, chart ids per page + TF).

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
        cls.page.goto(BASE + "/#/ai")
        cls.page.wait_for_function("() => window.__mqCharts && ['ai-M1','ai-M5','ai-M15','ai-H1'].every(k => window.__mqCharts[k] && window.__mqCharts[k].bars() > 50)",
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
        loc = self.page.locator(f"[data-chart-id='{cid}'] .chart-box")
        loc.scroll_into_view_if_needed()                   # 1.7.1: the signal card is above the charts
        box = loc.bounding_box()
        self.page.mouse.move(box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.4)
        for _ in range(times):
            self.page.mouse.wheel(0, dy)
            time.sleep(0.08)
        time.sleep(0.6)

    def width(self, r):
        return r["to"] - r["from"]

    # ------------------------------------------------------------ 1. independent zoom
    def test_01_wheel_zoom_changes_only_that_chart(self):
        before = {c: self.logical(c) for c in ("ai-M1", "ai-M5", "ai-M15", "ai-H1")}
        self.wheel("ai-M5", -300)
        after = {c: self.logical(c) for c in ("ai-M1", "ai-M5", "ai-M15", "ai-H1")}
        self.assertLess(self.width(after["ai-M5"]), self.width(before["ai-M5"]) * 0.9, (before["ai-M5"], after["ai-M5"]))
        for c in ("ai-M1", "ai-M15", "ai-H1"):
            self.assertAlmostEqual(self.width(after[c]), self.width(before[c]), delta=0.5, msg=c)
        # drag the zoomed chart to the left (manual view, no longer following)
        self.page.locator("[data-chart-id='ai-M5'] .chart-box").scroll_into_view_if_needed()
        box = self.page.locator("[data-chart-id='ai-M5'] .chart-box").bounding_box()
        self.page.mouse.move(box["x"] + box["width"] * 0.4, box["y"] + box["height"] * 0.4)
        self.page.mouse.down()
        self.page.mouse.move(box["x"] + box["width"] * 0.8, box["y"] + box["height"] * 0.4, steps=8)
        self.page.mouse.up()
        time.sleep(0.6)
        self.assertFalse(self.view("ai-M5")["follow"])
        self.assertAlmostEqual(self.width(self.logical("ai-M1")), self.width(before["ai-M1"]), delta=0.5)

    # ------------------------------------------------------------ 2. data refresh / ticks / reconnect-like reload keep the view
    def test_02_full_refresh_and_ticks_do_not_reset_view(self):
        if self.view("ai-M5")["follow"]:
            self.test_01_wheel_zoom_changes_only_that_chart()
        r0 = self.trange("ai-M5")
        w0 = self.width(self.logical("ai-M5"))
        creations = self.page.evaluate("() => window.__mqCharts['ai-M5'].creations")
        for _ in range(3):
            self.page.evaluate("() => window.__mqRefresh()")          # same path as reconnect/resync: reload of ALL charts
            time.sleep(1.2)
        time.sleep(3)                                                  # live ticks keep arriving meanwhile
        r1 = self.trange("ai-M5")
        self.assertEqual((r0["from"], r0["to"]), (r1["from"], r1["to"]))
        self.assertAlmostEqual(self.width(self.logical("ai-M5")), w0, delta=0.5)
        self.assertEqual(self.page.evaluate("() => window.__mqCharts['ai-M5'].creations"), creations)   # never re-created
        self.assertFalse(self.view("ai-M5")["follow"])

    # ------------------------------------------------------------ 3. buttons act on one panel only
    def test_03_buttons_per_panel(self):
        w1 = self.width(self.logical("ai-M1"))
        w3 = self.width(self.logical("ai-M15"))
        self.page.locator("[data-chart-id='ai-M15'] [data-act='zoom-in']").click()
        time.sleep(0.5)
        self.assertLess(self.width(self.logical("ai-M15")), w3)
        self.assertAlmostEqual(self.width(self.logical("ai-M1")), w1, delta=0.5)
        self.page.locator("[data-chart-id='ai-M15'] [data-act='zoom-out']").click()
        self.page.locator("[data-chart-id='ai-M15'] [data-act='latest']").click()
        time.sleep(0.5)
        self.assertTrue(self.view("ai-M15")["follow"])
        n = self.page.evaluate("() => window.__mqCharts['ai-M15'].bars()")
        self.assertGreaterEqual(self.logical("ai-M15")["to"], n - 1)
        self.page.locator("[data-chart-id='ai-M15'] [data-act='autoscale']").click()
        self.assertFalse(self.view("ai-M15")["autoScale"])
        self.page.locator("[data-chart-id='ai-M15'] [data-act='autoscale']").click()
        self.assertTrue(self.view("ai-M15")["autoScale"])

    # ------------------------------------------------------------ 4. theme change: charts updated in place, view kept
    def test_04_theme_change_keeps_view(self):
        if self.view("ai-M5")["follow"]:
            self.test_01_wheel_zoom_changes_only_that_chart()
        r0 = self.trange("ai-M5")
        creations = self.page.evaluate("() => window.__mqCharts['ai-M5'].creations")
        bg0 = self.page.evaluate("() => getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()")
        self.page.locator("button[title^='Wygląd']").click()
        dlg = self.page.locator(".theme-dialog")
        dlg.locator("select").first.select_option("light")
        time.sleep(0.4)
        dlg.get_by_role("button", name="Zastosuj").click()
        time.sleep(0.8)
        bg1 = self.page.evaluate("() => getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()")
        self.assertNotEqual(bg0, bg1)
        self.assertEqual(self.page.evaluate("() => window.__mqCharts['ai-M5'].creations"), creations)
        r1 = self.trange("ai-M5")
        self.assertEqual((r0["from"], r0["to"]), (r1["from"], r1["to"]))
        stored = self.page.evaluate("() => JSON.parse(localStorage.getItem('mq.theme.v1'))")
        self.assertEqual((stored["version"], stored["preset"]), (1, "light"))

    # ------------------------------------------------------------ 5. resize keeps the manual view
    def test_05_resize_keeps_manual_view(self):
        if self.view("ai-M5")["follow"]:
            self.test_01_wheel_zoom_changes_only_that_chart()
        v0 = self.view("ai-M5")
        self.page.set_viewport_size({"width": 1400, "height": 900})
        time.sleep(1.0)
        self.page.set_viewport_size({"width": 1700, "height": 1000})
        time.sleep(1.0)
        v1 = self.view("ai-M5")
        self.assertEqual((v0["from"], v0["to"], v0["follow"]), (v1["from"], v1["to"], v1["follow"]))   # saved state untouched

    # ------------------------------------------------------------ 6. persistence after reload (refresh / restart of the page)
    def test_06_view_and_theme_persist_after_reload(self):
        if self.view("ai-M5")["follow"]:
            self.test_01_wheel_zoom_changes_only_that_chart()
        time.sleep(0.6)
        v0 = self.view("ai-M5")
        self.page.reload()
        self.page.wait_for_function("() => window.__mqCharts && window.__mqCharts['ai-M5'] && window.__mqCharts['ai-M5'].bars() > 50", timeout=60000)
        time.sleep(1.5)
        v1 = self.view("ai-M5")
        self.assertFalse(v1["follow"])
        r = self.trange("ai-M5")
        self.assertLessEqual(abs(r["from"] - v0["from"]), 120)          # within ~one M5 bar of the saved range
        self.assertTrue(self.view("ai-M1")["follow"])                  # other panels keep their own (default) state
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

    # ------------------------------------------------------------ helpers for the 1.10 pages
    def go(self, h):
        self.page.goto(BASE + "/" + h)
        self.page.wait_for_selector("[data-page]", timeout=30000)

    def open_section(self, testid):
        sec = self.page.locator(f"[data-testid={testid}]")
        if sec.get_attribute("open") is None:
            sec.locator("summary").click()
        return sec

    # ------------------------------------------------------------ 8. checklist (page 3) and ML panel
    def test_08_checklist_and_ml_panel(self):
        self.go("#/warunki/bot")
        self.open_section("sec-engine-plan")
        panel = self.page.locator("[data-testid='entry-checklist']")
        panel.wait_for(timeout=30000)
        txt = panel.inner_text()
        for word in ("BUY", "SELL", "LONG", "SHORT"):
            self.assertNotIn(word, txt.upper().replace("LONGER", ""), word)
        self.assertTrue(any(k in txt for k in ("Spełnione", "Brak aktualnego scenariusza")))
        self.open_section("sec-ml")
        ml = self.page.locator("[data-testid='ml-panel']")
        ml.wait_for(timeout=30000)
        mt = ml.inner_text()
        self.assertTrue(any(s in mt for s in ("COLLECTING", "WAITING_FOR_LABELS", "SHADOW", "ACTIVE")), mt[:300])
        for b in ("Zbieraj dane", "Trenuj teraz", "Wstrzymaj trening", "Historia modeli", "Przywróć poprzedni model"):
            self.assertIn(b, mt)
        ml.get_by_role("button", name="Trenuj teraz").click()
        self.page.wait_for_function("() => document.querySelector(\"[data-testid='ml-panel']\").innerText.includes('ETYKIET')", timeout=15000)
        self.go("#/ai")

    def test_09_volatility_levels_and_walls_named_by_source(self):
        p = self.page
        v = json.loads(p.evaluate("() => fetch('/api/v1/volatility').then(r => r.text())"))
        self.assertEqual(v["status"], "OK", v)
        self.assertEqual(len(v["walls"]), 4)
        self.go("#/wykresy")
        p.locator("[data-view=all]").click()
        self.open_section("sec-vol")
        p.wait_for_selector("[data-testid=vol-panel] .vol-walls tbody tr", timeout=30000)
        self.assertEqual(p.locator("[data-testid=vol-panel] .vol-walls tbody tr").count(), 4)
        src = "IV" if v.get("source_type") == "IV_MANUAL" else "HV-proxy"
        self.assertIn(f"Daily High ({src} 1σ)", p.locator("[data-testid=vol-panel]").inner_text())
        p.wait_for_function("() => window.__mqCharts['bot-M1'] && window.__mqCharts['bot-M1'].volLines().includes('Daily Open')", timeout=30000)
        titles = p.evaluate("() => window.__mqCharts['bot-M1'].volLines()")
        for t in ("Daily Open", f"Daily High ({src} 1σ)", f"Daily Low ({src} 1σ)", "PDH", "PDL"):
            self.assertIn(t, titles)
        self.assertFalse(any("IV 1σ" in t for t in titles) and src != "IV", titles)   # HV never presented as implied volatility
        before = p.evaluate("() => window.__mqCharts['bot-M1'].logical()")
        box = p.locator(".chart-toolbar label", has_text="Walls dzienne / Daily").locator("input")
        box.uncheck()
        p.wait_for_function("() => window.__mqCharts['bot-M1'].volLines().length === 0", timeout=10000)
        after = p.evaluate("() => window.__mqCharts['bot-M1'].logical()")
        self.assertAlmostEqual(before["from"], after["from"], delta=1.5)      # toggling levels never moves the view
        box.check()
        p.wait_for_function("() => window.__mqCharts['bot-M1'].volLines().length > 5", timeout=10000)
        self.go("#/ai")

    def test_10_markets_scanner_and_detail_chart(self):
        """1.14: the scanner covers ONLY the two allowed assets (XAUUSD + the confirmed BTC symbol); other terminal symbols are
        rejected by the backend (403), never scanned or charted."""
        p = self.page
        st, _ = p.evaluate("""async () => { const s = await (await fetch('/api/v1/session')).json();
            const r = await fetch('/api/v1/assets/confirm', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-MQ-CSRF': s.csrf},
              body: JSON.stringify({asset: 'BTC', broker_symbol: 'BTCUSD-'})}); return [r.status, null]; }""")
        self.assertEqual(st, 200)
        self.go("#/wykresy")
        self.open_section("sec-markets")
        p.wait_for_selector("[data-testid=markets-panel] tr[data-symbol='BTCUSD-']", timeout=90000)
        rows = p.locator("[data-testid=markets-panel] tbody tr[data-symbol]")
        names = {rows.nth(i).get_attribute("data-symbol") for i in range(rows.count())}
        self.assertTrue(names <= {"XAUUSD-", "BTCUSD-"}, names)
        self.assertEqual(p.request.get(BASE + "/api/v1/markets/detail?symbol=EURUSD-").status, 403)
        sym0 = json.loads(p.evaluate("() => fetch('/api/v1/state').then(r => r.text())"))["symbol"]["symbol"]
        p.locator("[data-testid=markets-panel] tr[data-symbol='BTCUSD-']").click()
        p.wait_for_selector("[data-testid=market-detail]", timeout=10000)
        p.wait_for_function("() => window.__mqMarketChart && window.__mqMarketChart.bars() > 100", timeout=20000)
        self.assertEqual(p.locator("[data-act=detail-ai]").count(), 0)
        p.keyboard.press("Escape")
        if p.locator("[data-testid=market-detail]").count():
            p.locator(".modal-head button.icon").first.click()
        sym1 = json.loads(p.evaluate("() => fetch('/api/v1/state').then(r => r.text())"))["symbol"]["symbol"]
        self.assertEqual(sym0, sym1)                                   # browsing the other asset never changes the engine's symbol
        state = json.loads(p.evaluate("() => fetch('/api/v1/bot-signals').then(r => r.text())"))
        self.assertTrue(all(x["source"] == "BOT" and x["strategy_id"] and x["symbol"] in ("XAUUSD-", "BTCUSD-") for x in state["items"]))
        self.go("#/ai")

    def test_11_signal_plan_context_all_timeframes_and_history(self):
        p = self.page
        self.go("#/warunki/bot")
        self.open_section("sec-engine-plan")
        p.wait_for_selector("[data-testid=signal-plan]", timeout=30000)
        p.wait_for_selector("[data-testid=context-tf] .ctx-card[data-tf=H8]", timeout=30000)
        h8 = p.locator(".ctx-card[data-tf=H8]").inner_text()
        self.assertTrue("natywne MT5" in h8 or "BRAK_DANYCH" in h8, h8)
        st = json.loads(p.evaluate("() => fetch('/api/v1/context-tf').then(r => r.text())"))
        self.assertIn("M30", st["context"])
        self.assertIn("H8", st["context"])
        sig = st["signal"]
        if sig:
            self.assertIn(sig["status"], ("OCZEKIWANIE", "POTWIERDZONY", "ZABLOKOWANY", "UNIEWAŻNIONY", "WYGASŁY", "BRAK_DANYCH"))
            self.assertEqual(sig["ai"]["status"], "AI_NIEDOSTEPNE")                    # no API key in tests: never a fake AI verdict
            self.assertIsNone(sig["probability_win"])
            self.assertIsNone(sig["fill_price"])
        # positions / signal history: global side panel, available from every page
        p.locator("[data-testid=open-side]").click()
        p.wait_for_selector("[data-testid=sidepanel]", timeout=5000)
        p.locator("[data-testid=sidepanel] button", has_text="Pozycje i zlecenia").click()
        p.locator("[data-testid=sidepanel] button", has_text="Historia sygnałów").first.click()
        p.wait_for_selector("[data-testid=signal-history]", timeout=10000)
        p.keyboard.press("Escape")
        p.wait_for_selector("[data-testid=sidepanel]", state="detached", timeout=5000)
        # page 2: every TF of the backend registry (8 in this release), M30 and H8 charts load real bars
        self.go("#/wykresy")
        p.locator("[data-view=all]").click()
        reg = json.loads(p.evaluate("() => fetch('/api/v1/timeframes').then(r => r.text())"))
        tfs = [t["tf"] for t in reg["timeframes"]]
        self.assertGreaterEqual(len(tfs), 8)
        p.wait_for_function("(tfs) => tfs.every(tf => window.__mqCharts['bot-' + tf] && window.__mqCharts['bot-' + tf].bars() > 20)", arg=tfs, timeout=90000)
        self.assertEqual(p.locator("[data-testid=tf-bar] .tf-chip").count(), len(tfs))
        self.go("#/ai")
        p.wait_for_function("() => ['ai-M1','ai-M5','ai-M15','ai-H1'].every(k => window.__mqCharts[k] && window.__mqCharts[k].bars() > 50)", timeout=60000)


if __name__ == "__main__":
    unittest.main()
