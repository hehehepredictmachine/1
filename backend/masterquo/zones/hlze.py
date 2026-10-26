"""High/Low Zone Engine - HLZE (PMW-ZONES-HLZE-1). M5 / M15 swing zones with a lifecycle, equal highs / lows, previous day,
previous session, intraday and consolidation levels. Pure functions of a closed-bar Series as known at `as_of`.

Reused, not duplicated: pivots = strategies.indicators.pivots (left >=, right strictly; known only at p + right), ATR = Wilder ATR14
(strategies.indicators.atr), session boxes and their sweep / breakout edges = analytics.session_engine (DST-aware IANA zones),
M5 consolidation = analysis.range_m5. HLZE adds what those do not have: M5 / M15 zones with explicit boundaries, provisional vs
confirmed pivots, swing prominence, equal highs / lows clusters and the zone lifecycle below.

Timestamps: `created_at` = close of the pivot candle; `confirmed_at` = close of the candle that confirmed it (pivot + right bars).
The bot could not know a pivot before confirmed_at, and nothing is ever back-dated to the pivot candle.

Zone of one pivot (wick-to-body, capped): swing high [max(body top, high - k*ATR), high]; swing low [low, min(body bottom, low + k*ATR)];
at least `min_width_ticks` ticks wide. A zone wider than max_zone_width_atr * ATR is flagged WIDE; more than twice that is rejected.

Lifecycle (bars after confirmed_at only):
  PROVISIONAL (pivot not yet confirmed) -> ACTIVE -> TESTED (a retest after price left the zone for retest_gap_bars)
  -> WEAKENED (retests >= weaken_after_retests: repeated tests can consume resting liquidity - more tests are NOT "stronger")
  -> SWEPT (wick beyond the outer boundary and a close back on the zone side within reclaim_bars = liquidity taken and reclaimed)
  -> BROKEN (a CLOSE beyond the outer boundary by break_close_atr * ATR - a wick alone never breaks a zone)
  -> EXPIRED (older than max_age_bars).
A broken swing high / low continues as BREAKOUT_LEVEL / BREAKDOWN_LEVEL (role flip) from the breaking candle's close.
Liquidity: equal highs / lows and obvious extremes are INFERRED liquidity areas - the engine never claims a quantity of stop orders.
"""
from __future__ import annotations

import hashlib

from ..strategies import indicators as ind
from .series import Series, iso

VERSION = "PMW-ZONES-HLZE-1"
HIGH_TYPES = {"SWING_HIGH", "EQUAL_HIGHS", "INTRADAY_HIGH", "PREVIOUS_SESSION_HIGH", "PREVIOUS_DAY_HIGH", "CONSOLIDATION_HIGH",
              "BREAKDOWN_LEVEL", "SUPPLY"}
LOW_TYPES = {"SWING_LOW", "EQUAL_LOWS", "INTRADAY_LOW", "PREVIOUS_SESSION_LOW", "PREVIOUS_DAY_LOW", "CONSOLIDATION_LOW",
             "BREAKOUT_LEVEL", "DEMAND"}


def _id(prefix: str, *parts) -> str:
    return prefix + "-" + hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:12]


def _rnd(x: float, tick: float) -> float:
    return round(round(x / tick) * tick, 10) if tick > 0 else x


def atr_series(s: Series) -> list[float | None]:
    return ind.atr(s.h, s.l, s.c, 14)


def _atr_at(a: list, i: int) -> float | None:
    for k in range(min(i, len(a) - 1), -1, -1):
        if a[k]:
            return a[k]
    return None


