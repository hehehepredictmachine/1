"""Price-structure lab modules on CLOSED bars (MQ-LAB-MKT-1.0.0). Own implementations, described in
docs/LAB_MODULY_PL.md; names of MQL5 sources are inspiration only (their code was not available in this environment).

M09 Markov chain   M10 regime map   M11 volatility regime   M12 swing structure (origin/confirmed times)
M13 trendlines     M14 liquidity pools   M16 ICT sequence (sweep -> MSS/displacement -> FVG -> retest)
M22 SMMA(3) H/L channel   M23 Z-Score hypotheses   M24 Parabolic SAR (shared scalp implementation)
M25 Stochastic daily breakout candidate   M27 quiet-drift hypothesis

Causality: every value at bar i uses bars <= i; a pivot needs R right bars and is usable only from `confirmed_at`.
"""
from __future__ import annotations

import math

import numpy as np

from ..analytics.ta import TF_SEC
from .common import EPS, arrays, atr, close_time, ema, iso, pct_rank, rolling_std, sma, ts

VERSION = "MQ-LAB-MKT-1.0.0"


# ----------------------------------------------------------------------------- M12 swings
def pivots(bars: list[dict], tf: str, left: int = 3, right: int = 3) -> list[dict]:
    """Confirmed pivots. A high pivot at i: h[i] > max(h[i-left:i]) and h[i] >= max(h[i+1:i+right+1]).
    origin_time = open of bar i; confirmed_at = close of bar i+right (the earliest moment it is known)."""
    a = arrays(bars)
    h, lo = a["h"], a["l"]
    out = []
    for i in range(left, len(bars) - right):
        if h[i] > h[i - left:i].max() and h[i] >= h[i + 1:i + right + 1].max():
            out.append({"kind": "H", "i": i, "price": float(h[i]), "origin_time": bars[i]["open_utc"],
                        "confirmed_i": i + right, "confirmed_at": close_time(bars[i + right], tf)})
        if lo[i] < lo[i - left:i].min() and lo[i] <= lo[i + 1:i + right + 1].min():
            out.append({"kind": "L", "i": i, "price": float(lo[i]), "origin_time": bars[i]["open_utc"],
                        "confirmed_i": i + right, "confirmed_at": close_time(bars[i + right], tf)})
    out.sort(key=lambda p: (p["confirmed_i"], p["i"]))
    return out


def swing_structure(bars: list[dict], tf: str, left: int = 3, right: int = 3) -> dict:
    """HH/HL/LH/LL labels, alternating swing legs (impulse / pullback), retracement and duration; Market Story text."""
    pv = pivots(bars, tf, left, right)
    last = {"H": None, "L": None}
    labelled = []
    for p in pv:
        prev = last[p["kind"]]
        if prev is None:
            lab = "H0" if p["kind"] == "H" else "L0"
        elif p["kind"] == "H":
            lab = "HH" if p["price"] > prev["price"] else "LH"
        else:
            lab = "HL" if p["price"] > prev["price"] else "LL"
        q = {**p, "label": lab}
        labelled.append(q)
        last[p["kind"]] = q
    # alternating sequence (consecutive same-kind pivots -> keep the extreme)
    alt: list[dict] = []
    for p in sorted(labelled, key=lambda p: p["i"]):
        if alt and alt[-1]["kind"] == p["kind"]:
            better = p["price"] > alt[-1]["price"] if p["kind"] == "H" else p["price"] < alt[-1]["price"]
            if better:
                alt[-1] = p
            continue
        alt.append(p)
    legs = []
    for k in range(1, len(alt)):
        a, b = alt[k - 1], alt[k]
        size = b["price"] - a["price"]
        leg = {"from": a["origin_time"], "to": b["origin_time"], "direction": "UP" if size > 0 else "DOWN",
               "size": round(size, 5), "bars": b["i"] - a["i"], "confirmed_at": b["confirmed_at"]}
        if legs and abs(legs[-1]["size"]) > EPS:
            leg["retracement_pct"] = round(abs(size) / abs(legs[-1]["size"]) * 100, 1)
        legs.append(leg)
    for k in range(1, len(legs)):
        legs[k]["role"] = "IMPULSE" if abs(legs[k]["size"]) >= abs(legs[k - 1]["size"]) else "PULLBACK"
    hs = [p for p in labelled if p["kind"] == "H"][-2:]
    ls = [p for p in labelled if p["kind"] == "L"][-2:]
    story = "brak wystarczającej liczby potwierdzonych swingów"
    bias = "UNKNOWN"
    if len(hs) == 2 and len(ls) == 2:
        if hs[-1]["label"] == "HH" and ls[-1]["label"] == "HL":
            bias, story = "UP", "wyższe szczyty i wyższe dołki (HH/HL) – struktura wzrostowa"
        elif hs[-1]["label"] == "LH" and ls[-1]["label"] == "LL":
            bias, story = "DOWN", "niższe szczyty i niższe dołki (LH/LL) – struktura spadkowa"
        else:
            bias, story = "MIXED", f"mieszana struktura ({hs[-1]['label']}/{ls[-1]['label']}) – brak jednoznacznego kierunku"
    return {"pivots": labelled[-30:], "legs": legs[-20:], "bias": bias, "story": story,
            "confirmation_lag_bars": right, "params": {"left": left, "right": right}}


