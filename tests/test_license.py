"""Licensing: server (server/mqlicense) + client (masterquo.license) + gating. Time is simulated with ControlledClock,
nothing waits 72 hours. No real license, no real account."""
from __future__ import annotations

import io
import json
import os
import sqlite3
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request

import _env  # noqa: F401
from _env import TempData
from _license import TEST_ADMIN, LicenseServerFixture, free_port  # noqa: E402

try:
    import pyotp  # noqa: E402
    from mqlicense import LICENSE_SECONDS  # noqa: E402
    from mqlicense.clock import ControlledClock  # noqa: E402
    from mqlicense.service import Denied  # noqa: E402
except ImportError:                             # client package without the server: whole module skipped
    raise unittest.SkipTest("license server package (server/mqlicense) not present") from None

from masterquo.license.client import LicenseClient, LicenseError  # noqa: E402
from masterquo.license.guard import LicenseGuard, licensed, prompt_key  # noqa: E402

T0 = 1_790_000_000
BOOT = "b" * 32


def nonce():
    return os.urandom(16).hex()


def http(method, url, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}"), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}"), dict(e.headers)


class TestLicenseService(unittest.TestCase):
    def setUp(self):
        self.clock = ControlledClock(T0)
        self.f = LicenseServerFixture(clock=self.clock, serve=False)
        self.svc = self.f.svc

    def tearDown(self):
        self.f.close()

    def test_01_exactly_72h_from_generation_server_clock(self):
        self.assertEqual(LICENSE_SECONDS, 259200)
        lic = self.f.issue()
        self.assertEqual(lic["expires_at"] - lic["created_at"], 259200)
        self.assertEqual(lic["created_at"], T0)
        self.clock.advance(259199)                          # first use 1 s before expiry: still valid, NOT extended
        s = self.svc.open_session(lic["key"], boot_id=BOOT, nonce=nonce())
        self.assertEqual(s["license_expires_at"], T0 + 259200)
        self.assertLessEqual(s["lease_expires_at"], T0 + 259200)   # lease never beyond the license
        self.clock.advance(1)
        with self.assertRaises(Denied) as e:
            self.svc.heartbeat(s["session_token"], boot_id=BOOT)
        self.assertEqual(e.exception.code, "LICENSE_EXPIRED")
        with self.assertRaises(Denied) as e:
            self.svc.open_session(lic["key"], boot_id="c" * 32, nonce=nonce())
        self.assertEqual(e.exception.code, "LICENSE_EXPIRED")
        self.assertEqual(self.svc.get_license(lic["id"])["status"], "WYGASLA")

    def test_02_key_never_stored_in_plaintext(self):
        lic = self.f.issue(note="x")
        self.assertTrue(lic["key"].startswith("MQL72-"))
        self.assertNotIn("key", self.svc.get_license(lic["id"]))
        self.svc.open_session(lic["key"], boot_id=BOOT, nonce=nonce())
        con = sqlite3.connect(self.f.settings.db_path)
        dump = "\n".join(con.iterdump())
        con.close()
        raw = lic["key"].replace("-", "")
        self.assertNotIn(lic["key"], dump)
        self.assertNotIn(raw[5:], dump)
        self.assertIn(lic["key_hint"], dump)               # only a short hint (last 4 symbols)

    def test_03_unknown_and_malformed_get_same_answer(self):
        from mqlicense import security as sec
        for k in ("", "abc", "MQL72-AAAAA", sec.license_key()):
            with self.assertRaises(Denied) as e:
                self.svc.open_session(k, boot_id=BOOT, nonce=nonce())
            self.assertEqual(e.exception.code, "LICENSE_INVALID")

    def test_04_session_limit_crash_recovery_and_end(self):
        lic = self.f.issue()
        s1 = self.svc.open_session(lic["key"], boot_id="1" * 32, nonce=nonce())
        with self.assertRaises(Denied) as e:
            self.svc.open_session(lic["key"], boot_id="2" * 32, nonce=nonce())
        self.assertEqual(e.exception.code, "SESSION_LIMIT_REACHED")
        self.clock.advance(31)                              # run 1 crashed: its lease lapsed -> slot free
        s2 = self.svc.open_session(lic["key"], boot_id="2" * 32, nonce=nonce())
        with self.assertRaises(Denied) as e:                # the crashed run cannot come back while run 2 holds the slot
            self.svc.heartbeat(s1["session_token"], boot_id="1" * 32)
        self.assertEqual(e.exception.code, "SESSION_LIMIT_REACHED")
        self.svc.end_session(s2["session_token"], boot_id="2" * 32)   # clean exit frees the slot at once
        self.svc.open_session(lic["key"], boot_id="3" * 32, nonce=nonce())
        lic2 = self.f.issue(max_sessions=2)
        self.svc.open_session(lic2["key"], boot_id="4" * 32, nonce=nonce())
        self.svc.open_session(lic2["key"], boot_id="5" * 32, nonce=nonce())

    def test_05_revoke_and_terminate_reach_client_on_next_renewal(self):
        lic = self.f.issue()
        s = self.svc.open_session(lic["key"], boot_id=BOOT, nonce=nonce())
        self.assertLessEqual(s["lease_expires_at"] - T0, 30)
        self.svc.heartbeat(s["session_token"], boot_id=BOOT)
        with self.assertRaises(Denied):
            self.svc.revoke_license(TEST_ADMIN, lic["id"], "")          # reason required
        self.svc.revoke_license(TEST_ADMIN, lic["id"], "test")
        with self.assertRaises(Denied) as e:
            self.svc.heartbeat(s["session_token"], boot_id=BOOT)
        self.assertEqual(e.exception.code, "LICENSE_REVOKED")
        with self.assertRaises(Denied) as e:
            self.svc.open_session(lic["key"], boot_id="9" * 32, nonce=nonce())
        self.assertEqual(e.exception.code, "LICENSE_REVOKED")
        lic2 = self.f.issue()
        s2 = self.svc.open_session(lic2["key"], boot_id=BOOT, nonce=nonce())
        self.svc.terminate_session(TEST_ADMIN, s2["session_id"])
        with self.assertRaises(Denied) as e:
            self.svc.heartbeat(s2["session_token"], boot_id=BOOT)
        self.assertEqual(e.exception.code, "SESSION_TERMINATED")

    def test_06_reissue_creates_new_key_and_record(self):
        lic = self.f.issue(note="klient A")
        self.clock.advance(3600)
        new = self.svc.reissue_license(TEST_ADMIN, lic["id"], "zgubiony klucz")
        self.assertNotEqual(new["key"], lic["key"])
        self.assertEqual(new["replaces"], lic["id"])
        self.assertEqual(new["expires_at"], T0 + 3600 + 259200)
        old = self.svc.get_license(lic["id"])
        self.assertEqual(old["status"], "COFNIETA")
        self.assertEqual(old["replaced_by"], new["id"])

    def test_07_nonce_replay_and_boot_binding(self):
        lic = self.f.issue()
        n = nonce()
        s = self.svc.open_session(lic["key"], boot_id=BOOT, nonce=n)
        self.svc.end_session(s["session_token"], boot_id=BOOT)
        with self.assertRaises(Denied) as e:
            self.svc.open_session(lic["key"], boot_id=BOOT, nonce=n)
        self.assertEqual(e.exception.code, "NONCE_REUSED")
        s = self.svc.open_session(lic["key"], boot_id=BOOT, nonce=nonce())
        with self.assertRaises(Denied):
            self.svc.heartbeat(s["session_token"], boot_id="z" * 32)       # token of another run

    def test_08_clock_anomaly_stops_issuing(self):
        lic = self.f.issue()
        self.clock.anomaly = "CLOCK_WENT_BACK_600S"
        with self.assertRaises(Denied) as e:
            self.svc.open_session(lic["key"], boot_id=BOOT, nonce=nonce())
        self.assertEqual(e.exception.code, "SERVER_CLOCK_ANOMALY")
        with self.assertRaises(Denied):
            self.f.issue()

    def test_09_admin_bootstrap_login_totp_roles(self):
        self.assertFalse(self.svc.admins_exist())          # no default administrator / password
        with self.assertRaises(Denied):
            self.svc.add_admin("a@example.invalid", "short", bootstrap=True)
        a = self.svc.add_admin("a@example.invalid", "a-long-test-password-1", bootstrap=True)
        with self.assertRaises(Denied) as e:
            self.svc.add_admin("b@example.invalid", "a-long-test-password-2", bootstrap=True)
        self.assertEqual(e.exception.code, "ALREADY_BOOTSTRAPPED")
        code = pyotp.TOTP(a["totp_secret"]).at(self.clock.now())
        with self.assertRaises(Denied):
            self.svc.login("a@example.invalid", "a-long-test-password-1", "000000")
        out = self.svc.login("a@example.invalid", "a-long-test-password-1", code)
        me = self.svc.auth(out["sid"])
        self.assertEqual(me["role"], "ADMIN")
        rc = a["recovery_codes"][0]
        self.svc.login("a@example.invalid", "a-long-test-password-1", rc)
        with self.assertRaises(Denied):
            self.svc.login("a@example.invalid", "a-long-test-password-1", rc)            # single use
        v = self.svc.add_admin("v@example.invalid", "a-long-test-password-3", "VIEWER")
        vs = self.svc.login("v@example.invalid", "a-long-test-password-3", pyotp.TOTP(v["totp_secret"]).at(self.clock.now()))
        with self.assertRaises(Denied) as e:
            self.svc.create_license(self.svc.auth(vs["sid"]))
        self.assertEqual(e.exception.code, "FORBIDDEN_ROLE")
        self.svc.logout(out["sid"])
        with self.assertRaises(Denied):
            self.svc.auth(out["sid"])
        for _ in range(5):                                  # lockout after 5 failures
            with self.assertRaises(Denied):
                self.svc.login("v@example.invalid", "wrong-password-xxxx", "123456")
        with self.assertRaises(Denied):
            self.svc.login("v@example.invalid", "a-long-test-password-3", pyotp.TOTP(v["totp_secret"]).at(self.clock.now()))

    def test_10_audit_summary_customers(self):
        c = self.svc.create_customer(TEST_ADMIN, "Klient testowy", stats_allowed=True)
        lic = self.f.issue(customer_id=c["id"])
        s = self.svc.open_session(lic["key"], boot_id=BOOT, nonce=nonce(), telemetry_opt_in=True)
        self.svc.heartbeat(s["session_token"], boot_id=BOOT, telemetry={"winrate_net_pct": 40.0, "account_password": "x", "trades_closed": 5})
        tel = self.svc.telemetry()
        self.assertEqual(tel[0]["trades_closed"], 5)
        self.assertNotIn("account_password", tel[0])        # only whitelisted aggregate fields
        summ = self.svc.summary()
        self.assertEqual((summ["licenses_active"], summ["sessions_active"], summ["customers"]), (1, 1, 1))
        acts = {a["action"] for a in self.svc.list_audit()}
        self.assertTrue({"LICENSE_CREATE", "SESSION_OPEN", "CUSTOMER_CREATE"} <= acts)
        self.assertEqual(self.svc.list_customers()[0]["licenses_active"], 1)


