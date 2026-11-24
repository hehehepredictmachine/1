"""1.46 arch fix wave, group "quant": D4, D8, D9, D11, D17, D21 (scalp A calibration); D22 withdrawn (S0) - regression test only.

S0 rule of this group: Quant ASSIST fails OPEN (an incompatible / unloaded MetaModel never holds an entry), so the existing MetaModels are
NOT invalidated. The feature SEMANTICS are versioned instead: an artifact with feature_schema PMW-QUANT-FEAT-1 gets exactly the input it got
before (bit-for-bit on a frozen input), the fixed meaning (D8 Kalman candidate = 0, D9 stale DXY = mask, D4 regime in the coordinator SH
candidate) applies to PMW-QUANT-FEAT-3; new ledger rows record their version and training never mixes versions.
Isolated MASTERQUO_DATA_DIR, stub runtimes, SYNTHETIC data - no terminal, no orders, no HTTP server."""
from __future__ import annotations

import json
import sqlite3
import time
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _env  # noqa: F401
import numpy as np
from _env import TempData


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, UTC).isoformat()


# ================================================================================================ frozen input (FEAT-1 bit-for-bit)
def frozen_cand():
    return {"setup_id": "SIG-F", "engine": "SH_SCALPING", "strategy_id": "SCALPING", "symbol": "XAUUSD-", "instrument": "XAUUSD",
            "timeframe": "M1", "decision_ts": 1_794_000_123.0, "direction": "LONG", "entry_type": "MARKET", "entry_price": 2000.0,
            "stop_loss": 1998.0, "targets": [{"price": 2002.5, "weight": 0.5}, {"price": 2004.0, "weight": 0.5}], "horizon_s": 1800.0,
            "market_regime": {"state": "TREND", "source": "sh.context (RegimeMachine v2)"}, "features": {"atr_m5": 1.7},
            "execution_context": {"spread": 0.21, "cost_price": 0.35, "commission_known": True}, "score": 64.0,
            "research_features": {"etc:score": 0.25, "g7:none": None}}


def pred(cid, tt, task, tf, res, unit="probability", state="READY", eligible=True):
    return {"canonical_id": cid, "task_type": tt, "task": task, "timeframe": tf, "result": res, "unit": unit, "state": state,
            "eligibility": {"eligible": eligible, "reason": None if eligible else "STALE"}}


def frozen_preds():
    return [pred("trainhub:TH_LOGREG", "CLASS_PROBABILITIES", "DIRECTION_H6_M5", "M5", {"UP": 0.61, "DOWN": 0.27, "FLAT": 0.12}),
            pred("mm:gpr_logret", "REGRESSION", "LOG_RETURN_H3_M5", "M5", {"mean": 0.0004, "sd": 0.0011}, unit="log_return"),
            pred("lab:lgbm", "SCORE", "TRIPLE_BARRIER_LONG_SCORE_H6", "M5", {"raw_score": 0.37}, unit="ratio"),
            pred("mm:kalman_cross", "FILTER_STATE", "KALMAN_CROSS_STATE", "M5", {"state": "BULLISH_CANDIDATE", "fast": 2001.0}, unit="state"),
            pred("mm:breakout_zones", "FILTER_STATE", "BREAKOUT_ZONES_STATE", "M5", {"state": "BEARISH"}, unit="state"),
            pred("analysis:dxy_correlation", "STATE", "XAU_DXY_RELATION_H1", "H1", {"status": "STALE", "corr_72": -0.4, "resid_z_72": 1.25,
                                                                                  "beta_72": -1.1}, unit="mixed"),
            pred("tsfm:chronos2", "REGRESSION", "PRICE_H12_M5", "M5", {"last_close": 2000.1, "pred_close": 2001.3, "median": 2001.0,
                                                                     "quantiles_h": {"0.1": 1999.2, "0.9": 2003.4}}, unit="price"),
            pred("scalp:A_direction", "CLASS_PROBABILITIES", "SCALP_DIRECTION_H1_M1", "M1", {"UP": 0.2, "DOWN": 0.7, "FLAT": 0.1}, state="BLOCKED_DATA"),
            pred("gold_candles:plan", "CLASS_PROBABILITIES", "DIRECTION_H15_M5", "M5", {"UP": 0.5, "DOWN": 0.4, "FLAT": 0.1}, eligible=False)]


