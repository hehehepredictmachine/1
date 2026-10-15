"""Event-ordered replay of the scalp profile on closed M1 bars (Bid chart OHLC + per-bar spread) - research tool.

Order of events at a common close T: context TF (M15/M30) -> M5 (range) -> M1 (trigger). A plan emitted at the close of
the retest bar is filled at the OPEN of the next M1 (the first fresh quote after the close was known) - never at the
signal bar's close. BUY fills at Ask = bid open + spread + slippage; SELL at Bid - slippage. Exits: BUY compares
levels with Bid, SELL with Ask (= bid + spread of the bar). Costs: commission per side and adverse slippage per fill,
both in price units per unit of volume (commission cash / contract size); the spread is never subtracted twice.

OHLC ambiguity: without ticks the order of H/L inside one bar is unknown. If SL and a TP are both inside one bar the
conservative order (adverse extreme first) is used and the cycle is flagged `ambiguous`. Results are APPROXIMATE OHLC
replay, not a tick-exact backtest.

Outputs: cycles (task B labels: net R, TP1 before SL, MFE/MAE) and decision points of open positions with the outcome of
each frozen action HOLD / REDUCE / CLOSE / HEDGE_PARTIAL on the same subsequent path (task C labels).
"""
from __future__ import annotations

from . import strategy as st
from .strategy import V, iso_ts, ts

ACTIONS = ("HOLD", "REDUCE", "CLOSE", "HEDGE_PARTIAL")


def aggregate(m1: list[dict], minutes: int) -> list[dict]:
    """TF bars from COMPLETE buckets of M1 only (all `minutes` M1 present, no forward fill)."""
    buckets: dict[int, list[dict]] = {}
    for b in m1:
        t = ts(b["open_utc"])
        buckets.setdefault(t - t % (minutes * 60), []).append(b)
    out = []
    for k in sorted(buckets):
        bs = sorted(buckets[k], key=lambda x: ts(x["open_utc"]))
        if len(bs) != minutes:
            continue
        out.append({"open_utc": iso_ts(k), "o": bs[0]["o"], "h": max(x["h"] for x in bs), "l": min(x["l"] for x in bs), "c": bs[-1]["c"],
                    "tv": None if any(x.get("tv") is None for x in bs) else sum(x["tv"] for x in bs)})
    return out


class Path:
    def __init__(self, m1: list[dict], default_spread: float | None):
        self.t = [ts(b["open_utc"]) for b in m1]
        self.o = [float(b["o"]) for b in m1]
        self.h = [float(b["h"]) for b in m1]
        self.l = [float(b["l"]) for b in m1]
        self.c = [float(b["c"]) for b in m1]
        self.sp = [float(b["spread_price"]) if b.get("spread_price") is not None else default_spread for b in m1]
        self.index = {t: i for i, t in enumerate(self.t)}


