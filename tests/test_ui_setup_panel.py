"""Page "Warunki setupu" (1.10) in the REAL monitor (Chromium + demo backend on the synthetic terminal): scenario list ->
details WITHOUT any change of the engine's strategy choice (no POST /api/v1/prefs/setup-view), summary "X z Y wymaganych",
grouped checklist with Polish statuses, viewed setup kept in the URL (refresh, Back/Forward), "Pokaż na wykresie", the
explicit engine choice (the only mutation), leverage limit (three values), persistence after a program restart, no order
created by any choice. Screenshots: data/logs/ui_setup_panel/.
Skipped (never "passed") without Playwright/Chromium."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import unittest
import urllib.request

import _env
from _env import TempData, wait_for

PORT = 8795
BASE = f"http://127.0.0.1:{PORT}"
CHROMIUM = os.environ.get("MQ_CHROMIUM", "/opt/pw-browsers/chromium")
SHOTS = _env.ROOT / "data" / "logs" / "ui_setup_panel"
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
class TestSetupPanelUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (_env.ROOT / "frontend" / "dist" / "index.html").exists():
            raise unittest.SkipTest("frontend not built")
        SHOTS.mkdir(parents=True, exist_ok=True)
        cls.td = TempData()
        with open(os.path.join(cls.td.dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"server": {"port": PORT, "open_browser": False}, "news": {"enabled": False}, "clock": {"reference_url": None},
                       "risk": {"risk_per_trade_pct": 1.0, "max_total_open_risk_pct": 3.0, "daily_loss_limit_pct": 5.0, "max_drawdown_pct": 10.0,
                                "max_open_positions": 3, "min_free_margin_buffer_pct": 20},
                       "costs": {"slippage_stress_points": 5, "commission_mode": "CONFIGURED", "commission_per_lot_per_side": 3.5},
                       "execution": {"mode": "SIGNALS"},     # analysis only: any order attempt would come from a UI choice
                       "first_run_completed": True}, f)
        cls.env = dict(os.environ, MASTERQUO_DATA_DIR=cls.td.dir, PYTHONPATH=str(_env.ROOT / "backend"))
        cls.env.pop("ANTHROPIC_API_KEY", None)
        cls.start_server()
        cls.pw = sync_playwright().start()
        kw = {"executable_path": CHROMIUM} if os.path.exists(CHROMIUM) else {}
        cls.browser = cls.pw.chromium.launch(**kw)
        cls.ctx = cls.browser.new_context(viewport={"width": 1700, "height": 1100})
        cls.page = cls.ctx.new_page()
        cls.errors = []
        cls.page.on("console", lambda m: cls.errors.append(m.text) if m.type == "error" else None)
        cls.posts = []
        cls.page.on("request", lambda r: cls.posts.append(r.url) if r.method == "POST" else None)
        cls.page.goto(BASE + "/#/warunki/bot")
        cls.page.wait_for_selector("[data-testid=page-warunki]", timeout=30000)

    @classmethod
    def start_server(cls):
        cls.proc = subprocess.Popen([sys.executable, "-m", "masterquo", "serve", "--demo", "--no-browser"], env=cls.env, cwd=str(_env.ROOT / "backend"),
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not wait_for(health, 60, 0.5):
            cls.proc.kill()
            raise RuntimeError("server did not start")

    @classmethod
    def stop_server(cls):
        subprocess.run([sys.executable, "-m", "masterquo", "stop"], env=cls.env, cwd=str(_env.ROOT / "backend"), timeout=60)
        try:
            cls.proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            cls.proc.kill()
        wait_for(lambda: not health(), 20, 0.5)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.browser.close()
            cls.pw.stop()
        finally:
            cls.stop_server()
            cls.td.close()

    def api(self, path):
        return self.page.request.get(BASE + path).json()

    def shot(self, name):
        self.page.screenshot(path=str(SHOTS / f"{name}.png"))

    def wait_scenarios(self):
        self.assertTrue(wait_for(lambda: len([i for i in self.api("/api/v1/setups")["items"] if i["status"] == "ACTIVE"]) > 0, 90, 1.0),
                        "no scenario from the synthetic terminal")

    def test_01_details_without_strategy_change(self):
        self.wait_scenarios()
        prefs0 = self.api("/api/v1/prefs")["setup_view"]
        auto0 = self.api("/api/v1/strategy/auto")
        self.page.wait_for_selector("[data-testid=setup-list] [data-testid=open-details]", timeout=30000)
        self.posts.clear()
        items = self.page.locator("[data-testid=setup-list] .setup-item")
        sids = [items.nth(i).get_attribute("data-setup") for i in range(min(items.count(), 3))]
        for sid in sids:                                                       # look at several setups, also non-selected ones
            self.page.locator(f".setup-item[data-setup='{sid}'] a").click()
            self.page.wait_for_selector(f"[data-testid=setup-summary][data-setup='{sid}']", timeout=20000)
            self.assertIn(f"#/warunki/{sid}", self.page.url.replace("%3A", ":"))
        # filters are presentation only as well
        self.page.locator("[data-testid=setup-list] select[aria-label=Kierunek]").select_option("BUY")
        self.page.locator("[data-testid=setup-list] select[aria-label=Kierunek]").select_option("")
        time.sleep(1)
        self.assertEqual([u for u in self.posts if "setup-view" in u or "strategy/mode" in u], [])       # NO engine mutation
        self.assertEqual(self.api("/api/v1/prefs")["setup_view"], prefs0)
        self.assertEqual(self.api("/api/v1/strategy/auto")["strategy_mode"], auto0["strategy_mode"])
        sid = sids[0]
        self.page.locator(f".setup-item[data-setup='{sid}'] a").click()
        self.page.wait_for_selector(f"[data-testid=setup-summary][data-setup='{sid}']", timeout=20000)
        cnt = self.page.inner_text("[data-testid=req-count]")
        self.assertRegex(cnt, r"Spełniono \d+ z \d+ warunków wymaganych")
        d = self.api(f"/api/v1/setups/{sid}/details")
        self.assertEqual(cnt, f"Spełniono {d['summary']['required_met']} z {d['summary']['required_total']} warunków wymaganych")
        self.assertTrue(all(r["required"] is False for r in d["checklist"] if r["state"] == "NA"))      # n/a never in the denominator
        cl = self.page.locator("[data-testid=condition-list]")
        txt = cl.inner_text()
        self.assertTrue(any(w in txt for w in ("Spełnione", "Niespełnione", "Oczekiwanie", "Brak danych")))
        groups = {cl.locator(".cond-group").nth(i).get_attribute("data-group") for i in range(cl.locator(".cond-group").count())}
        self.assertTrue({"1", "4", "9", "10"} <= groups, groups)               # data, trigger, permission, invalidation always present
        for part in ("Trigger i unieważnienie", "Plan wejścia", "Wymagane zamknięcie", "Dźwignia rachunku / limit bota"):
            self.assertIn(part, self.page.inner_text("[data-testid=page-warunki]"))
        cl.locator("[data-filter=nodata]").click()
        self.assertTrue(all(x == "NO_DATA" for x in cl.locator(".cond").evaluate_all("els => els.map(e => e.dataset.state)")))
        cl.locator("[data-filter=all]").click()
        self.shot("01_details")
        type(self).viewed = sid

    def test_02_refresh_back_forward_and_show_on_chart(self):
        sid = self.viewed
        self.page.reload()
        self.page.wait_for_selector(f"[data-testid=setup-summary][data-setup='{sid}']", timeout=30000)   # the viewed setup survives a refresh
        btn = self.page.locator("[data-testid=show-on-chart]").first
        if not btn.count():
            self.skipTest("setup without a price level to show")
        btn.click()
        self.page.wait_for_selector("[data-testid=page-bot]", timeout=20000)
        self.assertIn("#/wykresy?tf=", self.page.url)
        tf = self.page.evaluate("() => new URLSearchParams(location.hash.split('?')[1]).get('tf')")
        self.page.wait_for_function("(tf) => window.__mqCharts['bot-' + tf] && window.__mqCharts['bot-' + tf].highlight().length === 1", arg=tf, timeout=30000)
        self.assertEqual(self.page.locator("[data-testid=bot-grid] .chart-panel").count(), 1)          # focus view on that TF
        self.page.go_back()
        self.page.wait_for_selector(f"[data-testid=setup-summary][data-setup='{sid}']", timeout=20000)
        self.page.go_forward()
        self.page.wait_for_selector("[data-testid=page-bot]", timeout=20000)
        self.assertEqual([u for u in self.posts if "setup-view" in u or "agent/analyze" in u], [])

    def test_03_explicit_engine_choice_no_orders(self):
        self.page.goto(BASE + "/#/warunki/bot")
        self.page.wait_for_selector("[data-testid=page-warunki]")
        sec = self.page.locator("[data-testid=sec-engine-choice]")
        if sec.get_attribute("open") is None:
            sec.locator("summary").click()
        sec.locator("select").select_option("S03")
        sec.locator("[data-testid=engine-selected]").click()
        self.assertTrue(wait_for(lambda: self.api("/api/v1/prefs")["setup_view"]["mode"] == "SELECTED"
                                 and self.api("/api/v1/prefs")["setup_view"]["strategy_id"] == "S03", 10, 0.3))
        self.assertTrue(wait_for(lambda: self.api("/api/v1/strategy/auto")["manual_strategy_id"] == "S03", 20, 0.5))
        time.sleep(2)
        st = self.api("/api/v1/state")
        self.assertIn((st.get("auto") or {}).get("selected_strategy_id"), (None, "S03"))
        self.assertEqual(st.get("attempts") or [], [])                                          # no order attempt was created
        self.assertEqual(st["mode"]["mode"], "SIGNALS")
        self.shot("03_engine_S03")
        sec.locator("[data-testid=engine-auto]").click()
        self.assertTrue(wait_for(lambda: self.api("/api/v1/prefs")["setup_view"]["mode"] == "AUTO", 10, 0.3))

    def test_04_leverage_setting_three_values_and_effect(self):
        self.wait_scenarios()
        self.page.click("button[title='Ustawienia']")
        self.page.click("button:has-text('Ryzyko')")
        self.page.wait_for_selector("[data-testid=leverage-settings]")
        self.page.wait_for_function("() => document.querySelector('[data-testid=lev-account]')?.textContent === '1:100'", timeout=10000)
        self.page.check("[data-testid=leverage-settings] input[type=radio] >> nth=1")
        self.page.select_option("[data-testid=lev-select]", "10")
        self.page.click("[data-testid=lev-save]")
        self.page.wait_for_selector("[data-testid=lev-msg]:has-text('Zapisano')")
        self.assertEqual(self.page.inner_text("[data-testid=lev-user]"), "1:10")
        self.assertNotIn("1:200", self.page.inner_html("[data-testid=lev-select]"))
        self.page.locator("[data-testid=leverage-settings]").screenshot(path=str(SHOTS / "04_leverage_settings.png"))
        self.page.locator(".modal-head button.icon").first.click()
        p = self.api("/api/v1/prefs")
        self.assertEqual((p["exposure"]["account_leverage"], p["exposure"]["user_limit"], p["exposure"]["limit"]), (100, 10, 10))
        items = [i for i in self.api("/api/v1/setups")["items"] if i["status"] == "ACTIVE"]
        self.assertTrue(items)
        d = self.api(f"/api/v1/setups/{items[0]['setup_id']}/details")
        self.assertEqual(d["leverage"]["user_limit"], 10)
        if d["sizing"]["lots"]:
            self.assertLessEqual(d["leverage"]["effective_exposure_position"], 10.0 + 1e-9)

    def test_05_restart_keeps_choices(self):
        before = self.api("/api/v1/prefs")
        type(self).stop_server()
        type(self).start_server()
        self.page.goto(BASE + "/")
        self.page.wait_for_selector("[data-testid=page-warunki]", timeout=30000)                 # last page remembered
        after = self.api("/api/v1/prefs")
        self.assertEqual((after["setup_view"], after["leverage"]), (before["setup_view"], before["leverage"]))
        self.shot("05_after_restart")
        self.assertEqual([e for e in self.errors if "WebSocket" not in e and "favicon" not in e and "Failed to load resource" not in e], [])


if __name__ == "__main__":
    unittest.main()
