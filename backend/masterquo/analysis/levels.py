"""Support / resistance zones from confirmed swings (multi_tf: MQ-SR-1.1.0 BOUNDED; zone map: MQ-SR-1.0.0 CHAIN) + W1 / MN1 from D1.

W1 / MN1: the bridge receives MT5 TFs M1..D1; weeks and months are AGGREGATED from closed D1 bars (source
AGGREGATED_FROM_D1). The broker date of a D1 bar = calendar date of (open_utc + 12 h) - correct for any server offset in
[-12 h, +12 h]. A month has calendar boundaries (never "30 days"); a week runs Sunday..Saturday of that date like the MT5 W1
bar (a Sunday D1 bar - gold / FX reopen on Sunday at servers with UTC+0 or a negative offset - opens the NEXT week, it is
never glued to the closed one). A W1/MN1 bar is available only after its period is COMPLETE (a D1 bar of the next period
exists - closed or still forming) - available_at = close of its last D1 bar. Without enough history the analysis reports
BRAK_DANYCH (INSUFFICIENT_HISTORY) - no zone is fabricated.

Zones: confirmed pivots (left = right = 3 bars; W1/MN1: 2/2) of each TF are clustered by price with tolerance
`tol_atr` x ATR14(TF) (at least 2 points). A zone records: TF of origin, low/high, number of INDEPENDENT reactions (pivots
>= `right` bars apart), first/last reaction, age in bars, freshness, state (INTACT / BROKEN_UP / BROKEN_DOWN / RECLAIMED)
and available_at = when its last reaction became known (pivot + right bars closed). S/R, FVG/OB and volatility walls are
different level types: their proximity is a confluence FEATURE, it never renames a support into a "wall".

Clustering rule (1.46 arch, I0757), pivots sorted by price:
  BOUNDED (MQ-SR-1.1.0)  a pivot joins the cluster while price - LOWEST price of the cluster <= tol, so the raw width of a zone never
                         exceeds the tolerance; used by multi_tf (/api/v1/structure chart, agent tool get_walls_and_patterns).
  CHAIN   (MQ-SR-1.0.0)  single linkage (price - LAST pivot <= tol): a chain of pivots spaced < tol glues into a zone many times wider than
                         the tolerance. Kept as the zones_for_tf default ONLY because the zone map (zones/engine -> UZICE HTF overlap) feeds
                         the features of trained models (ML legacy zone_*, Quant analysis:zones) - old artifacts must keep exactly today's
                         inputs; a switch belongs to a new feature-schema version.
"""
from __future__ import annotations

import hashlib
from datetime import timedelta

from ..indicators import series as ind
from ..timeutil import TF_SECONDS, iso, parse_iso

VERSION = "MQ-SR-1.1.0"                       # multi_tf (BOUNDED clusters)
CLUSTER_RULES = {"BOUNDED": "MQ-SR-1.1.0", "CHAIN": "MQ-SR-1.0.0"}
# 1.46: the unused constant UTC (and its timezone import) removed


def broker_date(open_utc: str):
    return (parse_iso(open_utc) + timedelta(hours=12)).date()


