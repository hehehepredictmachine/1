"""COA (Coyote) and BChimp (continuous) optimisers - ports of AO_COA_CoyoteOptimizationAlgorithm.mqh (Andrey Dik, article 23053) and
AO_BChimp_ChimpOptimizationAlgorithm.mqh (Andrey Dik, article 23132), MAXIMISING fitness like the source framework (C_AO: f > fB).
PMW objectives are losses -> fitness = -loss (ONE documented sign change, in ObjectiveSnapshot.fitness).

Shared contract (both algorithms, same frozen objective, same bounds / step / budget / deadline):
  ParameterSpace     names, bounds, step, param_version (an allow-list of ANALYTICAL parameters only)
  ObjectiveSnapshot  task, data ids, target, cost definition, cutoff, direction, hash - frozen for the whole job
  OptimizationJob    algorithm, seed, budget (evaluations), deadline, scope, status
  ParameterProposal  incumbent, candidate, fitness of both, data_count, change_set, base version
The incumbent is always evaluated and is a candidate; a proposal is APPLIED only when it beats the incumbent on the SAME objective,
stays inside the bounds and the change limits, and the base version is still current (else STALE_PROPOSAL). Neither optimiser is a
prediction model: no BUY / SELL vote, no confidence. Forbidden groups (account routing, credentials, live mode, position size, stake,
leverage, max loss, grid multiplier) can never be part of a ParameterSpace (checked).
The binary BChimp (feature-mask) variant is NOT implemented - no such capability is shown.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass, field

import numpy as np

FORBIDDEN = ("account", "routing", "credential", "live", "position_size", "lot", "stake", "leverage", "max_loss", "grid", "multiplier", "risk")


@dataclass
class ParameterSpace:
    names: list
    lo: list
    hi: list
    step: list
    param_version: str
    group: str = "bounded_detector_parameters"

    def __post_init__(self):
        bad = [n for n in self.names if any(f in n.lower() for f in FORBIDDEN)]
        if bad:
            raise ValueError(f"FORBIDDEN_PARAMETERS:{bad}")
        if not (len(self.names) == len(self.lo) == len(self.hi) == len(self.step)) or any(h < l_ for l_, h in zip(self.lo, self.hi)):
            raise ValueError("PARAMETER_SPACE_INVALID")

    def snap(self, x: np.ndarray) -> np.ndarray:
        """SeInDiSp of the source: clip to [lo, hi] and round to the step grid."""
        lo, hi, st = np.asarray(self.lo, float), np.asarray(self.hi, float), np.asarray(self.step, float)
        x = np.clip(x, lo, hi)
        return np.where(st > 0, np.clip(lo + np.round((x - lo) / np.where(st > 0, st, 1)) * st, lo, hi), x)


@dataclass
class ObjectiveSnapshot:
    task: str
    target: str
    data_ids: list
    costs: str
    cutoff: float
    direction: str = "minimize"                       # PMW losses; fitness = -loss for the maximising source algorithms
    fn: object = field(default=None, repr=False, compare=False)

    def hash(self) -> str:
        return hashlib.sha256(json.dumps({k: getattr(self, k) for k in ("task", "target", "data_ids", "costs", "cutoff", "direction")},
                                         sort_keys=True, default=str).encode()).hexdigest()[:16]

    def fitness(self, x) -> float:
        v = float(self.fn(x))
        if not math.isfinite(v):
            return -math.inf
        return -v if self.direction == "minimize" else v


class _Budget:
    def __init__(self, n: int, deadline_s: float):
        self.n, self.left, self.t_end = n, n, time.monotonic() + deadline_s
        self.timed_out = False

    def ok(self) -> bool:
        if time.monotonic() > self.t_end:
            self.timed_out = True
            return False
        return self.left > 0

    def take(self) -> None:
        self.left -= 1


def coa(space: ParameterSpace, obj: ObjectiveSnapshot, *, incumbent=None, packs: int = 4, per_pack: int = 5, max_evals: int = 240,
        deadline_s: float = 10.0, seed: int = 20261116) -> dict:
    """COA (Coyote) port: packs of nCoy coyotes, alpha = best of the pack, social tendency = coordinate median of the pack, pup from two
    parents (crossover mask of the source: one coordinate from each parent fixed, the rest with probability (1-1/D)/2 each, else uniform
    noise), pup replaces the worst (oldest on a tie) when better, greedy acceptance, pack exchange with p = 0.005 nCoy^2."""
    rng = np.random.default_rng(seed)
    D, n = len(space.names), packs * per_pack
    lo, hi = np.asarray(space.lo, float), np.asarray(space.hi, float)
    bud = _Budget(max_evals, deadline_s)
    X = space.snap(rng.uniform(lo, hi, (n, D)))
    if incumbent is not None:
        X[0] = space.snap(np.asarray(incumbent, float))
    F = np.full(n, -math.inf)
    for i in range(n):
        if not bud.ok():
            break
        F[i] = obj.fitness(X[i])
        bud.take()
    ages = np.zeros(n, int)
    order = rng.permutation(n)
    p_leave = 0.005 * per_pack * per_pack
    p_pup = (1 - 1 / D) * 0.5 if D > 0 else 0.0
    while bud.ok():
        if packs > 1 and rng.random() < p_leave:
            p1, p2 = rng.choice(packs, 2, replace=False)
            c1, c2 = rng.integers(per_pack), rng.integers(per_pack)
            a, b = p1 * per_pack + c1, p2 * per_pack + c2
            order[a], order[b] = order[b], order[a]
        Xs, Fs = X.copy(), F.copy()
        newX = X.copy()
        is_pup = np.zeros(n, bool)
        for p in range(packs):
            idx = order[p * per_pack:(p + 1) * per_pack]
            alpha = idx[np.argmax(Fs[idx])]
            tend = np.median(Xs[idx], axis=0)
            worst = idx[0]
            for k in idx[1:]:
                if Fs[k] < Fs[worst] or (Fs[k] == Fs[worst] and ages[k] > ages[worst]):
                    worst = k
            is_pup[worst] = True
            for k_pos, i in enumerate(idx):
                if i == worst:
                    par1, par2 = rng.choice(idx, 2, replace=False)
                    pdr = rng.permutation(D)
                    mask = np.zeros(D, int)
                    mask[pdr[0]] = 1
                    if D > 1:
                        mask[pdr[1]] = 2
                    for j in range(2, D):
                        r = rng.random()
                        mask[pdr[j]] = 1 if r < p_pup else 2 if r > 1 - p_pup else 0
                    v = np.where(mask == 1, Xs[par1], np.where(mask == 2, Xs[par2], rng.uniform(lo, hi)))
                else:
                    others = [x for x in idx if x != i]
                    rc1 = rng.choice(others)
                    rc2 = rng.choice([x for x in others if x != rc1])
                    r1, r2 = rng.random(), rng.random()
                    v = Xs[i] + r1 * (Xs[alpha] - Xs[rc1]) + r2 * (tend - Xs[rc2])
                newX[i] = space.snap(v)
        for i in range(n):
            if not bud.ok():
                newX[i], F[i] = Xs[i], Fs[i]
                continue
            f = obj.fitness(newX[i])
            bud.take()
            if f > Fs[i]:
                X[i], F[i] = newX[i], f
                ages[i] = 0 if is_pup[i] else ages[i] + 1
            else:
                X[i], F[i] = Xs[i], Fs[i]
                ages[i] += 1
    b = int(np.argmax(F))
    return {"algorithm": "COA", "implementation_id": "PMW_COA_PORT_V1", "best": X[b].tolist(), "best_fitness": float(F[b]),
            "evaluations": max_evals - bud.left, "timed_out": bud.timed_out, "seed": seed, "population": n}


def bchimp(space: ParameterSpace, obj: ObjectiveSnapshot, *, incumbent=None, pop: int = 16, max_evals: int = 160, deadline_s: float = 10.0,
           seed: int = 20261116) -> dict:
    """BChimp (continuous variant as published): four leaders (attacker, barrier, chaser, driver), chaotic multiplier per chimp from the
    piecewise map (P = 0.4, x0 = 0.7), group coefficients of the source, a = 2 - 2t, x_new = mean_k(leader_k - A_k |C_k leader_k - m x|)."""
    rng = np.random.default_rng(seed)
    D = len(space.names)
    lo, hi = np.asarray(space.lo, float), np.asarray(space.hi, float)
    bud = _Budget(max_evals, deadline_s)
    X = space.snap(rng.uniform(lo, hi, (pop, D)))
    if incumbent is not None:
        X[0] = space.snap(np.asarray(incumbent, float))
    m = np.empty(pop)
    P, x = 0.4, 0.7
    for i in range(pop):
        m[i] = x
        x = x / P if x < P else (x - P) / (0.5 - P) if x < 0.5 else (1 - P - x) / (0.5 - P) if x < 1 - P else (1 - x) / P
    F = np.full(pop, -math.inf)
    lead_c, lead_f = np.zeros((4, D)), np.full(4, -math.inf)

    def insert(i):
        f = F[i]
        p = next((k for k in range(4) if f > lead_f[k]), None)
        if p is None:
            return
        lead_c[p + 1:], lead_f[p + 1:] = lead_c[p:3].copy(), lead_f[p:3].copy()
        lead_c[p], lead_f[p] = X[i], f
    for i in range(pop):
        if not bud.ok():
            break
        F[i] = obj.fitness(X[i])
        bud.take()
        insert(i)
    epochs = max(2, max_evals // max(1, pop))
    ep = 0
    while bud.ok():
        ep += 1
        t = min(1.0, ep / (epochs - 1))
        a = 2 - 2 * t
        u1, u3 = t ** (1 / 3), t ** 3
        C1 = np.array([1.95 - 2 * u1, 1.95 - 2 * u1, -2 * u3 + 2.5, -2 * u3 + 2.5])
        C2 = np.array([2 * u1 + 0.5, 2 * u3 + 0.5, 2 * u1 + 0.5, 2 * u3 + 0.5])
        for i in range(pop):
            if not bud.ok():
                break
            A = a * C1[:, None] * (2 * rng.random((4, D)) - 1)
            C = C2[:, None] * rng.random((4, D))
            Dk = np.abs(C * lead_c - m[i] * X[i])
            X[i] = space.snap((lead_c - A * Dk).mean(axis=0))
            F[i] = obj.fitness(X[i])
            bud.take()
            insert(i)
    return {"algorithm": "BCHIMP_CONTINUOUS", "implementation_id": "PMW_BCHIMP_CONTINUOUS_PORT_V1", "best": lead_c[0].tolist(),
            "best_fitness": float(lead_f[0]), "evaluations": max_evals - bud.left, "timed_out": bud.timed_out, "seed": seed, "population": pop}


def run_job(space: ParameterSpace, obj: ObjectiveSnapshot, incumbent: list, *, base_version: str, budgets: dict | None = None,
            max_changed: int = 3, max_norm_change: float = 0.1, seed: int = 20261116) -> dict:
    """COA explores, then BChimp refines (both on the SAME frozen objective, budgets / deadline shared); the incumbent is a candidate.
    Returns a ParameterProposal (APPLY / KEEP_INCUMBENT) - the caller publishes it atomically on the next snapshot boundary."""
    b = {"coa_evals": 240, "bchimp_evals": 160, "deadline_s": 10.0, **(budgets or {})}
    t0 = time.monotonic()
    inc = space.snap(np.asarray(incumbent, float))
    f_inc = obj.fitness(inc)
    r1 = coa(space, obj, incumbent=inc, max_evals=int(b["coa_evals"]), deadline_s=float(b["deadline_s"]) / 2, seed=seed)
    r2 = bchimp(space, obj, incumbent=np.asarray(r1["best"]), max_evals=int(b["bchimp_evals"]), deadline_s=max(0.1, float(b["deadline_s"]) - (time.monotonic() - t0)),
                seed=seed + 1)
    cand, f_c, src = (r2["best"], r2["best_fitness"], "BCHIMP") if r2["best_fitness"] >= r1["best_fitness"] else (r1["best"], r1["best_fitness"], "COA")
    cand = space.snap(np.asarray(cand, float))
    span = np.maximum(np.asarray(space.hi, float) - np.asarray(space.lo, float), 1e-12)
    delta = np.abs(cand - inc) / span
    changed = [space.names[k] for k in range(len(space.names)) if delta[k] > 1e-12]
    reasons = []
    if not math.isfinite(f_c):
        reasons.append("NON_FINITE_FITNESS")
    if f_c <= f_inc:
        reasons.append("NOT_BETTER_THAN_INCUMBENT")
    if len(changed) > max_changed:
        # keep the max_changed largest improvements only (bounded change per publication) - re-evaluate the reduced candidate
        keep = np.argsort(-delta)[:max_changed]
        red = inc.copy()
        red[keep] = cand[keep]
        cand, f_c = np.minimum(red, red), obj.fitness(red)
        changed = [space.names[k] for k in keep if delta[k] > 1e-12]
        if f_c <= f_inc:
            reasons.append("REDUCED_CANDIDATE_NOT_BETTER")
    if np.any(np.abs(cand - inc) / span > max_norm_change + 1e-12):
        lim = inc + np.clip(cand - inc, -max_norm_change * span, max_norm_change * span)
        cand = space.snap(lim)
        f_c = obj.fitness(cand)
        if f_c <= f_inc:
            reasons.append("STEP_LIMITED_CANDIDATE_NOT_BETTER")
    decision = "APPLY" if not reasons else "KEEP_INCUMBENT"
    return {"schema": "PMW-PARAM-PROPOSAL-1", "objective_hash": obj.hash(), "objective": {"task": obj.task, "target": obj.target, "direction": obj.direction,
            "costs": obj.costs, "cutoff": obj.cutoff, "data_count": len(obj.data_ids)}, "space": {"names": space.names, "lo": space.lo, "hi": space.hi,
            "step": space.step, "group": space.group}, "base_version": base_version, "incumbent": inc.tolist(), "incumbent_fitness": f_inc,
            "candidate": cand.tolist(), "candidate_fitness": float(f_c), "winner_algorithm": src, "change_set": changed, "decision": decision,
            "reasons": reasons, "runs": [r1, r2], "seconds": round(time.monotonic() - t0, 3), "seed": seed,
            "note": "wynik optymalizacji na tych danych – nie jest potwierdzeniem przyszłej skuteczności"}
