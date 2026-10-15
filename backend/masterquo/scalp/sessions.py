"""Session sweep boxes (own explicit rules, SESS-1.0.0) - context only, separate from the M5 consolidation range.

Sessions are defined in LOCAL time of an IANA zone (DST handled by zoneinfo - no year-round manual offset):
  ASIA      09:00-15:00 Asia/Tokyo
  LONDON    08:00-12:00 Europe/London   (opening box)
  NEW_YORK  08:00-12:00 America/New_York (opening box)
A box (high/low of the CLOSED bars whose whole interval lies in the window) becomes known only at the window end;
`boxes_as_of(t)` never returns a box whose end is later than t. A sweep is a later closed bar whose extreme crosses
the box edge: SWEEP_HIGH (high > box high, close back <= box high), BREAK_HIGH (close > box high); mirrored for low.
These rules are not a copy of any external indicator (the external Session Sweep Boxes buffer mapping is unverified).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

VERSION = "SESS-1.0.0"
SESSIONS = {"ASIA": ("Asia/Tokyo", (9, 0), (15, 0)), "LONDON": ("Europe/London", (8, 0), (12, 0)),
            "NEW_YORK": ("America/New_York", (8, 0), (12, 0))}


def _t(s) -> datetime:
    return s if isinstance(s, datetime) else datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def windows(day_utc: datetime) -> list[tuple[str, datetime, datetime]]:
    """Session windows (UTC) whose local date is the calendar day of day_utc or the day before (for Asia at UTC midnight)."""
    out = []
    for name, (tz, (h0, m0), (h1, m1)) in SESSIONS.items():
        z = ZoneInfo(tz)
        for dd in (-1, 0):
            d = (day_utc + timedelta(days=dd)).date()
            a = datetime(d.year, d.month, d.day, h0, m0, tzinfo=z).astimezone(timezone.utc)
            b = datetime(d.year, d.month, d.day, h1, m1, tzinfo=z).astimezone(timezone.utc)
            out.append((name, a, b))
    return out


def boxes_as_of(bars: list[dict], tf_minutes: int, as_of) -> list[dict]:
    """Latest COMPLETED box of each session (end <= as_of) from closed bars {open_utc, h, l, c}, plus its sweep state."""
    t = _t(as_of)
    step = timedelta(minutes=tf_minutes)
    rows = [(_t(b["open_utc"]), b) for b in bars]
    rows = [(o, b) for (o, b) in rows if o + step <= t]          # closed and known
    out = []
    for name in SESSIONS:
        cands = [(a, b) for (n, a, b) in windows(t) + windows(t - timedelta(days=1)) if n == name and b <= t]
        if not cands:
            continue
        a, e = max(cands, key=lambda x: x[1])
        inside = [b for (o, b) in rows if o >= a and o + step <= e]
        if not inside:
            out.append({"session": name, "start_utc": a.isoformat(), "end_utc": e.isoformat(), "status": "NO_BARS"})
            continue
        hi, lo = max(b["h"] for b in inside), min(b["l"] for b in inside)
        after = [b for (o, b) in rows if o >= e]
        state, at = "UNTOUCHED", None
        for b in after:
            if b["c"] > hi:
                state, at = "BREAK_HIGH", b["open_utc"]
                break
            if b["c"] < lo:
                state, at = "BREAK_LOW", b["open_utc"]
                break
            if b["h"] > hi and state == "UNTOUCHED":
                state, at = "SWEEP_HIGH", b["open_utc"]
            elif b["l"] < lo and state == "UNTOUCHED":
                state, at = "SWEEP_LOW", b["open_utc"]
        out.append({"session": name, "start_utc": a.isoformat(), "end_utc": e.isoformat(), "known_at": e.isoformat(), "high": hi, "low": lo,
                    "bars": len(inside), "state": state, "state_at": at, "status": "OK", "version": VERSION})
    return out
