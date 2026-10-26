"""Architecture audit 2026-10 (REFACTOR_PLAN.md): regression tests for defects found by the audit.

AR-01 (K): SCALPING/HEDGING ignored the user's STOP (kill switch) and the account-binding gate reasons of the shared ModeManager -
       the service read only gate()["mode"], so new SH plans kept opening in PAPER / AUTO_DEMO after STOP. Management of already
       open plans must continue (STOP = no NEW entries, positions keep their protection).
O1 (decision 2026-10-26): one primary execution path per instrument chosen by the user; the other path only analyses.
O3 (decision 2026-10-26): HEDGING on a NETTING account runs without the opposite leg (hedge event -> REDUCE), only after the REDUCE
       variant passed the replay validation on the client's own history."""
import unittest
from unittest import mock

import _env  # noqa: F401
from _env import TempData
from test_sh_service import NOW, Bridge, Log, mk_setup


class GateModes:
    def __init__(self, mode, reasons=(), kill=False):
        self.mode, self.reasons, self.kill_switch = mode, list(reasons), kill

    def gate(self, key, **kw):
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



class PrimaryPath(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.config import ConfigStore
        from masterquo.db.database import Database
        from masterquo.events import EventBus
        from masterquo.execution.modes import ModeManager
        self.cfg, self.db = ConfigStore(), Database()
        self.modes = ModeManager(self.cfg, self.db, EventBus(), Log(),
                                 account_provider=lambda: ({"trade_mode": "DEMO", "login": 1}, "srv:1", True))

    def tearDown(self):
        self.td.close()

    def test_unset_blocks_both_paths_but_not_manual_trades(self):
        self.assertEqual(self.modes.primary_path(), "UNSET")
        for path in ("ACTIVE", "SH"):
            self.assertIn("PRIMARY_PATH_NOT_SELECTED", self.modes.gate("srv:1", path=path)["reason_codes"])
        self.assertNotIn("PRIMARY_PATH_NOT_SELECTED", self.modes.gate("srv:1")["reason_codes"])     # manual pad / management

    def test_choice_allows_one_path_and_persists(self):
        from masterquo.config import ConfigStore
        st = self.modes.set_primary_path("XAUUSD", "SH")
        self.assertEqual((st["primary_path"], st["primary_paths"]["BTC"]), ("SH", "UNSET"))
        self.assertNotIn("NOT_PRIMARY_PATH_SH", self.modes.gate("srv:1", path="SH")["reason_codes"])
        self.assertIn("NOT_PRIMARY_PATH_SH", self.modes.gate("srv:1", path="ACTIVE")["reason_codes"])
        self.assertEqual(ConfigStore().get().execution.primary_path, {"XAUUSD": "SH"})               # restored after restart
        self.assertEqual(len(self.db.query("SELECT * FROM settings_audit WHERE change_json LIKE '%primary_path%'")), 1)

    def test_signals_mode_adds_no_path_reason_and_bad_input_is_refused(self):
        from masterquo.execution.modes import ModeError
        self.modes.set_mode("SIGNALS", account=None, account_key=None, synthetic=True)
        self.assertEqual([r for r in self.modes.gate("srv:1", path="SH")["reason_codes"] if "PRIMARY" in r], [])
        for inst, path in (("EURUSD", "SH"), ("XAUUSD", "BOTH")):
            with self.assertRaises(ModeError):
                self.modes.set_primary_path(inst, path)

    def test_sh_opens_plans_only_as_primary_path(self):
        t = ShStopGate("test_paper_opens_plan_when_allowed")
        t.setUp()
        try:
            from masterquo.events import EventBus
            from masterquo.execution.modes import ModeManager
            modes = ModeManager(t.cfg_store, t.db, EventBus(), Log())
            modes.set_primary_path("XAUUSD", "ACTIVE")
            svc, plans = t.run_tick(modes)
            self.assertEqual(plans, [])
            self.assertIn("NOT_PRIMARY_PATH_ACTIVE", svc.last_eval["SCALPING"].get("entry_block", []))
            self.assertEqual(svc.last_eval["SCALPING"]["status"], "READY")                       # still analysed
            modes.set_primary_path("XAUUSD", "SH")
            _svc, plans = t.run_tick(modes)
            self.assertEqual(len(plans), 1)
        finally:
            t.tearDown()



class NettingReduce(unittest.TestCase):
    def setUp(self):
        from test_sh_risk_state import Risk
        self.b = Risk("test_hedging_exposure_counts_max_hedge")          # reuse its fixtures (config, temp data dir, risk())
        self.b.setUp()

    def tearDown(self):
        self.b.tearDown()

    def risk(self, val=None, alt=None, margin_mode="NETTING"):
        from test_sh_risk_state import ACC, _setup
        prof = self.b.C.profile(self.b.cfg, "XAUUSD", "HEDGING")
        if alt:
            prof = dict(prof, hedge=dict(prof["hedge"], netting_alternative=alt))
        return self.b.risk(setup=_setup("HEDGING", sl=1996.2), prof=prof, acc=dict(ACC, margin_mode=margin_mode),
                           state={"netting_reduce_validation": val} if val else None)

    def test_validated_reduce_variant_allows_hedging_without_opposite_leg(self):
        r = self.risk(val={"ok": True, "source": "walidacja X"})
        self.assertEqual(r["status"], "PASS", r.get("reasons"))
        self.assertTrue(r["netting_reduce"])
        self.assertAlmostEqual(r["gross_exposure_after"], r["volume"])          # no hedge leg in exposure / margin
        self.assertTrue(any("REDUCE" in w for w in r["warnings"]))

    def test_blocked_without_validation_when_disabled_or_on_other_account_types(self):
        for kw, txt in ((dict(val={"ok": False, "reason": "n=3 < 30"}), "niezwalidowany"), (dict(), "niezwalidowany"),
                        (dict(val={"ok": True, "source": "x"}, alt="BLOCK"), "wyłączony"),
                        (dict(val={"ok": True, "source": "x"}, margin_mode="EXCHANGE"), "nieobsługiwany")):
            r = self.risk(**kw)
            self.assertEqual(r["status"], "BLOCK", kw)
            self.assertTrue(any("account_hedging" in x and txt in x for x in r["reasons"]), (kw, r["reasons"]))

    def test_validation_requires_client_data_sample_and_positive_result(self):
        import json
        from masterquo import paths
        from masterquo.sh.service import SHService
        d = paths.data_dir() / "sh" / "validation"
        d.mkdir(parents=True, exist_ok=True)
        f = d / "XAUUSD_HEDGING.json"
        self.assertFalse(SHService.netting_reduce_validation("XAUUSD")["ok"])                  # no report
        for kind, n, e, ok in (("SYNTHETIC_TEST", 120, 0.2, False), ("REAL_USER_DATA", 12, 0.2, False),
                               ("REAL_USER_DATA", 120, -0.05, False), ("REAL_USER_DATA", 120, 0.08, True)):
            f.write_text(json.dumps({"created_at": "2026-10-26", "dataset": {"data_kind": kind},
                                     "variants": {"REDUCE": {"n": n, "expectancy": e}}}), encoding="utf-8")
            self.assertEqual(SHService.netting_reduce_validation("XAUUSD")["ok"], ok, (kind, n, e))


if __name__ == "__main__":
    unittest.main()
