"""Chart pattern engine (MQ-CHART-1.0.0) - OHLC + CONFIRMED pivots only (no screenshots).

Pivots: swing highs/lows with left = right = 3 bars (strategies.indicators.pivots); a pivot at bar p is KNOWN only after
bar p+3 has closed (`known_at`). A pattern is never dated before its last pivot became known: detected_at = known time of
the last anchor; a confirmation (breakout / neckline break) is a CLOSED bar after that.  States:
  FORMING      geometry complete with known pivots, no confirming close yet (a preview - never a trade by itself)
  CONFIRMED    a closed bar broke the boundary / neckline in the pattern's direction (available_at = that bar's close)
  INVALIDATED  after confirmation price closed back beyond the invalidation level, or before it beyond the pattern's extreme
  EXPIRED      no confirmation within `ttl_bars` after detection, or confirmation older than `ttl_bars`
Tolerances are in ATR14 of the TF.  Lines are least-squares fits through the pivots with a residual check (max residual
<= `max_resid_atr` x ATR) - two random points are not a pattern.  Limits: lookback `window` bars, at most `max_per_family`
candidates per family.

Definitions (direction_if_confirmed in brackets; mirrored patterns are listed together):
  RECTANGLE          >= 2 pivot highs and >= 2 pivot lows inside the window, highs within tol of their mean, lows within tol,
                     both fitted slopes |s| <= flat_slope, height >= 1.5 ATR, span >= 12 bars. [direction of the breakout close]
  BREAKOUT_RETEST    rectangle broken by a close beyond boundary + 0.1 ATR, later low/high returns to the boundary
                     (<= 0.3 ATR) and a close on the breakout side follows. [breakout side]
  FAILED_BREAKOUT    rectangle broken by a close, then a close back inside within 5 bars. [opposite of the breakout]
  DOUBLE_TOP/BOTTOM  2 highs (lows) within 0.5 ATR, >= 5 bars apart, a trough (peak) between them at least 1 ATR deep;
                     neckline = that trough; confirmation = close beyond the neckline. [SHORT / LONG]
  TRIPLE_TOP/BOTTOM  3 highs (lows) within 0.5 ATR, troughs between them; neckline = the lower (higher) trough. [SHORT / LONG]
  HEAD_SHOULDERS     highs LS < H > RS, head >= 0.5 ATR above both shoulders, shoulders within 1 ATR, troughs T1, T2 between;
  / INVERSE          neckline through T1-T2 (|slope| <= 0.1 ATR/bar); confirmation = close beyond the neckline. [SHORT / LONG]
  TRIANGLE_ASC/DESC/SYM  >= 2 highs and >= 2 lows, fitted lines converge (width at the end <= 0.75 x width at the start);
                     ascending: flat highs + rising lows; descending: falling highs + flat lows; symmetrical: falling highs +
                     rising lows. The NAME never sets the direction: it comes only from the confirmed breakout close.
  WEDGE_RISING/FALLING  both lines slope the same way and converge. [breakout side only]
  CHANNEL_ASC/DESC   both lines slope the same way, parallel (|slope difference| <= 0.02 ATR/bar). [breakout side only]
  FLAG / PENNANT     a pole: move >= 3 ATR within <= 10 bars, then a consolidation of 5..15 bars with height <= 0.5 x pole;
                     FLAG = parallel (or counter-sloped) box, PENNANT = converging. [pole direction, after the breakout close]
Targets are measured-move PROPOSALS, not promises. geometric_score (0..1) = quality of the fit, not a probability.
"""
from __future__ import annotations

import hashlib
from datetime import timedelta

from ..strategies import indicators as ind
from ..timeutil import TF_SECONDS, iso, parse_iso

VERSION = "MQ-CHART-1.0.0"
P = {"left": 3, "right": 3, "window": 150, "max_per_family": 2, "ttl_bars": 30, "max_resid_atr": 0.5, "flat_slope": 0.03,
     "eq_tol_atr": 0.5, "min_rect_bars": 12, "min_rect_h_atr": 1.5}


