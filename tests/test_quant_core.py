"""1.35 PMW Quant Core - acceptance tests of the spec table (docs/quant/TEST_REPORT.md maps each row to a test here).

Behaviour and math, not a copy of the implementation: point-in-time data, contract / time checks, aliases, costs / EV, plan labels,
leakage-free meta-model levels, artifacts and rollback, scheduler failures, SHADOW parity and ASSIST permissions of the existing
coordinator. Isolated data dirs, stub bridges; no MT5, no order, no Telegram."""
from __future__ import annotations

import json
import math
import subprocess
import sys
import threading
import time
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np

import _env
from _env import TempData

NOW = 1_794_000_000.0


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


def bar(t, o, h, l_, c, tf_s=60, closed=True, spread=20):
    return {"open_utc": iso(t), "o": o, "h": h, "l": l_, "c": c, "tv": 5, "spread": spread, "closed": closed, "available_at": iso(t + tf_s),
            "source": "native", "revision": 0}


class StubBridge:
    """Bridge buffers with closed / forming bars per TF (the real bridge already excludes forming bars with include_forming=False)."""
    def __init__(self, n=300, now=NOW, synthetic=True):
        self.now_t = now
        self.synthetic = synthetic
        self.cfg = SimpleNamespace(symbol="XAUUSD-")
        self.buffer_symbol = "XAUUSD-"
        self.symbol_info = {"point": 0.01, "trade_tick_size": 0.01, "trade_tick_value": 1.0, "volume_step": 0.01, "volume_min": 0.01}
        self.series = {}
        for tf, s in (("M1", 60), ("M5", 300), ("M15", 900), ("H1", 3600)):
            t0 = now - (now % s) - n * s
            rows, p = [], 2000.0
            for i in range(n):
                t = t0 + i * s
                rows.append(bar(t, p, p + 0.5, p - 0.5, p + 0.1, s, closed=t + s <= now))
                p += 0.1
            ft = t0 + n * s                                            # the forming bar (opened, not closed)
            rows.append(bar(ft, p, p + 9.0, p - 9.0, p + 5.0, s, closed=False))
            self.series[tf] = rows
        self.tfs = {k: None for k in self.series}

    def bars(self, tf, limit=None, include_forming=True):
        rows = self.series.get(tf, [])
        rows = rows if include_forming else [r for r in rows if r["closed"]]
        return list(rows[-limit:] if limit else rows)

    def quote_status(self):
        return {"bid": 2000.0, "ask": 2000.2, "age_seconds": 0.5}


def pred(name="TH_LOGREG_M5_H6", tf="M5", up=0.4, down=0.3, age=60.0, now=NOW, **kw):
    from masterquo.modelhub import contract as C
    flat = round(1 - up - down, 10)
    return C.make(instrument="XAUUSD", symbol="XAUUSD-", timeframe=tf, model_name=name, model_version=kw.pop("version", "v1"),
                  task_type="CLASS_PROBABILITIES", task=kw.pop("task", "DIRECTION_H6_M5"), horizon_bars=kw.pop("h", 6), unit="probability",
                  state="READY", result={"DOWN": down, "FLAT": flat, "UP": up}, data_time=iso(now - age), extra=kw)


def cand(direction="LONG", entry=2000.0, sl=1998.0, targets=((2002.5, 0.5), (2003.0, 0.3), (2005.0, 0.2)), horizon=3600, ts=NOW, cost=0.1,
         engine="SH_SCALPING", known=True):
    return {"setup_id": "S1", "engine": engine, "strategy_id": "SCALPING", "symbol": "XAUUSD-", "instrument": "XAUUSD", "timeframe": "M1",
            "decision_ts": ts, "direction": direction, "entry_type": "MARKET", "entry_price": entry, "stop_loss": sl,
            "targets": [{"price": p, "weight": w} for p, w in targets], "horizon_s": horizon, "market_regime": {"state": "TREND"}, "features": {},
            "data_quality": {"status": "OK"}, "execution_context": {"cost_price": cost, "commission_known": known, "spread": 0.2}, "score": 70}


