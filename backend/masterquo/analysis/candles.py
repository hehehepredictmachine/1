"""Candle pattern engine (MQ-CANDLE-1.0.0) - deterministic geometry on CLOSED bars (a forming bar gives PREVIEW only).

Geometry of a bar:  range = h - l, body = |c - o|, upper = h - max(o, c), lower = min(o, c) - l,
close location CLV = (c - l) / range (0 = at the low, 1 = at the high). Sizes are compared with ATR14 of the same TF.
A zero-range bar (h == l) has no geometry: no pattern, reason ZERO_RANGE.

Definitions (LONG form; SHORT = mirrored):
  ENGULFING_BULL     previous bar bearish, current bullish, current body >= previous body, current body >= 0.3 ATR,
                     open <= previous close + tol and close >= previous open.  The CFD feed is nearly continuous, so the
                     classic "open below previous close" gap is NOT required: variant NO_GAP_CFD (tol = 0.05 ATR).
  PIN_BAR_BULL       lower wick >= 0.6 range, body <= 0.3 range, CLV >= 0.6, range >= 0.5 ATR (geometry only).
  HAMMER             PIN_BAR_BULL + context: a down-swing before it (close 3 bars earlier > previous close).
  SHOOTING_STAR      the SHORT counterpart of HAMMER (upper wick, after an up-swing).
  MORNING_STAR       bar-2 bearish with body >= 0.6 ATR, bar-1 body <= 0.3 x body(bar-2), current bullish closing above
                     the midpoint of bar-2's body (no gap required, variant NO_GAP_CFD).  EVENING_STAR mirrored.
  INSIDE_BAR         high <= mother high and low >= mother low: COMPRESSION only (direction NEUTRAL).
  INSIDE_BAR_BREAK   a later CLOSE beyond the mother bar high/low (within 3 bars): the confirmation, separate record.
  OUTSIDE_BAR        high > previous high and low < previous low; EXPANSION (body >= 0.6 range, close in the outer 30%)
                     or REJECTION (close back inside the previous range with a wick >= 0.4 range on the rejected side).
  DOJI               body <= 0.1 range: equilibrium / uncertainty (NEUTRAL - never a direction by itself);
                     LONG_LEGGED_DOJI: both wicks >= 0.3 range and range >= 1 ATR.
  MARUBOZU           body >= 0.85 range and range >= 1.2 ATR (displacement candle) - direction of the body.
  TWEEZER_BOTTOM     |low - previous low| <= 0.1 ATR, previous bearish, current bullish.  TWEEZER_TOP mirrored.
  THREE_WHITE_SOLDIERS  3 bullish bars, each close > previous close, each open inside the previous body, each body
                     >= 0.5 ATR, upper wick <= 0.3 body.  THREE_BLACK_CROWS mirrored.
Context (trend / zone) is supplied by the caller and recorded; an engulfing in the middle of a range is reported with
context IN_MIDDLE and is never a trigger by itself. Several names on the same bar(s) and direction form ONE evidence
event (`evidence_events`) - five names of one candle are not five confirmations. The score is a geometry quality 0..1,
not a probability of a winning trade.
"""
from __future__ import annotations

import hashlib

VERSION = "MQ-CANDLE-1.0.0"


def _geo(o, h, lo, c):
    rng = h - lo
    if rng <= 0:
        return None
    body = abs(c - o)
    return {"range": rng, "body": body, "upper": h - max(o, c), "lower": min(o, c) - lo, "clv": (c - lo) / rng,
            "bull": c > o, "bear": c < o}


def _pid(tf, t, kind):
    return "CP-" + hashlib.sha256(f"{tf}|{t}|{kind}".encode()).hexdigest()[:12]


def _rec(tf, kind, direction, times, avail, geo, score, nxt, inval, variant=None, state="CONFIRMED_SHAPE", context=None):
    return {"candle_pattern_id": _pid(tf, times[-1], kind), "type": kind, "version": VERSION, "tf": tf, "bars": times,
            "detected_at": avail, "available_at": avail, "direction": direction, "geometry": geo, "score": round(max(0.0, min(1.0, score)), 3),
            "next_confirmation": nxt, "invalidation": inval, "variant": variant, "state": state, "context": context or {}}