def _fit(pts):
    n = len(pts)
    if n < 2:
        return None
    mx = sum(x for x, _ in pts) / n
    my = sum(y for _, y in pts) / n
    sxx = sum((x - mx) ** 2 for x, _ in pts)
    if sxx == 0:
        return None
    b = sum((x - mx) * (y - my) for x, y in pts) / sxx
    a = my - b * mx
    resid = max(abs(y - (a + b * x)) for x, y in pts)
    return {"a": a, "b": b, "resid": resid}


def _at(line, x):
    return line["a"] + line["b"] * x


def _pid(tf, kind, anchors):
    return "CH-" + hashlib.sha256(f"{tf}|{kind}|{'|'.join(str(a['t']) for a in anchors)}".encode()).hexdigest()[:12]


class _Ctx:
    def __init__(self, v, tf, p):
        self.v, self.tf, self.p = v, tf, p
        self.n = len(v)
        self.a = v.atr()
        self.sec = TF_SECONDS[tf]
        self.start = max(0, self.n - p["window"])
        piv = ind.pivots(v.h, v.l, p["left"], p["right"])
        self.piv = [x for x in piv if x["index"] >= self.start and x["confirmed_index"] <= self.n - 1]
        self.H = [x for x in self.piv if x["kind"] == "H"]
        self.L = [x for x in self.piv if x["kind"] == "L"]
        self.atr = self.a[self.n - 1] if self.n else None

    def close_time(self, i):
        return iso(parse_iso(self.v.t[i]) + timedelta(seconds=self.sec))

    def anchor(self, pv, role):
        return {"role": role, "t": self.v.t[pv["index"]], "index": pv["index"], "price": round(pv["price"], 5), "known_at": self.close_time(pv["confirmed_index"])}


def _first_close(cx, from_i, pred):
    for j in range(from_i, cx.n):
        if pred(j):
            return j
    return None


def _finish(cx, kind, direction, anchors, known_i, boundary, invalidation, target, score, extra=None, confirm=None, broken_fn=None):
    """Common state machine: FORMING -> CONFIRMED -> INVALIDATED / EXPIRED."""
    p = cx.p
    state, avail, conf_i = "FORMING", cx.close_time(known_i), None
    if confirm is not None:
        conf_i = _first_close(cx, known_i + 1, confirm)
    if conf_i is not None:
        state, avail = "CONFIRMED", cx.close_time(conf_i)
        if broken_fn is not None and any(broken_fn(j) for j in range(conf_i + 1, cx.n)):
            state = "INVALIDATED"
        elif cx.n - 1 - conf_i > p["ttl_bars"]:
            state = "EXPIRED"
    elif cx.n - 1 - known_i > p["ttl_bars"]:
        state = "EXPIRED"
    missing = [] if state != "FORMING" else ["CLOSE_BEYOND_BOUNDARY"]
    rec = {"pattern_id": _pid(cx.tf, kind, anchors), "type": kind, "version": VERSION, "tf": cx.tf, "direction_if_confirmed": direction,
           "state": state, "anchors": anchors, "start": anchors[0]["t"], "end": cx.v.t[conf_i] if conf_i is not None else anchors[-1]["t"],
           "detected_at": cx.close_time(known_i), "available_at": avail, "boundary": boundary, "invalidation": None if invalidation is None else round(invalidation, 5),
           "target_projection": None if target is None else round(target, 5), "geometric_score": round(max(0.0, min(1.0, score)), 3),
           "required": ["CONFIRMED_PIVOTS", "CLOSE_BEYOND_BOUNDARY"], "missing": missing,
           "source_event_id": f"{cx.tf}:{anchors[0]['t']}:{anchors[-1]['t']}", "reason_codes": [], "confirm_bar": cx.v.t[conf_i] if conf_i is not None else None}
    if extra:
        rec.update(extra)
    return rec


