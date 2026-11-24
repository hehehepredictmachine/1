"""WF3.2 TASK 005 (Decision Tree Signal Ranker), TASK 006 + 016 (BAT encoder with BTC / SATMA), TASK 010 (association rules filter),
TASK 011 (Pesaran-Timmermann directional skill)."""
from __future__ import annotations

import math
import random
import unittest

import _env  # noqa: F401


class TestPT(unittest.TestCase):
    def test_article_formula_and_profiles_differ(self):
        from masterquo.evaluation import pt_skill as PT
        uu, ud, du, dd = 60, 40, 30, 70
        a = PT.pt_from_counts(uu, ud, du, dd, "ARTICLE_25105_V1")
        s = PT.pt_from_counts(uu, ud, du, dd, "STATSMODELS_REFERENCE_V1")
        n = 200
        P, Py, Px = (uu + dd) / n, (uu + du) / n, (uu + ud) / n
        Ps = Py * Px + (1 - Py) * (1 - Px)
        vp = Ps * (1 - Ps) / n
        vps = ((2 * Py - 1) ** 2 * Px * (1 - Px)) / n + ((2 * Px - 1) ** 2 * Py * (1 - Py)) / n + 4 * Py * Px * (1 - Py) * (1 - Px) / n ** 2
        self.assertAlmostEqual(a["pt"], (P - Ps) / math.sqrt(vp - vps), places=12)
        self.assertNotAlmostEqual(a["pt"], s["pt"], places=6)
        self.assertAlmostEqual(a["p_right"] + a["p_left"], 1.0, places=12)
        self.assertTrue(a["gate_open"])
        self.assertEqual(a["chi2"]["status"], "OK")

    def test_degenerate_cases_never_fake_values(self):
        from masterquo.evaluation import pt_skill as PT
        for args, st in (((5, 5, 5, 5), "INSUFFICIENT_N"), ((50, 50, 0, 0), "NO_FORECAST_VARIATION"), ((50, 0, 50, 0), "NO_OUTCOME_VARIATION")):
            r = PT.pt_from_counts(*args)
            self.assertEqual((r["status"], r["pt"], r["p_right"], r["gate_open"]), (st, None, None, False))

    def test_flats_zero_forecasts_and_maturity(self):
        from masterquo.evaluation import pt_skill as PT
        c = PT.counts([1, -1, 0, 1, 2], [1, 0, 1, -1, 3])
        self.assertEqual((c["uu"], c["ud"], c["zero_forecast_excluded"], c["flat_outcome_excluded"]), (2, 1, 1, 1))
        pairs = PT.matured_pairs([{"t": 1, "f": 1}, {"t": 2, "f": -1}], [{"t": 1, "c": 10}, {"t": 2, "c": 11}, {"t": 3, "c": 9, "final": False}])
        self.assertEqual(pairs, [(1, 1)])                                           # t=2 waits for the final close of t+1

    def test_skilled_forecast_is_significant_random_is_not(self):
        from masterquo.evaluation import pt_skill as PT
        rnd = random.Random(3)
        y = [rnd.choice([1, -1]) for _ in range(2000)]
        good = [v if rnd.random() < 0.6 else -v for v in y]
        noise = [rnd.choice([1, -1]) for _ in y]
        self.assertLess(PT.evaluate(good, y)["p_right"], 1e-6)
        self.assertGreater(PT.evaluate(noise, y)["p_right"], 0.001)


