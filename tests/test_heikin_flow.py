"""PMW-UPD-11 FF03 Heikin Flow + shared MA core (T17-T28)."""
import itertools
import unittest

import numpy as np

import _env  # noqa: F401

from _bars import bar
from masterquo.lab.flow_context import heikin as HF
from masterquo.lab.flow_context import ma as MA


def bars(n=200, seed=0):
    r = np.random.default_rng(seed)
    c, out = 100.0, []
    for i in range(n):
        o = c
        c = o + r.normal(0, 0.5)
        out.append(bar(i, max(o, c) + abs(r.normal(0, .2)), min(o, c) - abs(r.normal(0, .2)), c, o=o))
    return out


class MATests(unittest.TestCase):
    def test_t18_t19_t23_all_methods_vs_naive(self):
        xs = list(np.random.default_rng(1).normal(1000, 3, 300))
        for m in MA.METHODS:
            for P in (1, 2, 7, 20):
                for seed in MA.SEEDS:
                    a, b = MA.ma_series(xs, m, P, seed), MA.naive_ma(xs, m, P, seed)
                    for x, y in zip(a, b):
                        if y is None:
                            self.assertIsNone(x)
                        else:
                            self.assertAlmostEqual(x, y, places=7, msg=(m, P, seed))
        self.assertEqual(MA.ma_series([1.0, 2.0, 3.0], "LWMA", 3)[2], (1 + 4 + 9) / 6)   # oldest weight 1 -> newest 3
        from masterquo.lab import common
        e = common.ema(np.arange(10.0), 5)
        self.assertTrue(np.isnan(e[0]))                                 # global FULL_SEED EMA unchanged

    def test_t20_clamp(self):
        self.assertEqual(MA.normalize_period(0), (1, "CONFIG_CLAMPED"))
        self.assertEqual(MA.normalize_period(20000), (10000, "CONFIG_CLAMPED"))
        for bad in (2.5, float("nan"), "3", True):
            with self.assertRaises(ValueError):
                MA.normalize_period(bad)
        with self.assertRaises(ValueError):
            MA.RollingMA("XMA", 3)
        big = MA.RollingMA("LWMA", 10000)
        for x in range(12000):
            big.commit(float(x % 7))
        self.assertTrue(big.warm)

    def test_t22_preview_does_not_mutate(self):
        r = MA.RollingMA("EMA", 5)
        for x in (1.0, 2.0, 3.0):
            r.commit(x)
        p1 = r.preview(10.0)
        p2 = r.preview(10.0)
        self.assertEqual(p1, p2)
        self.assertEqual(r.commit(10.0), p1)


class HeikinTests(unittest.TestCase):
    def test_t17_manual_pipeline(self):
        b = bars(5)
        rows = HF.heikin_series(b, {"ma1": "SMA", "p1": 1, "ma2": "SMA", "p2": 1})["rows"]
        ho = (b[0]["o"] + b[0]["c"]) / 2
        hc = sum(b[0][k] for k in "ohlc") / 4
        self.assertAlmostEqual(rows[0]["o"], ho)
        self.assertAlmostEqual(rows[0]["c"], hc)
        hc1 = sum(b[1][k] for k in "ohlc") / 4
        self.assertAlmostEqual(rows[1]["o"], (ho + hc) / 2)               # recursion on RAW HA open/close
        self.assertAlmostEqual(rows[1]["c"], hc1)
        r2 = HF.heikin_series(b, {"ma1": "SMA", "p1": 1, "ma2": "SMA", "p2": 3})["rows"]
        self.assertAlmostEqual(r2[2]["o"], np.mean([x["raw_ha"][0] for x in r2[:3]]))   # stage 2 smooths raw HA, not final open

    def test_t18_sixteen_pairs_and_invariants(self):
        b = bars(150)
        for m1, m2 in itertools.product(MA.METHODS, MA.METHODS):
            rows = HF.heikin_series(b, {"ma1": m1, "p1": 6, "ma2": m2, "p2": 3})["rows"]
            for r in rows:
                self.assertGreaterEqual(r["h"], max(r["o"], r["c"]) - 1e-9)
                self.assertLessEqual(r["l"], min(r["o"], r["c"]) + 1e-9)
        q = HF.heikin_series(b, {"p1": 10, "p2": 5})["rows"]
        self.assertEqual(q[0]["quality"], "PARTIAL_STARTUP")
        self.assertEqual(q[-1]["quality"], "OK")

    def test_t22_t27_incremental_equals_batch_and_preview(self):
        b = bars(80)
        batch = HF.heikin_series(b)["rows"]
        hf = HF.HeikinFlow()
        for i, x in enumerate(b):
            pv = hf.preview(dict(x, c=x["c"] + 0.3, h=x["h"] + 0.3))           # forming ticks never committed
            hf.preview(x)
            r = hf.update(x)
            self.assertIsNone(hf.update(x))                                   # repeated poll of the same bar
            self.assertAlmostEqual(r["c"], batch[i]["c"])
            self.assertFalse(pv["closed"])
        with self.assertRaises(ValueError):
            hf.update(dict(b[0], open_utc=b[-1]["open_utc"] + 60, h=1.0, l=2.0))

    def test_t26_colour_and_units(self):
        out = HF.heikin_series(bars(60), {"deadband_points": 0.0})
        self.assertIn(out["rows"][-1]["color"], ("BULL", "BEAR", "NEUTRAL"))
        self.assertEqual(out["source_parity"], "UNVERIFIED_ORIGINAL")
        self.assertIn("synthetic", out["units"])
        self.assertEqual(HF.ABI["canonical"], [12, 13, 14, 15])


if __name__ == "__main__":
    unittest.main()
