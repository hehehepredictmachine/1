"""Data quality of stored candles (PMW-MD-QUALITY-1): order, duplicates, OHLC validity, gaps classified as market sessions vs
missing data, and the REAL available history per timeframe.

Gap classes (between consecutive stored bars, UTC):
* WEEKEND        - the gap covers a Saturday (UTC): the market was closed for the weekend;
* SESSION_BREAK  - a break that recurs at the same UTC time of day on >= 30 % of the trading days in this data (e.g. the daily
                   rollover / maintenance break of gold CFDs) and lasts <= 3 h - learned from the data, not assumed per broker;
* NO_TICKS_SHORT - 1-3 missing bars: MT5 builds no bar when no price changed - normal in quiet minutes (M1), not necessarily a loss;
* MISSING        - anything else: data missing in the terminal history (listed with the number of missing bars).
Nothing is filled or repaired: invalid geometry is rejected at ingest and listed, gaps stay gaps.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from .store import TF_SECONDS, iso


def check_rows(rows: list[tuple]) -> tuple[list[tuple], list[dict]]:
    """Rejects rows with invalid OHLC geometry or non-positive prices (never repaired). rows: tuples in store.COLUMNS order."""
    ok, bad = [], []
    for r in rows:
        t, o, h, lo, c = r[0], r[1], r[2], r[3], r[4]
        if not (o > 0 and h > 0 and lo > 0 and c > 0 and h >= max(o, c) and lo <= min(o, c) and h >= lo):
            bad.append({"time_utc": iso(t), "ohlc": [o, h, lo, c], "reason": "nieprawidłowa geometria OHLC"})
        else:
            ok.append(r)
    return ok, bad


def classify_gaps(times: list[int], step: int) -> dict:
    gaps = []
    for a, b in zip(times, times[1:]):
        if b - a > step:
            gaps.append((a, b))
    days = {datetime.fromtimestamp(t, timezone.utc).date() for t in times}
    starts = Counter(((a + step) % 86400) // step * step for a, b in gaps if b - a <= 3 * 3600 + step and (b - a) // step - 1 > 3)
    recurring = {k for k, v in starts.items() if days and v >= max(3, 0.3 * len(days))}
    out = {"WEEKEND": 0, "SESSION_BREAK": 0, "NO_TICKS_SHORT": 0, "MISSING": 0, "missing_bars": 0, "missing_list": [],
           "session_break_times_utc": sorted(f"{k // 3600:02d}:{k % 3600 // 60:02d}" for k in recurring)}
    for a, b in gaps:
        miss = (b - a) // step - 1
        da, db = datetime.fromtimestamp(a, timezone.utc), datetime.fromtimestamp(b, timezone.utc)
        covers_sat = any((datetime.fromtimestamp(a + k * 3600, timezone.utc)).weekday() == 5 for k in range(0, int((b - a) // 3600) + 1))
        if covers_sat and b - a >= 20 * 3600:
            out["WEEKEND"] += 1
        elif ((a + step) % 86400) // step * step in recurring and b - a <= 3 * 3600 + step:
            out["SESSION_BREAK"] += 1
        elif miss <= 3:
            out["NO_TICKS_SHORT"] += 1
        else:
            out["MISSING"] += 1
            out["missing_bars"] += int(miss)
            if len(out["missing_list"]) < 100:
                out["missing_list"].append({"after_utc": iso(a), "next_utc": iso(b), "missing_bars": int(miss), "weekday": da.strftime("%a"),
                                            "next_weekday": db.strftime("%a")})
    return out


def report(cols: dict, tf: str, requested: tuple[float | None, float | None] | None = None) -> dict:
    step = TF_SECONDS[tf]
    t = cols.get("time") or []
    n = len(t)
    unsorted = sum(1 for a, b in zip(t, t[1:]) if b <= a)
    dups = n - len(set(t))
    misaligned = sum(1 for x in t if x % step)
    invalid = 0
    for i in range(n):
        o, h, lo, c = cols["open"][i], cols["high"][i], cols["low"][i], cols["close"][i]
        if not (h >= max(o, c) and lo <= min(o, c) and lo > 0):
            invalid += 1
    gaps = classify_gaps(sorted(set(t)), step) if n > 1 else {}
    days = sorted({datetime.fromtimestamp(x, timezone.utc).date().isoformat() for x in t})
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


def _median(v: list) -> float | None:
    s = sorted(x for x in v if x is not None)
    return float(s[len(s) // 2]) if s else None
