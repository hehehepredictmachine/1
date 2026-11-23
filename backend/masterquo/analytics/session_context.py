"""Session Context Clock (Apollo23 TASK 008) + Multi-Session Range Boxes with Spread / StopsLevel / ATR HUD (TASK 009).

READ-ONLY / OBSERVABILITY_ONLY: nothing here changes session sweep boxes, scalp session filters, risk, rankers or order routing.

Distinct concepts, never conflated:
  * named liquidity sessions (Sydney / Tokyo / London / New York) - global time-of-day windows in IANA zones with DST,
  * venue trading state of the exact symbol (UNKNOWN unless an authoritative calendar is configured),
  * broker server clock (MT5 ServerClock evidence; UNKNOWN / MEASURING / STORED_UNVERIFIED / INCONSISTENT are shown as such),
  * chart bar schedule (candle countdown), and
  * broker-server-hour range boxes (TASK 009: fixed server hours, applied to the broker's raw bar time - NOT IANA sessions).

PMW convention (TASK 008, declared - no parity claim with the MQL5 CodeBase #79485 source): the listing's northern-winter GMT opening
hours 21/00/08/13 correspond to LOCAL opening hours Sydney 08:00, Tokyo 09:00, London 08:00, New York 08:00; each session lasts 9 h and
follows its own zone's DST. FIXED_GMT mode uses the entered GMT hours literally. Status CONFIGURED_UNVERIFIED.
"""
from __future__ import annotations

import math
from datetime import datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

SCHEMA_VERSION = "session_context.v1"
ENGINE_VERSION = "PMW-SESSION-CTX-1"
UTC = timezone.utc

SESSIONS = (
    {"id": "SYDNEY", "zone": "Australia/Sydney", "local_open": "08:00", "gmt_winter_open": 21},
    {"id": "TOKYO", "zone": "Asia/Tokyo", "local_open": "09:00", "gmt_winter_open": 0},
    {"id": "LONDON", "zone": "Europe/London", "local_open": "08:00", "gmt_winter_open": 8},
    {"id": "NEW_YORK", "zone": "America/New_York", "local_open": "08:00", "gmt_winter_open": 13},
)
DURATION = timedelta(hours=9)
TF_SECONDS = {"M1": 60, "M3": 180, "M5": 300, "M10": 600, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "H8": 28800, "D1": 86400}

# TASK 009 broker-server-hour boxes (server time, not IANA): Asia 00-08, London 08-14, New York 14-21; end < start = overnight wrap
SERVER_BOXES = ({"id": "ASIA", "start": "00:00", "end": "08:00"}, {"id": "LONDON", "start": "08:00", "end": "14:00"},
                {"id": "NEW_YORK", "start": "14:00", "end": "21:00"})


def _hm(s: str) -> dtime:
    h, m = (int(x) for x in s.split(":"))
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ValueError(f"INVALID_TIME: {s}")
    return dtime(h, m)


def _iso(d: datetime | None) -> str | None:
    return d.astimezone(UTC).isoformat().replace("+00:00", "Z") if d else None


# ---------------------------------------------------------------- TASK 008: named sessions
def session_window(sdef: dict, as_of: datetime, mode: str = "AUTO_DST") -> dict:
    """The occurrence of the session that is active at as_of, else the next one. Half-open [open, close)."""
    as_of = as_of.astimezone(UTC)
    cands = []
    if mode == "FIXED_GMT":
        for d in (-1, 0, 1):
            day = (as_of + timedelta(days=d)).date()
            o = datetime.combine(day, dtime(sdef["gmt_winter_open"] % 24), UTC)
            cands.append((o, o + DURATION))
    else:
        z = ZoneInfo(sdef["zone"])
        loc = as_of.astimezone(z)
        for d in (-1, 0, 1):
            day = (loc + timedelta(days=d)).date()
            o = datetime.combine(day, _hm(sdef["local_open"]), z).astimezone(UTC)
            cands.append((o, o + DURATION))
    cands.sort()
    active = next(((o, c) for o, c in cands if o <= as_of < c), None)
    nxt = next(((o, c) for o, c in cands if o > as_of), None)
    o, c = active or nxt
    z = ZoneInfo(sdef["zone"])
    return {"id": sdef["id"], "zone": sdef["zone"], "open_utc": _iso(o), "close_utc": _iso(c), "is_active": active is not None,
            "next_transition_utc": _iso(c if active else o), "next_transition": "CLOSE" if active else "OPEN",
            "seconds_to_transition": int(((c if active else o) - as_of).total_seconds()),
            "local_label": f"{o.astimezone(z):%H:%M}–{c.astimezone(z):%H:%M} {o.astimezone(z).tzname()}",
            "utc_offset_hours": o.astimezone(z).utcoffset().total_seconds() / 3600, "mode": mode,
            "definition_source": "PMW_CONVENTION (lokalna godzina otwarcia z domyślnych 21/00/08/13 GMT zimą, 9 h)" if mode == "AUTO_DST"
            else "FIXED_GMT (godziny wpisane dosłownie)", "quality": "CONFIGURED_UNVERIFIED"}


