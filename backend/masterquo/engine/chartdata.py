"""Chart series and overlays derived from closed bars only.

Indicator lines use the *same* functions and per-timeframe profile as M02I
(M02I_PROFILE_MT5_TIMEFRAMES_v1.1: EMA with SMA seed, Wilder RSI/ATR/ADX, MACD 12/26/9 with SMA
signal line). Panels that the profile does not enable for a timeframe (e.g. MACD on M1, RSI on M1)
are computed with the H1/M15 parameters and flagged `visual_only=true` - they are drawn for the
user and are NOT inputs of any strategy rule.
Overlays (BOS/CHoCH/MSS, FVG, OB candidates, sweeps, liquidity levels, swing pivots) are copied
from the M03/M02 outputs with their confirmation timestamps.
"""
from __future__ import annotations

from .legacy import modules

DEFAULT_RSI = 14
DEFAULT_MACD = {"fast": 12, "slow": 26, "signal": 9, "signal_ma": "SMA"}


def indicator_series(tf: str, closed: list[dict], tf_profile: dict) -> dict:
    m = modules()["m02i"]
    closes = [b["c"] for b in closed]
    times = [b["open_utc"] for b in closed]
    enabled = (tf_profile or {}).get("enabled", {})
    out: dict = {"tf": tf, "role": (tf_profile or {}).get("role"), "lines": [], "panels": {}}

    def pts(vals):
        return [{"time": t, "value": round(v, 5)} for t, v in zip(times, vals) if v is not None]

    for n in enabled.get("ema", []):
        out["lines"].append({"id": f"EMA{n}", "label": f"EMA {n}", "points": pts(m.ema(closes, n)), "visual_only": False})
    bb = enabled.get("bollinger")
    if bb:
        mids, ups, los = [], [], []
        p, k = bb["period"], bb["std_mult"]
        for i in range(len(closes)):
            if i + 1 < p:
                mids.append(None); ups.append(None); los.append(None)
                continue
            r = m.bb(closes[: i + 1], p, k)
            mids.append(r["mid"]); ups.append(r["upper"]); los.append(r["lower"])
        out["lines"] += [{"id": "BB_U", "label": "BB górna", "points": pts(ups), "visual_only": False},
                         {"id": "BB_L", "label": "BB dolna", "points": pts(los), "visual_only": False}]
    rsi_n = enabled.get("rsi")
    rsi_visual = rsi_n is None
    out["panels"]["rsi"] = {"period": rsi_n or DEFAULT_RSI, "visual_only": rsi_visual,
                            "points": pts(m.rsi(closes, rsi_n or DEFAULT_RSI))}
    mc = enabled.get("macd")
    mcfg = mc or DEFAULT_MACD
    md = m.macd(closes, mcfg["fast"], mcfg["slow"], mcfg["signal"], mcfg.get("signal_ma", "SMA"))
    out["panels"]["macd"] = {"params": mcfg, "visual_only": mc is None, "signal_ma": mcfg.get("signal_ma", "SMA"),
                             "line": pts(md["line"]), "signal": pts(md["signal"]), "histogram": pts(md["histogram"])}
    atr = m.atr([{"high": b["h"], "low": b["l"], "close": b["c"]} for b in closed], 14) if closed else []
    out["atr14"] = next((round(v, 5) for v in reversed(atr) if v is not None), None)
    return out


def overlays(tf: str, m03_tf: dict | None, m02_tf: dict | None, limit: int = 12) -> dict:
    m03_tf = m03_tf or {}
    m02_tf = m02_tf or {}
    breaks = [{"kind": b["kind"], "direction": b["direction"], "level": b["break_level"], "bar_open_utc": b["bar_open_utc"],
               "observed_at": b["observed_at"], "reference_pivot_time": b["reference_pivot_time"],
               "displacement": b["displacement_confirmed"], "id": b["event_id"]} for b in (m03_tf.get("breaks") or [])][-limit:]
    fvgs = [{"direction": f["direction"], "low": f["zone_low"], "high": f["zone_high"], "formed_at": f["formed_at"],
             "status": f["status"], "mitigated": round(f["mitigated_fraction"], 3), "age_bars": f["age_closed_bars"], "id": f["event_id"]}
            for f in (m03_tf.get("fvgs") or []) if f.get("status") != "FILLED"][-limit:]
    obs = [{"direction": o["direction"], "low": o["zone_low"], "high": o["zone_high"], "origin_bar": o["origin_bar"],
            "confirmed_at": o["confirmed_at"], "id": o["event_id"]} for o in (m03_tf.get("order_blocks") or [])][-6:]
    sweeps = [{"side": s["liquidity_side"], "level": s["reference_level"], "observed_at": s["observed_at"], "id": s["event_id"]}
              for s in (m03_tf.get("sweeps") or [])][-limit:]
    levels = [{"side": lv["liquidity_side"], "level": lv["reference_level"], "pivot_time": lv["pivot_time"],
               "available_at": lv["available_at"], "id": lv["event_id"]} for lv in (m03_tf.get("liquidity_levels") or [])][-limit:]
    sw = m02_tf.get("swings") or {}
    pivots = ([{"type": "H", "price": p["price"], "time": p["pivot_time"], "available_at": p["available_at"]} for p in sw.get("highs", [])][-limit:] +
              [{"type": "L", "price": p["price"], "time": p["pivot_time"], "available_at": p["available_at"]} for p in sw.get("lows", [])][-limit:])
    return {"breaks": breaks, "fvgs": fvgs, "order_blocks": obs, "sweeps": sweeps, "liquidity_levels": levels,
            "pivots": pivots, "premium_discount": m03_tf.get("premium_discount"),
            "regime": m02_tf.get("structure_regime"), "direction": m02_tf.get("direction"), "status": m03_tf.get("status")}
