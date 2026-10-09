"""Data quality gate (M01 role in the live application).

Why not the legacy M01_AUDIT for live data: it marks *any* gap among the last 14 bars as
PENDING and requires 230 bars on every timeframe. With a daily gold session break and weekends,
H1/H4 would be blocked for most of the day. Here gaps are classified using a session model learned
from the broker's own H1 history (recurring missing server hours = session break) and the calendar
(weekend). Unexplained gaps remain visible and block entries on the affected timeframe.

Outputs per-timeframe status and global gates:
  analysis_allowed - engine may compute (bars valid, time verified or stored)
  entries_allowed  - new entries may be considered (fresh quote, verified time, market open,...)
"""
from __future__ import annotations

import math
from collections import Counter
from datetime import datetime, timedelta

from ..timeutil import TF_SECONDS, TIMEFRAMES, from_epoch, iso, parse_iso

FIX_HISTORY = ("Otwórz w MT5 wykres {sym} {tf}, przewiń go w lewo (Home) aż do pobrania historii; "
               "sprawdź Narzędzia → Opcje → Wykresy → 'Maks. liczba słupków na wykresie' (min. 5000).")


class SessionModel:
    """Recurring broker break hours (server time) learned from H1 history, plus weekend rule."""

    def __init__(self, h1_raw_opens: list[int]):
        self.break_hours: set[int] = set()
        self.trading_days_seen = 0
        days: dict[str, set[int]] = {}
        for t in h1_raw_opens:
            d = from_epoch(t)
            if d.weekday() >= 5:
                continue
            days.setdefault(d.strftime("%Y-%m-%d"), set()).add(d.hour)
        full = [h for k, h in days.items()]
        if len(full) >= 5:
            self.trading_days_seen = len(full)
            counts = Counter(h for hs in full for h in hs)
            # an hour missing on >= 80% of observed weekdays is a recurring break
            self.break_hours = {h for h in range(24) if counts.get(h, 0) <= 0.2 * len(full)}

    def classify_gap(self, prev_raw: int, next_raw: int, tf_sec: int) -> str:
        start = prev_raw + tf_sec
        end = next_raw  # missing interval [start, end)
        t = start
        while t < end and t < start + 21 * 86400:
            if from_epoch(t).weekday() >= 5:
                return "WEEKEND"
            t += 3600
        if self.break_hours:
            hours = {from_epoch(t).hour for t in range(start, end, 60 if tf_sec < 3600 else 3600)}
            if hours and hours <= self.break_hours:
                return "SESSION_BREAK"
        if tf_sec == 60 and (end - start) <= 3 * 60:
            return "NO_TICK_MINUTES"
        return "UNEXPLAINED"

    def market_closed_reason(self, server_now: datetime) -> str | None:
        if server_now.weekday() >= 5:
            return "CLOSED_WEEKEND"
        if server_now.hour in self.break_hours:
            return "CLOSED_SESSION_BREAK"
        return None

    def as_dict(self) -> dict:
        return {"break_hours_server": sorted(self.break_hours), "trading_days_seen": self.trading_days_seen}


def _finite(*xs) -> bool:
    return all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in xs)


