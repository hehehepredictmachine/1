"""OrderStatisticDispersionVolatility - experimental robust dispersion estimator (PMW-MM-ROBUSTVOL-1). DETERMINISTIC_INDICATOR.

Not a standard volatility measure: its scale, lag and usefulness are measured against ATR / log-return std / MAD in `benchmark()`.
For the N closed-bar prices of a window (source configurable, default close):
 1. validate (N >= min_samples, finite, > 0);
 2. optional winsorisation-like clipping of the INPUT samples at the window's own [q_lo, q_hi] quantiles (no data outside the
    window; with fewer than `min_clip_samples` samples clipping is skipped and flagged);
 3. sort ascending;  4. relative adjacent gaps g_i = (p_(i+1) - p_(i)) / max(|p_(i)|, eps);
 5. aggregate with the median (default) or a trimmed mean -> dimensionless relative dispersion per sorted step.
    (A plain sum of sorted gaps telescopes to (max-min)/~p - that is why a robust per-gap statistic is used.)
Time-aware variant (separate output): z_price = (p - median)/MAD_scale, z_time = (rank in time)/(N-1); samples are still ordered by
price; d_i = sqrt(dz_price_i^2 + lambda^2 dz_time_i^2) between price-adjacent samples, aggregated by the median. lambda = 0 reproduces a
(scaled) sorted-price statistic; temporal placement changes the value only through lambda.
Direction is NOT inferable from either dispersion (sorting destroys the path): `path` = sum of chronological log returns / (sqrt(N-1) *
robust sd of those returns), a separate signed statistic.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np

VERSION = "PMW-MM-ROBUSTVOL-1"


@dataclass
class RobustVolConfig:
    lookback: int = 48
    source: str = "CLOSE"
    clip: bool = True
    q_lo: float = 0.05
    q_hi: float = 0.95
    min_clip_samples: int = 20
    aggregate: str = "MEDIAN"          # MEDIAN | TRIMMED_MEAN
    trim: float = 0.1
    lambda_time: float = 1.0
    min_samples: int = 10
    eps: float = 1e-12

    def validate(self):
        if self.lookback < 3 or self.min_samples < 3 or self.min_samples > self.lookback:
            raise ValueError("ROBUSTVOL_LOOKBACK_INVALID")
        if not (0 <= self.q_lo < self.q_hi <= 1) or self.aggregate not in ("MEDIAN", "TRIMMED_MEAN") or not (0 <= self.trim < 0.5):
            raise ValueError("ROBUSTVOL_PARAM_INVALID")
        if self.lambda_time < 0 or self.source not in ("CLOSE", "TYPICAL", "MEDIAN", "WEIGHTED_CLOSE"):
            raise ValueError("ROBUSTVOL_PARAM_INVALID")


def _agg(x: np.ndarray, how: str, trim: float) -> float:
    if how == "MEDIAN":
        return float(np.median(x))
    k = int(len(x) * trim)
    s = np.sort(x)
    s = s[k:len(s) - k] if len(s) - 2 * k > 0 else s
    return float(s.mean())


def window_stat(p: np.ndarray, cfg: RobustVolConfig) -> dict:
    p = np.asarray(p, float)
    if len(p) < cfg.min_samples:
        return {"status": "INSUFFICIENT_SAMPLES", "n": int(len(p))}
    if not np.all(np.isfinite(p)) or np.any(p <= 0):
        return {"status": "INVALID_INPUT", "n": int(len(p))}
    flags = []
    x = p.copy()
    if cfg.clip:
        if len(x) >= cfg.min_clip_samples:
            lo, hi = np.quantile(x, [cfg.q_lo, cfg.q_hi])
            x = np.clip(x, lo, hi)
        else:
            flags.append("CLIP_SKIPPED_SMALL_SAMPLE")
    order = np.argsort(x, kind="stable")
    s = x[order]
    gaps = np.diff(s) / np.maximum(np.abs(s[:-1]), cfg.eps)
    disp = _agg(gaps, cfg.aggregate, cfg.trim)
    med = np.median(x)
    mad = float(np.median(np.abs(x - med))) * 1.4826
    if mad <= cfg.eps:
        ta, flags = 0.0, flags + ["FLAT_WINDOW"]
    else:
        zp = (s - med) / mad
        zt = (order / (len(x) - 1.0))
        d = np.sqrt(np.diff(zp) ** 2 + (cfg.lambda_time ** 2) * np.diff(zt) ** 2)
        ta = float(np.median(d))
    r = np.diff(np.log(p))
    rs = float(np.median(np.abs(r - np.median(r)))) * 1.4826
    path = float(r.sum() / (math.sqrt(len(r)) * rs)) if rs > cfg.eps else (0.0 if abs(r.sum()) <= cfg.eps else math.copysign(math.inf, r.sum()))
    return {"status": "OK", "n": int(len(p)), "sorted_dispersion": disp, "time_aware_dispersion": ta, "path": path if math.isfinite(path) else None,
            "path_status": "OK" if math.isfinite(path) else "DEGENERATE_RETURNS", "flags": flags,
            "units": {"sorted_dispersion": "relative price step (dimensionless)", "time_aware_dispersion": "robust z-units (dimensionless)",
                      "path": "signed robust t-like statistic of chronological log returns"}}


def series(t_open, h, l, c, cfg: RobustVolConfig) -> dict:  # noqa: E741
    cfg.validate()
    from .align_mean import price
    p = price(cfg.source, np.asarray(h, float), np.asarray(l, float), np.asarray(c, float))
    n = len(p)
    out = {k: np.full(n, np.nan) for k in ("sorted_dispersion", "time_aware_dispersion", "path")}
    status = ["NOT_READY"] * n
    for i in range(cfg.lookback - 1, n):
        w = window_stat(p[i + 1 - cfg.lookback:i + 1], cfg)
        status[i] = w["status"]
        if w["status"] == "OK":
            for k in out:
                if w.get(k) is not None:
                    out[k][i] = w[k]
    return {"version": VERSION, "config": asdict(cfg), **out, "status": status}


def baselines(h, l, c, n: int) -> dict:  # noqa: E741
    """ATR(n) / close, std of log returns, MAD-scaled log-return dispersion - same closed-bar window."""
    from .align_mean import atr_wilder
    c = np.asarray(c, float)
    r = np.r_[np.nan, np.diff(np.log(c))]
    std, mad = np.full(len(c), np.nan), np.full(len(c), np.nan)
    for i in range(n, len(c)):
        w = r[i + 1 - n:i + 1]
        std[i] = np.std(w)
        mad[i] = np.median(np.abs(w - np.median(w))) * 1.4826
    return {"atr_rel": atr_wilder(h, l, c, n) / c, "std_logret": std, "mad_logret": mad}


def benchmark(h, l, c, cfg: RobustVolConfig) -> dict:  # noqa: E741
    import time
    t0 = time.perf_counter()
    s = series(None, h, l, c, cfg)
    dt = time.perf_counter() - t0
    b = baselines(h, l, c, cfg.lookback)
    out = {"runtime_s": dt, "bars": int(len(c)), "correlations": {}, "scale": {}}
    for k in ("sorted_dispersion", "time_aware_dispersion"):
        x = s[k]
        out["scale"][k] = {"median": float(np.nanmedian(x)) if np.isfinite(x).any() else None, "p90": float(np.nanpercentile(x, 90)) if np.isfinite(x).any() else None}
        for bk, bv in b.items():
            m = np.isfinite(x) & np.isfinite(bv)
            out["correlations"][f"{k}~{bk}"] = float(np.corrcoef(x[m], bv[m])[0, 1]) if m.sum() > 30 and np.std(x[m]) > 0 and np.std(bv[m]) > 0 else None
    for bk, bv in b.items():
        out["scale"][bk] = {"median": float(np.nanmedian(bv)) if np.isfinite(bv).any() else None}
    return out
