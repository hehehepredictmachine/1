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


if __name__ == "__main__":
    unittest.main()
