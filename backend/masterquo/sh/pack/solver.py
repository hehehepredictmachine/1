"""Two-target plan solver of the 20 SH variants (§3.2 of the specification) - geometry, costs and the net risk/reward of the WHOLE plan.

Notation (price units of the instrument, per unit of volume): E executable planned entry (BUY Ask / SELL Bid), S initial stop from the
invalidation + buffer (quantized OUTWARD), r = |E-S|, d1 = |TP1-E|, d2 = |TP2-E|, shares w1 + w2 = 1 (default 50/50).
  SC: d1 >= max(25 pip, 1.5 r), d2 >= max(d1 + tick, 3 r)          HG: d1 >= max(40 pip, 2 r), d2 >= max(d1 + tick, 5 r)
  rr_plan_net = (w1 d1 + w2 d2 - C_win) / (r + C_loss)            d2_required = (rr_min (r + C_loss) + C_win - w1 d1) / w2
The spread is already inside the executable prices (BUY enters at Ask and its targets / stop are hit on Bid), so it is NOT subtracted
again; C = 2 x slippage + commission of the round trip (commission of partial exits is proportional to the executed volume, so the
normalized round trip is one commission, not two). Unknown commission -> an explicit cost SCENARIO (cost_status ESTIMATED_SCENARIO),
never zero; such a plan is never NET_VALIDATED / READY_TO_EXECUTE.
HEDGING adds the bounded hedge path: HL = ratio x (modelled hedge-to-unwind gap + C). It reduces the target path and is added to the
initial risk (whipsaw path: hedge loss, then the base stop):  rr_basket_net_target = (w1 d1 + w2 d2 - C - HL) / (r + C + HL).
If the policy cannot bound HL the result is RR_NOT_ESTIMABLE, never 3.0. The stop is never shortened to reach a ratio; when the required
TP2 does not fit the target space (nearest opposite level known at entry) or the ATR reach heuristic, the answer is NO_TRADE /
TARGET_UNREACHABLE.
"""
from __future__ import annotations

import math

EPS = 1e-9


def snap_out(x: float, tick: float, outward_up: bool) -> float:
    """View units (BUY orientation): targets snap UP (further), stops snap DOWN (further)."""
    q = x / tick
    n = math.ceil(q - EPS) if outward_up else math.floor(q + EPS)
    return round(n * tick, 10)


def rr_plan_net(d1: float, d2: float, r: float, c_win: float, c_loss: float, w1: float = 0.5, w2: float = 0.5) -> float:
    return (w1 * d1 + w2 * d2 - c_win) / (r + c_loss)


def rr_basket(d1: float, d2: float, r: float, c: float, hl_target: float, hl_risk: float, w1: float = 0.5, w2: float = 0.5) -> float:
    """Basket target scenario: hl_target = hedge loss/cost in the path that still reaches both targets, hl_risk = hedge loss added to
    the initial risk (whipsaw then stop). The specification's illustrative example keeps hl_risk = 0."""
    return (w1 * d1 + w2 * d2 - c - hl_target) / (r + c + hl_risk)


def d2_required(rr_min: float, d1: float, r: float, c_win: float, c_loss: float, w1: float = 0.5, w2: float = 0.5) -> float:
    return (rr_min * (r + c_loss) + c_win - w1 * d1) / w2


def costs(ic: dict, mpp_per_lot: float | None, common: dict) -> dict:
    """Round-trip cost per unit volume in price units, with its basis."""
    slip = float(ic.get("slippage_usd") or 0.0)
    comm = ic.get("commission_per_lot_side")
    if comm is not None and mpp_per_lot:
        cpx, status, basis = 2 * float(comm) / mpp_per_lot, "KNOWN", "prowizja z profilu instrumentu (na lot i stronę) przeliczona na cenę"
    else:
        cpx, status = float(common.get("commission_scenario_price_rt", 0.10)), "ESTIMATED_SCENARIO"
        basis = f"prowizja NIEZNANA – scenariusz kosztowy {cpx} USD ceny na round trip (nie zero, nie NET_VALIDATED)"
    return {"c_round_trip": round(2 * slip + cpx, 6), "slippage_price": slip, "commission_price_rt": round(cpx, 6), "cost_status": status,
            "basis": basis, "spread_note": "spread zawarty w cenach Ask/Bid wejścia i wyjść – nie jest odejmowany drugi raz"}


