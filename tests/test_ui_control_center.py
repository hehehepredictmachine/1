"""1.24 desktop panels in a real browser (Chromium + demo backend on the SYNTHETIC terminal): Centrum sterowania (modes with
account confirmation, STOP of new entries, primary path, risk limits, application preferences, Telegram state that is never
pretended) and AI Neural Lab (registry list, illustrative drawing labelled as such, tabs on real endpoints). No order reaches
any broker here - the terminal is the simulator and the tests never select AUTO LIVE (it is refused on synthetic data)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
import urllib.request

import _env
from _env import TempData, wait_for

PORT = 8792
BASE = f"http://127.0.0.1:{PORT}"
CHROMIUM = os.environ.get("MQ_CHROMIUM", "/opt/pw-browsers/chromium")
SHOTS = _env.ROOT / "data" / "logs" / "ui_desktop"
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
class TestControlCenter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (_env.ROOT / "frontend" / "dist" / "index.html").exists():
            raise unittest.SkipTest("frontend not built")
        SHOTS.mkdir(parents=True, exist_ok=True)
        if health():
            raise RuntimeError(f"port {PORT} busy")
        cls.td = TempData()
        os.makedirs(cls.td.dir, exist_ok=True)
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
        cls.page = cls.browser.new_context(viewport={"width": 1600, "height": 1000}).new_page()
        cls.errors = []
        cls.page.on("pageerror", lambda e: cls.errors.append(str(e)))
        cls.page.goto(BASE + "/#/system-control")
        cls.page.wait_for_selector("[data-testid=page-system-control]", timeout=30000)
        wait_for(lambda: cls.page.locator("[data-testid=t-mt5]").get_attribute("data-mt5") == "CONNECTED", 60, 0.5)

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

    def state(self):
        return self.page.request.get(BASE + "/api/v1/state").json()

    def go(self, route, tab=None):
        self.page.goto(BASE + f"/#/{route}")
        self.page.wait_for_selector(f"[data-testid=page-{route}]", timeout=20000)
        if tab:
            self.page.locator(f"[data-testid={tab}]").click()

    def test_01_mode_change_goes_through_the_checked_endpoint(self):
        self.go("system-control", "sc-tab-overview")
        self.assertEqual(self.page.locator("[data-testid=sc-mode-current]").inner_text(), self.state()["mode"]["mode"])
        self.page.locator("[data-testid=sc-mode] [data-mode=SIGNALS]").click()
        self.page.locator("[data-testid=sc-mode-apply]").click()
        wait_for(lambda: self.state()["mode"]["mode"] == "SIGNALS", 10, 0.2)
        self.assertEqual(self.state()["mode"]["mode"], "SIGNALS")
        # AUTO DEMO needs the account login typed - the button stays disabled until the phrase is exact
        self.page.locator("[data-testid=sc-mode] [data-mode=AUTO_DEMO]").click()
        login = str(self.state()["account"]["login"])
        self.assertTrue(self.page.locator("[data-testid=sc-mode-apply]").is_disabled())
        self.assertIn(login, self.page.locator("[data-testid=sc-mode-confirm]").inner_text())
        self.page.locator("[data-testid=sc-mode-phrase]").fill("999")
        self.assertTrue(self.page.locator("[data-testid=sc-mode-apply]").is_disabled())
        self.page.locator("[data-testid=sc-mode] [data-mode=AUTO_LIVE]").click()       # synthetic data: the engine refuses LIVE
        self.page.locator("[data-testid=sc-mode-phrase]").fill(f"LIVE {login}")
        self.page.locator("[data-testid=sc-mode-apply]").click()
        wait_for(lambda: self.page.locator("[data-testid=sc-mode-msg]").count() > 0, 10, 0.2)
        self.assertNotEqual(self.state()["mode"]["mode"], "AUTO_LIVE")
        self.assertIn("niedostępne", self.page.locator("[data-testid=sc-mode-msg]").inner_text())
        self.page.locator("[data-testid=sc-mode] [data-mode=PAPER]").click()
        self.page.locator("[data-testid=sc-mode-apply]").click()
        wait_for(lambda: self.state()["mode"]["mode"] == "PAPER", 10, 0.2)
        self.page.screenshot(path=str(SHOTS / "control_center.png"))

    def test_02_stop_and_primary_path(self):
        self.go("system-control", "sc-tab-overview")
        self.page.locator("[data-testid=sc-stop-btn]").click()
        wait_for(lambda: self.state()["mode"]["kill_switch"] is True, 10, 0.2)
        self.assertIn("STOP", self.page.locator("[data-testid=sc-stop-state]").inner_text())
        wait_for(lambda: "STOP" in self.page.locator("[data-testid=t-entries]").inner_text(), 10, 0.2)
        self.page.locator("[data-testid=sc-stop-btn]").click()
        wait_for(lambda: self.state()["mode"]["kill_switch"] is False, 10, 0.2)
        self.page.locator("[data-testid=sc-path-ACTIVE]").click()
        wait_for(lambda: self.state()["mode"]["primary_path"] == "ACTIVE", 10, 0.2)
        self.page.locator("[data-testid=sc-path-UNSET]").click()
        wait_for(lambda: self.state()["mode"]["primary_path"] == "UNSET", 10, 0.2)

    def test_03_risk_limits_are_set_consciously(self):
        self.go("system-control", "sc-tab-risk")
        self.page.wait_for_selector("[data-testid=sc-risk-risk_per_trade_pct]")
        self.assertEqual(self.page.locator("[data-testid=sc-risk-risk_per_trade_pct]").input_value(), "")   # not configured = empty, not 0
        self.page.locator("[data-testid=sc-risk-risk_per_trade_pct]").fill("0.5")
        self.page.locator("[data-testid=sc-risk-max_open_positions]").fill("2")
        self.page.locator("[data-testid=sc-risk-save]").click()
        wait_for(lambda: self.state()["risk_config"]["risk_per_trade_pct"] == 0.5, 10, 0.2)
        self.assertEqual(self.state()["risk_config"]["max_open_positions"], 2)
        self.assertIsNone(self.state()["risk_config"]["daily_loss_limit_pct"])                   # untouched fields stay unset

    def test_04_application_preferences_and_telegram_state(self):
        self.go("system-control", "sc-tab-overview")
        self.page.wait_for_selector("[data-testid=sc-close-action]")
        self.assertTrue(self.page.locator("[data-testid=sc-autostart]").is_disabled())          # browser, not the Windows app
        self.page.locator("[data-testid=sc-close-action]").select_option("background")
        self.page.locator("[data-testid=sc-app-save]").click()
        wait_for(lambda: self.page.request.get(BASE + "/api/v1/desktop").json()["prefs"]["close_action"] == "background", 10, 0.2)
        self.go("system-control", "sc-tab-connections")
        self.page.wait_for_selector("[data-testid=sc-tg-state]")
        wait_for(lambda: self.page.locator("[data-testid=sc-tg-state]").get_attribute("data-state") != "", 10, 0.2)
        self.page.wait_for_selector("[data-testid=sc-tg-chat]")
        self.assertEqual(self.page.locator("[data-testid=sc-tg-state]").get_attribute("data-state"), "NOT_CONFIGURED")
        self.assertTrue(self.page.locator("[data-testid=sc-tg-test]").is_disabled())            # nothing to test without token + chat
        self.page.locator("[data-testid=sc-tg-chat]").fill("12345")
        self.page.locator("[data-testid=sc-tg-lang]").select_option("ZH")
        self.page.locator("[data-testid=sc-tg-save]").click()
        wait_for(lambda: self.page.request.get(BASE + "/api/v1/telegram").json()["language"] == "ZH", 10, 0.2)
        st = self.page.request.get(BASE + "/api/v1/telegram").json()
        self.assertEqual((st["state"], st["chat_id_set"], st["token_set"]), ("NOT_CONFIGURED", True, False))

    def test_05_neural_lab_on_the_registry(self):
        self.go("ai-neural-lab", "nl-tab-universe")
        self.page.wait_for_selector("[data-testid=nl-models] [data-model]")
        reg = self.page.request.get(BASE + "/api/v1/training/models?instrument=XAUUSD").json()
        trained = [m for m in reg["models"] if m["kind"] == "TRAINED"]
        self.assertEqual(self.page.locator("[data-testid=nl-models] [data-model]").count(), len(trained))
        self.assertIn("NIE DANE MODELU", self.page.locator("[data-testid=nl-illustration]").inner_text())
        ready = sum(1 for m in trained if m["status"] == "READY")
        self.assertIn(f"{ready} / {len(trained)}", self.page.locator("[data-testid=nl-ready]").inner_text())
        self.page.locator("[data-testid=nl-shape-xgb]").click()
        self.assertEqual(self.page.locator("[data-testid=nl-canvas]").get_attribute("data-shape"), "xgb")
        self.page.locator("[data-testid=nl-next]").click()
        self.assertIn("Krok 2", self.page.locator("[data-testid=nl-step]").inner_text())
        self.assertEqual(self.page.locator("[data-testid=nl-canvas]").get_attribute("data-mode"), "path")
        first = trained[0]
        self.page.locator(f"[data-testid=nl-models] [data-model={first['id']}]").click()
        self.assertIn(first["name"][:20], self.page.locator("[data-testid=nl-details]").inner_text())
        self.page.locator("[data-testid=nl-tab-training]").click()
        self.page.wait_for_selector("[data-testid=nl-training]")
        self.page.locator("[data-testid=nl-tab-validation]").click()
        self.page.wait_for_selector("[data-testid=nl-validation]")
        self.page.locator("[data-testid=nl-tab-deploy]").click()
        self.page.wait_for_selector("[data-testid=nl-deploy]")
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main()
