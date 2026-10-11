"""1.8 in the REAL monitor (Chromium + demo backend on the synthetic terminal): setup selector AUTO / WYBRANY SETUP /
WSZYSTKIE, scenario list -> details, persistence after refresh AND after a program restart, leverage limit in the settings
(three values) and its effect on the details, no order created by any choice. Screenshots: data/logs/ui_setup_panel/.
Skipped (never "passed") without Playwright/Chromium or the license server package."""
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
from _license import LicenseServerFixture  # noqa: E402

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
        cls.lic = LicenseServerFixture()
        cls.info = cls.lic.issue(note="ui setup panel", max_sessions=2)
        with open(os.path.join(cls.td.dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"server": {"port": PORT, "open_browser": False}, "news": {"enabled": False}, "clock": {"reference_url": None},
                       "risk": {"risk_per_trade_pct": 1.0, "max_total_open_risk_pct": 3.0, "daily_loss_limit_pct": 5.0, "max_drawdown_pct": 10.0,
                                "max_open_positions": 3, "min_free_margin_buffer_pct": 20},
                       "costs": {"slippage_stress_points": 5, "commission_mode": "CONFIGURED", "commission_per_lot_per_side": 3.5},
                       **cls.lic.client_config(), "first_run_completed": True}, f)
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
        cls.page.goto(BASE + "/")
        cls.page.wait_for_selector("[data-testid=setup-panel]", timeout=30000)

    @classmethod
    def start_server(cls):
        cls.proc = subprocess.Popen([sys.executable, "-m", "masterquo", "serve", "--demo", "--no-browser"], env=cls.env, cwd=str(_env.ROOT / "backend"),
                                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.proc.stdin.write((cls.info["key"] + "\n").encode())
        cls.proc.stdin.close()
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
            cls.lic.close()

    def api(self, path):
        return self.page.request.get(BASE + path).json()

    def shot(self, name):
        self.page.locator("[data-testid=setup-panel]").screenshot(path=str(SHOTS / f"{name}.png"))

    def wait_scenarios(self):
        self.assertTrue(wait_for(lambda: len(self.api("/api/v1/setups")["items"]) > 0, 90, 1.0), "no scenario from the synthetic terminal")

    def test_01_auto_all_details_and_refresh(self):
        self.assertIn("on", self.page.get_attribute("[data-testid=setup-auto]", "class") or "")
        self.wait_scenarios()
        self.page.click("[data-testid=setup-all]")
        self.page.wait_for_selector("[data-testid=scenario-list] [data-testid=open-details]", timeout=20000)
        row = self.page.locator("[data-testid=scenario-list] tbody tr").first
        sid = row.get_attribute("data-setup")
        row.locator("[data-testid=open-details]").click()
        self.page.wait_for_selector(f"[data-testid=setup-details][data-setup='{sid}']", timeout=20000)
        txt = self.page.inner_text("[data-testid=setup-details]")
        for part in ("Status scenariusza", "Możliwość wejścia", "Checklista warunków wejścia", "Wymagany próg", "Aktualna wartość",
                     "Szacowana strata przy SL", "Dźwignia rachunku (MT5)", "Limit wybrany przez Ciebie", "Efektywna ekspozycja", "kierunek scenariusza"):
            self.assertIn(part, txt)
        self.assertIn(self.page.inner_text("[data-testid=sd-entry]"), ("DOSTĘPNE", "ZABLOKOWANE"))
        self.shot("01_all_details")
        self.page.reload()                                                     # refresh keeps the manual choice
        self.page.wait_for_selector(f"[data-testid=setup-details][data-setup='{sid}']", timeout=30000)
        self.assertIn("on", self.page.get_attribute("[data-testid=setup-all]", "class") or "")
        type(self).focus = sid

    def test_02_selected_strategy_no_orders(self):
        self.page.click("[data-testid=setup-selected]")
        self.page.wait_for_selector("[data-testid=setup-strategy]")
        self.page.select_option("[data-testid=setup-strategy]", "S03")
        self.assertTrue(wait_for(lambda: self.api("/api/v1/prefs")["setup_view"] == {"mode": "SELECTED", "strategy_id": "S03", "focus_setup_id": None}, 10, 0.3))
        self.assertTrue(wait_for(lambda: self.api("/api/v1/strategy/auto")["manual_strategy_id"] == "S03", 20, 0.5))
        time.sleep(2)
        st = self.api("/api/v1/state")
        self.assertIn((st.get("auto") or {}).get("selected_strategy_id"), (None, "S03"))
        self.assertEqual(st.get("attempts") or [], [])                                          # no order attempt was created
        self.assertIn(st["mode"]["mode"], ("SIGNALS", "PAPER"))
        self.shot("02_selected_S03")
        self.page.reload()
        self.page.wait_for_selector("[data-testid=setup-strategy]", timeout=30000)
        self.assertEqual(self.page.input_value("[data-testid=setup-strategy]"), "S03")

    def test_03_leverage_setting_three_values_and_effect(self):
        self.page.click("[data-testid=setup-all]")
        self.wait_scenarios()
        self.page.click("button[title='Ustawienia']")
        self.page.click("button:has-text('Ryzyko')")
        self.page.wait_for_selector("[data-testid=leverage-settings]")
        self.page.wait_for_function("() => document.querySelector('[data-testid=lev-account]')?.textContent === '1:100'", timeout=10000)                # read from the (synthetic) MT5 account
        self.page.check("[data-testid=leverage-settings] input[type=radio] >> nth=1")
        self.page.select_option("[data-testid=lev-select]", "10")
        self.page.click("[data-testid=lev-save]")
        self.page.wait_for_selector("[data-testid=lev-msg]:has-text('Zapisano')")
        self.assertEqual(self.page.inner_text("[data-testid=lev-user]"), "1:10")
        self.assertNotIn("1:200", self.page.inner_html("[data-testid=lev-select]"))                 # above the account leverage: not offered
        self.page.locator("[data-testid=leverage-settings]").screenshot(path=str(SHOTS / "03_leverage_settings.png"))
        self.page.locator(".modal-head button.icon").first.click()
        p = self.api("/api/v1/prefs")
        self.assertEqual((p["exposure"]["account_leverage"], p["exposure"]["user_limit"], p["exposure"]["limit"]), (100, 10, 10))
        items = [i for i in self.api("/api/v1/setups")["items"] if i["status"] == "ACTIVE"]
        self.assertTrue(items)
        d = self.api(f"/api/v1/setups/{items[0]['setup_id']}/details")
        self.assertEqual(d["leverage"]["user_limit"], 10)
        if d["sizing"]["lots"]:
            self.assertLessEqual(d["leverage"]["effective_exposure_position"], 10.0 + 1e-9)

    def test_04_restart_keeps_choices(self):
        before = self.api("/api/v1/prefs")
        type(self).stop_server()
        type(self).start_server()
        self.page.goto(BASE + "/")
        self.page.wait_for_selector("[data-testid=setup-panel]", timeout=30000)
        after = self.api("/api/v1/prefs")
        self.assertEqual((after["setup_view"], after["leverage"]), (before["setup_view"], before["leverage"]))
        self.assertIn("on", self.page.get_attribute("[data-testid=setup-all]", "class") or "")
        self.shot("04_after_restart")
        self.assertEqual([e for e in self.errors if "WebSocket" not in e and "favicon" not in e and "Failed to load resource" not in e], [])


if __name__ == "__main__":
    unittest.main()
