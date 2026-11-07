"""Unified prediction contract (PMW-PRED-2) - one shape for every model output shown or routed by the bot.

PMW-PRED-2 (1.33) extends PMW-PRED-1 (same field names, every PMW-PRED-1 producer still validates) with:
* strict numbers: every numeric value must be a finite int/float and never a bool (`True` is not a probability, NaN / +-Inf are refused);
* task-specific result schemas (validate_result): a distribution, an event probability, a regression / forecast with an optional
  interval, a volatility (variance / sigma with its scale), a pair relation, a microstructure measurement, a filter state, an RL action
  proposal and an NLP sentiment - each checked field by field; descriptive text fields (direction, forecast_id ...) stay legal;
* horizon: a forecast (CLASS_PROBABILITIES, EVENT_PROBABILITY, REGRESSION, VOLATILITY) needs a positive integer number of bars OR a
  positive number of seconds; a measurement of a state (MICROSTRUCTURE, PAIR_RELATION, FILTER_STATE, NLP_SENTIMENT, STATE, ZONES,
  SCORE) may have no horizon (null) - no invented horizon_bars=1;
* provenance / validity (optional, validated when present): run_id, source, data_kind REAL|SYNTHETIC, available_at, computed_at,
  ttl_s, label_version;
* the whole record must be JSON-serialisable without NaN (json.dumps(allow_nan=False)).
A model that is not READY carries NO result (null) and a reason - a failure can never look like a neutral or positive value; a valid 0
is a value, not a missing one. A score / z-score / share of conditions is never labelled a probability (unit says what it is).
States (panel): READY gotowy, NOT_TRAINED niewytrenowany, TRAINING trening, ERROR błąd, INCOMPATIBLE niezgodny, DISABLED wyłączony,
BLOCKED_DATA brak wymaganych danych, STALE nieaktualny.
"""
from __future__ import annotations

import json
import math
import time

VERSION = "PMW-PRED-2"
COMPATIBLE = ("PMW-PRED-1", "PMW-PRED-2")
STATES = {"READY": "gotowy", "NOT_TRAINED": "niewytrenowany", "TRAINING": "trening", "ERROR": "błąd", "INCOMPATIBLE": "niezgodny",
          "DISABLED": "wyłączony", "BLOCKED_DATA": "brak wymaganych danych", "STALE": "nieaktualny"}
FORECAST_TASKS = ("CLASS_PROBABILITIES", "EVENT_PROBABILITY", "REGRESSION", "VOLATILITY")
TASK_TYPES = FORECAST_TASKS + ("SCORE", "STATE", "ZONES", "PAIR_RELATION", "MICROSTRUCTURE", "FILTER_STATE", "RL_ACTION",
                               "NLP_SENTIMENT")
UNITS = ("probability", "score_0_100", "price", "atr", "log_return", "return", "state", "zones", "variance", "sigma_return",
         "z_score", "ratio", "mixed", "action", "sentiment")
CALIBRATION = ("CALIBRATED_DEV", "UNCALIBRATED", "NOT_APPLICABLE")
DATA_KINDS = ("REAL", "SYNTHETIC")
VOL_SCALES = ("decimal", "percent")


class ContractError(ValueError):
    pass


def is_num(v) -> bool:
    """A finite number that is not a bool."""
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _num(v, what: str) -> float:
    if not is_num(v):
        raise ContractError(f"NOT_FINITE_NUMBER:{what}")
    return float(v)


def _prob(v, what: str) -> float:
    x = _num(v, what)
    if x < 0 or x > 1:
        raise ContractError(f"PROBABILITY_OUT_OF_RANGE:{what}")
    return x


def _dist(r, what: str = "result") -> None:
    if not isinstance(r, dict) or not r:
        raise ContractError(f"DISTRIBUTION_EMPTY:{what}")
    tot = 0.0
    for k, v in r.items():
        if not isinstance(k, str) or not k:
            raise ContractError(f"CLASS_NAME_INVALID:{what}")
        tot += _prob(v, f"{what}.{k}")
    if abs(tot - 1.0) > 1e-6:
        raise ContractError("DISTRIBUTION_NOT_NORMALISED")


