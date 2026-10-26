"""Shared setup evaluation (SHADOW, docs: REFACTOR_PLAN.md phases B-D): contract, P/EV engine, outcome labels, read-only exposure,
ledger service, per-engine statistics and isolation from the order path."""
import ast
import json
import unittest
from pathlib import Path

import _env  # noqa: F401
from _env import TempData
from test_sh_service import NOW, Bridge, Log, mk_setup

from masterquo.evaluation import contract as K
from masterquo.evaluation import engine as E
from masterquo.evaluation import outcome as O


def cand(**kw):
    base = dict(setup_id="S-1", engine="SH_SCALPING", strategy_id="SCALPING", symbol="XAUUSD-", instrument="XAUUSD", timeframe="M1",
                decision_ts=NOW, direction="LONG", entry_type="MARKET", entry_price=100.0, stop_loss=99.0,
                targets=[{"price": 102.0, "weight": 1.0}], horizon_s=1800.0)
    base.update(kw)
    return K.SetupCandidate(**base)


def m1(t0, rows):
    """rows: (h, l, c) per closed M1 bar starting at t0."""
    from datetime import datetime, timezone
    return [{"open_utc": datetime.fromtimestamp(t0 + 60 * i, timezone.utc).isoformat().replace("+00:00", "Z"), "o": c, "h": h, "l": l, "c": c,
             "closed": True} for i, (h, l, c) in enumerate(rows)]


class Contract(unittest.TestCase):
    def test_valid_candidate(self):
        self.assertEqual(cand().validate().risk_price(), 1.0)

    def test_rejects_wrong_levels_and_weights(self):
        for kw, code in ((dict(stop_loss=101.0), "STOP_ON_WRONG_SIDE"), (dict(targets=[{"price": 99.5, "weight": 1.0}]), "TARGET_ON_WRONG_SIDE"),
                         (dict(targets=[{"price": 102.0, "weight": 0.6}]), "TARGET_WEIGHTS_SUM"), (dict(entry_price=float("nan")), "NOT_FINITE"),
                         (dict(targets=[]), "NO_TARGETS"), (dict(timeframe="M2"), "TIMEFRAME_INVALID"), (dict(engine="X"), "ENGINE_UNKNOWN")):
            with self.assertRaises(K.ContractError) as cm:
                cand(**kw).validate()
            self.assertIn(code, str(cm.exception))

    def test_lookahead_is_a_violation(self):
        with self.assertRaises(K.ContractError) as cm:
            cand(features_as_of=NOW + 60).validate()
        self.assertIn("LOOKAHEAD", str(cm.exception))
        with self.assertRaises(K.ContractError):
            cand(data_quality={"status": "OK", "data_as_of": NOW + 1}).validate()

    def test_sh_adapter_uses_shares_and_horizon(self):
        from masterquo.sh.units import SymbolSpec
        spec = SymbolSpec.from_mt5(Bridge().symbol_info, {"margin_mode": 2})
        c = K.from_sh_setup(mk_setup(spec, "HEDGING", "SELL", ref=2000.0)).validate()
        self.assertEqual(c.engine, "SH_HEDGING")
        self.assertEqual(c.direction, "SHORT")
        self.assertAlmostEqual(sum(t["weight"] for t in c.targets), 1.0)
        self.assertEqual(c.horizon_s, 1800.0)


