"""MasterQUO research-only M02I -> M03/M09/M14 adapter v1.0.0 CANDIDATE.

Never submits orders. Takes an immutable matched M01+M02+M02I packet. Indicator
observations are *context*, never independent CORE or verified trade triggers.
All client-provided permissions ignored. M01 preview remains PENDING end-to-end.
"""
from __future__ import annotations
import copy
from datetime import datetime
import json
import math
from pathlib import Path
import sys
from typing import Any

BASE = Path(__file__).resolve().parent
for name in ("M03", "M09", "M14"):
    sys.path.insert(0, str(BASE / "vendor" / name))
from M03_REFERENCE_ENGINE import analyze as m03_analyze
from M09_REFERENCE_ROUTER import run as m09_run
from M14_REFERENCE_DECISION_ENGINE import evaluate as m14_evaluate

VERSION = "1.0.0-CANDIDATE"
REQUIRED_INDICATOR_PROFILE = "M02I-XAUUSD-TF-ROLES-MT5-ZERO-1.1"
POLICY = "MT5_PRIMARY_TV_SUPPLEMENTAL_NO_SCREENSHOTS"
TF_ORDER = ("D1", "H4", "H1", "M15", "M5", "M1")
GOOD = {"PASS", "PASS_WITH_LIMITATIONS"}
CORE = ("structural_advantage", "meaningful_location", "liquidity_context", "development_path", "known_invalidation")
TERMINAL = {"INVALIDATED", "EXPIRED", "CANCELLED", "MISSED_ENTRY"}
INDICATOR_KEYS = ("ema_stack", "ema_extension_context", "adx_strength", "di_direction",
                  "rsi_context", "macd_histogram_cross", "volatility_context", "bollinger_context",
                  "cvd_status", "correlation_warning")


def _time(x: Any) -> datetime | None:
    if not isinstance(x, str): return None
    try:
        z = datetime.fromisoformat(x.replace("Z", "+00:00"))
        return z if z.utcoffset() is not None else None
    except ValueError:
        return None


def _safe_identical(snapshot: dict, market: dict, indicators: dict) -> list[str]:
    reasons = []
    sid = snapshot.get("snapshot_id")
    when = snapshot.get("as_of")
    t = _time(when)
    if not sid or not t: reasons.append("M01_SNAPSHOT_OR_TIME_INVALID")
    if not isinstance(market, dict) or not isinstance(indicators, dict):
        reasons.append("M02_M02I_MISSING"); return reasons
    for module, rec in (("M02", market), ("M02I", indicators)):
        if rec.get("snapshot_id") != sid or not sid: reasons.append(module + "_SNAPSHOT_MISMATCH")
        if rec.get("as_of") != when or _time(rec.get("as_of")) is None: reasons.append(module + "_TIME_MISMATCH")
        if rec.get("instrument_id") != "XAUUSD": reasons.append(module + "_INSTRUMENT_MISMATCH")
    if snapshot.get("instrument_id") != "XAUUSD": reasons.append("M01_INSTRUMENT_MISMATCH")
    if snapshot.get("data_source_policy") != POLICY or snapshot.get("visual_capture_enabled") is not False:
        reasons.append("M01_SOURCE_POLICY_INVALID")
    if indicators.get("market_data_source_policy") != POLICY or indicators.get("visual_capture_enabled") is not False:
        reasons.append("M02I_SOURCE_POLICY_INVALID")
    if market.get("visual_capture_enabled") is not False:
        reasons.append("M02_SOURCE_POLICY_INVALID")
    if indicators.get("profile_id") != REQUIRED_INDICATOR_PROFILE:
        reasons.append("M02I_TIMEFRAME_PROFILE_NOT_APPROVED")
    if snapshot.get("_preview_only") is True: reasons.append("M01_PREVIEW_NOT_PRODUCTION_AUDITED")
    return reasons