def walk(P: Path, i0: int, sgn: int, vol: float, sl: float, tp1: float | None, tp2: float | None, f1: float, t_end: int,
         costs: dict, open_in_first_bar: bool = True, entry: float | None = None, be_offset: float | None = None,
         early: tuple[int, float] | None = None) -> dict:
    """Exit path of a position (volume `vol`) from bar i0. Returns exits [(vol, price, t, reason)], ambiguity, MFE/MAE in price.
    be_offset: after TP1 the stop moves to entry + be_offset (cost-adjusted BE) from the NEXT bar.
    early=(n, min_mfe): after n closed bars without TP1 and with MFE < min_mfe (price) the position exits at the close."""
    rem, exits, amb = vol, [], False
    new_sl = None
    tp1_left = tp1 is not None and f1 > 0
    slip = costs.get("slippage_price", 0.0)
    mfe = mae = 0.0
    entry_ref = None
    for i in range(i0, len(P.t)):
        sp = P.sp[i] or 0.0
        if sgn > 0:
            lo, hi, cl = P.l[i], P.h[i], P.c[i]
        else:
            lo, hi, cl = P.l[i] + sp, P.h[i] + sp, P.c[i] + sp
        if new_sl is not None:
            sl, new_sl = new_sl, None
        if entry_ref is None:
            entry_ref = entry if entry is not None else P.o[i] + (sp if sgn > 0 else 0.0)
        adverse, favor = (lo, hi) if sgn > 0 else (hi, lo)
        mfe = max(mfe, sgn * (favor - entry_ref))
        mae = max(mae, sgn * (entry_ref - adverse))
        sl_hit = (lo <= sl) if sgn > 0 else (hi >= sl)
        t1_hit = tp1_left and ((hi >= tp1) if sgn > 0 else (lo <= tp1))
        t2_hit = tp2 is not None and ((hi >= tp2) if sgn > 0 else (lo <= tp2))
        if sl_hit and (t1_hit or t2_hit):
            amb = True                                               # conservative: adverse extreme first
        if sl_hit:
            gap_px = P.o[i] + (0 if sgn > 0 else sp)
            px = min(sl, gap_px) if sgn > 0 else max(sl, gap_px)      # gap through the stop fills at the open
            exits.append((rem, px - sgn * slip, P.t[i] + 60, "BE" if tp1 is not None and not tp1_left and be_offset is not None else "SL"))
            return {"exits": exits, "ambiguous": amb, "mfe": mfe, "mae": mae, "end_i": i}
        if t1_hit:
            v1 = vol * f1 if tp2 is not None else rem
            exits.append((v1, tp1 - sgn * slip, P.t[i] + 60, "TP1"))
            rem -= v1
            tp1_left = False
            if be_offset is not None:
                new_sl = entry_ref + sgn * be_offset
            if rem <= 1e-12:
                return {"exits": exits, "ambiguous": amb, "mfe": mfe, "mae": mae, "end_i": i}
        if t2_hit and not tp1_left:
            exits.append((rem, tp2 - sgn * slip, P.t[i] + 60, "TP2"))
            return {"exits": exits, "ambiguous": amb, "mfe": mfe, "mae": mae, "end_i": i}
        if early and tp1_left and i - i0 + 1 >= early[0] and mfe < early[1]:
            exits.append((rem, cl - sgn * slip, P.t[i] + 60, "EARLY_NO_PROGRESS"))
            return {"exits": exits, "ambiguous": amb, "mfe": mfe, "mae": mae, "end_i": i}
        if P.t[i] + 60 >= t_end:
            exits.append((rem, cl - sgn * slip, P.t[i] + 60, "TIME"))
            return {"exits": exits, "ambiguous": amb, "mfe": mfe, "mae": mae, "end_i": i}
        if i + 1 < len(P.t) and P.t[i + 1] - P.t[i] > 60 * 15:
            exits.append((rem, cl - sgn * slip, P.t[i] + 60, "DATA_GAP_EXIT"))
            return {"exits": exits, "ambiguous": amb, "mfe": mfe, "mae": mae, "end_i": i}
    return {"exits": exits, "ambiguous": amb, "mfe": mfe, "mae": mae, "end_i": len(P.t) - 1, "open_at_end": rem}


def pnl(sgn: int, fill: float, vol: float, exits: list, costs: dict) -> float:
    """Net P&L in price units (per 1 unit of volume scale): legs at their fill/exit sides minus commission per side."""
    com = costs.get("commission_price_side", 0.0)
    return sum(sgn * (px - fill) * v for (v, px, _, _) in exits) - com * vol - com * sum(v for (v, *_rest) in exits)


def get_fill(plan: dict, P: Path, T: int, slip: float) -> dict:
    """Fill of a plan decided at T (close of the retest bar). MARKET: open of the next M1 (first fresh quote) with the chase
    limit. LIMIT_EDGE: limit at the zone edge, filled when the Ask (BUY) / Bid (SELL) reaches it within limit_wait_m1 bars."""
    sgn = 1 if plan["direction"] == "BUY" else -1
    i = P.index.get(T)
    if i is None:
        return {"ok": False, "reason": "MISSED_NO_FRESH_QUOTE"}
    if P.sp[i] is None:
        return {"ok": False, "reason": "SPREAD_UNKNOWN"}
    if plan.get("entry_mode") == "LIMIT_EDGE":
        lim = plan["limit_price"]
        for k in range(i, min(len(P.t), i + (plan.get("limit_wait_m1") or 3))):
            if k > i and P.t[k] - P.t[k - 1] != 60:
                break
            spk = P.sp[k] or 0.0
            if sgn > 0 and P.l[k] + spk <= lim:
                return {"ok": True, "i": k, "fill": min(lim, P.o[k] + spk), "spread": spk, "mode": "LIMIT"}
            if sgn < 0 and P.h[k] >= lim:
                return {"ok": True, "i": k, "fill": max(lim, P.o[k]), "spread": spk, "mode": "LIMIT"}
        return {"ok": False, "reason": "MISSED_LIMIT_NOT_FILLED"}
    sp = P.sp[i]
    fill = P.o[i] + (sp if sgn > 0 else 0.0) + sgn * slip
    ref_exec = plan["ref_close_bid"] + ((plan["spread_at_signal"] or sp) if sgn > 0 else 0.0)
    if sgn * (fill - ref_exec) > plan["chase_limit"]:
        return {"ok": False, "reason": "MISSED_CHASE_LIMIT"}
    return {"ok": True, "i": i, "fill": fill, "spread": sp, "mode": "MARKET"}