# =============================================================================================== data / snapshot
class TestSnapshotPointInTime(unittest.TestCase):
    def test_forming_bar_and_future_availability_excluded(self):
        from masterquo.quant import snapshot as S
        br = StubBridge()
        snap = S.build(br, instrument="XAUUSD", now=NOW, tfs=("M1", "M5", "M15", "H1"))
        for tf in ("M15", "H1"):
            last = snap["bars"][tf][-1]
            self.assertLessEqual(last["available_at"], NOW)
            self.assertNotEqual(last["h"] - last["l"], 18.0)            # the forming bar's final high/low never enter
        self.assertEqual(snap["data_kind"], "SYNTHETIC")
        self.assertEqual(snap["quality"]["M1"]["status"], "OK")
        self.assertIn("TICK_VOLUME", snap["quality"]["M1"]["volume_kind"])

    def test_change_after_t_does_not_change_history_at_t(self):
        from masterquo.quant import snapshot as S
        br = StubBridge()
        snap = S.build(br, instrument="XAUUSD", now=NOW, tfs=("M5",))
        t = NOW - 3600
        before = json.dumps(S.asof(snap, t))
        br.series["M5"].append(bar(NOW, 1.0, 9e9, 0.1, 5.0, 300))     # later data (and an absurd bar) after t
        br.series["M5"][-3]["c"] = 12345.0                            # a revision of a bar after t
        snap2 = S.build(br, instrument="XAUUSD", now=NOW + 600, tfs=("M5",))
        self.assertEqual(before, json.dumps(S.asof(snap2, t)))

    def test_qc_flags_gaps_duplicates_and_incomplete_resampled(self):
        from masterquo.quant import snapshot as S
        rows = S.normalise([bar(0, 1, 2, 0.5, 1.5), bar(60, 1, 2, 0.5, 1.5), bar(60, 1, 2, 0.5, 1.5), bar(600, 1, 0.9, 0.5, 1.5)], "M1")
        q = S.qc(rows, "M1")
        self.assertEqual(q["status"], "BLOCK")
        self.assertTrue(any(i.startswith("DUPLICATES") for i in q["issues"]))
        self.assertTrue(any(i.startswith("OHLC_INVALID") for i in q["issues"]))
        self.assertEqual(q["gap_count"], 1)                               # reported, never filled
        r = dict(bar(0, 1, 2, 0.5, 1.5, 180), source="resampled", complete=False)
        self.assertEqual(S.qc(S.normalise([r], "M3"), "M3")["issues"], ["RESAMPLED_INCOMPLETE:1"])


# =============================================================================================== contract / time checks
class TestChecks(unittest.TestCase):
    def test_future_stale_late_and_synthetic(self):
        from masterquo.quant import checks as CK
        self.assertEqual(CK.check(pred(age=-120), now=NOW)["reason"].split(":")[0], "FUTURE_TIME")
        self.assertEqual(CK.check(pred(age=5000), now=NOW)["reason"].split(":")[0], "STALE")
        floor = {"M5": NOW - 300}
        self.assertEqual(CK.check(pred(age=900), now=NOW, generation_floor=floor)["reason"], "LATE_GENERATION:M5")
        p = dict(pred(), data_kind="SYNTHETIC")
        self.assertEqual(CK.check(p, now=NOW, snapshot_kind="REAL")["reason"], "SYNTHETIC_IN_REAL_SNAPSHOT")
        self.assertTrue(CK.check(pred(age=60), now=NOW)["eligible"])

    def test_contract_errors_never_reach_features(self):
        from masterquo.quant import checks as CK
        from masterquo.quant import features as F
        bad = []
        for res in ({"DOWN": float("nan"), "FLAT": 0.5, "UP": 0.5}, {"DOWN": True, "FLAT": 0.0, "UP": 0.0}, {"DOWN": 0.5, "FLAT": 0.5, "UP": 0.5}):
            p = pred()
            p["result"] = res
            bad.append(p)
        u = pred()
        u["unit"] = "price"                                               # wrong unit for a distribution
        bad.append(u)
        sc = CK.screen(bad, now=NOW)
        self.assertEqual(sc["eligible"], [])
        self.assertTrue(all(x["eligibility"]["reason"].startswith("CONTRACT_ERROR") for x in sc["excluded"]))
        self.assertEqual({k for k in F.prediction_features(sc["eligible"], "LONG")}, set())

    def test_valid_zero_is_kept(self):
        from masterquo.modelhub import contract as C
        from masterquo.quant import checks as CK
        from masterquo.quant import features as F
        from masterquo.quant.adapters import clean
        p = C.make(instrument="XAUUSD", symbol=None, timeframe="M5", model_name="mm:gpr_logret", model_version="x", task_type="REGRESSION",
                   task="LOG_RETURN_H3_M5", horizon_bars=3, unit="log_return", state="READY", result={"mean": 0.0, "sd": 0.01},
                   data_time=iso(NOW - 60), extra={"canonical_id": "mm:gpr_logret"})
        sc = CK.screen([p], now=NOW)
        f = F.prediction_features(sc["eligible"], "LONG")
        self.assertEqual(f["fc:mm:gpr_logret:LOG_RETURN_H3_M5:M5:z"], 0.0)   # present (mask 0), not missing
        v, m = F.vectorise(f, ["fc:mm:gpr_logret:LOG_RETURN_H3_M5:M5:z"])
        self.assertEqual((v, m), ([0.0], [0.0]))
        self.assertEqual(clean({"a": 0, "b": None, "c": float("inf"), "d": False}), {"a": 0, "d": "NIE"})

    def test_no_implicit_averaging_of_different_events(self):
        from masterquo.quant import checks as CK
        from masterquo.quant import features as F
        a, b = pred(task="DIRECTION_H6_M5"), pred(name="TH_LOGREG_M15_H3", tf="M15", task="DIRECTION_H3_M15", h=3)
        ok, why = CK.ensemble_compatible(a, b)
        self.assertFalse(ok)
        self.assertEqual(why, "DIFFERENT_TASK")
        f = F.prediction_features(CK.screen([a, b], now=NOW)["eligible"], "LONG")
        self.assertEqual(len([k for k in f if k.endswith(":edge")]), 2)        # two separate named features, nothing averaged


