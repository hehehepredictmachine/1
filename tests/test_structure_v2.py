"""PMW-UPD-07 cores: Black-76 (T15-T17), MITP (T19-T22), STRUCTURE_CAUSAL_V2 (T02, T05-T08, A-07-01)."""
import math
import random
import unittest

import _env  # noqa: F401

from masterquo.analytics import black76 as B
from masterquo.analysis import mitp, structure_v2 as S


class Black76Tests(unittest.TestCase):
    def test_t15_degenerate_cases_do_not_raise(self):
        a = B.price(100, 100, 0.0, 1.0)
        self.assertTrue(a["degenerate"])
        self.assertEqual(a["call"], 0.0)
        self.assertAlmostEqual(a["delta_call"], 0.5)
        self.assertIsNone(a["gamma"])
        self.assertEqual(a["gamma_reason"], "NONDIFFERENTIABLE")
        self.assertAlmostEqual(a["vega"], 100 * B.npdf(0.0))
        b = B.price(110, 100, 0.2, 0.0, 0.99)
        self.assertAlmostEqual(b["call"], 0.99 * 10)
        self.assertEqual(b["p_above_strict"], 1.0)
        self.assertEqual(b["vega"], 0.0)
        self.assertIsNone(b["p_touch"])

    def test_t16_parity_rates_and_extremes(self):
        for r in (0.05, -0.01, 0.0):
            for f, k in ((100, 50), (100, 100), (100, 400), (2000, 2001)):
                for sig in (0.01, 0.2, 2.0):
                    d = B.discount(r, 0.5)
                    x = B.price(f, k, sig, 0.5, d)
                    self.assertLess(abs(x["parity_residual"]), 1e-9 * max(f, k))
                    lo, hi = B.bounds(f, k, d, "call")
                    self.assertTrue(lo - 1e-9 <= x["call"] <= hi + 1e-9)
        # independent textbook value (Hull-style): F=20, K=20, sigma=.25, T=4/12, r=9% -> call ~= 1.1166
        self.assertAlmostEqual(B.price(20, 20, 0.25, 4 / 12, math.exp(-0.09 * 4 / 12))["call"], 1.1166, places=3)
        with self.assertRaises(B.Black76Error):
            B.discount(5.0, 1.0)                           # 5 (percent) instead of the fraction 0.05

    def test_t17_iv_roundtrip_and_states(self):
        for t in (7 / 365, 0.25, 1.0):
            for k in (90, 100, 115):
                for kind in ("call", "put"):
                    p = B.price(100, k, 0.3, t, 0.98)[kind]
                    r = B.implied_vol(p, 100, k, t, 0.98, kind)
                    self.assertEqual(r["status"], "CONVERGED")
                    self.assertAlmostEqual(r["sigma"], 0.3, places=6)
        self.assertEqual(B.implied_vol(120.0, 100, 100, 0.5)["status"], "NO_SOLUTION")      # above the upper bound D*F
        self.assertEqual(B.implied_vol(1.0, 100, 100, 0.0)["status"], "T_ZERO_UNIDENTIFIED")
        self.assertEqual(B.implied_vol(0.0, 100, 100, 0.5)["status"], "BOUNDARY")
        self.assertEqual(B.forward_from_parity([], 1.0, exercise_style="AMERICAN")["status"], "BLOCKED_EXERCISE_STYLE")

    def test_forward_from_parity_qa(self):
        pairs = [{"strike": k, "call_bid": max(0, 100 - k) + 1.9, "call_ask": max(0, 100 - k) + 2.1, "put_bid": max(0, k - 100) + 1.9,
                  "put_ask": max(0, k - 100) + 2.1, "age_s": 5} for k in (95, 100, 105)]
        r = B.forward_from_parity(pairs, 1.0)
        self.assertEqual(r["status"], "OK")
        self.assertAlmostEqual(r["forward"], 100.0)
        pairs[0]["call_bid"] = 99                       # crossed
        pairs[1]["age_s"] = 999                         # stale
        r = B.forward_from_parity(pairs, 1.0)
        self.assertEqual(r["status"], "INSUFFICIENT_PAIRS")
        self.assertEqual({x[1] for x in r["rejected"]}, {"CROSSED", "STALE"})

    def test_quantile_median(self):
        self.assertAlmostEqual(B.quantile(100, 0.2, 1.0, 0.5), 100 * math.exp(-0.02), places=6)


