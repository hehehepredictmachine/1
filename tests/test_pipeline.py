"""Canonical flow on the synthetic terminal: engine -> data gate -> lifecycle -> levels -> risk -> AI gate
-> mode gate -> decision -> AUTO -> execution gateway (PAPER). The AI is stubbed (no network)."""
import json
import unittest

import _env  # noqa: F401
from _env import TempData, core, wait_for


class StubAgent:
    def __init__(self, status="PASS"):
        self.status = status
        self.requests = []

    def gate_for(self, setup, **kw):
        if self.status == "PASS" and setup and setup["state"] == "CONFIRMED":
            return {"status": "PASS", "reason_codes": [], "agent_decision_id": "AGD-test", "expires_at": "2099-01-01T00:00:00Z"}
        return {"status": "UNAVAILABLE", "reason_codes": ["AI_UNAVAILABLE_NO_KEY"]}

    def request(self, *a, **k):
        self.requests.append((a, k))


class TestPipeline(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        cfg, db, bus, log, fake, worker, b = core()
        self.cfg, self.db, self.b, self.worker = cfg, db, b, worker
        cfg.update({"risk": {"risk_per_trade_pct": 1.0, "max_total_open_risk_pct": 3.0, "daily_loss_limit_pct": 5.0, "max_drawdown_pct": 10.0,
                             "max_open_positions": 3, "macro_block_high_impact": False},
                    "costs": {"slippage_stress_points": 5, "commission_mode": "CONFIGURED", "commission_per_lot_per_side": 3.5},
                    "news": {"enabled": False}, "clock": {"reference_url": None},
                    "active": {"profile": "ORIGINAL"}})   # this class tests the original M07/M10A path
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
        news = NewsService(cfg, SecretStore(), bus, log)
        self.engine = EngineService(cfg, b, db, bus, log, self.modes, news, PCClockCheck(None, 30))
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

    def _confirmed_setup(self):
        from masterquo.engine import lifecycle
        q = self.b.quote_status()
        bid = q["bid"]
        rule = lambda f, op, lv: {"timeframe": "M15", "field": f, "operator": op, "level": lv, "requires_closed_bar": True, "reference_evidence_id": "x"}  # noqa: E731
        plan = {"strategy_id": "XAU-S01", "version": "1.0.0-RESEARCH", "profile_name": "MVP", "setup_tf": "M15", "intended_direction": "SHORT",
                "frozen_plan_hash": "pipeline-test", "lifecycle_rules": {"qualification": rule("close", "<", bid + 1), "arming": rule("low", "<", bid + 0.8),
                                                                       "trigger": rule("low", "<", bid + 0.6), "confirmation": rule("close", "<", bid + 0.4)},
                "invalidation": {"timeframe": "M15", "condition": rule("close", ">", bid + 8), "rule": "CLOSED_BAR"}}
        rec, _ = self.engine.lifecycle.register(plan, account_key=self.b.account_key, symbol="XAUUSD-", detected_at="2099-01-01T00:00:00Z",
                                                last_closed_open=None, ttl_bars=24, synthetic=True)
        self.db.execute("UPDATE setups SET state='CONFIRMED' WHERE setup_id=?", (rec["setup_id"],))
        return rec, bid

    def test_full_chain_to_paper_execution(self):
        from masterquo.engine import service as svc
        rec, bid = self._confirmed_setup()
        # deterministic execution levels for the test (real rule needs real M03 liquidity levels)
        svc.targets.derive_levels = lambda plan, m03, atr, **kw: {
            "rule_version": "TEST", "status": "AVAILABLE", "side": "SHORT", "stop_loss": round(bid + 8.12, 2), "invalidation_level": bid + 8,
            "entry_zone": {"low": bid, "high": bid + 1}, "reasons": [],
            "targets": [{"price": round(bid - 12, 2), "weight": 0.5}, {"price": round(bid - 24, 2), "weight": 0.5}]}
        self.engine.full_cycle()
        d = self.engine.current_decision()
        self.assertEqual(d["signal_stage"], "CONFIRMED")
        self.assertEqual(d["execution_permission"], "BLOCKED")          # no AI yet, mode SIGNALS ("Analiza warunków")
        self.assertIn("EXECUTION_MODE_SIGNALS", d["reason_codes"])
        self.assertIn(self.engine.current_decision()["decision_tree"][2]["node"], "STRATEGY")
        # synthetic random walk: force the M02 structural context to match the frozen SHORT setup
        self.engine.last_full["legacy"]["m02"]["structural_direction"] = "BEARISH"
        self.engine.agent = StubAgent("PASS")
        self.modes.set_mode("PAPER", confirm="PAPER", account=self.b.account_status(), account_key=self.b.account_key, synthetic=True)
        self.engine.light_cycle()
        d = self.engine.current_decision()
        self.assertEqual(d["decision"], "SELL", json.dumps(d["decision_tree"], default=str)[:2000])
        self.assertEqual(d["execution_permission"], "ALLOWED")
        self.assertGreater(d["risk"]["lots"], 0)
        self.engine.light_cycle()                                        # PAPER = automatic simulated execution -> gateway
        att = self.db.query("SELECT * FROM order_attempts")
        self.assertEqual(len(att), 1)
        self.assertEqual(att[0]["mode"], "PAPER")
        self.assertEqual(att[0]["state"], "FILLED")
        self.assertEqual(self.engine.lifecycle.get(rec["setup_id"])["state"], "ENTERED")
        self.engine.light_cycle()                                        # no second entry
        self.assertEqual(len(self.db.query("SELECT * FROM order_attempts")), 1)
        stored = self.db.one("SELECT record_json FROM decisions WHERE decision_id=?", (d["decision_id"],))
        self.assertIsNotNone(stored)                                    # decision persisted

    def test_ai_unavailable_blocks_entry_but_shows_direction(self):
        from masterquo.engine import service as svc
        rec, bid = self._confirmed_setup()
        svc.targets.derive_levels = lambda plan, m03, atr, **kw: {
            "rule_version": "TEST", "status": "AVAILABLE", "side": "SHORT", "stop_loss": round(bid + 8.12, 2), "invalidation_level": bid + 8,
            "entry_zone": None, "reasons": [], "targets": [{"price": round(bid - 20, 2), "weight": 1.0}]}
        self.engine.agent = StubAgent("UNAVAILABLE")
        self.modes.set_mode("PAPER", confirm="PAPER", account=self.b.account_status(), account_key=self.b.account_key, synthetic=True)
        self.engine.full_cycle()
        d = self.engine.current_decision()
        self.assertEqual(d["analysis_direction"], "SHORT")
        self.assertEqual(d["execution_permission"], "BLOCKED")
        self.assertIn("AI_UNAVAILABLE_NO_KEY", d["reason_codes"])


if __name__ == "__main__":
    unittest.main()
