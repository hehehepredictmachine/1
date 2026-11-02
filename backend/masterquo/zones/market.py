"""Market Zones Engine - PMW-MZ-1: zones of one instrument on M1 / M5 / M15 / M30 for the "Strefy rynkowe" panel.

Pure functions of CLOSED bars as known at `as_of` (zones/series.Series drops a forming bar and every bar whose close is after
as_of), so the same call reproduces the historical state ("as of") and the live state. Analytical only: no order path, no
settings, no terminal trading calls.

Detection rules (every zone carries `detectable_from` = close of the candle at which the rule could first be evaluated):
* SR_SUPPORT / SR_RESISTANCE - confirmed swing low / high (strategies.indicators.pivots: `left` bars >=, `right` bars strictly;
  known only after the `right` confirming candles CLOSE) with prominence >= prom_atr x ATR14. Zone = wick to body, capped at
  0.25 x ATR. A swing whose right side is not complete yet is PRELIMINARY (wstępna) and may disappear.
* DEMAND / SUPPLY - base candle (range <= 1.0 x ATR) followed within <= 3 candles by a displacement: close beyond the base
  extreme by >= 1.5 x ATR with a displacement candle body >= 60 % of its range. Zone = base low .. base body top (demand),
  base body bottom .. base high (supply). Known at the close of the displacement candle.
* FVG_BULL / FVG_BEAR - three-candle gap: low[i] > high[i-2] (bull) / high[i] < low[i-2] (bear), gap >= max(0.3 x ATR,
  min width). Known at the close of candle i.
* OB_BULL / OB_BEAR (explicit confirmation rule) - a close beyond the latest swing high (low) that was already CONFIRMED before
  that candle = break of structure (BOS). The order block is the last opposite-colour candle between that swing and the BOS
  candle; zone = its full range (capped at max_width_atr x ATR). Known only at the close of the BOS candle; without a BOS
  there is no order block.
* EQH / EQL - two or more confirmed swing highs (lows) within eq_tol_atr x ATR of each other, >= 3 bars apart, with no close
  beyond the level between them. Shown as POTENTIAL LIQUIDITY INFERRED FROM OHLC - never as measured liquidity or as resting
  orders (OHLC carries no order-book information). Known when the last pivot of the cluster is confirmed.

Lifecycle (only candles after detectable_from):
  PRELIMINARY (wstępna) -> ACTIVE (aktywna) -> TESTED (testowana) -> INVALIDATED (unieważniona) | EXPIRED (wygasła)
* test = a candle whose range reaches the zone (+- touch_tol_atr x ATR) after price stayed outside it for >= test_gap candles;
  touches without leaving the zone in between are ONE test (independent tests only);
* invalidation = a CLOSE beyond the far boundary by break_atr x ATR (a wick alone never invalidates S/R, S/D, FVG, OB);
  EQH / EQL are invalidated by a wick beyond the level (the inferred liquidity area was traded through);
* expiry = more than max_age candles since detection.

Quality score 0-100 = structure 30 (size in ATR / type norm) + reaction 25 (move away within 12 candles / 6 ATR) + freshness 15 +
tests 10 (0 tests 10, 1: 8, 2: 5, more: 2) + confluence 15 (other TFs / 3) + width 5 (components returned).
It ranks zones; it is NOT a probability and it is not calibrated (`probability` stays None).

Merging: only zones of the same type on the same timeframe that overlap >= 50 % of the narrower one and are both live; the
merged zone keeps the id and detectable_from of its oldest member, lists every member (provenance) and widens its bounds only from
the moment each next member became detectable (`segments`, `bounds_known_from`) - its tests are counted with the bounds known then. Different timeframes are never merged - they produce confluence (price ranges that overlap + compatible direction, using
only zones known at as_of).
Parameters scale with ATR14 of each timeframe and with the instrument profile (min width from tick, price and recorded spread).
"""
from __future__ import annotations

import copy
import hashlib
import statistics

from ..strategies import indicators as ind
from .series import Series, iso

