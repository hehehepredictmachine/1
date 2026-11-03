"""License System acceptance (1.29) over real HTTP: a License API server WITHOUT any admin password (device keys only), the OWNER
License Manager (no login screen, signed requests) and CLIENT LicenseGuards on separate data folders and device fingerprints.

Scenarios: pairing out-of-band, 72h / 7d / 31d keys, activation, OWNER restart without login, CLIENT restart, second device,
device reset without extending the period, expiry on the server's test clock, revocation, no network (no grace period), forged
assertion and forged admin signature, a replaced server key (pinned public key), replay of a signed admin request (also after a
server restart), concurrent activation, admin requests without / with an untrusted key, key rotation (old key revoked), the
server CLI (admin-keys add / list / revoke, backup-db), backup + restore of database and signing key, password login disabled.
Everything runs locally (127.0.0.1, no TLS): HTTPS, the proxy and a public domain are NOT tested here."""
from __future__ import annotations

import base64
import contextlib
import io
import json
import os
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import _env
from _env import TempData
from test_license_client import HW1, HW2, Mono, guard_for
from test_license_server import Clock, Server, call

from masterquo.license import protocol as P
from masterquo.license.owner import OwnerError, OwnerLicenseManager
from masterquo.license.owner_key import OwnerKeyStore
from pmw_license import admin_auth as AA


def pair(srv, public_b64: str, label="OWNER PC") -> str:
    return AA.add_key(srv.app.state.store, public_b64, label, "server-shell", time.time())["kid"]


def signed_raw(srv, key, method, path, body=None, ts=None, headers=None):
    """A raw signed admin request (to test replay / forgery precisely)."""
    raw = json.dumps(body, separators=(",", ":")).encode() if body is not None else None
    hdr = headers or key.sign_headers(method, path, raw, int(ts if ts is not None else srv_time(srv)))
    req = urllib.request.Request(srv.base + path, data=raw, method=method, headers={"Content-Type": "application/json", **hdr})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read()), hdr
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}"), hdr


def srv_time(srv) -> float:
    return P.parse_utc(call(srv.base, "/health")[1]["server_time"])


