"""Etap 4 (1.46.0, gałąź claude/architektura-modele-146) - rdzeń kontroli jakości danych (PMW-DQ-CORE-1).

ETAP2 §4 „Jakość danych”: wspólny rdzeń czystych kontroli (geometria, kolejność, duplikaty, luki, świeżość) w data/quality.py, polityki per
tor bez zmian. Fala 2 (I0047 / I0051) przeniosła na rdzeń bramki ACTIVE i SH oraz klasyfikator luk raportów offline; tu pozostałe tory:
  * Quant snapshot QC (quant/snapshot.qc, stan notowania w build),
  * raporty offline: marketdata/quality (check_rows, report), forecast/export (geometria eksportu),
  * wejście Kronos / TSFM (kronos/quality.check), kroki prognozy Kronos (kronos/service), historia Monte Carlo (montecarlo/engine.history),
  * świeżość: SH (zamknięta świeca), ACTIVE (notowanie), find_gaps / classify_gap_series przez gap_pairs.
Każdy tor porównany z kodem sprzed zmiany (wyrocznie poniżej - kopie dosłowne HEAD) na losowych seriach ze stałym ziarnem (>= 200
przypadków), w tym z lukami, duplikatami, cofnięciami czasu, złą geometrią, NaN / inf / None / bool / tekstem - wynik i wyjątek identyczne.
"""
from __future__ import annotations

import ast
import hashlib
import math
import random
import re
import unittest
from collections import Counter
from datetime import datetime, timedelta, timezone
from itertools import pairwise

import _env

ROOT = _env.ROOT
BACKEND = ROOT / "backend" / "masterquo"
UTC = timezone.utc  # noqa: UP017 - the same constant as in the legacy oracles
NAN, INF = float("nan"), float("inf")


def _outcome(fn, *a, **kw):
    try:
        return ("ok", repr(fn(*a, **kw)))
    except Exception as exc:  # noqa: BLE001 - the exception type and text are part of the parity
        return ("raise", type(exc).__name__, str(exc))


# ============================================================================================ random inputs
def _price_tuple(rnd, faults: bool, *, bad=(NAN, INF, -INF, -1.0, 0.0)):
    """(o, h, l, c) - mostly a valid bar; with faults: tolerance edges, crossed bounds, swapped h / l, bad values."""
    o = 2400 + rnd.uniform(-5, 5)
    c = o + rnd.uniform(-2, 2)
    h, lo = max(o, c) + rnd.uniform(0, 1), min(o, c) - rnd.uniform(0, 1)
    if faults:
        k = rnd.random()
        if k < 0.08:
            h = max(o, c) - rnd.choice((0.0, 4e-10, 9e-10, 1.1e-9, 3e-9, 1e-6, 0.5))          # high just below the body
        elif k < 0.16:
            lo = min(o, c) + rnd.choice((0.0, 4e-10, 9e-10, 1.1e-9, 3e-9, 1e-6, 0.5))         # low just above the body
        elif k < 0.20:
            h, lo = lo, h                                                                       # swapped
        elif k < 0.24:
            c = h + rnd.choice((0.1, 1.0))                                                      # close above high
        elif k < 0.27:
            o, h, lo, c = (round(x) for x in (o, h, lo, c))                                     # ints
        elif k < 0.29:
            o, h, lo, c = 1e308, 1.7e308, 1e308, 1.5e308                                        # huge (slack overflow)
        if rnd.random() < 0.10:
            vals = [o, h, lo, c]
            vals[rnd.randrange(4)] = rnd.choice(bad)
            o, h, lo, c = vals
    return o, h, lo, c


def _times(rnd, n: int, step: int, t0: float, faults: bool, *, floats: bool = False) -> list:
    out, t = [], t0
    for _ in range(n):
        if faults and rnd.random() < 0.12:
            t += rnd.choice((0, -step, 2 * step, 3 * step, 1.5 * step, 1.5 * step + 1, 30 * step, 2 * 86400, 2 * 86400 + 3600, 3 * 86400,
                             5 * 86400, 7 * 3600, step + 7))
        else:
            t += step
        out.append(float(t) if floats else int(t))
    return out