VERSION = "PMW-MZ-1"
TFS = ("M1", "M5", "M15", "M30")
STATE_PL = {"PRELIMINARY": "wstępna", "ACTIVE": "aktywna", "TESTED": "testowana", "INVALIDATED": "unieważniona", "EXPIRED": "wygasła"}
LIVE = ("PRELIMINARY", "ACTIVE", "TESTED")
TYPES = {  # type: (label PL, direction, side tested from)  side BELOW = support-like (price above it), ABOVE = resistance-like
    "SR_SUPPORT": ("wsparcie (swing low)", "BULLISH", "BELOW"),
    "SR_RESISTANCE": ("opór (swing high)", "BEARISH", "ABOVE"),
    "DEMAND": ("popyt (baza + impuls w górę)", "BULLISH", "BELOW"),
    "SUPPLY": ("podaż (baza + impuls w dół)", "BEARISH", "ABOVE"),
    "FVG_BULL": ("luka FVG wzrostowa", "BULLISH", "BELOW"),
    "FVG_BEAR": ("luka FVG spadkowa", "BEARISH", "ABOVE"),
    "OB_BULL": ("order block wzrostowy (po BOS)", "BULLISH", "BELOW"),
    "OB_BEAR": ("order block spadkowy (po BOS)", "BEARISH", "ABOVE"),
    "EQH": ("równe szczyty – potencjalna płynność wnioskowana z OHLC", "NEUTRAL", "ABOVE"),
    "EQL": ("równe dołki – potencjalna płynność wnioskowana z OHLC", "NEUTRAL", "BELOW"),
}
TF_PARAMS = {
    "M1": {"left": 3, "right": 3, "prom_atr": 0.8, "max_age": 720, "test_gap": 3, "bars": 1500},
    "M5": {"left": 3, "right": 3, "prom_atr": 0.6, "max_age": 576, "test_gap": 3, "bars": 1000},
    "M15": {"left": 3, "right": 2, "prom_atr": 0.5, "max_age": 480, "test_gap": 2, "bars": 700},
    "M30": {"left": 2, "right": 2, "prom_atr": 0.5, "max_age": 480, "test_gap": 2, "bars": 500},
}
# Instrument profiles: gold and BTC differ in tick, price level, noise and spread - widths / tolerances are not shared constants.
PROFILES = {
    "XAUUSD": {"min_width_bp": 0.3, "min_width_ticks": 10, "eq_tol_atr": 0.12, "touch_tol_atr": 0.05, "break_atr": 0.15, "spread_mult": 2.0},
    "BTC": {"min_width_bp": 0.8, "min_width_ticks": 100, "eq_tol_atr": 0.18, "touch_tol_atr": 0.08, "break_atr": 0.25, "spread_mult": 2.0},
}
COMMON = {"half_width_atr": 0.25, "max_width_atr": 1.5, "base_max_atr": 1.0, "disp_atr": 1.5, "disp_bars": 3, "disp_body": 0.6,
          "fvg_min_atr": 0.3, "eq_min_gap": 3, "eq_max_span": 120, "reaction_bars": 12, "visible_per_tf": 8, "history_per_tf": 40,
          "confluence_tol_atr": 0.0}
RULES = {
    "detection": {k: v for k, v in {
        "SR": "potwierdzony swing (pivot left/right) o wielkości >= prom_atr x ATR14; znany po zamknięciu `right` świec potwierdzenia",
        "DEMAND_SUPPLY": "świeca bazowa (zakres <= 1,0 ATR) + w <= 3 świecach zamknięcie dalej niż ekstremum bazy o >= 1,5 ATR (korpus >= 60 % zakresu)",
        "FVG": "luka trzech świec: low[i] > high[i-2] lub high[i] < low[i-2], >= max(0,3 ATR, min. szerokość); znana po zamknięciu świecy i",
        "ORDER_BLOCK": "zamknięcie za ostatnim POTWIERDZONYM swingiem = BOS; OB = ostatnia świeca przeciwnego koloru między swingiem a świecą BOS; znany po zamknięciu świecy BOS",
        "EQH_EQL": "co najmniej dwa potwierdzone swingi w odległości <= eq_tol_atr x ATR, >= 3 świece od siebie, bez zamknięcia za poziomem pomiędzy",
    }.items()},
    "confirmation": "strefa jest wstępna, dopóki jej świece potwierdzenia nie zamkną się; wynik ze świecy formującej się jest zawsze wstępny",
    "test": "świeca sięga strefy (+- touch_tol_atr x ATR) po >= test_gap świecach poza strefą; dotknięcia bez wyjścia ze strefy = jeden test",
    "invalidation": "zamknięcie za dalszą granicą o >= break_atr x ATR (knot nie unieważnia); EQH/EQL: knot za poziomem (obszar przehandlowany)",
    "expiry": "więcej niż max_age świec od wykrycia",
    "liquidity_note": "EQH/EQL to obszary wnioskowane z OHLC – nie są zmierzoną płynnością ani zleceniami oczekującymi",
    "score_note": "jakość 0–100 porządkuje strefy; nie jest prawdopodobieństwem i nie jest skalibrowana",
}


