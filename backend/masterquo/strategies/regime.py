"""MarketRegimeEngine (MQ-REGIME-1.0.0) - context, not a forecast.

Per timeframe, on CLOSED bars only (the forming bar is ignored here):
  er        Kaufman efficiency ratio over `er_n` bars (0 = noise, 1 = straight line)
  slope     EMA20 change over 5 bars / (5 x ATR14)  (per-bar slope in ATR units)
  bbw_pct   percentile of Bollinger width(20,2) among the previous `bbw_lookback` bars
  atr_ratio ATR5 / ATR50 (short vs long volatility)
  ext       |close - EMA20| / ATR14 (stretch from the mean)
  fading    MACD histogram magnitude falling for 2 bars in the direction of the stretch
Direction: UP if EMA20 > EMA50, close > EMA50 and slope > slope_dir; DOWN symmetric; else FLAT.

State (first match wins, so volatility is never mistaken for direction):
  DATA_UNAVAILABLE  fewer than `min_bars` closed bars
  EXHAUSTION_OR_REVERSAL_CANDIDATE  ext >= exhaustion_ext and er >= 0.2 and fading
  EXPANSION         atr_ratio >= expansion_atr_ratio or last range >= expansion_bar_atr x ATR14
  COMPRESSION       bbw_pct <= compression_pct and atr_ratio <= compression_atr_ratio
  TREND_UP/DOWN     er >= trend_er and |slope| >= trend_slope and direction agrees
  RANGE             er <= range_er and |slope| <= range_slope
  TRANSITION        otherwise
The overall regime is the state of the local TF (default M15); M1/M5 = current move,
H1 = local context, H4/D1 = background. Conflicts are reported with their horizon, never used
to delete candidates. Data status STALE/UNAVAILABLE overrides the state.
"""
from __future__ import annotations

from . import indicators as ind
from .base import MarketView, TFView

ENGINE_VERSION = "MQ-REGIME-1.0.0"
DEFAULTS = {"er_n": 20, "trend_er": 0.30, "trend_slope": 0.05, "slope_dir": 0.02, "range_er": 0.20, "range_slope": 0.03,
            "bbw_lookback": 120, "compression_pct": 0.20, "compression_atr_ratio": 0.90, "expansion_atr_ratio": 1.6,
            "expansion_bar_atr": 2.0, "exhaustion_ext": 2.5, "min_bars": 130, "local_tf": "M15"}
STATES = ("TREND_UP", "TREND_DOWN", "RANGE", "COMPRESSION", "EXPANSION", "EXHAUSTION_OR_REVERSAL_CANDIDATE", "TRANSITION",
          "DATA_UNAVAILABLE", "STALE")
HORIZON = {"M1": "MICRO", "M5": "MICRO", "M15": "LOCAL", "H1": "LOCAL_CONTEXT", "H4": "HTF", "D1": "HTF"}


