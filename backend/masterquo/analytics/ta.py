"""Shared Bollinger Bands and moving-average engine (MQ-TA-1.0.0) - ONE implementation for charts, explanations, history
snapshots and tests. Pure Python on CLOSED bars (a forming bar is never an input of these values).

Bollinger Bands (math contract):
    middle = SMA(close, n);  sigma = population std of the same window (ddof=0);  upper/lower = middle +/- k*sigma
    percent_b = (close - lower) / (upper - lower)   - NOT clipped (can be < 0 or > 1); null when upper == lower (flat window)
    bandwidth_ratio = (upper - lower) / middle;  bandwidth_pct = 100 * bandwidth_ratio  (two separate fields, never mixed)
    Warm-up (< n bars) -> null with reason WARMUP. Same convention as MT5 iBands and the vendored M02I engine (pstdev).
    Squeeze: bandwidth_ratio percentile vs the PREVIOUS `squeeze_lookback` widths only (current excluded) <= squeeze_pct.
Moving averages: SMA; EMA seeded with the SMA of the first n values (alpha = 2/(n+1), same as M02I); WMA linear weights 1..n.
    Crosses are confirmed on a CLOSED bar (sign change of fast-slow between the previous and the current close), each with a
    stable event id. Distances in price and, when ATR14 is known, in ATR. Context rules are explicit (see ma_analysis).
SMA(n) equal to the BB middle is flagged `same_as_bb_middle` so it never adds a second vote for the same phenomenon.
Touching a band is NOT a buy/sell instruction: band events are descriptive and the trend case (walking the band) is flagged.
"""
from __future__ import annotations

import hashlib
import math
import time

from . import contract

VERSION = "MQ-TA-1.0.0"
DEFAULT_BB = {"source": "close", "period": 20, "k": 2.0, "squeeze_lookback": 120, "squeeze_pct": 20.0}
DEFAULT_MA = [{"id": "EMA9", "type": "EMA", "period": 9, "visible": False}, {"id": "EMA21", "type": "EMA", "period": 21, "visible": True},
              {"id": "SMA50", "type": "SMA", "period": 50, "visible": False}, {"id": "SMA200", "type": "SMA", "period": 200, "visible": False}]
TF_SEC = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "H8": 28800, "D1": 86400}


