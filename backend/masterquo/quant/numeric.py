"""Shared numeric core of PMW Quant Core (PMW-QUANT-NUM-1). float64 everywhere; no silent nan_to_num.

Every function either returns a finite result or raises NumericError with a named reason (ZERO_VARIANCE, SMALL_SAMPLE, SINGULAR,
NON_FINITE_INPUT, ZERO_DENOMINATOR ...). Callers turn the error into an unavailable result with that reason - never into 0 / 0.5.

Contents: log returns, rolling mean / variance (Welford, stable), quantiles, historical volatility, GARCH(1,1) variance recursion for
given parameters, time-aligned covariance / correlation with PSD repair (eigenvalue floor + shrinkage) and sample-size checks, stable
softmax, log loss, Brier score, reliability bins with counts + ECE, regression metrics, moving-block bootstrap for metrics of dependent
series. (1.46 arch, I0114: simple_returns, EWMA volatility, percent/decimal scale, sqrt-of-time scaling and log-sum-exp had no caller
and were removed.)
Square-root-of-time scaling is NOT applied anywhere implicitly (it assumes i.i.d. increments; a caller must apply it explicitly).
"""
from __future__ import annotations

import math
from itertools import pairwise

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


# ------------------------------------------------------------------------------------------------ shared calibration metrics (1.46 arch, I0054)
# The consumers had their own copies with other constants. The ones below are THE implementations, each with the consumer's exact
# convention (results bit-for-bit as before - tests/test_arch146_w2_quant_core.py pins them on fixed arrays):
#   log_loss            (above) Quant MetaModel: checked input (NumericError), clip 1e-12, log1p
#   log_loss_clipped    Monte Carlo validation (montecarlo/validate.logloss): clip eps = 1e-4, no input check
#   log_loss_multiclass Training Center DOWN/FLAT/UP (trainhub/learn.logloss): true-class probability, clip [1e-12, 1]
#   reliability         (below) Quant: equal-width bins on p in [0, 1]
#   ece_confidence      Training Center (trainhub/learn.ece): top-label confidence max p in [1/3, 1]
# METRIC_VARIANTS lists every variant that stays separate and why (the bootstraps: another resampling scheme / RNG stream / interval
# each - unifying them changes the numbers of the gates that read them, i.e. decisions; that is Etap 4 work, not a refactor).
METRIC_VARIANTS = {
    "log_loss": {"quant/numeric.log_loss": "clip 1e-12, log1p, NumericError na złym wejściu",
                 "montecarlo/validate.logloss": "-> numeric.log_loss_clipped(eps=1e-4)",
                 "trainhub/learn.logloss": "-> numeric.log_loss_multiclass(eps=1e-12)"},
    "ece": {"quant/numeric.reliability": "biny równej szerokości na p w [0, 1], min_count",
            "trainhub/learn.ece": "-> numeric.ece_confidence (max p w [1/3, 1])",
            "lab/nss._ece_top, ml/scalp_task._ece, extind/trainer._ece": "własne biny – osobne bramki modułów (Etap 4)"},
    "block_bootstrap": {"quant/numeric.block_bootstrap": "moving block, PCG64(seed=7), blok n^(1/3), przedział percentylowy 1-alpha",
                        "ml/validation.block_bootstrap": "moving block, default_rng(42) per powtórzenie, blok 10, 95 %",
                        "strategies/ema_pullback_backtest.block_bootstrap": "random.Random(7), blok max(2, n^(1/3)), 90 %, expectancy/WR/PF",
                        "lab/edge.block_bootstrap_mean": "circular block, default_rng(7), blok max(2, n^(1/3)), 95 %",
                        "baskets/sfb._block_bootstrap_lcb": "random.Random(0), blok min(block, n//2), dolna granica (LCB)"},
}


def log_loss_clipped(p, y, eps: float) -> float:
    """Binary log loss with the probability clipped to [eps, 1 - eps] and NO input check (a NaN stays NaN) - the Monte Carlo validation
    convention (eps = 1e-4); log_loss() above is the checked MetaModel variant."""
    p = np.clip(np.asarray(p, float), eps, 1 - eps)
    y = np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def log_loss_multiclass(P, y, eps: float = 1e-12) -> float:
    """Multiclass log loss: -mean log P[i, y_i], the true-class probability clipped to [eps, 1] (P: n x k, y: class indices)."""
    return float(-np.mean(np.log(np.clip(P[np.arange(len(y)), y], eps, 1.0))))


def ece_confidence(P, y, bins: int = 10, lo: float = 1 / 3) -> dict:
    """Top-label ECE: confidence = max p, hit = argmax == y, equal-width bins on [lo, 1] (lo = 1/k for k classes; the Training Center
    3-class default 1/3). -> {"ece" (rounded 5), "bins": [{from, to, n, confidence, accuracy}]}."""
    conf = P.max(axis=1)
    pred = P.argmax(axis=1)
    hit = (pred == y).astype(float)
    edges = np.linspace(lo, 1.0, bins + 1)
    tot, rows = 0.0, []
    for a, b in pairwise(edges):
        m = (conf >= a) & (conf < b if b < 1 else conf <= b)
        if m.sum():
            gap = abs(hit[m].mean() - conf[m].mean())
            tot += m.sum() / len(y) * gap
            rows.append({"from": round(float(a), 3), "to": round(float(b), 3), "n": int(m.sum()), "confidence": round(float(conf[m].mean()), 4),
                         "accuracy": round(float(hit[m].mean()), 4)})
    return {"ece": round(float(tot), 5), "bins": rows}


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