# --------------------------------------------------------------------------------------------- swings
def swings(s: Series, cfg, tick: float, a: list | None = None) -> list[dict]:
    """Confirmed pivots (known at p + right) and provisional candidates in the last `right` bars (never usable as confirmed)."""
    tf = s.tf
    left, right = cfg.swing_left.get(tf, 3), cfg.swing_right.get(tf, 3)
    k_prom = cfg.min_prominence_atr.get(tf, 0.5)
    a = a if a is not None else atr_series(s)
    n = len(s)
    out = []
    for p in ind.pivots(s.h, s.l, left, right):
        at = _atr_at(a, p["index"])
        lo_w, hi_w = p["index"] - left, p["index"] + right + 1
        prom = (s.h[p["index"]] - min(s.l[lo_w:hi_w])) if p["kind"] == "H" else (max(s.h[lo_w:hi_w]) - s.l[p["index"]])
        if not at or prom < k_prom * at:
            continue                                                     # not structurally significant
        out.append(_pivot(s, p["kind"], p["index"], p["confirmed_index"], at, prom, tick, provisional=False))
    for i in range(max(left, n - right), n):                            # right side not complete yet
        at = _atr_at(a, i)
        if not at:
            continue
        rs = range(i + 1, n)
        if all(s.h[i] >= s.h[i - k] for k in range(1, left + 1)) and all(s.h[i] > s.h[j] for j in rs):
            out.append(_pivot(s, "H", i, None, at, s.h[i] - min(s.l[i - left:n]), tick, provisional=True))
        if all(s.l[i] <= s.l[i - k] for k in range(1, left + 1)) and all(s.l[i] < s.l[j] for j in rs):
            out.append(_pivot(s, "L", i, None, at, max(s.h[i - left:n]) - s.l[i], tick, provisional=True))
    return sorted(out, key=lambda x: (x["index"], x["kind"]))


def _pivot(s: Series, kind: str, i: int, ci: int | None, atr: float, prom: float, tick: float, provisional: bool) -> dict:
    return {"pivot_id": _id("PV", s.tf, kind, s.t[i]), "kind": kind, "tf": s.tf, "index": i, "price": s.h[i] if kind == "H" else s.l[i],
            "created_at": s.close_time(i), "confirm_index": ci, "confirmed_at": s.close_time(ci) if ci is not None else None,
            "provisional": provisional, "atr": atr, "prominence_atr": round(prom / atr, 3) if atr else None}


def pivot_zone(s: Series, pv: dict, cfg, tick: float) -> tuple[float, float]:
    i, at = pv["index"], pv["atr"]
    minw = cfg.min_width_ticks * tick
    if pv["kind"] == "H":
        up = s.h[i]
        lo = max(max(s.o[i], s.c[i]), up - cfg.zone_half_width_atr * at)
        lo = min(lo, up - minw)
    else:
        lo = s.l[i]
        up = min(min(s.o[i], s.c[i]), lo + cfg.zone_half_width_atr * at)
        up = max(up, lo + minw)
    return _rnd(lo, tick), _rnd(up, tick)


