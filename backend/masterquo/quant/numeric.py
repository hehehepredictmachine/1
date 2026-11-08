"""Shared numeric core of PMW Quant Core (PMW-QUANT-NUM-1). float64 everywhere; no silent nan_to_num.

Every function either returns a finite result or raises NumericError with a named reason (ZERO_VARIANCE, SMALL_SAMPLE, SINGULAR,
NON_FINITE_INPUT, ZERO_DENOMINATOR ...). Callers turn the error into an unavailable result with that reason - never into 0 / 0.5.

Contents: simple / log returns, rolling mean / variance (Welford, stable), quantiles, historical and EWMA volatility, GARCH(1,1) variance
recursion for given parameters, percent <-> decimal scale, time-aligned covariance / correlation with PSD repair (eigenvalue floor +
shrinkage) and sample-size checks, stable log-sum-exp / softmax, log loss, Brier score, reliability bins with counts + ECE, regression
metrics, moving-block bootstrap for metrics of dependent series.
Square-root-of-time scaling is NOT applied anywhere implicitly (it assumes i.i.d. increments; a caller must ask for it by name).
"""
from __future__ import annotations

import math

import numpy as np

VERSION = "PMW-QUANT-NUM-1"
EPS = 1e-15


class NumericError(ValueError):
    pass


def _arr(x, what: str = "x", min_n: int = 1) -> np.ndarray:
    a = np.asarray(x, dtype=np.float64)
    if a.ndim == 0:
        a = a.reshape(1)
    if a.size < min_n:
        raise NumericError(f"SMALL_SAMPLE:{what}:{a.size}<{min_n}")
    if not np.all(np.isfinite(a)):
        raise NumericError(f"NON_FINITE_INPUT:{what}")
    return a


# ------------------------------------------------------------------------------------------------ returns and statistics
def simple_returns(prices) -> np.ndarray:
    p = _arr(prices, "prices", 2)
    if np.any(p <= 0):
        raise NumericError("NON_POSITIVE_PRICE")
    return p[1:] / p[:-1] - 1.0


def log_returns(prices) -> np.ndarray:
    p = _arr(prices, "prices", 2)
    if np.any(p <= 0):
        raise NumericError("NON_POSITIVE_PRICE")
    return np.diff(np.log(p))


def rolling_mean_var(x, window: int) -> tuple[np.ndarray, np.ndarray]:
    """Welford update / downdate: stable for long series with a large mean (prices). ddof=1. First window-1 values are NaN-free by
    construction - the output starts at index window-1 (length n-window+1)."""
    a = _arr(x, "x", window)
    if window < 2:
        raise NumericError("WINDOW_TOO_SMALL")
    n = len(a)
    means, vars_ = np.empty(n - window + 1), np.empty(n - window + 1)
    m, s = 0.0, 0.0
    for i in range(window):
        d = a[i] - m
        m += d / (i + 1)
        s += d * (a[i] - m)
    means[0], vars_[0] = m, max(s / (window - 1), 0.0)
    for i in range(window, n):
        old, new = a[i - window], a[i]
        m_new = m + (new - old) / window
        s += (new - old) * (new - m_new + old - m)
        m = m_new
        means[i - window + 1], vars_[i - window + 1] = m, max(s / (window - 1), 0.0)
    return means, vars_


def quantiles(x, qs=(0.05, 0.5, 0.95)) -> dict:
    a = _arr(x, "x", 1)
    return {f"q{int(round(q * 100)):02d}": float(np.quantile(a, q)) for q in qs}


def hist_vol(returns, ddof: int = 1) -> float:
    r = _arr(returns, "returns", ddof + 2)
    v = float(np.var(r, ddof=ddof))
    if v <= 0:
        raise NumericError("ZERO_VARIANCE")
    return math.sqrt(v)


def ewma_vol(returns, lam: float = 0.94, seed_n: int = 20) -> np.ndarray:
    """RiskMetrics recursion sigma2_t = lam * sigma2_{t-1} + (1 - lam) * r_{t-1}^2, seeded with the variance of the first seed_n returns."""
    r = _arr(returns, "returns", seed_n + 1)
    if not 0 < lam < 1:
        raise NumericError("LAMBDA_OUT_OF_RANGE")
    s2 = np.empty(len(r) - seed_n + 1)
    s2[0] = float(np.mean(r[:seed_n] ** 2))
    if s2[0] <= 0:
        raise NumericError("ZERO_VARIANCE")
    for i, x in enumerate(r[seed_n:], start=1):
        s2[i] = lam * s2[i - 1] + (1 - lam) * x * x
    return np.sqrt(s2)


