"""Shared analysis snapshot for SCALPING / HEDGING. Computed from CLOSED bars only (the forming bar is never read) and the
current Bid/Ask, with a freshness stamp per component. Every component reports status OK / WARMUP / MISSING / ERROR and its
reason, so a missing input becomes an explicit WAIT reason, never a silent default.

Components: data quality, volatility (ATR M1/M5), regime (MQ_REGIME_MULTI_V2 on M5 + bounded Katz FD), structure per TF
(structure_v2 internal/major), SMC/pullback (M5), VAMD momentum (M1, M5), candle role of the last closed M1/M5 bar (sci2),
nearest obstacles (swings, active SMC levels) above/below the price.
"""
from __future__ import annotations

import math
import time
from datetime import datetime

TF_S = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600}


def _ts(x) -> float:
    return float(x) if isinstance(x, (int, float)) else datetime.fromisoformat(str(x).replace("Z", "+00:00")).timestamp()


def _atr(bars: list[dict], n: int = 14) -> float | None:
    if len(bars) < n + 1:
        return None
    trs = []
    for i in range(1, len(bars)):
        h, lo, pc = bars[i]["h"], bars[i]["l"], bars[i - 1]["c"]
        trs.append(max(h - lo, abs(h - pc), abs(lo - pc)))
    a = sum(trs[:n]) / n
    for tr in trs[n:]:
        a = (a * (n - 1) + tr) / n                                   # Wilder
    return a


def data_quality(bars: dict, quote: dict | None, now: float, cfg: dict) -> dict:
    """Ordered, finite, de-duplicated closed bars; fresh last bar per TF; fresh quote; spread within the limit."""
    issues, ages = [], {}
    for tf, bs in bars.items():
        if not bs:
            issues.append(f"{tf}: brak świec")
            continue
        ts = [_ts(b["open_utc"]) for b in bs[-60:]]                  # ordering/duplicates of the recent window (the analysed part)
        if any(b2 <= b1 for b1, b2 in zip(ts, ts[1:])):
            issues.append(f"{tf}: świece nieuporządkowane lub zdublowane")
        if any(not all(math.isfinite(float(b[k])) for k in ("o", "h", "l", "c")) or b["h"] < b["l"] for b in bs[-50:]):
            issues.append(f"{tf}: NaN/inf lub błędna geometria")
        close_t = ts[-1] + TF_S.get(tf, 60)
        ages[tf] = round(now - close_t, 1)
        if close_t > now + 1:
            issues.append(f"{tf}: ostatnia świeca nie jest zamknięta (forming) – odrzucona")
        elif now - close_t > cfg["max_bar_age_s"].get(tf, 3 * TF_S.get(tf, 60)):
            issues.append(f"{tf}: dane nieaktualne ({now - close_t:.0f} s od zamknięcia)")
    q_age = None
    spread = None
    if not quote:
        issues.append("brak notowania Bid/Ask")
    else:
        q_age = round(now - float(quote.get("time") or now), 2)
        spread = float(quote["ask"]) - float(quote["bid"])
        if q_age > cfg["max_quote_age_s"]:
            issues.append(f"notowanie nieaktualne ({q_age:.1f} s)")
        if spread < 0:
            issues.append("Ask < Bid")
        elif cfg.get("max_spread_usd") is not None and spread > cfg["max_spread_usd"]:
            issues.append(f"spread {spread:.3f} > limit {cfg['max_spread_usd']:.3f} USD")
    return {"status": "OK" if not issues else "BLOCK", "issues": issues, "bar_age_s": ages, "quote_age_s": q_age, "spread": spread}


def _structure(bars: list[dict], tick: float) -> dict:
    from ..analysis import structure_v2 as S
    if len(bars) < 30:
        return {"status": "WARMUP"}
    r = S.analyse([b["open_utc"] for b in bars], [b["h"] for b in bars], [b["l"] for b in bars], [b["c"] for b in bars], tick=tick)
    lay = r["layers"]
    sw = lay["internal"]["swings"]
    return {"status": "OK", "internal": lay["internal"]["trend"], "major": lay["major"]["trend"],
            "last_high": next((x["price"] for x in reversed(sw) if x["kind"] == "H"), None),
            "last_low": next((x["price"] for x in reversed(sw) if x["kind"] == "L"), None),
            "highs": [x["price"] for x in sw if x["kind"] == "H"][-6:], "lows": [x["price"] for x in sw if x["kind"] == "L"][-6:],
            "last_event": (r["events"] or [None])[-1]}