class Engine(unittest.TestCase):
    def test_economics_and_break_even(self):
        e = E.economics(cand(), 0.1)
        self.assertAlmostEqual(e["gain_r"], 1.9)
        self.assertAlmostEqual(e["loss_r"], 1.1)
        self.assertAlmostEqual(e["break_even_p"], 1.1 / 3.0)

    def test_no_calibrated_probability_defers_with_threshold(self):
        a = E.assess(cand(), prob=None, extra_cost=0.1)
        self.assertEqual(a.decision, "DEFER")
        self.assertIsNone(a.probability)
        self.assertTrue(any("P > 0.367" in n for n in a.notes))
        raw = E.assess(cand(), prob={"value": 0.9, "calibrated": False}, extra_cost=0.1)   # a raw score is never used as P
        self.assertEqual((raw.decision, raw.probability_status), ("DEFER", "UNCALIBRATED"))

    def test_ev_sign_decides(self):
        lo = E.assess(cand(), prob={"value": 0.30, "calibrated": True, "n_calibration": 500}, extra_cost=0.1)
        self.assertEqual(lo.decision, "REJECT")
        self.assertAlmostEqual(lo.expected_value_r, 0.3 * 1.9 - 0.7 * 1.1, places=4)
        hi = E.assess(cand(), prob={"value": 0.60, "calibrated": True, "n_calibration": 2000}, extra_cost=0.1)
        self.assertEqual(hi.decision, "ACCEPT")
        self.assertGreater(hi.expected_value_interval_r[0], 0)

    def test_uncertainty_reduces(self):
        a = E.assess(cand(), prob={"value": 0.42, "calibrated": True, "n_calibration": 40}, extra_cost=0.1)
        self.assertEqual(a.decision, "REDUCE")
        self.assertEqual(a.rejection_reasons, ["EV_INTERVAL_STRADDLES_ZERO"])
        b = E.assess(cand(), prob={"value": 0.60, "calibrated": True}, extra_cost=0.1)           # n unknown -> interval unknown
        self.assertEqual((b.decision, b.rejection_reasons), ("REDUCE", ["EV_INTERVAL_UNKNOWN"]))

    def test_hard_rejections_independent_of_model(self):
        p = {"value": 0.9, "calibrated": True, "n_calibration": 5000}
        self.assertIn("TARGETS_DO_NOT_COVER_COSTS", E.assess(cand(), prob=p, extra_cost=2.5).rejection_reasons)
        self.assertEqual(E.assess(cand(execution_context={"spread": 0.5}), prob=p, extra_cost=0.1).decision, "REJECT")
        self.assertIn("PORTFOLIO_CONFLICT", E.assess(cand(), prob=p, extra_cost=0.1, exposure={"status": "CONFLICT"}).rejection_reasons)
        self.assertIn("DATA_STALE", E.assess(cand(data_quality={"status": "STALE"}), prob=p, extra_cost=0.1).rejection_reasons)

    def test_event_mismatch_is_labelled(self):
        a = E.assess(cand(engine="ACTIVE_S01_S12"), prob={"value": 0.6, "calibrated": True, "event_matches": False}, extra_cost=0.1)
        self.assertEqual(a.probability_status, "EVENT_MISMATCH")
        self.assertEqual(a.mode, "SHADOW")