def _numeric_fields(r: dict, what: str, *, allow_none: bool = False) -> int:
    """Every numeric-looking field must be finite; strings / bool-free metadata stay legal. Returns the number of numbers."""
    n = 0
    for k, v in r.items():
        if isinstance(v, bool):
            raise ContractError(f"BOOL_NOT_A_NUMBER:{what}.{k}")
        if isinstance(v, (int, float)):
            _num(v, f"{what}.{k}")
            n += 1
        elif v is None and not allow_none:
            raise ContractError(f"NULL_FIELD_WITHOUT_REASON:{what}.{k}")
        elif isinstance(v, (list, tuple)):
            for i, x in enumerate(v):
                if isinstance(x, bool) or (isinstance(x, (int, float)) and not math.isfinite(x)):
                    raise ContractError(f"NOT_FINITE_NUMBER:{what}.{k}[{i}]")
                if isinstance(x, (int, float)):
                    n += 1
        elif isinstance(v, dict):
            n += _numeric_fields(v, f"{what}.{k}", allow_none=allow_none)
    return n


def _interval(r: dict) -> None:
    for lo, hi in (("lo", "hi"), ("lower", "upper"), ("q_lo", "q_hi")):
        if lo in r and hi in r and r[lo] is not None and r[hi] is not None and _num(r[lo], lo) > _num(r[hi], hi):
            raise ContractError(f"INTERVAL_INVERTED:{lo}>{hi}")


def validate_result(task_type: str, unit: str, r) -> None:
    if task_type == "CLASS_PROBABILITIES":
        if unit != "probability":
            raise ContractError("UNIT_MISMATCH:CLASS_PROBABILITIES_NEEDS_probability")
        _dist(r)
    elif task_type == "EVENT_PROBABILITY":
        if unit != "probability":
            raise ContractError("UNIT_MISMATCH:EVENT_PROBABILITY_NEEDS_probability")
        if isinstance(r, dict):
            if "p" not in r:
                raise ContractError("EVENT_PROBABILITY_WITHOUT_p")
            _prob(r["p"], "result.p")
            _numeric_fields(r, "result")
        else:
            _prob(r, "result")
    elif task_type == "REGRESSION":
        if not isinstance(r, dict) or _numeric_fields(r, "result") == 0:
            raise ContractError("REGRESSION_WITHOUT_NUMERIC_FIELD")
        _interval(r)
    elif task_type == "VOLATILITY":
        if not isinstance(r, dict):
            raise ContractError("VOLATILITY_NOT_A_RECORD")
        if "sigma" not in r and "variance" not in r:
            raise ContractError("VOLATILITY_WITHOUT_sigma_OR_variance")
        for k in ("sigma", "variance"):
            if k in r and _num(r[k], f"result.{k}") < 0:
                raise ContractError(f"VOLATILITY_NEGATIVE:{k}")
        if r.get("scale") not in VOL_SCALES:
            raise ContractError("VOLATILITY_SCALE_MISSING")     # decimal vs percent must be explicit
        _numeric_fields(r, "result")
    elif task_type in ("PAIR_RELATION", "MICROSTRUCTURE"):
        if not isinstance(r, dict) or _numeric_fields(r, "result", allow_none=True) == 0:
            raise ContractError(f"{task_type}_WITHOUT_NUMERIC_FIELD")
    elif task_type == "FILTER_STATE":
        if not isinstance(r, dict) or not isinstance(r.get("state"), str):
            raise ContractError("FILTER_STATE_WITHOUT_state")
        _numeric_fields(r, "result", allow_none=True)
    elif task_type == "RL_ACTION":
        if not isinstance(r, dict) or not isinstance(r.get("action"), str):
            raise ContractError("RL_ACTION_WITHOUT_action")
        if "action_probabilities" in r:
            _dist(r["action_probabilities"], "action_probabilities")
        _numeric_fields({k: v for k, v in r.items() if k != "action_probabilities"}, "result", allow_none=True)
    elif task_type == "NLP_SENTIMENT":
        if not isinstance(r, dict) or "sentiment" not in r:
            raise ContractError("NLP_SENTIMENT_WITHOUT_sentiment")
        _dist(r["sentiment"], "sentiment")
        _numeric_fields({k: v for k, v in r.items() if k != "sentiment"}, "result", allow_none=True)
    elif task_type == "SCORE":
        if unit == "probability":
            raise ContractError("SCORE_IS_NOT_A_PROBABILITY")
        if isinstance(r, dict):
            _numeric_fields(r, "result")
        else:
            _num(r, "result")
    elif task_type == "ZONES":
        if not isinstance(r, list):
            raise ContractError("ZONES_NOT_A_LIST")
    elif task_type == "STATE":
        if isinstance(r, dict):
            _numeric_fields(r, "result", allow_none=True)
        elif not isinstance(r, str):
            raise ContractError("STATE_NOT_TEXT_OR_RECORD")


