"""OTC_PAYOFF_GATE (spec 9.2): the full money PnL of a fixed-expiry group, enumerated over price intervals between strikes and on
every strike (ties), plus the gate that accepts a protective leg only when it improves the worst case by >= min_improvement.

Leg: {"dir": "CALL"|"PUT", "stake": s, "r": payout profit ratio (0.8 for 80 %), "strike": K, "expiry": absolute ts, "tie": "REFUND"}
  CALL: +s*r if P > K, -s if P < K, 0 on a tie (REFUND);  PUT symmetric.  Group PnL = sum of legs - extra costs.
Different expiries are different final prices: never evaluated as one state (EXPIRY_MISMATCH).
"""
from __future__ import annotations

import math


def leg_pnl(leg: dict, P: float) -> float:
    s, r, K = float(leg["stake"]), float(leg["r"]), float(leg["strike"])
    if P == K:
        tie = leg.get("tie", "REFUND")
        return 0.0 if tie == "REFUND" else (-s if tie == "LOSS" else s * r)
    win = P > K if leg["dir"] == "CALL" else P < K
    return s * r if win else -s


def eval_points(legs: list[dict]) -> list[tuple[str, float]]:
    ks = sorted({float(l["strike"]) for l in legs})
    if not ks:
        return []
    span = max(1e-9, (ks[-1] - ks[0]) or abs(ks[0]) * 1e-6 or 1e-6)
    pts = [("below", ks[0] - span)]
    for a, b in zip(ks, ks[1:]):
        pts.append(("between", (a + b) / 2))
    pts.append(("above", ks[-1] + span))
    pts += [("tie", k) for k in ks]
    return pts


def table(legs: list[dict], extra_cost: float = 0.0) -> dict:
    exp = {l.get("expiry") for l in legs}
    if len(exp) > 1:
        return {"ok": False, "code": "EXPIRY_MISMATCH", "reason": "różne expiry = różne ceny końcowe – nie łączę ich w jeden wynik"}
    rows = []
    for kind, P in eval_points(legs):
        rows.append({"kind": kind, "price": P, "pnl": round(sum(leg_pnl(l, P) for l in legs) - extra_cost, 10)})
    pn = [r["pnl"] for r in rows]
    return {"ok": True, "rows": sorted(rows, key=lambda r: (r["price"], r["kind"] != "tie")), "worst": min(pn) if pn else 0.0, "best": max(pn) if pn else 0.0,
            "cash_at_risk": sum(float(l["stake"]) for l in legs)}


def b_star(a: float, r_call: float, r_put: float) -> float:
    """Stake equalising the two outer outcomes of one CALL a + PUT b (Kc <= Kp), before costs and limits (reference, not an order)."""
    return a * (1 + r_call) / (1 + r_put)


def gate(parents: list[dict], *, dir_new: str, strike_est: float, strike_band: float, r_new: float | None, expiry: float,
         stake_min: float, stake_step: float, stake_max: float, cash_free: float | None, min_improvement: float, quantum_money: float = 0.01,
         allow_negative_lock: bool = True, params_confirmed: bool = False, layers_used: int = 0, max_layers: int = 1) -> dict:
    """Steps 1-7 of the spec. Returns {state: HEDGE_PLAN | NO_HEDGE, reason, before, after, stake, ...}."""
    if not parents:
        return {"state": "NO_EXPOSURE", "reason": "brak otwartych kontraktów do ochrony"}
    if any(p.get("expiry") != expiry for p in parents):
        return {"state": "NO_HEDGE", "reason": "EXPIRY_MISMATCH: proponowana noga ma inny absolutny expiry niż rodzic"}
    if layers_used >= max_layers:
        return {"state": "NO_HEDGE", "reason": f"limit warstw ochrony ({max_layers}) wyczerpany"}
    if r_new is None:
        return {"state": "NO_HEDGE", "reason": "brak aktualnego payout przeciwnej nogi (nieaktualny lub nieznany)"}
    before = table(parents)
    if not before["ok"]:
        return {"state": "NO_HEDGE", "reason": before["reason"]}
    need = max(float(min_improvement), float(quantum_money))
    cap = min(float(stake_max), float(cash_free) if cash_free is not None else float(stake_max))
    if cap < stake_min:
        return {"state": "NO_HEDGE", "reason": f"wolne środki / limit stawki ({cap}) poniżej minimum ({stake_min})", "before": before}
    strikes = [strike_est - strike_band, strike_est, strike_est + strike_band] if strike_band > 0 else [strike_est]
    tried = []
    s = float(stake_min)
    while s <= cap + 1e-9:
        worst_after = math.inf
        for K in strikes:                                   # uncertain future strike: the WORST of the plausible strikes counts
            t = table(parents + [{"dir": dir_new, "stake": s, "r": r_new, "strike": K, "expiry": expiry}])
            worst_after = min(worst_after, t["worst"])
        imp = worst_after - before["worst"]
        tried.append({"stake": round(s, 8), "worst_after": round(worst_after, 8), "improvement": round(imp, 8)})
        if imp >= need and (allow_negative_lock or worst_after >= 0):
            leg = {"dir": dir_new, "stake": round(s, 8), "r": r_new, "strike": strike_est, "expiry": expiry}
            after = table(parents + [leg])
            return {"state": "HEDGE_PLAN", "stake": round(s, 8), "leg": leg, "before": before, "after": after, "worst_after_band": worst_after,
                    "improvement": imp, "extra_cash": round(s, 8), "label": "CONFIRMED_PARAMETERS" if params_confirmed else "ESTIMATED_PAYOFF",
                    "candidates": tried[-5:], "note": "koszt ochrony nie jest zyskiem; możliwy lock ujemnego wyniku pokazany w tabeli"}
        s = round(s + float(stake_step), 10)
    return {"state": "NO_HEDGE", "reason": f"żadna dopuszczalna stawka nie poprawia najgorszego wyniku o ≥ {need}", "before": before, "candidates": tried[-5:]}


def ev_money(stake: float, r: float, p_win: float | None, p_loss: float | None) -> float | None:
    """EV = stake * (p_win * r - p_loss) - only with an estimator of the named event; else None (never 1 - p_win silently)."""
    if p_win is None or p_loss is None:
        return None
    return stake * (p_win * r - p_loss)
