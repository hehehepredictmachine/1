"""Risk engine (M11 port), decision separation, modes, execution gateway, reconciliation, stats."""
import unittest
from datetime import datetime, timedelta

import _env  # noqa: F401
from _env import UTC, TempData, core, wait_for

LIMITS = {"risk_per_trade_pct": 1.0, "max_total_open_risk_pct": 3.0, "daily_loss_limit_pct": 5.0, "max_drawdown_pct": 10.0, "max_open_positions": 3}
SYM = {"point": 0.01, "trade_stops_level": 10, "trade_mode": 4, "volume_min": 0.01, "volume_max": 100.0, "volume_step": 0.01}


def profit(side, vol, o, c):  # linear XAU: 100 oz per lot
    return round((c - o if side == "BUY" else o - c) * 100 * vol, 2)


def levels(side="SHORT"):
    if side == "SHORT":
        return {"status": "AVAILABLE", "stop_loss": 2010.0, "targets": [{"price": 1980.0, "weight": 0.5}, {"price": 1970.0, "weight": 0.5}]}
    return {"status": "AVAILABLE", "stop_loss": 1990.0, "targets": [{"price": 2015.0, "weight": 0.5}, {"price": 2025.0, "weight": 0.5}]}


class TestRisk(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.config import ConfigStore
        self.cfg = ConfigStore()

    def tearDown(self):
        self.td.close()

    def ev(self, equity=10000.0, side="SHORT", comm=3.5, positions=None, deals=None, margin_mode="HEDGING", lim=True, slip=5):
        from masterquo.risk import engine as R
        c = self.cfg.update({"risk": LIMITS if lim else {}, "costs": {"slippage_stress_points": slip}}).model_copy()
        q = {"bid": 2000.0, "ask": 2000.2, "spread_points": 20}
        return R.evaluate(side=side, levels=levels(side), quote=q, symbol_info=SYM,
                          account={"equity": equity, "free_margin": equity, "currency": "USD"}, limits=c.risk, costs_cfg=c.costs,
                          commission={"per_lot_per_side": comm}, profit_fn=profit, margin_fn=lambda s, v, p: v * 2000.0 / 100,
                          positions=positions or [], deals=deals or [], day_start_raw=0, equity_peak=equity,
                          open_risk_info={"open_risk": 0.0, "positions_without_sl": []}, margin_mode=margin_mode,
                          last_bot_loss_at=None, now=datetime.now(UTC), max_spread_points=None, symbol="XAUUSD-")

    def test_spread_not_double_counted_and_rr_net(self):
        r = self.ev()
        # SELL at Bid 2000.0 -> SL 2010 = 10.0 *100 = 1000/lot; commission 7, slippage 2*5pts*0.01*100 = 10
        self.assertEqual(r["entry"], 2000.0)
        self.assertEqual(r["per_lot"]["stop_loss_gross"], 1000.0)
        self.assertEqual(r["per_lot"]["commission_roundtrip"], 7.0)
        self.assertAlmostEqual(r["per_lot"]["slippage_stress"], 10.0)
        exp = (0.5 * 2000 + 0.5 * 3000 - 17) / (1000 + 17)
        self.assertAlmostEqual(r["rr_net"], round(exp, 3))
        self.assertEqual(r["risk_gate"], "PASS")
        self.assertEqual(r["lots"], 0.09)  # floor(100 / 1017 = 0.0983) to step 0.01

    def test_min_lot_never_rounded_up(self):
        r = self.ev(equity=500.0)  # budget 5 USD < loss of 0.01 lot (10.17)
        self.assertEqual(r["lots"], 0.0)
        self.assertIn("SIZE_BELOW_BROKER_MIN_LOT", r["reason_codes"])
        self.assertEqual(r["risk_gate"], "BLOCKED")

    def test_limits_missing_blocks_but_rr_visible(self):
        r = self.ev(lim=False)
        self.assertEqual(r["risk_gate"], "BLOCKED")
        self.assertIn("RISK_LIMITS_NOT_CONFIGURED", r["reason_codes"])
        self.assertIsNotNone(r["rr_net"])

    def test_unknown_commission_and_slippage_block(self):
        r = self.ev(comm=None, slip=None)
        self.assertIn("COST_MODEL_UNKNOWN_COMMISSION", r["reason_codes"])
        self.assertIn("SLIPPAGE_STRESS_NOT_CONFIGURED", r["reason_codes"])
        self.assertEqual(r["risk_gate"], "BLOCKED")
        self.assertFalse(r["rr_complete"])

    def test_netting_existing_position_blocks(self):
        r = self.ev(margin_mode="NETTING", positions=[{"symbol": "XAUUSD-", "profit": 0, "swap": 0}])
        self.assertIn("NETTING_ACCOUNT_EXISTING_POSITION_ON_SYMBOL", r["reason_codes"])

    def test_daily_loss_excludes_balance_operations(self):
        from masterquo.risk.engine import daily_loss_used
        deals = [{"type": 2, "entry": 0, "time": 10, "profit": 5000},          # deposit - not P/L
                 {"type": 1, "entry": 1, "time": 10, "profit": -120, "commission": -7, "swap": 0, "fee": 0}]
        d = daily_loss_used(deals, 0, floating=50.0)  # floating profit never enlarges the limit
        self.assertEqual(d["realized_today"], -127.0)
        self.assertEqual(d["used"], 127.0)

    def test_rr_thresholds(self):
        from masterquo.risk import engine as R

        def run(**risk):
            base = {"rr_block_below": 1.0, "rr_pass_from": 1.5, "conditional_rr_executes": True, "conditional_risk_factor": 0.5}
            c = self.cfg.update({"risk": {**LIMITS, **base, **risk}, "costs": {"slippage_stress_points": 0}})
            lv = {"status": "AVAILABLE", "stop_loss": 2010.0, "targets": [{"price": 1988.0, "weight": 1.0}]}  # RR 1.2
            return R.evaluate(side="SHORT", levels=lv, quote={"bid": 2000.0, "ask": 2000.2}, symbol_info=SYM, account={"equity": 1e4, "free_margin": 1e4},
                              limits=c.risk, costs_cfg=c.costs, commission={"per_lot_per_side": 0.0}, profit_fn=profit, margin_fn=lambda *a: 1.0,
                              positions=[], deals=[], day_start_raw=0, equity_peak=1e4, open_risk_info={"open_risk": 0, "positions_without_sl": []},
                              margin_mode="HEDGING", last_bot_loss_at=None, now=datetime.now(UTC), max_spread_points=None, symbol="XAUUSD-")
        # default (relaxed): 1.0 <= RR < 1.5 executes with half the risk budget
        r = run()
        self.assertTrue(1.0 <= r["rr_net"] < 1.5, r["rr_net"])
        self.assertEqual(r["risk_gate"], "PASS", r["reason_codes"])
        self.assertEqual(r["risk_factor"], 0.5)
        full = run(conditional_risk_factor=1.0)
        self.assertAlmostEqual(r["lots"], full["lots"] / 2, delta=0.011)
        # original M11 policy is still available
        self.assertEqual(run(rr_block_below=1.0, rr_pass_from=2.0, conditional_rr_executes=False)["risk_gate"], "CONDITIONAL")
        self.assertEqual(run(rr_block_below=1.5, rr_pass_from=2.0)["risk_gate"], "BLOCKED")
        self.assertEqual(run(rr_block_below=1.0, rr_pass_from=1.1)["risk_factor"], 1.0)        # RR 1.2 >= pass threshold -> full risk
        self.assertEqual(run(conditional_rr_executes=False)["risk_factor"], 1.0)


class TestDecisionSeparation(unittest.TestCase):
    def build(self, setup_state="EARLY_SETUP", risk_gate="PASS", ai="PASS", mode_allowed=False, dq_entries=True):
        from masterquo.config import AppConfig
        from masterquo.engine import decision
        cfg = AppConfig()
        dq = {"analysis_allowed": True, "entries_allowed": dq_entries, "reason_codes": [], "market_state": "OPEN", "data_quality": "GOOD"}
        setup = {"setup_id": "MQS-1", "state": setup_state, "signal_stage": {"CONFIRMED": "CONFIRMED", "INVALIDATED": "INVALIDATED"}.get(setup_state, "EARLY"),
                 "direction": "SHORT", "strategy_id": "XAU-S01", "profile": "MVP", "setup_tf": "M15"}
        return decision.build(snapshot_id="S", as_of="2026-10-08T12:00:00Z", symbol="XAUUSD-", account_key="a", session_epoch=1, dq=dq,
                              legacy={"m02": {"structural_direction": "BEARISH", "timeframes": {"D1": {"direction": "BULLISH"}}}},
                              setup=setup, levels={}, risk={"risk_gate": risk_gate, "reason_codes": []}, agent_gate={"status": ai, "reason_codes": []},
                              mode_gate={"mode": "DEMO_EXECUTION" if mode_allowed else "READ_ONLY", "allowed": mode_allowed, "reason_codes": []},
                              macro={"status": "PARTIAL", "risk_level": "NONE"}, strategy_cfg=cfg.strategy, risk_cfg=cfg.risk, dxy_status="NOT_CONFIGURED", synthetic=True)

    def test_early_is_not_execution(self):
        d = self.build("EARLY_SETUP", mode_allowed=True)
        self.assertEqual(d["analysis_direction"], "SHORT")
        self.assertEqual(d["signal_stage"], "EARLY")
        self.assertEqual(d["decision"], "WAIT")
        self.assertEqual(d["execution_permission"], "BLOCKED")

    def test_confirmed_but_read_only(self):
        d = self.build("CONFIRMED", mode_allowed=False)
        self.assertEqual(d["decision"], "SELL")
        self.assertEqual(d["execution_permission"], "BLOCKED")
        self.assertTrue(d["structure"]["d1_conflict"])  # described, not blocking by default

    def test_confirmed_and_allowed(self):
        self.assertEqual(self.build("CONFIRMED", mode_allowed=True)["execution_permission"], "ALLOWED")

    def test_ai_or_risk_failure_blocks(self):
        self.assertEqual(self.build("CONFIRMED", ai="UNAVAILABLE", mode_allowed=True)["execution_permission"], "BLOCKED")
        d = self.build("CONFIRMED", risk_gate="BLOCKED", mode_allowed=True)
        self.assertEqual(d["decision"], "NO_TRADE")
        self.assertEqual(self.build("CONFIRMED", dq_entries=False, mode_allowed=True)["execution_permission"], "BLOCKED")


class StubEngine:
    def __init__(self, lifecycle):
        self.decision = None
        self.lifecycle = lifecycle

    def current_decision(self):
        return self.decision

    def mark_entered(self, setup_id, reason):
        self.lifecycle.terminate(setup_id, "ENTERED", reason)


class TestExecution(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        cfg, db, bus, log, fake, worker, b = core()
        self.cfg, self.db, self.bus, self.log, self.fake, self.worker, self.b = cfg, db, bus, log, fake, worker, b
        cfg.update({"risk": LIMITS, "costs": {"slippage_stress_points": 5}})
        b.start()
        self.assertTrue(wait_for(lambda: b.state == "CONNECTED" and b.quote_status() and b.symbol_info, 40))
        from masterquo.engine.lifecycle import LifecycleStore
        from masterquo.execution.gateway import ExecutionGateway
        from masterquo.execution.manager import PositionManager
        from masterquo.execution.modes import ModeManager
        from masterquo.execution.paper import PaperBroker
        self.modes = ModeManager(cfg, db, bus, log)
        self.engine = StubEngine(LifecycleStore(db))
        self.paper = PaperBroker(cfg, b, db, bus, log)
        self.gw = ExecutionGateway(cfg, b, db, bus, log, self.modes, self.engine, self.paper)
        self.mgr = PositionManager(cfg, b, db, bus, log, self.modes, self.paper)
        self.gw.manager = self.mgr
        self.mgr.reconciled_epoch = b.session_epoch

    def tearDown(self):
        self.b.stop()
        self.worker.stop()
        self.td.close()

    def decision(self, did="MQD-1", setup_id="MQS-T1"):
        q = self.b.quote_status()
        e = q["bid"]
        return {"decision_id": did, "execution_permission": "ALLOWED", "expires_at_utc": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
                "account_key": self.b.account_key, "session_epoch": self.b.session_epoch, "symbol": "XAUUSD-", "analysis_direction": "SHORT",
                "reason_codes": [], "setup": {"setup_id": setup_id, "state": "CONFIRMED", "strategy_id": "XAU-S01"},
                "risk": {"risk_gate": "PASS", "lots": 0.05, "entry": e, "stop_loss": round(e + 8, 2),
                         "targets": [{"price": round(e - 6, 2), "weight": 0.5}, {"price": round(e - 12, 2), "weight": 0.5}], "modeled_loss": 41.0}}

    def test_read_only_blocks_real_orders(self):
        self.engine.decision = self.decision()
        calls = []
        orig = self.fake.order_send
        self.fake.order_send = lambda r: calls.append(r) or orig(r)
        r = self.gw.execute("MQD-1")
        self.assertEqual(r["status"], "BLOCKED")
        self.assertIn("READ_ONLY_MODE", r["reason"])
        self.assertEqual(calls, [])

    def test_mode_requires_confirmation_and_limits(self):
        from masterquo.execution.modes import ModeError
        acct = self.b.account_status()
        with self.assertRaises(ModeError):
            self.modes.set_mode("DEMO_EXECUTION", confirm="wrong", account=acct, account_key=self.b.account_key, synthetic=True)
        with self.assertRaises(ModeError):
            self.modes.set_mode("LIVE_EXECUTION", confirm=f"LIVE {acct['login']}", account=acct, account_key=self.b.account_key, synthetic=True)
        self.modes.set_mode("DEMO_EXECUTION", confirm=str(acct["login"]), account=acct, account_key=self.b.account_key, synthetic=True)
        self.assertFalse(self.modes.status()["auto_trading"])
        self.modes.reset("ACCOUNT_CHANGED")
        self.assertEqual(self.modes.status()["mode"], "READ_ONLY")

    def test_paper_never_calls_order_send_and_is_idempotent(self):
        self.modes.set_mode("PAPER", confirm="PAPER", account=self.b.account_status(), account_key=self.b.account_key, synthetic=True)
        self.engine.decision = self.decision()
        calls = []
        self.fake.order_send = lambda r: calls.append(r)
        r1 = self.gw.execute("MQD-1")
        r2 = self.gw.execute("MQD-1")   # double click
        self.assertEqual(r1["status"], "FILLED")
        self.assertTrue(r1["paper"])
        self.assertEqual(r2["status"], "DUPLICATE")
        self.assertEqual(calls, [])
        self.assertEqual(len(self.db.query("SELECT * FROM managed_positions WHERE mode='PAPER'")), 1)

    def test_demo_execution_once_with_sl_tp_and_restart(self):
        acct = self.b.account_status()
        self.modes.set_mode("DEMO_EXECUTION", confirm=str(acct["login"]), account=acct, account_key=self.b.account_key, synthetic=True)
        self.engine.decision = self.decision()
        r = self.gw.execute("MQD-1")
        self.assertEqual(r["status"], "FILLED", r)
        pos = self.fake.positions_get()
        self.assertEqual(len(pos), 1)
        self.assertGreater(pos[0].sl, pos[0].price_open)  # SHORT: SL above entry
        self.assertLess(pos[0].tp, pos[0].price_open)
        # a new gateway instance over the same DB (= restart) refuses the same setup again
        from masterquo.execution.gateway import ExecutionGateway
        gw2 = ExecutionGateway(self.cfg, self.b, self.db, self.bus, self.log, self.modes, self.engine, self.paper)
        gw2.manager = self.mgr
        self.assertEqual(gw2.execute("MQD-1")["status"], "DUPLICATE")
        self.assertEqual(len(self.fake.positions_get()), 1)

    def test_timeout_unknown_no_resend_then_reconciled(self):
        acct = self.b.account_status()
        self.modes.set_mode("DEMO_EXECUTION", confirm=str(acct["login"]), account=acct, account_key=self.b.account_key, synthetic=True)
        self.engine.decision = self.decision(setup_id="MQS-T2")
        orig = self.fake.order_send
        sent = []

        def flaky(req):
            sent.append(req)
            orig(req)                    # the broker executes...
            raise TimeoutError("lost")   # ...but the answer never arrives
        self.fake.order_send = flaky
        r = self.gw.execute("MQD-1")
        self.assertEqual(r["status"], "UNKNOWN")
        self.assertEqual(self.gw.execute("MQD-1")["status"], "DUPLICATE")
        self.assertEqual(len(sent), 1)  # never re-sent
        self.b._t_account = 0
        self.b._t_hist = 0
        self.assertTrue(wait_for(lambda: bool(self.b.positions), 15))
        self.mgr.tick()
        st = self.db.one("SELECT state FROM order_attempts WHERE setup_id='MQS-T2'")["state"]
        self.assertEqual(st, "FILLED")

    def test_tp1_partial_and_breakeven_demo_and_paper(self):
        acct = self.b.account_status()
        self.modes.set_mode("DEMO_EXECUTION", confirm=str(acct["login"]), account=acct, account_key=self.b.account_key, synthetic=True)
        d = self.decision(setup_id="MQS-TP")
        d["risk"]["lots"] = 0.10
        self.engine.decision = d
        self.assertEqual(self.gw.execute("MQD-1")["status"], "FILLED")
        q = self.b.quote_status()
        # put TP1 just above the market for the SHORT so it is "reached" now
        self.db.execute("UPDATE managed_positions SET tp1=? WHERE mode='DEMO_EXECUTION'", (q["ask"] + 1.0,))
        self.b._t_account = 0
        self.assertTrue(wait_for(lambda: bool(self.b.positions), 10))
        self.mgr.tick()
        self.b._t_account = 0
        self.assertTrue(wait_for(lambda: self.b.positions and abs(self.b.positions[0]["volume"] - 0.05) < 1e-9, 10))
        self.mgr.tick()
        mp = self.db.one("SELECT * FROM managed_positions WHERE mode='DEMO_EXECUTION'")
        self.assertEqual(mp["tp1_done"], 1)
        self.assertEqual(mp["be_done"], 1)
        self.assertAlmostEqual(self.fake.positions_get()[0].sl, mp["entry_price"])
        # PAPER (commission configured explicitly; unknown commission is blocked earlier by the risk gate)
        self.cfg.update({"costs": {"commission_mode": "CONFIGURED", "commission_per_lot_per_side": 3.5}})
        self.modes.set_mode("PAPER", confirm="PAPER", account=acct, account_key=self.b.account_key, synthetic=True)
        d = self.decision(setup_id="MQS-TP-P")
        d["risk"]["lots"] = 0.10
        self.engine.decision = d
        self.assertEqual(self.gw.execute("MQD-1")["status"], "FILLED")
        self.db.execute("UPDATE managed_positions SET tp1=? WHERE mode='PAPER'", (self.b.quote_status()["ask"] + 1.0,))
        self.mgr.tick()
        mp = self.db.one("SELECT * FROM managed_positions WHERE mode='PAPER'")
        self.assertAlmostEqual(mp["volume_open"], 0.05)
        self.assertEqual(mp["sl"], mp["entry_price"])
        t = self.db.one("SELECT * FROM trades WHERE mode='PAPER'")
        self.assertIsNotNone(t)
        self.assertLess(t["commission"], 0)  # commission included, entry side once

    def test_broker_rejection_recorded(self):
        acct = self.b.account_status()
        self.modes.set_mode("DEMO_EXECUTION", confirm=str(acct["login"]), account=acct, account_key=self.b.account_key, synthetic=True)
        self.engine.decision = self.decision(setup_id="MQS-T3")
        self.fake.fail_next_order = 10019
        r = self.gw.execute("MQD-1")
        self.assertEqual(r["status"], "REJECTED")
        self.assertEqual(self.db.one("SELECT retcode FROM order_attempts WHERE setup_id='MQS-T3'")["retcode"], 10019)

    def test_expired_or_superseded_decision_rejected(self):
        self.modes.set_mode("PAPER", confirm="PAPER", account=self.b.account_status(), account_key=self.b.account_key, synthetic=True)
        d = self.decision()
        d["expires_at_utc"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        self.engine.decision = d
        self.assertIn("EXPIRED", self.gw.execute("MQD-1")["reason"])
        self.engine.decision = self.decision(did="MQD-2")
        self.assertIn("SUPERSEDED", self.gw.execute("MQD-1")["reason"])


class TestStats(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_no_demo_numbers_and_balance_ops_separate(self):
        from masterquo import stats
        from masterquo.db.database import Database
        db = Database()
        s = stats.bot_stats(db, "PAPER")
        self.assertEqual(s["all"]["trades"], 0)
        self.assertIsNone(s["all"]["win_rate"])
        self.assertEqual(stats.equity_curve(db, "PAPER", None)["status"], "NO_DATA")
        a = stats.account_stats([{"type": 2, "profit": 1000}, {"type": 0, "entry": 1, "symbol": "XAUUSD-", "profit": -5, "commission": -1}], "XAUUSD-", 0)
        self.assertEqual(a["trading_net_all_symbols"], -6.0)
        self.assertEqual(a["balance_operations"], 1000.0)


class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_migrations_and_backup(self):
        from masterquo import paths
        from masterquo.db.database import Database
        db = Database()
        self.assertEqual(db.schema_versions(), ["0001", "0002"])
        db.execute("INSERT INTO app_events(ts, level, category, code, message) VALUES ('t','INFO','T','C','m')")
        p = db.backup("test")
        self.assertTrue(p.exists())
        db2 = Database()  # reopen = restart: data persisted, no re-migration
        self.assertEqual(db2.one("SELECT COUNT(*) AS n FROM app_events")["n"], 1)
        self.assertTrue(list(paths.backups_dir().glob("*.sqlite")))


if __name__ == "__main__":
    unittest.main()
