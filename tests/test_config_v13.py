"""1.33 config v13: a 1.32 (v12) config.json is upgraded without changing any existing value, and the untouched original is kept as
config.v12.bak.json BEFORE the new sections (indicators / families / decision) are written - 1.32 refuses unknown sections, so the
rollback restores that copy."""
import json
import unittest
from pathlib import Path

import _env  # noqa: F401
from _env import TempData


class TestConfigV13(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_v12_upgrade_keeps_values_and_rollback_copy(self):
        from masterquo import paths
        from masterquo.config import ConfigStore
        p = Path(paths.data_dir()) / "config.json"
        v12 = {"config_version": 12, "server": {"port": 8899, "open_browser": False}, "risk": {"risk_per_trade_pct": 0.7, "max_open_positions": 2},
               "mt5": {"symbol": "XAUUSD-", "dxy_symbol": None}, "first_run_completed": True}
        p.write_text(json.dumps(v12), encoding="utf-8")
        c = ConfigStore(p).get()
        self.assertEqual(c.config_version, 14)                                   # 1.39: v14 (execution.start_mode)
        self.assertEqual((c.server.port, c.risk.risk_per_trade_pct, c.risk.max_open_positions), (8899, 0.7, 2))
        bak = p.with_name("config.v12.bak.json")
        self.assertTrue(bak.exists())
        self.assertEqual(json.loads(bak.read_text(encoding="utf-8")), v12)                 # byte-for-byte the 1.32 content
        saved = json.loads(p.read_text(encoding="utf-8"))
        self.assertTrue({"indicators", "families", "decision"} <= set(saved))
        self.assertEqual(saved["decision"]["required_models"], [])                         # no REQUIRED model by default
        bak.write_text("{}", encoding="utf-8")
        ConfigStore(p)                                                                      # second start: no migration, copy untouched
        self.assertEqual(bak.read_text(encoding="utf-8"), "{}")


if __name__ == "__main__":
    unittest.main()