def garch11_forecast(returns, omega: float, alpha: float, beta: float, h: int = 1) -> dict:
    """Variance recursion for GIVEN parameters (fitting belongs to the VOL_GARCH family); h-step forecast of the per-bar variance.
    Requires omega > 0, alpha, beta >= 0, alpha + beta < 1 (covariance stationary)."""
    r = _arr(returns, "returns", 5)
    if omega <= 0 or alpha < 0 or beta < 0 or alpha + beta >= 1:
        raise NumericError("GARCH_PARAMS_NOT_STATIONARY")
    lr = omega / (1 - alpha - beta)
    s2 = lr
    for x in r:
        s2 = omega + alpha * x * x + beta * s2
    path = [lr + (alpha + beta) ** (k - 1) * (s2 - lr) for k in range(1, h + 1)]
    return {"variance_next": float(s2), "variance_path": [float(v) for v in path], "long_run_variance": float(lr),
            "variance_sum_h": float(sum(path)), "note": "suma wariancji po krokach (bez skalowania pierwiastkiem czasu)"}


def to_decimal(v: float, scale: str) -> float:
    if scale == "decimal":
        return float(v)
    if scale == "percent":
        return float(v) / 100.0
    raise NumericError(f"SCALE_UNKNOWN:{scale}")


def sqrt_time(sigma: float, h: int) -> float:
    """Explicit i.i.d. scaling - only when the caller accepts that assumption."""
    if h <= 0:
        raise NumericError("HORIZON_INVALID")
    return float(sigma) * math.sqrt(h)


# ------------------------------------------------------------------------------------------------ covariance
def align(series: dict[str, dict[float, float]]) -> tuple[list[str], np.ndarray, list[float]]:
    """{name: {t: value}} -> (names, matrix [T x k] on the COMMON timestamps only, timestamps). No forward fill."""
    names = sorted(series)
    common = None
    for n in names:
        ks = {float(t) for t, v in series[n].items() if v is not None and math.isfinite(v)}
        common = ks if common is None else common & ks
    ts = sorted(common or [])
    return names, np.array([[series[n][t] for n in names] for t in ts], dtype=np.float64).reshape(len(ts), len(names)), ts


def psd_repair(S, floor_rel: float = 1e-10) -> tuple[np.ndarray, dict]:
    S = _arr(S, "cov", 1)
    if S.ndim != 2 or S.shape[0] != S.shape[1]:
        raise NumericError("COV_NOT_SQUARE")
    S = 0.5 * (S + S.T)
    w, V = np.linalg.eigh(S)
    floor = max(float(np.max(np.abs(w))) * floor_rel, EPS)
    clipped = int(np.sum(w < floor))
    w2 = np.maximum(w, floor)
    R = (V * w2) @ V.T
    return 0.5 * (R + R.T), {"min_eig_before": float(w.min()), "clipped_eigs": clipped, "cond_after": float(w2.max() / w2.min())}


def covariance(X, *, min_obs_per_var: int = 5, shrink: float | None = None) -> dict:
    """Sample covariance of aligned columns (ddof=1) + optional shrinkage towards the diagonal + PSD repair; refuses n < k * min_obs."""
    A = _arr(X, "X", 2)
    if A.ndim != 2:
        raise NumericError("X_NOT_2D")
    n, k = A.shape
    if n < max(3, k * min_obs_per_var):
        raise NumericError(f"SMALL_SAMPLE:cov:{n}<{max(3, k * min_obs_per_var)}")
    S = np.cov(A, rowvar=False, ddof=1).reshape(k, k)
    if np.any(np.diag(S) <= 0):
        raise NumericError("ZERO_VARIANCE")
    lam = shrink
    if lam is None:                                   # simple data-driven intensity: k / n (bounded) - documented, not tuned on outcomes
        lam = min(0.5, k / n)
    S = (1 - lam) * S + lam * np.diag(np.diag(S))
    R, info = psd_repair(S)
    d = np.sqrt(np.diag(R))
    C = R / np.outer(d, d)
    np.fill_diagonal(C, 1.0)
    return {"cov": R, "corr": C, "n": n, "k": k, "shrinkage": lam, **info}


# ------------------------------------------------------------------------------------------------ probabilities
def logsumexp(z, axis: int = -1) -> np.ndarray:
    z = _arr(z, "z", 1)
    m = np.max(z, axis=axis, keepdims=True)
    return (m + np.log(np.sum(np.exp(z - m), axis=axis, keepdims=True))).squeeze(axis)


def softmax(z, axis: int = -1) -> np.ndarray:
    z = _arr(z, "z", 1)
    e = np.exp(z - np.max(z, axis=axis, keepdims=True))
    return e / np.sum(e, axis=axis, keepdims=True)


def sigmoid(x) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    return np.where(x >= 0, 1 / (1 + np.exp(-np.abs(x))), np.exp(-np.abs(x)) / (1 + np.exp(-np.abs(x))))


