"""License System v1 - the bot side (CLIENT / OWNER editions) against a real License API (uvicorn thread, test clock).
Acceptance items covered here: edition is fail-closed, KEY FOR MAGIC activation (valid / invalid / second device / same
device), signed-answer verification (tampered, foreign server key), server unavailable at startup and during operation,
periodic validation, expiry between validations, revocation, order submission blocked for new entries (S01-S12 gateway on
the MT5 simulator, SCALPING / HEDGING primary entries) while existing positions are NOT force-closed and stay managed,
Telegram new-signal notifications gated, OWNER License Manager through the authenticated admin API, the shared protocol
file identical on both sides, the license key never stored locally."""
from __future__ import annotations

import json
import os
import threading
import time
import unittest
from pathlib import Path

import _env
from _env import TempData, core, wait_for
from test_license_server import PASSWORD, Clock, Server, call

HW1, HW2 = "1" * 64, "2" * 64


class Mono:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def guard_for(srv, tmp: Path, hw=HW1, mono=None, request=None, interval=300.0, api=None, pub=None):
    from masterquo.license.edition import Edition
    from masterquo.license.guard import LicenseGuard
    from masterquo.license.tokenstore import TokenStore
    from masterquo.license import protocol as P
    pub = pub or srv.signer.public_b64
    import base64
    ed = Edition("CLIENT", api or srv.base, pub, P.key_id(base64.b64decode(pub)))
    kw = {"request": request} if request else {}
    return LicenseGuard(ed, store=TokenStore(tmp), hwid_fn=lambda: hw, mono=mono or Mono(), interval=interval, **kw)


def admin_token(srv):
    return call(srv.base, "/api/v1/admin/login", {"username": "owner", "password": PASSWORD})[1]["token"]


def new_key(srv, duration="31d"):
    st, out = call(srv.base, "/api/v1/admin/licenses", {"duration": duration}, admin_token(srv))
    assert st == 200, out
    return out


