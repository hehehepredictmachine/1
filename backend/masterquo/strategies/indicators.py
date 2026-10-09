"""Causal indicator functions shared by the regime engine and the 10 strategies.

Every series function returns a list aligned with its input; element i uses only inputs[0..i]
(Donchian/pivots document their own lag). Warm-up positions are None - never back-filled.
Units: prices in instrument price units; ATR in price units; slopes are expressed in ATR.
"""
from __future__ import annotations

import math


def sma(x: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(x)
    s = 0.0
    for i, v in enumerate(x):
        s += v
        if i >= n:
            s -= x[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def ema(x: list[float], n: int) -> list[float | None]:
    """EMA seeded with the SMA of the first n values (k = 2/(n+1))."""
    out: list[float | None] = [None] * len(x)
    if len(x) < n:
        return out
    k = 2.0 / (n + 1)
    e = sum(x[:n]) / n
    out[n - 1] = e
    for i in range(n, len(x)):
        e = x[i] * k + e * (1 - k)
        out[i] = e
    return out


def true_range(h: list[float], lo: list[float], c: list[float]) -> list[float]:
    return [h[0] - lo[0]] + [max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1])) for i in range(1, len(c))]


def atr(h: list[float], lo: list[float], c: list[float], n: int = 14) -> list[float | None]:
    """Wilder ATR (RMA of true range), seeded with the SMA of the first n true ranges."""
    tr = true_range(h, lo, c)
    out: list[float | None] = [None] * len(tr)
    if len(tr) < n:
        return out
    a = sum(tr[:n]) / n
    out[n - 1] = a
    for i in range(n, len(tr)):
        a = (a * (n - 1) + tr[i]) / n
        out[i] = a
    return out


def rsi(c: list[float], n: int = 14) -> list[float | None]:
    """Wilder RSI."""
    out: list[float | None] = [None] * len(c)
    if len(c) <= n:
        return out
    gains = [max(c[i] - c[i - 1], 0.0) for i in range(1, len(c))]
    losses = [max(c[i - 1] - c[i], 0.0) for i in range(1, len(c))]
    ag, al = sum(gains[:n]) / n, sum(losses[:n]) / n
    out[n] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(n + 1, len(c)):
        ag = (ag * (n - 1) + gains[i - 1]) / n
        al = (al * (n - 1) + losses[i - 1]) / n
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def efficiency_ratio(c: list[float], n: int = 10) -> list[float | None]:
    """Kaufman efficiency ratio |c[i]-c[i-n]| / sum|c[k]-c[k-1]| over the window (0..1)."""
    out: list[float | None] = [None] * len(c)
    for i in range(n, len(c)):
        noise = sum(abs(c[k] - c[k - 1]) for k in range(i - n + 1, i + 1))
        out[i] = 0.0 if noise == 0 else abs(c[i] - c[i - n]) / noise
    return out


def kama(c: list[float], n: int = 10, fast: int = 2, slow: int = 30) -> list[float | None]:
    """Kaufman adaptive moving average: sc = (ER*(2/(fast+1) - 2/(slow+1)) + 2/(slow+1))^2."""
    er = efficiency_ratio(c, n)
    out: list[float | None] = [None] * len(c)
    if len(c) <= n:
        return out
    fsc, ssc = 2.0 / (fast + 1), 2.0 / (slow + 1)
    k = c[n]
    out[n] = k
    for i in range(n + 1, len(c)):
        sc = ((er[i] or 0.0) * (fsc - ssc) + ssc) ** 2
        k = k + sc * (c[i] - k)
        out[i] = k
    return out


def rolling_std(x: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(x)
    for i in range(n - 1, len(x)):
        w = x[i - n + 1:i + 1]
        m = sum(w) / n
        out[i] = math.sqrt(sum((v - m) ** 2 for v in w) / n)
    return out


def zscore(x: list[float], n: int) -> list[float | None]:
    m, s = sma(x, n), rolling_std(x, n)
    return [None if m[i] is None or not s[i] else (x[i] - m[i]) / s[i] for i in range(len(x))]


def donchian_prior(h: list[float], lo: list[float], n: int) -> tuple[list[float | None], list[float | None]]:
    """Channel of the n bars BEFORE bar i (bar i is excluded from its own threshold)."""
    up: list[float | None] = [None] * len(h)
    dn: list[float | None] = [None] * len(h)
    for i in range(n, len(h)):
        up[i] = max(h[i - n:i])
        dn[i] = min(lo[i - n:i])
    return up, dn


def bb_width(c: list[float], n: int = 20, k: float = 2.0) -> list[float | None]:
    """Bollinger band width (upper-lower)/middle."""
    m, s = sma(c, n), rolling_std(c, n)
    return [None if m[i] is None or s[i] is None or m[i] == 0 else (2 * k * s[i]) / m[i] for i in range(len(c))]


def percentile_rank(x: list[float | None], i: int, lookback: int) -> float | None:
    """Share of the previous `lookback` values (excluding i) that are below x[i] (0..1)."""
    if x[i] is None or i < lookback:
        return None
    w = [v for v in x[i - lookback:i] if v is not None]
    if len(w) < lookback * 0.8:
        return None
    return sum(1 for v in w if v < x[i]) / len(w)


def macd_hist(c: list[float], fast: int = 12, slow: int = 26, sig: int = 9) -> list[float | None]:
    ef, es = ema(c, fast), ema(c, slow)
    line = [None if ef[i] is None or es[i] is None else ef[i] - es[i] for i in range(len(c))]
    start = next((i for i, v in enumerate(line) if v is not None), None)
    out: list[float | None] = [None] * len(c)
    if start is None:
        return out
    sig_s = ema([v for v in line[start:]], sig)
    for j, v in enumerate(sig_s):
        if v is not None:
            out[start + j] = line[start + j] - v
    return out


def slope_atr(series: list[float | None], a: list[float | None], i: int, lag: int = 5) -> float | None:
    """Change of `series` over `lag` bars divided by lag*ATR (per-bar slope in ATR units)."""
    if i - lag < 0 or series[i] is None or series[i - lag] is None or not a[i]:
        return None
    return (series[i] - series[i - lag]) / (lag * a[i])


def pivots(h: list[float], lo: list[float], left: int = 3, right: int = 3) -> list[dict]:
    """Swing highs/lows. A pivot at bar p is known only at bar p+right (`confirmed_index`).

    Callers must use only pivots with confirmed_index <= the evaluated bar index.
    Ties are resolved conservatively: the pivot must be strictly greater/lower than its neighbours on the right.
    """
    out = []
    for p in range(left, len(h) - right):
        if all(h[p] >= h[p - k] for k in range(1, left + 1)) and all(h[p] > h[p + k] for k in range(1, right + 1)):
            out.append({"kind": "H", "index": p, "price": h[p], "confirmed_index": p + right})
        if all(lo[p] <= lo[p - k] for k in range(1, left + 1)) and all(lo[p] < lo[p + k] for k in range(1, right + 1)):
            out.append({"kind": "L", "index": p, "price": lo[p], "confirmed_index": p + right})
    return out


def known_pivots(piv: list[dict], at_index: int) -> list[dict]:
    return [p for p in piv if p["confirmed_index"] <= at_index]
