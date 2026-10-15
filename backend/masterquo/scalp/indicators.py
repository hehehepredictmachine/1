"""Causal indicators for the scalp profile (value at bar i uses bars <= i only). Pure Python - the bot venv has no pandas.

ATR14   Wilder: seed = mean of the first 14 true ranges, then (prev*13 + TR)/14.
ER(n)   |C_t - C_(t-n)| / sum(|C_i - C_(i-1)|); zero denominator -> 0.0 with flat=True (caller checks minimal movement).
BB      basis = SMA(20) of close, dev = POPULATION standard deviation (divide by N - the MT5 iBands formula), upper/lower =
        basis +/- 2*dev, %B = (C-lower)/(upper-lower), BandWidth = (upper-lower)/basis, its percentile over the previous 100
        bars (strictly earlier values), slope = (basis_t - basis_(t-3)) / (3 * ATR_t)  [ATR per bar].
SAR     Parabolic SAR, step 0.02, maximum 0.2 (Wilder): initial trend from the first two bars; the SAR never enters the
        range of the current or previous bar. Compare with MT5 iSAR on real data before relying on exact values.
"""
from __future__ import annotations

import math


def atr(h, lo, c, n: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(c)
    trs = []
    for i in range(len(c)):
        tr = h[i] - lo[i] if i == 0 else max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1]))
        trs.append(tr)
        if i == n - 1:
            out[i] = sum(trs) / n
        elif i >= n:
            out[i] = (out[i - 1] * (n - 1) + tr) / n
    return out


def er(c, n: int = 10) -> list[float | None]:
    out: list[float | None] = [None] * len(c)
    for i in range(n, len(c)):
        den = sum(abs(c[k] - c[k - 1]) for k in range(i - n + 1, i + 1))
        out[i] = 0.0 if den == 0 else abs(c[i] - c[i - n]) / den
    return out


def bollinger(c, a: list, n: int = 20, k: float = 2.0, pct_window: int = 100) -> list[dict | None]:
    out: list[dict | None] = [None] * len(c)
    widths: list[float] = []
    for i in range(n - 1, len(c)):
        win = c[i - n + 1: i + 1]
        m = sum(win) / n
        sd = math.sqrt(sum((x - m) ** 2 for x in win) / n)
        up, dn = m + k * sd, m - k * sd
        bw = (up - dn) / m if m else None
        prev = widths[-pct_window:]
        pct = None if len(prev) < pct_window or bw is None else 100.0 * sum(1 for x in prev if x < bw) / len(prev)
        slope = None
        if i >= n - 1 + 3 and out[i - 3] is not None and a[i]:
            slope = (m - out[i - 3]["basis"]) / (3 * a[i])
        out[i] = {"basis": m, "upper": up, "lower": dn, "pct_b": None if up == dn else (c[i] - dn) / (up - dn), "bandwidth": bw,
                  "bandwidth_pct100": pct, "slope_atr_per_bar": slope}
        if bw is not None:
            widths.append(bw)
    return out


def sar(h, lo, step: float = 0.02, maximum: float = 0.2) -> list[dict | None]:
    n = len(h)
    out: list[dict | None] = [None] * n
    if n < 2:
        return out
    up = h[1] >= h[0]
    ep = h[1] if up else lo[1]
    s = lo[0] if up else h[0]
    af = step
    out[1] = {"sar": s, "trend": "UP" if up else "DOWN", "flip": False}
    for i in range(2, n):
        s = s + af * (ep - s)
        flip = False
        if up:
            s = min(s, lo[i - 1], lo[i - 2])
            if lo[i] < s:
                up, flip, s, ep, af = False, True, ep, lo[i], step
            elif h[i] > ep:
                ep, af = h[i], min(maximum, af + step)
        else:
            s = max(s, h[i - 1], h[i - 2])
            if h[i] > s:
                up, flip, s, ep, af = True, True, ep, h[i], step
            elif lo[i] < ep:
                ep, af = lo[i], min(maximum, af + step)
        out[i] = {"sar": s, "trend": "UP" if up else "DOWN", "flip": flip}
    return out


def median(xs: list[float]) -> float | None:
    v = sorted(x for x in xs if x is not None)
    if not v:
        return None
    m = len(v) // 2
    return v[m] if len(v) % 2 else (v[m - 1] + v[m]) / 2