def assess_tf(tf: str, bars: list[dict], required: int, now: datetime, offset: int | None, session: SessionModel,
              market_open: bool, symbol: str) -> dict:
    sec = TF_SECONDS[tf]
    reasons: list[str] = []
    closed = [b for b in bars if b["closed"]]
    invalid = [b["t_raw"] for b in bars if not (_finite(b["o"], b["h"], b["l"], b["c"]) and b["l"] > 0
                                                and b["l"] <= min(b["o"], b["c"]) <= max(b["o"], b["c"]) <= b["h"])]
    neg_vol = [b["t_raw"] for b in bars if b["tv"] < 0]
    raws = [b["t_raw"] for b in bars]
    dups = len(raws) - len(set(raws))
    nonmono = sum(1 for a, b in zip(raws, raws[1:]) if b <= a)
    gaps = []
    for a, b in zip(bars, bars[1:]):
        if tf == "D1":
            continue
        step = b["t_raw"] - a["t_raw"]
        if step > sec:
            kind = session.classify_gap(a["t_raw"], b["t_raw"], sec)
            gaps.append({"from_raw": a["t_raw"] + sec, "to_raw": b["t_raw"], "missing_bars": step // sec - 1, "kind": kind})
    recent_cut = bars[-30]["t_raw"] if len(bars) >= 30 else (bars[0]["t_raw"] if bars else 0)
    recent_unexplained = [g for g in gaps if g["kind"] == "UNEXPLAINED" and g["to_raw"] >= recent_cut]
    future = []
    if offset is not None:
        future = [b["t_raw"] for b in bars if from_epoch(b["t_raw"] - offset) > now + timedelta(seconds=60)]
    status = "OK"
    if not bars:
        status = "NO_DATA"
        reasons.append("NO_BARS_FROM_TERMINAL")
    elif invalid or neg_vol or dups or nonmono:
        status = "INVALID"
        reasons += (["INVALID_OHLC"] if invalid else []) + (["NEGATIVE_TICK_VOLUME"] if neg_vol else []) + \
                   (["DUPLICATE_BARS"] if dups else []) + (["NON_MONOTONIC_BARS"] if nonmono else [])
    elif future:
        status = "TIME_ERROR"
        reasons.append("FUTURE_BAR_TIMESTAMP")
    elif len(closed) < required:
        status = "INSUFFICIENT_HISTORY"
        reasons.append(f"CLOSED_BARS_{len(closed)}_LT_REQUIRED_{required}")
    stale = False
    if bars and offset is not None and market_open:
        forming_open = from_epoch(bars[-1]["t_raw"] - offset)
        age = (now - forming_open).total_seconds()
        if age > sec + 180:
            stale = True
            reasons.append("BARS_NOT_UPDATING")
            if status == "OK":
                status = "STALE"
    if recent_unexplained:
        reasons.append("RECENT_UNEXPLAINED_GAP")
        if status == "OK":
            status = "DEGRADED"
    hint = FIX_HISTORY.format(sym=symbol, tf=tf) if status in ("INSUFFICIENT_HISTORY", "NO_DATA") else None
    return {"tf": tf, "status": status, "closed_bars": len(closed), "required": required, "bars_total": len(bars),
            "last_closed_raw": closed[-1]["t_raw"] if closed else None,
            "last_closed_available_at": closed[-1].get("available_at") if closed else None,
            "forming_open_raw": bars[-1]["t_raw"] if bars and not bars[-1]["closed"] else None,
            "invalid_bars": len(invalid), "duplicates": dups, "non_monotonic": nonmono, "future_bars": len(future),
            "gaps": gaps[-10:], "gap_counts": dict(Counter(g["kind"] for g in gaps)), "stale": stale,
            "reasons": reasons, "fix_hint": hint}


def assess(*, symbol: str, bars_by_tf: dict[str, list[dict]], required: dict[str, int], quote: dict | None,
           clock: dict, connection_state: str, now: datetime, max_quote_age: float,
           pc_clock: dict | None = None, symbol_status: str = "UNKNOWN") -> dict:
    offset = clock.get("offset_seconds") if clock.get("status") in ("VERIFIED", "STORED_UNVERIFIED") else None
    session = SessionModel([b["t_raw"] for b in bars_by_tf.get("H1", [])])
    reasons: list[str] = []
    # ---- market / quote
    quote_fresh = bool(quote and quote.get("age_seconds") is not None and quote["age_seconds"] <= max_quote_age)
    tick_ahead = bool(quote and quote.get("source_age_seconds") is not None and quote["source_age_seconds"] < -5)
    server_now = now + timedelta(seconds=offset) if offset is not None else None
    if connection_state != "CONNECTED":
        market_state = "UNKNOWN_DISCONNECTED"
    elif quote_fresh and not tick_ahead:
        market_state = "OPEN"
    else:
        closed_reason = session.market_closed_reason(server_now) if server_now else None
        market_state = closed_reason or "NO_FRESH_TICKS"
    market_open = market_state == "OPEN"
    per_tf = {tf: assess_tf(tf, bars_by_tf.get(tf, []), required.get(tf, 0), now, offset, session, market_open, symbol)
              for tf in TIMEFRAMES}
    # ---- global reasons
    if connection_state != "CONNECTED":
        reasons.append("MT5_" + connection_state)
    if symbol_status not in ("OK",):
        reasons.append("SYMBOL_" + symbol_status)
    if clock.get("status") != "VERIFIED":
        reasons.append("TIME_OFFSET_" + str(clock.get("status")))
    if tick_ahead:
        reasons.append("BROKER_TICK_AHEAD_OF_UTC")
    if not quote:
        reasons.append("NO_QUOTE")
    elif not quote_fresh:
        reasons.append("QUOTE_STALE")
    if market_state != "OPEN":
        reasons.append("MARKET_" + market_state)
    if pc_clock and pc_clock.get("status") == "SKEW":
        reasons.append("PC_CLOCK_SKEW")
    bad = [tf for tf, r in per_tf.items() if r["status"] in ("INVALID", "TIME_ERROR", "NO_DATA")]
    warming = [tf for tf, r in per_tf.items() if r["status"] == "INSUFFICIENT_HISTORY"]
    degraded = [tf for tf, r in per_tf.items() if r["status"] in ("STALE", "DEGRADED")]
    for tf in bad:
        reasons.append(f"{tf}_{per_tf[tf]['status']}")
    for tf in warming:
        reasons.append(f"{tf}_INSUFFICIENT_HISTORY")
    for tf in degraded:
        reasons.append(f"{tf}_{per_tf[tf]['status']}")
    analysis_allowed = connection_state == "CONNECTED" and offset is not None and not bad and not tick_ahead
    entries_allowed = (analysis_allowed and clock.get("status") == "VERIFIED" and market_open and quote_fresh
                       and not warming and not degraded and symbol_status == "OK"
                       and not (pc_clock and pc_clock.get("status") == "SKEW"))
    if bad or (connection_state != "CONNECTED") or offset is None:
        dq = "BAD"
    elif warming or degraded or not entries_allowed:
        dq = "DEGRADED"
    else:
        dq = "GOOD"
    return {"data_quality": dq, "analysis_allowed": analysis_allowed, "entries_allowed": entries_allowed,
            "market_state": market_state, "server_now": iso(server_now) if server_now else None,
            "quote_fresh": quote_fresh, "timeframes": per_tf, "session_model": session.as_dict(),
            "reason_codes": sorted(set(reasons)), "warming_up": warming, "assessed_at": iso(now)}


def tf_status_message(r: dict) -> str:
    st = r["status"]
    if st == "OK":
        return "OK"
    if st == "INSUFFICIENT_HISTORY":
        return f"WARMING_UP: {r['closed_bars']}/{r['required']} zamkniętych świec"
    return st


__all__ = ["assess", "SessionModel", "tf_status_message", "parse_iso", "datetime"]
