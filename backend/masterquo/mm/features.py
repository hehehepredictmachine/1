"""Feature registry + target registry (PMW-MM-FEATURES-1).

Every feature is computed from CLOSED bars <= i and is available at the close of bar i (t_open[i] + tf). Warm-up rows are NaN and are
dropped by the dataset builder (never zero-filled). Each model declares the subset it consumes (feature schema id = hash of names +
versions), so reuse cannot silently change another model's inputs. Targets are separate objects: their value at i uses bars > i and they
carry the label maturation time; they are never passed to `features()`.
"""
from __future__ import annotations

import hashlib
import json

import numpy as np

VERSION = "PMW-MM-FEATURES-1"

FEATURES = {
    "ret_1": {"formula": "ln(C[i]/C[i-1])", "unit": "log return", "lookback": 1, "missing": "NaN until warm", "repaint": "no"},
    "ret_3": {"formula": "ln(C[i]/C[i-3])", "unit": "log return", "lookback": 3, "missing": "NaN until warm", "repaint": "no"},
    "ret_12": {"formula": "ln(C[i]/C[i-12])", "unit": "log return", "lookback": 12, "missing": "NaN until warm", "repaint": "no"},
    "atr_rel_14": {"formula": "Wilder ATR14 / C[i]", "unit": "relative", "lookback": 14, "missing": "NaN until warm", "repaint": "no"},
    "range_rel": {"formula": "(H-L)/C", "unit": "relative", "lookback": 0, "missing": "-", "repaint": "no"},
    "body_rel": {"formula": "(C-O)/(H-L) (0 when H==L)", "unit": "[-1,1]", "lookback": 0, "missing": "-", "repaint": "no"},
    "dist_ema20_atr": {"formula": "(C-EMA20)/ATR14", "unit": "ATR units", "lookback": 20, "missing": "NaN until warm", "repaint": "no"},
    "rsi_14": {"formula": "Wilder RSI14/100 - 0.5", "unit": "[-0.5,0.5]", "lookback": 15, "missing": "NaN until warm", "repaint": "no"},
    "tv_rel_48": {"formula": "ln(TV / median(TV[i-47..i]))", "unit": "log ratio (tick volume = activity, not traded volume)", "lookback": 48,
                  "missing": "NaN when median 0", "repaint": "no"},
}

TARGETS = {
    "DIR3_H12": {"formula": "r = ln(C[i+12]/C[i]); DOWN if r < -band, UP if r > band, else FLAT", "horizon_bars": 12,
                 "classes": ["DOWN", "FLAT", "UP"], "neutral": "|r| < band, band = 0.35 * atr_rel_14[i] * sqrt(12) (known at i)",
                 "available_at": "close of bar i+12"},
    "LOGRET_H": {"formula": "ln(C[i+h]/C[i])", "horizon_bars": "h", "available_at": "close of bar i+h"},
}


def schema_id(names: list[str]) -> str:
    return "FS-" + hashlib.sha256(json.dumps([VERSION, names], sort_keys=False).encode()).hexdigest()[:12]


def features(b, names: list[str]) -> np.ndarray:
    from .align_mean import atr_wilder
    from .multi_indicator import _ema
    from ..strategies.indicators import rsi
    c, o, h, l, tv = (np.asarray(x, float) for x in (b.c, b.o, b.h, b.l, b.tv))  # noqa: E741
    out = {}
    lc = np.log(c)

    def lag(k):
        r = np.full(len(c), np.nan)
        r[k:] = lc[k:] - lc[:-k]
        return r
    atr = atr_wilder(h, l, c, 14)
    if "ret_1" in names:
        out["ret_1"] = lag(1)
    if "ret_3" in names:
        out["ret_3"] = lag(3)
    if "ret_12" in names:
        out["ret_12"] = lag(12)
    if "atr_rel_14" in names:
        out["atr_rel_14"] = atr / c
    if "range_rel" in names:
        out["range_rel"] = (h - l) / c
    if "body_rel" in names:
        rg = h - l
        out["body_rel"] = np.where(rg > 0, (c - o) / np.where(rg > 0, rg, 1), 0.0)
    if "dist_ema20_atr" in names:
        e = _ema(c, 20)
        e[:19] = np.nan
        out["dist_ema20_atr"] = (c - e) / atr
    if "rsi_14" in names:
        out["rsi_14"] = np.array([np.nan if v is None else v / 100.0 - 0.5 for v in rsi(list(c), 14)])
    if "tv_rel_48" in names:
        m = np.full(len(c), np.nan)
        for i in range(47, len(c)):
            md = np.median(tv[i - 47:i + 1])
            m[i] = np.log(tv[i] / md) if md > 0 and tv[i] > 0 else np.nan
        out["tv_rel_48"] = m
    unknown = [n for n in names if n not in FEATURES]
    if unknown:
        raise ValueError(f"UNKNOWN_FEATURES:{unknown}")
    return np.column_stack([out[n] for n in names])


def target_dir3(b, h: int = 12, band_k: float = 0.35) -> tuple[np.ndarray, np.ndarray]:
    """Class 0/1/2 = DOWN/FLAT/UP and the label availability time; NaN (-1) when i+h does not exist."""
    from .align_mean import atr_wilder
    c = np.asarray(b.c, float)
    atr_rel = atr_wilder(b.h, b.l, c, 14) / c
    y = np.full(len(c), -1, dtype=int)
    t_end = np.full(len(c), np.nan)
    tf = float(b.t[1] - b.t[0]) if len(b.t) > 1 else 60.0
    for i in range(len(c) - h):
        if not np.isfinite(atr_rel[i]):
            continue
        r = np.log(c[i + h] / c[i])
        band = band_k * atr_rel[i] * np.sqrt(h)
        y[i] = 0 if r < -band else (2 if r > band else 1)
        t_end[i] = b.t[i + h] + tf
    return y, t_end


def dataset(b, names: list[str], tf_s: int, h: int = 12) -> dict:
    X = features(b, names)
    y, t_end = target_dir3(b, h)
    t_obs = np.asarray(b.t, float) + tf_s
    ok = np.isfinite(X).all(axis=1) & (y >= 0)
    return {"X": X[ok], "y": y[ok], "t_obs": t_obs[ok], "t_end": t_end[ok], "idx": np.where(ok)[0], "names": names, "schema": schema_id(names),
            "target": "DIR3_H12" if h == 12 else f"DIR3_H{h}", "horizon_bars": h}