def indicator_context(snapshot: dict, market: dict, indicators: dict) -> dict:
    asof = _time(snapshot.get("as_of"))
    reasons = _safe_identical(snapshot, market, indicators)
    view = {}
    allowed = not reasons and market.get("status") in GOOD and indicators.get("status") in GOOD
    # Preserve numerical observations as diagnostic even when overall status is PENDING.
    for tf in TF_ORDER:
        item = (indicators.get("timeframes") or {}).get(tf) or {}
        source = (market.get("timeframes") or {}).get(tf) or {}
        interpretation = item.get("interpretation") or {}
        last = _time(item.get("last_closed_at"))
        market_last = _time(source.get("last_closed_at"))
        valid_boundary = bool(last and market_last and last == market_last and asof and last <= asof)
        tf_ok = bool(allowed and valid_boundary and item.get("status") in GOOD and source.get("status") in GOOD)
        direction = source.get("direction") or "UNKNOWN"
        di = interpretation.get("di_direction", "UNKNOWN")
        contradictory = bool(direction in ("BULLISH", "BEARISH") and di in ("UP", "DOWN") and
                             ((direction == "BULLISH" and di == "DOWN") or (direction == "BEARISH" and di == "UP")))
        # Retain diagnostic numeric values only when M02 and M02I agree on a closed
        # bar boundary not later than as_of. Never expose future/misaligned values.
        safe_values = bool(valid_boundary and item.get("status") in GOOD and source.get("status") in GOOD)
        values = {key: dict(m) for key, m in (item.get("indicators") or {}).items()
                  if safe_values and isinstance(m, dict) and m.get("status") == "AVAILABLE" and
                  isinstance(m.get("value"), (int, float)) and not isinstance(m.get("value"), bool)
                  and math.isfinite(m["value"])}
        view[tf] = {
            "status": "PASS" if tf_ok else ("PENDING" if item else "UNAVAILABLE"),
            "evidence_ids": list(item.get("evidence_ids") or []),
            "m02_last_closed_at": source.get("last_closed_at"),
            "indicator_last_closed_at": item.get("last_closed_at"),
            "source_series_hash": item.get("source_series_hash"),
            "price_basis": item.get("price_basis"),
            "profile_role": item.get("profile_role"),
            "structure_direction": direction,
            "interpretation": {k: interpretation.get(k) for k in INDICATOR_KEYS if k in interpretation},
            "indicators": values, "context_conflict": "DI_VS_STRUCTURE" if contradictory else "NONE",
            "reason_codes": ([] if tf_ok else ["UNVERIFIED_M01_M02_M02I_OR_CLOSED_BAR_BOUNDARY"]),
            "can_confirm_trigger": False,
        }
    # The value of RSI/MACD etc can never independently satisfy M03E five CORE.
    return {"module_id": "M02I_CONTEXT_HANDOFF", "status": "PASS" if allowed and all(x["status"] == "PASS" for x in view.values()) else "PENDING",
            "profile_id": indicators.get("profile_id"), "snapshot_id": snapshot.get("snapshot_id"),
            "as_of": snapshot.get("as_of"), "timeframes": view,
            "scope": "NON_VOTING_INDICATOR_CONTEXT", "indicators_are_not_independent_votes": True,
            "indicator_based_trade_signal": None, "win_probability": None,
            "execution_permission": "BLOCKED", "reason_codes": reasons,
            "limitations": ["NOT_A_NEW_M03E_CORE", "NO_EMPIRICAL_EDGE", "NO_UNVALIDATED_TRIGGER_PROMOTION"]}


def _m14_snapshot(snapshot: dict) -> dict:
    out = copy.deepcopy(snapshot)
    a = out.get("analysis_gate")
    out["analysis_gate"] = a.get("status") if isinstance(a, dict) else (a if isinstance(a, str) else "PENDING")
    e = out.get("execution_gate")
    out["execution_gate"] = e.get("status") if isinstance(e, dict) else (e if isinstance(e, str) else "PENDING")
    return out


def _selected_setup(rr: dict, raw: list[dict]) -> dict | None:
    ranked = [rr.get("top_confirmed_setup_id"), rr.get("top_conditional_setup_id"), rr.get("top_early_setup_id")]
    for sid in ranked:
        if not sid: continue
        entry = next((c for c in rr.get("analysis_pool", []) if c.get("setup_id") == sid), None)
        if entry and entry.get("analytical_eligible"):
            for raw_setup in raw:
                if raw_setup.get("setup_id") == sid: return raw_setup
    return None


def _join_setup(setup: dict, snap: dict) -> dict:
    s = copy.deepcopy(setup)
    # Bridge owns no M10 lifecycle: only consume the supplied stage, never promote it.
    s["state"] = s.get("stage")
    s["strategy_version"] = s.get("version")
    s["last_as_of"] = s.get("available_at")
    return s