class TestAssociationRules(unittest.TestCase):
    def test_laplace_edge_lift_and_min_count(self):
        from masterquo.ml import association_rules as AR
        masks = [0b1] * 60 + [0b10] * 60 + [0b11] * 10
        labs = ["UP"] * 45 + ["DOWN"] * 15 + ["UP"] * 20 + ["DOWN"] * 40 + ["UP"] * 10
        m = AR.train(masks, labs, alpha=1.0, min_rule_count=50, max_rule_len=2)
        r1 = next(r for r in m["rules"] if r["mask"] == 0b1)
        self.assertEqual((r1["antecedent_count"], r1["up_count"]), (70, 55))
        self.assertAlmostEqual(r1["p_up"], 56 / 72)
        self.assertAlmostEqual(m["base_up"], (75 + 1) / (130 + 2))
        self.assertAlmostEqual(r1["edge_up"], 56 / 72 - 76 / 132)
        self.assertAlmostEqual(r1["lift_up"], (55 / 70) / (75 / 130))
        self.assertFalse(any(r["mask"] == 0b11 for r in m["rules"]))              # n=10 < min_rule_count

    def test_filter_never_creates_side_assist_only_holds(self):
        from masterquo.ml import association_rules as AR
        m = AR.train([0b1] * 100 + [0b10] * 100, ["DOWN"] * 80 + ["UP"] * 20 + ["UP"] * 80 + ["DOWN"] * 20, min_rule_count=50, max_rule_len=1)
        obs = AR.assess(m, 0b1, "LONG", mode="OBSERVE")
        self.assertEqual((obs["action"], obs["candidate_direction_supported"]), ("PASS", False))
        self.assertEqual(AR.assess(m, 0b1, "LONG", mode="ASSIST")["action"], "HOLD")
        self.assertEqual(AR.assess(m, 0b1, "SHORT", mode="ASSIST")["action"], "PASS")
        self.assertEqual(AR.assess(m, None, "LONG")["reason"], "NO_MODEL_OR_WARMUP")
        self.assertEqual(AR.assess(m, 0b100, "LONG")["reason"], "NO_MATCH")
        self.assertTrue(AR.assess(m, 0b10, "LONG")["candidate_direction_supported"])

    def test_event_bits_causal_and_labels_mature(self):
        from masterquo.ml import association_rules as AR
        bars = [{"o": 100 + i, "h": 101 + i, "l": 99 + i, "c": 100 + i + (i % 3), "hour": i % 24} for i in range(120)]
        a = AR.event_bits(bars)
        b = AR.event_bits(bars[:80] + [{"o": 1, "h": 1e6, "l": 0.5, "c": 1, "hour": 0}] * 40)
        self.assertEqual(a[:80], b[:80])
        self.assertIsNone(a[0])
        self.assertEqual(AR.labels([1, 2, 3], 2, 0)[1:], [None, None])


def make_sets(n_events=600, seed=5):
    """Synthetic candidate sets: hidden truth - high rr with low cost earns, setup_score is noise (baseline must not beat the ranker)."""
    from masterquo.ml.dt_ranker import Candidate, net_r_label
    rnd = random.Random(seed)
    out = []
    for e in range(n_events):
        ts = 1_700_000_000 + e * 3600
        for k in range(3):
            rr = rnd.choice([1.0, 2.0, 3.0])
            spread = rnd.choice([0.05, 0.6])
            c = Candidate(f"c{e}-{k}", f"S{k}", "BASKET", "FOREX", "XAUUSD", "M15", "LONG", ts, ts, f"g{e}", 100.0, 99.0, 100.0 + rr,
                          setup_score=rnd.random(), spread=spread, commission_R=0.02, atr=2.0)
            win = rnd.random() < (0.55 if (rr == 3.0 and spread < 0.1) else 0.25)
            ex = c.target if win else c.stop
            lab = net_r_label(c, ex)
            out.append({"candidate": c, "net_R": lab["net_R"], "decision_ts": ts, "label_end_ts": ts + 1800, "event_group_id": f"g{e}"})
    return out


