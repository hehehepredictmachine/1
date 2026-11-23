"""Contract and freshness checks of predictions entering Quant Core (PMW-QUANT-CHECK-1).

Every prediction is (1) validated with the PMW-PRED-2 validator - NaN / Inf / bool numbers, wrong units, broken distributions, missing
horizons are contract errors, the record is excluded with that reason and has no influence; (2) timed: a data_time or available_at in
the FUTURE (beyond a small clock tolerance) is FUTURE_TIME - never age 0; an age above the TTL (record ttl_s, else the TF / horizon
default) is STALE; a record computed for a bar more than one bar older than the newest closed bar of the snapshot (late worker answer) is LATE_GENERATION;
(3) data kind: a SYNTHETIC record never enters a REAL snapshot. A valid 0 stays 0 (values are never touched).
Direct ensembling is allowed only between records with the identical event definition (task, unit, horizon, timeframe, plan / side) -
`ensemble_compatible`; anything else is kept as separate named features or excluded.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from ..modelhub import contract as C
from ..timeutil import TF_SECONDS
from . import ids as I

VERSION = "PMW-QUANT-CHECK-1"
CLOCK_TOLERANCE_S = 5.0
DEFAULT_TTL_BARS = 2                 # a candle model is stale after 2 bars of its TF beyond its data bar close
STATE_TTL_S = 900.0                  # measurements / states without a TF


def ts(v) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None


def ttl_for(p: dict) -> float:
    if C.is_num(p.get("ttl_s")) and p["ttl_s"] > 0:
        return float(p["ttl_s"])
    tf = p.get("timeframe")
    if tf in TF_SECONDS:
        return float(TF_SECONDS[tf]) * (DEFAULT_TTL_BARS + 1)       # measured from the bar OPEN (bar_open_ts) -> bar close + 2 bars
    return STATE_TTL_S


# 1.46: the TTL and LATE_GENERATION checks assumed data_time = bar OPEN for every record, but the Training Center inference
# (data_time = close_t), Kronos and TSFM (data_time = last_bar_close_utc) report the bar CLOSE - their records lived one bar longer and
# a record two bars older than the newest closed bar was not LATE_GENERATION. The basis is now explicit: a record may declare
# data_time_basis BAR_OPEN | BAR_CLOSE; without it the known close-basis producers below are recognised, everything else stays BAR_OPEN.
CLOSE_BASIS_PRODUCERS = ("trainhub:", "kronos:", "tsfm:")
DATA_TIME_BASES = ("BAR_OPEN", "BAR_CLOSE")


def data_time_basis(p: dict) -> str:
    b = p.get("data_time_basis")
    if b in DATA_TIME_BASES:
        return b
    return "BAR_CLOSE" if I.canonical(p).startswith(CLOSE_BASIS_PRODUCERS) else "BAR_OPEN"


def bar_open_ts(p: dict, dt: float | None) -> float | None:
    """Open time of the bar the record was computed for (data_time moved back one TF for a close-basis record)."""
    sec = TF_SECONDS.get(p.get("timeframe"))
    if dt is None or not sec:
        return dt
    return dt - sec if data_time_basis(p) == "BAR_CLOSE" else dt


def check(p: dict, *, now: float | None = None, snapshot_kind: str | None = None, generation_floor: dict | None = None) -> dict:
    """-> {"eligible": bool, "reason": code|None, "age_s": float|None}. generation_floor: {timeframe: newest closed bar open ts}."""
    now = time.time() if now is None else now
    try:
        C.validate(p)
    except C.ContractError as exc:
        return {"eligible": False, "reason": f"CONTRACT_ERROR:{exc}", "age_s": None}
    if p.get("state") != "READY":
        return {"eligible": False, "reason": f"STATE_{p.get('state')}:{p.get('unavailable_reason') or ''}"[:200], "age_s": None}
    dt = ts(p.get("data_time"))
    av = ts(p.get("available_at"))
    if dt is None:
        return {"eligible": False, "reason": "NO_DATA_TIME", "age_s": None}
    for name, t in (("data_time", dt), ("available_at", av)):
        if t is not None and t > now + CLOCK_TOLERANCE_S:
            return {"eligible": False, "reason": f"FUTURE_TIME:{name}+{t - now:.0f}s", "age_s": now - dt}
    age = now - dt
    bo = bar_open_ts(p, dt)                                        # 1.46: TTL / LATE_GENERATION from the bar open (close-basis records)
    explicit_ttl = C.is_num(p.get("ttl_s")) and p["ttl_s"] > 0
    ttl_age = age if explicit_ttl else now - bo
    tf = p.get("timeframe")
    # the generation-relative reason first: a close-basis record late by >1 bar is now usually past its TTL as well
    if generation_floor and tf in generation_floor and generation_floor[tf] is not None and bo < generation_floor[tf] - TF_SECONDS.get(tf, 60):
        return {"eligible": False, "reason": f"LATE_GENERATION:{tf}", "age_s": age}
    if ttl_age > ttl_for(p):
        return {"eligible": False, "reason": f"STALE:{ttl_age:.0f}s>{ttl_for(p):.0f}s", "age_s": age}
    if snapshot_kind == "REAL" and p.get("data_kind") == "SYNTHETIC":
        return {"eligible": False, "reason": "SYNTHETIC_IN_REAL_SNAPSHOT", "age_s": age}
    return {"eligible": True, "reason": None, "age_s": age}


def screen(preds: list[dict], *, now: float | None = None, snapshot_kind: str | None = None, generation_floor: dict | None = None) -> dict:
    """Dedup aliases, then check every record. -> {"eligible": [...], "excluded": [...], "aliases_dropped": [...]}"""
    kept, dropped = I.dedup(preds)
    elig, excl = [], []
    for p in kept:
        r = check(p, now=now, snapshot_kind=snapshot_kind, generation_floor=generation_floor)
        q = dict(p)
        q["eligibility"] = {"eligible": r["eligible"], "reason": r["reason"]}
        q["age_s"] = None if r["age_s"] is None else round(r["age_s"], 2)
        (elig if r["eligible"] else excl).append(q)
    return {"eligible": elig, "excluded": excl, "aliases_dropped": dropped}


def ensemble_compatible(a: dict, b: dict) -> tuple[bool, str | None]:
    for k in ("task_type", "task", "unit", "timeframe"):
        if a.get(k) != b.get(k):
            return False, f"DIFFERENT_{k.upper()}"
    if (a.get("horizon") or {}) != (b.get("horizon") or {}):
        return False, "DIFFERENT_HORIZON"
    for k in ("event_id", "plan_hash", "direction"):
        if a.get(k) != b.get(k):
            return False, f"DIFFERENT_{k.upper()}"
    return True, None