# =============================================================================================== aliases
class TestAliases(unittest.TestCase):
    def test_th_and_event_gru_have_one_identity(self):
        from masterquo.quant import ids as I
        self.assertEqual(I.resolve("TH_RF"), I.resolve("TH_RF_M5_H6"))
        self.assertEqual(I.canonical({"family": "TH_XGB"}), "trainhub:TH_XGB")
        for n in ("SEQ_GRU_EVENT", "mm_event_engine", "event_engine_dir3"):
            self.assertEqual(I.resolve(n), "mm:event_engine_dir3")
        self.assertTrue(I.canonical({"model_name": "zzz"}).startswith("unresolved:"))   # never '?'
        a = pred(name="TH_RF_M5_H6")
        b = dict(a, family="TH_RF")                                       # the same artifact seen through the family adapter
        kept, dropped = I.dedup([a, b])
        self.assertEqual(len(kept), 1)
        self.assertEqual(len(dropped), 1)

    def test_family_adapters_do_not_vote_or_train_twice(self):
        td = TempData()
        try:
            from masterquo.config import ConfigStore
            from masterquo.modelhub.families.service import FamilyService
            fs = FamilyService(ConfigStore())
            for fid in ("TH_RF", "TH_XGB", "TH_SVM", "SEQ_GRU_EVENT"):
                self.assertIsNone(fs.predict(fid, "XAUUSD"))
            ready = pred(name="mm:event_engine_dir3", tf="EVENT", task="EVENT_UNITS_DIR3", h=2, family="SEQ_GRU_EVENT", use="SHADOW")
            fs.event_gru_provider = lambda inst: ready
            self.assertEqual(fs.predict("SEQ_GRU_EVENT", "XAUUSD")["family"], "SEQ_GRU_EVENT")
            fs.event_gru_provider = lambda inst: dict(ready, state="NOT_TRAINED")
            self.assertIsNone(fs.predict("SEQ_GRU_EVENT", "XAUUSD"))              # nothing READY -> no record (as before)
            out = fs.train_all("XAUUSD", "smoke")
            self.assertEqual({d["family"] for d in out["delegated"]}, {"TH_RF", "TH_XGB", "TH_SVM", "SEQ_GRU_EVENT"})
            for k in ("started", "blocked"):
                self.assertFalse({"TH_RF", "SEQ_GRU_EVENT"} & {x.get("family") for x in out[k]})
            for p in list(fs.procs.values()):
                p.kill()
        finally:
            td.close()


# =============================================================================================== units / costs / EV
class TestUnitsEV(unittest.TestCase):
    def test_hand_computable_ev(self):
        from masterquo.quant import units as U
        r = U.binary_ev(0.6, 2.0, 1.0)
        self.assertAlmostEqual(r["ev_r"], 0.8)
        self.assertAlmostEqual(r["break_even_p"], 1 / 3)
        s = U.scenario_ev([{"name": "SL", "p": 0.4, "net_r": -1.0}, {"name": "TP", "p": 0.6, "net_r": 2.0}])
        self.assertAlmostEqual(s["ev_r"], 0.8)
        with self.assertRaises(U.UnitsError):
            U.scenario_ev([{"name": "SL", "p": 0.4, "net_r": -1.0}, {"name": "TP", "p": 0.5, "net_r": 2.0}])   # not complete: never renormalised

    def test_unknown_commission_or_currency_is_not_validated(self):
        from masterquo.quant import units as U
        spec = U.InstrumentSpec(symbol="XAUUSD-", point=0.01, tick_size=0.01, tick_value=1.0, tick_value_ccy="USD", volume_step=0.01, volume_min=0.01)
        with self.assertRaises(U.UnitsError):
            spec.money(2.5, 1.0, account_ccy="PLN")                       # 2.5 USD of price is not 2.5 of account money
        self.assertAlmostEqual(spec.money(2.5, 0.1, "USD"), 25.0)
        with self.assertRaises(U.UnitsError):
            spec.pips(1.0)                                                # no pip definition in the spec
        cm = U.CostModel(commission_per_lot_side=None)
        self.assertEqual(cm.basis()["status"], "PARTIAL")
        self.assertIsNone(cm.price_cost_per_unit(spec)["total"])
        r = U.ev_for_plan(p_event=0.6, event_id="TP_BEFORE_SL", targets=[{"price": 1, "weight": 1}], be_after=None, timeout=False, gain_r=2.0,
                          loss_r=1.0, cost_known=False)
        self.assertEqual(r["status"], "SCENARIO_UNKNOWN_COSTS")
        r2 = U.ev_for_plan(p_event=0.6, event_id="TP2_BEFORE_STOP", targets=[{}, {}], be_after="TP2", timeout=True, gain_r=2.0, loss_r=1.0, cost_known=True)
        self.assertEqual(r2["status"], "EV_NEEDS_SCENARIOS")              # P(TP2) is not the payoff distribution of a partial plan

    def test_spread_in_prices_not_subtracted_twice(self):
        from masterquo.quant import units as U
        spec = U.InstrumentSpec(symbol="X", point=0.01, tick_size=0.01, tick_value=1.0)
        self.assertEqual(U.CostModel(spread_in_prices=True, spread_price=0.3, commission_per_lot_side=0.0).price_cost_per_unit(spec)["components"]["spread"], 0.0)
        self.assertEqual(U.CostModel(spread_in_prices=False, spread_price=0.3, commission_per_lot_side=0.0).price_cost_per_unit(spec)["components"]["spread"], 0.3)
        vs = U.InstrumentSpec(symbol="X", point=0.01, tick_size=0.01, volume_step=0.01, volume_min=0.01)
        self.assertEqual(vs.quantize_volume(0.019), 0.01)
        self.assertIsNone(U.InstrumentSpec(symbol="X", point=0.01, tick_size=0.01, volume_step=0.01, volume_min=0.01).quantize_volume(0.005))


