"""1.46 arch fix wave 2b, group "quant_core": quant/checks (data_time basis), features (FEAT-4 regime vocabulary), metamodel (missing
features never missing in training), TabICL (strategy encoding, persisted confidences, weights folder), Event GRU READY path, NO_SPEC rows,
quant/units production API, shared calibration metrics.

Isolated MASTERQUO_DATA_DIR, stub runtimes, SYNTHETIC data - no terminal, no orders, no HTTP server."""
from __future__ import annotations

import json
import unittest
from typing import ClassVar
from unittest import mock

import _env
from _env import TempData
from test_quant_core import NOW, pred


# ================================================================================================ I0797 checks: data_time basis
class TestChecksDataTimeBasis(unittest.TestCase):
    """trainhub / Kronos / TSFM records report the bar CLOSE as data_time, checks.py measured TTL and LATE_GENERATION as if it were the
    bar OPEN - such a record lived one bar longer and a record two bars older than the newest closed bar was not LATE_GENERATION.
    Ported from the withdrawn patch 9f1958f (chunk_26#5); only tightens: a record is never eligible where it was excluded before."""

    def test_close_basis_record_two_bars_old_is_late(self):
        from masterquo.quant import checks as CK
        floor = {"M5": NOW - 300}                               # newest closed M5 bar opened 300 s ago
        p1 = pred(age=300)                                     # trainhub: data_time = CLOSE of the bar one before the newest
        self.assertTrue(CK.check(p1, now=NOW, generation_floor=floor)["eligible"])
        p2 = pred(age=600)                                     # close of the bar two before the newest -> late worker answer
        self.assertEqual(CK.check(p2, now=NOW, generation_floor=floor)["reason"], "LATE_GENERATION:M5")
        # the same time on a bar-OPEN record is one bar newer -> not late (unchanged rule for open-basis producers)
        p3 = dict(pred(age=600), data_time_basis="BAR_OPEN")
        self.assertTrue(CK.check(p3, now=NOW, generation_floor=floor)["eligible"])

    def test_close_basis_ttl_is_two_bars_after_close(self):
        from masterquo.quant import checks as CK
        self.assertTrue(CK.check(pred(age=590), now=NOW)["eligible"])                       # close + < 2 bars
        self.assertEqual(CK.check(pred(age=700), now=NOW)["reason"].split(":")[0], "STALE")  # close + 2 bars + 100 s
        p = dict(pred(age=700), data_time_basis="BAR_OPEN")                                  # open + 700 s < open + 3 bars
        self.assertTrue(CK.check(p, now=NOW)["eligible"])
        kr = pred(name="Kronos-small", task="KRONOS_CLOSE_PATH_H6_M5", age=850)
        self.assertEqual(CK.data_time_basis(kr), "BAR_CLOSE")
        self.assertEqual(CK.check(kr, now=NOW)["reason"].split(":")[0], "STALE")

    def test_explicit_ttl_and_open_basis_producers_unchanged(self):
        from masterquo.quant import checks as CK
        p = dict(pred(name="mm:gpr_logret", age=850))           # not a close-basis producer: TTL = 3 bars from data_time as before
        p["canonical_id"] = "mm:gpr_logret"
        self.assertEqual(CK.data_time_basis(p), "BAR_OPEN")
        self.assertTrue(CK.check(p, now=NOW)["eligible"])
        q = dict(pred(age=850), ttl_s=900.0)                    # an explicit ttl_s is measured from data_time (unchanged)
        self.assertTrue(CK.check(q, now=NOW)["eligible"])

    def test_tightening_only_on_a_grid(self):
        """Every record eligible after the change was eligible before (old rule re-implemented here): no new eligible record."""
        from masterquo.quant import checks as CK
        from masterquo.timeutil import TF_SECONDS

        def old_check(p, now, floor):
            dt = CK.ts(p.get("data_time"))
            age = now - dt
            if age > CK.ttl_for(p):
                return False
            tf = p.get("timeframe")
            return not (floor and tf in floor and dt < floor[tf] - TF_SECONDS.get(tf, 60))
        for name in ("TH_LOGREG_M5_H6", "Kronos-small", "mm:gpr_logret"):
            for age in range(0, 1300, 25):
                for floor in (None, {"M5": NOW - 300}, {"M5": NOW - 900}):
                    p = pred(name=name, age=float(age))
                    new = CK.check(p, now=NOW, generation_floor=floor)["eligible"]
                    if new:
                        self.assertTrue(old_check(p, NOW, floor), (name, age, floor))


# ================================================================================================ I0561 / I0565 / I0566 / I0016 regime
SH_SRC = "sh.context (RegimeMachine v2)"
ACT_SRC = "strategies.regime (MarketRegimeEngine)"


def reg_cand(state, *, source=SH_SRC, engine="SH_SCALPING", direction="LONG"):
    from test_arch146_fix_quant import frozen_cand
    return dict(frozen_cand(), engine=engine, direction=direction, market_regime={"state": state, "source": source})


def regime_cols(f: dict) -> dict:
    return {k: v for k, v in f.items() if k.startswith("ctx:regime")}


