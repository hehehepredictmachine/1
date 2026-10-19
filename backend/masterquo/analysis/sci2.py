"""MQ_STRUCTURE_CANDLES_V2 - Super Candles Intelligence 2 (PMW-UPD-07 R03). Own module developing SCI (not a clone of a product).

A candle reading is CONDITIONAL evidence inside a structure. Candle geometry comes unchanged from analysis/candles (MQ-CANDLE-1.0.0);
several names on one bar form ONE evidence group (no tripled confidence). The structural role is decided by deterministic rules
(ATR / tick parameters, UNKNOWN without data), checked in this order:
  NECKLINE_BREAK    a known double bottom / inverse H&S (or the SHORT mirror) whose v2 instance CONFIRMED on this very bar
  BREAKOUT_FAILURE  an instance that had confirmed and closed back inside (RETEST_FAILED) on this bar -> opposite scenario hypothesis
  RETEST_HOLD       an instance in RETEST_PENDING / RETEST_HELD and this bar touched the frozen boundary (retest tolerance) and closed
                    on the breakout side
  SWEEP_RECLAIM     a SWEEP_CANDIDATE structure event on this bar (wick beyond a known swing, close back inside) - a rejection
                    HYPOTHESIS, not proof of institutional absorption
  TREND_PULLBACK    internal trend UP (DOWN): the bar's low (high) is in the lower (upper) half of the last known swing range and the
                    protected swing is intact; the candle confirms resumption only after its close and a trigger
  COMPRESSION       range of the last 5 bars < 0.7 x range of the previous 5 and the ATR declining; direction unresolved
  MID_RANGE         close in the middle 40 % of the last known swing range and > 0.3 ATR from both boundaries; limited directional
                    value, by default no new plan
  STRUCTURE_ONLY    structure known, none of the above;  NO_STRUCTURAL_CONTEXT  no known swings (warm-up / no data)
`supports` is True only when the candle evidence direction agrees with the role's direction; it is never an order and never a
probability. Tick volume is broker activity, not aggressive buy/sell volume.
"""
from __future__ import annotations

import hashlib

from . import candles as CA
from . import structure_v2 as S

VERSION = "MQ_STRUCTURE_CANDLES_V2"
ROLE_DIR = {"NECKLINE_BREAK": None, "BREAKOUT_FAILURE": None, "RETEST_HOLD": None, "SWEEP_RECLAIM": None, "TREND_PULLBACK": None,
            "COMPRESSION": "NEUTRAL", "MID_RANGE": "NEUTRAL", "STRUCTURE_ONLY": None, "NO_STRUCTURAL_CONTEXT": None}
BULL_FAMILIES = ("DOUBLE_BOTTOM", "INVERSE_HEAD", "TRIPLE_BOTTOM")
BEAR_FAMILIES = ("DOUBLE_TOP", "HEAD_AND_SHOULDERS", "TRIPLE_TOP")


def _atr(h, lo, c, i, n=14):
    return S._atr(h, lo, c, i, n)


