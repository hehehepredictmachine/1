"""PMW-UPD-09 R24 SMMA(3) channel and R25 Z-score (T136-T144)."""
import math
import unittest

import numpy as np

import _env  # noqa: F401

from _bars import bar, from_closes
from masterquo.lab import market_v2 as V


class SmmaTests(unittest.TestCase):
    def test_t136_manual_values_and_stream(self):
        bars = [bar(i, h, lo, (h + lo) / 2) for i, (h, lo) in enumerate([(3, 1), (6, 2), (9, 3), (12, 6), (6, 3)])]
        ch = V.SmmaChannel(deadband=0.0)
        recs = [ch.update(b) for b in bars]
        self.assertAlmostEqual(recs[2]["U"], 6.0)
        self.assertAlmostEqual(recs[2]["L"], 2.0)
        self.assertAlmostEqual(recs[3]["U"], (2 * 6 + 12) / 3)
        self.assertAlmostEqual(recs[4]["L"], (2 * ((2 * 2 + 6) / 3) + 3) / 3)
        ch2 = V.SmmaChannel(deadband=0.0)
        for b in bars[:3]:
            ch2.update(b)
        ck = ch2.checkpoint()
        ch3 = V.SmmaChannel(deadband=0.0)
        ch3.restore(ck)
        self.assertAlmostEqual(ch3.update(bars[3])["U"], recs[3]["U"])
        self.assertTrue(all(r["U"] >= r["L"] for r in recs if r.get("U") is not None))

    def test_t137_profiles_and_lag(self):
        with self.assertRaises(ValueError):
            V.SmmaChannel(lag=-1)
        cs = [10, 10, 10, 10, 13, 13, 9, 9]
        b = from_closes(cs, 0.5)
        cur = [r.get("event") for r in V.smma_series(b, deadband=0.01)["series"]]
        prev = [r.get("event") for r in V.smma_series(b, boundary="PREVIOUS_BOUNDARY", deadband=0.01)["series"]]
        self.assertIn("UP", cur)
        self.assertNotEqual(cur, prev)
        lag = V.smma_series(b, lag=1, deadband=0.01)["series"]
        self.assertEqual(lag[0]["status"], "WARMUP")

    def test_t138_events_and_dedup(self):
        b = from_closes([10, 10, 10, 10, 13, 14, 15, 15], 0.5)
        ch = V.SmmaChannel(deadband=0.01)
        recs = [ch.update(x) for x in b]
        self.assertEqual([r.get("event") for r in recs].count("UP"), 1)        # held state is not a new event
        self.assertEqual(recs[-1]["location"], "ABOVE")
        n = len(ch.events)
        ch.update(b[-1])                                                        # repeated poll of the same bar
        self.assertEqual(len(ch.events), n)
        ch2 = V.SmmaChannel(deadband=0.01)
        for x in b:
            ch2.update(x)
        self.assertEqual(set(ch.events), set(ch2.events))                      # restart -> identical stable ids

    def test_t139_gap_blocks_cross(self):
        b = from_closes([10, 10, 10, 10], 0.5) + [dict(x, open_utc=x["open_utc"] + 7200) for x in from_closes([0, 0, 0, 0, 14], 0.5)[4:]]
        recs = [r.get("event") for r in V.smma_series(b, deadband=0.01)["series"]]
        self.assertNotIn("UP", recs)


class ZTests(unittest.TestCase):
    def test_t140_windows(self):
        c = np.array([0.0] * 19 + [100.0])
        self.assertAlmostEqual(V.zscore_at(c, 19)["z"], math.sqrt(19))
        p = V.zscore_at(np.array([0.0] * 20 + [100.0]), 20, mode="PREVIOUS_N")
        self.assertIsNone(p["z"])
        self.assertEqual(p["status"], "LOW_DISPERSION")
        a = V.zscore_at(np.arange(30.0), 25)
        b = V.zscore_at(np.arange(30.0), 25, mode="PREVIOUS_N")
        self.assertEqual(a["window"], [6, 25])
        self.assertEqual(b["window"], [5, 24])
        self.assertNotAlmostEqual(a["z"], b["z"])

    def test_t141_validation_affine(self):
        with self.assertRaises(ValueError):
            V.zscore_at(np.arange(30.0), 25, ddof=20)
        r = np.random.default_rng(0).normal(0, 1, 40)
        z1 = V.zscore_at(r, 39, tick=1e-6)["z"]
        z2 = V.zscore_at(3 * r + 1000, 39, tick=3e-6)["z"]
        self.assertAlmostEqual(z1, z2, places=9)
        r2 = r.copy()
        r2[-1] = 50
        self.assertLessEqual(abs(V.zscore_at(r2, 39)["z"]), math.sqrt(19) + 1e-12)
        self.assertIsNone(V.zscore_at(r2, 39, mode="PREVIOUS_N").get("bound"))

    def test_t142_cancellation(self):
        c = 1e8 + np.array([0.0, 0.01, 0.02, 0.01, 0.0] * 4)
        z = V.zscore_at(c, 19, tick=1e-4, min_rel_std=0)
        ref = (c[-1] - c[-20:].mean()) / c[-20:].std()
        self.assertAlmostEqual(z["z"], ref, places=6)
        self.assertEqual(V.zscore_at(np.full(20, 2000.0), 19)["status"], "LOW_DISPERSION")

    def test_t143_percent_b(self):
        c = np.random.default_rng(2).normal(100, 2, 20)
        z = V.zscore_at(c, 19)["z"]
        m, s = c.mean(), c.std()
        pb = (c[-1] - (m - 2 * s)) / (4 * s)
        self.assertAlmostEqual(V.percent_b_from_z(z, 2.0), pb)

    def test_t144_hypotheses_causal(self):
        cs = list(2000 + np.cumsum(np.random.default_rng(5).normal(0, 1, 400)))
        bars = from_closes(cs)
        full = V.zscore_series(bars)
        part = V.zscore_series(bars[:300])
        ids_part = {e["event_id"] for e in part["events"]}
        ids_full = {e["event_id"] for e in full["events"] if e["t"] < bars[300]["open_utc"]}
        self.assertTrue(ids_part.issubset(ids_full) or ids_part == ids_full)
        self.assertEqual(len({e["hypothesis"] for e in full["events"]} - {"H_MR", "H_BO", "H_TP"}), 0)
        self.assertNotIn("p_value", str(full))


if __name__ == "__main__":
    unittest.main()
