"""Explicit decision tree. Code - not model text - decides entry eligibility.

  1 DATA      required data valid & fresh (data-quality gate)
  2 MARKET    market open, macro window, session
  3 STRATEGY  M02 structure resolved, frozen M07 setup exists, D1/DXY rules
  4 TRIGGER   setup lifecycle reached CONFIRMED (M10A rules) and entry window open
  5 RISK      M11 risk gate PASS (costs, RR net, limits, sizing)
  6 AI        Claude assessment valid for this setup/state, agrees with direction (if required)
  7 PERMISSION operating mode / account / limits allow execution

Separate outputs:
  analysis_direction  LONG | SHORT | NEUTRAL      (what the analysis sees; may be shown while blocked)
  signal_stage        WATCH | EARLY | CONFIRMED | EXPIRED | INVALIDATED
  decision            BUY | SELL | WAIT | NO_TRADE (analytical decision)
  execution_permission ALLOWED | BLOCKED          (may an order be sent now)
"""
from __future__ import annotations

import hashlib
import json
from datetime import timedelta

from ..timeutil import TF_SECONDS, iso, parse_iso
from ..version import DECISION_SCHEMA_VERSION, SPEC_VERSION


def _node(name: str, status: str, met: list[str] | None = None, unmet: list[str] | None = None, codes: list[str] | None = None) -> dict:
    return {"node": name, "status": status, "met": met or [], "unmet": unmet or [], "reason_codes": codes or []}


def structural_direction(m02: dict | None) -> str:
    d = (m02 or {}).get("structural_direction")
    return {"BULLISH": "LONG", "BEARISH": "SHORT"}.get(d, "NEUTRAL")


