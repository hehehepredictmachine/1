"""PMW-UPD-09 R21 MQ_MINIROCKET_UNIVARIATE_V2 / MQ_MINIROCKET_RIDGE_V2 (T109-T122). sktime fixture = pinned external reference
(tests/fixtures/minirocket/provenance.json); native MQL5 compilation/execution is NOT available here and must stay NOT_COMPILED."""
import struct
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

import _env  # noqa: F401

from masterquo.lab import minirocket_v2 as M

FIX = Path(__file__).resolve().parent / "fixtures" / "minirocket"


def _rw(n, L=128, seed=0):
    return np.cumsum(np.random.default_rng(seed).normal(0, 1, (n, L)), axis=1)


class TransformTests(unittest.TestCase):
    def test_t109_lifecycle_refusals(self):
        mr = M.MiniRocketV2()
        with self.assertRaises(M.MRError):
            mr.transform(_rw(1))
        mr.configure(128, 840, 32)
        with self.assertRaisesRegex(M.MRError, "NOT_FITTED"):
            mr.transform(_rw(1))
        with self.assertRaisesRegex(M.MRError, "L<9"):
            M.MiniRocketV2().configure(8)
        with self.assertRaisesRegex(M.MRError, "BUDGET"):
            M.MiniRocketV2().configure(128, 83)
        mr.fit(_rw(5))
        for bad in ([], np.zeros((0, 128)), [[1.0] * 128, [1.0] * 127]):
            with self.assertRaises(M.MRError):
                mr.transform(bad)
        x = _rw(1)
        x[0, 5] = np.nan
        with self.assertRaisesRegex(M.MRError, "NON_FINITE"):
            mr.transform(x)
        with self.assertRaisesRegex(M.MRError, "LENGTH"):
            mr.transform(_rw(1, 100))
        mr.configure(128, 840, 32)                               # reconfigure invalidates Fit
        self.assertEqual(mr.validate_state()["status"], "NOT_FITTED")

    def test_t110_kernels(self):
        self.assertEqual(len(M.KERNELS), 84)
        self.assertEqual(len({tuple(k) for k in M.KERNELS}), 84)
        self.assertEqual(M.KERNELS[0].tolist(), [0, 1, 2])
        self.assertEqual(M.KERNELS[-1].tolist(), [6, 7, 8])
        for k in M.KERNELS:
            w = np.full(9, -1)
            w[k] = 2
            self.assertEqual(w.sum(), 0)
            self.assertEqual((w == 2).sum(), 3)

    def test_t110_t114_oracle_signals(self):
        L = 64
        sig = {"impulse": np.eye(1, L, 30)[0] * 5, "ramp": np.arange(L, dtype=float), "sin": np.sin(np.arange(L) / 3.0), "flat": np.zeros(L)}
        X = np.stack(list(sig.values()))
        mr = M.MiniRocketV2().configure(L, 840, 32).fit(_rw(6, L, 2), seed=4)
        H, den = mr.counts(X)
        f0s = np.cumsum([0] + [84 * c for c in mr.lay["counts"]])
        for di, d in enumerate(mr.lay["dilations"]):
            nf = mr.lay["counts"][di]
            for k in (0, 17, 83):
                f = int(f0s[di] + k * nf)
                for w in range(len(X)):
                    hc, dn = M.oracle_counts(X[w], d, k, float(mr.biases[f]), (di + k) % 2 == 1)
                    self.assertEqual((hc, dn), (int(H[w, f]), int(den[f])), (di, k, w))
        ppv = mr.transform(X)
        self.assertTrue(((ppv >= 0) & (ppv <= 1)).all())
        self.assertTrue(set(np.unique(den)).issubset({L} | {L - 8 * d for d in mr.lay["dilations"]}))

    def test_t114_strict_greater(self):
        mr = M.MiniRocketV2().configure(16, 84, 32)
        mr.fit(np.zeros((1, 16)))
        H, _ = mr.counts(np.zeros((1, 16)))                      # conv == 0 == bias everywhere: equality is not a hit
        self.assertEqual(int(H.sum()), 0)

    def test_t111_golden_layout_and_boundaries(self):
        lay = M.layout(128, 10000, 32)
        self.assertEqual(lay["F"], 9996)
        self.assertEqual(lay["dilations"], list(range(1, 16)))
        self.assertEqual(lay["counts"], [30, 19, 12, 12, 8, 4, 8, 4, 4, 3, 3, 3, 3, 3, 3])
        self.assertEqual(sum(lay["counts"]), 119)
        exp = {9: ([1], [119]), 16: ([1], [119]), 17: ([1, 2], [116, 3]),
               129: (list(range(1, 15)) + [16], [30, 19, 12, 8, 12, 4, 8, 4, 4, 3, 3, 3, 3, 3, 3])}
        for L, (d, c) in exp.items():
            lay = M.layout(L, 10000, 32)
            self.assertEqual((lay["dilations"], lay["counts"]), (d, c), L)
            self.assertEqual(lay["F"], 9996)
        self.assertEqual(M.layout(257, 10000, 32)["dilations"][-1], 32)

    def test_t112_quantiles_global_float32(self):
        lay = M.layout(128, 10000, 32)
        q = lay["quantiles"]
        self.assertEqual(q.dtype, np.float32)
        self.assertEqual(len(q), 9996)
        self.assertAlmostEqual(float(q[0]), ((1 + 5 ** 0.5) / 2) % 1, places=6)
        self.assertNotEqual(float(q[30]), float(q[0]))          # not restarted per kernel

    def test_t113_train_only_and_portable_indices(self):
        tr = _rw(20, seed=1)
        a = M.MiniRocketV2().configure(128, 840, 32).fit(tr, seed=9)
        b = M.MiniRocketV2().configure(128, 840, 32).fit(tr, seed=9)
        np.testing.assert_array_equal(a.biases, b.biases)
        np.testing.assert_array_equal(a.fit_idx, M.fit_window_indices(20, len(a.lay["dilations"]), 9))
        self.assertEqual(hex(M.SplitMix64(0).next()), "0xe220a8397b1dcdaf")      # canonical SplitMix64 vector (also in MQL5 self-test)
        c = M.MiniRocketV2().configure(128, 840, 32).fit(tr, indices=a.fit_idx)   # frozen indices reproduce
        np.testing.assert_array_equal(c.biases, a.biases)
        self.assertEqual(c.fit_info["source"], "FROZEN_INDICES")
        s = M.MiniRocketV2().configure(128, 840, 32).fit(tr, mode="SINGLE_WINDOW")
        self.assertEqual(s.fit_info["source"], "SINGLE_WINDOW")

    def test_t115_t117_sktime_fixture_parity(self):
        if not (FIX / "sktime_fixture.npz").exists():
            self.skipTest("SKIP: brak fixture sktime")
        r = M.parity(FIX)
        self.assertEqual(r["results"]["FIT_LAYOUT_PARITY"], "PASS")
        self.assertEqual(r["results"]["FROZEN_STATE_PARITY"], "PASS")
        self.assertEqual(r["results"]["ALGORITHM_VALIDATED"], "PASS")
        self.assertTrue(r["details"]["frozen_state"]["ppv_exact_float32"])
        self.assertEqual(r["results"]["FIT_RANDOM_SELECTION_PARITY"], "NOT_CLAIMED")
        self.assertEqual(r["results"]["NATIVE_COMPILED"], "NOT_COMPILED_NO_METAEDITOR")
        self.assertEqual(r["results"]["NATIVE_EXECUTED"], "NATIVE_NOT_EXECUTED")
        self.assertLess(r["details"]["single_window_fit"]["max_rel_to_bias_scale"], 1e-5)

    def test_t116_offset_and_price_path(self):
        mr = M.MiniRocketV2().configure(128, 840, 32).fit(_rw(5))
        x = _rw(1, seed=3)
        H1, den = mr.counts(x)
        H2, _ = mr.counts(x + 1000.0)
        centre = den < 128
        np.testing.assert_array_equal(H1[:, centre], H2[:, centre])          # valid-centre invariant to a constant offset
        c = 2000 + np.cumsum(np.random.default_rng(1).normal(0, 1, 300))
        w = M.price_path_atr(c, 200, 2.0, 0.01)
        self.assertEqual(w[0], 0.0)
        np.testing.assert_allclose(w, (c[73:201] - c[73]) / 2.0)
        self.assertIsNone(M.price_path_atr(c, 50, 2.0, 0.01))


