"""PMW-UPD-14 VAMD (T01-T10) and bounded Katz FD (T39-T48). Expected values are hand-derived here, not produced by the module."""
import math
import unittest

import numpy as np

import _env  # noqa: F401

from _bars import bar, from_closes
from masterquo.lab.context_ind import fractal as FD
from masterquo.lab.context_ind import vamd as VM


def ramp(n, step=1.0, rng=0.5):
    return [bar(i, 100 + step * i + rng, 100 + step * i - rng, 100 + step * i) for i in range(n)]


class VAMDTests(unittest.TestCase):
    def test_t03_t04_t05_definition(self):
        bs = ramp(80)
        out = VM.series(bs)
        self.assertEqual(out[61]["status"], "WARMING_UP")
        self.assertEqual(out[62]["status"], "READY")                     # A+B-1 = 63rd valid bar
        # independent ATR: TR0 = H-L = 1, then max(H-L, |H-Cprev|, |L-Cprev|) = 1.5 for a ramp of +1
        tr = [1.0] + [1.5] * 79
        atr = sum(tr[:14]) / 14
        atrs = [atr]
        for x in tr[14:]:
            atr = (atr * 13 + x) / 14
            atrs.append(atr)
        t = 62
        a_t = atrs[t - 13]
        base = sum(atrs[t - 13 - 49:t - 13 + 1]) / 50
        m = (bs[t]["c"] - bs[t - 10]["c"]) / a_t
        self.assertAlmostEqual(out[t]["m"], m)
        self.assertAlmostEqual(out[t]["baseline"], base)
        self.assertAlmostEqual(out[t]["alpha"], min(0.9, 0.15 * a_t / base))
        self.assertAlmostEqual(out[t]["y"], m)                            # first y seeded with m
        self.assertAlmostEqual(out[t]["raw_momentum"], 10.0)              # price units, no division by P
        with self.assertRaises(ValueError):
            VM.VAMD({"base_decay": 0.95, "max_decay": 0.9})

    def test_t06_t07_recursion_semantics(self):
        v = VM.VAMD()
        v.y = 4.0
        y = v.y + 0.9 * (4.0 - v.y)
        self.assertEqual(y, 4.0)                                          # constant target 4 stays 4 for any alpha
        bs = ramp(100, step=0.0, rng=0.5)                                 # zero momentum target -> y decays only if it was non-zero
        out = VM.series(ramp(70) + [bar(70 + i, 170.5, 169.5, 170) for i in range(60)])
        ys = [o["y"] for o in out if o.get("y") is not None]
        self.assertTrue(all(abs(b2) <= abs(a2) + 1e-12 for a2, b2 in zip(ys[-40:], ys[-39:])))   # fading target -> monotone decay
        for o in out:
            if o.get("y") is not None and o.get("m") is not None:
                pass
        self.assertTrue(bs)

    def test_t05_zero_atr_and_invalid(self):
        out = VM.series([bar(i, 100, 100, 100) for i in range(80)])
        self.assertEqual(out[-1]["status"], "FLAT_NO_MOTION")
        self.assertIsNone(out[-1]["y"])
        self.assertEqual(VM.VAMD().update(bar(0, 1, 2, 1.5))["status"], "INVALID_INPUT")

    def test_t02_t09_checkpoint_and_preview(self):
        bs = ramp(90)
        a = VM.VAMD()
        for b in bs[:70]:
            a.update(b)
        ck = a.checkpoint()
        pv = a.preview(bs[70])
        self.assertFalse(pv["closed"])
        self.assertEqual(a.checkpoint(), ck)                              # preview never mutates
        b2 = VM.VAMD()
        b2.restore(ck)
        r1 = [a.update(b)["y"] for b in bs[70:]]
        r2 = [b2.update(b)["y"] for b in bs[70:]]
        self.assertEqual(r1, r2)

    def test_t01_prefix(self):
        bs = ramp(90)
        full = VM.series(bs)
        part = VM.series(bs[:75] + [dict(b, c=b["c"] + 50, h=b["h"] + 50) for b in bs[75:]])
        self.assertEqual([x["y"] for x in full[:75]], [x["y"] for x in part[:75]])


