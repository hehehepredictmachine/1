"""Unified prediction contract (PMW-PRED-1) - one shape for every model output shown or routed by the bot.

Fields: instrument, symbol, timeframe, data_time (close of the last candle used), model_name, model_version, feature_schema,
task_type / task / horizon (+ unit of the horizon), result + unit, calibration (method + status), data_quality, freshness_s,
compute_ms, state, unavailable_reason.
Rules enforced by validate():
* a model that is not READY carries NO result (result None) and a reason - a failure can never look like a neutral or positive value;
* probabilities are in [0, 1] and a distribution sums to 1; a score is not a probability (unit says which);
* every result states its unit and its horizon; results with different task / horizon / unit are never aggregated (aggregate.py).
States (panel): READY gotowy, NOT_TRAINED niewytrenowany, TRAINING trening, ERROR błąd, INCOMPATIBLE niezgodny, DISABLED wyłączony.
"""
from __future__ import annotations

import time

VERSION = "PMW-PRED-1"
STATES = {"READY": "gotowy", "NOT_TRAINED": "niewytrenowany", "TRAINING": "trening", "ERROR": "błąd", "INCOMPATIBLE": "niezgodny",
          "DISABLED": "wyłączony"}
TASK_TYPES = ("CLASS_PROBABILITIES", "EVENT_PROBABILITY", "REGRESSION", "SCORE", "STATE", "ZONES")
UNITS = ("probability", "score_0_100", "price", "atr", "log_return", "state", "zones")
CALIBRATION = ("CALIBRATED_DEV", "UNCALIBRATED", "NOT_APPLICABLE")


class ContractError(ValueError):
    pass


def make(*, instrument: str, symbol: str | None, timeframe: str, model_name: str, model_version: str | None, task_type: str, task: str,
         horizon_bars: int | None, unit: str, state: str, result=None, data_time: str | None = None, feature_schema: str | None = None,
         calibration: dict | None = None, data_quality: str = "OK", freshness_s: float | None = None, compute_ms: float | None = None,
         unavailable_reason: str | None = None, extra: dict | None = None) -> dict:
    p = {"contract": VERSION, "instrument": instrument, "symbol": symbol, "timeframe": timeframe, "data_time": data_time,
         "model_name": model_name, "model_version": model_version, "feature_schema": feature_schema, "task_type": task_type, "task": task,
         "horizon": {"bars": horizon_bars, "timeframe": timeframe}, "result": result if state == "READY" else None, "unit": unit,
         "calibration": calibration or {"method": None, "status": "NOT_APPLICABLE"}, "data_quality": data_quality, "freshness_s": freshness_s,
         "compute_ms": compute_ms, "state": state, "state_pl": STATES.get(state, state),
         "unavailable_reason": unavailable_reason if state != "READY" else None, "created_at": time.time(), **(extra or {})}
    validate(p)
    return p


def validate(p: dict) -> dict:
    if p.get("state") not in STATES:
        raise ContractError(f"STATE_INVALID:{p.get('state')}")
    if p.get("task_type") not in TASK_TYPES:
        raise ContractError(f"TASK_TYPE_INVALID:{p.get('task_type')}")
    if p.get("unit") not in UNITS:
        raise ContractError(f"UNIT_INVALID:{p.get('unit')}")
    if p["state"] != "READY":
        if p.get("result") is not None:
            raise ContractError("RESULT_WITHOUT_READY_STATE")                 # a failure must not carry a value
        if not p.get("unavailable_reason"):
            raise ContractError("MISSING_UNAVAILABLE_REASON")
        return p
    r = p.get("result")
    if r is None:
        raise ContractError("READY_WITHOUT_RESULT")
    if not p.get("data_time"):
        raise ContractError("READY_WITHOUT_DATA_TIME")
    if p["unit"] == "probability":
        vals = list(r.values()) if isinstance(r, dict) else [r]
        if any((not isinstance(v, (int, float))) or v < 0 or v > 1 for v in vals):
            raise ContractError("PROBABILITY_OUT_OF_RANGE")
        if p["task_type"] == "CLASS_PROBABILITIES" and abs(sum(vals) - 1.0) > 1e-6:
            raise ContractError("DISTRIBUTION_NOT_NORMALISED")
    if p["task_type"] in ("CLASS_PROBABILITIES", "EVENT_PROBABILITY", "REGRESSION") and not (p.get("horizon") or {}).get("bars"):
        raise ContractError("MISSING_HORIZON")
    if (p.get("calibration") or {}).get("status") not in CALIBRATION:
        raise ContractError("CALIBRATION_STATUS_INVALID")
    return p
