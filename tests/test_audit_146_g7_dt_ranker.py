"""1.46 audit (group G7_dt_ranker) - regression tests for backend/masterquo/ml/dt_ranker.py.

Unit level only (no HTTP server, no network). Rank logic is exercised with a fake bundle (fixed predictions per candidate) or with a
RankerBundle wrapped around fake CART heads, so no training is needed except for the small train() exclusion test."""
from __future__ import annotations

import math
import random
import unittest

import _env  # noqa: F401  (sys.path)
import numpy as np

TS = 1_800_000_000


def _cand(cid="a", direction="LONG", group="g1", **kw):
    from masterquo.ml.dt_ranker import Candidate
    plan = {"LONG": (100.0, 99.0, 102.0), "SHORT": (100.0, 101.0, 98.0)}[direction]
    base = {"setup_score": 0.5, "spread": 0.05, "commission_R": 0.02, "slippage_R": 0.01, "funding_R": 0.0, "atr": 2.0}
    return Candidate(cid, "S1", "BASKET", "FOREX", "XAUUSD", "M15", direction, TS, TS, group, *plan, **{**base, **kw})


def _payload(**kw):
    d = {"candidate_id": "p1", "strategy_id": "S1", "source": "BASKET", "market": "CRYPTO", "instrument": "BTCUSDT", "timeframe": "M15",
         "direction": "LONG", "decision_ts": TS, "feature_as_of": TS, "event_group_id": "g1", "entry": 100.0, "stop": 99.0, "target": 102.0,
         "commission_R": 0.02}
    d.update(kw)
    return {k: v for k, v in d.items() if v is not _DROP}


_DROP = object()


class _FakeBundle:
    """predict() returns fixed values per candidate id (all eligible unless the candidate itself fails validate())."""

    def __init__(self, exp: dict[str, float]):
        self.exp = exp

    def predict(self, c, z=None):
        e = self.exp[c.candidate_id]
        return {"expected_net_R": e, "p_positive_net_R": None, "probability_status": "UNCALIBRATED", "leaf_id": 1, "leaf_support_events": 100,
                "leaf_net_r": {"events": 100, "mean": e, "std": 0.0}, "uncertainty_R": 0.0, "conservative_net_R": e}


class _Reg:
    def apply(self, x):
        return np.array([7])

    def predict(self, x):
        return np.array([1.0])


class _Clf:
    classes_ = np.array([False, True])

    def predict_proba(self, x):
        return np.array([[0.4, 0.6]])


def _samples(n_events=100, seed=3, **cost):
    from masterquo.ml.dt_ranker import Candidate
    rnd = random.Random(seed)
    out = []
    for e in range(n_events):
        ts = 1_700_000_000 + e * 3600
        for k in range(3):
            rr = rnd.choice([1.0, 2.0, 3.0])
            c = Candidate(f"c{e}-{k}", f"S{k}", "BASKET", "CRYPTO", "BTCUSDT", "M15", "LONG", ts, ts, f"g{e}", 100.0, 99.0, 100.0 + rr,
                          setup_score=rnd.random(), spread=0.05, commission_R=0.02, atr=2.0, **cost)
            net = (rr if rnd.random() < 0.4 else -1.0) - 0.1           # label supplied by the caller (e.g. an external ledger)
            out.append({"candidate": c, "net_R": net, "decision_ts": ts, "label_end_ts": ts + 1800, "event_group_id": f"g{e}"})
    return out


