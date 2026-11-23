"""1.46 audit (group B_core_exec_1) - regression tests for decision/{contracts,coordinator,ledger}.py and
engine/{active,checklist,context_tf,decision,service,setup_details,signal_contract,volzones}.py.

Unit level only: isolated data dir (TempData), fakes instead of the terminal / HTTP server, no order is ever sent."""
from __future__ import annotations

import threading
import time
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest import mock

import _env  # noqa: F401  (sys.path, offline flags)
from _env import TempData

NOW = time.time()


def _iso(age_s: float) -> str:
    return datetime.fromtimestamp(NOW - age_s, UTC).isoformat()


class Store:
    def __init__(self, **upd):
        from masterquo.config import AppConfig
        self.c = AppConfig()
        for sec, kv in upd.items():
            for k, v in kv.items():
                setattr(getattr(self.c, sec), k, v)

    def get(self):
        return self.c


# ---------------------------------------------------------------------------------------------------------------- coordinator
class TestCoordinatorRecordsMatchTheGate(unittest.TestCase):
    """chunk_08#6, chunk_08#7, chunk_08#9."""

    def setUp(self):
        self.td = TempData()
        from masterquo.db.database import Database
        from masterquo.decision.coordinator import DecisionCoordinator
        self.db = Database()
        self.preds: list[dict] = []
        fam = SimpleNamespace(predictions=lambda inst: list(self.preds))
        self.store = Store()
        self.arc = DecisionCoordinator(self.db, self.store, families=fam, instrument_fn=lambda: "XAUUSD", clock=lambda: NOW)

    def tearDown(self):
        self.db.close()
        self.td.close()

    @staticmethod
    def _decision(direction="LONG"):
        return {"decision_id": "MQD-T1", "symbol": "XAUUSD-", "analysis_direction": direction, "execution_permission": "BLOCKED",
                "decision": "WAIT", "decision_tree": [{"node": "DATA", "status": "PASS"}, {"node": "MODELS", "status": "FAIL"}],
                "risk": {"entry": 2000.0, "stop_loss": 1990.0, "targets": [{"price": 2030.0}], "modeled_loss": 10.0, "lots": 0.1},
                "setup": {"strategy_id": "S11"}, "reason_codes": [], "mode_gate": {"reason_codes": []}, "account_key": "P"}

    def test_record_active_keeps_the_gate_verdict_of_a_fresh_tsfm_forecast(self):
        # Chronos DOWN 1500 s old, its own max_age_s 7200 (H1), ASSIST, setup LONG -> the gate holds the entry
        self.preds = [{"family": "tsfm:chronos2", "use": "ASSIST", "state": "READY", "task_type": "REGRESSION",
                       "result": {"direction": "DOWN"}, "data_time": _iso(1500), "max_age_s": 7200}]
        gate = self.arc.model_gate_active({"direction": "LONG"})
        self.assertEqual((gate["status"], gate["codes"]), ("FAIL", ["MODEL_ASSIST_HOLD:tsfm:chronos2"]))
        d = self._decision()
        rec = self.arc.record_active(d, "PAPER", gate)
        # 1.45: the record re-evaluated without max_age_s (900 s default) -> ENTER -> ENTER with no reason
        self.assertEqual(rec["final_verdict"], "BLOCKED")
        self.assertIn("MODEL_ASSIST_HOLD:tsfm:chronos2", rec["reason_codes"])
        self.assertEqual(d["decision_record"]["final_verdict"], "BLOCKED")
        self.assertEqual([m["influence"] for m in rec["models"]], ["HOLD"])

    def test_record_active_required_pass_is_not_recorded_as_stale(self):
        self.store.c.decision.required_models = ["tsfm:chronos2"]
        self.preds = [{"family": "tsfm:chronos2", "use": "ASSIST", "state": "READY", "task_type": "REGRESSION",
                       "result": {"direction": "UP"}, "data_time": _iso(1500), "max_age_s": 7200}]
        gate = self.arc.model_gate_active({"direction": "LONG"})
        self.assertEqual(gate["status"], "PASS")
        d = dict(self._decision(), execution_permission="ALLOWED", decision_tree=[{"node": "MODELS", "status": "PASS"}])
        rec = self.arc.record_active(d, "PAPER", gate)
        self.assertEqual(rec["final_verdict"], "ENTER")                      # 1.45: BLOCKED MODEL_REQUIRED_STALE
        self.assertFalse([r for r in rec["reason_codes"] if r.startswith("MODEL_")])

    def test_coordinator_error_gate_is_recorded_with_its_own_code(self):
        self.store.c.decision.required_models = ["GARCH"]
        rec = self.arc.record_active(self._decision(), "PAPER", {"status": "FAIL", "codes": ["MODEL_COORDINATOR_ERROR_RuntimeError"]})
        self.assertEqual(rec["final_verdict"], "BLOCKED")
        self.assertIn("MODEL_COORDINATOR_ERROR_RuntimeError", rec["reason_codes"])

    def _su(self):
        return {"signal_id": "SH-B1", "strategy": "SCALPING", "symbol": "XAUUSD-", "side": "BUY", "status": "READY", "entry_ref": 2000.0,
                "sl": 1998.0, "tps": [{"price": 2003.0}], "family_context": {"context": []}}

