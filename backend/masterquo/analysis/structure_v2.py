"""STRUCTURE_CAUSAL_V2 (PMW-UPD-07 R02) - swing structure and the pattern-instance automaton; LEGACY_COMPAT = analysis/chart_patterns.

Swings: two layers, internal 3/3 and major 5/5. A pivot at bar p is known after bar p+right closes (known_index); equal extremes:
the EARLIEST bar wins (deterministic tie-break). Labels per layer vs the previous swing of the same side: HH/LH (highs), HL/LL (lows),
EQH/EQL within the tolerance max(2 ticks, 0.1 ATR); UNKNOWN without history. Trend UP needs a known HH and HL, DOWN needs LL and LH,
anything else TRANSITION/RANGE (never a forced direction).
Events on CLOSED bars against swings known BEFORE the bar (+ buffer = max(2 ticks, 0.1 ATR)):
  BOS_UP / BOS_DOWN               close beyond the last swing in the direction of the current structure (or from RANGE)
  STRUCTURE_CHANGE_UP / _DOWN     close beyond the protected swing against the current structure (CHoCH is only a label)
  SWEEP_CANDIDATE_HIGH / _LOW     wick beyond, close back - not a BOS
Each level fires once (event_id = layer + kind + pivot time). usable_at = the confirming bar's close (never the pivot time).

Pattern instance automaton (any family with a confirm level, a direction and an invalidation level):
  FORMING -> CONFIRMED -> RETEST_PENDING -> RETEST_HELD / RETEST_FAILED, separately INVALIDATED / EXPIRED (TTL bars).
  Each new bar is judged against the state BEFORE that bar: invalidation is checked before confirmation; an instance invalidated
  earlier is never revived by a later breakout (regression A-07-01: closes [100, 90, 101, 110], invalidation 95, confirm > 105 ->
  INVALIDATED). If one bar both touches the invalidation (wick) and closes beyond the confirm level the order is unknown:
  conservative INVALIDATED + flag INTRABAR_ORDER_UNKNOWN. Anchors and prices of an instance never change (new geometry = new revision).
"""
from __future__ import annotations

import hashlib

PROFILE = "STRUCTURE_CAUSAL_V2"
PARAMS = {"internal": (3, 3), "major": (5, 5), "window": 300, "eq_tol_atr": 0.5, "breakout_buffer_atr": 0.1, "retest_tol_atr": 0.3, "ttl_bars": 30,
          "label_tol_atr": 0.1, "min_ticks": 2}


def pivots(h: list[float], lo: list[float], left: int, right: int) -> list[dict]:
    out = []
    for p in range(left, len(h) - right):
        if h[p] > max(h[p - left:p]) and h[p] >= max(h[p + 1:p + right + 1]):
            out.append({"kind": "H", "index": p, "price": h[p], "known_index": p + right})
        if lo[p] < min(lo[p - left:p]) and lo[p] <= min(lo[p + 1:p + right + 1]):
            out.append({"kind": "L", "index": p, "price": lo[p], "known_index": p + right})
    return out


def label_swings(piv: list[dict], tol: float) -> list[dict]:
    last = {"H": None, "L": None}
    out = []
    for p in sorted(piv, key=lambda x: (x["known_index"], x["index"])):
        prev = last[p["kind"]]
        if prev is None:
            lab = "UNKNOWN"
        elif abs(p["price"] - prev["price"]) <= tol:
            lab = "EQH" if p["kind"] == "H" else "EQL"
        elif p["kind"] == "H":
            lab = "HH" if p["price"] > prev["price"] else "LH"
        else:
            lab = "HL" if p["price"] > prev["price"] else "LL"
        out.append(dict(p, label=lab))
        last[p["kind"]] = p
    return out


def trend(labeled: list[dict], upto_index: int) -> str:
    known = [p for p in labeled if p["known_index"] <= upto_index]
    lh = next((p["label"] for p in reversed(known) if p["kind"] == "H"), None)
    ll = next((p["label"] for p in reversed(known) if p["kind"] == "L"), None)
    if lh is None or ll is None or "UNKNOWN" in (lh, ll):
        return "UNKNOWN"
    if lh == "HH" and ll == "HL":
        return "UP"
    if lh == "LH" and ll == "LL":
        return "DOWN"
    return "TRANSITION/RANGE"


def _atr(h, lo, c, i, n=14):
    if i < n:
        return None
    trs = [max(h[k] - lo[k], abs(h[k] - c[k - 1]), abs(lo[k] - c[k - 1])) for k in range(i - n + 1, i + 1)]
    return sum(trs) / n


def atr_series(h, lo, c, n=14) -> list:
    out, tr = [None] * len(c), []
    for i in range(len(c)):
        tr.append(h[i] - lo[i] if i == 0 else max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1])))
        if i >= n:
            out[i] = sum(tr[i - n + 1:i + 1]) / n
    return out


