"""PMW-UPD-08 R18 SEW merge operators ADD / AND / IAND - T72-T79."""
import math
import unittest

import numpy as np

import _env  # noqa: F401
from _env import TempData

from masterquo.lab import structure_nets as SN

CFG = {"widths": [4, 8], "blocks_per_stage": 1, "cardinality": 2, "horizons": [3, 5]}


class TestOperators(unittest.TestCase):
    def test_t72_truth_tables_orientation(self):
        A = np.array([0., 0., 1., 1.])
        S = np.array([0., 1., 0., 1.])
        np.testing.assert_array_equal(SN.sew_merge_forward(A, S, "ADD"), [0, 1, 1, 2])
        np.testing.assert_array_equal(SN.sew_merge_forward(A, S, "AND"), [0, 0, 0, 1])
        np.testing.assert_array_equal(SN.sew_merge_forward(A, S, "IAND"), [0, 1, 0, 0])   # IAND(0,1)=1, IAND(1,0)=0

    def test_t73_identity_conditions(self):
        S = np.array([0., 1., 1., 0.])
        np.testing.assert_array_equal(SN.sew_merge_forward(np.zeros(4), S, "ADD"), S)
        np.testing.assert_array_equal(SN.sew_merge_forward(np.zeros(4), S, "IAND"), S)
        np.testing.assert_array_equal(SN.sew_merge_forward(np.ones(4), S, "AND"), S)
        self.assertFalse(np.array_equal(SN.sew_merge_forward(np.zeros(4), S, "AND"), S))

    def test_t74_partials_vs_reference(self):
        rng = np.random.default_rng(0)
        A, S, d = rng.random(6), rng.random(6), rng.normal(size=6)
        for op in SN.CONNECT_F:
            dA, dS = SN.sew_merge_backward(d, A, S, op)
            for i in range(6):
                for which, arr, g in (("A", A, dA), ("S", S, dS)):
                    x = arr.copy()
                    x[i] += 1e-6
                    up = np.sum(d * SN.sew_merge_forward(x if which == "A" else A, x if which == "S" else S, op))
                    x[i] -= 2e-6
                    dn = np.sum(d * SN.sew_merge_forward(x if which == "A" else A, x if which == "S" else S, op))
                    self.assertAlmostEqual((up - dn) / 2e-6, g[i], places=6)
        rng = np.random.default_rng(1)
        for op in SN.CONNECT_F:                                                     # full chain rule through the network (smooth reference)
            net = SN.StructureNet("MQ_SEW_RESNET1D_V2", 3, dict(CFG, connect_f=op, identity_init=False), seed=2)
            for k in net.p:
                if k.startswith("b_"):
                    net.p[k] = rng.normal(0, 0.3, net.p[k].shape)
            net.smooth_reference, net.reset_reference = True, False
            x, y, r = rng.normal(size=(2, 3, 6)), np.array([[0, 2], [1, -1]]), np.array([[0.3, np.nan], [-0.1, 0.5]])
            _, G = net.loss_grad(x, y, r)
            worst = 0
            for k in net.p:
                idx = np.unravel_index(np.argmax(np.abs(G[k])), G[k].shape)
                o = net.p[k][idx]
                net.p[k][idx] = o + 1e-6
                lp = net.loss_grad(x, y, r)[0]["loss"]
                net.p[k][idx] = o - 1e-6
                lm = net.loss_grad(x, y, r)[0]["loss"]
                net.p[k][idx] = o
                n = (lp - lm) / 2e-6
                worst = max(worst, abs(n - G[k][idx]) / (abs(n) + abs(G[k][idx]) + 1e-9))
            self.assertLess(worst, 1e-4, op)

    def test_t75_t77_identity_init_multistep_and_projection(self):
        x = np.random.default_rng(3).normal(size=(2, 3, 20))
        for op, want in (("AND", 1.0), ("IAND", 0.0), ("ADD", 0.0)):
            net = SN.StructureNet("MQ_SEW_RESNEXT_EB_V1", 3, dict(CFG, connect_f=op, identity_init=True), seed=1)
            st = net.block_stats(x)
            self.assertEqual(st[0]["branch_firing"], want, op)                   # verified by a real multi-step forward
            _, _, fc = net.forward(x)
            blk = fc["layers"][1]
            np.testing.assert_array_equal(blk[5], blk[4])                        # same-width block = identity at init
            self.assertTrue(fc["layers"][2][1]["proj"])                          # width change: projection, not identity
            self.assertEqual(net.manifest()["connect_f"], op)

    def test_t76_domain_guard(self):
        with self.assertRaises(ValueError):
            SN.StructureNet("MQ_RESNEXT1D_V2", 3, dict(CFG, connect_f="AND"))
        net = SN.StructureNet("MQ_SEW_RESNET1D_V2", 3, dict(CFG, connect_f="AND"), seed=1)
        net.blocks[0]["ops"] = net.blocks[0]["ops"][:-1]                          # drop the branch spike -> analogue A
        with self.assertRaises(ValueError) as cm:
            net.forward(np.random.default_rng(0).normal(size=(1, 3, 5)))
        self.assertIn("DOMAIN_MISMATCH", str(cm.exception))

    def test_t78_artifact_keeps_operator(self):
        td = TempData()
        try:
            d = _env.Path(td.dir)
            a = SN.StructureNet("MQ_SEW_RESNET1D_V2", 3, CFG, seed=1)
            a.save(d / "add")
            b = SN.StructureNet("MQ_SEW_RESNET1D_V2", 3, dict(CFG, connect_f="IAND"), seed=1)
            b.save(d / "iand")
            self.assertEqual(SN.StructureNet.load(d / "add").op, "ADD")
            self.assertEqual(SN.StructureNet.load(d / "iand").op, "IAND")
            with self.assertRaises(ValueError):
                SN.StructureNet.load(d / "add", {"connect_f": "AND"})
        finally:
            td.close()

    def test_t79_add_counts(self):
        net = SN.StructureNet("MQ_SEW_RESNET1D_V2", 3, dict(CFG, widths=[4, 4]), seed=5)
        for k in net.p:
            if k.startswith("b_"):
                net.p[k][:] = 3.0                                                 # everything fires
        st = net.block_stats(np.random.default_rng(1).normal(size=(2, 3, 8)))
        self.assertGreater(st[-1]["mean_output"], 1.0)                           # count-valued, not a binary spike
        self.assertLessEqual(st[-1]["fraction_nonzero"], 1.0)


if __name__ == "__main__":
    unittest.main()