class TestRegimeVocabularyFeat4(unittest.TestCase):
    """quant/features.py compared the regime state with ('TREND', 'RANGE', 'TRANSITION', 'HIGH_VOL'): the SH RegimeMachine v2 emits
    TREND_UP / TREND_DOWN / RANGE / TRANSITION and the ACTIVE MarketRegimeEngine TREND_UP / TREND_DOWN / COMPRESSION / ... - a trend was
    'known, none' (all ctx:regime=* = 0 with mask 0), HIGH_VOL never occurred and both definitions shared one column. FEAT-4 (CURRENT)
    encodes the state in the vocabulary of its own source; FEAT-1 / FEAT-3 artifacts keep their frozen input."""

    def test_trend_states_are_encoded(self):
        from masterquo.quant import features as F
        self.assertEqual(F.CURRENT, F.VERSION4)
        f = F.build_for(F.CURRENT, reg_cand("TREND_UP"), [])
        self.assertEqual(f["ctx:regime_sh=TREND_UP"], 1.0)
        self.assertEqual([f[f"ctx:regime_sh={s}"] for s in ("TREND_DOWN", "RANGE", "TRANSITION")], [0.0, 0.0, 0.0])
        self.assertEqual(f["ctx:regime_sh:trend_aligned"], 1.0)
        self.assertEqual(F.build4(reg_cand("TREND_DOWN"), [])["ctx:regime_sh:trend_aligned"], -1.0)          # LONG against the trend
        self.assertEqual(F.build4(reg_cand("TREND_DOWN", direction="SHORT"), [])["ctx:regime_sh:trend_aligned"], 1.0)
        self.assertEqual(F.build4(reg_cand("RANGE"), [])["ctx:regime_sh:trend_aligned"], 0.0)
        # the frozen FEAT-3 input of the same candidate: the trend was all zeros (what FEAT-3 artifacts keep getting)
        self.assertEqual(set(regime_cols(F.build3(reg_cand("TREND_UP"), [])).values()), {0.0})

    def test_active_states_have_their_own_columns(self):
        from masterquo.quant import features as F
        f = F.build4(reg_cand("COMPRESSION", source=ACT_SRC, engine="ACTIVE_S01_S12"), [])
        self.assertEqual(f["ctx:regime_active=COMPRESSION"], 1.0)
        self.assertEqual(sum(v for k, v in f.items() if k.startswith("ctx:regime_active=")), 1.0)
        self.assertFalse([k for k in f if k.startswith("ctx:regime_sh")])
        for st in ("DATA_UNAVAILABLE", "STALE", "XYZ", "", None, "TREND", "HIGH_VOL", "WARMING_UP"):
            for src, eng in ((ACT_SRC, "ACTIVE_S01_S12"), (SH_SRC, "SH_SCALPING")):
                self.assertEqual(regime_cols(F.build4(reg_cand(st, source=src, engine=eng), [])), {}, (st, src))   # mask, never 'none'
        self.assertEqual(regime_cols(F.build4(reg_cand("COMPRESSION"), [])), {})          # an ACTIVE-only state from the SH source

    def test_sources_use_separate_columns(self):
        from masterquo.quant import features as F
        sh = regime_cols(F.build4(reg_cand("RANGE"), []))
        act = regime_cols(F.build4(reg_cand("RANGE", source=ACT_SRC, engine="ACTIVE_S01_S12"), []))
        self.assertEqual(sh["ctx:regime_sh=RANGE"], 1.0)
        self.assertEqual(act["ctx:regime_active=RANGE"], 1.0)
        self.assertFalse(set(sh) & set(act))
        self.assertEqual(regime_cols(F.build4(reg_cand("RANGE", source="scalp (kontekst M15/M30/H1)", engine="SCALP_SHADOW"), [])), {})
        no_src = dict(reg_cand("TREND_UP"), market_regime={"state": "TREND_UP"})          # no source: the engine names the definition
        self.assertEqual(F.build4(no_src, [])["ctx:regime_sh=TREND_UP"], 1.0)
        f = F.build4(reg_cand("TREND_UP"), [])
        self.assertFalse([k for k in f if k.startswith("ctx:regime=") or "HIGH_VOL" in k])

    def test_vocabularies_match_the_regime_engines(self):
        from masterquo.quant import features as F
        from masterquo.strategies import regime as SR
        self.assertEqual(set(F.REGIME_ACTIVE), set(SR.STATES) - {"DATA_UNAVAILABLE", "STALE"})
        src = (_env.ROOT / "backend" / "masterquo" / "lab" / "market_v2.py").read_text(encoding="utf-8")
        for st in F.REGIME_SH:                                                            # RegimeMachine v2 (lab/market_v2.py) states
            self.assertIn(f'"{st}"', src)

    def test_feat4_differs_from_feat3_only_by_the_regime_columns(self):
        from masterquo.quant import features as F
        from test_arch146_fix_quant import frozen_preds
        c = reg_cand("TREND_DOWN")
        f3, f4 = F.build3(c, frozen_preds()), F.build4(c, frozen_preds())
        self.assertEqual({k: v for k, v in f3.items() if not k.startswith("ctx:regime")},
                         {k: v for k, v in f4.items() if not k.startswith("ctx:regime")})
        self.assertEqual(F.build_for(F.VERSION3, c, frozen_preds()), f3)

    def test_versions_are_known_to_the_artifact_loader(self):
        from masterquo.quant import features as F
        self.assertIn(F.VERSION4, F.ARTIFACT_VERSIONS)
        self.assertIn(F.VERSION3, F.ARTIFACT_VERSIONS)
        self.assertEqual(F.version_of(F.schema_for(F.VERSION4, ["a"])), F.VERSION4)
        self.assertEqual(F.REGIME_IN_SH_CANDIDATE, (F.VERSION3, F.VERSION4))


