"""Anchored VWAP (PMW-IND-AVWAP-1): one engine, three anchor modes.

  SESSION  start of the chosen session window (analytics.session_engine: IANA zones, DST) - known at the window start.
  EVENT    the last CONFIRMED BOS / CHoCH / sweep of the structure engine (lab.context_ind.smc, closed-bar, append-only events).
           source_time = open of the bar where the move started (the opposite structure point for BOS/CHoCH, the wick bar of a sweep);
           confirmed_at = close of the bar that confirmed the event. Before confirmed_at the anchor does not exist (replay-safe); after it
           the line may be drawn back from source_time.
  MANUAL   a user anchor picked on the chart; known from its created_at.

AVWAP_t = sum(p_i * w_i) / sum(w_i) over closed bars from the anchor bar to t; sigma_t = sqrt(sum(w_i (p_i - AVWAP_t)^2) / sum(w_i));
bands AVWAP +/- 1 sigma / 2 sigma. Bands are a weighted dispersion of prices, NOT probability intervals.
Price: TYPICAL = (H + L + C) / 3 (default for OHLC) or CLOSE. Weights: EXCHANGE_VOLUME (real_volume) when the feed has it, else
TICK_VOLUME = number of quote updates (activity proxy). One source per line - never mixed; a bar without the chosen weight weighs 0.
No positive weight / no bar after the anchor = not ready.

Events (definition v1): CROSS_UP / CROSS_DOWN - close on the other side of the line than the previous close (each vs its own line value);
RETEST_UP - after a CROSS_UP, a later bar whose low comes within tol x ATR of the line and closes above it (mirror: RETEST_DOWN).
"""
from __future__ import annotations

import hashlib
import math

from . import contract as C

VERSION = "PMW-IND-AVWAP-1"
UNITS = {"avwap": "price", "sigma": "price", "upper1": "price", "lower1": "price", "upper2": "price", "lower2": "price",
         "distance_atr": "atr", "distance_sigma": "sigma", "slope_per_bar": "price_per_bar", "slope_atr": "atr_per_bar",
         "anchor_age_bars": "bars", "anchor_age_s": "seconds"}


class Accumulator:
    """Incremental AVWAP state - add() bar by bar gives exactly the full-recompute value (same sums)."""
    __slots__ = ("sw", "swp", "swp2", "n", "zero")

    def __init__(self):
        self.sw = self.swp = self.swp2 = 0.0
        self.n = self.zero = 0

    def add(self, price: float, weight: float) -> None:
        self.n += 1
        if not (weight > 0) or not math.isfinite(weight):
            self.zero += 1
            return
        self.sw += weight
        self.swp += price * weight
        self.swp2 += price * price * weight

    def value(self) -> tuple[float | None, float | None]:
        if self.sw <= 0:
            return None, None
        m = self.swp / self.sw
        var = max(0.0, self.swp2 / self.sw - m * m)
        return m, math.sqrt(var)


def weight_source(bars: list[dict]) -> str:
    n = len(bars)
    if n and sum(1 for b in bars if (b.get("rv") or 0) > 0) >= 0.5 * n:
        return "EXCHANGE_VOLUME"
    if n and sum(1 for b in bars if (b.get("tv") or 0) > 0) >= 0.5 * n:
        return "TICK_VOLUME"
    return "NONE"


def _price(b: dict, mode: str) -> float:
    return float(b["c"]) if mode == "CLOSE" else (float(b["h"]) + float(b["l"]) + float(b["c"])) / 3.0


def _weight(b: dict, src: str) -> float:
    return float(b.get("rv") or 0) if src == "EXCHANGE_VOLUME" else float(b.get("tv") or 0) if src == "TICK_VOLUME" else 0.0


def _closed(bars: list[dict], tf_s: int, as_of: float | None) -> list[dict]:
    out = []
    for b in bars or []:
        if b.get("closed") is False or not b.get("open_utc"):
            continue
        if as_of is not None and C.ts(b["open_utc"]) + tf_s > as_of + 1e-6:
            continue
        out.append(b)
    return out


def atr(bars: list[dict], n: int = 14) -> float | None:
    if len(bars) < n + 1:
        return None
    trs = []
    for i in range(len(bars) - n, len(bars)):
        h, lo, pc = float(bars[i]["h"]), float(bars[i]["l"]), float(bars[i - 1]["c"])
        trs.append(max(h - lo, abs(h - pc), abs(lo - pc)))
    return sum(trs) / n


