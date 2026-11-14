"""Replay and walk-forward validation of the 20 variants (PMW-SH-PACK-REPLAY-1) on an exported history - the SAME detectors, solver and
hedge policies as the live cycle, never a re-implementation.

* Data: a training export (source_metadata.json + <PREFIX>_<TF>.csv, the format of `sh train`) - M1 required; M3 / M5 / M15 / H1 from the
  export when present (NATIVE), else aggregated from COMPLETE M1 groups only (RESAMPLED; an incomplete group is dropped, never padded).
  Bars are broker chart prices (MT5: Bid); Ask = Bid + the bar's recorded spread (else the configured fallback) - historical bid/ask is
  not reconstructed beyond that, and the report says so.
* Causality: at every M1 close t the views show only bars CLOSED by t (features.Context.advance); a variant is evaluated when its own
  signal-TF bar closed at t. A READY plan is filled at the NEXT M1 open (BUY at Ask, SELL at Bid) plus the slippage assumption - never at
  the trigger close.
* Outcome on M1 bars, closing side (BUY on Bid, SELL on Ask): TP1 (50 %) then TP2 (50 %), SL, timeout at position_max_minutes. A bar that
  touches the stop AND a target is resolved STOP_FIRST (counted; sensitivity with the ambiguous trades excluded is reported). One open plan
  per variant x TF at a time.
* HEDGING: the variant policy (policies.decision) on the closed M5 after the fill -> hedge leg at the next M1 open, unwind / timeout /
  exit as the live basket. The same entries are also run as NO_HEDGE and as REDUCE (close the hedge ratio of the base instead, re-open it
  at the unwind) with the same data, decision times, costs and initial budget.
* Metrics in R of the plan's initial risk (r + C [+ bounded hedge loss]): expectancy with a day-block bootstrap 95 % interval, profit
  factor, win rate with a Wilson interval, average win / loss, max drawdown of the closed-trade R equity, holding time, path distribution,
  MAE / MFE, timeout / ambiguous counts, >= 3 chronological walk-forward segments, cost stress (extra slippage + spread).
* Verdict: VALIDATED only on REAL_USER_DATA with known commission, >= 200 OOS plans, >= 3 segments all positive, bootstrap lower bound
  > 0 and (HG) not dominated by REDUCE / NO_HEDGE; synthetic data -> NOT_VALIDATED; too few plans -> INSUFFICIENT_EVIDENCE; otherwise
  REJECTED_OOS. Parameters are NOT fitted here (fixed research starting values), so the whole replay range is out-of-sample for them;
  every variant x TF tried is listed (multiple testing is visible, no "best only" report).
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path

from ... import paths
from . import catalog as CAT
from . import features as F
from . import policies as POL
from .engine import PackEngine

TF_S = F.TF_S
VERSION = "PMW-SH-PACK-REPLAY-1"


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat().replace("+00:00", "Z")


def load(ds: Path, *, last_m1: int | None = None) -> tuple[dict, dict]:
    ds = Path(ds)
    meta = json.loads((ds / "source_metadata.json").read_text(encoding="utf-8"))
    pref = meta.get("file_prefix") or meta.get("instrument") or "XAUUSD"
    point = float((meta.get("spec") or {}).get("point") or meta.get("tick_size") or 0.01)
    out, src = {}, {}
    for tf in ("M1", "M3", "M5", "M15", "H1"):
        p = ds / f"{pref}_{tf}.csv"
        if not p.exists():
            continue
        rows = []
        with p.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                sp = r.get("spread_points")
                tv = r.get("tick_volume") or r.get("tv") or 0
                t = r.get("time_open_utc") or r.get("open_utc")
                rows.append({"open_utc": t, "o": float(r["open"]), "h": float(r["high"]), "l": float(r["low"]), "c": float(r["close"]),
                             "tv": float(tv or 0), "spread_price": float(sp) * point if sp not in (None, "") else None, "closed": True})
        out[tf], src[tf] = rows, "NATIVE"
    if "M1" not in out:
        raise ValueError("DATASET_WITHOUT_M1")
    if last_m1 and len(out["M1"]) > last_m1:
        t0 = F.ts(out["M1"][-last_m1]["open_utc"])
        out["M1"] = out["M1"][-last_m1:]
        for tf in ("M3", "M5", "M15", "H1"):
            if tf in out:
                out[tf] = [b for b in out[tf] if F.ts(b["open_utc"]) >= t0 - 1100 * TF_S[tf]]
    for tf in ("M3", "M5", "M15", "H1"):
        if tf not in out:
            out[tf], src[tf] = aggregate(out["M1"], TF_S[tf]), "RESAMPLED_FROM_M1"
    meta["tf_sources"] = src
    return out, meta


def aggregate(m1: list[dict], sec: int) -> list[dict]:
    """Complete groups only: k = sec/60 consecutive M1 bars inside one bucket, else the bucket is dropped (never padded)."""
    k = sec // 60
    out, cur, cnt = [], None, 0
    for b in m1:
        t = F.ts(b["open_utc"])
        slot = t - (t % sec)
        if cur is None or cur["_slot"] != slot:
            if cur is not None and cnt == k:
                out.append(cur)
            cur, cnt = {"_slot": slot, "open_utc": _iso(slot), "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "tv": b.get("tv") or 0,
                        "closed": True, "source": "resampled", "complete": True}, 1
        else:
            cur.update(h=max(cur["h"], b["h"]), l=min(cur["l"], b["l"]), c=b["c"], tv=cur["tv"] + (b.get("tv") or 0))
            cnt += 1
    if cur is not None and cnt == k:
        out.append(cur)
    for x in out:
        x.pop("_slot", None)
    return out


class _Spec:
    def __init__(self, tick, mpp=None, symbol="XAUUSD", point=None):
        self.tick_size, self.symbol, self.currency_profit, self.point, self.digits = tick, symbol, "USD", point or tick, 2
        self._mpp = mpp

    def money_per_price(self, v):
        if not self._mpp:
            raise ValueError("TICK_VALUE_UNKNOWN")
        return self._mpp * v


# ---------------------------------------------------------------------------------------------------------- trade simulation
def _px_close(bar, side, sp, which):
    """Closing-side price extremes / close of an M1 bar: BUY closes on Bid (bar prices), SELL on Ask (bar + spread)."""
    add = 0.0 if side == "BUY" else sp
    return {"h": bar["h"] + add, "l": bar["l"] + add, "o": bar["o"] + add, "c": bar["c"] + add}[which]


def simulate(m1: list[dict], j_entry: int, su: dict, *, spread_fb: float, slip: float, c_rt: float, max_minutes: float,
             hedge_ctx: dict | None = None, mode: str = "HEDGE") -> dict | None:
    """One plan from the open of m1[j_entry]. Units: price per 1.0 base volume; result in R of the plan's initial risk."""
    if j_entry >= len(m1):
        return None
    side = su["side"]
    sg = 1 if side == "BUY" else -1
    b0 = m1[j_entry]
    sp0 = b0.get("spread_price") if b0.get("spread_price") is not None else spread_fb
    fill = (b0["o"] + sp0 + slip) if side == "BUY" else (b0["o"] - slip)
    sl, tp1, tp2 = su["sl"], su["tps"][0]["price"], su["tps"][1]["price"]
    econ = su["pack"]["economics"]
    hl = float(econ.get("hedge_loss_bound_price") or 0.0) if hedge_ctx else 0.0
    r_plan = abs(su["entry_ref"] - sl)
    R = r_plan + c_rt + hl
    if sg * (fill - sl) <= 0 or sg * (tp1 - fill) <= 0:
        return {"path": "ENTRY_ABORT", "end": "ENTRY_ABORT", "net_r": -(c_rt + sp0) / R, "minutes": 0.0, "ambiguous": False, "entry_fill": fill,
                "t_entry": b0["open_utc"], "day": b0["open_utc"][:10], "mae_r": 0.0, "mfe_r": 0.0, "activations": 0, "hedge_price": 0.0, "R_price": R}
    rem, w = 1.0, [0.5, 0.5]
    realized, path = 0.0, []
    mae = mfe = 0.0
    t0 = F.ts(b0["open_utc"])
    amb = False
    hedge = None                       # {"vol", "entry", "opened_at"}
    hedge_pnl = 0.0
    reduce_off = None                  # REDUCE: base volume temporarily closed {"vol", "price"}
    activations = 0
    extra_vol = 0.0                    # hedge / reduce volume (its own round-trip costs)
    pstate: dict = {}
    m5_hist = hedge_ctx["m5"] if hedge_ctx else None
    last_m5_close = None
    end_reason = None
    for j in range(j_entry, len(m1)):
        bar = m1[j]
        sp = bar.get("spread_price") if bar.get("spread_price") is not None else spread_fb
        tb = F.ts(bar["open_utc"])
        if (tb - t0) / 60.0 >= max_minutes:
            px = _px_close(bar, side, sp, "o")
            realized += rem * sg * (px - fill) - rem * 0.0
            path.append("TIMEOUT")
            end_reason = "TIMEOUT"
            if hedge:
                hp = bar["o"] + (sp if side == "BUY" else 0.0)                   # hedge (opposite side) closes on the other quote
                hedge_pnl += -sg * (hp - hedge["entry"]) * hedge["vol"]
                hedge = None
            rem = 0.0
            break
        hi, lo = _px_close(bar, side, sp, "h"), _px_close(bar, side, sp, "l")
        fav, adv = (hi, lo) if side == "BUY" else (lo, hi)
        mfe = max(mfe, sg * (fav - fill))
        mae = max(mae, -sg * (adv - fill))
        stop = (lo <= sl) if side == "BUY" else (hi >= sl)
        t1 = rem > 0.5 + 1e-9 and ((hi >= tp1) if side == "BUY" else (lo <= tp1))
        t2 = (hi >= tp2) if side == "BUY" else (lo <= tp2)
        if stop and (t1 or t2):
            amb = True                                                    # STOP_FIRST: the conservative order
        if stop:
            o = _px_close(bar, side, sp, "o")
            px = min(o, sl) if side == "BUY" else max(o, sl)               # a gap fills beyond the stop, never better
            realized += rem * sg * (px - fill)
            path.append("SL")
            end_reason = "SL"
            rem = 0.0
            if hedge:
                hp = sl + (sp if side == "BUY" else -sp)
                hedge_pnl += -sg * (hp - hedge["entry"]) * hedge["vol"]
                hedge = None
            break
        if t1:
            realized += w[0] * sg * (tp1 - fill)
            rem -= w[0]
            path.append("TP1")
            if hedge and hedge["vol"] > 0.5 * rem + 1e-9:                    # ratio cap after the partial
                cut = hedge["vol"] - 0.5 * rem
                hp = tp1 + (sp if side == "BUY" else -sp)
                hedge_pnl += -sg * (hp - hedge["entry"]) * cut
                hedge["vol"] -= cut
        if t2:
            realized += rem * sg * (tp2 - fill)
            path.append("TP2")
            end_reason = "TP2"
            rem = 0.0
            if hedge:
                hp = tp2 + (sp if side == "BUY" else -sp)
                hedge_pnl += -sg * (hp - hedge["entry"]) * hedge["vol"]
                hedge = None
            break
        # ---- hedge policy on M5 closes (HEDGING variants)
        if hedge_ctx is not None and mode in ("HEDGE", "REDUCE"):
            tc = tb + 60
            k5 = hedge_ctx["m5_idx"](tc)
            if k5 != last_m5_close and k5 > 0:
                last_m5_close = k5
                m5b = m5_hist[max(0, k5 - 700):k5]
                q = {"bid": bar["c"], "ask": bar["c"] + sp}
                dec = POL.decision(su["strategy_id"], plan={"pack": {**su["pack"], "hedge": hedge_ctx["hcfg"], "params": su["pack"].get("params")}},
                                   st=su["pack"].get("structure_view") or {}, pstate=pstate, m5_bars=m5b,
                                   h1_bars=hedge_ctx["h1"](tc), quote=q, now=tc,
                                   primary={"side": side, "entry": fill, "sl": sl, "remaining": rem, "volume": 1.0, "opened_at": t0},
                                   hedged=bool(hedge or reduce_off), hedge_opened_at=(hedge or reduce_off or {}).get("opened_at"),
                                   activations=activations, tick=hedge_ctx["tick"], common=hedge_ctx["common"])
                nxt = m1[j + 1] if j + 1 < len(m1) else bar
                spn = nxt.get("spread_price") if nxt.get("spread_price") is not None else spread_fb
                if dec["decision"] == "EXIT":
                    px = _px_close(nxt, side, spn, "o")
                    realized += rem * sg * (px - fill)
                    if hedge:
                        hp = nxt["o"] + (spn if side == "BUY" else 0.0)
                        hedge_pnl += -sg * (hp - hedge["entry"]) * hedge["vol"]
                        hedge = None
                    if reduce_off:
                        reduce_off = None
                    rem = 0.0
                    path.append("BASKET_EXIT")
                    end_reason = "BASKET_EXIT"
                    break
                if dec["decision"] == "HEDGE" and activations == 0:
                    activations = 1
                    vol = min(float(dec.get("ratio") or 0.5), 0.5) * rem
                    extra_vol += vol
                    if mode == "HEDGE":
                        hp = nxt["o"] + (0.0 if side == "BUY" else spn) - sg * slip      # opposite side opens on the other quote
                        hedge = {"vol": vol, "entry": hp, "opened_at": tc}
                        path.append("HEDGE")
                    else:
                        px = _px_close(nxt, side, spn, "o")
                        realized += vol * sg * (px - fill)
                        rem -= vol
                        reduce_off = {"vol": vol, "price": px, "opened_at": tc}
                        path.append("REDUCE")
                elif dec["decision"] == "UNWIND":
                    if hedge:
                        hp = nxt["o"] + (spn if side == "BUY" else 0.0)
                        hedge_pnl += -sg * (hp - hedge["entry"]) * hedge["vol"]
                        hedge = None
                        path.append("UNWIND")
                    elif reduce_off:                                     # REDUCE re-opens the same volume by the same rule
                        px = (nxt["o"] + spn) if side == "BUY" else nxt["o"]
                        realized -= reduce_off["vol"] * sg * (px - fill)   # new part entered at px instead of fill: account the difference
                        rem += reduce_off["vol"]
                        reduce_off = None
                        path.append("REOPEN")
    if rem > 1e-9:                                                       # data ended: close at the last close
        bar = m1[-1]
        sp = bar.get("spread_price") if bar.get("spread_price") is not None else spread_fb
        realized += rem * sg * (_px_close(bar, side, sp, "c") - fill)
        end_reason = end_reason or "DATA_END"
    cost = c_rt * (1.0 + extra_vol)
    net = realized + hedge_pnl - cost
    t_end = F.ts(m1[min(j, len(m1) - 1)]["open_utc"])
    return {"path": "→".join(path) or end_reason, "end": end_reason, "net_r": net / R, "gross_price": realized, "hedge_price": hedge_pnl,
            "ambiguous": amb, "mae_r": mae / R, "mfe_r": mfe / R, "minutes": (t_end - t0) / 60.0, "entry_fill": fill, "t_entry": b0["open_utc"],
            "day": b0["open_utc"][:10], "activations": activations, "R_price": R}


