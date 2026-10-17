"""Causal feature set + triple-barrier labels per asset / horizon (FS-1.0.0, LBL-TB-1.0.0).

Question answered by the models (fixed before testing): "at the close of bar i, if we enter LONG (or SHORT) at the next bar's
open (earliest fill) paying the spread, is the take-profit barrier (k_tp x ATR) hit before the stop barrier (k_sl x ATR) within H
bars?" - NOT the direction of the next bar. Abstention is a separate engine state (probability inside the no-trade band).

Rules: long side evaluated on Bid (exit) after Ask entry; when SL and TP are both inside one OHLC bar the SL is assumed first
(conservative) and the case is counted as ambiguous; a label that has not matured by the cut-off is dropped (never guessed);
a gap > gap_bars x TF inside the label window drops the sample. Every sample stores t_event (decision) and t_label_end
(resolution) for purging.
"""
from __future__ import annotations

import hashlib
import json

import numpy as np

from ..analytics.ta import TF_SEC
from .common import arrays, atr, ema, rolling_std, sma

FEATURE_SET = "FS-1.0.0"
LABELS = "LBL-TB-1.0.0"
FEATURE_GROUPS = {
    "returns": ["ret_1", "ret_3", "ret_12"],
    "volatility": ["atr_rel", "range_rel", "vol_pct"],
    "bands": ["bb_pctb", "z20"],
    "trend": ["ema_gap_50", "er_20"],
    "activity": ["tv_pct"],
    "time": ["hour_sin", "hour_cos"],
}
FEATURES = [f for g in FEATURE_GROUPS.values() for f in g]
SEQ_CHANNELS = ["ret_1", "range_rel", "z20", "tv_pct"]


def feature_matrix(bars: list[dict], tf: str) -> dict:
    """Row i uses bars[0..i] only. warmup rows are NaN and flagged."""
    a = arrays(bars)
    o, h, lo, c, tv, t = a["o"], a["h"], a["l"], a["c"], a["tv"], a["t"]
    n = len(c)
    F = np.full((n, len(FEATURES)), np.nan)
    at = atr(h, lo, c)
    m20, s20 = sma(c, 20), rolling_std(c, 20)
    e50 = ema(c, 50)
    col = {f: i for i, f in enumerate(FEATURES)}

    def lagret(k):
        r = np.full(n, np.nan)
        r[k:] = c[k:] / c[:-k] - 1
        return r
    F[:, col["ret_1"]] = lagret(1)
    F[:, col["ret_3"]] = lagret(3)
    F[:, col["ret_12"]] = lagret(12)
    F[:, col["atr_rel"]] = at / c
    F[:, col["range_rel"]] = (h - lo) / np.where(at > 0, at, np.nan)
    for i in range(n):
        if i >= 100 and not np.isnan(at[i]):
            w = at[i - 99:i + 1]
            F[i, col["vol_pct"]] = (w < at[i]).mean()
            w2 = tv[i - 99:i + 1]
            F[i, col["tv_pct"]] = (w2 < tv[i]).mean()
        if i >= 20:
            path = np.abs(np.diff(c[i - 20:i + 1])).sum()
            F[i, col["er_20"]] = abs(c[i] - c[i - 20]) / path if path > 0 else 0.0
    sd = np.where(s20 > 1e-9 * np.abs(c), s20, np.nan)
    F[:, col["z20"]] = (c - m20) / sd
    F[:, col["bb_pctb"]] = (c - (m20 - 2 * sd)) / (4 * sd)
    F[:, col["ema_gap_50"]] = (c - e50) / np.where(at > 0, at, np.nan)
    hr = ((t + TF_SEC[tf]) % 86400) / 3600.0
    F[:, col["hour_sin"]] = np.sin(2 * np.pi * hr / 24)
    F[:, col["hour_cos"]] = np.cos(2 * np.pi * hr / 24)
    warm = np.isnan(F).any(axis=1)
    return {"X": F, "t_event": t + TF_SEC[tf], "warmup": warm, "atr": at, "features": FEATURES, "feature_set": FEATURE_SET,
            "groups": FEATURE_GROUPS}