# =============================================================================================== plan labels
class TestPlanSimulator(unittest.TestCase):
    def spec(self, **kw):
        from masterquo.quant import events as EV
        base = dict(instrument="XAUUSD", strategy="t", direction="LONG", entry=100.0, sl=99.0, targets=((101.0, 0.5), (102.0, 0.3), (103.0, 0.2)),
                    horizon_s=600, cost_price=0.1, be_after="TP2")
        base.update(kw)
        return EV.EventSpec(**base)

    def b(self, i, o, h, l_, c, sp=None):
        return {"t": float(i * 60), "o": o, "h": h, "l": l_, "c": c, "spread_price": sp}

    def test_partials_then_be_from_next_bar(self):
        from masterquo.quant import events as EV
        bars = [self.b(0, 100, 101.2, 99.8, 101), self.b(1, 101, 102.1, 100.5, 101.5), self.b(2, 101.5, 101.6, 99.95, 100)]
        r = EV.simulate(self.spec(be_offset_price=0.1), bars, 0.0)
        self.assertEqual(r["scenario"], "TP2_BE")
        exp_gross = 0.5 * 1.0 + 0.3 * 2.0 + 0.2 * 0.1                    # BE = entry + costs (offset) for the 20 % remainder
        self.assertAlmostEqual(r["gross_r"], exp_gross, places=6)
        self.assertAlmostEqual(r["net_r"], exp_gross - 0.1, places=6)  # costs ONCE for the whole position; R never redefined
        self.assertTrue(r["events"]["TP2_BEFORE_STOP"])
        self.assertFalse(r["events"]["TP3_BEFORE_STOP"])

    def test_timeout_gap_and_immature(self):
        from masterquo.quant import events as EV
        flat = [self.b(i, 100, 100.4, 99.6, 100.2) for i in range(10)]
        r = EV.simulate(self.spec(), flat, 0.0)
        self.assertEqual(r["scenario"], "TP0_TIMEOUT")
        self.assertAlmostEqual(r["gross_r"], 0.2)
        gap = [self.b(0, 100, 100.4, 99.6, 100.1), self.b(1, 98.0, 98.5, 97.5, 98.2)]
        g = EV.simulate(self.spec(), gap, 0.0, available_until=600)
        self.assertTrue(g["gap"])
        self.assertAlmostEqual(g["gross_r"], -2.0)                         # filled at the open, worse than SL
        self.assertFalse(EV.simulate(self.spec(), flat[:3], 0.0)["mature"])  # horizon not over: not a loss, not a timeout

    def test_ambiguous_bar_policy_fixed_in_advance(self):
        from masterquo.quant import events as EV
        both = [self.b(0, 100, 101.5, 98.5, 100)]
        sl = EV.simulate(self.spec(ambiguity="SL_FIRST"), both, 0.0, available_until=600)
        tp = EV.simulate(self.spec(ambiguity="TP_FIRST"), both, 0.0, available_until=600)
        bd = EV.simulate(self.spec(ambiguity="BOUNDS"), both, 0.0, available_until=600)
        self.assertEqual(sl["scenario"], "TP0_SL")
        self.assertTrue(sl["ambiguous"])
        self.assertEqual(tp["scenario"], "TP1_SL")
        self.assertEqual(bd["net_r"], sl["net_r"])                         # the label stays conservative
        self.assertEqual(bd["net_r_bounds"], [sl["net_r"], tp["net_r"]])

    def test_short_exits_on_ask_and_unknown_costs(self):
        from masterquo.quant import events as EV
        s = self.spec(direction="SHORT", entry=100.0, sl=101.0, targets=((99.0, 1.0),), be_after=None, cost_price=None)
        r = EV.simulate(s, [self.b(0, 100, 100.2, 98.95, 99.5, sp=0.1)], 0.0, available_until=600)
        self.assertEqual(r["scenario"], "TP0_TIMEOUT")                    # bid low 98.95 + spread 0.1 = ask 99.05 > TP 99.0
        self.assertIsNone(r["net_r"])
        self.assertEqual(r["cost_status"], "UNKNOWN")
        self.assertNotEqual(self.spec().task_hash(), self.spec(be_after=None).task_hash())   # a plan change is a new task


