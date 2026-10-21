"""Historical replay / validation of SCALPING and HEDGING with the SAME code used live: context.snapshot (same caching), setup.evaluate,
lifecycle.Position and hedge_fsm.Basket. The replay validates the real decision and management logic, not a re-implementation.

Conventions (docs/strategie_sh/06_WALIDACJA.md):
* Setups are evaluated on CLOSED M1 bars with M5/M15/H1 closed at that time (no look-ahead; windows by close time).
* One plan per strategy at a time (like live: the coordinator blocks a new plan while one is open).
* Entry at the NEXT M1 open on the executable side (BUY at ask = open + spread of that bar, SELL at bid) + slippage. SL is the
  plan's PRICE (as live); a fill beyond the SL is closed at once (ENTRY_ABORT, a real loss).
* The path inside a bar is unknown: CONSERVATIVE order (adverse extreme first). A bar that touches a target and the stop is
  AMBIGUOUS and the stop wins. Only M1 OHLC is available here (no ticks) - reported as a limitation.
* Partials fill at the target minus slippage; the stop fills at the stop or at the bar open if it gapped beyond it.
* BE becomes active only after the CONFIRMED TP2 fill and from the NEXT bar on.
* One plan = one cycle (three partials are not three wins). Costs: spread (per bar) + slippage inside fills + commission if known.
* The event label "TP2 before SL within the horizon" is computed independently of the management (same conservative rules).
"""
from __future__ import annotations

import bisect
import csv
import json
import random
from datetime import datetime, timezone
from pathlib import Path

from . import context as CX
from . import setup as SU
from . import tpmodel as TM
from .hedge_fsm import Basket, HedgeConfig
from .lifecycle import Leg, Position
from .units import SymbolSpec

TF_S = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600}


def _ts(x) -> float:
    return float(x) if isinstance(x, (int, float)) else datetime.fromisoformat(str(x).replace("Z", "+00:00")).timestamp()