def params_for(instrument: str) -> dict:
    return {"version": VERSION, "tf": TF_PARAMS, "instrument": PROFILES.get(instrument, PROFILES["XAUUSD"]), "common": COMMON}


def _id(*parts) -> str:
    return "MZ-" + hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:14]


def _rnd(x: float, tick: float) -> float:
    return round(round(x / tick) * tick, 10) if tick > 0 else x


def _atr_at(a: list, i: int) -> float | None:
    for k in range(min(i, len(a) - 1), -1, -1):
        if a[k]:
            return a[k]
    return None


def min_width(instrument: str, tick: float, price: float, spread_price: float | None) -> float:
    p = PROFILES.get(instrument, PROFILES["XAUUSD"])
    return max(p["min_width_ticks"] * tick, p["min_width_bp"] * price / 1e4, p["spread_mult"] * (spread_price or 0.0))


# ------------------------------------------------------------------------------------------------ detection
def _zone(inst, tf, ztype, s: Series, origin: int, detect: int, lower: float, upper: float, atr: float, reason: str, struct: float,
          prelim: bool = False, extra: dict | None = None) -> dict:
    label, direction, side = TYPES[ztype]
    return {"id": _id(inst, tf, ztype, s.t[origin]), "instrument": inst, "timeframe": tf, "type": ztype,
            "type_pl": label, "direction": direction, "side": side, "lower": lower, "upper": upper, "origin_index": origin,
            "detect_index": detect, "origin_time": iso(s.t[origin]), "detectable_from": iso(s.close_time(detect)),
            "atr": atr, "reason": reason, "structure_atr": round(struct, 3), "preliminary": prelim, "members": [], **(extra or {})}


def _widen(lo: float, up: float, minw: float, side: str) -> tuple[float, float]:
    if up - lo >= minw:
        return lo, up
    return (lo, lo + minw) if side == "BELOW" else (up - minw, up)


