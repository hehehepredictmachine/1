"""SYNTHETIC_TEST bars for analytics tests (code checks only - never market evidence)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

T0 = datetime(2026, 3, 2, tzinfo=timezone.utc)


def from_path(prices: list[float], tf_min: int = 5, wick: float = 0.2, t0=T0) -> list[dict]:
    out = []
    prev = prices[0]
    for i, p in enumerate(prices):
        o = prev
        out.append({"open_utc": (t0 + timedelta(minutes=tf_min * i)).strftime("%Y-%m-%dT%H:%M:%SZ"), "o": round(o, 3), "h": round(max(o, p) + wick, 3),
                    "l": round(min(o, p) - wick, 3), "c": round(p, 3), "tv": 100})
        prev = p
    return out


def lin(a, b, n):
    return [a + (b - a) * k / n for k in range(1, n + 1)]


def double_bottom(resolve: str = "up", second_low: float = 1990.2) -> list[dict]:
    """decline 2010 -> 1990, bounce to neckline ~2000, second bottom, then break up / break down / nothing."""
    path = [2010.0] + lin(2010, 1990, 12) + lin(1990, 2000, 8) + lin(2000, second_low, 8) + lin(second_low, 1997, 5)
    if resolve == "up":
        path += lin(1997, 2004, 4) + lin(2004, 1993, 6)          # break above, then a later false-breakout drop
    elif resolve == "down":
        path += lin(1997, 1985, 6) + lin(1985, 2005, 8)          # break below, then a later rally
    return from_path(path)