def build(*, snapshot_id: str, as_of: str, symbol: str, account_key: str | None, session_epoch: int, dq: dict,
          legacy: dict, setup: dict | None, levels: dict | None, risk: dict | None, agent_gate: dict, mode_gate: dict,
          macro: dict, strategy_cfg, risk_cfg, dxy_status: str, synthetic: bool, active: dict | None = None,
          ml_gate: dict | None = None) -> dict:
    """`active` (profile ACTIVE): {"regime", "bias", "trade_allowed", "reason_codes"} - the STRATEGY node then
    validates the setup selected by StrategyAutoSelector instead of the legacy M02/M07 structure rule."""
    nodes = []
    m02 = legacy.get("m02")
    # 1 DATA
    if not dq["analysis_allowed"]:
        nodes.append(_node("DATA", "FAIL", unmet=["ANALYSIS_DATA_VALID"], codes=dq["reason_codes"]))
    elif not dq["entries_allowed"]:
        nodes.append(_node("DATA", "PARTIAL", met=["ANALYSIS_DATA_VALID"], unmet=["ENTRY_DATA_FRESH"], codes=dq["reason_codes"]))
    else:
        nodes.append(_node("DATA", "PASS", met=["ANALYSIS_DATA_VALID", "ENTRY_DATA_FRESH"]))
    # 2 MARKET
    mk_unmet, mk_codes = [], []
    if dq["market_state"] != "OPEN":
        mk_unmet.append("MARKET_OPEN")
        mk_codes.append("MARKET_" + dq["market_state"])
    if risk_cfg.macro_block_high_impact:
        if macro.get("status") not in ("OK", "PARTIAL"):
            if risk_cfg.macro_calendar_required:
                mk_unmet.append("MACRO_CALENDAR_AVAILABLE")
            mk_codes.append("MACRO_CALENDAR_" + str(macro.get("status")))
        elif macro.get("risk_level") == "HIGH":
            mk_unmet.append("NO_HIGH_IMPACT_EVENT_WINDOW")
            mk_codes.append("MACRO_EVENT_WINDOW")
    nodes.append(_node("MARKET", "FAIL" if mk_unmet else "PASS", met=[] if mk_unmet else ["MARKET_OPEN", "MACRO_OK"], unmet=mk_unmet, codes=mk_codes))
    # 3 STRATEGY
    sdir = structural_direction(m02)
    st_unmet, st_met, st_codes = [], [], []
    if active is not None:
        sdir = active.get("bias") or "NEUTRAL"
        reg = active.get("regime") or {}
        st_codes.append("REGIME_" + str(reg.get("state")))
        st_codes += ["TF_CONFLICT_" + c["kind"] for c in reg.get("conflicts") or []]
        if setup is None:
            st_unmet.append("SELECTED_STRATEGY_SETUP")
            st_codes += list(active.get("reason_codes") or [])[:4]
        else:
            st_met.append(f"SELECTED_{setup['strategy_id']}_{setup['state']}")
            if setup.get("countertrend"):
                st_codes.append("COUNTERTREND_" + str(setup.get("horizon")))
        d1 = ((m02 or {}).get("timeframes") or {}).get("D1", {}).get("direction")
        d1_conflict = False
        nodes.append(_node("STRATEGY", "FAIL" if st_unmet else "PASS", st_met, st_unmet, st_codes))
    elif legacy.get("errors"):
        st_codes += legacy["errors"]
    if active is not None:
        pass
    elif sdir == "NEUTRAL":
        st_unmet.append("STRUCTURAL_DIRECTION_RESOLVED")
        st_codes.append("M02_STRUCTURE_" + str((m02 or {}).get("structural_direction")))
    else:
        st_met.append("STRUCTURAL_DIRECTION_" + sdir)
        st_codes += list((m02 or {}).get("structure_notes") or [])
    if active is None:
        d1 = ((m02 or {}).get("timeframes") or {}).get("D1", {}).get("direction")
        d1_conflict = (sdir == "LONG" and d1 == "BEARISH") or (sdir == "SHORT" and d1 == "BULLISH")
    if active is None and d1_conflict:
        st_codes.append("D1_OPPOSES_H4_H1_STRUCTURE")
        if strategy_cfg.d1_conflict_blocks_entry:
            st_unmet.append("D1_NOT_OPPOSING")
    if active is not None:
        pass
    elif setup is None:
        st_unmet.append("FROZEN_M07_SETUP")
        st_codes += [c for c in ((legacy.get("m07") or {}).get("reason_codes") or [])][:6]
    else:
        st_met.append(f"SETUP_{setup['strategy_id']}_{setup['profile']}")
        if setup["strategy_id"] in strategy_cfg.strategies_requiring_dxy and dxy_status != "OK":
            st_unmet.append("DXY_REQUIRED_BY_STRATEGY")
            st_codes.append("DXY_" + dxy_status)
    if active is None:
        nodes.append(_node("STRATEGY", "FAIL" if st_unmet else "PASS", st_met, st_unmet, st_codes))
    # 4 TRIGGER
    stage = setup["signal_stage"] if setup else "WATCH"
    if setup and setup["state"] == "CONFIRMED":
        nodes.append(_node("TRIGGER", "PASS", met=["M10A_CONFIRMED"]))
    elif setup:
        nodes.append(_node("TRIGGER", "PENDING", unmet=["M10A_CONFIRMED"], codes=["SETUP_STATE_" + setup["state"]]))
    else:
        nodes.append(_node("TRIGGER", "SKIPPED", unmet=["SETUP"]))
    # 5 RISK
    if risk is None:
        nodes.append(_node("RISK", "SKIPPED", unmet=["RISK_EVALUATED"]))
    else:
        rs = {"PASS": "PASS", "CONDITIONAL": "PARTIAL", "PREVIEW": "PENDING"}.get(risk["risk_gate"], "FAIL")
        nodes.append(_node("RISK", rs, met=["RISK_GATE_PASS"] if rs == "PASS" else [],
                           unmet=[] if rs == "PASS" else ["RISK_GATE_PASS"], codes=risk.get("reason_codes", [])))
    # 6 AI
    ag = agent_gate.get("status")
    nodes.append(_node("AI", {"PASS": "PASS", "NOT_REQUIRED": "PASS"}.get(ag, "FAIL" if ag in ("FAIL", "DISAGREE") else "PENDING"),
                       met=["AI_" + ag] if ag in ("PASS", "NOT_REQUIRED") else [],
                       unmet=[] if ag in ("PASS", "NOT_REQUIRED") else ["AI_ASSESSMENT_VALID_AND_AGREES"],
                       codes=agent_gate.get("reason_codes", [])))
    # 7 ML (Decision Tree / XGBoost champion). OFF/SHADOW/no model never block; ASSIST blocks below the validated threshold.
    if ml_gate is not None:
        nodes.append(_node("ML", ml_gate["status"], met=["ML_" + ml_gate["mode"]] if ml_gate["status"] == "PASS" else [],
                           unmet=[] if ml_gate["status"] == "PASS" else ["ML_PROBABILITY_ABOVE_THRESHOLD"], codes=ml_gate.get("codes", [])))
    # 8 PERMISSION
    perm_ok = mode_gate["allowed"]
    perm_unmet = [] if mode_gate["allowed"] else ["EXECUTION_MODE_ALLOWS_ORDERS"]
    perm_codes = list(mode_gate.get("reason_codes", []))
    if active is not None and setup is not None and not active.get("trade_allowed", True):
        perm_ok = False
        perm_unmet.append("STRATEGY_ALLOWED_TO_TRADE")
        perm_codes.append(f"STRATEGY_TRADE_DISABLED_{setup['strategy_id']}")
    nodes.append(_node("PERMISSION", "PASS" if perm_ok else "FAIL",
                       met=["MODE_" + mode_gate["mode"]] if perm_ok else [], unmet=perm_unmet, codes=perm_codes))

    by = {n["node"]: n["status"] for n in nodes}
    direction = setup["direction"] if setup and setup["state"] not in ("INVALIDATED", "EXPIRED", "MISSED_ENTRY", "CANCELLED") else sdir
    direction_basis = "SETUP" if setup and direction == setup["direction"] and setup["state"] not in ("INVALIDATED", "EXPIRED", "MISSED_ENTRY", "CANCELLED") \
        else (("REGIME_OBSERVATION" if active is not None else "STRUCTURE_OBSERVATION") if sdir != "NEUTRAL" else "NONE")
    actionable = (by["DATA"] == "PASS" and by["MARKET"] == "PASS" and by["STRATEGY"] == "PASS" and by["TRIGGER"] == "PASS"
                  and by["RISK"] == "PASS" and by["AI"] == "PASS" and by.get("ML", "PASS") == "PASS")
    if actionable:
        decision = "BUY" if direction == "LONG" else "SELL"
    elif by["DATA"] == "FAIL" or (setup and setup["state"] == "CONFIRMED" and by["RISK"] == "FAIL"):
        decision = "NO_TRADE"
    elif by["MARKET"] == "FAIL" and by["DATA"] != "PASS":
        decision = "NO_TRADE"
    else:
        decision = "WAIT"
    permission = "ALLOWED" if actionable and by["PERMISSION"] == "PASS" else "BLOCKED"
    reasons = []
    for n in nodes:
        if n["status"] not in ("PASS",):
            reasons += n["reason_codes"] or n["unmet"]
    tf = (setup or {}).get("setup_tf", "M15")
    exp = parse_iso(as_of) + timedelta(seconds=min(TF_SECONDS[tf] * 2, 3600))
    if agent_gate.get("expires_at"):
        exp = min(exp, parse_iso(agent_gate["expires_at"]))
    core = {"snapshot_id": snapshot_id, "setup_id": (setup or {}).get("setup_id"), "setup_state": (setup or {}).get("state"),
            "decision": decision, "permission": permission, "direction": direction,
            "nodes": [(n["node"], n["status"]) for n in nodes], "risk_gate": (risk or {}).get("risk_gate"),
            "agent": agent_gate.get("agent_decision_id"), "mode": mode_gate["mode"], "epoch": session_epoch}
    content_hash = hashlib.sha256(json.dumps(core, sort_keys=True, default=str).encode()).hexdigest()
    decision_id = "MQD-" + content_hash[:20]
    return {
        "schema_version": DECISION_SCHEMA_VERSION, "spec_version": SPEC_VERSION, "decision_id": decision_id,
        "content_hash": content_hash, "snapshot_id": snapshot_id, "symbol": symbol, "account_key": account_key,
        "session_epoch": session_epoch, "as_of_utc": as_of, "expires_at_utc": iso(exp),
        "analysis_direction": direction, "direction_basis": direction_basis, "signal_stage": stage,
        "decision": decision, "execution_permission": permission, "system_state": "SYNTHETIC_DEMO" if synthetic else "LIVE_DATA",
        "data_quality": dq["data_quality"], "market_state": dq["market_state"],
        "setup": setup, "levels": levels, "risk": risk, "agent_gate": agent_gate, "mode_gate": mode_gate,
        "decision_tree": nodes, "reason_codes": sorted(set(reasons)), "ml": (ml_gate or {}).get("prediction"), "structure": {
            "structural_direction": (m02 or {}).get("structural_direction"), "tactical_direction": (m02 or {}).get("tactical_direction"),
            "regime_conflict": (m02 or {}).get("regime_conflict"), "d1_direction": d1, "d1_conflict": d1_conflict,
            "conflict_rule": "Kierunek strukturalny = zgodność H4 i H1 (M02 SCALP). D1 tylko kontekst" +
                             (" i blokuje wejścia przy konflikcie." if strategy_cfg.d1_conflict_blocks_entry else "; konflikt D1 opisany, nie blokuje.")},
        "profile": "ACTIVE" if active is not None else "ORIGINAL",
        "synthetic": synthetic, "observation_note": None if permission == "ALLOWED" else
            ("Kierunek jest obserwacją analityczną, nie zgodą na wejście." if direction != "NEUTRAL" else None),
    }
