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
        ts = [_ts(b["open_utc"]) for b in bs]
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


def _regime(m5: list[dict], tick: float) -> dict:
    from ..lab import market_v2 as MV
    if len(m5) < 120:
        return {"status": "WARMUP"}
    r = MV.regime_series(m5[-400:], "M5", tick, tf_s=300, keep=3)
    cur = (r.get("series") or [{}])[-1]
    return {"status": "OK", "state": cur.get("state"), "strength": cur.get("strength"), "volatility": cur.get("volatility")}


def _context_ind(m5: list[dict], m1: list[dict], tick: float) -> dict:
    from ..lab.context_ind import fractal as FD
    from ..lab.context_ind import smc as SM
    from ..lab.context_ind import vamd as VM
    out = {}
    v5 = [x for x in VM.series(m5[-300:]) if x.get("status") == "READY"]
    v1 = [x for x in VM.series(m1[-300:]) if x.get("status") == "READY"]
    out["vamd_m5"] = v5[-1]["y"] if v5 else None
    out["vamd_m1"] = v1[-1]["y"] if v1 else None
    f = [x for x in FD.series(m5[-200:]) if x.get("zone")]
    out["fd_zone_m5"] = f[-1]["zone"] if f else None
    s = SM.run(m5[-400:], 300, tick=tick)
    out["smc_trend_m5"] = s.trend
    out["smc_high_m5"] = s.slot["H"].get("level") if s.slot["H"].get("status") == "ACTIVE" else None
    out["smc_low_m5"] = s.slot["L"].get("level") if s.slot["L"].get("status") == "ACTIVE" else None
    pb = s.pb.ledger
    out["pb_last_low_m5"] = next((x["price"] for x in reversed(pb) if x["side"] == "L"), None)
    out["pb_last_high_m5"] = next((x["price"] for x in reversed(pb) if x["side"] == "H"), None)
    s1 = SM.run(m1[-240:], 60, tick=tick)
    ev1 = [e for e in s1.events if e["kind"].startswith(("BOS", "CHOCH"))]
    out["smc_trend_m1"] = s1.trend
    out["smc_last_m1"] = {"kind": ev1[-1]["kind"], "bars_ago": len(s1.bars) - 1 - ev1[-1]["bar"]} if ev1 else None
    out["status"] = "OK" if (v5 and f) else "WARMUP"
    return out


def _candle(bars: list[dict], tf: str, tick: float) -> dict:
    from ..analysis import sci2
    if len(bars) < 30:
        return {"status": "WARMUP"}
    b = bars[-120:]
    r = sci2.read([x["open_utc"] for x in b], [x["o"] for x in b], [x["h"] for x in b], [x["l"] for x in b], [x["c"] for x in b], tf, tick=tick)
    return {"status": "OK", "role": r.get("role"), "direction": r.get("role_direction"), "reasons": r.get("reason_codes")}


def snapshot(bars: dict, quote: dict | None, *, tick: float, now: float | None = None, cfg: dict | None = None) -> dict:
    now = time.time() if now is None else now
    cfg = cfg or {}
    cfg = {"max_bar_age_s": {"M1": 180, "M5": 600, "M15": 1800, "H1": 7200}, "max_quote_age_s": 10.0, **cfg}
    m1, m5 = bars.get("M1") or [], bars.get("M5") or []
    snap = {"computed_at": now, "data": data_quality(bars, quote, now, cfg)}

    def guard(name, fn):
        try:
            snap[name] = fn()
        except Exception as exc:  # noqa: BLE001 - one broken component must not hide the others
            snap[name] = {"status": "ERROR", "reason": f"{type(exc).__name__}: {exc}"[:200]}
    guard("vol", lambda: {"status": "OK" if _atr(m5) else "WARMUP", "atr_m1": _atr(m1), "atr_m5": _atr(m5)})
    guard("regime", lambda: _regime(m5, tick))
    for tf in ("M5", "M15", "H1"):
        guard(f"structure_{tf}", lambda tf=tf: _structure(bars.get(tf) or [], tick))
    guard("ctx", lambda: _context_ind(m5, m1, tick))
    guard("candle_m1", lambda: _candle(m1, "M1", tick))
    guard("candle_m5", lambda: _candle(m5, "M5", tick))
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