# --------------------------------------------------------------------------------------------- lifecycle
def lifecycle(s: Series, a: list, *, side: str, lower: float, upper: float, start: int, cfg, max_age: int, birth_index: int) -> dict:
    """side HIGH = resistance tested from below (outer boundary = upper); LOW = support tested from above (outer = lower).
    Only bars with index > start (known after the zone became known) are evaluated."""
    n = len(s)
    st = {"status": "ACTIVE", "retests": 0, "first_touch_at": None, "last_touch_at": None, "penetration_max": 0.0, "rejection_max_atr": 0.0,
          "swept_at": None, "broken_at": None, "broken_index": None, "events": []}
    inside_since, left_for, pending = None, cfg.retest_gap_bars, None   # pending = (index of wick beyond, extreme)
    for j in range(start + 1, n):
        at = _atr_at(a, j) or 0.0
        tol, brk = cfg.touch_tol_atr * at, cfg.break_close_atr * at
        hi, lo, c = s.h[j], s.l[j], s.c[j]
        t_close = s.close_time(j)
        if side == "HIGH":
            touch = hi >= lower - tol
            wick_beyond = hi > upper + tol
            close_beyond = c > upper + brk
            back = c <= upper
            pen = (hi - lower) / (upper - lower) if upper > lower else 0.0
            rej = max(0.0, lower - c) / at if at else 0.0
        else:
            touch = lo <= upper + tol
            wick_beyond = lo < lower - tol
            close_beyond = c < lower - brk
            back = c >= lower
            pen = (upper - lo) / (upper - lower) if upper > lower else 0.0
            rej = max(0.0, c - upper) / at if at else 0.0
        if close_beyond:
            st.update(status="BROKEN", broken_at=t_close, broken_index=j)
            st["events"].append({"kind": "BROKEN_BY_CLOSE", "at": iso(t_close)})
            break
        if pending is not None:
            if back:
                st.update(status="SWEPT", swept_at=t_close)
                st["events"].append({"kind": "SWEEP_RECLAIMED", "at": iso(t_close), "wick_at": iso(s.close_time(pending))})
                pending = None
            elif j - pending >= cfg.reclaim_bars:
                pending = None                                           # stayed beyond without a decisive close: no reclaim
        if wick_beyond and back and pending is None and st["status"] != "SWEPT":
            st.update(status="SWEPT", swept_at=t_close)
            st["events"].append({"kind": "SWEEP_RECLAIMED", "at": iso(t_close), "wick_at": iso(t_close)})
        elif wick_beyond and not back:
            pending = j
        if touch:
            st["penetration_max"] = max(st["penetration_max"], round(min(pen, 9.99), 3))
            if st["first_touch_at"] is None:
                st["first_touch_at"] = t_close
            if left_for >= cfg.retest_gap_bars:
                st["retests"] += 1
                st["events"].append({"kind": "RETEST", "at": iso(t_close), "rejection_atr": round(rej, 3)})
            st["rejection_max_atr"] = max(st["rejection_max_atr"], round(rej, 3))
            st["last_touch_at"] = t_close
            left_for = 0
        else:
            left_for += 1
    if st["status"] not in ("BROKEN", "SWEPT"):
        if st["retests"] >= cfg.weaken_after_retests:
            st["status"] = "WEAKENED"
        elif st["retests"] > 0:
            st["status"] = "TESTED"
    if st["status"] != "BROKEN" and (n - 1 - birth_index) > max_age:
        st["status"] = "EXPIRED"
    return st


def _zone(zid, ztype, s: Series, lower, upper, created_at, confirmed_at, atr, *, provisional=False, evidence=None, sources=None,
          extra=None) -> dict:
    w = upper - lower
    z = {"zone_id": zid, "zone_type": ztype, "tf": s.tf, "lower": lower, "upper": upper, "mid": round((lower + upper) / 2, 10), "width": round(w, 10),
         "width_atr": round(w / atr, 3) if atr else None, "atr_at_creation": atr, "created_at": iso(created_at), "confirmed_at": iso(confirmed_at),
         "provisional": provisional, "status": "PROVISIONAL" if provisional else "ACTIVE", "evidence": evidence or [], "source_ids": sources or [],
         "origin_module": VERSION}
    z.update(extra or {})
    return z


def _apply(z: dict, lc: dict, n: int, birth: int) -> dict:
    z.update(status=lc["status"], retests=lc["retests"], first_touch_at=iso(lc["first_touch_at"]), last_touch_at=iso(lc["last_touch_at"]),
             penetration_max=lc["penetration_max"], rejection_max_atr=lc["rejection_max_atr"], swept_at=iso(lc["swept_at"]),
             broken_at=iso(lc["broken_at"]), events=lc["events"][-12:], age_bars=n - 1 - birth)
    return z