def exit_params(prof: dict, costs: dict, risk: float) -> dict:
    """Profile switches of the exit policy -> walk() arguments (BE after TP1, early no-progress exit)."""
    out = {}
    if V(prof, "exits", "be_after_tp1", default="NONE") == "COST_ADJUSTED":
        out["be_offset"] = 2 * costs.get("commission_price_side", 0.0) + 2 * costs.get("slippage_price", 0.0)
    n = V(prof, "exits", "early_exit_m1")
    if n:
        out["early"] = (int(n), (V(prof, "exits", "early_exit_min_mfe_r", default=0.3) or 0.0) * risk)
    return out


def run(m1: list[dict], prof: dict, tick: float, costs: dict, m5: list[dict] | None = None, m15: list[dict] | None = None,
        m30: list[dict] | None = None, decision_points: int = 10, margin_mode: str = "HEDGING", h1: list[dict] | None = None) -> dict:
    m1 = sorted(m1, key=lambda b: ts(b["open_utc"]))
    h1 = h1 if h1 is not None else aggregate(m1, 60)
    m5 = m5 if m5 is not None else aggregate(m1, 5)
    m15 = m15 if m15 is not None else aggregate(m1, 15)
    m30 = m30 if m30 is not None else aggregate(m1, 30)
    P = Path(m1, costs.get("default_spread_price"))
    mach = st.ScalpMachine(prof, tick)
    ev = []
    for tf, bars, pri in ((60, h1, 0), (30, m30, 0), (15, m15, 1), (5, m5, 2)):
        for b in bars:
            ev.append((ts(b["open_utc"]) + tf * 60, pri, tf, b))
    for b in m1:
        ev.append((ts(b["open_utc"]) + 60, 3, 1, b))
    ev.sort(key=lambda x: (x[0], x[1]))
    cycles, blocked, decisions = [], [], []
    busy_until = 0
    slip, hold = costs.get("slippage_price", 0.0), V(prof, "exits", "max_hold_minutes") * 60
    for T, _, tf, b in ev:
        if tf in (15, 30, 60):
            mach.add_context(tf, b)
            continue
        if tf == 5:
            mach.on_m5_close(b)
            continue
        for plan in mach.on_m1_close(b):
            sgn = 1 if plan["direction"] == "BUY" else -1
            blk, why = st.entry_filters(mach, plan, prof)
            rec = {"setup_id": plan["setup_id"], "direction": plan["direction"], "decision_time": plan["decision_time"]}
            if T < busy_until:
                blocked.append(dict(rec, reason="CYCLE_ACTIVE_OR_COOLDOWN"))
                mach.close_direction(plan["direction"], "BLOCKED", "aktywny cykl / cooldown", T)
                continue
            if blk is None or blk:
                blocked.append(dict(rec, reason=why))
                mach.close_direction(plan["direction"], "BLOCKED", why, T)
                continue
            fl = get_fill(plan, P, T, slip)
            if not fl["ok"]:
                blocked.append(dict(rec, reason=fl["reason"]))
                mach.close_direction(plan["direction"], "BLOCKED" if fl["reason"] == "SPREAD_UNKNOWN" else "MISSED", fl["reason"], T)
                continue
            i, fill, sp = fl["i"], fl["fill"], fl["spread"]
            extra = 2 * costs.get("commission_price_side", 0.0) + 2 * slip
            eco = st.economics(plan, fill, sp, extra, prof)
            if not eco["ok"]:
                blocked.append(dict(rec, reason="ECONOMICS: " + eco["reason"], economics=eco))
                mach.close_direction(plan["direction"], "BLOCKED", eco["reason"], T)
                continue
            f1 = V(prof, "exits", "tp1_fraction") if costs.get("split_allowed", True) else 1.0
            tp2 = plan["tp2"] if f1 < 1.0 else None
            res = walk(P, i, sgn, 1.0, plan["sl"], plan["tp1"], tp2, f1, P.t[i] + hold, costs, entry=fill,
                       **exit_params(prof, costs, eco["risk_per_unit"]))
            if res.get("open_at_end"):
                blocked.append(dict(rec, reason="DATA_END_OPEN"))
                continue
            risk = eco["risk_per_unit"]
            net = pnl(sgn, fill, 1.0, res["exits"], costs)
            first = res["exits"][0][3] if res["exits"] else None
            cyc = dict(rec, range_id=plan["range_id"], fill_time=iso_ts(P.t[i]), fill=fill, entry_mode=fl["mode"], features=plan.get("features"), sl=plan["sl"], tp1=plan["tp1"], tp2=tp2, spread=sp,
                       exits=[{"vol": v, "price": round(px, 5), "time": iso_ts(t), "reason": r} for (v, px, t, r) in res["exits"]],
                       net_price=net, risk_price=risk, net_r=net / risk, tp1_before_sl=first == "TP1", ambiguous=res["ambiguous"],
                       mfe_r=res["mfe"] / risk, mae_r=res["mae"] / risk, hold_min=(res["exits"][-1][2] - P.t[i]) / 60 if res["exits"] else None, win=net > 0,
                       economics=eco, precision="OHLC_APPROX", confirmation=plan["confirmation"]["family"])
            cycles.append(cyc)
            end_t = res["exits"][-1][2]
            busy_until = end_t + V(prof, "risk", "cooldown_after_cycle_min") * 60
            mach.close_direction(plan["direction"], "COOLDOWN", "cykl zakończony (replay)", end_t)
            decisions += policies(P, i, res, plan, sgn, fill, f1, tp2, P.t[i] + hold, risk, net, costs, prof, decision_points, margin_mode)
    return {"cycles": cycles, "blocked": blocked, "decisions": decisions, "journal_tail": mach.journal[-50:], "profile_id": prof["profile_id"],
            "precision": "OHLC_APPROX (bez ticków; konserwatywna kolejność SL przed TP w niejednoznacznych barach)", "margin_mode_assumed": margin_mode}


