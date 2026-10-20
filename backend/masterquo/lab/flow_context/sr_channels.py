"""MQ_SR_CHANNELS_V1 (FF04) - ranked support/resistance bands from confirmed pivots (own implementation; original MQ5 unread).

Raw OHLC only (never Heikin). Pivots WICK (High/Low) or BODY (max/min(O,C)), left/right 10/10, plateau = first qualifying point
(high > left, >= right; low < left, <= right); outside bar that is both -> both kept with AMBIGUOUS_ORDER flag. A pivot is eligible for
290 real bars after CONFIRMATION (age 0..290, expires at 291). Width cap W = (maxH300 - minL300) * 5% (cap, not a target); fewer than 300
bars -> RANGE_WINDOW_PARTIAL; zero range -> FLAT_RANGE (zero-width level allowed). Candidates: each eligible pivot seeds [p, p] and
absorbs other pivots newest->oldest while max(hi,p)-min(lo,p) <= W (bounds = min/max of members - no single-link chaining).
Score = 20*N_pivot + N_touch_bars (High OR Low inside [lo,hi], counted once; a bar spanning the band with both ends outside is not a
touch) over the last `loopback` closed bars. Greedy: score desc, ties more pivots / newer last confirmation / smaller span / stable id;
any intersection (incl. shared edge / containment) removes a candidate; top 10, visible 6. Score is geometry, not P(bounce).
Channel id = hash(context, profile, member ids, bounds); events CREATED/UPDATED/RETIRED per closed-bar snapshot (as_of archive)."""
from __future__ import annotations

import hashlib
import json

ALGO = "MQ_SR_CHANNELS_V1"
DEFAULT = {"depth": 10, "source": "WICK", "retention": 290, "loopback": 300, "width_pct": 5.0, "range_window": 300, "max_selected": 10,
           "visible": 6, "min_pivots": 1}


def validate(cfg: dict | None) -> dict:
    c = dict(DEFAULT, **(cfg or {}))
    if not 1 <= int(c["depth"]) <= 50 or not 100 <= int(c["loopback"]) <= 400 or not 1 <= float(c["width_pct"]) <= 8 or c["source"] not in ("WICK", "BODY"):
        raise ValueError("SR_CONFIG_INVALID")
    c["hash"] = hashlib.sha256(json.dumps({k: c[k] for k in DEFAULT}, sort_keys=True).encode()).hexdigest()[:16]
    return c


def pivots(bars: list[dict], depth: int, source: str = "WICK", upto: int | None = None) -> list[dict]:
    """Confirmed pivots known at bar index `upto` (inclusive): origin i, confirmed at i+depth."""
    n = len(bars) if upto is None else upto + 1
    hi = [max(b["o"], b["c"]) if source == "BODY" else b["h"] for b in bars[:n]]
    lo = [min(b["o"], b["c"]) if source == "BODY" else b["l"] for b in bars[:n]]
    out = []
    for i in range(depth, n - depth):
        isH = hi[i] > max(hi[i - depth:i]) and hi[i] >= max(hi[i + 1:i + depth + 1])
        isL = lo[i] < min(lo[i - depth:i]) and lo[i] <= min(lo[i + 1:i + depth + 1])
        flag = "AMBIGUOUS_ORDER" if (isH and isL) else None
        for k, ok, p in (("H", isH, hi[i]), ("L", isL, lo[i])):
            if ok:
                out.append({"id": f"PV-{k}-{bars[i]['open_utc']}", "kind": k, "origin_index": i, "price": float(p), "confirmed_index": i + depth,
                            "origin_time": bars[i]["open_utc"], "flag": flag})
    return out


