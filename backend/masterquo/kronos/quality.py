"""Checks of the closed bars that go into a Kronos forecast (bars as returned by the bridge: t_raw, open_utc, o/h/l/c, tv, rv, closed).

* only bars the bridge marks closed are used (the forming bar is never part of the input);
* sorted by time; duplicates: identical copies dropped, conflicting copies -> BLOCK;
* OHLC geometry (h >= max(o, c), l <= min(o, c), h >= l, all finite and > 0) and missing values -> the bar is invalid; any invalid bar in
  the context window -> BLOCK (no silent repair: the forecast would be computed on prices that did not exist);
* gaps on OPEN calendar slots (a weekend / daily break is not a gap): > 2 % of the window -> DEGRADED, > 10 % -> BLOCK;
* freshness: the last closed bar must have closed within max_staleness_bars x timeframe (+60 s) - otherwise STALE (market closed, MT5
  disconnected or no ticks): no new forecast, an older one is shown as not current;
* volume source: REAL_VOLUME when the broker reports real volume on >= 90 % of bars, else TICK_VOLUME (number of price changes - NOT
  traded volume), or NONE (setting / no data). `amount` is never real turnover here: when a volume is passed, the upstream predictor
  derives amount = volume x mean(OHLC) - a SYNTHETIC PROXY, labelled so.
"""
from __future__ import annotations

import math

VOLUME_PL = {"REAL_VOLUME": "wolumen rzeczywisty z MT5 (real_volume)", "TICK_VOLUME": "tick_volume MT5 – liczba zmian ceny, NIE wolumen obrotu",
             "NONE": "bez wolumenu (oryginalna obsługa Kronos: volume = amount = 0)"}
AMOUNT_PL = {"SYNTHETIC_PROXY": "amount = wolumen × średnia OHLC – syntetyczne przybliżenie (upstream), NIE rzeczywisty obrót",
             "NONE": "amount = 0 (brak wolumenu)"}


def _finite_pos(*xs) -> bool:
    return all(isinstance(x, (int, float)) and math.isfinite(x) and x > 0 for x in xs)


def check(bars: list[dict], tf_sec: int, *, now_utc: float, lookback: int, min_context: int, calendar=None, volume_setting: str = "AUTO",
          max_staleness_bars: float = 2.0) -> dict:
    issues, status = [], "OK"

    def worse(s: str, why: str):
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
        if not _finite_pos(o, h, l, c):
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
        from ..timeutil import parse_iso
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


def atr(bars: list[dict], n: int = 14) -> float | None:
    if len(bars) < n + 1:
        return None
    trs = []
    for a, b in zip(bars[-n - 1:-1], bars[-n:]):
        trs.append(max(b["h"] - b["l"], abs(b["h"] - a["c"]), abs(b["l"] - a["c"])))
    return sum(trs) / len(trs)
