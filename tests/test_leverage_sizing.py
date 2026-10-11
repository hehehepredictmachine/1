"""1.8: leverage / exposure limit, deterministic sizing under ALL limits, per-account preferences, setup view,
pre-send re-check. Synthetic broker calculators (linear XAU: 100 oz per lot) - no assumed contract size in the code."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta

import _env  # noqa: F401
from _env import UTC, TempData, core, wait_for
from _license import AllowGuard  # noqa: E402
from test_risk_execution import LIMITS, SYM, StubEngine, levels, profit  # noqa: E402

Q = {"bid": 2000.0, "ask": 2000.2, "spread_points": 20}
# SELL at 2000: SL 2010 -> 1000 USD/lot + 17 costs; budget 1% of 10 000 = 100 -> risk cap 0.0983 lot
# notional of 1 lot = 1% move (20 USD/oz x 100 oz) x 100 = 200 000 USD; margin (test calculator) 2 000 USD/lot


def margin(s, v, p):
    return round(v * 2000.0, 2)


class TestSizing(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.config import ConfigStore
        self.cfg = ConfigStore()

    def tearDown(self):
        self.td.close()

    def ev(self, *, equity=10000.0, free=None, limit=None, acc_lev=100, portfolio=None, margin_fn=margin, profit_fn=profit, sym=None,
           buffer=None, quote=Q):
        from masterquo.risk import engine as R
        risk = dict(LIMITS, **({"min_free_margin_buffer_pct": buffer} if buffer is not None else {}))
        c = self.cfg.update({"risk": risk, "costs": {"slippage_stress_points": 5}})
        exposure = {"mode": "MANUAL" if limit else "AUTO", "limit": limit or acc_lev, "account_leverage": acc_lev, "user_limit": limit}
        return R.evaluate(side="SHORT", levels=levels("SHORT"), quote=quote, symbol_info=sym or SYM,
                          account={"equity": equity, "free_margin": equity if free is None else free, "currency": "USD"}, limits=c.risk,
                          costs_cfg=c.costs, commission={"per_lot_per_side": 3.5}, profit_fn=profit_fn, margin_fn=margin_fn, positions=[], deals=[],
                          day_start_raw=0, equity_peak=equity, open_risk_info={"open_risk": 0.0, "positions_without_sl": []}, margin_mode="HEDGING",
                          last_bot_loss_at=None, now=datetime.now(UTC), max_spread_points=None, symbol="XAUUSD-", exposure=exposure,
                          portfolio={"positions_notional": 0.0, **(portfolio or {})}, settings_version="SV-test")

    def test_lower_limit_reduces_volume(self):
        hi = self.ev(limit=30)
        self.assertEqual((hi["lots"], hi["binding_constraint"]), (0.09, "risk"))
        lo = self.ev(limit=1)
        self.assertEqual((lo["lots"], lo["binding_constraint"]), (0.05, "exposure"))   # 1 x 10 000 / 200 000
        self.assertEqual(lo["notional_per_lot"], 200000.0)
        self.assertEqual(lo["leverage"]["effective_exposure_position"], 1.0)
        self.assertEqual((lo["leverage"]["account_leverage"], lo["leverage"]["user_limit"]), (100, 1))
        self.assertEqual(lo["risk_gate"], "PASS")

    def test_higher_limit_never_raises_risk_budget_or_moves_levels(self):
        a, b = self.ev(limit=10), self.ev(limit=500, acc_lev=500)
        self.assertEqual((a["trade_budget"], a["lots"]), (b["trade_budget"], b["lots"]))
        self.assertEqual((a["stop_loss"], a["targets"]), (b["stop_loss"], b["targets"]))           # technical SL/TP unchanged
        self.assertLessEqual(a["modeled_loss"], a["available_budget"])

    def test_margin_binding_buffer_and_no_margin(self):
        r = self.ev(free=100.0)
        self.assertEqual((r["lots"], r["binding_constraint"]), (0.05, "margin"))
        r = self.ev(free=200.0, buffer=50)
        self.assertEqual(r["lots"], 0.05)                                                     # 50% buffer kept free
        r = self.ev(free=10.0)
        self.assertEqual(r["lots"], 0.0)
        self.assertIn("MIN_LOT_EXCEEDS_FREE_MARGIN", r["reason_codes"])
        self.assertEqual(r["risk_gate"], "BLOCKED")

    def test_rounding_and_min_lot_too_big(self):
        r = self.ev(sym={**SYM, "volume_step": 0.02})
        self.assertEqual(r["lots"], 0.08)                                                     # floor to step, never up
        r = self.ev(sym={**SYM, "volume_min": 0.1, "volume_step": 0.1})
        self.assertEqual(r["lots"], 0.0)
        self.assertIn("MIN_LOT_EXCEEDS_RISK_BUDGET", r["reason_codes"])
        self.assertEqual(r["risk_gate"], "BLOCKED")
        r = self.ev(equity=1000.0, limit=1)                                                   # room 1000/200000 = 0.005 < 0.01
        self.assertIn("MIN_LOT_EXCEEDS_EXPOSURE_LIMIT", r["reason_codes"])

    def test_nonlinear_rounding_rechecked_with_broker_calculator(self):
        # broker margin with a fixed component: estimate from 1 lot gives 0.07, the broker calculator says 170 > 150
        # -> the floored size is re-checked and stepped down to 0.06 (margin 150)
        r = self.ev(free=150.0, margin_fn=lambda s, v, p: round(v * 2000.0 + 30.0, 2))
        self.assertEqual(r["lots"], 0.06)
        self.assertLessEqual(r["margin_required"], 150.0)

    def test_open_positions_and_pending_orders(self):
        r = self.ev(limit=1, portfolio={"positions_notional": 15000.0})
        self.assertIn("EXPOSURE_LIMIT_ALREADY_USED", r["reason_codes"])
        self.assertEqual(r["lots"], 0.0)
        r = self.ev(portfolio={"pending_risk": 250.0})                                        # 3% cap 300 - 250 = 50 -> 0.04
        self.assertEqual(r["lots"], 0.04)
        self.assertEqual(r["total_open_risk"], 250.0)
        r = self.ev(free=200.0, portfolio={"pending_margin": 100.0})
        self.assertEqual(r["lots"], 0.05)
        r = self.ev(portfolio={"pending_count": 3})
        self.assertIn("MAX_OPEN_POSITIONS", r["reason_codes"])
        r = self.ev(portfolio={"pending_without_sl": [123]})
        self.assertIn("PENDING_ORDER_WITHOUT_SL_RISK_UNBOUNDED", r["reason_codes"])

    def test_zero_equity_no_data_lost_connection(self):
        r = self.ev(equity=0.0)
        self.assertIn("EQUITY_NOT_POSITIVE", r["reason_codes"])
        self.assertEqual(r["risk_gate"], "BLOCKED")
        r = self.ev(quote=None)
        self.assertEqual(r["reason_codes"], ["QUOTE_OR_SYMBOL_OR_ACCOUNT_UNAVAILABLE"])
        r = self.ev(margin_fn=lambda s, v, p: None)                                           # terminal call failed
        self.assertIn("BROKER_MARGIN_CALC_UNAVAILABLE", r["reason_codes"])
        self.assertEqual(r["risk_gate"], "BLOCKED")
        r = self.ev(limit=10, portfolio={"positions_notional": None})                          # positions not valued -> no guess
        self.assertIn("EXPOSURE_NOT_COMPUTABLE", r["reason_codes"])
        self.assertEqual(r["lots"], 0.0)


class FakeBridge:
    def __init__(self, key="Srv-A:1", lev=100):
        self.account_key = key
        self.account = {"leverage": lev}

    def account_status(self):
        return dict(self.account)


class TestPrefs(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.config import ConfigStore
        from masterquo.db.database import Database
        self.cfg, self.db = ConfigStore(), Database()

    def tearDown(self):
        self.td.close()

    def test_leverage_validation_three_values_and_per_account(self):
        from masterquo.prefs import AccountPrefs, PrefsError
        br = FakeBridge()
        p = AccountPrefs(self.db, br, self.cfg)
        self.assertEqual(p.exposure_limit()["limit"], 100)                       # AUTO = account leverage from MT5
        v0 = p.settings_version()
        with self.assertRaises(PrefsError):
            p.set("leverage", {"mode": "MANUAL", "limit": 200})                  # above the account leverage
        with self.assertRaises(PrefsError):
            p.set("leverage", {"mode": "MANUAL", "limit": 0})
        p.set("leverage", {"mode": "MANUAL", "limit": 20})
        e = p.exposure_limit()
        self.assertEqual((e["account_leverage"], e["user_limit"], e["limit"]), (100, 20, 20))
        self.assertIn("nie zmienia dźwigni u brokera", e["note"])
        self.assertNotEqual(p.settings_version(), v0)                             # any change invalidates older calculations
        br.account_key = "Srv-B:2"                                                # another account (server:login)
        self.assertEqual(p.get("leverage")["mode"], "AUTO")
        br.account_key = "Srv-A:1"
        self.assertEqual(AccountPrefs(self.db, br, self.cfg).get("leverage")["limit"], 20)   # restart keeps it

    def test_setup_view_validation_and_persistence(self):
        from masterquo.prefs import AccountPrefs, PrefsError
        p = AccountPrefs(self.db, FakeBridge(), self.cfg)
        self.assertEqual(p.get("setup_view")["mode"], "AUTO")
        with self.assertRaises(PrefsError):
            p.set("setup_view", {"mode": "SELECTED", "strategy_id": "S99"})        # only strategies from the registry
        p.set("setup_view", {"mode": "SELECTED", "strategy_id": "S11"})
        self.assertEqual(AccountPrefs(self.db, FakeBridge(), self.cfg).get("setup_view"), {"mode": "SELECTED", "strategy_id": "S11", "focus_setup_id": None})
        p.set("setup_view", {"mode": "ALL", "focus_setup_id": "MQA-x"})
        self.assertEqual(p.get("setup_view")["focus_setup_id"], "MQA-x")

    def test_selected_strategy_drives_selector_without_forcing(self):
        from masterquo.engine.active import ActiveEngine
        from masterquo.prefs import AccountPrefs
        act = ActiveEngine.__new__(ActiveEngine)
        act.prefs = AccountPrefs(self.db, FakeBridge(), self.cfg)
        ac = self.cfg.get().active
        self.assertEqual(act.selection_cfg(ac).strategy_mode, "AUTO")
        act.prefs.set("setup_view", {"mode": "SELECTED", "strategy_id": "S03"})
        sc = act.selection_cfg(ac)
        self.assertEqual((sc.strategy_mode, sc.manual_strategy_id), ("MANUAL", "S03"))
        act.prefs.set("setup_view", {"mode": "ALL"})
        self.assertEqual(act.selection_cfg(ac).strategy_mode, "AUTO")             # ALL: engine stays automatic
        # the selector with no detected S03 setup selects nothing - a choice never creates a setup
        from masterquo.strategies.selector import StrategyAutoSelector
        sel = StrategyAutoSelector(self.db)
        st = sel.select([], cfg=act.selection_cfg(ac.model_copy(update={})) if False else sc, regime={}, data_ok=True, new_data=True,
                        now=datetime.now(UTC), snapshot_id=None, account_key=None, per_strategy={})
        self.assertIsNone(st["selected"])


class SettingsEngine(StubEngine):
    def __init__(self, lifecycle, prefs, fresh):
        super().__init__(lifecycle)
        self.prefs = prefs
        self.fresh = fresh

    def recheck_risk(self, d):
        return self.fresh


class TestPreSendRecheck(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        cfg, db, bus, log, fake, worker, b = core()
        self.cfg, self.db, self.fake, self.worker, self.b = cfg, db, fake, worker, b
        cfg.update({"risk": LIMITS, "costs": {"slippage_stress_points": 5}})
        b.start()
        self.assertTrue(wait_for(lambda: b.state == "CONNECTED" and b.quote_status() and b.symbol_info, 40))
        from masterquo.engine.lifecycle import LifecycleStore
        from masterquo.execution.gateway import ExecutionGateway
        from masterquo.execution.manager import PositionManager
        from masterquo.execution.modes import ModeManager
        from masterquo.execution.paper import PaperBroker
        from masterquo.prefs import AccountPrefs
        self.modes = ModeManager(cfg, db, bus, log, account_provider=lambda: (b.account_status(), b.account_key, b.synthetic))
        acct = b.account_status()
        self.modes.set_mode("AUTO_DEMO", confirm=str(acct["login"]), account=acct, account_key=b.account_key, synthetic=True)
        self.prefs = AccountPrefs(db, b, cfg)
        self.engine = SettingsEngine(LifecycleStore(db), self.prefs, {"risk_gate": "PASS", "lots": 0.05})
        self.gw = ExecutionGateway(cfg, b, db, bus, log, self.modes, self.engine, PaperBroker(cfg, b, db, bus, log))
        self.gw.license = AllowGuard()
        mgr = PositionManager(cfg, b, db, bus, log, self.modes, None)
        mgr.reconciled_epoch = b.session_epoch
        self.gw.manager = mgr

    def tearDown(self):
        self.b.stop()
        self.worker.stop()
        self.td.close()

    def decision(self, version):
        e = self.b.quote_status()["bid"]
        return {"decision_id": "MQD-9", "execution_permission": "ALLOWED", "expires_at_utc": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
                "account_key": self.b.account_key, "session_epoch": self.b.session_epoch, "symbol": "XAUUSD-", "analysis_direction": "SHORT",
                "reason_codes": [], "setup": {"setup_id": "MQS-LV", "state": "CONFIRMED", "strategy_id": "S01"},
                "risk": {"risk_gate": "PASS", "lots": 0.05, "entry": e, "stop_loss": round(e + 8, 2), "settings_version": version,
                         "targets": [{"price": round(e - 6, 2), "weight": 1.0}], "modeled_loss": 41.0}}

    def test_changed_settings_or_smaller_size_block_the_send(self):
        sent = []
        orig = self.fake.order_send
        self.fake.order_send = lambda r: sent.append(r) or orig(r)
        v = self.prefs.settings_version()
        self.engine.decision = self.decision(v)
        self.prefs.set("leverage", {"mode": "MANUAL", "limit": 10})             # user lowers the limit after the decision
        r = self.gw.execute("MQD-9")
        self.assertEqual(r["status"], "BLOCKED")
        self.assertIn("SETTINGS_CHANGED_RECALC", r["reason"])
        self.engine.decision = self.decision(self.prefs.settings_version())
        self.engine.fresh = {"risk_gate": "PASS", "lots": 0.02}                 # fresh limits allow less than planned
        r = self.gw.execute("MQD-9")
        self.assertIn("LIMITS_CHANGED_SIZE_SMALLER_RECALC", r["reason"])
        self.engine.fresh = {"risk_gate": "BLOCKED", "lots": 0, "reason_codes": ["MIN_LOT_EXCEEDS_FREE_MARGIN"]}
        r = self.gw.execute("MQD-9")
        self.assertIn("RISK_RECHECK_FAILED", r["reason"])
        self.assertEqual(sent, [])                                               # nothing reached the broker
        self.engine.fresh = {"risk_gate": "PASS", "lots": 0.05}
        r = self.gw.execute("MQD-9")
        self.assertEqual(r["status"], "FILLED", r)                               # order_check + order_send path still works


if __name__ == "__main__":
    unittest.main()