def detect(s: Series, inst: str, tick: float, minw: float) -> list[dict]:
    tf = s.tf
    tp, prof, cm = TF_PARAMS[tf], PROFILES.get(inst, PROFILES["XAUUSD"]), COMMON
    n = len(s)
    a = ind.atr(s.h, s.l, s.c, 14)
    out: list[dict] = []
    if n < 30:
        return out
    left, right = tp["left"], tp["right"]
    piv = ind.pivots(s.h, s.l, left, right)
    sig = []                                                   # significant confirmed pivots (also used by OB / EQH)
    for p in piv:
        i = p["index"]
        at = _atr_at(a, i)
        if not at:
            continue
        lo_w, hi_w = i - left, min(n, i + right + 1)
        prom = (s.h[i] - min(s.l[lo_w:hi_w])) if p["kind"] == "H" else (max(s.h[lo_w:hi_w]) - s.l[i])
        sig.append({**p, "atr": at, "prom": prom / at})
        if prom < tp["prom_atr"] * at:
            continue
        if p["kind"] == "H":
            up = s.h[i]
            lo = max(max(s.o[i], s.c[i]), up - cm["half_width_atr"] * at)
            lo, up = _widen(lo, up, minw, "ABOVE")
            out.append(_zone(inst, tf, "SR_RESISTANCE", s, i, p["confirmed_index"], _rnd(lo, tick), _rnd(up, tick), at,
                             f"swing high {s.h[i]:.{_dg(tick)}f} potwierdzony {right} świecami; wielkość {prom / at:.2f} ATR", prom / at))
        else:
            lo = s.l[i]
            up = min(min(s.o[i], s.c[i]), lo + cm["half_width_atr"] * at)
            lo, up = _widen(lo, up, minw, "BELOW")
            out.append(_zone(inst, tf, "SR_SUPPORT", s, i, p["confirmed_index"], _rnd(lo, tick), _rnd(up, tick), at,
                             f"swing low {s.l[i]:.{_dg(tick)}f} potwierdzony {right} świecami; wielkość {prom / at:.2f} ATR", prom / at))
    # provisional swings: at least one confirming candle closed but not all yet -> PRELIMINARY (can disappear with the next candles);
    # strict on both sides, so a flat market does not produce a candidate on every candle
    for i in range(max(left, n - right), n - 1):
        at = _atr_at(a, i)
        if not at:
            continue
        rs = range(i + 1, n)
        if all(s.h[i] > s.h[i - k] for k in range(1, left + 1)) and all(s.h[i] > s.h[j] for j in rs):
            prom = s.h[i] - min(s.l[i - left:n])
            if prom >= tp["prom_atr"] * at:
                lo, up = _widen(max(max(s.o[i], s.c[i]), s.h[i] - cm["half_width_atr"] * at), s.h[i], minw, "ABOVE")
                out.append(_zone(inst, tf, "SR_RESISTANCE", s, i, n - 1, _rnd(lo, tick), _rnd(up, tick), at,
                                 f"kandydat na swing high – brakuje {right - (n - 1 - i)} świec potwierdzenia", prom / at, prelim=True))
        if all(s.l[i] < s.l[i - k] for k in range(1, left + 1)) and all(s.l[i] < s.l[j] for j in rs):
            prom = max(s.h[i - left:n]) - s.l[i]
            if prom >= tp["prom_atr"] * at:
                lo, up = _widen(s.l[i], min(min(s.o[i], s.c[i]), s.l[i] + cm["half_width_atr"] * at), minw, "BELOW")
                out.append(_zone(inst, tf, "SR_SUPPORT", s, i, n - 1, _rnd(lo, tick), _rnd(up, tick), at,
                                 f"kandydat na swing low – brakuje {right - (n - 1 - i)} świec potwierdzenia", prom / at, prelim=True))
    # supply / demand: base + displacement
    for j in range(15, n - 1):
        at = _atr_at(a, j)
        if not at or s.h[j] - s.l[j] > cm["base_max_atr"] * at:
            continue
        for k in range(1, cm["disp_bars"] + 1):
            d = j + k
            if d >= n:
                break
            rng = s.h[d] - s.l[d]
            body = abs(s.c[d] - s.o[d])
            if rng <= 0 or body < cm["disp_body"] * rng:
                continue
            if s.c[d] - s.h[j] >= cm["disp_atr"] * at and s.c[d] > s.o[d]:
                lo, up = _widen(s.l[j], max(s.o[j], s.c[j]), minw, "BELOW")
                out.append(_zone(inst, tf, "DEMAND", s, j, d, _rnd(lo, tick), _rnd(up, tick), at,
                                 f"baza {iso(s.t[j])} + impuls w górę {(s.c[d] - s.h[j]) / at:.2f} ATR w {k} świec(ach)", (s.c[d] - s.h[j]) / at))
                break
            if s.l[j] - s.c[d] >= cm["disp_atr"] * at and s.c[d] < s.o[d]:
                lo, up = _widen(min(s.o[j], s.c[j]), s.h[j], minw, "ABOVE")
                out.append(_zone(inst, tf, "SUPPLY", s, j, d, _rnd(lo, tick), _rnd(up, tick), at,
                                 f"baza {iso(s.t[j])} + impuls w dół {(s.l[j] - s.c[d]) / at:.2f} ATR w {k} świec(ach)", (s.l[j] - s.c[d]) / at))
                break
    # fair value gaps
    for i in range(16, n):
        at = _atr_at(a, i)
        if not at:
            continue
        thr = max(cm["fvg_min_atr"] * at, minw)
        if s.l[i] - s.h[i - 2] >= thr:
            out.append(_zone(inst, tf, "FVG_BULL", s, i - 1, i, _rnd(s.h[i - 2], tick), _rnd(s.l[i], tick), at,
                             f"luka {(s.l[i] - s.h[i - 2]) / at:.2f} ATR między high świecy {iso(s.t[i - 2])} a low świecy {iso(s.t[i])}",
                             (s.l[i] - s.h[i - 2]) / at))
        if s.l[i - 2] - s.h[i] >= thr:
            out.append(_zone(inst, tf, "FVG_BEAR", s, i - 1, i, _rnd(s.h[i], tick), _rnd(s.l[i - 2], tick), at,
                             f"luka {(s.l[i - 2] - s.h[i]) / at:.2f} ATR między low świecy {iso(s.t[i - 2])} a high świecy {iso(s.t[i])}",
                             (s.l[i - 2] - s.h[i]) / at))
    # order blocks: BOS over a swing CONFIRMED before the breaking candle
    highs = sorted((p for p in sig if p["kind"] == "H" and p["prom"] >= tp["prom_atr"]), key=lambda p: p["confirmed_index"])
    lows = sorted((p for p in sig if p["kind"] == "L" and p["prom"] >= tp["prom_atr"]), key=lambda p: p["confirmed_index"])
    used_h, used_l = set(), set()
    for i in range(16, n):
        at = _atr_at(a, i)
        if not at:
            continue
        lh = next((p for p in reversed(highs) if p["confirmed_index"] < i), None)
        if lh and lh["index"] not in used_h and s.c[i] > lh["price"] and s.c[i - 1] <= lh["price"]:
            used_h.add(lh["index"])
            j = next((k for k in range(i - 1, lh["index"] - 1, -1) if s.c[k] < s.o[k]), None)
            if j is not None:
                lo, up = s.l[j], s.h[j]
                if up - lo > cm["max_width_atr"] * at:
                    lo = up - cm["max_width_atr"] * at
                lo, up = _widen(lo, up, minw, "BELOW")
                imp = (s.c[i] - s.l[j]) / at
                out.append(_zone(inst, tf, "OB_BULL", s, j, i, _rnd(lo, tick), _rnd(up, tick), at,
                                 f"ostatnia świeca spadkowa przed BOS: zamknięcie {iso(s.t[i])} nad swing high {lh['price']:.{_dg(tick)}f} "
                                 f"(potwierdzony {iso(s.close_time(lh['confirmed_index']))})", imp, extra={"bos_time": iso(s.close_time(i))}))
        ll = next((p for p in reversed(lows) if p["confirmed_index"] < i), None)
        if ll and ll["index"] not in used_l and s.c[i] < ll["price"] and s.c[i - 1] >= ll["price"]:
            used_l.add(ll["index"])
            j = next((k for k in range(i - 1, ll["index"] - 1, -1) if s.c[k] > s.o[k]), None)
            if j is not None:
                lo, up = s.l[j], s.h[j]
                if up - lo > cm["max_width_atr"] * at:
                    up = lo + cm["max_width_atr"] * at
                lo, up = _widen(lo, up, minw, "ABOVE")
                imp = (s.h[j] - s.c[i]) / at
                out.append(_zone(inst, tf, "OB_BEAR", s, j, i, _rnd(lo, tick), _rnd(up, tick), at,
                                 f"ostatnia świeca wzrostowa przed BOS: zamknięcie {iso(s.t[i])} pod swing low {ll['price']:.{_dg(tick)}f} "
                                 f"(potwierdzony {iso(s.close_time(ll['confirmed_index']))})", imp, extra={"bos_time": iso(s.close_time(i))}))
    # equal highs / lows (inferred liquidity areas)
    for kind, ztype, side in (("H", "EQH", "ABOVE"), ("L", "EQL", "BELOW")):
        pts = sorted((p for p in sig if p["kind"] == kind and p["prom"] >= 0.3), key=lambda p: p["index"])
        in_cluster: set[int] = set()
        for x in range(len(pts)):
            if pts[x]["index"] in in_cluster:
                continue
            cl = [pts[x]]
            for y in range(x + 1, len(pts)):
                q = pts[y]
                if q["index"] - cl[-1]["index"] < cm["eq_min_gap"]:
                    continue
                if q["index"] - cl[0]["index"] > cm["eq_max_span"]:
                    break
                at = cl[0]["atr"]
                if abs(q["price"] - cl[0]["price"]) <= prof["eq_tol_atr"] * at:
                    lvl = max(p["price"] for p in cl + [q]) if kind == "H" else min(p["price"] for p in cl + [q])
                    between = s.c[cl[0]["index"] + 1:q["index"]]
                    if (kind == "H" and between and max(between) > lvl) or (kind == "L" and between and min(between) < lvl):
                        break
                    cl.append(q)
            if len(cl) >= 2:
                in_cluster.update(p["index"] for p in cl)
                prices = [p["price"] for p in cl]
                lo, up = _widen(min(prices), max(prices), minw, side)
                last = max(cl, key=lambda p: p["confirmed_index"])
                out.append(_zone(inst, tf, ztype, s, cl[0]["index"], last["confirmed_index"], _rnd(lo, tick), _rnd(up, tick), cl[0]["atr"],
                                 f"{len(cl)} swingi {'high' if kind == 'H' else 'low'} w odległości <= {prof['eq_tol_atr']} ATR – potencjalna "
                                 "płynność wnioskowana z OHLC (nie zmierzona, nie zlecenia oczekujące)", float(len(cl) - 1),
                                 extra={"pivot_times": [iso(s.t[p["index"]]) for p in cl]}))
    # one zone per (type, origin): repeated clusters of the same first pivot -> keep the largest
    best: dict[str, dict] = {}
    for z in out:
        k = z["id"]
        if k not in best or z["structure_atr"] > best[k]["structure_atr"]:
            best[k] = z
    return sorted(best.values(), key=lambda z: (z["detect_index"], z["type"]))