# build2(frozen_cand(), frozen_preds()) computed by the code BEFORE this change (HEAD 42d6949) - FEAT-1 artifacts must keep getting it
FROZEN_FEAT1 = {
    'plan:side_long': 1.0, 'plan:gain_r': 1.625, 'plan:tp1_r': 1.25, 'plan:n_targets': 2.0, 'plan:horizon_min': 30.0, 'ctx:cost_r': 0.175,
    'ctx:spread_r': 0.105, 'ctx:risk_atr': 1.1764705882352942, 'ctx:hour_sin': -0.6360782202777646, 'ctx:hour_cos': 0.7716245833877194,
    'ctx:regime=TREND': 1.0, 'ctx:regime=RANGE': 0.0, 'ctx:regime=TRANSITION': 0.0, 'ctx:regime=HIGH_VOL': 0.0, 'ctx:engine=SH_SCALPING': 1.0,
    'ctx:engine=SH_HEDGING': 0.0, 'ctx:engine=SCALP_SHADOW': 0.0, 'ctx:engine=ACTIVE_S01_S12': 0.0, 'ctx:heuristic_score': 0.64,
    'fc:trainhub:TH_LOGREG:DIRECTION_H6_M5:M5:edge': 0.33999999999999997, 'fc:mm:gpr_logret:LOG_RETURN_H3_M5:M5:z': 0.36363636363636365,
    'fc:lab:lgbm:TRIPLE_BARRIER_LONG_SCORE_H6:M5:score': 0.37, 'fc:lab:lgbm:TRIPLE_BARRIER_LONG_SCORE_H6:M5:score_x_side': 0.37,
    'st:mm:kalman_cross:aligned': 1.0, 'st:mm:breakout_zones:aligned': -1.0, 'ctx:dxy_corr_72': -0.4, 'ctx:dxy_resid_z_72': 1.25,
    'ctx:dxy_beta_72': -1.1, 'fcp:tsfm:chronos2:M5:d_atr': 0.7058823529412033, 'fcp:tsfm:chronos2:M5:band_atr': 2.4705882352941444,
    'fcp:tsfm:chronos2:M5:to_tp1_r': -0.6000000000000227, 'fcp:tsfm:chronos2:M5:to_sl_r': 1.6499999999999773,
    'fcp:tsfm:chronos2:M5:med_vs_entry_r': 0.5, 'rm:etc:score': 0.25,
}


class TestFeat1FrozenBitForBit(unittest.TestCase):
    """The FEAT-1 computation (build2 - what every MetaModel artifact trained before 1.46 receives) is unchanged, value for value."""

    def test_legacy_builder_reproduces_the_frozen_output(self):
        from masterquo.quant import features as F
        self.assertEqual(F.build2(frozen_cand(), frozen_preds()), FROZEN_FEAT1)
        self.assertEqual(F.build_for(F.VERSION, frozen_cand(), frozen_preds()), FROZEN_FEAT1)
        self.assertEqual(F.build_for(F.VERSION2, frozen_cand(), frozen_preds()), FROZEN_FEAT1)
        self.assertEqual(F.prediction_features(frozen_preds(), "LONG")["st:mm:kalman_cross:aligned"], 1.0)   # legacy meaning kept
        self.assertEqual(F.schema(["a", "b"]), F.schema_for(F.VERSION, ["a", "b"]))

    def test_feat3_differs_only_by_the_fixed_meaning(self):
        from masterquo.quant import features as F
        f3 = F.build3(frozen_cand(), frozen_preds())
        self.assertEqual(F.CURRENT, F.VERSION3)
        self.assertEqual(F.build_for(F.CURRENT, frozen_cand(), frozen_preds()), f3)
        diff = {k for k in set(f3) | set(FROZEN_FEAT1) if f3.get(k) != FROZEN_FEAT1.get(k)}
        self.assertEqual(diff, {"st:mm:kalman_cross:aligned", "ctx:dxy_corr_72", "ctx:dxy_resid_z_72", "ctx:dxy_beta_72"})
        self.assertEqual(f3["st:mm:kalman_cross:aligned"], 0.0)


# ================================================================================================ D8
class TestKalmanCandidateNotDirectionD8(unittest.TestCase):
    """quant/features._dir_of matched the substring BULL / BEAR: Kalman BULLISH_CANDIDATE (an unconfirmed raw change against the accepted
    crossover) became +1 in st:mm:kalman_cross:aligned."""

    def rec(self, state):
        return [pred("mm:kalman_cross", "FILTER_STATE", "KALMAN_CROSS_STATE", "M5", {"state": state}, unit="state")]

    def test_candidate_is_zero_confirmed_keeps_the_sign(self):
        from masterquo.quant import features as F
        v3 = F.VERSION3
        for state, side, want in (("BULLISH_CANDIDATE", "LONG", 0.0), ("BEARISH_CANDIDATE", "LONG", 0.0), ("BEARISH_CANDIDATE", "SHORT", 0.0),
                                  ("BULLISH_CONFIRMED", "LONG", 1.0), ("BEARISH_CONFIRMED", "LONG", -1.0), ("BEARISH_CONFIRMED", "SHORT", 1.0),
                                  ("NEUTRAL", "LONG", 0.0), ("INSUFFICIENT_HISTORY", "LONG", 0.0), ("INITIALIZING", "SHORT", 0.0)):
            got = F.prediction_features(self.rec(state), side, semantics=v3)["st:mm:kalman_cross:aligned"]
            self.assertEqual(got, want, (state, side))
        c = dict(frozen_cand(), direction="LONG")
        self.assertEqual(F.build3(c, self.rec("BULLISH_CANDIDATE"))["st:mm:kalman_cross:aligned"], 0.0)
        self.assertEqual(F.build2(c, self.rec("BULLISH_CANDIDATE"))["st:mm:kalman_cross:aligned"], 1.0)   # FEAT-1: frozen


