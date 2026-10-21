"""Historical replay / validation of SCALPING and HEDGING with the SAME state machines used live (lifecycle.Position,
hedge_fsm.Basket) - the replay validates the real management logic, not a re-implementation.

Conventions (docs/strategie_sh/06_WALIDACJA.md):
* Setups are evaluated on closed M1 bars with the analysis snapshot as known at the last closed M5 bar (no look-ahead).
* Entry at the NEXT M1 bar open on the executable side (BUY at ask = open + spread, SELL at bid = open) + slippage.
* OHLC path inside a bar is unknown: CONSERVATIVE order (adverse extreme first, then favourable). A bar that could hit both a
  target and the stop is flagged AMBIGUOUS; with the conservative order the stop wins. Tick data (Bid/Ask) is preferred when
  available - this module accepts M1 only, which is reported as a limitation.
* Partials fill at the target price minus slippage; the stop fills at the stop or at the bar open if it gapped beyond it.
* BE becomes active only after the CONFIRMED TP2 fill and from the NEXT bar on.
* One trade/basket = one cycle (three partials are not three wins). Costs: spread + 2x slippage + commission (if known).
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

from . import context as CX
from . import setup as SU
from .hedge_fsm import Basket, HedgeConfig
from .lifecycle import Leg, Position
from .units import SymbolSpec


def _ts(x) -> float:
    return float(x) if isinstance(x, (int, float)) else datetime.fromisoformat(str(x).replace("Z", "+00:00")).timestamp()


def _agg(m1: list[dict], k: int) -> list[dict]:
    out, cur = [], None
    for b in m1:
        t = _ts(b["open_utc"])
        slot = t - (t % (k * 60))
        if cur is None or cur["_slot"] != slot:
            if cur:
                out.append(cur)
            cur = {"_slot": slot, "open_utc": slot, "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "spread": b.get("spread")}
        else:
            cur["h"], cur["l"], cur["c"] = max(cur["h"], b["h"]), min(cur["l"], b["l"]), b["c"]
    if cur:
        out.append(cur)
    return out


def session(t: float) -> str:
    h = datetime.fromtimestamp(t, tz=timezone.utc).hour
    return "ASIA" if h < 7 else "LONDON" if h < 12 else "NY_OVERLAP" if h < 16 else "NY" if h < 21 else "LATE"


def iter_setups(m1: list[dict], spec: SymbolSpec, strategy: str, prof: dict, *, spread_price: float, start: int = 600, step: int = 1,
                max_setups: int | None = None):
    """Yield (index, setup, snapshot) for READY setups. The snapshot uses bars closed up to the current M1 close; the heavy
    M5/M15/H1 components are recomputed at each new M5 close (cached in between)."""
    m5_all, m15_all, h1_all = _agg(m1, 5), _agg(m1, 15), _agg(m1, 60)
    t5 = [x["_slot"] for x in m5_all]
    cache_key, snap_base = None, None
    n = 0
    j5 = 0
    for i in range(start, len(m1) - 1, step):
        t_close = _ts(m1[i]["open_utc"]) + 60
        while j5 < len(t5) and t5[j5] + 300 <= t_close:
            j5 += 1
        m5 = m5_all[max(0, j5 - 400):j5]
        if len(m5) < 150:
            continue
        key = j5
        if key != cache_key:
            m15 = [x for x in m15_all if x["_slot"] + 900 <= t_close][-300:]
            h1 = [x for x in h1_all if x["_slot"] + 3600 <= t_close][-300:]
            q0 = {"bid": m1[i]["c"], "ask": m1[i]["c"] + spread_price, "time": t_close}
            snap_base = CX.snapshot({"M1": m1[max(0, i - 299):i + 1], "M5": m5, "M15": m15, "H1": h1}, q0, tick=spec.tick_size, now=t_close + 0.5,
                                    cfg={"max_spread_usd": None})
            cache_key = key
        snap = dict(snap_base)
        snap["price"] = {"bid": m1[i]["c"], "ask": m1[i]["c"] + spread_price}
        su = SU.evaluate(strategy, "REPLAY", snap, spec, prof, now=t_close, m1=m1[max(0, i - 20):i + 1])
        if su["status"] == "READY":
            yield i, su, snap
            n += 1
            if max_setups and n >= max_setups:
                return


def _quotes(bar: dict, side: str, spread: float):
    """Conservative intrabar path as (bid, ask) quotes: open -> adverse -> favourable -> close."""
    o, h, lo, c = bar["o"], bar["h"], bar["l"], bar["c"]
    path = [o, lo, h, c] if side == "BUY" else [o, h, lo, c]
    return [(p, p + spread) for p in path]


def simulate_scalp(i: int, su: dict, m1: list[dict], spec: SymbolSpec, prof: dict, *, spread: float, slippage: float,
                   commission_side: float | None, volume: float = 1.0) -> dict:
    side = su["side"]
    nb = m1[i + 1]
    entry = (nb["o"] + spread + slippage) if side == "BUY" else (nb["o"] - slippage)
    # plan relative to the ACTUAL fill (targets are distances from the real entry)
    sl_dist = abs(su["entry_ref"] - su["sl"])
    sl = spec.stop(entry, side, sl_dist)
    split = spec.split(volume, list(su["shares"]))
    if split["status"] != "OK":
        return {"status": "SKIPPED_VOLUME", "reason": split.get("reason")}
    legs = [Leg(t["name"], spec.target(entry, side, t["distance_requested"])["price"], v) for t, v in zip(su["tps"], split["legs"])]
    cost_off = su["be"]["offset_price"]
    pos = Position(plan_id=su["signal_id"], side=side, entry=entry, volume=volume, sl=sl, legs=legs,
                   be_rule="ENTRY_PLUS_COSTS" if cost_off else "ENTRY", be_offset=cost_off)
    horizon_bars = int(su["horizon_minutes"])
    max_bars = int(prof["position_max_minutes"])
    mae = mfe = 0.0
    ambiguous = False
    hit = {"TP1": None, "TP2": None, "TP3": None, "SL": None}
    be_active_from = None
    k = 0
    for k in range(i + 1, min(len(m1), i + 1 + max_bars)):
        bar = m1[k]
        age = k - i
        sgn = 1 if side == "BUY" else -1
        mae = min(mae, sgn * ((bar["l"] if side == "BUY" else bar["h"] + spread) - entry))
        mfe = max(mfe, sgn * ((bar["h"] if side == "BUY" else bar["l"] + spread) - entry))
        cur_sl = pos.sl if (be_active_from is None or k >= be_active_from) else sl
        adverse_hit = (bar["l"] <= cur_sl) if side == "BUY" else (bar["h"] + spread >= cur_sl)
        fav = [lg for lg in pos.legs if lg.status == "PENDING" and ((bar["h"] >= lg.price) if side == "BUY" else (bar["l"] + spread <= lg.price))]
        if adverse_hit and fav:
            ambiguous = True                                            # both in one bar: conservative -> stop first
        if adverse_hit:
            gap = (bar["o"] < cur_sl) if side == "BUY" else (bar["o"] + spread > cur_sl)
            px = (bar["o"] if gap else cur_sl) - slippage if side == "BUY" else (bar["o"] + spread if gap else cur_sl) + slippage
            pos.on_closed(f"sl{k}", pos.remaining, px, "SL")
            hit["SL"] = hit["SL"] or age
            break
        for bid, ask in _quotes(bar, side, spread)[1:]:
            for a in pos.on_quote(bid, ask):
                if a["kind"] in ("CLOSE_PARTIAL", "CLOSE_RUNNER"):
                    lg = next(x for x in pos.legs if x.name == a["action_id"].split(":")[-1]) if a["kind"] == "CLOSE_PARTIAL" else pos.legs[-1]
                    fill = lg.price - slippage if side == "BUY" else lg.price + slippage
                    acts = pos.on_fill(f"f{a['action_id']}", lg.name, a["volume"], fill)
                    hit[lg.name] = hit[lg.name] or age
                    for b2 in acts:
                        if b2["kind"] == "MODIFY_SL":
                            pos.on_sl_result(f"s{b2['action_id']}", True, bid, ask)
                            be_active_from = k + 1                       # BE effective from the next bar
        if pos.state == "CLOSED":
            break
        if age >= max_bars:
            break
    if pos.state != "CLOSED":
        last = m1[k]
        px = last["c"] - slippage if side == "BUY" else last["c"] + spread + slippage
        pos.on_closed("time", pos.remaining, px, "TIME_LIMIT")
    moves = sum(r["volume"] * r["move"] for r in pos.realized)
    comm = (2 * commission_side * volume / spec.money_per_price(1.0)) if commission_side is not None and spec.tick_value > 0 else 0.0
    net_price = moves / volume - comm                                    # spread/slippage already inside the fills
    sl_risk = abs(entry - sl)
    return {"status": "DONE", "t": _ts(m1[i]["open_utc"]), "side": side, "mode": su.get("mode"), "entry": entry, "sl": sl,
            "net_price": net_price, "net_r": net_price / sl_risk if sl_risk else None, "mae": mae, "mfe": mfe, "ambiguous": ambiguous,
            "tp1_before_sl_h": bool(hit["TP1"] and hit["TP1"] <= horizon_bars and (not hit["SL"] or hit["TP1"] < hit["SL"])),
            "tp2_before_sl_h": bool(hit["TP2"] and hit["TP2"] <= horizon_bars and (not hit["SL"] or hit["TP2"] < hit["SL"])),
            "tp3_before_sl_h": bool(hit["TP3"] and hit["TP3"] <= horizon_bars and (not hit["SL"] or hit["TP3"] < hit["SL"])),
            "hold_minutes": k - i, "legs": [vars(x) for x in pos.legs], "session": session(_ts(m1[i]["open_utc"])),
            "commission_known": commission_side is not None}


def simulate_hedge(i: int, su: dict, m1: list[dict], spec: SymbolSpec, prof: dict, *, spread: float, slippage: float,
                   commission_side: float | None, variant: str, volume: float = 1.0) -> dict:
    """variant: NO_HEDGE (plain primary), REDUCE (close reduce_fraction at the hedge event), HEDGE (state machine)."""
    side = su["side"]
    nb = m1[i + 1]
    entry = (nb["o"] + spread + slippage) if side == "BUY" else (nb["o"] - slippage)
    sl_dist = abs(su["entry_ref"] - su["sl"])
    sl = spec.stop(entry, side, sl_dist)
    split = spec.split(volume, list(su["shares"]))
    if split["status"] != "OK":
        return {"status": "SKIPPED_VOLUME"}
    legs = [Leg(t["name"], spec.target(entry, side, t["distance_requested"])["price"], v) for t, v in zip(su["tps"], split["legs"])]
    pos = Position(plan_id=su["signal_id"], side=side, entry=entry, volume=volume, sl=sl, legs=legs,
                   be_rule="ENTRY_PLUS_COSTS" if su["be"]["offset_price"] else "ENTRY", be_offset=su["be"]["offset_price"])
    hc = prof["hedge"]
    mpp = spec.money_per_price(1.0)
    risk_money = sl_dist * volume * mpp
    cfg = HedgeConfig(trigger_adverse_usd=hc["trigger_fraction_of_sl"] * sl_dist, ratio=hc["ratio"], max_ratio=hc["max_ratio"],
                      max_activations=hc["max_activations"], max_hedge_minutes=hc["max_hedge_minutes"],
                      unwind_recovery_usd=hc["unwind_recovery_atr_m5"] * 1.0, basket_loss_limit_money=hc["basket_loss_limit_x_risk"] * risk_money,
                      basket_max_minutes=prof["position_max_minutes"])
    bk = Basket(basket_id=su["signal_id"], primary=pos, cfg=cfg, money_per_price_per_lot=mpp, opened_at=0.0)
    reduced = False
    ambiguous = False
    k = i
    for k in range(i + 1, min(len(m1), i + 1 + int(prof["position_max_minutes"]))):
        t = (k - i) * 60.0
        bar = m1[k]
        if pos.state == "CLOSED" and bk.state in ("CLOSED", "PRIMARY_OPEN") and not (bk.hedge and bk.hedge.status == "OPEN"):
            break
        cur_sl = pos.sl
        adverse = (bar["l"] <= cur_sl) if side == "BUY" else (bar["h"] + spread >= cur_sl)
        if adverse and pos.remaining > 1e-9:
            if any(lg.status == "PENDING" and ((bar["h"] >= lg.price) if side == "BUY" else (bar["l"] + spread <= lg.price)) for lg in pos.legs):
                ambiguous = True
            gap = (bar["o"] < cur_sl) if side == "BUY" else (bar["o"] + spread > cur_sl)
            px = (bar["o"] if gap else cur_sl) - slippage if side == "BUY" else (bar["o"] + spread if gap else cur_sl) + slippage
            for a in bk.on_primary_closed(f"sl{k}", t, pos.remaining, px, "SL"):
                _fill_hedge_close(bk, a, bar, spread, slippage, k, t)
            break
        for bid, ask in _quotes(bar, side, spread)[1:]:
            if variant != "NO_HEDGE" and bk.state == "PRIMARY_OPEN" and bk.activations < cfg.max_activations and not reduced:
                dec = bk.hedge_decision(bid, ask, structure_valid=((bid > su["invalidation"]) if side == "BUY" else (ask < su["invalidation"])),
                                        risk_ok=True, risk_reason="", hedge_cost_price=spread + 2 * slippage,
                                        reduce_cost_price=spread + 2 * slippage + 1e-9 if variant == "HEDGE" else 0.0)
                if dec["decision"] in ("HEDGE", "REDUCE", "EXIT"):
                    if variant == "REDUCE":
                        vol_r = spec.floor_volume(pos.remaining * hc.get("reduce_fraction", 0.5))
                        if vol_r >= spec.volume_min:
                            px = bid - slippage if side == "BUY" else ask + slippage
                            pos.on_closed(f"red{k}", vol_r, px, "REDUCE")
                        reduced = True
                    elif variant == "HEDGE" and dec["decision"] == "HEDGE":
                        hv = bk.hedge_volume(spec.floor_volume)
                        for a in bk.request_hedge(t, hv, dec["reason"]):
                            px = bid - slippage if a["side"] == "SELL" else ask + slippage
                            bk.on_hedge_result(f"h{k}", t, True, a["volume"], px)
            for a in bk.on_quote(t, bid, ask, structure_valid=True):
                if a["kind"] in ("CLOSE_PARTIAL", "CLOSE_RUNNER"):
                    lg = next(x for x in pos.legs if x.name == a["action_id"].split(":")[-1]) if a["kind"] == "CLOSE_PARTIAL" else pos.legs[-1]
                    fill = lg.price - slippage if side == "BUY" else lg.price + slippage
                    for b2 in bk.on_primary_fill(f"f{a['action_id']}", t, lg.name, a["volume"], fill):
                        if b2["kind"] == "MODIFY_SL":
                            pos.on_sl_result(f"s{b2['action_id']}", True, bid, ask)
                        else:
                            _fill_hedge_close(bk, b2, bar, spread, slippage, k, t)
                elif a["kind"] in ("CLOSE_HEDGE",):
                    _fill_hedge_close(bk, a, bar, spread, slippage, k, t, bid=bid, ask=ask)
                elif a["kind"] == "CLOSE_PRIMARY":
                    px = bid - slippage if side == "BUY" else ask + slippage
                    bk.on_primary_closed(f"cp{k}", t, pos.remaining, px, "EXIT")
            if pos.state == "CLOSED":
                break
    last = m1[k]
    if pos.remaining > 1e-9:
        px = last["c"] - slippage if side == "BUY" else last["c"] + spread + slippage
        bk.on_primary_closed("time", (k - i) * 60.0, pos.remaining, px, "TIME_LIMIT")
    if bk.hedge and bk.hedge.status in ("OPEN", "CLOSING"):
        hpx = last["c"] + spread + slippage if bk.hedge.side == "SELL" else last["c"] - slippage
        bk.hedge.status = "OPEN"
        bk.on_hedge_closed("htime", (k - i) * 60.0, bk.hedge.volume, hpx)
    gross = bk.primary_realized() + bk.hedge_realized_money
    legs_n = 1 + (1 if bk.activations and bk.hedge else 0)
    comm = (2 * commission_side * volume * legs_n) if commission_side is not None else 0.0
    net_money = gross - comm
    return {"status": "DONE", "variant": variant, "t": _ts(m1[i]["open_utc"]), "side": side, "net_money": net_money,
            "net_r": net_money / risk_money if risk_money else None, "primary_money": bk.primary_realized(), "hedge_money": bk.hedge_realized_money,
            "hedge_activations": bk.activations, "ambiguous": ambiguous, "hold_minutes": k - i, "session": session(_ts(m1[i]["open_utc"])),
            "tp2_before_sl_h": any(r["leg"] == "TP2" for r in pos.realized), "transitions": bk.transitions[-10:]}


def _fill_hedge_close(bk: Basket, a: dict, bar: dict, spread: float, slippage: float, k: int, t: float, bid=None, ask=None) -> None:
    if a.get("kind") != "CLOSE_HEDGE" or not bk.hedge:
        return
    bid = bar["c"] if bid is None else bid
    ask = bid + spread if ask is None else ask
    px = ask + slippage if bk.hedge.side == "SELL" else bid - slippage
    bk.hedge.status = "OPEN"
    bk.on_hedge_closed(f"hc{k}{a['action_id']}", t, bk.hedge.volume, px)


def metrics(trades: list[dict], key: str = "net_price") -> dict:
    done = [x for x in trades if x.get("status") == "DONE"]
    if not done:
        return {"n": 0}
    v = [x[key] for x in done]
    wins = [x for x in v if x > 0]
    losses = [-x for x in v if x < 0]
    eq, peak, dd = 0.0, 0.0, 0.0
    for x in v:
        eq += x
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    mean = sum(v) / len(v)
    sd = math.sqrt(sum((x - mean) ** 2 for x in v) / max(1, len(v) - 1))
    return {"n": len(v), "net_total": sum(v), "expectancy": mean, "expectancy_se": sd / math.sqrt(len(v)),
            "win_rate": len(wins) / len(v), "profit_factor": (sum(wins) / sum(losses)) if losses else None, "max_drawdown": dd,
            "ambiguous_share": sum(1 for x in done if x.get("ambiguous")) / len(done),
            "avg_hold_min": sum(x.get("hold_minutes", 0) for x in done) / len(done)}