def _walk(n=400, seed=7):
    rnd = random.Random(seed)
    c, h, lo, o = [], [], [], []
    p = 2000.0
    for _ in range(n):
        op = p
        p = p + rnd.gauss(0.05, 1.5)
        o.append(op)
        c.append(p)
        h.append(max(op, p) + abs(rnd.gauss(0, 0.6)))
        lo.append(min(op, p) - abs(rnd.gauss(0, 0.6)))
    return o, h, lo, c


class MitpTests(unittest.TestCase):
    def test_t19_32_nodes_warmup_and_flat(self):
        o, h, lo, c = _walk()
        r = mitp.run(h, lo, c)
        self.assertEqual(len(r["nodes"]), 32)
        early = mitp.run(h[:5], lo[:5], c[:5])
        self.assertIn(early["status"], ("WARMING_UP", "PARTIAL_UNKNOWN"))
        flat = mitp.run([100.0] * 200, [100.0] * 200, [100.0] * 200)
        self.assertEqual(flat["votes"]["buy"], 0)
        self.assertEqual(flat["votes"]["sell"], 0)

    def test_t20_never_confirms_on_own_bar(self):
        ts = mitp.TwoStage()
        ts.step(0, 1, 101.0, 99.0, 102.0, 0)            # close above its own high is impossible in OHLC, but even then: no confirm
        self.assertIsNone(ts.state)
        self.assertEqual(ts.pending, 1)
        ts.step(1, 1, 102.0, 100.0, 101.5, 1)
        self.assertEqual(ts.state, "BUY")
        self.assertEqual(ts.confirmed_at, 1)
        ts2 = mitp.TwoStage()
        ts2.step(0, 1, 101.0, 99.0, 100.0, 0)
        ts2.step(1, -1, 101.0, 98.0, 98.5, 1)            # opposite cancels pending, starts SELL pending
        self.assertIsNone(ts2.state)
        self.assertEqual(ts2.pending, -1)
        ts2.step(2, None, 101.0, 98.0, 97.0, -1)
        self.assertEqual(ts2.flag, "UNKNOWN_SUSPENDED")
        self.assertIsNone(ts2.state)

    def test_t21_no_enabled_and_strict_all(self):
        o, h, lo, c = _walk()
        self.assertEqual(mitp.run(h, lo, c, enabled=[])["status"], "NO_ENABLED_SIGNALS")

        class St:
            def __init__(self, s):
                self.state = s
        nodes = [f"n{i}" for i in range(32)]
        st = {n: St("BUY") for n in nodes}
        st["n31"].state = "SELL"
        self.assertEqual(mitp._general(st, nodes, "STRICT_ALL")["vote"], 0)
        st["n31"].state = "BUY"
        self.assertEqual(mitp._general(st, nodes, "STRICT_ALL")["vote"], 1)

    def test_t22_checkpoint_equals_batch(self):
        o, h, lo, c = _walk()
        for prof in ("STRICT_ALL", "GROUP_BALANCED"):
            full = mitp.run(h, lo, c, profile=prof)
            part = mitp.run(h[:250], lo[:250], c[:250], profile=prof)
            res = mitp.run(h, lo, c, profile=prof, checkpoint=part["checkpoint"])
            self.assertEqual(full["nodes"], res["nodes"])
            self.assertEqual(full["general"], res["general"])
            self.assertIn("UNVERIFIED", full["source_parity"])


