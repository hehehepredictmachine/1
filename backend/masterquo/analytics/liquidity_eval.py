"""B0-B3 evaluation of the session / heatmap context (PMW-UPD-06 LS-10) on ONE baseline opportunity stream (scalp replay).

B0  unchanged baseline (all its valid opportunities)
B1  + session rejection context: SWEEP_LOW for BUY / SWEEP_HIGH for SELL of a FINAL box, swept edge <= 0.15 ATR(M5) from the setup
    reference price, event age <= 30 min, event available before the decision
B2  + estimated heatmap zone <= 0.15 ATR(M5) from the setup price - only with a VALIDATED mapping and a snapshot received before
    the decision (archive first_received_at); otherwise BLOCKED (MAPPING_UNVALIDATED / BLOCKED_NO_POINT_IN_TIME_HISTORY)
B3  B1 and B2
Each variant is a full chronological replay with the variant as a decision filter (a rejected opportunity frees the one-cycle /
cooldown slot), costs and exits of scalp/replay.py. Thresholds are fixed and versioned (no tuning here). Per-opportunity
expectancy counts a rejected opportunity as 0. Uncertainty: paired day-block bootstrap of daily net_R differences vs B0.
The last 20 % of calendar time is reported separately and reserved in the shared eval_ledger before it is read.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import session_engine as se

TASK_ID = "LIQUIDITY_CONTEXT_B0_B3"
PARAMS = {"near_atr": 0.15, "max_event_age_min": 30, "zone_quantile": 0.85, "profile": "SCALP_OPENING_V1", "version": "LIQ-EVAL-1.0.0"}
MIN_TRADES, MIN_DAYS = 100, 30


def _ts(s) -> float:
    return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()


def session_index(m1: list[dict], instrument: str, profile: str) -> list[dict]:
    """All boxes of the history computed once (prefix-invariant: at decision T only boxes known <= T and events available <= T)."""
    if not m1:
        return []
    t0, t1 = _ts(m1[0]["open_utc"]), _ts(m1[-1]["open_utc"]) + 60
    days = int((t1 - t0) // 86400) + 2
    return [b for b in se.build(m1, 60, profile, instrument, t1, days=days) if b["state"] == "FINAL"]


def b1_ok(boxes: list[dict], plan: dict, T: float, atr: float | None) -> bool:
    if not atr:
        return False
    want, edge_key = ("SWEEP_LOW", "final_low") if plan["direction"] == "BUY" else ("SWEEP_HIGH", "final_high")
    px = plan.get("ref_close_bid") or plan.get("sl")
    for b in boxes:
        if _ts(b["known_at"]) > T:
            continue
        for e in b["events"]:
            av = _ts(e["available_at"])
            if e["kind"] == want and av <= T and T - av <= PARAMS["max_event_age_min"] * 60 and abs(px - b[edge_key]) <= PARAMS["near_atr"] * atr:
                return True
    return False


def b2_ok(snap: dict | None, plan: dict, atr: float | None) -> bool:
    if not snap or not atr:
        return False
    px = plan.get("ref_close_bid")
    for z in (snap.get("zones") or {}).get("zones") or []:
        d = 0.0 if z["low"] <= px <= z["high"] else min(abs(px - z["low"]), abs(px - z["high"]))
        if d <= PARAMS["near_atr"] * atr:
            return True
    return False


def _boot_diff(days_a: dict, days_b: dict, reps=2000, seed=11) -> dict:
    keys = sorted(set(days_a) | set(days_b))
    if len(keys) < 5:
        return {"status": "INSUFFICIENT_DAYS", "days": len(keys)}
    diff = np.array([days_a.get(k, 0.0) - days_b.get(k, 0.0) for k in keys])
    rng = np.random.default_rng(seed)
    sims = [float(rng.choice(diff, size=len(diff), replace=True).mean()) for _ in range(reps)]
    return {"mean_daily_diff_r": float(diff.mean()), "ci95": [float(np.percentile(sims, 2.5)), float(np.percentile(sims, 97.5))], "days": len(keys)}


def _summ(cycles: list[dict], n_opp: int) -> dict:
    r = np.array([c["net_r"] for c in cycles]) if cycles else np.array([])
    eq = np.cumsum(r) if len(r) else np.array([0.0])
    dd = float(np.max(np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:] - eq)) if len(r) else 0.0
    by_day = {}
    for c in cycles:
        by_day[c["decision_time"][:10]] = by_day.get(c["decision_time"][:10], 0.0) + c["net_r"]
    return {"trades": len(cycles), "net_r_total": float(r.sum()) if len(r) else 0.0, "expectancy_per_trade": float(r.mean()) if len(r) else None,
            "expectancy_per_opportunity": float(r.sum() / n_opp) if n_opp else None, "max_drawdown_r": dd, "days": len(by_day),
            "by_side": {s: int(sum(1 for c in cycles if c["direction"] == s)) for s in ("BUY", "SELL")}, "_by_day": by_day}


def evaluate(inst: str, ds: Path, *, commission: float | None = None, db=None, liquidity=None, log=print) -> dict:
    from ..ml import scalp_task as stk
    from ..scalp import replay
    data = stk.build_dataset(inst, ds, commission, log)
    synthetic = data["data_kind"] != "REAL_USER_DATA"
    m1 = data["m1"]
    boxes = session_index(m1, inst, PARAMS["profile"])

    def atr_at(plan):
        return (plan.get("range") or {}).get("atr_m5")
    src = liquidity.cfg.sources.get(inst) if liquidity is not None else None
    mapping_ok = bool(src and src.mapping == "VALIDATED_BASIS")
    heat_status = ("MAPPING_UNVALIDATED" if src and src.source_symbol and not mapping_ok else "NO_SOURCE_FOR_INSTRUMENT" if not (src and src.source_symbol) else "OK")
    covered = 0

    def snap_at(T):
        nonlocal covered
        if not mapping_ok or liquidity is None:
            return None
        s = liquidity.as_of(inst, datetime.fromtimestamp(T, timezone.utc).isoformat())
        if s:
            covered += 1
        return s
    variants = {"B0": lambda p: True,
                "B1": lambda p: b1_ok(boxes, p, p["decision_ts"], atr_at(p)),
                "B2": lambda p: b2_ok(snap_at(p["decision_ts"]), p, atr_at(p)),
                "B3": lambda p: b1_ok(boxes, p, p["decision_ts"], atr_at(p)) and b2_ok(snap_at(p["decision_ts"]), p, atr_at(p))}
    t_all = [_ts(r["signal_time"]) for r in data["rows"]]
    cut = (min(t_all) + 0.8 * (max(t_all) - min(t_all))) if t_all else None
    rep = {"task_id": TASK_ID, "instrument": inst, "dataset_id": data["dataset_id"], "data_kind": data["data_kind"], "params": PARAMS, "profile_hash": data["profile_hash"],
           "costs": data["costs"], "precision": "OHLC_APPROX", "baseline_opportunities": len(data["rows"]), "session_boxes_final": len(boxes),
           "heatmap_status": heat_status, "variants": {}, "created_at": datetime.now(timezone.utc).isoformat(),
           "holdout_from": datetime.fromtimestamp(cut, timezone.utc).isoformat() if cut else None}
    if cut and db is not None:
        h0 = datetime.fromtimestamp(cut, timezone.utc).isoformat()
        rep["ledger"] = stk.reserve_holdout(db, inst, h0, data["rows"][-1]["label_end"], f"{PARAMS['version']}:{data['profile_hash']}", TASK_ID)
    n_opp = len(data["rows"])
    base_days = None
    for name, acc in variants.items():
        if name in ("B2", "B3") and not mapping_ok:
            rep["variants"][name] = {"status": "BLOCKED", "reason": heat_status + " – heatmapa obcego instrumentu bez zweryfikowanego mapowania nie jest oceniana na cenie brokera"}
            continue
        t0 = time.time()
        res = replay.run(m1, data["prof"], data["tick"], data["replay_costs"], accept=None if name == "B0" else acc)
        cyc = res["cycles"]
        full = _summ(cyc, n_opp)
        hold = _summ([c for c in cyc if cut is not None and _ts(c["decision_time"]) >= cut], sum(1 for t in t_all if cut is not None and t >= cut))
        v = {"full": {k: x for k, x in full.items() if not k.startswith("_")}, "holdout": {k: x for k, x in hold.items() if not k.startswith("_")},
             "rejected_by_variant": sum(1 for b in res["blocked"] if b.get("reason") == "ML_POLICY_REJECTED"), "seconds": round(time.time() - t0, 1)}
        if name == "B0":
            base_days = (full["_by_day"], hold["_by_day"])
        else:
            v["paired_vs_B0_full"] = _boot_diff(full["_by_day"], base_days[0])
            v["paired_vs_B0_holdout"] = _boot_diff(hold["_by_day"], base_days[1])
        if name in ("B2", "B3"):
            v["heatmap_coverage_decisions"] = covered
            if covered == 0:
                v["status"] = "BLOCKED_NO_POINT_IN_TIME_HISTORY"
        trades, days = v["holdout"]["trades"], v["holdout"]["days"]
        ci = (v.get("paired_vs_B0_holdout") or {}).get("ci95")
        v.setdefault("status", "FIXTURE_ONLY" if synthetic else "INSUFFICIENT_EVIDENCE" if trades < MIN_TRADES or days < MIN_DAYS else
                     "BASELINE" if name == "B0" else "LIMITED_POSITIVE_RESULT_THIS_PERIOD" if (ci and ci[0] > 0 and rep.get("ledger", {}).get("status") == "FRESH")
                     else "NO_VALIDATED_EDGE")
        rep["variants"][name] = v
        log(f"{name}: {v['full']['trades']} transakcji, net {v['full']['net_r_total']:.2f} R ({v['status']})")
    rep["note"] = ("Wynik dotyczy tego okresu i danych; nie promuje wariantu do LIVE ani nie zmienia bramek. Bez archiwum heatmapy otrzymanej przed "
                   "decyzjami B2/B3 pozostają zablokowane.")
    return rep


def save_report(rep: dict) -> Path:
    import mq_instruments
    d = mq_instruments.data_dir() / "liquidity" / "reports"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{rep['instrument']}_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json"
    p.write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    return p
