"""Setup lifecycle (M10A rules) with SQLite persistence.

Implements the M10_AUTO_TRIGGER_CONFIRM v1.1.0 rules on the frozen M07 plan:
  EARLY_SETUP -> QUALIFIED -> ARMED -> TRIGGERED -> CONFIRMED
  terminal: INVALIDATED, EXPIRED, MISSED_ENTRY, ENTERED, CANCELLED
* only closed setup-timeframe bars that became available *after* the setup was detected count;
* invalidation is checked before advancement on every bar (also after CONFIRMED);
* at most one stage change per closed bar; CONFIRMED needs a later bar than TRIGGERED;
* every closed bar since the last evaluation is replayed in order (gap after reconnect is
  filled from terminal history, not skipped);
* TTL: `ttl_bars` evaluated bars before CONFIRMED; a CONFIRMED setup has a short entry window
  (`confirmed_window_bars`) after which it becomes MISSED_ENTRY.
Rules are taken verbatim from the frozen plan; the plan hash is stored and never changes.
"""
from __future__ import annotations

import hashlib
import json
import math

from ..db.database import Database, dumps
from ..timeutil import iso, parse_iso, utcnow

ORDER = ("EARLY_SETUP", "QUALIFIED", "ARMED", "TRIGGERED", "CONFIRMED")
ACTIVE = set(ORDER)
TERMINAL = {"INVALIDATED", "EXPIRED", "MISSED_ENTRY", "ENTERED", "CANCELLED"}
NEXT_RULE = {"EARLY_SETUP": "qualification", "QUALIFIED": "arming", "ARMED": "trigger", "TRIGGERED": "confirmation"}
STAGE_MAP = {"EARLY_SETUP": "EARLY", "QUALIFIED": "EARLY", "ARMED": "EARLY", "TRIGGERED": "EARLY",
             "CONFIRMED": "CONFIRMED", "INVALIDATED": "INVALIDATED", "EXPIRED": "EXPIRED", "MISSED_ENTRY": "EXPIRED",
             "ENTERED": "CONFIRMED", "CANCELLED": "EXPIRED"}
CONFIRMED_WINDOW_BARS = 2


def setup_id_for(plan: dict, account_key: str | None) -> str:
    base = json.dumps([account_key, plan["frozen_plan_hash"]], sort_keys=True)
    return "MQS-" + hashlib.sha256(base.encode()).hexdigest()[:20]


def _match(rule: dict, bar: dict) -> bool:
    x = {"close": bar["c"], "high": bar["h"], "low": bar["l"]}[rule["field"]]
    lv = float(rule["level"])
    if not (isinstance(x, (int, float)) and math.isfinite(x)):
        raise ValueError("BAR_PRICE_NOT_FINITE")
    return {">": x > lv, ">=": x >= lv, "<": x < lv, "<=": x <= lv}[rule["operator"]]


def validate_rules(plan: dict) -> str | None:
    rs = plan.get("lifecycle_rules") or {}
    tf = plan.get("setup_tf")
    long_ = plan.get("intended_direction") == "LONG"
    trend_ops = {">", ">="} if long_ else {"<", "<="}
    rev_ops = {"<", "<="} if long_ else {">", ">="}
    for name in ("qualification", "arming", "trigger", "confirmation"):
        r = rs.get(name)
        if not isinstance(r, dict) or r.get("timeframe") != tf or r.get("requires_closed_bar") is not True:
            return "INVALID_RULE_" + name.upper()
        if r.get("field") not in (("close",) if name == "confirmation" else ("close", "high", "low")):
            return "INVALID_RULE_FIELD_" + name.upper()
        if r.get("operator") not in trend_ops:
            return "RULE_DIRECTION_CONTRADICTS_STRATEGY_" + name.upper()
        if not isinstance(r.get("level"), (int, float)) or r["level"] <= 0:
            return "INVALID_RULE_LEVEL_" + name.upper()
    inv = (plan.get("invalidation") or {}).get("condition") or {}
    if (plan.get("invalidation") or {}).get("rule") != "CLOSED_BAR" or inv.get("operator") not in rev_ops or inv.get("field") != "close":
        return "INVALIDATION_RULE_UNVERIFIABLE"
    return None


