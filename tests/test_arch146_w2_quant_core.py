"""1.46 arch fix wave 2b, group "quant_core": quant/checks (data_time basis), features (FEAT-4 regime vocabulary), metamodel (missing
features never missing in training), TabICL (strategy encoding, persisted confidences, weights folder), Event GRU READY path, NO_SPEC rows,
quant/units production API, shared calibration metrics.

Isolated MASTERQUO_DATA_DIR, stub runtimes, SYNTHETIC data - no terminal, no orders, no HTTP server."""
from __future__ import annotations

import json
import unittest
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


if __name__ == "__main__":
    unittest.main()