def sma(x: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(x)
    s = 0.0
    for i, v in enumerate(x):
        s += v
        if i >= n:
            s -= x[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def ema(x: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(x)
    if len(x) < n:
        return out
    a = 2.0 / (n + 1)
    e = sum(x[:n]) / n
    out[n - 1] = e
    for i in range(n, len(x)):
        e = a * x[i] + (1 - a) * e
        out[i] = e
    return out


def wma(x: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(x)
    den = n * (n + 1) / 2
    for i in range(n - 1, len(x)):
        out[i] = sum(x[i - n + 1 + j] * (j + 1) for j in range(n)) / den
    return out


MA_FN = {"SMA": sma, "EMA": ema, "WMA": wma}


def atr14(h, lo, c, n: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(c)
    trs = []
    for i in range(len(c)):
        tr = h[i] - lo[i] if i == 0 else max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1]))
        trs.append(tr)
        if i == n - 1:
            out[i] = sum(trs) / n
        elif i >= n:
            out[i] = (out[i - 1] * (n - 1) + tr) / n
    return out


def bollinger(c: list[float], n: int = 20, k: float = 2.0) -> dict[str, list]:
    keys = ("middle", "upper", "lower", "sigma", "percent_b", "bandwidth_ratio", "bandwidth_pct")
    out = {key: [None] * len(c) for key in keys}
    out["reason"] = ["WARMUP"] * len(c)
    for i in range(n - 1, len(c)):
        w = c[i - n + 1: i + 1]
        m = sum(w) / n
        sd = math.sqrt(sum((v - m) ** 2 for v in w) / n)
        up, lo = m + k * sd, m - k * sd
        out["middle"][i], out["upper"][i], out["lower"][i], out["sigma"][i] = m, up, lo, sd
        out["percent_b"][i] = None if up == lo else (c[i] - lo) / (up - lo)
        if m:
            out["bandwidth_ratio"][i] = (up - lo) / m
            out["bandwidth_pct"][i] = 100.0 * (up - lo) / m
        out["reason"][i] = "FLAT_WINDOW" if up == lo else ("ZERO_MIDDLE" if not m else None)
    return out


def _r(x, n=5):
    return None if x is None else round(x, n)


def bb_analysis(bars: list[dict], cfg: dict | None = None, *, symbol: str | None = None, tf: str | None = None) -> dict:
    t0 = time.perf_counter()
    cfg = {**DEFAULT_BB, **(cfg or {})}
    n, k = int(cfg["period"]), float(cfg["k"])
    if n < 2 or k <= 0:
        return contract.result("bollinger", VERSION, cfg, symbol=symbol, tf=tf, bars=bars, status="error", reason="INVALID_CONFIG", t0=t0, tf_seconds=TF_SEC.get(tf or ""))
    c, h, lo = [b["c"] for b in bars], [b["h"] for b in bars], [b["l"] for b in bars]
    if len(c) < n:
        return contract.result("bollinger", VERSION, cfg, symbol=symbol, tf=tf, bars=bars, status="warming_up", reason=f"WARMUP: {len(c)}/{n} świec",
                               t0=t0, tf_seconds=TF_SEC.get(tf or ""))
    bb = bollinger(c, n, k)
    i = len(c) - 1
    widths = [w for w in bb["bandwidth_ratio"][max(0, i - int(cfg["squeeze_lookback"])): i] if w is not None]
    w = bb["bandwidth_ratio"][i]
    pct = None if len(widths) < 20 or w is None else 100.0 * sum(1 for x in widths if x < w) / len(widths)
    up, lw, mid = bb["upper"][i], bb["lower"][i], bb["middle"][i]
    prev_out = i > 0 and bb["upper"][i - 1] is not None and (c[i - 1] > bb["upper"][i - 1] or c[i - 1] < bb["lower"][i - 1])
    events = []
    if h[i] >= up and c[i] <= up:
        events.append("TOUCH_UPPER")
    if c[i] > up:
        events.append("CLOSE_ABOVE_UPPER")
    if lo[i] <= lw and c[i] >= lw:
        events.append("TOUCH_LOWER")
    if c[i] < lw:
        events.append("CLOSE_BELOW_LOWER")
    if prev_out and lw <= c[i] <= up:
        events.append("RETURN_INSIDE")
    if i > 0 and bb["middle"][i - 1] is not None and (c[i - 1] - bb["middle"][i - 1]) * (c[i] - mid) < 0:
        events.append("CROSS_MIDDLE")
    walk_up = sum(1 for j in range(max(n - 1, i - 4), i + 1) if bb["upper"][j] is not None and c[j] >= bb["upper"][j] - 0.1 * (bb["sigma"][j] or 0))
    walk_dn = sum(1 for j in range(max(n - 1, i - 4), i + 1) if bb["lower"][j] is not None and c[j] <= bb["lower"][j] + 0.1 * (bb["sigma"][j] or 0))
    trend_walk = "UP" if walk_up >= 3 else "DOWN" if walk_dn >= 3 else None
    expanding = all(bb["bandwidth_ratio"][j] is not None and bb["bandwidth_ratio"][j - 1] is not None and bb["bandwidth_ratio"][j] > bb["bandwidth_ratio"][j - 1]
                    for j in range(i - 2, i + 1)) if i >= n + 2 else None
    squeeze = None if pct is None else pct <= float(cfg["squeeze_pct"])
    slope = None
    if i >= n + 2 and bb["middle"][i - 3] is not None:
        slope = (mid - bb["middle"][i - 3]) / 3
    a = atr14(h, lo, c)[i]
    interp = []
    if trend_walk:
        interp.append(f"cena „idzie wzdłuż” {'górnego' if trend_walk == 'UP' else 'dolnego'} pasma – w trendzie dotknięcie pasma nie oznacza odwrotu")
    if squeeze:
        interp.append("zawężenie pasm (squeeze) względem własnej historii – zmienność niska, kierunek wybicia nieznany")
    if expanding:
        interp.append("pasma się rozszerzają – rośnie zmienność")
    if not interp:
        interp.append("pasma bez wyraźnego sygnału zmienności")
    vals = {"middle": _r(mid), "upper": _r(up), "lower": _r(lw), "sigma": _r(bb["sigma"][i]), "percent_b": _r(bb["percent_b"][i], 4),
            "bandwidth_ratio": _r(w, 6), "bandwidth_pct": _r(bb["bandwidth_pct"][i], 4), "bandwidth_percentile": _r(pct, 1), "squeeze": squeeze,
            "expanding": expanding, "events": events, "trend_walk": trend_walk, "middle_slope_per_bar": _r(slope),
            "middle_slope_atr_per_bar": _r(slope / a, 4) if slope is not None and a else None, "close": c[i],
            "interpretation": interp, "units": {"middle/upper/lower/sigma": "cena", "bandwidth_ratio": "ułamek ceny", "bandwidth_pct": "%"}}
    return contract.result("bollinger", VERSION, cfg, symbol=symbol, tf=tf, bars=bars, status="ready", values=vals, t0=t0,
                           tf_seconds=TF_SEC.get(tf or ""), reason=bb["reason"][i])


def ma_analysis(bars: list[dict], mas: list[dict] | None = None, *, symbol: str | None = None, tf: str | None = None, bb_period: int | None = 20,
                lookback_events: int = 50) -> dict:
    t0 = time.perf_counter()
    mas = mas or DEFAULT_MA
    cfg = {"mas": mas, "source": "close"}
    for m in mas:
        if m.get("type") not in MA_FN or int(m.get("period", 0)) < 1:
            return contract.result("moving_averages", VERSION, cfg, symbol=symbol, tf=tf, bars=bars, status="error", reason=f"INVALID_CONFIG: {m}", t0=t0)
    c, h, lo = [b["c"] for b in bars], [b["h"] for b in bars], [b["l"] for b in bars]
    if not c:
        return contract.result("moving_averages", VERSION, cfg, symbol=symbol, tf=tf, bars=bars, status="unavailable", reason="NO_DATA", t0=t0)
    a = atr14(h, lo, c)
    i = len(c) - 1
    series = {m["id"]: MA_FN[m["type"]](c, int(m["period"])) for m in mas}
    rows = []
    for m in mas:
        s = series[m["id"]]
        v = s[i]
        sl = (v - s[i - 3]) / 3 if v is not None and i >= 3 and s[i - 3] is not None else None
        rows.append({"id": m["id"], "type": m["type"], "period": m["period"], "value": _r(v), "status": "ready" if v is not None else "warming_up",
                     "price_vs": None if v is None else ("ABOVE" if c[i] > v else "BELOW" if c[i] < v else "AT"),
                     "distance": _r(c[i] - v) if v is not None else None, "distance_atr": _r((c[i] - v) / a[i], 3) if v is not None and a[i] else None,
                     "slope_per_bar": _r(sl), "slope_atr_per_bar": _r(sl / a[i], 4) if sl is not None and a[i] else None,
                     "same_as_bb_middle": m["type"] == "SMA" and int(m["period"]) == bb_period, "visible": bool(m.get("visible"))})
    ready = [r for r in rows if r["value"] is not None]
    ordered = sorted(ready, key=lambda r: int(r["period"]))
    events = []
    for x in range(len(ordered)):
        for y in range(x + 1, len(ordered)):
            f, s = series[ordered[x]["id"]], series[ordered[y]["id"]]
            for j in range(max(1, i - lookback_events + 1), i + 1):
                if None in (f[j], s[j], f[j - 1], s[j - 1]):
                    continue
                d0, d1 = f[j - 1] - s[j - 1], f[j] - s[j]
                if d0 <= 0 < d1 or d0 >= 0 > d1:
                    kind = "BULLISH_CROSS" if d1 > 0 else "BEARISH_CROSS"
                    eid = "MAX-" + hashlib.sha256(f"{symbol}|{tf}|{bars[j]['open_utc']}|{ordered[x]['id']}|{ordered[y]['id']}|{kind}".encode()).hexdigest()[:12]
                    events.append({"event_id": eid, "kind": kind, "fast": ordered[x]["id"], "slow": ordered[y]["id"], "bar_open_utc": bars[j]["open_utc"],
                                   "confirmed_on_close": True})
    vals = [r["value"] for r in ordered]
    asc = len(vals) >= 2 and all(vals[q] > vals[q + 1] for q in range(len(vals) - 1))      # fast above slow = bullish order
    desc = len(vals) >= 2 and all(vals[q] < vals[q + 1] for q in range(len(vals) - 1))
    slowest = ordered[-1] if ordered else None
    if not ordered or len(ordered) < 2:
        ctx, why = "UNKNOWN", "za mało średnich po rozgrzewce"
    elif asc and c[i] > ordered[0]["value"] and (ordered[0]["slope_per_bar"] or 0) > 0:
        ctx, why = "TREND_UP", "średnie ułożone rosnąco (szybka nad wolną), cena nad najszybszą, nachylenie dodatnie"
    elif desc and c[i] < ordered[0]["value"] and (ordered[0]["slope_per_bar"] or 0) < 0:
        ctx, why = "TREND_DOWN", "średnie ułożone malejąco, cena pod najszybszą, nachylenie ujemne"
    elif slowest and slowest["slope_atr_per_bar"] is not None and abs(slowest["slope_atr_per_bar"]) < 0.02:
        ctx, why = "CONSOLIDATION", f"najwolniejsza średnia płaska (|nachylenie| {abs(slowest['slope_atr_per_bar']):.3f} ATR/bar < 0.02)"
    elif asc or desc:
        ctx, why = "CORRECTION", "ułożenie średnich trendowe, ale cena / nachylenie najszybszej przeciwne"
    else:
        ctx, why = "MIXED", "średnie przeplatają się"
    v = {"close": c[i], "atr14": _r(a[i]), "mas": rows, "ordering": "BULLISH" if asc else "BEARISH" if desc else "MIXED", "context": ctx,
         "context_rule": why, "crosses": events[-10:], "rules": {"crosses": "zmiana znaku (szybka − wolna) między dwoma zamknięciami",
                                                                     "consolidation": "|nachylenie najwolniejszej| < 0.02 ATR/bar"}}
    return contract.result("moving_averages", VERSION, cfg, symbol=symbol, tf=tf, bars=bars, status="ready", values=v, t0=t0, tf_seconds=TF_SEC.get(tf or ""))


def chart_lines(bars: list[dict], bb_cfg: dict | None = None, mas: list[dict] | None = None, ema_periods: list[int] | None = None) -> list[dict]:
    """Chart line series from the same functions (BB upper/middle/lower + visible MAs, or the legacy EMA list of the profile)."""
    times = [b["open_utc"] for b in bars]
    c = [b["c"] for b in bars]

    def pts(vals):
        return [{"time": t, "value": round(v, 5)} for t, v in zip(times, vals) if v is not None]
    out = []
    for n in ema_periods or []:
        out.append({"id": f"EMA{n}", "label": f"EMA {n}", "points": pts(ema(c, n)), "visual_only": False, "engine": VERSION})
    for m in mas or []:
        if m.get("visible"):
            out.append({"id": m["id"], "label": f"{m['type']} {m['period']}", "points": pts(MA_FN[m["type"]](c, int(m["period"]))), "visual_only": True,
                        "engine": VERSION})
    if bb_cfg:
        bb = bollinger(c, int(bb_cfg["period"]), float(bb_cfg.get("k", bb_cfg.get("std_mult", 2.0))))
        out += [{"id": "BB_U", "label": "BB górna", "points": pts(bb["upper"]), "visual_only": False, "engine": VERSION},
                {"id": "BB_M", "label": "BB środek", "points": pts(bb["middle"]), "visual_only": False, "engine": VERSION},
                {"id": "BB_L", "label": "BB dolna", "points": pts(bb["lower"]), "visual_only": False, "engine": VERSION}]
    return out
