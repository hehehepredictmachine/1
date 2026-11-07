"""Shared feature code (PMW-TH-FEAT-1) - the SAME function builds the training matrix from the candle store and the live inference
row from the bridge, so training and inference cannot drift apart (no train/serve skew).

Row i = the base-timeframe candle i at its CLOSE. Every value uses only candles closed at that moment:
* base TF: log returns (1/3/6/12), ATR14 / price, candle range / body / wicks in ATR, realised volatility (12/48), RSI14, distance to
  EMA20 / EMA50 in ATR, z-score of the close (48), tick-activity ratio (tick volume / its 48-candle mean - NOT traded volume), spread in
  ATR (recorded bar spread), time of day / day of week (UTC), a flag for a gap before the candle (session break);
* higher TFs (M1 -> M5/M15/M30, M5 -> M15/M30, M15 -> M30): values of the last HIGHER-TF candle whose CLOSE is <= the base candle's
  close (availability join) - an M15/M30 candle is never used before it closed.
A row with any missing value (warm-up, missing higher-TF history) is not usable: training drops it, inference reports
DATA_INSUFFICIENT instead of predicting.
"""
from __future__ import annotations

import hashlib
import math

import numpy as np

FEATURE_SCHEMA = "PMW-TH-FEAT-1"
TF_S = {"M1": 60, "M3": 180, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600}
HTF_OF = {"M1": ("M5", "M15", "M30"), "M3": ("M15", "M30"), "M5": ("M15", "M30"), "M15": ("M30",), "M30": ()}
BASE_NAMES = ("r1", "r3", "r6", "r12", "atr_rel", "rng_atr", "body_atr", "uwick_atr", "lwick_atr", "vol12", "vol48", "rsi14", "ema20_atr",
              "ema50_atr", "z48", "tick_ratio", "spread_atr", "tod_sin", "tod_cos", "dow_sin", "dow_cos", "gap_before")
HTF_NAMES = ("r1", "rsi14", "ema20_atr", "atr_rel", "pos20")


def names(base_tf: str) -> list[str]:
    out = [f"{base_tf}_{n}" for n in BASE_NAMES]
    for h in HTF_OF[base_tf]:
        out += [f"{h}_{n}" for n in HTF_NAMES]
    return out


def schema(base_tf: str) -> dict:
    nm = names(base_tf)
    return {"version": FEATURE_SCHEMA, "base_tf": base_tf, "htf": list(HTF_OF[base_tf]), "names": nm,
            "hash": hashlib.sha256((FEATURE_SCHEMA + "|" + ",".join(nm)).encode()).hexdigest()[:16]}


