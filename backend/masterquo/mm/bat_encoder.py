"""BAT_EVENT_ENCODER (Apollo23 TASK 006 + TASK 016 BTC / SATMA refinement; MQL5 articles #20559 / #20506 / #20528) - a separate namespace,
NOT a replacement of mm.event_engine, mm.ste_flownet, mm.stfs, lab.spike_brain, ML / ModelHub families or any execution path.

Independent PMW adaptation of the published architecture (no article code copied; the MQL5.zip attachments were not inspected):
  event voxels (closed bars -> normalized channels) -> multi-scale branches ->
  BTC  : CENTRAL reference = the middle element of the OBSERVED buffer, normalized features, learned multi-window warp,
         bidirectional normalized correlations INSIDE the observed window, MotionEncoder (borrowed TMA-style component - PMW adaptation)
  SATMA: LATEST reference (current state), relative cross-attention, sigmoid latent feature gate, element-wise fusion
         (BTC reference != SATMA reference; STFS in PMW is not SATMA)
  -> GRU temporal state -> STFS-style fusion -> Actor (action preference) / Critic (value) heads.
Causality: every computation for decision time t uses rows <= t only ("bidirectional" means both directions WITHIN the observed buffer).
Output = versioned context / forecast / action-evaluation data. Mode SHADOW; no order placement, no risk change.
"""
from __future__ import annotations

import numpy as np

SCHEMA = "PMW-BAT-EVENT-ENCODER-1"
TASK016_REFINEMENT = "BTC_CENTRAL_REF + SATMA_LATEST_REF + MULTI_WINDOW_WARP + SIGMOID_GATE"
CHANNELS = ("ret", "range", "body", "upper_wick", "lower_wick", "vol_z")


def voxels(bars: list[dict]) -> np.ndarray:
    """Closed bars -> [T, C] channels, each normalized only with data up to that row (expanding, causal)."""
    o = np.array([float(b["o"]) for b in bars])
    h = np.array([float(b["h"]) for b in bars])
    lo = np.array([float(b["l"]) for b in bars])
    c = np.array([float(b["c"]) for b in bars])
    v = np.array([float(b.get("v", b.get("tv", 0.0)) or 0.0) for b in bars])
    prev = np.concatenate([[o[0]], c[:-1]])
    x = np.stack([np.log(c / prev), (h - lo) / c, (c - o) / c, (h - np.maximum(o, c)) / c, (np.minimum(o, c) - lo) / c, v], axis=1)
    out = np.zeros_like(x)
    csum, csq = np.cumsum(x, 0), np.cumsum(x * x, 0)
    for t in range(len(x)):
        n = t + 1
        m = csum[t] / n
        sd = np.sqrt(np.maximum(csq[t] / n - m * m, 1e-12))
        out[t] = (x[t] - m) / sd
    return np.clip(out, -6, 6)