def walk(t, h, lo, c, tick: float, p: dict, layer: str, trace: bool = False):
    """Incremental O(n) pass of one swing layer: at bar i only swings with known_index <= i-1 are used. Returns (labeled swings,
    events, per-bar trace or None). Each level fires a break once; sweeps are per bar."""
    L, R = p[layer]
    piv = sorted(pivots(h, lo, L, R), key=lambda x: (x["known_index"], x["index"]))
    n = len(c)
    atr = atr_series(h, lo, c)
    a_last = atr[n - 1] or 0.0
    # labels must not depend on the final ATR for the causal trace: relabel with the ATR known at each swing's known bar
    lab_c, last_side = [], {"H": None, "L": None}
    for x in piv:
        a_k = atr[x["known_index"]] or a_last
        tol = max(p["min_ticks"] * tick, p["label_tol_atr"] * a_k)
        prev = last_side[x["kind"]]
        if prev is None:
            lb = "UNKNOWN"
        elif abs(x["price"] - prev["price"]) <= tol:
            lb = "EQH" if x["kind"] == "H" else "EQL"
        elif x["kind"] == "H":
            lb = "HH" if x["price"] > prev["price"] else "LH"
        else:
            lb = "HL" if x["price"] > prev["price"] else "LL"
        lab_c.append(dict(x, label=lb))
        last_side[x["kind"]] = x
    lab = lab_c
    events, fired, tr = [], set(), [] if trace else None
    k = 0
    last = {"H": None, "L": None}
    for i in range(n):
        while k < len(lab) and lab[k]["known_index"] <= i - 1:
            last[lab[k]["kind"]] = lab[k]
            k += 1
        lh, ll = last["H"], last["L"]
        if lh is None or ll is None or "UNKNOWN" in (lh["label"], ll["label"]):
            trd = "UNKNOWN"
        elif lh["label"] == "HH" and ll["label"] == "HL":
            trd = "UP"
        elif lh["label"] == "LH" and ll["label"] == "LL":
            trd = "DOWN"
        else:
            trd = "TRANSITION/RANGE"
        bar_ev = []
        a_i = atr[i]
        if a_i:
            buf = max(p["min_ticks"] * tick, p["breakout_buffer_atr"] * a_i)
            for side, sw in (("H", lh), ("L", ll)):
                if sw is None:
                    continue
                key_base = f"{layer}|{side}|{t[sw['index']]}"
                if side == "H":
                    bc, bw = c[i] > sw["price"] + buf, h[i] > sw["price"] and c[i] <= sw["price"]
                    kind = ("STRUCTURE_CHANGE_UP" if trd == "DOWN" else "BOS_UP") if bc else "SWEEP_CANDIDATE_HIGH" if bw else None
                else:
                    bc, bw = c[i] < sw["price"] - buf, lo[i] < sw["price"] and c[i] >= sw["price"]
                    kind = ("STRUCTURE_CHANGE_DOWN" if trd == "UP" else "BOS_DOWN") if bc else "SWEEP_CANDIDATE_LOW" if bw else None
                if kind is None:
                    continue
                is_sweep = kind.startswith("SWEEP")
                key = key_base + (f"|SWEEP|{i}" if is_sweep else "|BREAK")
                if key in fired or (is_sweep and key_base + "|BREAK" in fired):
                    continue
                fired.add(key)
                e = {"event_id": "SE-" + hashlib.sha256(key.encode()).hexdigest()[:12], "layer": layer, "kind": kind, "level": sw["price"],
                     "swing_t": t[sw["index"]], "bar_t": t[i], "bar_index": i, "trend_before": trd,
                     "label": "CHoCH (etykieta przyjętej definicji)" if kind.startswith("STRUCTURE_CHANGE") else None}
                events.append(e)
                bar_ev.append(kind)
        if trace:
            tr.append({"trend": trd, "last_h": lh["price"] if lh else None, "last_l": ll["price"] if ll else None,
                       "last_h_label": lh["label"] if lh else None, "last_l_label": ll["label"] if ll else None, "events": bar_ev, "atr": a_i})
    return lab, events, tr


def analyse(t: list[str], h: list[float], lo: list[float], c: list[float], tick: float = 0.01, params: dict | None = None) -> dict:
    """Swings + structure events over closed bars (oldest first). Pure, prefix-invariant (labels use the ATR known at each swing)."""
    p = dict(PARAMS, **(params or {}))
    n = len(c)
    res = {"profile": PROFILE, "params": p, "layers": {}, "events": [], "status": "OK" if n >= 30 else "WARMING_UP"}
    for layer in ("internal", "major"):
        lab, ev, _ = walk(t, h, lo, c, tick, p, layer)
        res["layers"][layer] = {"swings": [{"kind": x["kind"], "label": x["label"], "price": x["price"], "t": t[x["index"]],
                                            "known_at_bar": t[x["known_index"]]} for x in lab][-20:], "trend": trend(lab, n - 1)}
        res["events"] += ev
    res["events"] = sorted(res["events"], key=lambda e: (e["bar_index"], e["layer"]))[-60:]
    return res


