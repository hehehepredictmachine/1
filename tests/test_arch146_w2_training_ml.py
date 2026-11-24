"""Fala 2 / grupa training_ml (Apollo23 1.46): I0342 (reguły asocjacyjne walidowane na holdoucie), I0667 (TH_RF bez class_weight),
I0674 (TH_SVM: fallback na Prior widoczny, paczka nie zapisana), I0024 (manifest stref / sesji w bundlu ML), I0731 (epizody zdarzeń
w walidacji ML), I0788 (fold walk-forward z jedną klasą), I0050 (poślizg TH na round trip), I0063 (atomowa blokada treningu, blokada
eksportu), I0070 (limit czasu w Centrum Pepe = anulowanie), I0074 (dostępność .venv_candles jak w runnerze).
Każdy test nie przechodzi na kodzie sprzed poprawki. Dane SYNTETYCZNE - sprawdzają reguły, nie wartość predykcyjną."""
from __future__ import annotations

import random
import unittest

import _env  # noqa: F401


def _walk(seed: int, n: int = 3000) -> list[dict]:
    rnd = random.Random(seed)
    c, bars = 2000.0, []
    for i in range(n):
        o = c
        c = c + rnd.gauss(0, 1.0)
        bars.append({"o": o, "h": max(o, c) + 0.3, "l": min(o, c) - 0.3, "c": c, "hour": i % 24})
    return bars


# ============================================================================= I0342 association rules
class TestAssociationRulesValidity(unittest.TestCase):
    def test_no_supported_on_random_walk(self):
        """Random walk, labels 24 bars ahead (as the route): no SUPPORTED / CONTRARY_EDGE on the last 200 bars (before: seed 0 -> 72)."""
        from masterquo.ml import association_rules as AR
        for seed in (0, 1, 2):
            bars = _walk(seed)
            masks = AR.event_bits(bars)
            m = AR.train(masks, AR.labels([b["c"] for b in bars], 24, 0.0), horizon=24)
            res = [AR.assess(m, mk, d)["reason"] for mk in masks[-200:] for d in ("LONG", "SHORT") if mk is not None]
            self.assertEqual(res.count("SUPPORTED") + res.count("CONTRARY_EDGE"), 0, f"seed {seed}: {sorted(set(res))}")
            self.assertEqual(m["validation"], AR.VALIDATION)
            self.assertEqual(m["validated_rules"], 0)
            if seed == 0:                                   # the in-sample edge is still visible - as IN_SAMPLE_ONLY, not SUPPORTED
                self.assertIn("IN_SAMPLE_ONLY", res)

    def test_injected_dependence_still_supported(self):
        """Control: MOM_UP -> UP with p = 0.7 (else 0.5), independent labels: the rule is validated and LONG is SUPPORTED."""
        from masterquo.ml import association_rules as AR
        mom = 1 << AR.CATALOG.index("MOM_UP")
        for seed in (0, 1, 2):
            bars = _walk(seed)
            masks = AR.event_bits(bars)
            rnd = random.Random(100 + seed)
            labs = [None if mk is None else ("UP" if rnd.random() < (0.7 if mk & mom else 0.5) else "DOWN") for mk in masks]
            m = AR.train(masks, labs, horizon=1)
            mk = next(x for x in reversed(masks) if x is not None and x & mom)
            a = AR.assess(m, mk, "LONG")
            self.assertEqual((a["reason"], a["candidate_direction_supported"]), ("SUPPORTED", True), seed)
            self.assertGreaterEqual(a["validated_rules_for"], 1)
            self.assertEqual(AR.assess(m, mk, "SHORT")["reason"], "CONTRARY_EDGE")
            r = next(r for r in m["rules"] if r["events"] == ["MOM_UP"])
            for k in ("p_adj", "n_eff_holdout", "holdout_edge_up", "fit_edge_up", "validated_direction"):
                self.assertIn(k, r)

    def test_holdout_is_purged_and_bonferroni_counts_every_rule(self):
        from masterquo.ml import association_rules as AR
        bars = _walk(4)
        masks = AR.event_bits(bars)
        labs = AR.labels([b["c"] for b in bars], 24, 0.0)
        m = AR.train(masks, labs, horizon=24)
        vp = m["validation_params"]
        self.assertEqual(vp["tests_bonferroni"], 2 * len(m["rules"]))
        self.assertEqual(vp["purge_bars"], 24)
        idx = [i for i, (mk, y) in enumerate(zip(masks, labs)) if mk is not None and y in ("UP", "DOWN")]
        n_fit = sum(1 for i in idx if i + 24 <= vp["holdout_start_index"])
        self.assertEqual(vp["n_fit"], n_fit)
        self.assertEqual(vp["n_fit"] + vp["n_holdout"] + sum(1 for i in idx if vp["holdout_start_index"] - 24 < i < vp["holdout_start_index"]),
                         m["n_labeled"])
        self.assertAlmostEqual(vp["n_eff_holdout"], vp["n_holdout"] / 24)


if __name__ == "__main__":
    unittest.main()