# ----------------------------------------------------------------------------- M10 regime
def efficiency_ratio(c: np.ndarray, n: int = 20) -> float | None:
    if len(c) <= n:
        return None
    path = np.abs(np.diff(c[-n - 1:])).sum()
    return float(abs(c[-1] - c[-n - 1]) / path) if path > EPS else 0.0


def regime_map(bars: list[dict], tf: str, er_n: int = 20, trend_er: float = 0.30, range_er: float = 0.18) -> dict:
    a = arrays(bars)
    er = efficiency_ratio(a["c"], er_n)
    sw = swing_structure(bars, tf)
    if er is None:
        return {"state": "WARMING_UP", "er": None, "measures": {}, "confirmation_lag_bars": sw["confirmation_lag_bars"]}
    if er >= trend_er and sw["bias"] == "UP":
        st = "TREND_UP"
    elif er >= trend_er and sw["bias"] == "DOWN":
        st = "TREND_DOWN"
    elif er <= range_er:
        st = "RANGE"
    else:
        st = "TRANSITION"
    return {"state": st, "er": round(er, 3), "swing_bias": sw["bias"],
            "measures": {"efficiency_ratio_window": er_n, "trend_er_min": trend_er, "range_er_max": range_er,
                         "structure": "ostatnie 2 potwierdzone szczyty i dołki"},
            "confirmation_lag_bars": sw["confirmation_lag_bars"],
            "note": "kontekst – nie samodzielny sygnał; opóźnienie = potwierdzenie pivotu (prawe świece)"}


# ----------------------------------------------------------------------------- M11 volatility regime
def vol_regime(bars: list[dict], n_atr: int = 14, window: int = 200, lo_pct: float = 0.2, hi_pct: float = 0.8, series: int = 300) -> dict:
    a = arrays(bars)
    at = atr(a["h"], a["l"], a["c"], n_atr)
    states = []
    for i in range(len(at)):
        if np.isnan(at[i]) or i < n_atr + 20:
            states.append(None)
            continue
        w = at[max(0, i - window + 1):i + 1]           # past window incl. bar i (closed) - no future
        p = pct_rank(w, at[i])
        states.append(None if p is None else ("COMPRESSION" if p < lo_pct else "EXPANSION" if p > hi_pct else "NORMAL"))
    last_p = pct_rank(at[max(0, len(at) - window):], at[-1]) if len(at) and not np.isnan(at[-1]) else None
    return {"state": states[-1] if states else None, "atr": None if not len(at) or np.isnan(at[-1]) else round(float(at[-1]), 5),
            "atr_percentile": None if last_p is None else round(last_p, 3),
            "series": [{"t": bars[i]["open_utc"], "state": states[i]} for i in range(max(0, len(bars) - series), len(bars))],
            "params": {"atr": n_atr, "window": window, "compression_below": lo_pct, "expansion_above": hi_pct}}