def tf_regime(v: TFView, p: dict) -> dict:
    n = len(v)
    if n < p["min_bars"]:
        return {"state": "DATA_UNAVAILABLE", "direction": None, "reason": f"WARMING_UP_{n}/{p['min_bars']}"}
    i = v.last
    a14, a5, a50 = v.atr(14), v.atr(5), v.atr(50)
    e20, e50 = v.ema(20), v.ema(50)
    er = ind.efficiency_ratio(v.c, p["er_n"])[i]
    sl = ind.slope_atr(e20, a14, i, 5)
    bbw = v.get("bbw", lambda: ind.bb_width(v.c, 20, 2.0))
    bbw_pct = ind.percentile_rank(bbw, i, p["bbw_lookback"])
    atr_ratio = (a5[i] / a50[i]) if a5[i] and a50[i] else None
    ext = abs(v.c[i] - e20[i]) / a14[i] if e20[i] is not None and a14[i] else None
    mh = v.macd_hist()
    sgn = 1 if (e20[i] is not None and v.c[i] >= e20[i]) else -1
    fading = (mh[i] is not None and mh[i - 1] is not None and mh[i - 2] is not None
              and sgn * mh[i] < sgn * mh[i - 1] < sgn * mh[i - 2])
    rng = v.h[i] - v.l[i]
    if None in (er, sl, e20[i], e50[i], a14[i]):
        return {"state": "DATA_UNAVAILABLE", "direction": None, "reason": "INDICATORS_WARMING_UP"}
    if e20[i] > e50[i] and v.c[i] > e50[i] and sl > p["slope_dir"]:
        direction = "UP"
    elif e20[i] < e50[i] and v.c[i] < e50[i] and sl < -p["slope_dir"]:
        direction = "DOWN"
    else:
        direction = "FLAT"
    m = {"er": round(er, 3), "slope_atr": round(sl, 4), "bbw_pct": None if bbw_pct is None else round(bbw_pct, 3),
         "atr_ratio": None if atr_ratio is None else round(atr_ratio, 3), "ext_atr": None if ext is None else round(ext, 2),
         "momentum_fading": fading, "atr14": round(a14[i], 4), "last_range_atr": round(rng / a14[i], 2)}
    if ext is not None and ext >= p["exhaustion_ext"] and er >= 0.2 and fading:
        st, why = "EXHAUSTION_OR_REVERSAL_CANDIDATE", f"ext {ext:.2f} ATR >= {p['exhaustion_ext']}, momentum słabnie"
    elif (atr_ratio is not None and atr_ratio >= p["expansion_atr_ratio"]) or rng >= p["expansion_bar_atr"] * a14[i]:
        st, why = "EXPANSION", f"ATR5/ATR50 {atr_ratio} lub zakres świecy {rng / a14[i]:.2f} ATR"
    elif bbw_pct is not None and bbw_pct <= p["compression_pct"] and atr_ratio is not None and atr_ratio <= p["compression_atr_ratio"]:
        st, why = "COMPRESSION", f"szerokość BB w {bbw_pct:.0%} percentylu, ATR5/ATR50 {atr_ratio:.2f}"
    elif er >= p["trend_er"] and abs(sl) >= p["trend_slope"] and direction in ("UP", "DOWN"):
        st, why = ("TREND_UP" if direction == "UP" else "TREND_DOWN"), f"ER {er:.2f}, nachylenie EMA20 {sl:.3f} ATR/świecę"
    elif er <= p["range_er"] and abs(sl) <= p["range_slope"]:
        st, why = "RANGE", f"ER {er:.2f}, nachylenie {sl:.3f}"
    else:
        st, why = "TRANSITION", f"ER {er:.2f}, nachylenie {sl:.3f} – brak jednoznacznego stanu"
    return {"state": st, "direction": direction, "metrics": m, "reason": why, "as_of_bar": v.t[i]}


def evaluate(view: MarketView, p: dict | None = None, data_status: str = "OK") -> dict:
    p = {**DEFAULTS, **(p or {})}
    per = {tf: tf_regime(v, p) for tf, v in view.tfs.items()}
    local = p["local_tf"]
    if data_status in ("STALE", "UNAVAILABLE"):
        state = "STALE" if data_status == "STALE" else "DATA_UNAVAILABLE"
        return {"engine": ENGINE_VERSION, "state": state, "local_tf": local, "per_tf": per, "conflicts": [], "reason": "DATA_" + data_status,
                "horizons": {}}
    st = (per.get(local) or {}).get("state", "DATA_UNAVAILABLE")
    dirs = {tf: (per.get(tf) or {}).get("direction") for tf in per}
    conflicts = []
    pairs = (("M5", "M15", "MICRO_VS_LOCAL"), ("M15", "H1", "LOCAL_VS_CONTEXT"), ("H1", "H4", "CONTEXT_VS_HTF"))
    for a, b, name in pairs:
        if {dirs.get(a), dirs.get(b)} == {"UP", "DOWN"}:
            conflicts.append({"kind": name, "a": a, "b": b, "a_dir": dirs.get(a), "b_dir": dirs.get(b)})
    horizons = {"MICRO": dirs.get("M5"), "LOCAL": dirs.get("M15"), "LOCAL_CONTEXT": dirs.get("H1"), "HTF": dirs.get("H4"), "BACKGROUND": dirs.get("D1")}
    return {"engine": ENGINE_VERSION, "state": st, "local_tf": local, "per_tf": per, "conflicts": conflicts, "horizons": horizons,
            "reason": (per.get(local) or {}).get("reason")}