def read(t: list[str], o, h, lo, c, tf: str, *, i: int | None = None, tick: float = 0.01, patterns: list[dict] | None = None,
         structure: dict | None = None, zones: list[dict] | None = None, available_at: str | None = None) -> dict:
    """Reading of the closed bar i (default: last). `patterns` = structure_v2.upgrade_patterns records, `structure` = structure_v2.analyse
    over the same bars (computed here when absent). Pure: uses only bars <= i."""
    n = len(c)
    i = n - 1 if i is None else i
    t, o, h, lo, c = t[:i + 1], o[:i + 1], h[:i + 1], lo[:i + 1], c[:i + 1]
    a = _atr(h, lo, c, i)
    base = {"version": VERSION, "tf": tf, "bar_t": t[i] if t else None, "available_at": available_at, "atr": a}
    if a is None or a <= 0:
        return dict(base, role="NO_STRUCTURAL_CONTEXT", reason_codes=["ATR_UNAVAILABLE"], data_quality="WARMING_UP", candles=[], evidence=[])
    st = structure or S.analyse(t, h, lo, c, tick=tick)
    cands = CA.detect_at(o, h, lo, c, t, i, a, tf, available_at)
    ev = CA.evidence_events(cands)
    lay = st["layers"].get("internal", {})
    sw = lay.get("swings") or []
    trend = lay.get("trend", "UNKNOWN")
    last_h = next((x for x in reversed(sw) if x["kind"] == "H"), None)
    last_l = next((x for x in reversed(sw) if x["kind"] == "L"), None)
    role, direction, reasons, pat_ref, ev_ids, level = None, None, [], None, [], None
    for p in patterns or []:
        hist = p.get("v2_history") or []
        last = hist[-1] if hist else None
        if not last or last["bar_index"] != i:
            continue
        fam = str(p.get("type", ""))
        d = "LONG" if p.get("direction_if_confirmed") == "LONG" else "SHORT"
        if last["to"] == "CONFIRMED" and fam.startswith(BULL_FAMILIES + BEAR_FAMILIES):
            role, direction, pat_ref = "NECKLINE_BREAK", d, p
            reasons.append("CLOSE_BEYOND_NECKLINE_BUFFER")
            break
        if last["to"] == "RETEST_FAILED":
            role, direction, pat_ref = "BREAKOUT_FAILURE", ("SHORT" if d == "LONG" else "LONG"), p
            reasons.append("CLOSE_BACK_INSIDE_AFTER_BREAKOUT")
            break
        if last["to"] in ("RETEST_PENDING", "RETEST_HELD"):
            role, direction, pat_ref = "RETEST_HOLD", d, p
            reasons.append("RETEST_OF_FROZEN_BOUNDARY")
            break
    if role is None:
        sweep = [e for e in st["events"] if e["bar_index"] == i and e["kind"].startswith("SWEEP") and e["layer"] == "internal"]
        if sweep:
            e = sweep[-1]
            role, direction, level = "SWEEP_RECLAIM", ("SHORT" if e["kind"].endswith("HIGH") else "LONG"), e["level"]
            ev_ids.append(e["event_id"])
            reasons.append("WICK_BEYOND_KNOWN_SWING_CLOSE_INSIDE")
    if role is None and last_h and last_l:
        top, bot = max(last_h["price"], last_l["price"]), min(last_h["price"], last_l["price"])
        mid_lo, mid_hi = bot + 0.3 * (top - bot), bot + 0.7 * (top - bot)
        if trend == "UP" and lo[i] <= (top + bot) / 2 and c[i] > last_l["price"]:
            role, direction, level = "TREND_PULLBACK", "LONG", last_l["price"]
            reasons.append("PULLBACK_IN_UP_STRUCTURE_PROTECTED_HL_INTACT")
        elif trend == "DOWN" and h[i] >= (top + bot) / 2 and c[i] < last_h["price"]:
            role, direction, level = "TREND_PULLBACK", "SHORT", last_h["price"]
            reasons.append("PULLBACK_IN_DOWN_STRUCTURE_PROTECTED_LH_INTACT")
        elif i >= 10 and (max(h[i - 4:i + 1]) - min(lo[i - 4:i + 1])) < 0.7 * (max(h[i - 9:i - 4]) - min(lo[i - 9:i - 4])) \
                and (_atr(h, lo, c, i - 5) or a) > a:
            role, direction = "COMPRESSION", "NEUTRAL"
            reasons.append("RANGE_AND_ATR_CONTRACTING")
        elif mid_lo <= c[i] <= mid_hi and min(abs(c[i] - top), abs(c[i] - bot)) > 0.3 * a:
            role, direction = "MID_RANGE", "NEUTRAL"
            reasons.append("NO_CONTACT_WITH_BOUNDARY")
        else:
            role = "STRUCTURE_ONLY"
            reasons.append("NO_DEFINED_ROLE")
    if role is None:
        role = "NO_STRUCTURAL_CONTEXT"
        reasons.append("NO_KNOWN_SWINGS")
    zone = None
    for z in zones or []:
        lo_z, hi_z = z.get("bottom"), z.get("top")
        if lo_z is not None and hi_z is not None:
            dist = 0.0 if lo_z <= c[i] <= hi_z else min(abs(c[i] - lo_z), abs(c[i] - hi_z)) / a
            if zone is None or dist < zone["distance_atr"]:
                zone = {"zone_id": z.get("zone_id") or z.get("id"), "revision": z.get("revision"), "distance_atr": round(dist, 3)}
    readings = []
    for g in ev:
        sup = direction in ("LONG", "SHORT") and g["direction"] == direction
        readings.append({"candle_family": g["members"], "geometric_strength": g["score"], "evidence_group_id": g["evidence_id"],
                         "candle_direction": g["direction"], "supports_role": bool(sup),
                         "interpretation": "świeca wspiera rolę strukturalną (warunkowo, nie sygnał)" if sup else
                         "świeca bez wsparcia roli / rola neutralna"})
    if level is None and pat_ref:
        b = pat_ref.get("boundary")
        level = b.get("price") if isinstance(b, dict) else b
    rid = "SCI2-" + hashlib.sha256(f"{tf}|{t[i]}|{role}".encode()).hexdigest()[:12]
    return dict(base, reading_id=rid, role=role, role_direction=direction, structural_level=level,
                chart_pattern_id=(pat_ref or {}).get("pattern_id"), chart_pattern_revision=(pat_ref or {}).get("revision"),
                structure_event_ids=ev_ids, zone=zone, context_trend=trend, reason_codes=reasons, candles=readings,
                evidence=[g["evidence_id"] for g in ev], invalidation=(pat_ref or {}).get("invalidation") if pat_ref else
                (last_l["price"] if direction == "LONG" and last_l else last_h["price"] if direction == "SHORT" and last_h else None),
                confirmation="zamknięcie kolejnej świecy w kierunku roli (trigger)" if direction in ("LONG", "SHORT") else None,
                data_quality="OK", signal=None,
                note="Rola i świeca to dowód warunkowy; brak procentu i brak zlecenia. Tick volume ≠ wolumen agresorów.")