# ----------------------------------------------------------------------------- M09 Markov
STATES = ("DOWN", "FLAT", "UP")


def markov(bars: list[dict], fit_window: int = 500, flat_quantile: float = 0.33, alpha: float = 1.0) -> dict:
    """3-state chain on close-to-close returns. The flat threshold and the transition matrix are estimated ONLY on the
    fit window ending at the last closed bar; the forecast is the next-bar state distribution from the current state."""
    c = arrays(bars)["c"]
    if len(c) < 60:
        return {"status": "warming_up", "reason": "ZA_MALO_SWIEC"}
    r = np.diff(c[-fit_window - 1:]) / c[-fit_window - 1:-1]
    thr = float(np.quantile(np.abs(r), flat_quantile))
    s = np.where(r > thr, 2, np.where(r < -thr, 0, 1))
    m = np.full((3, 3), alpha)
    for x, y in zip(s[:-1], s[1:]):
        m[x, y] += 1
    counts = m - alpha
    p = m / m.sum(axis=1, keepdims=True)
    cur = int(s[-1])
    nxt = p[cur]
    ent = float(-(nxt * np.log2(nxt)).sum())
    stat = np.linalg.matrix_power(p, 64)[0]
    return {"status": "ready", "current_state": STATES[cur], "next_distribution": {STATES[k]: round(float(nxt[k]), 3) for k in range(3)},
            "entropy_bits": round(ent, 3), "max_entropy_bits": round(math.log2(3), 3),
            "transition_matrix": [[round(float(v), 3) for v in row] for row in p], "transition_counts": counts.astype(int).tolist(),
            "stationary": {STATES[k]: round(float(stat[k]), 3) for k in range(3)}, "flat_threshold_return": thr,
            "samples": int(len(s)), "params": {"fit_window": fit_window, "flat_quantile": flat_quantile, "laplace_alpha": alpha}}


# ----------------------------------------------------------------------------- M13 trendlines
def trendlines(bars: list[dict], tf: str, max_pivots: int = 8, tol_atr: float = 0.15, max_lines: int = 4) -> dict:
    a = arrays(bars)
    if len(bars) < 40:
        return {"lines": [], "reason": "ZA_MALO_SWIEC"}
    at = atr(a["h"], a["l"], a["c"])
    tol = float(np.nanmean(at[-50:])) * tol_atr if not np.all(np.isnan(at[-50:])) else 0.0
    pv = pivots(bars, tf)
    lines = []
    n = len(bars)
    for kind, price_arr, side in (("L", a["l"], "SUPPORT"), ("H", a["h"], "RESISTANCE")):
        ps = [p for p in pv if p["kind"] == kind][-max_pivots:]
        for x in range(len(ps)):
            for y in range(x + 1, len(ps)):
                p1, p2 = ps[x], ps[y]
                slope = (p2["price"] - p1["price"]) / (p2["i"] - p1["i"])
                line = lambda i, p1=p1, slope=slope: p1["price"] + slope * (i - p1["i"])  # noqa: E731
                seg = range(p1["i"], p2["i"] + 1)
                if side == "SUPPORT" and any(a["c"][i] < line(i) - tol for i in seg):
                    continue
                if side == "RESISTANCE" and any(a["c"][i] > line(i) + tol for i in seg):
                    continue
                touches = sum(1 for p in ps if abs(p["price"] - line(p["i"])) <= tol and p["i"] >= p1["i"])
                after = range(p2["confirmed_i"] + 1, n)        # usable only after the 2nd anchor is confirmed
                broke = next((i for i in after if (a["c"][i] < line(i) - tol if side == "SUPPORT" else a["c"][i] > line(i) + tol)), None)
                status = "INTACT"
                if broke is not None:
                    status = "BROKEN"
                    rt = next((i for i in range(broke + 1, n) if abs((a["h"][i] if side == "SUPPORT" else a["l"][i]) - line(i)) <= tol), None)
                    if rt is not None:
                        status = "BROKEN_RETESTED"
                lines.append({"id": f"TL-{tf}-{side[0]}-{p1['origin_time']}-{p2['origin_time']}", "side": side,
                              "anchor1": {"t": p1["origin_time"], "price": p1["price"]}, "anchor2": {"t": p2["origin_time"], "price": p2["price"]},
                              "usable_from": p2["confirmed_at"], "slope_per_bar": round(slope, 6), "touches": touches,
                              "value_now": round(line(n - 1), 5), "status": status,
                              "broken_at": bars[broke]["open_utc"] if broke is not None else None})
    # duplicates: same side, similar slope and level now -> keep the one with more touches
    lines.sort(key=lambda L: (-L["touches"], L["anchor2"]["t"]), reverse=False)
    kept: list[dict] = []
    for L in lines:
        if any(K["side"] == L["side"] and abs(K["value_now"] - L["value_now"]) <= tol and
               abs(K["slope_per_bar"] - L["slope_per_bar"]) <= tol / 20 for K in kept):
            continue
        kept.append(L)
    return {"lines": kept[:max_lines * 2], "tolerance": round(tol, 5),
            "method": "własna: pary potwierdzonych pivotów, brak zamknięć po złej stronie między kotwicami, dotknięcia w tolerancji ATR"}