def detect_at(o, h, lo, c, t, i: int, atr: float | None, tf: str, avail: str | None, context: dict | None = None, preview: bool = False) -> list[dict]:
    """Patterns ending at bar i. `avail` = time the bar is closed and known. preview=True for a forming bar."""
    if i < 0 or atr is None or atr <= 0:
        return []
    g = _geo(o[i], h[i], lo[i], c[i])
    if g is None:
        return []
    state = "PREVIEW" if preview else "CONFIRMED_SHAPE"
    out = []
    rng, body = g["range"], g["body"]
    gr = {k: round(v, 5) if isinstance(v, float) else v for k, v in g.items()}
    tol = 0.05 * atr
    p = _geo(o[i - 1], h[i - 1], lo[i - 1], c[i - 1]) if i >= 1 else None
    # engulfing
    if p is not None:
        for d, cond in (("LONG", p["bear"] and g["bull"] and o[i] <= c[i - 1] + tol and c[i] >= o[i - 1]),
                        ("SHORT", p["bull"] and g["bear"] and o[i] >= c[i - 1] - tol and c[i] <= o[i - 1])):
            if cond and body >= p["body"] and body >= 0.3 * atr:
                out.append(_rec(tf, "ENGULFING_BULL" if d == "LONG" else "ENGULFING_BEAR", d, [t[i - 1], t[i]], avail, gr,
                                min(1.0, body / (2 * max(p["body"], 1e-9))) * 0.5 + 0.5 * min(1.0, body / atr),
                                "kolejna świeca bez zamknięcia za ekstremum formacji", lo[i] if d == "LONG" else h[i],
                                variant="NO_GAP_CFD", state=state, context=context))
    # pin bar / hammer / shooting star
    if g["lower"] >= 0.6 * rng and body <= 0.3 * rng and g["clv"] >= 0.6 and rng >= 0.5 * atr:
        down_before = i >= 3 and c[i - 3] > c[i - 1]
        out.append(_rec(tf, "PIN_BAR_BULL", "LONG", [t[i]], avail, gr, g["lower"] / rng, "zamknięcie kolejnej świecy powyżej high pin bara",
                        lo[i], state=state, context=context))
        if down_before:
            out.append(_rec(tf, "HAMMER", "LONG", [t[i]], avail, gr, g["lower"] / rng, "zamknięcie kolejnej świecy powyżej high młota",
                            lo[i], state=state, context=dict(context or {}, prior_swing="DOWN")))
    if g["upper"] >= 0.6 * rng and body <= 0.3 * rng and g["clv"] <= 0.4 and rng >= 0.5 * atr:
        up_before = i >= 3 and c[i - 3] < c[i - 1]
        out.append(_rec(tf, "PIN_BAR_BEAR", "SHORT", [t[i]], avail, gr, g["upper"] / rng, "zamknięcie kolejnej świecy poniżej low pin bara",
                        h[i], state=state, context=context))
        if up_before:
            out.append(_rec(tf, "SHOOTING_STAR", "SHORT", [t[i]], avail, gr, g["upper"] / rng, "zamknięcie kolejnej świecy poniżej low formacji",
                            h[i], state=state, context=dict(context or {}, prior_swing="UP")))
    # morning / evening star
    if i >= 2 and p is not None:
        a = _geo(o[i - 2], h[i - 2], lo[i - 2], c[i - 2])
        if a is not None and a["body"] >= 0.6 * atr and p["body"] <= 0.3 * a["body"]:
            mid = (o[i - 2] + c[i - 2]) / 2
            if a["bear"] and g["bull"] and c[i] > mid:
                out.append(_rec(tf, "MORNING_STAR", "LONG", [t[i - 2], t[i - 1], t[i]], avail, gr, min(1.0, (c[i] - mid) / max(a["body"], 1e-9) + 0.5),
                                "brak zamknięcia poniżej low środkowej świecy", min(lo[i - 2:i + 1]), variant="NO_GAP_CFD", state=state, context=context))
            if a["bull"] and g["bear"] and c[i] < mid:
                out.append(_rec(tf, "EVENING_STAR", "SHORT", [t[i - 2], t[i - 1], t[i]], avail, gr, min(1.0, (mid - c[i]) / max(a["body"], 1e-9) + 0.5),
                                "brak zamknięcia powyżej high środkowej świecy", max(h[i - 2:i + 1]), variant="NO_GAP_CFD", state=state, context=context))
    # inside / outside
    if p is not None and h[i] <= h[i - 1] and lo[i] >= lo[i - 1]:
        out.append(_rec(tf, "INSIDE_BAR", "NEUTRAL", [t[i - 1], t[i]], avail, dict(gr, mother_high=h[i - 1], mother_low=lo[i - 1]),
                        1 - rng / max(p["range"], 1e-9), "zamknięcie poza high/low świecy matki", None, state=state, context=context))
    if p is not None and h[i] > h[i - 1] and lo[i] < lo[i - 1]:
        if body >= 0.6 * rng and (g["clv"] >= 0.7 or g["clv"] <= 0.3):
            d = "LONG" if g["clv"] >= 0.7 else "SHORT"
            out.append(_rec(tf, "OUTSIDE_BAR_EXPANSION", d, [t[i - 1], t[i]], avail, gr, body / rng, "brak powrotu do środka świecy",
                            lo[i] if d == "LONG" else h[i], state=state, context=context))
        elif lo[i - 1] <= c[i] <= h[i - 1] and (g["lower"] >= 0.4 * rng or g["upper"] >= 0.4 * rng):
            d = "LONG" if g["lower"] >= g["upper"] else "SHORT"
            out.append(_rec(tf, "OUTSIDE_BAR_REJECTION", d, [t[i - 1], t[i]], avail, gr, max(g["lower"], g["upper"]) / rng,
                            "zamknięcie kolejnej świecy w kierunku odrzucenia", lo[i] if d == "LONG" else h[i], state=state, context=context))
    # inside bar break (confirmation of an earlier inside bar)
    for j in range(max(1, i - 3), i):
        if h[j] <= h[j - 1] and lo[j] >= lo[j - 1]:
            if c[i] > h[j - 1] and all(c[k] <= h[j - 1] for k in range(j, i)):
                out.append(_rec(tf, "INSIDE_BAR_BREAK_UP", "LONG", [t[j - 1], t[j], t[i]], avail, gr, min(1.0, (c[i] - h[j - 1]) / atr + 0.5),
                                "brak powrotu poniżej low matki", lo[j - 1], state=state, context=context))
            if c[i] < lo[j - 1] and all(c[k] >= lo[j - 1] for k in range(j, i)):
                out.append(_rec(tf, "INSIDE_BAR_BREAK_DOWN", "SHORT", [t[j - 1], t[j], t[i]], avail, gr, min(1.0, (lo[j - 1] - c[i]) / atr + 0.5),
                                "brak powrotu powyżej high matki", h[j - 1], state=state, context=context))
    # doji
    if body <= 0.1 * rng:
        ll = g["upper"] >= 0.3 * rng and g["lower"] >= 0.3 * rng and rng >= atr
        out.append(_rec(tf, "LONG_LEGGED_DOJI" if ll else "DOJI", "NEUTRAL", [t[i]], avail, gr, 1 - body / rng,
                        "kierunek dopiero po zamknięciu kolejnej świecy", None, state=state, context=context))
    # marubozu / displacement
    if body >= 0.85 * rng and rng >= 1.2 * atr:
        d = "LONG" if g["bull"] else "SHORT"
        out.append(_rec(tf, "MARUBOZU_DISPLACEMENT", d, [t[i]], avail, gr, min(1.0, rng / (2 * atr)), "brak powrotu za połowę korpusu",
                        (o[i] + c[i]) / 2, state=state, context=context))
    # tweezers
    if p is not None:
        if abs(lo[i] - lo[i - 1]) <= 0.1 * atr and p["bear"] and g["bull"]:
            out.append(_rec(tf, "TWEEZER_BOTTOM", "LONG", [t[i - 1], t[i]], avail, gr, 1 - abs(lo[i] - lo[i - 1]) / (0.1 * atr + 1e-12) * 0.5,
                            "zamknięcie powyżej high pary", min(lo[i], lo[i - 1]), state=state, context=context))
        if abs(h[i] - h[i - 1]) <= 0.1 * atr and p["bull"] and g["bear"]:
            out.append(_rec(tf, "TWEEZER_TOP", "SHORT", [t[i - 1], t[i]], avail, gr, 1 - abs(h[i] - h[i - 1]) / (0.1 * atr + 1e-12) * 0.5,
                            "zamknięcie poniżej low pary", max(h[i], h[i - 1]), state=state, context=context))
    # three soldiers / crows
    if i >= 2:
        gs = [_geo(o[k], h[k], lo[k], c[k]) for k in (i - 2, i - 1, i)]
        if all(gs):
            if all(x["bull"] and x["body"] >= 0.5 * atr and x["upper"] <= 0.3 * x["body"] for x in gs) and \
               c[i - 1] > c[i - 2] and c[i] > c[i - 1] and o[i - 2] < o[i - 1] <= c[i - 2] and o[i - 1] < o[i] <= c[i - 1]:
                out.append(_rec(tf, "THREE_WHITE_SOLDIERS", "LONG", [t[i - 2], t[i - 1], t[i]], avail, gr, 0.8, "brak zamknięcia poniżej open trzeciej świecy",
                                o[i], state=state, context=context))
            if all(x["bear"] and x["body"] >= 0.5 * atr and x["lower"] <= 0.3 * x["body"] for x in gs) and \
               c[i - 1] < c[i - 2] and c[i] < c[i - 1] and o[i - 2] > o[i - 1] >= c[i - 2] and o[i - 1] > o[i] >= c[i - 1]:
                out.append(_rec(tf, "THREE_BLACK_CROWS", "SHORT", [t[i - 2], t[i - 1], t[i]], avail, gr, 0.8, "brak zamknięcia powyżej open trzeciej świecy",
                                o[i], state=state, context=context))
    return out


