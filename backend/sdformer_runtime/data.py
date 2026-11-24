"""Bar descriptor of the source (Study.mq5 CreateBuffers): per bar [close-open, high-open, low-open, tick_volume/1000, RSI14, CCI14,
ATR14, MACD(12,26,9) main, MACD signal] - computed causally on CLOSED bars, ordered OLDEST -> NEWEST (the source fed MQL "as series"
arrays newest-first; PMW never passes a reversed sequence as chronological). Sample i: input = descriptors of bars i-119..i,
target (self-supervised, STFS head) = descriptors of the next 24 bars i+1..i+24 - known only after those bars closed.
Normalisation: mean / std per descriptor fitted on the TRAINING rows only, stored in the checkpoint (never refitted at inference)."""
from __future__ import annotations

import math

import numpy as np

HISTORY, DESCR, FORECAST = 120, 9, 24
NAMES = ("close_open", "high_open", "low_open", "tick_volume_k", "rsi14", "cci14", "atr14", "macd_main", "macd_signal")


def _ema(x: np.ndarray, n: int) -> np.ndarray:
    k = 2.0 / (n + 1)
    out = np.empty_like(x)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = x[i] * k + out[i - 1] * (1 - k)
    return out


def descriptors(bars: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """-> (D [n, 9], valid [n]) ; valid False during the indicator warm-up (no invented values)."""
    o = np.array([float(b["o"]) for b in bars])
    h = np.array([float(b["h"]) for b in bars])
    l_ = np.array([float(b["l"]) for b in bars])
    c = np.array([float(b["c"]) for b in bars])
    tv = np.array([float(b.get("tv") or 0.0) for b in bars])
    n = len(bars)
    d = np.diff(c, prepend=c[0])
    up, dn = np.maximum(d, 0), np.maximum(-d, 0)
    au, ad = np.zeros(n), np.zeros(n)
    for i in range(1, n):                                         # Wilder RSI 14
        if i < 15:
            au[i], ad[i] = up[1:i + 1].mean(), dn[1:i + 1].mean()
        else:
            au[i] = (au[i - 1] * 13 + up[i]) / 14
            ad[i] = (ad[i - 1] * 13 + dn[i]) / 14
    rsi = np.where(ad > 0, 100 - 100 / (1 + au / np.where(ad > 0, ad, 1)), 100.0)
    tp = (h + l_ + c) / 3
    cci = np.zeros(n)
    for i in range(13, n):
        w = tp[i - 13:i + 1]
        md = np.abs(w - w.mean()).mean()
        cci[i] = (tp[i] - w.mean()) / (0.015 * md) if md > 0 else 0.0
    tr = np.maximum(h - l_, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l_ - np.roll(c, 1))))
    tr[0] = h[0] - l_[0]
    atr = np.zeros(n)
    for i in range(n):
        atr[i] = tr[max(0, i - 13):i + 1].mean()
    macd = _ema(c, 12) - _ema(c, 26)
    sig = _ema(macd, 9)
    D = np.stack([c - o, h - o, l_ - o, tv / 1000.0, rsi, cci, atr, macd, sig], axis=1)
    valid = np.arange(n) >= 40
    valid &= np.isfinite(D).all(axis=1)
    return D, valid


def samples(bars: list[dict], *, with_target: bool = True):
    D, valid = descriptors(bars)
    t = np.array([float(b["t"]) for b in bars])
    X, Y, T, idx = [], [], [], []
    last = len(bars) - (FORECAST if with_target else 0)
    for i in range(HISTORY - 1, last):
        a = i - HISTORY + 1
        if not valid[a:i + 1].all() or (with_target and not valid[i + 1:i + 1 + FORECAST].all()):
            continue
        X.append(D[a:i + 1])
        T.append(t[a:i + 1])
        if with_target:
            Y.append(D[i + 1:i + 1 + FORECAST])
        idx.append(i)
    return (np.asarray(X, np.float32), np.asarray(Y, np.float32) if with_target else None, np.asarray(T, np.float64), idx)


def time_features(T: np.ndarray) -> np.ndarray:
    """Mamba4Cast-style calendar embedding input of the source (periods D1 and MN1): sin / cos of the day and of the ~month phase."""
    day = 2 * math.pi * (T % 86400) / 86400
    mon = 2 * math.pi * (T % (30.4375 * 86400)) / (30.4375 * 86400)
    return np.stack([np.sin(day), np.cos(day), np.sin(mon), np.cos(mon)], axis=-1).astype(np.float32)