def _double(cx, top: bool, n_peaks: int):
    pts = cx.H if top else cx.L
    out = []
    tol = cx.p["eq_tol_atr"] * cx.atr
    for k in range(len(pts) - n_peaks, -1, -1):
        grp = pts[k:k + n_peaks]
        if len(grp) < n_peaks:
            continue
        prices = [g["price"] for g in grp]
        if max(prices) - min(prices) > tol or any(grp[j + 1]["index"] - grp[j]["index"] < 5 for j in range(n_peaks - 1)):
            continue
        troughs = []
        opp = cx.L if top else cx.H
        ok = True
        for j in range(n_peaks - 1):
            between = [x for x in opp if grp[j]["index"] < x["index"] < grp[j + 1]["index"]]
            if not between:
                ok = False
                break
            troughs.append(min(between, key=lambda x: x["price"]) if top else max(between, key=lambda x: x["price"]))
        if not ok:
            continue
        neck = min(t["price"] for t in troughs) if top else max(t["price"] for t in troughs)
        depth = (min(prices) - neck) if top else (neck - max(prices))
        if depth < 1.0 * cx.atr:
            continue
        ext = max(prices) if top else min(prices)
        name = ("DOUBLE_TOP" if n_peaks == 2 else "TRIPLE_TOP") if top else ("DOUBLE_BOTTOM" if n_peaks == 2 else "TRIPLE_BOTTOM")
        d = "SHORT" if top else "LONG"
        anchors = [cx.anchor(g, f"PEAK_{j + 1}") for j, g in enumerate(grp)] + [cx.anchor(t, f"NECK_{j + 1}") for j, t in enumerate(troughs)]
        anchors.sort(key=lambda a: a["index"])
        known_i = max(g["confirmed_index"] for g in grp + troughs)
        conf = (lambda j: cx.v.c[j] < neck) if top else (lambda j: cx.v.c[j] > neck)
        broken = (lambda j: cx.v.c[j] > ext) if top else (lambda j: cx.v.c[j] < ext)
        score = 1 - (max(prices) - min(prices)) / (tol + 1e-12) * 0.5
        out.append(_finish(cx, name, d, anchors, known_i, {"neckline": round(neck, 5), "slope": 0.0}, ext + (0.1 if top else -0.1) * cx.atr,
                           neck - depth if top else neck + depth, score, confirm=conf, broken_fn=broken))
        if len(out) >= cx.p["max_per_family"]:
            break
    return out


def _hs(cx, inverse: bool):
    pts = cx.L if inverse else cx.H
    opp = cx.H if inverse else cx.L
    out = []
    s = -1 if inverse else 1
    for k in range(len(pts) - 3, -1, -1):
        ls, hd, rs = pts[k:k + 3]
        if not (s * (hd["price"] - ls["price"]) >= 0.5 * cx.atr and s * (hd["price"] - rs["price"]) >= 0.5 * cx.atr):
            continue
        if abs(ls["price"] - rs["price"]) > 1.0 * cx.atr:
            continue
        t1 = [x for x in opp if ls["index"] < x["index"] < hd["index"]]
        t2 = [x for x in opp if hd["index"] < x["index"] < rs["index"]]
        if not t1 or not t2:
            continue
        T1 = (max if inverse else min)(t1, key=lambda x: x["price"])
        T2 = (max if inverse else min)(t2, key=lambda x: x["price"])
        line = _fit([(T1["index"], T1["price"]), (T2["index"], T2["price"])])
        if line is None or abs(line["b"]) > 0.1 * cx.atr:
            continue
        known_i = max(x["confirmed_index"] for x in (ls, hd, rs, T1, T2))
        height = s * (hd["price"] - _at(line, hd["index"]))
        conf = (lambda j: cx.v.c[j] > _at(line, j)) if inverse else (lambda j: cx.v.c[j] < _at(line, j))
        broken = (lambda j: cx.v.c[j] < hd["price"]) if inverse else (lambda j: cx.v.c[j] > hd["price"])
        anchors = sorted([cx.anchor(ls, "LEFT_SHOULDER"), cx.anchor(hd, "HEAD"), cx.anchor(rs, "RIGHT_SHOULDER"),
                          cx.anchor(T1, "NECK_1"), cx.anchor(T2, "NECK_2")], key=lambda a: a["index"])
        neck_end = _at(line, cx.n - 1)
        out.append(_finish(cx, "INVERSE_HEAD_SHOULDERS" if inverse else "HEAD_SHOULDERS", "LONG" if inverse else "SHORT", anchors, known_i,
                           {"neckline": round(neck_end, 5), "slope": round(line["b"], 6)}, rs["price"] - s * 0.1 * cx.atr,
                           neck_end + (height if inverse else -height), 1 - abs(ls["price"] - rs["price"]) / (cx.atr + 1e-12) * 0.5,
                           confirm=conf, broken_fn=broken))
        if len(out) >= cx.p["max_per_family"]:
            break
    return out


