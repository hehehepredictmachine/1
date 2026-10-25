"""STE-FlowNet-inspired financial event model (PMW-MM-STEFLOW-1). TRAINABLE. Not a reproduction of STE-FlowNet (event-camera optical flow).

Source mechanism -> financial adaptation (see docs/MASTER_MODELE_AUDYT_INTEGRACJA_PL.md for the full mapping):
  * N count-based event splits + Gaussian temporal weighting (RETAINED): per split of M events with timestamps t_i, mu/sigma of the
    split's own timestamps, k_g(t_i) = lam/(sqrt(2pi) sigma) exp(-(t_i-mu)^2/(2 sigma^2)), lam = M / sum k_g (weights sum to M);
    sigma ~ 0 (repeated timestamps) -> uniform weights. Count-like channels (inferred up/down polarity counts) are accumulated with the
    source-style ceiling; real-valued channels (sum dmid, sum |dmid|, mean spread, mean dt_log, mean activity) use FLOAT weighting.
  * Image H x W / pixel coordinates (NOT APPLICABLE): no pseudo-spatial axis is invented - the tensor is [B, N splits, 7 channels]
    (a 1D adaptation along the split/time axis; downsampling only along time).
  * Dual pyramid (ADAPTED): feed-forward causal conv path + recurrent GRU path at two temporal scales (N and N/2).
  * Correlation layer (ADAPTED): flow-warped spatial correlation -> causal LAGGED feature correlation c_l(t) = <f_t, f_{t-l}>/sqrt(C),
    l = 1..L, injected into the GRU input (the reference is always the model's own past features; zero before the window start).
  * Encoder-decoder + skip (ADAPTED): level-2 GRU output upsampled (repeat x2) and concatenated with the level-1 GRU output.
  * Intermediate predictions (ADAPTED): an auxiliary head on level 2; outputs are future log returns, not flow fields.
  * Iterative residual refinement (RETAINED): f_0 = 0, f_k = f_{k-1} + Delta(d_last, f_{k-1}) with ONE shared block, K iterations.
  * Photometric warp loss + smoothness (NOT APPLICABLE: no grayscale frames) -> Huber loss on the standardised future mid log return
    y = ln(mid_{e+h}/mid_e) (h events ahead), deep supervision 0.5^(K-k) on refinement iterates + lambda_aux on the level-2 head.
Ablations share the same code path: no temporal weighting, no recurrence (GRU -> identity on the FF features), no correlation, K = 1.
Streaming: the state is the bounded window of the last N*M accepted events of the current segment (reset at gaps); the network is
re-evaluated over that window (O(N) per new split) - identical to the offline sample construction (parity-tested).
"""
from __future__ import annotations

import math
import time

import numpy as np

from ..lab import autodiff as A

VERSION = "PMW-MM-STEFLOW-1"
CHANNELS = ["up_count", "down_count", "sum_dmid", "sum_absdmid", "spread_mean", "dt_mean", "act_mean"]


def gaussian_weights(t: np.ndarray) -> tuple[np.ndarray, str]:
    M = len(t)
    if M == 0:
        return np.zeros(0), "EMPTY"
    if M == 1:
        return np.ones(1), "SINGLE"
    mu, sd = float(np.mean(t)), float(np.std(t))
    if sd < 1e-9 * max(1.0, abs(mu)):
        return np.ones(M), "ZERO_TIME_VARIANCE"
    k = np.exp(-((t - mu) ** 2) / (2 * sd * sd)) / (math.sqrt(2 * math.pi) * sd)
    lam = M / k.sum()
    return lam * k, "OK"


def split_repr(t, dmid, spread, dtl, act, weighting: bool = True) -> np.ndarray:
    w, _ = gaussian_weights(np.asarray(t, float)) if weighting else (np.ones(len(t)), "OFF")
    up, dn = (dmid > 0).astype(float), (dmid < 0).astype(float)
    return np.array([math.ceil(float((w * up).sum()) - 1e-9), math.ceil(float((w * dn).sum()) - 1e-9), float((w * dmid).sum()),
                     float((w * np.abs(dmid)).sum()), float((w * spread).sum() / len(t)), float((w * dtl).sum() / len(t)), float((w * act).sum() / len(t))])


