"""1.46 arch, wave 2 - group decision_eval: decision coordinator (REQUIRED quant hold, fail-closed contract error, REQUIRED producer
check), shared reservation / intent ledger (in-flight reservations, HEDGE intents, HEDGING entry slots), evaluation ledger (indicator
context observation, champion row after promotion, per-instrument readiness, label policies), SI forecast <-> snapshot link, live ATR of
the setup candidates, the prediction contract as a neutral leaf. Unit level only: no terminal, no order is ever sent."""
from __future__ import annotations

import ast
import json
import time
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _env  # noqa: F401
from _env import ROOT, TempData

MQ = ROOT / "backend" / "masterquo"
NOW = time.time()


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, UTC).isoformat()


class Store:
    def __init__(self, **upd):
        from masterquo.config import AppConfig
        self.c = AppConfig()
        for sec, kv in upd.items():
            for k, v in kv.items():
                setattr(getattr(self.c, sec), k, v)

    def get(self):
        return self.c


def _quant_pred(hold="E[net R] <= 0", state="READY", age=5.0):
    return {"family": "quant:metamodel", "state": state, "use": "ASSIST", "task_type": "EVENT_PROBABILITY", "data_time": _iso(NOW - age),
            "result": {"p": 0.31, "e_net_r": -0.2} if state == "READY" else None, "quant_hold": hold}


# ---------------------------------------------------------------------------------------------------------------- I0771
class TestRequiredQuantHold(unittest.TestCase):
    def ev(self, preds, required=()):
        from masterquo.decision.coordinator import evaluate_models
        return evaluate_models(preds, "BUY", required=set(required), assist_threshold=0.6, max_age_s=900, now=NOW)

    def test_required_quant_metamodel_with_hold_blocks(self):
        models, reasons = self.ev([_quant_pred()], required={"quant:metamodel"})
        self.assertEqual(reasons, ["MODEL_QUANT_HOLD:quant:metamodel"])                 # przed: [] i PASS
        self.assertEqual((models[0]["role"], models[0]["influence"]), ("REQUIRED", "BLOCK"))

    def test_required_without_hold_passes_and_earlier_blocks_keep_priority(self):
        m, r = self.ev([_quant_pred(hold=None)], required={"quant:metamodel"})
        self.assertEqual((r, m[0]["influence"]), ([], "PASS"))
        _, r = self.ev([_quant_pred(age=5000)], required={"quant:metamodel"})             # stale AND hold -> the stale block stays
        self.assertEqual(r, ["MODEL_REQUIRED_STALE:quant:metamodel"])
        _, r = self.ev([_quant_pred(state="NOT_TRAINED")], required={"quant:metamodel"})
        self.assertEqual(r, ["MODEL_REQUIRED_UNAVAILABLE:quant:metamodel"])

    def test_assist_role_unchanged(self):
        m, r = self.ev([_quant_pred()])
        self.assertEqual((r, m[0]["role"], m[0]["influence"]), (["MODEL_QUANT_HOLD:quant:metamodel"], "ASSIST", "HOLD"))

    def test_sh_receiver_blocks_on_the_new_code(self):
        src = (MQ / "sh" / "service.py").read_text(encoding="utf-8")
        self.assertIn('startswith(("MODEL_REQUIRED", "MODEL_QUANT_HOLD"))', src)        # SH: READY -> WAIT on the REQUIRED hold too