# --------------------------------------------------------------------------------------------- swing / equal / role-flip zones
def swing_zones(s: Series, cfg, tick: float, a: list | None = None, piv: list | None = None) -> list[dict]:
    a = a if a is not None else atr_series(s)
    piv = piv if piv is not None else swings(s, cfg, tick, a)
    n = len(s)
    max_age = cfg.max_age_bars.get(s.tf, 500)
    lim = cfg.max_zone_width_atr
    out = []
    for pv in piv:
        lo, up = pivot_zone(s, pv, cfg, tick)
        ztype = "SWING_HIGH" if pv["kind"] == "H" else "SWING_LOW"
        ev = [{"group": "structure", "kind": f"{s.tf}_{ztype}", "root": pv["pivot_id"], "detail": f"prominence {pv['prominence_atr']} ATR"}]
        z = _zone(_id("HZ", s.tf, ztype, s.t[pv["index"]]), ztype, s, lo, up, pv["created_at"], pv["confirmed_at"], pv["atr"],
                  provisional=pv["provisional"], evidence=ev, sources=[pv["pivot_id"]],
                  extra={"pivot_id": pv["pivot_id"], "pivot_time": iso(s.t[pv["index"]]), "pivot_price": pv["price"], "prominence_atr": pv["prominence_atr"]})
        if z["width_atr"] and z["width_atr"] > 2 * lim:
            continue                                                     # too wide to carry entry / invalidation information
        z["wide"] = bool(z["width_atr"] and z["width_atr"] > lim)
        if pv["provisional"]:
            z["age_bars"] = n - 1 - pv["index"]
            out.append(z)
            continue
        lc = lifecycle(s, a, side="HIGH" if pv["kind"] == "H" else "LOW", lower=lo, upper=up, start=pv["confirm_index"], cfg=cfg,
                       max_age=max_age, birth_index=pv["index"])
        out.append(_apply(z, lc, n, pv["index"]))
        if lc["status"] == "BROKEN":                                     # role flip from the breaking close
            j = lc["broken_index"]
            ft = "BREAKOUT_LEVEL" if pv["kind"] == "H" else "BREAKDOWN_LEVEL"
            f = _zone(_id("HZ", s.tf, ft, s.t[pv["index"]]), ft, s, lo, up, s.close_time(j), s.close_time(j), _atr_at(a, j),
                      evidence=[{"group": "reaction", "kind": "BREAK_BY_CLOSE", "root": pv["pivot_id"], "detail": f"close {s.c[j]}"}],
                      sources=[z["zone_id"], pv["pivot_id"]], extra={"pivot_id": pv["pivot_id"], "flipped_from": z["zone_id"]})
            lc2 = lifecycle(s, a, side="LOW" if pv["kind"] == "H" else "HIGH", lower=lo, upper=up, start=j, cfg=cfg, max_age=max_age, birth_index=j)
            out.append(_apply(f, lc2, n, j))
    return out


def equal_zones(s: Series, piv: list[dict], cfg, tick: float, a: list) -> list[dict]:
    """Equal highs / lows: >= 2 CONFIRMED pivots of one kind within tolerance, at least min_cluster_gap_bars apart. Known when the
    second member was confirmed. Marked as an INFERRED liquidity area (stops above highs / below lows), never a measured quantity."""
    n = len(s)
    at_last = _atr_at(a, n - 1) or 0.0
    tol = max(cfg.cluster_tol_atr * at_last, cfg.min_width_ticks * tick)
    out = []
    for kind in ("H", "L"):
        ps = sorted([p for p in piv if p["kind"] == kind and not p["provisional"]], key=lambda p: p["price"])
        groups: list[list[dict]] = []
        for p in ps:
            if groups and p["price"] - groups[-1][0]["price"] <= tol:
                groups[-1].append(p)
            else:
                groups.append([p])
        for g in groups:
            idx = sorted(p["index"] for p in g)
            if len(g) < 2 or idx[-1] - idx[0] < cfg.min_cluster_gap_bars:
                continue
            g = sorted(g, key=lambda p: p["confirm_index"])
            known_i = g[1]["confirm_index"]
            lo, up = min(p["price"] for p in g), max(p["price"] for p in g)
            if up - lo < cfg.min_width_ticks * tick:
                lo, up = (lo, lo + cfg.min_width_ticks * tick) if kind == "L" else (up - cfg.min_width_ticks * tick, up)
            ztype = "EQUAL_HIGHS" if kind == "H" else "EQUAL_LOWS"
            ev = [{"group": "structure", "kind": f"{s.tf}_{ztype}", "root": p["pivot_id"], "detail": f"{len(g)} szczytów/dołków w tolerancji"}
                  for p in g]
            z = _zone(_id("HZ", s.tf, ztype, s.t[g[0]["index"]]), ztype, s, _rnd(lo, tick), _rnd(up, tick), s.close_time(g[0]["index"]),
                      s.close_time(known_i), _atr_at(a, known_i), evidence=ev, sources=[p["pivot_id"] for p in g],
                      extra={"liquidity": {"inference": "INFERRED", "side": "ABOVE" if kind == "H" else "BELOW",
                                           "note": "obszar prawdopodobnej płynności (zlecenia stop) – bez danych o zleceniach, ilość nieznana"},
                             "members": len(g)})
            lc = lifecycle(s, a, side="HIGH" if kind == "H" else "LOW", lower=z["lower"], upper=z["upper"], start=known_i, cfg=cfg,
                           max_age=cfg.max_age_bars.get(s.tf, 500), birth_index=idx[-1])
            out.append(_apply(z, lc, n, idx[-1]))
    return out


