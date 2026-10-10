"""Symbol-agnostic market analysis used by the multi-market scanner.

Inputs are bars of ONE symbol from the connected MT5 terminal (H1, H4, D1; oldest first, newest may be
forming). Every indicator uses CLOSED bars only. The result describes the market (trend per timeframe,
momentum, trend strength, volatility, daily IV walls position, cost of the spread) and a ranking score
0-100 that only orders symbols for a closer look - it is a heuristic, not a probability and not a trade signal.
The MasterQUO strategies S01-S10 and the execution path stay on the main symbol; nothing here places orders.
"""
from __future__ import annotations

import math

from ..engine import volzones
from ..strategies import indicators as ind

MODEL_VERSION = "MQ-MARKETSCAN-1.0.0"
TFS = ("H1", "H4", "D1")


def _last(xs):
    return next((v for v in reversed(xs) if v is not None), None)


def _adx(h: list[float], lo: list[float], c: list[float], n: int = 14) -> float | None:
    """Wilder ADX (same construction as M02I)."""
    if len(c) <= 2 * n:
        return None
    tr = ind.true_range(h, lo, c)
    pdm = [0.0] + [max(h[i] - h[i - 1], 0.0) if h[i] - h[i - 1] > lo[i - 1] - lo[i] else 0.0 for i in range(1, len(c))]
    mdm = [0.0] + [max(lo[i - 1] - lo[i], 0.0) if lo[i - 1] - lo[i] > h[i] - h[i - 1] else 0.0 for i in range(1, len(c))]
    trs, ps, ms = sum(tr[1:n + 1]), sum(pdm[1:n + 1]), sum(mdm[1:n + 1])
    dx = []
    for i in range(n, len(c)):
        if i > n:
            trs, ps, ms = trs - trs / n + tr[i], ps - ps / n + pdm[i], ms - ms / n + mdm[i]
        p = 100 * ps / trs if trs > 0 else 0.0
        m = 100 * ms / trs if trs > 0 else 0.0
        dx.append(100 * abs(p - m) / (p + m) if p + m > 0 else 0.0)
    a = sum(dx[:n]) / n
    for v in dx[n:]:
        a = (a * (n - 1) + v) / n
    return a


def tf_view(closed: list[dict]) -> dict:
    c = [b["c"] for b in closed]
    h = [b["h"] for b in closed]
    lo = [b["l"] for b in closed]
    if len(c) < 60:
        return {"status": "INSUFFICIENT_HISTORY", "closed_bars": len(c)}
    e20, e50, e200 = _last(ind.ema(c, 20)), _last(ind.ema(c, 50)), _last(ind.ema(c, 200)) if len(c) >= 200 else None
    last = c[-1]
    if e20 > e50 and (e200 is None or last > e200):
        trend = "UP"
    elif e20 < e50 and (e200 is None or last < e200):
        trend = "DOWN"
    else:
        trend = "MIXED"
    atr = _last(ind.atr(h, lo, c, 14))
    up, dn = ind.donchian_prior(h, lo, 20)
    u, d = up[-1], dn[-1]
    return {"status": "OK", "closed_bars": len(c), "close": last, "trend": trend, "ema20": e20, "ema50": e50, "ema200": e200,
            "rsi14": _last(ind.rsi(c, 14)), "adx14": _adx(h, lo, c, 14), "atr14": atr,
            "donchian20_high": u, "donchian20_low": d,
            "donchian_pos": None if u is None or d is None or u <= d else round((last - d) / (u - d), 3),
            "ema20_dist_atr": None if not atr else round((last - e20) / atr, 2),
            "last_closed_utc": closed[-1]["open_utc"]}