# ---------------------------------------------------------------------------------------------------------------- I0772
class _Coord(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.db.database import Database
        from masterquo.decision.coordinator import DecisionCoordinator
        self.db = Database()
        self.store = Store()
        self.arc = DecisionCoordinator(self.db, self.store, families=SimpleNamespace(predictions=lambda inst: []), instrument_fn=lambda: "XAUUSD")

    def tearDown(self):
        self.td.close()

    @staticmethod
    def su(**kw):
        d = {"signal_id": "SH-CV1", "strategy": "SCALPING", "symbol": "XAUUSD-", "side": "BUY", "status": "READY", "entry_ref": 2000.0,
             "sl": 1998.0, "tps": [{"price": 2003.0}], "family_context": {"context": []}}
        d.update(kw)
        return d


class TestRecordShContractViolationFailClosed(_Coord):
    def _break_contract(self):
        # a NaN in the (presentation-only) confidence makes the DecisionRecord fail its contract (NOT_JSON_SAFE)
        self.arc.quant = SimpleNamespace(assist_active=lambda: False, confidence_for=lambda *a: {"confidence_score": float("nan")})

    def test_required_configured_contract_error_propagates(self):
        from masterquo.decision import contracts as K
        self._break_contract()
        self.store.c.decision.required_models = ["TS_ARIMA"]
        with self.assertRaises(K.ContractViolation):                                    # przed: None (SH bez model_block -> open_plan)
            self.arc.record_sh(self.su(), {"risk_money": 5.0, "volume": 0.1}, "PAPER", "P")

    def test_without_required_unchanged(self):
        self._break_contract()
        self.assertIsNone(self.arc.record_sh(self.su(), {"risk_money": 5.0, "volume": 0.1}, "PAPER", "P"))

    def test_active_path_unchanged(self):
        self._break_contract()
        self.store.c.decision.required_models = ["TS_ARIMA"]
        d = {"decision_id": "MQD-1", "symbol": "XAUUSD-", "analysis_direction": "LONG", "execution_permission": "ALLOWED", "decision": "BUY",
             "risk": {"entry": 2000.0, "stop_loss": 1998.0, "targets": [{"price": 2003.0}], "lots": 0.1, "modeled_loss": 5.0},
             "setup": {"strategy_id": "S01"}, "decision_tree": [], "reason_codes": []}
        self.assertIsNone(self.arc.record_active(d, "PAPER", None))
        self.assertIn("error", d["decision_record"])

    def test_nan_in_a_model_result_never_passes_required(self):
        fc = [{"family": "GARCH", "state": "READY", "use": "ASSIST", "task_type": "CLASS_PROBABILITIES",
               "result": {"UP": float("nan"), "DOWN": 0.2, "FLAT": 0.1}}]
        self.store.c.decision.required_models = ["GARCH"]
        rec = self.arc.record_sh(self.su(family_context={"context": fc}), None, "PAPER", "P")
        self.assertEqual(rec["final_verdict"], "BLOCKED")                                # przed: None (rekord odrzucony, brak blokady)
        self.assertIn("MODEL_REQUIRED_UNAVAILABLE:GARCH", rec["reason_codes"])
        self.store.c.decision.required_models = []
        rec = self.arc.record_sh(self.su(signal_id="SH-CV2", family_context={"context": fc}), None, "PAPER", "P")
        self.assertEqual(rec["final_verdict"], "ENTER")                                  # ASSIST: a non-finite result has no effect
        self.assertEqual((rec["models"][0]["state"], rec["models"][0]["result"], rec["models"][0]["influence"]), ("INVALID_RESULT", None, "NONE"))


# ---------------------------------------------------------------------------------------------------------------- I0440 / I0773 status
class TestRequiredModelsCheckInStatus(_Coord):
    def test_required_id_without_producer_is_reported(self):
        self.store.c.decision.required_models = ["TH_RF", "GARCH"]
        self.arc.record_sh(self.su(), None, "PAPER", "P")
        chk = {x["model_id"]: x for x in self.arc.status()["required_models_check"]}     # przed: KeyError
        self.assertIn("TH_RF", chk)
        self.assertEqual(chk["GARCH"]["missing_in"], ["SH"])
        self.assertIn("Quant ASSIST", chk["TH_RF"]["warning"])
        # matching is unchanged: the REQUIRED id still blocks
        from masterquo.decision.coordinator import evaluate_models
        _, r = evaluate_models([], "BUY", required={"TH_RF"}, assist_threshold=0.6, max_age_s=900, now=NOW)
        self.assertEqual(r, ["MODEL_REQUIRED_UNAVAILABLE:TH_RF"])

    def test_ttl_warning(self):
        self.assertEqual(self.arc.status()["config_warnings"], [])
        self.store.c.decision.reservation_ttl_s = 30.0
        self.assertTrue(any("reservation_ttl_s" in w for w in self.arc.status()["config_warnings"]))


class TestCoordinatorDoc(unittest.TestCase):
    def test_no_svp_observe_record_claimed(self):
        from masterquo.decision import coordinator
        self.assertNotIn("SVP context", coordinator.__doc__)                             # I0606: no producer of an SVP record


# ---------------------------------------------------------------------------------------------------------------- ledger base
class _Ledger(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.db.database import Database
        from masterquo.decision.ledger import IntentLedger, RiskBook
        self.db = Database()
        self.store = Store(risk={"max_open_positions": 1}, decision={"reservation_ttl_s": 10.0})
        self.t = [NOW]
        self.book = RiskBook(self.db, self.store, sh_limits=dict, clock=lambda: self.t[0])
        self.led = IntentLedger(self.db, self.book)

    def tearDown(self):
        self.db.close()
        self.td.close()

    def open(self, subject, path="SH", reserve_subject=None, kind="ENTRY", **kw):
        return self.led.open(path=path, mode="PAPER", account_key="P", subject=subject, symbol="XAUUSD-", side="BUY", volume=0.1,
                             risk_money=5.0, record_id=None, equity=1000.0, reserve_subject=reserve_subject, kind=kind, **kw)

    def attempt(self, aid, state):
        self.db.execute("INSERT INTO order_attempts(attempt_id, entry_key, decision_id, setup_id, created_at, updated_at, mode, account_key, symbol, "
                        "side, volume, client_tag, state, initiated_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (aid, "k-" + aid, "d", "MQS-" + aid, "t", "t", "PAPER", "P", "XAUUSD", "BUY", 0.1, "MQ:" + aid, state, "AUTO"))

    def plan(self, pid, state="PRIMARY_OPEN", hedge=None, policy=None):
        fsm = {"type": "BASKET", "data": {"basket_id": pid, "state": state, "hedge": hedge, "policy": policy or {}}}
        self.db.execute("INSERT INTO sh_plans(plan_id, signal_id, strategy, instrument, symbol, side, exec_mode, account_key, state, config_hash, plan, "
                        "fsm, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (pid, "SIG-" + pid, "HEDGING", "XAUUSD", "XAUUSD-", "BUY", "PAPER", "P", state, "h", "{}", json.dumps(fsm), NOW, NOW))

    def res_state(self, iid):
        rid = self.led.get(iid)["reservation_id"]
        return self.db.one("SELECT state FROM risk_reservations WHERE reservation_id=?", (rid,))["state"]


# ---------------------------------------------------------------------------------------------------------------- I0773
class TestReservationTtlSentIntent(_Ledger):
    def test_order_in_flight_keeps_its_slot_and_unknown_is_counted(self):
        a = self.open("MQS-1", path="ACTIVE", reserve_subject="MQO-1")
        iid = a["intent"]["intent_id"]
        self.attempt("MQO-1", "SENDING")
        self.led.sent(iid, "MQO-1")
        self.t[0] += 20                                                                  # > TTL 10 s, order_send still running
        b = self.open("PL-2")
        self.assertEqual(b["status"], "BLOCKED")                                         # przed: RESERVED (rezerwacja EXPIRED)
        self.assertIn("PORTFOLIO_MAX_OPEN_POSITIONS_RESERVED", b["reasons"])
        self.led.outcome(iid, {"status": "UNKNOWN", "reason": "ORDER_SEND_TIMEOUT"})
        self.assertEqual(self.res_state(iid), "UNKNOWN")

    def test_crash_before_send_still_expires(self):
        self.store.c.risk.max_open_positions = 2
        a = self.open("MQS-1", path="ACTIVE", reserve_subject="MQO-1")
        self.attempt("MQO-1", "PREPARED")                                                # never sent: no terminal order to wait for
        self.led.sent(a["intent"]["intent_id"], "MQO-1")
        c = self.open("MQS-3", path="ACTIVE", reserve_subject="MQO-3")                    # no attempt row at all
        self.assertEqual(c["status"], "RESERVED")
        self.led.sent(c["intent"]["intent_id"], "MQO-3")
        self.assertEqual(self.open("PL-2")["status"], "BLOCKED")
        self.t[0] += 20
        self.assertEqual(self.open("PL-2")["status"], "RESERVED")                         # as before: TTL releases a reservation that waits for nothing
        self.assertEqual((self.res_state(a["intent"]["intent_id"]), self.res_state(c["intent"]["intent_id"])), ("EXPIRED", "EXPIRED"))

    def test_expired_reservation_counted_again_on_unknown(self):
        a = self.open("MQS-1", path="ACTIVE", reserve_subject="MQO-1")
        iid = a["intent"]["intent_id"]
        self.t[0] += 20
        self.book.live()
        self.store.c.risk.max_open_positions = 5
        self.assertEqual(self.open("PL-9")["status"], "RESERVED")                         # runs _expire
        self.assertEqual(self.res_state(iid), "EXPIRED")
        self.led.outcome(iid, {"status": "UNKNOWN"})
        self.assertEqual(self.res_state(iid), "UNKNOWN")                                  # przed: EXPIRED (nie liczona)
        self.store.c.risk.max_open_positions = 2
        self.assertEqual(self.open("PL-10")["status"], "BLOCKED")


# ---------------------------------------------------------------------------------------------------------------- I0776
class TestSyncHedgeIntent(_Ledger):
    def setUp(self):
        super().setUp()
        self.store.c.risk.max_open_positions = 5

    def hedge(self, pid="PL-1"):
        op = self.open(f"{pid}:HEDGE1", kind="HEDGE")
        self.assertEqual(op["status"], "RESERVED")
        iid = op["intent"]["intent_id"]
        self.led.sent(iid, pid)                                                          # as sh/service.pack_hedge_step: source_ref = main plan
        return iid

    def test_leg_not_resolved_yet_stays_counted(self):
        self.plan("PL-1", state="HEDGE_PENDING")
        iid = self.hedge()
        self.led.sync()
        self.assertEqual((self.led.get(iid)["state"], self.res_state(iid)), ("SENT", "HELD"))   # przed: RECONCILED_FILLED / CONSUMED
        self.db.execute("UPDATE sh_plans SET state='PRIMARY_OPEN' WHERE plan_id='PL-1'")          # persisted state before the leg request
        self.led.sync()
        self.assertEqual(self.led.get(iid)["state"], "SENT")
        self.t[0] += 20                                                                  # leg order in flight longer than the TTL
        self.open("PL-7")
        self.assertEqual(self.res_state(iid), "HELD")                                     # I0773: not EXPIRED while the plan is open
        self.db.execute("UPDATE sh_plans SET state='CLOSED' WHERE plan_id='PL-1'")
        self.led.sync()
        self.assertEqual((self.led.get(iid)["state"], self.res_state(iid)), ("RECONCILED_NOT_FOUND", "RELEASED"))   # never hangs

    def test_filled_leg_settles_consumed(self):
        self.plan("PL-1", state="HEDGED", hedge={"side": "SELL", "volume": 0.05, "entry": 2000.0, "opened_at": NOW, "status": "OPEN"})
        iid = self.hedge()
        self.assertEqual(self.led.sync(), {"filled": 1, "not_found": 0})
        self.assertEqual((self.led.get(iid)["state"], self.res_state(iid)), ("RECONCILED_FILLED", "CONSUMED"))

    def test_closed_plan_or_no_leg_request_releases(self):
        self.plan("PL-1", state="CLOSED")
        iid = self.hedge("PL-1")
        self.plan("PL-2", state="PRIMARY_OPEN")
        iid2 = self.hedge("PL-2")
        self.db.execute("UPDATE sh_plans SET fsm=? WHERE plan_id='PL-2'", (json.dumps({"type": "BASKET", "data": {
            "basket_id": "PL-2", "state": "PRIMARY_OPEN", "hedge": None, "policy": {"hedge_intent": iid2}}}),))   # request_hedge gave no action
        self.led.sync()
        self.assertEqual((self.led.get(iid)["state"], self.res_state(iid)), ("RECONCILED_NOT_FOUND", "RELEASED"))
        self.assertEqual((self.led.get(iid2)["state"], self.res_state(iid2)), ("RECONCILED_NOT_FOUND", "RELEASED"))

    def test_entry_intent_unchanged(self):
        self.plan("PL-3", state="PENDING_ENTRY")
        op = self.open("PL-3")
        self.led.sent(op["intent"]["intent_id"], "PL-3")
        self.led.sync()
        self.assertEqual(self.led.get(op["intent"]["intent_id"])["state"], "SENT")
        self.db.execute("UPDATE sh_plans SET state='OPEN' WHERE plan_id='PL-3'")
        self.led.sync()
        self.assertEqual(self.led.get(op["intent"]["intent_id"])["state"], "RECONCILED_FILLED")


# ---------------------------------------------------------------------------------------------------------------- I0774
class TestHedgingEntryNeedsTwoSlots(_Ledger):
    def test_reserve_positions_counts_in_the_cap_and_in_pending(self):
        self.store.c.risk.max_open_positions = 2
        self.assertTrue(self.book.reserve(path="ACTIVE", subject="MQO-A", mode="PAPER", account_key="P", risk_money=1.0, equity=None)["ok"])
        r = self.book.reserve(path="SH", subject="PL-H", mode="PAPER", account_key="P", risk_money=1.0, equity=None, positions=2)
        self.assertEqual(r["reasons"], ["PORTFOLIO_MAX_OPEN_POSITIONS_RESERVED"])       # 1 + 2 > 2 (przed: brak argumentu positions)
        self.store.c.risk.max_open_positions = 3
        r = self.book.reserve(path="SH", subject="PL-H", mode="PAPER", account_key="P", risk_money=1.0, equity=None, positions=2)
        self.assertTrue(r["ok"])
        self.assertEqual(self.db.one("SELECT positions FROM risk_reservations WHERE reservation_id=?", (r["reservation_id"],))["positions"], 2)
        self.assertEqual(r["portfolio"]["pending_reservations"], 1)
        # the hedge-leg check itself is unchanged (+1): pending now counts 1 + 2 = 3 >= cap 3
        r2 = self.book.reserve(path="SH", subject="PL-X:HEDGE1", mode="PAPER", account_key="P", risk_money=None, equity=None)
        self.assertFalse(r2["ok"])

    def test_default_single_position_unchanged(self):
        self.store.c.risk.max_open_positions = 2
        self.assertTrue(self.book.reserve(path="ACTIVE", subject="MQO-A", mode="PAPER", account_key="P", risk_money=1.0, equity=None)["ok"])
        self.assertTrue(self.book.reserve(path="SH", subject="PL-S", mode="PAPER", account_key="P", risk_money=1.0, equity=None)["ok"])


class TestShHedgingEntryReservesTwo(unittest.TestCase):
    """SHService.open_plan with the coordinator: a HEDGING plan on a HEDGING account needs room for its possible hedge leg."""

    def setUp(self):
        import test_sh_service as S
        self.S = S.PaperScalping("test_full_cycle_be_after_confirmed_tp2")
        self.S.setUp()
        from masterquo.decision.coordinator import DecisionCoordinator
        self.arc = DecisionCoordinator(self.S.db, self.S.cfg_store)
        self.arc.book.sh_limits = dict
        self.S.svc.arc = self.arc
        self.S.cfg_store.update({"risk": {"max_open_positions": 2}})
        self.assertTrue(self.arc.book.reserve(path="ACTIVE", subject="MQO-X", mode="PAPER", account_key=self.S.bridge.account_key, risk_money=5.0,
                                              equity=None)["ok"])

    def tearDown(self):
        self.S.tearDown()

    def test_hedging_blocked_scalping_passes(self):
        r, _ = self.S.open(strategy="HEDGING")
        self.assertEqual(r["status"], "BLOCKED", r)                                       # przed: OPEN (1 wolne miejsce na 2 pozycje koszyka)
        self.assertIn("PORTFOLIO_MAX_OPEN_POSITIONS_RESERVED", r["reason"])
        r, _ = self.S.open(strategy="SCALPING")
        self.assertEqual(r["status"], "OPEN", r)

    def test_hedging_with_room_reserves_two(self):
        self.S.cfg_store.update({"risk": {"max_open_positions": 3}})
        r, _ = self.S.open(strategy="HEDGING")
        self.assertEqual(r["status"], "OPEN", r)
        row = self.S.db.one("SELECT positions FROM risk_reservations WHERE path='SH'")
        self.assertEqual(row["positions"], 2)

    def test_netting_account_single_slot(self):
        self.S.bridge.acc["margin_mode"] = "NETTING"
        r, _ = self.S.open(strategy="HEDGING")
        self.assertNotEqual(r["status"], "BLOCKED", r)                                   # no hedge leg possible -> one slot, as before


# ---------------------------------------------------------------------------------------------------------------- evaluation
class _Eval(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.config import ConfigStore
        from masterquo.db.database import Database
        from masterquo.evaluation.service import EvaluationService
        from test_sh_service import Bridge
        self.cfg, self.db = ConfigStore(), Database()
        self.bridge = Bridge(None, "HEDGING")
        self.bridge.buffer_symbol = self.bridge.symbol_info["name"]
        self.bridge.bars = lambda tf, limit=None, include_forming=True: []
        self.svc = EvaluationService(self.cfg, self.bridge, self.db, data_dir=Path(self.td.dir) / "evaluation", clock=lambda: NOW)

    def tearDown(self):
        self.svc.ledger.c.close()
        self.td.close()

    @staticmethod
    def scalp_plan(**kw):
        plan = {"setup_id": "SC-1", "direction": "BUY", "decision_ts": NOW, "sl": 1999.0, "tp1": 2001.0, "tp2": 2002.0, "fill_shadow": 2000.2,
                "spread_fill": 0.2, "entry_mode": "MARKET", "model_b": {"status": "UNAVAILABLE", "pass": False}, "range": {"atr_m5": 1.5}}
        plan.update(kw)
        return plan

    def scalp(self, plan):
        self.svc.on_scalp_setup(plan, status="BLOCKED", reasons=[], instrument="XAUUSD", symbol="XAUUSD-", f1=0.5, horizon_s=1800,
                                extra_cost=0.07, commission_known=True)
        return [json.loads(r["payload"]) for r in self.svc.ledger.c.execute(
            "SELECT payload FROM predictions WHERE json_extract(payload, '$.candidate.setup_id')=?", (plan["setup_id"],)).fetchall()]


class TestIndicatorContextLedger(_Eval):
    def test_observation_logged_assessment_identical(self):
        ic = {"status": "READY_INFERENCE", "task_id": "SCALP_TP1_FIRST_WITHIN_FROZEN_POLICY_V1", "p_tp1_first": 0.62, "threshold": 0.55,
              "groups": ["SAR"], "role": "SHADOW", "mode": "SHADOW"}
        with_ic = self.scalp(self.scalp_plan(indicator_context=ic))[0]
        without = self.scalp(self.scalp_plan(setup_id="SC-2"))[0]
        obs = (with_ic.get("observations") or {}).get("indicator_context")              # przed: brak pola
        self.assertEqual((obs or {}).get("p_tp1_first"), 0.62)
        self.assertEqual(obs["mode"], "SHADOW")
        self.assertNotIn("observations", without)
        a, b = dict(with_ic["assessment"]), dict(without["assessment"])
        for k in ("setup_id", "candidate_key", "assessment_id"):
            a.pop(k, None), b.pop(k, None)
        self.assertEqual(a, b)                                                            # the probability of the assessment is unchanged
        no_ready = self.scalp(self.scalp_plan(setup_id="SC-3", indicator_context={"status": "NO_MODEL"}))[0]
        self.assertNotIn("observations", no_ready)

    def test_docstring_no_longer_claims_probability_in_ledger(self):
        from masterquo.quant import adapters
        self.assertIn("observations", adapters.__doc__)


class TestEvaluationActiveProbAfterPromotion(_Eval):
    def test_challenger_row_of_the_current_champion_is_used(self):
        self.db.execute("INSERT INTO ml_predictions(at, setup_id, setup_version, model_id, role, raw_score, calibrated_probability, readiness, "
                        "contract_json) VALUES (?,?,?,?,?,?,?,?,?)", ("t", "S1", 1, "M2", "CHALLENGER_SHADOW", 0.4, 0.61, "READY",
                                                                       json.dumps({"target_definition": "TP1", "model_version": "v2"})))
        self.svc.ml = SimpleNamespace(registry=SimpleNamespace(champion_id="M2"), db=self.db)
        p = self.svc._active_prob({"setup_id": "S1", "version": 1}, None)
        self.assertIsNotNone(p)                                                           # przed: None
        self.assertEqual((p["value"], p["source"]), (0.61, "M2"))
        self.svc.ml.registry.champion_id = "M3"
        self.assertIsNone(self.svc._active_prob({"setup_id": "S1", "version": 1}, None))   # another model's row never counts


class TestEvaluationReportPerInstrument(_Eval):
    def _row(self, pid, inst, version, engine="SH_SCALPING", hit=True):
        from masterquo.evaluation import engine as E
        c = {"setup_id": pid, "engine": engine, "instrument": inst, "market_regime": {"both": {}}}
        a = {"engine": engine, "decision": "DEFER", "probability": 0.6}
        self.svc.ledger.log(pred_id=pid, model_id=f"{version or E.VERSION}/{engine}", artifact_id=None, feature_schema=None, symbol="X",
                            timeframe="M1", source_ts=NOW, available_at=NOW, matures_at=NOW + 60, horizon="60s", kind="SETUP_ASSESSMENT",
                            payload={"candidate": c, "assessment": a}, quality="OK")
        self.svc.ledger.c.execute("UPDATE predictions SET outcome=? WHERE pred_id=?",
                                  (json.dumps({"status": "MATURED", "event_hit": hit, "plan_r_net": 1.0 if hit else -1.0, "targets_hit": [hit]}), pid))

    def test_readiness_per_instrument_current_engine_only(self):
        self._row("A1", "XAUUSD", None)
        self._row("A2", "XAUUSD", None, hit=False)
        self._row("B1", "BTC", None)
        self._row("L1", "XAUUSD", "PMW-EVAL-OLD")
        rep = self.svc.report()
        r = rep["assist_readiness"]["SH_SCALPING"]
        self.assertEqual((r["matured"], r["instrument"]), (2, "XAUUSD"))                 # przed: 4 (BTC i stara wersja razem)
        by = rep["assist_readiness_by_instrument"]
        self.assertEqual((by["XAUUSD"]["SH_SCALPING"]["matured"], by["BTC"]["SH_SCALPING"]["matured"]), (2, 1))
        self.assertEqual(rep["matured"], 3)
        self.assertEqual(rep["legacy"]["PMW-EVAL-OLD/SH_SCALPING"]["matured"], 1)


class TestLabelPolicyInViews(_Eval):
    def test_evaluation_assessments(self):
        from masterquo.evaluation import engine as E
        self.scalp(self.scalp_plan())
        it = self.svc.assessments()[0]
        self.assertEqual(it["label_policy"], f"EVAL_BINARY_PLAN_APPROX/{E.VERSION}")       # przed: KeyError
        row = self.svc.ledger.c.execute("SELECT payload, outcome FROM predictions").fetchone()
        self.assertNotIn("label_policy", row["payload"])                                  # never stored

    def test_scalp_signals_quant_views(self):
        from masterquo.scalp.service import ScalpService
        sc = object.__new__(ScalpService)
        sc.db = self.db
        self.db.execute("INSERT INTO scalp_shadow(created_at, setup_id, profile_id, direction, decision_time_utc, status, reasons, plan, gates, hedge, "
                        "outcome_status, instrument) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        ("t", "SC-1", "P", "BUY", "2026-01-01T00:00:00Z", "BLOCKED", "[]", "{}", "[]", "{}", "NOT_APPLICABLE", "XAUUSD"))
        self.assertEqual(sc.recent(5)[0]["label_policy"], "SCALP_REPLAY_NET_V1")
        from masterquo.markets.signals import BotSignalService
        self.assertEqual(BotSignalService._public({"signal_id": "B1", "record_json": "{}", "synthetic": 0, "take_profits_json": "[]",
                                                            "validation_json": None})["label_policy"], "SIGNAL_M15_GROSS")
        from masterquo.quant import service as QS
        items = QS.with_label_policy([{"task_hash": "th1"}, {"status": "INVALID_PLAN"}])
        self.assertEqual([x["label_policy"] for x in items], ["QUANT_EVENTSPEC/th1", "QUANT_EVENTSPEC"])


# ---------------------------------------------------------------------------------------------------------------- I0041 (SI)
class TestSiForecastSnapshotId(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.db.database import Database
        self.db = Database()

    def tearDown(self):
        self.td.close()

    def test_forecast_rows_carry_the_snapshot_id(self):
        from masterquo.lab import si_service as SI
        from masterquo.lab import structure_task as T
        svc = SI.StructureIntelligenceService(None, SimpleNamespace(symbol_info={"point": 0.01}), self.db, SimpleNamespace(publish=lambda *a: None),
                                              None)
        fc = SimpleNamespace(model=object(), forecast=lambda *a, **k: {"forecast_status": "OK", "artifact_id": "ART-1", "as_of": "2026-01-01T00:00:00Z",
                                                                        "anchor_close": 2000.0, "anchor_atr": 1.0, "heads": [{"h_bars": 5}]})
        with mock.patch.object(T, "_reg", lambda inst: {}), mock.patch.object(T, "indicator_profile", lambda inst: {"hash": "h"}), \
                mock.patch.object(SI.StructureIntelligenceService, "mature", lambda self, inst, m1: 0):
            key = json.dumps({"shadow": None, "profile": "h"}, sort_keys=True)
            svc._fc, svc._fc_key = fc, ("XAUUSD", key)
            svc.forecast({"M1": []}, "XAUUSD", 0.01, "2026-01-01T00:00:00Z", snapshot_id="SIS-abc")
        self.assertEqual(self.db.one("SELECT snapshot_id FROM si_forecasts")["snapshot_id"], "SIS-abc")   # przed: TypeError / NULL


# ---------------------------------------------------------------------------------------------------------------- I0017
class TestLiveCandidateHasAtr(unittest.TestCase):
    def su(self, **kw):
        d = {"signal_id": "SH-A1", "strategy": "SCALPING", "symbol": "XAUUSD-", "instrument": "XAUUSD", "side": "BUY", "status": "READY",
             "entry_ref": 2000.0, "sl": 1998.0, "tps": [{"price": 2002.0, "share": 0.5}, {"price": 2004.0, "share": 0.5}], "created_at": NOW,
             "pack": {"features": {"atr_m5": 2.0}}}
        d.update(kw)
        return d

    def test_sh_and_scalp_candidates_carry_atr_never_invented(self):
        from masterquo.evaluation import contract as EK
        from masterquo.quant import features as F
        cd = EK.sh_candidate(self.su()).to_dict()
        self.assertEqual(cd["features"].get("atr_m5"), 2.0)                               # przed: brak
        self.assertAlmostEqual(F.build2(cd, [])["ctx:risk_atr"], 1.0)
        self.assertAlmostEqual(F.build_for(F.CURRENT, cd, [])["ctx:risk_atr"], 1.0)
        no = EK.sh_candidate(self.su(pack=None)).to_dict()
        self.assertNotIn("atr_m5", no["features"])
        self.assertNotIn("ctx:risk_atr", F.build2(no, []))
        bad = EK.sh_candidate(self.su(pack={"features": {"atr_m5": float("nan")}})).to_dict()
        self.assertNotIn("atr_m5", bad["features"])
        sc = EK.from_scalp_plan(_Eval.scalp_plan(), status="BLOCKED", reasons=[], instrument="XAUUSD", symbol="XAUUSD-", f1=0.5,
                                horizon_s=1800).to_dict()
        self.assertEqual(sc["features"].get("atr_m5"), 1.5)

    def test_existing_metamodel_input_unchanged(self):
        """A MetaModel learnt from ledger rows without ATR has no ctx:risk_atr / fcp:*:d_atr column - its vector is identical."""
        from masterquo.evaluation import contract as EK
        from masterquo.quant import features as F
        with_atr = F.build2(EK.sh_candidate(self.su()).to_dict(), [])
        without = F.build2(EK.sh_candidate(self.su(pack=None)).to_dict(), [])
        names = sorted(without)
        self.assertEqual(F.vectorise(with_atr, names), F.vectorise(without, names))

    def test_reconstructed_candidate_carries_spread_and_coverage_report(self):
        from masterquo.quant import tabicl as TB
        su = self.su(costs={"spread": 0.25, "round_trip_price": 0.4}, position_max_minutes=60)
        cd = TB.recon_candidate("XAUUSD", "PMW_SC01", NOW, su)
        self.assertEqual(cd["execution_context"]["spread"], 0.25)                         # przed: brak funkcji / brak spreadu
        self.assertEqual(cd["features"]["atr_m5"], 2.0)
        rows = [{"provenance": "LIVE_LEDGER", "features": {"a": 1.0, "b": 1.0}}, {"provenance": "RECONSTRUCTED_HISTORY", "features": {"a": 1.0, "c": 2.0}}]
        cov = TB.coverage_by_provenance(rows, ["a", "b", "c"])
        self.assertEqual(cov["LIVE_LEDGER"]["missing_columns"], ["c"])
        self.assertEqual(cov["RECONSTRUCTED_HISTORY"]["missing_columns"], ["b"])


# ---------------------------------------------------------------------------------------------------------------- I0082
class TestProducersDoNotImportModelhub(unittest.TestCase):
    def test_no_modelhub_import_in_producers(self):
        bad = []
        for pkg in ("kronos", "tsfm", "trainhub"):
            for f in sorted((MQ / pkg).rglob("*.py")):
                tree = ast.parse(f.read_text(encoding="utf-8"))
                for n in ast.walk(tree):
                    mods = []
                    if isinstance(n, ast.ImportFrom):
                        mods = [n.module or ""] + ([f"{n.module}.{a.name}" for a in n.names] if n.module else [a.name for a in n.names])
                    elif isinstance(n, ast.Import):
                        mods = [a.name for a in n.names]
                    if any(m == "modelhub" or m.startswith("modelhub.") or "masterquo.modelhub" in m for m in mods):
                        bad.append(f"{f.relative_to(MQ)}:{n.lineno}")
        self.assertEqual(bad, [])                                                        # przed: 3 naruszenia

    def test_shim_is_the_same_module_and_leaf_is_stdlib_only(self):
        from masterquo.contracts import prediction as P
        from masterquo.modelhub import contract as C
        self.assertIs(C, P)
        tree = ast.parse((MQ / "contracts" / "prediction.py").read_text(encoding="utf-8"))
        rel = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.level]
        self.assertEqual(rel, [])


if __name__ == "__main__":
    unittest.main()
