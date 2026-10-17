"""Tick-based lab modules (MQ-LAB-TICK-1.0.0). They need real quote ticks (bid/ask changes); OHLC is never used to
fake inter-quote durations. Without ticks the result is `missing_data` (module runs as a live collector / monitor).

M28 Quote-interval activity + Engle-Russell ACD(1,1) with diurnal adjustment
M31 local bid/ask kinematics (velocity / acceleration with estimation uncertainty) + forecast verification
"""
from __future__ import annotations

import math

import numpy as np

VERSION = "MQ-LAB-TICK-1.0.0"


def quote_changes(ticks: list[dict]) -> np.ndarray:
    """Times (UTC seconds) of quote CHANGES (bid or ask differs from the previous tick)."""
    t, last = [], None
    for x in ticks:
        k = (x["bid"], x["ask"])
        if k != last:
            t.append(x["t"])
            last = k
    return np.asarray(t, float)


def durations(times: np.ndarray, gap_seconds: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """Inter-quote durations; any duration > gap_seconds is a session break / outage, NOT a quiet period: it is removed
    and the ACD recursion is reset after it (explicit policy). Returns (durations, segment_ids, end_times, n_gaps)."""
    dd = np.diff(times)
    brk = (dd > gap_seconds) | (dd < 0)
    seg = np.cumsum(brk)
    keep = ~brk
    return dd[keep], seg[keep], times[1:][keep], int(brk.sum())


def diurnal(times_end: np.ndarray, d: np.ndarray, bins: int = 24) -> np.ndarray:
    """Mean duration per UTC hour (fit on the given history only); missing hours -> overall mean."""
    hrs = ((times_end % 86400) // (86400 / bins)).astype(int)
    overall = float(d.mean()) if len(d) else 1.0
    phi = np.full(bins, overall)
    for h in range(bins):
        m = hrs == h
        if m.sum() >= 5:
            phi[h] = d[m].mean()
    return np.maximum(phi, 1e-6)


def acd_filter(x: np.ndarray, seg: np.ndarray, w: float, a: float, b: float) -> np.ndarray:
    psi = np.empty(len(x))
    mean = float(x.mean()) if len(x) else 1.0
    for i in range(len(x)):
        if i == 0 or seg[i] != seg[i - 1]:
            psi[i] = mean                    # reset after a gap
        else:
            psi[i] = w + a * x[i - 1] + b * psi[i - 1]
    return psi


def fit_acd(x: np.ndarray, seg: np.ndarray) -> dict:
    """Exponential QMLE of ACD(1,1) on diurnally adjusted durations. Constraints: w>0, a,b>=0, a+b<1."""
    from scipy.optimize import minimize

    def nll(p):
        w, a, b = math.exp(p[0]), 1 / (1 + math.exp(-p[1])), 1 / (1 + math.exp(-p[2]))
        if a + b >= 0.999:
            return 1e12
        psi = acd_filter(x, seg, w, a, b)
        return float(np.sum(np.log(psi) + x / psi))
    p0 = np.array([math.log(max(1e-6, 0.1 * x.mean())), 0.0, 1.0])
    r = minimize(nll, p0, method="Nelder-Mead", options={"maxiter": 600, "xatol": 1e-4, "fatol": 1e-6})
    w, a, b = math.exp(r.x[0]), 1 / (1 + math.exp(-r.x[1])), 1 / (1 + math.exp(-r.x[2]))
    return {"omega": w, "alpha": a, "beta": b, "converged": bool(r.success), "nll": float(r.fun), "n": int(len(x))}


def acd_activity(ticks: list[dict], now_t: float, gap_seconds: float = 300.0, min_events: int = 300) -> dict:
    t = quote_changes(ticks)
    if len(t) < min_events:
        return {"status": "missing_data", "reason": f"ZA_MALO_ZMIAN_KWOTOWAN_{len(t)}_<_{min_events}", "events": int(len(t))}
    d, seg, ends, gaps = durations(t, gap_seconds)
    phi = diurnal(ends, d)
    hrs = ((ends % 86400) // 3600).astype(int)
    x = d / phi[hrs]
    fit = fit_acd(x, seg)
    psi = acd_filter(x, seg, fit["omega"], fit["alpha"], fit["beta"])
    nxt = fit["omega"] + fit["alpha"] * x[-1] + fit["beta"] * psi[-1]
    h_now = int((now_t % 86400) // 3600)
    expected_wait = float(nxt * phi[h_now])
    elapsed = float(now_t - t[-1])
    in_gap = elapsed > gap_seconds
    return {"status": "ready", "events": int(len(t)), "durations": int(len(d)), "gaps_removed": int(gaps), "fit": fit,
            "expected_wait_s": round(expected_wait, 3), "elapsed_since_last_change_s": round(elapsed, 3),
            "activity_ratio": None if in_gap else round(elapsed / expected_wait, 3) if expected_wait > 0 else None,
            "state": "SESSION_BREAK_OR_OUTAGE" if in_gap else ("UNUSUALLY_QUIET" if elapsed > 3 * expected_wait else "NORMAL"),
            "diurnal_mean_duration_s": [round(float(v), 3) for v in phi],
            "policy": f"przerwa > {gap_seconds:.0f} s = brak notowań (nie spokój); rekursja ACD resetowana po przerwie"}


def kinematics(ticks: list[dict], window_s: float = 30.0, horizon_s: float = 10.0) -> dict:
    """Local quadratic fit of mid price vs time over the last window: velocity, acceleration and their standard errors.
    A statistical description of recent quotes - not a physical law of prices."""
    if len(ticks) < 10:
        return {"status": "missing_data", "reason": "ZA_MALO_TICKOW"}
    t = np.array([x["t"] for x in ticks])
    mid = np.array([(x["bid"] + x["ask"]) / 2 for x in ticks])
    m = t >= t[-1] - window_s
    if m.sum() < 8:
        return {"status": "missing_data", "reason": "ZA_MALO_TICKOW_W_OKNIE"}
    tt = t[m] - t[-1]
    X = np.vstack([np.ones_like(tt), tt, 0.5 * tt ** 2]).T
    beta, res, rank, _ = np.linalg.lstsq(X, mid[m], rcond=None)
    dof = max(1, m.sum() - 3)
    resid = mid[m] - X @ beta
    s2 = float(resid @ resid) / dof
    cov = None
    try:
        cov = s2 * np.linalg.inv(X.T @ X)
        se = np.sqrt(np.maximum(np.diag(cov), 0))
    except np.linalg.LinAlgError:
        se = np.array([np.nan] * 3)
    fc = float(beta[0] + beta[1] * horizon_s + 0.5 * beta[2] * horizon_s ** 2)
    xf = np.array([1, horizon_s, 0.5 * horizon_s ** 2])
    fse = float(np.sqrt(max(0.0, xf @ cov @ xf + s2))) if (rank == 3 and cov is not None) else None
    return {"status": "ready", "n": int(m.sum()), "window_s": window_s, "mid": float(mid[-1]),
            "velocity_per_s": float(beta[1]), "velocity_se": float(se[1]), "acceleration_per_s2": float(beta[2]), "acceleration_se": float(se[2]),
            "forecast": {"horizon_s": horizon_s, "mid": fc, "se": fse, "issued_at_t": float(t[-1])},
            "significant_velocity": bool(abs(beta[1]) > 2 * se[1]) if np.isfinite(se[1]) else False,
            "note": "model statystyczny lokalnej trajektorii – nie prawo fizyki"}


def verify_forecasts(archive: list[dict], ticks: list[dict]) -> dict:
    """Compare archived kinematic forecasts (stored at issue time) with the first mid observed at/after their horizon."""
    if not archive or not ticks:
        return {"verified": 0}
    t = np.array([x["t"] for x in ticks])
    mid = np.array([(x["bid"] + x["ask"]) / 2 for x in ticks])
    errs, inside = [], 0
    for f in archive:
        target = f["issued_at_t"] + f["horizon_s"]
        j = int(np.searchsorted(t, target))
        if j >= len(t):
            continue
        e = mid[j] - f["mid"]
        errs.append(e)
        if f.get("se") and abs(e) <= 2 * f["se"]:
            inside += 1
    if not errs:
        return {"verified": 0}
    e = np.array(errs)
    return {"verified": len(e), "mae": float(np.abs(e).mean()), "bias": float(e.mean()), "coverage_2se": inside / len(e)}
