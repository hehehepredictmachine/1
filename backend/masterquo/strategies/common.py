"""Helpers shared by S01-S10 (plans, buckets, swing levels). No market I/O."""
from __future__ import annotations

from .base import MarketView, TFView, real_price


def sgn(direction: str) -> int:
    return 1 if direction == "LONG" else -1


def level_bucket(view: MarketView, level: float) -> str:
    """Price bucket used to group signals that describe the same level (event_id).

    Bucket width = 0.5 x ATR14(M15) rounded to 0.1 (fallback 1.0 price unit); documented as a
    grouping heuristic, not a trading level.
    """
    v = view.tfs.get("M15")
    a = None
    if v is not None and len(v) > 20:
        a = v.atr()[v.last]
    w = max(0.1, round((a or 2.0) * 0.5, 1))
    real = real_price(view, level)
    return f"{round(real / w) * w:.1f}"


def stop_with_spread(direction: str, level: float, buffer: float, spread: float) -> float:
    """LONG stop below level; SHORT stop above level + spread (a short is stopped on Ask)."""
    return level - buffer if direction == "LONG" else level + buffer + spread


def valid_targets(direction: str, entry: float, stop: float, cands: list[tuple[float, float, str]], min_r: float = 0.3) -> list[dict]:
    """Keep targets beyond entry by at least min_r x risk, ordered from nearest; weights renormalised."""
    s = sgn(direction)
    risk = abs(entry - stop)
    if risk <= 0:
        return []
    ok = [(p, w, b) for p, w, b in cands if p is not None and s * (p - entry) >= min_r * risk]
    ok.sort(key=lambda t: s * (t[0] - entry))
    seen, out = set(), []
    for p, w, b in ok:
        key = round(p, 2)
        if key in seen:
            continue
        seen.add(key)
        out.append([p, w, b])
    tot = sum(t[1] for t in out)
    return [{"price": round(p, 5), "weight": round(w / tot, 4), "basis": b} for p, w, b in out] if tot > 0 else []


def plan(kind: str, ref: float, zone: tuple[float, float] | None, trigger: str, trigger_level: float | None,
         max_wait_bars: int, max_distance_atr: float) -> dict:
    return {"order_type": "MARKET_ON_CONFIRMATION", "kind": kind, "reference_price": round(ref, 5),
            "zone": None if zone is None else [round(min(zone), 5), round(max(zone), 5)], "trigger": trigger,
            "trigger_level": None if trigger_level is None else round(trigger_level, 5),
            "max_wait_bars": max_wait_bars, "max_distance_atr": max_distance_atr,
            "send_when": "po zamknięciu świecy wyzwalającej, jeśli cena nie odjechała dalej niż max_distance_atr od poziomu"}


def last_swing(v: TFView, kind: str, at: int, left: int = 3, right: int = 3, max_age: int = 80) -> dict | None:
    """Most recent confirmed pivot of `kind` ('H'/'L') known at bar `at`."""
    best = None
    for p in v.pivots(left, right):
        if p["kind"] == kind and p["confirmed_index"] <= at and at - p["index"] <= max_age:
            if best is None or p["index"] > best["index"]:
                best = p
    return best


def body_ratio(v: TFView, i: int) -> float:
    rng = v.h[i] - v.l[i]
    return 0.0 if rng <= 0 else abs(v.c[i] - v.o[i]) / rng


def close_pos(v: TFView, i: int) -> float:
    """Close location in the bar range (0 = low, 1 = high)."""
    rng = v.h[i] - v.l[i]
    return 0.5 if rng <= 0 else (v.c[i] - v.l[i]) / rng


def mirror_ok(direction: str, a: float, b: float) -> bool:
    """a is 'beyond' b in the trade direction."""
    return a > b if direction == "LONG" else a < b