class TestRegimeArtifactsKeepTheirInput(unittest.TestCase):
    """Service level: a FEAT-3 artifact still gets build3 (+ the D4 evaluation without regime), a FEAT-4 artifact build4 (+ the same D4
    tightening); the ledger row is FEAT-4; FEAT-3 rows never train a FEAT-4 model and never enter the TabICL context."""

    def setUp(self):
        self.td = TempData()
        self.addCleanup(self.td.close)

    def _run(self, version):
        from masterquo.quant import events as QE
        from masterquo.quant import features as F
        from masterquo.quant import metamodel as M
        from test_arch146_fix_quant import AssessFixture, as_feat3_artifact, synth_rows
        fx = AssessFixture()
        fx.td = self.td
        q = fx.service()
        cd = fx.cand_dict({"state": "TREND_UP"})
        th = QE.spec_from_candidate(cd).task_hash()
        res = M.train(synth_rows(), task={"task_hash": th, "event_id": "TP1_BEFORE_STOP"})
        if version == F.VERSION3:
            res = as_feat3_artifact(res)
        M.activate("XAUUSD", th, M.save("XAUUSD", res, spec={"task_hash": th}))
        self.assertIsNotNone(q._model("XAUUSD", th)[1])
        seen, real = [], M.predict

        def spy(model, feats, **kw):
            seen.append(dict(feats))
            return real(model, feats, **kw)
        with mock.patch.object(M, "predict", side_effect=spy):
            e = q.coordinator_entry("SH", cand=cd)
        self.assertEqual(e["state"], "READY", e)
        return q, cd, fx.preds, seen

    def test_feat3_artifact_gets_build3(self):
        from masterquo.quant import features as F
        _, cd, preds, seen = self._run(F.VERSION3)
        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[0], F.build3(cd, preds))
        self.assertIn("ctx:regime=TREND", seen[0])                     # frozen FEAT-3 meaning (TREND_UP = all zeros)
        self.assertEqual(seen[1], F.build3(dict(cd, market_regime=dict(cd["market_regime"], state=None)), preds))

    def test_feat4_artifact_gets_build4_and_d4_tightening(self):
        from masterquo.quant import features as F
        q, cd, preds, seen = self._run(F.VERSION4)
        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[0], F.build4(cd, preds))
        self.assertEqual(seen[0]["ctx:regime_sh=TREND_UP"], 1.0)
        self.assertFalse(regime_cols(seen[1]))                         # the D4 evaluation without regime: masks
        a = q.assess(cd, log_row=True)
        with q.ledger._lock:
            row = q.ledger.c.execute("SELECT feature_version, features_json FROM rows").fetchone()
        self.assertEqual(row[0], F.VERSION4)
        self.assertEqual(json.loads(row[1])["ctx:regime_sh=TREND_UP"], 1.0)
        self.assertEqual(a["model"]["feature_version"], F.VERSION4)

    def test_feat3_rows_never_train_or_enter_the_context(self):
        from masterquo.quant import features as F
        from masterquo.quant import metamodel as M
        from masterquo.quant import tabicl as T
        from test_arch146_fix_quant import synth_rows
        rows = synth_rows(version=F.CURRENT)
        rows[3]["feature_version"] = F.VERSION3
        with self.assertRaises(M.MetaError) as ctx:
            M.train(rows, task={"task_hash": "t", "event_id": "E"})
        self.assertIn("FEATURE_VERSION_MIXED", str(ctx.exception))
        self.assertFalse(T._current({"feature_version": F.VERSION3}))
        self.assertTrue(T._current({"feature_version": F.VERSION4}))


# ================================================================================================ I0530 never-missing features
def manual_model(names, mean, scale, coef, *, ridge=None, intercept=0.0, version=None):
    from masterquo.quant import features as F
    from masterquo.quant import metamodel as M
    return {"version": M.VERSION, "feature_names": list(names), "feature_schema": F.schema_for(version or F.CURRENT, list(names)),
            "scaler": {"mean": list(mean), "scale": list(scale)}, "logit": {"coef": list(coef), "intercept": intercept, "C": 1.0},
            "calibrator": {"kind": "identity"}, "prior": 0.5, "event_id": "E", "task_hash": "t", "ridge": ridge}


