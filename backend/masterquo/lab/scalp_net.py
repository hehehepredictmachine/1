"""CAUSAL_MTF_TCN_V1 (PMW-UPD-04 Neural Scalp System) - small causal dilated TCN in pure numpy.

Branch M1 : 128 closed M1 x C channels -> 1x1 stem (16) -> 5 residual blocks, kernel 3, dilations 1,2,4,8,16
Branch M5 : 32 closed M5 x C channels  -> 1x1 stem (16) -> 3 residual blocks, dilations 1,2,4
Context   : M15/H1 last closed rows + SETUP_FEATURES + time -> dense 32 (ReLU) -> dense 16 (ReLU)
Fusion    : last time step of both encoders (16 + 16) + context 16 = 48 -> dense 32 (ReLU)
Heads     : per side (BUY = 0, SELL = 1): 32 -> 3 logits (TP1_FIRST, SL_FIRST, TIMEOUT) and 32 -> 1 expected net_R (MSE).
            Loss and gradient only through the head of the side of the sample.
Block     : out = ReLU(x + conv_d(ReLU(conv_d(x)))) with left padding (k-1)*d -> every output t depends only on inputs <= t.
            Receptive field of B blocks with two convs: 1 + 2*(k-1)*sum(d) -> 125 (M1) and 29 (M5).
Loss      : CE(events) + 0.2 * MSE(net_R) + L2 1e-4 (weights), global gradient-norm clipping 1.0, Adam (lab.nets.Adam).
One forward returns the outputs AND the layer telemetry (no extra forward for the panel). Inference never touches weights.
"""
from __future__ import annotations

import numpy as np

from .nets import Adam, softmax

ARCH_ID = "CAUSAL_MTF_TCN_V1"
CLASSES = ("TP1_FIRST", "SL_FIRST", "TIMEOUT")
DEFAULT_CFG = {"width": 16, "k": 3, "m1_len": 128, "m5_len": 32, "m1_dil": [1, 2, 4, 8, 16], "m5_dil": [1, 2, 4], "ctx_hidden": 32, "ctx_out": 16,
               "fusion": 32, "reg_weight": 0.2, "l2": 1e-4, "clip": 1.0}


# ----------------------------------------------------------------------------- causal dilated conv
def causal_cols(x, k, d):
    """x (n,c,L) -> cols (n, c*k, L); tap j looks back (k-1-j)*d steps (left zero padding)."""
    n, c, L = x.shape
    p = (k - 1) * d
    xp = np.pad(x, ((0, 0), (0, 0), (p, 0)))
    return np.stack([xp[:, :, j * d:j * d + L] for j in range(k)], axis=2).reshape(n, c * k, L)


def causal_uncols(dcols, c, L, k, d):
    n = dcols.shape[0]
    p = (k - 1) * d
    dd = dcols.reshape(n, c, k, L)
    dxp = np.zeros((n, c, L + p))
    for j in range(k):
        dxp[:, :, j * d:j * d + L] += dd[:, :, j, :]
    return dxp[:, :, p:]


def cconv_fwd(x, W, b, k, d):
    cols = causal_cols(x, k, d)
    return np.einsum("fk,nkl->nfl", W, cols) + b[None, :, None], cols


def cconv_bwd(dout, x, W, cols, k, d):
    dW = np.einsum("nfl,nkl->fk", dout, cols)
    db = dout.sum(axis=(0, 2))
    dx = causal_uncols(np.einsum("fk,nfl->nkl", W, dout), x.shape[1], x.shape[2], k, d)
    return dx, dW, db


def receptive_field(k: int, dils) -> int:
    return 1 + 2 * (k - 1) * int(sum(dils))


