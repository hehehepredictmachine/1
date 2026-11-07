"""Shared sequence dataset (SEQ_LSTM / SEQ_GRU): the SAME function builds training windows and the live window.

Per-bar features (only data of closed bars <= decision time): log return, range / close, body / close, log(1 + tick volume) z-scored on
TRAIN only. Window [i-L+1 .. i] -> label of bars i+1 .. i+H: forward log return vs band = k_atr x ATR14/price + cost/price ->
DOWN / FLAT / UP. label_end = i + H; the split purges samples whose label reaches into the next part (embargo = H).
Scaler (mean / std of each feature) is fitted on the train part and stored with the model.
"""
from __future__ import annotations

import numpy as np

LABELS = ("DOWN", "FLAT", "UP")


def per_bar(bars: list[dict]) -> np.ndarray:
    o = np.asarray([b["o"] for b in bars], dtype=float); h = np.asarray([b["h"] for b in bars], dtype=float)
    l = np.asarray([b["l"] for b in bars], dtype=float); c = np.asarray([b["c"] for b in bars], dtype=float)
    v = np.asarray([b.get("tv") or 0 for b in bars], dtype=float)
    r = np.concatenate([[0.0], np.diff(np.log(c))])
    return np.column_stack([r, (h - l) / c, (c - o) / c, np.log1p(v)])


def atr_rel(bars, n=14) -> np.ndarray:
    h = np.asarray([b["h"] for b in bars]); l = np.asarray([b["l"] for b in bars]); c = np.asarray([b["c"] for b in bars])
    tr = np.concatenate([[h[0] - l[0]], np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))])
    out = np.full(len(c), np.nan)
    cs = np.cumsum(tr)
    out[n:] = (cs[n:] - cs[:-n]) / n
    return out / c


def build(bars: list[dict], *, L: int = 64, H: int = 6, k_atr: float = 0.25, cost_rel: float = 0.0):
    F = per_bar(bars)
    c = np.asarray([b["c"] for b in bars], dtype=float)
    a = atr_rel(bars)
    X, y, idx = [], [], []
    for i in range(max(L, 15), len(bars) - H):
        if not np.isfinite(a[i]):
            continue
        fwd = np.log(c[i + H] / c[i])
        band = k_atr * a[i] + cost_rel
        y.append(0 if fwd < -band else 2 if fwd > band else 1)
        X.append(F[i - L + 1:i + 1])
        idx.append(i)
    return np.asarray(X, dtype=np.float32), np.asarray(y, dtype=np.int64), np.asarray(idx)


def split(n: int, H: int, holdout_frac=0.2, val_frac=0.2):
    h0 = int(n * (1 - holdout_frac))
    v0 = int(h0 * (1 - val_frac))
    return {"train": (0, max(0, v0 - H)), "val": (v0, max(v0, h0 - H)), "holdout": (h0, n)}


def fit_scaler(X: np.ndarray) -> dict:
    flat = X.reshape(-1, X.shape[-1])
    return {"mean": flat.mean(0).tolist(), "std": (flat.std(0) + 1e-9).tolist()}


def apply_scaler(X: np.ndarray, sc: dict) -> np.ndarray:
    return ((X - np.asarray(sc["mean"], dtype=np.float32)) / np.asarray(sc["std"], dtype=np.float32)).astype(np.float32)


def live_window(bars: list[dict], L: int) -> np.ndarray | None:
    if len(bars) < L + 1:
        return None
    return per_bar(bars)[-L:][None, ...].astype(np.float32)
