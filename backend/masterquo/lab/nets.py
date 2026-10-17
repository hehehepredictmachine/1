"""Small sequence networks in pure numpy (no torch in the target environment) - MQ-LAB-NN-1.0.0.

ResNet1D (M04)  : stem conv(k=3) -> B residual blocks [conv-ReLU-conv + identity, ReLU] -> global average pool -> linear
                  -> softmax. Exact backprop (verified by a numerical gradient check in tests). Optional ResNeXt-style
                  grouped first conv in blocks (`groups`).
SEW-SNN (M02/M03): spiking network over the time axis of the window. Layer 1 LIF on W1 x_t; SEW block: LIF on W2 s1_t and
                  the element-wise ADD connection o_t = s2_t + s1_t (identity on spikes - with W2 = 0 the block passes s1).
                  Readout = mean_t(o_t) -> linear (optionally two regime experts routed by a fixed, causal volatility flag =
                  the 'routing' element of M02, not a learned MoE). Training: BPTT with an arctan surrogate gradient; reset by
                  subtraction (the reset path is detached, a common, documented simplification).
"Energy-balanced" = an explicit penalty lambda * mean firing rate in the loss; the reported compute cost is the measured
synaptic operations (spikes x fan-out) per inference - not a hardware energy measurement.
No gradient update ever happens in inference (`predict` has no optimizer state).
"""
from __future__ import annotations

import time

import numpy as np

VERSION = "MQ-LAB-NN-1.0.0"


def softmax(z):
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


class Adam:
    def __init__(self, params: dict, lr=1e-3, b1=0.9, b2=0.999, eps=1e-8, wd=0.0):
        self.p, self.lr, self.b1, self.b2, self.eps, self.wd = params, lr, b1, b2, eps, wd
        self.m = {k: np.zeros_like(v) for k, v in params.items()}
        self.v = {k: np.zeros_like(v) for k, v in params.items()}
        self.t = 0

    def step(self, grads: dict):
        self.t += 1
        for k, g in grads.items():
            if self.wd and k.startswith("W"):
                g = g + self.wd * self.p[k]
            self.m[k] = self.b1 * self.m[k] + (1 - self.b1) * g
            self.v[k] = self.b2 * self.v[k] + (1 - self.b2) * g * g
            mh = self.m[k] / (1 - self.b1 ** self.t)
            vh = self.v[k] / (1 - self.b2 ** self.t)
            self.p[k] -= self.lr * mh / (np.sqrt(vh) + self.eps)


# ----------------------------------------------------------------------------- conv helpers ('same' padding, k=3)
def im2col(x, k=3):
    n, c, L = x.shape
    p = k // 2
    xp = np.pad(x, ((0, 0), (0, 0), (p, p)))
    cols = np.stack([xp[:, :, i:i + L] for i in range(k)], axis=2)      # n, c, k, L
    return cols.reshape(n, c * k, L)


def col2im(dcols, c, L, k=3):
    n = dcols.shape[0]
    p = k // 2
    d = dcols.reshape(n, c, k, L)
    dxp = np.zeros((n, c, L + 2 * p))
    for i in range(k):
        dxp[:, :, i:i + L] += d[:, :, i, :]
    return dxp[:, :, p:p + L]


def conv_fwd(x, W, b, groups=1):
    """x (n,c,L), W (f, c/groups*k), b (f,) -> (n,f,L)."""
    n, c, L = x.shape
    f = W.shape[0]
    if groups == 1:
        cols = im2col(x)
        return np.einsum("fk,nkl->nfl", W, cols) + b[None, :, None], (cols,)
    cg, fg = c // groups, f // groups
    outs, caches = [], []
    for g in range(groups):
        cols = im2col(x[:, g * cg:(g + 1) * cg])
        outs.append(np.einsum("fk,nkl->nfl", W[g * fg:(g + 1) * fg], cols))
        caches.append(cols)
    return np.concatenate(outs, axis=1) + b[None, :, None], tuple(caches)