# ------------------------------------------------------------------------------------------------ primitives (causal)
def _wilder(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    a = np.nanmean(x[:n])
    out[n - 1] = a
    for i in range(n, len(x)):
        a = (a * (n - 1) + x[i]) / n
        out[i] = a
    return out


def _ema(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    k = 2.0 / (n + 1)
    a = float(np.mean(x[:n]))
    out[n - 1] = a
    for i in range(n, len(x)):
        a = a + k * (x[i] - a)
        out[i] = a
    return out


def _roll(x: np.ndarray, n: int, fn) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    w = np.lib.stride_tricks.sliding_window_view(x, n)
    out[n - 1:] = fn(w, axis=1)
    return out


def _atr(h, lo, c) -> np.ndarray:
    pc = np.concatenate([[np.nan], c[:-1]])
    tr = np.nanmax(np.vstack([h - lo, np.abs(h - pc), np.abs(lo - pc)]), axis=0)
    return _wilder(tr, 14)


def _rsi(c) -> np.ndarray:
    d = np.diff(c, prepend=np.nan)
    up, dn = np.where(d > 0, d, 0.0), np.where(d < 0, -d, 0.0)
    up[0] = dn[0] = np.nan
    au, ad = _wilder(np.nan_to_num(up), 14), _wilder(np.nan_to_num(dn), 14)
    rs = np.divide(au, ad, out=np.full_like(au, np.inf), where=ad > 0)
    r = 100 - 100 / (1 + rs)
    r[np.isnan(au)] = np.nan
    return r / 100.0 - 0.5


def _lr(c: np.ndarray, k: int) -> np.ndarray:
    out = np.full(len(c), np.nan)
    out[k:] = np.log(c[k:] / c[:-k])
    return out


def _arr(cols: dict, k: str) -> np.ndarray:
    return np.asarray(cols.get(k) or [], dtype=float)


def _base(cols: dict, tf: str, point: float) -> np.ndarray:
    t, o, h, lo, c = (_arr(cols, k) for k in ("time", "open", "high", "low", "close"))
    tv, sp = _arr(cols, "tick_volume"), _arr(cols, "spread")
    n = len(c)
    if n == 0:
        return np.zeros((0, len(BASE_NAMES)))
    atr = _atr(h, lo, c)
    r1 = _lr(c, 1)
    ema20, ema50 = _ema(c, 20), _ema(c, 50)
    mean48, std48 = _roll(c, 48, np.mean), _roll(c, 48, np.std)
    tvm = _roll(tv, 48, np.mean) if len(tv) == n else np.full(n, np.nan)
    tclose = t + TF_S[tf]
    tod = (tclose % 86400) / 86400.0 * 2 * math.pi
    dow = (((tclose // 86400) + 3) % 7) / 7.0 * 2 * math.pi              # epoch day 0 = Thursday -> Monday = 0
    gap = np.zeros(n)
    gap[1:] = (np.diff(t) > TF_S[tf]).astype(float)
    with np.errstate(divide="ignore", invalid="ignore"):
        cols_out = [r1, _lr(c, 3), _lr(c, 6), _lr(c, 12), atr / c, (h - lo) / atr, (c - o) / atr, (h - np.maximum(o, c)) / atr,
                    (np.minimum(o, c) - lo) / atr, _roll(np.nan_to_num(r1), 12, np.std), _roll(np.nan_to_num(r1), 48, np.std), _rsi(c),
                    (c - ema20) / atr, (c - ema50) / atr, np.where(std48 > 0, (c - mean48) / std48, 0.0),
                    np.log((tv + 1.0) / (tvm + 1.0)) if len(tv) == n else np.full(n, np.nan),
                    (sp * point) / atr if len(sp) == n else np.full(n, np.nan), np.sin(tod), np.cos(tod), np.sin(dow), np.cos(dow), gap]
    X = np.vstack(cols_out).T
    X[:, 9][:12] = np.nan
    X[:, 10][:48] = np.nan
    return X


def _htf(cols: dict) -> np.ndarray:
    h, lo, c = (_arr(cols, k) for k in ("high", "low", "close"))
    n = len(c)
    if n == 0:
        return np.zeros((0, len(HTF_NAMES)))
    atr = _atr(h, lo, c)
    hi20, lo20 = _roll(h, 20, np.max), _roll(lo, 20, np.min)
    with np.errstate(divide="ignore", invalid="ignore"):
        pos = np.where(hi20 > lo20, (c - lo20) / (hi20 - lo20), 0.5)
        pos[np.isnan(hi20)] = np.nan
        return np.vstack([_lr(c, 1), _rsi(c), (c - _ema(c, 20)) / atr, atr / c, pos]).T


def build(cols_by_tf: dict[str, dict], base_tf: str, point: float) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """(base open times, X [n_base, n_features], feature names). Rows with NaN are returned as they are (caller decides)."""
    base = cols_by_tf.get(base_tf) or {}
    t = np.asarray(base.get("time") or [], dtype=np.int64)
    Xb = _base(base, base_tf, point)
    parts = [Xb]
    base_close = t + TF_S[base_tf]
    for htf in HTF_OF[base_tf]:
        hc = cols_by_tf.get(htf) or {}
        ht = np.asarray(hc.get("time") or [], dtype=np.int64)
        Xh = _htf(hc)
        if len(ht) == 0:
            parts.append(np.full((len(t), len(HTF_NAMES)), np.nan))
            continue
        avail = ht + TF_S[htf]                                       # an HTF candle is known only at its close
        idx = np.searchsorted(avail, base_close, side="right") - 1
        g = np.full((len(t), len(HTF_NAMES)), np.nan)
        ok = idx >= 0
        g[ok] = Xh[idx[ok]]
        parts.append(g)
    X = np.hstack(parts) if parts else np.zeros((len(t), 0))
    X[~np.isfinite(X)] = np.nan
    return t, X, names(base_tf)


def last_row(cols_by_tf: dict[str, dict], base_tf: str, point: float) -> tuple[int | None, np.ndarray | None, list[str]]:
    """Live inference: features of the newest CLOSED base candle (same code as training)."""
    t, X, nm = build(cols_by_tf, base_tf, point)
    if not len(t):
        return None, None, nm
    return int(t[-1]), X[-1], nm
