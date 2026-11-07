"""1.33 U6 - decision architecture (PMW-ARC-1): contracts, model roles OBSERVE / ASSIST / REQUIRED, one coordinator for both paths,
shared atomic risk reservation (threads), execution intents with dedup and UNKNOWN reconciliation, both real adapters (gateway on
FakeMT5, SH service in PAPER / AUTO_DEMO on the simulated terminal) and the replay old vs new. No real account, no LIVE order."""
import json
import threading
import time
import unittest
from types import SimpleNamespace

import _env  # noqa: F401
from _env import TempData

NOW = time.time()


def pred(fam, use="SHADOW", state="READY", up=0.3, down=0.7, age=10.0, task="CLASS_PROBABILITIES"):
    from datetime import datetime, timezone
    dt = datetime.fromtimestamp(NOW - age, timezone.utc).isoformat()
    return {"family": fam, "use": use, "state": state, "task_type": task, "data_time": dt,
            "result": {"UP": up, "DOWN": down, "FLAT": round(1 - up - down, 4)} if state == "READY" else None}


class TestContracts(unittest.TestCase):
    def test_make_validates_fields_types_enums_nan(self):
        from masterquo.decision import contracts as K
        c = K.make("StrategyCandidate", path="SH", strategy_id="SCALPING", source_id="SH-1", symbol="XAUUSD", side="BUY", base_verdict="ENTER",
                   reasons=[])
        self.assertEqual(c["contract"], "PMW-ARC-1/StrategyCandidate")
        for bad in ({"side": "LONGISH"}, {"path": "OTHER"}, {"entry": float("nan")}, {"volume": True}, {"extra_field": 1}):
            with self.assertRaises(K.ContractViolation, msg=bad):
                K.make("StrategyCandidate", **{**{k: v for k, v in c.items() if k != "contract"}, **bad})
        with self.assertRaises(K.ContractViolation):
            K.make("ExecutionOutcome", intent_id="I", status="FILLED")          # missing 'at'
        self.assertEqual(len(K.SCHEMAS), 10)                                    # the 10 ARC contracts
        spec = K.instrument_spec("XAUUSD-", {"digits": 2, "point": 0.01, "trade_tick_size": 0.01, "trade_tick_value": 1.0})
        self.assertEqual(spec["tick_size"], 0.01)


class TestModelRoles(unittest.TestCase):
    def ev(self, preds, side="BUY", required=()):
        from masterquo.decision.coordinator import evaluate_models
        return evaluate_models(preds, side, required=set(required), assist_threshold=0.6, max_age_s=900, now=NOW)

    def test_observe_never_influences(self):
        models, reasons = self.ev([pred("ARIMA", "SHADOW", down=0.95, up=0.03)])
        self.assertEqual(reasons, [])
        self.assertEqual(models[0]["role"], "OBSERVE")
        self.assertEqual(models[0]["influence"], "NONE")

    def test_assist_holds_only_when_opposite_strong_and_never_upgrades(self):
        from masterquo.decision.coordinator import final_verdict
        _, r = self.ev([pred("LSTM", "ASSIST", up=0.2, down=0.7)])
        self.assertEqual(r, ["MODEL_ASSIST_HOLD:LSTM"])
        _, r = self.ev([pred("LSTM", "ASSIST", up=0.45, down=0.4)])
        self.assertEqual(r, [])
        self.assertEqual(final_verdict("WAIT", [], []), "WAIT")                 # nothing upgrades WAIT / NO_TRADE
        self.assertEqual(final_verdict("NO_TRADE", [], ["X"]), "NO_TRADE")
        self.assertEqual(final_verdict("ENTER", [], ["MODEL_ASSIST_HOLD:LSTM"]), "BLOCKED")

    def test_required_missing_stale_contrary_and_ok(self):
        _, r = self.ev([], required=["GARCH"])
        self.assertEqual(r, ["MODEL_REQUIRED_UNAVAILABLE:GARCH"])
        _, r = self.ev([pred("GARCH", state="NOT_TRAINED")], required=["GARCH"])
        self.assertEqual(r, ["MODEL_REQUIRED_UNAVAILABLE:GARCH"])
        _, r = self.ev([pred("GARCH", up=0.6, down=0.2, age=5000)], required=["GARCH"])
        self.assertEqual(r, ["MODEL_REQUIRED_STALE:GARCH"])
        _, r = self.ev([pred("GARCH", up=0.2, down=0.6)], required=["GARCH"])
        self.assertEqual(r, ["MODEL_REQUIRED_CONTRARY:GARCH"])
        m, r = self.ev([pred("GARCH", up=0.6, down=0.2)], required=["GARCH"])
        self.assertEqual((r, m[0]["influence"]), ([], "PASS"))