def policies(P: Path, i_fill: int, base: dict, plan: dict, sgn: int, fill: float, f1: float, tp2, t_end: int, risk: float, hold_net: float,
             costs: dict, prof: dict, max_points: int, margin_mode: str) -> list[dict]:
    """Decision points k = fill bar .. before the first base exit (base fully open): each frozen action on the SAME path."""
    out = []
    first_exit_i = P.index.get(base["exits"][0][2] - 60, i_fill) if base["exits"] else i_fill
    slip, com = costs.get("slippage_price", 0.0), costs.get("commission_price_side", 0.0)
    for k in range(i_fill, min(first_exit_i, i_fill + max_points)):
        if k + 1 >= len(P.t):
            break
        sp_k = P.sp[k] or 0.0
        mark = P.c[k] if sgn > 0 else P.c[k] + sp_k              # price at which the base would close now
        unreal = sgn * (mark - fill)
        res = {"HOLD": hold_net}
        res["CLOSE"] = sgn * (mark - sgn * slip - fill) - 2 * com
        rest = walk(P, k + 1, sgn, 0.5, plan["sl"], plan["tp1"], tp2, f1, t_end, costs, entry=fill)
        res["REDUCE"] = 0.5 * (sgn * (mark - sgn * slip - fill) - 2 * com) + pnl(sgn, fill, 0.5, rest["exits"], costs)
        if margin_mode == "NETTING":
            res["HEDGE_PARTIAL"] = None                               # opposite order reduces the net position = REDUCE
        else:
            res["HEDGE_PARTIAL"] = hedge_value(P, k + 1, sgn, plan, fill, hold_net, base, t_end, risk, costs, prof)
        out.append({"setup_id": plan["setup_id"], "decision_time": iso_ts(P.t[k] + 60), "k": k - i_fill, "unrealized_r": unreal / risk,
                    "values_r": {a: (None if v is None else v / risk) for a, v in res.items()},
                    "best": max((a for a in res if res[a] is not None), key=lambda a: res[a]),
                    "hedge_minus_reduce_r": None if res["HEDGE_PARTIAL"] is None else (res["HEDGE_PARTIAL"] - res["REDUCE"]) / risk,
                    "label_end": iso_ts(t_end)})
    return out


