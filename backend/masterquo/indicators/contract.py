"""PMW-IND-1 - one versioned result shape for every analytical indicator (AVWAP, spread percentile, semivariance, profile features,
order-book microstructure, XAUUSD-DXY relation).

* A number that cannot be computed is None with a reason - never a fake 0. A legitimate 0.0 is a value.
* status: READY | WARMUP (not enough history yet) | NO_DATA (source absent) | STALE (source older than its limit) | ERROR | DISABLED.
  Only READY results may vote / enter features as known values; every other status is a typed absence.
* The same pure functions are used online, in replay and in dataset export (indicators.* modules take bars / samples + as_of).
* config_hash covers the indicator configuration and the instrument metadata (tick size, digits) - part of every cache key.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from datetime import datetime, timezone

VERSION = "PMW-IND-1"
STATUSES = ("READY", "WARMUP", "NO_DATA", "STALE", "ERROR", "DISABLED")
REQUIRED = ("contract", "instrument", "broker_symbol", "source", "timeframe", "data_time", "available_at", "computed_at", "snapshot_id",
            "indicator_id", "algorithm_version", "config_hash", "values", "units", "status", "reason", "sample_count", "volume_source")


def iso(t) -> str | None:
    if t is None:
        return None
    if isinstance(t, datetime):
        return t.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return datetime.fromtimestamp(float(t), timezone.utc).isoformat().replace("+00:00", "Z")


def ts(x) -> float | None:
    if x is None:
        return None
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return float(x)
    if isinstance(x, datetime):
        return x.timestamp()
    return datetime.fromisoformat(str(x).replace("Z", "+00:00")).timestamp()


def finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def num(x, sig: int = 12):
    """Finite float (12 significant digits - small quantities such as squared log returns keep their precision), else None
    (NaN / inf / bool / None never leak as numbers)."""
    return float(f"{float(x):.{sig}g}") if finite(x) else None


def config_hash(cfg: dict, instrument_meta: dict | None = None) -> str:
    blob = json.dumps({"cfg": cfg, "meta": instrument_meta or {}}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def result(indicator_id: str, algorithm_version: str, *, instrument: str, broker_symbol: str | None, source: str, timeframe: str | None,
           data_time=None, available_at=None, values: dict | None = None, units: dict | None = None, status: str = "READY",
           reason: str | None = None, sample_count: int | None = 0, volume_source: str | None = None, cfg: dict | None = None,
           instrument_meta: dict | None = None, computed_at=None, extra: dict | None = None) -> dict:
    if status not in STATUSES:
        raise ValueError(f"IND_STATUS_INVALID: {status}")
    vals = {k: (num(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v) for k, v in (values or {}).items()}
    if status != "READY" and not reason:
        reason = status
    ch = config_hash(cfg or {}, instrument_meta)
    sid = hashlib.sha256(f"{indicator_id}|{instrument}|{timeframe}|{iso(ts(data_time)) if data_time is not None else ''}|{ch}|"
                         f"{json.dumps(vals, sort_keys=True, default=str)}".encode()).hexdigest()[:16]
    out = {"contract": VERSION, "instrument": instrument, "broker_symbol": broker_symbol, "source": source, "timeframe": timeframe,
           "data_time": iso(ts(data_time)) if data_time is not None else None,
           "available_at": iso(ts(available_at)) if available_at is not None else None,
           "computed_at": iso(computed_at if computed_at is not None else time.time()), "snapshot_id": f"IND-{sid}",
           "indicator_id": indicator_id, "algorithm_version": algorithm_version, "config_hash": ch, "values": vals, "units": units or {},
           "status": status, "reason": reason, "sample_count": int(sample_count or 0), "volume_source": volume_source}
    if extra:
        out.update(extra)
    return out


def validate(r: dict) -> list[str]:
    errs = [f"missing:{k}" for k in REQUIRED if k not in r]
    if r.get("contract") != VERSION:
        errs.append("contract")
    if r.get("status") not in STATUSES:
        errs.append("status")
    if r.get("status") != "READY" and not r.get("reason"):
        errs.append("reason_required")
    for k, v in (r.get("values") or {}).items():
        if isinstance(v, bool):
            continue
        if isinstance(v, float) and not math.isfinite(v):
            errs.append(f"non_finite:{k}")
    try:
        json.dumps(r, allow_nan=False, default=str)
    except ValueError:
        errs.append("json_nan")
    return errs


def ready(r: dict | None) -> bool:
    return bool(r) and r.get("status") == "READY"


def value(r: dict | None, key: str):
    """Known value of a READY result, else None (consumers never read numbers out of a non-ready result)."""
    return (r.get("values") or {}).get(key) if ready(r) else None