class TestMetaMissingNeverSeen(unittest.TestCase):
    """A feature present in every training row has a constant mask column (scaler mean 0, scale 1, coefficient 0): vectorise() turned a
    missing value into 0, so p(missing) == p(value 0) - an arbitrary point of its scale. Now: training mean + missing_never_seen + an
    ASSIST hold (fail-closed); the pre-change value stays in `legacy` (reproduction check, D4 floor) so no HOLD can disappear."""

    def setUp(self):
        self.td = TempData()
        self.addCleanup(self.td.close)

    def test_missing_never_seen_feature_gets_the_training_mean(self):
        from masterquo.quant import metamodel as M
        from masterquo.quant import numeric as N
        m = manual_model(["ctx:hour_sin"], [0.3, 0.0], [0.5, 1.0], [2.0, 0.0])
        got = M.predict(m, {})
        self.assertAlmostEqual(got["p_event"], M.predict(m, {"ctx:hour_sin": 0.3})["p_event"], places=12)     # neutral, not value 0
        self.assertAlmostEqual(got["p_event"], 0.5, places=12)
        self.assertEqual(got["missing_never_seen"], ["ctx:hour_sin"])
        self.assertAlmostEqual(got["legacy"]["p_event"], float(N.sigmoid((0.0 - 0.3) / 0.5 * 2.0)), places=12)    # the old value
        self.assertNotIn("legacy", M.predict(m, {"ctx:hour_sin": 0.1}))                                       # present: unchanged

    def test_feature_seen_missing_in_training_keeps_its_learned_mask(self):
        from masterquo.quant import metamodel as M
        m = manual_model(["a", "b"], [0.3, 0.1, 0.0, 0.25], [0.5, 0.2, 1.0, 0.4], [1.0, 0.5, 0.0, 0.7])
        got = M.predict(m, {"a": 0.3})
        self.assertEqual(got["missing_never_seen"], [])
        x = [(0.3 - 0.3) / 0.5 * 1.0, (0.0 - 0.1) / 0.2 * 0.5, 0.0, (1.0 - 0.25) / 0.4 * 0.7]                     # value 0 + mask 1 as before
        from masterquo.quant import numeric as N
        self.assertAlmostEqual(got["p_event"], float(N.sigmoid(sum(x))), places=12)

    def _service_with(self, model):
        from masterquo.quant import events as QE
        from masterquo.quant import metamodel as M
        from test_arch146_fix_quant import AssessFixture
        fx = AssessFixture()
        fx.td = self.td
        q = fx.service()
        cd = fx.cand_dict({"state": "TREND_UP"})
        th = QE.spec_from_candidate(cd).task_hash()
        model = dict(model, task_hash=th)
        M.activate("XAUUSD", th, M.save("XAUUSD", {"status": "VALIDATED_SHADOW", "model": model, "report": {"reproduction": []}},
                                         spec={"task_hash": th}))
        return q, cd

    def test_assist_holds_when_a_never_missing_feature_is_missing(self):
        m = manual_model(["ctx:hour_sin", "fc:not_in_this_snapshot:X:M5:edge"], [0.1, 0.2, 0.0, 0.0], [0.7, 0.3, 1.0, 1.0],
                         [0.1, 0.1, 0.0, 0.0])
        q, cd = self._service_with(m)
        e = q.coordinator_entry("SH", cand=cd)
        self.assertEqual(e["state"], "READY", e)
        self.assertIn("brak cech obecnych w każdym wierszu treningu", e["quant_hold"] or "")
        a = q.assess(cd, mode="SHADOW")
        self.assertEqual(a["probability"]["status"], "DEGRADED_MISSING_FEATURES")
        self.assertEqual(a["probability"]["missing_never_seen"], ["fc:not_in_this_snapshot:X:M5:edge"])
        self.assertEqual(a["influence"], "NONE")                                                       # SHADOW: recorded only

    def test_no_change_when_every_trained_feature_is_present(self):
        m = manual_model(["ctx:hour_sin"], [0.1, 0.0], [0.7, 1.0], [0.1, 0.0])
        q, cd = self._service_with(m)
        a = q.assess(cd, mode="ASSIST")
        self.assertEqual(a["probability"]["status"], "CALIBRATED_VALIDATED")
        self.assertEqual(a["probability"]["missing_never_seen"], [])
        self.assertIsNone(a["would_hold"])

    def test_d4_evaluation_without_regime_keeps_the_pre_change_hold(self):
        """The regime column was present in every training row: the D4 evaluation WITHOUT regime has it missing. The old computation
        (value 0) holds there (E[net R] <= 0); the mean fill would not - the floor must stay the old one (never a looser gate)."""
        ridge = {"scaler": {"mean": [0.5, 0.0], "scale": [0.5, 1.0]}, "coef": [1.0, 0.0], "intercept": 0.5, "alpha": 1.0, "resid_q": None}
        m = manual_model(["ctx:regime_sh=TREND_UP"], [0.5, 0.0], [0.5, 1.0], [1.0, 0.0], ridge=ridge)
        q, cd = self._service_with(m)
        e = q.coordinator_entry("SH", cand=cd)
        self.assertEqual(e["state"], "READY", e)
        self.assertAlmostEqual(e["result"]["e_net_r"], 1.5)                                            # with the regime: no hold
        self.assertIsNotNone(e["quant_hold"])
        self.assertIn("bez reżimu", e["quant_hold"])
        self.assertIn("E[net R] = -0.500", e["quant_hold"])                                            # value 0, exactly as before
        self.assertNotIn("brak cech", e["quant_hold"])

    def test_old_artifact_reproduction_stays_loadable(self):
        """An artifact whose stored reproduction row lacks a never-missing feature (computed with value 0) still loads."""
        from masterquo.quant import metamodel as M
        m = manual_model(["ctx:hour_sin"], [0.3, 0.0], [0.5, 1.0], [2.0, 0.0])
        old_out = M.predict(m, {})["legacy"]
        ver = M.save("XAUUSD", {"status": "VALIDATED_SHADOW", "model": m, "report": {"reproduction": [{"features": {}, "out": old_out}]}},
                     spec={"task_hash": "t"})
        model, _ = M.load("XAUUSD", "t", ver)
        self.assertEqual(model["feature_names"], ["ctx:hour_sin"])


# ================================================================================================ I0538 TabICL strategy encoding
class TestTabICLStrategyEncoding(unittest.TestCase):
    """ctx:strategy_code = sha256(strategy) % 997 gave TabICL a categorical id as one ordinal number. Now a one-hot column per strategy
    (absent = 0, not NaN); a reconstruction file written by TABICL-1 is migrated when read (nothing deleted)."""

    def setUp(self):
        self.td = TempData()
        self.addCleanup(self.td.close)

    def test_one_hot_instead_of_a_hash_code(self):
        from masterquo.quant import tabicl as T
        f = T.strategy_features("SH_SCALPING", "SH_SCALPING/PMW_SC01")
        self.assertNotIn("ctx:strategy_code", f)
        self.assertEqual(f["ctx:strategy=SH_SCALPING/PMW_SC01"], 1.0)
        self.assertEqual(T.strategy_features(None, "PMW_HG02")["ctx:family_hedging"], 1.0)
        self.assertEqual(T.VERSION, "PMW-QUANT-TABICL-2")

    def test_vector_fills_other_strategies_with_zero(self):
        import math

        from masterquo.quant import tabicl as T
        self.assertEqual(T.vector({}, ["ctx:strategy=X"]), [0.0])
        self.assertEqual(T.vector({"ctx:strategy=X": 1.0}, ["ctx:strategy=X"]), [1.0])
        self.assertTrue(math.isnan(T.vector({}, ["ctx:hour_sin"])[0]))                    # other features: missing stays NaN

    def test_old_reconstruction_file_is_migrated_on_read(self):
        from masterquo.quant import tabicl as T
        row = {"id": "R:PMW_SC01:M1:1:LONG", "tf": "M1", "decision_ts": 1.0, "resolve_ts": 2.0, "y": 1, "strategy": "PMW_SC01",
               "features": {"ctx:strategy_code": 412.0, "ctx:family_hedging": 0.0, "plan:gain_r": 1.5}, "event_key": "K",
               "provenance": "RECONSTRUCTED_HISTORY", "data_kind": "REAL_USER_DATA"}
        T.recon_path("XAUUSD").write_text(json.dumps(row) + "\n", encoding="utf-8")
        got = T.recon_rows("XAUUSD", "K", 10.0)
        self.assertEqual(len(got), 1)
        self.assertNotIn("ctx:strategy_code", got[0]["features"])
        self.assertEqual(got[0]["features"]["ctx:strategy=PMW_SC01"], 1.0)
        self.assertEqual(got[0]["features"]["plan:gain_r"], 1.5)
        self.assertIn("ctx:strategy_code", T.recon_path("XAUUSD").read_text(encoding="utf-8"))   # the file itself is not rewritten


