"""Deterministic SYNTHETIC_TEST scenario for the scalp state machine (code tests only).

A sine-shaped M5 consolidation (period 30 min, amplitude 3) arms a range; then crafted M1 bars walk down to the lower M1
zone, sweep it with a bullish rejection candle on high tick volume, retest the zone top and rally to the opposite edge.
`mirror()` reflects every price around the centre (o,c -> 2C-o, 2C-c; h <-> l) to obtain the SELL counterpart."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from masterquo.scalp import strategy as st

C = 2000.0
START = datetime(2026, 3, 3, 0, 0, tzinfo=timezone.utc)


def _bar(t, o, h, l, c, tv=100, sp=0.1):
    return {"open_utc": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "o": round(o, 2), "h": round(h, 2), "l": round(l, 2), "c": round(c, 2), "tv": tv, "spread_price": sp}


def sine(n: int, amp: float = 3.0, period: int = 30) -> list[dict]:
    out = []
    p_prev = C + amp * math.sin(-2 * math.pi / period)
    for k in range(n):
        p = C + amp * math.sin(2 * math.pi * k / period)
        out.append(_bar(START + timedelta(minutes=k), p_prev, max(p, p_prev) + 0.1, min(p, p_prev) - 0.1, p))
        p_prev = p
    return out


def m5_of(m1):
    from masterquo.scalp.replay import aggregate
    return aggregate(m1, 5)


def build(prof: dict) -> tuple[list[dict], dict]:
    """Returns M1 bars + info {arm_time, zone, sweep_time, retest_time}. Context filter must be disabled in `prof`."""
    base = sine(24 * 60)
    m = st.ScalpMachine(prof, 0.01)
    m5 = {st.ts(b["open_utc"]) + 300: b for b in m5_of(base)}
    cut = None
    for b in base:
        T = st.ts(b["open_utc"]) + 60
        m.on_m1_close(b)
        if T in m5:
            m.on_m5_close(m5[T])
            d = m.dirs.get("BUY")
            if m.range and d and d["state"] == "WAIT_SWEEP" and st.ts(b["open_utc"]) > st.ts(base[0]["open_utc"]) + 6 * 3600:
                cut = base.index(b) + 1
                break
    assert cut, "range never armed"
    r, z = m.range, m.dirs["BUY"]["zone"]
    bars = base[:cut]
    t = st.ts(bars[-1]["open_utc"]) + 60
    p = bars[-1]["c"]
    tgt = z["z_high"] + 0.05
    nxt = lambda: datetime.fromtimestamp(t, timezone.utc)  # noqa: E731
    while p - tgt > 0.5:                                    # walk down to the zone top
        q = max(tgt, p - 0.7)
        bars.append(_bar(nxt(), p, p + 0.05, q - 0.05, q))
        p, t = q, t + 60
    zl, zh = z["z_low"], z["z_high"]
    o = p
    c = zh + 0.35
    sweep = _bar(nxt(), o, c + 0.02, zl - 0.6, c, tv=400)
    bars.append(sweep)
    t += 60
    retest = _bar(nxt(), c, c + 0.05, zh - 0.02, zh + 0.3)
    bars.append(retest)
    t += 60
    p = zh + 0.3
    for _ in range(25):                                     # rally to the opposite edge
        q = p + 0.6
        bars.append(_bar(nxt(), p, q + 0.05, p - 0.05, q))
        p, t = q, t + 60
    return bars, {"zone": z, "range": {k: r[k] for k in ("L", "H", "MID")}, "sweep_time": sweep["open_utc"], "retest_time": retest["open_utc"]}


def mirror(bars: list[dict]) -> list[dict]:
    return [dict(b, o=round(2 * C - b["o"], 2), c=round(2 * C - b["c"], 2), h=round(2 * C - b["l"], 2), l=round(2 * C - b["h"], 2)) for b in bars]


def run(prof: dict, bars: list[dict]):
    m = st.ScalpMachine(prof, 0.01)
    m5 = {st.ts(b["open_utc"]) + 300: b for b in m5_of(bars)}
    plans = []
    for b in bars:
        T = st.ts(b["open_utc"]) + 60
        plans += m.on_m1_close(b)
        if T in m5:
            m.on_m5_close(m5[T])
    return m, plans