# ---------------------------------------------------------------------------- data
def load_dataset(ds: Path, *, last_m1: int | None = None) -> tuple[dict, dict]:
    """Bars of an exported training dataset (broker bars, exactly as exported). Missing timeframes are aggregated from M1."""
    ds = Path(ds)
    meta = json.loads((ds / "source_metadata.json").read_text(encoding="utf-8"))
    pref = meta.get("file_prefix") or meta.get("instrument") or "XAUUSD"
    point = float((meta.get("spec") or {}).get("point") or meta.get("tick_size") or 0.01)
    out = {}
    for tf in ("M1", "M5", "M15", "H1"):
        p = ds / f"{pref}_{tf}.csv"
        if not p.exists():
            continue
        rows = []
        with p.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                sp = r.get("spread_points")
                rows.append({"open_utc": r["time_open_utc"], "o": float(r["open"]), "h": float(r["high"]), "l": float(r["low"]), "c": float(r["close"]),
                             "spread_price": float(sp) * point if sp not in (None, "") else None})
        out[tf] = rows
    if "M1" not in out:
        raise ValueError("DATASET_WITHOUT_M1")
    if last_m1 and len(out["M1"]) > last_m1:
        out["M1"] = out["M1"][-last_m1:]
        t0 = _ts(out["M1"][0]["open_utc"])
        for tf in ("M5", "M15", "H1"):
            if tf in out:                                      # keep enough higher-TF history for the warm-up
                out[tf] = [b for b in out[tf] if _ts(b["open_utc"]) >= t0 - 400 * TF_S[tf]]
    for tf in ("M5", "M15", "H1"):
        if tf not in out:
            out[tf] = aggregate(out["M1"], TF_S[tf] // 60)
    return out, meta


def aggregate(m1: list[dict], k: int) -> list[dict]:
    out, cur = [], None
    for b in m1:
        t = _ts(b["open_utc"])
        slot = t - (t % (k * 60))
        if cur is None or cur["_slot"] != slot:
            if cur:
                out.append(cur)
            cur = {"_slot": slot, "open_utc": datetime.fromtimestamp(slot, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
                   "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "spread_price": b.get("spread_price")}
        else:
            cur["h"], cur["l"], cur["c"] = max(cur["h"], b["h"]), min(cur["l"], b["l"]), b["c"]
    if cur:
        out.append(cur)
    return out


def session(t: float) -> str:
    h = datetime.fromtimestamp(t, tz=timezone.utc).hour
    return "ASIA" if h < 7 else "LONDON" if h < 12 else "NY_OVERLAP" if h < 16 else "NY" if h < 21 else "LATE"


class Market:
    """Point-in-time access: the bars of each timeframe CLOSED at a given time (bisect on close times)."""

    def __init__(self, bars: dict, spread_fallback: float):
        self.bars = bars
        self.m1 = bars["M1"]
        self.close_t = {tf: [_ts(b["open_utc"]) + TF_S[tf] for b in bars[tf]] for tf in ("M1", "M5", "M15", "H1")}
        self.spread_fallback = spread_fallback

    def spread(self, i: int) -> float:
        sp = self.m1[i].get("spread_price")
        return float(sp) if sp is not None and sp > 0 else self.spread_fallback

    def window(self, t_close: float) -> dict:
        out = {}
        for tf, n in (("M1", 300), ("M5", 400), ("M15", 300), ("H1", 300)):
            j = bisect.bisect_right(self.close_t[tf], t_close + 1e-6)
            out[tf] = self.bars[tf][max(0, j - n):j]
        return out


# ---------------------------------------------------------------------------- setup scan
def scan(market: Market, spec: SymbolSpec, profiles: dict, *, start: int = 0, end: int | None = None, progress=None):
    """Yield (i, {strategy: setup}, snapshot) for every closed M1 bar. ONE snapshot per bar shared by all strategies (as live)."""
    cache: dict = {}
    end = len(market.m1) - 1 if end is None else end
    max_sp = min(((p.get("_instrument") or {}).get("max_spread_usd") for p in profiles.values()), key=lambda x: x or 0)
    for i in range(start, end):
        t_close = market.close_t["M1"][i]
        if progress and i % 500 == 0:
            progress(i, end)
        w = market.window(t_close)
        if len(w["M5"]) < 150 or len(w["M1"]) < 60:
            continue
        sp = market.spread(i)
        q = {"bid": market.m1[i]["c"], "ask": market.m1[i]["c"] + sp, "time": t_close}
        snap = CX.snapshot(w, q, tick=spec.tick_size, now=t_close + 0.5, cfg={"max_spread_usd": max_sp}, cache=cache)
        yield i, {s: SU.evaluate(s, "REPLAY", snap, spec, p, now=t_close, m1=w["M1"][-20:]) for s, p in profiles.items()}, snap


# ---------------------------------------------------------------------------- simulation helpers
def _entry(market: Market, i: int, side: str, slip: float) -> float:
    nb = market.m1[i + 1]
    return (nb["o"] + market.spread(i + 1) + slip) if side == "BUY" else (nb["o"] - slip)


def _adverse(bar, side, sp, level):
    return (bar["l"] <= level) if side == "BUY" else (bar["h"] + sp >= level)


def _fav(bar, side, sp, level):
    return (bar["h"] >= level) if side == "BUY" else (bar["l"] + sp <= level)


def _stop_fill(bar, side, sp, level, slip):
    if side == "BUY":
        return (bar["o"] if bar["o"] < level else level) - slip
    return (bar["o"] + sp if bar["o"] + sp > level else level) + slip


def label_event(market: Market, i: int, su: dict, spec: SymbolSpec, slip: float, horizon: int) -> int:
    """1 if TP2 (from the actual fill) is reached before the SL within the horizon (conservative ambiguous bars), else 0."""
    side = su["side"]
    e = _entry(market, i, side, slip)
    sl = float(su["sl"])
    if (e <= sl) if side == "BUY" else (e >= sl):
        return 0
    tp2 = spec.target(e, side, su["tps"][1]["distance_requested"])["price"]
    for k in range(i + 1, min(len(market.m1), i + 1 + horizon)):
        b, sp = market.m1[k], market.spread(k)
        if _adverse(b, side, sp, sl):
            return 0
        if _fav(b, side, sp, tp2):
            return 1
    return 0


def _legs(spec, e, side, su, volume):
    sp = spec.split(volume, list(su["shares"]))
    if sp["status"] != "OK":
        return None
    return [Leg(t["name"], spec.target(e, side, t["distance_requested"])["price"], v) for t, v in zip(su["tps"], sp["legs"])]


def simulate_scalp(market: Market, i: int, su: dict, spec: SymbolSpec, prof: dict, *, slip: float, commission_side: float | None,
                   volume: float = 1.0) -> dict:
    side = su["side"]
    e = _entry(market, i, side, slip)
    sl = float(su["sl"])
    t0 = market.close_t["M1"][i]
    base = {"t": t0, "side": side, "mode": su.get("mode"), "session": session(t0), "entry": e, "sl": sl, "commission_known": commission_side is not None}
    comm_price = (2 * commission_side / spec.money_per_price(1.0)) if commission_side is not None else 0.0
    if (e <= sl) if side == "BUY" else (e >= sl):                    # fill beyond the stop: closed at once (live: ENTRY_ABORT)
        sp = market.spread(i + 1)
        net = -(sp + 2 * slip) - comm_price
        return {**base, "status": "DONE", "exit": "ENTRY_ABORT", "net_price": net, "net_r": None, "mae": 0.0, "mfe": 0.0, "ambiguous": False,
                "hold_minutes": 0, "cost_price": sp + 2 * slip + comm_price, "end_index": i + 1}
    legs = _legs(spec, e, side, su, volume)
    if legs is None:
        return {**base, "status": "SKIPPED_VOLUME"}
    off = float((su.get("be") or {}).get("offset_price") or 0.0)
    pos = Position(plan_id="R", side=side, entry=e, volume=volume, sl=sl, legs=legs, be_rule="ENTRY_PLUS_COSTS" if off else "ENTRY", be_offset=off)
    max_bars = int(prof["position_max_minutes"])
    mae = mfe = 0.0
    ambiguous = False
    be_from = None
    k = i
    exit_reason = "TIME_LIMIT"
    sgn = 1 if side == "BUY" else -1
    for k in range(i + 1, min(len(market.m1), i + 1 + max_bars)):
        b, sp = market.m1[k], market.spread(k)
        mae = min(mae, sgn * ((b["l"] if side == "BUY" else b["h"] + sp) - e))
        mfe = max(mfe, sgn * ((b["h"] if side == "BUY" else b["l"] + sp) - e))
        cur_sl = pos.sl if (be_from is None or k >= be_from) else sl
        hit = _adverse(b, side, sp, cur_sl)
        if hit and any(lg.status == "PENDING" and _fav(b, side, sp, lg.price) for lg in pos.legs):
            ambiguous = True
        if hit:
            exit_reason = "BE" if be_from and k >= be_from else "SL"
            pos.on_closed(f"s{k}", pos.remaining, _stop_fill(b, side, sp, cur_sl, slip), exit_reason)
            break
        path = [b["o"], b["l"], b["h"], b["c"]] if side == "BUY" else [b["o"], b["h"], b["l"], b["c"]]
        for px in path[1:]:
            for a in pos.on_quote(px, px + sp):
                lg = next(x for x in pos.legs if x.name == a["action_id"].split(":")[-1]) if a["kind"] == "CLOSE_PARTIAL" else pos.legs[-1]
                fill = lg.price - slip if side == "BUY" else lg.price + slip
                for b2 in pos.on_fill(f"f{a['action_id']}", lg.name, a["volume"], fill):
                    if b2["kind"] == "MODIFY_SL":
                        pos.on_sl_result(f"s{b2['action_id']}", True, px, px + sp)
                        be_from = k + 1
            if pos.state == "CLOSED":
                exit_reason = "TP3"
                break
        if pos.state == "CLOSED":
            break
    if pos.state != "CLOSED":
        b, sp = market.m1[k], market.spread(k)
        pos.on_closed("time", pos.remaining, b["c"] - slip if side == "BUY" else b["c"] + sp + slip, "TIME_LIMIT")
    net = sum(r["volume"] * r["move"] for r in pos.realized) / volume - comm_price
    risk = abs(e - sl)
    return {**base, "status": "DONE", "exit": exit_reason, "net_price": net, "net_r": net / risk if risk else None, "mae": mae, "mfe": mfe,
            "ambiguous": ambiguous, "hold_minutes": k - i, "legs_done": [x.name for x in pos.legs if x.status == "DONE"],
            "cost_price": market.spread(i + 1) + 2 * slip + comm_price, "end_index": k}


def simulate_hedge(market: Market, i: int, su: dict, spec: SymbolSpec, prof: dict, *, slip: float, commission_side: float | None,
                   variant: str, atr_m5: float, volume: float = 1.0) -> dict:
    """variant NO_HEDGE / REDUCE / HEDGE - the same decision rule as live (event, structure, cost cap); results per unit volume."""
    side = su["side"]
    e = _entry(market, i, side, slip)
    sl = float(su["sl"])
    t0 = market.close_t["M1"][i]
    base = {"t": t0, "variant": variant, "side": side, "session": session(t0), "mode": su.get("mode"), "commission_known": commission_side is not None}
    comm_price = (2 * commission_side / spec.money_per_price(1.0)) if commission_side is not None else 0.0
    risk = abs(e - sl)
    if (e <= sl) if side == "BUY" else (e >= sl):
        sp = market.spread(i + 1)
        return {**base, "status": "DONE", "exit": "ENTRY_ABORT", "net_price": -(sp + 2 * slip) - comm_price, "net_r": None, "hedge_activations": 0,
                "ambiguous": False, "hold_minutes": 0, "end_index": i + 1}
    legs = _legs(spec, e, side, su, volume)
    if legs is None:
        return {**base, "status": "SKIPPED_VOLUME"}
    off = float((su.get("be") or {}).get("offset_price") or 0.0)
    pos = Position(plan_id="R", side=side, entry=e, volume=volume, sl=sl, legs=legs, be_rule="ENTRY_PLUS_COSTS" if off else "ENTRY", be_offset=off)
    h = prof["hedge"]
    cfg = HedgeConfig(trigger_adverse_usd=h["trigger_fraction_of_sl"] * risk, ratio=h["ratio"], max_ratio=h["max_ratio"],
                      max_activations=h["max_activations"], max_hedge_minutes=h["max_hedge_minutes"],
                      unwind_recovery_usd=h["unwind_recovery_atr_m5"] * atr_m5, basket_loss_limit_money=h["basket_loss_limit_x_risk"] * risk * volume,
                      basket_max_minutes=prof["position_max_minutes"])
    bk = Basket(basket_id="R", primary=pos, cfg=cfg, money_per_price_per_lot=1.0, opened_at=0.0)
    inval = su.get("invalidation")
    cap = float(h.get("max_hedge_cost_fraction_of_sl", 0.25)) * risk
    ambiguous = False
    hedge_lots = 0.0
    k = i

    def close_hedge(a, bid, ask, t, tag):
        if a.get("kind") != "CLOSE_HEDGE" or not bk.hedge:
            return
        bk.hedge.status = "OPEN"
        bk.on_hedge_closed(f"hc{tag}", t, bk.hedge.volume, ask + slip if bk.hedge.side == "SELL" else bid - slip)

    def all_closed():
        return pos.state == "CLOSED" and not (bk.hedge and bk.hedge.status in ("OPEN", "CLOSING"))

    for k in range(i + 1, min(len(market.m1), i + 1 + int(prof["position_max_minutes"]))):
        t = (k - i) * 60.0
        b, sp = market.m1[k], market.spread(k)
        if all_closed():
            break
        if pos.remaining > 1e-9 and _adverse(b, side, sp, pos.sl):
            if any(lg.status == "PENDING" and _fav(b, side, sp, lg.price) for lg in pos.legs):
                ambiguous = True
            for a in bk.on_primary_closed(f"sl{k}", t, pos.remaining, _stop_fill(b, side, sp, pos.sl, slip), "SL"):
                close_hedge(a, b["c"], b["c"] + sp, t, f"sl{k}")
            break
        path = [b["o"], b["l"], b["h"], b["c"]] if side == "BUY" else [b["o"], b["h"], b["l"], b["c"]]
        for j, px in enumerate(path[1:]):
            bid, ask = px, px + sp
            sv = True if inval is None else ((bid > inval) if side == "BUY" else (ask < inval))
            if variant != "NO_HEDGE" and bk.state == "PRIMARY_OPEN" and pos.state in ("OPEN", "TP1_DONE") and bk.activations < cfg.max_activations:
                dec = bk.hedge_decision(bid, ask, structure_valid=sv, risk_ok=True, risk_reason="", hedge_cost_price=sp + 2 * slip,
                                        reduce_cost_price=cap)
                if dec["decision"] == "EXIT":
                    for a in bk._exit_all(t, dec["reason"]):
                        if a["kind"] == "CLOSE_PRIMARY":
                            bk.on_primary_closed(f"ex{k}", t, pos.remaining, bid - slip if side == "BUY" else ask + slip, "EXIT")
                elif dec["decision"] == "REDUCE" or (dec["decision"] == "HEDGE" and variant == "REDUCE"):
                    vol_r = spec.floor_volume(pos.remaining * h.get("reduce_fraction", 0.5))
                    bk.activations += 1
                    if vol_r >= spec.volume_min and pos.remaining - vol_r >= spec.volume_min - 1e-9:
                        pos.on_closed(f"red{k}", vol_r, bid - slip if side == "BUY" else ask + slip, "REDUCE")
                elif dec["decision"] == "HEDGE":
                    for a in bk.request_hedge(t, bk.hedge_volume(spec.floor_volume), dec["reason"]):
                        hedge_lots += a["volume"]
                        bk.on_hedge_result(f"h{k}", t, True, a["volume"], bid - slip if a["side"] == "SELL" else ask + slip)
            for a in bk.on_quote(t, bid, ask, structure_valid=sv):
                if a["kind"] in ("CLOSE_PARTIAL", "CLOSE_RUNNER"):
                    lg = next(x for x in pos.legs if x.name == a["action_id"].split(":")[-1]) if a["kind"] == "CLOSE_PARTIAL" else pos.legs[-1]
                    fill = lg.price - slip if side == "BUY" else lg.price + slip
                    for b2 in bk.on_primary_fill(f"f{a['action_id']}", t, lg.name, a["volume"], fill):
                        if b2["kind"] == "MODIFY_SL":
                            pos.on_sl_result(f"s{b2['action_id']}", True, bid, ask)
                        else:
                            close_hedge(b2, bid, ask, t, f"{k}{j}{b2['action_id']}")
                elif a["kind"] == "CLOSE_HEDGE":
                    close_hedge(a, bid, ask, t, f"{k}{j}{a['action_id']}")
                elif a["kind"] == "CLOSE_PRIMARY":
                    for b2 in bk.on_primary_closed(f"cp{k}{j}", t, pos.remaining, bid - slip if side == "BUY" else ask + slip, "EXIT"):
                        close_hedge(b2, bid, ask, t, f"cpx{k}{j}")
            if all_closed():
                break
        if all_closed():
            break
    b, sp = market.m1[k], market.spread(k)
    if pos.remaining > 1e-9:
        bk.on_primary_closed("time", (k - i) * 60.0, pos.remaining, b["c"] - slip if side == "BUY" else b["c"] + sp + slip, "TIME_LIMIT")
    if bk.hedge and bk.hedge.status in ("OPEN", "CLOSING"):
        bk.hedge.status = "OPEN"
        bk.on_hedge_closed("htime", (k - i) * 60.0, bk.hedge.volume, b["c"] + sp + slip if bk.hedge.side == "SELL" else b["c"] - slip)
    gross = (bk.primary_realized() + bk.hedge_realized_money) / volume
    net = gross - comm_price * (1 + hedge_lots / volume)
    return {**base, "status": "DONE", "exit": "CYCLE", "net_price": net, "net_r": net / risk if risk else None, "primary_price": bk.primary_realized() / volume,
            "hedge_price": bk.hedge_realized_money / volume, "hedge_activations": bk.activations, "ambiguous": ambiguous, "hold_minutes": k - i,
            "end_index": k}


# ---------------------------------------------------------------------------- metrics
def metrics(trades: list[dict], key: str = "net_r", seed: int = 7, boot: int = 1000) -> dict:
    done = [x for x in trades if x.get("status") == "DONE" and x.get(key) is not None]
    out = {"n": len(done)}
    if not done:
        return out
    v = [float(x[key]) for x in done]
    wins = [x for x in v if x > 0]
    losses = [-x for x in v if x < 0]
    eq = peak = dd = 0.0
    for x in v:
        eq += x
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    mean = sum(v) / len(v)
    rng = random.Random(seed)
    bs = sorted(sum(rng.choice(v) for _ in v) / len(v) for _ in range(boot)) if len(v) >= 5 else []
    out.update(total=sum(v), expectancy=mean, ci90=[bs[int(0.05 * boot)], bs[int(0.95 * boot) - 1]] if bs else None,
               win_rate=len(wins) / len(v), profit_factor=(sum(wins) / sum(losses)) if losses else None, max_drawdown=dd,
               ambiguous_share=sum(1 for x in done if x.get("ambiguous")) / len(done),
               avg_hold_min=sum(x.get("hold_minutes", 0) for x in done) / len(done))
    if any("mae" in x for x in done):
        out.update(avg_mae_price=sum(x.get("mae", 0.0) for x in done) / len(done), avg_mfe_price=sum(x.get("mfe", 0.0) for x in done) / len(done))
    if any("cost_price" in x for x in done):
        out["avg_cost_price"] = sum(x.get("cost_price", 0.0) for x in done) / len(done)
    return out


def breakdown(trades: list[dict], field: str, key: str = "net_r") -> dict:
    groups: dict = {}
    for x in trades:
        groups.setdefault(str(x.get(field)), []).append(x)
    return {g: metrics(v, key, boot=200) for g, v in sorted(groups.items())}


def folds(trades: list[dict], k: int = 4, key: str = "net_r") -> list[dict]:
    done = sorted([x for x in trades if x.get("status") == "DONE"], key=lambda x: x["t"])
    if len(done) < k:
        return []
    n = len(done)
    return [{"fold": f + 1, "from": done[f * n // k]["t"], "to": done[(f + 1) * n // k - 1]["t"],
             **metrics(done[f * n // k:(f + 1) * n // k], key, boot=200)} for f in range(k)]


# ---------------------------------------------------------------------------- full strategy replay
def run(market: Market, spec: SymbolSpec, profiles: dict, *, slip: float, commission_side: float | None,
        start: int = 0, end: int | None = None, progress=None, baseline_every: int = 60) -> dict:
    """All strategies over one scan; one plan at a time PER STRATEGY (as live). Returns per strategy: trades (variants for
    HEDGING), event-model samples, status counts, top rejection reasons, baseline."""
    out = {s: {"counts": {}, "reasons": {}, "trades": [], "variants": {"NO_HEDGE": [], "REDUCE": [], "HEDGE": []}, "samples": [], "busy": -1,
               "sl": []} for s in profiles}
    for i, sus, snap in scan(market, spec, profiles, start=start, end=end, progress=progress):
        for strat, su in sus.items():
            R, prof = out[strat], profiles[strat]
            R["counts"][su["status"]] = R["counts"].get(su["status"], 0) + 1
            if su["status"] != "READY":
                r = (su.get("status_reason") or "")[:60]
                R["reasons"][r] = R["reasons"].get(r, 0) + 1
                continue
            if i <= R["busy"] or i + 2 >= len(market.m1):
                R["counts"]["READY_SKIPPED_OPEN_PLAN"] = R["counts"].get("READY_SKIPPED_OPEN_PLAN", 0) + 1
                continue
            y = label_event(market, i, su, spec, slip, int(prof["horizon_minutes"]))
            R["samples"].append({"t": market.close_t["M1"][i], "x": TM.features(su, snap), "y": y})
            R["sl"].append(abs(su["entry_ref"] - su["sl"]))
            if strat == "SCALPING":
                tr = simulate_scalp(market, i, su, spec, prof, slip=slip, commission_side=commission_side)
                tr["label_tp2_before_sl"] = y
                R["trades"].append(tr)
                R["busy"] = tr.get("end_index", i)
            else:
                a5 = (snap.get("vol") or {}).get("atr_m5") or abs(su["entry_ref"] - su["sl"])
                ends = []
                for v in R["variants"]:
                    tr = simulate_hedge(market, i, su, spec, prof, slip=slip, commission_side=commission_side, variant=v, atr_m5=a5)
                    tr["label_tp2_before_sl"] = y
                    R["variants"][v].append(tr)
                    ends.append(tr.get("end_index", i))
                R["busy"] = max(ends)
    for strat, R in out.items():
        sl = sorted(R.pop("sl"))
        R.pop("busy")
        R["reasons"] = dict(sorted(R["reasons"].items(), key=lambda x: -x[1])[:15])
        R["baseline"] = baseline(market, spec, strat, profiles[strat], slip=slip, commission_side=commission_side, start=start, end=end,
                                 every=baseline_every, sl_dist=(sl[len(sl) // 2] if sl else profiles[strat]["sl_min_usd"]))
    return out


def baseline(market: Market, spec: SymbolSpec, strategy: str, prof: dict, *, slip: float, commission_side: float | None, start: int, end: int | None,
             every: int, sl_dist: float) -> list[dict]:
    """Naive comparison: every `every` M1 bars, side = sign of the last 60 min return, SAME targets / SL distance / management /
    costs, no setup filter. Shows whether the setup logic adds anything over a trivial rule."""
    out = []
    end = len(market.m1) - 2 if end is None else min(end, len(market.m1) - 2)
    i = max(start, 61)
    busy = -1
    while i < end:
        if i > busy:
            side = "BUY" if market.m1[i]["c"] >= market.m1[i - 60]["c"] else "SELL"
            ref = market.m1[i]["c"] + (market.spread(i) if side == "BUY" else 0.0)
            su = {"side": side, "entry_ref": ref, "sl": spec.stop(ref, side, sl_dist), "shares": prof["shares"], "mode": "BASELINE",
                  "tps": [{"name": n, "distance_requested": d} for n, d in zip(("TP1", "TP2", "TP3"), prof["tp_usd"])],
                  "be": {"offset_price": 0.0}, "invalidation": None}
            tr = (simulate_scalp(market, i, su, spec, prof, slip=slip, commission_side=commission_side) if strategy == "SCALPING" else
                  simulate_hedge(market, i, su, spec, prof, slip=slip, commission_side=commission_side, variant="NO_HEDGE", atr_m5=sl_dist))
            out.append(tr)
            busy = tr.get("end_index", i)
        i += every
    return out


def report(res: dict, strategy: str, *, meta: dict | None = None, model: dict | None = None) -> dict:
    """Validation report of one strategy: everything is computed from the replay result (nothing typed in)."""
    first = (res["trades"] or res["variants"]["HEDGE"] or [{}])[0]
    rep = {"strategy": strategy, "created_at": datetime.now(timezone.utc).isoformat(), "counts": res["counts"], "top_rejections": res["reasons"],
           "dataset": {k: (meta or {}).get(k) for k in ("dataset_id", "symbol", "instrument", "range_utc", "data_kind")},
           "event_model": model, "unit": "R = wynik całego cyklu / ryzyko planu (wejście–SL); cena = USD ruchu ceny na jednostkę wolumenu"}
    if strategy == "SCALPING":
        tr = res["trades"]
        done = [x for x in tr if x.get("status") == "DONE"]
        n = max(1, len(done))
        rep.update(metrics=metrics(tr), metrics_price=metrics(tr, "net_price"), by_side=breakdown(tr, "side"), by_session=breakdown(tr, "session"),
                   by_mode=breakdown(tr, "mode"), by_exit=breakdown(tr, "exit"), folds=folds(tr),
                   hit_rates={"TP1": sum("TP1" in (x.get("legs_done") or []) for x in done) / n,
                              "TP2": sum("TP2" in (x.get("legs_done") or []) for x in done) / n,
                              "TP3": sum("TP3" in (x.get("legs_done") or []) for x in done) / n,
                              "event_TP2_before_SL_in_horizon": sum(x.get("label_tp2_before_sl", 0) for x in done) / n})
    else:
        rep["variants"] = {v: metrics(t) for v, t in res["variants"].items()}
        rep["variants_price"] = {v: metrics(t, "net_price") for v, t in res["variants"].items()}
        h = res["variants"]["HEDGE"]
        rep.update(metrics=rep["variants"]["HEDGE"], by_side=breakdown(h, "side"), by_session=breakdown(h, "session"), by_mode=breakdown(h, "mode"),
                   folds=folds(h), hedge_activation_share=(sum(1 for x in h if x.get("hedge_activations")) / max(1, len(h))),
                   variants_note="HEDGE vs NO_HEDGE vs REDUCE na tych samych setupach; automat wybiera wariant tylko przy n ≥ 30")
    rep["baseline"] = metrics(res["baseline"])
    rep["baseline_note"] = "naiwna reguła (co 60 min, kierunek ostatniej godziny), te same TP/SL/zarządzanie/koszty, bez filtra setupu"
    rep["limitations"] = ["tylko świece M1 (bez ticków): kolejność wewnątrz świecy konserwatywna, świece niejednoznaczne liczone jako SL",
                          "spread z kolumny spread świecy M1 (punkty) lub stała zastępcza; poślizg z profilu",
                          "prowizja " + ("uwzględniona" if first.get("commission_known") else "nieznana – nieuwzględniona (wynik zawyżony o prowizję)"),
                          "swap nieuwzględniony",
                          "parametry strategii nie były optymalizowane na tych danych (brak wielokrotnego użycia holdoutu)"]
    return rep
