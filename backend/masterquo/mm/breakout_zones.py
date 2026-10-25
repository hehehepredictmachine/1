"""Confirmed swing breakout zones (PMW-MM-BREAKOUT-1). DETERMINISTIC_INDICATOR / analytical events (no orders).

Swings: a swing high at bar i needs `left` bars before and `right` bars after with lower highs (strict on the left, <= on the right
so the earlier of equal highs wins); it becomes KNOWN at the close of bar i+right (available_at). Prominence: high_i - min(low over the
pivot window) >= prominence_atr * ATR(n) at the confirmation bar. Same-type swings closer than `min_sep` bars: only the more extreme one
is kept as a distinct touch (one visit cannot inflate the count). Lows mirrored.

Zones (greedy, deterministic, in confirmation order): a confirmed high joins the ACTIVE resistance zone whose centre is nearest and within
tol = max(tol_atr * ATR, tol_floor_points * point); otherwise it creates a PROVISIONAL zone. Centre = mean of member prices; bounds =
[min(members) - pad, max(members) + pad] with pad = pad_atr * ATR at the zone's creation (frozen). Touches = distinct member swings.
touches >= min_touches -> QUALIFIED_RESISTANCE / QUALIFIED_SUPPORT. Overlapping zones of the same type merge (recorded transition;
the older id survives). A zone without a new touch for `expire_bars` -> EXPIRED. Every transition is appended to zone["history"].

Breakout: CLOSED bar close > upper + buffer of a QUALIFIED resistance (bullish) / close < lower - buffer of a QUALIFIED support (bearish).
Wicks never count; the forming bar is never fed. The first such close CONSUMES the zone (BROKEN_UP/BROKEN_DOWN) whether or not the
direction filter accepts it, so one breakout is reported once. Direction filter (applied before acceptance): SESSION_VWAP (default;
typical price weighted by TICK VOLUME - an activity proxy, flagged), SMA(20), SMMA (MT5 MODE_SMMA recursion), NONE. A filter that is not
ready rejects with FILTER_NOT_READY (never a silent bypass). Event id = zone id + bar time (stable across recalculation).
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np

VERSION = "PMW-MM-BREAKOUT-1"
FILTERS = ("SESSION_VWAP", "SMA", "SMMA", "NONE")


@dataclass
class BreakoutConfig:
    left: int = 3
    right: int = 3
    min_sep: int = 3
    prominence_atr: float = 0.5
    atr_period: int = 14
    tol_atr: float = 0.35
    tol_floor_points: float = 10.0
    pad_atr: float = 0.10
    min_touches: int = 2
    expire_bars: int = 600
    buffer_atr: float = 0.0
    confirmation: str = "SESSION_VWAP"
    sma_period: int = 20
    smma_period: int = 20
    session_start_min: int = 0
    session_tz_offset_min: int = 0
    max_zones: int = 200

    def validate(self):
        if self.left < 1 or self.right < 1 or self.min_sep < 0 or self.min_touches < 1 or self.atr_period < 1:
            raise ValueError("BREAKOUT_SWING_PARAM_INVALID")
        if self.tol_atr < 0 or self.pad_atr < 0 or self.buffer_atr < 0 or self.prominence_atr < 0 or self.expire_bars < 1:
            raise ValueError("BREAKOUT_ZONE_PARAM_INVALID")
        if self.confirmation not in FILTERS or self.sma_period < 1 or self.smma_period < 1:
            raise ValueError("BREAKOUT_FILTER_INVALID")


class Engine:
    """Streaming engine: feed closed bars in order with update(); replay == incremental by construction."""

    def __init__(self, cfg: BreakoutConfig | None = None, point: float = 0.01, tf_s: int = 300):
        self.cfg = cfg or BreakoutConfig()
        self.cfg.validate()
        self.point, self.tf_s = point, tf_s
        self.t, self.o, self.h, self.l, self.c, self.v = [], [], [], [], [], []
        self.atr = []
        self.zones: list[dict] = []
        self.events: list[dict] = []
        self.rejected: list[dict] = []
        self.swings: list[dict] = []
        self._last = {"H": None, "L": None}
        self._sma_sum = 0.0
        self._smma = None
        self._sess, self._pv, self._vol = None, 0.0, 0.0
        self.latest = None
        self.n_zone = 0
        self.n_qualified = 0

    # ----------------------------------------------------------------- indicators (causal, per closed bar)
    def _atr_step(self):
        i = len(self.c) - 1
        tr = self.h[i] - self.l[i] if i == 0 else max(self.h[i] - self.l[i], abs(self.h[i] - self.c[i - 1]), abs(self.l[i] - self.c[i - 1]))
        n = self.cfg.atr_period
        if i + 1 < n:
            self.atr.append(math.nan)
            self._tr_acc = getattr(self, "_tr_acc", 0.0) + tr
        elif i + 1 == n:
            self.atr.append((getattr(self, "_tr_acc", 0.0) + tr) / n)
        else:
            self.atr.append((self.atr[-1] * (n - 1) + tr) / n)

    def _filters_step(self):
        cfg, i = self.cfg, len(self.c) - 1
        self._sma_sum += self.c[i]
        if i >= cfg.sma_period:
            self._sma_sum -= self.c[i - cfg.sma_period]
        self.sma = self._sma_sum / cfg.sma_period if i + 1 >= cfg.sma_period else math.nan
        if i + 1 == cfg.smma_period:
            self._smma = sum(self.c[-cfg.smma_period:]) / cfg.smma_period
        elif i + 1 > cfg.smma_period:
            self._smma = (self._smma * (cfg.smma_period - 1) + self.c[i]) / cfg.smma_period
        self.smma = self._smma if self._smma is not None else math.nan
        tc = self.t[i] + self.tf_s
        sid = math.floor((tc + cfg.session_tz_offset_min * 60 - cfg.session_start_min * 60) / 86400)
        if sid != self._sess:
            self._sess, self._pv, self._vol = sid, 0.0, 0.0
        tp = (self.h[i] + self.l[i] + self.c[i]) / 3.0
        self._pv += tp * self.v[i]
        self._vol += self.v[i]
        self.vwap = self._pv / self._vol if self._vol > 0 else math.nan

    # ----------------------------------------------------------------- swings
    def _confirm_swings(self):
        cfg = self.cfg
        j = len(self.c) - 1 - cfg.right                                 # candidate pivot index confirmed by this bar
        if j - cfg.left < 0:
            return
        a, b = j - cfg.left, j + cfg.right
        atr = self.atr[-1]
        if not math.isfinite(atr):
            return
        H, L = self.h, self.l
        if all(H[k] < H[j] for k in range(a, j)) and all(H[k] <= H[j] for k in range(j + 1, b + 1)):
            prom = H[j] - min(L[a:b + 1])
            if prom >= cfg.prominence_atr * atr:
                self._add_swing("H", j, H[j], atr)
        if all(L[k] > L[j] for k in range(a, j)) and all(L[k] >= L[j] for k in range(j + 1, b + 1)):
            prom = max(H[a:b + 1]) - L[j]
            if prom >= cfg.prominence_atr * atr:
                self._add_swing("L", j, L[j], atr)

    def _add_swing(self, side, j, px, atr):
        i = len(self.c) - 1
        sw = {"side": side, "bar": j, "price": px, "pivot_ts": self.t[j], "confirmed_bar": i, "available_at": self.t[i] + self.tf_s, "atr": atr}
        last = self._last[side]
        if last is not None and j - last["bar"] < self.cfg.min_sep:
            better = (px > last["price"]) if side == "H" else (px < last["price"])
            if not better:
                return                                                   # same visit, less extreme: not a new touch
            self._replace_touch(last, sw)
            self._last[side] = sw
            return
        self._last[side] = sw
        self.swings.append(sw)
        self._cluster(sw)

    def _replace_touch(self, old, new):
        for z in self.zones:
            if old in z["members"] and z["state"] in ("PROVISIONAL", "QUALIFIED_RESISTANCE", "QUALIFIED_SUPPORT"):
                z["members"][z["members"].index(old)] = new
                self._refresh(z, "TOUCH_REPLACED_MORE_EXTREME")
                return
        self.swings.append(new)
        self._cluster(new)

    # ----------------------------------------------------------------- zones
    def _cluster(self, sw):
        cfg = self.cfg
        kind = "RES" if sw["side"] == "H" else "SUP"
        tol = max(cfg.tol_atr * sw["atr"], cfg.tol_floor_points * self.point)
        live = [z for z in self.zones if z["kind"] == kind and z["state"] in ("PROVISIONAL", "QUALIFIED_RESISTANCE", "QUALIFIED_SUPPORT")]
        best = min(live, key=lambda z: (abs(z["center"] - sw["price"]), z["created_bar"]), default=None)
        if best is not None and abs(best["center"] - sw["price"]) <= tol:
            best["members"].append(sw)
            self._refresh(best, "TOUCH")
            self._merge(best)
            return
        self.n_zone += 1
        z = {"zone_id": f"BZ-{kind}-{sw['bar']}-{self.n_zone}", "kind": kind, "members": [sw], "pad": cfg.pad_atr * sw["atr"],
             "created_bar": len(self.c) - 1, "created_ts": sw["available_at"], "state": "PROVISIONAL", "history": []}
        self.zones.append(z)
        self._refresh(z, "CREATED")
        if len(self.zones) > cfg.max_zones:
            old = [x for x in self.zones if x["state"] not in ("PROVISIONAL", "QUALIFIED_RESISTANCE", "QUALIFIED_SUPPORT")]
            for x in old[: len(self.zones) - cfg.max_zones]:
                self.zones.remove(x)

    def _refresh(self, z, why):
        ps = [m["price"] for m in z["members"]]
        z["center"] = float(np.mean(ps))
        z["lower"], z["upper"] = min(ps) - z["pad"], max(ps) + z["pad"]
        z["touches"] = len(z["members"])
        z["first_touch_ts"] = min(m["available_at"] for m in z["members"])
        z["last_touch_ts"] = max(m["available_at"] for m in z["members"])
        z["last_touch_bar"] = max(m["confirmed_bar"] for m in z["members"])
        z["updated_ts"] = self.t[-1] + self.tf_s
        new = ("QUALIFIED_RESISTANCE" if z["kind"] == "RES" else "QUALIFIED_SUPPORT") if z["touches"] >= self.cfg.min_touches else "PROVISIONAL"
        if new != z["state"]:
            z["history"].append({"at": z["updated_ts"], "from": z["state"], "to": new, "why": why})
            if new != "PROVISIONAL" and z["state"] == "PROVISIONAL":
                self.n_qualified += 1
            z["state"] = new

    def _merge(self, z):
        for o in list(self.zones):
            if o is z or o["kind"] != z["kind"] or o["state"] not in ("PROVISIONAL", "QUALIFIED_RESISTANCE", "QUALIFIED_SUPPORT"):
                continue
            if o["lower"] <= z["upper"] and z["lower"] <= o["upper"]:
                keep, gone = (o, z) if o["created_bar"] < z["created_bar"] else (z, o)
                keep["members"] = sorted(keep["members"] + gone["members"], key=lambda m: m["confirmed_bar"])
                keep["pad"] = min(keep["pad"], gone["pad"])
                gone["history"].append({"at": self.t[-1] + self.tf_s, "from": gone["state"], "to": "INVALIDATED", "why": f"MERGED_INTO:{keep['zone_id']}"})
                gone["state"] = "INVALIDATED"
                self._refresh(keep, f"MERGED:{gone['zone_id']}")
                return self._merge(keep)

    # ----------------------------------------------------------------- breakout
    def _filter(self, direction, close):
        m = self.cfg.confirmation
        if m == "NONE":
            return True, None, "NONE"
        ref = {"SESSION_VWAP": self.vwap, "SMA": self.sma, "SMMA": self.smma}[m]
        if not math.isfinite(ref):
            return False, None, "FILTER_NOT_READY"
        ok = close > ref if direction == "BULLISH" else close < ref
        return ok, ref, "PASS" if ok else "FILTER_REJECTED"

    def _breakouts(self):
        i = len(self.c) - 1
        close, atr = self.c[i], self.atr[i]
        buf = self.cfg.buffer_atr * atr if math.isfinite(atr) else (0.0 if self.cfg.buffer_atr == 0 else math.nan)
        tc = self.t[i] + self.tf_s
        for z in self.zones:
            if z["state"] == "QUALIFIED_RESISTANCE" and math.isfinite(buf) and close > z["upper"] + buf:
                d, to = "BULLISH", "BROKEN_UP"
            elif z["state"] == "QUALIFIED_SUPPORT" and math.isfinite(buf) and close < z["lower"] - buf:
                d, to = "BEARISH", "BROKEN_DOWN"
            else:
                if z["state"] in ("PROVISIONAL", "QUALIFIED_RESISTANCE", "QUALIFIED_SUPPORT") and i - z["last_touch_bar"] > self.cfg.expire_bars:
                    z["history"].append({"at": tc, "from": z["state"], "to": "EXPIRED", "why": "NO_TOUCH"})
                    z["state"] = "EXPIRED"
                continue
            ok, ref, why = self._filter(d, close)
            ev = {"event_id": f"{z['zone_id']}@{int(self.t[i])}", "bar_ts": self.t[i], "available_at": tc, "direction": d, "zone_id": z["zone_id"],
                  "zone_lower": z["lower"], "zone_upper": z["upper"], "touches": z["touches"], "close": close, "filter": self.cfg.confirmation,
                  "filter_ref": ref, "filter_status": why, "accepted": ok, "volume_source": "TICK_VOLUME_PROXY" if self.cfg.confirmation == "SESSION_VWAP" else None,
                  "version": VERSION}
            z["history"].append({"at": tc, "from": z["state"], "to": to, "why": "CLOSE_BEYOND_ZONE" + ("" if ok else f"/{why}")})
            z["state"] = to
            z["breakout_event"] = ev["event_id"]
            (self.events if ok else self.rejected).append(ev)
            if ok:
                self.latest = {"direction": d, "bar_ts": self.t[i], "filter": self.cfg.confirmation, "event_id": ev["event_id"]}

    def update(self, t, o, h, l, c, v) -> None:  # noqa: E741
        if self.t and t <= self.t[-1]:
            return                                                   # replayed / older bar: processed exactly once
        for arr, x in ((self.t, t), (self.o, o), (self.h, h), (self.l, l), (self.c, c), (self.v, v)):
            arr.append(float(x))
        self._atr_step()
        self._filters_step()
        self._breakouts()                                            # against zones known BEFORE this bar's swing confirmations
        self._confirm_swings()

    def panel(self) -> dict:
        d = self.latest["direction"] if self.latest else "NONE"
        return {"text": f"LATEST ACCEPTED BREAKOUT: {d}", "direction": d, **({k: self.latest[k] for k in ("bar_ts", "filter")} if self.latest else {}),
                "note": "kierunek ostatniego zaakceptowanego wybicia - nie pozycja, nie zlecenie"}


def run(bars, cfg: BreakoutConfig | None = None, point: float = 0.01, tf_s: int = 300) -> Engine:
    e = Engine(cfg, point, tf_s)
    for i in range(len(bars.t)):
        e.update(bars.t[i], bars.o[i], bars.h[i], bars.l[i], bars.c[i], bars.tv[i])
    return e


def evaluate(bars, cfg: BreakoutConfig, point: float, tf_s: int, horizon: int = 12, follow_atr: float = 1.0) -> dict:
    """False breakout = close back inside the zone within `horizon` bars before price moves follow_atr*ATR in the breakout direction;
    follow-through = the opposite order. Measured on closed bars after the event (declared horizon), no orders."""
    e = run(bars, cfg, point, tf_s)
    idx = {float(t): i for i, t in enumerate(bars.t)}
    res = {"follow": 0, "false": 0, "open": 0, "bars_to_follow": []}
    for ev in e.events:
        i = idx[ev["bar_ts"]]
        atr = e.atr[i]
        s = 1 if ev["direction"] == "BULLISH" else -1
        out = "open"
        for k in range(i + 1, min(len(bars.t), i + 1 + horizon)):
            fav = (bars.h[k] - ev["close"]) if s > 0 else (ev["close"] - bars.l[k])
            back = bars.c[k] < ev["zone_upper"] if s > 0 else bars.c[k] > ev["zone_lower"]
            if fav >= follow_atr * atr:
                out = "follow"
                res["bars_to_follow"].append(k - i)
                break
            if back:
                out = "false"
                break
        res[out] += 1
    zs = e.zones
    return {"config": asdict(cfg), "bars": int(len(bars.t)), "swings": len(e.swings), "zones_total": e.n_zone,
            "qualified_ever": e.n_qualified, "zones_retained": len(zs),
            "accepted": len(e.events), "rejected": len(e.rejected),
            "rejected_by_reason": {r: sum(1 for x in e.rejected if x["filter_status"] == r) for r in ("FILTER_REJECTED", "FILTER_NOT_READY")},
            "follow_through": res["follow"], "false_breakout": res["false"], "unresolved": res["open"],
            "false_rate": res["false"] / max(1, res["follow"] + res["false"]),
            "median_bars_to_follow": float(np.median(res["bars_to_follow"])) if res["bars_to_follow"] else None,
            "horizon_bars": horizon, "follow_atr": follow_atr, "panel": e.panel()}
