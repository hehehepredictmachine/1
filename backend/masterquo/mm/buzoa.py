"""BUZOA population optimiser + reference optimisers + benchmark functions (PMW-MM-BUZOA-1). OPTIMIZER - never a market model.

Agent state: L (position), C (movement / "ability"), pBest, plus the population gBest. Per iteration ONE mode per agent (all dimensions):
  r_mode < 1/3 -> 001  C = a1*C + c1*r*(pBest-L)
  r_mode < 2/3 -> 010  C1 = a1*C + c1*r*(pBest-L);  C = C1 + c1*r1*(pBest-L) + c2*r2*(gBest-L)
                       (LITERAL variant of the supplied formula: the pBest attraction appears twice - kept on purpose; the
                        single-pBest variant is `variant="single_pbest"` for comparison)
  else         -> 100  L ~ U(lb, ub), C = 0  (no further move in this iteration; pBest is kept)
then for 001/010: C = clip(C, -Cmax, Cmax), L = clip(L + C, lb, ub) with Cmax = (ub-lb)/2 per dimension; after each iteration a1 *= wDamp.
r, r1, r2 ~ U(0,1) per dimension (independent draws). Objective errors / NaN / inf are recorded as failed evaluations and never become a
best (the position is kept, its fitness = worst). Minimisation and maximisation are both supported (explicit `direction`).
Budget = max evaluations (hard stop), optional cancel callback; cache of identical parameter vectors when `cache=True`.
Discrete parameters: an explicit `int_dims` set is rounded inside the objective adapter (the optimiser state stays continuous).
"""
from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass

import numpy as np

VERSION = "PMW-MM-BUZOA-1"


@dataclass
class BuzoaConfig:
    pop: int = 20
    epochs: int = 50
    alpha1: float = 0.9
    c1: float = 1.5
    c2: float = 1.5
    w_damp: float = 0.99
    seed: int = 7
    max_evals: int = 1000
    direction: str = "min"
    variant: str = "literal"            # literal | single_pbest
    mode_probs: tuple = (1 / 3, 1 / 3, 1 / 3)
    cache: bool = True

    def validate(self, lb, ub):
        lb, ub = np.asarray(lb, float), np.asarray(ub, float)
        if lb.shape != ub.shape or lb.ndim != 1 or not len(lb) or not np.all(np.isfinite(lb)) or not np.all(np.isfinite(ub)):
            raise ValueError("BUZOA_BOUNDS_INVALID")
        if np.any(ub <= lb):
            raise ValueError("BUZOA_BOUNDS_EMPTY_OR_INVERTED")
        if self.pop < 2 or self.epochs < 1 or self.max_evals < self.pop or self.direction not in ("min", "max") or self.variant not in ("literal", "single_pbest"):
            raise ValueError("BUZOA_CONFIG_INVALID")
        if abs(sum(self.mode_probs) - 1) > 1e-9 or min(self.mode_probs) < 0:
            raise ValueError("BUZOA_MODE_PROBS_INVALID")


class _Eval:
    def __init__(self, f, direction, max_evals, cache, cancel):
        self.f, self.sign, self.max, self.cache_on, self.cancel = f, (1.0 if direction == "min" else -1.0), max_evals, cache, cancel
        self.n, self.failed, self.cache, self.trials = 0, 0, {}, []

    def __call__(self, x) -> float | None:
        """Internal score (always minimised): sign * f(x). None when the budget is exhausted / cancelled."""
        key = tuple(np.round(x, 12))
        if self.cache_on and key in self.cache:
            return self.cache[key]
        if self.n >= self.max or (self.cancel and self.cancel()):
            return None
        self.n += 1
        try:
            v = float(self.f(np.array(x)))
            ok = math.isfinite(v)
        except Exception as exc:  # noqa: BLE001
            v, ok = math.nan, False
            self.trials.append({"x": list(map(float, x)), "error": f"{type(exc).__name__}: {exc}"[:160]})
        if not ok:
            self.failed += 1
            s = math.inf
        else:
            s = self.sign * v
            self.trials.append({"x": list(map(float, x)), "f": v})
        if self.cache_on:
            self.cache[key] = s
        return s


