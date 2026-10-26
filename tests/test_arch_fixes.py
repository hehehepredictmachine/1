"""Architecture audit 2026-10 (REFACTOR_PLAN.md): regression tests for defects found by the audit.

AR-01 (K): SCALPING/HEDGING ignored the user's STOP (kill switch) and the account-binding gate reasons of the shared ModeManager -
       the service read only gate()["mode"], so new SH plans kept opening in PAPER / AUTO_DEMO after STOP. Management of already
       open plans must continue (STOP = no NEW entries, positions keep their protection)."""
import unittest
from unittest import mock

import _env  # noqa: F401
from _env import TempData
from test_sh_service import NOW, Bridge, Log, mk_setup


class GateModes:
    def __init__(self, mode, reasons=(), kill=False):
        self.mode, self.reasons, self.kill_switch = mode, list(reasons), kill

    def gate(self, key):
        r = list(self.reasons) + (["NEW_ENTRIES_STOPPED"] if self.kill_switch else [])
        return {"mode": self.mode, "allowed": not r, "auto_trading": not r, "kill_switch": self.kill_switch, "reason_codes": r}


def bars(n=30):
    out = []
    for i in range(n):
        t = NOW - 60 * (n - i)
        out.append({"open_utc": f"2025-10-09T08:{i:02d}:00Z", "time": t, "o": 2000.0, "h": 2000.5, "l": 1999.5, "c": 2000.2, "closed": True})
    return out


class ShStopGate(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.config import ConfigStore
        from masterquo.db.database import Database
        self.cfg_store, self.db = ConfigStore(), Database()
        self.bridge = Bridge(None, "HEDGING")
        self.bridge.bars = lambda tf, n, include_forming=False: bars()
        self.bridge.instrument = "XAUUSD"

    def tearDown(self):
        self.td.close()

    def run_tick(self, modes):
        from masterquo.sh import service as S
        svc = S.SHService(self.cfg_store, self.bridge, self.db, None, Log(), modes, clock=lambda: NOW)
        svc.instrument = lambda: "XAUUSD"
        svc.quote = lambda now: {"bid": 2000.0, "ask": 2000.2, "spread": 0.2, "age_s": 0.3, "time": now}
        spec = svc.spec(svc.account())
        su = mk_setup(spec, "SCALPING", "BUY", ref=2000.2)
        risk = {"status": "PASS", "checks": [], "warnings": [], "volume": 0.3, "legs": spec.split(0.3, su["shares"])["legs"],
                "shares_used": {"variant": "PRIMARY", "shares": su["shares"]}, "risk_money": 69.0, "basket_loss_limit_money": 69.0}
        idle = {"signal_id": "SH-IDLE", "status": "WAIT", "status_reason": "test", "strategy": "HEDGING", "side": None, "instrument": "XAUUSD",
                "symbol": spec.symbol, "created_at": NOW}
        with mock.patch.object(S.CX, "snapshot", return_value={"vol": {"atr_m5": 1.5}}), \
             mock.patch.object(S.SU, "evaluate", side_effect=lambda strat, *a, **k: dict(su) if strat == "SCALPING" else dict(idle)), \
             mock.patch.object(S.RK, "evaluate", return_value=risk), \
             mock.patch.object(S, "arbitrate", return_value=[{"strategy": "SCALPING", "decision": "PROCEED", "reason": "ok"}]):
            svc._tick()
        return svc, self.db.query("SELECT plan_id, state FROM sh_plans")

    def test_paper_opens_plan_when_allowed(self):
        _svc, plans = self.run_tick(GateModes("PAPER"))
        self.assertEqual(len(plans), 1)                                    # control: the same tick opens a plan without STOP

    def test_stop_blocks_new_sh_plans(self):
        svc, plans = self.run_tick(GateModes("PAPER", kill=True))
        self.assertEqual(plans, [])
        self.assertIn("NEW_ENTRIES_STOPPED", " ".join(svc.last_eval["SCALPING"].get("entry_block", [])))

    def test_account_binding_reasons_block_auto_demo(self):
        _svc, plans = self.run_tick(GateModes("AUTO_DEMO", reasons=["ACCOUNT_DIFFERS_FROM_CONFIRMED_x:1"]))
        self.assertEqual(plans, [])

    def test_legacy_limit_reason_does_not_block_sh(self):
        _svc, plans = self.run_tick(GateModes("PAPER", reasons=["RISK_LIMITS_NOT_CONFIGURED"]))   # SH has its own risk limits
        self.assertEqual(len(plans), 1)


if __name__ == "__main__":
    unittest.main()