class IncRegime:
    """MQ_REGIME_MULTI_V2 on closed M5 bars fed ONE bar at a time with exactly the per-bar step of market_v2.regime_series (same
    RegimeMachine, MarketBehavior, ATR14 rolling mean, volatility axis) - O(1) per bar instead of re-running 400 bars at every
    close. The hysteresis state is path dependent: live and replay both start from the window available at their first call."""

    def __init__(self, tick: float):
        from ..lab import market_v2 as MV
        self.MV = MV
        self.rm = MV.RegimeMachine(None, tick)
        self.mb = MV.MarketBehavior("M5", 300, tick=tick)
        self.c, self.h, self.l, self.tr, self.atr_rel = [], [], [], [], []
        self.last_bias = "UNKNOWN"
        self.last_t = None
        self.view = None
        self.n = 0

    def feed(self, b: dict) -> None:
        t = _ts(b["open_utc"])
        if self.last_t is not None and t <= self.last_t:
            return
        self.last_t = t
        h, lo, c = float(b["h"]), float(b["l"]), float(b["c"])
        self.tr.append(h - lo if not self.c else max(h - lo, abs(h - self.c[-1]), abs(lo - self.c[-1])))
        self.c.append(c)
        i = self.n
        self.n += 1
        atr = sum(self.tr[-14:]) / 14 if i >= 14 else None
        self.atr_rel.append(atr / c if atr else float("nan"))
        self.mb.update({"open_utc": b["open_utc"], "h": h, "l": lo, "c": c, "o": b.get("o", c)})
        bias = self.mb.bias_at(i)
        opp = self.last_bias in ("UP", "DOWN") and bias in ("UP", "DOWN") and bias != self.last_bias
        self.last_bias = bias if bias in ("UP", "DOWN") else self.last_bias
        cf = self.rm.cfg
        import numpy as np
        ar = np.array(self.atr_rel[-(cf["vol_window"] + 1):], dtype=float)
        self.view = self.rm.step(str(b["open_utc"]), np.array(self.c[-400:], dtype=float), atr, bias, opp,
                                 self.MV.vol_axis(ar, len(ar) - 1, cf["vol_window"], cf["vol_min"], cf["vol_lo"], cf["vol_hi"]))
        if len(self.c) > 2000:                              # bounded memory; windows use at most the last 400 values
            del self.c[:1000], self.tr[:1000], self.atr_rel[:1000]

    def public(self) -> dict:
        v = self.view or {}
        st = v.get("state")
        if not st or st == "WARMING_UP" or self.n < 120:
            return {"status": "WARMUP", "state": None}
        return {"status": "OK", "state": st, "strength": v.get("strength"), "volatility": (v.get("volatility") or {}).get("state"),
                "candidate": v.get("candidate"), "bars_fed": self.n}


def _regime(m5: list[dict], tick: float, cache: dict | None = None) -> dict:
    """Incremental when the caller keeps a cache (live service, replay); otherwise a fresh machine over the window."""
    if len(m5) < 120:
        return {"status": "WARMUP"}
    inc = (cache or {}).get("regime_inc")
    if inc is None or (inc.last_t is not None and _ts(m5[-1]["open_utc"]) < inc.last_t):
        inc = IncRegime(tick)
        for b in m5[-400:]:
            inc.feed(b)
    else:
        lt = inc.last_t
        for b in m5[-400:]:
            if lt is None or _ts(b["open_utc"]) > lt:
                inc.feed(b)
    if cache is not None:
        cache["regime_inc"] = inc
    return inc.public()


def _ctx_m5(m5: list[dict], tick: float) -> dict:
    from ..lab.context_ind import fractal as FD
    from ..lab.context_ind import smc as SM
    from ..lab.context_ind import vamd as VM
    out = {}
    v5 = [x for x in VM.series(m5[-300:]) if x.get("status") == "READY"]
    out["vamd_m5"] = v5[-1]["y"] if v5 else None
    f = [x for x in FD.series(m5[-200:]) if x.get("zone")]
    out["fd_zone_m5"] = f[-1]["zone"] if f else None
    s = SM.run(m5[-400:], 300, tick=tick)
    out["smc_trend_m5"] = s.trend
    out["smc_high_m5"] = s.slot["H"].get("level") if s.slot["H"].get("status") == "ACTIVE" else None
    out["smc_low_m5"] = s.slot["L"].get("level") if s.slot["L"].get("status") == "ACTIVE" else None
    pb = s.pb.ledger
    out["pb_last_low_m5"] = next((x["price"] for x in reversed(pb) if x["side"] == "L"), None)
    out["pb_last_high_m5"] = next((x["price"] for x in reversed(pb) if x["side"] == "H"), None)
    out["status"] = "OK" if (v5 and f) else "WARMUP"
    return out