def _lines(cx, cut=None):
    """Fitted upper/lower lines through the last pivots (>= 2 each, up to 4) with index <= cut (None = all)."""
    hs = [x for x in cx.H if cut is None or x["index"] <= cut][-4:]
    ls = [x for x in cx.L if cut is None or x["index"] <= cut][-4:]
    if len(hs) < 2 or len(ls) < 2:
        return None
    up = _fit([(x["index"], x["price"]) for x in hs])
    lo = _fit([(x["index"], x["price"]) for x in ls])
    if up is None or lo is None:
        return None
    if max(up["resid"], lo["resid"]) > cx.p["max_resid_atr"] * cx.atr:
        return None
    i0 = min(hs[0]["index"], ls[0]["index"])
    i1 = max(hs[-1]["index"], ls[-1]["index"])
    w0, w1 = _at(up, i0) - _at(lo, i0), _at(up, i1) - _at(lo, i1)
    if w0 <= 0 or w1 <= 0:
        return None
    return {"up": up, "lo": lo, "hs": hs, "ls": ls, "i0": i0, "i1": i1, "w0": w0, "w1": w1,
            "known_i": max(x["confirmed_index"] for x in hs + ls)}


def _geometric(cx):
    """The structure may already be broken: pivots made AFTER a breakout are not part of it, so the fit is tried with
    the pivot set cut at each of the last few pivots (newest first); the first valid geometry wins."""
    cuts = [None] + sorted({x["index"] for x in cx.piv}, reverse=True)[1:6]
    for cut in cuts:
        out = _geometric_at(cx, _lines(cx, cut))
        if out:
            return out
    return []


