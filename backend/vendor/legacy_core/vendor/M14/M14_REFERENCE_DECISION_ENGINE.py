"""MasterQUO M14 v1.0.0-CANDIDATE: deterministic read-only decision gate.
No MetaTrader connection, order_send, authorization, background loops, or persistence.
Only Python standard library is used.
"""
from __future__ import annotations
import argparse, copy, json, math
from datetime import datetime, timezone
from typing import Any

VERSION = "1.0.0-CANDIDATE"
POLICY = "MT5_PRIMARY_TV_SUPPLEMENTAL_NO_SCREENSHOTS"
CORE = ("structural_advantage", "meaningful_location", "liquidity_context", "development_path", "known_invalidation")
CONFIRM = ("data", "trigger", "invalidation", "expiry", "conflict")
SCORE_WEIGHTS = {
    "structure": 15, "liquidity": 15, "displacement_structure": 15,
    "poi_location": 10, "htf_mtf_alignment": 10, "price_action": 10,
    "order_flow": 5, "usd_macro_event": 5, "session_regime_volatility": 5,
    "trap_filter": 5, "risk_invalidation_rr": 5,
}
TERMINAL = {"INVALIDATED", "CANCELLED", "EXPIRED", "MISSED_ENTRY", "EXITED", "REVIEWED"}
EARLY = {"EARLY_SETUP", "SETUP_FORMING"}
CONDITIONAL = {"QUALIFIED", "ARMED", "TRIGGERED"}
DONE = {"ENTERED", "MANAGED"}


def _time(v: Any):
    if not isinstance(v, str):
        return None
    try:
        t = datetime.fromisoformat(v.replace("Z", "+00:00"))
        return t.astimezone(timezone.utc) if t.tzinfo is not None else None
    except ValueError:
        return None


def _valid_asof(v: Any, now: datetime) -> bool:
    t = _time(v)
    return t is not None and t <= now


def _gate(gate_id: str, scope: str, status: str, reason: str, evidence=None, unblock=None):
    return {"gate_id": gate_id, "required_for": [scope], "status": status,
            "evidence_ids": list(evidence or []), "reason_codes": [] if status == "PASS" else [reason],
            "unblock_condition": None if status == "PASS" else (unblock or reason)}


def _num(v):
    return isinstance(v, (float, int)) and not isinstance(v, bool) and math.isfinite(float(v))


def score_sq41(components):
    """Score 0..100 is NOT probability, signal, permission or trade expectancy."""
    known = 0.0; coverage_weight = 0; used_events = {}; details = {}; reasons = []
    components = components if isinstance(components, dict) else {}
    for group, w in SCORE_WEIGHTS.items():
        v = components.get(group)
        evidence = v if isinstance(v, dict) else {}
        q = evidence.get("q")
        eid = evidence.get("underlying_event_id")
        if eid and eid in used_events and group != used_events[eid]:
            q = None
            reasons.append("DEPENDENT_EVIDENCE_NOT_DOUBLE_COUNTED:" + group)
        if eid and q is not None:
            used_events[eid] = group
        if not (_num(q) and float(q) in (0.0, 0.5, 1.0)):
            details[group] = {"weight": w, "q": None, "reason": "UNKNOWN_OR_DEPENDENT"}
            continue
        coverage_weight += w; known += w * float(q)
        details[group] = {"weight": w, "q": float(q), "reason": None}
    unknown = 100 - coverage_weight
    return {"value": round(known, 10) if unknown == 0 else None, "unit": "score",
            "score_status": "COMPLETE" if not unknown else ("PARTIAL" if coverage_weight else "UNAVAILABLE"),
            "method_id": "SQ-4.1", "known_points": round(known, 10),
            "coverage": coverage_weight / 100, "score_interval": [round(known, 10), round(known + unknown, 10)],
            "components": details, "reason_codes": reasons,
            "quality_band": _band(known) if not unknown else "UNKNOWN"}


