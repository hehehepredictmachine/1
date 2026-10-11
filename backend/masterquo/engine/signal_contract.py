"""Signal contract (MQ-SIGNAL-1.0.0) - one object used by the engine, API, monitor, history and notifications.

Built from the deterministic decision of the engine (strategy setup + risk engine + data gate) and, when available,
the AI assessment of exactly that setup state. Prices, SL/TP, costs and sizing come from the engine and the broker
calculator; the AI only qualifies (agrees / disagrees) and explains - it never adds levels or a "probability".

status (Polish, for the user):  OCZEKIWANIE | POTWIERDZONY | ZABLOKOWANY | UNIEWAŻNIONY | WYGASŁY | BRAK_DANYCH
execution_state (separate):     BRAK | WYSŁANO | WYKONANO | ODRZUCONO
decision_source:                STRATEGIA | STRATEGIA + AI   (a strategy-only signal is never labelled as AI)
probability_win:                only from a calibrated ML model validated out of sample (champion), else null
"""
from __future__ import annotations

from ..timeutil import CONTEXT_TIMEFRAMES, TF_SECONDS, iso, parse_iso

SIGNAL_SCHEMA = "MQ-SIGNAL-1.0.0"
RR_NET_DEFINITION = ("RR po kosztach = (ważony zysk do celów − prowizja w obie strony − stres poślizgu) / "
                     "(strata do SL + prowizja + stres poślizgu), liczone kalkulatorem brokera dla 1 lota")
RR_GROSS_DEFINITION = "RR brutto = ważona odległość do celów / odległość do SL od planowanej ceny wejścia (bez kosztów)"

STAGE_TERMINAL = {"INVALIDATED": "UNIEWAŻNIONY", "EXPIRED": "WYGASŁY", "MISSED_ENTRY": "WYGASŁY", "CANCELLED": "UNIEWAŻNIONY"}


def _rr_gross(side: str, entry: float | None, sl: float | None, targets: list[dict]) -> float | None:
    if entry is None or sl is None or not targets:
        return None
    risk = (entry - sl) if side == "LONG" else (sl - entry)
    if risk <= 0:
        return None
    w = sum(float(t.get("weight") or 0) for t in targets) or 1.0
    rew = sum(float(t.get("weight") or 0) / w * ((t["price"] - entry) if side == "LONG" else (entry - t["price"])) for t in targets)
    return round(rew / risk, 3)


def levels_consistent(side: str, entry: float | None, sl: float | None, targets: list[dict]) -> bool:
    if entry is None or sl is None or not targets:
        return False
    tps = [t["price"] for t in targets]
    if side == "LONG":
        return sl < entry < min(tps)
    return max(tps) < entry < sl


def _ai_block(agent_result: dict | None, setup: dict | None, agent_status: dict | None, snapshot_ok: bool) -> dict:
    st = (agent_status or {}).get("state")
    if st in ("AI_UNAVAILABLE_NO_KEY", "MODEL_NOT_CONFIGURED", "DISABLED"):
        return {"status": "AI_NIEDOSTEPNE", "detail": st, "verdict": None, "explanation": None}
    if not setup:
        return {"status": "BRAK_SETUPU", "verdict": None, "explanation": None}
    if not agent_result:
        return {"status": "OCZEKUJE_NA_OCENE" if setup.get("state") == "CONFIRMED" else "OCENA_TYLKO_PO_POTWIERDZENIU", "verdict": None,
                "explanation": None}
    if agent_result.get("status") != "OK" or not agent_result.get("record"):
        return {"status": "AI_BLAD", "detail": agent_result.get("status"), "verdict": None, "explanation": None}
    rec = agent_result["record"]
    stale = (agent_result.get("setup_state_changed_at") != setup.get("state_changed_at") or rec.get("setup_id") != setup.get("setup_id")
             or not snapshot_ok)
    want = "BUY" if setup.get("direction") == "LONG" else "SELL"
    verdict = "ZGODA" if rec.get("proposed_action") == want else "BRAK_ZGODY"
    return {"status": "NIEAKTUALNA" if stale else "AKTUALNA", "verdict": None if stale else verdict, "proposed_action": rec.get("proposed_action"),
            "explanation": rec.get("explanation_pl"), "contradictions": rec.get("contradictions"), "missing_data": rec.get("missing_data"),
            "model_id": rec.get("model_id"), "decision_id": rec.get("decision_id"), "as_of": rec.get("as_of_utc"),
            "expires_at": rec.get("expires_at_utc"), "snapshot_id": agent_result.get("snapshot_id")}


