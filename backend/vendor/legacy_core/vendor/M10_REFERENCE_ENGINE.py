"""MasterQUO M10 v1.0.0 candidate: read-only point-in-time setup lifecycle.

No screenshot/OCR, MT5 authoritative price, TradingView supplemental only.
Not an execution adapter, does not place orders or claim broker fills.
Standard library only. All input JSON is untrusted; broker fills are never
accepted outside explicit offline SIMULATION test mode.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import math
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

VERSION = "1.0.0-CANDIDATE"
POLICY = "MT5_PRIMARY_TV_SUPPLEMENTAL_NO_SCREENSHOTS"
STATES = ("OBSERVE", "CANDIDATE", "EARLY_SETUP", "SETUP_FORMING", "QUALIFIED", "ARMED", "TRIGGERED", "CONFIRMED", "ENTERED", "MANAGED", "EXITED", "REVIEWED", "INVALIDATED", "CANCELLED", "EXPIRED", "MISSED_ENTRY")
TERMINAL = {"REVIEWED", "INVALIDATED", "CANCELLED", "EXPIRED", "MISSED_ENTRY"}
CORE = ("structural_advantage", "meaningful_location", "liquidity_context", "development_path", "known_invalidation")
VALID_SOURCES = {"MT5_PRIMARY", "TRADINGVIEW_SUPPLEMENTAL"}
BROKER_EVENTS = {"FILL", "PARTIAL_FILL", "FULL_EXIT"}
STEP = {"CORE_READY": ("OBSERVE", "CANDIDATE"), "DEVELOPMENT": ("EARLY_SETUP",), "QUALIFY": ("EARLY_SETUP", "SETUP_FORMING"), "ARM": ("QUALIFIED",), "TRIGGER": ("ARMED",), "CONFIRM": ("TRIGGERED",), "FILL": ("CONFIRMED", "ENTERED", "MANAGED"), "PARTIAL_FILL": ("CONFIRMED", "ENTERED", "MANAGED"), "MANAGE": ("ENTERED",), "FULL_EXIT": ("ENTERED", "MANAGED"), "REVIEW": ("EXITED",), "REGRESS": ("SETUP_FORMING", "QUALIFIED", "ARMED", "TRIGGERED", "CONFIRMED")}
NEXT = {"CORE_READY": "EARLY_SETUP", "DEVELOPMENT": "SETUP_FORMING", "QUALIFY": "QUALIFIED", "ARM": "ARMED", "TRIGGER": "TRIGGERED", "CONFIRM": "CONFIRMED", "FILL": "ENTERED", "MANAGE": "MANAGED", "FULL_EXIT": "EXITED", "REVIEW": "REVIEWED", "REGRESS": "EARLY_SETUP"}


def ts(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("TIME_UNKNOWN")
    t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if t.tzinfo is None or t.utcoffset() is None:
        raise ValueError("TIMEZONE_REQUIRED")
    return t.astimezone(timezone.utc)


def finite_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def digest(x):
    return hashlib.sha256(json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def passed(x):
    return x in {"PASS", "VERIFIED"}


def core_ok(core, as_of, snapshot_id, instrument):
    reasons = []
    if not isinstance(core, dict):
        return False, ["CORE_MISSING"]
    for name in CORE:
        e = core.get(name)
        if not isinstance(e, dict) or not e.get("evidence_id"):
            reasons.append("CORE_MISSING_" + name.upper()); continue
        if e.get("instrument_id") != instrument or e.get("snapshot_id") != snapshot_id:
            reasons.append("CORE_CONTEXT_MISMATCH_" + name.upper())
        if e.get("evidence_status") != "VERIFIED":
            reasons.append("CORE_NOT_VERIFIED_" + name.upper())
        try:
            if ts(e.get("available_at")) > as_of: reasons.append("FUTURE_CORE_" + name.upper())
        except (ValueError, TypeError): reasons.append("CORE_TIME_INVALID_" + name.upper())
        if e.get("requires_closed_bar") and e.get("bar_state") != "CLOSED":
            reasons.append("CORE_BAR_NOT_CLOSED_" + name.upper())
        if e.get("source") not in VALID_SOURCES:
            reasons.append("CORE_SOURCE_FORBIDDEN_" + name.upper())
        if e.get("category") in ("BROKER_QUOTE", "EXECUTION_TRIGGER") and e.get("source") != "MT5_PRIMARY":
            reasons.append("BROKER_SOURCE_REQUIRED_" + name.upper())
    return not reasons, reasons


def validated_plan(p, direction):
    """Returns an illustrative plan. Does not claim fill, order or net reward."""
    p = copy.deepcopy(p or {})
    if not p:
        return {"plan_status": "ILLUSTRATIVE", "entry": None, "stop_loss": None, "targets": [], "rr_gross": None, "rr_net": None, "reason_codes": ["PLAN_NOT_SUPPLIED"]}
    reasons = []
    if p.get("price_source") != "MT5_PRIMARY": reasons.append("ENTRY_PRICE_MUST_BE_MT5")
    entry, sl = p.get("entry"), p.get("stop_loss")
    if not finite_num(entry) or not finite_num(sl) or entry <= 0 or sl <= 0:
        reasons.append("ENTRY_SL_UNAVAILABLE")
    elif direction == "LONG" and not sl < entry: reasons.append("LONG_STOP_GE_ENTRY")
    elif direction == "SHORT" and not sl > entry: reasons.append("SHORT_STOP_LE_ENTRY")
    elif direction not in ("LONG", "SHORT"): reasons.append("DIRECTION_UNAVAILABLE")
    targets = p.get("targets", [])
    if not isinstance(targets, list) or any(not finite_num(t) or t <= 0 for t in targets):
        reasons.append("TARGETS_INVALID"); targets = []
    if finite_num(entry) and direction in ("LONG", "SHORT"):
        if any((t <= entry if direction == "LONG" else t >= entry) for t in targets):
            reasons.append("TARGET_OPPOSITE_DIRECTION")
    parts = p.get("partial_weights")
    if parts is not None and (not isinstance(parts, list) or len(parts) != len(targets) or any(not finite_num(w) or w < 0 for w in parts) or abs(sum(parts)-1)>1e-9):
        reasons.append("PARTIAL_WEIGHTS_NOT_SUM_ONE")
    if not p.get("invalidation"):
        reasons.append("INVALIDATION_UNDEFINED")
    if not p.get("entry_trigger"):
        reasons.append("TRIGGER_RULE_UNDEFINED")
    if not p.get("management_rules"):
        reasons.append("MANAGEMENT_RULES_UNDEFINED")
    rr = None
    if not reasons and targets:
        rr = round(abs(targets[0]-entry)/abs(entry-sl), 8)
    return {"plan_status": "ILLUSTRATIVE" if reasons else "CONDITIONAL", "entry": entry if finite_num(entry) else None, "stop_loss": sl if finite_num(sl) else None, "targets": targets, "partial_weights": parts, "entry_trigger": p.get("entry_trigger"), "invalidation": p.get("invalidation"), "management_rules": p.get("management_rules"), "rr_gross": rr, "rr_net": None, "reason_codes": reasons + (["NET_RR_OWNED_BY_M11"] if not reasons else [])}


def init_record(p):
    setup = p.get("setup", {})
    sid = setup.get("setup_id")
    if not isinstance(sid, str) or not sid.strip(): raise ValueError("SETUP_ID_REQUIRED")
    if setup.get("direction") not in ("LONG", "SHORT"):
        raise ValueError("SETUP_DIRECTION_REQUIRED")
    if not setup.get("strategy_id") or not setup.get("version") or not setup.get("horizon_id"):
        raise ValueError("STRATEGY_VERSION_HORIZON_REQUIRED")
    asof = ts(p["as_of"])
    created = setup.get("created_at", p["as_of"])
    if ts(created) > asof: raise ValueError("CREATED_IN_FUTURE")
    c = p.get("config", {})
    ttl = c.get("ttl_closed_bars", 12)
    aging = c.get("aging_closed_bars", 6)
    if not isinstance(ttl, int) or isinstance(ttl, bool) or ttl < 1:
        raise ValueError("TTL_INVALID")
    if not isinstance(aging, int) or isinstance(aging, bool) or aging < 1 or aging > ttl:
        raise ValueError("AGING_INVALID")
    return {"setup_id": sid, "strategy_id": setup["strategy_id"], "strategy_version": setup["version"], "spec_hash": setup.get("spec_hash"), "instrument_id": setup.get("instrument_id", "XAUUSD"), "horizon_id": setup["horizon_id"], "setup_tf": setup.get("setup_tf", "M5"), "direction": setup["direction"], "created_at": created, "last_as_of": created, "snapshot_id": None, "state": "CANDIDATE", "order_state": "NONE", "execution_permission": "BLOCKED", "entry_status": "NOT_READY", "broker_fills": [], "closed_bars_elapsed": 0, "aging": False, "ttl_closed_bars": ttl, "aging_closed_bars": aging, "closed_bar_keys": [], "evidence_ids": [], "event_hashes": {}, "change_log": [], "reason_codes": [], "revision": 0, "plan": validated_plan(p.get("plan"), setup["direction"]), "next_expected_event": setup.get("next_expected_event"), "invalidation": setup.get("invalidation"), "probabilities": copy.deepcopy(setup.get("probabilities")), "trigger_event_id": None, "persistence_status": "SESSION_ONLY"}


def event_validate(e, record, asof, snapshot_id):
    if not isinstance(e, dict) or not isinstance(e.get("event_id"), str) or not e["event_id"]:
        return "EVENT_ID_REQUIRED"
    if e.get("source") not in VALID_SOURCES and not (e.get("type") in BROKER_EVENTS and e.get("source") == "MT5_BROKER_EVENT"):
        return "FORBIDDEN_EVENT_SOURCE"
    if e.get("instrument_id") != record["instrument_id"]: return "INSTRUMENT_MISMATCH"
    if e.get("snapshot_id") != snapshot_id: return "SNAPSHOT_MISMATCH"
    if e.get("evidence_status") != "VERIFIED": return "EVIDENCE_NOT_VERIFIED"
    if e.get("requires_closed_bar") and e.get("bar_state") != "CLOSED": return "BAR_NOT_CLOSED"
    try:
        t = ts(e.get("available_at"))
        if t > asof: return "FUTURE_EVIDENCE"
        if t < ts(record["created_at"]): return "PRE_CREATION_EVENT"
    except (ValueError, TypeError): return "EVENT_TIME_INVALID"
    if e.get("type") in ("TRIGGER", "CONFIRM", "CLOSED_BAR", "INVALIDATE", "TARGET_REACHED", "MISSED_ENTRY") and e.get("source") != "MT5_PRIMARY":
        return "MT5_PRICE_EVIDENCE_REQUIRED"
    return None


def step(rec, new, e, asof, reason=None):
    old = rec["state"]
    if old == new: return False
    rec["state"] = new
    rec["revision"] += 1
    rec["change_log"].append({"transition_id": f"{rec['setup_id']}:{rec['revision']}", "available_at": e.get("available_at", asof), "previous_state": old, "new_state": new, "event_id": e.get("event_id"), "evidence_id": e.get("evidence_id"), "reason": reason or e.get("type"), "source": e.get("source")})
    return True


def process(p, previous=None):
    """Point-in-time idempotent lifecycle reducer; no order submission ever."""
    if p.get("schema_version") != "2.0.0": raise ValueError("SCHEMA_VERSION_MISMATCH")
    if p.get("data_source_policy") != POLICY: raise ValueError("DATA_SOURCE_POLICY_MISMATCH")
    if p.get("screenshot_capture_enabled") is not False: raise ValueError("SCREENSHOTS_FORBIDDEN")
    asof = ts(p.get("as_of"))
    snap = p.get("data_snapshot", {})
    snapshot_id = snap.get("snapshot_id")
    if not snapshot_id: raise ValueError("SNAPSHOT_REQUIRED")
    setup = p.get("setup")
    if not isinstance(setup, dict): raise ValueError("SETUP_REQUIRED")
    rec = copy.deepcopy(previous) if previous is not None else init_record(p)
    if rec["setup_id"] != setup.get("setup_id") or rec["direction"] != setup.get("direction") or rec["strategy_id"] != setup.get("strategy_id") or rec["strategy_version"] != setup.get("version") or rec["horizon_id"] != setup.get("horizon_id") or rec["spec_hash"] != setup.get("spec_hash"):
        raise ValueError("IMMUTABLE_SETUP_IDENTITY_MISMATCH")
    if rec["instrument_id"] != setup.get("instrument_id", "XAUUSD"):
        raise ValueError("IMMUTABLE_INSTRUMENT_MISMATCH")
    if asof < ts(rec["last_as_of"]): raise ValueError("AS_OF_ROLLBACK")
    if snap.get("instrument_id") != rec["instrument_id"]: raise ValueError("DATA_INSTRUMENT_MISMATCH")
    if ts(snap.get("as_of")) != asof: raise ValueError("AS_OF_SNAPSHOT_MISMATCH")
    if snap.get("screenshot_capture_enabled") not in (None, False): raise ValueError("SCREENSHOTS_FORBIDDEN")
    if snap.get("data_source_policy") not in (None, POLICY): raise ValueError("DATA_SOURCE_POLICY_MISMATCH")
    reasons = []
    if snap.get("analysis_gate") not in ("PASS", "PASS_WITH_LIMITATIONS"):
        reasons.append("M01_ANALYSIS_GATE_NOT_PASS")
    if p.get("runtime", {}).get("status") not in (None, "HEALTHY"):
        reasons.append("M16_RUNTIME_NOT_HEALTHY")
    if p.get("router_result", {}).get("module_id") not in ("M09",):
        reasons.append("M09_RESULT_MISSING")
    else:
        matching = [x for x in p["router_result"].get("analysis_pool", []) if x.get("setup_id") == rec["setup_id"]]
        if not matching or not matching[0].get("analytical_eligible", False):
            reasons.append("M09_ANALYTICAL_CANDIDATE_NOT_ELIGIBLE")
        else:
            candidate = matching[0]
            for field, value in (("strategy_id", rec["strategy_id"]), ("version", rec["strategy_version"]), ("horizon_id", rec["horizon_id"]), ("spec_hash", rec["spec_hash"])):
                if field in candidate and candidate[field] != value:
                    reasons.append("M09_"+field.upper()+"_MISMATCH")
    core_valid, core_reasons = core_ok(setup.get("core_evidence"), asof, snapshot_id, rec["instrument_id"])
    if not core_valid: reasons.extend(core_reasons)
    events = p.get("events", [])
    if not isinstance(events, list): raise ValueError("EVENTS_NOT_LIST")
    seen_local = {}
    new_events = []
    rejected = []
    for e in events:
        eid = e.get("event_id") if isinstance(e, dict) else None
        if isinstance(eid, str) and eid:
            h = digest(e)
            if eid in seen_local and seen_local[eid] != h: raise ValueError("EVENT_ID_COLLISION_IN_BATCH")
            seen_local[eid] = h
            existing = rec["event_hashes"].get(eid)
            if existing is not None:
                if existing != h: raise ValueError("EVENT_ID_COLLISION_WITH_HISTORY")
                continue
        err = event_validate(e, rec, asof, snapshot_id)
        if err:
            rejected.append({"event_id": eid, "reason": err}); continue
        new_events.append(e)
    new_events.sort(key=lambda e: ts(e["available_at"]))  # Stable tie order: original stream order
    for e in new_events:
        name = e.get("type")
        eid = e["event_id"]
        rec["event_hashes"][eid] = digest(e)
        # Critical observation is processed before ordinary progression.
        if rec["state"] in TERMINAL:
            rejected.append({"event_id": eid, "reason": "TERMINAL_SETUP_NO_REACTIVATION"}); continue
        if name in ("INVALIDATE", "EXPIRE", "CANCEL", "MISSED_ENTRY", "TARGET_REACHED"):
            if rec["state"] in {"ENTERED", "MANAGED", "EXITED"}:
                rejected.append({"event_id": eid, "reason": "OPEN_POSITION_REQUIRES_M11_MANAGEMENT"}); continue
            new = {"INVALIDATE": "INVALIDATED", "EXPIRE": "EXPIRED", "CANCEL": "CANCELLED", "MISSED_ENTRY": "MISSED_ENTRY", "TARGET_REACHED": "EXPIRED"}[name]
            step(rec, new, e, p["as_of"], "TARGET_REACHED_BEFORE_ENTRY" if name == "TARGET_REACHED" else name)
            continue
        if name == "CLOSED_BAR":
            tf_minutes = {"M1": 1, "M5": 5, "M15": 15, "H1": 60, "H4": 240, "D1": 1440}
            if (e.get("source") != "MT5_PRIMARY" or e.get("bar_state") != "CLOSED" or
                e.get("timeframe") != rec["setup_tf"] or not e.get("bar_open_utc") or
                e.get("timeframe") not in tf_minutes or not e.get("close_confirmed_at")):
                rejected.append({"event_id": eid, "reason": "CLOSED_BAR_NOT_VALID"}); continue
            try:
                opened, confirmed = ts(e["bar_open_utc"]), ts(e["close_confirmed_at"])
                expected = (ts(e["bar_expected_close_utc"]) if e.get("timeframe") == "D1" and e.get("bar_expected_close_utc") else opened + timedelta(minutes=tf_minutes[e["timeframe"]]))
                if e.get("timeframe") == "D1" and not e.get("bar_expected_close_utc"):
                    rejected.append({"event_id": eid, "reason": "DAILY_BAR_CALENDAR_REQUIRED"}); continue
                if confirmed < expected or confirmed > ts(e["available_at"]):
                    rejected.append({"event_id": eid, "reason": "CANDLE_LIFECYCLE_INCONSISTENT"}); continue
            except (TypeError, ValueError):
                rejected.append({"event_id": eid, "reason": "CANDLE_LIFECYCLE_INCONSISTENT"}); continue
            key = e["timeframe"] + ":" + e["bar_open_utc"]
            if key not in rec["closed_bar_keys"] and ts(e["bar_open_utc"]) >= ts(rec["created_at"]):
                rec["closed_bar_keys"].append(key)
                rec["closed_bars_elapsed"] += 1
                rec["aging"] = rec["closed_bars_elapsed"] >= rec["aging_closed_bars"]
                if rec["closed_bars_elapsed"] >= rec["ttl_closed_bars"] and rec["state"] not in {"ENTERED", "MANAGED", "EXITED"}:
                    step(rec, "EXPIRED", e, p["as_of"], "TTL_CLOSED_BARS_ELAPSED")
            continue
        if name not in STEP:
            rejected.append({"event_id": eid, "reason": "UNKNOWN_EVENT_TYPE"}); continue
        if rec["state"] not in STEP[name]:
            rejected.append({"event_id": eid, "reason": "ILLEGAL_STATE_TRANSITION"}); continue
        if name == "CORE_READY" and (not core_valid or reasons):
            rejected.append({"event_id": eid, "reason": "CORE_OR_DATA_GATE_NOT_READY"}); continue
        if name in ("QUALIFY", "ARM") and (not e.get("conditions_met") or reasons):
            rejected.append({"event_id": eid, "reason": "CONDITIONS_OR_DATA_GATE_NOT_PASS"}); continue
        if name in ("TRIGGER", "CONFIRM"):
            if reasons or not core_valid:
                rejected.append({"event_id": eid, "reason": "REQUIRED_DATA_NOT_VALID"}); continue
            if e.get("source") != "MT5_PRIMARY" or not e.get("trigger_confirmed", False) and name == "TRIGGER":
                rejected.append({"event_id": eid, "reason": "PRIMARY_TRIGGER_UNCONFIRMED"}); continue
            required_confirmation = {"data", "trigger", "invalidation", "expiry", "conflict"}
            if name == "CONFIRM" and (not isinstance(e.get("confirmation_gates"), dict) or not required_confirmation.issubset(e["confirmation_gates"]) or not all(e["confirmation_gates"][x] == "PASS" for x in required_confirmation) or not e.get("distinct_confirmation", False) or e.get("ref_trigger_event_id") != rec.get("trigger_event_id")):
                rejected.append({"event_id": eid, "reason": "CONFIRMATION_GATES_NOT_PASS"}); continue
            if name == "TRIGGER":
                rec["trigger_event_id"] = eid
        if name in BROKER_EVENTS:
            # Only a dedicated trusted adapter can turn actual broker reports into authoritative fills.
            # SIMULATION intentionally creates simulated state, not a real fill.
            if p.get("reference_mode") != "SIMULATION":
                rejected.append({"event_id": eid, "reason": "TRUSTED_BROKER_RECONCILIATION_NOT_IMPLEMENTED"}); continue
            if e.get("source") != "MT5_BROKER_EVENT" or not e.get("broker_deal_id"):
                rejected.append({"event_id": eid, "reason": "BROKER_DEAL_ID_REQUIRED"}); continue
            if e["broker_deal_id"] in rec["broker_fills"]:
                rejected.append({"event_id": eid, "reason": "BROKER_DEAL_ID_DUPLICATE"}); continue
            if name == "PARTIAL_FILL":
                rec["order_state"] = "PARTIALLY_FILLED"
                rec["broker_fills"].append(e["broker_deal_id"])
                if rec["state"] == "CONFIRMED":
                    step(rec, "ENTERED", e, p["as_of"], "SIMULATED_PARTIAL_POSITION_OPEN")
                continue
            if name == "FILL":
                rec["order_state"] = "FILLED"; rec["broker_fills"].append(e["broker_deal_id"])
            elif name == "FULL_EXIT":
                if not e.get("position_fully_closed"):
                    rejected.append({"event_id": eid, "reason": "POSITION_NOT_FULLY_CLOSED"}); continue
                rec["broker_fills"].append(e["broker_deal_id"])
        if name == "REGRESS":
            target = e.get("target_state", "EARLY_SETUP")
            if target not in {"EARLY_SETUP", "SETUP_FORMING", "QUALIFIED", "ARMED"}:
                rejected.append({"event_id": eid, "reason": "REGRESS_TARGET_INVALID"}); continue
            step(rec, target, e, p["as_of"], "SOFT_EVIDENCE_WITHDRAWN")
        elif name == "FILL" and rec["state"] in {"ENTERED", "MANAGED"}:
            # Completion of an existing simulated partial position must never rewind the lifecycle.
            pass
        else:
            step(rec, NEXT[name], e, p["as_of"])
    rec["last_as_of"] = p["as_of"]
    rec["snapshot_id"] = snapshot_id
    if p.get("state_store_enabled"):
        rec["persistence_status"] = "LOCAL_SQLITE"
    reason_codes = sorted(set(reasons + (["PROVISIONAL_TTL_NOT_LIVE_VALIDATED"] if rec["ttl_closed_bars"] == 12 else []) + rec["plan"].get("reason_codes", [])))
    if rec["state"] in {"ARMED", "TRIGGERED", "CONFIRMED"} and core_valid:
        # Analytic confirmation is not execution permission. Only M11/M14 can lift this in production.
        rec["entry_status"] = "CONDITIONAL"
    else:
        rec["entry_status"] = "NOT_READY"
    blockers = ["M11_RISK_APPROVAL_NOT_PRESENT", "M14_EXECUTION_AUTHORIZATION_NOT_PRESENT", "BROKER_EXECUTION_ADAPTER_NOT_IMPLEMENTED"]
    if snap.get("execution_gate") != "PASS": blockers.append("M01_EXECUTION_DATA_NOT_READY")
    if p.get("runtime", {}).get("status") != "HEALTHY": blockers.append("M16_RUNTIME_NOT_HEALTHY")
    if p.get("router_result", {}).get("execution_permission") != "AUTHORIZED": blockers.append("M09_HAS_NO_EXECUTION_AUTHORITY")
    quote = snap.get("quote", {})
    usable_quote = (isinstance(quote, dict) and quote.get("source") == "MT5_PRIMARY" and quote.get("evidence_status") == "VERIFIED" and finite_num(quote.get("bid")) and finite_num(quote.get("ask")) and quote["bid"] > 0 and quote["ask"] >= quote["bid"])
    quote_policy = p.get("config", {}).get("max_quote_age_seconds")
    if not finite_num(quote_policy) or quote_policy <= 0:
        blockers.append("QUOTE_FRESHNESS_POLICY_MISSING")
        usable_quote = False
    if usable_quote:
        try:
            age = (asof - ts(quote.get("available_at"))).total_seconds()
            if age < 0 or age > quote_policy:
                usable_quote = False
        except (ValueError, TypeError): usable_quote = False
    if not usable_quote: blockers.append("MT5_QUOTE_UNVERIFIED_OR_UNAVAILABLE")
    else:
        max_distance = p.get("config", {}).get("max_entry_distance_abs")
        entry = rec["plan"].get("entry")
        if finite_num(max_distance) and max_distance >= 0 and finite_num(entry):
            price = quote["ask"] if rec["direction"] == "LONG" else quote["bid"]
            if abs(price - entry) > max_distance:
                blockers.append("ANTI_FOMO_WAIT_FOR_RETEST")
    if p.get("account", {}).get("account_type") == "ZERO_SPREAD" and not p.get("account", {}).get("costs_verified_from_mt5"):
        blockers.append("ZERO_ACCOUNT_COSTS_NOT_VERIFIED")
    if rec["state"] != "CONFIRMED": blockers.append("SETUP_NOT_CONFIRMED")
    reason_codes = sorted(set(reason_codes + ( ["WAIT_FOR_RETEST"] if "ANTI_FOMO_WAIT_FOR_RETEST" in blockers else [])))
    return {"module_id": "M10", "module_version": VERSION, "schema_version": "2.0.0", "analysis_id": p.get("analysis_id"), "as_of": p["as_of"], "data_source_policy": POLICY, "screenshot_capture_enabled": False, "setup": rec, "rejected_events": rejected, "reason_codes": reason_codes, "execution_blockers": sorted(set(blockers)), "status": "PASS_WITH_LIMITATIONS" if not reasons else "PENDING", "execution_permission": "BLOCKED", "execution_eligible": False, "live_execution_allowed": False, "submitted_order_id": None, "order_actions": [], "alert_emission": "NOT_SENT", "signal_dedupe_key": digest([rec["setup_id"], rec["strategy_version"], rec["state"]])[:24], "broker_execution": "SIMULATION_ONLY" if p.get("reference_mode") == "SIMULATION" else "NOT_IMPLEMENTED", "simulated_fills_only": p.get("reference_mode") == "SIMULATION", "actual_fills": None, "run_status": "COMPLETED"}


class SQLiteSetupStore:
    """Transactional local snapshot journal. No network and no broker credentials."""
    def __init__(self, path):
        self.db = sqlite3.connect(str(path), timeout=10, isolation_level=None)
        self.db.execute("PRAGMA busy_timeout=10000")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS setup_state(setup_id TEXT PRIMARY KEY, record_json TEXT NOT NULL, revision INTEGER NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, setup_id TEXT NOT NULL, revision INTEGER NOT NULL, state_hash TEXT NOT NULL, recorded_at TEXT NOT NULL)")
    def apply(self, payload):
        sid = payload.get("setup", {}).get("setup_id")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute("SELECT record_json FROM setup_state WHERE setup_id=?", (sid,)).fetchone()
            old = json.loads(row[0]) if row else None
            result = process({**payload, "state_store_enabled": True}, old)
            rec = result["setup"]
            new_json = json.dumps(rec, sort_keys=True, ensure_ascii=False)
            if row is None or json.loads(row[0]) != rec:
                self.db.execute("INSERT INTO setup_state(setup_id,record_json,revision) VALUES(?,?,?) ON CONFLICT(setup_id) DO UPDATE SET record_json=excluded.record_json,revision=excluded.revision", (sid, new_json, rec["revision"]))
                self.db.execute("INSERT INTO audit(setup_id,revision,state_hash,recorded_at) VALUES(?,?,?,?)", (sid, rec["revision"], digest(rec), payload["as_of"]))
            self.db.execute("COMMIT")
            return result
        except Exception:
            self.db.execute("ROLLBACK")
            raise
    def close(self): self.db.close()


def main():
    parser = argparse.ArgumentParser(description="M10 offline reference; never places trades")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--state-db", default=None)
    a = parser.parse_args()
    payload = json.loads(Path(a.input).read_text(encoding="utf-8"))
    if a.state_db:
        store = SQLiteSetupStore(a.state_db)
        try: result = store.apply(payload)
        finally: store.close()
    else: result = process(payload)
    Path(a.output).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"M10 state={result['setup']['state']} revision={result['setup']['revision']} execution=BLOCKED")


if __name__ == "__main__": main()
