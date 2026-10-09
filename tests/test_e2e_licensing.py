"""Test 15 - complete flow in real processes and a real browser:

register (monitor) -> verify e-mail (account page) -> admin logs in with TOTP and generates a 48 h-type license in the
MasterQUO License Manager -> client enters the key in the monitor -> enables the MT5 connector -> admin sees the
account data -> license expires -> client loses new functions -> admin issues a new license -> access returns.

The central server runs in MQC_ENV=dev with MQC_LICENSE_SECONDS=45 so the expiry happens within the test (the exact
172800 s boundary is tested with a controlled clock in test_central). Data are synthetic test fixtures.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import _env
from _env import TempData, wait_for
from test_licensing_client import free_port

CHROMIUM = os.environ.get("MQ_CHROMIUM", "/opt/pw-browsers/chromium")
try:
    import pyotp
    from playwright.sync_api import sync_playwright
    HAVE = True
except ImportError:  # pragma: no cover
    HAVE = False

ADMIN_PW = "zielona-zaba-tanczy-77"
USER = "jan.klient@example.com"
USER_PW = "haslo-klienta-12345"


def http_ok(url: str) -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


@unittest.skipUnless(HAVE and (_env.ROOT / "server" / "admin-web" / "dist" / "admin.html").exists(), "playwright / admin-web build missing")
class TestEndToEndLicensing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="mq_e2e_"))
        cls.cport, cls.bport = free_port(), free_port()
        cls.central = f"http://127.0.0.1:{cls.cport}"
        cls.bot = f"http://127.0.0.1:{cls.bport}"
        from cryptography.fernet import Fernet
        cls.cenv = dict(os.environ, MQC_ENV="dev", MQC_DATABASE_URL=f"sqlite:///{cls.tmp}/central.sqlite", MQC_PUBLIC_URL=cls.central,
                        MQC_ALLOWED_ORIGINS=cls.central, MQC_SIGNING_KEY_FILE=str(cls.tmp / "lease.pem"), MQC_DATA_KEY=Fernet.generate_key().decode(),
                        MQC_MAIL_MODE="dev-outbox", MQC_SECURE_COOKIES="0", MQC_LICENSE_SECONDS="45", MQC_ENV_FILE=str(cls.tmp / "none.env"),
                        PYTHONPATH=str(_env.ROOT / "server"))
        srv = str(_env.ROOT / "server")
        subprocess.run([sys.executable, "-m", "mqcentral", "gen-keys", "--out", str(cls.tmp / "lease.pem")], env=cls.cenv, cwd=srv, check=True, capture_output=True)
        # first administrator (the CLI asks for the password with getpass - here the same function is called directly)
        boot = subprocess.run([sys.executable, "-c", "import json,sys; from mqcentral.__main__ import build; c=build(); "
                               f"print(json.dumps(c.bootstrap_admin('boss@example.com', '{ADMIN_PW}')))"], env=cls.cenv, cwd=srv, check=True,
                              capture_output=True, text=True)
        cls.totp = pyotp.TOTP(json.loads(boot.stdout.strip().splitlines()[-1])["totp_secret"])
        cls.cproc = subprocess.Popen([sys.executable, "-m", "mqcentral", "serve", "--port", str(cls.cport)], env=cls.cenv, cwd=srv,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        assert wait_for(lambda: http_ok(cls.central + "/api/v1/health"), 60, 0.5), "central server did not start"
        cls.td = TempData()
        with open(os.path.join(cls.td.dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"server": {"port": cls.bport, "open_browser": False}, "news": {"enabled": False}, "clock": {"reference_url": None},
                       "first_run_completed": True}, f)
        cls.benv = dict(os.environ, MASTERQUO_DATA_DIR=cls.td.dir, PYTHONPATH=str(_env.ROOT / "backend"))
        cls.benv.pop("ANTHROPIC_API_KEY", None)
        cls.bproc = subprocess.Popen([sys.executable, "-m", "masterquo", "serve", "--demo", "--no-browser"], env=cls.benv, cwd=str(_env.ROOT / "backend"),
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        assert wait_for(lambda: http_ok(cls.bot + "/api/v1/health"), 60, 0.5), "bot did not start"
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(**({"executable_path": CHROMIUM} if os.path.exists(CHROMIUM) else {}))
        cls.user_ctx = cls.browser.new_context(viewport={"width": 1500, "height": 1000})
        cls.admin_ctx = cls.browser.new_context(viewport={"width": 1500, "height": 1000})   # separate browser profile
        cls.mon = cls.user_ctx.new_page()
        cls.adm = cls.admin_ctx.new_page()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.browser.close()
            cls.pw.stop()
        finally:
            subprocess.run([sys.executable, "-m", "masterquo", "stop"], env=cls.benv, cwd=str(_env.ROOT / "backend"), timeout=60)
            cls.cproc.terminate()
            try:
                cls.bproc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                cls.bproc.kill()
            cls.td.close()

    def outbox_token(self, to: str, subject_part: str) -> str:
        c = sqlite3.connect(self.tmp / "central.sqlite")
        rows = c.execute("SELECT subject, body FROM mail_outbox WHERE to_addr=? ORDER BY created_at DESC", (to,)).fetchall()
        c.close()
        body = next(b for s, b in rows if subject_part in s)
        return body.split("#token=")[1].split()[0]

    def admin_generate(self) -> str:
        a = self.adm
        a.get_by_role("button", name="Licencje").click()
        a.get_by_role("button", name="Wygeneruj licencję 48h").first.click()
        dlg = a.locator("[role=dialog][aria-label='Generowanie licencji']")
        dlg.locator("input").first.fill("jan.klient")
        a.wait_for_function("() => document.querySelectorAll(\"select[name=user] option\").length > 1", timeout=10000)
        val = dlg.locator("select[name=user] option", has_text=USER).get_attribute("value")
        dlg.locator("select[name=user]").select_option(val)
        dlg.locator("input[name=note]").fill("test e2e")
        dlg.get_by_role("button", name="Utwórz licencję").click()
        key = a.locator("[data-testid=license-key]").inner_text().strip()
        a.get_by_role("button", name=re.compile("Zamknij")).click()
        self.assertEqual(a.locator("[data-testid=license-key]").count(), 0)          # shown only once
        return key

    def test_full_flow(self):
        m, a = self.mon, self.adm
        # ---- 1. monitor: a plain http:// server address is refused (HTTPS required for clients)
        m.goto(self.bot + "/")
        m.locator("input[name=central-url]").fill(self.central)
        m.get_by_role("button", name="Zapisz").click()
        m.wait_for_selector(".note.bad")
        self.assertIn("https", m.locator(".note.bad").inner_text())
        # local development only: the flag is set in the local config file (not reachable from the browser), then restart
        subprocess.run([sys.executable, "-m", "masterquo", "stop"], env=self.benv, cwd=str(_env.ROOT / "backend"), timeout=60)
        self.bproc.wait(timeout=30)
        cfgp = Path(self.td.dir) / "config.json"
        c = json.loads(cfgp.read_text())
        c.setdefault("central", {}).update({"url": self.central, "allow_insecure_localhost": True})
        cfgp.write_text(json.dumps(c))
        type(self).bproc = subprocess.Popen([sys.executable, "-m", "masterquo", "serve", "--demo", "--no-browser"], env=self.benv, cwd=str(_env.ROOT / "backend"),
                                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.assertTrue(wait_for(lambda: http_ok(self.bot + "/api/v1/health"), 60, 0.5))
        m.goto(self.bot + "/")
        m.get_by_role("button", name="Rejestracja").click()
        m.locator("input[name=email]").fill(USER)
        m.locator("input[name=password]").fill(USER_PW)
        m.get_by_role("button", name="Załóż konto").click()
        m.wait_for_selector("[data-testid=gate-msg]")
        # ---- 2. login before verification is refused; verify via the account page
        m.get_by_role("button", name="Logowanie").click()
        m.locator("input[name=email]").fill(USER)
        m.locator("input[name=password]").fill(USER_PW)
        m.get_by_role("button", name="Zaloguj").click()
        m.wait_for_selector("[data-testid=gate-msg]")
        self.assertIn("Potwierdź", m.locator("[data-testid=gate-msg]").inner_text())
        tok = self.outbox_token(USER, "potwierdź")
        v = self.user_ctx.new_page()
        v.goto(f"{self.central}/account/verify#token={tok}")
        self.assertNotIn(tok, v.url)                                              # token removed from the address bar
        v.get_by_role("button", name="Potwierdź adres").click()
        v.wait_for_selector("[data-testid=verified]")
        v.close()
        # ---- 3. login -> activation screen (no license yet: product locked, analysis API refused)
        m.locator("input[name=password]").fill(USER_PW)
        m.get_by_role("button", name="Zaloguj").click()
        m.wait_for_selector("input[name=license-key]")
        st = json.loads(m.evaluate("() => fetch('/api/v1/signals').then(r => r.status + '')"))
        self.assertEqual(st, 403)
        # ---- 4. admin: password + TOTP, sees the user, generates the license (key shown once)
        a.goto(self.central + "/admin/")
        a.locator("input[name=email]").fill("boss@example.com")
        a.locator("input[name=password]").fill(ADMIN_PW)
        a.get_by_role("button", name="Zaloguj").click()
        a.locator("input[name=mfa]").fill(self.totp.now())
        a.get_by_role("button", name="Potwierdź kod").click()
        a.wait_for_selector(f"tr[data-email='{USER}']")
        key = self.admin_generate()
        self.assertTrue(key.startswith("MQL1-"))
        # ---- 5. client activates -> monitor with license bar
        m.locator("input[name=license-key]").fill(key)
        m.get_by_role("button", name="Aktywuj licencję").click()
        m.wait_for_selector("[data-testid=license-bar]", timeout=30000)
        self.assertIn("ACTIVE", m.locator("[data-testid=license-bar]").inner_text())
        m.wait_for_selector("[data-testid=entry-checklist]", timeout=60000)      # product (checklist) available
        # ---- 6. connector: explicit consent, then admin sees balance/equity of THIS account
        m.once("dialog", lambda d: d.accept())
        m.locator("[data-testid=license-bar]").get_by_role("button", name="Włącz…").click()
        a.get_by_role("button", name="Użytkownicy").click()
        row = a.locator(f"tr[data-email='{USER}']")
        ok = wait_for(lambda: (a.reload() or True) and "USD" in a.locator(f"tr[data-email='{USER}']").inner_text(), 60, 3)
        self.assertTrue(ok, row.inner_text() if row.count() else "no row")
        txt = a.locator(f"tr[data-email='{USER}']").inner_text()
        self.assertIn("DEMO", txt)
        self.assertIn("ACTIVE", txt)
        self.assertIn("ONLINE", txt)
        # ---- 7. license expires (45 s in this dev setup) -> client loses new functions
        self.assertTrue(wait_for(lambda: m.locator("[data-testid=lock-reason]").count() > 0, 90, 1), "monitor did not lock after expiry")
        self.assertIn("wygasła", m.locator("[data-testid=lock-reason]").inner_text())
        self.assertEqual(json.loads(m.evaluate("() => fetch('/api/v1/signals').then(r => r.status + '')")), 403)
        # ---- 8. admin issues a NEW license -> access returns without reinstall
        a.reload()
        a.wait_for_selector(f"tr[data-email='{USER}']")
        key2 = self.admin_generate()
        self.assertNotEqual(key, key2)
        m.locator("input[name=license-key]").fill(key2)
        m.get_by_role("button", name="Aktywuj licencję").click()
        m.wait_for_selector("[data-testid=license-bar]", timeout=30000)
        self.assertEqual(json.loads(m.evaluate("() => fetch('/api/v1/signals').then(r => r.status + '')")), 200)
        # ---- 9. logout: monitor returns to login, no data of the previous user stays visible
        m.locator("[data-testid=license-bar]").get_by_role("button", name="Wyloguj").click()
        m.wait_for_selector("input[name=email]", timeout=20000)
        body = m.locator("body").inner_text()
        self.assertNotIn("BALANCE", body)
        self.assertNotIn(USER, body)
        self.assertEqual(json.loads(m.evaluate("() => fetch('/api/v1/state').then(r => r.json()).then(j => JSON.stringify(j.account === undefined))")), True)