class BATEncoder:
    def __init__(self, channels: int = len(CHANNELS), hidden: int = 16, scales=(1, 2, 4), windows=(4, 8, 16), seed: int = 7):
        rng = np.random.default_rng(seed)
        self.C, self.H, self.scales, self.windows = channels, hidden, tuple(scales), tuple(windows)
        g = lambda *s: rng.normal(0, 1 / np.sqrt(s[0]), s)  # noqa: E731
        self.W_in = g(channels, hidden)
        self.W_scale = [g(hidden, hidden) for _ in scales]
        self.warp = rng.normal(0, 0.1, len(windows))              # learned multi-window warp logits (softmax weights)
        self.W_motion = g(len(windows) * 2, hidden)
        self.Wq, self.Wk, self.Wv = g(hidden, hidden), g(hidden, hidden), g(hidden, hidden)
        self.W_gate = g(hidden, hidden)
        self.Wz, self.Wr, self.Wh = g(2 * hidden, hidden), g(2 * hidden, hidden), g(2 * hidden, hidden)
        self.W_fuse = g(3 * hidden, hidden)
        self.W_actor = g(hidden, 3)                               # LONG / FLAT / SHORT preference (evaluation only)
        self.W_critic = g(hidden, 1)

    # ------------------------------------------------------------ blocks
    def _branches(self, x: np.ndarray) -> np.ndarray:
        e = np.tanh(x @ self.W_in)
        outs = []
        for s, W in zip(self.scales, self.W_scale):
            k = np.ones(s) / s                                    # causal moving average at scale s
            sm = np.stack([np.convolve(e[:, j], k)[: len(e)] for j in range(e.shape[1])], 1)
            outs.append(np.tanh(sm @ W))
        return np.mean(outs, 0)

    @staticmethod
    def _ncorr(a: np.ndarray, b: np.ndarray) -> float:
        a, b = a - a.mean(), b - b.mean()
        d = np.linalg.norm(a) * np.linalg.norm(b)
        return float(a @ b / d) if d > 1e-12 else 0.0

    def btc(self, f: np.ndarray, t: int) -> np.ndarray:
        """Bidirectional Temporal Correlation for decision row t: reference = CENTRAL element of each observed window [t-w+1 .. t]."""
        wts = np.exp(self.warp) / np.exp(self.warp).sum()
        feats = []
        for w, a in zip(self.windows, wts):
            lo = max(0, t - w + 1)
            buf = f[lo: t + 1]
            if len(buf) < 3:
                feats += [0.0, 0.0]
                continue
            ref = buf[len(buf) // 2]                              # central reference (observed)
            past = np.mean([self._ncorr(ref, r) for r in buf[: len(buf) // 2]]) if len(buf) // 2 else 0.0
            after = np.mean([self._ncorr(ref, r) for r in buf[len(buf) // 2 + 1:]])       # "future side" = still <= t (observed)
            feats += [a * past, a * after]
        return np.tanh(np.array(feats) @ self.W_motion)          # MotionEncoder

    def satma(self, f: np.ndarray, t: int, ctx: int = 16) -> np.ndarray:
        """Latest-reference relative cross-attention + sigmoid latent gate (query = row t, keys = rows t-ctx+1..t)."""
        lo = max(0, t - ctx + 1)
        keys = f[lo: t + 1]
        q = f[t] @ self.Wq
        k = keys @ self.Wk
        v = (keys - f[t]) @ self.Wv                              # relative to the latest state
        s = k @ q / np.sqrt(self.H)
        a = np.exp(s - s.max())
        a /= a.sum()
        att = a @ v
        gate = 1 / (1 + np.exp(-(f[t] @ self.W_gate)))
        return gate * att                                         # element-wise fusion

    def _gru(self, hprev: np.ndarray, x: np.ndarray) -> np.ndarray:
        hx = np.concatenate([hprev, x])
        z = 1 / (1 + np.exp(-(hx @ self.Wz)))
        r = 1 / (1 + np.exp(-(hx @ self.Wr)))
        hh = np.tanh(np.concatenate([r * hprev, x]) @ self.Wh)
        return (1 - z) * hprev + z * hh

    # ------------------------------------------------------------ forward
    def run(self, bars: list[dict], asof_index: int | None = None) -> dict:
        """Encodes rows 0..asof_index (inclusive); rows after asof_index are never read."""
        T = len(bars) if asof_index is None else asof_index + 1
        if T < 8:
            return {"schema": SCHEMA, "status": "WARMUP", "rows": T}
        x = voxels(bars[:T])                                      # causal slice BEFORE any computation
        f = self._branches(x)
        h = np.zeros(self.H)
        for t in range(T):
            h = self._gru(h, f[t])
        b, s = self.btc(f, T - 1), self.satma(f, T - 1)
        z = np.tanh(np.concatenate([h, b, s]) @ self.W_fuse)     # STFS-style fusion of temporal state + BTC + SATMA
        logits = z @ self.W_actor
        p = np.exp(logits - logits.max())
        p /= p.sum()
        return {"schema": SCHEMA, "refinement": TASK016_REFINEMENT, "status": "SHADOW_UNTRAINED", "asof_index": T - 1,
                "context": z.round(6).tolist(), "actor": {"LONG": float(p[0]), "FLAT": float(p[1]), "SHORT": float(p[2])},
                "critic_value": float((z @ self.W_critic)[0]), "execution": "NONE (SHADOW – brak ścieżki zleceń)",
                "note": "wagi niewytrenowane (deterministyczny seed) – wyjście opisowe do walidacji; nie promować bez SHADOW/OOS"}
