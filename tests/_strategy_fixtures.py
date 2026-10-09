"""SYNTHETIC deterministic price paths for S01-S10 rule tests (not market data).

Each scenario returns closed bars for one timeframe ending with the bar that should complete the
LONG rule. `mirror()` turns a LONG scenario into the matching SHORT one (prices p -> 2*C - p).
Bars carry generous wicks so ATR is independent of close-to-close efficiency.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
T0 = datetime(2026, 1, 12, 0, 0, tzinfo=UTC)   # Monday, winter time (London = UTC)


def iso(t: datetime) -> str:
    return t.isoformat().replace("+00:00", "Z")


def bars_from_closes(closes: list[float], *, tf_min: int = 15, wick: float = 1.0, start: datetime = T0, opens: list[float] | None = None,
                     highs: dict | None = None, lows: dict | None = None) -> list[dict]:
    out = []
    for i, c in enumerate(closes):
        o = opens[i] if opens else (closes[i - 1] if i else c)
        h = max(o, c) + wick
        lo = min(o, c) - wick
        if highs and i in highs:
            h = highs[i]
        if lows and i in lows:
            lo = lows[i]
        t = start + timedelta(minutes=tf_min * i)
        out.append({"open_utc": iso(t), "o": o, "h": h, "l": lo, "c": c, "closed": True, "close_confirmed_utc": iso(t + timedelta(minutes=tf_min)),
                    "available_at": iso(t + timedelta(minutes=tf_min))})
    return out


def noise(i: int, amp: float) -> float:
    return amp * (math.sin(i * 1.7) * 0.6 + math.sin(i * 0.37) * 0.4)


def mirror(bars: list[dict], center: float = 2000.0) -> list[dict]:
    out = []
    for b in bars:
        out.append({**b, "o": 2 * center - b["o"], "c": 2 * center - b["c"], "h": 2 * center - b["l"], "l": 2 * center - b["h"]})
    return out


# ----------------------------------------------------------------------------- scenarios (LONG)
def s01_trend_pullback() -> list[dict]:
    c = [1940 + 0.5 * i + noise(i, 0.15) for i in range(120)]
    for _ in range(6):
        c.append(c[-1] - 0.9)
    c.append(c[-1] + 2.4)                       # reaction bar: close above the previous bar's high
    return bars_from_closes(c, wick=1.0)


def s02_adaptive_trend() -> list[dict]:
    c = [2000 + noise(i, 0.6) for i in range(100)]
    c.append(c[-1] + 3.2)                       # state change: close above KAMA + band with ER >= 0.3
    return bars_from_closes(c, wick=1.0)


def s03_channel_breakout() -> list[dict]:
    c = [2000 + 3.0 * math.sin(i * 2 * math.pi / 14) + noise(i, 0.2) for i in range(70)]
    top = max(x + 0.6 for x in c[-20:])         # channel top incl. wick (prior 20 bars)
    c.append(top - 0.8)                         # inside the channel, near the top
    c.append(top + 0.9)                         # fresh close above the prior 20-bar high
    return bars_from_closes(c, wick=0.6)


def s04_compression_breakout() -> list[dict]:
    c = [2000 + 3.0 * math.sin(i * 2 * math.pi / 9) + noise(i, 0.8) for i in range(140)]
    base = c[-1]
    for i in range(10):
        c.append(base + 0.1 * math.sin(i))
    bars = bars_from_closes(c, wick=0.15)
    vol = bars_from_closes(c[:140], wick=1.2)
    bars[:140] = vol
    top = max(b["h"] for b in bars[-10:])
    last = bars[-1]
    nb = bars_from_closes([last["c"], top + 0.45], wick=0.15, start=datetime.fromisoformat(last["open_utc"].replace("Z", "+00:00")))
    bars.append({**nb[1]})
    return bars


def s05_session_breakout() -> tuple[list[dict], dict]:
    start = datetime(2026, 1, 14, 4, 0, tzinfo=UTC)          # winter: London 08:00 = 08:00 UTC
    c = [2000 + noise(i, 0.4) for i in range(48)]            # 04:00-07:55
    rng = [2000 + 1.5 * math.sin(i * 0.9) for i in range(12)]  # 08:00-08:55 range
    after = [2000.5, 2000.2]                                  # 09:00, 09:05 inside
    c = c + rng + after
    bars = bars_from_closes(c, tf_min=5, wick=0.5, start=start)
    hi = max(b["h"] for b in bars[48:60])
    nb = bars_from_closes([bars[-1]["c"], hi + 0.6], tf_min=5, wick=0.3, start=start + timedelta(minutes=5 * (len(bars) - 1)))
    bars.append(nb[1])
    return bars, {"range_high": hi}


def s06_breakout_retest() -> list[dict]:
    c = [2000 + noise(i, 0.3) for i in range(90)]
    c += [2001, 2002.5, 2004, 2005.0, 2003.5, 2002, 2001, 2000.5, 2001.5, 2002.5, 2003.5, 2004.2]
    peak = 2005.0 + 0.5                                       # pivot high (wick)
    c += [peak + 1.0]                                         # break bar: close above level + buffer
    c += [peak + 2.0, peak + 0.6]                             # continuation, retest bar (low into level zone)
    c += [peak + 3.2]                                         # reaction: close above the retest bar high
    return bars_from_closes(c, wick=0.5)


def s07_failed_breakout() -> list[dict]:
    c = [2000 + 2.5 * math.sin(i * 2 * math.pi / 12) + noise(i, 0.2) for i in range(60)]
    low = min(x - 0.5 for x in c[-20:])
    c += [low - 0.2]                                          # excursion bar: trades and closes below the range low
    bars = bars_from_closes(c, wick=0.5)
    bars[-1]["l"] = low - 1.2
    nb = bars_from_closes([bars[-1]["c"], low + 1.0], wick=0.4, start=datetime.fromisoformat(bars[-1]["open_utc"].replace("Z", "+00:00")))
    bars.append(nb[1])                                        # reclaim close above level + buffer
    return bars


def s08_range_edge() -> list[dict]:
    c = [2000 + 4.0 * math.sin(i * 2 * math.pi / 12) for i in range(83)]
    bars = bars_from_closes(c, wick=0.5)
    bot = min(b["l"] for b in bars[-40:])
    t = datetime.fromisoformat(bars[-1]["open_utc"].replace("Z", "+00:00")) + timedelta(minutes=15)
    bars.append({"open_utc": iso(t), "o": bot + 1.6, "h": bot + 2.6, "l": bot + 0.2, "c": bot + 2.5, "closed": True,
                 "close_confirmed_utc": iso(t + timedelta(minutes=15)), "available_at": iso(t + timedelta(minutes=15))})
    return bars


def s09_mean_reversion() -> list[dict]:
    c = [2000 + 1.6 * math.sin(i * 1.9) + noise(i, 0.6) for i in range(70)]
    base = c[-1]
    c += [base - 2.0, base - 3.6, base - 4.6]                 # deviation (z <= -2) without an efficient trend
    c += [c[-1] + 1.2]                                        # turn: z rising, bullish close
    return bars_from_closes(c, wick=0.5)


def s10_exhaustion() -> list[dict]:
    c = [2040 + noise(i, 0.4) for i in range(60)]
    c += [2040 - 1.2 * k for k in range(1, 11)]               # impulse down to 2028
    c += [2029.5, 2031.0, 2032.2, 2031.0, 2029.8, 2028.6]    # lower high (pivot) around 2032.2
    c += [2026, 2023, 2020.5, 2019.0]                         # final leg to the extreme (stretched)
    c += [2020.5, 2023.0, 2026.0, 2029.5, 2033.6]             # recovery, last bar closes above the lower high
    return bars_from_closes(c, wick=0.5)


SCENARIOS = {"S01": s01_trend_pullback, "S02": s02_adaptive_trend, "S03": s03_channel_breakout, "S04": s04_compression_breakout,
             "S06": s06_breakout_retest, "S07": s07_failed_breakout, "S08": s08_range_edge, "S09": s09_mean_reversion, "S10": s10_exhaustion}