def _horizon(task_type: str, h: dict | None) -> None:
    h = h or {}
    bars, secs = h.get("bars"), h.get("seconds")
    for name, v in (("bars", bars), ("seconds", secs)):
        if v is None:
            continue
        if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
            raise ContractError(f"HORIZON_INVALID:{name}={v!r}")      # positive integer only
    if task_type in FORECAST_TASKS and bars is None and secs is None:
        raise ContractError("MISSING_HORIZON")


def make(*, instrument: str, symbol: str | None, timeframe: str | None, model_name: str, model_version: str | None, task_type: str, task: str,
         horizon_bars: int | None, unit: str, state: str, result=None, data_time: str | None = None, feature_schema: str | None = None,
         calibration: dict | None = None, data_quality: str = "OK", freshness_s: float | None = None, compute_ms: float | None = None,
         unavailable_reason: str | None = None, extra: dict | None = None, horizon_seconds: int | None = None, run_id: str | None = None,
         source: str | None = None, data_kind: str | None = None, available_at: str | None = None, ttl_s: float | None = None,
         label_version: str | None = None) -> dict:
    p = {"contract": VERSION, "instrument": instrument, "symbol": symbol, "timeframe": timeframe, "data_time": data_time,
         "model_name": model_name, "model_version": model_version, "run_id": run_id, "feature_schema": feature_schema,
         "label_version": label_version, "task_type": task_type, "task": task,
         "horizon": {"bars": horizon_bars, "seconds": horizon_seconds, "timeframe": timeframe},
         "result": result if state == "READY" else None, "unit": unit,
         "calibration": calibration or {"method": None, "status": "NOT_APPLICABLE"}, "data_quality": data_quality, "freshness_s": freshness_s,
         "compute_ms": compute_ms, "state": state, "state_pl": STATES.get(state, state), "source": source, "data_kind": data_kind,
         "available_at": available_at, "computed_at": time.time(), "ttl_s": ttl_s,
         "unavailable_reason": unavailable_reason if state != "READY" else None, "created_at": time.time(), **(extra or {})}
    validate(p)
    return p


def validate(p: dict) -> dict:
    if p.get("contract", VERSION) not in COMPATIBLE:
        raise ContractError(f"CONTRACT_VERSION_UNKNOWN:{p.get('contract')}")
    if p.get("state") not in STATES:
        raise ContractError(f"STATE_INVALID:{p.get('state')}")
    if p.get("task_type") not in TASK_TYPES:
        raise ContractError(f"TASK_TYPE_INVALID:{p.get('task_type')}")
    if p.get("unit") not in UNITS:
        raise ContractError(f"UNIT_INVALID:{p.get('unit')}")
    if (p.get("calibration") or {}).get("status") not in CALIBRATION:
        raise ContractError("CALIBRATION_STATUS_INVALID")
    if p.get("data_kind") is not None and p["data_kind"] not in DATA_KINDS:
        raise ContractError(f"DATA_KIND_INVALID:{p['data_kind']}")
    for k in ("freshness_s", "compute_ms", "ttl_s"):
        if p.get(k) is not None and (not is_num(p[k]) or p[k] < 0):
            raise ContractError(f"NOT_FINITE_NUMBER:{k}")
    _horizon(p["task_type"], p.get("horizon"))
    if p["state"] != "READY":
        if p.get("result") is not None:
            raise ContractError("RESULT_WITHOUT_READY_STATE")                 # a failure must not carry a value
        if not p.get("unavailable_reason"):
            raise ContractError("MISSING_UNAVAILABLE_REASON")
    else:
        if p.get("result") is None:
            raise ContractError("READY_WITHOUT_RESULT")
        if not p.get("data_time"):
            raise ContractError("READY_WITHOUT_DATA_TIME")
        validate_result(p["task_type"], p["unit"], p["result"])
    try:
        json.dumps(p, allow_nan=False, default=str)
    except ValueError as exc:
        raise ContractError(f"NOT_JSON_SERIALISABLE:{exc}") from exc
    return p
