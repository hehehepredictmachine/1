"""PMW-UPD-11 FF01/FF02 Markov 3-state and difference buckets (T01-T16). TEST_ONLY inputs; no edge claim."""
import itertools
import tempfile
import unittest
from pathlib import Path

import numpy as np

import _env  # noqa: F401

from _bars import from_closes
from masterquo.lab.flow_context import markov as MK


class Markov3Tests(unittest.TestCase):
    def test_t01_counts_alpha_and_threshold(self):
        core = MK.MarkovCore(3, 1.0)
        for a, b in ((0, 1), (0, 1), (1, 2), (2, 2)):
            core.add(a, b)
        P = core.P()
        np.testing.assert_allclose(P[0], [1 / 5, 3 / 5, 1 / 5])
        np.testing.assert_allclose(P.sum(1), 1.0)
        self.assertEqual(core.support(), [2, 1, 1])
        cs = list(100 + np.cumsum(np.random.default_rng(0).normal(0, 1, 300)))
        m = MK.Markov3(0.01).fit(from_closes(cs[:200]))
        tau = m.tau
        m.step(from_closes(cs)[-3:])
        self.assertEqual(m.tau, tau)                                  # tau frozen after Fit
        self.assertEqual(m.state(tau), 1)                             # equality boundary is FLAT
        self.assertEqual(m.state(tau + 1e-9), 2)
        from masterquo.lab import market as legacy
        self.assertTrue(callable(legacy.markov))                         # legacy M09 kept (LEGACY profile)

    def test_t02_prequential_dedup_ring_gap(self):
        cs = list(100 + np.cumsum(np.random.default_rng(1).normal(0, 1, 400)))
        bars = from_closes(cs)
        m = MK.Markov3(0.01, ring=50).fit(bars[:100])
        self.assertEqual(sum(m.core.support()), 50)                   # ring keeps the newest 50 transitions
        r1 = m.step(bars[:101])
        n = sum(m.core.support())
        self.assertFalse(m.core.add(0, 0, str(bars[100]["open_utc"])))  # same transition id -> no double update
        self.assertEqual(sum(m.core.support()), n)
        r2 = m.step(bars[:102])
        self.assertIsNotNone(r2["score_prev"])                        # the forecast issued at 101 was scored before update
        gap = dict(bars[103], open_utc=bars[103]["open_utc"] + 3600)
        r3 = m.step(bars[:102] + [gap])
        self.assertEqual(r3["score_prev"]["gap"], "GAP_NO_TRANSITION")
        self.assertIn("next", r1)

    def test_t03_multistep(self):
        core = MK.MarkovCore(3)
        rng = np.random.default_rng(2)
        for _ in range(200):
            core.add(int(rng.integers(3)), int(rng.integers(3)))
        fc = core.forecast(1, 5)
        np.testing.assert_allclose(fc[4], np.eye(3)[1] @ np.linalg.matrix_power(core.P(), 5))

    def test_t04_stationary(self):
        s = MK.stationary(np.array([[.9, .1], [.2, .8]]))
        np.testing.assert_allclose(s["pi"], [2 / 3, 1 / 3])
        self.assertLess(s["residual"], 1e-10)
        self.assertEqual(MK.stationary(np.array([[0, 1.], [1, 0]]))["status"], "PERIODIC")
        self.assertEqual(MK.stationary(np.eye(2))["status"], "NON_UNIQUE")
        self.assertEqual(MK.stationary(np.array([[.5, .6], [.2, .8]]))["status"], "INVALID_P")

    def test_t06_save_load(self):
        cs = list(100 + np.cumsum(np.random.default_rng(3).normal(0, 1, 300)))
        m = MK.Markov3(0.01).fit(from_closes(cs))
        m2 = MK.Markov3.from_dict(m.to_dict())
        np.testing.assert_allclose(m2.core.P(), m.core.P())
        with self.assertRaises(ValueError):
            MK.Markov3.from_dict(dict(m.to_dict(), model_id="X"))