def buzoa(f, lb, ub, cfg: BuzoaConfig | None = None, cancel=None) -> dict:
    cfg = cfg or BuzoaConfig()
    cfg.validate(lb, ub)
    lb, ub = np.asarray(lb, float), np.asarray(ub, float)
    D = len(lb)
    rng = np.random.Generator(np.random.PCG64(cfg.seed))
    cmax = (ub - lb) / 2.0
    L = lb + rng.random((cfg.pop, D)) * (ub - lb)
    C = (rng.random((cfg.pop, D)) * 2 - 1) * cmax
    ev = _Eval(f, cfg.direction, cfg.max_evals, cfg.cache, cancel)
    t0 = time.perf_counter()
    fit = np.full(cfg.pop, math.inf)
    for i in range(cfg.pop):
        s = ev(L[i])
        if s is None:
            break
        fit[i] = s
    pbest, pfit = L.copy(), fit.copy()
    g = int(np.argmin(pfit))
    gbest, gfit = pbest[g].copy(), float(pfit[g])
    a1 = cfg.alpha1
    hist, modes, stop = [], {"001": 0, "010": 0, "100": 0}, "EPOCHS"
    p1, p2 = cfg.mode_probs[0], cfg.mode_probs[0] + cfg.mode_probs[1]
    for ep in range(cfg.epochs):
        done = False
        for i in range(cfg.pop):
            rm = rng.random()
            if rm < p1:
                m = "001"
                C[i] = a1 * C[i] + cfg.c1 * rng.random(D) * (pbest[i] - L[i])
            elif rm < p2:
                m = "010"
                c1v = a1 * C[i] + cfg.c1 * rng.random(D) * (pbest[i] - L[i])
                if cfg.variant == "literal":
                    C[i] = c1v + cfg.c1 * rng.random(D) * (pbest[i] - L[i]) + cfg.c2 * rng.random(D) * (gbest - L[i])
                else:
                    C[i] = a1 * C[i] + cfg.c1 * rng.random(D) * (pbest[i] - L[i]) + cfg.c2 * rng.random(D) * (gbest - L[i])
            else:
                m = "100"
                L[i] = lb + rng.random(D) * (ub - lb)
                C[i] = 0.0
            modes[m] += 1
            if m != "100":
                C[i] = np.clip(C[i], -cmax, cmax)
                L[i] = np.clip(L[i] + C[i], lb, ub)
            s = ev(L[i])
            if s is None:
                done, stop = True, ("CANCELLED" if cancel and cancel() else "MAX_EVALS")
                break
            if s < pfit[i]:
                pbest[i], pfit[i] = L[i].copy(), s
                if s < gfit:
                    gbest, gfit = L[i].copy(), s
        a1 *= cfg.w_damp
        hist.append(gfit if math.isfinite(gfit) else None)
        if done:
            break
    sign = 1.0 if cfg.direction == "min" else -1.0
    ok = math.isfinite(gfit)
    return {"algorithm": "BUZOA", "version": VERSION, "status": "OK" if ok else "NO_VALID_EVALUATION", "best_x": gbest.tolist() if ok else None,
            "best_f": sign * gfit if ok else None, "direction": cfg.direction, "iterations": len(hist), "evaluations": ev.n, "failed_evaluations": ev.failed,
            "runtime_s": time.perf_counter() - t0, "seed": cfg.seed, "config": asdict(cfg), "convergence": [None if h is None else sign * h for h in hist],
            "mode_counts": modes, "stop": stop, "alpha1_final": a1, "trials": ev.trials}


# ------------------------------------------------------------------------------------------ reference optimisers (same budget semantics)
def pso(f, lb, ub, pop=20, max_evals=1000, w=0.72, c1=1.49, c2=1.49, seed=7, direction="min") -> dict:
    lb, ub = np.asarray(lb, float), np.asarray(ub, float)
    D, rng = len(lb), np.random.Generator(np.random.PCG64(seed))
    ev = _Eval(f, direction, max_evals, False, None)
    X = lb + rng.random((pop, D)) * (ub - lb)
    V = (rng.random((pop, D)) * 2 - 1) * (ub - lb) / 2
    fit = np.array([ev(x) for x in X], dtype=float)
    pb, pf = X.copy(), fit.copy()
    g = int(np.argmin(pf))
    hist = []
    while ev.n < max_evals:
        for i in range(pop):
            V[i] = w * V[i] + c1 * rng.random(D) * (pb[i] - X[i]) + c2 * rng.random(D) * (pb[g] - X[i])
            V[i] = np.clip(V[i], -(ub - lb) / 2, (ub - lb) / 2)
            X[i] = np.clip(X[i] + V[i], lb, ub)
            s = ev(X[i])
            if s is None:
                break
            if s < pf[i]:
                pb[i], pf[i] = X[i].copy(), s
                if s < pf[g]:
                    g = i
        hist.append(float(pf[g]))
    sign = 1.0 if direction == "min" else -1.0
    return {"algorithm": "PSO", "best_x": pb[g].tolist(), "best_f": sign * float(pf[g]), "evaluations": ev.n, "convergence": [sign * h for h in hist]}