def build(d: dict, *, quote: dict | None, row: dict | None, agent_result: dict | None, agent_status: dict | None,
          context: dict | None, costs: dict | None, attempts: list[dict] | None, ml: dict | None, data_source: str) -> dict | None:
    """d = decision record; row = tracker row of the selected setup (stage/expiry/terminal); context = M30/H8 summary."""
    setup = d.get("setup")
    if not setup:
        return None
    lv = d.get("levels") or {}
    risk = d.get("risk") or {}
    side = setup.get("direction")
    stage = setup.get("state")
    nodes = {n["node"]: n for n in d.get("decision_tree") or []}
    ep = setup.get("entry_plan") or {}
    targets = lv.get("targets") or []
    sl = lv.get("stop_loss")
    confirmed = stage == "CONFIRMED"
    bid, ask = (quote or {}).get("bid"), (quote or {}).get("ask")
    planned = (ask if side == "LONG" else bid) if (confirmed and quote) else (ep.get("trigger_level") or ep.get("reference_price"))
    # ---- status
    block = []
    if (row or {}).get("status") and row["status"] != "ACTIVE":
        status = STAGE_TERMINAL.get(row.get("terminal_reason") or row["status"], "UNIEWAŻNIONY")
    elif nodes.get("DATA", {}).get("status") == "FAIL" or (row or {}).get("stale"):
        status = "BRAK_DANYCH"
    elif not confirmed:
        status = "OCZEKIWANIE"
    else:
        for name in ("DATA", "MARKET", "STRATEGY", "RISK", "AI", "ML", "PERMISSION"):
            n = nodes.get(name)
            if n and n["status"] not in ("PASS", "NOT_REQUIRED"):
                block += [f"{name}:{c}" for c in (n.get("reason_codes") or n.get("unmet") or ["BLOCKED"])]
        status = "POTWIERDZONY" if d.get("decision") in ("BUY", "SELL") else "ZABLOKOWANY"
    if confirmed and not levels_consistent(side, planned, sl, targets):
        if status == "POTWIERDZONY":
            status = "ZABLOKOWANY"
        block.append("LEVELS_INCONSISTENT_WITH_LIVE_PRICE")
    if setup.get("strategy_id") and status == "POTWIERDZONY" and d.get("execution_permission") != "ALLOWED":
        block.append("EXECUTION_NOT_PERMITTED_BY_MODE")
    # ---- execution state (separate)
    ex = "BRAK"
    for a in attempts or []:
        if a.get("setup_id") == setup.get("setup_id") or a.get("decision_id") == d.get("decision_id"):
            st = str(a.get("state") or "")
            ex = "WYKONANO" if st in ("FILLED", "DONE", "PARTIAL") else ("ODRZUCONO" if st in ("REJECTED", "FAILED", "CANCELLED", "ERROR") else "WYSŁANO")
            break
    ai = _ai_block(agent_result, setup, agent_status, True)
    source = "STRATEGIA + AI" if ai.get("verdict") else "STRATEGIA"
    spread = (ask - bid) if (bid is not None and ask is not None) else None
    sl_dist = abs(planned - sl) if (planned is not None and sl is not None) else None
    tf = setup.get("setup_tf")
    ctx_tfs = ["H1", "H4"] + [t for t in CONTEXT_TIMEFRAMES]
    valid_until = (row or {}).get("expires_at") or d.get("expires_at_utc")
    prob = None
    if (ml and ml.get("calibrated_probability") is not None and ml.get("calibration_status") not in (None, "NONE")
            and ml.get("readiness") == "READY"):
        prob = {"value": ml["calibrated_probability"], "model": ml.get("model_id"), "model_version": ml.get("model_version"),
                "event": "etykieta ML: osiągnięcie celu przed SL netto (ml/labels.py)", "validated": "walk-forward z purgingiem (champion)"}
    cl = d.get("checklist") or {}
    return {
        "schema": SIGNAL_SCHEMA, "signal_id": f"SIG-{setup['setup_id']}-v{setup.get('version') or 1}", "setup_id": setup["setup_id"],
        "strategy_id": setup.get("strategy_id"), "strategy_version": setup.get("strategy_version"), "strategy_name": setup.get("strategy_name"),
        "symbol": d.get("symbol"), "data_source": data_source, "decision_source": source,
        "status": status, "execution_state": ex, "side": side if status not in ("BRAK_DANYCH",) else side,
        "entry_tf": tf, "context_tfs": ctx_tfs, "snapshot_id": d.get("snapshot_id"), "generated_at": d.get("as_of_utc"), "valid_until": valid_until,
        "reference_price": ep.get("reference_price"), "quote": {"bid": bid, "ask": ask, "time_utc": (quote or {}).get("time_utc"),
                                                                "age_seconds": (quote or {}).get("age_seconds")},
        "entry_type": ep.get("order_type") or "MARKET_ON_CONFIRMATION", "entry_price": planned if confirmed else None,
        "entry_zone": ep.get("zone"), "trigger_level": ep.get("trigger_level"), "fill_price": None,
        "stop_loss": sl if (confirmed or stage in ("EARLY", "EARLY_SETUP", "QUALIFIED", "ARMED", "TRIGGERED")) else None,
        "targets": targets, "tp_rule": (setup.get("exit_rules") or lv.get("exit_rules") or {}).get("tp_rule"),
        "risk_money": risk.get("modeled_loss"), "risk_pct": round(100 * risk["modeled_loss"] / risk["equity"], 3)
        if risk.get("modeled_loss") and risk.get("equity") else None, "volume": risk.get("lots"), "currency": risk.get("currency"),
        "rr_gross": _rr_gross(side, planned, sl, targets), "rr_net": risk.get("rr_net"),
        "rr_definitions": {"gross": RR_GROSS_DEFINITION, "net": RR_NET_DEFINITION},
        "spread": {"price": None if spread is None else round(spread, 10), "points": risk.get("spread_points") or (quote or {}).get("spread_points"),
                   "pct_of_sl_distance": round(100 * spread / sl_dist, 2) if (spread is not None and sl_dist) else None},
        "cost_assumptions": {"commission_per_lot_side": (costs or {}).get("per_lot_per_side"), "commission_source": (costs or {}).get("source"),
                             "slippage_stress_points": (costs or {}).get("slippage_stress_points"), "rr_complete": risk.get("rr_complete")},
        "data_flags": {"data_quality": d.get("data_quality"), "market_state": d.get("market_state"),
                       "context": {k: (context or {}).get(k, {}).get("status") for k in CONTEXT_TIMEFRAMES}},
        "conditions_met": [m.get("label") for m in cl.get("met") or []], "conditions_missing": [m.get("label") for m in cl.get("missing") or []],
        "trigger": ep.get("trigger"), "invalidation": {"level": setup.get("invalidation_level"), "rule": (row or {}).get("record", {}).get("invalidation_rule")},
        "block_reasons": sorted(set(block)), "ai": ai, "quality": {"score": setup.get("setup_score"), "method": "ACTIVE 0–100 (heurystyka strategii, nie prawdopodobieństwo)"},
        "probability_win": prob, "synthetic": d.get("synthetic"),
    }


def ttl_status(sig: dict, now_iso: str) -> dict:
    """Apply TTL: a signal past valid_until is WYGASŁY (never shown as current after a restart/reconnect)."""
    if sig and sig.get("valid_until") and sig["status"] in ("OCZEKIWANIE", "POTWIERDZONY", "ZABLOKOWANY"):
        if parse_iso(now_iso) >= parse_iso(sig["valid_until"]):
            return {**sig, "status": "WYGASŁY", "block_reasons": sorted(set(sig.get("block_reasons", []) + ["TTL"]))}
    return sig