def process(packet: dict, m03_profile: dict) -> dict:
    """Offline/realtime read-only handoff. packet needs raw M01 snapshot (not only JSON monitor view).
    `candidate_setups` are externally supplied M10 candidates, not synthesized from indicators.
    """
    if not isinstance(packet, dict): raise ValueError("PACKET_NOT_OBJECT")
    snap = packet.get("data_snapshot") or {}
    market = packet.get("market_state") or {}
    indi = packet.get("indicator_intelligence") or {}
    reasons = _safe_identical(snap, market, indi)
    if packet.get("schema_version") != "2.0.0": reasons.append("SCHEMA_MISMATCH")
    if packet.get("execution_environment", "ANALYSIS_ONLY") != "ANALYSIS_ONLY":
        reasons.append("EXECUTION_ENVIRONMENT_FORBIDDEN")
    if packet.get("account", {}).get("account_type", "ZERO_SPREAD") != "ZERO_SPREAD":
        reasons.append("MT5_ZERO_ACCOUNT_PROFILE_MISMATCH")
    if packet.get("enable_orders") is True or packet.get("screenshot_capture_enabled") is not False:
        reasons.append("ORDERS_OR_SCREENSHOTS_REQUESTED")
    if reasons and any(x not in ("M01_PREVIEW_NOT_PRODUCTION_AUDITED",) for x in reasons):
        # Invalidly mixed snapshots cannot safely be sent through analyzers.
        m03 = {"module_id": "M03", "status": "FAIL", "run_status": "NOT_RUN", "reason_codes": reasons,
               "evidence_ids": [], "early_evidence": {"status": "CANDIDATE", "missing_core": list(CORE)}}
    else:
        try:
            m03 = m03_analyze(snap, market, m03_profile, strategy_plan=packet.get("strategy_plan"))
        except (KeyError, ValueError, TypeError, ZeroDivisionError) as exc:
            m03 = {"module_id": "M03", "status": "FAIL", "run_status": "FAILED", "reason_codes": ["M03_INPUT_INVALID:" + type(exc).__name__],
                   "evidence_ids": [], "early_evidence": {"status": "CANDIDATE", "missing_core": list(CORE)}}
    context = indicator_context(snap, market, indi)
    supplied = packet.get("candidate_setups") or []
    if not isinstance(supplied, list): raise ValueError("CANDIDATE_SETUPS_NOT_LIST")
    # M10 supplied records can only be used when every upstream analytic gate is audited.
    verified = (not reasons and m03.get("status") in GOOD and context["status"] == "PASS" and
                (snap.get("analysis_gate") or {}).get("status") in GOOD and market.get("status") in GOOD)
    # External M10 candidates are NOT created from RSI/EMA. Even in a fully
    # audited synthetic test, only consume those explicitly tied to existing
    # M03/M02 evidence and accompanied by a strategy-owned M03E EARLY plan.
    known_evidence = set(m03.get("evidence_ids", [])) | set(market.get("evidence_ids", []))
    external_plan = packet.get("strategy_plan")
    m03early = (m03.get("early_evidence") or {}).get("status") == "EARLY_SETUP"
    def verifiable_candidate(s):
        if not isinstance(s, dict) or not s.get("setup_id") or not s.get("strategy_id"):
            return False
        core = s.get("core_evidence") or {}
        if not all(isinstance(core.get(k), dict) and core[k].get("evidence_id") for k in CORE):
            return False
        if any(core[k]["evidence_id"] == core[h]["evidence_id"] for i, k in enumerate(CORE) for h in CORE[i+1:]):
            return False
        # Structure/location/liquidity must point to actual already available
        # M01/M02/M03 evidence; a self-declared VERIFIED flag is not enough.
        return all(core[k]["evidence_id"] in known_evidence for k in CORE[:3])
    allowed_candidates = supplied if verified and m03early and isinstance(external_plan, dict) and \
        all(verifiable_candidate(s) for s in supplied) else []
    if supplied and not allowed_candidates: reasons.append("CANDIDATES_WITHHELD_UNVERIFIED_OR_NO_M03E_CORE")
    try:
        route = m09_run({
            "schema_version": "2.0.0", "analysis_id": snap.get("analysis_id"),
            "as_of": snap.get("as_of"), "mode": packet.get("mode", "AUTO"),
            "data_snapshot": snap, "market_state": market,
            "setups": allowed_candidates, "runtime": {"status": "UNVERIFIED"},
            "config": {}, "account": {"account_type": "ZERO_SPREAD", "costs_verified_from_mt5": False},
            "mode_profiles": packet.get("mode_profiles") or {},
            "strategy_specs": {}, "registry_snapshots": [],
            "execution_environment": "ANALYSIS_ONLY", "portfolio_snapshot": None,
        })
    except (KeyError, ValueError, TypeError) as exc:
        route = {"module_id": "M09", "status": "FAIL", "analysis_pool": [], "horizon_conflicts": [],
                 "top_early_setup_id": None, "top_conditional_setup_id": None, "top_confirmed_setup_id": None,
                 "reason_codes": ["M09_ROUTING_FAILED:" + type(exc).__name__], "execution_permission": "BLOCKED"}
    chosen = _selected_setup(route, allowed_candidates)
    placeholder = {"setup_id": None, "instrument_id": snap.get("instrument_id"),
                   "snapshot_id": snap.get("snapshot_id"), "state": "OBSERVE"}
    try:
        decision = m14_evaluate({
            "schema_version": "2.0.0", "analysis_id": snap.get("analysis_id"), "as_of": snap.get("as_of"),
            "data_source_policy": POLICY, "screenshot_capture_enabled": False,
            "visual_capture_enabled": False, "ocr_enabled": False,
            "execution_environment": "ANALYSIS_ONLY", "data_snapshot": _m14_snapshot(snap),
            "router_result": route, "setup": _join_setup(chosen, snap) if chosen else placeholder,
            "runtime": {"status": "UNKNOWN"}, "risk_result": {}, "registry_snapshot": {},
            "account": {"source": "MT5_PRIMARY", "verified": False, "account_type": "ZERO_SPREAD"},
            "config": {}, "portfolio_snapshot": {}, "kill_switch": True,
            "score_components": None,
        })
    except (KeyError, ValueError, TypeError) as exc:
        decision = {"module_id": "M14", "decision": "NO_TRADE", "intended_direction": "UNKNOWN",
                    "execution_permission": "BLOCKED", "execution_eligible": False,
                    "live_execution_allowed": False, "submitted_order_id": None,
                    "reason_codes": ["M14_EVALUATION_FAILED:" + type(exc).__name__]}
    reasons = list(dict.fromkeys(reasons + (m03.get("reason_codes") or []) + (route.get("reason_codes") or []) +
                                 (context.get("reason_codes") or [])))
    return {"schema_version": "2.0.0", "prompt_version": "4.1.0", "module_id": "M02I_M03_M09_M14_READONLY_ADAPTER",
            "module_version": VERSION, "analysis_id": snap.get("analysis_id"), "snapshot_id": snap.get("snapshot_id"),
            "as_of": snap.get("as_of"), "instrument_id": snap.get("instrument_id"),
            "data_source_policy": POLICY, "account_profile": "ZERO_SPREAD_DECLARED_UNVERIFIED",
            "mode": packet.get("mode", "AUTO"), "indicator_context": context, "market_evidence": m03,
            "router_result": route, "decision_result": decision,
            "analysis_decision": decision.get("decision", "NO_TRADE"),
            "intended_direction": decision.get("intended_direction", "UNKNOWN"),
            "selected_setup_id": chosen.get("setup_id") if chosen else None,
            "status": ("PASS_WITH_LIMITATIONS" if verified else
                       "FAIL" if any(x != "M01_PREVIEW_NOT_PRODUCTION_AUDITED" for x in _safe_identical(snap, market, indi))
                       or packet.get("schema_version") != "2.0.0"
                       or packet.get("execution_environment", "ANALYSIS_ONLY") != "ANALYSIS_ONLY"
                       or packet.get("enable_orders") is True
                       or packet.get("screenshot_capture_enabled") is not False
                       or packet.get("account", {}).get("account_type", "ZERO_SPREAD") != "ZERO_SPREAD"
                       else "PENDING"),
            "research_observation_only": True, "analysis_gates_audited": verified,
            "reason_codes": reasons, "execution_permission": "BLOCKED", "execution_eligible": False,
            "live_execution_allowed": False, "broker_order_sent": False, "order_actions": [],
            "submitted_order_id": None, "visual_capture_enabled": False,
            "limitations": ["NO_ORDER_EXECUTION", "NO_LIVE_SIGNAL_CERTIFICATION", "CANDIDATE_M02I_M03_M09_M14", "M06_FORWARD_OOS_PENDING"]}


def main():
    import argparse
    ap = argparse.ArgumentParser(description="M02I->M03->M09->M14 deterministic research adapter (NO ORDERS)")
    ap.add_argument("--input", required=True, help="Packet JSON containing matched raw M01/M02/M02I outputs")
    ap.add_argument("--output", required=True)
    ap.add_argument("--m03-profile", default=str(BASE / "M03_PROFILE.example.json"))
    a = ap.parse_args()
    packet = json.loads(Path(a.input).read_text(encoding="utf-8"))
    result = process(packet, json.loads(Path(a.m03_profile).read_text(encoding="utf-8")))
    dst = Path(a.output)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print("DECISION:", result["analysis_decision"], "| EXECUTION:", result["execution_permission"])

if __name__ == "__main__": main()