# ----------------------------------------------------------------------------- M14 liquidity
def previous_day_levels(d1: list[dict] | None, as_of_t: float) -> dict | None:
    """PDH/PDL of the last COMPLETED D1 bar before as_of (developing day is never used as 'previous')."""
    if not d1:
        return None
    done = [b for b in d1 if ts(b["open_utc"]) + TF_SEC["D1"] <= as_of_t]
    if not done:
        return None
    b = done[-1]
    return {"day_open": b["open_utc"], "pdh": float(b["h"]), "pdl": float(b["l"]), "available_at": iso(ts(b["open_utc"]) + TF_SEC["D1"])}


def liquidity(bars: list[dict], tf: str, d1: list[dict] | None = None, tol_atr: float = 0.10) -> dict:
    a = arrays(bars)
    if len(bars) < 30:
        return {"pools": [], "reason": "ZA_MALO_SWIEC"}
    at = atr(a["h"], a["l"], a["c"])
    tol = float(np.nanmean(at[-50:])) * tol_atr
    pv = pivots(bars, tf)
    pools = []
    for kind, side in (("H", "ABOVE"), ("L", "BELOW")):
        ps = [p for p in pv if p["kind"] == kind][-20:]
        used = set()
        for x, p in enumerate(ps):
            if x in used:
                continue
            grp = [p] + [q for y, q in enumerate(ps) if y > x and abs(q["price"] - p["price"]) <= tol and not used.add(y)]
            lvl = float(np.mean([g["price"] for g in grp]))
            start = max(g["confirmed_i"] for g in grp)
            pools.append(_pool_status({"id": f"LQ-{tf}-{side}-{p['origin_time']}", "kind": "EQUAL_HIGHS" if kind == "H" and len(grp) > 1 else
                                       "EQUAL_LOWS" if len(grp) > 1 else ("SWING_HIGH" if kind == "H" else "SWING_LOW"),
                                       "side": side, "level": round(lvl, 5), "touches": len(grp), "known_from": grp[-1]["confirmed_at"]}, a, start, side))
    pdl = previous_day_levels(d1, a["t"][-1] + TF_SEC[tf])
    if pdl:
        i0 = int(np.searchsorted(a["t"], ts(pdl["available_at"])))
        for name, lvl, side in (("PDH", pdl["pdh"], "ABOVE"), ("PDL", pdl["pdl"], "BELOW")):
            pools.append(_pool_status({"id": f"LQ-D1-{name}-{pdl['day_open']}", "kind": name, "side": side, "level": lvl, "touches": 1,
                                       "known_from": pdl["available_at"]}, a, i0 - 1, side))
    last = a["c"][-1]
    pools.sort(key=lambda p: abs(p["level"] - last))
    return {"pools": pools[:16], "tolerance": round(tol, 5),
            "note": "pule wywnioskowane ze struktury ceny – to NIE jest odczyt rzeczywistych zleceń stop"}