def evidence_events(patterns: list[dict]) -> list[dict]:
    """Group interdependent names (same TF, same last bar, same direction) into ONE evidence event."""
    groups: dict[tuple, dict] = {}
    for p in patterns:
        key = (p["tf"], p["bars"][-1], p["direction"])
        g = groups.setdefault(key, {"evidence_id": "EVD-" + hashlib.sha256("|".join(map(str, key)).encode()).hexdigest()[:12],
                                    "tf": p["tf"], "bar": p["bars"][-1], "direction": p["direction"], "members": [], "score": 0.0,
                                    "available_at": p["available_at"], "state": p["state"]})
        g["members"].append(p["type"])
        g["score"] = max(g["score"], p["score"])
    return list(groups.values())


def scan(v, tf: str, lookback: int = 5, context_fn=None, include_forming: bool = False) -> dict:
    """Patterns on the last `lookback` closed bars of a TFView (+ the forming bar as PREVIEW if asked)."""
    from ..timeutil import TF_SECONDS, iso, parse_iso
    from datetime import timedelta
    n = len(v)
    if n < 20:
        return {"version": VERSION, "tf": tf, "status": "INSUFFICIENT_BARS", "patterns": [], "evidence": []}
    a = v.atr()
    pats = []
    for i in range(max(3, n - lookback), n):
        avail = iso(parse_iso(v.t[i]) + timedelta(seconds=TF_SECONDS[tf]))
        ctx = context_fn(i) if context_fn else None
        pats += detect_at(v.o, v.h, v.l, v.c, v.t, i, a[i], tf, avail, ctx)
    if include_forming and v.forming:
        f = v.forming
        o, h, lo, c, t = v.o + [f["o"]], v.h + [f["h"]], v.l + [f["l"]], v.c + [f["c"]], v.t + [f["open_utc"]]
        pats += detect_at(o, h, lo, c, t, n, a[n - 1], tf, None, None, preview=True)
    return {"version": VERSION, "tf": tf, "status": "OK", "patterns": pats, "evidence": evidence_events([p for p in pats if p["state"] != "PREVIEW"])}
