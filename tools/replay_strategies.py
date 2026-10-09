"""Chronological replay / research runner for S01-S10 (profile ACTIVE) and the ORIGINAL M07 path.

Data:   --csv-dir DIR   files D1.csv..M1.csv from `python -m masterquo export` (UTC, available_at_utc)
        --synthetic N   N days from the built-in terminal simulator (labelled SYNTHETIC in every output)
Method (fixed BEFORE looking at results; see docs/RAPORT_TESTOW.md):
  * steps at every close of --step-tf (default M15); at time t only bars with available_at <= t are visible
    (the closed-bar replay never uses the forming bar - conservative vs live, which may show EARLY sooner)
  * the same scanner/tracker/selector code as the live monitor (strategies/registry, tracker, selector)
  * every first CONFIRMED setup is simulated: entry at the OPEN of the next M5 bar after the signal
    (Bid bars: LONG pays the spread), slippage added against the trade, commission per side;
    SL/targets/time exit from the setup; if one M5 bar touches SL and a target, SL is assumed first
    (OHLC does not reveal the intrabar order - conservative rule); TP1 partial then SL to break-even
  * results in R (initial risk), net of costs; chronological split DEV 60% / VAL 20% / OOS 20% by signal time
  * portfolio = only the AUTO-selected setup, one position at a time, common to all strategies
Ten strategies x variants form a multiple-testing problem: a good DEV number is not evidence; the OOS
segment must not be used for tuning. Synthetic data proves only that the pipeline runs.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import tempfile
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from masterquo.config import AppConfig  # noqa: E402
from masterquo.db.database import Database  # noqa: E402
from masterquo.strategies import adapter, registry  # noqa: E402
from masterquo.strategies.base import TF_SECONDS  # noqa: E402
from masterquo.strategies.selector import StrategyAutoSelector  # noqa: E402
from masterquo.strategies.tracker import SetupTracker  # noqa: E402

UTC = timezone.utc
TFS = ("M1", "M5", "M15", "H1", "H4", "D1")


def iso(t: datetime) -> str:
    return t.isoformat().replace("+00:00", "Z")


def p(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


# ----------------------------------------------------------------------------- data
def load_csv(d: Path) -> tuple[dict, str]:
    out = {}
    for tf in TFS:
        f = d / f"{tf}.csv"
        rows = []
        if f.exists():
            with f.open(encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    rows.append({"open_utc": r["time_utc"], "o": float(r["open"]), "h": float(r["high"]), "l": float(r["low"]), "c": float(r["close"]),
                                 "available_at": r["available_at_utc"], "spread_points": int(r.get("spread_points") or 0), "closed": True})
        out[tf] = rows
    return out, "BROKER_CSV"


def load_synthetic(days: int, seed: int) -> tuple[dict, str]:
    from masterquo.mt5 import fake as F
    fk = F.FakeMT5(seed=seed)
    off = fk.offset
    raw_now = int(fk._raw_now()) // 3600 * 3600
    codes = {"M1": F.TIMEFRAME_M1, "M5": F.TIMEFRAME_M5, "M15": F.TIMEFRAME_M15, "H1": F.TIMEFRAME_H1, "H4": F.TIMEFRAME_H4, "D1": F.TIMEFRAME_D1}
    start = raw_now - (days + 60) * 86400
    out = {}
    for tf, code in codes.items():
        r = fk._rates(code, raw_now)
        rows = []
        for x in r:
            t = int(x["time"])
            if t < start:
                continue
            op = datetime.fromtimestamp(t - off, UTC)
            rows.append({"open_utc": iso(op), "o": float(x["open"]), "h": float(x["high"]), "l": float(x["low"]), "c": float(x["close"]),
                         "available_at": iso(op + timedelta(seconds=TF_SECONDS[tf])), "spread_points": 12, "closed": True})
        out[tf] = rows[:-1]
    return out, "SYNTHETIC"


# ----------------------------------------------------------------------------- simulation
def simulate(setup: dict, signal_t: datetime, m5: list[dict], m5_index: dict, cost: dict) -> dict | None:
    d = setup["direction"]
    sl = setup["stop_loss"]
    tg = setup.get("targets") or []
    if sl is None or not tg:
        return {"status": "NO_LEVELS"}
    # first M5 bar opening at/after the signal time
    import bisect
    k = bisect.bisect_left(m5_index["times"], signal_t)
    if k >= len(m5):
        return None
    b = m5[k]
    spread = cost["spread"]
    entry = b["o"] + (spread if d == "LONG" else 0.0) + (cost["slip"] if d == "LONG" else -cost["slip"])
    risk = (entry - sl) if d == "LONG" else (sl - entry)
    if risk <= 0:
        return {"status": "ENTRY_BEYOND_STOP"}
    tf_s = TF_SECONDS[setup["timeframe"]]
    max_bars = max(1, int((setup.get("exit_rules") or {}).get("time_exit_bars", 24) * tf_s / 300))
    remaining = 1.0
    pnl = 0.0
    stop = sl
    mae = mfe = 0.0
    tps = [(t["price"], t["weight"]) for t in tg]
    held = 0
    exit_reason = "TIME"
    for j in range(k, min(len(m5), k + max_bars)):
        bb = m5[j]
        held += 1
        hi_exec = bb["h"] + (0 if d == "LONG" else spread)          # SHORT exits at Ask
        lo_exec = bb["l"] + (0 if d == "LONG" else spread)
        fav = (bb["h"] - entry) if d == "LONG" else (entry - lo_exec)
        adv = (entry - bb["l"]) if d == "LONG" else (hi_exec - entry)
        mfe, mae = max(mfe, fav / risk), max(mae, adv / risk)
        stop_hit = bb["l"] <= stop if d == "LONG" else hi_exec >= stop
        if stop_hit:                                               # conservative: stop before any target in the same bar
            pnl += remaining * (((stop - entry) if d == "LONG" else (entry - stop)) - cost["slip"])
            remaining = 0
            exit_reason = "STOP" if stop == sl else "BREAKEVEN"
            break
        while tps and ((d == "LONG" and bb["h"] >= tps[0][0]) or (d == "SHORT" and lo_exec <= tps[0][0])):
            price, w = tps.pop(0)
            w = min(w, remaining)
            pnl += w * ((price - entry) if d == "LONG" else (entry - price))
            remaining -= w
            if (setup.get("exit_rules") or {}).get("be_after_tp1", True):
                stop = entry
            if remaining <= 1e-9:
                exit_reason = "TARGETS"
                break
        if remaining <= 1e-9:
            break
    if remaining > 1e-9:                                           # time exit at the last bar close (SHORT buys back at Ask)
        last = m5[min(len(m5) - 1, k + held - 1)]
        pnl += remaining * ((last["c"] - entry) if d == "LONG" else (entry - (last["c"] + spread)))
    pnl -= 2 * cost["commission"]
    return {"status": "CLOSED", "r": round(pnl / risk, 4), "mae_r": round(mae, 3), "mfe_r": round(mfe, 3), "held_m5": held, "exit": exit_reason,
            "entry_time": b["open_utc"], "risk_price": round(risk, 4)}


def stats(trades: list[dict]) -> dict:
    rs = [t["r"] for t in trades if t.get("status") == "CLOSED"]
    if not rs:
        return {"trades": 0, "note": "brak danych (0 transakcji) - to nie jest wynik zero ani PASS"}
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    eq, peak, dd = 0.0, 0.0, 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return {"trades": len(rs), "expectancy_r": round(sum(rs) / len(rs), 3), "total_r": round(sum(rs), 2),
            "profit_factor": round(sum(wins) / -sum(losses), 2) if losses and sum(losses) < 0 else None,
            "win_rate": f"{len(wins)}/{len(rs)} ({100 * len(wins) / len(rs):.0f}%)", "max_drawdown_r": round(dd, 2),
            "avg_mae_r": round(sum(t["mae_r"] for t in trades if t.get("status") == "CLOSED") / len(rs), 2),
            "avg_mfe_r": round(sum(t["mfe_r"] for t in trades if t.get("status") == "CLOSED") / len(rs), 2),
            "avg_hold_m5_bars": round(sum(t["held_m5"] for t in trades if t.get("status") == "CLOSED") / len(rs), 1)}


# ----------------------------------------------------------------------------- replay
def run(data: dict, source: str, step_tf: str, cost: dict, compare_original: bool, max_steps: int | None) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="mq_replay_"))
    db = Database(tmp / "replay.sqlite")
    tr, sel = SetupTracker(db), StrategyAutoSelector(db)
    cfg = AppConfig().active
    steps = [p(b["available_at"]) for b in data[step_tf]]
    steps = [t for t in steps if t >= steps[0] + timedelta(days=45)] if steps else []     # warm-up for D1/H4 context
    if max_steps:
        steps = steps[:max_steps]
    ptr = {tf: 0 for tf in TFS}
    seen: dict[str, dict] = {}
    first_stage: dict[str, dict] = {}
    confirmed: list[tuple] = []
    selected_confirmed: list[tuple] = []
    event_groups: dict[str, set] = defaultdict(set)
    funnel = defaultdict(Counter)
    regimes = Counter()
    terminal = Counter()
    sel_changes = 0
    prev_sel = None
    t0 = time.time()
    m5 = data["M5"]
    m5_index = {"times": [p(b["open_utc"]) for b in m5]}
    for t in steps:
        for tf in TFS:
            rows = data[tf]
            while ptr[tf] < len(rows) and p(rows[ptr[tf]]["available_at"]) <= t:
                ptr[tf] += 1
        bars = {tf: data[tf][max(0, ptr[tf] - 400):ptr[tf]] for tf in TFS if ptr[tf] > 0}
        last = bars.get("M1") or bars.get("M5")
        if not last:
            continue
        sp = cost["spread"]
        view = adapter.build_view(symbol="XAUUSD-", bars_by_tf=bars, bid=last[-1]["c"], ask=last[-1]["c"] + sp, point=0.01, as_of=iso(t),
                                  synthetic=source == "SYNTHETIC", regime_params=cfg.regime)
        regimes[view.regime["state"]] += 1
        res = registry.scan(view, enabled={}, overrides={}, thresholds=cfg.thresholds.model_dump(), account_key="replay")
        for sid, ps in res["per_strategy"].items():
            funnel[sid]["drafts"] += ps.get("drafts", 0)
            funnel[sid]["below_watch"] += ps.get("below_watch", 0)
            for stg, n in (ps.get("published") or {}).items():
                funnel[sid]["published_" + stg] += n
        events = tr.update(res["candidates"], view=view, symbol="XAUUSD-", account_key="replay", data_ok=True, new_data=True, now=t, cfg=cfg,
                           scanned=set(registry.STRATEGIES))
        for c in res["candidates"]:
            event_groups[c["event_id"]].add(c["strategy_id"])
        for kind, r in events:
            if not r:
                continue
            sid = r["setup_id"]
            rec = r["record"]
            if kind.startswith("NEW_"):
                seen.setdefault(sid, {"strategy": rec["strategy_id"], "first": t, "stage0": r["stage"]})
            if kind in ("NEW_EARLY", "STAGE_EARLY"):
                first_stage.setdefault(sid, {})["EARLY"] = t
            if kind in ("NEW_CONFIRMED", "STAGE_CONFIRMED"):
                first_stage.setdefault(sid, {})["CONFIRMED"] = t
                confirmed.append((t, dict(rec)))
            if kind in ("INVALIDATED", "EXPIRED", "MISSED_ENTRY", "CANCELLED"):
                terminal[(rec["strategy_id"], kind)] += 1
        st = sel.select(tr.active("XAUUSD-", "replay"), cfg=cfg, regime=view.regime, data_ok=True, new_data=True, now=t, snapshot_id=None,
                        account_key="replay", per_strategy=res["per_strategy"])
        cur = (st.get("selected") or {}).get("setup_id")
        if cur != prev_sel:
            sel_changes += 1
            prev_sel = cur
        if st.get("selected") and st["selected"]["stage"] == "CONFIRMED":
            r = tr.get(cur)
            if r and not any(s == cur for _, s, _ in selected_confirmed):
                selected_confirmed.append((t, cur, dict(r["record"])))
    elapsed = time.time() - t0
    hours = len(steps) * TF_SECONDS[step_tf] / 3600
    # trades per strategy (each first CONFIRMED), chronological segments
    trades = defaultdict(list)
    for t, rec in confirmed:
        sim = simulate(rec, t, m5, m5_index, cost)
        if sim:
            trades[rec["strategy_id"]].append({**sim, "signal_time": iso(t)})
    if steps:
        a, b = steps[0], steps[-1]
        cut1, cut2 = a + (b - a) * 0.6, a + (b - a) * 0.8
    else:
        cut1 = cut2 = None

    def seg(ts, name):
        if not cut1:
            return []
        if name == "DEV":
            return [x for x in ts if p(x["signal_time"]) < cut1]
        if name == "VAL":
            return [x for x in ts if cut1 <= p(x["signal_time"]) < cut2]
        return [x for x in ts if p(x["signal_time"]) >= cut2]
    per = {}
    for sid in registry.STRATEGIES:
        ids = [k for k, v in seen.items() if v["strategy"] == sid]
        e2c = [k for k in ids if "EARLY" in first_stage.get(k, {}) and "CONFIRMED" in first_stage.get(k, {})]
        leads = sorted((first_stage[k]["CONFIRMED"] - first_stage[k]["EARLY"]).total_seconds() / 60 for k in e2c)
        segs = {}
        for name in ("DEV", "VAL", "OOS"):
            segs[name] = stats(seg(trades[sid], name))
        per[sid] = {"unique_setups": len(ids), "per_observed_hour": round(len(ids) / hours, 3) if hours else None,
                    "early_to_confirmed": len(e2c), "median_lead_early_to_confirmed_min": leads[len(leads) // 2] if leads else None,
                    "confirmed": sum(1 for _, r in confirmed if r["strategy_id"] == sid),
                    "terminal": {k: v for (s, k), v in terminal.items() if s == sid}, "funnel": dict(funnel[sid]),
                    "all": stats(trades[sid]), "segments": segs,
                    "no_levels": sum(1 for x in trades[sid] if x.get("status") == "NO_LEVELS")}
    # portfolio: AUTO-selected only, one position at a time
    port, busy_until = [], None
    for t, sid_, rec in selected_confirmed:
        if busy_until and t < busy_until:
            continue
        sim = simulate(rec, t, m5, m5_index, cost)
        if sim and sim.get("status") == "CLOSED":
            port.append({**sim, "signal_time": iso(t), "strategy": rec["strategy_id"]})
            busy_until = p(sim["entry_time"]) + timedelta(minutes=5 * sim["held_m5"])
    multi = [len(v) for v in event_groups.values() if len(v) > 1]
    reasons = Counter()
    for row in db.query("SELECT reason FROM strategy_selection_log"):
        key = row["reason"].split("_BY_")[0] if row["reason"].startswith("CHALLENGER") else row["reason"]
        reasons[key] += 1
    out = {"source": source, "step_tf": step_tf, "steps": len(steps), "observed_hours": round(hours, 1), "elapsed_s": round(elapsed, 1),
           "ms_per_step": round(1000 * elapsed / max(1, len(steps)), 1), "cost_model": cost, "regimes": dict(regimes),
           "selection_changes": sel_changes, "selection_change_reasons": dict(reasons), "events_shared_by_several_strategies": len(multi),
           "max_strategies_per_event": max(multi) if multi else 1, "per_strategy": per, "portfolio_auto_selected": stats(port),
           "segments_cut": [iso(cut1), iso(cut2)] if cut1 else None,
           "method": "closed-bar replay, next-M5-open entry, SL-first on ambiguous bars, costs in R; DEV/VAL/OOS 60/20/20",
           "status": "FUNCTIONAL_REPLAY_" + source + (" - wyniki nie są dowodem skuteczności" if source == "SYNTHETIC" else " - OOS do oceny wg z góry ustalonych kryteriów")}
    if compare_original:
        out["original_m07"] = original_counts(data, step_tf="H1", max_steps=None)
    return out


def original_counts(data: dict, step_tf: str = "H1", max_steps: int | None = None) -> dict:
    """ORIGINAL profile on the same data: unique frozen M07 plans (legacy engines, unchanged code)."""
    from masterquo.engine.legacy import LegacyEngines, build_snapshot
    tmp = Path(tempfile.mkdtemp(prefix="mq_orig_"))
    out = {}
    for policy in ("STRICT_H4_H1", "H1_LEAD"):
        eng = LegacyEngines(tmp / f"lock_{policy}.sqlite")
        steps = [p(b["available_at"]) for b in data[step_tf]]
        steps = [t for t in steps if t >= steps[0] + timedelta(days=45)]
        if max_steps:
            steps = steps[:max_steps]
        ptr = {tf: 0 for tf in TFS}
        plans, dirn = set(), 0
        for t in steps:
            for tf in TFS:
                rows = data[tf]
                while ptr[tf] < len(rows) and p(rows[ptr[tf]]["available_at"]) <= t:
                    ptr[tf] += 1
            closed = {tf: [{**b, "close_confirmed_utc": b["available_at"], "tv": 0, "t_raw": int(p(b["open_utc"]).timestamp())}
                           for b in data[tf][max(0, ptr[tf] - 260):ptr[tf]]] for tf in TFS}
            snap = build_snapshot(snapshot_id=f"R{int(t.timestamp())}", analysis_id="R", as_of=iso(t), symbol="XAUUSD-", alias="XAUUSD",
                                  closed_bars=closed, analysis_status="PASS", reason_codes=[])
            o = eng.run(snap, "AUTO", policy)
            if (o.get("m02") or {}).get("structural_direction") in ("BULLISH", "BEARISH"):
                dirn += 1
            if o.get("m07_plan"):
                plans.add(o["m07_plan"].get("frozen_plan_hash"))
        hours = len(steps) * TF_SECONDS[step_tf] / 3600
        out[policy] = {"steps": len(steps), "hours_with_direction": dirn, "unique_plans": len(plans),
                       "per_observed_hour": round(len(plans) / hours, 3) if hours else None}
    return out


def to_markdown(r: dict) -> str:
    L = [f"# Replay S01–S10 – {r['source']}", "", f"Kroki: {r['steps']} × {r['step_tf']} ({r['observed_hours']} h obserwowanego rynku), "
         f"{r['ms_per_step']} ms/krok. Metoda: {r['method']}.", f"Status: **{r['status']}**", "",
         "| Strategia | Unikalne setupy | /h | EARLY→CONF | Mediana [min] | Transakcje | Expectancy R | PF | Win | DD R | OOS trans. | OOS exp. R |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for sid, s in r["per_strategy"].items():
        a, o = s["all"], s["segments"]["OOS"]
        L.append(f"| {sid} | {s['unique_setups']} | {s['per_observed_hour']} | {s['early_to_confirmed']} | {s['median_lead_early_to_confirmed_min']} | "
                 f"{a.get('trades')} | {a.get('expectancy_r', '—')} | {a.get('profit_factor', '—')} | {a.get('win_rate', '—')} | {a.get('max_drawdown_r', '—')} | "
                 f"{o.get('trades')} | {o.get('expectancy_r', '—')} |")
    L += ["", f"Portfel (tylko wybór AUTO, 1 pozycja naraz): {json.dumps(r['portfolio_auto_selected'], ensure_ascii=False)}",
          f"Zdarzenia opisane przez kilka strategii jednocześnie: {r['events_shared_by_several_strategies']} (maks. {r['max_strategies_per_event']} strategie/zdarzenie).",
          f"Zmiany wyboru AUTO: {r['selection_changes']} – przyczyny: {json.dumps(r['selection_change_reasons'])}. Reżimy: {json.dumps(r['regimes'])}"]
    if r.get("original_m07"):
        L += ["", "## ORIGINAL (M07) na tych samych danych", json.dumps(r["original_m07"], ensure_ascii=False, indent=1)]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--csv-dir")
    g.add_argument("--synthetic", type=int, metavar="DAYS")
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--step-tf", default="M15", choices=["M5", "M15", "H1"])
    ap.add_argument("--spread", type=float, default=0.12, help="spread in price units when the CSV has none (gold: 0.12 = 12 pts at 2 digits)")
    ap.add_argument("--slippage", type=float, default=0.05, help="slippage per fill, price units")
    ap.add_argument("--commission", type=float, default=0.035, help="commission per side, price units per unit (e.g. 3.5 USD/lot/side = 0.035)")
    ap.add_argument("--compare-original", action="store_true")
    ap.add_argument("--max-steps", type=int)
    ap.add_argument("--out", default=str(ROOT / "data" / "reports"))
    a = ap.parse_args()
    data, source = load_csv(Path(a.csv_dir)) if a.csv_dir else load_synthetic(a.synthetic, a.seed)
    if not data.get("M5") or not data.get(a.step_tf):
        print("[BLAD] brak danych M5/" + a.step_tf)
        return 2
    r = run(data, source, a.step_tf, {"spread": a.spread, "slip": a.slippage, "commission": a.commission}, a.compare_original, a.max_steps)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    (out / f"replay_{source.lower()}_{stamp}.json").write_text(json.dumps(r, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    md = to_markdown(r)
    (out / f"replay_{source.lower()}_{stamp}.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
