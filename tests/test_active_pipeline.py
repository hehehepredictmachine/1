"""Profile ACTIVE end to end on the SYNTHETIC terminal (FakeMT5): scanner -> tracker -> AUTO selector ->
decision -> risk -> AI gate -> mode gate -> PAPER gateway. The AI is stubbed; no network, no real orders."""
import unittest

import _env  # noqa: F401
from _env import TempData, core, wait_for
from test_pipeline import StubAgent


class TestActivePipeline(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        cfg, db, bus, log, fake, worker, b = core()
        self.cfg, self.db, self.b, self.worker, self.fake = cfg, db, b, worker, fake
        cfg.update({"risk": {"risk_per_trade_pct": 1.0, "max_total_open_risk_pct": 3.0, "daily_loss_limit_pct": 5.0, "max_drawdown_pct": 10.0,
                             "max_open_positions": 3},
                    "costs": {"slippage_stress_points": 5, "commission_mode": "CONFIGURED", "commission_per_lot_per_side": 3.5},
                    "news": {"enabled": False}, "clock": {"reference_url": None},
                    "active": {"profile": "ACTIVE", "cancel_after_misses": 50, "scan_min_interval_seconds": 0.5}})
        b.start()
        self.assertTrue(wait_for(lambda: b.state == "CONNECTED" and b.clock.verified and b.quote_status(), 40))
        from masterquo.data.pcclock import PCClockCheck
        from masterquo.engine.service import EngineService
        from masterquo.execution.gateway import ExecutionGateway
        from masterquo.execution.manager import PositionManager
        from masterquo.execution.modes import ModeManager
        from masterquo.execution.paper import PaperBroker
        from masterquo.news.service import NewsService
        from masterquo.secrets_store import SecretStore
        self.modes = ModeManager(cfg, db, bus, log, account_provider=lambda: (b.account_status(), b.account_key, b.synthetic))
        self.modes.set_mode("SIGNALS", account=None, account_key=None, synthetic=True)
        self.engine = EngineService(cfg, b, db, bus, log, self.modes, NewsService(cfg, SecretStore(), bus, log), PCClockCheck(None, 30))
        self.paper = PaperBroker(cfg, b, db, bus, log)
        self.gw = ExecutionGateway(cfg, b, db, bus, log, self.modes, self.engine, self.paper)
        self.mgr = PositionManager(cfg, b, db, bus, log, self.modes, self.paper)
        self.gw.manager = self.mgr
        self.engine.gateway = self.gw
        self.mgr.reconciled_epoch = b.session_epoch

    def tearDown(self):
        self.b.stop()
        self.worker.stop()
        self.td.close()

    def test_auto_selection_runs_without_ai_or_dxy_and_never_enables_orders(self):
        self.engine.full_cycle()
        st = self.engine.active.status()
        for k in ("strategy_mode", "system_state", "regime", "selected_strategy_id", "selected_strategy_version", "selection_reason_codes",
                  "candidate_ranking", "selected_at", "last_evaluated_at", "snapshot_id", "data_status"):
            self.assertIn(k, st)
        self.assertEqual(st["data_status"], "OK")
        self.assertGreaterEqual(st["scans"], 1)
        self.assertIn(st["regime"]["state"], ("TREND_UP", "TREND_DOWN", "RANGE", "COMPRESSION", "EXPANSION", "EXHAUSTION_OR_REVERSAL_CANDIDATE", "TRANSITION"))
        self.assertEqual(len(st["strategies"]), 10)
        self.assertNotEqual(st["system_state"], "STARTING")              # works with no Claude key and no DXY symbol
        d = self.engine.current_decision()
        self.assertEqual(d["profile"], "ACTIVE")
        # switching the strategy mode never touches execution
        self.cfg.update({"active": {"strategy_mode": "MANUAL", "manual_strategy_id": "S03"}})
        self.engine.full_cycle()
        self.cfg.update({"active": {"strategy_mode": "AUTO", "manual_strategy_id": None}})
        self.engine.full_cycle()
        ms = self.modes.status()
        self.assertEqual((ms["mode"], ms["auto_trading"]), ("SIGNALS", False))
        self.assertEqual(self.db.query("SELECT * FROM order_attempts"), [])

    def test_stale_after_mt5_loss_then_reconnect(self):
        self.engine.full_cycle()
        self.fake.terminal_connected = False
        self.assertTrue(wait_for(lambda: self.b.state != "CONNECTED", 30))
        self.engine.full_cycle()
        st = self.engine.active.status()
        self.assertNotEqual(st["data_status"], "OK")
        self.assertIsNone(st["selected_strategy_id"])
        self.assertFalse([r for r in self.engine.active.tracker.active("XAUUSD-", self.b.account_key) if not r["stale"]])
        self.fake.terminal_connected = True
        self.assertTrue(wait_for(lambda: self.b.state == "CONNECTED" and self.b.quote_status(), 40))
        self.assertTrue(wait_for(lambda: (self.engine.full_cycle() or True) and self.engine.active.status()["data_status"] == "OK", 30))

    def test_selected_confirmed_setup_executes_once_in_paper(self):
        self.engine.full_cycle()
        act = self.engine.active
        q = self.b.quote_status()
        bid, ask = q["bid"], q["ask"]
        cand = {"schema_version": "mq-setup-1.0.0", "strategy_id": "S01", "strategy_name": "TREND_PULLBACK", "strategy_version": "1.0.0-EXPERIMENTAL",
                "config_hash": "t", "setup_id": "MQA-test-confirmed", "event_id": "EV-test", "symbol": "XAUUSD-", "direction": "LONG", "timeframe": "M15",
                "horizon": "INTRADAY", "family": "TREND", "regime": "TREND_UP", "stage": "CONFIRMED", "phase": "TRIGGER", "setup_score": 99.0,
                "score": {"points": {}}, "strategy_fit_score": 100.0, "structure_key": "t", "anchor_time": None, "source_time": None,
                "forming_bar_used": False, "entry_plan": {"reference_price": ask, "trigger_level": ask, "zone": None, "trigger": "test"},
                "invalidation_level": bid - 9, "invalidation_rule": "CLOSE_BEYOND", "stop_loss": bid - 8,
                "targets": [{"price": ask + 12, "weight": 0.5, "basis": "T1"}, {"price": ask + 24, "weight": 0.5, "basis": "T2"}],
                "exit_rules": {}, "expires_bars": 12, "reason_codes": [], "missing_confirmations": [], "countertrend": False, "facts": {},
                "validation_status": "FUNCTIONAL_ONLY_OOS_NOT_RUN", "synthetic": True}
        from masterquo.timeutil import utcnow
        act.tracker.update([cand], view=act.view, symbol="XAUUSD-", account_key=self.b.account_key, data_ok=True, new_data=True, now=utcnow(),
                           cfg=self.cfg.get().active, scanned=set())
        act.selector.selected = {"setup_id": "MQA-test-confirmed", "strategy_id": "S01", "at": "2026-01-01T00:00:00Z"}
        rows = act.tracker.active("XAUUSD-", self.b.account_key)
        act.selector.select(rows, cfg=self.cfg.get().active, regime=act.view.regime, data_ok=True, new_data=False, now=utcnow(), snapshot_id="S",
                            account_key=self.b.account_key, per_strategy={})
        self.engine.agent = StubAgent("PASS")
        self.modes.set_mode("PAPER", confirm="PAPER", account=self.b.account_status(), account_key=self.b.account_key, synthetic=True)
        self.engine.light_cycle()
        d = self.engine.current_decision()
        self.assertEqual(d["setup"]["setup_id"], "MQA-test-confirmed")
        self.assertEqual((d["decision"], d["execution_permission"]), ("BUY", "ALLOWED"), [n for n in d["decision_tree"] if n["status"] != "PASS"])
        # strategy trade switch OFF blocks execution, scanning/display stays
        self.cfg.update({"active": {"strategies": {"S01": {"scan": True, "trade": False}}}})
        self.engine.light_cycle()
        self.assertEqual(self.engine.current_decision()["execution_permission"], "BLOCKED")
        self.cfg.update({"active": {"strategies": {"S01": {"scan": True, "trade": True}}}})
        self.engine.light_cycle()
        self.engine.light_cycle()
        att = self.db.query("SELECT * FROM order_attempts")
        self.assertEqual(len(att), 1)
        self.assertEqual(att[0]["setup_id"], "MQA-test-confirmed")
        self.assertEqual(act.tracker.get("MQA-test-confirmed")["status"], "ENTERED")
        pos = self.db.query("SELECT strategy_id FROM managed_positions") or self.db.query("SELECT * FROM paper_account")
        self.assertTrue(pos)
        # a later selection change never modifies the open position's strategy/levels
        mp = self.db.query("SELECT strategy_id, sl, tp1, tp2 FROM managed_positions")
        act.selector.reset("TEST")
        self.engine.light_cycle()
        self.assertEqual(self.db.query("SELECT strategy_id, sl, tp1, tp2 FROM managed_positions"), mp)


if __name__ == "__main__":
    unittest.main()