def _pool_status(p: dict, a: dict, start: int, side: str) -> dict:
    st, at_t = "UNTOUCHED", None
    for i in range(start + 1, len(a["c"])):
        beyond = a["h"][i] > p["level"] if side == "ABOVE" else a["l"][i] < p["level"]
        if not beyond:
            continue
        closed_beyond = a["c"][i] > p["level"] if side == "ABOVE" else a["c"][i] < p["level"]
        st, at_t = ("TAKEN" if closed_beyond else "SWEPT_REJECTED"), i
        break
    p["status"] = st
    p["event_bar"] = int(at_t) if at_t is not None else None
    return p


# ----------------------------------------------------------------------------- M16 ICT
DEFINITIONS = {
    "sweep": "knot świecy poza ostatnim potwierdzonym swingiem (pulą) i zamknięcie z powrotem po wewnętrznej stronie",
    "MSS": "po sweepie: zamknięcie za ostatnim potwierdzonym swingiem przeciwnym (zmiana struktury)",
    "displacement": "świeca MSS ma korpus ≥ displacement_atr × ATR14",
    "FVG": "luka 3-świecowa: low[i] > high[i-2] (wzrostowa) / high[i] < low[i-2] (spadkowa), powstała w odcinku displacementu",
    "retest": "pierwsza późniejsza świeca, której zakres wchodzi w FVG",
    "BOS": "zamknięcie za ostatnim potwierdzonym swingiem w kierunku dotychczasowej struktury (bez sweepu)",
}


def fvgs(bars: list[dict], tf: str, start: int = 2) -> list[dict]:
    a = arrays(bars)
    out = []
    for i in range(max(2, start), len(bars)):
        for d, ok, top, bot in (("BULL", a["l"][i] > a["h"][i - 2], a["l"][i], a["h"][i - 2]),
                                ("BEAR", a["h"][i] < a["l"][i - 2], a["l"][i - 2], a["h"][i])):
            if not ok:
                continue
            size = top - bot
            fill = 0.0
            for j in range(i + 1, len(bars)):
                pen = (top - a["l"][j]) if d == "BULL" else (a["h"][j] - bot)
                fill = max(fill, min(1.0, max(0.0, pen / size))) if size > EPS else 1.0
            out.append({"id": f"FVG-{tf}-{d}-{bars[i - 1]['open_utc']}", "tf": tf, "direction": d, "top": round(float(top), 5),
                        "bottom": round(float(bot), 5), "created_at": close_time(bars[i], tf), "i": i, "age_bars": len(bars) - 1 - i,
                        "fill_pct": round(fill * 100, 1)})
    return out


