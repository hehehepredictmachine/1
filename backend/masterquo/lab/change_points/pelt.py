"""Floored Gaussian segment cost + exact DP / guarded deferred PELT (MQL5 article #25093, independent implementation of the formulas).

C(s, e) = n * ln(max(var(s, e), eps)), var = population variance (divisor n), eps = 1e-8 * var_all.
F(t) = min_tau [F(tau) + C(tau, t) + beta], F(0) = -beta, segments >= m. beta auto = 2 ln(n).
Pruning (F(tau) + C(tau, t) > F(t)) is used ONLY when the guard passes: the minimum variance of every length-m window is >= 2 * eps;
otherwise the unpruned DP runs (still exact for the floored objective). Pruned candidates are removed DEFERRED at t + m, never immediately.
Retrospective segmentation only: not a signal, p-value or probability; never attached to earlier trades without a point-in-time snapshot.
"""
from __future__ import annotations

import math

OBJECTIVE_VERSION = "PMW-PELT-FLOORED-GAUSS-1"
INF = float("inf")
SENSITIVITY_MAX_RETURNS = 2000          # detect(sensitivity=True): above this the robustness runs are skipped (sensitivity_skipped)


class Moments:
    def __init__(self, r: list[float]):
        self.n = len(r)
        self.S = [0.0]
        self.Q = [0.0]
        # shift by the global mean for numerical stability of prefix variance
        self.mu = sum(r) / len(r) if r else 0.0
        for x in r:
            d = x - self.mu
            self.S.append(self.S[-1] + d)
            self.Q.append(self.Q[-1] + d * d)

    def var(self, s: int, e: int) -> float:
        n = e - s
        m = (self.S[e] - self.S[s]) / n
        v = (self.Q[e] - self.Q[s]) / n - m * m
        return 0.0 if v < 0 else v                  # clamp tiny negative roundoff (documented)


def segment_cost_table(r, eps):
    M = Moments(r)
    return lambda s, e: (e - s) * math.log(max(M.var(s, e), eps)), M


def guard(M: Moments, m: int, eps: float) -> bool:
    return all(M.var(i, i + m) >= 2 * eps for i in range(0, M.n - m + 1))


def solve(r: list[float], m: int = 10, beta: float | None = None, use_pruning: bool | None = None, deferred: bool = True) -> dict:
    n = len(r)
    if m < 2:
        return {"status": "INVALID_MIN_SEGMENT", "change_points": []}
    if n < 2 * m:
        return {"status": "INSUFFICIENT_DATA", "change_points": [], "n": n}
    mu = sum(r) / n
    var_all = sum((x - mu) ** 2 for x in r) / n
    if not (var_all > 0 and math.isfinite(var_all)):
        return {"status": "ZERO_GLOBAL_VARIANCE", "change_points": [], "n": n}
    eps = 1e-8 * var_all
    if beta is None or beta <= 0:
        beta = 2 * math.log(n)
    _, M = segment_cost_table(r, eps)
    g = guard(M, m, eps)
    prune = g if use_pruning is None else (use_pruning and (g or use_pruning == "FORCE"))
    F = [INF] * (n + 1)
    cp = [-1] * (n + 1)
    F[0] = -beta
    active = [0]
    prune_at: dict[int, int] = {}
    evals = 0
    # 1.46 (performance, identical result): the cost is computed inline from the prefix lists with exactly the arithmetic of
    # Moments.var / segment_cost_table and reused by the pruning test (it was evaluated twice through a lambda + method call);
    # `active` stays ascending and unique by construction (the filter keeps the order, appended starts t-m+1 grow), so the
    # sorted(set(active)) of every step is gone
    S, Q, log = M.S, M.Q, math.log
    for t in range(m, n + 1):
        best, arg = INF, -1
        St, Qt = S[t], Q[t]
        costs: dict[int, float] = {}
        for tau in active:
            if t - tau < m or F[tau] == INF:
                continue
            k = t - tau
            mean = (St - S[tau]) / k
            var = (Qt - Q[tau]) / k - mean * mean
            c = k * log(max(0.0 if var < 0 else var, eps))
            costs[tau] = c
            v = F[tau] + c + beta
            evals += 1
            if v < best:
                best, arg = v, tau
        F[t], cp[t] = best, arg
        if prune and best < INF:
            for tau in active:
                if tau in costs and F[tau] + costs[tau] > F[t] and tau not in prune_at:
                    prune_at[tau] = t + m if deferred else t
            active = [tau for tau in active if not (tau in prune_at and prune_at[tau] <= t)]
        if t - m + 1 >= m:                          # new candidate start that can host a segment of length >= m
            active.append(t - m + 1)
    if F[n] == INF:
        return {"status": "NO_LEGAL_SEGMENTATION", "change_points": []}
    cps, t = [], n
    while t > 0:
        p = cp[t]
        if p < 0 or p >= t or t - p < m:
            return {"status": "NO_LEGAL_SEGMENTATION", "change_points": []}
        if p > 0:
            cps.append(p)
        t = p
    cps.sort()
    bounds = [0, *cps, n]
    segs = []
    for a, b in zip(bounds, bounds[1:]):
        seg = r[a:b]
        mm = sum(seg) / len(seg)
        segs.append({"start": a, "end": b, "n": b - a, "mean": mm, "var": sum((x - mm) ** 2 for x in seg) / len(seg),
                     "warning": "SMALL_SEGMENT_ESTIMATE" if b - a < 30 else None})
    return {"status": "OK", "change_points": cps, "segments": segs, "objective": F[n], "beta": beta, "eps": eps, "n": n, "min_segment": m,
            "pruning_guard_passed": g, "pruning_used": bool(prune), "deferred_pruning": deferred,
            "pruning_disabled_reason": None if prune else ("GUARD_FAILED" if not g else "DISABLED"), "cost_evaluations": evals,
            "exact_solver": True, "objective_version": OBJECTIVE_VERSION}