# ================================================================================================ I0536 TabICL READY persisted
class TestTabICLConfidencePersisted(unittest.TestCase):
    """A READY TabICLv2 result lived only in RAM (newest 500) and the ledger kept the assessment as at submit (QUEUED): no durable
    p_event_raw for a later calibration check. Now one row per plan_hash in the additive ledger table confidence_scores."""

    def setUp(self):
        self.td = TempData()
        self.addCleanup(self.td.close)

    def test_ready_result_is_written_to_the_ledger(self):
        import time
        from pathlib import Path

        from masterquo.quant import events as EV
        from masterquo.quant import tabicl as QT
        from masterquo.quant.ledger import QuantLedger
        from masterquo.quant.tabicl import TabICLService
        from test_audit_146_g2_tabicl import (
            FakeLedger,
            FakeQ,
            FakeWorkerCalls,
            ledger_row,
            sh_cd,
        )

        real = QuantLedger(Path(self.td.dir) / "quant" / "ledger.sqlite")

        class Ledger(FakeLedger):
            def add_confidence(self, r):
                real.add_confidence(r)
        D = time.time() - 7200
        spec = EV.spec_from_candidate(sh_cd(D))
        rows = [ledger_row(i, spec, D - 9000 + i, D - 5000 + i, i % 2) for i in range(30)]
        tb = TabICLService(FakeQ(ledger=Ledger(rows)))
        fake = FakeWorkerCalls()
        tb.worker.call = fake
        tb.submit(sh_cd(D), spec, {"a": 1.0}, 1)
        with mock.patch.object(QT, "find_python", lambda: "/stub/python"):
            tb._score(tb.jobs.get_nowait())
        r = tb.results[spec.plan_hash()]
        self.assertEqual(r["state"], "READY", r)
        got = real.confidences()
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["plan_hash"], spec.plan_hash())
        self.assertEqual(got[0]["p_event_raw"], 0.5)
        self.assertEqual((got[0]["task_hash"], got[0]["strategy"], got[0]["calibration_status"]), (spec.task_hash(), "PMW_SC01", "UNCALIBRATED"))
        self.assertEqual(got[0]["context_id"], r["context_id"])
        self.assertEqual(got[0]["context_n"], 30)

    def test_write_failure_never_changes_the_result(self):
        import time

        from masterquo.quant import events as EV
        from masterquo.quant import tabicl as QT
        from masterquo.quant.tabicl import TabICLService
        from test_audit_146_g2_tabicl import (
            FakeLedger,
            FakeQ,
            FakeWorkerCalls,
            ledger_row,
            sh_cd,
        )

        class Broken(FakeLedger):
            def add_confidence(self, r):
                raise OSError("disk full")
        D = time.time() - 7200
        spec = EV.spec_from_candidate(sh_cd(D))
        tb = TabICLService(FakeQ(ledger=Broken([ledger_row(i, spec, D - 9000 + i, D - 5000 + i, i % 2) for i in range(30)])))
        tb.worker.call = FakeWorkerCalls()
        tb.submit(sh_cd(D), spec, {"a": 1.0}, 1)
        with mock.patch.object(QT, "find_python", lambda: "/stub/python"):
            tb._score(tb.jobs.get_nowait())
        self.assertEqual(tb.results[spec.plan_hash()]["state"], "READY")

    def test_table_is_additive_and_replaces_per_plan(self):
        import sqlite3
        from pathlib import Path

        from masterquo.quant.ledger import QuantLedger
        p = Path(self.td.dir) / "old.sqlite"
        con = sqlite3.connect(p)                                    # a ledger file from before: rows + assessments only
        con.executescript("CREATE TABLE rows(row_id TEXT PRIMARY KEY, instrument TEXT, engine TEXT, strategy TEXT, direction TEXT, "
                          "decision_ts REAL, task_hash TEXT, event_id TEXT, spec_json TEXT, features_json TEXT, snapshot_id TEXT, "
                          "generation INTEGER, data_kind TEXT, matures_at REAL, status TEXT, label_json TEXT, resolve_ts REAL, y INTEGER, "
                          "net_r REAL, created_at REAL); INSERT INTO rows(row_id) VALUES ('keep');")
        con.commit()
        con.close()
        led = QuantLedger(p)
        led.add_confidence({"plan_hash": "P", "p_event_raw": 0.4, "instrument": "XAUUSD", "computed_at": 1.0})
        led.add_confidence({"plan_hash": "P", "p_event_raw": 0.6, "instrument": "XAUUSD", "computed_at": 2.0})
        self.assertEqual([(r["plan_hash"], r["p_event_raw"]) for r in led.confidences(instrument="XAUUSD")], [("P", 0.6)])
        with led._lock:
            self.assertEqual(led.c.execute("SELECT row_id FROM rows").fetchall()[0][0], "keep")