# ================================================================================================ D9
class TestDxyStaleMaskedD9(unittest.TestCase):
    """A STALE DXY relation (last DXY bar older than max_age_s) was READY in Quant and its old correlations entered the features."""

    def rec(self, status):
        res = {"corr_72": -0.4, "resid_z_72": 1.2, "beta_72": -1.1}
        if status is not None:
            res["status"] = status
        return [pred("analysis:dxy_correlation", "STATE", "XAU_DXY_RELATION_H1", "H1", res, unit="mixed")]

    def test_stale_or_warmup_relation_is_missing_in_feat3(self):
        from masterquo.quant import features as F
        for status in ("STALE", "WARMUP", "NO_DATA", "DISABLED"):
            f = F.build3(frozen_cand(), self.rec(status))
            self.assertFalse([k for k in f if k.startswith("ctx:dxy_")], status)
            names = ["ctx:dxy_corr_72", "ctx:dxy_beta_72"]
            self.assertEqual(F.vectorise(f, names), ([0.0, 0.0], [1.0, 1.0]))        # masks, never an old value
        for status in ("READY", None):
            f = F.build3(frozen_cand(), self.rec(status))
            self.assertEqual((f["ctx:dxy_corr_72"], f["ctx:dxy_beta_72"]), (-0.4, -1.1), status)
        self.assertEqual(F.build2(frozen_cand(), self.rec("STALE"))["ctx:dxy_corr_72"], -0.4)               # FEAT-1: frozen


# ================================================================================================ versions: metamodel / ledger / training
def synth_rows(n=900, seed=1, version=None):
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        x = float(rng.normal())
        y = int(rng.random() < 1 / (1 + np.exp(-1.5 * x)))
        f = {"plan:gain_r": 1.5, "fc:trainhub:TH_LOGREG:DIRECTION_H6_M5:M5:edge": x, "ctx:hour_sin": float(rng.normal())}
        r = {"row_id": f"r{i}", "decision_ts": 1_794_000_000.0 + i * 600, "resolve_ts": 1_794_000_000.0 + i * 600 + 1800, "features": f, "y": y,
             "net_r": (1.5 if y else -1.0) - 0.05, "data_kind": "REAL"}
        if version:
            r["feature_version"] = version
        rows.append(r)
    return rows


def as_legacy_artifact(res: dict) -> dict:
    """A MetaModel exactly as metamodel.train wrote it before 1.46: feature_schema PMW-QUANT-FEAT-1:<hash>."""
    from masterquo.quant import features as F
    res = json.loads(json.dumps(res))
    res["model"]["feature_schema"] = F.schema(res["model"]["feature_names"])
    return res