# ---------------------------------------------------------------------------------------------------------- statistics
def wilson(k: int, n: int, z: float = 1.96) -> tuple[float | None, float | None]:
    if n == 0:
        return None, None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return round(c - h, 4), round(c + h, 4)


def stats(trades: list[dict], seed: int = 7, boot: int = 1000) -> dict:
    xs = [t["net_r"] for t in trades]
    n = len(xs)
    if not n:
        return {"n": 0}
    wins = [x for x in xs if x > 0]
    loss = [x for x in xs if x <= 0]
    eq, peak, dd = 0.0, 0.0, 0.0
    for x in xs:
        eq += x
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    days: dict = {}
    for t in trades:
        days.setdefault(t["day"], []).append(t["net_r"])
    blocks = list(days.values())
    rnd = random.Random(seed)
    bs = []
    for _ in range(boot if len(blocks) >= 5 else 0):
        smp = [x for _ in blocks for x in rnd.choice(blocks)]
        bs.append(sum(smp) / len(smp))
    bs.sort()
    paths: dict = {}
    for t in trades:
        paths[t["end"] or "?"] = paths.get(t["end"] or "?", 0) + 1
    seg = max(3, 3)
    size = max(1, n // seg)
    segs = [xs[i * size:(i + 1) * size if i < seg - 1 else n] for i in range(seg)] if n >= seg else []
    return {"n": n, "expectancy_r": round(sum(xs) / n, 4), "profit_factor": round(sum(wins) / -sum(loss), 3) if loss and sum(loss) < 0 else None,
            "win_rate": round(len(wins) / n, 4), "win_rate_ci95": wilson(len(wins), n), "avg_win_r": round(sum(wins) / len(wins), 4) if wins else None,
            "avg_loss_r": round(sum(loss) / len(loss), 4) if loss else None, "max_drawdown_r": round(dd, 3),
            "expectancy_ci95_day_block": [round(bs[int(0.025 * len(bs))], 4), round(bs[int(0.975 * len(bs)) - 1], 4)] if bs else None,
            "avg_minutes": round(sum(t["minutes"] for t in trades) / n, 1), "ambiguous_stop_first": sum(1 for t in trades if t["ambiguous"]),
            "expectancy_ex_ambiguous": round(sum(t["net_r"] for t in trades if not t["ambiguous"]) / max(1, sum(1 for t in trades if not t["ambiguous"])), 4),
            "mae_r_avg": round(sum(t["mae_r"] for t in trades) / n, 3), "mfe_r_avg": round(sum(t["mfe_r"] for t in trades) / n, 3),
            "paths": paths, "segments": [{"n": len(s), "expectancy_r": round(sum(s) / len(s), 4)} for s in segs if s],
            "days": len(days)}


def verdict(st: dict, *, real: bool, commission_known: bool, hedge_cmp: dict | None, min_n: int = 200) -> tuple[str, str]:
    if not real:
        return "NOT_VALIDATED", "dane nie są historią MT5 użytkownika (REAL_USER_DATA) – wynik wyłącznie techniczny"
    if st.get("n", 0) < min_n:
        return "INSUFFICIENT_EVIDENCE", f"{st.get('n', 0)} zakończonych planów OOS < {min_n}"
    if not commission_known:
        return "INSUFFICIENT_EVIDENCE", "prowizja nieznana – wynik netto niepełny"
    segs = st.get("segments") or []
    ci = st.get("expectancy_ci95_day_block")
    if len(segs) < 3 or any(s["expectancy_r"] <= 0 for s in segs):
        return "REJECTED_OOS", "nie wszystkie odcinki walk-forward mają dodatnią wartość oczekiwaną"
    if not ci or ci[0] <= 0:
        return "REJECTED_OOS", "dolna granica bootstrapu (bloki dzienne) ≤ 0"
    if hedge_cmp and hedge_cmp.get("dominated_by"):
        return "REJECTED_OOS", f"wariant HEDGE zdominowany przez {hedge_cmp['dominated_by']} przy tych samych wejściach"
    return "VALIDATED", "dodatnia i stabilna przewaga OOS po kosztach (warunek konieczny – nie gwarancja przyszłych wyników)"


# ---------------------------------------------------------------------------------------------------------- driver
def run(bars: dict, meta: dict, *, variants: list[str] | None = None, tfs_only: list[str] | None = None, spread_fallback: float = 0.20,
        slip: float = 0.05, commission_price_rt: float | None = None, stress: tuple = (0.20, 0.10), progress=None, warm_m1: int = 1200,
        garch: dict | None = None) -> dict:
    cfg = CAT.load()
    tick = float((meta.get("spec") or {}).get("trade_tick_size") or (meta.get("spec") or {}).get("point") or meta.get("tick_size") or 0.01)
    spec = _Spec(tick, symbol=meta.get("symbol") or "XAUUSD")
    X = F.Context(bars, tick=tick, common=cfg["common"], as_of=F.ts(bars["M1"][0]["open_utc"]), symbol=spec.symbol, instrument=meta.get("instrument") or "XAUUSD")
    X.advance(X.as_of)
    X.garch = garch                                                         # HG09 VOL_GARCH: frozen artifact parameters (else NO_DATA)
    eng = PackEngine()
    pipdef = (cfg["instruments"] or {}).get(meta.get("instrument") or "XAUUSD")
    ic = {"slippage_usd": slip, "commission_per_lot_side": None}
    c_rt = 2 * slip + (commission_price_rt if commission_price_rt is not None else float(cfg["common"].get("commission_scenario_price_rt", 0.10)))
    m1 = bars["M1"]
    m5_full = bars["M5"]
    m5_close = [F.ts(b["open_utc"]) + 300 for b in m5_full]
    import bisect
    m5_idx = lambda t: bisect.bisect_right(m5_close, t + 1e-6)  # noqa: E731 - number of M5 bars closed by t
    h1_full = bars["H1"]
    h1_close = [F.ts(b["open_utc"]) + 3600 for b in h1_full]
    h1_upto = lambda t: h1_full[max(0, bisect.bisect_right(h1_close, t + 1e-6) - 1050):bisect.bisect_right(h1_close, t + 1e-6)]  # noqa: E731
    vids = [v for v in (variants or list(CAT.IDS)) if v in cfg["variants"]]
    busy: dict = {}
    trades: dict = {}
    counts: dict = {}
    t_start = time.time()
    n = len(m1)
    for j in range(min(warm_m1, n - 1), n - 1):
        t = F.ts(m1[j]["open_utc"]) + 60
        X.advance(t)
        bar = m1[j]
        sp = bar.get("spread_price") if bar.get("spread_price") is not None else spread_fallback
        q = {"bid": bar["c"], "ask": bar["c"] + sp, "spread": sp, "age_s": 0.0}
        for vid in vids:
            v = cfg["variants"][vid]
            for tf in v["signal_tfs"]:
                if tfs_only and tf not in tfs_only:
                    continue
                if int(t) % TF_S[tf] != 0:
                    continue                                     # evaluated only when its own signal-TF bar closed at t
                key = (vid, tf)
                if busy.get(key, 0) > t:
                    continue
                eng.active.clear()
                su = eng._one(X, v, tf, X.instrument, spec, ic, q, t, pipdef, cfg, None, "USD")
                c = counts.setdefault(f"{vid}|{tf}", {})
                code = (su.get("pack") or {}).get("reason_code") or su["status"]
                c[f"{su['status']}:{code}"] = c.get(f"{su['status']}:{code}", 0) + 1
                if su["status"] != "READY":
                    continue
                hctx = None
                if v["family"] == "HEDGING":
                    hctx = {"m5": m5_full, "m5_idx": m5_idx, "h1": h1_upto, "hcfg": v["hedge"] or {}, "tick": tick, "common": cfg["common"]}
                res = {}
                for mode in (("HEDGE", "NO_HEDGE", "REDUCE") if hctx else ("PLAN",)):
                    r = simulate(m1, j + 1, su, spread_fb=spread_fallback, slip=slip, c_rt=c_rt, max_minutes=v["position_max_minutes"],
                                 hedge_ctx=hctx if mode in ("HEDGE", "REDUCE") else None, mode=mode)
                    if r is None:
                        continue
                    rs = simulate(m1, j + 1, su, spread_fb=spread_fallback + stress[0], slip=slip + stress[1], c_rt=c_rt + 2 * stress[1],
                                  max_minutes=v["position_max_minutes"], hedge_ctx=hctx if mode in ("HEDGE", "REDUCE") else None, mode=mode)
                    r["stress_net_r"] = rs["net_r"] if rs else None
                    r.update(signal_id=su["signal_id"], side=su["side"], rr_plan_net=su["pack"]["economics"].get("rr_plan_net"),
                             rr_basket=su["pack"]["economics"].get("rr_basket_net_target"))
                    res[mode] = r
                if not res:
                    continue
                main = res.get("HEDGE") or res.get("PLAN")
                busy[key] = t + 60 * max(1.0, main["minutes"]) + 60
                for mode, r in res.items():
                    trades.setdefault(f"{vid}|{tf}|{mode}", []).append(r)
        if progress and j % 500 == 0:
            progress(j, n)
    real = meta.get("data_kind") == "REAL_USER_DATA"
    comm_known = commission_price_rt is not None
    out = {"schema": VERSION, "created_at": _iso(time.time()), "dataset": meta.get("dataset_id") or meta.get("source"), "data_kind": meta.get("data_kind"),
           "instrument": meta.get("instrument") or "XAUUSD", "symbol": meta.get("symbol"), "tf_sources": meta.get("tf_sources"),
           "m1_bars": n, "first": m1[0]["open_utc"], "last": m1[-1]["open_utc"], "pack_version": cfg["pack_version"], "pack_hash": cfg["hash"],
           "costs": {"c_round_trip_price": c_rt, "commission": "znana (parametr)" if comm_known else "scenariusz (nieznana)", "slippage_price": slip,
                     "spread": "z kolumny spread świecy" if any(b.get("spread_price") is not None for b in m1[:50]) else f"założenie {spread_fallback}",
                     "stress": {"extra_spread": stress[0], "extra_slippage": stress[1]}},
           "ambiguous_policy": "STOP_FIRST (wrażliwość: wynik bez niejednoznacznych świec w statystykach)",
           "fill_rule": "następne otwarcie M1 po zamknięciu triggera; BUY po Ask (Bid + spread), SELL po Bid",
           "multiple_testing": f"{len(vids)} wariantów × TF – wszystkie raportowane; DSR/PBO wymagają większej liczby niezależnych prób",
           "seconds": round(time.time() - t_start, 1), "variants": {}}
    for vid in vids:
        v = cfg["variants"][vid]
        for tf in v["signal_tfs"]:
            if tfs_only and tf not in tfs_only:
                continue
            key = f"{vid}|{tf}"
            row = {"counts": counts.get(key, {})}
            if v["family"] == "HEDGING":
                modes = {m: stats(trades.get(f"{key}|{m}", [])) for m in ("HEDGE", "NO_HEDGE", "REDUCE")}
                e = {m: (s.get("expectancy_r") if s.get("n") else None) for m, s in modes.items()}
                dom = None
                if e["HEDGE"] is not None:
                    better = [m for m in ("REDUCE", "NO_HEDGE") if e[m] is not None and e[m] > e["HEDGE"] and
                              (modes[m].get("max_drawdown_r") or -1e9) >= (modes["HEDGE"].get("max_drawdown_r") or -1e9)]
                    dom = better[0] if better else None
                row.update(modes=modes, hedge_comparison={"expectancy": e, "dominated_by": dom,
                                                          "activations": sum(t.get("activations", 0) for t in trades.get(f"{key}|HEDGE", [])),
                                                          "hedge_pnl_price": round(sum(t.get("hedge_price", 0) for t in trades.get(f"{key}|HEDGE", [])), 4)})
                main = modes["HEDGE"]
                vd, why = verdict(main, real=real, commission_known=comm_known, hedge_cmp=row["hedge_comparison"])
            else:
                main = stats(trades.get(f"{key}|PLAN", []))
                row["metrics"] = main
                vd, why = verdict(main, real=real, commission_known=comm_known, hedge_cmp=None)
            st = [x.get("stress_net_r") for x in trades.get(f"{key}|{'HEDGE' if v['family'] == 'HEDGING' else 'PLAN'}", []) if x.get("stress_net_r") is not None]
            row["stress_expectancy_r"] = round(sum(st) / len(st), 4) if st else None
            row["verdict"], row["verdict_reason"] = vd, why
            out["variants"][key] = row
    out["report_id"] = "PKR-" + hashlib.sha256(json.dumps([out["dataset"], out["first"], out["last"], out["pack_hash"]], default=str).encode()).hexdigest()[:12]
    return out


def write(rep: dict) -> dict:
    """Run report -> data/sh/pack_validation/runs/; on REAL_USER_DATA also the per-variant status file read by the catalog (the best TF is
    NOT picked after the fact: a variant is VALIDATED only if every enabled signal TF of it is)."""
    d = paths.data_dir() / "sh" / "pack_validation"
    (d / "runs").mkdir(parents=True, exist_ok=True)
    p = d / "runs" / f"{rep['report_id']}.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(rep, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    os.replace(tmp, p)
    written = []
    if rep.get("data_kind") == "REAL_USER_DATA":
        by: dict = {}
        for key, row in rep["variants"].items():
            by.setdefault(key.split("|")[0], []).append(row)
        for vid, rows in by.items():
            vds = [r["verdict"] for r in rows]
            vd = "VALIDATED" if all(x == "VALIDATED" for x in vds) else ("REJECTED_OOS" if "REJECTED_OOS" in vds else "INSUFFICIENT_EVIDENCE")
            obj = {"strategy_id": vid, "verdict": vd, "verdict_reason": "; ".join(f"{k}: {r['verdict_reason']}" for k, r in zip(vds, rows))[:600],
                   "report_id": rep["report_id"], "data_kind": rep["data_kind"], "created_at": rep["created_at"]}
            q = d / f"{vid}.json"
            q.write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")
            written.append(str(q))
    return {"report": str(p), "variant_files": written}
