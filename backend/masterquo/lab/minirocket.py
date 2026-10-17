"""MiniRocket transform (M05) - clean-room numpy implementation from the published method (Dempster, Schmidt, Webb 2021).
The authors' reference code is GPL-3.0 and was NOT copied.

* 84 fixed kernels of length 9: weights -1 everywhere and +2 at 3 of the 9 positions (all C(9,3) combinations);
* dilations exponentially spaced (powers of 2 up to (L-1)/8), features split across dilations;
* biases = quantiles of the convolution output of ONE random training example (fit on the training fold only - that is the
  fitted part of the transform); feature = PPV (proportion of positive values) of conv + bias, alternate kernels padded;
* multivariate: each kernel/dilation uses a fixed random subset of channels (summed), as in the multivariate variant.
The fitted object (dilations, channel subsets, biases, seed, input length) is stored inside the model artifact.
"""
from __future__ import annotations

from itertools import combinations

import numpy as np

VERSION = "MINIROCKET-NP-1.0.0"
KERNELS = np.array(list(combinations(range(9), 3)))          # 84 x 3


class MiniRocket:
    def __init__(self, num_features: int = 2016, max_dilations: int = 16, seed: int = 0):
        self.num_features = num_features
        self.max_dilations = max_dilations
        self.seed = seed
        self.fitted = None

    def _conv(self, x: np.ndarray, kernel_idx: int, d: int, pad: bool) -> np.ndarray:
        """x (n, L) single (summed) channel. Returns (n, L') convolution with weights -1 / +2."""
        L = x.shape[1]
        p = (9 - 1) * d // 2 if pad else 0
        xp = np.pad(x, ((0, 0), (p, p))) if p else x
        Lout = xp.shape[1] - 8 * d
        if Lout <= 0:
            return np.zeros((x.shape[0], 1))
        taps = np.stack([xp[:, j * d:j * d + Lout] for j in range(9)], axis=0)    # 9, n, Lout
        out = -taps.sum(axis=0)
        out += 3 * taps[KERNELS[kernel_idx]].sum(axis=0)                          # -1 + 3 = +2 on the chosen positions
        return out[:, :L] if pad else out

    def fit(self, X: np.ndarray) -> "MiniRocket":
        n, C, L = X.shape
        rng = np.random.default_rng(self.seed)
        max_exp = np.log2(max(1.0, (L - 1) / 8))
        dil = np.unique(np.floor(np.logspace(0, max_exp, self.max_dilations, base=2)).astype(int))
        per = max(1, self.num_features // (84 * len(dil)))
        quantiles = (np.arange(1, per + 1) * ((np.sqrt(5) + 1) / 2)) % 1        # low-discrepancy quantiles
        ex = X[rng.integers(0, n)]
        spec = []
        for di, d in enumerate(dil):
            for k in range(84):
                nch = int(rng.integers(1, min(C, 3) + 1))
                chans = np.sort(rng.choice(C, nch, replace=False))
                pad = (di + k) % 2 == 0
                conv = self._conv(ex[chans].sum(axis=0)[None, :], k, int(d), pad)[0]
                b = np.quantile(conv, quantiles)
                spec.append({"k": k, "d": int(d), "ch": chans.tolist(), "pad": pad, "bias": (-b).tolist()})
        self.fitted = {"version": VERSION, "seed": self.seed, "L": L, "C": C, "dilations": dil.tolist(), "per": per, "spec": spec}
        return self

    def transform(self, X: np.ndarray) -> np.ndarray:
        if self.fitted is None:
            raise RuntimeError("NOT_FITTED")
        n, C, L = X.shape
        if C != self.fitted["C"] or L != self.fitted["L"]:
            raise ValueError("INPUT_SHAPE_DIFFERS_FROM_FIT")
        feats = []
        for s in self.fitted["spec"]:
            conv = self._conv(X[:, s["ch"]].sum(axis=1), s["k"], s["d"], s["pad"])
            for b in s["bias"]:
                feats.append(((conv + b) > 0).mean(axis=1))
        return np.stack(feats, axis=1)

    def state(self) -> dict:
        return self.fitted