# ----------------------------------------------------------------------------- the network
class CausalMTFTCN:
    architecture_id = ARCH_ID

    def __init__(self, c_m1: int, c_m5: int, c_ctx: int, cfg: dict | None = None, seed: int = 17):
        self.cfg = {**DEFAULT_CFG, **(cfg or {}), "c_m1": c_m1, "c_m5": c_m5, "c_ctx": c_ctx, "seed": seed}
        c = self.cfg
        rng = np.random.default_rng(seed)
        w, k = c["width"], c["k"]
        he = lambda fan: np.sqrt(2.0 / fan)  # noqa: E731
        P = {}
        for br, cin, dils in (("m1", c_m1, c["m1_dil"]), ("m5", c_m5, c["m5_dil"])):
            P[f"W_{br}_stem"] = rng.normal(0, he(cin), (w, cin))
            P[f"b_{br}_stem"] = np.zeros(w)
            for i, _ in enumerate(dils):
                P[f"W_{br}_{i}a"] = rng.normal(0, he(w * k), (w, w * k))
                P[f"b_{br}_{i}a"] = np.zeros(w)
                P[f"W_{br}_{i}b"] = rng.normal(0, he(w * k) * 0.1, (w, w * k))       # block starts near identity
                P[f"b_{br}_{i}b"] = np.zeros(w)
        P["W_ctx1"] = rng.normal(0, he(c_ctx), (c_ctx, c["ctx_hidden"]))
        P["b_ctx1"] = np.zeros(c["ctx_hidden"])
        P["W_ctx2"] = rng.normal(0, he(c["ctx_hidden"]), (c["ctx_hidden"], c["ctx_out"]))
        P["b_ctx2"] = np.zeros(c["ctx_out"])
        fin = 2 * w + c["ctx_out"]
        P["W_fuse"] = rng.normal(0, he(fin), (fin, c["fusion"]))
        P["b_fuse"] = np.zeros(c["fusion"])
        for s in (0, 1):
            P[f"W_cls{s}"] = rng.normal(0, np.sqrt(1.0 / c["fusion"]), (c["fusion"], 3))
            P[f"b_cls{s}"] = np.zeros(3)
            P[f"W_reg{s}"] = rng.normal(0, np.sqrt(1.0 / c["fusion"]) * 0.1, (c["fusion"], 1))
            P[f"b_reg{s}"] = np.zeros(1)
        self.p = P

    # -------------------------------------------------- forward
    def _branch(self, x, br, dils, cache, acts):
        P, k = self.p, self.cfg["k"]
        z = np.einsum("fc,ncl->nfl", P[f"W_{br}_stem"], x) + P[f"b_{br}_stem"][None, :, None]
        h = z                                                    # linear 1x1 stem (projection), ReLU inside the blocks
        cache[f"{br}_stem"] = (x,)
        acts.append((f"{br}_stem", h))
        for i, d in enumerate(dils):
            za, ca = cconv_fwd(h, P[f"W_{br}_{i}a"], P[f"b_{br}_{i}a"], k, d)
            a = np.maximum(za, 0)
            zb, cb = cconv_fwd(a, P[f"W_{br}_{i}b"], P[f"b_{br}_{i}b"], k, d)
            s = h + zb
            out = np.maximum(s, 0)
            cache[f"{br}_{i}"] = (h, za, ca, a, cb, s, d)
            h = out
            acts.append((f"{br}_block{i + 1}_d{d}", h))
        return h

    def forward(self, xm1, xm5, xc, side, keep=False):
        """side: int array (0 BUY / 1 SELL). Returns logits (n,3), net_r (n,) [+ cache, activations]."""
        P, c = self.p, self.cfg
        cache, acts = {}, []
        h1 = self._branch(xm1, "m1", c["m1_dil"], cache, acts)
        h5 = self._branch(xm5, "m5", c["m5_dil"], cache, acts)
        zc1 = xc @ P["W_ctx1"] + P["b_ctx1"]
        c1 = np.maximum(zc1, 0)
        zc2 = c1 @ P["W_ctx2"] + P["b_ctx2"]
        c2 = np.maximum(zc2, 0)
        acts += [("ctx_dense1", c1), ("ctx_dense2", c2)]
        f_in = np.concatenate([h1[:, :, -1], h5[:, :, -1], c2], axis=1)
        zf = f_in @ P["W_fuse"] + P["b_fuse"]
        f = np.maximum(zf, 0)
        acts.append(("fusion", f))
        side = np.asarray(side, dtype=int)
        logits = np.zeros((len(side), 3))
        net = np.zeros(len(side))
        for s in (0, 1):
            m = side == s
            if m.any():
                logits[m] = f[m] @ P[f"W_cls{s}"] + P[f"b_cls{s}"]
                net[m] = (f[m] @ P[f"W_reg{s}"] + P[f"b_reg{s}"])[:, 0]
        if not keep:
            return logits, net
        cache.update(ctx=(xc, zc1, c1, zc2), fuse=(f_in, zf, f), h1=h1, h5=h5)
        acts.append(("head_logits", logits))
        return logits, net, cache, acts

    # -------------------------------------------------- loss + exact gradient
    def _branch_bwd(self, dh, br, dils, cache, G):
        P, k = self.p, self.cfg["k"]
        for i in reversed(range(len(dils))):
            hin, za, ca, a, cb, s, d = cache[f"{br}_{i}"]
            ds = dh * (s > 0)
            da, G[f"W_{br}_{i}b"], G[f"b_{br}_{i}b"] = cconv_bwd(ds, a, P[f"W_{br}_{i}b"], cb, k, d)
            dza = da * (za > 0)
            dhin, G[f"W_{br}_{i}a"], G[f"b_{br}_{i}a"] = cconv_bwd(dza, hin, P[f"W_{br}_{i}a"], ca, k, d)
            dh = dhin + ds
        (x,) = cache[f"{br}_stem"]
        G[f"W_{br}_stem"] = np.einsum("nfl,ncl->fc", dh, x)
        G[f"b_{br}_stem"] = dh.sum(axis=(0, 2))

    def loss_grad(self, xm1, xm5, xc, side, y, r, w_reg: float | None = None, l2: float | None = None):
        c, P = self.cfg, self.p
        w_reg = c["reg_weight"] if w_reg is None else w_reg
        l2 = c["l2"] if l2 is None else l2
        logits, net, cache, _ = self.forward(xm1, xm5, xc, side, keep=True)
        n = len(y)
        side = np.asarray(side, dtype=int)
        pr = softmax(logits)
        ce = float(-np.log(pr[np.arange(n), y] + 1e-12).mean())
        mse = float(np.mean((net - r) ** 2))
        reg = 0.5 * l2 * sum(float((v * v).sum()) for kk, v in P.items() if kk.startswith("W"))
        dlog = pr.copy()
        dlog[np.arange(n), y] -= 1
        dlog /= n
        dnet = w_reg * 2 * (net - r) / n
        f_in, zf, f = cache["fuse"]
        G = {}
        df = np.zeros_like(f)
        for s in (0, 1):
            m = side == s
            G[f"W_cls{s}"] = f[m].T @ dlog[m]
            G[f"b_cls{s}"] = dlog[m].sum(0)
            G[f"W_reg{s}"] = f[m].T @ dnet[m][:, None]
            G[f"b_reg{s}"] = np.array([dnet[m].sum()])
            df[m] = dlog[m] @ P[f"W_cls{s}"].T + dnet[m][:, None] @ P[f"W_reg{s}"].T
        dzf = df * (zf > 0)
        G["W_fuse"] = f_in.T @ dzf
        G["b_fuse"] = dzf.sum(0)
        dfin = dzf @ P["W_fuse"].T
        w = c["width"]
        xc, zc1, c1, zc2 = cache["ctx"]
        dzc2 = dfin[:, 2 * w:] * (zc2 > 0)
        G["W_ctx2"] = c1.T @ dzc2
        G["b_ctx2"] = dzc2.sum(0)
        dzc1 = (dzc2 @ P["W_ctx2"].T) * (zc1 > 0)
        G["W_ctx1"] = xc.T @ dzc1
        G["b_ctx1"] = dzc1.sum(0)
        for br, sl, h in (("m1", slice(0, w), cache["h1"]), ("m5", slice(w, 2 * w), cache["h5"])):
            dh = np.zeros_like(h)
            dh[:, :, -1] = dfin[:, sl]
            self._branch_bwd(dh, br, c[f"{br}_dil"], cache, G)
        if l2:
            for kk in G:
                if kk.startswith("W"):
                    G[kk] = G[kk] + l2 * P[kk]
        return {"loss": ce + w_reg * mse + reg, "ce": ce, "mse": mse, "l2": reg}, G

    # -------------------------------------------------- inference + telemetry (one forward)
    def predict(self, xm1, xm5, xc, side) -> dict:
        logits, net = self.forward(xm1, xm5, xc, side)
        return {"logits": logits, "proba": softmax(logits), "net_r": net}

    def infer_with_telemetry(self, xm1, xm5, xc, side, heat_t: int = 32, heat_c: int = 16) -> dict:
        """Batch of 1 (or more; telemetry of sample 0). Outputs and layer statistics come from THIS forward."""
        logits, net, _, acts = self.forward(xm1, xm5, xc, side, keep=True)
        layers = []
        for name, a in acts:
            a0 = np.asarray(a[0], dtype=float)
            ent = {"layer_id": name, "mean": float(a0.mean()), "std": float(a0.std()), "mean_abs": float(np.abs(a0).mean()),
                   "l2_norm": float(np.sqrt((a0 ** 2).sum())), "finite_fraction": float(np.isfinite(a0).mean())}
            if name != "head_logits" and not name.endswith("_stem"):
                ent["active_fraction"] = float((a0 > 0).mean())
            if a0.ndim == 2:
                hm = a0[:heat_c, -heat_t:]
                ent["heatmap"] = {"values": np.round(hm, 4).tolist(), "sampled_channel_ids": list(range(hm.shape[0])),
                                  "sampled_times": list(range(-hm.shape[1] + 1, 1)), "aggregation": "none (kanał × krok)",
                                  "vmin": float(hm.min()), "vmax": float(hm.max())}
            layers.append(ent)
        return {"logits": logits, "proba": softmax(logits), "net_r": net, "layers": layers}

    def context_telemetry(self, xm1, xm5) -> list[dict]:
        """Encoders only (no candidate -> no head output, CONTEXT_ONLY)."""
        cache, acts = {}, []
        self._branch(xm1, "m1", self.cfg["m1_dil"], cache, acts)
        self._branch(xm5, "m5", self.cfg["m5_dil"], cache, acts)
        return [{"layer_id": n, "mean": float(a[0].mean()), "std": float(a[0].std()), "mean_abs": float(np.abs(a[0]).mean()),
                 "l2_norm": float(np.sqrt((a[0] ** 2).sum())), "finite_fraction": float(np.isfinite(a[0]).mean()),
                 **({} if n.endswith("_stem") else {"active_fraction": float((a[0] > 0).mean())})} for n, a in acts]

    # -------------------------------------------------- description
    def n_params(self) -> int:
        return int(sum(v.size for v in self.p.values()))

    def macs(self) -> int:
        c = self.cfg
        w, k = c["width"], c["k"]
        m = c["m1_len"] * (c["c_m1"] * w + len(c["m1_dil"]) * 2 * w * w * k) + c["m5_len"] * (c["c_m5"] * w + len(c["m5_dil"]) * 2 * w * w * k)
        m += c["c_ctx"] * c["ctx_hidden"] + c["ctx_hidden"] * c["ctx_out"] + (2 * w + c["ctx_out"]) * c["fusion"] + c["fusion"] * 4
        return int(m)

    def architecture(self) -> dict:
        c, P = self.cfg, self.p
        w, k = c["width"], c["k"]
        nodes = [{"layer_id": "in_m1", "name": "Wejście M1", "operation": "input", "shape_in": None, "shape_out": [c["c_m1"], c["m1_len"]], "params": 0, "area": "DANE"},
                 {"layer_id": "in_m5", "name": "Wejście M5", "operation": "input", "shape_in": None, "shape_out": [c["c_m5"], c["m5_len"]], "params": 0, "area": "DANE"},
                 {"layer_id": "in_ctx", "name": "Kontekst M15/H1 + setup", "operation": "input", "shape_in": None, "shape_out": [c["c_ctx"]], "params": 0, "area": "DANE"}]
        edges = []
        for br, dils, L in (("m1", c["m1_dil"], c["m1_len"]), ("m5", c["m5_dil"], c["m5_len"])):
            nodes.append({"layer_id": f"{br}_stem", "name": f"{br.upper()} stem 1×1", "operation": "conv1x1", "shape_in": [c[f"c_{br}"], L], "shape_out": [w, L],
                          "params": int(P[f"W_{br}_stem"].size + w), "area": "PRZETWARZANIE"})
            edges.append({"source_layer_id": f"in_{br}", "target_layer_id": f"{br}_stem", "connection_type": "data"})
            prev = f"{br}_stem"
            rf = 1
            for i, d in enumerate(dils):
                rf += 2 * (k - 1) * d
                lid = f"{br}_block{i + 1}_d{d}"
                nodes.append({"layer_id": lid, "name": f"{br.upper()} blok {i + 1}", "operation": "causal residual block (2× conv k=3)", "dilation": d,
                              "receptive_field": rf, "shape_in": [w, L], "shape_out": [w, L], "params": int(2 * (w * w * k + w)), "area": "PRZETWARZANIE"})
                edges.append({"source_layer_id": prev, "target_layer_id": lid, "connection_type": "residual"})
                prev = lid
            edges.append({"source_layer_id": prev, "target_layer_id": "fusion", "connection_type": "last_step"})
        nodes += [{"layer_id": "ctx_dense1", "name": "Kontekst dense", "operation": "dense+ReLU", "shape_in": [c["c_ctx"]], "shape_out": [c["ctx_hidden"]],
                   "params": int(P["W_ctx1"].size + c["ctx_hidden"]), "area": "PRZETWARZANIE"},
                  {"layer_id": "ctx_dense2", "name": "Kontekst dense 2", "operation": "dense+ReLU", "shape_in": [c["ctx_hidden"]], "shape_out": [c["ctx_out"]],
                   "params": int(P["W_ctx2"].size + c["ctx_out"]), "area": "PRZETWARZANIE"},
                  {"layer_id": "fusion", "name": "Fuzja", "operation": "dense+ReLU", "shape_in": [2 * w + c["ctx_out"]], "shape_out": [c["fusion"]],
                   "params": int(P["W_fuse"].size + c["fusion"]), "area": "PRZETWARZANIE"}]
        edges += [{"source_layer_id": "in_ctx", "target_layer_id": "ctx_dense1", "connection_type": "data"},
                  {"source_layer_id": "ctx_dense1", "target_layer_id": "ctx_dense2", "connection_type": "dense"},
                  {"source_layer_id": "ctx_dense2", "target_layer_id": "fusion", "connection_type": "dense"}]
        for s, nm in ((0, "LONG"), (1, "SHORT")):
            for kind, out, opn in (("cls", 3, "dense → 3 logity (TP1/SL/TIMEOUT)"), ("reg", 1, "dense → net_R (MSE)")):
                lid = f"head_{kind}_{nm}"
                nodes.append({"layer_id": lid, "name": f"Głowica {nm} {'zdarzenia' if kind == 'cls' else 'net_R'}", "operation": opn,
                              "shape_in": [c["fusion"]], "shape_out": [out], "params": int(P[f"W_{kind}{s}"].size + out), "area": "WYNIK"})
                edges.append({"source_layer_id": "fusion", "target_layer_id": lid, "connection_type": "head"})
        return {"architecture_id": ARCH_ID, "nodes": nodes, "edges": edges, "params_total": self.n_params(), "macs_per_inference": self.macs(),
                "receptive_field": {"M1": receptive_field(k, c["m1_dil"]), "M5": receptive_field(k, c["m5_dil"])}}