def differential_evolution(f, lb, ub, pop=20, max_evals=1000, F=0.6, CR=0.9, seed=7, direction="min") -> dict:
    lb, ub = np.asarray(lb, float), np.asarray(ub, float)
    D, rng = len(lb), np.random.Generator(np.random.PCG64(seed))
    ev = _Eval(f, direction, max_evals, False, None)
    X = lb + rng.random((pop, D)) * (ub - lb)
    fit = np.array([ev(x) for x in X], dtype=float)
    hist = []
    while ev.n < max_evals:
        for i in range(pop):
            a, b, c = X[rng.choice([j for j in range(pop) if j != i], 3, replace=False)]
            mut = np.clip(a + F * (b - c), lb, ub)
            jr = rng.integers(D)
            tr = np.where((rng.random(D) < CR) | (np.arange(D) == jr), mut, X[i])
            s = ev(tr)
            if s is None:
                break
            if s <= fit[i]:
                X[i], fit[i] = tr, s
        hist.append(float(fit.min()))
    sign = 1.0 if direction == "min" else -1.0
    k = int(np.argmin(fit))
    return {"algorithm": "DE", "best_x": X[k].tolist(), "best_f": sign * float(fit[k]), "evaluations": ev.n, "convergence": [sign * h for h in hist]}


def random_search(f, lb, ub, max_evals=1000, seed=7, direction="min") -> dict:
    lb, ub = np.asarray(lb, float), np.asarray(ub, float)
    rng = np.random.Generator(np.random.PCG64(seed))
    ev = _Eval(f, direction, max_evals, False, None)
    best, bx, hist = math.inf, None, []
    while ev.n < max_evals:
        x = lb + rng.random(len(lb)) * (ub - lb)
        s = ev(x)
        if s is None:
            break
        if s < best:
            best, bx = s, x
        hist.append(best)
    sign = 1.0 if direction == "min" else -1.0
    return {"algorithm": "RANDOM", "best_x": bx.tolist(), "best_f": sign * best, "evaluations": ev.n, "convergence": [sign * h for h in hist]}


# ------------------------------------------------------------------------------------------ benchmark functions
def sphere(x):
    return float(np.sum(x ** 2))


def rastrigin(x):
    return float(10 * len(x) + np.sum(x ** 2 - 10 * np.cos(2 * np.pi * x)))


def rosenbrock(x):
    return float(np.sum(100 * (x[1:] - x[:-1] ** 2) ** 2 + (1 - x[:-1]) ** 2))


def ackley(x):
    n = len(x)
    return float(-20 * np.exp(-0.2 * np.sqrt(np.sum(x ** 2) / n)) - np.exp(np.sum(np.cos(2 * np.pi * x)) / n) + 20 + math.e)


def scaled_sphere(x):
    """Very different parameter scales: x_k weighted by 10^(k mod 4)."""
    w = 10.0 ** (np.arange(len(x)) % 4)
    return float(np.sum((x * w) ** 2))


BENCH = {"sphere": (sphere, -5.12, 5.12), "rastrigin": (rastrigin, -5.12, 5.12), "rosenbrock": (rosenbrock, -2.048, 2.048),
         "ackley": (ackley, -32.768, 32.768), "scaled_sphere": (scaled_sphere, -5.0, 5.0)}


def benchmark(dims=(2, 10, 30), seeds=(1, 2, 3, 4, 5), budget: int = 2000, tol: float = 1e-2) -> dict:
    out = {}
    for name, (fn, lo, hi) in BENCH.items():
        for d in dims:
            lb, ub = np.full(d, lo), np.full(d, hi)
            res = {"BUZOA": [], "BUZOA_single_pbest": [], "PSO": [], "DE": [], "RANDOM": []}
            t = {k: 0.0 for k in res}
            modes = {"001": 0, "010": 0, "100": 0}
            for s in seeds:
                t0 = time.perf_counter()
                r = buzoa(fn, lb, ub, BuzoaConfig(seed=s, max_evals=budget, epochs=10 ** 6, cache=False))
                t["BUZOA"] += time.perf_counter() - t0
                res["BUZOA"].append(r["best_f"])
                for k in modes:
                    modes[k] += r["mode_counts"][k]
                t0 = time.perf_counter()
                res["BUZOA_single_pbest"].append(buzoa(fn, lb, ub, BuzoaConfig(seed=s, max_evals=budget, epochs=10 ** 6, cache=False, variant="single_pbest"))["best_f"])
                t["BUZOA_single_pbest"] += time.perf_counter() - t0
                for k, fx in (("PSO", pso), ("DE", differential_evolution), ("RANDOM", random_search)):
                    t0 = time.perf_counter()
                    res[k].append(fx(fn, lb, ub, max_evals=budget, seed=s)["best_f"])
                    t[k] += time.perf_counter() - t0
            out[f"{name}_d{d}"] = {k: {"best": float(np.min(v)), "median": float(np.median(v)), "iqr": float(np.subtract(*np.percentile(v, [75, 25]))),
                                       "hit_tol": int(sum(x <= tol for x in v)), "runs": len(v), "time_s": t[k]} for k, v in res.items()}
            out[f"{name}_d{d}"]["BUZOA_modes"] = modes
    return {"version": VERSION, "budget_evals": budget, "seeds": list(seeds), "dims": list(dims), "tolerance": tol, "results": out,
            "note": "porównanie przy równym budżecie ewaluacji; wynik nie przesądza o przewadze w zadaniach rynkowych"}
