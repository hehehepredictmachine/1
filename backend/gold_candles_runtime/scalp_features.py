"""Causal M1 feature / label contract of the scalp models (SCALP-FEAT-1.0.0) - the SAME function is used by training and
by the worker at inference (`scalp_forecast`). Row i uses only bars <= i (closed). Indicators come from the bot's own
pure-Python module (masterquo.scalp.indicators) so train/live share one implementation.

Labels (task A): d = C(i+h) - C(i) for h = 1/3/5 M1, valid only if bars i+1..i+h are consecutive minutes (no gap / weekend);
tau = max(0.20 * ATR14_M1(i), cost(i)), cost(i) = spread(i) + 2 * commission_price + 2 * slippage_price  (price units for a
reference volume of 1 lot: commission cash per lot side / contract size). UP if d > tau, DOWN if d < -tau, else FLAT.
The cost dead zone defines a neutral move; it is not a trade profit. Quantile target: d / ATR14_M1(i).
"""
from __future__ import annotations

import hashlib
import json
import math

import numpy as np

from masterquo.scalp import indicators as ind

VERSION = "SCALP-FEAT-1.0.0"
HORIZONS = (1, 3, 5)
FEATURES = ("ret1", "ret2", "ret3", "ret5", "ret10", "ret15", "atr_bp", "clv", "body_ratio", "upper_r", "lower_r", "r_atr", "zero_range",
            "bb_pctb", "bb_bw_bp", "bb_slope", "bb_bw_pct", "sar_dist", "sar_up", "tv_log_ratio", "tv_missing", "pos60", "dist_hi60", "dist_lo60",
            "er10", "spread_atr", "spread_missing", "hour_sin", "hour_cos", "dow")


def contract_hash(symbol: str, tick: float) -> str:
    return hashlib.sha256(json.dumps({"v": VERSION, "f": FEATURES, "h": HORIZONS, "s": symbol, "t": tick}, sort_keys=True).encode()).hexdigest()[:16]


def build(t, o, h, lo, c, tv, spread) -> np.ndarray:
    """Feature matrix (n x len(FEATURES)); rows without full warmup contain NaN (dropped by the caller, never imputed OHLC)."""
    n = len(c)
    a = ind.atr(h, lo, c)
    bb = ind.bollinger(c, a)
    sr = ind.sar(h, lo)
    er = ind.er(c, 10)
    X = np.full((n, len(FEATURES)), np.nan)
    for i in range(n):
        ai = a[i]
        if ai is None or ai <= 0 or i < 60 or bb[i] is None or bb[i]["bandwidth_pct100"] is None or bb[i]["slope_atr_per_bar"] is None or sr[i] is None:
            continue
        R = h[i] - lo[i]
        f = {f"ret{k}": (c[i] - c[i - k]) / ai for k in (1, 2, 3, 5, 10, 15)}
        f["atr_bp"] = ai / c[i] * 1e4
        if R > 0:
            f.update(clv=(c[i] - lo[i]) / R, body_ratio=abs(c[i] - o[i]) / R, upper_r=(h[i] - max(o[i], c[i])) / R,
                     lower_r=(min(o[i], c[i]) - lo[i]) / R, r_atr=R / ai, zero_range=0.0)
        else:
            f.update(clv=0.5, body_ratio=0.0, upper_r=0.0, lower_r=0.0, r_atr=0.0, zero_range=1.0)
        b = bb[i]
        f.update(bb_pctb=b["pct_b"] if b["pct_b"] is not None else 0.5, bb_bw_bp=b["bandwidth"] * 1e4, bb_slope=b["slope_atr_per_bar"],
                 bb_bw_pct=b["bandwidth_pct100"], sar_dist=(c[i] - sr[i]["sar"]) / ai, sar_up=1.0 if sr[i]["trend"] == "UP" else 0.0)
        prev = [x for x in tv[i - 20:i] if x is not None and not (isinstance(x, float) and math.isnan(x))]
        med = float(np.median(prev)) if prev else 0.0
        if tv[i] is None or med <= 0:
            f.update(tv_log_ratio=0.0, tv_missing=1.0)
        else:
            f.update(tv_log_ratio=math.log(max(tv[i], 1e-9) / med), tv_missing=0.0)
        hi60, lo60 = max(h[i - 59:i + 1]), min(lo[i - 59:i + 1])
        f.update(pos60=(c[i] - lo60) / (hi60 - lo60) if hi60 > lo60 else 0.5, dist_hi60=(hi60 - c[i]) / ai, dist_lo60=(c[i] - lo60) / ai,
                 er10=er[i] if er[i] is not None else 0.0)
        sp = spread[i] if spread is not None else None
        if sp is None or (isinstance(sp, float) and math.isnan(sp)):
            f.update(spread_atr=0.0, spread_missing=1.0)
        else:
            f.update(spread_atr=sp / ai, spread_missing=0.0)
        hr = (t[i] % 86400) / 3600.0
        f.update(hour_sin=math.sin(2 * math.pi * hr / 24), hour_cos=math.cos(2 * math.pi * hr / 24), dow=float(((t[i] // 86400) + 3) % 7))
        X[i] = [f[k] for k in FEATURES]
    return X, a


def labels(t, c, a, spread, commission_price: float, slippage_price: float):
    """Y[h] in {0 DOWN, 1 FLAT, 2 UP} or -1 (no valid label), Q[h] = d / ATR, label end time (epoch) per row."""
    n = len(c)
    Y, Q, END = {}, {}, {}
    for hz in HORIZONS:
        y = np.full(n, -1, dtype=int)
        q = np.full(n, np.nan)
        end = np.zeros(n, dtype=np.int64)
        for i in range(n - hz):
            if a[i] is None or t[i + hz] - t[i] != 60 * hz:
                continue
            sp = spread[i] if spread is not None and spread[i] is not None and not (isinstance(spread[i], float) and math.isnan(spread[i])) else None
            if sp is None:
                continue                                   # unknown cost -> no label (cost dead zone undefined)
            tau = max(0.2 * a[i], sp + 2 * commission_price + 2 * slippage_price)
            d = c[i + hz] - c[i]
            y[i] = 2 if d > tau else 0 if d < -tau else 1
            q[i] = d / a[i]
            end[i] = t[i + hz] + 60
        Y[hz], Q[hz], END[hz] = y, q, end
    return Y, Q, END