class Outcome(unittest.TestCase):
    def c(self, **kw):
        return cand(targets=[{"price": 101.0, "weight": 0.5}, {"price": 102.0, "weight": 0.5}], **kw).to_dict()

    def test_targets_before_sl(self):
        out = O.label(self.c(), m1(NOW, [(100.5, 99.6, 100.4), (101.2, 100.3, 101.0), (102.1, 100.9, 102.0)]), cost_r=0.1)
        self.assertEqual(out["targets_hit"], [True, True])
        self.assertEqual(out["exit"], "ALL_TARGETS")
        self.assertAlmostEqual(out["plan_r_gross"], 1.5)
        self.assertAlmostEqual(out["plan_r_net"], 1.4)
        self.assertAlmostEqual(out["mae_r"], 0.4)
        self.assertTrue(O.event_hit("SH_SCALPING", out))

    def test_ambiguous_bar_counts_sl_first(self):
        out = O.label(self.c(), m1(NOW, [(101.5, 98.9, 100.0)]))
        self.assertEqual((out["exit"], out["targets_hit"], out["ambiguous_bars"]), ("SL", [False, False], 1))
        self.assertAlmostEqual(out["plan_r_gross"], -1.0)
        self.assertFalse(O.event_hit("SH_SCALPING", out))

    def test_partial_then_sl(self):
        out = O.label(self.c(), m1(NOW, [(101.1, 100.2, 101.0), (100.5, 98.8, 99.0)]))
        self.assertEqual(out["targets_hit"], [True, False])
        self.assertAlmostEqual(out["plan_r_gross"], 0.5 * 1.0 - 0.5)

    def test_timeout_marks_remainder_at_last_close(self):
        out = O.label(self.c(), m1(NOW, [(100.6, 99.7, 100.5)]))
        self.assertEqual(out["exit"], "TIMEOUT")
        self.assertAlmostEqual(out["plan_r_gross"], 0.5)

    def test_short_exits_on_ask(self):
        c = cand(direction="SHORT", entry_price=100.0, stop_loss=101.0, targets=[{"price": 99.0, "weight": 1.0}],
                 execution_context={"spread": 0.3}).to_dict()
        out = O.label(c, m1(NOW, [(100.2, 98.8, 99.0)]))            # Bid low 98.8 -> Ask 99.1: the target is NOT reached
        self.assertEqual(out["targets_hit"], [False])
        out = O.label(c, m1(NOW, [(100.2, 98.6, 99.0)]))            # Ask 98.9 <= 99.0
        self.assertEqual(out["targets_hit"], [True])

    def test_window_uses_only_post_decision_bars_inside_horizon(self):
        bars = m1(NOW - 60, [(100.0, 99.0, 100.0)] * 5)
        w = O.window(bars, NOW + 10, NOW + 190)
        self.assertEqual([O.bar_ts(b) for b in w], [NOW + 60, NOW + 120])     # forming bar at the decision and post-horizon bars excluded


