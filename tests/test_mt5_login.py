"""1.10.1 - attaching to MetaTrader 5 after "-6 Terminal: Authorization failed" (mt5/login.py, MarketBridge._initialize).

Covers: plain attach to the terminal session; optional explicit login with the password ONLY from the local secret store;
a rejected login is not repeated in a loop (until the credentials change) and falls back to the terminal session;
discovery tries only RUNNING terminals and remembers the one that worked; a Polish hint for -6 / IPC codes in the
error and the connection status; the password is never visible (mask, config, connection status, log). Simulated
terminal only - no real account, no order."""
from __future__ import annotations

import json
import os
import tempfile
import unittest

import _env
from _env import TempData


class StubLogin:
    """initialize() behaviour of a terminal: which (path, login, password) combinations succeed."""
    def __init__(self, ok=lambda kw: True):
        self.ok = ok
        self.calls: list[dict] = []
        self.err = (1, "Success")

    def initialize(self, **kw):
        self.calls.append(dict(kw))
        good = self.ok(kw)
        self.err = (1, "Success") if good else (-6, "Terminal: Authorization failed")
        return good

    def last_error(self):
        return self.err


class TestMT5Login(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.cfg, self.db, self.bus, self.log, self.fake, self.worker, self.bridge = _env.core()
        from masterquo.secrets_store import SecretStore
        self.secrets = SecretStore()
        self.bridge.secrets = self.secrets
        self.bridge._running_terminals = lambda: []

    def tearDown(self):
        self.worker.stop()
        self.td.close()

    def use(self, stub):
        self.fake.initialize = stub.initialize
        self.fake.last_error = stub.last_error
        return stub

    def test_terminal_session_without_credentials(self):
        st = self.use(StubLogin())
        self.bridge._initialize()
        self.assertEqual(st.calls, [{}])                                   # no login / password sent
        self.assertEqual(self.bridge.login_info["mode"], "TERMINAL_SESSION")

    def test_explicit_login_password_from_secret_store_only(self):
        self.cfg.update({"mt5": {"login": 5012345, "server": "Broker-Demo"}})
        self.secrets.set("MT5_PASSWORD", "s3cret-PW-123456")
        st = self.use(StubLogin())
        self.bridge._initialize()
        # 1.16: attach to the running session first; credentials only because ANOTHER account (the simulator's) is logged in
        self.assertEqual(st.calls, [{}, {"login": 5012345, "server": "Broker-Demo", "password": "s3cret-PW-123456"}])
        self.assertEqual(self.bridge.login_info["mode"], "CONFIG_LOGIN")
        self.assertEqual(self.secrets.mask("MT5_PASSWORD"), "•••")          # never partially shown
        dumped = json.dumps(self.cfg.get().model_dump(mode="json")) + json.dumps(self.bridge.connection_status(), default=str)
        self.assertNotIn("s3cret", dumped)                                    # not in config.json nor in the status

    def test_same_account_already_logged_in_is_not_logged_in_again(self):
        """User report 1.16 'connection lost every moment': re-sending login/password re-logs the account in MT5 and drops
        the trade-server connection. When the terminal already runs the configured account, no credentials are sent."""
        acc = self.fake._accounts[self.fake._login]                          # the account the (simulated) terminal runs
        self.fake.connected = True
        self.cfg.update({"mt5": {"login": int(acc["login"]), "server": str(acc["server"])}})
        self.secrets.set("MT5_PASSWORD", "s3cret-PW-123456")
        st = self.use(StubLogin())
        self.bridge._initialize()
        self.assertEqual(st.calls, [{}])
        from masterquo.diagnostics import attach
        st.calls.clear()
        self.assertTrue(attach(self.fake, self.cfg.get()))                 # training export / diagnostics: same rule
        self.assertEqual(st.calls, [{}])

    def test_rejected_login_not_repeated_and_falls_back_to_session(self):
        self.cfg.update({"mt5": {"login": 5012345, "server": "Broker-Demo"}})
        self.secrets.set("MT5_PASSWORD", "wrong-password")
        st = self.use(StubLogin(ok=lambda kw: "login" not in kw))           # the terminal itself is logged in
        self.bridge._initialize()
        self.assertEqual([("login" in c) for c in st.calls], [False, True, False])     # attach, rejected login, session
        self.assertTrue(self.bridge.login_info["credentials_rejected"])
        st.calls.clear()
        self.bridge._initialize()                                           # next reconnect: the rejected login is NOT sent again
        self.assertEqual(st.calls, [{}])
        self.secrets.set("MT5_PASSWORD", "new-password")                    # credentials changed -> one new attempt
        st.calls.clear()
        self.bridge._initialize()
        self.assertEqual([("login" in c) for c in st.calls][:2], [False, True])   # attach first, then the new credentials once
        logs = json.dumps(self.db.query("SELECT message, data_json FROM app_events"), ensure_ascii=False)
        self.assertIn("LOGIN_REJECTED", json.dumps(self.db.query("SELECT code FROM app_events")))
        self.assertNotIn("wrong-password", logs)
        self.assertNotIn("new-password", logs)

    def test_auth_failed_hint_and_running_terminal_detection(self):
        good = os.path.normcase(r"C:\MT5_Broker_B\terminal64.exe")
        self.bridge._running_terminals = lambda: [r"C:\MT5_Broker_A\terminal64.exe", r"C:\MT5_Broker_B\terminal64.exe"]
        st = self.use(StubLogin(ok=lambda kw: os.path.normcase(kw.get("path", "")) == good))
        self.bridge._initialize()                                           # default terminal fails (-6), B works
        self.assertEqual([c.get("path") for c in st.calls], [None, r"C:\MT5_Broker_A\terminal64.exe", r"C:\MT5_Broker_B\terminal64.exe"])
        self.assertEqual(self.bridge.login_info["terminal_path"], r"C:\MT5_Broker_B\terminal64.exe")
        st.calls.clear()
        self.bridge._initialize()                                           # remembered: goes straight to B
        self.assertEqual([c.get("path") for c in st.calls], [r"C:\MT5_Broker_B\terminal64.exe"])

    def test_all_fail_gives_polish_hint(self):
        from masterquo.mt5.bridge import BridgeError
        self.bridge._running_terminals = lambda: [r"C:\A\terminal64.exe", r"C:\B\terminal64.exe"]
        self.use(StubLogin(ok=lambda kw: False))
        with self.assertRaises(BridgeError) as ctx:
            self.bridge._initialize()
        msg = str(ctx.exception)
        self.assertTrue(msg.startswith("MT5_INITIALIZE_FAILED:(-6"), msg)
        self.assertIn("Zaloguj rachunek w MT5", msg)
        self.assertIn("Uruchomione terminale: 2", self.bridge.login_info["hint"])
        self.assertIn("login", self.bridge.connection_status())

    def test_fixed_path_is_never_replaced(self):
        self.cfg.update({"mt5": {"terminal_path": r"D:\MyMT5\terminal64.exe"}})
        self.bridge._running_terminals = lambda: [r"C:\Other\terminal64.exe"]
        st = self.use(StubLogin(ok=lambda kw: False))
        with self.assertRaises(Exception):
            self.bridge._initialize()
        self.assertEqual([c.get("path") for c in st.calls], [r"D:\MyMT5\terminal64.exe"])

    def test_discovery_reads_origin_files_and_program_files(self):
        from masterquo.mt5 import login as lg
        with tempfile.TemporaryDirectory() as d:
            inst = os.path.join(d, "PF", "Broker MT5")
            os.makedirs(inst)
            open(os.path.join(inst, "terminal64.exe"), "w").close()
            other = os.path.join(d, "Other")
            os.makedirs(other)
            open(os.path.join(other, "terminal64.exe"), "w").close()
            term = os.path.join(d, "AppData", "MetaQuotes", "Terminal", "ABC123")
            os.makedirs(term)
            with open(os.path.join(term, "origin.txt"), "w", encoding="utf-16") as f:
                f.write(other)
            found = lg.discover_terminals(env={"APPDATA": os.path.join(d, "AppData"), "ProgramFiles": os.path.join(d, "PF")}, running=[])
            self.assertEqual([os.path.normcase(p) for p in found],
                             [os.path.normcase(os.path.join(other, "terminal64.exe")), os.path.normcase(os.path.join(inst, "terminal64.exe"))])
        self.assertEqual(lg.init_kwargs(type("C", (), {"terminal_path": None, "login": 1, "server": None})(), "x"), {})   # login without server: unused


if __name__ == "__main__":
    unittest.main()