def _geometric_at(cx, g):
    if g is None:
        return []
    a, flat = cx.atr, cx.p["flat_slope"] * cx.atr
    bu, bl = g["up"]["b"], g["lo"]["b"]
    converging = g["w1"] <= 0.75 * g["w0"]
    parallel = abs(bu - bl) <= 0.02 * a
    kind = None
    if converging:
        if abs(bu) <= flat and bl > flat:
            kind = "TRIANGLE_ASCENDING"
        elif bu < -flat and abs(bl) <= flat:
            kind = "TRIANGLE_DESCENDING"
        elif bu < -flat and bl > flat:
            kind = "TRIANGLE_SYMMETRICAL"
        elif bu > flat and bl > flat:
            kind = "WEDGE_RISING"
        elif bu < -flat and bl < -flat:
            kind = "WEDGE_FALLING"
    elif parallel and abs(bu) > flat and abs(bl) > flat and (bu > 0) == (bl > 0):
        kind = "CHANNEL_ASCENDING" if bu > 0 else "CHANNEL_DESCENDING"
    elif abs(bu) <= flat and abs(bl) <= flat and g["i1"] - g["i0"] >= cx.p["min_rect_bars"] and g["w1"] >= cx.p["min_rect_h_atr"] * a:
        kind = "RECTANGLE"
    if kind is None:
        return []
    up, lo = g["up"], g["lo"]
    anchors = sorted([cx.anchor(x, "UPPER") for x in g["hs"]] + [cx.anchor(x, "LOWER") for x in g["ls"]], key=lambda z: z["index"])
    ki = g["known_i"]
    br_up = _first_close(cx, ki + 1, lambda j: cx.v.c[j] > _at(up, j) + 0.1 * a)
    br_dn = _first_close(cx, ki + 1, lambda j: cx.v.c[j] < _at(lo, j) - 0.1 * a)
    first = min([x for x in (br_up, br_dn) if x is not None], default=None)
    direction = None if first is None else ("LONG" if first == br_up else "SHORT")
    height = g["w1"]
    score = 1 - max(up["resid"], lo["resid"]) / (cx.p["max_resid_atr"] * a + 1e-12) * 0.6
    bnd = {"upper": round(_at(up, cx.n - 1), 5), "lower": round(_at(lo, cx.n - 1), 5), "upper_slope": round(bu, 6), "lower_slope": round(bl, 6)}
    if direction is None:
        rec = _finish(cx, kind, None, anchors, ki, bnd, None, None, score)
        return [rec]
    inval = _at(lo, first) if direction == "LONG" else _at(up, first)
    tgt = (cx.v.c[first] + height) if direction == "LONG" else (cx.v.c[first] - height)
    conf = (lambda j: j == first)
    broken = (lambda j: cx.v.c[j] < _at(lo, j)) if direction == "LONG" else (lambda j: cx.v.c[j] > _at(up, j))
    out = [_finish(cx, kind, direction, anchors, ki, bnd, inval, tgt, score, confirm=conf, broken_fn=broken)]
    if kind == "RECTANGLE":
        top, bot = _at(up, first), _at(lo, first)
        lvl = top if direction == "LONG" else bot
        back = _first_close(cx, first + 1, lambda j: (cx.v.c[j] < lvl) if direction == "LONG" else (cx.v.c[j] > lvl))
        if back is not None and back - first <= 5:
            d2 = "SHORT" if direction == "LONG" else "LONG"
            out.append(_finish(cx, "FAILED_BREAKOUT_RECLAIM", d2, anchors, first, {"level": round(lvl, 5)},
                               max(cx.v.h[first:back + 1]) if d2 == "SHORT" else min(cx.v.l[first:back + 1]),
                               bot if d2 == "SHORT" else top, score, confirm=lambda j: j == back))
        else:
            ret = _first_close(cx, first + 1, lambda j: (cx.v.l[j] <= lvl + 0.3 * a) if direction == "LONG" else (cx.v.h[j] >= lvl - 0.3 * a))
            if ret is not None:
                cont = _first_close(cx, ret, lambda j: (cx.v.c[j] > lvl and cx.v.c[j] > cx.v.h[ret] - 1e-12 and j > ret) if direction == "LONG"
                                    else (cx.v.c[j] < lvl and cx.v.c[j] < cx.v.l[ret] + 1e-12 and j > ret))
                if cont is not None:
                    out.append(_finish(cx, "BREAKOUT_RETEST", direction, anchors, ret, {"level": round(lvl, 5)},
                                       min(cx.v.l[ret:cont + 1]) - 0.1 * a if direction == "LONG" else max(cx.v.h[ret:cont + 1]) + 0.1 * a,
                                       tgt, score, confirm=lambda j: j == cont))
    return out