def _dg(tick: float) -> int:
    s = f"{tick:.10f}".rstrip("0")
    return max(0, len(s.split(".")[1]) if "." in s else 0)


# ------------------------------------------------------------------------------------------------ lifecycle
def lifecycle(z: dict, s: Series, a: list, inst: str) -> dict:
    """State of one zone from the candles after it became known. A merged zone is evaluated piecewise (`segments`): with the bounds
    known at each moment - the union grows only when the next member becomes detectable (no look-ahead in the test count)."""
    prof, tp, cm = PROFILES.get(inst, PROFILES["XAUUSD"]), TF_PARAMS[s.tf], COMMON
    side, d = z["side"], z["detect_index"]
    segs = z.get("segments") or [(d, z["lower"], z["upper"])]
    state = "PRELIMINARY" if z["preliminary"] else "ACTIVE"
    events = [{"at": z["detectable_from"], "event": "WYKRYTA" if not z["preliminary"] else "WSTĘPNA"}]
    for k, lo_k, up_k in segs[1:]:
        events.append({"at": iso(s.close_time(k)), "event": "POSZERZONA (połączenie)", "lower": lo_k, "upper": up_k})
    tests, test_times, outside, reaction = 0, [], 0, 0.0
    inval_at = exp_at = None
    n = len(s)
    lo, up = segs[0][1], segs[0][2]
    si = 1
    for j in range(d + 1, n):
        while si < len(segs) and segs[si][0] < j:                        # bounds known before candle j
            lo, up = segs[si][1], segs[si][2]
            si += 1
        at = _atr_at(a, j) or z["atr"]
        tol, brk = prof["touch_tol_atr"] * at, prof["break_atr"] * at
        if z["type"] in ("EQH", "EQL"):
            broken = s.h[j] > up if side == "ABOVE" else s.l[j] < lo
        else:
            broken = s.c[j] < lo - brk if side == "BELOW" else s.c[j] > up + brk
        if broken:
            state, inval_at = "INVALIDATED", iso(s.close_time(j))
            events.append({"at": inval_at, "event": "UNIEWAŻNIONA", "close": s.c[j]})
            break
        if j - d > tp["max_age"]:
            state, exp_at = "EXPIRED", iso(s.close_time(j))
            events.append({"at": exp_at, "event": "WYGASŁA"})
            break
        touched = s.h[j] >= lo - tol and s.l[j] <= up + tol
        if touched:
            if outside >= tp["test_gap"]:
                tests += 1
                test_times.append(iso(s.close_time(j)))
                events.append({"at": iso(s.close_time(j)), "event": f"TEST {tests}"})
                if state == "ACTIVE":
                    state = "TESTED"
            outside = 0
        else:
            outside += 1
        if j - d <= cm["reaction_bars"]:
            away = (s.h[j] - up) if side == "BELOW" else (lo - s.l[j])
            reaction = max(reaction, away / at if at else 0.0)
    events.sort(key=lambda e: e["at"])
    inval_level = z["lower"] if side == "BELOW" else z["upper"]
    z.update(state=state, state_pl=STATE_PL[state], tests=tests, test_times=test_times, invalidated_at=inval_at, expired_at=exp_at,
             events=events, reaction_atr=round(reaction, 3), age_bars=max(0, n - 1 - d),
             invalidation_rule=(("knot " + ("powyżej " if side == "ABOVE" else "poniżej ") + f"{inval_level}") if z["type"] in ("EQH", "EQL")
                                else ("zamknięcie " + ("poniżej " if side == "BELOW" else "powyżej ") +
                                      f"{inval_level} o >= {prof['break_atr']} ATR")),
             invalidation_level=inval_level)
    return z


