"""Daily volatility levels: historical volatility, 1-day contract pricing (Black-76) and IV walls.

What is computed (from MT5 D1 bars of the traded symbol, Bid prices):
  * Daily Open (open of the current broker day = forming D1 bar), today's high/low so far,
    previous day high/low (PDH/PDL) and previous close.
  * Historical volatility (HV) from the last `window` CLOSED D1 bars - close-to-close (log returns,
    sample stdev) or Parkinson (high/low). The current, still-forming day is never used (no look-ahead).
    Annualised with `trading_days_per_year`. HV percentile = rank of today's HV among the HV values
    of the last year (same window), i.e. how high volatility is versus its own history.
  * Volatility used for pricing ("IV"): MT5 gives no option chain for XAUUSD-, so by default HV is the
    proxy for implied volatility (iv_source=HV). With iv_source=MANUAL the user enters an implied
    volatility read elsewhere (e.g. the gold volatility index GVZ or an option chain).
  * Contract pricing: 1-trading-day European options on the daily open (Black-76, r=0, forward = Daily Open,
    T = 1/trading_days_per_year): ATM straddle price -> straddle break-even levels (the market-implied
    daily move), and for every wall the call/put price, delta, probability of finishing beyond the level
    and the (driftless) probability of touching it during the day.
  * IV walls: price zones at Daily Open * exp(+-k * sigma * sqrt(T)) for each k in `walls_sigma`; the zone
    half-width is `wall_band_sigma` (in sigma units). The +-1 sigma levels are the expected daily high/low.

These are statistical reference levels of a model (lognormal, constant volatility). They are not
dealer positioning, not open interest walls and not a forecast; real intraday moves have fat tails.
"""
from __future__ import annotations

import math
from statistics import NormalDist

from ..timeutil import parse_iso

MODEL_VERSION = "MQ-VOLZONES-1.0.0"
_N = NormalDist()


def _ncdf(x: float) -> float:
    return _N.cdf(x)


def hv_close_to_close(closes: list[float]) -> float | None:
    """Daily (not annualised) sample stdev of log returns."""
    rets = [math.log(b / a) for a, b in zip(closes, closes[1:]) if a > 0 and b > 0]
    n = len(rets)
    if n < 2:
        return None
    mu = sum(rets) / n
    return math.sqrt(sum((r - mu) ** 2 for r in rets) / (n - 1))


def hv_parkinson(highs: list[float], lows: list[float]) -> float | None:
    terms = [math.log(h / lo) ** 2 for h, lo in zip(highs, lows) if h > 0 and lo > 0 and h >= lo]
    if len(terms) < 2:
        return None
    return math.sqrt(sum(terms) / (4.0 * math.log(2.0) * len(terms)))


def black76(f: float, k: float, sigma: float, t: float) -> dict:
    """European option on a forward, zero rate. Returns call/put prices, deltas and N(d2)."""
    v = sigma * math.sqrt(t)
    d1 = (math.log(f / k) + 0.5 * v * v) / v
    d2 = d1 - v
    call = f * _ncdf(d1) - k * _ncdf(d2)
    put = k * _ncdf(-d2) - f * _ncdf(-d1)
    return {"call": call, "put": put, "call_delta": _ncdf(d1), "put_delta": _ncdf(d1) - 1.0,
            "p_above": _ncdf(d2), "p_below": _ncdf(-d2)}


def _daily_sigma(closed: list[dict], window: int, estimator: str) -> float | None:
    seg = closed[-(window + 1):]
    if len(seg) < window + 1:
        return None
    if estimator == "parkinson":
        seg = seg[1:]
        return hv_parkinson([b["h"] for b in seg], [b["l"] for b in seg])
    return hv_close_to_close([b["c"] for b in seg])


def _percentile(closed: list[dict], window: int, estimator: str, current: float, lookback: int) -> float | None:
    vals = []
    for end in range(max(window + 1, len(closed) - lookback + 1), len(closed) + 1):
        s = _daily_sigma(closed[:end], window, estimator)
        if s is not None:
            vals.append(s)
    if len(vals) < 20:
        return None
    return round(100.0 * sum(1 for v in vals if v <= current) / len(vals), 1)