# ----------------------------------------------------------------------------- training
def clip_grads(G: dict, max_norm: float) -> float:
    tot = float(np.sqrt(sum(float((g * g).sum()) for g in G.values())))
    if max_norm and tot > max_norm:
        s = max_norm / (tot + 1e-12)
        for k in G:
            G[k] = G[k] * s
    return tot


def fit(net: CausalMTFTCN, data: dict, idx: np.ndarray, val_idx: np.ndarray | None = None, *, epochs: int = 60, batch: int = 64, lr: float = 1e-3,
        patience: int = 7, seed: int = 17, fixed_epochs: int | None = None, log=None, cancel=None) -> dict:
    """Adam, chronological validation for early stopping (val_idx), or a fixed number of epochs (refit). Shuffling only inside
    the already separated training block. Returns the history; the network keeps the best (or last fixed) weights."""
    opt = Adam(net.p, lr=lr)
    rng = np.random.default_rng(seed)
    hist, best, best_p, bad = [], None, None, 0
    n_ep = fixed_epochs or epochs
    for ep in range(n_ep):
        if cancel is not None and cancel():
            break
        order = rng.permutation(idx)
        comp = {"loss": 0.0, "ce": 0.0, "mse": 0.0}
        for b0 in range(0, len(order), batch):
            bi = order[b0:b0 + batch]
            L, G = net.loss_grad(data["m1"][bi], data["m5"][bi], data["ctx"][bi], data["side"][bi], data["y"][bi], data["r"][bi])
            clip_grads(G, net.cfg["clip"])
            opt.step(G)
            for k in comp:
                comp[k] += L[k] * len(bi) / len(order)
        rec = {"epoch": ep + 1, "train_loss": comp["loss"], "train_ce": comp["ce"], "train_mse": comp["mse"]}
        if val_idx is not None and len(val_idx) and not fixed_epochs:
            L, _ = net.loss_grad(data["m1"][val_idx], data["m5"][val_idx], data["ctx"][val_idx], data["side"][val_idx], data["y"][val_idx], data["r"][val_idx])
            rec.update(val_loss=L["loss"], val_ce=L["ce"], val_mse=L["mse"])
            if best is None or L["loss"] < best - 1e-6:
                best, best_p, bad = L["loss"], {k: v.copy() for k, v in net.p.items()}, 0
                rec["best"] = True
            else:
                bad += 1
        hist.append(rec)
        if log:
            log(rec)
        if val_idx is not None and not fixed_epochs and bad >= patience:
            break
    if best_p is not None:
        net.p.update(best_p)
    best_epoch = max((h["epoch"] for h in hist if h.get("best")), default=len(hist))
    return {"history": hist, "best_epoch": best_epoch, "epochs_run": len(hist)}


# ----------------------------------------------------------------------------- calibration (temperature on log P, per side)
def temperature(logp: np.ndarray, y: np.ndarray) -> dict:
    if len(y) < 30 or len(set(y.tolist())) < 3:
        return {"T": 1.0, "status": "CALIBRATION_UNVERIFIED", "n": int(len(y))}
    grid = np.exp(np.linspace(np.log(0.25), np.log(4.0), 81))
    best = min(grid, key=lambda T: -np.mean(np.log(softmax(logp / T)[np.arange(len(y)), y] + 1e-12)))
    return {"T": float(best), "status": "FITTED_ON_CALIBRATION", "n": int(len(y))}


def apply_temperature(proba: np.ndarray, T: float) -> np.ndarray:
    return softmax(np.log(np.clip(proba, 1e-12, 1.0)) / T)