def line(bars: list[dict], anchor_t: float, *, price_mode: str = "TYPICAL", src: str | None = None) -> tuple[list[dict], str, int]:
    """Per-bar AVWAP / bands from the anchor bar (open >= anchor_t). Returns (points, weight source, zero-weight bars)."""
    seq = [b for b in bars if C.ts(b["open_utc"]) >= anchor_t - 1e-6]
    src = src or weight_source(seq)
    acc = Accumulator()
    pts = []
    for b in seq:
        acc.add(_price(b, price_mode), _weight(b, src))
        m, sd = acc.value()
        pts.append({"t": b["open_utc"], "avwap": m, "sigma": sd, "close": float(b["c"]), "high": float(b["h"]), "low": float(b["l"])})
    return pts, src, acc.zero


def events(pts: list[dict], atr_v: float | None, tol_atr: float = 0.1) -> list[dict]:
    out, last_cross = [], None
    tol = (atr_v or 0.0) * tol_atr
    for i in range(1, len(pts)):
        a, b = pts[i - 1], pts[i]
        if a["avwap"] is None or b["avwap"] is None:
            continue
        if a["close"] <= a["avwap"] and b["close"] > b["avwap"]:
            last_cross = "UP"
            out.append({"kind": "CROSS_UP", "t": b["t"], "price": b["avwap"]})
        elif a["close"] >= a["avwap"] and b["close"] < b["avwap"]:
            last_cross = "DOWN"
            out.append({"kind": "CROSS_DOWN", "t": b["t"], "price": b["avwap"]})
        elif last_cross == "UP" and b["low"] <= b["avwap"] + tol and b["close"] > b["avwap"]:
            out.append({"kind": "RETEST_UP", "t": b["t"], "price": b["avwap"]})
            last_cross = "UP_RETESTED"
        elif last_cross == "DOWN" and b["high"] >= b["avwap"] - tol and b["close"] < b["avwap"]:
            out.append({"kind": "RETEST_DOWN", "t": b["t"], "price": b["avwap"]})
            last_cross = "DOWN_RETESTED"
    return out


# ------------------------------------------------------------------ anchors
def anchor_id(mode: str, kind: str, source_time, confirmed_at) -> str:
    return "ANC-" + hashlib.sha256(f"{mode}|{kind}|{C.iso(C.ts(source_time))}|{C.iso(C.ts(confirmed_at))}".encode()).hexdigest()[:12]


def session_anchor(profile_id: str, as_of: float, session: str | None = None) -> dict | None:
    from ..analytics import session_engine as SE
    ws = [w for w in SE.windows(profile_id, as_of, 2, 0) if w["start"].timestamp() <= as_of and (session in (None, "CURRENT") or w["session"] == session)]
    if not ws:
        return None
    w = max(ws, key=lambda x: x["start"])
    t = w["start"].timestamp()
    return {"mode": "SESSION", "kind": w["session"], "source_time": C.iso(t), "confirmed_at": C.iso(t), "profile_id": profile_id,
            "session_local": w["local_hours"], "anchor_id": anchor_id("SESSION", w["session"], t, t)}


def event_anchor(bars: list[dict], tf_s: int, as_of: float, *, tick: float = 0.01, kinds=("BOS", "CHOCH", "X_")) -> dict | None:
    """Last confirmed structure event known at as_of (events of bars closed <= as_of only)."""
    from ..lab.context_ind import smc as SM
    seq = _closed(bars, tf_s, as_of)
    if len(seq) < 10:
        return None
    s = SM.run(seq, tf_s, tick=tick)
    evs = [e for e in s.events if e["kind"].startswith(tuple(kinds)) and e["available_at"] <= as_of + 1e-6]
    if not evs:
        return None
    e = evs[-1]
    if e["kind"].startswith("X_"):
        src_bar = e.get("wick_bar", e["bar"])
    else:
        opp = "L" if e["kind"].endswith("UP") else "H"
        pts = [x for x in s.events if x["kind"] == "STRUCTURE_" + opp and x["seq"] < e["seq"]]
        src_bar = pts[-1]["origin_bar"] if pts else e["bar"]
    src_bar = max(0, min(int(src_bar), len(seq) - 1))
    st = C.ts(seq[src_bar]["open_utc"])
    return {"mode": "EVENT", "kind": e["kind"], "source_time": C.iso(st), "confirmed_at": C.iso(e["available_at"]), "event_id": e["event_id"],
            "level": e.get("level"), "anchor_id": anchor_id("EVENT", e["kind"], st, e["available_at"])}