def _band(s):
    if s < 50: return "LOW_QUALITY"
    if s < 60: return "OBSERVATION_QUALITY"
    if s < 70: return "EARLY_QUALITY"
    if s < 80: return "CONDITIONAL_QUALITY"
    if s < 90: return "HIGH_QUALITY"
    return "A_PLUS_QUALITY"


def evaluate(payload: dict) -> dict:
    """Analyze a joined payload. All execution permissions fail closed by construction.
    Treat ALL JSON declarations as untrusted; trusted broker/user auth cannot be verified here.
    """
    p = copy.deepcopy(payload)
    stamp = p.get("as_of")
    now = _time(stamp)
    snap = p.get("data_snapshot") or {}
    runtime = p.get("runtime") or {}
    rr = p.get("router_result") or {}
    setup = p.get("setup") or {}
    risk = p.get("risk_result") or {}
    registry = p.get("registry_snapshot") or {}
    config = p.get("config") or {}
    gates = []
    def put(name, scope, yes, code, pending=False, ids=None, unblock=None):
        status = "PASS" if yes else ("PENDING" if pending else "FAIL")
        gates.append(_gate(name, scope, status, code, ids, unblock))
        return yes
    validtime = now is not None
    contract = (p.get("schema_version") == "2.0.0" and p.get("data_source_policy") == POLICY
                and p.get("screenshot_capture_enabled") is False
                and p.get("visual_capture_enabled", False) is False
                and p.get("ocr_enabled", False) is False)
    put("CONTRACT", "ANALYSIS", contract, "UNSUPPORTED_SCHEMA_OR_VISUAL_INPUT")
    put("AS_OF", "ANALYSIS", validtime, "INVALID_AS_OF")
    ds_t = snap.get("as_of")
    same_instrument = bool(setup.get("instrument_id")) and setup.get("instrument_id") == snap.get("instrument_id")
    same_snapshot = bool(snap.get("snapshot_id")) and setup.get("snapshot_id") == snap.get("snapshot_id")
    timestamps_ok = bool(validtime and _time(ds_t) == now and _valid_asof(setup.get("last_as_of", stamp), now))
    data_ok = bool(contract and timestamps_ok and same_instrument and same_snapshot
                   and snap.get("analysis_gate") in ("PASS", "PASS_WITH_LIMITATIONS"))
    put("M01_ANALYSIS", "ANALYSIS", data_ok, "M01_ANALYSIS_INVALID", ids=snap.get("evidence_ids", []))
    candidate = next((x for x in (rr.get("analysis_pool") or [])
                      if isinstance(x, dict) and x.get("setup_id") == setup.get("setup_id")), None)
    tier_selector = ("top_confirmed_setup_id" if setup.get("state") == "CONFIRMED" else
                     "top_conditional_setup_id" if setup.get("state") in CONDITIONAL else
                     "top_early_setup_id" if setup.get("state") in EARLY else None)
    chosen_top = rr.get(tier_selector) if tier_selector else None
    selected_ok = not chosen_top or chosen_top == setup.get("setup_id")
    route_ok = (rr.get("module_id") == "M09" and candidate is not None
                and candidate.get("analytical_eligible") is True and selected_ok)
    put("M09_ANALYSIS", "ANALYSIS", route_ok, "ROUTER_CANDIDATE_NOT_ELIGIBLE")
    core_reasons, ids = [], []
    for key in CORE:
        e = (setup.get("core_evidence") or {}).get(key)
        if not isinstance(e, dict) or not e.get("evidence_id"):
            core_reasons.append("CORE_MISSING:" + key); continue
        ids.append(e["evidence_id"])
        if (not validtime or not _valid_asof(e.get("available_at"), now)
            or e.get("snapshot_id") != snap.get("snapshot_id")
            or e.get("instrument_id") != snap.get("instrument_id")
            or e.get("evidence_status") != "VERIFIED"
            or e.get("source") not in ("MT5_PRIMARY", "MT5_DERIVED")
            or (e.get("requires_closed_bar") and e.get("bar_state") != "CLOSED")):
            core_reasons.append("CORE_INVALID:" + key)
    if not setup.get("invalidation") or not setup.get("next_expected_event"):
        core_reasons.append("MISSING_DEVELOPMENT_OR_INVALIDATION")
    cores = not core_reasons
    put("M03E_CORE", "EARLY_SETUP", cores, ";".join(core_reasons) or "MISSING_CORE", ids=ids)
    direction = setup.get("direction")
    direction_ok = direction in ("LONG", "SHORT") and bool(setup.get("horizon_id"))
    put("DIRECTION_HORIZON", "DIRECTION", direction_ok, "MISSING_DIRECTION_OR_HORIZON")
    conflict = (rr.get("horizon_conflicts") or [])
    conflicting = any(isinstance(x, dict) and (x.get("horizon_id") == setup.get("horizon_id")
                     or setup.get("setup_id") in x.get("setup_ids", [])) for x in conflict)
    put("HORIZON_CONFLICT", "ANALYSIS", not conflicting, "UNRESOLVED_SAME_HORIZON_CONFLICT")
    state = setup.get("state")
    invalidated = bool(setup.get("invalidated") or state == "INVALIDATED")
    expired = bool(setup.get("expired") or state == "EXPIRED")
    terminal = state in TERMINAL or invalidated or expired
    put("SETUP_VALIDITY", "ANALYSIS", not terminal, "TERMINAL_OR_INVALIDATED_SETUP")
    trigger = (setup.get("trigger_event_id") and setup.get("trigger_confirmed") is True
               and setup.get("trigger_source") == "MT5_PRIMARY"
               and validtime and _valid_asof(setup.get("trigger_available_at"), now))
    conf_gates = setup.get("confirmation_gates") or {}
    confirmed = bool(trigger and state == "CONFIRMED" and setup.get("confirmation_source") == "MT5_PRIMARY"
                     and setup.get("distinct_confirmation") is True
                     and all(conf_gates.get(g) == "PASS" for g in CONFIRM))
    put("ANALYTICAL_CONFIRMATION", "CONFIRMATION", confirmed, "TRIGGER_OR_CONFIRMATION_UNPROVEN",
        ids=[setup["trigger_event_id"]] if setup.get("trigger_event_id") else [])
    score = score_sq41(p.get("score_components"))
    audit_reasons = []
    if not (contract and data_ok and validtime):
        decision, validity, tier = "NO_TRADE", "INSUFFICIENT_EVIDENCE", "NONE"
        intended = "UNKNOWN"; audit_reasons.append("ANALYSIS_DATA_UNTRUSTWORTHY")
    elif terminal:
        decision, validity, tier = "NO_TRADE", ("INVALID" if invalidated else "EXPIRED"), "NONE"
        intended = direction if direction_ok else "UNKNOWN"
    elif conflicting:
        decision, validity, tier = "WAIT", "INSUFFICIENT_EVIDENCE", "NONE"
        intended = "UNKNOWN"; audit_reasons.append("HORIZON_CONFLICT")
    elif not route_ok or not cores or not direction_ok:
        decision, validity, tier = "WAIT", "INSUFFICIENT_EVIDENCE", "NONE"
        intended = direction if direction_ok else "UNKNOWN"
    elif state in EARLY:
        decision, validity, tier = "EARLY_SETUP", "VALID_EARLY_SETUP", "EARLY"
        intended = direction
    elif state in CONDITIONAL or state == "CONFIRMED" and not confirmed:
        decision, validity, tier = "CONDITIONAL_SETUP", "VALID_CONDITIONAL_SETUP", "CONDITIONAL"
        intended = direction
    elif state == "CONFIRMED" and confirmed:
        decision, validity, tier = direction, "VALID_CONFIRMED_SETUP", "CONFIRMED"
        intended = direction
        if (score.get("value") is not None and score["value"] >= 90
            and setup.get("plan", {}).get("rr_net") is not None
            and setup.get("context_consistent") is True):
            tier = "A_PLUS"
    else:
        decision, validity, tier = "WAIT", "INSUFFICIENT_EVIDENCE", "NONE"
        intended = direction if direction_ok else "UNKNOWN"
    # Execution: missing or untrusted fields never become an authorization.
    environment = p.get("execution_environment", "ANALYSIS_ONLY")
    env_ok = environment in ("PAPER", "DEMO", "LIVE")
    put("ENVIRONMENT", "EXECUTION", env_ok, "ANALYSIS_ONLY_OR_INVALID_ENVIRONMENT")
    put("M01_EXECUTION", "EXECUTION", snap.get("execution_gate") == "PASS" and data_ok,
        "MT5_EXECUTION_DATA_NOT_PASS")
    put("M16_RUNTIME", "EXECUTION", runtime.get("status") == "HEALTHY"
        and runtime.get("snapshot_id") == snap.get("snapshot_id"), "RUNTIME_NOT_HEALTHY")
    quote = snap.get("quote") or {}
    maxage = config.get("max_quote_age_seconds")
    age_ok = bool(validtime and _num(maxage) and float(maxage) >= 0
                  and (qt := _time(quote.get("available_at"))) is not None
                  and 0 <= (now - qt).total_seconds() <= float(maxage))
    b, a = quote.get("bid"), quote.get("ask")
    quote_ok = bool(quote.get("source") == "MT5_PRIMARY" and quote.get("evidence_status") == "VERIFIED"
                    and _num(b) and _num(a) and 0 < b <= a and age_ok)
    put("BROKER_QUOTE", "EXECUTION", quote_ok, "MISSING_STALE_OR_NONBROKER_QUOTE")
    registry_ok = bool(registry.get("source") == "TRUSTED_M08_ADAPTER" and registry.get("attested") is True
        and registry.get("strategy_id") == setup.get("strategy_id") and registry.get("strategy_version") == setup.get("strategy_version")
        and registry.get("spec_hash") == setup.get("spec_hash") and registry.get("status") in
        (("LIVE_ACTIVE", "LIVE_CONDITIONAL", "LIVE_REDUCED") if environment == "LIVE" else
        ("FORWARD_TEST", "LIVE_ACTIVE", "LIVE_CONDITIONAL", "LIVE_REDUCED"))
        and validtime and _valid_asof(registry.get("validated_at"), now)
        and (_time(registry.get("expires_at")) is not None and _time(registry["expires_at"]) >= now))
    put("M08_STRATEGY", "EXECUTION", registry_ok, "NO_VALID_ATTESTED_REGISTRY_ENTRY")
    account = p.get("account") or {}
    account_ok = (account.get("source") == "MT5_PRIMARY" and account.get("verified") is True
                  and account.get("account_type") == "ZERO_SPREAD")
    put("ACCOUNT_PROFILE", "EXECUTION", account_ok, "MT5_ZERO_ACCOUNT_PROFILE_NOT_VERIFIED")
    put("M10_CONFIRMED", "EXECUTION", decision in ("LONG", "SHORT") and confirmed,
        "SETUP_NOT_CONFIRMED")
    plan = setup.get("plan") or {}
    plan_ok = bool(plan.get("plan_status") == "COMPLETE" and plan.get("rr_net") is not None
                   and plan.get("management_rules") and plan.get("entry") is not None
                   and plan.get("stop_loss") is not None and plan.get("targets")
                   and plan.get("cost_verified") is True and plan.get("entry_tolerance_verified") is True)
    put("PLAN_COSTS", "EXECUTION", plan_ok, "PLAN_COSTS_OR_MANAGEMENT_INCOMPLETE")
    risk_ok = bool(risk.get("module_id") == "M11" and risk.get("setup_id") == setup.get("setup_id")
                   and risk.get("risk_gate") == "PASS" and risk.get("preliminary_risk_eligible") is True
                   and risk.get("risk_policy_frozen") is True and risk.get("account_verified") is True
                   and risk.get("portfolio_reconciled") is True and risk.get("costs_verified") is True)
    put("M11_RISK", "EXECUTION", risk_ok, "RISK_BUDGET_OR_BROKER_COSTS_NOT_VERIFIED")
    put("EVENT_TRAP", "EXECUTION", snap.get("event_gate") == "PASS" and snap.get("trap_gate") == "PASS"
        and p.get("kill_switch") is False, "EVENT_TRAP_OR_KILL_SWITCH")
    portfolio = p.get("portfolio_snapshot") or {}
    port_ok = bool(portfolio.get("source") == "MT5_PRIMARY" and portfolio.get("verified") is True
            and portfolio.get("reconciled") is True and portfolio.get("instrument_id") == snap.get("instrument_id")
            and portfolio.get("snapshot_id") == snap.get("snapshot_id"))
    put("PORTFOLIO", "EXECUTION", port_ok, "PORTFOLIO_NOT_RECONCILED")
    # An arbitrary JSON 'AUTHORIZED' / 'executor_available' can NEVER create a trusted action.
    action_block = [g["gate_id"] for g in gates if g["required_for"] == ["EXECUTION"] and g["status"] != "PASS"]
    if action_block: provisional = "BLOCKED"
    else: provisional = "READY"
    if not env_ok: action_block.insert(0, "ANALYSIS_ONLY")
    action_block.append("TRUSTED_AUTHORIZATION_AND_EXECUTOR_ABSENT")
    # In a production integration actual authentication and final broker recheck are external.
    result = {
        "module_id": "M14", "module_version": VERSION, "schema_version": "2.0.0",
        "analysis_id": p.get("analysis_id"), "as_of": stamp, "run_status": "COMPLETED",
        "status": "PASS_WITH_LIMITATIONS" if decision not in ("NO_TRADE",) else "FAIL",
        "data_source_policy": POLICY, "screenshot_capture_enabled": False,
        "decision_scope": "ANALYSIS", "decision": decision, "intended_direction": intended,
        "top_setup_id": setup.get("setup_id") if route_ok else None,
        "horizon_id": setup.get("horizon_id"), "signal_validity": validity, "signal_tier": tier,
        "entry_status": "READY" if confirmed and decision in ("LONG", "SHORT") else
                        ("CONDITIONAL" if decision in ("EARLY_SETUP", "CONDITIONAL_SETUP") else "NOT_READY"),
        "entry_trigger": "CONFIRMED" if confirmed else "NOT_CONFIRMED",
        "setup_score": score, "probabilities": p.get("probabilities") if isinstance(p.get("probabilities"), dict) else None,
        "execution_environment": environment, "preliminary_execution_readiness": provisional,
        "execution_permission": "BLOCKED", "execution_eligible": False,
        "live_execution_allowed": False, "submitted_order_id": None,
        "order_actions": [], "broker_order_sent": False,
        "execution_blockers": sorted(set(action_block)), "reason_codes": audit_reasons,
        "gates": gates, "limitations": ["UNTRUSTED_JSON_INPUT", "NO_TRUSTED_AUTHORITY", "NO_BROKER_ADAPTER",
          "NO_EXECUTION_SUBMISSION", "REAL_MT5_INTEGRATION_NOT_TESTED"],
    }
    return result


def main():
    parser = argparse.ArgumentParser(description="M14 deterministic offline decision tree; never sends broker orders")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    with open(args.input, encoding="utf-8") as f: payload = json.load(f)
    result = evaluate(payload)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write("\n")
    print(json.dumps({k: result[k] for k in ("decision", "execution_permission", "signal_tier", "preliminary_execution_readiness")}, ensure_ascii=False))

if __name__ == "__main__":
    main()
