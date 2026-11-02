"""License System v1 in the panel (Chromium): a real License API (uvicorn thread) + two demo bots.
CLIENT edition: KEY FOR MAGIC covers the panel until a valid key is activated (wrong key -> clear error; the right key -> the panel
opens, license chip "do <expiry>"), a revocation by the administrator brings the window back at the next periodic check (here every
5 s) with the open-position note. OWNER edition: License Manager - login to the license server, one-time key display, list, revoke.
Screenshots: data/logs/ui_license/. Skipped (never "passed") without Playwright/Chromium."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unittest
import urllib.request
from pathlib import Path

import _env
from _env import TempData, wait_for
from test_license_server import PASSWORD, Clock, Server, call

CHROMIUM = os.environ.get("MQ_CHROMIUM", "/opt/pw-browsers/chromium")
SHOTS = _env.ROOT / "data" / "logs" / "ui_license"
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


class Bot:
    def __init__(self, port: int, extra_env: dict):
        self.port, self.td = port, TempData()
        with open(os.path.join(self.td.dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"server": {"port": port, "open_browser": False}, "news": {"enabled": False}, "clock": {"reference_url": None},
                       "first_run_completed": True}, f)
        self.env = dict(os.environ, MASTERQUO_DATA_DIR=self.td.dir, PYTHONPATH=str(_env.ROOT / "backend"), **extra_env)
        self.env.pop("ANTHROPIC_API_KEY", None)
        self.proc = subprocess.Popen([sys.executable, "-m", "masterquo", "serve", "--demo", "--no-browser"], env=self.env, cwd=str(_env.ROOT / "backend"),
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not wait_for(lambda: up(port), 60, 0.5):
            self.proc.kill()
            raise RuntimeError("bot did not start")

    def stop(self):
        subprocess.run([sys.executable, "-m", "masterquo", "stop"], env=self.env, cwd=str(_env.ROOT / "backend"), timeout=60)
        try:
            self.proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.td.close()


@unittest.skipUnless(HAVE_PW, "playwright not installed")
class TestLicenseUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (_env.ROOT / "frontend" / "dist" / "index.html").exists():
            raise unittest.SkipTest("frontend not built")
        SHOTS.mkdir(parents=True, exist_ok=True)
        cls.td = TempData()
        cls.srv = Server(Path(cls.td.dir) / "srv", Clock())
        ed = Path(cls.td.dir) / "edition_client.json"
        ed.write_text(json.dumps({"edition": "CLIENT", "license_api": cls.srv.base, "public_key": cls.srv.signer.public_b64,
                                  "kid": cls.srv.signer.kid}), encoding="utf-8")
        cls.client = Bot(8786, {"MASTERQUO_EDITION_FILE": str(ed), "MASTERQUO_LICENSE_INTERVAL": "5", "PMW_HWID_OVERRIDE": "ui-test-device"})
        cls.owner = Bot(8785, {})
        cls.pw = sync_playwright().start()
        kw = {"executable_path": CHROMIUM} if os.path.exists(CHROMIUM) else {}
        cls.browser = cls.pw.chromium.launch(**kw)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.browser.close()
            cls.pw.stop()
        finally:
            cls.client.stop()
            cls.owner.stop()
            cls.srv.stop()
            cls.td.close()

    def admin(self):
        return call(self.srv.base, "/api/v1/admin/login", {"username": "owner", "password": PASSWORD})[1]["token"]

    def test_01_client_key_for_magic(self):
        key = call(self.srv.base, "/api/v1/admin/licenses", {"duration": "7d"}, self.admin())[1]["license_key"]
        ctx = self.browser.new_context(viewport={"width": 1366, "height": 768})
        p = ctx.new_page()
        try:
            p.goto(f"http://127.0.0.1:{self.client.port}/#/menu?webgl=0")
            p.wait_for_selector("[data-testid=license-overlay]", timeout=60000)
            self.assertEqual(p.locator("[data-testid=license-overlay]").get_attribute("data-status"), "NOT_ACTIVATED")
            self.assertIn("KEY FOR MAGIC", p.locator("#kfm-title").inner_text())
            p.screenshot(path=str(SHOTS / "01_key_for_magic.png"))
            p.fill("[data-testid=license-key]", "PMW-00000-00000-00000-00000")
            p.click("[data-testid=license-activate]")
            self.assertTrue(wait_for(lambda: "nieprawidłowy" in p.locator("[data-testid=license-status]").inner_text(), 20, 0.2))
            p.screenshot(path=str(SHOTS / "02_invalid_key.png"))
            p.fill("[data-testid=license-key]", key)
            p.click("[data-testid=license-activate]")
            self.assertTrue(wait_for(lambda: p.locator("[data-testid=license-overlay]").count() == 0, 30, 0.2))
            self.assertTrue(wait_for(lambda: p.locator("[data-testid=license-chip]").count() > 0, 20, 0.2))
            self.assertIn("Licencja", p.locator("[data-testid=license-chip]").inner_text())
            p.screenshot(path=str(SHOTS / "03_activated.png"))
            st = p.request.get(f"http://127.0.0.1:{self.client.port}/api/v1/license").json()
            self.assertEqual((st["status"], st["authorized"], st["edition"]["edition"]), ("ACTIVE", True, "CLIENT"))
            self.assertNotIn(key, json.dumps(st))
            lid = st["license_id"]
            call(self.srv.base, f"/api/v1/admin/licenses/{lid}/revoke", {"reason": "test UI"}, self.admin())
            p.wait_for_selector("[data-testid=license-overlay][data-status=REVOKED]", timeout=30000)   # next periodic check (5 s)
            self.assertIn("Otwarte pozycje", p.locator("[data-testid=license-positions]").inner_text())
            p.screenshot(path=str(SHOTS / "04_revoked.png"))
        finally:
            ctx.close()

    def test_02_owner_license_manager(self):
        ctx = self.browser.new_context(viewport={"width": 1366, "height": 900})
        p = ctx.new_page()
        p.on("dialog", lambda d: d.accept("koniec współpracy"))
        try:
            p.goto(f"http://127.0.0.1:{self.owner.port}/#/licencje")
            p.wait_for_selector("[data-testid=page-licencje]", timeout=60000)
            self.assertEqual(p.locator("[data-testid=license-overlay]").count(), 0)               # OWNER: no gate
            p.wait_for_selector("[data-testid=lm-login]", timeout=20000)
            p.fill("[data-testid=lm-url]", self.srv.base)
            p.fill("[data-testid=lm-user]", "owner")
            p.fill("[data-testid=lm-pass]", "zle-haslo-123456")
            p.click("[data-testid=lm-login-btn]")
            self.assertTrue(wait_for(lambda: p.locator("[data-testid=lm-error]").count() > 0, 20, 0.2))
            p.fill("[data-testid=lm-pass]", PASSWORD)
            p.click("[data-testid=lm-login-btn]")
            p.wait_for_selector("[data-testid=lm-stats]", timeout=20000)
            p.click("[data-testid=lm-dur-72h]")
            p.fill("[data-testid=lm-note]", "klient testowy")
            p.click("[data-testid=lm-create]")
            p.wait_for_selector("[data-testid=lm-new-key]", timeout=20000)
            key = p.locator("[data-testid=lm-key-value]").inner_text()
            self.assertRegex(key, r"^PMW-[0-9A-Z]{5}(-[0-9A-Z]{5}){3}$")
            self.assertTrue(wait_for(lambda: p.locator("[data-testid=lm-row]").count() > 0, 20, 0.2))
            p.screenshot(path=str(SHOTS / "05_owner_new_key.png"), full_page=True)
            n_rev = p.locator("[data-testid=lm-row][data-status=REVOKED]").count()
            row = p.locator("[data-testid=lm-row][data-status=CREATED]").first
            row.locator("button", has_text="Cofnij").click()
            self.assertTrue(wait_for(lambda: p.locator("[data-testid=lm-row][data-status=REVOKED]").count() == n_rev + 1, 20, 0.2))
            p.reload()
            p.wait_for_selector("[data-testid=page-licencje]", timeout=30000)
            self.assertEqual(p.locator("[data-testid=lm-key-value]").count(), 0)                 # the key is never shown again
            body = p.locator("body").inner_text()
            self.assertNotIn(key, body)
            self.assertIsNone(re.search(PASSWORD, body))
            p.screenshot(path=str(SHOTS / "06_owner_list.png"), full_page=True)
        finally:
            ctx.close()


if __name__ == "__main__":
    unittest.main()
