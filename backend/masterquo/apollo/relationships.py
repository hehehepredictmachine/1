"""Cross-market Relationship Engine (Apollo23 TASK 021) - correlation, return beta, log-price spread, spread z-score, cointegration and
lead-lag on SYNCHRONIZED log-returns. Each is a separate measure / hypothesis; none is a signal or proof of causality.

  r_t = ln(P_t / P_{t-1})                         (formula 1)
  beta_ret = Cov(r_A, r_B) / Var(r_B)             (formula 2 - hedge sizing beta)
  s_t = ln A_t - (alpha + beta_px * ln B_t)       (formula 3 - spread with the log-price regression beta, separate from beta_ret)
  z_t = (s_t - mean_w(s)) / std_w(s)              (formula 4 - rolling, past window only)
  rho(k) = Corr(r_A[t], r_B[t-k])                 (formula 5 - lead-lag; k > 0 = B leads A)
Raw CVD / delta is never compared across instruments. Candidates from the user's seeds are PROPOSED / OFF / SHADOW; indices and equity
perps RESEARCH_ONLY; OTC retired.
"""
from __future__ import annotations

import csv
import math
from pathlib import Path

VERSION = "PMW-REL-1"
CANDIDATES_FILE = Path(__file__).parent / "data" / "t021_strategy_candidates.csv"


def synchronize(a: list[tuple[float, float]], b: list[tuple[float, float]]) -> tuple[list[float], list[float], list[float]]:
    """Inner join on identical timestamps (no forward fill)."""
    mb = dict(b)
    ts = [t for t, _ in a if t in mb]
    ma = dict(a)
    return ts, [ma[t] for t in ts], [mb[t] for t in ts]


def log_returns(p: list[float]) -> list[float]:
    return [math.log(p[i] / p[i - 1]) for i in range(1, len(p))]


def _mean(x):
    return sum(x) / len(x)


def _cov(x, y):
    mx, my = _mean(x), _mean(y)
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (len(x) - 1)


def corr(x, y) -> float | None:
    if len(x) < 3:
        return None
    vx, vy = _cov(x, x), _cov(y, y)
    return _cov(x, y) / math.sqrt(vx * vy) if vx > 0 and vy > 0 else None


def return_beta(ra, rb) -> float | None:
    v = _cov(rb, rb) if len(rb) > 2 else 0
    return _cov(ra, rb) / v if v > 0 else None


def price_regression(pa, pb) -> tuple[float, float] | None:
    la, lb = [math.log(x) for x in pa], [math.log(x) for x in pb]
    v = _cov(lb, lb) if len(lb) > 2 else 0
    if v <= 0:
        return None
    beta = _cov(la, lb) / v
    return _mean(la) - beta * _mean(lb), beta


def spread(pa, pb, alpha, beta) -> list[float]:
    return [math.log(a) - (alpha + beta * math.log(b)) for a, b in zip(pa, pb)]


def zscore(s: list[float], w: int) -> list[float | None]:
    out = []
    for i in range(len(s)):
        if i < w:
            out.append(None)
            continue
        win = s[i - w:i]                                # past window only (bar i not inside its own normalisation)
        m = _mean(win)
        sd = math.sqrt(sum((x - m) ** 2 for x in win) / (w - 1))
        out.append((s[i] - m) / sd if sd > 0 else None)
    return out


def lead_lag(ra, rb, max_lag: int = 5) -> list[dict]:
    out = []
    for k in range(-max_lag, max_lag + 1):
        if k >= 0:
            x, y = ra[k:], rb[:len(rb) - k]
        else:
            x, y = ra[:len(ra) + k], rb[-k:]
        out.append({"lag": k, "corr": corr(x, y), "n": len(x)})
    return out


def adf_tstat(s: list[float]) -> float | None:
    """Dickey-Fuller t-statistic of d s_t = g * s_{t-1} + c + e (no lags) - Engle-Granger residual test (5 % crit. ~ -3.34 for 2 series)."""
    if len(s) < 20:
        return None
    y = [s[i] - s[i - 1] for i in range(1, len(s))]
    x = s[:-1]
    mx, my = _mean(x), _mean(y)
    sxx = sum((a - mx) ** 2 for a in x)
    if sxx <= 0:
        return None
    g = sum((a - mx) * (b - my) for a, b in zip(x, y)) / sxx
    c = my - g * mx
    res = [b - (c + g * a) for a, b in zip(x, y)]
    se = math.sqrt(sum(e * e for e in res) / (len(res) - 2) / sxx)
    return g / se if se > 0 else None


def analyse(a: list[tuple[float, float]], b: list[tuple[float, float]], z_window: int = 50, train_frac: float = 0.7) -> dict:
    ts, pa, pb = synchronize(a, b)
    if len(ts) < max(60, z_window + 10):
        return {"status": "INSUFFICIENT_SYNC_DATA", "n": len(ts), "version": VERSION}
    ra, rb = log_returns(pa), log_returns(pb)
    cut = int(len(pa) * train_frac)
    reg = price_regression(pa[:cut], pb[:cut])             # fitted on TRAIN only; applied forward
    if reg is None:
        return {"status": "DEGENERATE", "version": VERSION}
    alpha, beta_px = reg
    s = spread(pa, pb, alpha, beta_px)
    z = zscore(s, z_window)
    t = adf_tstat(s[:cut])
    ll = lead_lag(ra, rb)
    best = max((x for x in ll if x["corr"] is not None and x["lag"] != 0), key=lambda x: abs(x["corr"]), default=None)
    return {"status": "OK", "version": VERSION, "n": len(ts), "corr_returns": corr(ra, rb), "return_beta": return_beta(ra, rb),
            "price_beta": beta_px, "alpha": alpha, "spread_last": s[-1], "zscore_last": z[-1], "adf_t_train": t,
            "cointegration": "CANDIDATE" if t is not None and t < -3.34 else "NOT_SUPPORTED", "lead_lag": ll, "best_lag": best,
            "notes": ["korelacja ≠ przyczynowość; rozjazd ≠ automatyczny short", "beta zwrotów (hedge) ≠ beta cen (spread)"],
            "mode": "RESEARCH / SHADOW"}


def candidates() -> list[dict]:
    with open(CANDIDATES_FILE, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        scope = r.get("target_scope", "")
        status = "RESEARCH_ONLY" if "RESEARCH_ONLY" in scope else ("RISK_CONTEXT_ONLY" if "RISK_CONTEXT" in scope else "PROPOSED")
        out.append({**r, "runtime_status": status, "mode": "OFF", "active": False})
    return out