class DiffBucketTests(unittest.TestCase):
    def test_t07_bins(self):
        b = MK.make_bins(np.arange(1, 101, dtype=float), 4)
        self.assertEqual(b["K_effective"], 4)
        self.assertEqual(MK.bin_of(b["cuts"][0], b["cuts"]), 1)          # side=right: a value equal to a cut goes up
        d = MK.make_bins(np.array([0.0] * 90 + [1.0] * 10), 9)
        self.assertLess(d["K_effective"], 9)
        self.assertGreater(d["duplicates_merged"], 0)
        with self.assertRaises(ValueError):
            MK.make_bins(np.arange(10.0), 2)
        import json
        json.dumps(d, allow_nan=False)

    def test_t10_t11_dp_vs_exhaustive(self):
        P = np.array([[.7, .3], [.2, .8]])
        mu = np.array([-2.0, 3.0])
        r = MK.dp_moments(P, mu, mu ** 2, 0, 4)
        exp = {1: (-.5, 5.25), 2: (-.25, 16.6875), 4: (1.1875, 48.52734375)}
        for h, (m, v) in exp.items():
            self.assertAlmostEqual(r[h - 1]["mean"], m)
            self.assertAlmostEqual(r[h - 1]["var"], v)
        for h in range(1, 5):                                           # independent enumeration of all paths
            m = v = 0.0
            for path in itertools.product([0, 1], repeat=h):
                p, s, tot = 1.0, 0, 0.0
                for k in path:
                    p *= P[s, k]
                    s = k
                    tot += mu[k]
                m += p * tot
                v += p * tot * tot
            self.assertAlmostEqual(r[h - 1]["var"], v - m * m)
        indep = sum(np.var([-2, 3]) for _ in range(4))                  # sum of independent variances differs
        self.assertNotAlmostEqual(r[3]["var"], indep)

    def _model(self, n=3000, seed=4):
        cs = list(2000 + np.cumsum(np.random.default_rng(seed).normal(0, 0.3, n)))
        return MK.MarkovDiff(0.01, 9, n_paths=4096).fit(from_closes(cs)), cs

    def test_t08_t12_t13_t14_mc_and_units(self):
        m, cs = self._model()
        self.assertTrue(m.eligibility()["eligible"])
        fc = m.forecast(4, cs[-1], 15)
        pr = fc["projection"]
        for h in ("1", "5", "15"):
            q = pr[h]["q_points"]
            self.assertLessEqual(q[0], q[1])
            self.assertLessEqual(q[1], q[2])
        rng = np.random.default_rng(0)
        sims = m.simulate(np.array(fc["P"]), 4, 5, 20000, rng)
        self.assertAlmostEqual(sims[:, 4].mean(), pr["5"]["mean_points"], delta=4 * np.sqrt(pr["5"]["var_points2"] / 20000) + 1e-6)
        self.assertAlmostEqual(pr["5"]["price_mean"], cs[-1] + 0.01 * pr["5"]["mean_points"])
        self.assertAlmostEqual(pr["5"]["price_sd"], 0.01 * np.sqrt(pr["5"]["var_points2"]))

    def test_t09_degenerate(self):
        m = MK.MarkovDiff(0.01, 9).fit(from_closes([100.0] * 300))
        self.assertLessEqual(m.bins["K_effective"], 2)
        self.assertEqual(m.eligibility()["reason"], "NO_VARIATION")
        self.assertIsNone(m.forecast(0, 100.0)["projection"])

    def test_t15_save_load_and_tail(self):
        m, cs = self._model(1500, 5)
        with tempfile.TemporaryDirectory() as d:
            m.save(Path(d) / "m")
            m2 = MK.MarkovDiff.load(Path(d) / "m")
            np.testing.assert_allclose(m2.core.P(), m.core.P())
            (Path(d) / "m" / "emissions.npz").write_bytes(b"x")
            with self.assertRaises(ValueError):
                MK.MarkovDiff.load(Path(d) / "m")
        bars = from_closes(cs)
        last = dict(bars[-1], c=bars[-2]["c"] + 1000.0)
        self.assertIn("TAIL_OUT_OF_SUPPORT", m.step([bars[-2], last])["flags"])


if __name__ == "__main__":
    unittest.main()
