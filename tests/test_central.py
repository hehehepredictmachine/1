"""Central server: accounts, roles, licenses 48 h, devices, leases, operation tokens, telemetry, win ratio, audit.

Runs on SQLite (dev) and - when reachable - on a real PostgreSQL (MQ_TEST_PG_URL, default local test DB).
All time-dependent checks use a controlled server clock (no waiting 48 hours). Data here is TEST FIXTURES, not clients.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

import _env

sys.path.insert(0, str(_env.ROOT / "server"))

try:
    import pyotp
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from fastapi.testclient import TestClient
    HAVE = True
except ImportError:  # pragma: no cover
    HAVE = False

PG_URL = os.environ.get("MQ_TEST_PG_URL", "postgresql://mqtest:mqtest@127.0.0.1/mqcentral_test")
T0 = 1_900_000_000
ORIGIN = "http://testserver"
PW = "zielona-zaba-tanczy-77"


def pg_available() -> bool:
    try:
        import psycopg
        psycopg.connect(PG_URL, connect_timeout=3).close()
        return True
    except Exception:
        return False


class World:
    """Central server in-process with a controlled clock."""

    def __init__(self, url: str):
        from mqcentral import config
        from mqcentral import security as sec
        from mqcentral.api import create_app
        from mqcentral.clock import ControlledClock
        from mqcentral.db import Database
        from mqcentral.service import Central
        self.dir = Path(tempfile.mkdtemp(prefix="mqc_"))
        sec.gen_signing_key(self.dir / "k.pem")
        if url == "sqlite":
            url = f"sqlite:///{self.dir}/c.sqlite"
        self.s = config.Settings(env="dev", database_url=url, public_url=ORIGIN, allowed_origins=[ORIGIN], signing_key_file=str(self.dir / "k.pem"),
                                 data_key=Fernet.generate_key().decode(), mail_mode="dev-outbox", secure_cookies=False, admin_web_dir=str(self.dir))
        self.db = Database(url)
        if self.db.pg:
            self.db.x("DROP SCHEMA public CASCADE")
            self.db.x("CREATE SCHEMA public")
        self.db.migrate()
        self.clock = ControlledClock(T0)
        self.c = Central(self.s, self.db, self.clock)
        self.app = create_app(self.c)
        boot = self.c.bootstrap_admin("boss@example.com", PW)
        self.totp = pyotp.TOTP(boot["totp_secret"])
        self.recovery = boot["recovery_codes"]

    # ---------------------------------------------------------------- clients
    def web(self) -> TestClient:
        return TestClient(self.app, base_url=ORIGIN, headers={"Origin": ORIGIN})

    def admin(self) -> tuple[TestClient, str]:
        w = self.web()
        r = w.post("/api/v1/auth/login", json={"email": "boss@example.com", "password": PW})
        assert r.status_code == 200, r.text
        assert r.json()["mfa_required"]
        r = w.post("/api/v1/auth/mfa", json={"code": self.totp.at(self.clock.t)})
        assert r.status_code == 200, r.text
        return w, r.json()["csrf"]

    def last_mail_token(self, to: str) -> str:
        """The (single) still-unused token sent to this address (mails of the same second have no order)."""
        import hashlib
        for m in self.db.q("SELECT body FROM mail_outbox WHERE to_addr=?", (to,)):
            if "#token=" not in m["body"]:
                continue
            tok = m["body"].split("#token=")[1].split()[0]
            r = self.db.one("SELECT used_at FROM user_tokens WHERE token_hash=?", (hashlib.sha256(tok.encode()).hexdigest(),))
            if r and r["used_at"] is None:
                return tok
        raise AssertionError("no unused token mailed to " + to)

    def user(self, email: str, pw: str = "haslo-uzytkownika-1") -> str:
        w = self.web()
        assert w.post("/api/v1/auth/register", json={"email": email, "password": pw}).status_code == 202
        assert w.post("/api/v1/auth/verify-email", json={"token": self.last_mail_token(email)}).status_code == 200
        return self.db.one("SELECT id FROM users WHERE email=?", (email,))["id"]

    def bot_login(self, email: str, pw: str = "haslo-uzytkownika-1") -> str:
        r = self.web().post("/api/v1/auth/login", json={"email": email, "password": pw, "client": "bot"})
        assert r.status_code == 200, r.text
        return r.json()["token"]

    def license(self, uid: str) -> str:
        w, csrf = self.admin()
        r = w.post("/api/v1/admin/licenses", json={"user_id": uid, "note": "test"}, headers={"X-CSRF": csrf})
        assert r.status_code == 200, r.text
        return r.json()["key"]


class Device:
    def __init__(self, world: World, token: str, install: str = "inst-1"):
        self.w, self.token, self.install = world, token, install
        self.priv = Ed25519PrivateKey.generate()
        from mqcentral.security import public_pem
        self.pem = public_pem(self.priv.public_key())
        self.client = TestClient(world.app, base_url=ORIGIN)
        self.device_id = None

    def activate(self, key: str):
        from mqcentral.security import device_message, key_hash
        h = {"Authorization": f"Bearer {self.token}"}
        ch = self.client.post("/api/v1/device/challenge", json={"purpose": "ACTIVATE"}, headers=h).json()
        sig = base64.b64encode(self.priv.sign(device_message("POST", "/api/v1/licenses/activate", ch["nonce"], (key_hash(key) + "|" + self.install).encode()))).decode()
        r = self.client.post("/api/v1/licenses/activate", json={"key": key, "public_key": self.pem, "install_id": self.install, "nonce": ch["nonce"],
                                                                "signature": sig}, headers=h)
        if r.status_code == 200:
            self.device_id = r.json()["device_id"]
        return r

    def call(self, path: str, body=None, method="POST", nonce_override=None, sign_body=None):
        from mqcentral.security import device_message
        ch = self.client.post("/api/v1/device/challenge", json={"purpose": "DEVICE", "device_id": self.device_id}).json()
        n = nonce_override or ch["nonce"]
        raw = b"" if body is None else json.dumps(body).encode()
        sig = base64.b64encode(self.priv.sign(device_message(method, path, n, sign_body if sign_body is not None else raw))).decode()
        return self.client.request(method, path, content=raw if method != "GET" else None,
                                   headers={"X-MQ-Device": self.device_id, "X-MQ-Nonce": n, "X-MQ-Sig": sig, "Content-Type": "application/json"})


@unittest.skipUnless(HAVE, "server dependencies not installed")
class CentralTests:
    URL = "sqlite"

    def setUp(self):
        self.w = World(self.URL)

    def tearDown(self):
        self.w.db.close()

    # ================================================================ 1. accounts
    def test_01_register_verify_login_logout_reset_block(self):
        w = self.w
        web = w.web()
        r = web.post("/api/v1/auth/register", json={"email": "Ala@Example.com", "password": "haslo-uzytkownika-1"})
        self.assertEqual(r.status_code, 202)
        same = web.post("/api/v1/auth/register", json={"email": "ala@example.com", "password": "inne-haslo-12345"})
        self.assertEqual((same.status_code, same.json()["message"]), (202, r.json()["message"]))    # no enumeration
        self.assertEqual(web.post("/api/v1/auth/login", json={"email": "ala@example.com", "password": "haslo-uzytkownika-1"}).json()["error"], "EMAIL_NOT_VERIFIED")
        tok = next(m["body"] for m in w.db.q("SELECT subject, body FROM mail_outbox") if "potwierd" in m["subject"]).split("#token=")[1].split()[0]
        self.assertEqual(web.post("/api/v1/auth/verify-email", json={"token": tok}).status_code, 200)
        self.assertEqual(web.post("/api/v1/auth/verify-email", json={"token": tok}).json()["error"], "TOKEN_INVALID_OR_EXPIRED")   # single use
        u = w.db.one("SELECT * FROM users WHERE email='ala@example.com'")
        self.assertTrue(u["password_hash"].startswith("$argon2id$"))
        self.assertNotIn("haslo-uzytkownika-1", json.dumps(w.db.q("SELECT * FROM users")))
        r = web.post("/api/v1/auth/login", json={"email": "ala@example.com", "password": "zle-haslo-1234"})
        self.assertEqual(r.json()["error"], "INVALID_CREDENTIALS")
        r2 = web.post("/api/v1/auth/login", json={"email": "nikt@example.com", "password": "zle-haslo-1234"})
        self.assertEqual(r2.json()["error"], r.json()["error"])                                     # same answer for unknown account
        r = web.post("/api/v1/auth/login", json={"email": "ala@example.com", "password": "haslo-uzytkownika-1"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("httponly", r.headers["set-cookie"].lower())
        self.assertIn("samesite=strict", r.headers["set-cookie"].lower())
        csrf = r.json()["csrf"]
        self.assertEqual(web.get("/api/v1/me").status_code, 200)
        self.assertEqual(web.post("/api/v1/auth/password/change", json={"current_password": "haslo-uzytkownika-1", "new_password": "nowe-haslo-12345"}).json()["error"],
                         "CSRF_INVALID")
        # reset password: always 202, single-use token, revokes sessions
        self.assertEqual(web.post("/api/v1/auth/password/forgot", json={"email": "nikt@example.com"}).status_code, 202)
        web.post("/api/v1/auth/password/forgot", json={"email": "ala@example.com"})
        rt = w.last_mail_token("ala@example.com")
        self.assertEqual(web.post("/api/v1/auth/password/reset", json={"token": rt, "new_password": "nowe-haslo-12345"}).status_code, 200)
        self.assertEqual(web.get("/api/v1/me").status_code, 401)                                    # session revoked
        w.clock.advance(3601)
        self.assertEqual(web.post("/api/v1/auth/password/reset", json={"token": rt, "new_password": "kolejne-haslo-123"}).status_code, 400)
        # block: sessions die immediately, login refused
        tok_bot = w.bot_login("ala@example.com", "nowe-haslo-12345")
        a, ac = w.admin()
        self.assertEqual(a.post(f"/api/v1/admin/users/{u['id']}/block", json={"reason": "test"}, headers={"X-CSRF": ac}).status_code, 200)
        self.assertIn(TestClient(w.app).get("/api/v1/me", headers={"Authorization": f"Bearer {tok_bot}"}).status_code, (401, 403))   # sessions revoked
        self.assertEqual(web.post("/api/v1/auth/login", json={"email": "ala@example.com", "password": "nowe-haslo-12345"}).json()["error"], "ACCOUNT_BLOCKED")
        del csrf

    def test_01b_rate_limit_login(self):
        web = self.w.web()
        codes = [web.post("/api/v1/auth/login", json={"email": "x@example.com", "password": "zle-haslo-1234"}).status_code for _ in range(10)]
        self.assertIn(429, codes)

    # ================================================================ 2. no escalation, isolation
    def test_02_no_escalation_and_isolation(self):
        w = self.w
        web = w.web()
        r = web.post("/api/v1/auth/register", json={"email": "evil@example.com", "password": "haslo-uzytkownika-1", "role": "ADMIN"})
        self.assertEqual(r.status_code, 422)                                                        # unknown field rejected
        self.assertIsNone(w.db.one("SELECT 1 AS x FROM users WHERE email='evil@example.com'"))
        a_id, b_id = w.user("a@example.com"), w.user("b@example.com")
        ta, tb = w.bot_login("a@example.com"), w.bot_login("b@example.com")
        key_b = w.license(b_id)
        db_ = Device(w, tb)
        self.assertEqual(db_.activate(key_b).status_code, 200)
        acc = db_.call("/api/v1/connector/link", {"server": "Broker-Demo", "login": "123", "trade_mode": "DEMO", "currency": "USD", "consent": True}).json()
        ca = TestClient(w.app, headers={"Authorization": f"Bearer {ta}"})
        self.assertEqual(ca.get(f"/api/v1/me/stats?account_id={acc['account_id']}").status_code, 404)        # foreign account
        self.assertEqual(ca.get(f"/api/v1/admin/users/{b_id}").status_code, 401)                           # bearer is not admin web session
        ua = w.web()
        ua.post("/api/v1/auth/login", json={"email": "a@example.com", "password": "haslo-uzytkownika-1"})
        for path in ("/api/v1/admin/users", f"/api/v1/admin/users/{b_id}", "/api/v1/admin/licenses", "/api/v1/admin/audit"):
            self.assertEqual(ua.get(path).status_code, 403, path)
        me = ca.get("/api/v1/me").json()
        self.assertEqual(me["user"]["id"], a_id)
        self.assertEqual(me["licenses"], [])
        # A cannot use B's license key (bound to user_id)
        self.assertEqual(Device(w, ta, "inst-a").activate(key_b).json()["error"], "LICENSE_NOT_FOUND_FOR_ACCOUNT")
        # A's device cannot send telemetry for B's account
        ka = w.license(a_id)
        da = Device(w, ta, "inst-a2")
        self.assertEqual(da.activate(ka).status_code, 200)
        r = da.call("/api/v1/telemetry/snapshot", {"account_id": acc["account_id"], "seq": 1, "measured_ms": T0 * 1000, "balance": 1, "equity": 1, "currency": "USD"})
        self.assertEqual(r.json()["error"], "ACCOUNT_NOT_LINKED_TO_DEVICE")
        # user_id smuggled in the body is rejected
        r = da.call("/api/v1/telemetry/snapshot", {"account_id": acc["account_id"], "user_id": b_id, "seq": 1, "measured_ms": T0 * 1000, "balance": 1, "equity": 1,
                                                   "currency": "USD"})
        self.assertEqual(r.status_code, 422)

    # ================================================================ 3. license generation
    def test_03_generate_only_admin_key_shown_once(self):
        w = self.w
        uid = w.user("c@example.com")
        web = w.web()
        web.post("/api/v1/auth/login", json={"email": "c@example.com", "password": "haslo-uzytkownika-1"})
        self.assertEqual(web.post("/api/v1/admin/licenses", json={"user_id": uid}).status_code, 403)
        a, csrf = w.admin()
        self.assertEqual(a.post("/api/v1/admin/licenses", json={"user_id": uid}).json()["error"], "CSRF_INVALID")
        r = a.post("/api/v1/admin/licenses", json={"user_id": uid, "note": "n"}, headers={"X-CSRF": csrf}).json()
        key = r["key"]
        self.assertTrue(key.startswith("MQL1-") and len(key.replace("-", "")) == 56)
        dump = json.dumps(w.db.q("SELECT * FROM licenses")) + json.dumps(w.db.q("SELECT * FROM audit_events"))
        self.assertNotIn(key, dump)
        self.assertNotIn(key.replace("-", ""), dump)
        lst = a.get("/api/v1/admin/licenses").text + a.get(f"/api/v1/admin/users/{uid}").text
        self.assertNotIn(key, lst)
        self.assertEqual(r["license"]["status"], "ISSUED")
        self.assertIsNone(r["license"]["activated_at"])
        keys = {w.c.generate_license({"id": "x", "role": "ADMIN"}, uid, None, "")["key"] for _ in range(50)}
        self.assertEqual(len(keys), 50)

    # ================================================================ 4. activation & seat
    def test_04_owner_activates_other_rejected_one_seat(self):
        w = self.w
        uid = w.user("d@example.com")
        key = w.license(uid)
        t = w.bot_login("d@example.com")
        d1 = Device(w, t, "inst-1")
        r = d1.activate(key)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["license"]["expires_at"] - r.json()["license"]["activated_at"], 172800)
        d2 = Device(w, t, "inst-2")
        self.assertEqual(d2.activate(key).json()["error"], "SEAT_IN_USE")
        # several monitor tabs = same installation, heartbeats from the same device keep working
        for _ in range(3):
            self.assertEqual(d1.call("/api/v1/device/heartbeat", {}).status_code, 200)
        # wrong key / garbage
        self.assertEqual(d1.activate("MQL1-AAAAA-BBBBB").json()["error"], "LICENSE_NOT_FOUND_FOR_ACCOUNT")

    # ================================================================ 5. exact 48 h boundary
    def test_05_boundary(self):
        w = self.w
        uid = w.user("e@example.com")
        key = w.license(uid)
        w.clock.advance(5 * 86400)                                          # generation/assignment do not start the clock
        d = Device(w, w.bot_login("e@example.com"))
        lic = d.activate(key).json()["license"]
        self.assertEqual(lic["activated_at"], T0 + 5 * 86400)
        exp = lic["expires_at"]
        w.clock.t = exp - 1
        r = d.call("/api/v1/device/heartbeat", {})
        self.assertEqual(r.status_code, 200)
        import jwt
        c = jwt.decode(r.json()["lease"], options={"verify_signature": False})
        self.assertLessEqual(c["exp"], exp)                                 # lease never beyond expires_at
        self.assertEqual(c["exp"] - c["iat"], 1)
        w.clock.t = exp
        self.assertEqual(d.call("/api/v1/device/heartbeat", {}).json()["error"], "LICENSE_EXPIRED")
        w.clock.t = exp + 3600
        self.assertEqual(d.call("/api/v1/device/heartbeat", {}).json()["error"], "LICENSE_EXPIRED")
        self.assertEqual(d.call("/api/v1/ops/authorize", {"intent_id": "x", "op": "OPEN"}).json()["error"], "LICENSE_EXPIRED")
        self.assertEqual(w.c.sweep_expired(), 1)
        self.assertEqual(w.db.one("SELECT status FROM licenses")["status"], "EXPIRED")

    # ================================================================ 6. concurrency, retry, reinstall, seat reset, restart
    def test_06_concurrent_first_activation_and_no_reset(self):
        w = self.w
        uid = w.user("f@example.com")
        key = w.license(uid)
        t = w.bot_login("f@example.com")
        devs = [Device(w, t, f"inst-{i}") for i in range(6)]
        res = [None] * 6

        def go(i):
            res[i] = devs[i].activate(key)
        ths = [threading.Thread(target=go, args=(i,)) for i in range(6)]
        [x.start() for x in ths]
        [x.join() for x in ths]
        ok = [r for r in res if r.status_code == 200]
        self.assertEqual(len(ok), 1, [r.text for r in res])
        self.assertEqual(w.db.one("SELECT COUNT(*) AS n FROM license_activations WHERE released_at IS NULL")["n"], 1)
        winner = devs[[r.status_code for r in res].index(200)]
        exp = ok[0].json()["license"]["expires_at"]
        w.clock.advance(3600)
        again = winner.activate(key)                                        # retry / reinstall with the same credential: idempotent
        self.assertEqual((again.status_code, again.json()["license"]["expires_at"]), (200, exp))
        # seat reset by the admin: new computer may activate, but ONLY until the original expiry
        a, csrf = w.admin()
        act = w.db.one("SELECT id FROM license_activations WHERE released_at IS NULL")["id"]
        self.assertEqual(a.post(f"/api/v1/admin/activations/{act}/release", json={"reason": "nowy PC"}, headers={"X-CSRF": csrf}).status_code, 200)
        self.assertEqual(winner.call("/api/v1/device/heartbeat", {}).json()["error"], "DEVICE_REVOKED")
        newpc = Device(w, t, "inst-new")
        r = newpc.activate(key)
        self.assertEqual((r.status_code, r.json()["license"]["expires_at"]), (200, exp))
        # "server restart": new service instance over the same DB keeps the dates
        from mqcentral.service import Central
        c2 = Central(w.s, w.db, w.clock)
        self.assertEqual(c2.license_view(w.db.one("SELECT * FROM licenses"))["expires_at"], exp)
        # password change / logout do not touch license dates
        w.web().post("/api/v1/auth/logout")
        self.assertEqual(w.db.one("SELECT expires_at FROM licenses")["expires_at"], exp)

    # ================================================================ 8. forged leases, replay, revocation, op tokens
    def test_08_signatures_replay_revocation_op_tokens(self):
        w = self.w
        uid = w.user("g@example.com")
        key = w.license(uid)
        d = Device(w, w.bot_login("g@example.com"))
        d.activate(key)
        # nonce replay
        ch = d.client.post("/api/v1/device/challenge", json={"purpose": "DEVICE", "device_id": d.device_id}).json()["nonce"]
        self.assertEqual(d.call("/api/v1/device/heartbeat", {}, nonce_override=ch).status_code, 200)
        self.assertEqual(d.call("/api/v1/device/heartbeat", {}, nonce_override=ch).json()["error"], "NONCE_INVALID_OR_REPLAYED")
        # knowing the device_id is not enough: signature of another key
        other = Device(w, "x")
        other.device_id = d.device_id
        self.assertEqual(other.call("/api/v1/device/heartbeat", {}).json()["error"], "DEVICE_SIGNATURE_INVALID")
        # body tampering
        self.assertEqual(d.call("/api/v1/ops/authorize", {"intent_id": "A", "op": "OPEN"}, sign_body=b"{}").json()["error"], "DEVICE_SIGNATURE_INVALID")
        # operation tokens: single use per intent
        r = d.call("/api/v1/ops/authorize", {"intent_id": "AUTO_DEMO:acc:S1", "op": "OPEN", "symbol": "XAUUSD-", "side": "BUY", "volume": 0.01})
        self.assertEqual(r.status_code, 200, r.text)
        import jwt
        c = jwt.decode(r.json()["op_token"], options={"verify_signature": False})
        self.assertLessEqual(c["exp"] - c["iat"], 20)
        self.assertEqual(c["aud"], "masterquo-bot-op")
        self.assertEqual(d.call("/api/v1/ops/authorize", {"intent_id": "AUTO_DEMO:acc:S1", "op": "OPEN"}).json()["error"], "INTENT_ALREADY_AUTHORIZED")
        # forged lease: signed with a foreign key -> the client verification must fail (checked in client tests); here: server key id
        self.assertEqual(jwt.get_unverified_header(d.call("/api/v1/device/heartbeat", {}).json()["lease"])["alg"], "EdDSA")
        # revocation works immediately on the central API
        a, csrf = w.admin()
        lid = w.db.one("SELECT id FROM licenses")["id"]
        a.post(f"/api/v1/admin/licenses/{lid}/revoke", json={"reason": "test"}, headers={"X-CSRF": csrf})
        self.assertEqual(d.call("/api/v1/device/heartbeat", {}).json()["error"], "LICENSE_REVOKED")
        self.assertEqual(d.call("/api/v1/ops/authorize", {"intent_id": "B", "op": "OPEN"}).json()["error"], "LICENSE_REVOKED")
        # a new license restores access without reinstall
        key2 = w.license(uid)
        self.assertEqual(d.activate(key2).status_code, 200)
        self.assertEqual(d.call("/api/v1/device/heartbeat", {}).status_code, 200)
        # audit contains the actions, without secrets
        acts = [e["action"] for e in w.db.q("SELECT action FROM audit_events")]
        for x in ("LICENSE_GENERATED", "LICENSE_ACTIVATED", "LICENSE_REVOKED"):
            self.assertIn(x, acts)
        self.assertNotIn(key2, json.dumps(w.db.q("SELECT * FROM audit_events")))

    def test_08b_clock_anomaly_blocks_new_rights(self):
        w = self.w
        uid = w.user("h@example.com")
        key = w.license(uid)
        d = Device(w, w.bot_login("h@example.com"))
        d.activate(key)
        w.clock.anomaly = "TEST_ANOMALY"
        self.assertEqual(d.call("/api/v1/device/heartbeat", {}).json()["error"], "SERVER_CLOCK_ANOMALY")
        w.clock.anomaly = None
        self.assertEqual(d.call("/api/v1/device/heartbeat", {}).status_code, 200)

    def test_08c_admin_mfa_required_and_recovery_code(self):
        w = self.w
        web = w.web()
        r = web.post("/api/v1/auth/login", json={"email": "boss@example.com", "password": PW})
        self.assertTrue(r.json()["mfa_required"])
        self.assertEqual(web.get("/api/v1/admin/users").status_code, 401)      # password alone is not enough
        self.assertEqual(web.post("/api/v1/auth/mfa", json={"code": "000000"}).json()["error"], "MFA_INVALID")
        r = web.post("/api/v1/auth/mfa", json={"code": w.recovery[0]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(web.get("/api/v1/admin/users").status_code, 200)
        self.assertNotIn(w.recovery[0], json.dumps(w.db.q("SELECT * FROM recovery_codes")))
        web2 = w.web()
        web2.post("/api/v1/auth/login", json={"email": "boss@example.com", "password": PW})
        self.assertEqual(web2.post("/api/v1/auth/mfa", json={"code": w.recovery[0]}).json()["error"], "MFA_INVALID")   # single use
        self.assertEqual(w.web().post("/api/v1/auth/login", json={"email": "boss@example.com", "password": PW},
                                      headers={"Origin": "http://evil.example"}).json()["error"], "ORIGIN_NOT_ALLOWED")

    # ================================================================ 11/13. telemetry
    def test_11_13_snapshots_deals_dedupe_account_switch(self):
        w = self.w
        uid = w.user("i@example.com")
        key = w.license(uid)
        d = Device(w, w.bot_login("i@example.com"))
        d.activate(key)
        self.assertEqual(d.call("/api/v1/connector/link", {"server": "B", "login": "1", "trade_mode": "DEMO", "currency": "USD", "consent": False}).json()["error"],
                         "CONSENT_REQUIRED")
        acc = d.call("/api/v1/connector/link", {"server": "Broker-Demo", "login": "5550001", "trade_mode": "DEMO", "currency": "USD", "currency_digits": 2,
                                                "bot_magic": 777, "consent": True}).json()["account_id"]
        a, csrf = w.admin()
        row = a.get(f"/api/v1/admin/users/{uid}").json()["accounts"][0]
        self.assertIsNone(row["balance"])                                   # no data yet: None, never 0
        ms = T0 * 1000
        s1 = d.call("/api/v1/telemetry/snapshot", {"account_id": acc, "seq": ms, "measured_ms": ms, "balance": 10000.5, "equity": 9990.25, "currency": "USD"})
        self.assertTrue(s1.json()["accepted"])
        old = d.call("/api/v1/telemetry/snapshot", {"account_id": acc, "seq": ms - 5000, "measured_ms": ms - 5000, "balance": 1.0, "equity": 1.0, "currency": "USD"})
        self.assertTrue(old.json()["stale"])
        dup = d.call("/api/v1/telemetry/snapshot", {"account_id": acc, "seq": ms, "measured_ms": ms, "balance": 2.0, "equity": 2.0, "currency": "USD"})
        self.assertTrue(dup.json()["duplicate"])
        row = a.get(f"/api/v1/admin/users/{uid}").json()["accounts"][0]
        self.assertEqual((row["balance"], row["equity"], row["currency"]), (10000.5, 9990.25, "USD"))
        self.assertEqual(d.call("/api/v1/telemetry/snapshot", {"account_id": acc, "seq": ms + 1, "measured_ms": ms + 1, "balance": 1, "equity": 1,
                                                                "currency": "EUR"}).json()["error"], "CURRENCY_MISMATCH")
        w.clock.advance(600)
        row = a.get(f"/api/v1/admin/users/{uid}").json()["accounts"][0]
        self.assertFalse(row["data_fresh"])                                 # old reading is marked, kept, not zeroed
        self.assertEqual(row["balance"], 10000.5)
        deals = [{"ticket": 1, "position_id": 10, "time_ms": ms, "type": 0, "entry": 0, "volume": 1, "profit": 0, "commission": -2, "swap": 0, "fee": 0, "symbol": "XAUUSD-", "magic": 777},
                 {"ticket": 2, "position_id": 10, "time_ms": ms + 1000, "type": 1, "entry": 1, "volume": 1, "profit": 50, "commission": -2, "swap": 0, "fee": 0, "symbol": "XAUUSD-", "magic": 777}]
        r1 = d.call("/api/v1/telemetry/deals", {"account_id": acc, "deals": deals, "import": {"from_ms": ms - 86400000, "to_ms": ms + 2000, "complete": False}}).json()
        r2 = d.call("/api/v1/telemetry/deals", {"account_id": acc, "deals": deals, "import": {"to_ms": ms + 2000, "complete": True}}).json()
        self.assertEqual((r1["accepted"], r2["accepted"], r2["duplicates"]), (2, 0, 2))      # resumed import, no double counting
        st = a.get(f"/api/v1/admin/accounts/{acc}/stats?range=all").json()
        self.assertEqual((st["wins"], st["losses"], st["win_ratio"]), (1, 0, 100.0))
        self.assertEqual(st["history_status"], "COMPLETE")
        # explicit account switch: new account, history not merged
        acc2 = d.call("/api/v1/connector/link", {"server": "Broker-Live", "login": "999", "trade_mode": "REAL", "currency": "EUR", "consent": True}).json()["account_id"]
        self.assertNotEqual(acc, acc2)
        st2 = a.get(f"/api/v1/admin/accounts/{acc2}/stats?range=all").json()
        self.assertEqual((st2["wins"], st2["losses"], st2["win_ratio"]), (0, 0, None))
        self.assertEqual(d.call("/api/v1/telemetry/snapshot", {"account_id": acc, "seq": ms + 9, "measured_ms": ms + 9, "balance": 1, "equity": 1,
                                                                "currency": "USD"}).json()["error"], "ACCOUNT_NOT_LINKED_TO_DEVICE")
        users = a.get("/api/v1/admin/users").json()
        r = next(x for x in users["items"] if x["user"]["id"] == uid)
        self.assertEqual(r["account"]["trade_mode"], "LIVE")

    def test_10_admin_list_search_sort_page(self):
        w = self.w
        for i in range(7):
            w.user(f"user{i}@example.com")
        a, _ = w.admin()
        p = a.get("/api/v1/admin/users?size=3&page=2&sort=email&dir=asc").json()
        self.assertEqual((p["total"], len(p["items"])), (8, 3))
        self.assertEqual([x["user"]["email"] for x in p["items"]], ["user2@example.com", "user3@example.com", "user4@example.com"])   # page 1: boss, user0, user1
        q = a.get("/api/v1/admin/users?q=user5").json()
        self.assertEqual([x["user"]["email"] for x in q["items"]], ["user5@example.com"])
        self.assertEqual(a.get("/api/v1/admin/users?sort=DROP").status_code, 400)
        n = a.get("/api/v1/admin/users?license=NONE").json()["total"]
        self.assertEqual(n, 8)

    def test_14_invite_sets_own_password_admin_never_knows_it(self):
        w = self.w
        a, csrf = w.admin()
        r = a.post("/api/v1/admin/users", json={"email": "inv@example.com"}, headers={"X-CSRF": csrf})
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(w.db.one("SELECT password_hash FROM users WHERE email='inv@example.com'")["password_hash"])
        tok = w.last_mail_token("inv@example.com")
        self.assertEqual(w.web().post("/api/v1/auth/password/reset", json={"token": tok, "new_password": "moje-wlasne-haslo-1"}).status_code, 200)
        self.assertEqual(w.web().post("/api/v1/auth/login", json={"email": "inv@example.com", "password": "moje-wlasne-haslo-1"}).status_code, 200)


class TestCentralSQLite(CentralTests, unittest.TestCase):
    URL = "sqlite"


@unittest.skipUnless(HAVE and pg_available(), "PostgreSQL test database not reachable (MQ_TEST_PG_URL)")
class TestCentralPostgres(CentralTests, unittest.TestCase):
    URL = PG_URL


# ================================================================ 12. win ratio reconstruction (pure)
class TestWinRatio(unittest.TestCase):
    def setUp(self):
        from mqcentral import stats
        self.st = stats

    def d(self, t, typ, entry, vol, profit=0.0, comm=0.0, swap=0.0, fee=0.0, pid=1, magic=7, ticket=None):
        self._n = getattr(self, "_n", 0) + 1
        return {"ticket": str(ticket or self._n), "position_id": str(pid), "time_ms": t, "type": typ, "entry": entry, "volume": vol, "profit": profit,
                "commission": comm, "swap": swap, "fee": fee, "symbol": "XAUUSD-", "magic": magic}

    def wr(self, deals, **kw):
        cyc = self.st.reconstruct(deals, 7)
        return self.st.win_ratio(cyc, deals, digits=2, since_ms=None, until_ms=None, **kw), cyc

    def test_profit_loss_neutral_costs(self):
        ds = [self.d(1, 0, 0, 1, comm=-3), self.d(2, 1, 1, 1, profit=10, comm=-3),           # +4 win
              self.d(3, 1, 0, 1, pid=2), self.d(4, 0, 1, 1, profit=5, comm=-6, pid=2),          # -1 loss (costs make it negative)
              self.d(5, 0, 0, 1, pid=3), self.d(6, 1, 1, 1, profit=0.004, pid=3)]               # neutral (|net| <= 0.005)
        r, _ = self.wr(ds)
        self.assertEqual((r["wins"], r["losses"], r["neutral"], r["win_ratio"]), (1, 1, 1, 50.0))

    def test_deposits_excluded_and_zero_denominator(self):
        ds = [self.d(1, 2, 0, 0, profit=1000, pid=0), self.d(2, 2, 0, 0, profit=-200, pid=0)]   # deposit/withdrawal
        r, _ = self.wr(ds)
        self.assertIsNone(r["win_ratio"])
        self.assertEqual(r["excluded_non_trade"], {"BALANCE": 2})

    def test_partial_close_is_one_cycle(self):
        ds = [self.d(1, 0, 0, 1.0), self.d(2, 1, 1, 0.5, profit=20), self.d(3, 1, 1, 0.5, profit=-30)]
        r, cyc = self.wr(ds)
        self.assertEqual(len(cyc), 1)
        self.assertEqual((r["wins"], r["losses"]), (0, 1))                  # net -10 for the whole cycle

    def test_netting_reversal_split(self):
        # long 1.0, then SELL 1.5 IN/OUT: closes 1.0 (profit 30) and opens short 0.5; commission split 1.0/1.5 vs 0.5/1.5
        ds = [self.d(1, 0, 0, 1.0, comm=-1), self.d(2, 1, 2, 1.5, profit=30, comm=-3), self.d(3, 0, 1, 0.5, profit=-4, comm=-1)]
        r, cyc = self.wr(ds)
        self.assertEqual(len(cyc), 2)
        first, second = cyc
        self.assertAlmostEqual(first["net"], 30 - 1 - 2, places=6)
        self.assertAlmostEqual(second["net"], -4 - 1 - 1, places=6)
        self.assertEqual(second["direction"], "SHORT")
        self.assertEqual((r["wins"], r["losses"]), (1, 1))

    def test_incomplete_history_and_open(self):
        ds = [self.d(1, 1, 1, 1.0, profit=5, pid=9), self.d(2, 0, 0, 1.0, pid=10)]          # exit without entry; still open
        r, _ = self.wr(ds)
        self.assertEqual((r["incomplete_cycles"], r["open_cycles"], r["win_ratio"]), (1, 1, None))
        self.assertFalse(r["complete"])

    def test_bot_scope_and_symbol_filter(self):
        ds = [self.d(1, 0, 0, 1, magic=7), self.d(2, 1, 1, 1, profit=5, magic=7),
              self.d(3, 0, 0, 1, pid=2, magic=0), self.d(4, 1, 1, 1, profit=-5, pid=2, magic=0)]
        r, _ = self.wr(ds, scope="BOT")
        self.assertEqual((r["wins"], r["losses"]), (1, 0))
        r, _ = self.wr(ds, symbol="EURUSD")
        self.assertEqual((r["wins"], r["losses"]), (0, 0))

    def test_unattributed_costs_flagged(self):
        ds = [self.d(1, 0, 0, 1), self.d(2, 1, 1, 1, profit=5), self.d(3, 8, 0, 0, profit=-1.5, pid=0)]   # daily commission
        r, _ = self.wr(ds)
        self.assertEqual(r["unattributed_costs"], -1.5)
        self.assertFalse(r["complete"])


if __name__ == "__main__":
    unittest.main()