def build_samples(acc: dict, feats: dict, N: int = 8, M: int = 16, h: int = 32, weighting: bool = True, stride: int | None = None) -> dict:
    """One sample per split boundary: window = last N*M valid events of one segment, target = ln(mid[e+h]/mid[e]) (same segment)."""
    t, mid, seg = acc["t"], acc["mid"], acc["segment"]
    F, valid = feats["F"], feats["valid"]
    names = feats["names"]
    j_dm, j_sp, j_dt, j_ac, j_ok = (names.index(k) for k in ("dmid", "spread", "dt_log", "act_log", "spread_ok"))
    vidx = np.where(valid)[0]
    W = N * M
    stride = stride or M
    X, y, te, tl, ends = [], [], [], [], []
    for k in range(W - 1, len(vidx), stride):
        blk = vidx[k - W + 1:k + 1]
        e = blk[-1]
        if seg[blk[0]] != seg[e] or np.any(np.diff(blk) != 1):
            continue
        reps = []
        for s in range(N):
            b = blk[s * M:(s + 1) * M]
            sp = np.where(F[b, j_ok] > 0, F[b, j_sp], 0.0)
            reps.append(split_repr(t[b], F[b, j_dm], sp, F[b, j_dt], F[b, j_ac], weighting))
        tgt = e + h
        if tgt >= len(t) or seg[tgt] != seg[e]:
            yy, tlab = np.nan, np.nan
        else:
            yy, tlab = math.log(mid[tgt] / mid[e]), t[tgt]
        X.append(reps)
        y.append(yy)
        te.append(t[e])
        tl.append(tlab)
        ends.append(e)
    return {"X": np.asarray(X), "y": np.asarray(y), "t_obs": np.asarray(te), "t_label": np.asarray(tl), "end_event": np.asarray(ends),
            "N": N, "M": M, "h": h, "weighting": weighting}


