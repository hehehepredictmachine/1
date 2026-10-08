"""MasterQUO M09 v1.0.0 CANDIDATE — deterministic, read-only strategy router.

OFFLINE REFERENCE ONLY. No MT5 connection, no order execution, no self-approval,
no network, screenshots or strategy registry mutation. No claim of trading edge.
Input is already audited, point-in-time M01/M02/M03E/M08 snapshots.
"""
from __future__ import annotations
import copy
import json
import re
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

SCHEMA = "2.0.0"
POLICY = "MT5_PRIMARY_TV_SUPPLEMENTAL_NO_SCREENSHOTS"
MODES = {"MVP", "SMC", "SCALPING", "AUTO"}
CORE = ("structural_advantage", "meaningful_location", "liquidity_context", "development_path", "known_invalidation")
STAGES = ("OBSERVE", "CANDIDATE", "EARLY_SETUP", "SETUP_FORMING", "QUALIFIED", "ARMED", "TRIGGERED", "CONFIRMED")
TERMINAL_STAGES = {"INVALIDATED", "CANCELLED", "EXPIRED", "MISSED_ENTRY", "ENTERED", "MANAGED", "EXITED", "REVIEWED"}
LIVE_STATUSES = {"LIVE_CONDITIONAL", "LIVE_ACTIVE", "LIVE_REDUCED"}
BLOCKED_STATUSES = {"PAUSED", "QUARANTINED", "RETIRED"}
STABLE_HEALTH = {"HEALTHY", "STABLE"}
TRADINGVIEW_DENIED_CATEGORIES = {"BROKER_QUOTE", "BROKER_CANDLE", "EXECUTION_PRICE", "CONTRACT_SPEC", "ACCOUNT_COST", "MT5_TICK", "BROKER_HISTORY"}
SOURCE_ALLOWED = {"MT5_PRIMARY", "TRADINGVIEW_SUPPLEMENTAL", "DERIVED_FROM_MT5", "BROKER_CALENDAR", "UNKNOWN"}
CATALOG = {
    "XAU-S01": ("TREND_PULLBACK", ("SCALPING",)),
    "XAU-S02": ("LIQUIDITY_REVERSAL", ("SMC", "SCALPING")),
    "XAU-S03": ("BREAKOUT_RETEST", ("SCALPING",)),
    "XAU-S04": ("FAILED_BREAKOUT", ("SCALPING",)),
    "XAU-S05": ("RANGE_REVERSAL", ("SCALPING",)),
    "XAU-S06": ("MOMENTUM", ("SCALPING",)),
    "XAU-S07": ("VOLATILITY_EXPANSION", ("SCALPING",)),
    "XAU-S08": ("HTF_REVERSAL", ("SMC",)),
    "XAU-S09": ("SESSION_MODEL", ("SMC", "SCALPING")),
    "XAU-S10": ("SESSION_MODEL", ("SCALPING",)),
    "XAU-S11": ("SESSION_MODEL", ("SMC", "SCALPING")),
    "XAU-S12": ("LIQUIDITY_REVERSAL", ("SMC",)),
    "XAU-S13": ("LIQUIDITY_REVERSAL", ("SMC",)),
    "XAU-S14": ("SMC_CONTINUATION", ("SMC", "SCALPING")),
    "XAU-S15": ("SMC_CONTINUATION", ("SMC",)),
    "XAU-S16": ("SMC_CONTINUATION", ("SMC",)),
    "XAU-S17": ("SMC_CONTINUATION", ("SMC", "SCALPING")),
    "XAU-S18": ("SMC_REVERSAL", ("SMC", "SCALPING")),
    "XAU-S19": ("BREAKOUT", ("SCALPING",)),
    "XAU-S20": ("NEWS_REACTION", ("SCALPING",)),
}


