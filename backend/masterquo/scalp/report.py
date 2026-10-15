"""Strategy / hedge report from replay output: independent cycles, days, net R, expectancy, PF, max DD, costs, ambiguity,
day-block bootstrap 95% intervals and the research promotion gate. Small samples -> INSUFFICIENT_EVIDENCE (not a failure
of the code). The share of bootstrap replicas below zero is NOT a probability that the strategy loses."""
from __future__ import annotations

import random
from collections import defaultdict

GATE = {"min_days": 30, "min_cycles": 200, "max_dd_pct": 5.0, "cost_stress": 1.5}


def _block_ci(by_day: dict[str, list[float]], stat, n_boot: int = 2000, seed: int = 7) -> list[float] | None:
    days = sorted(by_day)
    if len(days) < 5:
        return None
    rnd = random.Random(seed)
    vals = []
    for _ in range(n_boot):
        xs = [x for _d in range(len(days)) for x in by_day[days[rnd.randrange(len(days))]]]
        if xs:
            vals.append(stat(xs))
    vals.sort()
    return [round(vals[int(0.025 * len(vals))], 4), round(vals[int(0.975 * len(vals)) - 1], 4)]


def strategy_summary(cycles: list[dict], risk_pct: float = 0.25) -> dict:
    n = len(cycles)
    if not n:
        return {"cycles": 0, "days": 0, "status": "INSUFFICIENT_EVIDENCE", "reason": "brak cykli"}
    rs = [c["net_r"] for c in cycles]
    by_day: dict[str, list[float]] = defaultdict(list)
    for c in cycles:
        by_day[c["fill_time"][:10]].append(c["net_r"])
    eq = peak = dd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    wins, losses = sum(r for r in rs if r > 0), -sum(r for r in rs if r < 0)
    exp = sum(rs) / n
    ci = _block_ci(by_day, lambda xs: sum(xs) / len(xs))
    out = {"cycles": n, "days": len(by_day), "net_r_total": round(sum(rs), 3), "expectancy_r": round(exp, 4), "expectancy_ci95_day_block": ci,
           "profit_factor": round(wins / losses, 3) if losses else None, "max_dd_r": round(dd, 3), "max_dd_pct_at_risk": round(dd * risk_pct, 3),
           "tp1_before_sl_share": round(sum(1 for c in cycles if c["tp1_before_sl"]) / n, 3),
           "ambiguous_share": round(sum(1 for c in cycles if c["ambiguous"]) / n, 3),
           "avg_hold_min": round(sum(c["hold_min"] or 0 for c in cycles) / n, 2), "worst_r": round(min(rs), 3),
           "by_direction": {d: len([c for c in cycles if c["direction"] == d]) for d in ("BUY", "SELL")},
           "precision": "OHLC_APPROX", "bootstrap": "blok = dzień handlowy, 2000 replik, seed 7"}
    fails = []
    if len(by_day) < GATE["min_days"]:
        fails.append(f"dni {len(by_day)} < {GATE['min_days']}")
    if n < GATE["min_cycles"]:
        fails.append(f"cykle {n} < {GATE['min_cycles']}")
    if fails:
        out.update(status="INSUFFICIENT_EVIDENCE", reason="; ".join(fails))
    elif exp > 0 and ci and ci[0] > 0 and dd * risk_pct <= GATE["max_dd_pct"]:
        out.update(status="PASSED_RESEARCH_GATE_PENDING_COST_STRESS", reason="wymagany też dodatni wynik przy kosztach +50% i brak błędów wykonania")
    else:
        out.update(status="FAILED", reason="expectancy / dolny kraniec CI / DD nie spełniają bramki")
    return out


def hedge_summary(decisions: list[dict]) -> dict:
    """HEDGE_PARTIAL vs REDUCE on the same paths. One value per CYCLE (mean over its decision points) - decision points of
    one position are dependent and are not counted as independent samples."""
    per_cycle: dict[str, list[float]] = defaultdict(list)
    day: dict[str, str] = {}
    best = defaultdict(int)
    for d in decisions:
        best[d["best"]] += 1
        if d["hedge_minus_reduce_r"] is not None:
            per_cycle[d["setup_id"]].append(d["hedge_minus_reduce_r"])
            day[d["setup_id"]] = d["decision_time"][:10]
    vals = {k: sum(v) / len(v) for k, v in per_cycle.items()}
    if not vals:
        return {"cycles": 0, "status": "NOT_EVALUATED", "reason": "brak punktów decyzji z hedge (NETTING lub brak cykli)", "best_action_counts": dict(best)}
    by_day: dict[str, list[float]] = defaultdict(list)
    for k, v in vals.items():
        by_day[day[k]].append(v)
    m = sum(vals.values()) / len(vals)
    ci = _block_ci(by_day, lambda xs: sum(xs) / len(xs))
    st = ("INSUFFICIENT_EVIDENCE" if len(vals) < GATE["min_cycles"] or len(by_day) < GATE["min_days"]
          else "HEDGE_BETTER_THAN_REDUCE" if ci and ci[0] > 0 else "NOT_BETTER_THAN_REDUCE")
    return {"cycles": len(vals), "days": len(by_day), "mean_hedge_minus_reduce_r": round(m, 4), "ci95_day_block": ci, "status": st,
            "best_action_counts": dict(best), "note": "porównanie koszyka (base + hedge) z częściowym zamknięciem o tej samej ekspozycji netto"}