def solve(*, E: float, S_raw: float, tick: float, pip: float, rules: dict, c: float, natural: list[float] | None = None,
          target_space: float | None = None, reach: float | None = None, hedge_loss: float | None = None, hedging: bool = False) -> dict:
    """All inputs in VIEW units (BUY orientation: S_raw < E). Returns status OK / NO_TRADE with reason_code and the plan numbers."""
    w1, w2 = rules["shares"]
    S = snap_out(S_raw, tick, outward_up=False)
    r = E - S
    out = {"entry": E, "sl": S, "r": round(r, 10), "c": c, "shares": [w1, w2], "pip_size": pip}
    if r <= tick:
        return {**out, "status": "NO_TRADE", "reason_code": "SL_INVALID", "reason": "SL nie jest po właściwej stronie wejścia (po kwantyzacji)"}
    d1_min = max(rules["tp1_min_pips"] * pip, rules["tp1_r_mult"] * r)
    hl = hedge_loss if hedging else 0.0
    if hedging and hedge_loss is None:
        return {**out, "status": "NO_TRADE", "reason_code": "RR_NOT_ESTIMABLE",
                "reason": "polityka hedge nie pozwala uczciwie ograniczyć straty nogi w scenariuszach celu – RR koszyka nieoszacowalny"}
    rr_min = rules["rr_min"]
    if natural:
        t1, t2 = natural
        if t1 is None or t2 is None:
            return {**out, "status": "NO_TRADE", "reason_code": "NATURAL_TARGETS_MISSING", "reason": "brak naturalnych celów"}
        d1 = snap_out(t1, tick, True) - E
        d2 = snap_out(t2, tick, True) - E
        if d1 < d1_min - EPS or d2 < max(d1 + tick, rules["tp2_r_mult"] * r) - EPS:
            return {**out, "status": "NO_TRADE", "reason_code": "TARGET_UNREACHABLE",
                    "reason": f"naturalne cele za blisko (TP1 {d1:.2f}, TP2 {d2:.2f} < wymagane {d1_min:.2f} / {max(d1 + tick, rules['tp2_r_mult'] * r):.2f}) – profil/pasma nie są przestawiane"}
        target_kind = "NATURAL"
    else:
        d1 = snap_out(E + d1_min, tick, True) - E
        rr_need = ((rr_min * (r + c + hl) + c + hl - w1 * d1) / w2) if hedging else d2_required(rr_min, d1, r, c, c, w1, w2)
        need = max(d1 + tick, rules["tp2_r_mult"] * r, rr_need)
        d2 = snap_out(E + need, tick, True) - E
        target_kind = "SOLVER_MINIMUM"
    rr_g1, rr_g2 = d1 / r, d2 / r
    rr_net = rr_plan_net(d1, d2, r, c, c, w1, w2)
    rr_b = rr_basket(d1, d2, r, c, hl, hl, w1, w2) if hedging else None
    out.update(tp1=E + d1, tp2=E + d2, d1=round(d1, 10), d2=round(d2, 10), d1_pips=round(d1 / pip, 2), d2_pips=round(d2 / pip, 2),
               rr_tp1_gross=round(rr_g1, 4), rr_tp2_gross=round(rr_g2, 4), rr_plan_net=round(rr_net, 4),
               rr_basket_net_target=None if rr_b is None else round(rr_b, 4), hedge_loss_bound=hl if hedging else None, target_kind=target_kind,
               target_space=target_space, reach=reach)
    if (rr_b if hedging else rr_net) < rr_min - 1e-6:
        return {**out, "status": "NO_TRADE", "reason_code": "RR_BELOW_MIN",
                "reason": f"RR {'koszyka' if hedging else 'planu'} netto {(rr_b if hedging else rr_net):.3f} < {rr_min}"}
    if target_space is not None and E + d2 > target_space + EPS:
        return {**out, "status": "NO_TRADE", "reason_code": "TARGET_UNREACHABLE",
                "reason": f"TP2 ({d2:.2f} od wejścia) za przeciwnym poziomem znanym przy wejściu ({target_space - E:.2f}) – cel nie jest odsuwany"}
    if reach is not None and d2 > reach + EPS:
        return {**out, "status": "NO_TRADE", "reason_code": "TARGET_UNREACHABLE",
                "reason": f"TP2 {d2:.2f} > zasięg heurystyki ATR {reach:.2f} w czasie pozycji (filtr heurystyczny, nie prawdopodobieństwo)"}
    return {**out, "status": "OK", "reason_code": "OK", "reason": "plan spełnia minima pakietu"}


def scenarios(*, d1: float, d2: float, r: float, c: float, hl: float | None, w1: float, w2: float, stress_gap: float, stress_slip: float) -> list[dict]:
    """Bounded scenario model of the plan / basket in R of the initial basket risk (r + C + HL). A property of the defined scenarios,
    not a guarantee of the maximum loss (gaps, liquidity and execution errors can exceed it)."""
    h = hl or 0.0
    R0 = r + c + h
    rows = [{"id": "NO_HEDGE_BOTH_TP", "net_r": (w1 * d1 + w2 * d2 - c) / R0},
            {"id": "STOP_NO_HEDGE", "net_r": -(r + c) / R0},
            {"id": "TP1_THEN_STOP", "net_r": (w1 * d1 - w2 * r - c) / R0},
            {"id": "GAP_STRESS_STOP", "net_r": -(r + c + stress_gap + stress_slip) / R0}]
    if hl is not None and h > 0:
        rows += [{"id": "HEDGE_RETURN_BOTH_TP", "net_r": (w1 * d1 + w2 * d2 - c - h) / R0},
                 {"id": "HEDGE_WHIPSAW_STOP", "net_r": -(r + c + h) / R0},
                 {"id": "HEDGE_CONTINUE_STOP", "net_r": None, "note": "noga hedge zmniejsza stratę bazy – wynik zależy od ceny aktywacji (raport po fillu)"},
                 {"id": "PARTIAL_BEFORE_ACTIVATION", "net_r": (w1 * d1 + w2 * d2 - c - h * w2) / R0, "note": "hedge liczony od pozostałej bazy"},
                 {"id": "HEDGE_REJECTED", "net_r": None, "note": "jak ścieżki bez hedge (odrzucenie nie jest fillem)"},
                 {"id": "TIMEOUT", "net_r": None, "note": "wyjście koszyka po limicie czasu – wynik w przedziale [STOP; cele]"}]
    for x in rows:
        if x["net_r"] is not None:
            x["net_r"] = round(x["net_r"], 4)
    return rows
