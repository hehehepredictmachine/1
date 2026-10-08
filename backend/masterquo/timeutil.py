"""Time helpers. Internally every timestamp is a timezone-aware UTC datetime.

MT5 raw epochs are kept separately (see mt5/clock.py); nothing here guesses offsets.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

UTC = timezone.utc
# Anything above this is certainly milliseconds, not seconds (year ~2286 in seconds).
_MS_THRESHOLD = 10_000_000_000

TF_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600, "H4": 14400, "D1": 86400}
TIMEFRAMES = ("M1", "M5", "M15", "H1", "H4", "D1")


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(d: datetime | None) -> str | None:
    if d is None:
        return None
    if d.tzinfo is None:
        raise ValueError("NAIVE_DATETIME")
    return d.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_iso(s: str | None) -> datetime | None:
    if s is None:
        return None
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if d.tzinfo is None:
        raise ValueError("NAIVE_TIMESTAMP")
    return d.astimezone(UTC)


def epoch_seconds(value: int | float) -> float:
    """Accept an epoch that must be in seconds; reject milliseconds explicitly."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("EPOCH_NOT_NUMERIC")
    if abs(value) >= _MS_THRESHOLD:
        raise ValueError("EPOCH_LOOKS_LIKE_MILLISECONDS")
    return float(value)


def from_epoch(value: int | float) -> datetime:
    return datetime.fromtimestamp(epoch_seconds(value), UTC)


def from_epoch_ms(value: int) -> datetime:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("EPOCH_MS_NOT_INT")
    return datetime.fromtimestamp(value / 1000.0, UTC)


def tf_delta(tf: str) -> timedelta:
    return timedelta(seconds=TF_SECONDS[tf])