class TestEditionAndProtocol(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()
        os.environ.pop("MASTERQUO_EDITION", None)

    def test_protocol_identical_on_both_sides(self):
        a = (_env.ROOT / "license_server" / "pmw_license" / "protocol.py").read_bytes()
        b = (_env.ROOT / "backend" / "masterquo" / "license" / "protocol.py").read_bytes()
        self.assertEqual(a, b)

    def test_edition_fail_closed(self):
        from masterquo.license.edition import load
        p = Path(self.td.dir) / "edition.json"
        self.assertEqual(load(p).edition, "CLIENT")                                  # missing file -> CLIENT, never OWNER
        p.write_text("garbage", encoding="utf-8")
        self.assertEqual(load(p).edition, "CLIENT")
        p.write_text(json.dumps({"edition": "OWNER"}), encoding="utf-8")
        self.assertTrue(load(p).is_owner)
        os.environ["MASTERQUO_EDITION"] = "CLIENT"                                    # the env can force the stricter edition only
        self.assertEqual(load(p).edition, "CLIENT")
        os.environ["MASTERQUO_EDITION"] = "OWNER"
        p.write_text(json.dumps({"edition": "CLIENT"}), encoding="utf-8")
        e = load(p)
        self.assertEqual(e.edition, "CLIENT")
        self.assertIn("nie jest przygotowana", e.problem)                            # unstamped client package
        p.write_text(json.dumps({"edition": "CLIENT", "license_api": "http://licencje.example", "public_key": "AAAA"}), encoding="utf-8")
        self.assertIn("HTTPS", load(p).problem)
        self.assertTrue(json.loads((_env.ROOT / "edition.json").read_text(encoding="utf-8"))["edition"] == "OWNER")   # the repository = OWNER

    def test_unconfigured_client_blocks_and_owner_allows(self):
        from masterquo.license.edition import Edition
        from masterquo.license.guard import LicenseGuard
        g = LicenseGuard(Edition("CLIENT", problem="paczka CLIENT nie jest przygotowana"))
        self.assertEqual(g.public()["status"], "NOT_CONFIGURED")
        self.assertEqual(g.authorize_new_order()[0], False)
        o = LicenseGuard(Edition("OWNER"))
        self.assertEqual(o.authorize_new_order(), (True, "OWNER_EDITION"))
        self.assertTrue(o.authorized())


class TestGuardAgainstServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = TempData()
        cls.clock = Clock()
        cls.srv = Server(Path(cls.td.dir) / "srv", cls.clock)

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()
        cls.td.close()

    def tmp(self, name):
        p = Path(self.td.dir) / name
        p.mkdir(parents=True, exist_ok=True)
        return p

    def test_01_key_for_magic_activation_flow(self):
        g = guard_for(self.srv, self.tmp("c1"))
        self.assertEqual(g.public()["status"], "NOT_ACTIVATED")
        self.assertFalse(g.authorize_new_order()[0])
        self.assertEqual(g.activate("PMW-00000-00000-00000-00000")["status"], "INVALID")
        self.assertEqual(g.activate("not a key")["status"], "INVALID")
        lic = new_key(self.srv, "7d")
        st = g.activate(lic["license_key"])
        self.assertEqual((st["status"], st["duration"], st["authorized"]), ("ACTIVE", "7d", True))
        self.assertEqual(g.authorize_new_order("test"), (True, "LICENSE_ACTIVE"))
        stored = (self.tmp("c1") / "license.local.json").read_text(encoding="utf-8")
        self.assertNotIn(lic["license_key"], stored)                                 # only id + device token + hint are stored
        self.assertIn("token", json.loads(stored))
        # restart of the bot: a new guard on the same data validates online at start
        g2 = guard_for(self.srv, self.tmp("c1"))
        self.assertEqual(g2.public()["status"], "CHECKING")
        self.assertEqual(g2.validate_now("start programu")["status"], "ACTIVE")
        # second device with the same key
        g3 = guard_for(self.srv, self.tmp("c1-other"), hw=HW2)
        self.assertEqual(g3.activate(lic["license_key"])["status"], "DEVICE_MISMATCH")
        self.assertFalse(g3.authorize_new_order()[0])

    def test_02_tampered_and_foreign_server(self):
        lic = new_key(self.srv)
        from masterquo.license import client as C
        from masterquo.license import protocol as P

        def tamper(base, path, body=None, **kw):
            out = C.request(base, path, body, **kw)
            if "assertion" in out:
                b, s = out["assertion"].split(".")
                pl = json.loads(P.b64u_dec(b))
                pl["exp"] = "2099-01-01T00:00:00Z"
                out["assertion"] = P.b64u(P.canonical(pl)) + "." + s
            return out
        g = guard_for(self.srv, self.tmp("c2"), request=tamper)
        self.assertEqual(g.activate(lic["license_key"])["status"], "TAMPERED")
        self.assertFalse(g.authorize_new_order()[0])
        # a fake server signing with another key (client pinned to the real public key)
        td2 = TempData()
        try:
            fake = Server(Path(td2.dir), Clock())
            k2 = new_key(fake)
            g2 = guard_for(fake, self.tmp("c2b"), pub=self.srv.signer.public_b64)
            self.assertEqual(g2.activate(k2["license_key"])["status"], "TAMPERED")
            fake.stop()
        finally:
            td2.close()

    def test_03_server_unavailable_at_start_and_during_operation(self):
        g0 = guard_for(self.srv, self.tmp("c3x"), api="http://127.0.0.1:9")            # nothing listens there
        g0.store.save({"license_id": "LIC-0123456789abcdef", "token": "t" * 43, "kid": g0.edition.kid, "api": g0.edition.license_api})
        self.assertEqual(g0.validate_now("start programu")["status"], "SERVER_UNAVAILABLE")
        self.assertFalse(g0.authorize_new_order()[0])
        lic = new_key(self.srv)
        mono = Mono()
        g = guard_for(self.srv, self.tmp("c3"), mono=mono)
        self.assertEqual(g.activate(lic["license_key"])["status"], "ACTIVE")
        down = {"on": False}
        from masterquo.license import client as C

        def flaky(base, path, body=None, **kw):
            if down["on"]:
                raise C.ApiError(None, "brak połączenia z serwerem licencji (URLError)")
            return C.request(base, path, body, **kw)
        g.request = flaky
        down["on"] = True
        ok, why = g.authorize_new_order("test")
        self.assertFalse(ok)
        self.assertIn("SERVER_UNAVAILABLE", why)
        self.assertFalse(g.authorized())
        down["on"] = False
        mono.t += 25                                                                  # the 20 s denial cache has passed
        self.assertTrue(g.authorize_new_order("test")[0])
        mono.t += 300 + 91                                                            # no successful validation for > interval + 90 s
        self.assertFalse(g.authorized())

    def test_04_periodic_validation_runs(self):
        lic = new_key(self.srv)
        g = guard_for(self.srv, self.tmp("c4"), interval=0.3)
        self.assertEqual(g.activate(lic["license_key"])["status"], "ACTIVE")
        calls = []
        orig = g.request
        g.request = lambda *a, **k: calls.append(a[1]) or orig(*a, **k)
        g.start()
        try:
            self.assertTrue(wait_for(lambda: calls.count("/api/v1/licenses/validate") >= 3, 10, 0.05))   # start + every interval
        finally:
            g.stop()
        self.assertEqual(g.public()["status"], "ACTIVE")

    def test_05_expiry_between_checks_and_revocation(self):
        lic = new_key(self.srv, "24h")
        mono = Mono()
        g = guard_for(self.srv, self.tmp("c5"), mono=mono, interval=10 ** 6)
        self.assertEqual(g.activate(lic["license_key"])["status"], "ACTIVE")
        mono.t += 86_400 + 1                                                         # local clock untouched; server time + elapsed
        self.assertFalse(g.authorized())
        self.assertEqual(g.public()["status"], "EXPIRED")
        lic2 = new_key(self.srv, "31d")
        g2 = guard_for(self.srv, self.tmp("c5b"))
        self.assertEqual(g2.activate(lic2["license_key"])["status"], "ACTIVE")
        lid = g2.public()["license_id"]
        call(self.srv.base, f"/api/v1/admin/licenses/{lid}/revoke", {"reason": "test"}, admin_token(self.srv))
        self.assertEqual(g2.validate_now()["status"], "REVOKED")
        self.assertFalse(g2.authorize_new_order()[0])

    def test_06_owner_license_manager_device_key(self):
        """1.29: no login screen - the OWNER app signs admin requests with its device key; the server trusts the key only after
        it was added from the server's shell. The test clock of the server is months ahead: the skew is measured and compensated."""
        from masterquo.license.owner import OwnerError, OwnerLicenseManager
        om = OwnerLicenseManager(self.tmp("owner"))
        st = om.set_server(self.srv.base)
        self.assertIs(st["paired"], False)                                            # unknown device key -> not trusted
        self.assertIn("admin-keys add --public-key", st["pairing_command"])
        with self.assertRaises(OwnerError):
            om.create("31d")
        pair(self.srv, st["device"]["public_key"])                                     # out-of-band, on the server
        self.assertIs(om.check()["paired"], True)
        made = {d: om.create(d, note=f"test {d}") for d in ("72h", "7d", "31d", "24h")}
        self.assertTrue(all(m["license_key"].startswith("PMW-") for m in made.values()))
        self.assertEqual(om.status()["durations"], ["72h", "7d", "31d"])
        lst = om.list(q="test")
        self.assertGreaterEqual(lst["total"], 4)
        self.assertNotIn(made["31d"]["license_key"], json.dumps(lst))
        lid = made["7d"]["license_id"]
        self.assertEqual(om.reset_device(lid, "x")["device_bound"], False)
        self.assertEqual(om.revoke(lid, "x")["status"], "REVOKED")
        self.assertIn("by_status", om.stats())
        self.assertTrue(om.audit(20)["items"])
        om2 = OwnerLicenseManager(self.tmp("owner"))                                   # restart: no login, same device key
        self.assertIs(om2.check()["paired"], True)
        self.assertEqual(om2.status()["device"]["kid"], st["device"]["kid"])
        saved = b"".join(p.read_bytes() for p in self.tmp("owner").iterdir() if p.is_file())
        self.assertNotIn(PASSWORD.encode(), saved)
        for lic in made.values():
            self.assertNotIn(lic["license_key"].encode(), saved)


def pair(srv, public_b64: str, label: str = "OWNER test") -> str:
    """What `python -m pmw_license admin-keys add` does on the server (same function, same database)."""
    from pmw_license import admin_auth as AA
    return AA.add_key(srv.app.state.store, public_b64, label, "server-shell", time.time())["kid"]


class TestOrdersBlockedPositionsKept(unittest.TestCase):
    """The real execution path on the MT5 simulator: a license failure blocks the NEXT entry; the open position is not
    closed by it and is still managed (partial close) and closable by the user."""

    def setUp(self):
        self.td = TempData()
        self.clock = Clock()
        self.srv = Server(Path(self.td.dir) / "srv", self.clock)
        from test_risk_execution import LIMITS, StubEngine
        cfg, db, bus, log, fake, worker, b = core()
        self.cfg, self.db, self.bus, self.log, self.fake, self.worker, self.b = cfg, db, bus, log, fake, worker, b
        cfg.update({"execution": {"primary_path": {"XAUUSD": "ACTIVE"}}, "risk": LIMITS, "costs": {"slippage_stress_points": 5}})
        b.start()
        self.assertTrue(wait_for(lambda: b.state == "CONNECTED" and b.quote_status() and b.symbol_info, 40))
        from masterquo.engine.lifecycle import LifecycleStore
        from masterquo.execution.gateway import ExecutionGateway
        from masterquo.execution.manager import PositionManager
        from masterquo.execution.modes import ModeManager
        from masterquo.execution.paper import PaperBroker
        self.modes = ModeManager(cfg, db, bus, log, account_provider=lambda: (b.account_status(), b.account_key, b.synthetic))
        self.engine = StubEngine(LifecycleStore(db))
        self.paper = PaperBroker(cfg, b, db, bus, log)
        self.gw = ExecutionGateway(cfg, b, db, bus, log, self.modes, self.engine, self.paper)
        self.mgr = PositionManager(cfg, b, db, bus, log, self.modes, self.paper)
        self.gw.manager = self.mgr
        self.mgr.reconciled_epoch = b.session_epoch
        p = Path(self.td.dir) / "client"
        p.mkdir()
        self.mono = Mono()
        self.guard = guard_for(self.srv, p, mono=self.mono)
        self.gw.license = self.guard

    def tearDown(self):
        self.b.stop()
        self.worker.stop()
        self.srv.stop()
        self.td.close()

    def decision(self, did, setup_id):
        from test_risk_execution import TestExecution
        return TestExecution.decision(self, did, setup_id)

    def test_entry_blocked_position_not_closed_and_still_managed(self):
        acct = self.b.account_status()
        self.modes.set_mode("AUTO_DEMO", confirm=str(acct["login"]), account=acct, account_key=self.b.account_key, synthetic=True)
        self.engine.decision = self.decision("MQD-L0", "MQS-L0")
        r0 = self.gw.execute("MQD-L0")
        self.assertEqual(r0["status"], "BLOCKED")                                     # not activated yet
        self.assertTrue(r0["reason"].startswith("LICENCJA_NOT_ACTIVATED"), r0)
        self.assertIsNone(self.db.one("SELECT 1 FROM order_attempts WHERE decision_id='MQD-L0'"))
        lic = new_key(self.srv)
        self.assertEqual(self.guard.activate(lic["license_key"])["status"], "ACTIVE")
        self.engine.decision = self.decision("MQD-L1", "MQS-L1")
        r1 = self.gw.execute("MQD-L1")
        self.assertEqual(r1["status"], "FILLED", r1)
        self.assertTrue(wait_for(lambda: len(self.b.positions) == 1, 20))
        call(self.srv.base, f"/api/v1/admin/licenses/{self.guard.public()['license_id']}/revoke", {"reason": "test"}, admin_token(self.srv))
        sends = []
        orig = self.fake.order_send
        self.fake.order_send = lambda r: sends.append(r) or orig(r)
        self.engine.decision = self.decision("MQD-L2", "MQS-L2")
        r2 = self.gw.execute("MQD-L2")
        self.assertEqual(r2["status"], "BLOCKED")
        self.assertIn("LICENCJA_REVOKED", r2["reason"])
        self.assertEqual(sends, [])                                                   # no order reached the terminal
        self.guard.validate_now("okresowo")                                           # periodic check also fails ...
        time.sleep(0.5)
        self.assertEqual(len(self.b.positions), 1)                                    # ... and nothing closed the open position
        mp = self.db.one("SELECT * FROM managed_positions WHERE state='OPEN' AND mode='AUTO_DEMO'")
        mod = self.gw.manual_modify(dict(mp), "PARTIAL", volume=0.02)                 # management keeps working
        self.assertEqual(mod["status"], "DONE", mod)
        res = self.mgr.close_positions("ALL")                                         # the user can still close
        self.assertEqual(res.get("errors") or [], [], res)
        self.assertTrue(wait_for(lambda: len(self.b.positions) == 0, 20))


class TestSHAndTelegramGates(unittest.TestCase):
    def test_sh_primary_entry_gated_management_and_hedge_not(self):
        from masterquo.db.database import Database
        from masterquo.mt5.fake import FakeMT5
        from masterquo.sh.executor import SHExecutor
        from masterquo.sh.store import SHStore
        td = TempData()
        try:
            fake = FakeMT5(hedging=True)
            fake.initialize()
            allow = {"ok": True}
            ex = SHExecutor(SHStore(Database()), terminal=lambda fn: fn(fake), account_key="acc", symbol_info=fake.symbol_info("XAUUSD-")._asdict(),
                            license_check=lambda: (allow["ok"], "LICENCJA_REVOKED: test"))
            t = fake.symbol_info_tick("XAUUSD-")
            q = {"bid": t.bid, "ask": t.ask}
            plan = {"plan_id": "PLN-LIC01", "symbol": "XAUUSD-", "account_key": "acc", "strategy": "SCALPING"}
            r = ex.open(plan, role="P", side="BUY", volume=0.1, sl=q["bid"] - 3, tp=0, mode="AUTO_DEMO", quote=q, tag="P")
            self.assertEqual(r["status"], "FILLED", r)
            allow["ok"] = False
            for mode in ("AUTO_DEMO", "PAPER"):
                b = ex.open({**plan, "plan_id": f"PLN-LIC-{mode}"}, role="P", side="SELL", volume=0.1, sl=q["ask"] + 3, tp=0, mode=mode, quote=q, tag="P")
                self.assertEqual((b["status"], b["reason"]), ("BLOCKED", "LICENCJA_REVOKED: test"))
            pos = fake.positions_get()[0]
            act = {"action_id": "PLN-LIC01:PART:1", "plan_id": "PLN-LIC01", "kind": "CLOSE_PARTIAL", "volume": 0.05}
            m = ex.perform(plan, act, mode="AUTO_DEMO", quote=q, ticket=pos.ticket, side_of_position="BUY")
            self.assertIn(m["status"], ("FILLED", "PARTIAL", "DONE"), m)                 # management of the existing plan works
            h = ex.open(plan, role="H", side="SELL", volume=0.05, sl=q["ask"] + 3, tp=0, mode="AUTO_DEMO", quote=q, tag="H")
            self.assertEqual(h["status"], "FILLED", h)                                   # the hedge leg protects an existing plan
        finally:
            td.close()

    def test_telegram_new_signal_gate(self):
        from types import SimpleNamespace as NS
        from masterquo.notify.telegram import TelegramNotifier
        sent = []
        tn = TelegramNotifier.__new__(TelegramNotifier)
        tn.cfg_store = NS(get=lambda: NS(telegram=NS(language="EN")))
        tn._deliver = lambda kind, key, text: sent.append(key) or True
        tn.signal_gate = lambda: False
        self.assertFalse(tn.signal("k1", {"symbol": "XAUUSD-", "side": "BUY"}))
        tn.signal_gate = lambda: True
        self.assertTrue(tn.signal("k2", {"symbol": "XAUUSD-", "side": "BUY", "strategy": "S01", "timeframe": "M5", "stage": "OPEN",
                                         "entry": 1, "sl": 0.5, "tps": [2]}))
        self.assertEqual(sent, ["k2"])


if __name__ == "__main__":
    unittest.main()
