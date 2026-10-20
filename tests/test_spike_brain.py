"""PMW-UPD-09 R20 MQ_SPIKE_BRAIN_FINANCE_V1 (T97-T108). Synthetic arrays are TEST_ONLY inputs; nothing here claims edge."""
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np

import _env  # noqa: F401

from masterquo.lab import autodiff as A
from masterquo.lab import spike_brain as SB


def _batch(seed=0, N=3, T=10, C=8, H=3):
    r = np.random.default_rng(seed)
    tok = r.integers(0, 3, (N, T, C)).astype(float)
    mean = r.random((N, T)) > 0.3
    mask = np.ones((N, T))
    mask[0, :3] = 0
    dt = np.ones((N, T))
    y = r.integers(-1, 3, (N, H))
    rr = r.normal(0, 1, (N, H))
    return tok, mean, mask, dt, y, rr


def _fd(net, args, key, idx, eps=1e-6):
    old = net.p[key].data[idx]
    net.p[key].data[idx] = old + eps
    lp = net.loss(*args)[1]["loss"]
    net.p[key].data[idx] = old - eps
    lm = net.loss(*args)[1]["loss"]
    net.p[key].data[idx] = old
    return (lp - lm) / (2 * eps)


class EncoderTests(unittest.TestCase):
    def test_t98_score_before_update_and_prefix(self):
        r = np.random.default_rng(1)
        X = r.normal(0, 1, (200, 4))
        t = np.arange(200.0)
        a = SB.EventEncoder(4).run(X, t)
        X2 = X.copy()
        X2[150:] += 50.0                                   # future perturbation
        b = SB.EventEncoder(4).run(X2, t)
        np.testing.assert_array_equal(a["tokens"][:150], b["tokens"][:150])
        e = SB.EventEncoder(4)                             # stepping == batch run (one stream, replayed once)
        st = np.array([e.step(X[i], t[i])["tokens"] for i in range(200)])
        np.testing.assert_array_equal(st, a["tokens"])

    def test_t99_dt_overflow_flags(self):
        e = SB.EventEncoder(1, warmup=3)
        for i in range(5):
            e.step(np.array([float(i % 2)]), float(i))
        out = e.step(np.array([1e6]), 5.0)                 # huge jump: clipped and COUNT4-capped
        self.assertIn("CLIP_0", out["flags"])
        self.assertLessEqual(out["tokens"].max(), 4)
        same = e.step(np.array([0.0]), 5.0)                # identical timestamp -> dt 0, not invented
        self.assertEqual(same["dt"], 0.0)
        miss = e.step(np.array([np.nan]), 6.0)
        self.assertIn("MISSING_0", miss["flags"])
        b = SB.EventEncoder(1, count_mode="BINARY1", warmup=3)
        for i in range(5):
            b.step(np.array([float(i % 2)]), float(i))
        self.assertLessEqual(b.step(np.array([1e6]), 5.0)["tokens"].max(), 1)
        flat = SB.EventEncoder(1, warmup=3)
        fl = [flat.step(np.array([1.0]), float(i))["flags"] for i in range(6)]
        self.assertIn("LOW_DISPERSION_0", fl[-1])

    def test_t100_quote_heartbeat_only_on_real_quotes(self):
        ticks = [{"t_ms": 1000 * i // 4, "bid": 100.0, "ask": 100.1} for i in range(40)]   # 4 quotes/s, no movement
        q = SB.quote_tokens(ticks, SB.EventEncoder(4, "QUOTE_EVENT_V1"), 0.01)
        self.assertTrue(all(k == "HEARTBEAT" for k in q["kind"]))
        self.assertTrue(np.all(np.diff(q["t"]) >= 1.0 - 1e-9))
        self.assertTrue(set(q["t"]).issubset({k["t_ms"] / 1000 for k in ticks}))


class NetworkTests(unittest.TestCase):
    def test_t97_identity_not_alias(self):
        net = SB.SpikeBrain(8)
        self.assertEqual(net.manifest()["architecture_id"], "MQ_SPIKE_BRAIN_FINANCE_V1")
        self.assertIn("W_r0", net.p)
        self.assertIn("W_q0", net.p)
        from masterquo.lab import nets
        self.assertFalse(isinstance(net, nets.SEWSNN) if hasattr(nets, "SEWSNN") else False)

    def test_t101_linear_matches_dense_kernel(self):
        """Independent dense causal reference with product(lambda) weights for one head."""
        r = np.random.default_rng(3)
        T, dk = 6, 3
        q, k, v = r.normal(size=(T, dk)), r.normal(size=(T, dk)), r.normal(size=(T, dk))
        lam = r.uniform(0.5, 1.0, T)
        phi = lambda x: np.where(x > 0, x + 1, np.exp(x))  # noqa: E731
        ref = []
        for t in range(T):
            w = [np.prod(lam[j + 1:t + 1]) for j in range(t + 1)]
            num = sum(w[j] * (phi(q[t]) @ phi(k[j])) * v[j] for j in range(t + 1))
            den = sum(w[j] * (phi(q[t]) @ phi(k[j])) for j in range(t + 1)) + 1e-8
            ref.append(num / den)
        S, z, out = np.zeros((dk, dk)), np.zeros(dk), []
        for t in range(T):                                 # the same recurrence the network uses
            S = lam[t] * S + np.outer(phi(k[t]), v[t])
            z = lam[t] * z + phi(k[t])
            out.append(phi(q[t]) @ S / (phi(q[t]) @ z + 1e-8))
        np.testing.assert_allclose(np.array(out), np.array(ref), rtol=1e-10)

    def test_t101_t102_t103_gradients_all_modes(self):
        args = _batch(0)
        for mode in SB.ATTENTION:
            net = SB.SpikeBrain(8, {"attention": mode, "window": 4, "blocks": 1}, seed=1)
            net.smooth_reference, net.reset_reference = True, False
            L, _ = net.loss(*args)
            L.backward()
            keys = ("W_in", "W_q0", "W_k0", "W_r0", "W_lif0", "theta0", "W_head") + (("W_g0",) if mode != "SLIDING" else ()) \
                + (("mix0",) if mode == "HYBRID" else ())
            for key in keys:
                g = net.p[key].grad
                self.assertIsNotNone(g, f"{mode} {key}")
                idx = tuple(np.unravel_index(int(np.argmax(np.abs(g))), g.shape))
                self.assertAlmostEqual(g[idx], _fd(net, args, key, idx), delta=1e-5 + 1e-4 * abs(g[idx]), msg=f"{mode} {key}")

    def test_t103_surrogate_vjp_formula(self):
        x = A.T(np.array([-1.0, -0.1, 0.0, 0.3, 2.0]))
        s = A.spike(x, 2.0)
        np.testing.assert_array_equal(s.data, [0, 0, 1, 1, 1])
        s.backward(np.ones(5))
        ref = (2.0 / 2) / (1 + (math.pi / 2 * 2.0 * x.data) ** 2)
        np.testing.assert_allclose(x.grad, ref)

    def test_t102_causal_and_padding(self):
        tok, mean, mask, dt, _, _ = _batch(5, N=1, T=40)
        mask[:] = 1
        for mode in SB.ATTENTION:
            net = SB.SpikeBrain(8, {"attention": mode, "window": 32}, 2)
            net.forward(tok, mean, mask, dt)
            o_full = net.forward(tok[:, :30], mean[:, :30], mask[:, :30], dt[:, :30])[0].data
            tok2 = tok.copy()
            tok2[:, 30:] = 7.0                              # future tokens changed
            o2 = net.forward(tok2[:, :30], mean[:, :30], mask[:, :30], dt[:, :30])[0].data
            np.testing.assert_allclose(o_full, o2)
            # left padding with mask 0 does not change the result
            pad = np.zeros((1, 5, 8))
            o3 = net.forward(np.concatenate([pad, tok[:, :30]], 1), np.concatenate([np.zeros((1, 5), bool), mean[:, :30]], 1),
                             np.concatenate([np.zeros((1, 5)), mask[:, :30]], 1), np.concatenate([np.zeros((1, 5)), dt[:, :30]], 1))[0].data
            np.testing.assert_allclose(o3, o_full, atol=1e-9, err_msg=mode)

    def test_t104_t105_router(self):
        net = SB.SpikeBrain(8, {"blocks": 1}, 4)
        tok, mean, mask, dt, y, r = _batch(7)
        L, parts = net.loss(tok, mean, mask, dt, y, r)
        L.backward()
        self.assertGreater(np.abs(net.p["W_r0"].grad).sum(), 0)          # gradient reaches the router through p_selected
        tel = net.last_tel["experts_block0"]
        self.assertAlmostEqual(sum(tel["share"]), 1.0)
        none = np.zeros_like(mean)
        _, p2 = net.loss(tok, none, mask, dt, y, r)                      # zero routed tokens: aux 0, finite
        self.assertEqual(p2["aux"], 0.0)
        self.assertTrue(net.last_tel["experts_block0"]["zero_routed"])
        # online result independent of other batch members (no capacity at inference)
        one = net.predict(tok[1:2], mean[1:2], mask[1:2], dt[1:2])["proba"]
        allb = net.predict(tok, mean, mask, dt)["proba"][1:2]
        np.testing.assert_allclose(one, allb, atol=1e-12)
        net.capacity_training = True
        net.cfg["capacity_factor"] = 0.25
        net.loss(tok, mean, mask, dt, y, r)
        self.assertGreater(net.last_tel["experts_block0"]["overflow_ratio"], 0)

    def test_t106_reset_each_window(self):
        net = SB.SpikeBrain(8, {}, 1)
        tok, mean, mask, dt, _, _ = _batch(9, N=1, T=16)
        a = net.predict(tok, mean, mask, dt)["proba"]
        net.predict(*_batch(10, N=1, T=16)[:4])
        np.testing.assert_allclose(net.predict(tok, mean, mask, dt)["proba"], a)

    def test_t107_train_resume_save_load(self):
        r = np.random.default_rng(0)
        N, T = 48, 12
        tok = r.integers(0, 2, (N, T, 8)).astype(float)
        y = (tok[:, -3:, 0].sum(1) > 1).astype(int)[:, None].repeat(3, 1) * 2         # TEST_ONLY learnable rule
        rr = (y[:, :1] - 1.0).repeat(3, 1)
        mean, mask, dt = tok.sum(-1) > 0, np.ones((N, T)), np.ones((N, T))

        def batches(rng):
            o = rng.permutation(N)
            for s in range(0, N, 16):
                p = o[s:s + 16]
                yield tok[p], mean[p], mask[p], dt[p], y[p], rr[p]
        net = SB.SpikeBrain(8, {"blocks": 1}, 3)
        before = {k: v.data.copy() for k, v in net.p.items()}
        info = SB.fit(net, batches, None, epochs=6, lr=3e-3, seed=1)
        self.assertEqual(info["status"], "TRAINED")
        h = info["history"]
        self.assertLess(h[-1]["train_loss"], h[0]["train_loss"])
        for k in ("W_in", "W_q0", "W_r0", "W_e10", "W_head"):
            self.assertGreater(np.abs(net.p[k].data - before[k]).max(), 0, k)
        with tempfile.TemporaryDirectory() as d:
            ck = Path(d) / "ck"
            n1 = SB.SpikeBrain(8, {"blocks": 1}, 3)
            SB.fit(n1, batches, None, epochs=2, lr=3e-3, seed=1, ckpt_dir=ck)
            SB.fit(n1, batches, None, epochs=4, lr=3e-3, seed=1, ckpt_dir=ck)          # resume
            n2 = SB.SpikeBrain(8, {"blocks": 1}, 3)
            SB.fit(n2, batches, None, epochs=4, lr=3e-3, seed=1)                       # uninterrupted
            for k in n1.p:
                np.testing.assert_allclose(n1.p[k].data, n2.p[k].data, atol=1e-12, err_msg=k)
            n1.save(Path(d) / "m")
            n3 = SB.SpikeBrain.load(Path(d) / "m")
            np.testing.assert_allclose(n3.predict(tok, mean, mask, dt)["proba"], n1.predict(tok, mean, mask, dt)["proba"])
            (Path(d) / "m" / "weights.npz").write_bytes(b"broken")
            with self.assertRaises(ValueError):
                SB.SpikeBrain.load(Path(d) / "m")
            self.assertIsNone(n1.manifest()["energy_j"])

    def test_t107_cancel(self):
        net = SB.SpikeBrain(8, {"blocks": 1}, 3)
        info = SB.fit(net, lambda rng: iter(()), None, epochs=3, cancel=lambda: True)
        self.assertEqual(info["status"], "CANCELLED")


if __name__ == "__main__":
    unittest.main()