def _overlap(a: dict, b: dict) -> float:
    inter = min(a["upper"], b["upper"]) - max(a["lower"], b["lower"])
    narrow = min(a["upper"] - a["lower"], b["upper"] - b["lower"]) or 1e-12
    return inter / narrow


def merge_same_type(zones: list[dict], s: Series, a: list, inst: str) -> list[dict]:
    """Controlled merge of live zones of the same type (same TF) overlapping >= 50 % of the narrower one; provenance kept.
    The merged zone keeps the oldest member's id and detectable_from; its bounds grow only from the moment the next member is known
    (segments), so the merged state never uses a boundary before it existed."""
    live = sorted([z for z in zones if z["state"] in LIVE], key=lambda z: (z["detect_index"], z["id"]))
    rest = [z for z in zones if z["state"] not in LIVE]
    merged: list[dict] = []
    for z in live:
        tgt = next((m for m in merged if m["type"] == z["type"] and m["preliminary"] == z["preliminary"] and _overlap(m, z) >= 0.5
                    and max(m["upper"], z["upper"]) - min(m["lower"], z["lower"]) <= COMMON["max_width_atr"] * max(m["atr"], z["atr"])), None)
        if tgt is None:
            merged.append(z)
            continue
        if not tgt["members"]:
            tgt["members"] = [_member(tgt)]
            tgt["segments"] = [(tgt["detect_index"], tgt["lower"], tgt["upper"])]
        tgt["members"].append(_member(z))
        tgt["lower"], tgt["upper"] = min(tgt["lower"], z["lower"]), max(tgt["upper"], z["upper"])
        tgt["segments"].append((z["detect_index"], tgt["lower"], tgt["upper"]))
        tgt["bounds_known_from"] = z["detectable_from"]
        tgt["structure_atr"] = max(tgt["structure_atr"], z["structure_atr"])
        tgt["reason"] = f"połączona z {len(tgt['members'])} stref tego samego typu (nakładanie >= 50 %): " + tgt["members"][0]["reason"]
    for m in merged:
        if m["members"]:
            lifecycle(m, s, a, inst)
            m["segments"] = [{"from": iso(s.close_time(k)), "lower": lo, "upper": up} for k, lo, up in m["segments"]]
    return merged + rest