class TestDecisionTreeRanker(unittest.TestCase):
    def test_candidate_validation_and_net_r_label(self):
        from masterquo.ml.dt_ranker import Candidate, net_r_label
        bad = Candidate("x", "S", "SH", "FOREX", "XAUUSD", "M5", "LONG", 100, 200, "g", 100, 101, 99, commission_R=None, status="WATCH")
        self.assertEqual(set(bad.validate()), {"STOP_WRONG_SIDE", "TARGET_WRONG_SIDE", "FUTURE_FEATURE", "SOURCE_WATCH", "COST_UNKNOWN"})
        c = Candidate("y", "S", "SH", "FOREX", "XAUUSD", "M5", "SHORT", 100, 100, "g", 100, 102, 96, spread=0.2, commission_R=0.05)
        lab = net_r_label(c, 96)
        self.assertAlmostEqual(lab["gross_R"], 2.0)
        self.assertAlmostEqual(lab["net_R"], 2.0 - 0.1 - 0.05)
        self.assertEqual(net_r_label(c, None, filled=False)["label_status"], "NO_ENTRY")

    def test_chrono_split_groups_purge_embargo(self):
        from masterquo.ml.dt_ranker import chrono_split
        s = make_sets(100)
        sp = chrono_split(s, purge_s=0, embargo_s=3600)
        gs = [{x["event_group_id"] for x in sp[k]} for k in ("fit", "calib", "test")]
        self.assertFalse(gs[0] & gs[1] or gs[1] & gs[2] or gs[0] & gs[2])
        self.assertLess(max(x["decision_ts"] for x in sp["fit"]), min(x["decision_ts"] for x in sp["calib"]))
        for k in ("fit", "calib"):
            nxt = {"fit": "calib", "calib": "test"}[k]
            self.assertLess(max(x["label_end_ts"] for x in sp[k]), min(x["decision_ts"] for x in sp[nxt]))

    def test_train_rank_no_trade_and_policy_evaluation(self):
        from masterquo.ml import dt_ranker as DT
        res = DT.train(make_sets(), {"min_leaf_events": 20, "calib_min": 10_000})
        self.assertEqual(res["status"], "READY")
        b = res["bundle"]
        ev = res["evaluation"]
        self.assertGreater(ev["DT_RANKER"]["mean_net_R_per_action"], ev["SETUP_SCORE_BASELINE"]["mean_net_R_per_action"])
        self.assertLess(ev["DT_RANKER"]["coverage"], 1.0)                          # abstains where nothing clears the conservative bound
        from masterquo.ml.dt_ranker import Candidate
        ts = 1_800_000_000
        good = Candidate("good", "S1", "BASKET", "FOREX", "XAUUSD", "M15", "LONG", ts, ts, "z", 100, 99, 103, setup_score=0.1, spread=0.05,
                         commission_R=0.02, atr=2.0)
        poor = Candidate("poor", "S2", "BASKET", "FOREX", "XAUUSD", "M15", "LONG", ts, ts, "z", 100, 99, 101, setup_score=0.99, spread=0.6,
                         commission_R=0.02, atr=2.0)
        r = DT.rank(b, [poor, good], {"min_leaf_events": 20})
        self.assertEqual((r["mode"], r["apply_to_selection"]), ("SHADOW", False))
        self.assertEqual(r["selected_candidate_id"], "good")
        self.assertEqual(r["ranked_candidates"][0]["probability_status"], "UNCALIBRATED")
        self.assertIsNone(r["ranked_candidates"][0]["p_positive_net_R"])
        self.assertEqual(DT.rank(b, [])["decision"], "NO_TRADE")
        self.assertEqual(DT.rank(b, [poor], {"min_leaf_events": 20})["decision"], "ABSTAIN")
        self.assertEqual(DT.rank(None, [good])["decision"], "FALLBACK_BASELINE")
        short = Candidate("s", "S3", "BASKET", "FOREX", "XAUUSD", "M15", "SHORT", ts, ts, "z", 100, 101, 97, spread=0.05, commission_R=0.02, atr=2.0)
        self.assertEqual(DT.rank(b, [good, short], {"min_leaf_events": 1, "min_conservative_net_r": -99})["decision"], "ABSTAIN")

    def test_insufficient_data_not_ready(self):
        from masterquo.ml import dt_ranker as DT
        self.assertEqual(DT.train(make_sets(20))["status"], "NOT_READY")


class TestBAT(unittest.TestCase):
    def bars(self, n=200, seed=1):
        rnd = random.Random(seed)
        p, out = 100.0, []
        for _ in range(n):
            o = p
            p *= math.exp(rnd.gauss(0, 0.002))
            out.append({"o": o, "h": max(o, p) * 1.001, "l": min(o, p) * 0.999, "c": p, "v": rnd.random() * 100})
        return out

    def test_future_perturbation_does_not_change_output(self):
        from masterquo.mm.bat_encoder import BATEncoder
        enc = BATEncoder()
        a = self.bars()
        b = a[:150] + self.bars(50, seed=99)
        b = [dict(x) for x in b]
        for x in b[150:]:
            x["c"] *= 3
            x["h"] *= 3
        ra, rb = enc.run(a, asof_index=149), enc.run(b, asof_index=149)
        self.assertEqual(ra["context"], rb["context"])
        self.assertEqual(ra["actor"], rb["actor"])
        self.assertNotEqual(enc.run(a)["context"], enc.run(b)["context"])

    def test_btc_central_vs_satma_latest_reference(self):
        import numpy as np
        from masterquo.mm.bat_encoder import BATEncoder, voxels
        enc = BATEncoder()
        f = enc._branches(voxels(self.bars(60)))
        g = f.copy()
        g[59] = g[59] + 5.0                                                          # change only the LATEST row
        self.assertFalse(np.allclose(enc.satma(f, 59), enc.satma(g, 59)))            # SATMA reference = latest
        w = max(enc.windows)
        h = f.copy()
        h[59 - w + 1 + w // 2, 0] += 5.0                                              # change one element of the central row of the largest window
        self.assertFalse(np.allclose(enc.btc(f, 59), enc.btc(h, 59)))
        r = enc.run(self.bars(5))
        self.assertEqual(r["status"], "WARMUP")
        out = enc.run(self.bars())
        self.assertAlmostEqual(sum(out["actor"].values()), 1.0)
        self.assertIn("NONE", out["execution"])


if __name__ == "__main__":
    unittest.main()