class TestPersistenceAndAdminOps(unittest.TestCase):
    def test_17_records_and_revocations_survive_server_restart(self):
        clock = ControlledClock(T0)
        f = LicenseServerFixture(clock=clock, serve=False)
        try:
            c = f.svc.create_customer(TEST_ADMIN, "Klient B")
            lic = f.issue(note="trwała")
            f.svc.assign_license(TEST_ADMIN, lic["id"], c["id"])
            f.svc.set_max_sessions(TEST_ADMIN, lic["id"], 2)
            lic2 = f.issue()
            f.svc.revoke_license(TEST_ADMIN, lic2["id"], "test")
            from mqlicense.db import DB
            from mqlicense.service import LicenseService
            svc2 = LicenseService(f.settings, DB(f.settings.db_path), clock)      # "restart": new process objects, same database
            l1, l2 = svc2.get_license(lic["id"]), svc2.get_license(lic2["id"])
            self.assertEqual((l1["customer_id"], l1["max_sessions"], l1["expires_at"]), (c["id"], 2, T0 + 259200))
            self.assertEqual(l2["status"], "COFNIETA")
            with self.assertRaises(Denied):
                svc2.open_session(lic2["key"], boot_id=BOOT, nonce=nonce())
            self.assertEqual(len(svc2.list_licenses(q="trwała")), 1)
            self.assertEqual(len(svc2.list_licenses(limit=1, offset=1)), 1)          # pagination
            self.assertTrue(any(a["action"] == "LICENSE_REVOKE" for a in svc2.list_audit()))
        finally:
            f.close()