def channels_at(bars: list[dict], t: int, cfg: dict | None = None, context: str = "XAUUSD|M15", piv: list | None = None) -> dict:
    """Channel map as known after the close of bar index t (only bars <= t)."""
    c = validate(cfg)
    piv = piv if piv is not None else pivots(bars, c["depth"], c["source"], t)
    elig = [p for p in piv if p["confirmed_index"] <= t and t - p["confirmed_index"] <= c["retention"]]
    w0 = max(0, t - c["range_window"] + 1)
    rng_hi = max(b["h"] for b in bars[w0:t + 1])
    rng_lo = min(b["l"] for b in bars[w0:t + 1])
    flags = []
    if t + 1 < c["range_window"]:
        flags.append("RANGE_WINDOW_PARTIAL")
    W = (rng_hi - rng_lo) * c["width_pct"] / 100.0
    if rng_hi - rng_lo == 0:
        flags.append("FLAT_RANGE")
    order = sorted(elig, key=lambda p: (-p["confirmed_index"], -p["origin_index"], p["id"]))   # newest first, stable
    cands, seen = [], set()
    for seed in order:
        lo_, hi_ = seed["price"], seed["price"]
        mem = [seed]
        for p in order:
            if p is seed:
                continue
            if max(hi_, p["price"]) - min(lo_, p["price"]) <= W + 1e-12:
                mem.append(p)
                lo_, hi_ = min(lo_, p["price"]), max(hi_, p["price"])
        if len(mem) < c["min_pivots"]:
            continue
        key = (round(lo_, 10), round(hi_, 10), tuple(sorted(m["id"] for m in mem)))
        if key in seen:
            continue
        seen.add(key)
        cands.append({"lo": lo_, "hi": hi_, "members": mem})
    l0 = max(0, t - c["loopback"] + 1)
    win = bars[l0:t + 1]
    for cd in cands:
        touch = sum(1 for b in win if cd["lo"] <= b["h"] <= cd["hi"] or cd["lo"] <= b["l"] <= cd["hi"])
        cd["n_pivots"] = len(cd["members"])
        cd["touch_bars"] = touch
        cd["score"] = 20 * cd["n_pivots"] + touch
        cd["last_confirmed"] = max(m["confirmed_index"] for m in cd["members"])
        cd["id"] = "SRC-" + hashlib.sha256(f"{context}|{c['hash']}|{sorted(m['id'] for m in cd['members'])}|{cd['lo']:.10g}|{cd['hi']:.10g}"
                                           .encode()).hexdigest()[:16]
    cands.sort(key=lambda x: (-x["score"], -x["n_pivots"], -x["last_confirmed"], x["hi"] - x["lo"], x["id"]))
    sel = []
    for cd in cands:
        if len(sel) >= c["max_selected"]:
            break
        if any(not (cd["hi"] < s["lo"] or cd["lo"] > s["hi"]) for s in sel):
            continue
        sel.append(cd)
    close = bars[t]["c"]
    out = []
    for rank, cd in enumerate(sel):
        role = "RESISTANCE" if close < cd["lo"] else ("SUPPORT" if close > cd["hi"] else "INSIDE")
        out.append({"id": cd["id"], "rank": rank + 1, "lo": cd["lo"], "hi": cd["hi"], "width": cd["hi"] - cd["lo"], "width_cap": W, "score": cd["score"],
                    "score_components": {"pivots": cd["n_pivots"], "pivot_points": 20 * cd["n_pivots"], "touch_bars": cd["touch_bars"]},
                    "members": [m["id"] for m in cd["members"]], "member_ages": [t - m["confirmed_index"] for m in cd["members"]],
                    "known_at_index": cd["last_confirmed"], "role": role, "status": "PRELIMINARY" if cd["n_pivots"] == 1 else "RANKED",
                    "visible": rank < c["visible"]})
    return {"algorithm_id": ALGO, "as_of_index": t, "as_of": bars[t]["open_utc"], "config_hash": c["hash"], "flags": flags, "width_cap": W,
            "eligible_pivots": len(elig), "candidates": len(cands), "channels": out, "window_used": len(win),
            "note": "score = geometria pasma, nie prawdopodobieństwo odbicia"}


def nearest(snapshot: dict, price: float) -> dict:
    """Native helper pairs: nearest support (hi < price), resistance (lo > price), inside; ties by rank."""
    ch = snapshot["channels"]
    sup = sorted([c for c in ch if c["hi"] < price], key=lambda c: (price - c["hi"], c["rank"]))
    res = sorted([c for c in ch if c["lo"] > price], key=lambda c: (c["lo"] - price, c["rank"]))
    ins = sorted([c for c in ch if c["lo"] <= price <= c["hi"]], key=lambda c: c["rank"])
    pick = lambda xs: {"lo": xs[0]["lo"], "hi": xs[0]["hi"], "id": xs[0]["id"]} if xs else None  # noqa: E731
    return {"support": pick(sup), "resistance": pick(res), "inside": pick(ins)}


class ChannelHistory:
    """Closed-bar archive: one snapshot per bar as known then (HISTORY_AS_KNOWN) + CREATED/UPDATED/RETIRED events."""

    def __init__(self, cfg: dict | None = None, context: str = "XAUUSD|M15", keep: int = 2000):
        self.cfg, self.context, self.keep = validate(cfg), context, keep
        self.snaps: list[dict] = []
        self.events: list[dict] = []
        self.last_ids: dict = {}

    def update(self, bars: list[dict]) -> dict:
        t = len(bars) - 1
        if self.snaps and self.snaps[-1]["as_of"] == bars[t]["open_utc"]:
            return self.snaps[-1]
        snap = channels_at(bars, t, self.cfg, self.context)
        cur = {c["id"]: c for c in snap["channels"]}
        for cid, c in cur.items():
            if cid not in self.last_ids:
                pred = next((p for p, pc in self.last_ids.items() if set(pc["members"]) & set(c["members"])), None)
                self.events.append({"kind": "CREATED" if pred is None else "UPDATED", "id": cid, "predecessor": pred, "as_of": snap["as_of"],
                                    "reason": "NEW_GEOMETRY" if pred is None else "PIVOT_ADDED_OR_WIDTH_CHANGED"})
            elif self.last_ids[cid]["rank"] != c["rank"]:
                self.events.append({"kind": "UPDATED", "id": cid, "as_of": snap["as_of"], "reason": "RANK_CHANGED"})
        for cid in self.last_ids:
            if cid not in cur and not any(e["predecessor"] == cid for e in self.events[-len(cur) - 1:] if e.get("predecessor")):
                self.events.append({"kind": "RETIRED", "id": cid, "as_of": snap["as_of"], "reason": "PIVOT_EXPIRED_OR_REPLACED"})
        self.last_ids = cur
        self.snaps = (self.snaps + [snap])[-self.keep:]
        self.events = self.events[-5000:]
        return snap

    def as_of(self, t_open) -> dict | None:
        xs = [s for s in self.snaps if str(s["as_of"]) <= str(t_open)]
        return xs[-1] if xs else None