class TestLicenseAcceptance(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.tmp = Path(self.td.dir)
        self.clock = Clock()
        self.srv = Server(self.tmp / "srv", self.clock, password=False)
        self.owner = OwnerLicenseManager(self.tmp / "owner")
        st = self.owner.set_server(self.srv.base)
        self.assertIs(st["paired"], False)
        pair(self.srv, st["device"]["public_key"])
        self.assertIs(self.owner.check()["paired"], True)

    def tearDown(self):
        self.srv.stop()
        self.td.close()

    def guard(self, name, hw=HW1, **kw):
        return guard_for(self.srv, self.tmp / name, hw=hw, **kw)

    def test_01_durations_activation_restarts_second_device_reset_expiry_revoke(self):
        keys = {d: self.owner.create(d, note=f"klient {d}") for d in ("72h", "7d", "31d")}
        self.assertEqual({k["duration"] for k in keys.values()}, {"72h", "7d", "31d"})
        mono = Mono()
        g = self.guard("c1", mono=mono, interval=10 ** 6)
        self.assertEqual(g.activate(keys["72h"]["license_key"])["status"], "ACTIVE")
        exp = g.public()["expires_at"]
        self.assertEqual(P.parse_utc(exp) - P.parse_utc(g.public()["activated_at"]), 72 * 3600)
        owner2 = OwnerLicenseManager(self.tmp / "owner")                                 # OWNER restart: no login, still paired
        self.assertIs(owner2.check()["paired"], True)
        g_restart = self.guard("c1")                                                      # CLIENT restart: token store, no key
        self.assertEqual(g_restart.validate_now("start programu")["status"], "ACTIVE")
        g2 = self.guard("c1b", hw=HW2)
        self.assertEqual(g2.activate(keys["72h"]["license_key"])["status"], "DEVICE_MISMATCH")
        lid = g.public()["license_id"]
        self.clock.t += 3600
        self.assertEqual(owner2.reset_device(lid, "nowy komputer klienta")["device_bound"], False)
        self.assertEqual(g2.activate(keys["72h"]["license_key"])["status"], "ACTIVE")    # rebinds the new device
        self.assertEqual(g2.public()["expires_at"], exp)                                 # reset never extends the period
        self.assertEqual(g.validate_now()["status"], "DEVICE_MISMATCH")                  # old device lost the binding
        self.clock.t += 72 * 3600
        self.assertEqual(g2.validate_now()["status"], "EXPIRED")
        self.assertFalse(g2.authorize_new_order()[0])
        g3 = self.guard("c3")
        self.assertEqual(g3.activate(keys["31d"]["license_key"])["status"], "ACTIVE")
        owner2.revoke(g3.public()["license_id"], "koniec współpracy")
        self.assertEqual(g3.validate_now()["status"], "REVOKED")
        self.assertFalse(g3.authorize_new_order()[0])

    def test_02_no_network_forged_answers_and_replaced_server_key(self):
        lic = self.owner.create("7d")
        g = self.guard("c1")
        self.assertEqual(g.activate(lic["license_key"])["status"], "ACTIVE")
        from masterquo.license import client as C

        def no_network(*_a, **_k):
            raise C.ApiError(None, "brak połączenia z serwerem licencji (URLError)")
        down = guard_for(self.srv, self.tmp / "c1", request=no_network)                  # no network: never "active by default"
        self.assertEqual(down.validate_now("start programu")["status"], "SERVER_UNAVAILABLE")
        self.assertFalse(down.authorize_new_order()[0])
        from pmw_license.signing import Signer
        other = Signer.generate()                                                       # a server with ANOTHER key (impostor / swap)
        imp = guard_for(self.srv, self.tmp / "c9", pub=other.public_b64)
        self.assertEqual(imp.activate(self.owner.create("7d")["license_key"])["status"], "TAMPERED")
        self.assertFalse(imp.authorize_new_order()[0])

    def test_03_admin_auth_unsigned_untrusted_forged_replay_skew(self):
        self.assertEqual(call(self.srv.base, "/api/v1/admin/stats")[0], 401)               # nothing
        st, out = call(self.srv.base, "/api/v1/admin/login", {"username": "owner", "password": "anything-long-1"})
        self.assertEqual(st, 401)
        self.assertIn("wyłączone", out["error"]["message"])                              # no password admin at all
        stranger = OwnerKeyStore(self.tmp / "stranger").active()                          # e.g. a CLIENT that wrote its own admin code
        self.assertEqual(signed_raw(self.srv, stranger, "GET", "/api/v1/admin/stats")[0], 401)
        key = self.owner.keys.active()
        st, _, hdr = signed_raw(self.srv, key, "POST", "/api/v1/admin/licenses", {"duration": "7d"})
        self.assertEqual(st, 200)
        st, out, _ = signed_raw(self.srv, key, "POST", "/api/v1/admin/licenses", {"duration": "7d"}, headers=hdr)
        self.assertEqual(st, 401)                                                        # replay of the same signed request
        self.assertIn("powtórzone", out["error"]["message"])
        st, out, _ = signed_raw(self.srv, key, "POST", "/api/v1/admin/licenses", {"duration": "31d"}, headers=hdr)
        self.assertEqual(st, 401)                                                        # body swapped under a valid signature
        forged = dict(hdr, **{P.ADMIN_HEADERS[3]: P.b64u(b"\x00" * 64), P.ADMIN_HEADERS[2]: P.new_nonce() + "abcdefgh"})
        self.assertEqual(signed_raw(self.srv, key, "GET", "/api/v1/admin/stats", headers=forged)[0], 401)
        st, out, _ = signed_raw(self.srv, key, "GET", "/api/v1/admin/stats", ts=srv_time(self.srv) - 600)
        self.assertEqual(st, 401)
        self.assertIn("czas", out["error"]["message"])
        n_lic = self.owner.stats()["total"]
        self.srv.stop()                                                                  # restart: the nonce store persists
        self.srv = Server(self.tmp / "srv", self.clock, password=False, signer=self.srv.signer)
        self.owner.url = self.srv.base
        st, out, _ = signed_raw(self.srv, key, "POST", "/api/v1/admin/licenses", {"duration": "7d"}, headers=hdr)
        self.assertEqual(st, 401)
        self.assertEqual(self.owner.stats()["total"], n_lic)
        audit = json.dumps(self.owner.audit(200))
        self.assertIn("ADMIN_UNAUTHORIZED", audit)
        self.assertNotIn(hdr[P.ADMIN_HEADERS[3]], audit)                                  # no signatures / secrets in the audit

    def test_04_concurrent_activation_binds_one_device(self):
        lic = self.owner.create("31d")
        res = {}

        def act(name, hw):
            res[name] = self.guard(name, hw=hw).activate(lic["license_key"])["status"]
        ts = [threading.Thread(target=act, args=(f"cc{i}", (str(i) * 64)[:64])) for i in range(1, 7)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(30)
        self.assertEqual(sorted(res.values()).count("ACTIVE"), 1)
        self.assertEqual(sorted(res.values()).count("DEVICE_MISMATCH"), 5)

    def test_05_key_rotation_and_self_revoke_guard(self):
        old_kid = self.owner.status()["device"]["kid"]
        st = self.owner.rotation("begin")
        new_pub = st["rotation"]["pending"]["public_key"]
        with self.assertRaises(OwnerError):
            self.owner.rotation("commit")                                                # not paired yet -> refused, old key kept
        self.assertEqual(self.owner.status()["device"]["kid"], old_kid)
        pair(self.srv, new_pub, "OWNER PC (nowy)")
        out = self.owner.rotation("commit")
        new_kid = out["device"]["kid"]
        self.assertNotEqual(new_kid, old_kid)
        self.assertEqual(out["rotation_result"]["old_revoked"]["status"], "REVOKED")
        old_key = OwnerKeyStore(self.tmp / "owner")
        prev = old_key._key(old_key._read()["previous"])
        self.assertEqual(signed_raw(self.srv, prev, "GET", "/api/v1/admin/stats")[0], 401)   # revoked key is useless
        self.assertIs(self.owner.check()["paired"], True)
        st, _, _ = signed_raw(self.srv, self.owner.keys.active(), "POST", f"/api/v1/admin/keys/{new_kid}/revoke", {})
        self.assertEqual(st, 400)                                                        # cannot lock itself out by mistake
        keys = self.owner.admin_keys()["items"]
        self.assertEqual({k["kid"]: bool(k["revoked_at"]) for k in keys}, {old_kid: True, new_kid: False})

    def test_06_server_cli_backup_and_restore(self):
        from pmw_license import cli
        env = {"PMW_LIC_DATABASE": str(self.srv.db_path), "PMW_LIC_SIGNING_KEY": str(self.tmp / "none.pem")}
        lic = self.owner.create("31d")
        g = self.guard("c1")
        self.assertEqual(g.activate(lic["license_key"])["status"], "ACTIVE")
        laptop = OwnerKeyStore(self.tmp / "laptop").active()
        with patched_env(env), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cli.main(["admin-keys", "add", "--public-key", laptop.public_b64, "--label", "laptop"]), 0)
            self.assertEqual(cli.main(["admin-keys", "list"]), 0)
            self.assertEqual(cli.main(["admin-keys", "add", "--public-key", "bm90LWEta2V5", "--label", "x"]), 2)
        self.assertIn(laptop.kid, out.getvalue())
        self.assertEqual(signed_raw(self.srv, laptop, "GET", "/api/v1/admin/stats")[0], 200)
        with patched_env(env), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["admin-keys", "revoke", laptop.kid, "--reason", "zgubiony"]), 0)
            self.assertEqual(cli.main(["backup-db", "--out", str(self.tmp / "backup" / "licenses.db")]), 0)
        self.assertEqual(signed_raw(self.srv, laptop, "GET", "/api/v1/admin/stats")[0], 401)
        signer = self.srv.signer
        self.srv.stop()                                                                  # disaster: restore DB + key on a new machine
        restored = self.tmp / "restored"
        restored.mkdir()
        (restored / "licenses.db").write_bytes((self.tmp / "backup" / "licenses.db").read_bytes())
        time.sleep(0.5)
        self.srv = Server(restored, self.clock, password=False, signer=signer, port=self.srv.port)   # same address (domain) as before
        g_new = guard_for(self.srv, self.tmp / "c1")                                     # same client installation
        self.assertEqual(g_new.validate_now("start programu")["status"], "ACTIVE")
        self.owner.url = self.srv.base
        self.assertIs(self.owner.check()["paired"], True)                               # admin key trust restored with the DB
        self.assertEqual(signed_raw(self.srv, laptop, "GET", "/api/v1/admin/stats")[0], 401)   # revocation restored too


@contextlib.contextmanager
def patched_env(values: dict):
    old = {k: os.environ.get(k) for k in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


if __name__ == "__main__":
    unittest.main()
