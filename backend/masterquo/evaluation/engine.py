"""AI Setup Probability Engine - shared assessment of every SetupCandidate (PMW-EVAL-ENGINE-1). SHADOW: it never gates or sends.

Event and probability
  The probability always names its event. SH strategies: "TP2 before SL within the horizon" from sh_tp_model (the strategy's own
  event). S01-S12: the legacy ML champion predicts "net R > 0 under the setup plan" - a DIFFERENT event than TP-before-SL, so its
  EV is labelled an approximation. No READY calibrated model -> probability None (NO_MODEL); a raw score is never turned into one.

Economics (R = |entry - SL| in price, entry on the executable side so the spread is already inside the price distances)
  G = (sum_i w_i * |TP_i - entry| - extra_cost) / R       (planned weighted targets, net of costs not already in the prices)
  L = (R + extra_cost) / R
  EV = p * G - (1 - p) * L ;  break-even p* = L / (G + L)  (the EV is positive only when p > p*)
  extra_cost = commission + slippage per unit (price units). Unknown commission is reported, never assumed to be zero silently.
  Partial exits, BE moves and timeouts make the real outcome distribution non-binary: the binary EV is labelled
  BINARY_PLAN_APPROX; it is a comparison scale, not a promise.

Uncertainty
  With the calibration sample size n the probability gets a Wilson 90% interval and the EV interval follows from it; without n the
  interval is unknown (reported). Decision rule (SHADOW): REJECT when EV <= 0 or execution POOR or data not OK; DEFER when there is no
  calibrated probability of a usable event; REDUCE when the EV interval straddles 0 or is unknown (a point EV without its
  uncertainty is not evidence enough for a full position); ACCEPT otherwise. A threshold is therefore p* (costs and R:R), not a
  fixed 75 %.
"""
from __future__ import annotations

import math

from .contract import SetupAssessment, SetupCandidate

VERSION = "PMW-EVAL-ENGINE-1"
DEFAULT_EVENT = {"SH_SCALPING": "TP2 przed SL w horyzoncie", "SH_HEDGING": "TP2 przed SL w horyzoncie",
                 "SCALP_SHADOW": "TP1 przed SL w horyzoncie", "ACTIVE_S01_S12": "net R > 0 wg planu setupu"}
Z90 = 1.6448536269514722


def wilson(p: float, n: int, z: float = Z90) -> list[float]:
    if n <= 0:
        return [0.0, 1.0]
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [max(0.0, c - h), min(1.0, c + h)]


def economics(c: SetupCandidate, extra_cost: float | None) -> dict:
    r = c.risk_price()
    if not (r > 0):
        return {"ok": False, "reason": "R_NOT_POSITIVE"}
    cost = float(extra_cost) if extra_cost is not None else 0.0
    w_tp = sum(t["weight"] * abs(t["price"] - c.entry_price) for t in c.targets)
    g = (w_tp - cost) / r
    l_ = (r + cost) / r
    return {"ok": True, "R_price": r, "gain_r": g, "loss_r": l_, "cost_r": cost / r, "cost_known": extra_cost is not None,
            "break_even_p": (l_ / (g + l_)) if g + l_ > 0 and g > 0 else None}


def execution_quality(c: SetupCandidate, *, max_spread_frac_of_risk: float = 0.25, max_quote_age_s: float = 5.0) -> dict:
    ec = c.execution_context or {}
    issues, r = [], c.risk_price()
    sp = ec.get("spread")
    if sp is not None and r > 0 and sp / r > max_spread_frac_of_risk:
        issues.append(f"SPREAD_{sp / r:.0%}_OF_RISK")
    qa = ec.get("quote_age_s")
    if qa is not None and qa > max_quote_age_s:
        issues.append(f"QUOTE_AGE_{qa:.1f}s")
    if ec.get("commission_known") is False:
        issues.append("COMMISSION_UNKNOWN")
    poor = any(i.startswith(("SPREAD", "QUOTE_AGE")) for i in issues)
    return {"status": "POOR" if poor else ("DEGRADED" if issues else "GOOD"), "issues": issues,
            "spread_frac_of_risk": (sp / r) if sp is not None and r > 0 else None}