# ---------------------------------------------------------------------------------------------------------------- ledger
class TestLedgerHedgeAndReserveErrors(unittest.TestCase):
    """Guard: an ENTRY intent still follows its plan state (chunk_08#2 / chunk_08#4 are owner decisions - see docs/AUDYT_1_45.md)."""

    def setUp(self):
        self.td = TempData()
        from masterquo.db.database import Database
        from masterquo.decision.ledger import IntentLedger, RiskBook
        self.db = Database()
        self.store = Store(risk={"max_open_positions": 5})
        self.book = RiskBook(self.db, self.store, sh_limits=dict, clock=lambda: NOW)
        self.led = IntentLedger(self.db, self.book)

    def tearDown(self):
        self.db.close()
        self.td.close()

    def _plan(self, pid="PL-1", state="PRIMARY_OPEN"):
        self.db.execute("INSERT INTO sh_plans(plan_id, signal_id, strategy, instrument, symbol, side, exec_mode, account_key, state, config_hash, plan, "
                        "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (pid, "SIG-1", "HEDGING", "XAUUSD", "XAUUSD-", "BUY", "PAPER", "P", state, "h", "{}", NOW, NOW))

    def _hedge(self, pid="PL-1"):
        op = self.led.open(path="SH", mode="PAPER", account_key="P", subject=f"{pid}:HEDGE1", symbol="XAUUSD-", side="SELL", volume=0.05,
                           risk_money=None, record_id=None, equity=1000.0, kind="HEDGE")
        self.assertEqual(op["status"], "RESERVED")
        iid = op["intent"]["intent_id"]
        self.led.sent(iid, pid)                                                  # as sh/service.pack_hedge_step: source_ref = main plan
        return iid

    def _res_state(self, iid):
        rid = self.led.get(iid)["reservation_id"]
        return self.db.one("SELECT state FROM risk_reservations WHERE reservation_id=?", (rid,))["state"]

    def test_entry_intent_still_follows_the_plan_state(self):
        self._plan("PL-3", state="PENDING_ENTRY")
        op = self.led.open(path="SH", mode="PAPER", account_key="P", subject="PL-3", symbol="XAUUSD-", side="BUY", volume=0.1, risk_money=5.0,
                           record_id=None, equity=1000.0)
        self.led.sent(op["intent"]["intent_id"], "PL-3")
        self.led.sync()
        self.assertEqual(self.led.get(op["intent"]["intent_id"])["state"], "SENT")
        self.db.execute("UPDATE sh_plans SET state='OPEN' WHERE plan_id='PL-3'")
        self.led.sync()
        self.assertEqual(self.led.get(op["intent"]["intent_id"])["state"], "RECONCILED_FILLED")

# ---------------------------------------------------------------------------------------------------------------- decision / signal
def _build(*, active=True, model_gate=None, setup_state="CONFIRMED", d1_blocks=True):
    from masterquo.config import AppConfig
    from masterquo.engine import decision as D
    cfg = AppConfig()
    cfg.strategy.d1_conflict_blocks_entry = d1_blocks
    setup = {"setup_id": "MQA-S1", "strategy_id": "S11", "strategy_name": "EMA pullback", "state": setup_state, "signal_stage": setup_state,
             "direction": "LONG", "setup_tf": "M15", "profile": "ACTIVE", "version": 2, "entry_plan": {"reference_price": 2000.0}}
    levels = {"status": "AVAILABLE", "stop_loss": 1990.0, "targets": [{"price": 2030.0, "weight": 1.0}]}
    dq = {"analysis_allowed": True, "entries_allowed": True, "market_state": "OPEN", "reason_codes": [], "data_quality": "GOOD"}
    legacy = {"m02": {"structural_direction": "BULLISH", "timeframes": {"D1": {"direction": "BEARISH"}}}}
    return D.build(snapshot_id="SNAP-1", as_of="2026-11-23T10:00:00Z", symbol="XAUUSD-", account_key="P", session_epoch=1, dq=dq,
                   legacy=legacy, setup=setup, levels=levels, risk={"risk_gate": "PASS", "reason_codes": []},
                   agent_gate={"status": "NOT_REQUIRED"}, mode_gate={"allowed": True, "mode": "PAPER", "reason_codes": []},
                   macro={"status": "OK"}, strategy_cfg=cfg.strategy, risk_cfg=cfg.risk, dxy_status="OK", synthetic=True,
                   active={"regime": {}, "bias": "LONG", "trade_allowed": True, "reason_codes": []} if active else None,
                   model_gate=model_gate)


class TestDecisionAndSignalPresentation(unittest.TestCase):
    """chunk_09#7, chunk_09#2, chunk_09#10, chunk_09#12, chunk_09#14."""

    def test_active_profile_conflict_rule_does_not_claim_a_d1_block(self):
        d = _build(active=True, d1_blocks=True)
        self.assertFalse(d["structure"]["d1_conflict"])
        self.assertNotIn("blokuje wejścia przy konflikcie", d["structure"]["conflict_rule"])
        self.assertIn("ORIGINAL", d["structure"]["conflict_rule"])
        legacy = _build(active=False, d1_blocks=True)                          # profile ORIGINAL: the rule really applies
        self.assertTrue(legacy["structure"]["d1_conflict"])
        self.assertIn("blokuje wejścia przy konflikcie", legacy["structure"]["conflict_rule"])

    def test_models_node_gives_block_reasons_and_a_checklist_gate(self):
        from masterquo.engine import checklist, signal_contract
        d = _build(model_gate={"status": "FAIL", "codes": ["MODEL_ASSIST_HOLD:LSTM"], "models": []})
        self.assertEqual(d["decision"], "WAIT")
        sig = signal_contract.build(d, quote={"bid": 2000.0, "ask": 2000.2}, row=None, agent_result=None, agent_status=None, context={},
                                    costs={}, attempts=[], ml=None, data_source="SYNTHETIC")
        self.assertEqual(sig["status"], "ZABLOKOWANY")
        self.assertIn("MODELS:MODEL_ASSIST_HOLD:LSTM", sig["block_reasons"])    # 1.45: ZABLOKOWANY with []
        cl = checklist.build(d, None)
        g = {x["id"]: x for x in cl["gates"]}
        self.assertEqual(g["MODELS"]["status"], "MISSING")
        self.assertEqual(g["MODELS"]["reasons"], ["MODEL_ASSIST_HOLD:LSTM"])

    def test_m3_is_not_a_context_timeframe(self):
        from masterquo.engine import context_tf, signal_contract
        self.assertEqual(set(context_tf.summarize({}, {})), {"M30", "H8"})
        sig = signal_contract.build(_build(), quote={"bid": 2000.0, "ask": 2000.2}, row=None, agent_result=None, agent_status=None,
                                    context={}, costs={}, attempts=[], ml=None, data_source="SYNTHETIC")
        self.assertEqual(sig["context_tfs"], ["H1", "H4", "M30", "H8"])
        self.assertEqual(set(sig["data_flags"]["context"]), {"M30", "H8"})

    def test_terminal_status_maps_by_status_not_reason(self):
        from masterquo.engine import signal_contract
        kw = {"quote": {"bid": 2000.0, "ask": 2000.2}, "agent_result": None, "agent_status": None, "context": {}, "costs": {}, "attempts": [],
              "ml": None, "data_source": "SYNTHETIC"}
        self.assertEqual(signal_contract.build(_build(), row={"status": "EXPIRED", "terminal_reason": "TTL_ELAPSED"}, **kw)["status"], "WYGASŁY")
        self.assertEqual(signal_contract.build(_build(), row={"status": "MISSED_ENTRY", "terminal_reason": "CONFIRMED_WINDOW_ELAPSED"},
                                               **kw)["status"], "WYGASŁY")
        self.assertEqual(signal_contract.build(_build(), row={"status": "INVALIDATED", "terminal_reason": "CLOSE_BEYOND_INVALIDATION"},
                                               **kw)["status"], "UNIEWAŻNIONY")

    def test_fmt_small_values_keep_precision(self):
        from masterquo.engine import checklist
        self.assertEqual(checklist._fmt(0.00042), "0.00042")                      # 1.45: '0.00'
        self.assertEqual(checklist._fmt(0.149), "0.149")
        self.assertEqual(checklist._fmt(2034.567), "2034.57")
        self.assertEqual(checklist._fmt(0.0), "0.00")
        self.assertEqual(checklist._fmt(True), "tak")


# ---------------------------------------------------------------------------------------------------------------- volzones
class TestVolzonesFlatHistory(unittest.TestCase):
    """chunk_09#8."""

    def test_flat_d1_bars_give_zero_volatility_status_not_an_exception(self):
        from masterquo.config import VolatilityConfig
        from masterquo.engine import volzones
        bars = [{"open_utc": f"2026-01-{1 + i % 28:02d}T00:00:00Z", "o": 100.0, "h": 100.0, "l": 100.0, "c": 100.0, "closed": True}
                for i in range(30)]
        bars.append({"open_utc": "2026-02-01T00:00:00Z", "o": 100.0, "h": 100.0, "l": 100.0, "c": 100.0, "closed": False})
        for est in ("close_to_close", "parkinson"):
            v = volzones.compute(bars, VolatilityConfig(estimator=est), digits=2)  # 1.45: ZeroDivisionError
            self.assertEqual(v["status"], "ZERO_VOLATILITY", est)
            self.assertNotIn("walls", v)
            self.assertEqual(v["hv_annual_pct"], 0.0)
        with self.assertRaises(ValueError):
            volzones.black76(100.0, 100.0, 0.0, 1 / 252)


# ---------------------------------------------------------------------------------------------------------------- engine service
class TestEngineServicePieces(unittest.TestCase):
    """chunk_09#4, chunk_09#9, chunk_09#15 (EngineService methods on small fakes)."""

    def test_structure_after_switching_to_an_unsupported_asset(self):
        from masterquo.config import AppConfig
        from masterquo.engine.service import EngineService
        cfg = AppConfig()
        view = SimpleNamespace(symbol=cfg.mt5.symbol, as_of="2026-11-23T10:00:00Z", synthetic=True, context={}, tfs={})
        fake = SimpleNamespace(active=SimpleNamespace(view=view), cfg_store=SimpleNamespace(get=lambda: cfg),
                               bridge=SimpleNamespace(bars=lambda tf: [], symbol_info={}))
        self.assertEqual(EngineService.structure(fake, "M5")["status"], "OK")
        cfg.assets.active = "BTC"
        cfg.mt5.symbol = "BTCUSD"
        fake._structure_cache = None
        out = EngineService.structure(fake, "M5")
        self.assertEqual(out["status"], "UNSUPPORTED_ASSET")                     # 1.45: the old XAUUSD view as OK
        self.assertNotIn("walls", out)
        cfg.assets.active = "XAUUSD"                                             # XAUUSD under another broker symbol: no scan of it yet
        self.assertEqual(EngineService.structure(fake, "M5")["status"], "NO_SCAN_YET")

    def test_last_signal_key_is_bounded(self):
        from masterquo.engine.service import EngineService
        fake = SimpleNamespace(_last_signal_key={}, db=SimpleNamespace(execute=lambda *a, **k: None),
                               bus=SimpleNamespace(publish=lambda *a, **k: None))
        for i in range(800):
            EngineService._record_signal(fake, {"signal_id": f"SIG-MQA-{i}-v1", "status": "OCZEKIWANIE", "execution_state": "BRAK",
                                                "generated_at": "t", "symbol": "X", "setup_id": str(i), "strategy_id": "S11", "entry_tf": "M15",
                                                "side": "LONG", "decision_source": "STRATEGIA"})
        self.assertLessEqual(len(fake._last_signal_key), 500)
        self.assertIn("SIG-MQA-799-v1", fake._last_signal_key)

    def _risk_fake(self):
        from masterquo.config import AppConfig
        from masterquo.db.database import Database
        cfg = AppConfig()
        bridge = SimpleNamespace(_lock=threading.Lock(), positions=[], deals=[], orders=[], server_day_start_utc=lambda: None,
                                 clock=SimpleNamespace(offset=None), account_key="P", account_status=dict, symbol_info={}, account={})
        return SimpleNamespace(cfg_store=SimpleNamespace(get=lambda: cfg), bridge=bridge, db=Database(), prefs=None, modes=None,
                               portfolio_snapshot=lambda p, o: {"positions_notional": 0.0})

    def test_preview_without_quote_is_flagged_spread_unknown(self):
        from masterquo.engine.service import EngineService
        td = TempData()
        try:
            fake = self._risk_fake()
            seen = {}

            def ev(**kw):
                seen.update(kw)
                return {"risk_gate": "PASS", "reason_codes": [], "lots": 0.1}
            with mock.patch("masterquo.engine.service.risk_engine.evaluate", side_effect=ev), \
                    mock.patch("masterquo.engine.service.risk_engine.open_risk", return_value={"total": 0.0}):
                levels = {"status": "AVAILABLE", "stop_loss": 1990.0, "targets": [{"price": 2030.0, "weight": 1.0}]}
                r = EngineService._risk(fake, "LONG", levels, None, False, 2000.0)
                self.assertEqual(r["risk_gate"], "PREVIEW")
                self.assertIn("SPREAD_UNKNOWN_PREVIEW", r["reason_codes"])        # 1.45: sized with spread 0, nothing said
                self.assertEqual(seen["quote"]["ask"], 2000.0)                    # the computation itself is unchanged
                r = EngineService._risk(fake, "LONG", levels, {"bid": 1999.8, "ask": 2000.0, "spread": 0.2, "spread_points": 20}, False, 2000.0)
                self.assertNotIn("SPREAD_UNKNOWN_PREVIEW", r["reason_codes"])
            fake.db.close()
        finally:
            td.close()


class TestActiveStatusTradeDefault(unittest.TestCase):
    """chunk_09#11."""

    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_status_trade_matches_trade_allowed(self):
        from masterquo.db.database import Database
        from masterquo.engine.active import ActiveEngine, trade_allowed
        from masterquo.strategies import registry
        store = Store()
        # a config saved before S11/S12 had toggles (no entry -> the registry default applies)
        store.c.active.strategies = {k: v for k, v in store.c.active.strategies.items() if k not in registry.DEFAULT_NO_TRADE}
        db = Database()
        eng = ActiveEngine(db, store, SimpleNamespace(), SimpleNamespace(), SimpleNamespace(publish=lambda *a, **k: None))
        st = {s["strategy_id"]: s for s in eng.status()["strategies"]}
        for sid in registry.DEFAULT_NO_TRADE:
            self.assertFalse(trade_allowed(store.c.active, sid))
            self.assertFalse(st[sid]["trade"], sid)                               # 1.45: True while trade_allowed() was False
        for sid, s in st.items():
            self.assertEqual(s["trade"], trade_allowed(store.c.active, sid), sid)
        db.close()


# ---------------------------------------------------------------------------------------------------------------- setup details
class _Tracker:
    def __init__(self, row):
        self.row = row

    def get(self, sid):
        return self.row if sid == self.row["setup_id"] else None


class TestSetupDetails(unittest.TestCase):
    """chunk_09#5, chunk_09#6."""

    def setUp(self):
        self.td = TempData()
        from masterquo.config import AppConfig
        from masterquo.db.database import Database
        from masterquo.engine.service import EngineService
        self.db = Database()
        self.cfg = AppConfig()
        rec = {"strategy_id": "S11", "strategy_version": "1", "strategy_name": "EMA pullback", "timeframe": "M15", "direction": "LONG",
               "reason_codes": ["PULLBACK"], "facts": {}, "score": {}, "setup_score": 80, "missing_confirmations": [],
               "entry_plan": {"reference_price": 2000.0, "trigger_level": 2000.0}, "invalidation_level": 1985.0, "stop_loss": 1990.0,
               "targets": [{"price": 2020.0, "weight": 1.0}], "exit_rules": {"tp_rule": "RR_FROM_FILL", "rr": 2.0}}
        self.row = {"setup_id": "MQA-D1", "version": 1, "stage": "CONFIRMED", "status": "ACTIVE", "stale": False, "expires_at": None,
                    "first_seen_at": "2026-11-23T09:00:00Z", "updated_at": "2026-11-23T09:30:00Z", "account_key": "ACC-A", "symbol": "XAUUSD-",
                    "record": rec}
        self.seen = {}
        test = self

        class Eng:
            _tp_from_entry = EngineService._tp_from_entry

            def __init__(self):
                self.active = SimpleNamespace(tracker=_Tracker(test.row), selector=SimpleNamespace(selected={"setup_id": "MQA-D1"}, state={}),
                                              prefs=None)
                self.bridge = SimpleNamespace(account_key="ACC-A", quote_status=lambda: {"bid": 2000.8, "ask": 2001.0, "spread": 0.2},
                                              symbol_info={"digits": 2}, synthetic=True, account={})
                self.cfg_store = SimpleNamespace(get=lambda: test.cfg)
                self.db = test.db
                self.modes = SimpleNamespace(mode="PAPER")
                self.prefs = None
                self.dq = None

            def current_decision(self):
                return {}

            def _risk(self, direction, levels, quote, live, hypo):
                test.seen["levels"] = levels
                return {"risk_gate": "PASS", "reason_codes": [], "lots": 0.1}

            def _bars(self):
                return {}
        self.eng = Eng()

    def tearDown(self):
        self.db.close()
        self.td.close()

    def test_confirmed_rr_from_fill_plan_is_sized_on_the_engine_levels(self):
        from masterquo.engine import setup_details
        d = setup_details.details(self.eng, "MQA-D1")
        tp = self.seen["levels"]["targets"]
        self.assertEqual([t["price"] for t in tp], [2023.0])                     # Ask 2001 + 2.0 x (2001 - 1990); 1.45: 2020 (signal close)
        self.assertEqual(d["levels"]["targets"], [2023.0])

    def _trade(self, tid, mode, acct, cur, net):
        self.db.execute("INSERT INTO trades(trade_id, mode, source, account_key, strategy_id, symbol, side, volume, opened_at, closed_at, gross_pnl, "
                        "commission, swap, fee, net_pnl, currency, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (tid, mode, "BOT", acct, "S11", "XAUUSD-", "BUY", 0.1, "2026-11-01T10:00:00Z", f"2026-11-0{len(tid)}T11:00:00Z",
                         net, 0.0, 0.0, 0.0, net, cur, "CLOSED"))

    def test_history_is_this_accounts_and_never_sums_modes_or_currencies(self):
        from masterquo.engine import setup_details
        self._trade("T1", "AUTO_DEMO", "ACC-A", "USD", 10.0)
        self._trade("T22", "AUTO_DEMO", "ACC-A", "USD", -4.0)
        self._trade("T333", "AUTO_DEMO", "ACC-B", "EUR", 1000.0)                 # another account (1.45: summed in)
        h = setup_details.details(self.eng, "MQA-D1")["history"]
        self.assertEqual(h["trades"], 2)
        self.assertEqual(h["stats"]["net"], 6.0)
        self._trade("T4444", "PAPER", "ACC-A", "PLN", 50.0)
        h = setup_details.details(self.eng, "MQA-D1")["history"]
        self.assertEqual(h["trades"], 3)
        self.assertIsNone(h["stats"])                                            # PAPER/PLN + AUTO_DEMO/USD are not one number
        by = {(g["mode"], g["currency"]): g["stats"]["net"] for g in h["by_mode"]}
        self.assertEqual(by, {("AUTO_DEMO", "USD"): 6.0, ("PAPER", "PLN"): 50.0})


# ---------------------------------------------------------------------------------------------------------------- contracts
class TestInstrumentSpecNoDefaults(unittest.TestCase):
    """chunk_08#12."""

    def test_digits_zero_kept_and_missing_fields_refused(self):
        from masterquo.decision import contracts as K
        s = K.instrument_spec("US500", {"digits": 0, "point": 1.0, "trade_tick_size": 0.25, "trade_tick_value": 12.5})
        self.assertEqual((s["digits"], s["point"], s["tick_size"]), (0, 1.0, 0.25))      # 1.45: digits 0 -> 2
        for missing in ("digits", "point", "trade_tick_size"):
            info = {"digits": 2, "point": 0.01, "trade_tick_size": 0.01}
            info.pop(missing)
            with self.assertRaises(K.ContractViolation, msg=missing):                     # 1.45: 2 / 0.01 invented
                K.instrument_spec("XAUUSD-", info)


if __name__ == "__main__":
    unittest.main()