class LifecycleStore:
    def __init__(self, db: Database):
        self.db = db

    def _row(self, setup_id: str) -> dict | None:
        r = self.db.one("SELECT * FROM setups WHERE setup_id=?", (setup_id,))
        if r:
            r["plan"] = json.loads(r.pop("plan_json"))
            r["change_log"] = json.loads(r.pop("change_log_json"))
        return r

    def get(self, setup_id: str) -> dict | None:
        return self._row(setup_id)

    def active(self, account_key: str | None, symbol: str) -> list[dict]:
        rows = self.db.query("SELECT setup_id FROM setups WHERE symbol=? AND IFNULL(account_key,'')=IFNULL(?, '') AND state IN (%s) ORDER BY created_at"
                             % ",".join("?" * len(ACTIVE)), (symbol, account_key, *ACTIVE))
        return [self._row(r["setup_id"]) for r in rows]

    def recent(self, limit: int = 30) -> list[dict]:
        rows = self.db.query("SELECT setup_id FROM setups ORDER BY created_at DESC LIMIT ?", (limit,))
        return [self._row(r["setup_id"]) for r in rows]

    def register(self, plan: dict, *, account_key: str | None, symbol: str, detected_at: str, last_closed_open: str | None,
                 ttl_bars: int, synthetic: bool) -> tuple[dict, bool]:
        """Create the setup for a frozen plan if unknown. Returns (record, created)."""
        sid = setup_id_for(plan, account_key)
        existing = self._row(sid)
        if existing:
            return existing, False
        err = validate_rules(plan)
        state = "EARLY_SETUP" if err is None else "CANCELLED"
        log = [{"at": detected_at, "event": "CORE_READY" if err is None else "REJECTED", "state": state,
                "reason": err or "M07_PLAN_FROZEN", "bar_open_utc": last_closed_open}]
        with self.db.tx() as c:
            c.execute("""INSERT OR IGNORE INTO setups(setup_id, created_at, symbol, account_key, synthetic, strategy_id, strategy_version, profile,
                         setup_tf, direction, plan_hash, plan_json, state, state_changed_at, last_evaluated_bar, bars_evaluated, ttl_bars,
                         change_log_json, terminal_reason) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (sid, detected_at, symbol, account_key, int(synthetic), plan["strategy_id"], plan["version"], plan.get("profile_name", ""),
                       plan["setup_tf"], plan["intended_direction"], plan["frozen_plan_hash"], dumps(plan), state, detected_at,
                       last_closed_open, 0, ttl_bars, dumps(log), err))
        return self._row(sid), True

    def _save(self, rec: dict) -> None:
        with self.db.tx() as c:
            c.execute("""UPDATE setups SET state=?, state_changed_at=?, last_evaluated_bar=?, bars_evaluated=?, change_log_json=?, terminal_reason=?
                         WHERE setup_id=?""", (rec["state"], rec["state_changed_at"], rec["last_evaluated_bar"], rec["bars_evaluated"],
                                               dumps(rec["change_log"][-200:]), rec.get("terminal_reason"), rec["setup_id"]))

    def terminate(self, setup_id: str, state: str, reason: str, at: str | None = None) -> dict | None:
        rec = self._row(setup_id)
        if not rec or rec["state"] in TERMINAL:
            return rec
        at = at or iso(utcnow())
        rec["change_log"].append({"at": at, "event": state, "state": state, "reason": reason})
        rec.update(state=state, state_changed_at=at, terminal_reason=reason)
        self._save(rec)
        return rec

    def evaluate(self, setup_id: str, closed_bars: list[dict]) -> tuple[dict, list[dict]]:
        """Replay all not-yet-evaluated closed bars of the setup TF. Returns (record, transitions)."""
        rec = self._row(setup_id)
        transitions: list[dict] = []
        if not rec or rec["state"] in TERMINAL:
            return rec, transitions
        plan = rec["plan"]
        detected = parse_iso(rec["created_at"])
        last = parse_iso(rec["last_evaluated_bar"]) if rec["last_evaluated_bar"] else None
        inv = plan["invalidation"]["condition"]
        rules = plan["lifecycle_rules"]
        changed = False
        for bar in closed_bars:
            opened = parse_iso(bar["open_utc"])
            if last is not None and opened <= last:
                continue
            avail = parse_iso(bar["available_at"]) if bar.get("available_at") else None
            if avail is None or avail <= detected:
                # information that existed when the setup was detected cannot advance it
                rec["last_evaluated_bar"] = bar["open_utc"]
                last = opened
                changed = True
                continue
            rec["bars_evaluated"] += 1
            rec["last_evaluated_bar"] = bar["open_utc"]
            last = opened
            changed = True
            state = rec["state"]
            event = None
            if _match(inv, bar):
                event, new_state, reason = "INVALIDATE", "INVALIDATED", f"CLOSE_{inv['operator']}_{inv['level']}"
            elif state == "CONFIRMED":
                conf_bars = sum(1 for x in rec["change_log"] if x.get("event") == "WINDOW_BAR")
                rec["change_log"].append({"at": bar["available_at"], "event": "WINDOW_BAR", "state": state, "bar_open_utc": bar["open_utc"]})
                if conf_bars + 1 >= CONFIRMED_WINDOW_BARS:
                    event, new_state, reason = "EXPIRE", "MISSED_ENTRY", "ENTRY_WINDOW_ELAPSED"
            else:
                rule_name = NEXT_RULE[state]
                if _match(rules[rule_name], bar):
                    new_state = ORDER[ORDER.index(state) + 1]
                    event, reason = rule_name.upper(), f"{rules[rule_name]['field'].upper()}_{rules[rule_name]['operator']}_{rules[rule_name]['level']}"
                elif rec["bars_evaluated"] >= rec["ttl_bars"]:
                    event, new_state, reason = "EXPIRE", "EXPIRED", f"TTL_{rec['ttl_bars']}_BARS"
            if event:
                tr = {"at": bar["available_at"], "event": event, "from": state, "state": new_state, "reason": reason,
                      "bar_open_utc": bar["open_utc"], "bar": {"o": bar["o"], "h": bar["h"], "l": bar["l"], "c": bar["c"]}}
                rec["change_log"].append(tr)
                rec["state"] = new_state
                rec["state_changed_at"] = bar["available_at"]
                if new_state in TERMINAL:
                    rec["terminal_reason"] = reason
                transitions.append(tr)
                if new_state in TERMINAL:
                    break
        if changed:
            self._save(rec)
        return rec, transitions


def public_setup(rec: dict | None) -> dict | None:
    if not rec:
        return None
    p = rec["plan"]
    return {"setup_id": rec["setup_id"], "created_at": rec["created_at"], "strategy_id": rec["strategy_id"],
            "strategy_version": rec["strategy_version"], "profile": rec["profile"], "setup_tf": rec["setup_tf"],
            "direction": rec["direction"], "state": rec["state"], "signal_stage": STAGE_MAP.get(rec["state"], "WATCH"),
            "state_changed_at": rec["state_changed_at"], "bars_evaluated": rec["bars_evaluated"], "ttl_bars": rec["ttl_bars"],
            "terminal_reason": rec.get("terminal_reason"), "plan_hash": rec["plan_hash"],
            "rules": p.get("lifecycle_rules"), "invalidation_level": p["invalidation"]["condition"]["level"],
            "location_evidence_id": p.get("location_evidence_id"), "liquidity_evidence_id": p.get("liquidity_evidence_id"),
            "structural_evidence_id": p.get("structural_evidence_id"), "fvg": p.get("source_fvg_geometry"),
            "synthetic": bool(rec.get("synthetic")), "change_log": rec["change_log"][-30:]}