# ================================================================================================ P004 one weights folder
class TestTabICLWeightsFolderP004(unittest.TestCase):
    """quant/tabicl.weights_root was always <data>/tsfm/models, the installer (tools/tsfm_setup.py --weights-root auto) used weights_root
    from <data>/tsfm/settings.json - with a user weights folder TabICL was installed where the bot never looked."""

    def setUp(self):
        self.td = TempData()
        self.addCleanup(self.td.close)

    def _installer_root(self):
        import sys
        tools = str(_env.ROOT / "tools")
        if tools not in sys.path:
            sys.path.insert(0, tools)
        import tsfm_setup as TS
        return TS.default_weights_root(_env.ROOT)

    def test_custom_folder_is_the_same_for_bot_and_installer(self):
        from pathlib import Path

        from masterquo.quant import tabicl as T
        from masterquo.tsfm.settings import tsfm_dir
        custom = Path(self.td.dir) / "my_weights"
        (tsfm_dir() / "settings.json").write_text(json.dumps({"weights_root": str(custom)}), encoding="utf-8")
        self.assertEqual(T.weights_root(), custom)
        self.assertEqual(self._installer_root(), custom)

    def test_default_folder_unchanged(self):
        from masterquo.quant import tabicl as T
        from masterquo.tsfm.settings import tsfm_dir
        self.assertEqual(T.weights_root(), tsfm_dir() / "models")
        self.assertEqual(self._installer_root().resolve(), (tsfm_dir() / "models").resolve())
        for bad in ("[1, 2]", "{not json", json.dumps({"weights_root": None}), json.dumps({"weights_root": ""})):
            (tsfm_dir() / "settings.json").write_text(bad, encoding="utf-8")
            self.assertEqual(T.weights_root(), tsfm_dir() / "models", bad)


# ================================================================================================ I0543 Event GRU READY path
class _M1Bridge:
    """Closed M1 bars (BAR_CLOSE_EVENTS source of the Event GRU adapter) + the broker point; no terminal."""
    synthetic = False
    symbol_info: ClassVar[dict] = {"point": 0.01}

    def __init__(self, n=140, t0=1_794_000_000.0, seed=11):
        import numpy as np
        from test_quant_core import iso
        rng = np.random.default_rng(seed)
        c, self.rows = 2000.0, []
        for i in range(n):
            o = c
            c = o + float(rng.normal(0, 0.4))
            self.rows.append({"open_utc": iso(t0 + 60 * i), "o": o, "h": max(o, c) + 0.1, "l": min(o, c) - 0.1, "c": c, "tv": 10 + i % 7,
                              "spread": 20 + i % 3, "closed": True})

    def bars(self, tf, include_forming=False):
        return list(self.rows) if tf == "M1" else []


class TestEventGruReadyPath(unittest.TestCase):
    """The READY path of quant.adapters.EventGRU (artifact -> MM SHADOW pointer -> closed M1 events -> units -> GRU + stack -> softmax) had
    no test in the repository (only modelhub/smoke/mm.py). Technical artifact with fixed random weights in a temporary data folder."""

    def setUp(self):
        self.td = TempData()
        self.addCleanup(self.td.close)

    def _promote(self):
        import numpy as np
        from masterquo.mm import artifacts as MA
        from masterquo.mm import event_engine as EE
        from masterquo.mm import events as EV
        m = EE.EventModel(len(EV.FEATURES), H=8, S=4, seed=5)
        nf = len(EV.FEATURES)
        st = {**m.state(), "scaler_med": np.zeros(nf), "scaler_iqr": np.ones(nf), "band": np.array([1e-4])}
        aid = MA.save("XAUUSD", "event_engine_dir3", st, {"status": "VALIDATED_SHADOW", "model_type": "EVENT_GRU_STACK",
                                                           "feature_schema": "PMW-MM-EVENT-1:" + ",".join(EV.FEATURES),
                                                           "event_source": "BAR_CLOSE_EVENTS", "note": "TEST: artefakt techniczny",
                                                           # merge with group mm (I0545): promote_shadow needs passed gates on REAL_USER_DATA
                                                           "gates": {"walk_forward": True}, "data_kind": "REAL_USER_DATA"})
        MA.promote_shadow("XAUUSD", "event_engine_dir3", aid, "test")
        return aid

    def test_not_trained_then_ready_with_a_promoted_artifact(self):
        from types import SimpleNamespace

        from masterquo.mm import data as D
        from masterquo.mm import events as EV
        from masterquo.mm.service import _to_bars
        from masterquo.modelhub import contract as C
        from masterquo.quant import adapters as QA
        from masterquo.quant import checks as CK
        br = _M1Bridge()
        rt = SimpleNamespace(bridge=br)
        self.assertEqual(QA.EventGRU().predict(rt, "XAUUSD")["state"], "NOT_TRAINED")
        aid = self._promote()
        p = QA.EventGRU().predict(rt, "XAUUSD")
        self.assertEqual(p["state"], "READY", p.get("unavailable_reason"))
        res = p["result"]
        self.assertEqual(set(res), {"DOWN", "FLAT", "UP"})
        self.assertLess(abs(sum(res.values()) - 1.0), 1e-6)
        self.assertEqual(p["model_version"], aid)
        self.assertEqual(p["data_kind"], "REAL")
        self.assertEqual(p["source"], "BAR_CLOSE_EVENTS")
        acc = EV.from_arrays(D.events_from_bars(_to_bars(br.rows, "M1"), 0.01), "XAUUSD", 900)
        u = EV.units(acc, EV.featurize(acc), 16)
        self.assertEqual(CK.ts(p["data_time"]), float(u["t_end"][-1]))   # data_time = end of the last full unit of 16 events
        self.assertLessEqual(CK.ts(p["data_time"]), CK.ts(br.rows[-1]["open_utc"]) + 60)
        C.validate(p)                                                   # a valid PMW-PRED record

    def test_too_few_bars_is_blocked_data(self):
        from types import SimpleNamespace

        from masterquo.quant import adapters as QA
        self._promote()
        p = QA.EventGRU().predict(SimpleNamespace(bridge=_M1Bridge(n=30)), "XAUUSD")
        self.assertEqual(p["state"], "BLOCKED_DATA")