class StructureTests(unittest.TestCase):
    def test_a0701_invalidated_before_breakout_long_short_ttl(self):
        closes = [100, 90, 101, 110]
        hi = [x + 0.5 for x in closes]
        lo = [x - 0.5 for x in closes]
        r = S.evaluate_instance("P1", 1, 105, 95, -1, closes, hi, lo, closes)
        self.assertEqual(r["state"], "INVALIDATED")
        self.assertEqual(r["history"][0]["bar_index"], 1)
        m = [200 - x for x in closes]                    # mirror SHORT: confirm < 95, invalidation 105
        r2 = S.evaluate_instance("P2", -1, 95, 105, -1, m, [x + 0.5 for x in m], [x - 0.5 for x in m], m)
        self.assertEqual(r2["state"], "INVALIDATED")
        flat = [100.0] * 50
        r3 = S.evaluate_instance("P3", 1, 105, 95, 0, flat, flat, flat, flat, ttl_bars=10)
        self.assertEqual(r3["state"], "EXPIRED")
        self.assertEqual(r3["history"][0]["bar_index"], 11)

    def test_intrabar_conservative_and_retest(self):
        c = [100, 106]
        r = S.evaluate_instance("P4", 1, 105, 95, 0, c, [100, 107], [100, 94], c)
        self.assertEqual(r["state"], "INVALIDATED")
        self.assertIn("INTRABAR_ORDER_UNKNOWN", r["flags"])
        c = [100, 107, 105.5, 108, 109]
        r = S.evaluate_instance("P5", 1, 105, 95, 0, c, [x + 0.5 for x in c], [100, 106, 105.1, 107.5, 108.5], c, retest_tol=0.3)
        self.assertEqual(r["state"], "RETEST_HELD")
        c = [100, 107, 104]
        r = S.evaluate_instance("P6", 1, 105, 95, 0, c, c, c, c)
        self.assertEqual(r["state"], "RETEST_FAILED")

    def test_t02_pivot_known_after_right_bars(self):
        h = [1, 2, 3, 10, 3, 2, 1, 1, 1]
        lo = [0] * 9
        piv = [p for p in S.pivots(h, lo, 3, 3) if p["kind"] == "H"]
        self.assertEqual(piv[0]["index"], 3)
        self.assertEqual(piv[0]["known_index"], 6)
        self.assertEqual(S.pivots(h[:6], lo[:6], 3, 3), [])         # not yet known
        eq = [1, 2, 3, 10, 10, 2, 1, 1, 1, 1]                       # equal highs: earliest wins, exactly one pivot
        self.assertEqual([p["index"] for p in S.pivots(eq, [0] * 10, 3, 3) if p["kind"] == "H"], [3])

    def test_t06_sweep_vs_bos(self):
        o, h, lo, c = _walk(300, 3)
        t = [f"2026-01-01T{i // 60:02d}:{i % 60:02d}:00Z" for i in range(300)]
        r = S.analyse(t, h, lo, c, tick=0.01)
        kinds = {e["kind"] for e in r["events"]}
        self.assertTrue(kinds)
        for e in r["events"]:
            i = e["bar_index"]
            if e["kind"].startswith("SWEEP"):
                self.assertTrue((c[i] <= e["level"]) if e["kind"].endswith("HIGH") else (c[i] >= e["level"]))
            elif e["kind"].endswith("UP"):
                self.assertGreater(c[i], e["level"])

    def test_t03_t08_prefix_invariance_and_no_duplicates(self):
        o, h, lo, c = _walk(300, 5)
        t = [f"2026-01-01T{i // 60:02d}:{i % 60:02d}:00Z" for i in range(300)]
        a = S.analyse(t[:200], h[:200], lo[:200], c[:200])
        h2, lo2, c2 = h[:200] + [x * 3 for x in h[200:]], lo[:200] + [x * 0.2 for x in lo[200:]], c[:200] + [x * 2 for x in c[200:]]
        b = S.analyse(t, h2, lo2, c2)
        early = [e for e in b["events"] if e["bar_index"] < 200 - 0]
        full_a = S.analyse(t[:200], h[:200], lo[:200], c[:200], params={})
        self.assertEqual({e["event_id"] for e in full_a["events"]}, {e["event_id"] for e in a["events"]})
        ids_a = {e["event_id"]: e["kind"] for e in a["events"] if e["bar_index"] < 190}
        ids_b = {e["event_id"]: e["kind"] for e in early}
        for k, v in ids_a.items():
            if k in ids_b:
                self.assertEqual(ids_b[k], v)
        self.assertEqual(len({e["event_id"] for e in b["events"]}), len(b["events"]))


if __name__ == "__main__":
    unittest.main()