def ict_sequence(bars: list[dict], tf: str, displacement_atr: float = 1.2, lookback: int = 120) -> dict:
    """Most recent sweep -> MSS(+displacement) -> FVG -> retest chain; every FVG gets an id, age, fill and why it was
    (not) selected. Ranking fixed before testing: FVG inside the MSS displacement leg, unfilled (<100%), the newest."""
    a = arrays(bars)
    n = len(bars)
    if n < 40:
        return {"stage": "WARMING_UP", "definitions": DEFINITIONS}
    at = atr(a["h"], a["l"], a["c"])
    pv = [p for p in pivots(bars, tf) if p["confirmed_i"] >= n - lookback]
    best = None
    for p in pv:
        side = "BUY" if p["kind"] == "L" else "SELL"
        j0 = p["confirmed_i"] + 1
        sw = next((j for j in range(j0, n) if ((a["l"][j] < p["price"] < a["c"][j]) if side == "BUY" else (a["h"][j] > p["price"] > a["c"][j]))), None)
        if sw is None:
            continue
        opp = [q for q in pivots(bars[:sw + 1], tf) if q["kind"] == ("H" if side == "BUY" else "L")]
        if not opp:
            best = best or {"stage": "SWEEP", "side": side, "sweep_bar": sw, "pool": p}
            continue
        ref = opp[-1]
        mss = next((j for j in range(sw + 1, n) if (a["c"][j] > ref["price"] if side == "BUY" else a["c"][j] < ref["price"])), None)
        cand = {"stage": "SWEEP", "side": side, "sweep_bar": sw, "pool": p, "mss_ref": ref}
        if mss is not None:
            body = abs(a["c"][mss] - a["o"][mss])
            disp = (not np.isnan(at[mss])) and body >= displacement_atr * at[mss]
            cand.update(stage="MSS", mss_bar=mss, displacement=bool(disp), displacement_body_atr=round(float(body / at[mss]), 2) if not np.isnan(at[mss]) else None)
            gaps = [g for g in fvgs(bars, tf, start=sw) if g["i"] <= mss + 1]
            want = "BULL" if side == "BUY" else "BEAR"
            ranked = []
            for g in gaps:
                why = []
                if g["direction"] != want:
                    why.append("KIERUNEK_PRZECIWNY")
                if g["fill_pct"] >= 100:
                    why.append("WYPELNIONA")
                if not disp:
                    why.append("BRAK_DISPLACEMENTU")
                ranked.append({**g, "selected": False, "rejected_because": why})
            ok = [g for g in ranked if not g["rejected_because"]]
            if ok:
                sel = max(ok, key=lambda g: g["i"])
                sel["selected"] = True
                cand.update(stage="FVG", fvg=sel)
                rt = next((j for j in range(sel["i"] + 1, n) if a["l"][j] <= sel["top"] and a["h"][j] >= sel["bottom"]), None)
                if rt is not None:
                    cand.update(stage="RETEST", retest_bar=rt, retest_at=close_time(bars[rt], tf))
            cand["fvg_candidates"] = ranked[-8:]
        if best is None or cand.get("sweep_bar", -1) >= best.get("sweep_bar", -1):
            best = cand
    if best is None:
        return {"stage": "NONE", "definitions": DEFINITIONS, "ranking_rule": "FVG w odcinku displacementu MSS, niewypełniona, najnowsza"}
    for k in ("sweep_bar", "mss_bar", "retest_bar"):
        if k in best:
            best[k.replace("_bar", "_at")] = close_time(bars[best[k]], tf)
    best["pool"] = {k: best["pool"][k] for k in ("kind", "price", "origin_time", "confirmed_at")}
    if "mss_ref" in best:
        best["mss_ref"] = {k: best["mss_ref"][k] for k in ("kind", "price", "origin_time", "confirmed_at")}
    best["definitions"] = DEFINITIONS
    best["ranking_rule"] = "FVG w odcinku displacementu MSS, niewypełniona, najnowsza (ustalone przed testem)"
    return best