def _member(z: dict) -> dict:
    return {k: z[k] for k in ("id", "lower", "upper", "origin_time", "detectable_from", "reason")}


# ------------------------------------------------------------------------------------------------ scoring, confluence
def confluence(by_tf: dict[str, list[dict]]) -> None:
    for tf, zs in by_tf.items():
        for z in zs:
            if z["state"] not in LIVE:
                z["confluence"] = {"timeframes": [], "zone_ids": [], "count": 0}
                continue
            tol = COMMON["confluence_tol_atr"] * z["atr"]
            hits = [(otf, o) for otf, ozs in by_tf.items() if otf != tf for o in ozs if o["state"] in LIVE
                    and o["lower"] <= z["upper"] + tol and o["upper"] >= z["lower"] - tol
                    and (o["direction"] == z["direction"] or "NEUTRAL" in (o["direction"], z["direction"]))]
            tfs = sorted({otf for otf, _ in hits}, key=TFS.index)
            z["confluence"] = {"timeframes": tfs, "zone_ids": [o["id"] for _, o in hits][:12], "count": len(tfs)}


def score(z: dict) -> None:
    tp = TF_PARAMS[z["timeframe"]]
    width_atr = (z["upper"] - z["lower"]) / z["atr"] if z["atr"] else 9.0
    norm = {"SR_SUPPORT": 6.0, "SR_RESISTANCE": 6.0, "DEMAND": 5.0, "SUPPLY": 5.0, "OB_BULL": 6.0, "OB_BEAR": 6.0,
            "FVG_BULL": 1.5, "FVG_BEAR": 1.5, "EQH": 3.0, "EQL": 3.0}[z["type"]]
    comp = {"struktura": round(30 * min(1.0, z["structure_atr"] / norm), 1),
            "reakcja": round(25 * min(1.0, z.get("reaction_atr", 0.0) / 6.0), 1),
            "świeżość": round(15 * max(0.0, 1 - z.get("age_bars", 0) / tp["max_age"]), 1),
            "testy": {0: 10.0, 1: 8.0, 2: 5.0}.get(z.get("tests", 0), 2.0),
            "konfluencja": round(15 * min(1.0, (z.get("confluence") or {}).get("count", 0) / 3), 1),
            "szerokość": 5.0 if width_atr <= 0.5 else 3.0 if width_atr <= 1.0 else 1.0}
    z["quality"] = {"score": round(min(100.0, sum(comp.values())), 1), "components": comp, "width_atr": round(width_atr, 3),
                    "note": "ocena jakości (heurystyka) – nie jest prawdopodobieństwem"}
    z["probability"] = None
    z["calibration"] = "BRAK – wynik jakości nie jest skalibrowanym prawdopodobieństwem"