def sessions(as_of: datetime, mode: str = "AUTO_DST") -> list[dict]:
    if mode not in ("AUTO_DST", "FIXED_GMT"):
        raise ValueError("mode: AUTO_DST | FIXED_GMT")
    return [session_window(s, as_of, mode) for s in SESSIONS]


# ---------------------------------------------------------------- candle countdown
def candle(tf: str, as_of: datetime, last_bar_open_utc: datetime | None = None, server_offset_seconds: int | None = None) -> dict:
    sec = TF_SECONDS.get(tf)
    if not sec:
        return {"timeframe": tf, "quality": "UNKNOWN", "reason": "UNKNOWN_TIMEFRAME"}
    as_of = as_of.astimezone(UTC)
    ep = as_of.timestamp()
    # 1.46: the schedule was always the UTC grid, but MT5 bars are anchored on the broker SERVER clock (D1 / H4 / H8 open at server
    # midnight = 22:00 UTC at UTC+2), so open/close/countdown of H4/H8/D1 were off by the server offset. Anchor, best evidence
    # first: VERIFIED server offset > open of the last MT5 bar of this TF > UTC grid (for H4/H8/D1 flagged TIME_MAPPING_UNVERIFIED).
    if server_offset_seconds is not None:
        anchor, basis = -float(server_offset_seconds), "BROKER_SERVER_CLOCK_VERIFIED"
    elif last_bar_open_utc is not None:
        anchor, basis = last_bar_open_utc.astimezone(UTC).timestamp(), "LAST_MT5_BAR_OPEN"
    else:
        anchor, basis = 0.0, "UTC_GRID"
    o = datetime.fromtimestamp(anchor + math.floor((ep - anchor) / sec) * sec, UTC)
    c = o + timedelta(seconds=sec)
    q = "CONFIGURED_UNVERIFIED"
    reason = {"BROKER_SERVER_CLOCK_VERIFIED": "ciągły harmonogram czasu serwera (offset VERIFIED)",
              "LAST_MT5_BAR_OPEN": "ciągły harmonogram od otwarcia ostatniej świecy MT5",
              "UTC_GRID": "ciągły harmonogram UTC"}[basis] + "; przerwy rynku nie są znane bez kalendarza venue"
    if basis == "UTC_GRID" and sec > 3600:
        q, reason = "TIME_MAPPING_UNVERIFIED", "H4/H8/D1 liczone od siatki UTC – świece MT5 zaczynają się o północy czasu serwera, offset niezweryfikowany"
    if last_bar_open_utc is not None and (as_of - last_bar_open_utc.astimezone(UTC)).total_seconds() > 2 * sec:
        q, reason = "STALE", "ostatnia świeca jest starsza niż 2 interwały – rynek zamknięty albo brak danych"
    return {"timeframe": tf, "open_utc": _iso(o), "close_utc": _iso(c), "seconds_remaining": None if q == "STALE" else int((c - as_of).total_seconds()),
            "progress": None if q == "STALE" else round((as_of - o).total_seconds() / sec, 4), "is_final": False, "quality": q, "reason": reason,
            "time_basis": basis}