class PatternInstance:
    """direction +1 LONG / -1 SHORT; confirm and invalidation are frozen prices (or callables of bar index for sloped boundaries)."""

    def __init__(self, pattern_id: str, direction: int, confirm, invalidation, start_index: int, ttl_bars: int = 30, retest_tol: float = 0.0):
        self.id, self.dir, self.confirm, self.inval = pattern_id, direction, confirm, invalidation
        self.start, self.ttl, self.retest_tol = start_index, ttl_bars, retest_tol
        self.state, self.flags, self.history, self.confirmed_index = "FORMING", [], [], None

    def _lvl(self, x, i):
        return x(i) if callable(x) else x

    def step(self, i: int, o: float, h: float, lo: float, c: float) -> str:
        if self.state in ("INVALIDATED", "EXPIRED", "RETEST_HELD", "RETEST_FAILED") or i <= self.start:
            return self.state
        cf, iv = self._lvl(self.confirm, i), self._lvl(self.inval, i)
        d = self.dir
        prev = self.state
        if prev == "FORMING":
            if (c - iv) * d < 0:
                self.state = "INVALIDATED"
            elif (c - cf) * d > 0:
                if (lo - iv if d > 0 else iv - h) < 0:
                    self.state = "INVALIDATED"
                    self.flags.append("INTRABAR_ORDER_UNKNOWN")
                else:
                    self.state, self.confirmed_index = "CONFIRMED", i
            elif i - self.start > self.ttl:
                self.state = "EXPIRED"
        elif prev in ("CONFIRMED", "RETEST_PENDING"):
            if (c - iv) * d < 0:
                self.state = "INVALIDATED"
            elif (c - cf) * d < 0:
                self.state = "RETEST_FAILED"                       # close back inside the pattern
            elif ((lo if d > 0 else h) - cf) * d <= self.retest_tol:
                self.state = "RETEST_PENDING" if prev == "CONFIRMED" else "RETEST_HELD"
            elif prev == "RETEST_PENDING":
                self.state = "RETEST_HELD"
            elif i - self.confirmed_index > self.ttl:
                self.state = "EXPIRED"
        if self.state != prev:
            self.history.append({"bar_index": i, "from": prev, "to": self.state})
        return self.state


def evaluate_instance(pattern_id: str, direction: int, confirm, invalidation, start_index: int, o, h, lo, c, ttl_bars: int = 30, retest_tol: float = 0.0) -> dict:
    inst = PatternInstance(pattern_id, direction, confirm, invalidation, start_index, ttl_bars, retest_tol)
    for i in range(len(c)):
        inst.step(i, o[i], h[i], lo[i], c[i])
    return {"pattern_id": pattern_id, "profile": PROFILE, "state": inst.state, "flags": inst.flags, "history": inst.history,
            "confirmed_index": inst.confirmed_index}


def upgrade_patterns(scan_result: dict, t: list[str], o, h, lo, c, atr: float | None) -> list[dict]:
    """STRUCTURE_CAUSAL_V2 view of the LEGACY_COMPAT records: same anchors, v2 automaton (invalidation checked before confirmation),
    geometry_quality from the number of contacts. Legacy records stay unchanged (separate profile)."""
    out = []
    idx = {x: i for i, x in enumerate(t)}
    for r in scan_result.get("patterns", []):
        d = {"LONG": 1, "SHORT": -1}.get(r.get("direction_if_confirmed"))
        b = r.get("boundary")
        lvl = b.get("price") if isinstance(b, dict) else b if isinstance(b, (int, float)) else None
        if d is None or lvl is None or r.get("invalidation") is None or r["anchors"][-1]["t"] not in idx:
            out.append(dict(r, profile=PROFILE, v2_state="UNSUPPORTED_FOR_V2", geometry_quality="PRELIMINARY"))
            continue
        start = idx[r["anchors"][-1]["t"]]
        ev = evaluate_instance(r["pattern_id"], d, lvl, r["invalidation"], start, o, h, lo, c, retest_tol=0.3 * (atr or 0.0))
        contacts = len(r["anchors"])
        out.append(dict(r, profile=PROFILE, v2_state=ev["state"], v2_flags=ev["flags"], v2_history=ev["history"],
                        geometry_quality="QUALIFIED" if contacts >= (3 if r["type"].startswith(("DOUBLE", "TRIPLE", "HEAD")) else 5) else "PRELIMINARY",
                        contacts=contacts))
    return out
