"""M5 consolidation range with frozen boundaries + local M1 reaction zones (MQ-RANGE-1.0.0).

Range (closed M5 bars only):
  window of L bars ending at bar r (L from `lookbacks`, checked in the configured order; research runs one L at a time):
    height = max(high) - min(low) between min_h_atr and max_h_atr x ATR14(M5 at r);
    efficiency ratio of closes over the window <= max_er (weak directionality);
    >= min_touches INDEPENDENT contacts (>= 3 bars apart) with each edge: high >= top - edge_frac x height,
    low <= bottom + edge_frac x height.
  The range is recognised at the EARLIEST qualifying r within the last `max_age` bars and its boundaries are FROZEN there
  (they never follow the price). available_at = close of bar r.
  After r: an ACCEPTED breakout = `accept_closes` consecutive closes beyond the boundary + 0.1 ATR, or one close beyond
  0.5 ATR -> state BROKEN_UP / BROKEN_DOWN (edge-to-edge trading of this range is then invalid); otherwise INSIDE.
Local M1 zones (frozen together with the range - all M1 bars used closed before available_at):
  lower zone = M1 bars of the range period whose low <= bottom + edge_frac x height (the reaction cluster at the lower
  edge); zone_low = lowest wick, zone_high = highest BODY-bottom of those bars (wick/body rule), width capped at
  zone_max_atr x ATR(M5). Upper zone mirrored. Not the min/max of all M1 bars of the range.
"""
from __future__ import annotations

import hashlib
from datetime import timedelta

from ..timeutil import iso, parse_iso

VERSION = "MQ-RANGE-1.0.0"
DEFAULTS = {"lookbacks": [18, 12, 24], "min_h_atr": 1.0, "max_h_atr": 6.0, "max_er": 0.35, "edge_frac": 0.2, "min_touches": 2,
            "max_age": 48, "accept_closes": 2, "zone_max_atr": 0.6}


def _touches(idx, gap=3):
    n, last = 0, -10 ** 9
    for k in idx:
        if k - last >= gap:
            n += 1
            last = k
    return n


def _qualify(v, r, L, a, p):
    s = r - L + 1
    if s < 1 or not a:
        return None
    top, bot = max(v.h[s:r + 1]), min(v.l[s:r + 1])
    h = top - bot
    if not (p["min_h_atr"] * a <= h <= p["max_h_atr"] * a):
        return None
    noise = sum(abs(v.c[k] - v.c[k - 1]) for k in range(s, r + 1))
    er = 0.0 if noise == 0 else abs(v.c[r] - v.c[s - 1]) / noise
    if er > p["max_er"]:
        return None
    ef = p["edge_frac"] * h
    tt = _touches([k for k in range(s, r + 1) if v.h[k] >= top - ef])
    tb = _touches([k for k in range(s, r + 1) if v.l[k] <= bot + ef])
    if tt < p["min_touches"] or tb < p["min_touches"]:
        return None
    return {"s": s, "top": top, "bot": bot, "height": h, "er": er, "touches_top": tt, "touches_bottom": tb}


def detect(m5, params: dict | None = None) -> dict:
    p = dict(DEFAULTS, **(params or {}))
    n = len(m5)
    if n < max(p["lookbacks"]) + 20:
        return {"version": VERSION, "status": "BRAK_DANYCH", "reason": "M5_HISTORY_TOO_SHORT"}
    a = m5.atr()
    for L in p["lookbacks"]:
        for r in range(max(L, n - 1 - p["max_age"]), n):
            q = _qualify(m5, r, L, a[r], p)
            if not q:
                continue
            top, bot, h = q["top"], q["bot"], q["height"]
            buf = 0.1 * a[r]
            state, brk = "INSIDE", None
            run_up = run_dn = 0
            for j in range(r + 1, n):
                c = m5.c[j]
                run_up = run_up + 1 if c > top + buf else 0
                run_dn = run_dn + 1 if c < bot - buf else 0
                if run_up >= p["accept_closes"] or c > top + 0.5 * a[r]:
                    state, brk = "BROKEN_UP", j
                    break
                if run_dn >= p["accept_closes"] or c < bot - 0.5 * a[r]:
                    state, brk = "BROKEN_DOWN", j
                    break
            avail = iso(parse_iso(m5.t[r]) + timedelta(minutes=5))
            rid = "RG-" + hashlib.sha256(f"M5|{m5.t[q['s']]}|{m5.t[r]}|{L}".encode()).hexdigest()[:12]
            return {"version": VERSION, "status": "OK", "range_id": rid, "tf": "M5", "lookback": L, "start_utc": m5.t[q["s"]],
                    "recognised_bar": m5.t[r], "recognised_index": r, "available_at": avail, "top": round(top, 5), "bottom": round(bot, 5),
                    "mid": round((top + bot) / 2, 5), "height": round(h, 5), "atr": round(a[r], 5), "height_atr": round(h / a[r], 2),
                    "er": round(q["er"], 3), "touches_top": q["touches_top"], "touches_bottom": q["touches_bottom"], "state": state,
                    "break_index": brk, "break_bar": m5.t[brk] if brk is not None else None,
                    "break_close": round(m5.c[brk], 5) if brk is not None else None, "bars_since": n - 1 - r, "params": p}
    return {"version": VERSION, "status": "NO_RANGE", "reason": "NO_RANGE"}


def local_zones(m1, rng: dict, params: dict | None = None) -> dict:
    p = dict(DEFAULTS, **(params or {}))
    if rng.get("status") != "OK":
        return {"status": "NO_RANGE"}
    start, end = parse_iso(rng["start_utc"]), parse_iso(rng["available_at"])
    idx = [k for k, t in enumerate(m1.t) if start <= parse_iso(t) and parse_iso(t) + timedelta(minutes=1) <= end]
    if not idx or parse_iso(m1.t[0]) > start:
        return {"status": "BRAK_DANYCH", "reason": "M1_HISTORY_DOES_NOT_COVER_RANGE"}
    ef = p["edge_frac"] * rng["height"]
    maxw = p["zone_max_atr"] * rng["atr"]
    out = {"status": "OK", "frozen_at": rng["available_at"], "range_id": rng["range_id"], "rule": "WICK_TO_BODY", "lower": None, "upper": None}
    lo_bars = [k for k in idx if m1.l[k] <= rng["bottom"] + ef]
    hi_bars = [k for k in idx if m1.h[k] >= rng["top"] - ef]
    if lo_bars:
        zl = min(m1.l[k] for k in lo_bars)
        zh = max(min(m1.o[k], m1.c[k]) for k in lo_bars)
        zh = min(max(zh, zl), zl + maxw)
        out["lower"] = {"low": round(zl, 5), "high": round(zh, 5), "bars": len(lo_bars), "first": m1.t[lo_bars[0]], "last": m1.t[lo_bars[-1]]}
    if hi_bars:
        zh = max(m1.h[k] for k in hi_bars)
        zl = min(max(m1.o[k], m1.c[k]) for k in hi_bars)
        zl = max(min(zl, zh), zh - maxw)
        out["upper"] = {"low": round(zl, 5), "high": round(zh, 5), "bars": len(hi_bars), "first": m1.t[hi_bars[0]], "last": m1.t[hi_bars[-1]]}
    if not lo_bars and not hi_bars:
        out["status"] = "NO_M1_REACTION"
    return out
