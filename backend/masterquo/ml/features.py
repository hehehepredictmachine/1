"""FeatureEngine (MQ-FEAT-1.0.0) - one deterministic feature code for training AND prediction.

Input: a MarketView (closed bars per TF, Bid/Ask) + a setup candidate + the decision time `asof`.
Every TF is cut AS-OF: only bars whose close time (open + TF) <= asof are used, so a view that
already contains later bars yields identical features. Confirmed pivots only (confirmed_index).
Unknown values are NaN (not 0) - both models handle missing values natively; selected groups also
get explicit `*_missing` flags. Account ids, future PnL, MAE/MFE and labels are never features.
Units are in the schema (`SCHEMA`): ATR-normalised distances, ratios, RSI points, hour of day...
Tick volume is the broker's tick count for a CFD (activity proxy), never "exchange volume".
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta

from ..strategies import indicators as ind
from ..strategies import regime as regime_mod
from ..strategies.base import TF_SECONDS, MarketView, TFView

FEATURE_SCHEMA_VERSION = "MQ-FEAT-1.0.0"
NAN = float("nan")

CATEGORICAL = {"strategy_id": [f"S{i:02d}" for i in range(1, 11)], "direction": ["LONG", "SHORT"], "timeframe": ["M1", "M5", "M15", "H1"],
               "regime": ["TREND_UP", "TREND_DOWN", "RANGE", "COMPRESSION", "EXPANSION", "EXHAUSTION_OR_REVERSAL_CANDIDATE", "TRANSITION",
                          "DATA_UNAVAILABLE", "STALE"],
               "family": ["TREND", "BREAKOUT", "REVERSION", "REVERSAL"]}


def _num(name, unit, desc):
    return {"name": name, "type": "float", "unit": unit, "desc": desc}


_TF_BLOCK = [
    ("ret1", "ATR", "zwrot ostatniej świecy / ATR14 (znak zgodny z kierunkiem setupu)"),
    ("ret3", "ATR", "zwrot 3 świec / ATR14 (znak wg kierunku)"),
    ("ret12", "ATR", "zwrot 12 świec / ATR14 (znak wg kierunku)"),
    ("atr_pct", "%", "ATR14 / cena x 100"),
    ("atr_ratio", "ratio", "ATR5 / ATR50"),
    ("rsi", "pkt", "RSI14 (dla SHORT 100-RSI)"),
    ("macdh_atr", "ATR", "histogram MACD / ATR14 (znak wg kierunku)"),
    ("slope20", "ATR/bar", "nachylenie EMA20 (5 świec) w ATR (znak wg kierunku)"),
    ("dist_ema20", "ATR", "(close - EMA20)/ATR (znak wg kierunku)"),
    ("dist_ema50", "ATR", "(close - EMA50)/ATR (znak wg kierunku)"),
    ("er20", "0-1", "efficiency ratio 20"),
    ("bbw_pct", "0-1", "percentyl szerokości Bollingera (120)"),
    ("don_pos", "0-1", "pozycja ceny w kanale 20 świec (wg kierunku: 1 = przy krawędzi w stronę setupu)"),
    ("body", "0-1", "korpus / zakres ostatniej świecy"),
    ("wick_with", "0-1", "knot w stronę setupu / zakres"),
    ("wick_against", "0-1", "knot przeciwko setupowi / zakres"),
    ("range_atr", "ATR", "zakres ostatniej świecy / ATR"),
    ("piv_hi_dist", "ATR", "odległość do ostatniego potwierdzonego szczytu / ATR"),
    ("piv_lo_dist", "ATR", "odległość do ostatniego potwierdzonego dołka / ATR"),
    ("piv_age", "bars", "liczba świec od ostatniego potwierdzonego pivotu"),
    ("tick_activity", "ratio", "liczba ticków ostatniej świecy / średnia 20 (aktywność tickowa CFD)"),
]
TF_FEATS = ("M5", "M15", "H1")
HTF_FEATS = ("H4", "D1")

SCHEMA: list[dict] = []
for _tf in TF_FEATS:
    for _n, _u, _d in _TF_BLOCK:
        SCHEMA.append(_num(f"{_tf}_{_n}", _u, f"{_tf}: {_d}"))
for _tf in HTF_FEATS:
    SCHEMA += [_num(f"{_tf}_dir", "-1/0/1", f"{_tf}: kierunek reżimu względem setupu"), _num(f"{_tf}_slope20", "ATR/bar", f"{_tf}: nachylenie EMA20 wg kierunku"),
               _num(f"{_tf}_er20", "0-1", f"{_tf}: efficiency ratio")]
SCHEMA += [
    _num("spread_atr_m5", "ATR", "spread / ATR14(M5)"), _num("hour_sin", "-", "sin godziny UTC"), _num("hour_cos", "-", "cos godziny UTC"),
    _num("dow", "0-6", "dzień tygodnia UTC"), _num("sess_asia", "0/1", "00-07 UTC"), _num("sess_london", "0/1", "07-12 UTC"),
    _num("sess_ny", "0/1", "12-21 UTC"), _num("risk_atr", "ATR", "|wejście - SL| / ATR TF setupu"), _num("rr_tp1", "R", "odległość TP1 / ryzyko"),
    _num("rr_last", "R", "odległość ostatniego celu / ryzyko"), _num("n_targets", "-", "liczba celów"), _num("setup_score", "0-100", "punktacja ACTIVE"),
    _num("fit_score", "0-100", "dopasowanie strategii do reżimu"), _num("pts_structure", "pkt", "punkty struktury"), _num("pts_formation", "pkt", "punkty formacji"),
    _num("pts_momentum", "pkt", "punkty momentum"), _num("pts_trigger", "pkt", "punkty triggera"), _num("pts_htf", "pkt", "punkty HTF"),
    _num("countertrend", "0/1", "setup przeciw HTF"), _num("conflicts", "-", "liczba konfliktów TF"), _num("dxy_missing", "0/1", "brak DXY (opcjonalny)"),
    _num("htf_missing", "0/1", "brak H4/D1"),
]
SCHEMA += [{"name": k, "type": "category", "unit": "-", "desc": f"kategoria {k}", "categories": v} for k, v in CATEGORICAL.items()]
FEATURE_NAMES = [f["name"] for f in SCHEMA]


def _cut(v: TFView, asof: datetime) -> int:
    """Number of bars of `v` closed at or before `asof`."""
    sec = TF_SECONDS[v.tf]
    n = len(v.t)
    while n > 0 and datetime.fromisoformat(v.t[n - 1].replace("Z", "+00:00")) + timedelta(seconds=sec) > asof:
        n -= 1
    return n


def _sub(v: TFView, n: int) -> TFView:
    if n == len(v.t):
        return v
    bars = [{"open_utc": t, "o": o, "h": h, "l": lo, "c": c, "tv": tv, "closed": True} for t, o, h, lo, c, tv in
            zip(v.t[:n], v.o[:n], v.h[:n], v.l[:n], v.c[:n], v.tv[:n])]
    return TFView(v.tf, bars)


def _safe(x) -> float:
    return NAN if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))) else float(x)


def tf_block(v: TFView | None, sgn: int) -> dict:
    out = {n: NAN for n, _u, _d in _TF_BLOCK}
    if v is None or len(v) < 60:
        return out
    i = v.last
    a = v.atr()[i]
    if not a:
        return out
    c = v.c
    out["ret1"] = sgn * (c[i] - c[i - 1]) / a
    out["ret3"] = sgn * (c[i] - c[i - 3]) / a
    out["ret12"] = sgn * (c[i] - c[i - 12]) / a
    out["atr_pct"] = 100 * a / c[i]
    a5, a50 = v.atr(5)[i], v.atr(50)[i]
    out["atr_ratio"] = _safe(a5 / a50) if a5 and a50 else NAN
    r = v.rsi()[i]
    out["rsi"] = NAN if r is None else (r if sgn > 0 else 100 - r)
    mh = v.macd_hist()[i]
    out["macdh_atr"] = NAN if mh is None else sgn * mh / a
    e20, e50 = v.ema(20), v.ema(50)
    sl = ind.slope_atr(e20, v.atr(), i, 5)
    out["slope20"] = NAN if sl is None else sgn * sl
    out["dist_ema20"] = NAN if e20[i] is None else sgn * (c[i] - e20[i]) / a
    out["dist_ema50"] = NAN if e50[i] is None else sgn * (c[i] - e50[i]) / a
    out["er20"] = _safe(v.get("er20", lambda: ind.efficiency_ratio(c, 20))[i])
    bbw = v.get("bbw", lambda: ind.bb_width(c, 20, 2.0))
    out["bbw_pct"] = _safe(ind.percentile_rank(bbw, i, 120)) if i >= 120 else NAN
    up, dn = v.get("don20", lambda: ind.donchian_prior(v.h, v.l, 20))
    if up[i] is not None and up[i] > dn[i]:
        pos = (c[i] - dn[i]) / (up[i] - dn[i])
        out["don_pos"] = pos if sgn > 0 else 1 - pos
    rng = v.h[i] - v.l[i]
    if rng > 0:
        out["body"] = abs(c[i] - v.o[i]) / rng
        upper = (v.h[i] - max(v.o[i], c[i])) / rng
        lower = (min(v.o[i], c[i]) - v.l[i]) / rng
        out["wick_with"], out["wick_against"] = (lower, upper) if sgn > 0 else (upper, lower)
        out["range_atr"] = rng / a
    piv = ind.known_pivots(v.pivots(), i)
    hs = [p for p in piv if p["kind"] == "H"]
    ls = [p for p in piv if p["kind"] == "L"]
    if hs:
        out["piv_hi_dist"] = (hs[-1]["price"] - c[i]) / a
    if ls:
        out["piv_lo_dist"] = (c[i] - ls[-1]["price"]) / a
    if hs or ls:
        out["piv_age"] = i - max(p["index"] for p in (hs[-1:] + ls[-1:]))
        if sgn < 0:
            out["piv_hi_dist"], out["piv_lo_dist"] = out["piv_lo_dist"], out["piv_hi_dist"]
    if len(v.tv) > 21 and sum(v.tv[i - 20:i]) > 0:
        out["tick_activity"] = v.tv[i] / (sum(v.tv[i - 20:i]) / 20)
    return out


def compute(view: MarketView, cand: dict, asof: datetime) -> dict:
    """Features for one setup candidate at decision time `asof` (closed bars only, cut as-of)."""
    sgn = 1 if cand["direction"] == "LONG" else -1
    tfs = {tf: _sub(v, _cut(v, asof)) for tf, v in view.tfs.items()}
    reg = view.regime
    if any(len(tfs[tf]) != len(v) for tf, v in view.tfs.items()):
        # the view contains bars after `asof`: the regime is recomputed on the as-of cut (no later information)
        reg = regime_mod.evaluate(MarketView(symbol=view.symbol, as_of=asof.isoformat(), tfs=tfs, bid=view.bid, ask=view.ask, point=view.point))
    f: dict = {}
    for tf in TF_FEATS:
        for k, val in tf_block(tfs.get(tf), sgn).items():
            f[f"{tf}_{k}"] = _safe(val)
    per = (reg or {}).get("per_tf") or {}
    for tf in HTF_FEATS:
        d = (per.get(tf) or {}).get("direction")
        f[f"{tf}_dir"] = NAN if d not in ("UP", "DOWN", "FLAT") else (0.0 if d == "FLAT" else (1.0 if (d == "UP") == (sgn > 0) else -1.0))
        v = tfs.get(tf)
        if v is not None and len(v) > 60 and v.atr()[v.last]:
            sl = ind.slope_atr(v.ema(20), v.atr(), v.last, 5)
            f[f"{tf}_slope20"] = NAN if sl is None else sgn * sl
            f[f"{tf}_er20"] = _safe(ind.efficiency_ratio(v.c, 20)[v.last])
        else:
            f[f"{tf}_slope20"] = f[f"{tf}_er20"] = NAN
    m5 = tfs.get("M5")
    a5 = m5.atr()[m5.last] if m5 is not None and len(m5) > 20 else None
    f["spread_atr_m5"] = _safe(view.spread / a5) if a5 and view.bid is not None else NAN
    h = asof.hour + asof.minute / 60
    f["hour_sin"], f["hour_cos"] = math.sin(2 * math.pi * h / 24), math.cos(2 * math.pi * h / 24)
    f["dow"] = float(asof.weekday())
    f["sess_asia"], f["sess_london"], f["sess_ny"] = float(0 <= asof.hour < 7), float(7 <= asof.hour < 12), float(12 <= asof.hour < 21)
    ep = cand.get("entry_plan") or {}
    entry = ep.get("trigger_level") or ep.get("reference_price")
    sl_ = cand.get("stop_loss")
    tv = tfs.get(cand["timeframe"])
    atr_s = tv.atr()[tv.last] if tv is not None and len(tv) > 20 else None
    risk = abs(entry - sl_) if entry is not None and sl_ is not None else None
    f["risk_atr"] = _safe(risk / atr_s) if risk and atr_s else NAN
    tg = cand.get("targets") or []
    f["rr_tp1"] = _safe(abs(tg[0]["price"] - entry) / risk) if tg and risk else NAN
    f["rr_last"] = _safe(abs(tg[-1]["price"] - entry) / risk) if tg and risk else NAN
    f["n_targets"] = float(len(tg))
    f["setup_score"] = _safe(cand.get("setup_score"))
    f["fit_score"] = _safe(cand.get("strategy_fit_score"))
    pts = (cand.get("score") or {}).get("points") or {}
    for k in ("structure", "formation", "momentum", "trigger", "htf"):
        f[f"pts_{k}"] = _safe(pts.get(k))
    f["countertrend"] = float(bool(cand.get("countertrend")))
    f["conflicts"] = float(len((reg or {}).get("conflicts") or []))
    f["dxy_missing"] = 1.0
    f["htf_missing"] = float(not tfs.get("H4") or not tfs.get("D1"))
    f["strategy_id"] = cand["strategy_id"]
    f["direction"] = cand["direction"]
    f["timeframe"] = cand["timeframe"]
    f["regime"] = (reg or {}).get("state") or "DATA_UNAVAILABLE"
    f["family"] = cand.get("family") or "TREND"
    missing = [n for n in FEATURE_NAMES if n not in f]
    if missing:
        raise RuntimeError("FEATURE_SCHEMA_INCOMPLETE:" + ",".join(missing[:5]))
    return {n: f[n] for n in FEATURE_NAMES}


def to_json_safe(feats: dict) -> dict:
    """NaN -> None for storage (JSON has no NaN); `from_json` restores NaN."""
    return {k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in feats.items()}


def from_json(d: dict) -> dict:
    return {k: (NAN if v is None and k not in CATEGORICAL else v) for k, v in d.items()}