def compute(d1_bars: list[dict], cfg, digits: int = 2, quote: dict | None = None) -> dict:
    """d1_bars: bridge D1 bars (oldest first, forming bar last if the day is open). cfg: VolatilityConfig."""
    window = int(cfg.window)
    tdy = float(cfg.trading_days_per_year)
    bars = [b for b in d1_bars if b.get("open_utc")]
    closed = [b for b in bars if b.get("closed")]
    forming = bars[-1] if bars and not bars[-1].get("closed") else None
    out: dict = {"model": MODEL_VERSION, "enabled": bool(cfg.enabled), "estimator": cfg.estimator, "window": window,
                 "trading_days_per_year": tdy, "iv_source": cfg.iv_source, "walls_sigma": list(cfg.walls_sigma),
                 "wall_band_sigma": cfg.wall_band_sigma, "closed_d1": len(closed), "required_d1": window + 1}
    if not cfg.enabled:
        return {**out, "status": "DISABLED"}
    if len(closed) < 2:
        return {**out, "status": "INSUFFICIENT_HISTORY"}
    prev = closed[-1]
    r = lambda x: None if x is None else round(x, digits)
    out["previous_day"] = {"open_utc": prev["open_utc"], "high": r(prev["h"]), "low": r(prev["l"]), "close": r(prev["c"])}
    if forming:
        anchor, day_open_utc = forming["o"], forming["open_utc"]
        hi, lo = forming["h"], forming["l"]
        out["day"] = {"open_utc": day_open_utc, "open": r(anchor), "high": r(hi), "low": r(lo), "last": r(forming["c"]), "state": "OPEN"}
    else:  # market closed (weekend / holiday): projection for the next session from the last close
        anchor, day_open_utc, hi, lo = prev["c"], None, None, None
        out["day"] = {"open_utc": None, "open": r(anchor), "high": None, "low": None, "last": r(prev["c"]), "state": "NEXT_SESSION_PROJECTION"}
    if quote and quote.get("bid") and forming:
        out["day"]["last"] = r(quote["bid"])
    sig_d = _daily_sigma(closed, window, cfg.estimator)
    if sig_d is None:
        return {**out, "status": "INSUFFICIENT_HISTORY"}
    hv_ann = sig_d * math.sqrt(tdy)
    out["hv_daily_pct"] = round(100 * sig_d, 4)
    out["hv_annual_pct"] = round(100 * hv_ann, 2)
    out["hv_percentile_1y"] = _percentile(closed, window, cfg.estimator, sig_d, int(tdy))
    if cfg.iv_source == "MANUAL" and cfg.manual_iv_pct:
        iv_ann = cfg.manual_iv_pct / 100.0
        out["iv_note"] = "Zmienność implikowana wpisana ręcznie (np. GVZ lub łańcuch opcji)."
    else:
        iv_ann = hv_ann
        out["iv_note"] = "MT5 nie udostępnia opcji na XAUUSD- – jako IV użyto zmienności historycznej (HV)."
    t = 1.0 / tdy
    move = iv_ann * math.sqrt(t)                     # 1 sigma of the daily log return
    out["iv_annual_pct"] = round(100 * iv_ann, 2)
    out["iv_vs_hv"] = round(iv_ann / hv_ann, 3) if hv_ann > 0 else None
    out["expected_move_1s"] = r(anchor * (math.exp(move) - 1))
    atm = black76(anchor, anchor, iv_ann, t)
    straddle = atm["call"] + atm["put"]
    out["contract"] = {"model": "Black-76, r=0, forward = Daily Open, T = 1 dzień handlowy", "expiry": "koniec bieżącego dnia brokera",
                       "atm_strike": r(anchor), "atm_call": r(atm["call"]), "atm_put": r(atm["put"]), "straddle": r(straddle),
                       "breakeven_up": r(anchor + straddle), "breakeven_down": r(anchor - straddle)}
    walls, zones = [], []
    band = cfg.wall_band_sigma * move
    for k in sorted(set(cfg.walls_sigma)):
        for side, sgn in (("UP", 1), ("DOWN", -1)):
            lvl = anchor * math.exp(sgn * k * move)
            o = black76(anchor, lvl, iv_ann, t)
            p_end = o["p_above"] if sgn > 0 else o["p_below"]
            w = {"sigma": k, "side": side, "level": r(lvl), "zone_low": r(lvl * math.exp(-band)), "zone_high": r(lvl * math.exp(band)),
                 "option": "CALL" if sgn > 0 else "PUT", "premium": r(o["call"] if sgn > 0 else o["put"]),
                 "delta": round(o["call_delta"] if sgn > 0 else o["put_delta"], 3),
                 "p_close_beyond": round(p_end, 4), "p_touch": round(min(1.0, 2 * p_end), 4),
                 "reached": (hi is not None and hi >= lvl) if sgn > 0 else (lo is not None and lo <= lvl)}
            walls.append(w)
            zones.append({"kind": "IV_WALL", "label": f"IV wall {'+' if sgn > 0 else '−'}{k:g}σ", "sigma": k, "side": side,
                          "low": w["zone_low"], "high": w["zone_high"], "from_utc": day_open_utc})
    out["walls"] = walls
    up1 = anchor * math.exp(move)
    dn1 = anchor * math.exp(-move)
    out["expected_high"], out["expected_low"] = r(up1), r(dn1)
    if hi is not None and lo is not None and up1 > dn1:
        out["day"]["range_used_pct"] = round(100 * (hi - lo) / (up1 - dn1), 1)
    lines = [{"kind": "DAILY_OPEN", "label": "Daily Open", "price": r(anchor)},
             {"kind": "EXPECTED_HIGH", "label": "Daily High (IV 1σ)", "price": r(up1)},
             {"kind": "EXPECTED_LOW", "label": "Daily Low (IV 1σ)", "price": r(dn1)},
             {"kind": "STRADDLE_BE", "label": "Straddle BE+", "price": out["contract"]["breakeven_up"]},
             {"kind": "STRADDLE_BE", "label": "Straddle BE−", "price": out["contract"]["breakeven_down"]},
             {"kind": "PDH", "label": "PDH", "price": r(prev["h"])},
             {"kind": "PDL", "label": "PDL", "price": r(prev["l"])}]
    if hi is not None:
        lines += [{"kind": "DAY_HIGH", "label": "Day High", "price": r(hi)}, {"kind": "DAY_LOW", "label": "Day Low", "price": r(lo)}]
    out["lines"] = lines
    out["zones"] = zones
    out["status"] = "OK" if len(closed) >= window + 1 else "INSUFFICIENT_HISTORY"
    if day_open_utc:
        out["as_of_day_utc"] = parse_iso(day_open_utc).date().isoformat()
    return out
