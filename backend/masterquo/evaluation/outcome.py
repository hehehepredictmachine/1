"""Realised outcome of one assessed setup from CLOSED M1 bars (PMW-EVAL-OUTCOME-1).

Only bars that OPEN at or after the decision time and CLOSE by the end of the horizon are used; the bar that was forming at the
decision is skipped (its pre-decision part is unknown), so nothing after the horizon and nothing before the decision enters the label.
Prices: Bid chart OHLC. A LONG exits on the Bid (the bar itself); a SHORT exits on the Ask, approximated as bar + the spread seen at
the decision. Inside one bar the path is unknown: a bar that touches the SL and a not-yet-hit target is counted as SL first
(conservative) and reported in `ambiguous_bars`.
The plan result keeps the target weights (partials) but no BE move or trailing - the same BINARY_PLAN_APPROX as the EV, so the
two are comparable; it is not the result of a real fill.
"""
from __future__ import annotations

from datetime import datetime

M1 = 60.0


def bar_ts(b: dict) -> float:
    t = b.get("t")
    if t is not None:
        return float(t)
    return datetime.fromisoformat(str(b["open_utc"]).replace("Z", "+00:00")).timestamp()


def window(bars: list[dict], t0: float, t1: float) -> list[dict]:
    return [b for b in bars if bar_ts(b) >= t0 - 1e-6 and bar_ts(b) + M1 <= t1 + 1e-6]


def label(cand: dict, bars: list[dict], *, cost_r: float = 0.0) -> dict:
    """cand = SetupCandidate.to_dict(); bars = the closed M1 bars of the horizon window (see window())."""
    entry, sl = float(cand["entry_price"]), float(cand["stop_loss"])
    sgn = 1.0 if cand["direction"] == "LONG" else -1.0
    shift = float((cand.get("execution_context") or {}).get("spread") or 0.0) if sgn < 0 else 0.0
    r = abs(entry - sl)
    tg = [(float(t["price"]), float(t["weight"])) for t in cand["targets"]]
    dist = [abs(p - entry) for p, _ in tg]
    hit = [False] * len(tg)
    hit_at: list = [None] * len(tg)
    sl_at, mfe, mae, amb, last_close = None, 0.0, 0.0, 0, None
    for b in bars:
        hi, lo = float(b["h"]) + shift, float(b["l"]) + shift
        fav = (hi - entry) if sgn > 0 else (entry - lo)
        adv = (entry - lo) if sgn > 0 else (hi - entry)
        last_close = float(b["c"]) + shift
        new_tp = [i for i in range(len(tg)) if not hit[i] and fav >= dist[i] - 1e-12]
        sl_now = adv >= r - 1e-12
        if sl_now and new_tp:
            amb += 1
            new_tp = []                                     # SL first inside an ambiguous bar
        mae = max(mae, min(adv, r) if sl_now else adv)
        if not sl_now or new_tp:
            mfe = max(mfe, fav)
        for i in new_tp:
            hit[i], hit_at[i] = True, bar_ts(b)
        if sl_now:
            sl_at = bar_ts(b)
            break
        if all(hit):
            break
    done_w = sum(w for (_, w), h in zip(tg, hit) if h)
    gross = sum(w * d for (_, w), d, h in zip(tg, dist, hit) if h) / r if r > 0 else 0.0
    rest = max(0.0, 1.0 - done_w)
    if sl_at is not None:
        gross -= rest
        exit_kind = "SL"
    elif all(hit):
        exit_kind = "ALL_TARGETS"
    else:
        exit_kind = "TIMEOUT"
        if last_close is not None and r > 0:
            gross += rest * sgn * (last_close - entry) / r          # remainder marked at the last close of the horizon
    first = "SL" if sl_at is not None and not any(hit) else ("TP1" if hit and hit[0] else ("TIMEOUT" if not any(hit) else "TP"))
    t0 = float(cand["decision_ts"])
    if sl_at is not None:
        exit_at = sl_at + M1                                # exit inside that bar: its close bounds the holding time
    elif all(hit):
        exit_at = max(hit_at) + M1
    else:
        exit_at = bar_ts(bars[-1]) + M1 if bars else None
    return {"status": "MATURED" if bars else "NO_BARS", "bars_used": len(bars), "ambiguous_bars": amb, "exit": exit_kind,
            "first_event": first, "targets_hit": hit, "targets_hit_at": hit_at, "sl_hit_at": sl_at,
            "mfe_r": round(mfe / r, 4) if r > 0 else None, "mae_r": round(mae / r, 4) if r > 0 else None,
            "plan_r_gross": round(gross, 4), "plan_r_net": round(gross - cost_r, 4),
            "hold_s": round(exit_at - t0, 1) if exit_at is not None else None,
            "method": "M1 zamknięte w horyzoncie; świeca niejednoznaczna = SL pierwszy; bez BE (BINARY_PLAN_APPROX)"}


def event_hit(engine: str, out: dict) -> bool | None:
    """Did the event the probability refers to occur? SH: TP2 (second target, or the last one) before the SL. Scalp SHADOW:
    TP1 before the SL. S01-S12 legacy ML event: net R > 0 under the plan."""
    if out.get("status") != "MATURED":
        return None
    h = out["targets_hit"]
    if engine.startswith("SH_"):
        return bool(h[min(1, len(h) - 1)]) if h else None
    if engine == "SCALP_SHADOW":                                    # scalp model B event: TP1 before SL
        return bool(h[0]) if h else None
    return out["plan_r_net"] > 0