# ============================================================================================ legacy oracles (HEAD before Etap 4, verbatim)
def _legacy_find_gaps(times, tf_sec, classify):
    out = []
    for a, b in pairwise(times):
        step = b - a
        if step > tf_sec:
            out.append({"from_raw": a + tf_sec, "to_raw": b, "missing_bars": step // tf_sec - 1, "kind": classify(a, b, tf_sec)})
    return out


def _legacy_classify_gap_series(times, step, *, weekend_min_s, weekend_probe_s, break_max_s, recurring_min_days=None, recurring_share=0.0,
                                recurring_min_missing=3, short_max_missing=None, gap_if_not_step=False):
    gaps = [(a, b) for a, b in pairwise(times) if (b - a != step if gap_if_not_step else b - a > step)]

    def start_key(a):
        return ((a + step) % 86400) // step * step
    recurring: set = set()
    if recurring_min_days is not None:
        days = {datetime.fromtimestamp(t, UTC).date() for t in times}
        starts = Counter(start_key(a) for a, b in gaps if b - a <= break_max_s + step and (b - a) // step - 1 > recurring_min_missing)
        recurring = {k for k, v in starts.items() if days and v >= max(recurring_min_days, recurring_share * len(days))}
    out = []
    for a, b in gaps:
        miss = (b - a) // step - 1
        if b - a >= weekend_min_s and any(datetime.fromtimestamp(a + k * weekend_probe_s, UTC).weekday() == 5
                                          for k in range(int((b - a) // weekend_probe_s) + 1)):
            kind = "WEEKEND"
        elif b - a <= break_max_s + step and (recurring_min_days is None or start_key(a) in recurring):
            kind = "BREAK"
        elif short_max_missing is not None and miss <= short_max_missing:
            kind = "SHORT"
        else:
            kind = "MISSING"
        out.append((a, b, kind, miss))
    return {"gaps": out, "recurring": recurring}


def _legacy_assess_tf(tf, bars, required, now, offset, session, market_open, symbol):
    """assess_tf before I0047 (verbatim, = HEAD behaviour - tests/test_arch146_w2_data_forecast_ui.py)."""
    from masterquo.data.quality import FIX_HISTORY, _finite
    from masterquo.timeutil import TF_SECONDS, from_epoch
    sec = TF_SECONDS[tf]
    reasons = []
    closed = [b for b in bars if b["closed"]]
    invalid = [b["t_raw"] for b in bars if not (_finite(b["o"], b["h"], b["l"], b["c"]) and b["l"] > 0
                                                and b["l"] <= min(b["o"], b["c"]) <= max(b["o"], b["c"]) <= b["h"])]
    neg_vol = [b["t_raw"] for b in bars if b["tv"] < 0]
    raws = [b["t_raw"] for b in bars]
    dups = len(raws) - len(set(raws))
    nonmono = sum(1 for a, b in pairwise(raws) if b <= a)
    gaps = []
    for a, b in pairwise(bars):
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


def _legacy_assess(*, symbol, bars_by_tf, required, quote, clock, connection_state, now, max_quote_age, pc_clock=None, symbol_status="UNKNOWN"):
    """data/quality.assess of HEAD (verbatim; the per-TF part is the legacy assess_tf above)."""
    from masterquo.data.quality import SessionModel
    from masterquo.timeutil import CONTEXT_TIMEFRAMES, CORE_TIMEFRAMES, TIMEFRAMES, iso
    offset = clock.get("offset_seconds") if clock.get("status") in ("VERIFIED", "STORED_UNVERIFIED") else None
    session = SessionModel([b["t_raw"] for b in bars_by_tf.get("H1", [])])
    reasons: list[str] = []
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
    per_tf = {tf: _legacy_assess_tf(tf, bars_by_tf.get(tf, []), required.get(tf, 0), now, offset, session, market_open, symbol)
              for tf in TIMEFRAMES}
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
    core = {tf: per_tf[tf] for tf in CORE_TIMEFRAMES}
    bad = [tf for tf, r in core.items() if r["status"] in ("INVALID", "TIME_ERROR", "NO_DATA")]
    warming = [tf for tf, r in core.items() if r["status"] == "INSUFFICIENT_HISTORY"]
    degraded = [tf for tf, r in core.items() if r["status"] in ("STALE", "DEGRADED")]
    context = {tf: per_tf[tf]["status"] for tf in CONTEXT_TIMEFRAMES}
    for tf, st in context.items():
        if st != "OK":
            reasons.append(f"CONTEXT_{tf}_{st}")
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
            "market_state": market_state, "server_now": server_now.replace(tzinfo=None).isoformat() if server_now else None,
            "server_tz_offset_s": offset,
            "quote_fresh": quote_fresh, "timeframes": per_tf, "context_timeframes": context, "session_model": session.as_dict(),
            "reason_codes": sorted(set(reasons)), "warming_up": warming, "assessed_at": iso(now)}


def _legacy_sh_data_quality(bars, quote, now, cfg):
    """sh/context.data_quality before I0047 (verbatim, = HEAD behaviour)."""
    from masterquo.sh.context import TF_S, _ts
    issues, ages = [], {}
    for tf, bs in bars.items():
        if not bs:
            issues.append(f"{tf}: brak świec")
            continue
        ts = [_ts(b["open_utc"]) for b in bs[-60:]]
        if any(b2 <= b1 for b1, b2 in pairwise(ts)):
            issues.append(f"{tf}: świece nieuporządkowane lub zdublowane")
        if any(not all(math.isfinite(float(b[k])) for k in ("o", "h", "l", "c")) or b["h"] < b["l"] for b in bs[-50:]):
            issues.append(f"{tf}: NaN/inf lub błędna geometria")
        close_t = ts[-1] + TF_S.get(tf, 60)
        ages[tf] = round(now - close_t, 1)
        if close_t > now + 1:
            issues.append(f"{tf}: ostatnia świeca nie jest zamknięta (forming) – odrzucona")
        elif now - close_t > cfg["max_bar_age_s"].get(tf, 3 * TF_S.get(tf, 60)):
            issues.append(f"{tf}: dane nieaktualne ({now - close_t:.0f} s od zamknięcia)")
    q_age = None
    spread = None
    if not quote:
        issues.append("brak notowania Bid/Ask")
    else:
        try:
            qt = float(quote.get("time") or 0.0)
        except (TypeError, ValueError):
            qt = 0.0
        spread = float(quote["ask"]) - float(quote["bid"])
        if not (math.isfinite(qt) and qt > 0):
            issues.append("brak znacznika czasu notowania")
        else:
            q_age = round(now - qt, 2)
            if q_age > cfg["max_quote_age_s"]:
                issues.append(f"notowanie nieaktualne ({q_age:.1f} s)")
        if spread < 0:
            issues.append("Ask < Bid")
        elif cfg.get("max_spread_usd") is not None and spread > cfg["max_spread_usd"]:
            issues.append(f"spread {spread:.3f} > limit {cfg['max_spread_usd']:.3f} USD")
    return {"status": "OK" if not issues else "BLOCK", "issues": issues, "bar_age_s": ages, "quote_age_s": q_age, "spread": spread}


# ---- quant/snapshot (HEAD, verbatim)
_LEGACY_WEEKEND_MAX_S = 4 * 86400


def _legacy_weekday_seconds(t0, t1):
    out, t = 0.0, t0
    while t < t1:
        day = math.floor(t / 86400.0)
        seg_end = min((day + 1) * 86400.0, t1)
        if (day + 3) % 7 < 5:
            out += seg_end - t
        t = seg_end
    return out


def _legacy_session_break(a_close, b_open, sec):
    span = b_open - a_close
    if span <= 0 or span > _LEGACY_WEEKEND_MAX_S:
        return False
    return _legacy_weekday_seconds(a_close, b_open) < sec


def _legacy_quant_qc(bars, tf, *, max_gap_report=20):
    from masterquo.timeutil import TF_SECONDS
    sec = TF_SECONDS.get(tf, 60)
    issues, gaps, bad = [], [], 0
    if not bars:
        return {"tf": tf, "n": 0, "status": "MISSING", "issues": ["NO_BARS"], "gaps": [], "gap_count": 0, "session_breaks": 0, "revised_bars": 0,
                "bars_without_spread": 0, "source": None, "volume_kind": "TICK_VOLUME (aktywność feedu, nie wolumen obrotu)", "last_close_t": None,
                "last_available_at": None}
    dup = sum(1 for a, b in pairwise(bars) if b["t"] == a["t"])
    unordered = sum(1 for a, b in pairwise(bars) if b["t"] < a["t"])
    breaks = 0
    for a, b in pairwise(bars):
        d = b["t"] - a["t"]
        if d > sec * 1.5:
            if _legacy_session_break(a["t"] + sec, b["t"], sec):
                breaks += 1
                continue
            gaps.append({"after": a["t"], "missing_bars": int(round(d / sec)) - 1})  # noqa: RUF046 - verbatim legacy code (oracle)
    for b in bars:
        vals = [b[k] for k in ("o", "h", "l", "c")]
        if any(v is None or isinstance(v, bool) or not math.isfinite(float(v)) for v in vals):
            bad += 1
            continue
        o, h, l_, c = (float(v) for v in vals)
        if not (h >= max(o, c) - 1e-9 and l_ <= min(o, c) + 1e-9 and h >= l_):
            bad += 1
    incomplete = sum(1 for b in bars if b["source"] == "RESAMPLED" and b["complete"] is False)
    revised = sum(1 for b in bars if (b.get("revision") or 0) > 0)
    no_spread = sum(1 for b in bars if b.get("spread_points") is None)
    if dup:
        issues.append(f"DUPLICATES:{dup}")
    if unordered:
        issues.append(f"UNORDERED:{unordered}")
    if bad:
        issues.append(f"OHLC_INVALID:{bad}")
    if incomplete:
        issues.append(f"RESAMPLED_INCOMPLETE:{incomplete}")
    if len(gaps) > 50:
        issues.append(f"GAPS:{len(gaps)}")
    status = "BLOCK" if (dup or unordered or bad) else ("DEGRADED" if incomplete or (gaps and len(gaps) > 50) else "OK")
    return {"tf": tf, "n": len(bars), "status": status, "issues": issues, "gaps": gaps[-max_gap_report:], "gap_count": len(gaps),
            "session_breaks": breaks, "revised_bars": revised, "bars_without_spread": no_spread,
            "source": sorted({b["source"] for b in bars}) or None, "volume_kind": "TICK_VOLUME (aktywność feedu, nie wolumen obrotu)",
            "last_close_t": bars[-1]["close_t"] if bars else None, "last_available_at": bars[-1]["available_at"] if bars else None}


# ---- marketdata/quality (HEAD, verbatim)
def _legacy_check_rows(rows):
    from masterquo.marketdata.store import iso
    ok, bad = [], []
    for r in rows:
        t, o, h, lo, c = r[0], r[1], r[2], r[3], r[4]
        if not (o > 0 and h > 0 and lo > 0 and c > 0 and h >= max(o, c) and lo <= min(o, c) and h >= lo):
            bad.append({"time_utc": iso(t), "ohlc": [o, h, lo, c], "reason": "nieprawidłowa geometria OHLC"})
        else:
            ok.append(r)
    return ok, bad


def _legacy_md_report(cols, tf, requested=None):
    from masterquo.marketdata.quality import _median, classify_gaps
    from masterquo.marketdata.store import TF_SECONDS, iso
    step = TF_SECONDS[tf]
    t = cols.get("time") or []
    n = len(t)
    unsorted = sum(1 for a, b in pairwise(t) if b <= a)
    dups = n - len(set(t))
    misaligned = sum(1 for x in t if x % step)
    invalid = 0
    for i in range(n):
        o, h, lo, c = cols["open"][i], cols["high"][i], cols["low"][i], cols["close"][i]
        if not (h >= max(o, c) and lo <= min(o, c) and lo > 0):
            invalid += 1
    gaps = classify_gaps(sorted(set(t)), step) if n > 1 else {}
    days = sorted({datetime.fromtimestamp(x, UTC).date().isoformat() for x in t})
    rep = {"timeframe": tf, "rows": n, "first_utc": iso(t[0]) if n else None, "last_utc": iso(t[-1]) if n else None,
           "trading_days": len(days), "order_violations": unsorted, "duplicates": dups, "misaligned_to_tf": misaligned,
           "invalid_ohlc": invalid, "gaps": gaps, "spread_points_median": _median(cols.get("spread") or []),
           "real_volume_nonzero_rows": sum(1 for v in cols.get("real_volume") or [] if v), "dst_ambiguous_rows": sum(cols.get("dst_ambiguous") or [])}
    if requested and requested[0] is not None and n:
        short = (t[0] - requested[0]) / 86400
        rep["history_shorter_than_requested_days"] = round(short, 1) if short > 1 else 0
    if n:
        expected = (t[-1] - t[0]) // step + 1
        rep["coverage_of_continuous_range"] = round(n / expected, 4) if expected else None
    rep["status"] = "OK" if not (unsorted or dups or misaligned or invalid) else "BŁĘDY"
    return rep


# ---- forecast/export and kronos/service (HEAD, verbatim expressions)
def _legacy_export_geometry_ok(o, h, lo, c):
    return o > 0 and h >= max(o, c) and lo <= min(o, c) and h >= lo


def _legacy_kronos_step_bad(o, h, low, c):
    return h < max(o, c) or low > min(o, c) or h < low


# ---- kronos/quality (HEAD, verbatim)
def _legacy_finite_pos(*xs):
    return all(isinstance(x, (int, float)) and math.isfinite(x) and x > 0 for x in xs)


def _legacy_kronos_check(bars, tf_sec, *, now_utc, lookback, min_context, calendar=None, volume_setting="AUTO", max_staleness_bars=2.0):
    from masterquo.kronos.quality import AMOUNT_PL, VOLUME_PL
    issues, status = [], "OK"

    def worse(s, why):
        nonlocal status
        order = {"OK": 0, "DEGRADED": 1, "STALE": 2, "WARMUP": 2, "BLOCK": 3}
        issues.append({"level": s, "reason": why})
        if order[s] > order[status]:
            status = s

    forming = sum(1 for b in bars if not b.get("closed"))
    rows = [b for b in bars if b.get("closed") and b.get("t_raw") is not None]
    rows.sort(key=lambda b: int(b["t_raw"]))
    dedup, dups, conflicts = [], 0, 0
    for b in rows:
        if dedup and int(dedup[-1]["t_raw"]) == int(b["t_raw"]):
            dups += 1
            if any(dedup[-1].get(k) != b.get(k) for k in ("o", "h", "l", "c")):
                conflicts += 1
            continue
        dedup.append(b)
    if conflicts:
        worse("BLOCK", f"{conflicts} zdublowanych świec o różnych cenach")
    window = dedup[-lookback:]
    invalid = []
    for b in window:
        o, h, l, c = (b.get(k) for k in ("o", "h", "l", "c"))
        if not _legacy_finite_pos(o, h, l, c):
            invalid.append(b.get("open_utc"))
            continue
        eps = 1e-9 * max(abs(h), 1.0)
        if h + eps < max(o, c) or l - eps > min(o, c) or h + eps < l:
            invalid.append(b.get("open_utc"))
    if invalid:
        worse("BLOCK", f"{len(invalid)} świec z niepoprawnym OHLC / brakującą wartością (pierwsza {invalid[0]})")
    n = len(window)
    if n < min_context:
        worse("WARMUP", f"{n} zamkniętych świec < minimum {min_context}")
    gaps = None
    if calendar is not None and n > 1:
        gaps = calendar.expected_missing([int(b["t_raw"]) for b in window], tf_sec)
        ratio = gaps["missing_open_slots"] / max(1, n)
        if ratio > 0.10:
            worse("BLOCK", f"luki: brak {gaps['missing_open_slots']} świec w otwartych slotach sesji ({ratio:.0%} okna)")
        elif ratio > 0.02:
            worse("DEGRADED", f"luki: brak {gaps['missing_open_slots']} świec w otwartych slotach sesji ({ratio:.1%} okna)")
    age = None
    if window:
        from masterquo.timeutil import parse_iso
        lo = window[-1].get("open_utc")
        if lo:
            close_t = parse_iso(lo).timestamp() + tf_sec
            age = now_utc - close_t
            if age > max_staleness_bars * tf_sec + 60:
                worse("STALE", f"ostatnia zamknięta świeca zamknęła się {int(age // 60)} min temu – rynek zamknięty, brak notowań albo MT5 rozłączony")
        else:
            worse("BLOCK", "brak czasu UTC świec (nieznany offset czasu serwera MT5)")
    rv_share = sum(1 for b in window if (b.get("rv") or 0) > 0) / max(1, n)
    tv_share = sum(1 for b in window if (b.get("tv") or 0) > 0) / max(1, n)
    if volume_setting == "NONE":
        vsrc = "NONE"
    elif volume_setting == "AUTO" and rv_share >= 0.9:
        vsrc = "REAL_VOLUME"
    elif tv_share >= 0.9:
        vsrc = "TICK_VOLUME"
    else:
        vsrc = "NONE"
        if volume_setting != "NONE":
            worse("DEGRADED", f"wolumen dostępny tylko na {tv_share:.0%} świec – prognoza bez wolumenu")
    return {"status": status, "issues": issues, "bars": window, "n": n, "forming_excluded": forming, "duplicates_dropped": dups,
            "invalid": len(invalid), "gaps": gaps, "last_close_age_s": None if age is None else round(age, 1),
            "volume_source": vsrc, "volume_source_pl": VOLUME_PL[vsrc],
            "amount_source": "SYNTHETIC_PROXY" if vsrc != "NONE" else "NONE", "amount_source_pl": AMOUNT_PL["SYNTHETIC_PROXY" if vsrc != "NONE" else "NONE"],
            "real_volume_share": round(rv_share, 3), "tick_volume_share": round(tv_share, 3)}


# ---- montecarlo/engine.history (HEAD, verbatim)
def _legacy_mc_history(bars, as_of, tf="M1", point=0.01, window=6000, stale_after_s=None):
    import numpy as np
    from masterquo.montecarlo.engine import TF_S, History, _ts, _weekend
    step = TF_S[tf]
    rows = []
    dropped = 0
    point_missing = False
    for b in bars:
        if not (b.get("open_utc") or b.get("t")):
            dropped += 1
            continue
        t = _ts(b.get("open_utc") or b.get("t"))
        if t + step > as_of + 1e-6:
            continue
        o, h, lo, c = (float(b[k]) for k in ("o", "h", "l", "c"))
        if not (o > 0 and h >= max(o, c) and lo <= min(o, c) and h >= lo and all(math.isfinite(x) for x in (o, h, lo, c))):
            dropped += 1
            continue
        sp = b.get("spread_price")
        if sp is None and b.get("spread") is not None:
            if point:
                sp = float(b["spread"]) * point
            else:
                point_missing = True
        rows.append((t, o, h, lo, c, float(sp) if sp is not None else math.nan))
    rows.sort(key=lambda r: r[0])
    rows = rows[-window:]
    if not rows:
        return History(tf, *(np.zeros(0) for _ in range(6)), flags=["NO_DATA"], dropped=dropped)
    a = np.array(rows, float)
    flags = []
    gaps = np.diff(a[:, 0])
    if (gaps > 3 * 86400).any():
        flags.append("LONG_GAP_IN_WINDOW")
    stale = stale_after_s if stale_after_s is not None else 10 * step
    if as_of - (a[-1, 0] + step) > stale and not _weekend(as_of):
        flags.append("STALE_LAST_BAR")
    rng = a[:, 2] - a[:, 3]
    med = float(np.median(rng)) if len(rng) else 0.0
    jumps = np.abs(a[1:, 1] - a[:-1, 4])
    if med > 0 and (jumps > 25 * med).any():
        flags.append("PRICE_JUMP_GT_25_MEDIAN_RANGES")
    if not np.isfinite(a[:, 5]).any():
        flags.append("NO_SPREAD_DATA")
    if point_missing:
        flags.append("POINT_UNKNOWN")
    hsh = hashlib.sha256(a.tobytes()).hexdigest()[:16]
    return History(tf, a[:, 0], a[:, 1], a[:, 2], a[:, 3], a[:, 4], a[:, 5], flags=flags, dropped=dropped, data_hash=hsh)


# ============================================================================================ core primitives
class TestDqCorePrimitives(unittest.TestCase):
    NAMES = ("finite_values", "prices_positive", "ohlc_ordered", "ohlc_crossed", "repeat_count", "step_back_count", "gap_pairs",
             "weekday_seconds", "weekend_closure", "is_forming", "is_stale", "age_within",
             # fala 2 (I0047 / I0051)
             "ohlc_finite", "geometry_ok", "order_violations", "duplicate_count", "find_gaps", "classify_gap_series")

    def test_core_exports(self):
        from masterquo.data import quality as Q
        for name in self.NAMES:
            self.assertTrue(callable(getattr(Q, name, None)), name)
            self.assertIn(name, Q.__all__)
        self.assertEqual(Q.FINITE_MODES, ("real", "number", "coerce", "lenient"))
        with self.assertRaises(ValueError):
            Q.finite_values(1.0, mode="nope")

    def test_finite_modes_same_as_the_track_expressions(self):
        from masterquo.data import quality as Q
        legacy = {"real": lambda *xs: Q._finite(*xs),
                  "number": lambda *xs: all(isinstance(x, (int, float)) and math.isfinite(x) for x in xs),
                  "coerce": lambda *xs: all(math.isfinite(float(x)) for x in xs),
                  "lenient": lambda *xs: not any(v is None or isinstance(v, bool) or not math.isfinite(float(v)) for v in xs)}
        pool = (1.0, 2400.5, 0, -3, NAN, INF, -INF, None, True, False, "2400.5", "abc", "nan", 10**400, 1e308)
        rnd = random.Random(401)
        for case in range(600):
            xs = tuple(rnd.choice(pool) for _ in range(rnd.choice((1, 2, 4))))
            for mode, fn in legacy.items():
                self.assertEqual(_outcome(Q.finite_values, *xs, mode=mode), _outcome(fn, *xs), f"case {case} {mode} {xs}")

    def test_geometry_primitives_on_random_bars(self):
        from masterquo.data import quality as Q
        rnd = random.Random(402)
        for case in range(3000):
            o, h, lo, c = _price_tuple(rnd, True)
            self.assertEqual(Q.ohlc_ordered(o, h, lo, c), h >= max(o, c) and lo <= min(o, c) and h >= lo, case)
            self.assertEqual(Q.ohlc_ordered(o, h, lo, c, tol=1e-9), h >= max(o, c) - 1e-9 and lo <= min(o, c) + 1e-9 and h >= lo, case)
            self.assertEqual(Q.ohlc_crossed(o, h, lo, c), h < max(o, c) or lo > min(o, c) or h < lo, case)
            if Q.finite_values(o, h, lo, c, mode="number"):
                eps = 1e-9 * max(abs(h), 1.0)
                self.assertEqual(Q.ohlc_crossed(o, h, lo, c, slack=eps), h + eps < max(o, c) or lo - eps > min(o, c) or h + eps < lo, case)
            self.assertEqual(Q.prices_positive(o, h, lo, c), o > 0 and h > 0 and lo > 0 and c > 0, case)

    def test_order_and_gap_primitives(self):
        from masterquo.data import quality as Q
        rnd = random.Random(403)
        for case in range(400):
            step = rnd.choice((60, 300, 3600, 86400))
            ts = _times(rnd, rnd.choice((0, 1, 2, 30, 200)), step, 1_793_000_000, True, floats=rnd.random() < 0.3)
            self.assertEqual(Q.repeat_count(ts), sum(1 for a, b in pairwise(ts) if b == a), case)
            self.assertEqual(Q.step_back_count(ts), sum(1 for a, b in pairwise(ts) if b < a), case)
            self.assertEqual(Q.order_violations(ts), Q.repeat_count(ts) + Q.step_back_count(ts), case)
            self.assertEqual(Q.gap_pairs(ts, step * 1.5), [(a, b) for a, b in pairwise(ts) if b - a > step * 1.5], case)
            self.assertEqual(Q.gap_pairs(ts, step, exact=True), [(a, b) for a, b in pairwise(ts) if b - a != step], case)

    def test_weekend_closure_same_as_quant_session_break(self):
        from masterquo.data import quality as Q
        from masterquo.quant import snapshot as S
        rnd = random.Random(404)
        for case in range(600):
            sec = rnd.choice((60, 180, 300, 900, 1800, 3600, 14400, 86400))
            a = 1_793_000_000 + rnd.randrange(14 * 86400) + rnd.random()
            b = a + rnd.choice((-sec, 0, sec, 2 * sec, 47 * 3600, 2 * 86400, 2 * 86400 + sec, 3 * 86400, 4 * 86400, 4 * 86400 + 1, 9 * 86400,
                                rnd.uniform(0, 5 * 86400)))
            self.assertEqual(Q.weekday_seconds(a, b), _legacy_weekday_seconds(a, b), case)
            self.assertEqual(Q.weekend_closure(a, b, sec, max_span_s=S.WEEKEND_MAX_S), _legacy_session_break(a, b, sec), case)
            self.assertEqual(S._session_break(a, b, sec), _legacy_session_break(a, b, sec), case)          # compatibility alias
            self.assertEqual(S._weekday_seconds(a, b), _legacy_weekday_seconds(a, b), case)

    def test_freshness_primitives(self):
        from masterquo.data import quality as Q
        rnd = random.Random(405)
        for _ in range(500):
            t, now = rnd.uniform(0, 1e9), rnd.uniform(0, 1e9)
            lim = rnd.choice((0, 1, 60, 180.5, 7200))
            self.assertEqual(Q.is_forming(t, now, lim), t > now + lim)
            self.assertEqual(Q.is_stale(t, now, lim), now - t > lim)
            age = rnd.choice((None, -1.0, 0.0, lim, lim + 1e-9, NAN, 3.5))
            self.assertEqual(Q.age_within(age, lim), age is not None and age <= lim)

    def test_find_gaps_and_classify_gap_series_same_as_before(self):
        from masterquo.data import quality as Q
        rnd = random.Random(406)
        sess = Q.SessionModel([1_793_000_000 - 3600 * k for k in range(24 * 10) if (1_793_000_000 - 3600 * k) % 86400 // 3600 != 22])
        for case in range(300):
            step = rnd.choice((60, 300, 900, 3600))
            ts = _times(rnd, rnd.choice((0, 1, 2, 40, 200)), step, 1_793_000_000 // step * step, True)
            self.assertEqual(_outcome(Q.find_gaps, ts, step, sess.classify_gap), _outcome(_legacy_find_gaps, ts, step, sess.classify_gap), case)
            kw = {"weekend_min_s": rnd.choice((20 * 3600, 40 * 3600)), "weekend_probe_s": rnd.choice((3600, 86400)),
                  "break_max_s": rnd.choice((2 * 3600, 3 * 3600)), "gap_if_not_step": rnd.random() < 0.5}
            if rnd.random() < 0.5:
                kw.update(recurring_min_days=3, recurring_share=0.3, recurring_min_missing=3, short_max_missing=rnd.choice((None, 3)))
            self.assertEqual(Q.classify_gap_series(ts, step, **kw), _legacy_classify_gap_series(ts, step, **kw), case)


# ============================================================================================ ACTIVE (quote freshness through the core)
def _active_series(rnd, n, step, t0, *, faults=True):
    out, t = [], t0
    for _ in range(n):
        t += step * (1 if not faults or rnd.random() > 0.08 else rnd.choice((0, -1, 2, 3, 30, 90)))
        o, h, lo, c = _price_tuple(rnd, faults, bad=(NAN, INF, -1.0, 0.0, "2400.5", None, True))
        out.append({"t_raw": t, "o": o, "h": h, "l": lo, "c": c, "tv": rnd.choice((0, 5, 100, -1) if faults else (5, 100)), "closed": True,
                    "available_at": None})
    if out and rnd.random() < 0.5:
        out[-1]["closed"] = False
    return out


class TestActiveAssessSameAsBefore(unittest.TestCase):
    def test_assess_random(self):
        from masterquo.data import quality as Q
        from masterquo.timeutil import TF_SECONDS, TIMEFRAMES
        rnd = random.Random(410)
        dq = Counter()
        for case in range(240):
            t0 = 1_793_000_000 + rnd.choice((0, 86400 * 2, 86400 * 5)) + rnd.randrange(86400)
            clock = rnd.choice(({"status": "VERIFIED", "offset_seconds": rnd.choice((0, 7200))}, {"status": "VERIFIED", "offset_seconds": 0},
                                {"status": "STORED_UNVERIFIED", "offset_seconds": 10800}, {"status": "UNKNOWN"}))
            off = clock.get("offset_seconds") or 0
            faults = case % 4 == 0
            bars = {}
            for tf in TIMEFRAMES:
                sec = TF_SECONDS[tf]
                if faults and rnd.random() < 0.1:
                    continue
                n = rnd.choice((0, 3, 40)) if faults else 40
                bars[tf] = _active_series(rnd, n, sec, (t0 + off) // sec * sec - n * sec, faults=faults)    # server time = UTC + offset
            quote = rnd.choice((None, {}, {"age_seconds": None}, {"age_seconds": rnd.choice((0.0, 4.9, 5.0, 5.02, 5.1, 10.03, 30.0, NAN)),
                                                                 "source_age_seconds": rnd.choice((None, 0.0, 0.0, -5.0, -6.0))},
                                {"age_seconds": rnd.choice((0.0, 1.0, 4.99)), "source_age_seconds": 0.0}))
            kw = {"symbol": "XAUUSD", "bars_by_tf": bars, "required": {tf: rnd.choice((0, 10, 30)) for tf in TIMEFRAMES}, "quote": quote,
                  "clock": clock, "connection_state": rnd.choice(("CONNECTED", "CONNECTED", "CONNECTED", "DISCONNECTED")),
                  "now": datetime.fromtimestamp(t0 + rnd.choice((0, 30, 600)), UTC), "max_quote_age": rnd.choice((5.0, 10.0)),
                  "pc_clock": rnd.choice((None, None, {"status": "OK"}, {"status": "SKEW"})), "symbol_status": rnd.choice(("OK", "OK", "OK", "UNKNOWN"))}
            got = _outcome(Q.assess, **kw)
            self.assertEqual(got, _outcome(_legacy_assess, **kw), f"case {case}")
            dq[re.search(r"'data_quality': '(\w+)'", got[1]).group(1) if got[0] == "ok" else "raise"] += 1
            if got[0] == "ok":
                dq["fresh" if "'quote_fresh': True" in got[1] else "not_fresh"] += 1
        for k in ("GOOD", "DEGRADED", "BAD", "fresh", "not_fresh"):
            self.assertGreater(dq[k], 0, dq)                                  # every branch of the gate is reached


# ============================================================================================ SH (closed-bar freshness through the core)
class TestShDataQualitySameAsBefore(unittest.TestCase):
    def test_freshness_boundaries_and_faults(self):
        from masterquo.sh import context as SC
        rnd = random.Random(411)
        st = Counter()
        for case in range(400):
            bars = {}
            end = 1_795_000_000 // 3600 * 3600                               # every TF's last bar closes at `end` (unless shifted below)
            faults = case % 3 == 0
            for tf, sec in (("M1", 60), ("M5", 300), ("M15", 900), ("H1", 3600), ("M30", 1800)):
                if faults and rnd.random() < 0.15:
                    bars[tf] = []
                    continue
                n = rnd.choice((1, 20, 70))
                ts = _times(rnd, n, sec, end - (n + 1) * sec + rnd.choice((0, 0, 0, sec, -sec, 2 * sec)), faults)
                ser = []
                for t in ts:
                    o, h, lo, c = _price_tuple(rnd, faults, bad=(NAN, INF, -1.0, 0.0, "2400.5", 7))
                    ser.append({"open_utc": rnd.choice((t, datetime.fromtimestamp(t, UTC).isoformat().replace("+00:00", "Z"))),
                                "o": o, "h": h, "l": lo, "c": c})
                bars[tf] = ser
            now = end + rnd.choice((-2, -1.2, -1, -0.5, 0, 0.5, 1, 1.5, 10, 149, 150, 150.5, 180, 180.5, 180.7, 599, 600, 600.5, 1800, 1800.5, 7200, 7201, 10**5))
            quote = rnd.choice((None, {"bid": 2400.0, "ask": 2400.3, "time": now - rnd.choice((0, 1, 5, 9))}, {"bid": 2400.0, "ask": 2400.1, "time": now},
                                {"bid": 2401.0, "ask": 2400.0, "time": "x"}))
            cfg = {"max_bar_age_s": rnd.choice(({"M1": 150, "M5": 600}, {"M1": 150, "M5": 600, "M15": 1800, "H1": 7200, "M30": 3600}, {})),
                   "max_quote_age_s": 5.0, "max_spread_usd": rnd.choice((None, 0.25))}
            if rnd.random() < 0.05:
                cfg.pop("max_bar_age_s")                                    # the KeyError (when a bar is not forming) stays the same
            got = _outcome(SC.data_quality, bars, quote, now, cfg)
            self.assertEqual(got, _outcome(_legacy_sh_data_quality, bars, quote, now, cfg), f"case {case}")
            if got[0] == "raise":
                st[got[1]] += 1
            else:
                st[re.search(r"'status': '(\w+)'", got[1]).group(1)] += 1
                st["forming"] += "(forming)" in got[1]
                st["stale"] += "dane nieaktualne" in got[1]
        for k in ("OK", "BLOCK", "forming", "stale", "KeyError"):
            self.assertGreater(st[k], 0, st)


# ============================================================================================ Quant snapshot QC
def _quant_bars(rnd, tf, n, faults, *, text=False):
    from masterquo.timeutil import TF_SECONDS
    sec = TF_SECONDS.get(tf, 60)
    t0 = 1_793_000_000 // sec * sec + rnd.choice((0, 2 * 86400, 4 * 86400))
    bad = (NAN, INF, -INF, -1.0, 0.0, None, True, False, "2400.5") + (("abc",) if text else ())
    out = []
    for t in _times(rnd, n, sec, t0, faults, floats=True):
        o, h, lo, c = _price_tuple(rnd, faults, bad=bad)
        src = "RESAMPLED" if rnd.random() < 0.1 else "NATIVE"
        out.append({"t": t, "close_t": t + sec, "available_at": t + sec, "o": o, "h": h, "l": lo, "c": c, "tick_volume": 10,
                    "spread_points": rnd.choice((None, 12, 15)), "source": src, "complete": rnd.choice((None, True, False)),
                    "revision": rnd.choice((None, 0, 1))})
    return out


class TestQuantSnapshotQcSameAsBefore(unittest.TestCase):
    def test_qc_random_series(self):
        from masterquo.quant import snapshot as S
        rnd = random.Random(420)
        statuses = Counter()
        for case in range(500):
            tf = rnd.choice(("M1", "M3", "M5", "M15", "M30", "H1", "H4", "D1"))
            bars = _quant_bars(rnd, tf, rnd.choice((0, 1, 2, 30, 120, 400)), case % 4 != 0, text=case % 25 == 0)
            mg = rnd.choice((20, 5))
            got, exp = _outcome(S.qc, bars, tf, max_gap_report=mg), _outcome(_legacy_quant_qc, bars, tf, max_gap_report=mg)
            self.assertEqual(got, exp, f"case {case}")
            statuses[got[0] if got[0] == "raise" else re.search(r"'status': '(\w+)'", got[1]).group(1)] += 1
        for st in ("OK", "BLOCK", "MISSING"):
            self.assertGreater(statuses[st], 0, statuses)                  # the random set reaches every outcome

    def test_weekend_d1_series(self):
        """Clean D1 / H4 of a market closed at the weekend: weekend gaps are session breaks, not missing bars (as before)."""
        from masterquo.quant import snapshot as S
        for tf, sec in (("D1", 86400), ("H4", 14400)):
            t, bars = 1_793_000_000 // 86400 * 86400, []
            while len(bars) < 300:
                if datetime.fromtimestamp(t, UTC).weekday() < 5:
                    bars.append({"t": float(t), "close_t": float(t + sec), "available_at": float(t + sec), "o": 2400.0, "h": 2401.0, "l": 2399.0,
                                 "c": 2400.5, "tick_volume": 1, "spread_points": 10, "source": "NATIVE", "complete": None, "revision": 0})
                t += sec
            self.assertEqual(S.qc(bars, tf), _legacy_quant_qc(bars, tf))
            self.assertEqual(S.qc(bars, tf)["status"], "OK")

    def test_quote_state_in_build(self):
        from masterquo.quant import snapshot as S

        class Bridge:
            tfs = ("M1",)

            def __init__(self, quote):
                self.q = quote

            def bars(self, tf, limit, include_forming=False):
                return [{"open_utc": 1_793_000_000 + 60 * i, "o": 1.0, "h": 2.0, "l": 0.5, "c": 1.5, "closed": True} for i in range(5)]

            def quote_status(self):
                return self.q
        rnd = random.Random(421)
        for case in range(200):
            age = rnd.choice((None, 0.0, 9.99, 10.0, 10.01, 60.0, NAN, -1.0))
            quote = rnd.choice((None, {}, {"age_seconds": age}))
            mx = rnd.choice((10.0, 5.0))
            snap = S.build(Bridge(quote), instrument="XAUUSD", tfs=("M1",), now=1_793_000_000 + 600, quote_max_age_s=mx)
            exp = "MISSING"
            if quote:
                a = quote.get("age_seconds")
                exp = "OK" if a is not None and a <= mx else "STALE"
            self.assertEqual(snap["quote_state"], exp, case)


# ============================================================================================ offline reports
def _md_rows(rnd, n, faults):
    rows = []
    for t in _times(rnd, n, 300, 1_793_000_100 // 300 * 300, faults):
        o, h, lo, c = _price_tuple(rnd, faults)
        rows.append((t, o, h, lo, c, 10, 12, 0, t + 7200, 0))
    return rows


class TestOfflineReportsSameAsBefore(unittest.TestCase):
    def test_marketdata_check_rows(self):
        from masterquo.marketdata import quality as MQ
        rnd = random.Random(430)
        for case in range(300):
            rows = _md_rows(rnd, rnd.choice((0, 1, 20, 200)), case % 3 != 0)
            if case % 40 == 0 and rows:
                r = list(rows[-1])
                r[rnd.randrange(1, 5)] = None                                   # a None price raises TypeError - the same one
                rows[-1] = tuple(r)
            self.assertEqual(_outcome(MQ.check_rows, rows), _outcome(_legacy_check_rows, rows), f"case {case}")

    def test_marketdata_report(self):
        from masterquo.marketdata import quality as MQ
        rnd = random.Random(431)
        for case in range(250):
            tf = rnd.choice(("M1", "M5", "M15", "H1"))
            step = MQ.TF_SECONDS[tf]
            t = _times(rnd, rnd.choice((0, 1, 2, 60, 300)), step, 1_793_000_000 // step * step + rnd.choice((0, 0, 0, 7)), case % 3 != 0)
            cols = {"time": t, "open": [], "high": [], "low": [], "close": [], "spread": [rnd.choice((None, 10, 12)) for _ in t],
                    "real_volume": [rnd.choice((0, 0, 5)) for _ in t], "dst_ambiguous": [rnd.choice((0, 0, 1)) for _ in t]}
            for _ in t:
                o, h, lo, c = _price_tuple(rnd, case % 3 != 0)
                for k, v in zip(("open", "high", "low", "close"), (o, h, lo, c), strict=True):
                    cols[k].append(v)
            req = rnd.choice((None, (None, None), (t[0] - 5 * 86400 if t else 1_793_000_000, None)))
            self.assertEqual(_outcome(MQ.report, cols, tf, req), _outcome(_legacy_md_report, cols, tf, req), f"case {case}")

    def test_forecast_export_geometry(self):
        from masterquo.forecast import export as EX
        rnd = random.Random(432)
        for case in range(3000):
            o, h, lo, c = _price_tuple(rnd, True)
            self.assertEqual(EX._geometry_ok(o, h, lo, c), _legacy_export_geometry_ok(o, h, lo, c), case)


# ============================================================================================ Kronos / TSFM input, Kronos steps, Monte Carlo
class _Calendar:
    def expected_missing(self, t_raws, tf_sec):
        miss = sum(max(0, (b - a) // tf_sec - 1) for a, b in pairwise(t_raws))
        return {"missing_open_slots": miss, "ambiguous_slots": 0}


def _kronos_bars(rnd, n, sec, faults):
    out = []
    for t in _times(rnd, n, sec, 1_793_000_000 // sec * sec, faults):
        o, h, lo, c = _price_tuple(rnd, faults, bad=(NAN, INF, -1.0, 0.0, None, True, False, "2400.5"))
        b = {"t_raw": t + 7200, "open_utc": datetime.fromtimestamp(t, UTC).isoformat().replace("+00:00", "Z"), "o": o, "h": h, "l": lo, "c": c,
             "tv": rnd.choice((0, 50, 50, 50)), "rv": rnd.choice((0, 3, 3)), "closed": True}
        if faults and rnd.random() < 0.05:
            b["closed"] = False
        if faults and rnd.random() < 0.03:
            b["t_raw"] = None
        if faults and rnd.random() < 0.02:
            b["open_utc"] = rnd.choice((None, ""))
        out.append(b)
        if faults and rnd.random() < 0.05:
            out.append(dict(b, c=b["c"] if rnd.random() < 0.5 else 2399.0))     # identical or conflicting copy
    return out


class TestKronosMonteCarloSameAsBefore(unittest.TestCase):
    def test_kronos_input_check(self):
        from masterquo.kronos import quality as KQ
        rnd = random.Random(440)
        statuses = Counter()
        for case in range(400):
            sec = rnd.choice((60, 300, 900, 3600))
            bars = _kronos_bars(rnd, rnd.choice((0, 1, 5, 60, 250)), sec, case % 4 != 0)
            last = max((b["t_raw"] - 7200 for b in bars if b.get("t_raw") is not None), default=1_793_000_000)
            kw = {"now_utc": last + sec + rnd.choice((0, 30, 2 * sec + 60, 2 * sec + 61, 10**5)), "lookback": rnd.choice((10, 120, 512)),
                  "min_context": rnd.choice((0, 32, 200)), "calendar": rnd.choice((None, _Calendar())),
                  "volume_setting": rnd.choice(("AUTO", "NONE", "TICK")), "max_staleness_bars": rnd.choice((2.0, 1e9))}
            got, exp = _outcome(KQ.check, bars, sec, **kw), _outcome(_legacy_kronos_check, bars, sec, **kw)
            self.assertEqual(got, exp, f"case {case}")
            statuses[got[0] if got[0] == "raise" else re.search(r"'status': '(\w+)'", got[1]).group(1)] += 1
        for st in ("OK", "BLOCK", "STALE", "WARMUP"):
            self.assertGreater(statuses[st], 0, statuses)

    def test_kronos_finite_pos_alias(self):
        from masterquo.kronos import quality as KQ
        rnd = random.Random(441)
        pool = (1.0, 2400.5, 0, -3, NAN, INF, None, True, False, "2400.5", 7)
        for _ in range(500):
            xs = tuple(rnd.choice(pool) for _ in range(4))
            self.assertEqual(KQ._finite_pos(*xs), _legacy_finite_pos(*xs), xs)

    def test_kronos_forecast_step_geometry(self):
        from masterquo.data import quality as Q
        rnd = random.Random(442)
        for case in range(3000):
            o, h, lo, c = _price_tuple(rnd, True)
            self.assertEqual(Q.ohlc_crossed(o, h, lo, c), _legacy_kronos_step_bad(o, h, lo, c), case)
        src = (BACKEND / "kronos" / "service.py").read_text(encoding="utf-8")
        self.assertIn("if DQ.ohlc_crossed(o, h, low, c):", src)               # the step loop calls exactly this

    def test_montecarlo_history(self):
        import numpy as np
        from masterquo.montecarlo import engine as E
        rnd = random.Random(443)
        for case in range(250):
            tf = rnd.choice(("M1", "M5", "M15"))
            sec = E.TF_S[tf]
            ts = _times(rnd, rnd.choice((0, 1, 30, 400)), sec, 1_793_000_000 // sec * sec, case % 3 != 0)
            bars = []
            for t in ts:
                o, h, lo, c = _price_tuple(rnd, case % 3 != 0, bad=(NAN, INF, -1.0, 0.0, "2400.5", "nan"))
                b = {rnd.choice(("open_utc", "open_utc", "t")): rnd.choice((t, datetime.fromtimestamp(t, UTC).isoformat())), "o": o, "h": h, "l": lo, "c": c}
                k = rnd.random()
                if k < 0.4:
                    b["spread"] = rnd.choice((10, 12.5))
                elif k < 0.6:
                    b["spread_price"] = 0.15
                if case % 50 == 0 and rnd.random() < 0.05:
                    b["c"] = None                                               # float(None) raises the same TypeError
                if rnd.random() < 0.02:
                    b.pop("open_utc", None)
                    b.pop("t", None)
                bars.append(b)
            as_of = (ts[-1] if ts else 1_793_000_000) + sec * rnd.choice((0, 1, 2, 20))
            kw = {"tf": tf, "point": rnd.choice((0.01, None, 0.001)), "window": rnd.choice((6000, 50)), "stale_after_s": rnd.choice((None, 120.0))}

            def run(fn, bars=bars, as_of=as_of, kw=kw):
                try:
                    h = fn(bars, as_of, **kw)
                except Exception as exc:  # noqa: BLE001 - the exception type and text are part of the parity
                    return ("raise", type(exc).__name__, str(exc))
                return ("ok", h.tf, h.flags, h.dropped, h.data_hash, [np.asarray(getattr(h, f)).tolist() for f in ("t", "o", "h", "lo", "c")],
                        np.isnan(h.spread).tolist(), np.nan_to_num(h.spread, nan=-1.0).tolist())
            self.assertEqual(run(E.history), run(_legacy_mc_history), f"case {case}")


# ============================================================================================ one place for the geometry rule
class TestNoInlineGeometryLeft(unittest.TestCase):
    """The tracks moved to the core do not keep their own copy of the OHLC bound expressions (a new copy = a new, unchecked policy)."""
    FILES = ("quant/snapshot.py", "marketdata/quality.py", "forecast/export.py", "kronos/quality.py", "kronos/service.py", "montecarlo/engine.py",
             "sh/context.py")

    @staticmethod
    def _body_bounds(tree) -> list[int]:
        """Lines of code (not docstrings / comments) that compare against max(o, c) / min(o, c)."""
        out = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                for part in (node.left, *node.comparators):
                    for sub in ast.walk(part):
                        if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id in ("max", "min") and len(sub.args) == 2
                                and all(isinstance(a, ast.Name) for a in sub.args) and [a.id for a in sub.args] == ["o", "c"]):
                            out.append(node.lineno)
        return out

    def test_no_inline_bounds(self):
        for rel in self.FILES:
            src = (BACKEND / rel).read_text(encoding="utf-8")
            self.assertEqual(self._body_bounds(ast.parse(src)), [], rel)
            self.assertIn("quality as DQ", src, rel)
        core = ast.parse((BACKEND / "data" / "quality.py").read_text(encoding="utf-8"))
        self.assertTrue(self._body_bounds(core))                               # the rule lives in the core


if __name__ == "__main__":
    unittest.main()
