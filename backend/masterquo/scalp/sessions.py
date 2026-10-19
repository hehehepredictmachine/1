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

from datetime import datetime

VERSION = "SESS-1.1.0"
PROFILE = "SCALP_OPENING_V1"
SESSIONS = {"ASIA": ("Asia/Tokyo", (9, 0), (15, 0)), "LONDON": ("Europe/London", (8, 0), (12, 0)),
            "NEW_YORK": ("America/New_York", (8, 0), (12, 0))}


def _t(s) -> datetime:
    return s if isinstance(s, datetime) else datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def windows(day_utc: datetime) -> list[tuple[str, datetime, datetime]]:
    """Session windows (UTC) whose local date is the calendar day of day_utc or the day before (for Asia at UTC midnight).
    PMW-UPD-06: computed by the shared engine (profile SCALP_OPENING_V1)."""
    from ..analytics import session_engine as se
    return [(w["session"], w["start"], w["end"]) for w in se.windows(PROFILE, day_utc, 1, 0)]


LEGACY_STATE = {"SWEEP_HIGH": "SWEEP_HIGH", "SWEEP_LOW": "SWEEP_LOW", "SWEEP_BOTH_AMBIGUOUS": "SWEEP_BOTH_AMBIGUOUS", "BREAKOUT_UP": "BREAK_HIGH",
                "BREAKOUT_DOWN": "BREAK_LOW"}


def boxes_as_of(bars: list[dict], tf_minutes: int, as_of, instrument: str = "XAUUSD") -> list[dict]:
    """Latest COMPLETED box of each session (end <= as_of) from closed bars {open_utc, h, l, c} + its edge events (shared engine).
    status OK only for a FINAL (complete) box; INCOMPLETE / NO_BARS otherwise (a single bar never makes a full box)."""
    from ..analytics import session_engine as se
    t = _t(as_of)
    boxes = se.build(bars, tf_minutes * 60, PROFILE, instrument, t, days=2)
    out = []
    for name in SESSIONS:
        done = [b for b in boxes if b["session"] == name and _t(b["end_utc"]) <= t]
        if not done:
            continue
        b = max(done, key=lambda x: x["end_utc"])
        base = {"session": name, "start_utc": b["start_utc"], "end_utc": b["end_utc"], "box_id": b["box_id"], "profile_id": PROFILE,
                "coverage": {k: b.get(k) for k in ("expected_slots", "observed_slots", "missing_slots", "coverage_ratio", "coverage_basis")},
                "version": VERSION, "engine": se.VERSION}
        if b["state"] == "NO_DATA":
            out.append(dict(base, status="NO_BARS"))
            continue
        if b["state"] == "INCOMPLETE":
            out.append(dict(base, status="INCOMPLETE", high=None, low=None, observed_high=b["observed_high"], observed_low=b["observed_low"],
                            bars=b["bars"], state="UNKNOWN", reason=b["reason"]))
            continue
        first = next((e for e in b["events"] if e["kind"] != "RETURN_INSIDE_AFTER_BREAK"), None)
        out.append(dict(base, known_at=b["known_at"], high=b["final_high"], low=b["final_low"], bars=b["bars"], revision=b["revision"],
                        state=LEGACY_STATE.get(first["kind"], first["kind"]) if first else "UNTOUCHED", state_at=first["bar_open_utc"] if first else None,
                        events=b["events"], edges=b["edges"], expires_at=b.get("expires_at"), status="OK"))
    return out