class TestUnknownCostsNeverZero(unittest.TestCase):
    """focus_X2#7: unknown spread / slippage / funding / setup_score must not be treated as 0.0."""

    def test_api_payload_without_costs_is_cost_unknown(self):
        from masterquo.ml import dt_ranker as DT
        c = DT.candidate_from_dict(_payload())
        self.assertIsNone(c.spread)
        self.assertIsNone(c.slippage_R)
        self.assertIsNone(c.funding_R)
        self.assertIsNone(c.setup_score)
        bad = c.validate()
        self.assertIn("COST_UNKNOWN", bad)
        self.assertIn("SETUP_SCORE_MISSING", bad)
        full = DT.candidate_from_dict(_payload(spread=0.05, slippage_R=0.01, funding_R=0.003, setup_score=0.7))
        self.assertEqual(full.validate(), [])
        self.assertEqual(full.funding_R, 0.003)
        # with a model loaded the incomplete candidate is ineligible (not ranked as a zero-cost plan)
        r = DT.rank(_FakeBundle({"p1": 1.0}), [c], {"min_conservative_net_r": -99})
        self.assertFalse(r["ranked_candidates"][0]["eligible"])
        self.assertIn("COST_UNKNOWN", r["ranked_candidates"][0]["reason_codes"])
        self.assertNotIn("rank_utility", r["ranked_candidates"][0])

    def test_explicit_none_cost_component_is_cost_unknown_in_validate_and_label(self):
        from masterquo.ml.dt_ranker import net_r_label
        for k in ("slippage_R", "funding_R", "spread"):
            c = _cand(**{k: None})
            self.assertIn("COST_UNKNOWN", c.validate(), k)
            lab = net_r_label(c, 102.0)
            self.assertEqual(lab["label_status"], "COST_UNKNOWN", k)
            self.assertIsNone(lab["net_R"], k)
        nan = _cand(funding_R=float("nan"))
        self.assertIn("COST_UNKNOWN", nan.validate())
        self.assertEqual(_cand(spread=np.float32(0.05), slippage_R=np.int64(0), setup_score=np.float64(0.3)).validate(), [])   # numpy scalars are known
        ok = net_r_label(_cand(), 102.0)
        self.assertEqual(ok["label_status"], "LABELED")
        self.assertAlmostEqual(ok["net_R"], 2.0 - 0.05 - 0.02 - 0.01 - 0.0)
        self.assertEqual(ok["funding_or_borrow_R"], 0.0)

    def test_features_mark_unknown_cost_and_score_as_nan_not_zero(self):
        from masterquo.ml.dt_ranker import FEATURE_NAMES, features
        f = features(_cand(slippage_R=None))
        self.assertTrue(math.isnan(f[FEATURE_NAMES.index("cost_R")]))
        g = features(_cand(setup_score=None))
        self.assertTrue(math.isnan(g[FEATURE_NAMES.index("setup_score")]))
        h = features(_cand())
        self.assertAlmostEqual(h[FEATURE_NAMES.index("cost_R")], 0.05 + 0.02 + 0.01 + 0.0)
        self.assertIn("SETUP_SCORE_MISSING", _cand(setup_score=None).validate())

    def test_train_excludes_rows_with_unknown_costs(self):
        from masterquo.ml import dt_ranker as DT
        res = DT.train(_samples(funding_R=None), {"min_leaf_events": 20})
        self.assertEqual(res["status"], "NOT_READY")
        self.assertEqual(res["excluded_missing_inputs"], 300)
        ok = DT.train(_samples(funding_R=0.0, slippage_R=0.01), {"min_leaf_events": 20})
        self.assertEqual(ok["status"], "READY")
        self.assertEqual(ok["manifest"]["excluded_missing_inputs"], 0)