class TestFeatureVersioning(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.addCleanup(self.td.close)

    def test_new_models_are_feat3_and_old_feat1_artifacts_still_load(self):
        from masterquo.quant import features as F
        from masterquo.quant import metamodel as M
        res = M.train(synth_rows(), task={"task_hash": "t", "event_id": "E"})
        self.assertTrue(res["model"]["feature_schema"].startswith(F.VERSION3 + ":"), res["model"]["feature_schema"])
        self.assertEqual(res["report"]["feature_version"], F.VERSION3)
        v3 = M.save("XAUUSD", res, spec={"task_hash": "t"})
        self.assertEqual(M.load("XAUUSD", "t", v3)[0]["feature_schema"], res["model"]["feature_schema"])
        v1 = M.save("XAUUSD", as_legacy_artifact(res), spec={"task_hash": "t"})
        model1, _ = M.load("XAUUSD", "t", v1)                              # no invalidation: Quant ASSIST is fail-open
        self.assertTrue(model1["feature_schema"].startswith(F.VERSION + ":"))
        M.activate("XAUUSD", "t", v1)
        bad = json.loads(json.dumps(res))
        bad["model"]["feature_schema"] = F.schema2(bad["model"]["feature_names"])   # metamodel.train never wrote FEAT-2
        vb = M.save("XAUUSD", bad, spec={"task_hash": "t"})
        with self.assertRaises(M.MetaError) as ctx:
            M.load("XAUUSD", "t", vb)
        self.assertIn("INCOMPATIBLE_FEATURE_SCHEMA", str(ctx.exception))

    def test_training_never_mixes_versions(self):
        from masterquo.quant import features as F
        from masterquo.quant import metamodel as M
        rows = synth_rows(version=F.CURRENT)
        rows[5]["feature_version"] = F.LEGACY_ROWS
        with self.assertRaises(M.MetaError) as ctx:
            M.train(rows, task={"task_hash": "t", "event_id": "E"})
        self.assertIn("FEATURE_VERSION_MIXED", str(ctx.exception))
        with self.assertRaises(M.MetaError):
            M.train(synth_rows(), task={"task_hash": "t", "event_id": "E"}, feature_version=F.VERSION)   # new models: CURRENT only

    def test_ledger_records_the_version_and_migrates_an_old_file_in_place(self):
        from masterquo.quant import features as F
        from masterquo.quant.ledger import SCHEMA, QuantLedger
        p = Path(self.td.dir) / "old_ledger.sqlite"
        con = sqlite3.connect(p)                                            # a 1.35-1.46 ledger file: no feature_version column
        con.executescript(SCHEMA)
        con.execute("INSERT INTO rows(row_id, instrument, engine, strategy, direction, decision_ts, task_hash, event_id, spec_json, features_json, "
                    "data_kind, matures_at, status, created_at) VALUES ('old', 'XAUUSD', 'E', 'S', 'LONG', 1.0, 'th', 'E', '{}', '{\"a\": 1.0}', "
                    "'REAL', 1.0, 'PENDING', 1.0)")
        con.commit()
        con.close()
        led = QuantLedger(p)
        led.add_row({"row_id": "new", "instrument": "XAUUSD", "engine": "E", "strategy": "S", "direction": "LONG", "decision_ts": 2.0,
                     "task_hash": "th", "event_id": "E", "spec": {}, "features": {"a": 2.0}, "data_kind": "REAL", "matures_at": 2.0,
                     "feature_version": F.CURRENT})
        for rid in ("old", "new"):
            led.label(rid, "LABELLED", {"y_event": True, "net_r": 1.0}, 10.0)
        got = {r["row_id"]: r["feature_version"] for r in led.training_rows("XAUUSD")}
        self.assertEqual(got, {"old": F.LEGACY_ROWS, "new": F.CURRENT})
        self.assertEqual([r["row_id"] for r in led.training_rows("XAUUSD", feature_version=F.CURRENT)], ["new"])
        self.assertEqual(QuantLedger(p).training_rows("XAUUSD", "th")[0]["features"], {"a": 1.0})     # reopening: no second ALTER

    def test_train_from_ledger_uses_current_rows_only(self):
        from masterquo.quant import features as F
        from masterquo.quant import service as SV
        from masterquo.quant.ledger import QuantLedger
        led = QuantLedger(Path(self.td.dir) / "l.sqlite")
        for i, fv in enumerate((F.CURRENT, F.LEGACY_ROWS, F.CURRENT, F.LEGACY_ROWS, F.LEGACY_ROWS)):
            led.add_row({"row_id": f"r{i}", "instrument": "XAUUSD", "engine": "E", "strategy": "S", "direction": "LONG", "decision_ts": 1e9 + i,
                         "task_hash": "th", "event_id": "TP1_BEFORE_STOP", "spec": {"event_id": "TP1_BEFORE_STOP"}, "features": {},
                         "data_kind": "REAL", "matures_at": 1e9 + i, "feature_version": fv})
            led.label(f"r{i}", "LABELLED", {"y_event": True, "net_r": 1.0}, 1e9 + i + 60)
        seen = {}

        def fake_train(rows, **kw):
            seen["versions"], seen["kw"] = sorted({r["feature_version"] for r in rows}), kw
            return {"status": "INSUFFICIENT_EVIDENCE", "report": {"reason": "test"}}
        with mock.patch.object(SV.M, "train", side_effect=fake_train):
            res = SV.train_from_ledger(led, "XAUUSD", log=lambda *_: None)
        self.assertEqual(seen["versions"], [F.CURRENT])
        self.assertEqual(seen["kw"]["feature_version"], F.CURRENT)
        self.assertEqual((res[0]["n_rows"], res[0]["excluded_older_feature_version"]), (2, 3))


# ================================================================================================ D4 (+ versions in the live assessment)
class StubBridge:
    synthetic = True

    def bars(self, tf, n=None, include_forming=False):
        return []


def su_ready():
    return {"strategy": "SCALPING", "signal_id": "SIG-D4", "symbol": "XAUUSD-", "instrument": "XAUUSD", "side": "BUY", "status": "READY",
            "entry_ref": 2000.0, "sl": 1998.0, "tps": [{"price": 2002.5, "share": 0.5, "name": "TP1"}, {"price": 2004.0, "share": 0.5, "name": "TP2"}],
            "horizon_minutes": 30, "created_at": 1_794_000_123.0, "costs": {"spread": 0.2, "round_trip_price": 0.3, "commission_known": True},
            "score": {"value": 64}, "status_reason": ""}


class CapturingQuant:
    def __init__(self):
        self.cands = []

    def assist_active(self):
        return True

    def coordinator_predictions(self, inst):
        return []

    def coordinator_entry(self, path, cand=None, setup=None):
        self.cands.append((path, cand))
        return {"family": "quant:metamodel", "use": "ASSIST", "task_type": "EVENT_PROBABILITY", "state": "READY", "data_time": iso(time.time()),
                "result": {"p": 0.6, "e_net_r": 0.2}, "quant_hold": None}


class TestSHCandidateRegimeD4(unittest.TestCase):
    """Quant training rows build the SH candidate with the regime of the SH snapshot (evaluation/service._sh); the coordinator built the
    ASSIST candidate with EK.from_sh_setup(su) - no regime, so ctx:regime=* were in every training row and masks at the SH decision."""

    def setUp(self):
        self.td = TempData()
        self.addCleanup(self.td.close)

    def coordinator(self, q):
        from masterquo.config import ConfigStore
        from masterquo.db.database import Database
        from masterquo.decision.coordinator import DecisionCoordinator
        db = Database()
        db.migrate()
        c = DecisionCoordinator(db, ConfigStore(), families=SimpleNamespace(predictions=lambda inst: []), instrument_fn=lambda: "XAUUSD")
        c.quant = q
        return c

    def test_one_factory_same_features_in_ledger_and_coordinator(self):
        from masterquo.evaluation import contract as EK
        from masterquo.quant import features as F
        snap = {"regime": {"state": "TREND"}}
        ledger_c = EK.sh_candidate(su_ready(), snap=snap).to_dict()               # what evaluation/service._sh logs
        q = CapturingQuant()
        rec = self.coordinator(q).record_sh(su_ready(), None, "PAPER", "acc", None, regime=snap["regime"])
        self.assertIsNotNone(rec)
        path, coord_c = q.cands[-1]
        self.assertEqual(path, "SH")
        self.assertEqual(coord_c["market_regime"]["state"], "TREND")
        self.assertEqual(F.build3(coord_c, frozen_preds()), F.build3(ledger_c, frozen_preds()))
        self.assertEqual(F.build3(coord_c, [])["ctx:regime=TREND"], 1.0)

    def test_evaluation_ledger_uses_the_shared_factory(self):
        from masterquo.evaluation import contract as EK
        from masterquo.evaluation import service as ES
        got = []
        svc = ES.EvaluationService.__new__(ES.EvaluationService)
        svc._log = lambda c, prob, extra: got.append(c)
        with mock.patch.object(EK, "sh_candidate", wraps=EK.sh_candidate) as fac:
            svc._sh(su_ready(), "XAUUSD", {"regime": {"state": "RANGE"}}, 1.0)
        self.assertEqual(fac.call_count, 1)
        self.assertEqual(got[0].market_regime["state"], "RANGE")

    def test_sh_service_passes_the_cycle_regime(self):
        from masterquo.sh import service as S
        calls = []

        def new(su, risk, mode, account_key, coord=None, *, regime=None):
            calls.append(regime)

        def old(su, risk, mode, account_key, coord=None):           # a receiver without the keyword stays valid
            calls.append("old")
        self.assertEqual(S._regime_kw(new, {"regime": {"state": "TREND"}}), {"regime": {"state": "TREND"}})
        self.assertEqual(S._regime_kw(new, None), {"regime": None})
        self.assertEqual(S._regime_kw(old, {"regime": {"state": "TREND"}}), {})
        new(su_ready(), None, "PAPER", "a", None, **S._regime_kw(new, {"regime": {"state": "TREND"}}))
        old(su_ready(), None, "PAPER", "a", None, **S._regime_kw(old, {"regime": {"state": "TREND"}}))
        self.assertEqual(calls, [{"state": "TREND"}, "old"])

    def test_sh_cycle_records_with_the_snapshot_regime(self):
        from masterquo.config import ConfigStore
        from masterquo.db.database import Database
        from masterquo.sh import config as C
        from masterquo.sh import service as S
        from masterquo.sh.service import SHService
        from test_sh_service import NOW, Bridge, Log, Modes, mk_setup
        seen = []

        class Arc:
            def record_sh(self, su, risk, mode, account_key, coord=None, *, regime=None):
                seen.append((su["signal_id"], regime))
        svc = SHService(ConfigStore(), Bridge(None, "HEDGING"), Database(), None, Log(), Modes("SIGNALS"), clock=lambda: NOW)
        svc.arc = Arc()
        spec = svc.spec(svc.account())
        s = mk_setup(spec, "SCALPING", "BUY", ref=2000.2, now=NOW)
        q = {"bid": 2000.0, "ask": 2000.2, "spread": 0.2, "age_s": 0.3, "time": NOW}
        with mock.patch.object(S.CX, "snapshot", side_effect=lambda *a, **k: {"vol": {"atr_m5": 1.5}, "regime": {"state": "TREND", "v": 2}}), \
             mock.patch.object(S.SU, "evaluate", side_effect=lambda strat, *a, **k: dict(s) if strat == "SCALPING" else
                               dict(s, status="NO_TRADE", strategy="HEDGING", signal_id="H")), \
             mock.patch.object(S.RK, "evaluate", return_value=None):
            svc.cycle("XAUUSD", {tf: [] for tf in ("M1", "M5", "M15", "H1")}, q, spec, svc.account(), "SIGNALS", NOW, C.load(), svc.executor(spec))
        self.assertIn((s["signal_id"], {"state": "TREND", "v": 2}), seen)


class StubRt:
    def __init__(self):
        self.bridge = StubBridge()


class TestAssessFeatureVersions(unittest.TestCase):
    """The live assessment: ledger row = FEAT-3 (with its version); a FEAT-1 artifact gets exactly the pre-1.46 input, a FEAT-3 artifact the
    new one - for the coordinator SH candidate too (D4 regime only for FEAT-3)."""

    def setUp(self):
        self.td = TempData()
        self.addCleanup(self.td.close)

    def service(self):
        from masterquo.quant.service import QuantService
        q = QuantService(StubRt())
        self.preds = [dict(p, available_at=iso(1_794_000_000.0)) for p in frozen_preds()[:7]]        # available before the decision
        q.pub.current = lambda: {"generation": 7, "instrument": "XAUUSD", "eligible": self.preds, "excluded": [],
                                 "snapshot": {"status": "OK", "data_kind": "REAL", "snapshot_id": "S"}}
        q.tabicl.submit = lambda *a, **k: {"state": "DISABLED", "reason": "test"}
        return q

    def activate(self, task_hash, legacy: bool):
        from masterquo.quant import metamodel as M
        res = M.train(synth_rows(), task={"task_hash": task_hash, "event_id": "TP1_BEFORE_STOP"})
        if legacy:
            res = as_legacy_artifact(res)
        M.activate("XAUUSD", task_hash, M.save("XAUUSD", res, spec={"task_hash": task_hash}))

    def cand_dict(self, regime):
        from masterquo.evaluation import contract as EK
        return EK.sh_candidate(su_ready(), regime=regime).to_dict()

    def run_assess(self, legacy: bool, *, via_coordinator: bool):
        from masterquo.quant import events as QE
        from masterquo.quant import metamodel as M
        q = self.service()
        cd = self.cand_dict({"state": "TREND"})
        th = QE.spec_from_candidate(cd).task_hash()
        self.activate(th, legacy)
        seen = []
        real = M.predict

        def spy(model, feats):
            seen.append(dict(feats))
            return real(model, feats)
        with mock.patch.object(M, "predict", side_effect=spy):
            if via_coordinator:
                e = q.coordinator_entry("SH", cand=cd)
                self.assertEqual(e["state"], "READY", e)
            else:
                a = q.assess(cd, log_row=True)
                self.assertEqual(a["status"], "READY", a)
        return q, cd, seen[-1]

    def test_feat1_artifact_gets_the_pre_146_input(self):
        from masterquo.quant import features as F
        _, cd, feats = self.run_assess(True, via_coordinator=True)
        before = dict(cd, market_regime={"state": None, "source": "sh.context (RegimeMachine v2)"})      # EK.from_sh_setup(su) before 1.46
        self.assertEqual(feats, F.build2(before, frozen_preds()[:7]))
        self.assertNotIn("ctx:regime=TREND", feats)
        self.assertEqual(feats["st:mm:kalman_cross:aligned"], 1.0)
        self.assertIn("ctx:dxy_corr_72", feats)
        _, cd, feats = self.run_assess(True, via_coordinator=False)                # ledger path: regime was there before too
        self.assertEqual(feats, F.build2(cd, frozen_preds()[:7]))

    def test_feat3_artifact_gets_the_fixed_input_and_the_row_records_its_version(self):
        from masterquo.quant import features as F
        _, cd, feats = self.run_assess(False, via_coordinator=True)
        self.assertEqual(feats, F.build3(cd, frozen_preds()[:7]))
        self.assertEqual(feats["ctx:regime=TREND"], 1.0)
        self.assertEqual(feats["st:mm:kalman_cross:aligned"], 0.0)
        self.assertNotIn("ctx:dxy_corr_72", feats)
        q, cd, feats = self.run_assess(False, via_coordinator=False)
        with q.ledger._lock:
            row = q.ledger.c.execute("SELECT feature_version, features_json FROM rows").fetchone()
        self.assertEqual(row[0], F.CURRENT)
        self.assertEqual(json.loads(row[1]), F.build3(cd, frozen_preds()[:7]))


# ================================================================================================ D11
class TestMonteCarloAdapterD11(unittest.TestCase):
    """quant/adapters.analysis read st['last'] / st['result'] - keys MonteCarloService.status() never has: a dead read, a reason that did
    not say why, the real service state (calibration, runs, errors) invisible. The record stays DISABLED (no snapshot result exists)."""

    def test_record_reports_the_real_service_state(self):
        from masterquo.quant import adapters as A
        st = {"version": "PMW-MC-1", "instrument": "XAUUSD", "variant": "GARCH_T", "calibrated": True, "active_calibration": "R1",
              "validations": [], "synthetic": False, "runs": 3, "last_ms": 120.5, "last_error": None, "note": "..."}
        rt = SimpleNamespace(montecarlo=SimpleNamespace(status=lambda: st))
        rec = next(r for r in A.analysis(rt, "XAUUSD") if r["canonical_id"] == "analysis:montecarlo")
        self.assertEqual(rec["state"], "DISABLED")
        self.assertIsNone(rec["result"])
        info = rec.get("service_status") or {}
        self.assertEqual((info.get("calibrated"), info.get("active_calibration"), info.get("runs"), info.get("variant")), ("TAK", "R1", 3, "GARCH_T"))
        self.assertIn("na żądanie", rec["unavailable_reason"])
        self.assertIn("R1", rec["unavailable_reason"])


# ================================================================================================ D17
def news_service(enabled=True):
    from masterquo.news.service import NewsService
    cfg = SimpleNamespace(news=SimpleNamespace(enabled=enabled, poll_seconds=300))
    return NewsService(SimpleNamespace(get=lambda: cfg), None, SimpleNamespace(publish=lambda *a: None), None)


class TestNewsRecordD17(unittest.TestCase):
    """rule:news was READY always (also with the calendar NOT_LOADED) and read 'blackout' / 'next_event_in_s', which NewsService.summary()
    never returns - both always empty."""

    def rec(self, n):
        from masterquo.quant import adapters as A
        rt = SimpleNamespace(sh=SimpleNamespace(snapshot={"computed_at": time.time()}), news=n)
        return next(r for r in A.rules(rt, "XAUUSD") if r["canonical_id"] == "rule:news")

    def test_not_loaded_calendar_is_not_ready(self):
        r = self.rec(news_service())
        self.assertNotEqual(r["state"], "READY")
        self.assertEqual(r["state"], "BLOCKED_DATA")
        self.assertIn("NOT_LOADED", r["unavailable_reason"])
        self.assertEqual(self.rec(news_service(enabled=False))["state"], "DISABLED")

    def test_loaded_calendar_carries_blackout_and_next_event(self):
        n = news_service()
        now = time.time()
        n.report = {"as_of": iso(now), "status": "PARTIAL",
                    "calendar": {"status": "PARTIAL", "risk": {"level": "HIGH", "events": [{"name": "NFP"}]},
                                 "events": [{"event_id": "a", "name": "NFP", "impact": "HIGH", "scheduled_at": iso(now + 600)},
                                            {"event_id": "b", "name": "Claims", "impact": "LOW", "scheduled_at": iso(now + 120)},
                                            {"event_id": "c", "name": "CPI", "impact": "HIGH", "scheduled_at": iso(now - 1800)}]}}
        r = self.rec(n)
        self.assertEqual(r["state"], "READY")
        self.assertEqual(r["result"]["blackout"], "TAK")
        self.assertAlmostEqual(r["result"]["next_event_in_s"], 600, delta=30)          # the next HIGH event, not the LOW one
        self.assertEqual(r["result"]["risk_level"], "HIGH")
        n.report = dict(n.report, calendar={"status": "PARTIAL", "risk": {"level": "NONE_DETECTED_IN_PARTIAL_CALENDAR", "events": []}, "events": []})
        r = self.rec(n)
        self.assertEqual((r["state"], r["result"]["blackout"]), ("READY", "NIE"))
        self.assertNotIn("next_event_in_s", r["result"])                              # none listed: absent (None), never 0
        n.report = dict(n.report, as_of=iso(now - 7200))                               # older than 2 x poll: STALE calendar
        self.assertEqual(self.rec(n)["state"], "BLOCKED_DATA")


# ================================================================================================ D21 (quant/adapters.py:352 only)
class TestScalpACalibrationD21(unittest.TestCase):
    """scalp A records were UNCALIBRATED for every run, although the trainer stores a calibrator per horizon and the worker applies it."""

    def test_calibration_status_follows_the_registry(self):
        from masterquo.quant import adapters as A
        reg = {"active": "R1", "runs": {"R1": {"models": {"1": {"selected": "LR", "calibrator": {"coef": [[0.1]]}}, "3": {"selected": "PRIOR"}}}}}
        hz = {"1": {"p_down": 0.2, "p_flat": 0.3, "p_up": 0.5}, "3": {"p_down": 0.3, "p_flat": 0.4, "p_up": 0.3}}
        sc = SimpleNamespace(registry=lambda: reg, forecasts=lambda: {"status": "SHADOW", "run_id": "R1", "feature_time_utc": iso(time.time() - 60),
                                                                      "horizons": hz})
        recs = {r["horizon"]["bars"]: r for r in A.scalp_a(SimpleNamespace(scalp=sc), "XAUUSD")}
        self.assertEqual(recs[1]["state"], "READY")
        self.assertEqual(recs[1]["calibration"]["status"], "CALIBRATED_DEV")
        self.assertEqual(recs[3]["calibration"]["status"], "UNCALIBRATED")             # no calibrator stored for that horizon
        self.assertEqual(recs[1]["result"], {"DOWN": 0.2, "FLAT": 0.3, "UP": 0.5})     # values untouched


# ================================================================================================ D22 (withdrawn - S0)
class TestEventGRUInputUnchangedD22(unittest.TestCase):
    """D22 (live Event GRU units cut from the END of the run) was WITHDRAWN as S0(b): a fresher mm:event_engine_dir3 record removes the
    periodic MODEL_REQUIRED_STALE block when the model is listed in decision.required_models, and silently feeds a different
    fc:mm:event_engine_dir3:* value to existing FEAT-1 MetaModels / to the SEQ_GRU_EVENT family in ASSIST (looser entry gate, no retraining,
    no schema version). The published record is computed exactly as in 42d6949: units cut from the START of the run like training (mm/jobs),
    so data_time is the end of the newest full unit (0-15 events before the newest event). Expected values frozen from 42d6949."""

    T0 = 1_794_000_000.0
    N = 1 + 16 * 3 + 7                                            # 56 closed M1 bars -> 55 valid events: 3 full units + remainder 7

    def predict(self):
        from masterquo.mm import artifacts as MA
        from masterquo.mm import event_engine as EE
        from masterquo.quant import adapters as A
        bars = [{"open_utc": iso(self.T0 + 60 * i), "o": 2000.0, "h": 2000.5, "l": 1999.5, "c": 2000.0 + 0.1 * np.sin(i), "tv": 5, "spread": 20,
                 "closed": True} for i in range(self.N)]
        rt = SimpleNamespace(bridge=SimpleNamespace(bars=lambda tf, include_forming=False: bars, symbol_info={"point": 0.01}, synthetic=True))
        st = {"scaler_med": [0.0] * 8, "scaler_iqr": [1.0] * 8}
        seen = []

        def fake_predict(m, X, seg):
            seen.append((np.array(X), np.array(seg)))
            return np.tile([0.2, 0.3, 0.5], (len(X), 1))
        with mock.patch.object(MA, "read_pointer", return_value={"active": {"event_engine_dir3": "EG1"}}), \
             mock.patch.object(MA, "load", return_value=(st, {"event_source": "BAR_CLOSE_EVENTS", "feature_schema": "PMW-MM-EVENTS-1"})), \
             mock.patch.object(EE.EventModel, "from_state", return_value=object()), \
             mock.patch.object(EE, "predict", side_effect=fake_predict):
            rec = A.EventGRU().predict(rt, "XAUUSD")
        return rec, seen

    def test_record_data_time_is_the_end_of_the_training_cut(self):
        rec, _ = self.predict()
        self.assertEqual(rec["state"], "READY", rec.get("unavailable_reason"))
        newest_close = self.T0 + 60 * (self.N - 1) + 60           # BAR_CLOSE_EVENTS: event = close of the newest closed M1
        self.assertEqual(datetime.fromisoformat(rec["data_time"]).timestamp(), newest_close - 7 * 60)   # 7 remainder events after it

    def test_model_input_is_the_42d6949_input(self):
        from masterquo.mm import events as EV
        rec, seen = self.predict()
        self.assertEqual(rec["result"], {"DOWN": 0.2, "FLAT": 0.3, "UP": 0.5})
        self.assertEqual(len(seen), 1)
        X, seg = seen[0]
        self.assertEqual(X.shape, (3, 16, len(EV.FEATURES)))     # units of events 1-16, 17-32, 33-48; the remainder 49-55 left out
        self.assertEqual([int(s) for s in seg], [0, 0, 0])
        common = [4.110873864173, 0.2, 0.0, 1.791759469228, 1.0]
        first = [[0.084147098481, 0.084147098481, 1.0], [-0.067349417522, 0.067349417522, -1.0], [0.044848517887, 0.044848517887, 1.0]]
        last = [[-0.093819115682, 0.093819115682, -1.0], [0.095546432656, 0.095546432656, 1.0], [-0.089182778407, 0.089182778407, -1.0]]
        for got, rows in ((X[:, 0, :], first), (X[:, -1, :], last)):                                  # first / last event of each unit
            np.testing.assert_allclose(got, [[common[0], *r, *common[1:]] for r in rows], rtol=0, atol=1e-11)
        self.assertAlmostEqual(float(X.sum()), 343.79566043583895, places=9)

    def test_units_has_one_cut(self):
        from masterquo.mm import events as EV
        with self.assertRaises(TypeError):
            EV.units({}, {}, 16, align="end")                     # no live-only variant: training and inference cut the same way


if __name__ == "__main__":
    unittest.main()