# --------------------------------------------------------------------------------------------- reference levels
def day_levels(m5: Series, d1: Series, cfg, tick: float, a5: list, as_of: float) -> list[dict]:
    """PREVIOUS_DAY_HIGH / LOW from the last CLOSED broker D1 bar (MT5 D1 = broker server day), lifecycle on M5 after its close;
    INTRADAY_HIGH / LOW = developing extremes of the current broker day (PROVISIONAL, change until the day closes)."""
    out = []
    if len(d1) == 0 or len(m5) == 0:
        return out
    k = len(d1) - 1
    prev_close = d1.close_time(k)
    minw = cfg.min_width_ticks * tick
    start = next((i for i in range(len(m5)) if m5.t[i] >= prev_close), None)
    at = _atr_at(a5, len(m5) - 1)
    for kind, price in (("PREVIOUS_DAY_HIGH", d1.h[k]), ("PREVIOUS_DAY_LOW", d1.l[k])):
        lo, up = (price - minw, price) if kind.endswith("HIGH") else (price, price + minw)
        z = _zone(_id("HZ", "D1", kind, d1.t[k]), kind, m5, _rnd(lo, tick), _rnd(up, tick), prev_close, prev_close, at,
                  evidence=[{"group": "structure", "kind": kind, "root": f"D1:{d1.t[k]}:{kind[-4:]}", "detail": f"D1 {iso(d1.t[k])[:10]}"}],
                  sources=[f"D1:{iso(d1.t[k])}"], extra={"tf": "D1", "day": iso(d1.t[k])[:10]})
        if start is not None:
            lc = lifecycle(m5, a5, side="HIGH" if kind.endswith("HIGH") else "LOW", lower=z["lower"], upper=z["upper"], start=start - 1,
                           cfg=cfg, max_age=10 ** 9, birth_index=start)
            _apply(z, lc, len(m5), start)
        out.append(z)
    if start is not None and start < len(m5):
        hi = max(m5.h[start:])
        lo = min(m5.l[start:])
        for kind, price in (("INTRADAY_HIGH", hi), ("INTRADAY_LOW", lo)):
            l_, u_ = (price - minw, price) if kind.endswith("HIGH") else (price, price + minw)
            out.append(_zone(_id("HZ", "D", kind, prev_close), kind, m5, _rnd(l_, tick), _rnd(u_, tick), as_of, None, at, provisional=True,
                             evidence=[{"group": "structure", "kind": kind, "root": f"DAY:{prev_close}:{kind[-4:]}", "detail": "ekstremum bieżącego dnia (rozwija się)"}],
                             extra={"tf": "M5", "developing": True}))
    return out