class TestCandidateFromDictTypes(unittest.TestCase):
    """chunk_19#13: malformed payloads raise CandidateError (400), never a raw TypeError later in rank()."""

    def test_non_object_and_bad_field_types(self):
        from masterquo.ml import dt_ranker as DT
        for bad in (5, None, 1.5, "x", ["a"]):
            with self.assertRaises(DT.CandidateError, msg=repr(bad)):
                DT.candidate_from_dict(bad)
        cases = [{"decision_ts": "abc"}, {"feature_as_of": None}, {"entry": "100"}, {"stop": True}, {"spread": "0.1"},
                 {"commission_R": [0.1]}, {"decision_ts": float("nan")}, {"expires_at": float("inf")}, {"candidate_id": 7},
                 {"timeframe": 15}, {"event_group_id": ["g"]}, {"trade_allowed": "false"}, {"extra": "x"}, {"atr": float("nan")}]
        for kw in cases:
            with self.assertRaises(DT.CandidateError, msg=repr(kw)):
                DT.candidate_from_dict(_payload(**kw))
        with self.assertRaises(DT.CandidateError):
            DT.candidate_from_dict(_payload(entry=_DROP))                  # missing required field
        with self.assertRaises(DT.CandidateError):
            DT.candidate_from_dict(_payload(foo=1))                        # unknown field

    def test_valid_payloads_still_parse(self):
        from masterquo.ml import dt_ranker as DT
        c = DT.candidate_from_dict(_payload(decision_ts=TS, entry=100, stop=99, target=103, spread=0, slippage_R=0, funding_R=0,
                                            setup_score=1, expires_at=None, atr=None, trade_allowed=False, extra={"k": 1}))
        self.assertEqual(c.validate(), ["TRADE_NOT_ALLOWED"])
        # a non-finite plan is still accepted by the parser and reported by validate() as before
        self.assertIn("NON_FINITE_PLAN", DT.candidate_from_dict(_payload(entry=float("nan"))).validate())
        r = DT.rank(_FakeBundle({"p1": 1.0}), [c], {"min_conservative_net_r": -99})
        self.assertEqual(r["decision"], "NO_TRADE")


class TestPredictUsesPolicyZ(unittest.TestCase):
    """chunk_19#15: conservative_net_R must use the policy z, not always DEFAULT_POLICY['z']."""

    def test_z_from_policy(self):
        from masterquo.ml import dt_ranker as DT
        b = DT.RankerBundle(_Reg(), _Clf(), None, {7: {"events": 100, "rows": 100, "mean": 1.0, "std": 2.0}}, {})
        c = _cand()
        self.assertAlmostEqual(b.predict(c)["conservative_net_R"], 1.0 - DT.DEFAULT_POLICY["z"] * 0.2)
        self.assertAlmostEqual(b.predict(c, z=6.0)["conservative_net_R"], 1.0 - 6.0 * 0.2)
        self.assertEqual(DT.rank(b, [c], {"min_leaf_events": 30})["decision"], "SELECT")
        r = DT.rank(b, [c], {"min_leaf_events": 30, "z": 6.0})
        self.assertEqual(r["decision"], "ABSTAIN")
        self.assertIn("CONSERVATIVE_NET_R_BELOW_MIN", r["ranked_candidates"][0]["reason_codes"])


class TestRankOrderingAndAbstain(unittest.TestCase):
    """chunk_19#16: rank_utility 0.0 is a value (not 'missing'); ineligible candidates do not cause SAME_EVENT_OPPOSING_CANDIDATES."""

    def test_zero_utility_sorts_above_negative(self):
        from masterquo.ml import dt_ranker as DT
        cands = [_cand("a"), _cand("b"), _cand("c", status="WATCH")]
        r = DT.rank(_FakeBundle({"a": 0.0, "b": -5.0, "c": 9.0}), cands, {"min_conservative_net_r": -99})
        self.assertEqual([x["candidate_id"] for x in r["ranked_candidates"]], ["a", "b", "c"])
        self.assertEqual(r["selected_candidate_id"], "a")

    def test_ineligible_opposite_candidate_does_not_force_abstain(self):
        from masterquo.ml import dt_ranker as DT
        pol = {"min_conservative_net_r": -99}
        a, b = _cand("a", "LONG", "g1"), _cand("b", "SHORT", "g2")
        expired = _cand("x", "SHORT", "g1", expires_at=TS - 10)
        r = DT.rank(_FakeBundle({"a": 1.0, "b": 0.5, "x": 3.0}), [a, b, expired], pol)
        self.assertEqual(r["decision"], "SELECT")
        self.assertEqual(r["selected_candidate_id"], "a")
        # two ELIGIBLE opposite candidates in one event group still abstain
        b1 = _cand("b", "SHORT", "g1")
        self.assertEqual(DT.rank(_FakeBundle({"a": 1.0, "b": 0.5}), [a, b1], pol)["decision"], "ABSTAIN")


if __name__ == "__main__":
    unittest.main()