# ================================================================================================ I0548 / I0549 / I0550 NO_SPEC rows
class TestNoSpecRows(unittest.TestCase):
    """The NO_SPEC rows were checked only for mm:sdom / mm:quant_momentum / mm:renko; mm:head_shoulders, mm:data_grabber, mm:chart_sync
    and extind:PAL02M were not. The list now comes from the source registries (mm/inventory.MODULES without a spec, quant.ids
    EXTRA_PRODUCERS of category NO_SPEC): every such row is code_state NO_SPEC, runtime UNAVAILABLE, no adapter, models check NO_SPEC."""

    def setUp(self):
        self.td = TempData()
        self.addCleanup(self.td.close)

    def _nospec_ids(self):
        from masterquo.mm import inventory as MI
        from masterquo.quant import ids as I
        # merge with quant_inventory (I0009): the MM -> canonical alias table is quant/ids (I.resolve), no private copy in inventory
        mm = [f"mm:{m['id']}" for m in MI.MODULES if not m.get("spec") and not I.resolve(m["id"])]
        return mm + [cid for cid, v in I.EXTRA_PRODUCERS.items() if v[1] == "NO_SPEC"]

    def test_every_registry_no_spec_row(self):
        from masterquo.modelhub import check as MC
        from masterquo.quant import inventory as QI
        ids = self._nospec_ids()
        for must in ("mm:sdom", "mm:quant_momentum", "mm:renko", "mm:head_shoulders", "mm:data_grabber", "mm:chart_sync", "extind:PAL02M"):
            self.assertIn(must, ids)
        by = {e["id"]: e for e in QI.build(None, "XAUUSD")["entries"]}
        for cid in ids:
            self.assertEqual(by[cid]["code_state"], "NO_SPEC", cid)
            self.assertEqual(by[cid]["runtime_state"], "UNAVAILABLE", cid)
            self.assertFalse(by[cid].get("adapter"), cid)                            # never implemented by guessing from the name
        prod = {p["id"]: p for p in MC.producers()}
        for cid in ids:
            self.assertEqual(prod[cid]["code_state"], "NO_SPEC", cid)


# ================================================================================================ I0053 / I0115 dead cost models
def _production_trees():
    """(relative path, AST) of every module of backend/masterquo - parsed only, nothing imported (tests excluded by construction)."""
    import ast
    root = _env.ROOT / "backend" / "masterquo"
    for p in sorted(root.rglob("*.py")):
        yield p.relative_to(root), ast.parse(p.read_text(encoding="utf-8"))


def _absolute(rel, level: int, module: str | None) -> str:
    pkg = ["masterquo", *rel.parent.parts]
    base = pkg[:len(pkg) - (level - 1)] if level else []
    return ".".join([*base, *([module] if module else [])])


class TestQuantUnitsProductionApi(unittest.TestCase):
    """quant/units: production used only binary_ev (CostModel, InstrumentSpec, ev_for_plan ... tests only) and three instrument
    specifications coexisted. The module now names its production API and the AST scan of backend/masterquo keeps it honest; the unused
    PMW-ARC-1 schemas are named in decision/contracts.UNUSED_IN_PRODUCTION (a separate constant - SCHEMAS / make / validate unchanged)."""

    def test_only_the_production_api_of_quant_units_is_used(self):
        import ast
        from pathlib import Path

        from masterquo.quant import units as U
        used: set[str] = set()
        for rel, tree in _production_trees():
            if rel == Path("quant/units.py"):
                continue
            aliases = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    target = _absolute(rel, node.level, node.module)
                    if target == "masterquo.quant.units":
                        used |= {a.name for a in node.names}
                    elif target == "masterquo.quant":
                        aliases |= {a.asname or a.name for a in node.names if a.name == "units"}
                elif isinstance(node, ast.Import):
                    aliases |= {a.asname or a.name for a in node.names if a.name == "masterquo.quant.units"}
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in aliases:
                    used.add(node.attr)
        self.assertEqual(U.PRODUCTION_API, ("binary_ev",))
        self.assertIn("binary_ev", used)                                    # the scan sees quant/service.py
        self.assertLessEqual(used, set(U.PRODUCTION_API), used - set(U.PRODUCTION_API))

    def test_unused_arc1_schemas_are_not_created_in_production(self):
        import ast
        from pathlib import Path

        from masterquo.decision import contracts as K
        self.assertEqual(K.UNUSED_IN_PRODUCTION, ("InstrumentSpec", "ObservationEvent", "MarketSnapshot", "FeatureSet", "MarketContext",
                                                  "instrument_spec"))
        self.assertNotIn("UNUSED_IN_PRODUCTION", K.SCHEMAS)
        for name in K.UNUSED_IN_PRODUCTION[:-1]:
            self.assertIn(name, K.SCHEMAS)                                  # still valid contracts (tests use them)
        made, calls = set(), set()
        for rel, tree in _production_trees():
            if rel == Path("decision/contracts.py"):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                fn = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id if isinstance(node.func, ast.Name) else None
                if fn in ("make", "validate") and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    made.add(node.args[0].value)
                if fn == "instrument_spec":
                    calls.add(str(rel))
        self.assertFalse(made & set(K.UNUSED_IN_PRODUCTION), made & set(K.UNUSED_IN_PRODUCTION))
        self.assertIn("DecisionRecord", made)                                # the scan sees the coordinator
        self.assertEqual(calls, set())


