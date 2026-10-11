"""Time helpers. Internally every timestamp is a timezone-aware UTC datetime.

MT5 raw epochs are kept separately (see mt5/clock.py); nothing here guesses offsets.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

UTC = timezone.utc
# Anything above this is certainly milliseconds, not seconds (year ~2286 in seconds).
_MS_THRESHOLD = 10_000_000_000

# Single timeframe registry (MQ-TF-REGISTRY-1.0.0). Every list of timeframes in the bot derives from it.
#   mt5   - name of the MetaTrader5 constant (never a number of minutes used as an enum)
#   pine  - TradingView interval string for the same bar size
#   core  - part of the original six-timeframe data gate of the MasterQUO engines (M01-M07);
#           context timeframes (M30, H8) are collected, analysed and shown, and a strategy that needs them
#           reports BRAK_DANYCH when they are missing - they never block the core engine
#   role  - what the timeframe contributes to decisions
TF_REGISTRY = {
    "M1": {"seconds": 60, "mt5": "TIMEFRAME_M1", "pine": "1", "core": True, "role": "TRIGGER"},
    "M5": {"seconds": 300, "mt5": "TIMEFRAME_M5", "pine": "5", "core": True, "role": "TRIGGER"},
    "M15": {"seconds": 900, "mt5": "TIMEFRAME_M15", "pine": "15", "core": True, "role": "SETUP"},
    "M30": {"seconds": 1800, "mt5": "TIMEFRAME_M30", "pine": "30", "core": False, "role": "SETUP_CONTEXT"},
    "H1": {"seconds": 3600, "mt5": "TIMEFRAME_H1", "pine": "60", "core": True, "role": "LOCAL_CONTEXT"},
    "H4": {"seconds": 14400, "mt5": "TIMEFRAME_H4", "pine": "240", "core": True, "role": "HTF"},
    "H8": {"seconds": 28800, "mt5": "TIMEFRAME_H8", "pine": "480", "core": False, "role": "TREND_REGIME_CONTEXT"},
    "D1": {"seconds": 86400, "mt5": "TIMEFRAME_D1", "pine": "D", "core": True, "role": "BACKGROUND"},
}
TF_SECONDS = {tf: v["seconds"] for tf, v in TF_REGISTRY.items()}
TIMEFRAMES = tuple(TF_REGISTRY)                                    # ordered by bar size
CORE_TIMEFRAMES = tuple(tf for tf, v in TF_REGISTRY.items() if v["core"])
CONTEXT_TIMEFRAMES = tuple(tf for tf, v in TF_REGISTRY.items() if not v["core"])


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