def session_levels(boxes: list[dict], m5: Series, cfg, tick: float, a5: list) -> list[dict]:
    """PREVIOUS_SESSION_HIGH / LOW from the most recent FINAL box of every session (analytics.session_engine); the box edge state
    (UNTOUCHED / SWEPT / BROKEN / EXPIRED, from closed bars only) becomes the zone status."""
    out = []
    last: dict = {}
    for b in boxes:
        if b.get("state") == "FINAL":
            last[b["session"]] = b
    minw = cfg.min_width_ticks * tick
    at = _atr_at(a5, len(m5) - 1) if len(m5) else None
    for sess, b in sorted(last.items()):
        edges = b.get("edges") or {}
        for kind, price, edge in (("PREVIOUS_SESSION_HIGH", b["final_high"], edges.get("HIGH")),
                                  ("PREVIOUS_SESSION_LOW", b["final_low"], edges.get("LOW"))):
            lo, up = (price - minw, price) if kind.endswith("HIGH") else (price, price + minw)
            est = (edge or {}).get("state") if isinstance(edge, dict) else edge
            status = {"SWEPT": "SWEPT", "BROKEN": "BROKEN", "EXPIRED": "EXPIRED"}.get(str(est or "").upper(), "ACTIVE")
            z = _zone(_id("HZ", "SES", b["box_id"], kind), kind, m5, _rnd(lo, tick), _rnd(up, tick),
                      None, None, at, evidence=[{"group": "structure", "kind": kind, "root": f"SES:{b['box_id']}:{kind[-4:]}",
                                                 "detail": f"{sess} {b.get('local_date')}"}],
                      sources=[b["box_id"]], extra={"session": sess, "tf": "M5", "box_state": b.get("state")})
            z.update(status=status, created_at=b.get("known_at"), confirmed_at=b.get("known_at"), edge=edge)
            out.append(z)
    return out


def consolidation_levels(m5_bars: list[dict], m5: Series, cfg, tick: float, a5: list) -> list[dict]:
    """CONSOLIDATION_HIGH / LOW from analysis.range_m5 (frozen M5 range); a range broken by close turns its edge into
    BREAKOUT_LEVEL / BREAKDOWN_LEVEL."""
    from ..analysis import range_m5 as RG
    from ..strategies.base import TFView
    if len(m5) < 60:
        return []
    v = TFView("M5", [dict(b, closed=True) for b in m5_bars])
    try:
        rg = RG.detect(v)
    except Exception:  # noqa: BLE001 - a detector error never removes other zones
        return []
    if rg.get("status") != "OK":
        return []
    minw = cfg.min_width_ticks * tick
    at = _atr_at(a5, len(m5) - 1)
    out = []
    state = rg.get("state")
    for kind, price in (("CONSOLIDATION_HIGH", rg["top"]), ("CONSOLIDATION_LOW", rg["bottom"])):
        ztype = kind
        if state == "BROKEN_UP" and kind.endswith("HIGH"):
            ztype = "BREAKOUT_LEVEL"
        elif state == "BROKEN_DOWN" and kind.endswith("LOW"):
            ztype = "BREAKDOWN_LEVEL"
        lo, up = (price - minw, price) if kind.endswith("HIGH") else (price, price + minw)
        z = _zone(_id("HZ", "RNG", rg.get("range_id"), kind), ztype, m5, _rnd(lo, tick), _rnd(up, tick), None, None, at,
                  evidence=[{"group": "structure", "kind": ztype, "root": f"RNG:{rg.get('range_id')}:{kind[-4:]}",
                             "detail": f"zakres M5 {rg.get('lookback')} świec, stan {state}"}],
                  sources=[str(rg.get("range_id"))], extra={"range_state": state})
        z.update(created_at=rg.get("available_at"), confirmed_at=rg.get("available_at"))
        out.append(z)
    return out


def build(series: dict[str, Series], cfg, tick: float, *, m5_bars: list[dict] | None = None, d1: Series | None = None,
          boxes: list[dict] | None = None, as_of: float) -> dict:
    """All HLZE zones known at as_of. series: {"M5": Series, "M15": Series} (cut at as_of by the caller)."""
    zones, pivots = [], {}
    for tf in cfg.tfs:
        s = series.get(tf)
        if s is None or len(s) < 40:
            continue
        a = atr_series(s)
        piv = swings(s, cfg, tick, a)
        pivots[tf] = piv
        zones.extend(swing_zones(s, cfg, tick, a, piv))
        zones.extend(equal_zones(s, piv, cfg, tick, a))
    m5 = series.get("M5")
    if m5 is not None and len(m5) >= 40:
        a5 = atr_series(m5)
        if d1 is not None:
            zones.extend(day_levels(m5, d1, cfg, tick, a5, as_of))
        if boxes:
            zones.extend(session_levels(boxes, m5, cfg, tick, a5))
        if m5_bars:
            zones.extend(consolidation_levels(m5_bars, m5, cfg, tick, a5))
    return {"version": VERSION, "zones": zones, "pivots": pivots}