def _ctx_m1(m1: list[dict], tick: float) -> dict:
    from ..lab.context_ind import smc as SM
    from ..lab.context_ind import vamd as VM
    v1 = [x for x in VM.series(m1[-300:]) if x.get("status") == "READY"]
    s1 = SM.run(m1[-240:], 60, tick=tick)
    ev1 = [e for e in s1.events if e["kind"].startswith(("BOS", "CHOCH"))]
    return {"vamd_m1": v1[-1]["y"] if v1 else None, "smc_trend_m1": s1.trend,
            "smc_last_m1": {"kind": ev1[-1]["kind"], "bars_ago": len(s1.bars) - 1 - ev1[-1]["bar"]} if ev1 else None}


def _candle(bars: list[dict], tf: str, tick: float) -> dict:
    from ..analysis import sci2
    if len(bars) < 30:
        return {"status": "WARMUP"}
    b = bars[-120:]
    r = sci2.read([x["open_utc"] for x in b], [x["o"] for x in b], [x["h"] for x in b], [x["l"] for x in b], [x["c"] for x in b], tf, tick=tick)
    return {"status": "OK", "role": r.get("role"), "direction": r.get("role_direction"), "reasons": r.get("reason_codes")}


HEAVY = ("regime", "structure_M5", "structure_M15", "structure_H1", "ctx_m5", "candle_m5", "atr_m5")


def snapshot(bars: dict, quote: dict | None, *, tick: float, now: float | None = None, cfg: dict | None = None,
             cache: dict | None = None) -> dict:
    """`cache` (optional, owned by the caller): the M5/M15/H1 components are recomputed only when a NEW closed M5 bar exists;
    the M1 components and data quality are computed on every call. Live and replay use the same code and the same caching."""
    now = time.time() if now is None else now
    cfg = cfg or {}
    cfg = {"max_bar_age_s": {"M1": 180, "M5": 600, "M15": 1800, "H1": 7200}, "max_quote_age_s": 10.0, **cfg}
    m1, m5 = bars.get("M1") or [], bars.get("M5") or []
    snap = {"computed_at": now, "data": data_quality(bars, quote, now, cfg)}

    def guard(fn):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - one broken component must not hide the others
            return {"status": "ERROR", "reason": f"{type(exc).__name__}: {exc}"[:200]}
    key = (m5[-1]["open_utc"] if m5 else None, (bars.get("M15") or [{}])[-1].get("open_utc"), (bars.get("H1") or [{}])[-1].get("open_utc"))
    heavy = cache.get("heavy") if cache is not None and cache.get("key") == key else None
    if heavy is None:
        heavy = {"regime": guard(lambda: _regime(m5, tick, cache)), "ctx_m5": guard(lambda: _ctx_m5(m5, tick)),
                 "candle_m5": guard(lambda: _candle(m5, "M5", tick)), "atr_m5": _atr(m5)}
        for tf in ("M5", "M15", "H1"):
            heavy[f"structure_{tf}"] = guard(lambda tf=tf: _structure(bars.get(tf) or [], tick))
        if cache is not None:
            cache.update(key=key, heavy=heavy)
    a1 = _atr(m1)
    snap["vol"] = {"status": "OK" if heavy["atr_m5"] else "WARMUP", "atr_m1": a1, "atr_m5": heavy["atr_m5"]}
    snap["regime"] = heavy["regime"]
    for tf in ("M5", "M15", "H1"):
        snap[f"structure_{tf}"] = heavy[f"structure_{tf}"]
    c1 = guard(lambda: _ctx_m1(m1, tick))
    c5 = heavy["ctx_m5"]
    snap["ctx"] = {**c5, **{k: v for k, v in c1.items() if k != "status"}}
    if c1.get("status") == "ERROR":
        snap["ctx"]["status"] = "ERROR"
        snap["ctx"]["reason_m1"] = c1.get("reason")
    snap["candle_m1"] = guard(lambda: _candle(m1, "M1", tick))
    snap["candle_m5"] = heavy["candle_m5"]
    snap["price"] = {"bid": quote["bid"], "ask": quote["ask"]} if quote else None
    snap["last_close_m1"] = m1[-1]["c"] if m1 else None
    return snap


def obstacles(snap: dict, side: str, ref: float) -> list[dict]:
    """Known levels between the entry and the targets in the trade direction (swing highs/lows, active SMC levels)."""
    lv = []
    for tf in ("M5", "M15", "H1"):
        s = snap.get(f"structure_{tf}") or {}
        for p in (s.get("highs") if side == "BUY" else s.get("lows")) or []:
            lv.append({"price": p, "source": f"swing {tf}"})
    c = snap.get("ctx") or {}
    p = c.get("smc_high_m5") if side == "BUY" else c.get("smc_low_m5")
    if p:
        lv.append({"price": p, "source": "SMC aktywny poziom M5"})
    ahead = [x for x in lv if (x["price"] > ref if side == "BUY" else x["price"] < ref)]
    return sorted(ahead, key=lambda x: abs(x["price"] - ref))