def hedge_value(P: Path, i: int, sgn: int, plan: dict, base_fill: float, base_net: float, base: dict, t_end: int, risk: float,
                costs: dict, prof: dict) -> float | None:
    """Base unchanged + ONE opposite hedge of 0.5 x base opened at the open of bar i; closes on TTL (3 closed M1), on the
    exit confirmation (2 consecutive closes in the base direction + close beyond the zone edge) or when the base exits.
    The hedge has its own server SL at the base risk distance. Basket P&L = base + hedge, all costs."""
    if i >= len(P.t):
        return None
    hs = -sgn
    slip, com = costs.get("slippage_price", 0.0), costs.get("commission_price_side", 0.0)
    sp = P.sp[i] or 0.0
    hfill = P.o[i] + (sp if hs > 0 else 0.0) + hs * slip
    h_sl = hfill - hs * risk
    ttl = V(prof, "hedge", "ttl_m1")
    edge = plan["zone"]["z_high"] if sgn > 0 else plan["zone"]["z_low"]
    base_end = base["exits"][-1][2] if base["exits"] else t_end
    run = 0
    vol = V(prof, "hedge", "max_fraction_of_base")
    for k in range(i, len(P.t)):
        spk = P.sp[k] or 0.0
        hi, lo = (P.h[k], P.l[k]) if hs > 0 else (P.h[k] + spk, P.l[k] + spk)
        close_side = P.c[k] if hs > 0 else P.c[k] + spk
        if (lo <= h_sl) if hs > 0 else (hi >= h_sl):
            px = h_sl - hs * slip
            break
        run = run + 1 if sgn * (P.c[k] - P.o[k]) > 0 else 0
        confirm = run >= V(prof, "hedge", "exit_confirm_m1") and sgn * (P.c[k] - edge) > 0
        if k - i + 1 >= ttl or confirm or P.t[k] + 60 >= min(base_end, t_end):
            px = close_side - hs * slip
            break
    else:
        return None
    return base_net + vol * (hs * (px - hfill)) - 2 * com * vol


def split_time(cycles: list[dict], frac: float = 0.8, t_range: tuple[int, int] | None = None) -> int:
    """Development / test boundary: frac of the data TIME span, cut at 00:00 UTC (same idea as the training plan)."""
    t0, t1 = t_range
    return (t0 + int(frac * (t1 - t0))) // 86400 * 86400


def compare_variants(m1: list[dict], prof: dict, variants: list[dict], tick: float, costs: dict, m5=None, m15=None, m30=None, h1=None,
                     min_dev_cycles: int = 30) -> dict:
    """Every variant on the SAME data and cost policy. Choice = highest development expectancy (R after costs, first 80% of
    time) with >= min_dev_cycles; the test part (last 20%) is shown for all but only the chosen one counts as its evaluation.
    The chosen variant is re-run with variable costs +50% (stress). Win ratio is reported next to expectancy, never decides."""
    from . import report
    ts_all = [ts(b["open_utc"]) for b in m1]
    cut = split_time([], 0.8, (min(ts_all), max(ts_all)))
    rows = []
    for v in variants:
        p = st.with_overrides(prof, v.get("set") or {})
        res = run(m1, p, tick, costs, m5, m15, m30, decision_points=0, h1=h1)
        dev = [c for c in res["cycles"] if ts(c["fill_time"]) < cut]
        test = [c for c in res["cycles"] if ts(c["fill_time"]) >= cut]
        rows.append({"id": v["id"], "desc": v.get("desc"), "set": v.get("set"), "development": report.strategy_summary(dev),
                     "test": report.strategy_summary(test), "blocked_counts": _count(res["blocked"])})
    elig = [r for r in rows if r["development"]["cycles"] >= min_dev_cycles]
    chosen = max(elig, key=lambda r: r["development"]["expectancy_r"]) if elig else None
    stress = None
    if chosen:
        sc = dict(costs, commission_price_side=1.5 * costs.get("commission_price_side", 0.0), slippage_price=1.5 * costs.get("slippage_price", 0.0))
        v = next(x for x in variants if x["id"] == chosen["id"])
        r2 = run(m1, st.with_overrides(prof, v.get("set") or {}), tick, sc, m5, m15, m30, decision_points=0, h1=h1)
        stress = report.strategy_summary([c for c in r2["cycles"] if ts(c["fill_time"]) >= cut])
    return {"boundary_utc": iso_ts(cut), "rows": rows, "chosen": chosen["id"] if chosen else None,
            "chosen_reason": "najwyższa expectancy w development" if chosen else f"żaden wariant nie ma ≥{min_dev_cycles} cykli w development – INSUFFICIENT_EVIDENCE",
            "chosen_test": chosen["test"] if chosen else None, "chosen_test_cost_stress_150": stress,
            "note": "warianty porównane na tych samych danych i kosztach; wiele wariantów = ryzyko przypadkowego zwycięzcy – test oceniany raz"}


def _count(rows: list[dict]) -> dict:
    c: dict[str, int] = {}
    for r in rows:
        k = r["reason"].split(":")[0]
        c[k] = c.get(k, 0) + 1
    return c