# ----------------------------------------------------------------------------- M22 SMMA channel
def smma(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    out[n - 1] = x[:n].mean()
    for i in range(n, len(x)):
        out[i] = (out[i - 1] * (n - 1) + x[i]) / n
    return out


def smma_channel(bars: list[dict], n: int = 3, shift: int = 0) -> dict:
    a = arrays(bars)
    hi, lo = smma(a["h"], n), smma(a["l"], n)
    if shift:
        hi = np.concatenate([np.full(shift, np.nan), hi[:-shift]])
        lo = np.concatenate([np.full(shift, np.nan), lo[:-shift]])
    if len(a["c"]) < n + shift + 2 or np.isnan(hi[-1]):
        return {"state": "WARMING_UP", "params": {"period": n, "shift": shift, "type": "SMMA (Wilder)"}}
    c = a["c"]
    ev = "INSIDE"
    if c[-1] > hi[-1] and c[-2] <= hi[-2]:
        ev = "CLOSE_CROSSED_ABOVE_HIGH"
    elif c[-1] < lo[-1] and c[-2] >= lo[-2]:
        ev = "CLOSE_CROSSED_BELOW_LOW"
    elif c[-1] > hi[-1]:
        ev = "ABOVE_HIGH"
    elif c[-1] < lo[-1]:
        ev = "BELOW_LOW"
    return {"state": ev, "smma_high": round(float(hi[-1]), 5), "smma_low": round(float(lo[-1]), 5), "warmup_bars": n + shift,
            "params": {"period": n, "shift": shift, "type": "SMMA (Wilder)", "price": "high / low", "evaluated_on": "zamknięte świece"}}


# ----------------------------------------------------------------------------- M23 Z-Score
ZSCORE_HYPOTHESES = {
    "version": "ZH-1.0.0",
    "note": "progi z materiałów to punkty startowe badania, NIE parametry potwierdzone dla XAUUSD/BTC; skrajny Z nie oznacza pewnego odwrócenia",
    "H_MR": {"name": "mean reversion", "extreme": 2.0, "rule": "powrót do wnętrza ±2 po zamknięciu poza ±2"},
    "H_BO": {"name": "breakout", "entry": 2.5, "exit_inside": 1.0, "rule": "zamknięcie poza ±2,5; wyjście po powrocie do ±1"},
    "H_TP": {"name": "trend pullback", "ema": 200, "band": 1.5, "rule": "trend wg EMA200, Z przecina ±1,5 w stronę trendu"},
}


def zscore(bars: list[dict], n: int = 20, min_rel_std: float = 1e-5) -> dict:
    a = arrays(bars)
    c = a["c"]
    if len(c) < max(n + 2, 30):
        return {"status": "warming_up", "hypotheses": ZSCORE_HYPOTHESES}
    m, s = sma(c, n), rolling_std(c, n)
    guard = s < min_rel_std * np.abs(c)
    z = np.where(guard | np.isnan(s), np.nan, (c - m) / np.where(s > 0, s, np.nan))
    if np.isnan(z[-1]) or np.isnan(z[-2]):
        return {"status": "low_dispersion", "z": None, "flag": "STD_BELOW_GUARD", "hypotheses": ZSCORE_HYPOTHESES}
    e200 = ema(c, 200)
    trend = None if np.isnan(e200[-1]) else ("UP" if c[-1] > e200[-1] else "DOWN")
    H = ZSCORE_HYPOTHESES
    st = {
        "H_MR": "LONG_CANDIDATE" if z[-2] < -H["H_MR"]["extreme"] <= z[-1] else "SHORT_CANDIDATE" if z[-2] > H["H_MR"]["extreme"] >= z[-1] else "NONE",
        "H_BO": "LONG_CANDIDATE" if z[-1] > H["H_BO"]["entry"] else "SHORT_CANDIDATE" if z[-1] < -H["H_BO"]["entry"] else
                ("EXIT_ZONE" if abs(z[-1]) < H["H_BO"]["exit_inside"] else "NONE"),
        "H_TP": "NO_TREND_WARMUP" if trend is None else
                ("LONG_CANDIDATE" if trend == "UP" and z[-2] < -H["H_TP"]["band"] <= z[-1] else
                 "SHORT_CANDIDATE" if trend == "DOWN" and z[-2] > H["H_TP"]["band"] >= z[-1] else "NONE"),
    }
    return {"status": "ready", "z": round(float(z[-1]), 3), "z_prev": round(float(z[-2]), 3), "window": n, "trend_ema200": trend,
            "hypotheses_state": st, "hypotheses": ZSCORE_HYPOTHESES, "series": [None if np.isnan(v) else round(float(v), 3) for v in z[-120:]]}


# ----------------------------------------------------------------------------- M24 PSAR (shared implementation)
def psar(bars: list[dict], step: float = 0.02, maximum: float = 0.2) -> dict:
    """Shared SAR core (scalp.indicators, profile MQ_SAR_WILDER_PROFILE_V1) - same values as scalp/chart/composer."""
    from ..scalp.indicators import SAR_PROFILE, atr, sar_diagnostics, sar_points
    a = arrays(bars)
    h, lo, c = list(a["h"]), list(a["l"]), list(a["c"])
    if len(h) < 2:
        return {"implementation": "scalp.indicators (wspólna)", "profile": SAR_PROFILE, "params": {"step": step, "max": maximum},
                "status": "WARMING_UP", "last": None, "series": []}
    pts = sar_points(h, lo, step, maximum)
    at = atr(h, lo, c)
    diag = sar_diagnostics(h, lo, c, at[-1], step, maximum)
    times = [b.get("open_utc") for b in bars]
    return {"implementation": "scalp.indicators (wspólna)", "profile": SAR_PROFILE, "params": {"step": step, "max": maximum},
            "last": pts[-1] and {k: pts[-1][k] for k in ("sar", "trend", "flip")}, "diagnostics": diag, "mt5_parity": "MT5_PARITY_NOT_RUN",
            "series": [x and {"t": times[i], "sar": round(x["sar"], 5), "trend": x["trend"], "flip": x["flip"]} for i, x in enumerate(pts)][-120:]}


# ----------------------------------------------------------------------------- M25 Stochastic daily breakout
def stochastic(a: dict, k: int = 14, d: int = 3) -> tuple[np.ndarray, np.ndarray]:
    n = len(a["c"])
    kk = np.full(n, np.nan)
    for i in range(k - 1, n):
        hh, ll = a["h"][i - k + 1:i + 1].max(), a["l"][i - k + 1:i + 1].min()
        kk[i] = 100 * (a["c"][i] - ll) / (hh - ll) if hh - ll > EPS else 50.0
    dd = np.full(n, np.nan)
    for i in range(k + d - 2, n):
        dd[i] = kk[i - d + 1:i + 1].mean()
    return kk, dd


def stoch_daily_breakout(bars: list[dict], tf: str, d1: list[dict] | None, asset: str, k: int = 14, d: int = 3) -> dict:
    a = arrays(bars)
    if len(bars) < k + d + 2:
        return {"state": "WARMING_UP"}
    kk, dd = stochastic(a, k, d)
    lv = previous_day_levels(d1, a["t"][-1] + TF_SEC[tf])
    hyp = "SDB-XAU-1.0.0 (kandydat replikowalny z opisu)" if asset == "XAUUSD" else \
          "SDB-BTC-H1 (osobna hipoteza dla BTC – nie przeniesione wyniki autora)"
    if lv is None:
        return {"state": "NO_PREVIOUS_DAY", "hypothesis": hyp}
    up = kk[-2] < dd[-2] and kk[-1] > dd[-1]
    dn = kk[-2] > dd[-2] and kk[-1] < dd[-1]
    st = "NONE"
    if a["c"][-1] > lv["pdh"] and up:
        st = "LONG_CANDIDATE"
    elif a["c"][-1] < lv["pdl"] and dn:
        st = "SHORT_CANDIDATE"
    return {"state": st, "k": round(float(kk[-1]), 1), "d": round(float(dd[-1]), 1), "pdh": lv["pdh"], "pdl": lv["pdl"],
            "levels_available_at": lv["available_at"], "hypothesis": hyp, "validated": False}


# ----------------------------------------------------------------------------- M27 quiet drift
def quiet_drift(bars: list[dict], window: int = 200, quiet_pct: float = 0.30, ema_n: int = 50) -> dict:
    """Hypothesis kept from the JPN225 material: low activity + momentum not overextended + slow drift. No hours or
    parameters transferred; quantiles computed on the past window only."""
    a = arrays(bars)
    if len(bars) < max(window, ema_n) + 5:
        return {"state": "WARMING_UP"}
    rng = a["h"] - a["l"]
    tvq = pct_rank(a["tv"][-window:], a["tv"][-1])
    rq = pct_rank(rng[-window:], rng[-1])
    e = ema(a["c"], ema_n)
    slope = (e[-1] - e[-6]) / 5
    zz = zscore(bars)
    over = zz.get("z") is not None and abs(zz["z"]) >= 1.0
    quiet = tvq is not None and rq is not None and tvq < quiet_pct and rq < quiet_pct
    st = "QUIET_DRIFT_" + ("UP" if slope > 0 else "DOWN") if quiet and not over else ("QUIET_BUT_STRETCHED" if quiet else "ACTIVE")
    return {"state": st, "tick_volume_pct": tvq, "range_pct": rq, "ema_slope_per_bar": float(slope), "z": zz.get("z"),
            "note": "tick volume = aktywność feedu brokera, nie wolumen rynku"}
