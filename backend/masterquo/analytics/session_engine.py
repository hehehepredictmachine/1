"""Shared session engine (PMW-UPD-06 LS-01..LS-03) - ONE implementation of session boxes and their edge events for scalp, lab,
charts and the agent; scalp/sessions.py and lab/sessions.py are thin adapters that keep their public outputs.

Profiles are explicit, named and versioned (IANA zones, DST via zoneinfo); different modules may use different profiles, but the
same profile always produces the same box (same id / levels) on every chart TF:
  SCALP_OPENING_V1        ASIA 09:00-15:00 Asia/Tokyo, LONDON 08:00-12:00 Europe/London, NEW_YORK 08:00-12:00 America/New_York
  LAB_XAU_REFERENCE_V1    ASIA 09:00-15:00 Asia/Tokyo, LONDON 08:00-16:30 Europe/London, NEW_YORK 08:20-13:30 America/New_York
  LAB_BTC_REFERENCE_V1    ASIA 08:00-16:00 Asia/Singapore, EUROPE 08:00-16:30 Europe/London, US 09:30-16:00 America/New_York
These are working definitions of the project, not universal trading hours.

Window [start_utc, end_utc). A box uses only CLOSED bars that lie wholly inside the window and are available at as_of.
States: SCHEDULED, DEVELOPING (developing_high/low only; final levels null), FINAL (window over AND every expected slot observed),
INCOMPLETE (window over, slots missing - never a full box), NO_DATA. known_at = max(end, availability of the last input).
Coverage: expected slots from the window and the base TF; without a confirmed broker calendar the basis is CALENDAR_UNKNOWN
(a missing slot is reported, never interpolated).
Edge events (FINAL boxes, later closed bars, available at max(bar close, known_at)):
  inside = L <= close <= H; high_taken = high > H + pen; low_taken = low < L - pen
  SWEEP_HIGH / SWEEP_LOW (one side, close inside), SWEEP_BOTH_AMBIGUOUS (both sides, close inside, intrabar order unknown),
  BREAKOUT_UP / BREAKOUT_DOWN (close beyond + breakout buffer; a two-sided bar keeps both_sides_breached=true),
  RETURN_INSIDE_AFTER_BREAK (a later close back inside - never re-labelled as an earlier sweep).
Edges: UNTOUCHED -> SWEPT or BROKEN -> EXPIRED at the next scheduled start of the same session (or TTL). FIRST_ONLY by default.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

VERSION = "PMW-SESSION-ENGINE-1.0.0"
PROFILES = {
    "SCALP_OPENING_V1": {"label": "Scalp – boksy otwarcia (SCALP_OPENING_V1)", "version": 1, "kind": "OPENING_BOX",
                         "sessions": [("ASIA", "Asia/Tokyo", "09:00", "15:00"), ("LONDON", "Europe/London", "08:00", "12:00"),
                                      ("NEW_YORK", "America/New_York", "08:00", "12:00")]},
    "LAB_XAU_REFERENCE_V1": {"label": "Lab XAUUSD – sesje referencyjne (LAB_XAU_REFERENCE_V1)", "version": 1, "kind": "SESSION_BOX",
                             "sessions": [("ASIA", "Asia/Tokyo", "09:00", "15:00"), ("LONDON", "Europe/London", "08:00", "16:30"),
                                          ("NEW_YORK", "America/New_York", "08:20", "13:30")]},
    "LAB_BTC_REFERENCE_V1": {"label": "Lab BTC – sesje referencyjne (LAB_BTC_REFERENCE_V1)", "version": 1, "kind": "SESSION_BOX",
                             "sessions": [("ASIA", "Asia/Singapore", "08:00", "16:00"), ("EUROPE", "Europe/London", "08:00", "16:30"),
                                          ("US", "America/New_York", "09:30", "16:00")]},
}


def _hm(s: str) -> dtime:
    h, m = s.split(":")
    return dtime(int(h), int(m))


def _t(x) -> float:
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, datetime):
        return x.timestamp()
    return datetime.fromisoformat(str(x).replace("Z", "+00:00")).timestamp()


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


def local_window(session: tuple, local_day: date) -> tuple[datetime, datetime]:
    """UTC [start, end) of one session on its LOCAL calendar date (an end <= start in local time crosses midnight)."""
    _, tz, a, b = session
    z = ZoneInfo(tz)
    start = datetime.combine(local_day, _hm(a), z)
    end_day = local_day + timedelta(days=1) if _hm(b) <= _hm(a) else local_day
    end = datetime.combine(end_day, _hm(b), z)
    # nonexistent / ambiguous local times (DST): zoneinfo resolves with fold=0 - the rule is explicit and fixed here
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def windows(profile_id: str, around_utc, days_back: int = 1, days_fwd: int = 1) -> list[dict]:
    """Windows of every session of the profile whose local date is within [around - days_back, around + days_fwd]."""
    p = PROFILES[profile_id]
    t = datetime.fromtimestamp(_t(around_utc), timezone.utc)
    out = []
    for s in p["sessions"]:
        z = ZoneInfo(s[1])
        d0 = t.astimezone(z).date()
        for k in range(-days_back, days_fwd + 1):
            ld = d0 + timedelta(days=k)
            a, b = local_window(s, ld)
            out.append({"session": s[0], "tz": s[1], "local_date": ld.isoformat(), "start": a, "end": b,
                        "local_hours": f"{s[2]}–{s[3]} {s[1]}"})
    return sorted(out, key=lambda w: (w["start"], w["session"]))


def _next_start(profile_id: str, session: str, after: datetime) -> datetime:
    nxt = [w["start"] for w in windows(profile_id, after, 0, 3) if w["session"] == session and w["start"] > after]
    return min(nxt) if nxt else after + timedelta(days=1)


def build(bars: list[dict], tf_s: int, profile_id: str, instrument: str, as_of, *, days: int = 3, pen_buffer: float = 0.0,
          breakout_buffer: float = 0.0, mode: str = "FIRST_ONLY", ttl_s: float | None = None, calendar=None) -> list[dict]:
    """Boxes of the profile for the last `days` local days, as known at as_of. bars: {open_utc, h, l, c, [available_at], [revision],
    [closed]} of ONE base TF. calendar(slot_open_epoch) -> True when the slot is a scheduled close (not a transmission gap)."""
    T = _t(as_of)
    rows = []
    for b in bars:
        o = _t(b["open_utc"])
        if b.get("closed") is False or o + tf_s > T:
            continue                                                 # forming / not closed yet at as_of
        av = _t(b["available_at"]) if b.get("available_at") else o + tf_s
        if av > T:
            continue                                                 # closed but not yet received at as_of
        rows.append((o, av, b))
    rows.sort(key=lambda x: x[0])
    opens = [r[0] for r in rows]
    if len({o for o in opens}) != len(opens):
        dedup = {}
        for r in rows:
            dedup[r[0]] = r                                          # latest revision of the same slot wins (explicit rule)
        rows = sorted(dedup.values(), key=lambda x: x[0])
    out = []
    for w in windows(profile_id, T, days, 0):
        s0, s1 = w["start"].timestamp(), w["end"].timestamp()
        if s0 > T:
            out.append(_box_stub(w, profile_id, instrument, "SCHEDULED"))
            continue
        inside = [r for r in rows if r[0] >= s0 and r[0] + tf_s <= s1]
        upto = min(T, s1)
        slots = [s0 + k * tf_s for k in range(int((upto - s0) // tf_s)) if s0 + (k + 1) * tf_s <= upto]
        sched_closed = [x for x in slots if calendar is not None and calendar(x)]
        expected = len(slots) - len(sched_closed)
        seen = {r[0] for r in inside}
        missing = [x for x in slots if x not in seen and x not in sched_closed]
        box = _box_stub(w, profile_id, instrument, None)
        box.update(expected_slots=expected, observed_slots=len(inside), missing_slots=len(missing),
                   coverage_ratio=(len(inside) / expected) if expected else None,
                   coverage_basis="BROKER_CALENDAR" if calendar is not None else "CALENDAR_UNKNOWN",
                   first_missing=_iso(missing[0]) if missing else None, bars=len(inside), base_tf_s=tf_s)
        if not inside:
            box["state"] = "NO_DATA"
            out.append(box)
            continue
        hi = max(r[2]["h"] for r in inside)
        lo = min(r[2]["l"] for r in inside)
        hi_at = next(r[2]["open_utc"] for r in inside if r[2]["h"] == hi)
        lo_at = next(r[2]["open_utc"] for r in inside if r[2]["l"] == lo)
        rev = hashlib.sha256(repr([(r[0], r[2]["h"], r[2]["l"], r[2].get("revision")) for r in inside]).encode()).hexdigest()[:12]
        box.update(revision=rev, high_at=hi_at, low_at=lo_at)
        if T < s1:
            box.update(state="DEVELOPING", developing_high=hi, developing_low=lo, final_high=None, final_low=None, known_at=None)
            out.append(box)
            continue
        known = max(s1, max(r[1] for r in inside))
        if missing:
            box.update(state="INCOMPLETE", observed_high=hi, observed_low=lo, final_high=None, final_low=None, known_at=None,
                       reason=f"brak {len(missing)} z {expected} świec okna (pierwsza {box['first_missing']}) – boks niepełny, nie FINAL")
            out.append(box)
            continue
        box.update(state="FINAL", final_high=hi, final_low=lo, known_at=_iso(known))
        exp = _next_start(profile_id, w["session"], w["end"]).timestamp()
        if ttl_s:
            exp = min(exp, s1 + ttl_s)
        box["expires_at"] = _iso(exp)
        after = [r for r in rows if r[0] >= s1]
        box["events"], box["edges"] = _events(box, after, tf_s, known, exp, T, pen_buffer, breakout_buffer, mode)
        out.append(box)
    return out


def _box_stub(w: dict, profile_id: str, instrument: str, state: str | None) -> dict:
    return {"box_id": f"{instrument}:{profile_id}:{w['session']}:{w['local_date']}", "profile_id": profile_id, "profile_label": PROFILES[profile_id]["label"],
            "kind": PROFILES[profile_id]["kind"], "session": w["session"], "tz": w["tz"], "local_date": w["local_date"], "local_hours": w["local_hours"],
            "start_utc": w["start"].isoformat(), "end_utc": w["end"].isoformat(), "state": state, "version": VERSION, "events": [], "edges": None}


def _events(box: dict, after: list, tf_s: int, known: float, exp: float, T: float, pen: float, brk: float, mode: str) -> tuple[list, dict]:
    H, L = box["final_high"], box["final_low"]
    edges = {"HIGH": {"state": "UNTOUCHED", "at": None}, "LOW": {"state": "UNTOUCHED", "at": None}}
    ev, broken_side = [], None

    def add(kind, edge, r, **kw):
        o, av, b = r
        eid = hashlib.sha256(f"{box['box_id']}|{box['revision']}|{edge}|{kind}|{b['open_utc']}".encode()).hexdigest()[:12]
        ev.append({"event_id": eid, "box_id": box["box_id"], "revision": box["revision"], "edge": edge, "kind": kind, "bar_open_utc": b["open_utc"],
                   "confirmed_at": _iso(o + tf_s), "available_at": _iso(max(av, known)), "high": b["h"], "low": b["l"], "close": b["c"], **kw})
    for r in after:
        o, av, b = r
        if o >= exp:
            break
        hi_t, lo_t = b["h"] > H + pen, b["l"] < L - pen
        inside = L <= b["c"] <= H
        both = hi_t and lo_t
        if broken_side is None:
            if b["c"] > H + brk or b["c"] < L - brk:
                side = "HIGH" if b["c"] > H + brk else "LOW"
                add("BREAKOUT_UP" if side == "HIGH" else "BREAKOUT_DOWN", side, r, both_sides_breached=both,
                    intrabar_order="UNKNOWN" if both else None)
                edges[side] = {"state": "BROKEN", "at": b["open_utc"]}
                broken_side = side
                continue
            if inside and both:
                if mode != "FIRST_ONLY" or (edges["HIGH"]["state"] == "UNTOUCHED" or edges["LOW"]["state"] == "UNTOUCHED"):
                    add("SWEEP_BOTH_AMBIGUOUS", "BOTH", r, intrabar_order="UNKNOWN")
                for e in ("HIGH", "LOW"):
                    if edges[e]["state"] == "UNTOUCHED":
                        edges[e] = {"state": "SWEPT", "at": b["open_utc"], "ambiguous": True}
                continue
            if inside and hi_t and (mode != "FIRST_ONLY" or edges["HIGH"]["state"] == "UNTOUCHED"):
                add("SWEEP_HIGH", "HIGH", r)
                edges["HIGH"] = {"state": "SWEPT", "at": b["open_utc"]}
            elif inside and lo_t and (mode != "FIRST_ONLY" or edges["LOW"]["state"] == "UNTOUCHED"):
                add("SWEEP_LOW", "LOW", r)
                edges["LOW"] = {"state": "SWEPT", "at": b["open_utc"]}
        elif broken_side == "RETURNED":
            continue                                                 # one break -> one return episode (FIRST_ONLY)
        elif inside:
            add("RETURN_INSIDE_AFTER_BREAK", broken_side, r)
            broken_side = "RETURNED"
    if T >= exp:
        for e in ("HIGH", "LOW"):
            if edges[e]["state"] == "UNTOUCHED":
                edges[e] = {"state": "EXPIRED", "at": _iso(exp)}
    return ev[:24], edges