def analyze(symbol: str, bars: dict[str, list[dict]], meta: dict | None, quote: dict | None, vol_cfg) -> dict:
    meta = meta or {}
    digits = int(meta.get("digits") or 5)
    r = lambda x, k=digits: None if x is None else round(x, k)  # noqa: E731
    closed = {tf: [b for b in bars.get(tf, []) if b.get("closed") and b.get("open_utc")] for tf in TFS}
    views = {tf: tf_view(closed[tf]) for tf in TFS}
    out: dict = {"symbol": symbol, "model": MODEL_VERSION, "description": meta.get("description"), "path": meta.get("path"),
                 "digits": digits, "currency_profit": meta.get("currency_profit"), "visible": meta.get("visible")}
    if any(v["status"] != "OK" for v in views.values()):
        out.update(status="INSUFFICIENT_HISTORY", timeframes={tf: {"status": v["status"], "closed_bars": v.get("closed_bars")} for tf, v in views.items()})
        return out
    d1, h4, h1 = views["D1"], views["H4"], views["H1"]
    price = (quote or {}).get("bid") or (bars["H1"][-1]["c"] if bars.get("H1") else h1["close"])
    prev_close = closed["D1"][-1]["c"]
    c5 = closed["D1"][-6]["c"] if len(closed["D1"]) >= 6 else None
    vol = volzones.compute(bars.get("D1", []), vol_cfg, digits=digits, quote=quote)
    sigma_pos = None
    if vol.get("status") == "OK" and vol.get("expected_move_1s"):
        a = vol["day"]["open"]
        move = math.log((a + vol["expected_move_1s"]) / a) if a else None
        if move:
            sigma_pos = round(math.log(price / a) / move, 2)
    spread = (quote or {}).get("spread")
    spread_atr_pct = round(100 * spread / h1["atr14"], 1) if spread is not None and h1["atr14"] else None
    adx4 = h4["adx14"] or 0.0
    aligned = h4["trend"] == d1["trend"] and h4["trend"] in ("UP", "DOWN")
    hv_pct = vol.get("hv_percentile_1y")
    if adx4 >= 25 and aligned:
        regime = "TREND_UP" if h4["trend"] == "UP" else "TREND_DOWN"
    elif adx4 < 18:
        regime = "RANGE"
    elif hv_pct is not None and hv_pct >= 85:
        regime = "HIGH_VOLATILITY"
    else:
        regime = "MIXED"
    obs = []
    if aligned and h4["ema20_dist_atr"] is not None and abs(h4["ema20_dist_atr"]) <= 0.6:
        obs.append("TREND_PULLBACK_TO_EMA20_H4")
    if h4["donchian20_high"] is not None and h4["close"] > h4["donchian20_high"]:
        obs.append("H4_CLOSE_ABOVE_DONCHIAN20")
    if h4["donchian20_low"] is not None and h4["close"] < h4["donchian20_low"]:
        obs.append("H4_CLOSE_BELOW_DONCHIAN20")
    if sigma_pos is not None and sigma_pos >= 0.9:
        obs.append("AT_OR_ABOVE_UPPER_IV_WALL_1S")
    if sigma_pos is not None and sigma_pos <= -0.9:
        obs.append("AT_OR_BELOW_LOWER_IV_WALL_1S")
    if d1["rsi14"] is not None and d1["rsi14"] >= 70:
        obs.append("D1_RSI_OVERBOUGHT")
    if d1["rsi14"] is not None and d1["rsi14"] <= 30:
        obs.append("D1_RSI_OVERSOLD")
    if spread_atr_pct is not None and spread_atr_pct > 25:
        obs.append("SPREAD_HIGH_VS_ATR_H1")
    # ranking heuristic (0-100): trend strength + alignment + a location worth a look - spread cost
    score = min(40.0, adx4 * 1.2) + (20 if aligned else 0) + (15 if obs and obs[0] == "TREND_PULLBACK_TO_EMA20_H4" else 0)
    score += 10 if any(o.startswith("H4_CLOSE_") for o in obs) else 0
    score += 10 if any("IV_WALL" in o for o in obs) else 0
    if spread_atr_pct is not None:
        score -= min(30.0, spread_atr_pct * 0.6)
    bias = h4["trend"] if aligned else "NEUTRAL"
    h1_last = bars["H1"][-1] if bars.get("H1") else None
    out.update(
        status="OK", price=r(price), change_d1_pct=round(100 * (price / prev_close - 1), 2),
        change_5d_pct=round(100 * (price / c5 - 1), 2) if c5 else None,
        regime=regime, bias=bias, score=round(max(0.0, min(100.0, score)), 1), observations=obs,
        atr_d1=r(d1["atr14"]), atr_d1_pct=round(100 * d1["atr14"] / price, 2) if d1["atr14"] else None, atr_h1=r(h1["atr14"]),
        spread=r(spread) if spread is not None else None, spread_atr_h1_pct=spread_atr_pct,
        sigma_position=sigma_pos, quote_age_seconds=(quote or {}).get("age_seconds"),
        last_bar_utc=h1_last["open_utc"] if h1_last else None,
        timeframes={tf: {k: (r(v) if isinstance(v, float) and k not in ("rsi14", "adx14", "donchian_pos", "ema20_dist_atr") else
                             (round(v, 1) if isinstance(v, float) and k in ("rsi14", "adx14") else v))
                         for k, v in views[tf].items()} for tf in TFS},
        volatility={k: vol.get(k) for k in ("status", "hv_annual_pct", "hv_percentile_1y", "iv_annual_pct", "iv_source", "expected_high",
                                            "expected_low", "expected_move_1s", "day", "previous_day", "walls", "contract")},
        score_note="Ranking do przeglądu (heurystyka), nie prawdopodobieństwo i nie sygnał wejścia.")
    return out