def _flags(cx):
    out = []
    a = cx.atr
    n = cx.n
    v = cx.v
    for cons in range(5, 16):
        e = n - 1
        s = e - cons + 1
        if s - 10 < cx.start:
            break
        hi, lo = max(v.h[s:e + 1]), min(v.l[s:e + 1])
        for pole_len in range(3, 11):
            ps = s - pole_len
            move = v.c[s - 1] - v.o[ps]
            if abs(move) < 3 * a or (hi - lo) > 0.5 * abs(move):
                continue
            d = "LONG" if move > 0 else "SHORT"
            highs = [(k, v.h[k]) for k in range(s, e + 1)]
            lows = [(k, v.l[k]) for k in range(s, e + 1)]
            fu, fl = _fit(highs), _fit(lows)
            if fu is None or fl is None:
                continue
            w0, w1 = _at(fu, s) - _at(fl, s), _at(fu, e) - _at(fl, e)
            kind = "PENNANT" if (w0 > 0 and w1 <= 0.7 * w0) else "FLAG"
            anchors = [{"role": "POLE_START", "t": v.t[ps], "index": ps, "price": round(v.o[ps], 5), "known_at": cx.close_time(ps)},
                       {"role": "POLE_END", "t": v.t[s - 1], "index": s - 1, "price": round(v.c[s - 1], 5), "known_at": cx.close_time(s - 1)},
                       {"role": "CONSOLIDATION_END", "t": v.t[e], "index": e, "price": round(v.c[e], 5), "known_at": cx.close_time(e)}]
            # the consolidation is only known when its last bar closed; the breakout must come after it (next scans)
            rec = _finish(cx, f"{kind}_{'BULL' if d == 'LONG' else 'BEAR'}", d, anchors, e, {"upper": round(hi, 5), "lower": round(lo, 5)},
                          lo if d == "LONG" else hi, (hi + abs(move)) if d == "LONG" else (lo - abs(move)),
                          1 - (hi - lo) / (0.5 * abs(move) + 1e-12) * 0.5)
            out.append(rec)
            return out
    return out


def _flag_breaks(cx, params):
    """FLAG/PENNANT confirmation: a close beyond the consolidation box in the pole's direction (checked on the bar AFTER
    the consolidation ended - the box of the previous scan is re-detected one bar earlier)."""
    out = []
    v = cx.v
    n = cx.n
    a = cx.atr
    for cons in range(5, 16):
        e = n - 2
        s = e - cons + 1
        if s - 10 < cx.start:
            break
        hi, lo = max(v.h[s:e + 1]), min(v.l[s:e + 1])
        for pole_len in range(3, 11):
            ps = s - pole_len
            move = v.c[s - 1] - v.o[ps]
            if abs(move) < 3 * a or (hi - lo) > 0.5 * abs(move):
                continue
            d = "LONG" if move > 0 else "SHORT"
            if (d == "LONG" and v.c[n - 1] > hi) or (d == "SHORT" and v.c[n - 1] < lo):
                anchors = [{"role": "POLE_START", "t": v.t[ps], "index": ps, "price": round(v.o[ps], 5), "known_at": cx.close_time(ps)},
                           {"role": "CONSOLIDATION_END", "t": v.t[e], "index": e, "price": round(v.c[e], 5), "known_at": cx.close_time(e)}]
                out.append(_finish(cx, f"FLAG_BREAK_{'BULL' if d == 'LONG' else 'BEAR'}", d, anchors, e, {"upper": round(hi, 5), "lower": round(lo, 5)},
                                   lo if d == "LONG" else hi, (v.c[n - 1] + abs(move)) if d == "LONG" else (v.c[n - 1] - abs(move)), 0.7,
                                   confirm=lambda j: j == n - 1))
                return out
    return out


def scan(v, tf: str, params: dict | None = None) -> dict:
    p = dict(P, **(params or {}))
    if len(v) < 40:
        return {"version": VERSION, "tf": tf, "status": "INSUFFICIENT_BARS", "patterns": []}
    cx = _Ctx(v, tf, p)
    if not cx.atr:
        return {"version": VERSION, "tf": tf, "status": "NO_ATR", "patterns": []}
    pats = []
    for fn in (lambda: _double(cx, True, 2), lambda: _double(cx, False, 2), lambda: _double(cx, True, 3), lambda: _double(cx, False, 3),
               lambda: _hs(cx, False), lambda: _hs(cx, True), lambda: _geometric(cx), lambda: _flags(cx), lambda: _flag_breaks(cx, p)):
        try:
            pats += fn()
        except (ZeroDivisionError, ValueError, IndexError):
            continue
    seen, uniq = set(), []
    for x in pats:
        if x["pattern_id"] in seen:
            continue
        seen.add(x["pattern_id"])
        uniq.append(x)
    return {"version": VERSION, "tf": tf, "status": "OK", "patterns": uniq, "pivots_known": len(cx.piv)}