# ---------------------------------------------------------------- spread / ADR14
def spread(quote: dict | None, ttl_s: float = 15.0) -> dict:
    if not quote:
        return {"current_points": None, "average_points": None, "quality": "UNKNOWN", "reason": "NO_QUOTE", "source": None}
    age = quote.get("age_seconds")
    q = "STALE" if age is None or age > ttl_s else "VERIFIED"
    pts = quote.get("spread_points")
    return {"current_points": pts if q != "STALE" else None, "last_points": pts, "unit": "points", "source": "MT5_BROKER_QUOTE",
            "as_of": quote.get("received_at"), "age_seconds": age,
            "quality": "UNKNOWN" if pts is None else q, "reason": "POINT_SIZE_UNKNOWN" if pts is None else None,
            "average_points": None, "average_reason": "AVERAGE_NOT_CONFIGURED", "sample_count": 0, "window": None}


def daily_range(d1_bars: list[dict]) -> dict:
    """today = last (forming) D1 bar; ADR14 = mean(high-low) of the previous 14 COMPLETED daily bars of the same symbol/provider."""
    if not d1_bars:
        return {"quality": "UNKNOWN", "reason": "NO_DAILY_BARS"}
    today = d1_bars[-1]
    done = [b for b in d1_bars[:-1] if b.get("closed", True)][-14:]
    tr = float(today["h"]) - float(today["l"])
    out = {"today_range": round(tr, 10), "completed_days_used": len(done), "session_boundary": "MT5 D1 (czas serwera brokera)", "source": "MT5_D1"}
    rngs = [float(b["h"]) - float(b["l"]) for b in done]
    if len(done) < 14 or any(r <= 0 for r in rngs):
        return {**out, "adr14": None, "percent_of_adr14": None, "quality": "INCOMPLETE",
                "reason": f"ukończonych dni z poprawnym zakresem: {sum(r > 0 for r in rngs)}/14"}
    adr = sum(rngs) / 14
    return {**out, "adr14": round(adr, 10), "percent_of_adr14": round(100 * tr / adr, 2), "quality": "VERIFIED", "reason": None}


def server_clock(evidence: dict | None) -> dict:
    ev = evidence or {}
    st = ev.get("status") or "UNKNOWN"
    off = ev.get("offset_seconds")
    now = datetime.now(UTC)
    return {"status": st, "offset_seconds": off, "measured_at": ev.get("measured_at"),
            "value": _iso(now + timedelta(seconds=off)).replace("Z", " (czas serwera)") if off is not None and st == "VERIFIED" else None,
            "label": {"VERIFIED": "zweryfikowany", "MEASURING": "pomiar w toku", "STORED_UNVERIFIED": "zapisany, niezweryfikowany",
                      "INCONSISTENT": "niespójny", "UNKNOWN": "nieznany"}.get(st, st)}


def _verified_offset(evidence: dict | None) -> int | None:
    """Server offset (s) only when the MT5 ServerClock evidence is VERIFIED - a stored / measuring value is not used (1.46)."""
    ev = evidence or {}
    return ev.get("offset_seconds") if ev.get("status") == "VERIFIED" else None


def snapshot(*, instrument: str, timeframe: str, as_of: datetime, mode: str = "AUTO_DST", quote: dict | None = None,
             clock_evidence: dict | None = None, last_bar_open_utc: datetime | None = None, d1_bars: list[dict] | None = None,
             market_type: str = "FX_CFD", venue: str = "MT5") -> dict:
    return {"schema_version": SCHEMA_VERSION, "engine_version": ENGINE_VERSION, "as_of_utc": _iso(as_of), "computed_at_utc": _iso(datetime.now(UTC)),
            "instrument_id": instrument, "venue": venue, "market_type": market_type, "timeframe": timeframe, "gmt_now": _iso(as_of),
            "server_clock": server_clock(clock_evidence), "sessions": sessions(as_of, mode),
            "venue_state": {"state": "UNKNOWN", "reason": "brak autorytatywnego kalendarza venue – sesje miast nie oznaczają otwarcia rynku"},
            "underlying_state": {"state": "NOT_APPLICABLE"},
            "candle": candle(timeframe, as_of, last_bar_open_utc, _verified_offset(clock_evidence)),   # 1.46: server-clock anchored
            "spread": spread(quote), "daily_range": daily_range(d1_bars or []), "calendar_id": None, "calendar_version": None,
            "warnings": ["Sesje Sydney/Tokio/Londyn/Nowy Jork to okna czasu, nie stan otwarcia rynku symbolu."],
            "mode": "READ_ONLY"}