def aggregate_d1(d1: list[dict], period: str) -> dict:
    """Closed D1 bars -> closed W1 / MN1 bars (complete periods only). A forming (closed=False) D1 bar is used only as the
    end-of-period marker: its data never enters a bar."""
    closed = [b for b in d1 if b.get("closed") and b.get("open_utc")]
    if not closed:
        return {"status": "INSUFFICIENT_HISTORY", "bars": [], "source": "AGGREGATED_FROM_D1", "period": period}

    def key(b):
        d = broker_date(b["open_utc"])
        if period == "MN1":
            return (d.year, d.month)
        # 1.46: the ISO week (Mon..Sun) glued a Sunday D1 bar (UTC+0 / negative server offsets) to the PREVIOUS, already closed week
        # (its h/l/c came from the reopening); the week now starts on Sunday like the MT5 W1 bar
        y, w, _ = (d + timedelta(days=1) if d.weekday() == 6 else d).isocalendar()
        return (y, w)
    groups: dict = {}
    order = []
    for b in closed:
        k = key(b)
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(b)
    # 1.46: with only CLOSED D1 bars the last group was always treated as incomplete - on Monday (D1 forming, last closed = Friday)
    # the complete previous week (and on the 1st the previous month) dropped out; a D1 bar of a LATER period (closed or forming) ends it
    later = [key(b) for b in d1 if b.get("open_utc") and b.get("closed") is False and parse_iso(b["open_utc"]) > parse_iso(closed[-1]["open_utc"])]
    nxt = next((k for k in later if k != order[-1]), None)
    complete = order if nxt is not None else order[:-1]
    bars = []
    for k in complete:                        # the last group may still be incomplete -> not a closed bar
        g = groups[k]
        last = g[-1]
        avail = last.get("available_at") or iso(parse_iso(last["open_utc"]) + timedelta(seconds=86400))
        bars.append({"open_utc": g[0]["open_utc"], "o": g[0]["o"], "h": max(x["h"] for x in g), "l": min(x["l"] for x in g), "c": last["c"],
                     "tv": sum(float(x.get("tv") or 0) for x in g), "closed": True, "available_at": avail, "days": len(g),
                     "period_key": f"{k[0]}-{k[1]:02d}"})
    fp = nxt if nxt is not None else order[-1]
    return {"status": "OK" if bars else "INSUFFICIENT_HISTORY", "bars": bars, "source": "AGGREGATED_FROM_D1", "period": period,
            "forming_period": f"{fp[0]}-{fp[1]:02d}"}


def cluster_pivots(piv: list[dict], tol: float, rule: str = "CHAIN") -> list[list[dict]]:
    """Pivots sorted by price -> clusters (see the module docstring: BOUNDED = width <= tol, CHAIN = single linkage)."""
    if rule not in CLUSTER_RULES:
        raise ValueError(f"unknown S/R cluster rule {rule}")
    clusters: list[list[dict]] = []
    for p in piv:
        ref = clusters[-1][0 if rule == "BOUNDED" else -1]["price"] if clusters else None
        if ref is not None and p["price"] - ref <= tol:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    return clusters


def zones_for_tf(v, tf: str, *, right: int = 3, tol_atr: float = 0.25, max_zones: int = 8, fresh_bars: int = 60,
                 point: float | None = None, period_seconds: int | None = None, cluster: str = "CHAIN") -> dict:
    """v: TFView-like (t, o, h, l, c). Returns zones nearest to the last close. `cluster`: BOUNDED / CHAIN (default - the rule of the zone
    map and of the trained zone features; see the module docstring)."""
    n = len(v)
    if n < 2 * right + 5:
        return {"tf": tf, "status": "INSUFFICIENT_HISTORY", "zones": []}
    a = ind.atr(v.h, v.l, v.c, 14)
    atr = a[n - 1] or (sum(h - lo for h, lo in zip(v.h[-14:], v.l[-14:])) / min(14, n))
    tol = max(tol_atr * atr, 2 * (point or 0.0))
    piv = [p for p in ind.pivots(v.h, v.l, right, right) if p["confirmed_index"] <= n - 1]
    sec = period_seconds or TF_SECONDS.get(tf, 86400)
    piv.sort(key=lambda p: p["price"])
    clusters = cluster_pivots(piv, tol, cluster)
    last_c = v.c[n - 1]
    zones = []
    for cl in clusters:
        idx = sorted(p["index"] for p in cl)
        indep, lastk = 0, -10 ** 9
        for k in idx:
            if k - lastk >= right:
                indep += 1
                lastk = k
        lo_, hi_ = min(p["price"] for p in cl), max(p["price"] for p in cl)
        if hi_ - lo_ < tol:
            mid = (hi_ + lo_) / 2
            lo_, hi_ = mid - tol / 2, mid + tol / 2
        last_rx = max(cl, key=lambda p: p["index"])
        known = max(p["confirmed_index"] for p in cl)
        after = range(last_rx["index"] + 1, n)
        broke_up = next((j for j in after if v.c[j] > hi_ + tol), None)
        broke_dn = next((j for j in after if v.c[j] < lo_ - tol), None)
        state = "INTACT"
        if broke_up is not None or broke_dn is not None:
            first = min(x for x in (broke_up, broke_dn) if x is not None)
            state = "BROKEN_UP" if first == broke_up else "BROKEN_DOWN"
            if lo_ <= last_c <= hi_ or (state == "BROKEN_UP" and last_c < lo_) or (state == "BROKEN_DOWN" and last_c > hi_):
                state = "RECLAIMED"
        age = n - 1 - last_rx["index"]
        open_last = v.t[known] if known < n else v.t[-1]
        avail = iso(parse_iso(open_last) + timedelta(seconds=sec))
        zid = "SR-" + hashlib.sha256(f"{tf}|{round(lo_, 2)}|{round(hi_, 2)}|{v.t[idx[0]]}".encode()).hexdigest()[:10]
        zones.append({"zone_id": zid, "kind": "SR", "version": CLUSTER_RULES[cluster], "tf": tf, "low": round(lo_, 5), "high": round(hi_, 5),
                      "reactions": indep, "touches": len(cl), "first_utc": v.t[idx[0]], "last_utc": v.t[last_rx["index"]], "age_bars": age,
                      "freshness": "FRESH" if age <= fresh_bars else "OLD", "state": state, "available_at": avail, "known_index": known,
                      "role": "SUPPORT" if hi_ < last_c else ("RESISTANCE" if lo_ > last_c else "AT_PRICE"),
                      "distance_atr": round(min(abs(last_c - lo_), abs(last_c - hi_)) / atr, 2) if atr else None})
    zones.sort(key=lambda z: (z["distance_atr"] if z["distance_atr"] is not None else 9e9))
    return {"tf": tf, "status": "OK", "zones": zones[:max_zones], "tolerance": round(tol, 5), "atr": round(atr, 5)}