def utc(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("TIMESTAMP_MISSING")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("TIMESTAMP_INVALID") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("TIMESTAMP_NAIVE")
    return dt.astimezone(timezone.utc)


def safe_time(v: Any, asof: datetime) -> bool:
    try:
        return utc(v) <= asof
    except ValueError:
        return False


def unique(xs: list[str]) -> list[str]:
    return list(dict.fromkeys(xs))


def contains_unsafe_key(obj: Any) -> bool:
    if isinstance(obj, dict):
        if any(k.lower() in {"screenshot", "screen_capture", "capture_screen", "ocr", "image_data", "order_send", "broker_execution"} for k in obj):
            return True
        return any(contains_unsafe_key(v) for v in obj.values())
    if isinstance(obj, list):
        return any(contains_unsafe_key(v) for v in obj)
    return False


def mode_allowed(strategy_id: str, mode: str, profiles: dict[str, Any], custom: dict[str, Any] | None) -> tuple[bool, str | None]:
    if mode == "MVP":
        p = profiles.get("MVP", {})
        if p.get("approved_mapping") is not True or not isinstance(p.get("strategy_ids"), list) or not p["strategy_ids"]:
            return False, "MVP_STRATEGY_DEFINITION_MISSING"
        return (strategy_id in p["strategy_ids"], None if strategy_id in p["strategy_ids"] else "MODE_FILTER")
    if strategy_id in CATALOG:
        return (mode == "AUTO" or mode in CATALOG[strategy_id][1], None if mode == "AUTO" or mode in CATALOG[strategy_id][1] else "MODE_FILTER")
    # Registered XAU-R research extensions require explicit, not inferred, mode mappings.
    if re.fullmatch(r"XAU-R\d{3,6}", strategy_id) and isinstance(custom, dict):
        tags = custom.get("mode_tags", [])
        return (mode == "AUTO" or mode in tags, None if mode == "AUTO" or mode in tags else "MODE_FILTER")
    return False, "STRATEGY_NOT_IN_CATALOG"


def check_evidence(entry: dict[str, Any], asof: datetime, snap_id: str, instrument: str) -> list[str]:
    r: list[str] = []
    if not isinstance(entry, dict) or not entry.get("evidence_id"):
        return ["EVIDENCE_ID_MISSING"]
    if not safe_time(entry.get("available_at"), asof):
        r.append("EVIDENCE_FUTURE_OR_TIME_UNKNOWN")
    if entry.get("snapshot_id") not in (None, snap_id):
        r.append("EVIDENCE_SNAPSHOT_MISMATCH")
    if entry.get("instrument_id") not in (None, instrument):
        r.append("EVIDENCE_INSTRUMENT_MISMATCH")
    if entry.get("requires_closed_bar") is True and entry.get("bar_state") != "CLOSED":
        r.append("EVIDENCE_OPEN_BAR")
    if entry.get("evidence_status") not in {"VERIFIED", "PARTIAL"}:
        r.append("EVIDENCE_UNVERIFIED")
    src = entry.get("source", "UNKNOWN")
    if src == "UNKNOWN":
        r.append("EVIDENCE_SOURCE_UNKNOWN")
    if src not in SOURCE_ALLOWED:
        r.append("EVIDENCE_SOURCE_UNRECOGNIZED")
    if src == "TRADINGVIEW_SUPPLEMENTAL":
        if entry.get("primary_field_missing") is not True:
            r.append("TV_NOT_REQUIRED_FOR_GAP")
        if entry.get("category") in TRADINGVIEW_DENIED_CATEGORIES:
            r.append("TV_BROKER_FIELD_FORBIDDEN")
    return r


def evaluate_setup(setup: dict[str, Any], asof: datetime, snap_id: str, instrument: str, mode: str,
                   profiles: dict[str, Any], custom: dict[str, Any] | None) -> dict[str, Any]:
    s = copy.deepcopy(setup)
    reasons: list[str] = []
    sid = str(s.get("strategy_id", ""))
    allowed, why = mode_allowed(sid, mode, profiles, custom)
    if not allowed and why:
        reasons.append(why)
    if s.get("direction") not in {"LONG", "SHORT"}:
        reasons.append("DIRECTION_NOT_ESTABLISHED")
    if not s.get("setup_id") or not s.get("horizon_id"):
        reasons.append("SETUP_ID_OR_HORIZON_MISSING")
    if s.get("instrument_id") != instrument:
        reasons.append("SETUP_INSTRUMENT_MISMATCH")
    if s.get("snapshot_id") != snap_id:
        reasons.append("SETUP_SNAPSHOT_MISMATCH")
    if not safe_time(s.get("available_at"), asof):
        reasons.append("SETUP_FUTURE_OR_TIME_UNKNOWN")
    stage = s.get("stage", "CANDIDATE")
    if stage in TERMINAL_STAGES:
        reasons.append("SETUP_TERMINAL_STATE")
    elif stage not in STAGES:
        reasons.append("SETUP_STAGE_INVALID")
    if "expires_at" in s and s["expires_at"] is not None:
        try:
            if utc(s["expires_at"]) <= asof:
                reasons.append("SETUP_EXPIRED")
        except ValueError:
            reasons.append("EXPIRY_TIME_INVALID")
    core = s.get("core_evidence", {})
    if not isinstance(core, dict):
        core = {}
    event_ids = []
    for key in CORE:
        e = core.get(key)
        if not isinstance(e, dict):
            reasons.append("CORE_MISSING:" + key)
        else:
            event_ids.append(e.get("evidence_id"))
            reasons.extend(check_evidence(e, asof, snap_id, instrument))
    if len(event_ids) != len(set(event_ids)):
        reasons.append("CORE_DUPLICATE_EVIDENCE")
    if not isinstance(s.get("next_expected_event"), dict) or not s["next_expected_event"].get("criterion") or not s["next_expected_event"].get("timeframe"):
        reasons.append("NEXT_EVENT_NOT_DEFINED")
    if not isinstance(s.get("invalidation"), dict) or not s["invalidation"].get("rule") or not s["invalidation"].get("timeframe"):
        reasons.append("INVALIDATION_NOT_DEFINED")
    if not isinstance(core.get("development_path"), dict):
        reasons.append("PATH_MISSING")
    if s.get("invalidation_observed") is True:
        reasons.append("SETUP_INVALIDATED")
    # Stage CONFIRMED requires independently timestamped trigger/confirmation evidence.
    if stage == "CONFIRMED":
        if s.get("trigger_confirmed") is not True:
            reasons.append("CONFIRMATION_TRIGGER_MISSING")
        con = s.get("confirmation_evidence")
        if not isinstance(con, dict):
            reasons.append("CONFIRMATION_EVIDENCE_MISSING")
        else:
            reasons.extend(check_evidence(con, asof, snap_id, instrument))
    if s.get("trap_risk") == "EXTREME":
        # Do not censor valid information, but block downstream execution.
        s["execution_trap_blocker"] = True
    hard_reasons = unique(reasons)
    stage_rank = {"CANDIDATE": 0, "OBSERVE": 0, "EARLY_SETUP": 1, "SETUP_FORMING": 2,
                  "QUALIFIED": 3, "ARMED": 4, "TRIGGERED": 5, "CONFIRMED": 6}.get(stage, -1)
    analytic_eligible = not hard_reasons and stage_rank >= 1
    # Higher rank only maturity / stated evidence quality; NO fictional numeric edge/probability.
    q_rank = {"VERIFIED": 2, "PARTIAL": 1}.get(s.get("evidence_status", "UNKNOWN"), 0)
    return {"setup_id": s.get("setup_id"), "strategy_id": sid, "version": s.get("version"),
            "family": s.get("family"), "horizon_id": s.get("horizon_id"), "market_scope": s.get("horizon_id"),
            "direction": s.get("direction"), "stage": stage, "stage_rank": stage_rank,
            "quality_rank": q_rank, "analytical_eligible": analytic_eligible, "reason_codes": hard_reasons,
            "source_evidence_ids": sorted(str(e) for e in event_ids if e),
            "underlying_event_id": s.get("underlying_event_id"), "poi_id": s.get("poi_id"),
            "invalidation_rule_id": (s.get("invalidation") or {}).get("rule_id") if isinstance(s.get("invalidation"), dict) else None,
            "spec_hash": s.get("spec_hash"), "trigger_confirmed": s.get("trigger_confirmed") is True,
            "trap_risk": s.get("trap_risk", "UNKNOWN"), "execution_trap_blocker": s.get("execution_trap_blocker", False),
            "conflict_type": "NONE", "duplicate_group_id": None, "primary_in_group": False}


def merge_duplicate_groups(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for c in candidates:
        if not c["analytical_eligible"]:
            continue
        if c["underlying_event_id"]:
            key = (c["horizon_id"], c["direction"], "EVENT", c["underlying_event_id"])
        elif c["poi_id"] and c["invalidation_rule_id"]:
            key = (c["horizon_id"], c["direction"], "POI_RULE", c["poi_id"], c["invalidation_rule_id"])
        else:
            key = (c["horizon_id"], c["direction"], "SETUP", c["setup_id"])
        groups.setdefault(key, []).append(c)
    result = []
    for key, members in groups.items():
        group_id = sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:16]
        top_score = max((c["stage_rank"], c["quality_rank"]) for c in members)
        leaders = [c for c in members if (c["stage_rank"], c["quality_rank"]) == top_score]
        for c in members:
            c["duplicate_group_id"] = group_id
            c["primary_in_group"] = (len(leaders) == 1 and leaders[0] is c)
            if len(leaders) > 1:
                c["reason_codes"] = unique(c["reason_codes"] + ["DUPLICATE_GROUP_TIE"])
        result.append({"group_id": group_id, "setup_ids": sorted(str(c["setup_id"]) for c in members),
                       "primary_setup_id": leaders[0]["setup_id"] if len(leaders) == 1 else None,
                       "horizon_id": key[0], "direction": key[1], "tie": len(leaders) > 1})
    return sorted(result, key=lambda x: (x["horizon_id"], str(x["group_id"])))


def detect_conflicts(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    byscope: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for c in candidates:
        if c["analytical_eligible"]:
            byscope.setdefault(str(c["market_scope"]), {"LONG": [], "SHORT": []})[c["direction"]].append(c)
    conflicts = []
    for scope, dirs in byscope.items():
        if dirs["LONG"] and dirs["SHORT"]:
            affected = sorted(str(c["setup_id"]) for x in dirs.values() for c in x)
            conflicts.append({"market_scope": scope, "type": "CRITICAL", "setup_ids": affected})
            for side in ("LONG", "SHORT"):
                for c in dirs[side]:
                    c["conflict_type"] = "CRITICAL"
                    c["reason_codes"] = unique(c["reason_codes"] + ["OPPOSING_SAME_HORIZON"])
    return sorted(conflicts, key=lambda x: x["market_scope"])


def best(candidates: list[dict[str, Any]], stage_set: set[str], scope: str | None = None) -> tuple[str | None, str | None]:
    conflicted_horizons = {c["horizon_id"] for c in candidates if c["conflict_type"] == "CRITICAL"}
    pool = [c for c in candidates if c["analytical_eligible"] and c["stage"] in stage_set
            and c["primary_in_group"] and c["conflict_type"] != "CRITICAL"
            and c["horizon_id"] not in conflicted_horizons and (scope is None or c["horizon_id"] == scope)]
    if not pool:
        return None, "NO_UNCONFLICTED_CANDIDATE"
    val = max((c["stage_rank"], c["quality_rank"]) for c in pool)
    leaders = [c for c in pool if (c["stage_rank"], c["quality_rank"]) == val]
    if len(leaders) != 1:
        return None, "TOP_RANK_TIE"
    return leaders[0]["setup_id"], None


def verify_registry(c: dict[str, Any], reg: dict[str, Any] | None, asof: datetime, cfg: dict[str, Any]) -> list[str]:
    why: list[str] = []
    if not isinstance(reg, dict):
        return ["NO_VERIFIED_M08_REGISTRY_ENTRY"]
    if reg.get("module_id") != "M08" or reg.get("schema_version") != SCHEMA:
        why.append("REGISTRY_CONTRACT_MISMATCH")
    if reg.get("run_status") != "COMPLETED":
        why.append("M08_NOT_COMPLETED")
    if reg.get("source_policy") != POLICY:
        why.append("M08_SOURCE_POLICY_MISMATCH")
    if reg.get("strategy_id") != c["strategy_id"] or reg.get("version") != c["version"]:
        why.append("REGISTRY_SPEC_REFERENCE_MISMATCH")
    if not c["spec_hash"] or reg.get("spec_hash") != c["spec_hash"]:
        why.append("REGISTRY_SPEC_HASH_MISMATCH")
    if reg.get("spec_status") != "FROZEN":
        why.append("REGISTRY_SPEC_NOT_FROZEN")
    if not isinstance(reg.get("registry_revision"), int) or reg["registry_revision"] < 1:
        why.append("REGISTRY_REVISION_INVALID")
    if reg.get("registry_integrity") != "PASS":
        why.append("REGISTRY_INTEGRITY_NOT_PASS")
    if reg.get("strategy_status") not in LIVE_STATUSES:
        why.append("STRATEGY_NOT_LIVE_APPROVED")
    if reg.get("edge_health") not in STABLE_HEALTH or reg.get("portfolio_group") not in {"CORE", "SPECIALIST"}:
        why.append("EDGE_OR_PORTFOLIO_NOT_APPROVED")
    if reg.get("m09_live_pool_candidate") is not True:
        why.append("M08_NOT_LIVE_CANDIDATE")
    if not isinstance(reg.get("evidence_gate"), dict) or reg["evidence_gate"].get("status") != "PASS":
        why.append("M08_VALIDATION_GATE_NOT_PASS")
    max_age = cfg.get("registry_max_age_seconds")
    if max_age is None or not isinstance(max_age, (int, float)) or max_age <= 0:
        why.append("REGISTRY_FRESHNESS_POLICY_UNDEFINED")
    else:
        try:
            ts = utc(reg.get("as_of"))
            if ts > asof or (asof - ts).total_seconds() > max_age:
                why.append("REGISTRY_STALE_OR_FUTURE")
        except ValueError:
            why.append("REGISTRY_TIME_UNKNOWN")
    return unique(why)


def strategy_environment_gate(c: dict[str, Any], spec: dict[str, Any] | None,
                              market: dict[str, Any], context: dict[str, Any]) -> list[str]:
    """Explicit strategy/regime/session constraints; unknown never treated as favorable."""
    reasons = []
    if not isinstance(spec, dict):
        return ["M07_STRATEGY_SPEC_UNAVAILABLE"]
    if spec.get("strategy_id") != c["strategy_id"] or spec.get("version") != c["version"]:
        reasons.append("M07_STRATEGY_REFERENCE_MISMATCH")
    if spec.get("spec_hash") != c["spec_hash"]:
        reasons.append("M07_STRATEGY_HASH_MISMATCH")
    if spec.get("spec_status") != "FROZEN":
        reasons.append("M07_STRATEGY_NOT_FROZEN")
    regime = market.get("structure_regime")
    required = spec.get("required_regimes", [])
    forbidden = spec.get("forbidden_regimes", [])
    if required and regime not in required:
        reasons.append("REQUIRED_REGIME_NOT_MET")
    if regime in forbidden:
        reasons.append("FORBIDDEN_REGIME")
    vol = market.get("volatility_level")
    if spec.get("forbidden_volatility_levels") and vol in spec["forbidden_volatility_levels"]:
        reasons.append("VOLATILITY_FORBIDDEN")
    if spec.get("required_volatility_levels") and vol not in spec["required_volatility_levels"]:
        reasons.append("VOLATILITY_NOT_QUALIFIED")
    allowed_sessions = spec.get("allowed_sessions", [])
    if allowed_sessions and context.get("session") not in allowed_sessions:
        reasons.append("SESSION_NOT_ALLOWED_OR_UNKNOWN")
    if spec.get("require_economic_calendar") is True and context.get("calendar_status") != "VERIFIED":
        reasons.append("REQUIRED_ECONOMIC_CALENDAR_NOT_VERIFIED")
    if context.get("event_risk") in {"EXTREME"}:
        reasons.append("EXTREME_EVENT_RISK")
    if context.get("trap_risk") == "EXTREME":
        reasons.append("EXTREME_TRAP_RISK")
    return reasons


def portfolio_data_gate(portfolio: Any, asof: datetime, max_age: Any) -> list[str]:
    if not isinstance(portfolio, dict):
        return ["MT5_PORTFOLIO_SNAPSHOT_MISSING"]
    errors=[]
    if portfolio.get("source") != "MT5_PRIMARY" or portfolio.get("verified") is not True:
        errors.append("MT5_PORTFOLIO_NOT_VERIFIED")
    if not isinstance(portfolio.get("positions"), list) or not isinstance(portfolio.get("pending_orders"), list):
        errors.append("MT5_POSITIONS_PENDING_UNAVAILABLE")
    if not isinstance(max_age, (int, float)) or max_age <= 0:
        errors.append("PORTFOLIO_FRESHNESS_POLICY_MISSING")
    else:
        try:
            recorded = utc(portfolio.get("as_of"))
            if recorded > asof or (asof-recorded).total_seconds() > max_age:
                errors.append("MT5_PORTFOLIO_SNAPSHOT_STALE")
        except ValueError:
            errors.append("MT5_PORTFOLIO_TIME_UNKNOWN")
    return errors


def run(payload: dict[str, Any]) -> dict[str, Any]:
    """Read-only routing. Always emits execution_permission=BLOCKED; downstream may re-evaluate."""
    if not isinstance(payload, dict):
        raise ValueError("PAYLOAD_NOT_OBJECT")
    mode = payload.get("mode", "AUTO")
    if mode not in MODES:
        raise ValueError("MODE_INVALID")
    asof = utc(payload.get("as_of"))
    snap = payload.get("data_snapshot") or {}
    market = payload.get("market_state") or {}
    runtime = payload.get("runtime") or {}
    cfg = payload.get("config") or {}
    profiles = payload.get("mode_profiles") or {}
    acc = payload.get("account") or {}
    raw = payload.get("setups", [])
    if not isinstance(raw, list):
        raise ValueError("SETUPS_NOT_LIST")
    if not isinstance(payload.get("registry_snapshots", []), list):
        raise ValueError("REGISTRY_NOT_LIST")
    reg_entries = payload.get("registry_snapshots", [])
    specs_by_id = payload.get("strategy_specs", {})
    if not isinstance(specs_by_id, dict):
        raise ValueError("STRATEGY_SPECS_NOT_OBJECT")
    context = payload.get("context") or {}
    reg_by_id: dict[tuple[str, str], dict[str, Any]] = {}
    dup_regs: set[tuple[str, str]] = set()
    for reg in reg_entries:
        if not isinstance(reg, dict):
            continue
        key = (reg.get("strategy_id"), reg.get("version"))
        if key in reg_by_id:
            dup_regs.add(key)
        reg_by_id[key] = reg
    preflight: list[str] = []
    if payload.get("schema_version") != SCHEMA:
        preflight.append("SCHEMA_VERSION_MISMATCH")
    if not snap.get("snapshot_id") or not snap.get("instrument_id"):
        preflight.append("M01_SNAPSHOT_REQUIRED")
    if snap.get("data_source_policy") != POLICY:
        preflight.append("SOURCE_POLICY_MISMATCH")
    if snap.get("visual_capture_enabled") is not False or contains_unsafe_key(payload):
        preflight.append("SCREENSHOT_OR_ORDER_API_FORBIDDEN")
    if snap.get("analysis_gate", {}).get("status") not in {"PASS", "PASS_WITH_LIMITATIONS"}:
        preflight.append("M01_ANALYSIS_GATE_NOT_PASS")
    if snap.get("as_of") != payload.get("as_of") or market.get("as_of") != payload.get("as_of") or market.get("snapshot_id") != snap.get("snapshot_id"):
        preflight.append("SNAPSHOT_TIME_ALIGNMENT_FAILED")
    if market.get("instrument_id") not in (None, snap.get("instrument_id")):
        preflight.append("M02_INSTRUMENT_MISMATCH")
    if market.get("status") not in {"PASS", "PASS_WITH_LIMITATIONS"}:
        preflight.append("M02_STATUS_NOT_PASS")
    if acc.get("account_type") not in (None, "ZERO_SPREAD"):
        preflight.append("ACCOUNT_PROFILE_UNEXPECTED")
    if not raw:
        preflight.append("NO_MARKET_EVIDENCE")
    mvp_missing = mode == "MVP" and not (profiles.get("MVP", {}).get("approved_mapping") is True
                                                   and isinstance(profiles.get("MVP", {}).get("strategy_ids"), list)
                                                   and profiles["MVP"]["strategy_ids"])
    if mvp_missing:
        preflight.append("MVP_STRATEGY_DEFINITION_MISSING")
    # Never assert a usable market from a failed M01/M02 preflight.
    can_analyze = not any(x in preflight for x in ("SCHEMA_VERSION_MISMATCH", "M01_SNAPSHOT_REQUIRED", "SOURCE_POLICY_MISMATCH",
                      "SCREENSHOT_OR_ORDER_API_FORBIDDEN", "M01_ANALYSIS_GATE_NOT_PASS", "SNAPSHOT_TIME_ALIGNMENT_FAILED",
                      "M02_INSTRUMENT_MISMATCH", "M02_STATUS_NOT_PASS"))
    evaluated: list[dict[str, Any]] = []
    if can_analyze and not mvp_missing:
        ids = set()
        for setup in raw:
            if not isinstance(setup, dict):
                preflight.append("SETUP_RECORD_NOT_OBJECT")
                continue
            sid = setup.get("setup_id")
            if sid in ids:
                preflight.append("DUPLICATE_SETUP_ID")
            ids.add(sid)
            custom = payload.get("custom_strategy_profiles", {}).get(setup.get("strategy_id"))
            evaluated.append(evaluate_setup(setup, asof, snap["snapshot_id"], snap["instrument_id"], mode, profiles, custom))
        if "DUPLICATE_SETUP_ID" in preflight:
            for c in evaluated:
                c["analytical_eligible"] = False
                c["reason_codes"] = unique(c["reason_codes"] + ["DUPLICATE_SETUP_ID"])
    # Do not advertise stopped/quarantined/retired strategies under the same version.
    for c in evaluated:
        r = reg_by_id.get((c["strategy_id"], c["version"]))
        if isinstance(r, dict) and r.get("strategy_status") in BLOCKED_STATUSES:
            c["analytical_eligible"] = False
            c["reason_codes"] = unique(c["reason_codes"] + ["STRATEGY_PAUSED_QUARANTINED_RETIRED"])
    groups = merge_duplicate_groups(evaluated)
    conflicts = detect_conflicts(evaluated)
    early, early_reason = best(evaluated, {"EARLY_SETUP", "SETUP_FORMING"})
    conditional, conditional_reason = best(evaluated, {"QUALIFIED", "ARMED", "TRIGGERED"})
    confirmed, confirmed_reason = best(evaluated, {"CONFIRMED"})
    execution_common: list[str] = []
    env = payload.get("execution_environment", "ANALYSIS_ONLY")
    if env not in {"ANALYSIS_ONLY", "PAPER", "DEMO", "LIVE"}:
        execution_common.append("EXECUTION_ENVIRONMENT_UNKNOWN")
    if env == "ANALYSIS_ONLY":
        execution_common.append("ANALYSIS_ONLY")
    if runtime.get("status") != "HEALTHY":
        execution_common.append("M16_NOT_HEALTHY")
    if snap.get("execution_gate", {}).get("status") != "PASS":
        execution_common.append("M01_EXECUTION_GATE_NOT_PASS")
    quote = snap.get("quote", {})
    if not isinstance(quote, dict) or quote.get("source") != "MT5_PRIMARY" or quote.get("verified") is not True:
        execution_common.append("MT5_EXECUTION_QUOTE_NOT_VERIFIED")
    elif not isinstance(quote.get("bid"), (int,float)) or not isinstance(quote.get("ask"),(int,float)) or quote["bid"] > quote["ask"] or quote["bid"] <= 0:
        execution_common.append("MT5_QUOTE_INVALID")
    if snap.get("source_health") not in ("PRIMARY_OK", "MT5_OK"):
        execution_common.append("MT5_PRIMARY_HEALTH_UNKNOWN")
    if not isinstance(cfg.get("execution_policy_version"), str) or not cfg["execution_policy_version"]:
        execution_common.append("EXECUTION_POLICY_MISSING")
    if cfg.get("event_policy_requires_calendar") is True and context.get("calendar_status") != "VERIFIED":
        execution_common.append("EVENT_CALENDAR_NOT_VERIFIED")
    # For Zero account, never infer costs=0. Require broker verification, no fixed spread threshold invented.
    if acc.get("account_type") == "ZERO_SPREAD" and acc.get("costs_verified_from_mt5") is not True:
        execution_common.append("ZERO_ACCOUNT_COSTS_NOT_VERIFIED")
    if env == "LIVE":
        # M14 exclusively authenticates authorization; do not accept client-supplied booleans as proof.
        pass
    if env in {"PAPER", "DEMO"} and payload.get("demo_research_enabled") is not True:
        execution_common.append("DEMO_RESEARCH_DISABLED")
    execution_common.extend(portfolio_data_gate(payload.get("portfolio_snapshot"), asof,
                                                  cfg.get("portfolio_max_age_seconds")))
    execution_common.extend(x for x in preflight if x != "NO_MARKET_EVIDENCE")
    execution_pool = []
    for c in evaluated:
        reg_key = (c["strategy_id"], c["version"])
        reg = reg_by_id.get(reg_key)
        r = verify_registry(c, reg, asof, cfg)
        if reg_key in dup_regs:
            r.append("DUPLICATE_REGISTRY_VERSION")
        if env in {"PAPER", "DEMO"} and isinstance(reg, dict):
            # DEMO is separate from live: still requires known frozen spec and explicit policy.
            r = [x for x in r if x not in {"STRATEGY_NOT_LIVE_APPROVED", "M08_NOT_LIVE_CANDIDATE", "EDGE_OR_PORTFOLIO_NOT_APPROVED"}]
            if reg.get("strategy_status") not in LIVE_STATUSES | {"FORWARD_TEST"}:
                r.append("DEMO_STRATEGY_STATUS_NOT_ALLOWED")
            if reg.get("strategy_status") == "FORWARD_TEST" and reg.get("evidence_gate", {}).get("status") != "PASS":
                # An M06 forward pilot may be in progress; still no real order permission from M09.
                r = [x for x in r if x != "M08_VALIDATION_GATE_NOT_PASS"]
        r.extend(strategy_environment_gate(c, specs_by_id.get(c["strategy_id"]), market, context))
        if not c["analytical_eligible"]:
            r.append("ANALYTICAL_SETUP_INVALID")
        if not c["primary_in_group"]:
            r.append("DUPLICATE_SETUP_NOT_PRIMARY")
        if c["conflict_type"] == "CRITICAL":
            r.append("CRITICAL_HORIZON_CONFLICT")
        if c["stage"] != "CONFIRMED" or not c["trigger_confirmed"]:
            r.append("SETUP_NOT_CONFIRMED")
        if c["execution_trap_blocker"] or c["trap_risk"] in {"HIGH", "EXTREME"}:
            r.append("TRAP_RISK_EXECUTION_BLOCK")
        why = unique(execution_common + r)
        execution_pool.append({"setup_id": c["setup_id"], "strategy_id": c["strategy_id"],
                               "version": c["version"], "preliminary_eligible_for_downstream": not bool(why),
                               "reason_codes": why, "execution_permission": "BLOCKED",
                               "live_execution_allowed": False, "submitted_order_id": None})
    elig = [c for c in execution_pool if c["preliminary_eligible_for_downstream"]]
    if not any(c["analytical_eligible"] for c in evaluated):
        astate = "NO_VALID_SETUP"
    elif confirmed is not None:
        astate = "CONFIRMED_SIGNAL"
    elif conditional is not None:
        astate = "CONDITIONAL_SETUP"
    elif early is not None:
        astate = "EARLY_SETUP"
    else:
        astate = "OBSERVING"
    if elig:
        estate = "EXECUTION_CANDIDATE"
    elif any(x["analytical_eligible"] and x["stage"] == "CONFIRMED" for x in evaluated):
        estate = "BLOCKED"
    elif any(x["analytical_eligible"] for x in evaluated):
        estate = "WAITING_FOR_SETUP"
    else:
        estate = "NO_ELIGIBLE_STRATEGY"
    out = {"module_id": "M09", "module_version": "1.0.0-CANDIDATE", "schema_version": SCHEMA,
           "analysis_id": payload.get("analysis_id"), "as_of": payload.get("as_of"), "config_version": payload.get("config_version"),
           "strategy_version": None, "mode": mode, "mode_status": "NOT_CONFIGURED" if mvp_missing else "CONFIGURED",
           "run_status": "COMPLETED", "status": "PENDING" if preflight or not evaluated else "PASS_WITH_LIMITATIONS",
           "data_source_policy": POLICY, "screenshot_capture_enabled": False,
           "analysis_router_state": astate, "execution_router_state": estate, "analysis_pool": evaluated,
           "execution_pool": execution_pool, "duplicate_groups": groups, "horizon_conflicts": conflicts,
           "top_early_setup_id": early, "top_conditional_setup_id": conditional,
           "top_confirmed_setup_id": confirmed, "top_reasons": {"early": early_reason, "conditional": conditional_reason,
                                                                  "confirmed": confirmed_reason},
           "current_champion_strategy": None, "deployed_champion_version": None,
           "missing_inputs": [], "limitations": ["READ_ONLY_REFERENCE", "NO_BROKER_EXECUTION", "NO_AUTHORITATIVE_RISK_DECISION", "LIVE_AUTHORIZATION_IS_M14_ONLY", "M08_RECORDS_REQUIRE_TRUSTED_ADAPTER"],
           "reason_codes": unique(preflight), "execution_blockers": unique(execution_common),
           "execution_permission": "BLOCKED", "execution_eligible": False, "live_execution_allowed": False,
           "submitted_order_id": None, "order_actions": [], "registry_write": False,
           "probabilities": None, "probability_reason": "OWNED_BY_M05P_NOT_CALCULATED"}
    return out


def main() -> None:
    import argparse
    p = argparse.ArgumentParser(description="M09 offline, read-only router")
    p.add_argument("--input", required=True, help="Local JSON fixture. No network/MT5 connection.")
    p.add_argument("--output", help="Write local JSON result instead of stdout")
    args = p.parse_args()
    obj = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = json.dumps(run(obj), ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(result + "\n", encoding="utf-8")
    else:
        print(result)


if __name__ == "__main__":
    main()