# =============================================================================================== numeric core
class TestNumeric(unittest.TestCase):
    def test_rolling_cov_metrics(self):
        from masterquo.quant import numeric as N
        x = 2000 + np.cumsum(np.random.default_rng(1).normal(0, 1, 500))
        m, v = N.rolling_mean_var(x, 50)
        self.assertAlmostEqual(m[-1], x[-50:].mean(), places=8)
        self.assertAlmostEqual(v[-1], x[-50:].var(ddof=1), places=6)
        with self.assertRaises(N.NumericError):
            N.hist_vol([0.0, 0.0, 0.0, 0.0])
        with self.assertRaises(N.NumericError):
            N.log_returns([1.0, float("nan"), 2.0])
        S = np.array([[1.0, 1.0], [1.0, 1.0 - 1e-14]])
        R, info = N.psd_repair(S)
        self.assertGreater(np.linalg.eigvalsh(R).min(), 0)
        with self.assertRaises(N.NumericError):
            N.covariance(np.random.default_rng(2).normal(size=(6, 3)))      # n < k * 5
        p, y = np.array([0.9, 0.1, 0.8, 0.3]), np.array([1, 0, 1, 1])
        self.assertAlmostEqual(N.brier(p, y), np.mean((p - y) ** 2))
        rel = N.reliability(p, y, 2)
        self.assertEqual(sum(b["n"] for b in rel["bins"]), 4)
        self.assertEqual(N.auc(np.array([0.1, 0.9]), np.array([0, 1])), 1.0)
        self.assertAlmostEqual(float(N.softmax(np.array([1000.0, 1000.0]))[0]), 0.5)   # stable at large logits
        bb = N.block_bootstrap(np.arange(100.0), n_boot=200)
        self.assertLessEqual(bb["lo"], bb["estimate"])
        self.assertLessEqual(bb["estimate"], bb["hi"])
        g = N.garch11_forecast(np.full(50, 0.001), 1e-7, 0.05, 0.9, h=3)
        self.assertEqual(len(g["variance_path"]), 3)
        with self.assertRaises(N.NumericError):
            N.garch11_forecast(np.full(50, 0.001), 1e-7, 0.5, 0.6)


# =============================================================================================== meta-model
def synth_rows(n=900, seed=1, kind="REAL", informative=True):
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        x = float(rng.normal())
        p = 1 / (1 + math.exp(-(1.5 * x if informative else 0.0)))
        y = int(rng.random() < p)
        f = {"plan:gain_r": 1.5, "fc:trainhub:TH_LOGREG:DIRECTION_H6_M5:M5:edge": x, "ctx:hour_sin": float(rng.normal())}
        if i % 7 == 0:
            del f["fc:trainhub:TH_LOGREG:DIRECTION_H6_M5:M5:edge"]
        rows.append({"row_id": f"r{i}", "decision_ts": NOW + i * 600, "resolve_ts": NOW + i * 600 + 1800, "features": f, "y": y,
                     "net_r": (1.5 if y else -1.0) - 0.05, "data_kind": kind})
    return rows