# ---------------------------------------------------------------- TASK 009: broker-server-hour range boxes + HUD
def _server_day_minutes(t_raw: int) -> tuple[int, int]:
    """t_raw = broker server time as epoch seconds (MT5 bar time): returns (server day index, minute of server day)."""
    return t_raw // 86400, (t_raw % 86400) // 60


def range_boxes(bars: list[dict], boxes=SERVER_BOXES, history_days: int = 5, tf_seconds: int = 300) -> list[dict]:
    """High/low per configured server-hour window, built ONLY from closed bars whose server time falls inside the window. Overnight wraps
    (end <= start) belong to the day on which the window starts. Partial (still running) windows are marked ACTIVE."""
    out = []
    closed = [b for b in bars if b.get("closed", True) and b.get("t_raw") is not None]
    if not closed:
        return out
    last_day = _server_day_minutes(int(closed[-1]["t_raw"]))[0]
    for bx in boxes:
        s, e = _hm(bx["start"]), _hm(bx["end"])
        sm, em = s.hour * 60 + s.minute, e.hour * 60 + e.minute
        wrap = em <= sm
        groups: dict[int, list[dict]] = {}
        for b in closed:
            day, minute = _server_day_minutes(int(b["t_raw"]))
            end_min = minute + max(1, tf_seconds // 60)                # a bar must fit inside the window
            if not wrap and sm <= minute and end_min <= em:
                groups.setdefault(day, []).append(b)
            elif wrap and minute >= sm:
                groups.setdefault(day, []).append(b)
            elif wrap and end_min <= em:
                groups.setdefault(day - 1, []).append(b)
        for day in sorted(groups)[-history_days:]:
            g = groups[day]
            start_raw = day * 86400 + sm * 60
            end_raw = (day + (1 if wrap else 0)) * 86400 + em * 60
            last_end = int(g[-1]["t_raw"]) + tf_seconds
            missing_start = int(g[0]["t_raw"]) >= start_raw + tf_seconds          # history begins inside the window
            state = ("INCOMPLETE" if missing_start else "COMPLETE" if last_end >= end_raw else
                     ("ACTIVE" if day >= last_day - (1 if wrap else 0) else "INCOMPLETE"))
            out.append({"box": bx["id"], "server_day": day, "start_raw": start_raw, "end_raw": end_raw, "high": max(float(b["h"]) for b in g),
                        "low": min(float(b["l"]) for b in g), "bars": len(g), "state": state, "time_basis": "BROKER_SERVER_TIME"})
    return sorted(out, key=lambda r: (r["start_raw"], r["box"]))


def atr14(bars: list[dict], n: int = 14) -> float | None:
    from .ta import atr14 as _atr
    closed = [b for b in bars if b.get("closed", True)]
    if len(closed) < n + 1:
        return None
    v = _atr([float(b["h"]) for b in closed], [float(b["l"]) for b in closed], [float(b["c"]) for b in closed], n)[-1]
    return v


def hud(quote: dict | None, meta: dict | None, bars: list[dict], clock_evidence: dict | None) -> dict:
    point = (meta or {}).get("point")
    stops = (meta or {}).get("trade_stops_level")
    a = atr14(bars)
    sp = spread(quote)
    ev = clock_evidence or {}
    return {"spread_points": sp["current_points"], "spread_quality": sp["quality"],
            "stops_level_points": stops, "stops_level_quality": "VERIFIED" if stops is not None else "UNKNOWN",
            "atr14": a, "atr14_points": round(a / point, 1) if (a is not None and point) else None, "point": point,
            "time_mapping": "VERIFIED" if ev.get("status") == "VERIFIED" else "TIME_MAPPING_UNVERIFIED",
            "note": "punkt (point) ≠ trade_tick_size; jednostki zachowane; tylko obserwacja"}
