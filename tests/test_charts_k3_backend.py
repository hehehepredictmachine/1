"""CHARTS 1:1 (pakiet update_charts, K3 – decyzja użytkownika): poziomy planu sygnału SH zapisywane razem z sygnałem (wejście, SL, TP1–TP3
z udziałami, RR netto, BE, horyzont) i zwracane przez GET /api/v1/sh/signals razem z wynikiem planu; stare wiersze bez poziomów → null."""
from __future__ import annotations

import unittest

import _env  # noqa: F401
from _env import TempData


def ready(sid="SH-K3-1", **kw):
    s = {"signal_id": sid, "strategy": "SCALPING", "instrument": "XAUUSD", "symbol": "XAUUSD-", "side": "BUY", "status": "READY",
         "status_reason": "ok", "created_at": 1795009320.0, "valid_until": 1795009920.0, "config_hash": "h", "entry_ref": 4050.5, "sl": 4049.0,
         "tps": [{"name": "TP1", "price": 4053.0, "share": 0.5}, {"name": "TP2", "price": 4053.5, "share": 0.3}, {"name": "TP3", "price": 4055.5, "share": 0.2}],
         "shares": [0.5, 0.3, 0.2], "net_rr": 1.514, "be": {"after": "TP2", "rule": "ENTRY_PLUS_COSTS"}, "horizon_minutes": 30, "position_max_minutes": 90}
    s.update(kw)
    return s


class TestSHSignalLevels(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.db.database import Database
        from masterquo.sh.store import SHStore
        db = Database()
        db.migrate()
        self.store = SHStore(db)

    def tearDown(self):
        self.td.close()

    def rows(self):
        return {r["signal_id"]: r for r in self.store.signals_with_levels(self.store.recent_signals(limit=50))}

    def test_ready_signal_keeps_levels_and_list_returns_them(self):
        self.store.save_signal(ready())
        r = self.rows()["SH-K3-1"]
        L = r["levels"]
        self.assertEqual((L["side"], L["entry"], L["sl"], L["net_rr"], L["be_after"], L["horizon_minutes"]), ("BUY", 4050.5, 4049.0, 1.514, "TP2", 30))
        self.assertEqual([(t["name"], t["price"], t["share"]) for t in L["targets"]], [("TP1", 4053.0, 0.5), ("TP2", 4053.5, 0.3), ("TP3", 4055.5, 0.2)])
        self.assertIsNone(r["plan"])

    def test_levels_survive_status_change_and_are_never_invented(self):
        self.store.save_signal(ready())
        self.store.save_signal(ready(status="EXPIRED", status_reason="TTL"))       # later update without a plan keeps the stored levels
        self.assertEqual(self.rows()["SH-K3-1"]["levels"]["entry"], 4050.5)
        self.store.save_signal(ready("SH-K3-2", status="WAIT", entry_ref=None, sl=None, tps=[]))
        self.assertIsNone(self.rows()["SH-K3-2"]["levels"])                         # no plan in the setup -> null, nothing reconstructed
        self.store.db.execute("UPDATE sh_signals SET levels=NULL WHERE signal_id='SH-K3-1'")   # old row from before the migration
        self.assertIsNone(self.rows()["SH-K3-1"]["levels"])

    def test_plan_outcome_joined(self):
        self.store.save_signal(ready())
        self.store.create_plan({"plan_id": "PLN-K3", "signal_id": "SH-K3-1", "strategy": "SCALPING", "instrument": "XAUUSD", "symbol": "XAUUSD-",
                                "side": "BUY", "exec_mode": "PAPER", "config_hash": "h"})
        self.store.update_plan("PLN-K3", state="CLOSED", result={"r_multiple": 0.8}, now=1795010000.0)
        p = self.rows()["SH-K3-1"]["plan"]
        self.assertEqual((p["plan_id"], p["state"], p["closed_at"], p["r_multiple"], p["tp_done"]), ("PLN-K3", "CLOSED", 1795010000.0, 0.8, []))


if __name__ == "__main__":
    unittest.main()