class TestLicenseHTTPAndClient(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.f = LicenseServerFixture(lease_seconds=6)

    @classmethod
    def tearDownClass(cls):
        cls.f.close()

    def test_11_http_client_flow_and_api_hardening(self):
        lic = self.f.issue()
        st, body, hdr = http("POST", self.f.url + "/api/v1/client/session?license_key=" + lic["key"], {})
        self.assertEqual((st, body["error"]), (400, "QUERY_NOT_ALLOWED"))        # secrets never in URLs
        self.assertEqual(hdr.get("x-frame-options") or hdr.get("X-Frame-Options"), "DENY")
        st, body, _ = http("POST", self.f.url + "/api/v1/client/session", {"license_key": lic["key"], "boot_id": BOOT, "nonce": nonce(), "extra": 1})
        self.assertEqual(st, 422)                                                  # strict request schema
        st, body, _ = http("POST", self.f.url + "/api/v1/admin/licenses", {}, {"Origin": self.f.url})
        self.assertEqual((st, body["error"]), (401, "NOT_AUTHENTICATED"))
        st, body, _ = http("POST", self.f.url + "/api/v1/admin/licenses", {}, {"Origin": "https://evil.example"})
        self.assertEqual((st, body["error"]), (403, "ORIGIN_NOT_ALLOWED"))
        st, body, _ = http("GET", self.f.url + "/api/v1/admin/summary")
        self.assertEqual(st, 401)
        st, page, _ = 200, urllib.request.urlopen(self.f.url + "/admin/", timeout=5).read().decode(), None
        self.assertIn("panel licencji", page)

    def test_12_admin_panel_api_with_csrf(self):
        a = self.f.svc.add_admin(f"adm{free_port()}@example.invalid", "a-long-test-password-9")
        import http.cookiejar
        jar = http.cookiejar.CookieJar()
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

        def call(method, path, body=None, csrf=None):
            h = {"Content-Type": "application/json", "Origin": self.f.url}
            if csrf:
                h["X-CSRF"] = csrf
            r = urllib.request.Request(self.f.url + path, data=json.dumps(body).encode() if body is not None else None, method=method, headers=h)
            try:
                with op.open(r, timeout=10) as resp:
                    return resp.status, json.loads(resp.read().decode())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read().decode())
        st, out = call("POST", "/api/v1/admin/login", {"email": a["email"], "password": "a-long-test-password-9", "code": pyotp.TOTP(a["totp_secret"]).now()})
        self.assertEqual(st, 200, out)
        self.assertTrue(any(c.name == "mql_admin" for c in jar))
        st, out2 = call("POST", "/api/v1/admin/licenses", {"note": "z panelu"})
        self.assertEqual((st, out2["error"]), (403, "CSRF_INVALID"))
        st, lic = call("POST", "/api/v1/admin/licenses", {"note": "z panelu"}, out["csrf"])
        self.assertEqual(st, 200)
        self.assertEqual(lic["expires_at"] - lic["created_at"], 259200)
        st, lst = call("GET", "/api/v1/admin/licenses")
        self.assertTrue(all("key" not in x and "key_hash" not in x for x in lst["licenses"]))  # key shown only once
        st, _ = call("POST", f"/api/v1/admin/licenses/{lic['id']}/revoke", {"reason": "test"}, out["csrf"])
        self.assertEqual(st, 200)

    def client(self, **kw):
        return LicenseClient(self.f.url, self.f.public_pem, client_version="test", **kw)

    def test_13_client_verifies_pinned_key_and_url(self):
        lic = self.f.issue()
        with self.assertRaises(LicenseError) as e:
            LicenseClient("http://licencje.example.com", self.f.public_pem)
        self.assertEqual(e.exception.code, "INSECURE_URL")
        from mqlicense import security as sec
        other = sec.gen_signing_key(self.f.dir / "other.pem")
        c = LicenseClient(self.f.url, other)
        with self.assertRaises(LicenseError) as e:
            c.open(lic["key"])                      # lease signed by a key other than the pinned one -> rejected
        self.assertEqual(e.exception.code, "LEASE_INVALID")
        self.assertFalse(c.lease_ok())
        self.assertNotIn(lic["key"], repr(c) + json.dumps(c.status()))

    def test_14_guard_lifecycle_revoke_and_lapse(self):
        self.assertFalse(LicenseGuard(None).ok())                       # deny by default
        self.assertFalse(licensed(object()))
        lic = self.f.issue()
        c = self.client()
        c.open(lic["key"])
        g = LicenseGuard(c)
        self.assertTrue(g.ok())
        events = []
        g.on_change = events.append
        g.start()
        time.sleep(3.5)
        self.assertTrue(g.ok())                                         # renewed (lease 6 s, renew every 3 s)
        self.f.svc.revoke_license(TEST_ADMIN, lic["id"], "test")
        t0 = time.monotonic()
        while g.ok() and time.monotonic() - t0 < 10:
            time.sleep(0.2)
        self.assertFalse(g.ok())
        self.assertLessEqual(time.monotonic() - t0, 7)                  # within one lease (<= 30 s in production)
        self.assertEqual(g.status()["reason"], "LICENSE_REVOKED")
        self.assertEqual(events[-1]["state"], "DENIED")
        # server unreachable: the lease is honoured only until its own exp, then blocked (no offline mode)
        lic2 = self.f.issue()
        c2 = self.client()
        c2.open(lic2["key"])
        c2.url = f"http://127.0.0.1:{free_port()}"
        g2 = LicenseGuard(c2)
        g2.start()
        self.assertTrue(g2.ok())
        time.sleep(6.5)
        self.assertFalse(g2.ok())
        self.assertEqual(g2.public_state(), "LEASE_LAPSED")
        g2._stop.set()

    def test_21_cli_new_license(self):
        envf = self.f.dir / "cli.env"
        envf.write_text(f"MQL_ENV=test\nMQL_DB_PATH={self.f.settings.db_path}\nMQL_SIGNING_KEY_FILE={self.f.settings.signing_key_file}\n"
                        f"MQL_KEY_PEPPER={self.f.settings.key_pepper}\nMQL_DATA_KEY={self.f.settings.data_key}\n", encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if not k.startswith("MQL_")}
        r = subprocess.run([sys.executable, "-m", "mqlicense", "--env-file", str(envf), "new-license", "--note", "z terminala"],
                           cwd=str(_env.ROOT / "server"), env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        key = next(w for w in r.stdout.split() if w.startswith("MQL72-"))
        c = self.client()
        st = c.open(key)                                                 # the printed key works for a client start
        self.assertTrue(c.lease_ok())
        self.assertLessEqual(st["license_seconds_left"], 259200)
        c.end()

    def test_18_replayed_lease_never_extends_access(self):
        lic = self.f.issue()
        c = self.client()
        c.open(lic["key"])
        old = c.lease_claims
        import jwt as _jwt
        old_lease = _jwt.encode(old, "x", algorithm="HS256")            # any token not signed by the pinned key
        with self.assertRaises(LicenseError):
            c._accept_lease(old_lease, c.mono())
        time.sleep(1.1)
        c.renew()
        newer = c.lease_claims
        self.assertGreater(newer["iat"], old["iat"])
        # replay of a genuine but OLDER signed lease (captured earlier) is rejected
        first = self.f.svc._lease({"id": newer["sub"], "expires_at": newer["lic_exp"], "max_sessions": 1},
                                  {"id": newer["sid"], "boot_id": c.boot_id}, int(old["iat"]))[0]
        with self.assertRaises(LicenseError) as e:
            c._accept_lease(first, c.mono())
        self.assertEqual(e.exception.code, "LEASE_INVALID")

    def test_15_prompt_reads_one_line_from_stdin(self):
        out = io.StringIO()
        self.assertEqual(prompt_key(stdin=io.StringIO("  MQL72-ABC  \nsecond\n"), stdout=out), "MQL72-ABC")
        self.assertNotIn("MQL72-ABC", out.getvalue())                   # never echoed


class TestStartRequiresLicense(unittest.TestCase):
    """masterquo_start (serve) without a valid pasted key does not start the protected program."""

    def _run(self, key: str | None, lic: LicenseServerFixture, extra_env: dict | None = None) -> subprocess.CompletedProcess:
        td = TempData()
        try:
            port = free_port()
            with open(os.path.join(td.dir, "config.json"), "w", encoding="utf-8") as f:
                json.dump({"server": {"port": port, "open_browser": False}, "news": {"enabled": False}, "clock": {"reference_url": None},
                           **lic.client_config()}, f)
            env = dict(os.environ, MASTERQUO_DATA_DIR=td.dir, PYTHONPATH=str(_env.ROOT / "backend"), **(extra_env or {}))
            env.pop("ANTHROPIC_API_KEY", None)
            return subprocess.run([sys.executable, "-m", "masterquo", "serve", "--demo", "--no-browser"], env=env, cwd=str(_env.ROOT / "backend"),
                                  input=(key + "\n") if key is not None else "", capture_output=True, text=True, timeout=60)
        finally:
            td.close()

    def test_19_every_start_asks_again_expiry_unchanged(self):
        """Two consecutive runs with the same license: each run needs the pasted key (no key -> refused), the license
        expiry stays the same (72 h from generation, never from start)."""
        lic = LicenseServerFixture()
        td = TempData()
        try:
            info = lic.issue()
            port = free_port()
            with open(os.path.join(td.dir, "config.json"), "w", encoding="utf-8") as f:
                json.dump({"server": {"port": port, "open_browser": False}, "news": {"enabled": False}, "clock": {"reference_url": None},
                           **lic.client_config()}, f)
            env = dict(os.environ, MASTERQUO_DATA_DIR=td.dir, PYTHONPATH=str(_env.ROOT / "backend"))
            env.pop("ANTHROPIC_API_KEY", None)
            for run in range(2):
                p = subprocess.Popen([sys.executable, "-m", "masterquo", "serve", "--demo", "--no-browser"], env=env, cwd=str(_env.ROOT / "backend"),
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                p.stdin.write(info["key"] + "\n")
                p.stdin.close()
                ok = False
                for _ in range(120):
                    try:
                        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/health", timeout=1) as r:
                            ok = r.status == 200
                            break
                    except OSError:
                        time.sleep(0.5)
                self.assertTrue(ok, f"run {run} did not start")
                self.assertEqual(lic.svc.get_license(info["id"])["expires_at"], info["expires_at"])
                self.assertEqual(lic.svc.get_license(info["id"])["active_sessions"], 1)
                subprocess.run([sys.executable, "-m", "masterquo", "stop"], env=env, cwd=str(_env.ROOT / "backend"), timeout=60)
                out = p.communicate(timeout=60)[0]
                self.assertIn("Wklej licencję", out)                          # asked on THIS run
                self.assertNotIn(info["key"], out)
                self.assertEqual(lic.svc.get_license(info["id"])["active_sessions"], 0)   # clean exit frees the slot
            r = subprocess.run([sys.executable, "-m", "masterquo", "serve", "--demo", "--no-browser"], env=env, cwd=str(_env.ROOT / "backend"),
                               input="", capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 5)                                 # nothing remembered from the previous runs
        finally:
            td.close()
            lic.close()

    def test_20_runtime_without_launcher_license_stays_blocked(self):
        """Starting the engine/workers directly (bypassing masterquo_start) gives no analysis, no signals, no orders."""
        td = TempData()
        try:
            from masterquo.runtime import Runtime
            rt = Runtime(demo=True)
            self.assertFalse(rt.license.ok())
            self.assertFalse(licensed(rt.engine) or licensed(rt.scanner) or licensed(rt.gateway) or licensed(rt.agent) or licensed(rt.ml))
            rt.start()
            try:
                time.sleep(6)
                self.assertIsNone(rt.engine.decision)
                self.assertEqual(rt.engine.last_error, "LICENSE_REQUIRED")
                self.assertEqual(rt.gateway.execute("D-any")["reason"], "LICENSE_REQUIRED")
                self.assertIsNone(rt.agent.request("TEST", snapshot_id=None, setup_id=None, setup_state=None))
            finally:
                rt.stop()
        finally:
            td.close()

    def test_16_wrong_expired_or_missing_key_refused(self):
        clock = ControlledClock(time.time())
        lic = LicenseServerFixture(clock=clock)
        try:
            r = self._run("", lic)
            self.assertEqual(r.returncode, 5)
            from mqlicense import security as sec
            r = self._run(sec.license_key() + "\n" + sec.license_key() + "\n" + sec.license_key(), lic)
            self.assertEqual(r.returncode, 5)
            self.assertIn("LICENSE_INVALID", r.stderr)
            good = lic.issue()
            r = self._run("", lic, {"MASTERQUO_LICENSE_KEY": good["key"], "LICENSE_KEY": good["key"]})   # env is never a key source
            self.assertEqual(r.returncode, 5)
            info = lic.issue()
            clock.advance(259200)
            r = self._run(info["key"], lic)
            self.assertEqual(r.returncode, 5)
            self.assertIn("LICENSE_EXPIRED", r.stderr)
            self.assertNotIn(info["key"], r.stdout + r.stderr)          # the key is never echoed or logged
        finally:
            lic.close()


if __name__ == "__main__":
    unittest.main()