class TestMetaModel(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_no_level_sees_future_labels(self):
        from masterquo.quant import metamodel as M
        rows = synth_rows()
        B = M.blocks(rows, 0.0)
        self.assertTrue(all(r["resolve_ts"] <= B["cal"][0]["decision_ts"] for r in B["dev"]))
        self.assertTrue(all(r["resolve_ts"] <= B["test"][0]["decision_ts"] for r in B["cal"]))
        for tr, va in M.folds(B["dev"], 4, 0.0):
            self.assertTrue(all(r["resolve_ts"] <= va[0]["decision_ts"] for r in tr))
        with self.assertRaises(M.MetaError):
            M.assert_no_future([{"row_id": "x", "resolve_ts": 10.0}], 5.0)
        # changing TEST labels cannot change anything fitted before the test (model, calibrator, selection)
        a = M.train(synth_rows(), task={"task_hash": "t", "event_id": "E"})
        rows2 = synth_rows()
        for r in rows2[-150:]:
            r["y"] = 1 - r["y"]
        b = M.train(rows2, task={"task_hash": "t", "event_id": "E"})
        self.assertEqual(a["model"]["logit"], b["model"]["logit"])
        self.assertEqual(a["model"]["calibrator"], b["model"]["calibrator"])
        self.assertNotEqual(a["report"]["test_once"]["log_loss"], b["report"]["test_once"]["log_loss"])

    def test_statuses_follow_evidence(self):
        from masterquo.quant import metamodel as M
        r = M.train(synth_rows(120), task={"task_hash": "t", "event_id": "E"})
        self.assertEqual(r["status"], "INSUFFICIENT_EVIDENCE")
        self.assertNotIn("model", r)
        ok = M.train(synth_rows(), task={"task_hash": "t", "event_id": "E"})
        self.assertEqual(ok["status"], "VALIDATED_SHADOW", ok["report"].get("failed_gates"))
        self.assertLess(ok["report"]["ablation_dev_oof"]["full"], ok["report"]["ablation_dev_oof"]["plan_context"])
        syn = M.train(synth_rows(kind="SYNTHETIC"), task={"task_hash": "t", "event_id": "E"})
        self.assertEqual(syn["status"], "VALIDATION_FAILED")              # synthetic data never validates
        self.assertIn("data_real", syn["report"]["failed_gates"])
        noise = M.train(synth_rows(informative=False), task={"task_hash": "t", "event_id": "E"})
        self.assertEqual(noise["status"], "VALIDATION_FAILED")            # no gain over the prior -> not promoted
        seen = M.train(synth_rows(), task={"task_hash": "t", "event_id": "E"}, seen_tests=[ok["report"]["test_row_ids"]])
        self.assertIn("test_block_fresh", seen["report"]["failed_gates"])   # a re-used final test cannot promote

    def test_save_load_schema_and_rollback(self):
        from masterquo.quant import metamodel as M
        res = M.train(synth_rows(), task={"task_hash": "t", "event_id": "E"})
        v1 = M.save("XAUUSD", res, spec={"task_hash": "t"})
        model, man = M.load("XAUUSD", "t", v1)
        f = synth_rows()[-1]["features"]
        self.assertAlmostEqual(M.predict(model, f)["p_event"], M.predict(res["model"], f)["p_event"], places=12)
        missing = M.predict(model, {"plan:gain_r": 1.5})                        # a missing model -> masks, as trained
        self.assertIn("fc:trainhub:TH_LOGREG:DIRECTION_H6_M5:M5:edge", missing["missing_features"])
        v2 = M.save("XAUUSD", res, spec={"task_hash": "t"})
        M.activate("XAUUSD", "t", v1)
        M.activate("XAUUSD", "t", v2)
        self.assertEqual(M.rollback("XAUUSD", "t")["active"]["t"], v1)
        self.assertNotIn("t", M.rollback("XAUUSD", "t")["active"])
        d = M.root("XAUUSD") / "t" / v2
        blob = json.loads((d / "model.json").read_text())
        blob["feature_names"] = blob["feature_names"] + ["extra"]
        (d / "model.json").write_text(json.dumps(blob, sort_keys=True))
        with self.assertRaises(M.MetaError):
            M.load("XAUUSD", "t", v2)                                      # checksum / schema change -> refused (INCOMPATIBLE)
        bad = M.train(synth_rows(kind="SYNTHETIC"), task={"task_hash": "s", "event_id": "E"})
        vb = M.save("XAUUSD", bad, spec={"task_hash": "s"})
        with self.assertRaises(M.MetaError):
            M.activate("XAUUSD", "s", vb)                                  # only VALIDATED_SHADOW can become active


# =============================================================================================== scheduler
class TestScheduler(unittest.TestCase):
    def test_cycles_timeouts_failures_and_generations(self):
        from masterquo.quant.scheduler import CycleError, Dag, OwnershipError, Publisher
        d = Dag()
        d.add("a", lambda c, _: 1, owner="x")
        d.add("slow", lambda c, _: time.sleep(2) or 2, deps=("a",), owner="x", deadline_s=0.2)
        d.add("boom", lambda c, _: 1 / 0, deps=("a",), owner="x")
        d.add("after_boom", lambda c, deps: deps["boom"], deps=("boom",), owner="x")
        d.add("independent", lambda c, deps: deps["a"] + 1, deps=("a",), owner="x")
        with self.assertRaises(OwnershipError):
            d.add("a", lambda c, _: 1, owner="y")                          # one owner per task
        with self.assertRaises(CycleError):
            d.add("a2", lambda c, _: 1, deps=("a3",), owner="x")
        t0 = time.perf_counter()
        r = d.run({}, 1)
        self.assertLess(time.perf_counter() - t0, 1.5)                    # the slow task did not hold the cycle
        st = {k: v["status"] for k, v in r["tasks"].items()}
        self.assertEqual(st, {"a": "OK", "slow": "TIMEOUT", "boom": "ERROR", "after_boom": "BLOCKED_DEPENDENCY", "independent": "OK"})
        self.assertFalse(r["complete"])
        pub = Publisher()
        pub.publish({"generation": 5, "v": "new"})
        pub.publish({"generation": 4, "v": "late worker"})                # an older generation never replaces a newer one
        self.assertEqual(pub.current()["v"], "new")
        d.shutdown()


# =============================================================================================== service (stub runtime)
class StubRt:
    def __init__(self):
        self.bridge = StubBridge(now=time.time())
        self.sh = SimpleNamespace(instrument=lambda: "XAUUSD", snapshot=None)


class TestService(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_runs_without_panel_reads_do_not_recompute_and_missing_inputs_are_states(self):
        from masterquo.quant.service import QuantService
        q = QuantService(StubRt())
        p = q.cycle()
        self.assertTrue(p["complete"])
        self.assertEqual(p["mode"], "SHADOW")
        g = q.pub.current()["generation"]
        for _ in range(20):
            q.status()
            q.predictions()
        self.assertEqual(q.pub.current()["generation"], g)                # API reads never run a cycle
        q.start()
        try:
            self.assertTrue(_env.wait_for(lambda: (q.pub.current() or {}).get("generation", 0) > g, 20, 0.2))   # own thread, no panel
        finally:
            q.stop()
        self.assertEqual(q.loop["errors"], 0)

    def test_empty_model_set_is_not_trained_without_invented_value(self):
        from masterquo.quant.service import QuantService
        q = QuantService(StubRt())
        q.cycle()
        a = q.assess(cand(ts=time.time()), log_row=True)
        self.assertEqual(a["status"], "NOT_TRAINED")
        self.assertEqual(a["reason"], "brak wytrenowanego modelu dla tego zdarzenia")
        self.assertIsNone(a["probability"])
        self.assertIsNone(a["ev"])
        self.assertEqual(q.ledger.counts("XAUUSD")["total"], 1)

    def test_label_maturation_and_training_from_ledger(self):
        from masterquo.quant import service as SV
        q = SV.QuantService(StubRt())
        br = q.rt.bridge
        t_dec = br.series["M1"][-120]["available_at"]
        ts = datetime.fromisoformat(t_dec).timestamp()
        e = 2018.0
        a = q.assess(cand(ts=ts, entry=e, sl=e - 2.0, targets=((e + 2.5, 0.5), (e + 3.0, 0.3), (e + 5.0, 0.2)), horizon=1800), log_row=True)
        self.assertEqual(a["status"], "NOT_TRAINED")
        bad = q.assess(cand(ts=ts, entry=e, sl=e - 2.0, targets=((e - 1.0, 1.0),)), log_row=True)
        self.assertEqual(bad["status"], "INVALID_PLAN")                   # a target on the wrong side is not a task
        n = q.mature(now=time.time())
        self.assertEqual(n, 1)
        row = q.ledger.training_rows("XAUUSD")[0]
        self.assertIn(row["y"], (0, 1))
        self.assertGreaterEqual(row["resolve_ts"], row["decision_ts"])
        res = SV.train_from_ledger(q.ledger, "XAUUSD")
        self.assertEqual(res[0]["status"], "INSUFFICIENT_EVIDENCE")       # one labelled row: honest status, no model

    def test_modes_assist_needs_validation_and_explicit_confirmation(self):
        from masterquo.quant import metamodel as M
        from masterquo.quant.service import QuantService
        q = QuantService(StubRt())
        self.assertFalse(q.set_mode("ASSIST", confirm=True)["ok"])         # no validated model
        res = M.train(synth_rows(), task={"task_hash": "t", "event_id": "E"})
        M.activate("XAUUSD", "t", M.save("XAUUSD", res, spec={"task_hash": "t"}))
        self.assertFalse(q.set_mode("ASSIST")["ok"])                       # no explicit confirmation
        self.assertFalse(q.assist_active())
        self.assertTrue(q.set_mode("ASSIST", confirm=True, by="TEST")["ok"])
        self.assertTrue(q.assist_active())
        q.set_mode("SHADOW")
        self.assertFalse(q.assist_active())


# =============================================================================================== coordinator: SHADOW parity / ASSIST / REQUIRED
class FakeQuant:
    def __init__(self, assist, hold=None, state="READY"):
        self.assist, self.hold, self.state = assist, hold, state

    def assist_active(self):
        return self.assist

    def coordinator_predictions(self, inst):
        return []

    def coordinator_entry(self, path, cand=None, setup=None):
        return {"family": "quant:metamodel", "use": "ASSIST", "task_type": "EVENT_PROBABILITY", "state": self.state, "data_time": iso(time.time()),
                "result": {"p": 0.3, "e_net_r": -0.2} if self.state == "READY" else None, "quant_hold": self.hold,
                "unavailable_reason": None if self.state == "READY" else "brak"}


class TestCoordinatorQuant(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.config import ConfigStore
        from masterquo.db.database import Database
        from masterquo.decision.coordinator import DecisionCoordinator
        self.db = Database()
        self.db.migrate()
        self.cfg = ConfigStore()
        t_fix = time.time()
        fam = SimpleNamespace(predictions=lambda inst: [{"family": "SEQ_GRU", "use": "SHADOW", "state": "READY", "task_type": "CLASS_PROBABILITIES",
                                                         "data_time": iso(t_fix - 30), "result": {"UP": 0.2, "DOWN": 0.7, "FLAT": 0.1}}])
        self.clock = lambda: t_fix
        self.C = lambda q: self._mk(DecisionCoordinator, fam, q)

    def _mk(self, cls, fam, q):
        c = cls(self.db, self.cfg, families=fam, instrument_fn=lambda: "XAUUSD", clock=self.clock)
        c.quant = q
        return c

    def tearDown(self):
        self.td.close()

    def su(self, status="READY"):
        return {"strategy": "SCALPING", "signal_id": "SIG-1", "symbol": "XAUUSD-", "side": "BUY", "status": status, "entry_ref": 2000.0, "sl": 1998.0,
                "tps": [{"price": 2002.5, "share": 0.5}, {"price": 2003.0, "share": 0.5}], "status_reason": ""}

    def test_off_and_shadow_parity(self):
        setup = {"direction": "LONG", "strategy_id": "S01"}
        base = self.C(None)
        sh = self.C(FakeQuant(assist=False, hold="Quant: E[net R] ≤ 0"))
        a, b = base.model_gate_active(setup), sh.model_gate_active(setup)
        self.assertEqual(json.dumps(a, default=str, sort_keys=True), json.dumps(b, default=str, sort_keys=True))
        ra = base.record_sh(self.su(), None, "PAPER", "acc", None)
        rb = sh.record_sh(self.su(), None, "PAPER", "acc", None)
        self.assertEqual((ra["final_verdict"], ra["reason_codes"], ra["inputs_hash"]), (rb["final_verdict"], rb["reason_codes"], rb["inputs_hash"]))

    def test_assist_can_only_hold(self):
        q = FakeQuant(assist=True, hold="Quant: E[net R] = -0.2 ≤ 0")
        c = self.C(q)
        r = c.record_sh(self.su(), None, "PAPER", "acc", None)
        self.assertEqual(r["final_verdict"], "BLOCKED")
        self.assertIn("MODEL_QUANT_HOLD:quant:metamodel", r["reason_codes"])
        w = c.record_sh(self.su("WAIT"), None, "PAPER", "acc", None)
        self.assertEqual(w["final_verdict"], "WAIT")                       # never upgrades WAIT
        g = c.model_gate_active({"direction": "LONG", "strategy_id": "S01"})
        self.assertEqual(g["status"], "FAIL")
        self.assertIn("MODEL_QUANT_HOLD:quant:metamodel", g["codes"])
        ok = self.C(FakeQuant(assist=True, hold=None)).record_sh(self.su(), None, "PAPER", "acc", None)
        self.assertEqual(ok["final_verdict"], "ENTER")                     # READY without hold: no effect

    def test_required_missing_quant_blocks_and_future_time_is_not_fresh(self):
        from masterquo.decision.coordinator import evaluate_models
        models, reasons = evaluate_models([], "BUY", required={"quant:metamodel"}, assist_threshold=0.6, max_age_s=900, now=time.time())
        self.assertEqual(reasons, ["MODEL_REQUIRED_UNAVAILABLE:quant:metamodel"])
        fut = {"family": "SEQ_GRU", "use": "SHADOW", "state": "READY", "task_type": "CLASS_PROBABILITIES", "data_time": iso(time.time() + 3600),
               "result": {"UP": 0.9, "DOWN": 0.05, "FLAT": 0.05}}
        _, r1 = evaluate_models([fut], "BUY", required={"SEQ_GRU"}, assist_threshold=0.6, max_age_s=900, now=time.time())
        self.assertEqual(r1, ["MODEL_REQUIRED_FUTURE_TIME:SEQ_GRU"])
        m2, r2 = evaluate_models([dict(fut, use="ASSIST", result={"UP": 0.05, "DOWN": 0.9, "FLAT": 0.05})], "BUY", required=set(),
                                 assist_threshold=0.6, max_age_s=900, now=time.time())
        self.assertEqual(r2, [])                                            # a future record never holds either
        self.assertEqual(m2[0]["influence"], "NONE")
        m3, _ = evaluate_models([{"model_name": "TH_LOGREG_M5_H6", "state": "READY", "task_type": "CLASS_PROBABILITIES", "data_time": iso(time.time())}],
                                "BUY", required=set(), assist_threshold=0.6, max_age_s=900, now=time.time())
        self.assertEqual(m3[0]["model_id"], "trainhub:TH_LOGREG")          # no ambiguous '?' at the coordinator boundary

    def test_quant_has_no_order_path(self):
        import pathlib
        src = "\n".join(p.read_text(encoding="utf-8") for p in (pathlib.Path(_env.ROOT) / "backend" / "masterquo" / "quant").glob("*.py"))
        for forbidden in ("order_send", "execution.", "from ..execution", "gateway", "RiskBook(", "reserve(", "telegram"):
            self.assertNotIn(forbidden, src, forbidden)


# =============================================================================================== inventory + CLI
class TestInventoryCli(unittest.TestCase):
    def test_inventory_classifies_everything(self):
        td = TempData()
        try:
            from masterquo.quant import inventory as I
            inv = I.build(None, "XAUUSD")
        finally:
            td.close()
        ids = [e["id"] for e in inv["entries"]]
        self.assertEqual(len(ids), len(set(ids)))
        c = inv["coverage"]
        self.assertEqual(c["inventory"]["recognised"], c["inventory"]["classified"])
        self.assertEqual(c["adapters"]["missing"], [])
        for must in ("rule:data_quality", "sh:tp_model", "mm:event_engine_dir3", "kronos:Kronos-small", "agent:claude", "trainhub:TH_SVM", "family:TS_ARIMA",
                     "family:NLP_SENTIMENT", "lab:SEW_SNN", "lab:LOGREG_GMM_AUG", "si:MQ_SEW_RESNEXT_EB_V1", "si:MQ_SPIKE_BRAIN_FINANCE_V1", "mm:buzoa",
                     "analysis:montecarlo", "quant:metamodel"):
            self.assertIn(must, ids)
        for alias in ("family:TH_RF", "family:SEQ_GRU_EVENT"):
            self.assertNotIn(alias, ids)                                    # folded into the producer
        by = {e["id"]: e for e in inv["entries"]}
        self.assertIn("SEQ_GRU_EVENT", by["mm:event_engine_dir3"]["aliases"])
        self.assertEqual(by["ext:catboost"]["code_state"], "NOT_IMPLEMENTED")
        for ns in ("mm:sdom", "mm:quant_momentum", "mm:renko"):
            self.assertEqual(by[ns]["code_state"], "NO_SPEC")
        self.assertEqual(by["group:lab"]["code_state"], "GROUP")
        self.assertEqual(c["operational"]["ready_with_live_output"], 0)      # offline: never claimed

    def test_cli_help_exit_codes_and_missing_data(self):
        td = TempData()
        try:
            env = dict(__import__("os").environ, PYTHONPATH=str(_env.ROOT / "backend"))
            run = lambda *a: subprocess.run([sys.executable, "-m", "masterquo", "quant", *a], cwd=str(_env.ROOT / "backend"), env=env,  # noqa: E731
                                            capture_output=True, text=True, timeout=300)
            self.assertEqual(run("--help").returncode, 0)
            self.assertEqual(run("status").returncode, 0)
            self.assertEqual(run("train").returncode, 2)                    # no labelled rows
            self.assertEqual(run("mode", "ASSIST", "--confirm").returncode, 3)
            self.assertEqual(run("mode", "BOGUS").returncode, 2)
            self.assertEqual(run("activate").returncode, 2)
            r = run("inventory", "--out", td.dir + "/inv")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        finally:
            td.close()


if __name__ == "__main__":
    unittest.main()