def conv_bwd(dout, x, W, cache, groups=1):
    n, c, L = x.shape
    f = W.shape[0]
    db = dout.sum(axis=(0, 2))
    if groups == 1:
        cols = cache[0]
        dW = np.einsum("nfl,nkl->fk", dout, cols)
        dcols = np.einsum("fk,nfl->nkl", W, dout)
        return col2im(dcols, c, L), dW, db
    cg, fg = c // groups, f // groups
    dx = np.zeros_like(x)
    dW = np.zeros_like(W)
    for g in range(groups):
        cols = cache[g]
        dg = dout[:, g * fg:(g + 1) * fg]
        dW[g * fg:(g + 1) * fg] = np.einsum("nfl,nkl->fk", dg, cols)
        dcols = np.einsum("fk,nfl->nkl", W[g * fg:(g + 1) * fg], dg)
        dx[:, g * cg:(g + 1) * cg] = col2im(dcols, cg, L)
    return dx, dW, db


# ----------------------------------------------------------------------------- ResNet1D
class ResNet1D:
    architecture_id = "RESNET1D"

    def __init__(self, c_in: int, width: int = 16, blocks: int = 2, n_cls: int = 2, groups: int = 1, seed: int = 0):
        rng = np.random.default_rng(seed)
        self.cfg = {"c_in": c_in, "width": width, "blocks": blocks, "n_cls": n_cls, "groups": groups, "seed": seed}
        he = lambda fan: np.sqrt(2.0 / fan)  # noqa: E731
        self.p = {"Ws": rng.normal(0, he(c_in * 3), (width, c_in * 3)), "bs": np.zeros(width)}
        for i in range(blocks):
            self.p[f"Wa{i}"] = rng.normal(0, he(width // groups * 3), (width, width // groups * 3))
            self.p[f"ba{i}"] = np.zeros(width)
            self.p[f"Wb{i}"] = rng.normal(0, he(width * 3) * 0.1, (width, width * 3))   # small: block starts near identity
            self.p[f"bb{i}"] = np.zeros(width)
        self.p["Wo"] = rng.normal(0, np.sqrt(1.0 / width), (width, n_cls))
        self.p["bo"] = np.zeros(n_cls)

    def forward(self, x, keep=False):
        P, g = self.p, self.cfg["groups"]
        cache = {}
        z, cs = conv_fwd(x, P["Ws"], P["bs"])
        h = np.maximum(z, 0)
        cache["stem"] = (x, z, cs)
        acts = [("stem", h)]
        for i in range(self.cfg["blocks"]):
            za, ca = conv_fwd(h, P[f"Wa{i}"], P[f"ba{i}"], g)
            a = np.maximum(za, 0)
            zb, cb = conv_fwd(a, P[f"Wb{i}"], P[f"bb{i}"])
            s = zb + h
            out = np.maximum(s, 0)
            cache[i] = (h, za, ca, a, zb, cb, s)
            h = out
            acts.append((f"block{i}", h))
        pooled = h.mean(axis=2)
        logits = pooled @ P["Wo"] + P["bo"]
        cache["head"] = (h, pooled)
        return (logits, cache, acts) if keep else logits

    def loss_grad(self, x, y, l2: float = 0.0):
        logits, cache, _ = self.forward(x, keep=True)
        P, g = self.p, self.cfg["groups"]
        n = len(y)
        pr = softmax(logits)
        loss = -np.log(pr[np.arange(n), y] + 1e-12).mean() + 0.5 * l2 * sum((v * v).sum() for k, v in P.items() if k.startswith("W"))
        d = pr.copy()
        d[np.arange(n), y] -= 1
        d /= n
        G = {}
        h, pooled = cache["head"]
        G["Wo"] = pooled.T @ d
        G["bo"] = d.sum(0)
        dpool = d @ P["Wo"].T
        dh = np.repeat(dpool[:, :, None], h.shape[2], axis=2) / h.shape[2]
        for i in reversed(range(self.cfg["blocks"])):
            hin, za, ca, a, zb, cb, s = cache[i]
            ds = dh * (s > 0)
            da, G[f"Wb{i}"], G[f"bb{i}"] = conv_bwd(ds, a, P[f"Wb{i}"], cb)
            dza = da * (za > 0)
            dhin, G[f"Wa{i}"], G[f"ba{i}"] = conv_bwd(dza, hin, P[f"Wa{i}"], ca, g)
            dh = dhin + ds                                   # identity path
        x0, z, cs = cache["stem"]
        dz = dh * (z > 0)
        _, G["Ws"], G["bs"] = conv_bwd(dz, x0, P["Ws"], cs)
        if l2:
            for k in G:
                if k.startswith("W"):
                    G[k] = G[k] + l2 * P[k]
        return loss, G

    def predict_proba(self, x):
        return softmax(self.forward(x))

    def telemetry(self, x) -> dict:
        logits, _, acts = self.forward(x, keep=True)
        layers = [{"layer": name, "mean_activation": float(a.mean()), "l2_norm": float(np.sqrt((a ** 2).sum() / a.shape[0])),
                   "active_fraction": float((a > 0).mean())} for name, a in acts]
        return {"layer_summaries": layers, "spike_metrics": None, "raw_output": softmax(logits)[-1].tolist(),
                "macs_per_sample": self.macs(x.shape[2])}

    def macs(self, L: int) -> int:
        c = self.cfg
        w = c["width"]
        return int(L * 3 * (c["c_in"] * w + c["blocks"] * (w * w // c["groups"] + w * w)) + w * c["n_cls"])

    def describe(self) -> list[dict]:
        c = self.cfg
        out = [{"stage": "encoder", "name": "stem conv1d k=3", "shape": f"{c['c_in']}→{c['width']}"}]
        for i in range(c["blocks"]):
            out.append({"stage": "block", "name": f"residual block {i + 1}" + (f" (grupy={c['groups']}, ResNeXt)" if c["groups"] > 1 else ""),
                        "shape": f"{c['width']}→{c['width']} + tożsamość"})
        out += [{"stage": "pooling", "name": "global average pool", "shape": f"{c['width']}"},
                {"stage": "output", "name": "linear + softmax", "shape": f"{c['width']}→{c['n_cls']}"}]
        return out


# ----------------------------------------------------------------------------- SEW spiking network
def surrogate(v, theta, alpha=2.0):
    """d spike / d v (arctan surrogate)."""
    u = np.pi * alpha * (v - theta) / 2
    return alpha / 2 / (1 + u * u)


class SEWSNN:
    architecture_id = "SEW_SNN"

    def __init__(self, c_in: int, hidden: int = 24, n_cls: int = 2, beta: float = 0.9, theta: float = 1.0, router: bool = False,
                 energy_lambda: float = 0.0, seed: int = 0):
        rng = np.random.default_rng(seed)
        self.cfg = {"c_in": c_in, "hidden": hidden, "n_cls": n_cls, "beta": beta, "theta": theta, "router": router,
                    "energy_lambda": energy_lambda, "seed": seed}
        self.p = {"W1": rng.normal(0, 1.5 / np.sqrt(c_in), (c_in, hidden)), "b1": np.full(hidden, 0.05),
                  "W2": rng.normal(0, 0.5 / np.sqrt(hidden), (hidden, hidden)), "b2": np.zeros(hidden),
                  "Wo": rng.normal(0, 1 / np.sqrt(hidden), (hidden, n_cls)), "bo": np.zeros(n_cls)}
        if router:
            self.p["Wo2"] = rng.normal(0, 1 / np.sqrt(hidden), (hidden, n_cls))
            self.p["bo2"] = np.zeros(n_cls)

    def run(self, x, state=None):
        """x (n, T, c). Returns spikes/membranes for all steps and the final state (for streaming)."""
        P, c = self.p, self.cfg
        n, T, _ = x.shape
        H = c["hidden"]
        v1 = np.zeros((n, H)) if state is None else state["v1"].copy()
        v2 = np.zeros((n, H)) if state is None else state["v2"].copy()
        S1, S2, V1, V2 = (np.zeros((n, T, H)) for _ in range(4))
        for t in range(T):
            v1 = c["beta"] * v1 + x[:, t] @ P["W1"] + P["b1"]
            V1[:, t] = v1
            s1 = (v1 >= c["theta"]).astype(float)
            v1 = v1 - s1 * c["theta"]
            v2 = c["beta"] * v2 + s1 @ P["W2"] + P["b2"]
            V2[:, t] = v2
            s2 = (v2 >= c["theta"]).astype(float)
            v2 = v2 - s2 * c["theta"]
            S1[:, t], S2[:, t] = s1, s2
        return {"S1": S1, "S2": S2, "V1": V1, "V2": V2, "state": {"v1": v1, "v2": v2}}

    def _logits(self, O, regime=None):
        P = self.p
        r = O.mean(axis=1)
        if self.cfg["router"] and regime is not None:
            g = np.asarray(regime, float)[:, None]
            return (1 - g) * (r @ P["Wo"] + P["bo"]) + g * (r @ P["Wo2"] + P["bo2"]), r
        return r @ P["Wo"] + P["bo"], r

    def loss_grad(self, x, y, regime=None, l2: float = 0.0):
        P, c = self.p, self.cfg
        out = self.run(x)
        S1, S2, V1, V2 = out["S1"], out["S2"], out["V1"], out["V2"]
        O = S1 + S2                                          # SEW ADD
        logits, r = self._logits(O, regime)
        n, T, H = S1.shape
        pr = softmax(logits)
        rate = (S1.mean() + S2.mean()) / 2
        loss = -np.log(pr[np.arange(n), y] + 1e-12).mean() + c["energy_lambda"] * rate
        d = pr.copy()
        d[np.arange(n), y] -= 1
        d /= n
        G = {}
        if c["router"] and regime is not None:
            g = np.asarray(regime, float)[:, None]
            G["Wo"], G["bo"] = r.T @ (d * (1 - g)), (d * (1 - g)).sum(0)
            G["Wo2"], G["bo2"] = r.T @ (d * g), (d * g).sum(0)
            dr = (d * (1 - g)) @ P["Wo"].T + (d * g) @ P["Wo2"].T
        else:
            G["Wo"], G["bo"] = r.T @ d, d.sum(0)
            if "Wo2" in P:
                G["Wo2"], G["bo2"] = np.zeros_like(P["Wo2"]), np.zeros_like(P["bo2"])
            dr = d @ P["Wo"].T
        dO = np.repeat(dr[:, None, :], T, axis=1) / T
        e = c["energy_lambda"] / (2 * n * T * H)
        dS2 = dO + e
        dS1_direct = dO + e
        # BPTT layer 2 (reset path detached): v2_t = beta v2_{t-1} + s1_t W2 + b2
        G["W2"], G["b2"] = np.zeros_like(P["W2"]), np.zeros_like(P["b2"])
        dS1 = dS1_direct.copy()
        dv = np.zeros((n, H))
        for t in reversed(range(T)):
            dv = dS2[:, t] * surrogate(V2[:, t], c["theta"]) + c["beta"] * dv
            G["W2"] += S1[:, t].T @ dv
            G["b2"] += dv.sum(0)
            dS1[:, t] += dv @ P["W2"].T
        G["W1"], G["b1"] = np.zeros_like(P["W1"]), np.zeros_like(P["b1"])
        dv = np.zeros((n, H))
        for t in reversed(range(T)):
            dv = dS1[:, t] * surrogate(V1[:, t], c["theta"]) + c["beta"] * dv
            G["W1"] += x[:, t].T @ dv
            G["b1"] += dv.sum(0)
        if l2:
            for k in G:
                if k.startswith("W"):
                    G[k] = G[k] + l2 * P[k]
        return float(loss), G

    def predict_proba(self, x, regime=None, state=None):
        out = self.run(x, state)
        logits, _ = self._logits(out["S1"] + out["S2"], regime)
        return softmax(logits)

    def telemetry(self, x, regime=None) -> dict:
        out = self.run(x[-1:])
        S1, S2 = out["S1"][0], out["S2"][0]
        logits, _ = self._logits((out["S1"] + out["S2"]), None if regime is None else regime[-1:])
        syn = int(S1.sum() * (self.cfg["hidden"] + self.cfg["n_cls"]) + S2.sum() * self.cfg["n_cls"])
        k = min(16, S1.shape[1])
        return {"layer_summaries": [{"layer": "LIF-1", "firing_rate": float(S1.mean()), "membrane_mean": float(out["V1"][0].mean())},
                                    {"layer": "LIF-2 (SEW)", "firing_rate": float(S2.mean()), "membrane_mean": float(out["V2"][0].mean())}],
                "spike_metrics": {"threshold": self.cfg["theta"], "beta": self.cfg["beta"], "raster_l1": S1[-32:, :k].astype(int).tolist(),
                                  "raster_l2": S2[-32:, :k].astype(int).tolist(), "synaptic_ops": syn,
                                  "firing_rate_total": float((S1.mean() + S2.mean()) / 2)},
                "raw_output": softmax(logits)[0].tolist()}

    def describe(self) -> list[dict]:
        c = self.cfg
        out = [{"stage": "encoder", "name": "kodowanie wejścia: prąd W1·x_t (cechy w kroku czasu)", "shape": f"{c['c_in']}→{c['hidden']}"},
               {"stage": "block", "name": f"LIF-1 (β={c['beta']}, θ={c['theta']}, reset przez odjęcie)", "shape": f"{c['hidden']}"},
               {"stage": "block", "name": "LIF-2 + połączenie SEW ADD (s1+s2)", "shape": f"{c['hidden']}"},
               {"stage": "pooling", "name": "średnia po czasie", "shape": f"{c['hidden']}"},
               {"stage": "output", "name": "linear + softmax" + (" (2 eksperci wg reżimu zmienności)" if c["router"] else ""), "shape": f"{c['hidden']}→{c['n_cls']}"}]
        return out


def train(model, X, y, Xv=None, yv=None, *, epochs=30, lr=3e-3, batch=64, l2=1e-4, patience=5, seed=0, regime=None, regime_v=None,
          progress=None, cancel=None) -> dict:
    """Mini-batch Adam with early stopping on the inner validation loss. Returns the learning curve."""
    rng = np.random.default_rng(seed)
    opt = Adam(model.p, lr=lr)
    best, best_p, bad, curve = np.inf, None, 0, []
    t0 = time.perf_counter()
    for ep in range(epochs):
        if cancel is not None and cancel():
            break
        idx = rng.permutation(len(y))
        tl = []
        for s in range(0, len(idx), batch):
            b = idx[s:s + batch]
            kw = {"regime": regime[b]} if (regime is not None and isinstance(model, SEWSNN)) else {}
            loss, G = model.loss_grad(X[b], y[b], l2=l2, **kw)
            opt.step(G)
            tl.append(loss)
        vl = None
        if Xv is not None and len(yv):
            kw = {"regime": regime_v} if (regime_v is not None and isinstance(model, SEWSNN)) else {}
            pv = model.predict_proba(Xv, **kw)
            vl = float(-np.log(pv[np.arange(len(yv)), yv] + 1e-12).mean())
        curve.append({"epoch": ep + 1, "train_loss": float(np.mean(tl)), "val_loss": vl})
        if progress:
            progress(ep + 1, epochs)
        if vl is not None:
            if vl < best - 1e-4:
                best, bad = vl, 0
                best_p = {k: v.copy() for k, v in model.p.items()}
            else:
                bad += 1
                if bad >= patience:
                    break
    if best_p is not None:
        model.p.update(best_p)
    return {"curve": curve, "best_val_loss": None if best == np.inf else best, "seconds": round(time.perf_counter() - t0, 2)}
