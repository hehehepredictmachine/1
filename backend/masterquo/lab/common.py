"""Shared helpers of the 1.14 lab modules (two assets, closed bars, point-in-time).

Every lab result is wrapped in the mq-analytics provenance contract (analytics/contract.py) and additionally carries
canonical_asset, decision_role (active / shadow / research / visual_only) and implementation_status.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import numpy as np

from ..analytics import contract
from ..analytics.ta import TF_SEC

EPS = 1e-12


def ts(iso_s: str) -> float:
    return datetime.fromisoformat(iso_s.replace("Z", "+00:00")).timestamp()


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def closed(bars: list[dict]) -> list[dict]:
    """Closed bars only, ascending, de-duplicated by open time (a forming bar never reaches a lab module)."""
    seen, out = set(), []
    for b in sorted((b for b in bars if b.get("closed", True) and b.get("open_utc")), key=lambda b: b["open_utc"]):
        if b["open_utc"] in seen:
            continue
        seen.add(b["open_utc"])
        out.append(b)
    return out


def arrays(bars: list[dict]) -> dict:
    return {"o": np.array([float(b["o"]) for b in bars]), "h": np.array([float(b["h"]) for b in bars]),
            "l": np.array([float(b["l"]) for b in bars]), "c": np.array([float(b["c"]) for b in bars]),
            "tv": np.array([float(b.get("tv") or 0) for b in bars]), "t": np.array([ts(b["open_utc"]) for b in bars])}


def close_time(bar: dict, tf: str) -> str:
    return iso(ts(bar["open_utc"]) + TF_SEC[tf])


def atr(h, lo, c, n: int = 14) -> np.ndarray:
    """Wilder ATR, NaN during warm-up (n bars)."""
    tr = np.empty(len(c))
    tr[:] = np.nan
    if len(c) == 0:
        return tr
    tr[0] = h[0] - lo[0]
    tr[1:] = np.maximum(h[1:] - lo[1:], np.maximum(abs(h[1:] - c[:-1]), abs(lo[1:] - c[:-1])))
    out = np.full(len(c), np.nan)
    if len(c) < n:
        return out
    out[n - 1] = tr[:n].mean()
    for i in range(n, len(c)):
        out[i] = (out[i - 1] * (n - 1) + tr[i]) / n
    return out


def ema(x, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    out[n - 1] = np.mean(x[:n])
    a = 2.0 / (n + 1)
    for i in range(n, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def sma(x, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        cs = np.cumsum(np.insert(np.asarray(x, float), 0, 0.0))
        out[n - 1:] = (cs[n:] - cs[:-n]) / n
    return out


def rolling_std(x, n: int) -> np.ndarray:
    """Population std (ddof=0), same convention as the BB engine."""
    out = np.full(len(x), np.nan)
    for i in range(n - 1, len(x)):
        out[i] = np.std(x[i - n + 1:i + 1])
    return out


def pct_rank(window: np.ndarray, v: float) -> float | None:
    w = window[~np.isnan(window)]
    if len(w) == 0 or np.isnan(v):
        return None
    return float((w < v).sum() + 0.5 * (w == v).sum()) / len(w)


def wrap(module: str, version: str, cfg: dict, *, asset: str | None, symbol: str | None, tf: str | None, bars: list[dict],
         status: str, values: dict | None = None, reason: str | None = None, quality: list[str] | None = None,
         role: str = "shadow", t0: float | None = None, available_at: str | None = None, extra: dict | None = None) -> dict:
    out = contract.result(module, version, cfg, symbol=symbol, tf=tf, bars=bars, status=status, values=values, reason=reason,
                          quality=quality, tf_seconds=TF_SEC.get(tf or "", None), t0=t0,
                          extra={"canonical_asset": asset, "decision_role": role, **(extra or {})})
    if available_at:
        out["available_at"] = available_at
    return out


def timer() -> float:
    return time.perf_counter()
