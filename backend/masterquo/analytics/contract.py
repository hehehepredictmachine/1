"""Common provenance contract of every analytical result (schema mq-analytics-1.0.0)."""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone

SCHEMA = "mq-analytics-1.0.0"
STATUSES = ("ready", "warming_up", "stale", "unavailable", "error", "disabled")


def config_hash(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True, default=str).encode()).hexdigest()[:12]


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def result(module: str, algorithm_version: str, cfg: dict, *, symbol: str | None, tf: str | None, bars: list[dict], status: str,
           values: dict | None = None, reason: str | None = None, quality: list[str] | None = None, tf_seconds: int | None = None,
           input_price_type: str = "close (broker chart, usually Bid)", source: str = "MT5", t0: float | None = None,
           closed_only: bool = True, extra: dict | None = None) -> dict:
    """as_of = open time of the last input bar's END (close time) - the data boundary; available_at = when the result could
    first be used (the bar close for bar-based results; later for pivots that need right-side bars - set by the caller)."""
    assert status in STATUSES, status
    first = bars[0]["open_utc"] if bars else None
    last = bars[-1]["open_utc"] if bars else None
    as_of = None
    if last and tf_seconds:
        t = datetime.fromisoformat(last.replace("Z", "+00:00")).timestamp() + tf_seconds
        as_of = datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rev = hashlib.sha256(json.dumps([(b["open_utc"], b["o"], b["h"], b["l"], b["c"]) for b in bars[-50:]]).encode()).hexdigest()[:12] if bars else None
    out = {"schema_version": SCHEMA, "module": module, "algorithm_version": algorithm_version, "config": cfg, "config_hash": config_hash(cfg),
           "snapshot_id": f"{module}|{symbol}|{tf}|{as_of}|{config_hash(cfg)}", "source_revision": rev, "symbol": symbol, "timeframe": tf,
           "source": source, "input_price_type": input_price_type, "as_of": as_of, "available_at": as_of, "computed_at": now_iso(),
           "window_start": first, "window_end": last, "status": status, "reason": reason, "quality_flags": quality or [],
           "closed_bars_only": closed_only, "preview": not closed_only, "samples": len(bars),
           "latency_ms": round((time.perf_counter() - t0) * 1000, 2) if t0 is not None else None, "values": values}
    if extra:
        out.update(extra)
    return clean(out)


def clean(x):
    """numpy scalars / arrays -> plain JSON types; NaN / inf -> None (a missing value never becomes a number)."""
    import math
    if isinstance(x, dict):
        return {k: clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    t = type(x).__module__
    if t == "numpy":
        if hasattr(x, "tolist"):
            x = x.tolist()
            return clean(x) if isinstance(x, (list, dict)) else x
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return None
    return x