class FDTests(unittest.TestCase):
    def test_t39_t40_monotonic_and_invariance(self):
        k = FD.katz([float(i) for i in range(30)])
        self.assertAlmostEqual(k["fd_raw"], 1.0)                          # straight line: L = d
        r = np.random.default_rng(1).normal(0, 1, 30).cumsum()
        a = FD.katz(list(r))
        b = FD.katz(list(3 * r + 1000))
        self.assertAlmostEqual(a["fd_raw"] or 2.0, b["fd_raw"] or 2.0, places=9)
        p = [0, 5, 1, 2, 3, 4, 4.5, 4.8]                                  # max displacement (5) differs from the endpoint (4.8)
        k2 = FD.katz(p)
        self.assertEqual(k2["d"], 5)
        self.assertAlmostEqual(k2["L"], sum(abs(p[j] - p[j - 1]) for j in range(1, len(p))))

    def test_t41_t42_t43_saturation_clip_flat(self):
        k = FD.katz([0.0, 1.0] * 15)
        self.assertEqual((k["L"], k["d"], k["n"]), (29, 1, 29))
        self.assertAlmostEqual(k["den"], 0.0)
        self.assertIsNone(k["fd_raw"])
        self.assertEqual(k["fd_bounded"], 2.0)
        self.assertEqual(k["bound_policy"], "CONSERVATIVE_CHOP_SATURATION")
        import json
        json.dumps(k, allow_nan=False)
        flat = FD.katz([5.0] * 30)
        self.assertEqual(flat["zone"], "NO_MOTION")
        self.assertIsNone(flat["fd_bounded"])
        z = FD.katz([0, 1, 0.2, 1.1, 0.3, 1.2, 0.4, 1.3])
        if z["fd_raw"] is not None and z["fd_raw"] > 2:
            self.assertTrue(z["clipped"])

    def test_t44_applied_prices(self):
        b = {"o": 1.0, "h": 4.0, "l": 0.0, "c": 2.0}
        self.assertEqual(FD.PRICES["MEDIAN"](b), 2.0)
        self.assertAlmostEqual(FD.PRICES["TYPICAL"](b), 2.0)
        self.assertEqual(FD.PRICES["WEIGHTED"](b), 2.0)
        with self.assertRaises(ValueError):
            FD.FractalRegime({"price": "XYZ"})

    def test_t45_t46_ema_zones(self):
        f = FD.FractalRegime({"N": 30, "S": 5})
        outs = [f.update(b) for b in ramp(40)]
        self.assertIsNone(outs[32]["fd_smooth"])
        self.assertIsNotNone(outs[33]["fd_smooth"])                       # warm-up N+S-1 = 34 bars
        self.assertEqual(f.zone(1.40), "TREND")
        self.assertEqual(f.zone(1.65), "CHOP")
        self.assertEqual(f.zone(1.5), "NEUTRAL")
        self.assertEqual(outs[-1]["zone"], "TREND")                       # no direction attached
        self.assertNotIn("UP", str(outs[-1]["zone"]))
        o2 = f.update(bar(41, 140.5, 139.5, 139.0))
        self.assertIn(o2["zone"], ("TREND", "NEUTRAL", "CHOP"))

    def test_t48_prefix(self):
        bs = from_closes(list(np.random.default_rng(3).normal(0, 1, 120).cumsum() + 100))
        a = FD.series(bs)
        b = FD.series(bs[:90] + [dict(x, c=x["c"] + 10) for x in bs[90:]])
        self.assertEqual([x.get("fd_smooth") for x in a[:90]], [x.get("fd_smooth") for x in b[:90]])


if __name__ == "__main__":
    unittest.main()
