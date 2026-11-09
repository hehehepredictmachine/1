"""Typed records of the decision flow (PMW-ARC-1). Plain dicts (JSON-serialisable, stored as-is) checked field by field.

InstrumentSpec -> ObservationEvent -> MarketSnapshot -> FeatureSet -> MarketContext -> ModelForecast -> StrategyCandidate
-> DecisionRecord -> ExecutionIntent -> ExecutionOutcome.

Every record carries `contract` = "PMW-ARC-1/<Name>". `make()` refuses unknown fields, missing required fields, wrong types,
NaN/Inf and values outside an enum - a broken record never travels further as if it were valid.
"""
from __future__ import annotations

import hashlib
import json
import math

from . import VERSION

PATHS = ("ACTIVE", "SH")
MODES = ("SIGNALS", "PAPER", "AUTO_DEMO", "AUTO_LIVE")
SIDES = ("BUY", "SELL", "NONE")
VERDICTS = ("ENTER", "WAIT", "NO_TRADE", "BLOCKED")
ROLES = ("OBSERVE", "ASSIST", "REQUIRED")
INFLUENCE = ("NONE", "HOLD", "BLOCK", "PASS")
INTENT_STATES = ("NEW", "RESERVED", "SENT", "FILLED", "PARTIAL", "REJECTED", "BLOCKED", "UNKNOWN", "RECONCILED_FILLED",
                 "RECONCILED_NOT_FOUND", "DUPLICATE")
OUTCOMES = ("FILLED", "PARTIAL", "REJECTED", "BLOCKED", "UNKNOWN", "DUPLICATE")
DQ = ("OK", "DEGRADED", "STALE", "MISSING", "SYNTHETIC")

# field -> spec: "str" "num" "int" "bool" "list" "dict" "any"; suffix "?" = may be None; tuple = enum (None allowed if "?" in tuple)
SCHEMAS: dict[str, dict] = {
    "InstrumentSpec": {"symbol": "str", "digits": "int", "point": "num", "tick_size": "num", "tick_value": "num?", "contract_size": "num?",
                       "volume_min": "num?", "volume_step": "num?", "volume_max": "num?", "currency_profit": "str?", "margin_mode": "str?"},
    "ObservationEvent": {"source": "str", "kind": "str", "symbol": "str?", "event_time": "str", "received_time": "str", "payload": "dict"},
    "MarketSnapshot": {"snapshot_id": "str", "as_of": "str", "symbol": "str", "bid": "num?", "ask": "num?", "spread": "num?",
                       "quote_age_s": "num?", "last_closed": "dict", "data_quality": DQ, "synthetic": "bool"},
    "FeatureSet": {"snapshot_id": "str", "features": "dict", "feature_hash": "str", "data_time": "str?"},
    "MarketContext": {"snapshot_id": "str", "regime": "str?", "session": "str?", "indicators": "dict?", "dxy": "dict?", "svp": "dict?",
                      "structure": "dict?", "role": ("OBSERVE",)},
    "ModelForecast": {"model_id": "str", "role": ROLES, "state": "str", "task_type": "str", "result": "any?", "data_time": "str?",
                      "age_s": "num?", "influence": INFLUENCE, "reason": "str?"},
    "StrategyCandidate": {"path": PATHS, "strategy_id": "str", "source_id": "str", "symbol": "str", "side": SIDES, "base_verdict": VERDICTS,
                          "entry": "num?", "sl": "num?", "tp": "num?", "risk_money": "num?", "volume": "num?", "reasons": "list"},
    "DecisionRecord": {"record_id": "str", "created_at": "str", "path": PATHS, "source_id": "str", "strategy_id": "str", "symbol": "str",
                       "account_key": "str?", "mode": MODES, "side": SIDES, "base_verdict": VERDICTS, "final_verdict": VERDICTS,
                       "reason_codes": "list", "models": "list", "gates": "dict", "inputs_hash": "str"},
    "ExecutionIntent": {"intent_id": "str", "dedup_key": "str", "record_id": "str?", "path": PATHS, "kind": ("ENTRY", "HEDGE"), "mode": MODES,
                        "account_key": "str?", "symbol": "str", "side": SIDES, "volume": "num?", "risk_money": "num?", "state": INTENT_STATES},
    "ExecutionOutcome": {"intent_id": "str", "status": OUTCOMES, "ticket": "int?", "price": "num?", "volume": "num?", "reason": "str?",
                         "at": "str"},
}


class ContractViolation(ValueError):
    pass


def _ok(v, spec) -> bool:
    if isinstance(spec, tuple):
        return v in spec
    opt = spec.endswith("?")
    t = spec.rstrip("?")
    if v is None:
        return opt
    if t == "any":
        return True
    if t == "str":
        return isinstance(v, str)
    if t == "bool":
        return isinstance(v, bool)
    if t == "int":
        return isinstance(v, int) and not isinstance(v, bool)
    if t == "num":
        return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
    if t == "list":
        return isinstance(v, list)
    if t == "dict":
        return isinstance(v, dict)
    raise ContractViolation(f"BAD_SPEC:{spec}")


def validate(name: str, rec: dict) -> list[str]:
    sch = SCHEMAS[name]
    errs = [f"MISSING:{k}" for k, spec in sch.items() if k not in rec and not (isinstance(spec, str) and spec.endswith("?"))]
    errs += [f"UNKNOWN_FIELD:{k}" for k in rec if k not in sch and k != "contract"]
    errs += [f"BAD_VALUE:{k}" for k, spec in sch.items() if k in rec and not _ok(rec[k], spec)]
    if rec.get("contract") not in (None, f"{VERSION}/{name}"):
        errs.append("WRONG_CONTRACT")
    try:
        json.dumps(rec, allow_nan=False, default=str)
    except ValueError:
        errs.append("NOT_JSON_SAFE")
    return errs


def make(name: str, **fields) -> dict:
    rec = {k: fields.get(k) for k in SCHEMAS[name] if k in fields or not str(SCHEMAS[name][k]).endswith("?")}
    rec.update({k: v for k, v in fields.items() if k not in rec})
    errs = validate(name, rec)
    if errs:
        raise ContractViolation(f"{name}: " + ",".join(errs[:8]))
    rec["contract"] = f"{VERSION}/{name}"
    return rec


def inputs_hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str, allow_nan=False).encode()).hexdigest()[:24]


def instrument_spec(symbol: str, info: dict | None) -> dict:
    i = info or {}
    f = (lambda k: float(i[k]) if i.get(k) is not None else None)
    return make("InstrumentSpec", symbol=symbol, digits=int(i.get("digits") or 2), point=float(i.get("point") or 0.01),
                tick_size=float(i.get("trade_tick_size") or i.get("point") or 0.01), tick_value=f("trade_tick_value"),
                contract_size=f("trade_contract_size"), volume_min=f("volume_min"), volume_step=f("volume_step"), volume_max=f("volume_max"),
                currency_profit=i.get("currency_profit"), margin_mode=i.get("margin_mode_name"))