# ------------------------------------------------------------------------------------------------ one timeframe / all
def compute_tf(s: Series, inst: str, tick: float, spread_price: float | None) -> dict:
    a = ind.atr(s.h, s.l, s.c, 14)
    if len(s) < 30:
        return {"tf": s.tf, "bars": len(s), "zones": [], "atr": None, "state": "NO_DATA" if not len(s) else "INSUFFICIENT",
                "last_closed": iso(s.close_time(len(s) - 1)) if len(s) else None}
    price = s.c[-1]
    minw = min_width(inst, tick, price, spread_price)
    zones = [lifecycle(z, s, a, inst) for z in detect(s, inst, tick, minw)]
    zones = merge_same_type(zones, s, a, inst)
    return {"tf": s.tf, "bars": len(s), "zones": zones, "atr": _atr_at(a, len(s) - 1), "min_width": minw, "price": price, "state": "OK",
            "first_open": iso(s.t[0]), "last_closed": iso(s.close_time(len(s) - 1))}


def compute(series: dict[str, Series], *, instrument: str, symbol: str, tick: float, as_of: float,
            spreads: dict[str, float | None] | None = None, visible_per_tf: int | None = None) -> dict:
    """series: {tf: Series cut at as_of}. Returns zones per TF (all + visible ids) with confluence computed across the requested TFs."""
    per = {tf: compute_tf(s, instrument, tick, (spreads or {}).get(tf)) for tf, s in series.items()}
    return finalize(per, instrument=instrument, symbol=symbol, as_of=as_of, visible_per_tf=visible_per_tf)


def finalize(per: dict[str, dict], *, instrument: str, symbol: str, as_of: float | str | None, visible_per_tf: int | None = None) -> dict:
    """Confluence, quality score, visible selection over per-TF results (raw results are not modified - live updates recompute
    one TF and finalize again with the cached results of the others, all of them computed from data known at their own as_of)."""
    per = copy.deepcopy(per)
    confluence({tf: r["zones"] for tf, r in per.items()})
    lim = visible_per_tf or COMMON["visible_per_tf"]
    for tf, r in per.items():
        for z in r["zones"]:
            score(z)
            z["algo_version"] = VERSION
            z["symbol"] = symbol
            for k in ("origin_index", "detect_index"):
                z.pop(k, None)
        price = r.get("price")
        live = [z for z in r["zones"] if z["state"] in LIVE]
        prio = {"TESTED": 0, "ACTIVE": 0, "PRELIMINARY": 1}
        live.sort(key=lambda z: (prio[z["state"]], -z["quality"]["score"], abs(((z["lower"] + z["upper"]) / 2) - (price or 0))))
        r["visible"] = [z["id"] for z in live[:lim]]
        dead = sorted([z for z in r["zones"] if z["state"] not in LIVE], key=lambda z: z.get("invalidated_at") or z.get("expired_at") or "")
        r["zones"] = live + dead[-COMMON["history_per_tf"]:]
        r["counts"] = {st: sum(1 for z in r["zones"] if z["state"] == st) for st in STATE_PL}
    return {"version": VERSION, "instrument": instrument, "symbol": symbol, "as_of": iso(as_of) if isinstance(as_of, (int, float)) else as_of,
            "timeframes": per, "params": params_for(instrument), "rules": RULES}


def spread_price(bars: list[dict], point: float) -> float | None:
    sp = [float(b.get("spread") or 0) for b in bars[-300:] if b.get("spread")]
    return statistics.median(sp) * point if sp and point else None


def state_as_of(z: dict, t_iso: str) -> str | None:
    """State of a stored zone at time t (ISO UTC) from its events; None = not known yet at t (no look-ahead)."""
    if z["detectable_from"] > t_iso:
        return None
    st = "PRELIMINARY" if z.get("preliminary") else "ACTIVE"
    for e in z.get("events") or []:
        if e["at"] > t_iso:
            break
        if e["event"].startswith("TEST") and st == "ACTIVE":
            st = "TESTED"
        elif e["event"] == "UNIEWAŻNIONA":
            st = "INVALIDATED"
        elif e["event"] == "WYGASŁA":
            st = "EXPIRED"
    return st