def manual_anchor(source_time, created_at, label: str | None = None) -> dict:
    return {"mode": "MANUAL", "kind": label or "MANUAL", "source_time": C.iso(C.ts(source_time)), "confirmed_at": C.iso(C.ts(created_at)),
            "anchor_id": anchor_id("MANUAL", label or "MANUAL", source_time, created_at)}


# ------------------------------------------------------------------ result
def compute(bars: list[dict], tf: str, anchor: dict | None, *, as_of: float, instrument: str, broker_symbol: str | None = None,
            price_mode: str = "TYPICAL", slope_bars: int = 5, retest_tol_atr: float = 0.1, cfg: dict | None = None,
            instrument_meta: dict | None = None, with_line: bool = False, anchor_version: int = 1) -> dict:
    from ..timeutil import TF_SECONDS
    tf_s = TF_SECONDS[tf]
    cfgd = dict(cfg or {}, price_mode=price_mode, slope_bars=slope_bars, retest_tol_atr=retest_tol_atr, tf=tf)
    iid = f"AVWAP_{(anchor or {}).get('mode', 'NONE')}"
    base = dict(instrument=instrument, broker_symbol=broker_symbol, source="MT5_BARS", timeframe=tf, cfg=cfgd, instrument_meta=instrument_meta,
                units=UNITS)
    if anchor is None:
        return C.result(iid, VERSION, status="NO_DATA", reason="NO_ANCHOR", **base)
    if C.ts(anchor["confirmed_at"]) > as_of + 1e-6:
        return C.result(iid, VERSION, status="WARMUP", reason="ANCHOR_NOT_CONFIRMED_YET", extra={"anchor": anchor}, **base)
    seq = _closed(bars, tf_s, as_of)
    pts, src, zero = line(seq, C.ts(anchor["source_time"]), price_mode=price_mode)
    extra = {"anchor": dict(anchor, version=anchor_version), "price_mode": price_mode, "zero_weight_bars": zero,
             "volume_note": "tick_volume = liczba zmian kwotowania (proxy aktywności), nie wolumen transakcyjny" if src == "TICK_VOLUME" else None}
    if not pts:
        return C.result(iid, VERSION, status="WARMUP", reason="NO_BARS_AFTER_ANCHOR", volume_source=src, extra=extra, **base)
    last = pts[-1]
    if last["avwap"] is None:
        return C.result(iid, VERSION, status="NO_DATA", reason="NO_POSITIVE_WEIGHTS", volume_source=src, sample_count=len(pts), extra=extra,
                        data_time=last["t"], **base)
    a = atr(seq)
    m, sd, px = last["avwap"], last["sigma"], last["close"]
    k = min(slope_bars, len(pts) - 1)
    slope = (m - pts[-1 - k]["avwap"]) / k if k >= 1 and pts[-1 - k]["avwap"] is not None else None
    ev = events(pts, a, retest_tol_atr)
    vals = {"avwap": m, "sigma": sd, "upper1": m + sd, "lower1": m - sd, "upper2": m + 2 * sd, "lower2": m - 2 * sd, "close": px,
            "distance_atr": (px - m) / a if a else None, "distance_sigma": (px - m) / sd if sd and sd > 0 else None,
            "slope_per_bar": slope, "slope_atr": (slope / a) if (slope is not None and a) else None,
            "anchor_age_bars": len(pts), "anchor_age_s": as_of - C.ts(anchor["source_time"]),
            "side": "ABOVE" if px > m else "BELOW" if px < m else "AT", "last_event": ev[-1]["kind"] if ev else None,
            "last_event_at": ev[-1]["t"] if ev else None}
    extra["events"] = ev[-10:]
    if with_line:
        extra["line"] = [{"t": p["t"], "avwap": C.num(p["avwap"]), "upper1": C.num(p["avwap"] + p["sigma"]) if p["avwap"] is not None else None,
                          "lower1": C.num(p["avwap"] - p["sigma"]) if p["avwap"] is not None else None,
                          "upper2": C.num(p["avwap"] + 2 * p["sigma"]) if p["avwap"] is not None else None,
                          "lower2": C.num(p["avwap"] - 2 * p["sigma"]) if p["avwap"] is not None else None} for p in pts]
    avail = C.ts(last["t"]) + tf_s
    return C.result(iid, VERSION, values=vals, volume_source=src, sample_count=len(pts), data_time=last["t"], available_at=avail, extra=extra,
                    **base)
