"""Long-Horizon Probabilistic Price Forecast Engine (Apollo23 TASK 012) - exact elapsed horizons 24h / 36h / 48h / 72h.

Output is a DISTRIBUTION of the log-return to the first observed price at or after t + H seconds (never "H bars"), with q05..q95, P(DOWN/
FLAT/UP), median / mean, volatility and an uncertainty status - never a single certain price. Baseline model (production base, as the spec
requires a direct-horizon model): empirical quantiles of historical non-overlapping direct H-returns scaled by the current/historical
volatility ratio. Probabilities/quantiles are labelled UNCALIBRATED until a separate CALIB block shows coverage within tolerance.
Mode OFF / REPLAY / SHADOW / DISPLAY_ONLY; Decision Tree weight OFF; execution HARD OFF. Separate from forecast_shadow (5/15/30 m).
"""
from __future__ import annotations

import bisect
import math

HORIZONS_S = {"24h": 86400, "36h": 129600, "48h": 172800, "72h": 259200}
QUANTILES = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)
ENGINE = "PMW-LHFE-EMPIRICAL-DIRECT-1"


def direct_returns(ts: list[float], px: list[float], horizon_s: int, max_fill_s: float, step: int = 1) -> list[tuple[float, float]]:
    """(t, log(P(t+H)/P(t))) using the first observation at/after t+H within max_fill_s (no unlimited forward fill, no interpolation)."""
    out = []
    for i in range(0, len(ts), step):
        j = bisect.bisect_left(ts, ts[i] + horizon_s)
        if j < len(ts) and ts[j] - (ts[i] + horizon_s) <= max_fill_s:
            out.append((ts[i], math.log(px[j] / px[i])))
    return out


def _q(xs, p):
    xs = sorted(xs)
    k = (len(xs) - 1) * p
    f, c = math.floor(k), math.ceil(k)
    return xs[f] if f == c else xs[f] + (xs[c] - xs[f]) * (k - f)


def _vol(ts, px, end_t, window_s):
    rs = [math.log(px[i] / px[i - 1]) for i in range(1, len(ts)) if end_t - window_s <= ts[i] <= end_t]
    if len(rs) < 10:
        return None
    m = sum(rs) / len(rs)
    return math.sqrt(sum((r - m) ** 2 for r in rs) / (len(rs) - 1))


def forecast(ts: list[float], px: list[float], horizon: str, *, as_of: float | None = None, flat_band: float = 0.001, max_fill_s: float = 3600,
             min_samples: int = 60, calib_frac: float = 0.25) -> dict:
    if horizon not in HORIZONS_S:
        raise ValueError(f"horizon: {list(HORIZONS_S)}")
    H = HORIZONS_S[horizon]
    as_of = ts[-1] if as_of is None else as_of
    k = bisect.bisect_right(ts, as_of)
    ts, px = ts[:k], px[:k]                                         # nothing after as_of is visible
    if len(ts) < 50:
        return {"horizon": horizon, "status": "UNAVAILABLE", "reason": "INSUFFICIENT_HISTORY", "engine": ENGINE}
    age = as_of - ts[-1]
    # samples must have MATURED before as_of: their target time t + H <= last observed time
    step = max(1, int(round(H / max(1.0, (ts[-1] - ts[0]) / max(1, len(ts) - 1)) / 6)))
    rs = [(t, r) for t, r in direct_returns(ts, px, H, max_fill_s, step) if t + H <= ts[-1]]
    if len(rs) < min_samples:
        return {"horizon": horizon, "status": "LOW_SAMPLE", "samples": len(rs), "engine": ENGINE}
    hist_vol = _vol(ts, px, ts[-1], ts[-1] - ts[0])
    cur_vol = _vol(ts, px, ts[-1], 7 * 86400)
    scale = (cur_vol / hist_vol) if (cur_vol and hist_vol) else 1.0
    cut = int(len(rs) * (1 - calib_frac))
    fit, cal = [r for _, r in rs[:cut]], [r for _, r in rs[cut:]]
    qs_fit = {p: _q(fit, p) for p in (0.05, 0.95)}
    cover = sum(1 for r in cal if qs_fit[0.05] <= r <= qs_fit[0.95]) / len(cal) if cal else None
    calibrated = cover is not None and len(cal) >= 30 and abs(cover - 0.90) <= 0.05
    allr = [r * scale for _, r in rs]
    qv = {f"q{int(p * 100):02d}": _q(allr, p) for p in QUANTILES}
    n = len(allr)
    up = sum(1 for r in allr if r > flat_band) / n
    dn = sum(1 for r in allr if r < -flat_band) / n
    last = px[-1]
    return {"horizon": horizon, "horizon_seconds": H, "as_of": as_of, "status": "STALE" if age > 2 * 3600 else "OK",
            "calibration": "CALIBRATED" if calibrated else "UNCALIBRATED", "calib_coverage_q05_q95": cover, "calib_samples": len(cal),
            "samples": n, "log_return_quantiles": qv, "price_quantiles": {k2: last * math.exp(v) for k2, v in qv.items()},
            "p_down": dn, "p_flat": 1 - up - dn, "p_up": up, "median_log_return": qv["q50"], "mean_log_return": sum(allr) / n,
            "volatility_h": math.sqrt(sum((r - sum(allr) / n) ** 2 for r in allr) / (n - 1)), "vol_scale": scale,
            "target_policy": f"pierwsza obserwacja >= t+{H}s (maks. {int(max_fill_s)} s opóźnienia), bez interpolacji",
            "mode": "SHADOW / DISPLAY_ONLY", "execution": "HARD_OFF", "engine": ENGINE,
            "note": "rozkład możliwych zmian – nie pewna cena; zgodność modeli to nie prawdopodobieństwo"}
