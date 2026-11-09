"""1.39 (user decision): the bot starts in AUTO_LIVE on a real terminal and binds itself to the account the terminal reports as REAL;
the validation gates of AUTO_LIVE are withdrawn (warnings instead). Kept: account type check (a DEMO account or synthetic data never
runs as LIVE), a different account than the bound one blocks, STOP, risk limits. Runs on plain objects - never on a real account."""
from __future__ import annotations

import json
import unittest

import _env  # noqa: F401
from _env import TempData


class _Log:
    def __getattr__(self, name):
        return lambda *a, **k: None


class _Bus:
    def publish(self, *a, **k):
        pass


class TestLiveStart(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.config import ConfigStore
        from masterquo.db.database import Database
        from masterquo.execution.modes import ModeManager
        self.cfg = ConfigStore()
        self.db = Database()
        self.acc = {"login": 777, "trade_mode": "REAL", "equity": 10000.0}
        self.key = "Broker-Live:777"
        self.synth = False
        self.mm = ModeManager(self.cfg, self.db, _Bus(), _Log(), account_provider=lambda: (self.acc, self.key, self.synth))

    def tearDown(self):
        self.td.close()

    def test_defaults_and_start_mode(self):
        ex = self.cfg.get().execution
        self.assertEqual((ex.start_mode, ex.live_autobind, self.cfg.get().config_version), ("AUTO_LIVE", True, 15))
        self.assertEqual(self.mm.mode, "PAPER")                       # the manager itself does not change the mode ...
        self.assertEqual(self.mm.apply_start_mode(), "AUTO_LIVE")     # ... the runtime applies start_mode on a real terminal
        self.assertEqual(self.cfg.get().execution.mode, "AUTO_LIVE")

    def test_autobind_real_account_only(self):
        self.mm.apply_start_mode()
        self.acc = {"login": 5, "trade_mode": "DEMO"}
        self.key = "Broker-Demo:5"
        g = self.mm.gate(self.key)
        self.assertIsNone(self.mm.bound_account)
        self.assertIn("AUTO_LIVE_BUT_ACCOUNT_IS_DEMO", g["reason_codes"])
        self.acc, self.key, self.synth = {"login": 777, "trade_mode": "REAL"}, "Synth:777", True
        g = self.mm.gate(self.key)
        self.assertIsNone(self.mm.bound_account)                     # synthetic data never binds as LIVE
        self.assertIn("AUTO_LIVE_ON_SYNTHETIC_DATA", g["reason_codes"])
        self.acc, self.key, self.synth = {"login": 777, "trade_mode": "REAL"}, "Broker-Live:777", False
        g = self.mm.gate(self.key)
        self.assertEqual(self.mm.bound_account, "Broker-Live:777")
        self.assertEqual(self.cfg.get().execution.bound_account, "Broker-Live:777")
        self.assertFalse([r for r in g["reason_codes"] if r.startswith(("NO_MT5", "ACCOUNT_DIFFERS", "AUTO_LIVE_BUT"))], g["reason_codes"])
        self.key = "Broker-Live:888"
        self.assertTrue(any(r.startswith("ACCOUNT_DIFFERS") for r in self.mm.gate(self.key)["reason_codes"]))   # another account still blocks
        self.mm.set_kill(True, "test")
        self.assertIn("NEW_ENTRIES_STOPPED", self.mm.gate(self.key)["reason_codes"])                           # STOP stays

    def test_autobind_can_be_disabled(self):
        self.cfg.update({"execution": {"live_autobind": False}})
        self.mm.apply_start_mode()
        g = self.mm.gate(self.key)
        self.assertIsNone(self.mm.bound_account)
        self.assertTrue(any(r.startswith("ACCOUNT_DIFFERS") for r in g["reason_codes"]))

    def test_migration_v13_keeps_backup(self):
        from masterquo import paths
        from masterquo.config import ConfigStore
        p = paths.data_dir() / "config.json"
        p.write_text(json.dumps({"config_version": 13, "execution": {"mode": "PAPER"}}), encoding="utf-8")
        c = ConfigStore()
        self.assertEqual((c.get().config_version, c.get().execution.start_mode), (15, "AUTO_LIVE"))
        self.assertTrue((paths.data_dir() / "config.v13.bak.json").exists())


if __name__ == "__main__":
    unittest.main()


class TestConfigV15(unittest.TestCase):
    def test_v14_to_v15_resources_backup(self):
        import json
        from pathlib import Path
        from _env import TempData
        from masterquo.config import ConfigStore
        td = TempData()
        try:
            p = Path(td.dir) / "config.json"
            raw = {"config_version": 14, "execution": {"start_mode": "SIGNALS", "live_autobind": False}, "first_run_completed": True}
            p.write_text(json.dumps(raw), encoding="utf-8")
            c = ConfigStore(p).get()
            self.assertEqual((c.config_version, c.resources.profile, c.execution.start_mode), (15, "LOW_MEMORY_16GB", "SIGNALS"))
            self.assertEqual(json.loads(p.with_name("config.v14.bak.json").read_text(encoding="utf-8"))["config_version"], 14)
        finally:
            td.close()
