"""License API v1 (license_server/) over real HTTP (uvicorn in a thread, test clock): the server side of the acceptance plan.
Durations 24h / 72h / 7d / 31d, one-time key display + hashed storage, first activation and device binding, invalid key,
second device, repeated activation on the same device (token rotation), validation with a fresh signed assertion (nonce),
expiry on the test clock, revocation, admin device reset (rebind, expiry unchanged), unauthorized admin requests,
tampered / foreign assertions, rate limiting, concurrent activation, audit log without secrets, production config check."""
from __future__ import annotations

import json
import re
import socket
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import _env
from _env import TempData

ROOT = _env.ROOT
sys.path.insert(0, str(ROOT / "license_server"))

from pmw_license import protocol as P  # noqa: E402
from pmw_license.config import Settings  # noqa: E402
from pmw_license.security import RateLimiter, hash_password  # noqa: E402
from pmw_license.signing import Signer  # noqa: E402
from pmw_license.store import Store  # noqa: E402

PASSWORD = "very-secret-admin-pass-123"
HW1, HW2 = "a" * 64, "b" * 64


class Clock:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        return self.t


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    def __init__(self, tmp: Path, clock: Clock, rate_public: int = 1000, rate_login: int = 100):
        import uvicorn
        from pmw_license.app import create_app
        self.signer = Signer.generate()
        self.db_path = tmp / "licenses.db"
        self.settings = Settings(database=self.db_path, signing_key=tmp / "none.pem", key_pepper="p" * 48, admin_user="owner",
                                 admin_password_hash=hash_password(PASSWORD), env="development", rate_public_per_min=rate_public,
                                 rate_login_per_min=rate_login)
        self.app = create_app(self.settings, clock=clock, signer=self.signer, store=Store(self.db_path), limiter=RateLimiter())
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.server = uvicorn.Server(uvicorn.Config(self.app, host="127.0.0.1", port=self.port, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        for _ in range(200):
            if self.server.started:
                break
            time.sleep(0.05)

    def stop(self):
        self.server.should_exit = True
        self.thread.join(timeout=10)


def call(base, path, body=None, token=None, method=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method or ("POST" if data is not None else "GET"),
                                 headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


class TestLicenseServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = TempData()
        cls.clock = Clock()
        cls.srv = Server(Path(cls.td.dir), cls.clock)
        st, out = call(cls.srv.base, "/api/v1/admin/login", {"username": "owner", "password": PASSWORD})
        assert st == 200, out
        cls.admin = out["token"]

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()
        cls.td.close()

    def adm(self) -> str:
        """Admin session token; the test clock jumps days ahead, so an expired session is renewed by logging in again."""
        if call(self.srv.base, "/api/v1/admin/stats", token=type(self).admin)[0] == 401:
            type(self).admin = call(self.srv.base, "/api/v1/admin/login", {"username": "owner", "password": PASSWORD})[1]["token"]
        return type(self).admin

    def new_key(self, duration="31d"):
        st, out = call(self.srv.base, "/api/v1/admin/licenses", {"duration": duration}, self.adm())
        self.assertEqual(st, 200, out)
        return out

    def activate(self, key, hw=HW1, nonce=None):
        nonce = nonce or P.new_nonce()
        st, out = call(self.srv.base, "/api/v1/licenses/activate", {"license_key": key, "hwid_hash": hw, "nonce": nonce, "client_version": "1.27.0"})
        return st, out, nonce

    def validate(self, lic, token, hw=HW1, nonce=None):
        nonce = nonce or P.new_nonce()
        st, out = call(self.srv.base, "/api/v1/licenses/validate", {"license_id": lic, "hwid_hash": hw, "token": token, "nonce": nonce})
        return st, out, nonce

    # ------------------------------------------------------------------ tests
    def test_01_health_and_public_key(self):
        st, h = call(self.srv.base, "/health")
        self.assertEqual((st, h["status"]), (200, "ok"))
        st, pk = call(self.srv.base, "/api/v1/public-key")
        self.assertEqual((pk["alg"], pk["kid"]), ("Ed25519", self.srv.signer.kid))
        self.assertNotIn("PRIVATE", json.dumps(pk))

    def test_02_four_durations_and_one_time_key(self):
        for d in P.DURATIONS:
            lic = self.new_key(d)
            self.assertTrue(P.normalize_key(lic["license_key"]))
            self.assertEqual((lic["status"], lic["duration"], lic["device_bound"]), ("CREATED", d, False))
        listing = call(self.srv.base, "/api/v1/admin/licenses?limit=200", token=self.adm())[1]
        blob = json.dumps(listing)
        self.assertIsNone(re.search(r"PMW-[0-9A-Z]{5}-", blob))                              # no plaintext key in lists (hints only)
        self.assertNotIn("key_hash", blob)
        for d, secs in P.DURATIONS.items():
            lic = self.new_key(d)
            self.clock.t += 7
            st, out, _ = self.activate(lic["license_key"], hw=(d.encode().hex() * 64)[:64])
            self.assertEqual(st, 200, out)
            self.assertEqual(P.parse_utc(out["expires_at"]) - P.parse_utc(out["activated_at"]), secs)   # expiry from first activation
        raw = self.srv.db_path.read_bytes() + (Path(str(self.srv.db_path) + "-wal").read_bytes() if Path(str(self.srv.db_path) + "-wal").exists() else b"")
        self.assertNotIn(lic["license_key"].encode(), raw)                                   # only the hash is stored

    def test_03_activation_binding_mismatch_repeat_and_validation(self):
        lic = self.new_key("72h")
        st, out, nonce = self.activate("bad-key-0000")
        self.assertEqual((st, out["error"]["code"]), (403, P.INVALID_LICENSE))
        st, out, nonce = self.activate(lic["license_key"].lower().replace("-", " "))           # tolerant input
        self.assertEqual(st, 200, out)
        pl = P.verify_assertion(out["assertion"], self.srv.signer.public_raw, license_id=out["license_id"], hwid=HW1, nonce=nonce)
        self.assertEqual((pl["st"], pl["dur"]), ("ACTIVE", "72h"))
        lid, token1 = out["license_id"], out["token"]
        st, out2, _ = self.activate(lic["license_key"], hw=HW2)                                  # second device
        self.assertEqual((st, out2["error"]["code"]), (403, P.DEVICE_MISMATCH))
        st, ok, n2 = self.validate(lid, token1)
        self.assertEqual(st, 200, ok)
        P.verify_assertion(ok["assertion"], self.srv.signer.public_raw, license_id=lid, hwid=HW1, nonce=n2)
        st, again, _ = self.activate(lic["license_key"])                                         # same device again
        self.assertEqual(st, 200)
        self.assertEqual(again["expires_at"], out["expires_at"])                                 # the clock does not restart
        self.assertNotEqual(again["token"], token1)
        self.assertEqual(self.validate(lid, token1)[1]["error"]["code"], P.INVALID_LICENSE)      # old token rotated out
        self.assertEqual(self.validate(lid, again["token"], hw=HW2)[1]["error"]["code"], P.DEVICE_MISMATCH)
        self.assertEqual(self.validate(lid, again["token"])[0], 200)

    def test_04_expiry_on_test_clock(self):
        lic = self.new_key("24h")
        st, out, _ = self.activate(lic["license_key"])
        self.clock.t += 86_400 - 1
        self.assertEqual(self.validate(out["license_id"], out["token"])[0], 200)
        self.clock.t += 2
        st, e, _ = self.validate(out["license_id"], out["token"])
        self.assertEqual((st, e["error"]["code"]), (403, P.LICENSE_EXPIRED))
        self.assertEqual(self.activate(lic["license_key"])[1]["error"]["code"], P.LICENSE_EXPIRED)
        g = call(self.srv.base, f"/api/v1/admin/licenses/{out['license_id']}", token=self.adm())[1]
        self.assertEqual(g["status"], "EXPIRED")

    def test_05_revoke_and_reset_device(self):
        lic = self.new_key("7d")
        st, out, _ = self.activate(lic["license_key"])
        lid = out["license_id"]
        st, r = call(self.srv.base, f"/api/v1/admin/licenses/{lid}/reset-device", {"reason": "nowy komputer"}, self.adm())
        self.assertEqual((st, r["device_bound"]), (200, False))
        self.assertEqual(self.validate(lid, out["token"])[1]["error"]["code"], P.DEVICE_MISMATCH)   # old device no longer bound
        self.clock.t += 3600
        st, nb, n = self.activate(lic["license_key"], hw=HW2)                                     # next activation binds the new device
        self.assertEqual(st, 200, nb)
        self.assertEqual(nb["expires_at"], out["expires_at"])                                     # expiry unchanged by the reset
        self.assertEqual(self.activate(lic["license_key"], hw=HW1)[1]["error"]["code"], P.DEVICE_MISMATCH)
        st, rv = call(self.srv.base, f"/api/v1/admin/licenses/{lid}/revoke", {"reason": "test"}, self.adm())
        self.assertEqual(rv["status"], "REVOKED")
        self.assertEqual(self.validate(lid, nb["token"], hw=HW2)[1]["error"]["code"], P.LICENSE_REVOKED)
        self.assertEqual(self.activate(lic["license_key"], hw=HW2)[1]["error"]["code"], P.LICENSE_REVOKED)
        audit = call(self.srv.base, f"/api/v1/admin/audit?license_id={lid}", token=self.adm())[1]["items"]
        actions = {a["action"] for a in audit}
        self.assertTrue({"LICENSE_CREATED", "ACTIVATED_FIRST", "DEVICE_RESET", "ACTIVATED_REBOUND", "LICENSE_REVOKED"} <= actions, actions)
        self.assertNotIn(lic["license_key"], json.dumps(audit))
        self.assertNotIn(HW2, json.dumps(audit))                                                 # only short device prefixes

    def test_06_unauthorized_admin(self):
        for path, body in (("/api/v1/admin/licenses", {"duration": "31d"}), ("/api/v1/admin/stats", None)):
            self.assertEqual(call(self.srv.base, path, body)[0], 401)
            self.assertEqual(call(self.srv.base, path, body, token="x" * 43)[0], 401)
        st, e = call(self.srv.base, "/api/v1/admin/login", {"username": "owner", "password": "wrong-password-xx"})
        self.assertEqual((st, e["error"]["code"]), (401, P.UNAUTHORIZED))
        st, s = call(self.srv.base, "/api/v1/admin/stats", token=self.adm())
        self.assertEqual(st, 200)
        self.assertEqual(set(s["by_status"]), set(P.STATUSES))

    def test_07_tampered_and_foreign_assertions(self):
        lic = self.new_key("31d")
        st, out, nonce = self.activate(lic["license_key"], hw="c" * 64)
        tok = out["assertion"]
        body, sig = tok.split(".")
        pl = json.loads(P.b64u_dec(body))
        forged = P.b64u(P.canonical({**pl, "exp": "2099-01-01T00:00:00Z"})) + "." + sig        # changed expiry, old signature
        with self.assertRaises(P.AssertionError_):
            P.verify_assertion(forged, self.srv.signer.public_raw)
        other = Signer.generate()                                                                 # a fake server with its own key
        with self.assertRaises(P.AssertionError_):
            P.verify_assertion(other.assertion(pl), self.srv.signer.public_raw)
        with self.assertRaises(P.AssertionError_):
            P.verify_assertion(tok, self.srv.signer.public_raw, nonce=P.new_nonce())             # replayed answer, other nonce
        with self.assertRaises(P.AssertionError_):
            P.verify_assertion(tok, self.srv.signer.public_raw, hwid="d" * 64)
        with self.assertRaises(P.AssertionError_):
            P.verify_assertion("garbage", self.srv.signer.public_raw)
        self.assertEqual(P.verify_assertion(tok, self.srv.signer.public_raw, nonce=nonce)["lid"], out["license_id"])

    def test_08_bad_requests(self):
        st, e = call(self.srv.base, "/api/v1/licenses/activate", {"license_key": "PMW-AAAAA-AAAAA-AAAAA-AAAAA", "hwid_hash": "XYZ", "nonce": "short"})
        self.assertEqual((st, e["error"]["code"]), (400, P.INVALID_REQUEST))
        st, e = call(self.srv.base, "/api/v1/licenses/activate", {"license_key": "x" * 5000, "hwid_hash": HW1, "nonce": P.new_nonce()})
        self.assertIn(st, (400, 413))
        st, e = call(self.srv.base, "/api/v1/admin/licenses", {"duration": "1y"}, self.adm())
        self.assertEqual(st, 400)

    def test_09_concurrent_activation_binds_one_device(self):
        lic = self.new_key("31d")
        res = []
        ths = [threading.Thread(target=lambda h=h: res.append(self.activate(lic["license_key"], hw=h)[0])) for h in ("e" * 64, "f" * 64)]
        for t in ths:
            t.start()
        for t in ths:
            t.join()
        self.assertEqual(sorted(res), [200, 403])

    def test_10_rate_limit_and_production_config(self):
        td = TempData()
        try:
            srv = Server(Path(td.dir), Clock(), rate_public=6)                      # activation limit = 6 // 3 = 2 per minute
            codes = [call(srv.base, "/api/v1/licenses/activate", {"license_key": "PMW-AAAAA-AAAAA-AAAAA-AAAAA", "hwid_hash": HW1,
                                                                  "nonce": P.new_nonce()})[0] for _ in range(4)]
            srv.stop()
            self.assertEqual(codes, [403, 403, 429, 429])
        finally:
            td.close()
        from pmw_license.app import create_app
        with self.assertRaises(RuntimeError):
            create_app(Settings(database=Path(self.td.dir) / "x.db", signing_key=Path(self.td.dir) / "missing.pem", key_pepper="",
                                admin_user="", admin_password_hash="", env="production"))


if __name__ == "__main__":
    unittest.main()