class ServiceAndExposure(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.config import ConfigStore
        from masterquo.db.database import Database
        from masterquo.evaluation.service import EvaluationService
        from masterquo.sh.units import SymbolSpec
        self.cfg, self.db = ConfigStore(), Database()
        self.bridge = Bridge(None, "HEDGING")
        self.bridge.buffer_symbol = self.bridge.symbol_info["name"]
        self.bars: list = []
        self.bridge.bars = lambda tf, limit=None, include_forming=True: list(self.bars)
        self.clock = [NOW]
        self.svc = EvaluationService(self.cfg, self.bridge, self.db, data_dir=Path(self.td.dir) / "evaluation", clock=lambda: self.clock[0])
        self.spec = SymbolSpec.from_mt5(self.bridge.symbol_info, {"margin_mode": 2})

    def tearDown(self):
        self.svc.ledger.c.close()
        self.td.close()

    def test_sh_setup_logged_once_and_matured(self):
        su = mk_setup(self.spec, "SCALPING", "BUY", ref=2000.2)
        self.svc.on_sh_cycle({"SCALPING": su, "HEDGING": {"status": "WAIT", "strategy": "HEDGING"}}, inst="XAUUSD", symbol=su["symbol"],
                             snap={"regime": {"state": "TREND"}}, now=NOW)
        self.svc.on_sh_cycle({"SCALPING": su}, inst="XAUUSD", symbol=su["symbol"], snap=None, now=NOW + 1)
        self.assertEqual((self.svc.counters["logged"], self.svc.counters["duplicates"]), (1, 1))
        it = self.svc.assessments()[0]
        self.assertEqual((it["engine"], it["decision"], it["probability_status"]), ("SH_SCALPING", "DEFER", "NO_MODEL"))
        self.assertAlmostEqual(it["cost_r"], 0.3 / abs(su["entry_ref"] - su["sl"]), places=3)   # spread is not counted twice
        self.assertIsNone(it["outcome"])                                   # horizon not elapsed: no label
        tp = [t["price"] for t in su["tps"]]
        self.bars = m1(NOW + 60, [(2000.3, 2000.0, 2000.2)] * 3 + [(tp[1] + 0.05, 2000.1, tp[1])] + [(2000.5, 2000.0, 2000.3)] * 27)
        self.assertEqual(self.svc.mature(NOW + 60 * 40), 1)
        out = self.svc.assessments()[0]["outcome"]
        self.assertEqual(out["targets_hit"][:2], [True, True])
        self.assertTrue(out["event_hit"])
        rep = self.svc.report()["groups"][0]
        self.assertEqual((rep["engine"], rep["decision"], rep["n"], rep["status"]), ("SH_SCALPING", "DEFER", 1, "SMALL_SAMPLE"))
        dist = self.svc.report()["outcome_distribution"]["SH_SCALPING"]                  # §8: empirical TP / SL / neither with interval
        self.assertEqual((dist["n"], dist["TP_FIRST"]["rate"], dist["SL_FIRST"]["rate"]), (1, 1.0, 0.0))
        self.assertLess(dist["TP_FIRST"]["interval90"][0], 0.5)                          # one observation: wide interval

    def test_window_older_than_buffer_is_unknown_not_invented(self):
        su = mk_setup(self.spec, "SCALPING", "BUY", ref=2000.2)
        self.svc.on_sh_cycle({"SCALPING": su}, inst="XAUUSD", symbol=su["symbol"], snap=None, now=NOW)
        self.bars = m1(NOW + 7200, [(2000.3, 2000.0, 2000.2)] * 5)
        self.svc.mature(NOW + 8000)
        self.assertEqual(self.svc.assessments()[0]["outcome"]["status"], "NO_BARS")
        self.assertEqual(self.svc.report()["matured"], 0)

    def test_active_confirmed_setup(self):
        class View:
            symbol, bid, ask, regime = "XAUUSD-", 2000.0, 2000.2, {"state": "TREND_UP"}
        row = {"setup_id": "ST-1", "stage": "CONFIRMED", "status": "ACTIVE", "version": 2, "expires_at": None, "stale": 0,
               "record": {"strategy_id": "S01", "direction": "LONG", "timeframe": "M15", "stop_loss": 1997.0, "setup_score": 71,
                          "targets": [{"price": 2003.0, "weight": 0.5}, {"price": 2006.0, "weight": 0.5}],
                          "entry_plan": {"order_type": "MARKET_ON_CONFIRMATION"}}}
        self.svc.on_active_events([("STAGE_CONFIRMED", row), ("NEW_WATCH", {**row, "stage": "WATCH"})], View())
        items = self.svc.assessments("ACTIVE_S01_S12")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["entry"], 2000.2)                    # LONG priced on the Ask
        self.assertEqual(items[0]["horizon_s"], 12 * 900)
        self.assertEqual(items[0]["decision"], "DEFER")                 # no ML prediction for this version -> no probability

    def scalp_plan(self, **kw):
        plan = {"setup_id": "SC-1", "direction": "BUY", "decision_ts": NOW, "sl": 1999.0, "tp1": 2001.0, "tp2": 2002.0, "fill_shadow": 2000.2,
                "spread_fill": 0.2, "entry_mode": "MARKET", "model_b": {"status": "UNAVAILABLE", "pass": False}}
        plan.update(kw)
        return plan

    def test_scalp_shadow_candidates_logged_with_their_own_event(self):
        """O6: the Range->Sweep->Retest SHADOW machine is a third source; blocked candidates are evaluated too."""
        self.svc.on_scalp_setup(self.scalp_plan(), status="BLOCKED", reasons=["kalendarz makro: brak"], instrument="XAUUSD", symbol="XAUUSD-",
                                f1=0.5, horizon_s=1800, extra_cost=0.07, commission_known=True)
        self.svc.on_scalp_setup(self.scalp_plan(setup_id="SC-2", fill_shadow=None), status="BLOCKED", reasons=[], instrument="XAUUSD",
                                symbol="XAUUSD-", f1=0.5, horizon_s=1800)
        self.assertEqual(self.svc.counters["no_entry"], 1)                     # no executable price -> nothing invented
        it = self.svc.assessments("SCALP_SHADOW")
        self.assertEqual(len(it), 1)
        self.assertEqual((it[0]["event"], it[0]["decision"]), ("TP1 przed SL w horyzoncie", "DEFER"))
        self.assertEqual([t["weight"] for t in it[0]["targets"]], [0.5, 0.5])
        self.bars = m1(NOW, [(2000.4, 2000.0, 2000.2), (2001.1, 2000.1, 2000.9), (2000.9, 1998.9, 1999.0)] + [(2000.0, 1999.5, 1999.8)] * 30)
        self.svc.mature(NOW + 3600)
        out = self.svc.assessments("SCALP_SHADOW")[0]["outcome"]
        self.assertEqual((out["targets_hit"], out["exit"]), ([True, False], "SL"))
        self.assertTrue(out["event_hit"])                                       # TP1 before SL = the scalp model's event

    def test_both_regimes_recorded_and_readiness_reported(self):
        """O4: the regime of both definitions is stored with every assessment; O2: ASSIST readiness is reported, never applied."""
        self.svc.regime_sources = {"ACTIVE": lambda: {"state": "TREND_UP"}, "SH": lambda: {"state": "TRANSITION"},
                                   "BROKEN": lambda: 1 / 0}
        su = mk_setup(self.spec, "SCALPING", "BUY", ref=2000.2)
        self.svc.on_sh_cycle({"SCALPING": su}, inst="XAUUSD", symbol=su["symbol"], snap=None, now=NOW)
        row = self.svc.ledger.rows(f"{E.VERSION}/SH_SCALPING")[0]
        self.assertEqual(row["payload"]["candidate"]["market_regime"]["both"], {"ACTIVE": "TREND_UP", "SH": "TRANSITION", "BROKEN": None})
        rep = self.svc.report()
        self.assertEqual((rep["regimes"][0]["active_regime"], rep["regimes"][0]["sh_regime"], rep["regimes"][0]["n"]), ("TREND_UP", "TRANSITION", 1))
        tp = [t["price"] for t in su["tps"]]
        self.bars = m1(NOW + 60, [(tp[1] + 0.05, 2000.1, tp[1])] + [(2000.5, 2000.0, 2000.3)] * 30)
        self.svc.mature(NOW + 60 * 40)
        r = self.svc.report()["assist_readiness"]["SH_SCALPING"]
        self.assertEqual((r["matured"], r["with_probability"], r["target"], r["evidence_sufficient"]), (1, 0, 200, False))

    def test_exposure_detects_cross_engine_conflict(self):
        from masterquo.evaluation import exposure as X
        self.db.execute("""INSERT INTO managed_positions(position_key, mode, symbol, side, volume_initial, volume_open, entry_price, sl, state, opened_at)
                           VALUES ('PAPER:1','PAPER','XAUUSD-','BUY',0.1,0.1,2000.0,1995.0,'OPEN','2025-10-09T08:00:00Z')""")
        self.assertEqual(X.portfolio(self.db)["status"], "SINGLE_ENGINE")
        self.db.execute("""INSERT INTO sh_plans(plan_id, signal_id, strategy, instrument, symbol, side, exec_mode, state, config_hash, plan, created_at, updated_at)
                           VALUES ('PL-1','SH-1','SCALPING','XAUUSD','XAUUSD-','SELL','PAPER','OPEN','h','{"risk": {"volume": 0.2}}',?,?)""", (NOW, NOW))
        p = X.portfolio(self.db)
        self.assertEqual(p["status"], "CONFLICT")
        self.assertEqual(p["symbols"]["XAUUSD-"]["net_volume"], -0.1)
        fc = X.for_candidate(X.positions(self.db), "XAUUSD-", "LONG")
        self.assertEqual((fc["status"], fc["opposite"][0]["engine"]), ("CONFLICT", "SH_SCALPING"))

    def test_engine_stats_include_sh_plans(self):
        from masterquo import stats
        self.db.execute("""INSERT INTO trades(trade_id, mode, source, symbol, side, volume, closed_at, gross_pnl, commission, swap, fee, net_pnl, r_multiple, status)
                           VALUES ('T1','PAPER','BOT','XAUUSD-','BUY',0.1,'2025-10-09T09:00:00Z',12,0,0,0,12,1.2,'CLOSED')""")
        res = json.dumps({"net_money": -5.0, "r_multiple": -0.5, "commission_money": 1.0, "commission_known": True})
        self.db.execute("""INSERT INTO sh_plans(plan_id, signal_id, strategy, instrument, symbol, side, exec_mode, state, config_hash, plan, created_at, updated_at,
                           closed_at, result) VALUES ('PL-2','SH-2','HEDGING','XAUUSD','XAUUSD-','BUY','PAPER','CLOSED','h','{}',?,?,?,?)""", (NOW, NOW, NOW, res))
        s = stats.engine_stats(self.db, "PAPER")
        self.assertEqual(s["per_engine"]["ACTIVE_S01_S12"]["trades"], 1)
        self.assertEqual(s["per_engine"]["SH_HEDGING"]["trades"], 1)
        self.assertEqual(s["combined"]["trades"], 2)
        self.assertEqual(s["combined"]["net"], 7.0)
        self.assertEqual(stats.bot_stats(self.db, "PAPER")["all"]["trades"], 1)      # the existing statistic is unchanged


