"""Bot-side licensing against a REAL central server over HTTP (uvicorn on 127.0.0.1, controlled server clock).

Covers: client clock / time zone / restart / sleep / network loss (no unauthorised extension), forged or foreign leases,
operation-token reuse and expiry, enforcement in engine / ML / agent / gateway / API / CLI, expiry during work with
cancellation of the bot's own pending opening orders, and the MT5 connector telemetry.
"""
from __future__ import annotations

import base64
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

import _env
from _env import TempData

sys.path.insert(0, str(_env.ROOT / "server"))
from test_central import World  # noqa: E402

UTC_PW = "haslo-uzytkownika-1"


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Live:
    """Central server (World) served over real HTTP in a background thread."""

    def __init__(self):
        import uvicorn
        self.w = World("sqlite")
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.w.s.public_url = self.url                       # issuer of leases
        self.w.s.allowed_origins = [self.url, "http://testserver"]
        self.server = uvicorn.Server(uvicorn.Config(self.w.app, host="127.0.0.1", port=self.port, log_level="warning"))
        self.th = threading.Thread(target=self.server.run, daemon=True)
        self.th.start()
        for _ in range(100):
            if self.server.started:
                break
            time.sleep(0.05)

    def stop(self):
        self.server.should_exit = True
        self.th.join(5)


class Mono:
    """Controllable monotonic + wall clocks for the client."""

    def __init__(self):
        self.m = 1000.0
        self.w = 1_900_000_000.0

    def mono(self):
        return self.m

    def wall(self):
        return self.w

    def adv(self, s, wall_too=True):
        self.m += s
        if wall_too:
            self.w += s


def client_service(live: Live, td: TempData, mono=None):
    from masterquo.config import ConfigStore
    from masterquo.licensing.service import LicenseService
    from masterquo.secrets_store import SecretStore
    cfg = ConfigStore(Path(td.dir) / "config.json")
    cfg.update({"central": {"url": live.url, "allow_insecure_localhost": True}})
    kw = {"mono": mono.mono, "wall": mono.wall} if mono else {}
    return LicenseService(cfg, SecretStore(Path(td.dir)), Path(td.dir), **kw), cfg


class LicensingClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.live = Live()
        w = cls.live.w
        cls.uid = w.user("klient@example.com")

    @classmethod
    def tearDownClass(cls):
        cls.live.stop()

    def setUp(self):
        self.td = TempData()
        self.live.w.clock.t = time.time()            # server clock = real time unless a test moves it

    def tearDown(self):
        self.td.close()

    def fresh_license(self):
        return self.live.w.license(self.uid)

    def activated(self, mono=None):
        lic, cfg = client_service(self.live, self.td, mono)
        lic.login("klient@example.com", UTC_PW)
        lic.activate(self.fresh_license())
        return lic, cfg

    # ------------------------------------------------------------ 4/5/6 client side: activation, lease, restart
    def test_activation_lease_and_restart_needs_online(self):
        lic, cfg = self.activated()
        self.assertTrue(lic.guard.allows("analysis"))
        st = lic.status()
        self.assertTrue(st["ui_unlocked"])
        self.assertEqual(st["license"]["status"], "ACTIVE")
        self.assertNotIn("token", json.dumps(lic.device.state()))           # no session token on disk
        self.assertNotIn("PRIVATE", (Path(self.td.dir) / "license" / "state.json").read_text())
        # restart = new process: no lease until a successful online heartbeat
        from masterquo.licensing.service import LicenseService
        from masterquo.secrets_store import SecretStore
        lic2 = LicenseService(cfg, SecretStore(Path(self.td.dir)), Path(self.td.dir))
        self.assertFalse(lic2.guard.allows("analysis"))
        self.assertTrue(lic2.heartbeat_now())                              # device credential, no password needed
        self.assertTrue(lic2.guard.allows("trade_open"))

    def test_editing_state_file_grants_nothing(self):
        lic, cfg = self.activated()
        p = Path(self.td.dir) / "license" / "state.json"
        st = json.loads(p.read_text())
        st["device_id"] = "00000000-0000-0000-0000-000000000000"
        p.write_text(json.dumps(st))
        from masterquo.licensing.service import LicenseService
        from masterquo.secrets_store import SecretStore
        lic2 = LicenseService(cfg, SecretStore(Path(self.td.dir)), Path(self.td.dir))
        self.assertFalse(lic2.heartbeat_now())
        self.assertFalse(lic2.guard.allows("analysis"))

    # ------------------------------------------------------------ 7. clocks, sleep, network
    def test_conservative_deadline_and_no_extension_offline(self):
        m = Mono()
        lic, cfg = self.activated(m)
        rem = lic.guard.lease_remaining()
        self.assertLessEqual(rem, 60.0)
        self.assertGreater(rem, 50.0)
        # network down: lease works only until its original deadline - no tolerance period
        cfg.update({"central": {"url": f"http://127.0.0.1:{free_port()}"}})
        m.adv(rem - 1)
        self.assertFalse(lic.heartbeat_now())
        self.assertTrue(lic.guard.allows("analysis"))
        self.assertEqual(lic.last_error, "CENTRAL_UNREACHABLE")
        m.adv(1.0)
        lic.heartbeat_now()
        self.assertFalse(lic.guard.allows("analysis"))
        self.assertEqual(lic.guard.reason, "LEASE_EXPIRED_NO_FRESH_SERVER_CONFIRMATION")

    def test_wall_clock_changes_do_not_extend(self):
        m = Mono()
        lic, _ = self.activated(m)
        m.w -= 3 * 86400                                                   # user sets the PC clock back 3 days
        self.assertFalse(lic.guard.allows("analysis"))                     # discontinuity -> online revalidation required
        self.assertEqual(lic.guard.reason, "CLOCK_DISCONTINUITY_REVALIDATE_ONLINE")
        self.assertTrue(lic.heartbeat_now())                               # server time decides, not the PC clock
        m.adv(30)
        os.environ["TZ"] = "Asia/Tokyo"                                    # time zone change: presentation only
        try:
            time.tzset()
            self.assertTrue(lic.guard.allows("analysis"))
        finally:
            os.environ.pop("TZ", None)
            time.tzset()
        m.adv(3600, wall_too=False)                                        # sleep where the monotonic clock kept running
        self.assertFalse(lic.guard.allows("analysis"))

    def test_server_expiry_reaches_client(self):
        m = Mono()
        lic, _ = self.activated(m)
        w = self.live.w
        exp = lic.license["expires_at"]
        w.clock.t = exp - 10
        self.assertTrue(lic.heartbeat_now())
        self.assertLessEqual(lic.guard.lease_remaining(), 10.0)           # lease bounded by expires_at
        w.clock.t = exp
        self.assertFalse(lic.heartbeat_now())
        self.assertFalse(lic.guard.allows("trade_open"))
        self.assertEqual(lic.guard.reason, "LICENSE_EXPIRED")
        w.clock.t = 1_900_000_000

    # ------------------------------------------------------------ 8. forged / foreign lease, op tokens
    def test_forged_and_foreign_leases_rejected(self):
        import jwt
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from masterquo.licensing.guard import LicenseRequired
        lic, _ = self.activated()
        st = lic.device.state()
        now = int(time.time())
        base = {"iss": st["issuer"], "aud": "masterquo-bot", "sub": st["owner_user_id"], "lic": "x", "act": st["activation_id"], "dev": st["device_id"],
                "scope": ["analysis", "trade_open"], "iat": now, "nbf": now, "exp": now + 60, "jti": "j"}
        evil = Ed25519PrivateKey.generate()
        for claims, key, kid, why in [
            (base, evil, st["kid"], "foreign signing key"),
            (dict(base, aud="other"), evil, st["kid"], "audience"),
            (dict(base, exp=now + 3600), evil, st["kid"], "ttl"),
        ]:
            tok = jwt.encode(claims, key, algorithm="EdDSA", headers={"kid": kid})
            with self.assertRaises(LicenseRequired, msg=why):
                lic._verify(tok, "masterquo-bot")
        tok = jwt.encode(base, "secret", algorithm="HS256", headers={"kid": st["kid"]})
        with self.assertRaises(LicenseRequired):
            lic._verify(tok, "masterquo-bot")                              # algorithm confusion
        # a genuine lease of ANOTHER device is rejected by this client
        other = TempData()
        try:
            lic_b, _ = client_service(self.live, other)
            lic_b.login("klient@example.com", UTC_PW)
            lic_b.activate(self.fresh_license())
            out, _t0, _ = lic_b.client().device_call(lic_b.device.private_key(), lic_b.device.state()["device_id"], "POST", "/api/v1/device/heartbeat", {})
            with self.assertRaises(LicenseRequired):
                lic._verify(out["lease"], "masterquo-bot")
        finally:
            other.close()

    def test_operation_token_single_use_and_expiry(self):
        from masterquo.licensing.guard import LicenseRequired
        m = Mono()
        lic, _ = self.activated(m)
        g = lic.authorize_open("AUTO_DEMO:acc:SETUP-1", {"symbol": "XAUUSD-", "side": "BUY", "volume": 0.01, "mode": "AUTO_DEMO"})
        lic.consume(g)
        with self.assertRaises(LicenseRequired):
            lic.consume(g)                                                 # reuse
        with self.assertRaises(LicenseRequired):
            lic.authorize_open("AUTO_DEMO:acc:SETUP-1", {})                # same intent again (server refuses)
        g2 = lic.authorize_open("AUTO_DEMO:acc:SETUP-2", {})
        m.adv(25)                                                          # longer than the op token validity
        with self.assertRaises(LicenseRequired):
            lic.consume(g2)

    # ------------------------------------------------------------ 10. enforcement: cancel own pending opening orders, race
    def test_enforcement_cancels_only_bot_opening_orders(self):
        from masterquo.licensing.enforce import cancel_bot_opening_orders

        class Order(dict):
            def _asdict(self):
                return dict(self)

        class Res:
            def __init__(self, rc):
                self.retcode = rc

        class M:
            TRADE_ACTION_REMOVE = 8

            def __init__(self):
                self.removed = []
                self.orders = [Order(ticket=1, type=2, magic=777, symbol="XAUUSD-", position_id=0),      # bot BUY_LIMIT -> cancel
                               Order(ticket=2, type=4, magic=0, symbol="XAUUSD-", position_id=0),        # manual -> keep
                               Order(ticket=3, type=5, magic=777, symbol="XAUUSD-", position_id=55),     # protective (position) -> keep
                               Order(ticket=4, type=3, magic=777, symbol="XAUUSD-", position_id=0)]      # bot, but filled meanwhile

            def orders_get(self):
                return self.orders

            def order_send(self, req):
                self.removed.append(req["order"])
                return Res(10009 if req["order"] != 4 else 10013)

        m = M()

        class Bridge:
            def raw_call(self, fn, prio=0, timeout=None):
                return fn(m)

        class Cfg:
            def get(self):
                return type("C", (), {"mt5": type("X", (), {"magic_number": 777})()})()

        class Mgr:
            ticks = 0

            def tick(self):
                Mgr.ticks += 1
        r = cancel_bot_opening_orders(Bridge(), Cfg(), None, Mgr())
        self.assertEqual((r["cancelled"], r["failed"]), ([1], [4]))
        self.assertEqual(sorted(m.removed), [1, 4])
        self.assertEqual(Mgr.ticks, 1)                                     # race: reconcile with the terminal

    # ------------------------------------------------------------ 9/10. gateway / engine / ML / agent without license
    def test_gateway_blocks_after_loss_and_paper_needs_lease(self):
        from _env import core
        from masterquo.engine.lifecycle import LifecycleStore
        from masterquo.execution.gateway import ExecutionGateway
        from masterquo.execution.modes import ModeManager
        from masterquo.execution.paper import PaperBroker
        m = Mono()
        lic, _ = self.activated(m)
        cfg, db, bus, log, fake, worker, b = core()
        cfg.update({"risk": {"risk_per_trade_pct": 1.0, "max_total_open_risk_pct": 3.0, "daily_loss_limit_pct": 5.0, "max_drawdown_pct": 10.0, "max_open_positions": 3}})
        b.start()
        try:
            self.assertTrue(_env.wait_for(lambda: b.state == "CONNECTED" and b.quote_status() and b.symbol_info, 40))
            modes = ModeManager(cfg, db, bus, log, account_provider=lambda: (b.account_status(), b.account_key, b.synthetic))
            acct = b.account_status()
            modes.set_mode("AUTO_DEMO", confirm=str(acct["login"]), account=acct, account_key=b.account_key, synthetic=True)

            class Eng:
                decision = None

                def current_decision(self):
                    return self.decision

                def mark_entered(self, *a):
                    pass
            eng = Eng()
            gw = ExecutionGateway(cfg, b, db, bus, log, modes, eng, PaperBroker(cfg, b, db, bus, log))
            gw.license = lic
            from datetime import datetime, timedelta, timezone
            q = b.quote_status()
            e = q["bid"]
            eng.decision = {"decision_id": "MQD-L", "execution_permission": "ALLOWED", "expires_at_utc": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
                            "account_key": b.account_key, "session_epoch": b.session_epoch, "symbol": "XAUUSD-", "analysis_direction": "SHORT", "reason_codes": [],
                            "setup": {"setup_id": "MQS-L1", "state": "CONFIRMED", "strategy_id": "S01"},
                            "risk": {"risk_gate": "PASS", "lots": 0.01, "entry": e, "stop_loss": round(e + 8, 2), "targets": [{"price": round(e - 6, 2), "weight": 1.0}]}}
            sent = []
            orig = fake.order_send
            fake.order_send = lambda r: sent.append(r) or orig(r)
            lic.guard.clear("LICENSE_REVOKED")                             # license lost while the bot runs
            r = gw.execute("MQD-L", initiated_by="AUTO")
            self.assertEqual(r["status"], "BLOCKED")
            self.assertTrue(r["reason"].startswith("LICENSE_"))
            self.assertEqual(sent, [])
            self.assertTrue(lic.heartbeat_now())
            r = gw.execute("MQD-L", initiated_by="AUTO")
            self.assertEqual(r["status"], "FILLED", r)
            self.assertEqual(len(sent), 1)
            att = db.one("SELECT authorized_at FROM order_attempts")
            self.assertIsNotNone(att["authorized_at"])
        finally:
            b.stop()
            worker.stop()

    def test_engine_ml_agent_denied_without_guard(self):
        from masterquo.licensing.guard import LicenseGuard
        g = LicenseGuard()                                                 # no lease
        self.assertFalse(g.allows("analysis"))

        class E:
            pass
        from masterquo.engine.service import EngineService
        e = E()
        e.guard, e.locked_reason, e.decision = None, None, {"x": 1}
        e._lock = threading.RLock()
        e.bus = type("B", (), {"publish": lambda *a, **k: None})()
        self.assertFalse(EngineService.licensed(e))                       # no guard object = no access
        self.assertIsNone(e.decision)
        e.guard = g
        self.assertFalse(EngineService.licensed(e))

    # ------------------------------------------------------------ connector
    def test_connector_sends_snapshot_and_deals(self):
        from _env import core
        from masterquo.licensing.connector import Connector
        from masterquo.mt5 import fake as F
        lic, cfg_lic = self.activated()
        cfg, db, bus, log, fake, worker, b = core()
        b.start()
        try:
            self.assertTrue(_env.wait_for(lambda: b.state == "CONNECTED" and b.account_status() and b.clock.offset is not None, 60))
            off = b.clock.offset
            now = int(time.time()) + int(off)
            fake._deals += [F.Deal(9001, 1, now - 7200, (now - 7200) * 1000, 0, 0, 777, 501, 0.10, 2300.0, -0.5, 0.0, 0.0, 0.0, "XAUUSD-", "MQ", 0),
                            F.Deal(9002, 2, now - 3600, (now - 3600) * 1000, 1, 1, 777, 501, 0.10, 2310.0, -0.5, 0.0, 100.0, 0.0, "XAUUSD-", "MQ:TP", 0),
                            F.Deal(9003, 0, now - 1800, (now - 1800) * 1000, 2, 0, 0, 0, 0.0, 0.0, 0.0, 0.0, 500.0, 0.0, "", "deposit", 0)]
            conn = Connector(lic, b, cfg_lic)
            conn.tick(0.0)
            self.assertEqual(conn.status_text, "OFF")                     # nothing is sent without explicit consent
            acc = b.account_status()
            cfg_lic.update({"central": {"connector": {"enabled": True, "server": acc["server"], "login": str(acc["login"]), "snapshot_seconds": 5,
                                                      "deals_seconds": 15, "initial_history_days": 7}}})
            for i in range(3):
                conn.tick(1000.0 + i * 20)
            self.assertEqual(conn.status_text, "ONLINE")
            w = self.live.w
            row = w.db.one("SELECT * FROM trading_accounts WHERE id=?", (conn.account_id,))
            self.assertEqual((row["server"], row["login"]), (acc["server"], str(acc["login"])))
            self.assertIsNotNone(row["last_balance"])
            st = w.c.account_stats(conn.account_id, rng="all")
            self.assertEqual((st["wins"], st["losses"]), (1, 0))
            self.assertEqual(st["excluded_non_trade"].get("BALANCE"), 1)
            # terminal switched to another account -> stops, no silent switch
            cfg_lic.update({"central": {"connector": {"login": "1"}}})
            conn.tick(5000.0)
            self.assertEqual(conn.status_text, "ACCOUNT_DIFFERS_FROM_CONSENTED")
        finally:
            b.stop()
            worker.stop()

    # ------------------------------------------------------------ 9. CLI
    def test_cli_export_requires_license(self):
        env = dict(os.environ, MASTERQUO_DATA_DIR=self.td.dir, PYTHONPATH=str(_env.ROOT / "backend"))
        out = subprocess.run([sys.executable, "-m", "masterquo", "export", "--from-utc", "2026-01-01", "--to-utc", "2026-01-02", "--out", self.td.dir],
                             env=env, cwd=str(_env.ROOT / "backend"), capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 3, out.stdout + out.stderr)
        self.assertIn("licencji", out.stdout)


if __name__ == "__main__":
    unittest.main()