def logit(p, eps: float = 1e-9) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=np.float64), eps, 1 - eps)          # explicit clip of the LOG argument only (documented)
    return np.log(p) - np.log1p(-p)


def _check_binary(p, y) -> tuple[np.ndarray, np.ndarray]:
    p, y = _arr(p, "p", 1), _arr(y, "y", 1)
    if p.shape != y.shape:
        raise NumericError("SHAPE_MISMATCH")
    if np.any((p < 0) | (p > 1)):
        raise NumericError("PROBABILITY_OUT_OF_RANGE")
    if np.any((y != 0) & (y != 1)):
        raise NumericError("LABEL_NOT_BINARY")
    return p, y


def log_loss(p, y, eps: float = 1e-12) -> float:
    p, y = _check_binary(p, y)
    q = np.clip(p, eps, 1 - eps)
    return float(-np.mean(y * np.log(q) + (1 - y) * np.log1p(-q)))


def brier(p, y) -> float:
    p, y = _check_binary(p, y)
    return float(np.mean((p - y) ** 2))


def reliability(p, y, n_bins: int = 10, min_count: int = 1) -> dict:
    """Equal-width bins: count, mean predicted, observed frequency; ECE = sum_b n_b / N * |obs_b - pred_b| over bins with n_b >= min_count."""
    p, y = _check_binary(p, y)
    edges = np.linspace(0, 1, n_bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1], right=False), 0, n_bins - 1)
    bins, ece, used = [], 0.0, 0
    for b in range(n_bins):
        m = idx == b
        c = int(m.sum())
        if c == 0:
            bins.append({"lo": float(edges[b]), "hi": float(edges[b + 1]), "n": 0, "pred": None, "obs": None})
            continue
        pr, ob = float(p[m].mean()), float(y[m].mean())
        bins.append({"lo": float(edges[b]), "hi": float(edges[b + 1]), "n": c, "pred": pr, "obs": ob})
        if c >= min_count:
            ece += c * abs(ob - pr)
            used += c
    return {"bins": bins, "ece": (ece / used) if used else None, "n": int(len(p)), "n_in_scored_bins": used}


def regression_metrics(pred, y) -> dict:
    pred, y = _arr(pred, "pred", 1), _arr(y, "y", 1)
    if pred.shape != y.shape:
        raise NumericError("SHAPE_MISMATCH")
    e = pred - y
    return {"mae": float(np.mean(np.abs(e))), "rmse": float(math.sqrt(np.mean(e * e))), "bias": float(np.mean(e)), "n": int(len(y))}


def auc(p, y) -> float | None:
    p, y = _check_binary(p, y)
    pos, neg = p[y == 1], p[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return None
    order = np.argsort(np.concatenate([pos, neg]), kind="mergesort")
    ranks = np.empty(len(order))
    allv = np.concatenate([pos, neg])[order]
    i = 0
    r = np.arange(1, len(order) + 1, dtype=np.float64)
    while i < len(allv):                                 # average ranks for ties
        j = i
        while j + 1 < len(allv) and allv[j + 1] == allv[i]:
            j += 1
        r[i:j + 1] = (i + j + 2) / 2
        i = j + 1
    ranks[order] = r
    return float((ranks[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


# ------------------------------------------------------------------------------------------------ bootstrap
def block_bootstrap(values, stat=np.mean, *, block: int | None = None, n_boot: int = 1000, seed: int = 7, alpha: float = 0.10) -> dict:
    """Moving-block bootstrap of a statistic of a time-ordered series (keeps short-range dependence). Percentile interval."""
    v = _arr(values, "values", 2)
    n = len(v)
    b = int(block or max(1, round(n ** (1 / 3))))
    if b >= n:
        raise NumericError("BLOCK_TOO_LONG")
    rng = np.random.Generator(np.random.PCG64(seed))
    k = int(math.ceil(n / b))
    starts = rng.integers(0, n - b + 1, size=(n_boot, k))
    idx = (starts[:, :, None] + np.arange(b)[None, None, :]).reshape(n_boot, -1)[:, :n]
    stats = np.array([stat(v[i]) for i in idx], dtype=np.float64)
    return {"estimate": float(stat(v)), "lo": float(np.quantile(stats, alpha / 2)), "hi": float(np.quantile(stats, 1 - alpha / 2)),
            "level": 1 - alpha, "block": b, "n_boot": n_boot, "seed": seed, "n": n, "method": "moving block bootstrap (percentyle)"}


def max_drawdown(pnl) -> float:
    c = np.cumsum(_arr(pnl, "pnl", 1))
    peak = np.maximum.accumulate(np.concatenate([[0.0], c]))[1:]
    return float(np.max(peak - c)) if len(c) else 0.0