class Store:
    def __init__(self, **upd):
        from masterquo.config import AppConfig
        self.c = AppConfig()
        for sec, kv in upd.items():
            for k, v in kv.items():
                setattr(getattr(self.c, sec), k, v)

    def get(self):
        return self.c


class TestLedger(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.db.database import Database
        from masterquo.decision.ledger import IntentLedger, RiskBook
        self.db = Database()
        self.store = Store(risk={"max_open_positions": 1})
        self.book = RiskBook(self.db, self.store, sh_limits=lambda: {})
        self.led = IntentLedger(self.db, self.book)

    def tearDown(self):
        self.td.close()

    def test_concurrent_threads_of_both_paths_only_one_passes(self):
        res, bar = [], threading.Barrier(8)

        def go(i):
            bar.wait()
            res.append(self.book.reserve(path=("ACTIVE", "SH")[i % 2], subject=f"S{i}", mode="AUTO_DEMO", account_key="D:1", risk_money=5.0,
                                         equity=1000.0))
        th = [threading.Thread(target=go, args=(i,)) for i in range(8)]
        [t.start() for t in th]
        [t.join() for t in th]
        self.assertEqual(sum(r["ok"] for r in res), 1)
        self.assertTrue(all("PORTFOLIO_MAX_OPEN_POSITIONS_RESERVED" in r["reasons"] for r in res if not r["ok"]))

    def test_dedup_blocked_frees_key_unknown_counts_until_reconciled(self):
        a = self.led.open(path="ACTIVE", mode="PAPER", account_key="P", subject="MQS-1", symbol="XAUUSD", side="BUY", volume=0.1, risk_money=5.0,
                          record_id=None, equity=1000.0, reserve_subject="MQO-1")
        self.assertEqual(a["status"], "RESERVED")
        self.assertEqual(self.led.open(path="ACTIVE", mode="PAPER", account_key="P", subject="MQS-1", symbol="XAUUSD", side="BUY", volume=0.1,
                                       risk_money=5.0, record_id=None, equity=1000.0)["status"], "DUPLICATE")
        b = self.led.open(path="SH", mode="PAPER", account_key="P", subject="PL-2", symbol="XAUUSD", side="SELL", volume=0.1, risk_money=5.0,
                          record_id=None, equity=1000.0)
        self.assertEqual(b["status"], "BLOCKED")                               # cap 1: the ACTIVE reservation holds the slot
        iid = a["intent"]["intent_id"]
        self.led.sent(iid, "MQO-1")
        self.led.outcome(iid, {"status": "UNKNOWN", "reason": "ORDER_SEND_TIMEOUT"})
        self.assertEqual(self.book.live()[0]["state"], "UNKNOWN")             # still counted while unknown
        self.assertEqual(self.led.open(path="SH", mode="PAPER", account_key="P", subject="PL-2", symbol="XAUUSD", side="SELL", volume=0.1,
                                       risk_money=5.0, record_id=None, equity=1000.0)["status"], "BLOCKED")   # BLOCKED key was freed
        self.db.execute("INSERT INTO order_attempts(attempt_id, entry_key, decision_id, setup_id, created_at, updated_at, mode, account_key, symbol, "
                        "side, volume, client_tag, state, initiated_by) VALUES ('MQO-1','k','d','MQS-1','t','t','PAPER','P','XAUUSD','BUY',0.1,'MQ:1',"
                        "'NOT_FOUND_CHECK_TERMINAL','AUTO')")
        self.assertEqual(self.led.sync(), {"filled": 0, "not_found": 1})
        self.assertEqual(self.led.get(iid)["state"], "RECONCILED_NOT_FOUND")
        self.assertEqual(self.book.live(), [])
        self.assertEqual(self.led.open(path="SH", mode="PAPER", account_key="P", subject="PL-2", symbol="XAUUSD", side="SELL", volume=0.1,
                                       risk_money=5.0, record_id=None, equity=1000.0)["status"], "RESERVED")

    def test_ttl_expires_held_but_never_unknown(self):
        t = [NOW]
        self.book.clock = lambda: t[0]
        self.store.c.risk.max_open_positions = 2
        r1 = self.book.reserve(path="SH", subject="A", mode="PAPER", account_key="P", risk_money=1.0, equity=None)
        r2 = self.book.reserve(path="SH", subject="B", mode="PAPER", account_key="P", risk_money=1.0, equity=None)
        self.book.settle(r2["reservation_id"], "UNKNOWN")
        t[0] += 10_000
        self.assertTrue(self.book.reserve(path="SH", subject="C", mode="PAPER", account_key="P", risk_money=1.0, equity=None)["ok"])
        st = {r["reservation_id"]: r["state"] for r in self.db.query("SELECT reservation_id, state FROM risk_reservations")}
        self.assertEqual(st[r1["reservation_id"]], "EXPIRED")
        self.assertEqual(st[r2["reservation_id"]], "UNKNOWN")

    def test_daily_loss_counts_pending_risk(self):
        self.store.c.risk.max_open_positions = 10
        self.store.c.risk.daily_loss_limit_pct = 5.0
        self.assertTrue(self.book.reserve(path="SH", subject="A", mode="PAPER", account_key="P", risk_money=60.0, equity=1000.0)["ok"])
        r = self.book.reserve(path="ACTIVE", subject="B", mode="PAPER", account_key="P", risk_money=10.0, equity=1000.0)
        self.assertEqual(r["reasons"], ["PORTFOLIO_DAILY_LOSS_LIMIT_RESERVED"])  # -60 pending <= -5% of 1000

    def test_signals_never_reserves(self):
        self.assertFalse(self.book.reserve(path="SH", subject="A", mode="SIGNALS", account_key="P", risk_money=1.0, equity=1.0)["ok"])


class TestCoordinatorRecords(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.db.database import Database
        from masterquo.decision.coordinator import DecisionCoordinator
        self.db = Database()
        self.preds = []
        fam = SimpleNamespace(predictions=lambda inst: list(self.preds))
        self.store = Store()
        self.arc = DecisionCoordinator(self.db, self.store, families=fam, instrument_fn=lambda: "XAUUSD")

    def tearDown(self):
        self.td.close()

    def test_active_model_gate_becomes_decision_tree_node(self):
        from masterquo.engine import decision as D
        self.assertIsNone(self.arc.model_gate_active({"direction": "LONG"}))     # no models -> no node (1.32 behaviour)
        self.preds = [pred("LSTM", "ASSIST", up=0.1, down=0.8)]
        g = self.arc.model_gate_active({"direction": "LONG"})
        self.assertEqual(g["status"], "FAIL")
        self.assertIn("MODEL_ASSIST_HOLD:LSTM", g["codes"])
        self.preds = [pred("LSTM", "SHADOW", up=0.1, down=0.8)]
        self.assertEqual(self.arc.model_gate_active({"direction": "LONG"})["status"], "PASS")
        self.store.c.decision.required_models = ["GARCH"]
        self.assertEqual(self.arc.model_gate_active({"direction": "SHORT"})["codes"], ["MODEL_REQUIRED_UNAVAILABLE:GARCH"])
        self.assertIn("model_gate", D.build.__code__.co_varnames)

    def test_record_dedup_and_sh_required_hold(self):
        su = {"signal_id": "SH-X1", "strategy": "SCALPING", "symbol": "XAUUSD-", "side": "BUY", "status": "READY", "entry_ref": 2000.0, "sl": 1998.0,
              "tps": [{"price": 2003.0}], "family_context": {"context": []}}
        r1 = self.arc.record_sh(su, {"risk_money": 5.0, "volume": 0.1}, "PAPER", "P")
        r2 = self.arc.record_sh(dict(su, entry_ref=2000.4), {"risk_money": 5.0, "volume": 0.1}, "PAPER", "P")   # price tick: same record
        self.assertEqual(r1["record_id"], r2["record_id"])
        self.assertEqual(self.db.one("SELECT COUNT(*) n FROM decision_records")["n"], 1)
        self.assertEqual(r1["final_verdict"], "ENTER")
        self.store.c.decision.required_models = ["ARIMA"]
        r3 = self.arc.record_sh(su, None, "PAPER", "P")
        self.assertEqual(r3["final_verdict"], "BLOCKED")
        self.assertIn("MODEL_REQUIRED_UNAVAILABLE:ARIMA", r3["reason_codes"])
        st = self.arc.status()
        self.assertEqual(len(st["records"]), 2)


class TestGatewayThroughLedger(unittest.TestCase):
    """Main path adapter: execution/gateway.py on FakeMT5 with the coordinator attached (as in runtime.py)."""

    def setUp(self):
        import test_risk_execution as T
        self.T = T.TestExecution("test_paper_never_calls_order_send_and_is_idempotent")
        self.T.setUp()
        from masterquo.decision.coordinator import DecisionCoordinator
        self.arc = DecisionCoordinator(self.T.db, self.T.cfg)
        self.T.gw.arc = self.T.mgr.arc = self.arc

    def tearDown(self):
        self.T.tearDown()

    def test_paper_fill_consumes_reservation_and_double_click_is_duplicate(self):
        t = self.T
        t.modes.set_mode("PAPER", confirm="PAPER", account=t.b.account_status(), account_key=t.b.account_key, synthetic=True)
        t.engine.decision = t.decision()
        self.assertEqual(t.gw.execute("MQD-1")["status"], "FILLED")
        self.assertEqual(t.gw.execute("MQD-1")["status"], "DUPLICATE")
        it = self.arc.intents.recent()
        self.assertEqual([x["state"] for x in it], ["FILLED"])
        self.assertEqual(self.T.db.one("SELECT state FROM risk_reservations")["state"], "CONSUMED")

    def test_cap_reached_blocks_with_reason_and_nothing_is_sent(self):
        t = self.T
        acct = t.b.account_status()
        t.cfg.update({"risk": {"max_open_positions": 1}})
        t.modes.set_mode("AUTO_DEMO", confirm=str(acct["login"]), account=acct, account_key=t.b.account_key, synthetic=True)
        self.arc.book.reserve(path="SH", subject="PL-OTHER", mode="AUTO_DEMO", account_key=t.b.account_key, risk_money=5.0, equity=None)
        t.engine.decision = t.decision(setup_id="MQS-C1")
        sent = []
        orig = t.fake.order_send
        t.fake.order_send = lambda r: sent.append(r) or orig(r)
        r = t.gw.execute("MQD-1")
        self.assertEqual(r["status"], "BLOCKED", r)
        self.assertIn("PORTFOLIO_MAX_OPEN_POSITIONS_RESERVED", r["reason"])
        self.assertEqual(sent, [])
        self.assertIsNone(t.db.one("SELECT 1 FROM order_attempts WHERE setup_id='MQS-C1'"))   # the setup may be tried again later

    def test_timeout_unknown_reconciled_by_manager_tick(self):
        from _env import wait_for
        t = self.T
        acct = t.b.account_status()
        t.modes.set_mode("AUTO_DEMO", confirm=str(acct["login"]), account=acct, account_key=t.b.account_key, synthetic=True)
        t.engine.decision = t.decision(setup_id="MQS-U1")
        orig = t.fake.order_send

        def flaky(req):
            orig(req)
            raise TimeoutError("lost")
        t.fake.order_send = flaky
        self.assertEqual(t.gw.execute("MQD-1")["status"], "UNKNOWN")
        self.assertEqual(self.arc.intents.recent()[0]["state"], "UNKNOWN")
        self.assertEqual(t.db.one("SELECT state FROM risk_reservations")["state"], "UNKNOWN")
        t.b._t_account = 0
        t.b._t_hist = 0
        self.assertTrue(wait_for(lambda: bool(t.b.positions), 15))
        t.mgr.tick()
        self.assertEqual(self.arc.intents.recent()[0]["state"], "RECONCILED_FILLED")
        self.assertEqual(t.db.one("SELECT state FROM risk_reservations")["state"], "CONSUMED")


class TestSHThroughLedger(unittest.TestCase):
    """SH adapter: SHService.open_plan in PAPER with the coordinator attached; a slot held by the main path blocks a new SH plan."""

    def setUp(self):
        import test_sh_service as S
        self.S = S.PaperScalping("test_full_cycle_be_after_confirmed_tp2")
        self.S.setUp()
        from masterquo.decision.coordinator import DecisionCoordinator
        self.arc = DecisionCoordinator(self.S.db, self.S.cfg_store)
        self.arc.book.sh_limits = lambda: {}
        self.S.svc.arc = self.arc

    def tearDown(self):
        self.S.tearDown()

    def test_open_plan_intent_filled_once_and_counted_once(self):
        r, su = self.S.open()
        self.assertEqual(r["status"], "OPEN", r)
        self.assertEqual([x["state"] for x in self.arc.intents.recent()], ["FILLED"])
        self.assertEqual(self.S.db.one("SELECT state FROM risk_reservations")["state"], "CONSUMED")
        from masterquo.risk import portfolio as PF
        st = PF.state(self.S.db, "PAPER", self.S.bridge.account_key, time.time())
        self.assertEqual(st["open_by_path"]["SH"], 1)

    def test_slot_held_by_active_blocks_sh(self):
        self.S.cfg_store.update({"risk": {"max_open_positions": 1}})
        ok = self.arc.book.reserve(path="ACTIVE", subject="MQO-X", mode="PAPER", account_key=self.S.bridge.account_key, risk_money=5.0, equity=None)
        self.assertTrue(ok["ok"])
        r, _ = self.S.open()
        self.assertEqual(r["status"], "BLOCKED", r)
        self.assertIn("PORTFOLIO_MAX_OPEN_POSITIONS_RESERVED", r["reason"])
        self.assertEqual(self.S.db.one("SELECT COUNT(*) n FROM sh_plans")["n"], 0)


class TestReplay(unittest.TestCase):
    def test_race_old_exceeds_new_never(self):
        from masterquo.decision.replay import race_scenario
        r = race_scenario(cap=2, requests=6)
        self.assertEqual((r["old_passed"], r["new_passed"]), (6, 2))
        self.assertTrue(r["old_exceeds_cap"])
        self.assertFalse(r["new_exceeds_cap"])

    def test_stored_decisions_equal_without_roles_and_differ_with_required(self):
        td = TempData()
        try:
            from masterquo.db.database import Database
            from masterquo.decision.replay import replay_decisions
            db = Database()
            for i, perm in enumerate(("ALLOWED", "BLOCKED", "ALLOWED")):
                rec = {"execution_permission": perm, "decision": "BUY" if perm == "ALLOWED" else "WAIT", "analysis_direction": "LONG"}
                db.execute("INSERT INTO decisions(decision_id, created_at, snapshot_id, session_epoch, symbol, synthetic, analysis_direction, signal_stage, decision, "
                           "execution_permission, expires_at, record_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                           (f"MQD-{i}", f"2026-01-0{i + 1}", "s", 1, "XAUUSD", 1, "LONG", "X", rec["decision"], perm, "2026", json.dumps(rec)))
            same = replay_decisions(db)
            self.assertEqual(same["active"]["changed"], [])
            self.assertEqual(same["active"]["old"], same["active"]["new"])
            diff = replay_decisions(db, required={"GARCH"})
            self.assertEqual(len(diff["active"]["changed"]), 2)
            self.assertEqual(diff["active"]["new"].get("BLOCKED"), 2)
        finally:
            td.close()


if __name__ == "__main__":
    unittest.main()
