"""1.10 three-page monitor in a real browser (Chromium + demo backend on the SYNTHETIC terminal - clearly marked data):
navigation (side menu / mobile buttons), Back/Forward, direct link, refresh, last page remembered, ONE WebSocket after
many page switches, no automatic (paid) AI request, AI card states without a key / expired / other setup, AI vs engine
permission kept separate, five AI timeframes with a main slot (no sixth chart, zoom kept), "Siatka 5 wykresów", page 2
built from the backend TF registry, focus view, fullscreen + Escape, theme kept across pages, corrupted localStorage ->
safe defaults, no horizontal page scroll at 1920x1080 / 1366x768 / 1024 / 390 px. Screenshots: data/logs/ui_pages/.
Skipped (never "passed") without Playwright/Chromium."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import unittest
import urllib.request
from datetime import datetime, timedelta, timezone

import _env
from _env import TempData, wait_for

PORT = 8794
BASE = f"http://127.0.0.1:{PORT}"
CHROMIUM = os.environ.get("MQ_CHROMIUM", "/opt/pw-browsers/chromium")
SHOTS = _env.ROOT / "data" / "logs" / "ui_pages"
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


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def agent_result(setup_id, *, expires_in_s=3600, action="BUY"):
    """A successful agent result in the backend contract (agent/schema.py record) - used to check the card states only."""
    now = datetime.now(timezone.utc)
    scen = lambda t: {"summary": t, "activation": [f"{t}: zamknięcie M5 powyżej 2405"], "invalidation": ["zamknięcie M5 poniżej 2390"]}
    rec = {"snapshot_id": "SNAP-UI", "setup_id": setup_id, "analysis_direction": "LONG", "signal_stage": "EARLY", "proposed_action": action,
           "strategy_id": "S01", "strategy_version": "1", "entry_zone": {"low": 2400.0, "high": 2402.5}, "invalidation_level": 2390.0,
           "proposed_targets": [2420.0, 2430.0], "scenarios": {"bullish": scen("wzrost"), "bearish": scen("spadek"), "wait": scen("czekaj")},
           "evidence_refs": ["M5:EMA20", "H1:BOS"], "contradictions": ["H4 w trendzie spadkowym"], "missing_data": ["kalendarz makro częściowy"],
           "reason_codes": ["PULLBACK_EMA"], "explanation_pl": "Pierwsze zdanie wyjaśnienia. " + "Długi opis kontekstu. " * 40,
           "answer_pl": None, "lessons": [], "playbook_proposals": [], "preferred_strategy_id": None, "scenario_still_valid": True,
           "decision_id": "MQD-UI-AI", "as_of_utc": iso(now), "expires_at_utc": iso(now + timedelta(seconds=expires_in_s)),
           "model_id": "test", "prompt_version": "test"}
    return {"run_id": f"AGR-UI-{expires_in_s}-{setup_id}", "status": "OK", "setup_id": setup_id, "record": rec, "finished_at": iso(now)}


@unittest.skipUnless(HAVE_PW, "playwright not installed")
class TestThreePagesUI(unittest.TestCase):
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
        cls.ctx = cls.browser.new_context(viewport={"width": 1920, "height": 1080})
        cls.page = cls.ctx.new_page()
        cls.errors, cls.sockets, cls.posts = [], [], []
        cls.page.on("console", lambda m: cls.errors.append(m.text) if m.type == "error" else None)
        cls.page.on("pageerror", lambda e: cls.errors.append(str(e)))
        cls.page.on("websocket", lambda ws: cls.sockets.append(ws.url))
        cls.page.on("request", lambda r: cls.posts.append(r.url) if r.method == "POST" else None)
        cls.inject = None                                  # agent result pushed into the live stream (card-state checks)
        cls.routes = []

        def on_ws(ws):
            server = ws.connect_to_server()
            cls.routes.append(ws)
            server.on_message(lambda msg: ws.send(msg))
        cls.page.route_web_socket(re.compile(r".*/api/v1/ws$"), on_ws)
        cls.page.goto(BASE + "/")
        cls.page.wait_for_selector("[data-testid=page-pulpit]", timeout=30000)     # 1.13: first start = Pulpit
        cls.first_url = cls.page.url
        cls.page.goto(BASE + "/#/ai")
        cls.page.wait_for_selector("[data-testid=page-ai]", timeout=30000)

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

    def api(self, path):
        return self.page.request.get(BASE + path).json()

    SECTION = {"wykresy": "wykresy", "warunki": "setupy", "ai": "setupy", "pulpit": "pulpit"}

    def nav(self, page_id):
        """1.14 menu: section in the side menu, then the sub-page tab."""
        self.page.locator(f"[data-testid=sidenav] [data-section={self.SECTION[page_id]}]").click()
        self.page.locator(f"main [data-testid=subtabs] [data-page={page_id}]").click()
        self.page.wait_for_selector(f"main.page[data-page={page_id}]", timeout=20000)

    def charts(self):
        return self.page.evaluate("() => Object.keys(window.__mqCharts || {}).sort()")

    def no_hscroll(self):
        return self.page.evaluate("() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")

    # ------------------------------------------------------------ 1. default page, nav, Back/Forward, direct link, refresh
    def test_01_navigation_history_direct_link_refresh(self):
        p = self.page
        self.assertTrue(self.first_url.endswith("#/pulpit"), self.first_url)                   # first start: "Pulpit" (1.13)
        self.assertEqual(p.locator("[data-testid=sidenav] [aria-current=page]").get_attribute("data-page"), "ai")
        p.evaluate("location.hash = '#/wykresy'")          # 1.14: section + sub-tab clicks add their own history entries; Back/Forward
        p.wait_for_selector("[data-testid=page-bot]")      # is checked on plain page-to-page navigation
        p.evaluate("location.hash = '#/warunki'")
        p.wait_for_selector("[data-testid=page-warunki]")
        p.go_back()
        p.wait_for_selector("[data-testid=page-bot]", timeout=10000)
        p.go_back()
        p.wait_for_selector("[data-testid=page-ai]", timeout=10000)
        p.go_forward()
        p.wait_for_selector("[data-testid=page-bot]", timeout=10000)
        p.goto(BASE + "/#/warunki/bot")                                                          # direct link
        p.wait_for_selector("[data-testid=page-warunki]", timeout=20000)
        p.reload()                                                                                # refresh: no 404, same page
        p.wait_for_selector("[data-testid=page-warunki]", timeout=20000)
        r = p.request.get(BASE + "/api/v1/health")
        self.assertEqual(r.status, 200)                                                          # API routes untouched
        p.goto(BASE + "/")                                                                       # last page remembered
        p.wait_for_selector("[data-testid=page-warunki]", timeout=20000)
        p.goto(BASE + "/#/ai")
        p.wait_for_selector("[data-testid=page-ai]")

    # ------------------------------------------------------------ 2. one WebSocket, no paid AI request, no engine mutation
    def test_02_many_switches_one_socket_no_side_effects(self):
        p = self.page
        p.goto(BASE + "/#/ai")
        p.wait_for_selector("[data-testid=page-ai]")
        time.sleep(1)
        n0 = len(self.routes)
        self.posts.clear()
        prefs0 = self.api("/api/v1/prefs")["setup_view"]
        mode0 = self.api("/api/v1/state")["mode"]["mode"]
        for _ in range(4):
            for pid in ("wykresy", "warunki", "ai"):
                self.nav(pid)
                time.sleep(0.4)
        self.nav("wykresy")
        p.locator("[data-testid=tf-bar] .tf-chip[data-tf=H1]").click()                           # clicking a TF: presentation only
        time.sleep(1)
        self.assertEqual(len(self.routes), n0)                                                   # page switches never open another socket
        self.assertEqual([u for u in self.posts if "/agent/" in u or "setup-view" in u or "strategy/mode" in u or "/mode" in u], [])
        self.assertEqual(self.api("/api/v1/prefs")["setup_view"], prefs0)
        self.assertEqual(self.api("/api/v1/state")["mode"]["mode"], mode0)
        self.assertEqual(self.api("/api/v1/state").get("attempts") or [], [])

    # ------------------------------------------------------------ 3. page 1: AI card states and the five charts
    def test_03_ai_card_states(self):
        p = self.page
        p.goto(BASE + "/#/ai")
        p.wait_for_selector("[data-testid=ai-card]")
        self.assertEqual(p.get_attribute("[data-testid=ai-card]", "data-ai-state"), "NO_KEY")    # no key in tests: own state, no fake verdict
        self.assertIn("brak klucza", p.inner_text("[data-testid=ai-state]"))
        self.assertTrue(p.locator("[data-testid=engine-gate]").is_visible())                     # engine permission shown separately
        p.screenshot(path=str(SHOTS / "ai_no_key_1920.png"))
        engine_setup = (self.api("/api/v1/state").get("decision") or {}).get("signal_view", {}).get("setup_id")
        # a current answer for the engine's setup
        self.routes[-1].send(json.dumps({"type": "agent_result", "data": agent_result(engine_setup)}))
        p.wait_for_function("() => document.querySelector('[data-testid=ai-card]').dataset.aiState === 'CURRENT'", timeout=10000)
        self.assertEqual(p.inner_text("[data-testid=ai-action]"), "KUPNO")
        self.assertIn("Pierwsze zdanie wyjaśnienia.", p.inner_text("[data-testid=ai-short]"))
        full = p.locator("[data-testid=ai-explanation]")
        self.assertIn("H4 w trendzie spadkowym", full.inner_text())                              # contradictions visible, not in a tooltip
        self.assertIn("kalendarz makro częściowy", full.inner_text())
        full.get_by_role("button", name="Pełny opis").click()
        self.assertNotIn("clamped", p.get_attribute("[data-testid=ai-full-text]", "class"))
        p.wait_for_function("() => (window.__mqCharts['ai-M5']?.aiLines() || []).some(t => t.startsWith('AI:'))", timeout=15000)
        href = p.get_attribute("[data-testid=ai-setup-link]", "href")
        self.assertTrue(href.startswith("#/warunki/"), href)
        p.screenshot(path=str(SHOTS / "ai_current_1920.png"))
        # an answer about ANOTHER setup is history, never a current signal
        self.routes[-1].send(json.dumps({"type": "agent_result", "data": agent_result("S99-OTHER")}))
        p.wait_for_function("() => document.querySelector('[data-testid=ai-card]').dataset.aiState === 'OTHER_SETUP'", timeout=10000)
        self.assertIn("HISTORIA", p.inner_text("[data-testid=ai-card]"))
        p.wait_for_function("() => (window.__mqCharts['ai-M5']?.aiLines() || []).length === 0", timeout=10000)   # no AI levels for history
        # expired answer
        self.routes[-1].send(json.dumps({"type": "agent_result", "data": agent_result(engine_setup, expires_in_s=-60)}))
        p.wait_for_function("() => document.querySelector('[data-testid=ai-card]').dataset.aiState === 'EXPIRED'", timeout=10000)
        self.assertIn("WYGASŁA", p.inner_text("[data-testid=ai-state]"))
        # a failed later run: the last good answer is labelled as history
        self.routes[-1].send(json.dumps({"type": "agent_result", "data": {"run_id": "AGR-UI-ERR", "status": "ERROR", "error": "TIMEOUT", "finished_at": iso(datetime.now(timezone.utc))}}))
        p.wait_for_function("() => document.querySelector('[data-testid=ai-card]').dataset.aiState === 'ERROR_LAST_RUN'", timeout=10000)
        self.assertIn("TIMEOUT", p.inner_text("[data-testid=ai-last-error]"))

    def test_04_five_charts_main_slot_grid_and_fullscreen(self):
        p = self.page
        p.goto(BASE + "/#/ai")
        p.wait_for_function("() => ['H1','M30','M15','M5','M1'].every(tf => window.__mqCharts['ai-' + tf] && window.__mqCharts['ai-' + tf].bars() > 30)", timeout=90000)
        self.assertEqual([c for c in self.charts() if c.startswith("ai-")], sorted(f"ai-{t}" for t in ("H1", "M30", "M15", "M5", "M1")))
        order = p.locator("[data-testid=page-ai] .chart-panel").evaluate_all("els => els.map(e => e.dataset.tf)")
        self.assertEqual(order, ["H1", "M30", "M15", "M5", "M1"])
        main = p.locator(".ai-slot[data-slot=main] .chart-panel")
        self.assertEqual(main.get_attribute("data-tf"), p.evaluate("() => JSON.parse(localStorage.getItem('mq.ai.main') || '\"M5\"')"))
        self.assertGreaterEqual(main.bounding_box()["height"], 420)
        for i in range(p.locator(".ai-slot .chart-panel").count()):
            self.assertGreaterEqual(p.locator(".ai-slot .chart-panel").nth(i).bounding_box()["height"], 300)
        # zoom H1, move it to the main slot: same chart instance (no 6th chart), zoom kept
        p.locator("[data-chart-id=ai-H1] [data-act=zoom-in]").click()
        time.sleep(0.5)
        spacing = lambda: p.evaluate("""() => { const r = window.__mqCharts['ai-H1'].logical();
            return document.querySelector('[data-chart-id=ai-H1] .chart-box').getBoundingClientRect().width / (r.to - r.from); }""")
        s0 = spacing()                                                                           # zoom = pixels per bar
        c0 = p.evaluate("() => window.__mqCharts['ai-H1'].creations")
        p.locator("[data-chart-id=ai-H1] [data-act=main]").click()
        p.wait_for_selector(".ai-slot[data-slot=main] [data-chart-id=ai-H1]", timeout=5000)
        time.sleep(0.8)
        self.assertEqual(p.locator("[data-testid=page-ai] .chart-panel").count(), 5)
        self.assertEqual(p.evaluate("() => window.__mqCharts['ai-H1'].creations"), c0)            # moved, not re-created
        self.assertLess(abs(spacing() - s0), 0.25 * s0)                                           # zoom kept: same bar spacing on the larger canvas
        p.locator("[data-testid=ai-grid5]").click()
        time.sleep(0.6)
        self.assertEqual(p.locator(".ai-slot[data-slot=main]").count(), 0)
        self.assertEqual(p.locator("[data-testid=page-ai] .chart-panel").count(), 5)
        p.screenshot(path=str(SHOTS / "ai_grid5_1920.png"), full_page=True)
        p.locator("button", has_text="Wykres główny + 4").click()
        p.locator("[data-chart-id=ai-M5] [data-act=main]").click()
        # fullscreen + Escape
        p.locator("[data-chart-id=ai-M15] [data-act=fullscreen]").click()
        p.wait_for_selector("[data-chart-id=ai-M15].fullscreen", timeout=3000)
        p.keyboard.press("Escape")
        p.wait_for_selector("[data-chart-id=ai-M15].fullscreen", state="detached", timeout=3000)

    # ------------------------------------------------------------ 5. page 2 from the TF registry, views, focus
    def test_05_bot_charts_registry_views_focus(self):
        p = self.page
        p.goto(BASE + "/#/wykresy")
        p.wait_for_selector("[data-testid=tf-bar] .tf-chip", timeout=20000)
        reg = self.api("/api/v1/timeframes")
        tfs = [t["tf"] for t in reg["timeframes"]]
        self.assertTrue({"M1", "M5", "M15", "M30", "H1", "H4", "H8", "D1"} <= set(tfs))
        chips = p.locator("[data-testid=tf-bar] .tf-chip").evaluate_all("els => els.map(e => e.dataset.tf)")
        self.assertEqual(sorted(chips), sorted(tfs))
        self.assertEqual(chips[0], "D1")
        self.assertEqual(chips[-1], "M1")
        p.locator("[data-view=all]").click()
        p.wait_for_function("(n) => document.querySelectorAll('[data-testid=bot-grid] .chart-panel').length === n", arg=len(tfs), timeout=10000)
        p.locator("[data-view=context]").click()
        ctx = p.locator("[data-testid=bot-grid] .chart-panel").evaluate_all("els => els.map(e => e.dataset.tf)")
        self.assertTrue(set(ctx) <= {"D1", "H8", "H4", "H1"} and ctx, ctx)
        p.locator("[data-view=setup]").click()
        st = p.locator("[data-testid=bot-grid] .chart-panel").evaluate_all("els => els.map(e => e.dataset.tf)")
        self.assertTrue(set(st) <= {"M30", "M15", "M5", "M1"} and st, st)
        p.locator("[data-cols='1']").click()
        p.locator("[data-cols='2']").click()
        p.locator("[data-testid=tf-bar] .tf-chip[data-tf=H8]").click()
        p.wait_for_selector("[data-testid=focus-list]")
        self.assertEqual(p.locator("[data-testid=bot-grid] .chart-panel").evaluate_all("els => els.map(e => e.dataset.tf)"), ["H8"])
        p.wait_for_function("() => window.__mqCharts['bot-H8'] && window.__mqCharts['bot-H8'].bars() > 20", timeout=60000)
        self.assertGreaterEqual(p.locator("[data-chart-id=bot-H8]").bounding_box()["height"], 420)
        self.assertIn("wymagan", p.inner_text("[data-testid=need-note]"))                         # TFs needed by the selected strategy
        p.screenshot(path=str(SHOTS / "bot_focus_1920.png"))
        p.locator("[data-view=all]").click()

    # ------------------------------------------------------------ 6. theme kept across pages; corrupted storage -> defaults
    def test_06_theme_across_pages_and_corrupted_storage(self):
        p = self.page
        p.goto(BASE + "/#/ai")
        p.locator("button[title^='Wygląd']").click()
        dlg = p.locator(".theme-dialog")
        dlg.locator("select").first.select_option("light")
        dlg.get_by_role("button", name="Zastosuj").click()
        time.sleep(0.5)
        bg = p.evaluate("() => getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()")
        self.nav("warunki")
        self.assertEqual(p.evaluate("() => getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()"), bg)
        p.screenshot(path=str(SHOTS / "warunki_light_1920.png"))
        p.evaluate("""() => { localStorage.setItem('mq.chartview.v1', '{broken'); localStorage.setItem('mq.ai.layout', '"x"');
                              localStorage.setItem('mq.bot.cols', '{'); localStorage.setItem('mq.chartopts.ai', 'null'); }""")
        p.goto(BASE + "/#/ai")
        p.wait_for_function("() => window.__mqCharts['ai-M5'] && window.__mqCharts['ai-M5'].bars() > 30", timeout=60000)
        self.assertEqual(p.locator(".ai-grid").get_attribute("class").split()[-1], "lay-main")   # invalid layout -> default
        p.goto(BASE + "/#/wykresy")
        p.wait_for_selector("[data-testid=bot-grid]")
        self.assertIn("cols-2", p.get_attribute("[data-testid=bot-grid]", "class") or "cols-2")

    # ------------------------------------------------------------ 7. side panel (positions/stats) and logs: one at a time
    def test_07_side_panel_and_logs(self):
        p = self.page
        p.goto(BASE + "/#/wykresy")
        p.locator("[data-testid=open-side]").click()
        p.wait_for_selector("[data-testid=sidepanel]")
        p.locator("[data-testid=sidepanel] [role=tab]", has_text="Statystyki").click()
        p.locator("[data-testid=open-logs]").click()
        self.assertEqual(p.locator("[data-testid=sidepanel]").count(), 1)
        p.wait_for_selector("[data-testid=logs-panel]")
        p.keyboard.press("Escape")
        p.wait_for_selector("[data-testid=sidepanel]", state="detached", timeout=3000)

    # ------------------------------------------------------------ 8. resolutions: no horizontal page scroll, readable text
    def test_08_resolutions(self):
        p = self.page
        for w, h in ((1920, 1080), (1366, 768), (1024, 768), (390, 844)):
            p.set_viewport_size({"width": w, "height": h})
            for route, sel in (("#/ai", "page-ai"), ("#/wykresy", "page-bot"), ("#/warunki/bot", "page-warunki")):
                p.goto(BASE + "/" + route)
                p.wait_for_selector(f"[data-testid={sel}]", timeout=20000)
                time.sleep(1.2)
                self.assertTrue(self.no_hscroll(), f"{w}px {route}: horizontal scroll")
                fs = p.evaluate("() => parseFloat(getComputedStyle(document.querySelector('.shell')).fontSize)")
                self.assertGreaterEqual(fs, 14)
                p.screenshot(path=str(SHOTS / f"{route.strip('#/').split('/')[0]}_{w}.png"))
            nav = "[data-testid=mobnav]" if w <= 760 else "[data-testid=sidenav]"
            self.assertTrue(p.locator(nav).is_visible(), f"{w}: navigation not visible")
        p.set_viewport_size({"width": 1920, "height": 1080})
        self.assertEqual([e for e in self.errors if "WebSocket" not in e and "favicon" not in e and "Failed to load resource" not in e], [])


if __name__ == "__main__":
    unittest.main()