def assess(c: SetupCandidate, *, prob: dict | None, extra_cost: float | None, exposure: dict | None = None,
           agreement: dict | None = None, zones: dict | None = None) -> SetupAssessment:
    """prob: {"value", "calibrated": bool, "event", "source", "n_calibration", "event_matches": bool}."""
    a = SetupAssessment(setup_id=c.setup_id, engine=c.engine, strategy_id=c.strategy_id, candidate_key=c.key(), decision_ts=c.decision_ts,
                        event=(prob or {}).get("event") or DEFAULT_EVENT.get(c.engine, "net R > 0 wg planu setupu"),
                        market_regime=dict(c.market_regime), data_timestamp=c.decision_ts,
                        model_agreement=agreement or {"status": "NO_INDEPENDENT_EVIDENCE",
                                                      "note": "brak skalibrowanych, niezależnych modeli dla tego zdarzenia; zgodność modułów z "
                                                              "tego samego feedu cen nie jest potwierdzeniem"})
    reasons = []
    dq = (c.data_quality or {}).get("status")
    if dq not in (None, "OK"):
        reasons.append(f"DATA_{dq}")
    eco = economics(c, extra_cost)
    if not eco["ok"]:
        a.decision, a.rejection_reasons = "REJECT", [eco["reason"]]
        return a
    a.gain_r, a.loss_r, a.cost_r, a.break_even_probability = (round(eco["gain_r"], 4), round(eco["loss_r"], 4), round(eco["cost_r"], 4),
                                                              None if eco["break_even_p"] is None else round(eco["break_even_p"], 4))
    if not eco["cost_known"]:
        a.notes.append("koszt dodatkowy nieznany (prowizja/poślizg) – EV liczone bez niego")
    if eco["gain_r"] <= 0:
        reasons.append("TARGETS_DO_NOT_COVER_COSTS")
    a.execution_quality = execution_quality(c)
    if a.execution_quality["status"] == "POOR":
        reasons.append("EXECUTION_" + "+".join(a.execution_quality["issues"]))
    a.portfolio_risk_status = exposure or {"status": "UNKNOWN"}
    if (exposure or {}).get("status") == "CONFLICT":
        reasons.append("PORTFOLIO_CONFLICT")
    p = (prob or {}).get("value")
    if p is not None and (prob or {}).get("calibrated") and math.isfinite(p):
        a.probability, a.probability_calibrated, a.probability_source = round(float(p), 4), True, (prob or {}).get("source")
        a.probability_status = "CALIBRATED" if (prob or {}).get("event_matches", True) else "EVENT_MISMATCH"
        a.model_versions = {(prob or {}).get("source") or "model": (prob or {}).get("version")}
        ev = p * eco["gain_r"] - (1 - p) * eco["loss_r"]
        a.expected_value_r = round(ev, 4)
        n = int((prob or {}).get("n_calibration") or 0)
        if n > 0:
            lo, hi = wilson(float(p), n)
            a.probability_interval = [round(lo, 4), round(hi, 4)]
            a.expected_value_interval_r = [round(lo * eco["gain_r"] - (1 - lo) * eco["loss_r"], 4),
                                           round(hi * eco["gain_r"] - (1 - hi) * eco["loss_r"], 4)]
            a.uncertainty = {"method": "Wilson 90% na liczności kalibracji", "n_calibration": n}
        else:
            a.uncertainty = {"method": None, "reason": "liczność kalibracji nieznana – przedział EV nieznany"}
        a.notes.append("EV binarne (BINARY_PLAN_APPROX): częściowe wyjścia, BE i timeout czynią rozkład wyniku niebinarnym")
        if a.probability_status == "EVENT_MISMATCH":
            a.notes.append("zdarzenie modelu różni się od TP-przed-SL – EV jest przybliżeniem")
        if ev <= 0:
            reasons.append(f"EV_NOT_POSITIVE({ev:.3f}R)")
    else:
        a.probability_status = "UNCALIBRATED" if p is not None else "NO_MODEL"
        a.uncertainty = {"method": None, "reason": "brak skalibrowanego prawdopodobieństwa zdarzenia"}
        if a.break_even_probability is not None:
            a.notes.append(f"setup wymaga P > {a.break_even_probability:.3f} dla dodatniego EV (próg z kosztów i R:R, nie arbitralny)")
    zflags = []
    if zones:
        a.zone_context = {k: zones.get(k) for k in ("map_id", "map_as_of", "data_state", "opposing_zone", "supporting_zone", "room_after_costs_r", "flags")}
        if zones.get("data_state") == "OK":
            zflags = list(zones.get("flags") or [])
        else:
            a.notes.append(f"mapa stref {zones.get('data_state')} – bez wpływu na ocenę")
    hard = [r for r in reasons if not r.startswith("EV_NOT_POSITIVE")]
    if reasons:
        a.decision = "REJECT"
    elif a.probability is None:
        a.decision, reasons = "DEFER", ["INSUFFICIENT_EVIDENCE_NO_CALIBRATED_PROBABILITY"]
    elif a.expected_value_interval_r is None:
        a.decision, reasons = "REDUCE", ["EV_INTERVAL_UNKNOWN"]
    elif a.expected_value_interval_r[0] <= 0 < a.expected_value_interval_r[1]:
        a.decision, reasons = "REDUCE", ["EV_INTERVAL_STRADDLES_ZERO"]
    elif "ZONE_ROOM_INSUFFICIENT" in zflags:
        a.decision, reasons = "REDUCE", ["ZONE_ROOM_INSUFFICIENT"]            # strong opposing zone closer than min_room_r after costs
    else:
        a.decision = "ACCEPT"
    if "ZONE_ROOM_INSUFFICIENT" in zflags and a.decision != "REDUCE":
        a.notes.append("silna strefa przeciwna bliżej niż minimalne miejsce po kosztach (kontekst strefowy)")
    a.rejection_reasons = reasons if reasons else []
    if hard:
        a.notes.append("odrzucenie niezależne od modelu: " + ", ".join(hard))
    return a
