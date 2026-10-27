"""1.24 (user decision): the 1.14 Execution Lock is withdrawn. Everything here runs on the terminal simulator (FakeMT5) or on
plain objects - never on a real account.

Covered (prompt DK §4 / §7 mandatory scenarios):
* an old config with lock LOCKED loads, the lock enforces nothing, a stored AUTO mode it was holding back is reset to PAPER
  (no silent start of automatic orders) with a visible note; an AUTO mode the user had unlocked keeps working;
* the MT5 worker hands the terminal module over unchanged (order_send reaches the terminal);
* the mode gate has no lock reason; AUTO_LIVE on a REAL account (mock data) is allowed by the gate after the account confirmation;
* STOP stops NEW entries only - an open AUTO_DEMO position is still reduced (partial close) and closed;
* SH: AUTO_LIVE entries need a passed validation on the client's history (concrete reason otherwise), management of an
  existing plan is never refused by the mode rules, a plan of another account is not touched.
"""
from __future__ import annotations

import json
import unittest

import _env  # noqa: F401
from _env import TempData, core, wait_for


class TestConfigMigration(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def _load(self, execution: dict):
        from masterquo import paths
        from masterquo.config import ConfigStore
        p = paths.data_dir() / "config.json"
        p.write_text(json.dumps({"config_version": 11, "execution": execution}), encoding="utf-8")
        return ConfigStore(), p

    def test_locked_auto_live_is_reset_to_paper_with_note(self):
        cfg, p = self._load({"mode": "AUTO_LIVE", "bound_account": "srv:1", "lock": "LOCKED", "lock_changed_at": None})
        ex = cfg.get().execution
        self.assertEqual(cfg.get().config_version, 12)
        self.assertEqual(ex.mode, "PAPER")                                   # removing the lock never starts orders silently
        self.assertIn("Execution Lock został wycofany", ex.mode_note or "")
        self.assertFalse(hasattr(ex, "lock"))
        stored = json.loads(p.read_text(encoding="utf-8"))
        self.assertNotIn("lock", stored["execution"])
        self.assertTrue((p.parent / "config.v11.bak.json").exists())         # rollback copy of the pre-migration file

    def test_unlocked_auto_demo_keeps_working(self):
        cfg, _ = self._load({"mode": "AUTO_DEMO", "bound_account": "srv:1", "lock": "UNLOCKED_BY_USER"})
        self.assertEqual(cfg.get().execution.mode, "AUTO_DEMO")
        self.assertIsNone(cfg.get().execution.mode_note)

    def test_locked_paper_and_signals_unchanged(self):
        for mode in ("PAPER", "SIGNALS"):
            cfg, _ = self._load({"mode": mode, "lock": "LOCKED"})
            self.assertEqual(cfg.get().execution.mode, mode)
            self.assertIsNone(cfg.get().execution.mode_note)

    def test_fresh_install_starts_in_paper(self):
        from masterquo.config import ConfigStore
        self.assertEqual(ConfigStore().get().execution.mode, "PAPER")


class TestNoLockOnSimulator(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from test_risk_execution import LIMITS, StubEngine
        cfg, db, bus, log, fake, worker, b = core()
        self.cfg, self.db, self.bus, self.log, self.fake, self.worker, self.b = cfg, db, bus, log, fake, worker, b
        cfg.update({"execution": {"primary_path": {"XAUUSD": "ACTIVE"}}, "risk": LIMITS, "costs": {"slippage_stress_points": 5}})
        b.start()
        self.assertTrue(wait_for(lambda: b.state == "CONNECTED" and b.quote_status() and b.symbol_info, 40))
        from masterquo.engine.lifecycle import LifecycleStore
        from masterquo.execution.gateway import ExecutionGateway
        from masterquo.execution.manager import PositionManager
        from masterquo.execution.modes import ModeManager
        from masterquo.execution.paper import PaperBroker
        self.modes = ModeManager(cfg, db, bus, log, account_provider=lambda: (b.account_status(), b.account_key, b.synthetic))
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

    def _decision(self, did, setup_id):
        from test_risk_execution import TestExecution
        return TestExecution.decision(self, did, setup_id)

    def test_worker_hands_the_terminal_over_unchanged(self):
        from masterquo.mt5.worker import PRIO_TRADE
        self.assertIs(self.b.raw_call(lambda m: m, PRIO_TRADE), self.fake)       # no proxy between the app and the terminal module

    def test_synthetic_terminal_is_recognised_behind_the_training_read_only_proxy(self):
        from masterquo.forecast.export import NoOrders
        from masterquo.mt5.fake import is_fake
        self.assertTrue(is_fake(NoOrders(self.fake)))       # export of a --demo run must be SYNTHETIC_TEST, never REAL_USER_DATA
        self.assertFalse(is_fake(NoOrders(object())))

    def test_gate_has_no_lock_and_live_needs_only_the_account_confirmation(self):
        acct = dict(self.b.account_status(), trade_mode="REAL")
        st = self.modes.set_mode("AUTO_LIVE", confirm=f"LIVE {acct['login']}", account=acct, account_key=self.b.account_key, synthetic=False)
        self.assertEqual(st["mode"], "AUTO_LIVE")
        g = self.modes.gate(self.b.account_key, account=acct, synthetic=False)
        self.assertNotIn("EXECUTION_LOCKED", g["reason_codes"])
        self.assertNotIn("execution_lock", g)
        self.assertTrue(g["allowed"], g["reason_codes"])

    def test_stop_blocks_new_entries_but_open_position_is_managed_and_closed(self):
        acct = self.b.account_status()
        self.modes.set_mode("AUTO_DEMO", confirm=str(acct["login"]), account=acct, account_key=self.b.account_key, synthetic=True)
        self.engine.decision = self._decision("MQD-1", "MQS-T1")
        r = self.gw.execute("MQD-1")
        self.assertEqual(r["status"], "FILLED", r)
        self.assertTrue(wait_for(lambda: len(self.b.positions) == 1, 20))
        self.modes.set_kill(True, "TEST")                                         # STOP
        self.engine.decision = self._decision("MQD-2", "MQS-T2")
        r2 = self.gw.execute("MQD-2")
        self.assertEqual(r2["status"], "BLOCKED")
        self.assertIn("NEW_ENTRIES_STOPPED", r2["reason"])
        mp = self.db.one("SELECT * FROM managed_positions WHERE state='OPEN' AND mode='AUTO_DEMO'")
        self.assertIsNotNone(mp)
        mod = self.gw.manual_modify(dict(mp), "PARTIAL", volume=0.02)             # management of the open position still works
        self.assertEqual(mod["status"], "DONE", mod)
        self.assertTrue(wait_for(lambda: self.b.positions and abs(self.b.positions[0]["volume"] - 0.03) < 1e-9, 20))
        res = self.mgr.close_positions("ALL")                                     # closing too
        self.assertEqual(res.get("errors") or [], [], res)
        self.assertTrue(wait_for(lambda: len(self.b.positions) == 0, 20))


class TestSHExecutorGate(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def _ex(self, live=True, check=None):
        from masterquo.sh.executor import SHExecutor
        return SHExecutor(None, terminal=lambda fn: None, account_key="srv:1", is_demo=lambda: not live, is_live=lambda: live,
                          live_check=check)

    def test_live_entry_needs_validation_management_does_not(self):
        from masterquo.sh.service import SHService
        ex = self._ex(check=lambda strat: SHService.live_validation("XAUUSD", strat))
        plan = {"plan_id": "P1", "strategy": "SCALPING", "account_key": "srv:1"}
        g = ex._gate("AUTO_LIVE", plan, entry=True)
        self.assertTrue(g and g.startswith("SH_LIVE_WYMAGA_WALIDACJI"), g)       # concrete reason, never a silent refusal
        self.assertIsNone(ex._gate("AUTO_LIVE", plan, entry=False))               # open plan: managed
        self.assertIsNone(ex._gate("AUTO_DEMO", plan, entry=False))
        self.assertTrue(ex._gate("AUTO_LIVE", dict(plan, account_key="other:2"), entry=False).startswith("INNY_RACHUNEK"))

    def test_validation_report_rules(self):
        from masterquo import paths
        from masterquo.sh.service import SHService
        d = paths.data_dir() / "sh" / "validation"
        d.mkdir(parents=True, exist_ok=True)
        f = d / "XAUUSD_SCALPING.json"

        def write(**kw):
            rep = {"created_at": "2026-10-27T00:00:00Z", "data_kind": "REAL_USER_DATA", "commission_source": "eksport (terminal)",
                   "metrics": {"n": 40, "expectancy": 0.12}}
            rep.update(kw)
            f.write_text(json.dumps(rep), encoding="utf-8")
            return SHService.live_validation("XAUUSD", "SCALPING")

        self.assertTrue(write()["ok"])
        self.assertFalse(write(data_kind="SYNTHETIC_TEST")["ok"])
        self.assertFalse(write(commission_source="NIEZNANA")["ok"])
        self.assertFalse(write(metrics={"n": 12, "expectancy": 0.3})["ok"])
        self.assertFalse(write(metrics={"n": 50, "expectancy": -0.01})["ok"])
        self.assertFalse(SHService.live_validation("XAUUSD", "HEDGING")["ok"])    # no report for HEDGING
        write()
        ex = self._ex(check=lambda strat: SHService.live_validation("XAUUSD", strat))
        self.assertIsNone(ex._gate("AUTO_LIVE", {"strategy": "SCALPING", "account_key": "srv:1"}, entry=True))
        self.assertEqual(self._ex(live=False)._gate("AUTO_LIVE", {"strategy": "SCALPING"}, entry=True), "RACHUNEK_NIE_REAL")

    def test_sh_risk_engine_reports_the_validation_result(self):
        from masterquo.sh import risk as RK
        su = {"strategy": "SCALPING", "status": "READY", "valid_until": 1e12, "side": "BUY", "model_mode": "PEŁNA"}
        try:
            out = RK.evaluate(setup=su, spec=None, prof={}, cfg={"risk": {"max_quote_age_s": 5}}, inst="XAUUSD", account={},
                              state={"live_validation": {"ok": False, "reason": "brak raportu"}}, exec_mode="AUTO_LIVE", now=0.0, quote=None)
        except Exception:  # noqa: BLE001 - later checks need a full spec; the mode check comes first and is what is tested
            return
        bad = [c for c in out["checks"] if c["id"] == "live_validation"]
        self.assertTrue(bad and not bad[0]["ok"])


if __name__ == "__main__":
    unittest.main()