def brute_force(r: list[float], m: int, beta: float | None = None) -> dict:
    """Plain O(n^2) DP over every legal start - the reference for parity tests."""
    return solve(r, m, beta, use_pruning=False)


def log_returns(closes: list[float]) -> list[float]:
    return [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i] > 0 and closes[i - 1] > 0]


def detect(closes: list[float], lookback_returns: int = 500, m: int = 10, beta: float | None = None, sensitivity: bool = False, tol: int = 3) -> dict:
    r = log_returns(closes)[-lookback_returns:]
    base = solve(r, m, beta)
    out = {"profile": {"lookback_returns": lookback_returns, "min_segment": m, "penalty": "auto 2 ln(n)" if not beta else beta}, **base,
           "mode": "RESEARCH / READ_ONLY (retrospektywna segmentacja – nie sygnał)"}
    if sensitivity and base["status"] == "OK" and len(r) > SENSITIVITY_MAX_RETURNS:
        # 1.46: 10 extra exact solves of an O(n^2) pure-Python DP (~40-50 s CPU for 5000 returns) ran synchronously in the API process
        out["sensitivity_skipped"] = "LOOKBACK_GT_2000"
    elif sensitivity and base["status"] == "OK":
        runs = []
        for pm in (0.5, 1, 2, 3):
            runs.append(("penalty×%s" % pm, solve(r, m, (base["beta"]) * pm)))
        for mm in (5, 10, 20):
            runs.append((f"min_len={mm}", solve(r, mm, beta)))
        for lm in (0.8, 1.0, 1.2):
            rr = log_returns(closes)[-int(lookback_returns * lm):]
            off = len(rr) - len(r)                                    # map to the base index space
            res = solve(rr, m, beta)
            res = {**res, "change_points": [c - off for c in res.get("change_points", []) if 0 < c - off < len(r)]}
            runs.append((f"lookback×{lm}", res))
        ok = [(name, x) for name, x in runs if x["status"] == "OK"]
        out["sensitivity"] = []
        for c in base["change_points"]:
            sup = [name for name, x in ok if any(abs(c - d) <= tol for d in x["change_points"])]
            frac = len(sup) / len(ok) if ok else 0
            out["sensitivity"].append({"index": c, "support_count": len(sup), "eligible_runs": len(ok), "date_tolerance_bars": tol,
                                       "robustness_label": "STABLE" if frac >= 0.75 else ("MIXED" if frac >= 0.4 else "FRAGILE"), "profiles": sup})
        out["sensitivity_note"] = "stabilność względem ustawień – nie prawdopodobieństwo, nie p-value"
    return out