# ================================================================================================ I0054 shared calibration metrics
# outputs of the metric / bootstrap variants on fixed arrays, computed by the code BEFORE the I0054 change (base 2dce8bf) - bit-for-bit
METRIC_SNAPSHOT = json.loads('{"mc_logloss": 0.5166767763410296, "num_log_loss": 0.5166755262722847, "th_logloss": 1.6256240352250673, "th_ece": {"ece": 0.29319, "bins": [{"from": 0.333, "to": 0.4, "n": 6, "confidence": 0.3751, "accuracy": 0.5}, {"from": 0.4, "to": 0.467, "n": 13, "confidence": 0.4375, "accuracy": 0.3077}, {"from": 0.467, "to": 0.533, "n": 32, "confidence": 0.4997, "accuracy": 0.25}, {"from": 0.533, "to": 0.6, "n": 30, "confidence": 0.5646, "accuracy": 0.2667}, {"from": 0.6, "to": 0.667, "n": 20, "confidence": 0.6371, "accuracy": 0.35}, {"from": 0.667, "to": 0.733, "n": 13, "confidence": 0.6911, "accuracy": 0.3846}, {"from": 0.733, "to": 0.8, "n": 16, "confidence": 0.7578, "accuracy": 0.3125}, {"from": 0.8, "to": 0.867, "n": 8, "confidence": 0.8345, "accuracy": 0.5}, {"from": 0.867, "to": 0.933, "n": 6, "confidence": 0.8852, "accuracy": 0.8333}, {"from": 0.933, "to": 1.0, "n": 6, "confidence": 0.9623, "accuracy": 0.1667}]}, "ml_block_bootstrap": {"mean": 0.1456, "ci95": [0.0252, 0.3195], "block": 10, "reps": 1000}, "num_block_bootstrap": {"estimate": 0.14555687677255386, "lo": 0.0010813369195748694, "hi": 0.3562873050066074, "level": 0.9, "block": 4, "n_boot": 300, "seed": 7, "n": 60, "method": "moving block bootstrap (percentyle)"}, "lab_edge": {"status": "ready", "n": 60, "block": 4, "mean": 0.14555687677255386, "ci95": [-0.04751707415349779, 0.3569385666274183], "p_mean_le_0": 0.07333333333333333, "verdict": "NO_VALIDATED_EDGE", "seed": 7, "n_boot": 300, "note": "bootstrap blokowy \\u2013 transakcje zale\\u017cne nie s\\u0105 liczone jako niezale\\u017cne"}, "bt_block_bootstrap": {"n": 60, "block": 4, "expectancy_r_90": [-0.0309, 0.3209], "winrate_90": [40.0, 59.322], "pf_90": [0.9205, 2.3142], "p_expectancy_le_0": 0.1}, "sfb_lcb": 0.029110750237050495}')


def _metric_data():
    import numpy as np
    rng = np.random.default_rng(20261124)
    p = rng.uniform(0, 1, 200)
    p[:3] = [0.0, 1.0, 0.99995]
    y = (rng.uniform(0, 1, 200) < p).astype(float)
    P = rng.dirichlet([1.0, 1.0, 1.0], 150)
    P[0] = [1.0, 0.0, 0.0]
    yc = rng.integers(0, 3, 150)
    yc[0] = 2
    r = [float(x) for x in rng.normal(0.05, 1.0, 60)]
    return p, y, P, yc, r


class TestMetricDelegation(unittest.TestCase):
    """Calibration metrics were duplicated with other constants (quant/numeric vs montecarlo vs trainhub). The Monte Carlo and Training
    Center log loss / ECE now live in quant/numeric with each consumer's exact convention; every variant (incl. the bootstraps that stay
    separate - quant/numeric.METRIC_VARIANTS says why) gives exactly the numbers it gave before."""

    def test_shared_functions_exist_and_consumers_delegate(self):
        from masterquo.montecarlo import validate as mcv
        from masterquo.quant import numeric as N
        from masterquo.trainhub import learn as L
        p, y, P, yc, _ = _metric_data()
        self.assertEqual(mcv.logloss(p, y), N.log_loss_clipped(p, y, 1e-4))
        self.assertEqual(L.logloss(P, yc), N.log_loss_multiclass(P, yc))
        self.assertEqual(L.ece(P, yc), N.ece_confidence(P, yc))
        for k in ("log_loss", "ece", "block_bootstrap"):
            self.assertIn(k, N.METRIC_VARIANTS)

    def test_numbers_are_bit_for_bit_as_before(self):
        from masterquo.baskets import sfb
        from masterquo.lab import edge
        from masterquo.ml import validation as mv
        from masterquo.montecarlo import validate as mcv
        from masterquo.quant import numeric as N
        from masterquo.strategies import ema_pullback_backtest as bt
        from masterquo.trainhub import learn as L
        p, y, P, yc, r = _metric_data()
        got = {"mc_logloss": mcv.logloss(p, y), "num_log_loss": N.log_loss(p, y), "th_logloss": L.logloss(P, yc), "th_ece": L.ece(P, yc),
               "ml_block_bootstrap": mv.block_bootstrap(r), "num_block_bootstrap": N.block_bootstrap(r, n_boot=300),
               "lab_edge": edge.block_bootstrap_mean(r, n_boot=300), "bt_block_bootstrap": bt.block_bootstrap(r, n_boot=300),
               "sfb_lcb": sfb._block_bootstrap_lcb(r, 5, 300, 0.9)}
        self.assertEqual(json.loads(json.dumps(got, default=float)), METRIC_SNAPSHOT)


if __name__ == "__main__":
    unittest.main()