class _Bars:
    def __init__(self, bars):
        self.t = [b["open_utc"] for b in bars]
        self.o = [float(b["o"]) for b in bars]
        self.h = [float(b["h"]) for b in bars]
        self.l = [float(b["l"]) for b in bars]
        self.c = [float(b["c"]) for b in bars]

    def __len__(self):
        return len(self.c)


def multi_tf(view, d1_raw: list[dict] | None = None, tfs=("H1", "H4", "H8", "D1"), point: float | None = None) -> dict:
    """S/R zones on the context TFs of a MarketView + W1 / MN1 aggregated from D1."""
    out = {"version": VERSION, "by_tf": {}, "zones": []}
    for tf in tfs:
        v = view.tfs.get(tf)
        if v is None or len(v) == 0:
            out["by_tf"][tf] = {"tf": tf, "status": "BRAK_DANYCH", "zones": []}
            continue
        r = zones_for_tf(v, tf, point=point, cluster="BOUNDED")
        out["by_tf"][tf] = r
        out["zones"] += r["zones"]
    d1 = d1_raw
    if d1 is None and view.tfs.get("D1") is not None:
        dv = view.tfs["D1"]
        d1 = [{"open_utc": t, "o": o, "h": h, "l": lo, "c": c, "closed": True} for t, o, h, lo, c in zip(dv.t, dv.o, dv.h, dv.l, dv.c)]
        if dv.forming:
            d1.append(dict(dv.forming, closed=False))
    for per, right in (("W1", 2), ("MN1", 2)):
        agg = aggregate_d1(d1 or [], per)
        if agg["status"] != "OK" or len(agg["bars"]) < 2 * right + 5:
            out["by_tf"][per] = {"tf": per, "status": "BRAK_DANYCH", "reason": "INSUFFICIENT_HISTORY", "source": agg["source"],
                                 "bars": len(agg["bars"]), "zones": []}
            continue
        r = zones_for_tf(_Bars(agg["bars"]), per, right=right, point=point, period_seconds=7 * 86400 if per == "W1" else 31 * 86400,
                         cluster="BOUNDED")
        for z in r["zones"]:
            z["available_at"] = agg["bars"][z["known_index"]]["available_at"]      # the period bar that confirmed the pivot is closed
        r["source"] = agg["source"]
        out["by_tf"][per] = r
        out["zones"] += r["zones"]
    return out
