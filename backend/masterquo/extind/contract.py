"""Envelope contract `pmw-extind-1` (outer {envelope, checksum, body}) written by mql5/PMW_ExtIndicatorExporter.mq5 (or a producer's documented export).

The reader accepts ONLY a complete, checksummed envelope; a partial / malformed file never replaces the last good snapshot.
Nothing in an envelope is executed: it is data (no eval, no paths, no commands). MQL5 EMPTY_VALUE (DBL_MAX) becomes null;
NaN/Inf/broken geometry is an error, never a number cleaned later. Zero is a valid value.
"""
from __future__ import annotations

import hashlib
import json
import math

SCHEMA = "pmw-extind-1"
MAX_BYTES = 2_000_000
MAX_OBJECTS = 2000
EMPTY_VALUE = 1.7976931348623157e308
OBJECT_TYPES = ("HLINE", "TREND", "VLINE", "RECTANGLE", "FIBO", "TEXT", "LABEL", "OTHER")
REQUIRED = ("schema_version", "producer_version", "adapter_id", "product", "terminal_fingerprint", "chart_id", "symbol", "tf",
            "time_basis", "captured_at_server", "generation", "sequence", "complete", "objects")


class EnvelopeError(ValueError):
    pass


def checksum(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def wrap(body: dict) -> bytes:
    """Outer file format: {"envelope": SCHEMA, "checksum": sha256(body text), "body": "<JSON text>"} - the checksum is taken
    over the exact body text the producer wrote, so MQL5 and Python agree without re-serialising floats."""
    txt = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    return json.dumps({"envelope": SCHEMA, "checksum": checksum(txt), "body": txt}, ensure_ascii=False).encode("utf-8")


def _num(x, field: str):
    if x is None:
        return None
    if not isinstance(x, (int, float)) or isinstance(x, bool):
        raise EnvelopeError(f"NOT_A_NUMBER:{field}")
    if not math.isfinite(x):
        raise EnvelopeError(f"NON_FINITE:{field}")
    return None if abs(x) >= EMPTY_VALUE * 0.999 else float(x)


def validate(raw: bytes) -> dict:
    if len(raw) > MAX_BYTES:
        raise EnvelopeError("ENVELOPE_TOO_LARGE")
    try:
        outer = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise EnvelopeError(f"ENVELOPE_NOT_JSON:{type(exc).__name__}") from exc     # partial write ends here
    if not isinstance(outer, dict) or outer.get("envelope") != SCHEMA or not isinstance(outer.get("body"), str):
        raise EnvelopeError("ENVELOPE_FORMAT")
    if checksum(outer["body"]) != outer.get("checksum"):
        raise EnvelopeError("CHECKSUM_MISMATCH")
    try:
        d = json.loads(outer["body"])
    except ValueError as exc:
        raise EnvelopeError("BODY_NOT_JSON") from exc
    if not isinstance(d, dict):
        raise EnvelopeError("ENVELOPE_NOT_OBJECT")
    d["checksum"] = outer["checksum"]
    miss = [k for k in REQUIRED if k not in d]
    if miss:
        raise EnvelopeError("ENVELOPE_MISSING:" + ",".join(miss))
    if d["schema_version"] != SCHEMA:
        raise EnvelopeError(f"SCHEMA_UNSUPPORTED:{d['schema_version']}")
    if d["complete"] is not True:
        raise EnvelopeError("ENVELOPE_INCOMPLETE")
    if not isinstance(d["objects"], list) or len(d["objects"]) > MAX_OBJECTS:
        raise EnvelopeError("OBJECTS_INVALID_OR_TOO_MANY")
    if d["time_basis"] not in ("BROKER_SERVER", "UTC"):
        raise EnvelopeError(f"TIME_BASIS_UNKNOWN:{d['time_basis']}")
    for k in ("generation", "sequence", "captured_at_server"):
        if not isinstance(d[k], int) or d[k] < 0:
            raise EnvelopeError(f"BAD_INTEGER:{k}")
    objs = []
    for i, o in enumerate(d["objects"]):
        if not isinstance(o, dict) or not isinstance(o.get("name"), str):
            raise EnvelopeError(f"OBJECT_INVALID@{i}")
        t = o.get("type") if o.get("type") in OBJECT_TYPES else "OTHER"
        prices = [_num(p, f"objects[{i}].prices") for p in (o.get("prices") or [])]
        times = [int(x) for x in (o.get("times") or []) if isinstance(x, int) and x >= 0]
        if t == "HLINE" and (not prices or prices[0] is None):
            raise EnvelopeError(f"HLINE_WITHOUT_PRICE@{i}")
        if t in ("TREND", "RECTANGLE") and (len(times) < 2 or len(prices) < 2):
            raise EnvelopeError(f"GEOMETRY_INCOMPLETE@{i}")
        if t == "VLINE" and not times:
            raise EnvelopeError(f"VLINE_WITHOUT_TIME@{i}")
        objs.append({"name": o["name"][:120], "type": t, "prices": prices, "times": times, "text": str(o.get("text") or "")[:200],
                     "color": o.get("color")})
    d["objects"] = objs
    if isinstance(d.get("buffers"), dict):                     # documented buffers only (Buffer Inspector extends this)
        d["buffers"] = {str(k)[:40]: _num(v, f"buffers.{k}") for k, v in list(d["buffers"].items())[:64]}
    return d