class Isolation(unittest.TestCase):
    """The evaluation layer may not reach the order path (static check of every import and attribute name)."""

    def test_no_order_path_references(self):
        root = _env.ROOT / "backend" / "masterquo" / "evaluation"
        banned_mod = ("execution", "mt5.worker", "sh.executor", "engine.decision", "risk.engine")
        banned_name = {"order_send", "ExecutionGateway", "PaperBroker", "PositionManager", "SHExecutor", "open_plan", "close_position"}
        files = sorted(root.glob("*.py"))
        self.assertGreaterEqual(len(files), 5)
        for f in files:
            tree = ast.parse(f.read_text(encoding="utf-8"))
            for n in ast.walk(tree):
                if isinstance(n, ast.ImportFrom):
                    mod = n.module or ""
                    full = [mod] + [f"{mod}.{a.name}" if mod else a.name for a in n.names]
                    self.assertFalse(any(m == b or m.endswith("." + b) or m.startswith(b + ".") or ("." + b + ".") in m
                                         for m in full for b in banned_mod), f"{f.name}: from {mod}")
                elif isinstance(n, ast.Import):
                    for a in n.names:
                        self.assertFalse(any(b in a.name for b in banned_mod), f"{f.name}: import {a.name}")
                elif isinstance(n, (ast.Attribute, ast.Name)):
                    self.assertNotIn(getattr(n, "attr", None) or getattr(n, "id", None), banned_name, f"{f.name}")


class ShListener(unittest.TestCase):
    def test_listener_sees_every_cycle_and_cannot_break_it(self):
        from test_arch_fixes import GateModes, ShStopGate
        t = ShStopGate("test_paper_opens_plan_when_allowed")
        t.setUp()
        try:
            from masterquo.sh import service as S
            seen = []
            orig = S.SHService.__init__

            def init(self, *a, **k):
                orig(self, *a, **k)
                self.listeners.append(lambda evals, **kw: seen.append((sorted(evals), kw["symbol"])))
                self.listeners.append(lambda evals, **kw: 1 / 0)          # a failing observer
            S.SHService.__init__ = init
            try:
                _svc, plans = t.run_tick(GateModes("PAPER"))
            finally:
                S.SHService.__init__ = orig
            self.assertEqual(len(plans), 1)                                # the cycle completed (plan opened as before)
            self.assertEqual(seen[0][0], ["HEDGING", "SCALPING"])
        finally:
            t.tearDown()


if __name__ == "__main__":
    unittest.main()