class HeadAndFormatTests(unittest.TestCase):
    def test_t118_ridge_matches_independent_solution(self):
        r = np.random.default_rng(0)
        X = r.normal(size=(60, 12))
        Y = r.normal(size=(60, 2))
        Xc, Yc = X - X.mean(0), Y - Y.mean(0)
        lam = 3.0
        ref = np.linalg.lstsq(np.vstack([Xc, np.sqrt(lam) * np.eye(12)]), np.vstack([Yc, np.zeros((12, 2))]), rcond=None)[0]
        Wd, i1 = M.ridge_solve(Xc, Yc, lam, "DUAL")
        Wc, i2 = M.ridge_solve(Xc, Yc, lam, "CG", tol=1e-12, chunk=7)
        np.testing.assert_allclose(Wd, ref, atol=1e-9)
        np.testing.assert_allclose(Wc, ref, atol=1e-7)
        self.assertTrue(i2["converged"])
        _, i3 = M.ridge_solve(Xc, Yc, 1e-9, "CG", tol=1e-30, max_iter=2)
        self.assertFalse(i3["converged"])
        self.assertEqual(i3["status"], "SOLVER_NOT_CONVERGED")
        with self.assertRaises(M.MRError):
            M.ridge_solve(np.zeros((3000, 2)), np.zeros((3000, 1)), 1.0, "DUAL")

    def test_t118_head_outputs(self):
        r = np.random.default_rng(1)
        Z = r.random((200, 30))
        Y = r.integers(0, 3, (200, 3))
        Y[:5, 0] = -1
        R = r.normal(size=(200, 3))
        h = M.RidgeHeadV2(3).fit(Z, Y, R, np.arange(120), np.arange(120, 160))
        self.assertEqual(h.status, "TRAINED")
        h.fit_residuals(Z, Y, R, np.arange(160, 200))
        P, Q = h.predict(Z[:4])
        self.assertEqual(P.shape, (4, 3, 3))
        np.testing.assert_allclose(P.sum(-1), 1.0)
        self.assertTrue((np.diff(Q, axis=-1) >= 0).all())

    def _model(self):
        mr = M.MiniRocketV2().configure(128, 840, 32).fit(_rw(8))
        Z = mr.transform(_rw(40, seed=2))
        r = np.random.default_rng(2)
        h = M.RidgeHeadV2(3).fit(Z, r.integers(0, 3, (40, 3)), r.normal(size=(40, 3)), np.arange(30), np.arange(30, 40))
        return mr, h

    def test_t120_export_import_and_rejections(self):
        mr, h = self._model()
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "exp"
            man = M.export_native(out, mr, h, [1.0, 1.1, 1.2], {"horizons": [3, 5, 15]})
            self.assertEqual(man["layout"]["F"], 840)
            mr2, h2, temps, _ = M.import_native(out)
            x = _rw(3, seed=5)
            np.testing.assert_array_equal(mr2.transform(x), mr.transform(x))
            np.testing.assert_allclose(h2.raw(mr2.transform(x))[0], h.raw(mr.transform(x))[0])
            self.assertEqual(temps, [1.0, 1.1, 1.2])
            M.export_native(out, mr, h, [1.0], {})                             # second export keeps .prev (last compatible)
            self.assertTrue((Path(d) / "exp.prev" / "model.bin").exists())
            raw = (out / "model.bin").read_bytes()
            bad = Path(d) / "bad.bin"
            for blob, err in ((raw[:-40], "CHECKSUM"), (raw[:30], "TRUNCATED|CHECKSUM")):
                bad.write_bytes(blob)
                with self.assertRaisesRegex(M.MRError, err):
                    M.read_model_bin(bad)
            body = bytearray(raw[:-32])
            struct.pack_into("<I", body, 8, 2)                                  # future version (valid checksum)
            import hashlib
            bad.write_bytes(bytes(body) + hashlib.sha256(bytes(body)).digest())
            with self.assertRaisesRegex(M.MRError, "UNSUPPORTED_VERSION"):
                M.read_model_bin(bad)
            body = bytearray(raw[:-32])
            struct.pack_into("<I", body, 12, 0x04030201)
            bad.write_bytes(bytes(body) + hashlib.sha256(bytes(body)).digest())
            with self.assertRaisesRegex(M.MRError, "ENDIAN"):
                M.read_model_bin(bad)
            body = bytearray(raw[:-32])
            struct.pack_into("<Q", body, 20 + 12, 10 ** 12)                     # absurd section length checked before allocation
            bad.write_bytes(bytes(body) + hashlib.sha256(bytes(body)).digest())
            with self.assertRaisesRegex(M.MRError, "BAD_SECTION_LENGTH"):
                M.read_model_bin(bad)
            with self.assertRaisesRegex(M.MRError, "TOO_LARGE"):
                M.read_model_bin(out / "model.bin", max_bytes=100)

    def test_t121_native_result_importer(self):
        with tempfile.TemporaryDirectory() as d:
            imp = M.NativeResultImporter(None, None, "XAUUSD-")
            self.assertEqual(imp.poll()["status"], "NATIVE_FEED_UNAVAILABLE")
            sha = "ab" * 32
            imp = M.NativeResultImporter(d, sha, "XAUUSD-", "M1", 120)
            now = time.time()
            p = Path(d) / M.NativeResultImporter.NAME
            M.write_result(p, 5, sha, "XAUUSD-", "M1", int(now) - 60, int(now), "BROKER_WALL_TIME", np.arange(12.0))
            r = imp.poll(now)
            self.assertEqual(r["status"], "IMPORTED")
            self.assertEqual(r["role"], "SHADOW_AUDIT")
            self.assertEqual(imp.poll(now)["status"], "STALE_SEQUENCE")             # same seq again
            M.write_result(p, 6, "cd" * 32, "XAUUSD-", "M1", int(now), int(now), "BROKER_WALL_TIME", np.zeros(12))
            self.assertEqual(imp.poll(now)["reason"], "MODEL_MISMATCH")
            M.write_result(p, 7, sha, "BTCUSD", "M1", int(now), int(now), "BROKER_WALL_TIME", np.zeros(12))
            self.assertEqual(imp.poll(now)["reason"], "CONTEXT_MISMATCH")
            M.write_result(p, 8, sha, "XAUUSD-", "M1", int(now), int(now) - 1000, "BROKER_WALL_TIME", np.zeros(12))
            self.assertEqual(imp.poll(now)["reason"], "RESULT_TOO_OLD")
            p.write_bytes(p.read_bytes()[:-1] + b"\x00")
            self.assertEqual(imp.poll(now)["status"], "REJECTED")

    def test_t122_benchmark_and_native_sources(self):
        b = M.benchmark(requested=840, n=30, warmup=3)
        self.assertEqual(b["n"], 30)
        self.assertEqual(len(b["raw_ms"]), 30)
        self.assertIn("p99", b["transform_ms"])
        root = Path(__file__).resolve().parents[1] / "mql5" / "MiniRocketV2"
        for f in ("Include/PMW/PMW_MR2_Core.mqh", "Include/PMW/PMW_MR2_Ridge.mqh", "Include/PMW/PMW_MR2_Format.mqh", "Scripts/PMW_MR2_SelfTest.mq5",
                  "Scripts/PMW_MR2_Fit.mq5", "Scripts/PMW_MR2_Infer.mq5", "Scripts/PMW_MR2_Benchmark.mq5", "Indicators/PMW_MR2_Indicator.mq5"):
            src = (root / f).read_text(encoding="utf-8")
            self.assertNotIn("OrderSend", src, f)
            self.assertNotIn("CTrade", src, f)
        self.assertFalse(list(root.rglob("*.ex5")), "żadnego fikcyjnego EX5")


if __name__ == "__main__":
    unittest.main()