def triple_barrier(bars: list[dict], tf: str, *, side: str, horizon: int, k_tp: float, k_sl: float, point: float,
                   cutoff_t: float | None = None, gap_bars: float = 3.0, spread_points_default: float = 0.0) -> dict:
    a = arrays(bars)
    o, h, lo, c, t = a["o"], a["h"], a["l"], a["c"], a["t"]
    spr = np.array([float(b.get("spread") if b.get("spread") is not None else spread_points_default) for b in bars]) * point
    at = atr(h, lo, c)
    n = len(c)
    sec = TF_SEC[tf]
    y = np.full(n, -1)
    end = np.full(n, np.nan)
    r_mult = np.full(n, np.nan)
    amb = np.zeros(n, bool)
    sgn = 1 if side == "LONG" else -1
    for i in range(n - 1):
        if np.isnan(at[i]):
            continue
        j0 = i + 1
        jmax = min(n - 1, i + horizon)
        if jmax - j0 + 1 < horizon:
            continue                                             # immature at the data end
        if (t[jmax] - t[i]) > (horizon + gap_bars) * sec:
            continue                                             # session gap inside the label window
        # Bars are Bid prices. LONG: enter at Ask = open + spread, exit on Bid. SHORT: enter on Bid, exit at Ask = Bid + spread.
        entry = o[j0] + spr[j0] if side == "LONG" else o[j0]
        risk = k_sl * at[i]
        tp = entry + sgn * k_tp * at[i]
        sl = entry - sgn * risk
        res, k_end = 0, jmax
        for j in range(j0, jmax + 1):
            hi_exit = h[j] if side == "LONG" else h[j] + spr[j]
            lo_exit = lo[j] if side == "LONG" else lo[j] + spr[j]
            hit_tp = hi_exit >= tp if side == "LONG" else lo_exit <= tp
            hit_sl = lo_exit <= sl if side == "LONG" else hi_exit >= sl
            if hit_tp and hit_sl:
                amb[i] = True
                res, k_end = -1, j                                   # conservative: SL first
                break
            if hit_sl:
                res, k_end = -1, j
                break
            if hit_tp:
                res, k_end = 1, j
                break
        t_end = t[k_end] + sec
        if cutoff_t is not None and t_end > cutoff_t:
            continue                                             # label not matured before the cut-off
        y[i] = 1 if res == 1 else 0
        end[i] = t_end
        if res == 1:
            r_mult[i] = k_tp / k_sl
        elif res == -1:
            r_mult[i] = -1.0
        else:
            exit_px = c[k_end] if side == "LONG" else c[k_end] + spr[k_end]
            r_mult[i] = sgn * (exit_px - entry) / risk
    return {"y": y, "t_label_end": end, "r": r_mult, "ambiguous": amb,
            "spec": {"labels": LABELS, "side": side, "horizon_bars": horizon, "k_tp_atr": k_tp, "k_sl_atr": k_sl,
                     "entry": "open następnej świecy (+spread dla LONG)", "same_bar_sl_tp": "SL_FIRST_CONSERVATIVE",
                     "timeout": "klasa 0 (TP nieosiągnięty); wynik R z zamknięcia"}}


def sequences(X: np.ndarray, idx: np.ndarray, length: int) -> np.ndarray:
    """(n, channels, length) windows ending at each idx (inclusive) over SEQ_CHANNELS - for MiniRocket / ResNet / SNN."""
    cols = [FEATURES.index(c) for c in SEQ_CHANNELS]
    out = np.stack([X[i - length + 1:i + 1, cols].T for i in idx])
    return np.nan_to_num(out, nan=0.0)


def dataset_hash(bars: list[dict]) -> str:
    return hashlib.sha256(json.dumps([(b["open_utc"], b["o"], b["h"], b["l"], b["c"]) for b in bars]).encode()).hexdigest()[:16]