class STEModel:
    def __init__(self, cin: int = 7, C1: int = 12, C2: int = 12, L: int = 2, Hr: int = 12, K: int = 3, seed: int = 5,
                 recurrence: bool = True, correlation: bool = True):
        g = np.random.Generator(np.random.PCG64(seed))
        w = lambda a, b: g.normal(0, 1 / math.sqrt(a), (a, b))  # noqa: E731
        self.cfg = dict(cin=cin, C1=C1, C2=C2, L=L, Hr=Hr, K=K, recurrence=recurrence, correlation=correlation)
        P = {"Wc1": w(3 * cin, C1), "bc1": np.zeros(C1), "Wc2": w(3 * C1, C2), "bc2": np.zeros(C2),
             "Wd": w(C1 + C2, C1), "bd": np.zeros(C1), "Wa": w(C2, 1) * 0.1, "ba": np.zeros(1),
             "Rw1": w(C1 + 1, Hr), "Rb1": np.zeros(Hr), "Rw2": w(Hr, 1) * 0.1, "Rb2": np.zeros(1)}
        for lvl, C in (("1", C1), ("2", C2)):                              # GRU gates z/r/n of level 1/2 (names never reused)
            ci = C + L
            for gname in ("z", "r", "n"):
                P[f"W{gname}{lvl}"], P[f"U{gname}{lvl}"], P[f"b{gname}{lvl}"] = w(ci, C), w(C, C), np.zeros(C)
        self.p = {k: A.T(v) for k, v in P.items()}
        self.y_scale = 1.0

    def n_params(self) -> int:
        return int(sum(v.data.size for v in self.p.values()))

    # ---------------------------------------------------------------- blocks
    @staticmethod
    def _conv(x: A.T, W: A.T, b: A.T) -> A.T:
        B, N, C = x.data.shape
        xp = A.concat([A.T(np.zeros((B, 2, C))), x], axis=1)
        cols = A.concat([xp[:, 0:N], xp[:, 1:N + 1], xp[:, 2:N + 2]], axis=2)
        return A.relu(cols @ W + b)

    def _corr(self, f: A.T) -> A.T:
        B, N, C = f.data.shape
        out = []
        for l in range(1, self.cfg["L"] + 1):  # noqa: E741
            if not self.cfg["correlation"]:
                out.append(A.T(np.zeros((B, N, 1))))
                continue
            sh = A.concat([A.T(np.zeros((B, l, C))), f[:, : N - l]], axis=1)
            out.append(((f * sh).sum(axis=2) * (1.0 / math.sqrt(C))).reshape(B, N, 1))
        return A.concat(out, axis=2)

    def _gru(self, f: A.T, c: A.T, lvl: str) -> A.T:
        if not self.cfg["recurrence"]:
            return f
        p = self.p
        B, N, C = f.data.shape
        h = A.T(np.zeros((B, C)))
        hs = []
        for t in range(N):
            x = A.concat([f[:, t], c[:, t]], axis=1)
            z = A.sigmoid(x @ p["Wz" + lvl] + h @ p["Uz" + lvl] + p["bz" + lvl])
            r = A.sigmoid(x @ p["Wr" + lvl] + h @ p["Ur" + lvl] + p["br" + lvl])
            n = A.tanh(x @ p["Wn" + lvl] + (r * h) @ p["Un" + lvl] + p["bn" + lvl])
            h = (1.0 - z) * n + z * h
            hs.append(h)
        return A.stack(hs, axis=1)

    def forward(self, X: np.ndarray) -> dict:
        p, K = self.p, self.cfg["K"]
        x = A.T(X)
        B, N, _ = X.shape
        if N % 2:
            raise ValueError("STE_N_MUST_BE_EVEN")
        f1 = self._conv(x, p["Wc1"], p["bc1"])
        g1 = self._gru(f1, self._corr(f1), "1")
        pooled = (f1[:, 0::2] + f1[:, 1::2]) * 0.5
        f2 = self._conv(pooled, p["Wc2"], p["bc2"])
        g2 = self._gru(f2, self._corr(f2), "2")
        up = A.stack([g2[:, t // 2] for t in range(N)], axis=1)
        d1 = A.tanh(A.concat([g1, up], axis=2) @ p["Wd"] + p["bd"])
        last = d1[:, N - 1]
        aux = g2[:, N // 2 - 1] @ p["Wa"] + p["ba"]
        f = A.T(np.zeros((B, 1)))
        iters = []
        for _ in range(K):                                                  # shared refinement block
            hdn = A.tanh(A.concat([last, f], axis=1) @ p["Rw1"] + p["Rb1"])
            f = f + (hdn @ p["Rw2"] + p["Rb2"])
            iters.append(f)
        return {"iters": iters, "aux": aux, "final": f}

    def predict(self, X: np.ndarray, batch: int = 512) -> np.ndarray:
        out = []
        for k in range(0, len(X), batch):
            out.append(self.forward(X[k:k + batch])["final"].data[:, 0])
        return np.concatenate(out) * self.y_scale if out else np.zeros(0)

    def state(self) -> dict:
        c = self.cfg
        return {**{k: v.data for k, v in self.p.items()}, "y_scale": np.array([self.y_scale]),
                "cfg": np.array([c["cin"], c["C1"], c["C2"], c["L"], c["Hr"], c["K"], int(c["recurrence"]), int(c["correlation"])])}

    @classmethod
    def from_state(cls, st: dict) -> "STEModel":
        cin, C1, C2, L, Hr, K, rec, cor = (int(v) for v in st["cfg"])
        m = cls(cin, C1, C2, L, Hr, K, recurrence=bool(rec), correlation=bool(cor))
        for k in m.p:
            m.p[k] = A.T(np.asarray(st[k], float))
        m.y_scale = float(st["y_scale"][0])
        return m


def huber(pred: A.T, y: np.ndarray, delta: float = 1.0) -> A.T:
    """Mean Huber loss; value 0.5 r^2 (|r| <= delta) else delta (|r| - delta/2); gradient r or delta sign(r)."""
    r = pred.data[:, 0] - y
    a = np.abs(r)
    val = float(np.where(a <= delta, 0.5 * r * r, delta * (a - 0.5 * delta)).mean())
    g = (np.where(a <= delta, r, delta * np.sign(r)) / len(y)).reshape(-1, 1)
    return A.T(val, (pred,), lambda gg: (gg * g,))


def train(Xtr, ytr, Xva, yva, *, epochs=15, lr=3e-3, batch=128, seed=5, patience=3, aux_w=0.3, cancel=None, log=None, **arch) -> dict:
    ok_tr, ok_va = np.isfinite(ytr), np.isfinite(yva)
    Xtr, ytr, Xva, yva = Xtr[ok_tr], ytr[ok_tr], Xva[ok_va], yva[ok_va]
    sc = float(np.std(ytr)) or 1.0
    m = STEModel(cin=Xtr.shape[2], seed=seed, **arch)
    m.y_scale = sc
    opt = A.Adam(m.p, lr=lr)
    rng = np.random.Generator(np.random.PCG64(seed))
    best, best_state, wait, hist = math.inf, None, 0, []
    K = m.cfg["K"]
    t0 = time.perf_counter()
    for ep in range(epochs):
        if cancel and cancel():
            break
        order = rng.permutation(len(Xtr))
        tl, nb = 0.0, 0
        for k in range(0, len(order), batch):
            ix = order[k:k + batch]
            out = m.forward(Xtr[ix])
            yt = ytr[ix] / sc
            loss = huber(out["final"], yt)
            for j, it in enumerate(out["iters"][:-1]):
                loss = loss + huber(it, yt) * (0.5 ** (K - 1 - j))
            loss = loss + huber(out["aux"], yt) * aux_w
            loss.backward()
            opt.step(clip=1.0)
            tl += float(loss.data)
            nb += 1
        pv = m.predict(Xva)
        mae = float(np.mean(np.abs(pv - yva)))
        hist.append({"epoch": ep, "train_loss": tl / max(1, nb), "val_mae": mae})
        if log:
            log(f"STE epoch {ep}: train {tl / max(1, nb):.4f} val MAE {mae:.3e}")
        if mae < best - 1e-12:
            best, best_state, wait = mae, {k: v.data.copy() for k, v in m.p.items()}, 0
        else:
            wait += 1
            if wait >= patience:
                break
    if best_state is not None:
        for k, v in best_state.items():
            m.p[k] = A.T(v)
    return {"model": m, "history": hist, "train_s": time.perf_counter() - t0, "best_val_mae": best, "n_params": m.n_params()}


def reg_metrics(pred, y) -> dict:
    ok = np.isfinite(y)
    p, y = pred[ok], y[ok]
    return {"n": int(len(y)), "mae": float(np.mean(np.abs(p - y))), "rmse": float(np.sqrt(np.mean((p - y) ** 2))),
            "dir_acc_nonzero": float(np.mean(np.sign(p[y != 0]) == np.sign(y[y != 0]))) if np.any(y != 0) else None}
