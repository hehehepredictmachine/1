"""Administrator panel in a real browser against a real license server: login (password + TOTP), generate a 72 h
license (key shown once), revoke it; a VIEWER cannot create. Skipped (never "passed") without Playwright/Chromium."""
from __future__ import annotations

import os
import unittest

import _env  # noqa: F401
from _license import LicenseServerFixture  # noqa: E402

CHROMIUM = os.environ.get("MQ_CHROMIUM", "/opt/pw-browsers/chromium")
try:
    from playwright.sync_api import sync_playwright
    HAVE_PW = True
except Exception:  # pragma: no cover
    HAVE_PW = False


@unittest.skipUnless(HAVE_PW, "playwright not installed")
class TestAdminPanelUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pyotp
        cls.pyotp = pyotp
        cls.f = LicenseServerFixture()
        cls.adm = cls.f.svc.add_admin("panel-admin@example.invalid", "a-long-panel-password-1", "ADMIN")
        cls.view = cls.f.svc.add_admin("panel-viewer@example.invalid", "a-long-panel-password-2", "VIEWER")
        cls.pw = sync_playwright().start()
        kw = {"executable_path": CHROMIUM} if os.path.exists(CHROMIUM) else {}
        cls.browser = cls.pw.chromium.launch(**kw)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.f.close()

    def login(self, page, who, pw):
        page.goto(self.f.url + "/admin/")
        page.fill("input[name=email]", who["email"])
        page.fill("input[name=password]", pw)
        page.fill("input[name=code]", self.pyotp.TOTP(who["totp_secret"]).now())
        page.click("[data-testid=login]")
        page.wait_for_selector("nav")

    def test_01_admin_generates_and_revokes(self):
        ctx = self.browser.new_context()
        page = ctx.new_page()
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.goto(self.f.url + "/admin/")
        page.fill("input[name=email]", self.adm["email"])
        page.fill("input[name=password]", "wrong-password-123")
        page.fill("input[name=code]", "123456")
        page.click("[data-testid=login]")
        page.wait_for_selector("#le:has-text('Nieprawidłowy')")
        self.login(page, self.adm, "a-long-panel-password-1")
        page.click("nav [data-tab=lic]")
        page.fill("#nf input[name=note]", "test UI")
        page.click("[data-testid=gen]")
        key = page.inner_text("[data-testid=new-key]").strip()
        self.assertTrue(key.startswith("MQL72-"))
        lic = [x for x in self.f.svc.list_licenses() if x["note"] == "test UI"][0]
        self.assertEqual(lic["expires_at"] - lic["created_at"], 259200)
        page.click("nav [data-tab=lic]")
        self.assertNotIn(key, page.content())                         # shown only once, not in the list
        page.once("dialog", lambda d: d.accept("test UI revoke"))
        page.click(f"tr[data-id='{lic['id']}'] button[data-act=revoke]")
        page.wait_for_selector(f"tr[data-id='{lic['id']}'] .st-COFNIETA")
        self.assertEqual(self.f.svc.get_license(lic["id"])["status"], "COFNIETA")
        page.click("nav [data-tab=aud]")
        page.wait_for_selector("td:has-text('LICENSE_REVOKE')")
        self.assertNotIn(key, page.content())                         # audit never shows full keys
        self.maxDiff = None
        self.assertEqual([e for e in errors if "401" not in e], [])
        ctx.close()

    def test_02_viewer_cannot_create(self):
        ctx = self.browser.new_context()
        page = ctx.new_page()
        self.login(page, self.view, "a-long-panel-password-2")
        page.click("nav [data-tab=lic]")
        page.wait_for_selector("[data-testid=lic-table]")
        self.assertEqual(page.locator("[data-testid=gen]").count(), 0)
        # and the endpoint itself refuses (not only the view)
        r = page.evaluate("""async () => { const me = await (await fetch('/api/v1/admin/me')).json();
            const r = await fetch('/api/v1/admin/licenses', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF': me.csrf}, body: '{}'});
            return [r.status, (await r.json()).error]; }""")
        self.assertEqual(r, [403, "FORBIDDEN_ROLE"])
        ctx.close()

    def test_03_one_click_generation(self):
        ctx = self.browser.new_context()
        page = ctx.new_page()
        self.login(page, self.adm, "a-long-panel-password-1")
        before = len(self.f.svc.list_licenses())
        page.click("[data-testid=quick-gen]")                     # one button, no form
        key = page.inner_text("[data-testid=quick-key]").strip()
        self.assertTrue(key.startswith("MQL72-"))
        self.assertEqual(len(self.f.svc.list_licenses()), before + 1)
        newest = self.f.svc.list_licenses()[0]
        self.assertEqual((newest["expires_at"] - newest["created_at"], newest["max_sessions"]), (259200, 1))
        ctx.close()
        vctx = self.browser.new_context()
        vpage = vctx.new_page()
        self.login(vpage, self.view, "a-long-panel-password-2")
        self.assertEqual(vpage.locator("[data-testid=quick-gen]").count(), 0)   # VIEWER has no button
        vctx.close()


if __name__ == "__main__":
    unittest.main()
