"""Reproducible backtest of the EMA20 Pullback + 2.5R strategy: ORIGINAL vs FIXED vs candidates (MasterQUO 1.7).

Data sources (closed Bid bars, UTC):
  --csv DIR        files <TF>.csv from `python -m masterquo export --from-utc .. --to-utc ..` (your terminal, XAUUSD-)
  --synthetic      the terminal simulator (pipeline check only - synthetic prices carry NO evidence of an edge)
Outputs (data/results/ema_pullback/<run_id>/): results.json, summary.csv, trades_<variant>.csv, input manifest with sha256,
and RAPORT_WYNIKOW.md in the repository root (regenerated from the run).

Protocol (fixed BEFORE looking at results):
  1. chronological split: development = first 75% of bars (3 folds), final test = last 25% (evaluated ONCE, frozen config)
  2. variants: ORIGINAL/PINE_DEFAULT (baseline replica), ORIGINAL/MT5 (same signals, realistic execution),
     FIXED/MT5 (bug fixes, same parameters), candidates = FIXED + one hypothesis each (ablation) + all combined
  3. promotion rule (development folds only): candidate expectancy_R > FIXED + 0.05 R, max DD <= 1.2 x FIXED,
     expectancy_R > 0 in >= 2 of 3 folds, >= 30 trades in development; otherwise FIXED stays the configuration
  4. final test once for FIXED and the chosen configuration; stress: costs x2, slippage +3 ticks, entry delay 1 bar,
     neighbouring parameters; moving-block bootstrap 90% intervals; same-bar SL/TP = SL (conservative)
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from masterquo.strategies import ema_pullback_backtest as bt  # noqa: E402
from masterquo.strategies import ema_pullback_core as core  # noqa: E402

CANDIDATES = {
    "C1_ZONE_TOUCH": dict(touch_mode="ZONE_ATR", touch_tol_atr=0.10, require_approach=True, max_depth_atr=1.0),
    "C2_RECLAIM": dict(confirm_mode="RECLAIM"),
    "C3_EMA_SEPARATION": dict(min_ema_sep_atr=0.5),
    "C4_H8_TREND": dict(h8_trend_filter=True),
}


def load_csv(path: Path) -> list[dict]:
    out = []
    with path.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r.get("bar_state", "CLOSED") != "CLOSED":
                continue
            out.append({"t": r["time_utc"], "o": float(r["open"]), "h": float(r["high"]), "l": float(r["low"]), "c": float(r["close"]),
                        "spread": float(r.get("spread_points") or 0)})
    out.sort(key=lambda b: b["t"])
    return out


def synthetic(tf: str, days: int = 420) -> list[dict]:
    from masterquo.mt5.fake import FakeMT5, TIMEFRAME_H8, TIMEFRAME_M15, TIMEFRAME_M30
    import os
    os.environ["MQ_FAKE_MARKET_ALWAYS_OPEN"] = "0"
    f = FakeMT5(seed=11, history_days=days, server_offset_hours=0)
    f.initialize()
    code = {"M15": TIMEFRAME_M15, "M30": TIMEFRAME_M30, "H8": TIMEFRAME_H8}[tf]
    r = f.copy_rates_from_pos("XAUUSD-", code, 0, 100000)
    rows = [{"t": datetime.fromtimestamp(int(x["time"]), timezone.utc).isoformat().replace("+00:00", "Z"), "o": float(x["open"]),
             "h": float(x["high"]), "l": float(x["low"]), "c": float(x["close"]), "spread": float(x["spread"])} for x in r]
    return rows[:-1]                           # drop the forming bar


def h8_series(base: list[dict], h8: list[dict], tf_sec: int, p: core.Params):
    if not h8:
        return None
    ts = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()  # noqa: E731
    return core.asof_h8_trend([ts(b["t"]) + tf_sec for b in base], [{"close_ts": ts(b["t"]) + 28800, "c": b["c"]} for b in h8], p)


def evaluate(bars, h8, tf_sec, p: core.Params, m: bt.ExecModel, variant: str) -> dict:
    tr = h8_series(bars, h8, tf_sec, p) if p.h8_trend_filter else None
    r = bt.run(bars, p, m, variant, tr)
    return {"variant": variant, "metrics": r["metrics"], "bootstrap": r["bootstrap"], "max_dd_pct": r["max_dd_pct"],
            "exposure_pct": r["exposure_pct"], "diag": r["diag"], "machine": r["machine_counts"], "_trades": r["trades"]}


def classify_original(bars, p: core.Params) -> dict:
    """Why ORIGINAL confirmations differ from FIXED on the same OHLC (defects 1-3 of the audit)."""
    o, h, lo, c = ([b[k] for b in bars] for k in "ohlc")
    ind = core.indicators(o, h, lo, c, p)
    orig = core.run_original(o, h, lo, c, p, ind)
    fix = core.run_fixed(o, h, lo, c, p, ind)
    fixed_conf = {(e.i, e.direction) for e in fix.events if e.kind == "CONFIRM"}
    first = core.warmup_bars(p)
    out = {"original_confirms": 0, "fixed_confirms": len(fixed_conf), "matched": 0, "against_trend": 0, "expired_boundary": 0,
           "extended_by_retouch": 0, "warmup_only": 0, "other": 0}
    touches = {}
    for e in orig.events:
        if e.kind == "TOUCH":
            touches.setdefault(e.direction, []).append(e.i)
    for e in orig.events:
        if e.kind != "CONFIRM":
            continue
        out["original_confirms"] += 1
        i, d = e.i, e.direction
        if (i, d) in fixed_conf:
            out["matched"] += 1
        elif i < first:
            out["warmup_only"] += 1
        elif (d == "LONG" and not ind["ema20"][i] > ind["ema50"][i]) or (d == "SHORT" and not ind["ema20"][i] < ind["ema50"][i]):
            out["against_trend"] += 1
        elif p.max_pullback_bars and i - e.setup_id == p.max_pullback_bars + 1:
            out["expired_boundary"] += 1
        elif any(t < e.setup_id and e.setup_id - t <= p.max_pullback_bars for t in touches.get(d, [])):
            out["extended_by_retouch"] += 1
        else:
            out["other"] += 1
    return out


def write_trades(path: Path, trades) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["direction", "setup_bar", "signal_bar", "signal_price", "fill_time", "fill_price", "stop", "target", "qty", "risk_money",
                    "exit_time", "exit_price", "exit_reason", "gross", "costs", "net", "r"])
        for t in trades:
            w.writerow([t.direction, t.setup_id, t.signal_i, round(t.signal_price, 5), t.time_open, round(t.fill_price, 5), round(t.stop, 5),
                        round(t.target, 5), round(t.qty, 6), round(t.risk_money, 2), t.time_close, round(t.exit_price or 0, 5), t.exit_reason,
                        round(t.gross, 2), round(t.costs, 2), round(t.net, 2), round(t.r, 4)])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv", help="directory with M15.csv / M30.csv / H8.csv from `masterquo export`")
    src.add_argument("--synthetic", action="store_true")
    ap.add_argument("--tf", default="M30", choices=["M15", "M30"])
    ap.add_argument("--capital", type=float, default=10000.0)
    ap.add_argument("--risk-pct", type=float, default=1.0)
    ap.add_argument("--commission-lot-side", type=float, default=3.5, help="account money per lot per side (MT5 model); 'Zero' accounts must be checked in the terminal")
    ap.add_argument("--slippage-ticks", type=int, default=3)
    ap.add_argument("--contract-size", type=float, default=100.0)
    ap.add_argument("--report", default=str(ROOT / "RAPORT_WYNIKOW.md"))
    a = ap.parse_args(argv)
    tf_sec = {"M15": 900, "M30": 1800}[a.tf]
    if a.synthetic:
        bars, h8, source = synthetic(a.tf), synthetic("H8"), "SYNTHETIC_SIMULATOR (FakeMT5 seed=11) - NIE SĄ TO NOTOWANIA"
        manifest = {"source": source}
    else:
        d = Path(a.csv)
        bars, h8 = load_csv(d / f"{a.tf}.csv"), (load_csv(d / "H8.csv") if (d / "H8.csv").exists() else [])
        source = f"CSV {d}"
        manifest = {"source": source, "files": {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in d.glob("*.csv")}}
        mf = d / "MT5_EXPORT_MANIFEST.json"
        if mf.exists():
            manifest["export_manifest"] = json.loads(mf.read_text(encoding="utf-8"))
    if len(bars) < 2000:
        print(f"[BLAD] Za mało świec ({len(bars)}); potrzeba co najmniej 2000 zamkniętych świec {a.tf}.")
        return 2
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ("_SYN" if a.synthetic else "")
    out = ROOT / "data" / "results" / "ema_pullback" / run_id
    out.mkdir(parents=True, exist_ok=True)
    base = core.Params()
    mt5 = bt.ExecModel(mode="MT5", initial_capital=a.capital, risk_pct=a.risk_pct, commission_per_lot_side=a.commission_lot_side,
                       slippage_ticks=a.slippage_ticks, contract_size=a.contract_size)
    pine = bt.ExecModel(mode="PINE_DEFAULT", initial_capital=a.capital, risk_pct=a.risk_pct, same_bar_policy="PINE_HEURISTIC")
    n = len(bars)
    cut = int(n * 0.75)
    dev, test = bars[:cut], bars[cut:]
    folds = [dev[k * cut // 3:(k + 1) * cut // 3] for k in range(3)]
    period = lambda b: f"{b[0]['t']} – {b[-1]['t']} ({len(b)} świec)"  # noqa: E731
    results = {"run_id": run_id, "source": source, "tf": a.tf, "bars": n, "periods": {"development": period(dev), "final_test": period(test),
               "folds": [period(f) for f in folds]}, "params_base": base.as_dict(), "model_mt5": mt5.as_dict(), "model_pine": pine.as_dict(),
               "protocol": __doc__.split("Protocol")[1].strip(), "variants_tried": [], "manifest": manifest}
    # ---- baseline and fixes on the whole development period
    stage = {}
    for name, p, m, var in (("ORIGINAL_PINE_DEFAULT", base, pine, "ORIGINAL"), ("ORIGINAL_MT5", base, mt5, "ORIGINAL"),
                            ("FIXED_MT5", base, mt5, "FIXED")):
        stage[name] = evaluate(dev, h8, tf_sec, p, m, var)
        results["variants_tried"].append(name)
    # ---- candidates: development folds only
    cand_rows = {}
    for name, kw in [*CANDIDATES.items(), ("C5_ALL", {k: v for d in CANDIDATES.values() for k, v in d.items()})]:
        p = replace(base, **kw)
        whole = evaluate(dev, h8, tf_sec, p, mt5, "FIXED")
        per_fold = [evaluate(f, h8, tf_sec, p, mt5, "FIXED")["metrics"] for f in folds]
        cand_rows[name] = {"params": kw, "dev": whole, "folds": per_fold}
        results["variants_tried"].append(name)
    fixed_folds = [evaluate(f, h8, tf_sec, base, mt5, "FIXED")["metrics"] for f in folds]
    fx = stage["FIXED_MT5"]
    fx_exp = fx["metrics"].get("expectancy_r") if fx["metrics"].get("trades") else None
    chosen, reasons = "FIXED_MT5", []
    best = None
    for name, row in cand_rows.items():
        mm = row["dev"]["metrics"]
        if not mm.get("trades"):
            reasons.append(f"{name}: brak transakcji")
            continue
        pos_folds = sum(1 for f in row["folds"] if f.get("trades") and (f.get("expectancy_r") or 0) > 0)
        ok = (mm["trades"] >= 30 and fx_exp is not None and mm["expectancy_r"] > fx_exp + 0.05
              and row["dev"]["max_dd_pct"] <= 1.2 * max(fx["max_dd_pct"], 0.01) and pos_folds >= 2)
        reasons.append(f"{name}: E[R]={mm['expectancy_r']} vs FIXED {fx_exp}, DD {row['dev']['max_dd_pct']}% vs {fx['max_dd_pct']}%, "
                       f"folds>0: {pos_folds}/3, n={mm['trades']} -> {'SPEŁNIA' if ok else 'nie spełnia'}")
        if ok and (best is None or mm["expectancy_r"] > cand_rows[best]["dev"]["metrics"]["expectancy_r"]):
            best = name
    if best:
        chosen = best
    results["selection"] = {"chosen": chosen, "rule_results": reasons}
    chosen_params = base if chosen == "FIXED_MT5" else replace(base, **cand_rows[chosen]["params"])
    # ---- final test: once
    final = {"FIXED_MT5": evaluate(test, h8, tf_sec, base, mt5, "FIXED"), "ORIGINAL_PINE_DEFAULT": evaluate(test, h8, tf_sec, base, pine, "ORIGINAL")}
    if chosen != "FIXED_MT5":
        final[chosen] = evaluate(test, h8, tf_sec, chosen_params, mt5, "FIXED")
    # ---- stress on the chosen configuration (final test period)
    stress = {}
    for sname, m2, p2 in (("COSTS_X2", replace(mt5, commission_per_lot_side=2 * mt5.commission_per_lot_side), chosen_params),
                          ("SLIPPAGE_+3", replace(mt5, slippage_ticks=mt5.slippage_ticks + 3), chosen_params),
                          ("ENTRY_DELAY_1", replace(mt5, entry_delay_bars=1), chosen_params),
                          ("RR_2.0", mt5, replace(chosen_params, rr=2.0)), ("RR_3.0", mt5, replace(chosen_params, rr=3.0)),
                          ("SWING_8", mt5, replace(chosen_params, swing_lookback=8)), ("SWING_12", mt5, replace(chosen_params, swing_lookback=12)),
                          ("ADX_18", mt5, replace(chosen_params, adx_threshold=18)), ("ADX_22", mt5, replace(chosen_params, adx_threshold=22))):
        stress[sname] = evaluate(test, h8, tf_sec, p2, m2, "FIXED")["metrics"]
    results["development"] = {k: {kk: vv for kk, vv in v.items() if kk != "_trades"} for k, v in stage.items()}
    results["development_folds_fixed"] = fixed_folds
    results["candidates"] = {k: {"params": v["params"], "dev": {kk: vv for kk, vv in v["dev"].items() if kk != "_trades"}, "folds": v["folds"]}
                             for k, v in cand_rows.items()}
    results["final_test"] = {k: {kk: vv for kk, vv in v.items() if kk != "_trades"} for k, v in final.items()}
    results["stress_final_test"] = stress
    results["original_vs_fixed_signals"] = classify_original(bars, base)
    results["n_variants_tested"] = len(results["variants_tried"]) + len(stress)
    for k, v in {**{f"dev_{k}": v for k, v in stage.items()}, **{f"test_{k}": v for k, v in final.items()}}.items():
        write_trades(out / f"trades_{k}.csv", v["_trades"])
    (out / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    with (out / "summary.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["segment", "variant", "trades", "winrate_pct", "breakeven", "profit_factor", "expectancy_r", "roi_pct", "max_dd_pct", "costs"])
        for seg, block in (("development", results["development"]), ("final_test", results["final_test"])):
            for k, v in block.items():
                mm = v["metrics"]
                w.writerow([seg, k, mm.get("trades"), mm.get("winrate_pct"), mm.get("breakeven"), mm.get("profit_factor"), mm.get("expectancy_r"),
                            mm.get("roi_pct"), v["max_dd_pct"], mm.get("costs")])
    Path(a.report).write_text(report_md(results, out), encoding="utf-8")
    print(f"[OK] Wyniki: {out}\n[OK] Raport: {a.report}")
    return 0


def _row(name, v):
    m = v["metrics"] if "metrics" in v else v
    if not m.get("trades"):
        return f"| {name} | 0 | – | – | – | – | – | – | – |"
    b = v.get("bootstrap") or {}
    ci = b.get("expectancy_r_90") or ["–", "–"]
    return (f"| {name} | {m['trades']} | {m['winrate_pct']} | {m['breakeven']} | {m['profit_factor'] if m['profit_factor'] is not None else 'brak strat'} | "
            f"{m['expectancy_r']} [{ci[0]}; {ci[1]}] | {m['roi_pct']} | {v.get('max_dd_pct', '–')} | {m['costs']} |")


def report_md(r: dict, out: Path) -> str:
    syn = "SYNTHETIC" in r["source"]
    hdr = "| Wariant | Transakcje | Winrate % (bez BE) | BE | PF | E[R] [90% CI] | ROI % | Max DD % | Koszty |\n|---|---|---|---|---|---|---|---|---|"
    s = [f"# Raport wyników – EMA20 Pullback 2.5R ({r['tf']})", "",
         f"Źródło danych: **{r['source']}**. Run `{r['run_id']}`, pliki: `{out.relative_to(ROOT)}`.", ""]
    if syn:
        s += ["> **To są dane syntetyczne z symulatora terminala.** Wynik sprawdza wyłącznie działanie potoku (sygnały, wykonanie, koszty, "
              "statystyki). Nie jest dowodem przewagi strategii ani podstawą do decyzji handlowych. Dla dowodu uruchom runner na eksporcie "
              "z Twojego terminala (instrukcja niżej).", ""]
    s += ["## Deklaracja z nazwy pliku", "Nazwa pliku deklaruje winrate 42,86% i PF 1,52. Plik nie zawiera okresu, instrumentu, kosztów ani liczby "
          "transakcji – **wartości nie są zweryfikowane** i nie zostały odtworzone w tym środowisku (brak historii XAUUSD- z Twojego terminala).", "",
          "## Protokół", "```", r["protocol"], "```",
          f"Okresy: rozwój {r['periods']['development']}; test końcowy {r['periods']['final_test']}.", "",
          "## Etapy na okresie rozwojowym (te same parametry)", hdr]
    s += [_row(k, v) for k, v in r["development"].items()]
    s += ["", "## Kandydaci (ablacja, tylko okres rozwojowy)", hdr]
    s += [_row(k, v["dev"]) for k, v in r["candidates"].items()]
    s += ["", "Reguła promocji (ustalona przed oceną):", *[f"- {x}" for x in r["selection"]["rule_results"]],
          f"", f"**Wybrana konfiguracja: {r['selection']['chosen']}** (jeśli żaden kandydat nie spełnił reguły – zostaje FIXED; kandydaci pozostają eksperymentalni).",
          "", "## Test końcowy (oceniony raz)", hdr]
    s += [_row(k, v) for k, v in r["final_test"].items()]
    s += ["", "## Testy obciążeniowe (wybrana konfiguracja, okres testowy)",
          "| Scenariusz | Transakcje | Winrate % | PF | E[R] | ROI % |", "|---|---|---|---|---|---|"]
    for k, m in r["stress_final_test"].items():
        s.append(f"| {k} | {m.get('trades', 0)} | {m.get('winrate_pct', '–')} | {m.get('profit_factor', '–')} | {m.get('expectancy_r', '–')} | {m.get('roi_pct', '–')} |")
    c = r["original_vs_fixed_signals"]
    s += ["", "## Oryginał vs wersja naprawiona – te same świece",
          f"Potwierdzenia oryginału: {c['original_confirms']}, wersji naprawionej: {c['fixed_confirms']}, zgodne: {c['matched']}. "
          f"Rozbieżności oryginału: wbrew trendowi {c['against_trend']}, na granicy wygaśnięcia {c['expired_boundary']}, "
          f"przedłużone ponownym dotknięciem {c['extended_by_retouch']}, w okresie rozgrzewki {c['warmup_only']}, inne {c['other']}.", "",
          f"Liczba przetestowanych wariantów/scenariuszy: {r['n_variants_tested']} (uwzględnij przy ocenie ryzyka przeuczenia).", "",
          "## Jak uruchomić na danych z terminala", "```",
          "cd backend",
          "..\\.venv\\Scripts\\python.exe -m masterquo export --from-utc 2025-01-01T00:00:00Z --to-utc 2026-06-01T00:00:00Z --out ..\\data\\export_xau",
          "cd ..",
          ".venv\\Scripts\\python.exe tools\\backtest_ema_pullback.py --csv data\\export_xau --tf M30 --commission-lot-side <prowizja z terminala>",
          "```", "Definicje: winrate = wygrane/(wygrane+przegrane) po kosztach, BE (|R| ≤ 0,05) osobno; PF = suma zysków netto / |suma strat netto| "
          "(brak strat = „brak strat”, nie nieskończoność); E[R] = średni wynik netto w R; ROI = wynik netto / kapitał początkowy w okresie; "
          "max DD z krzywej kapitału wycenianej na zamknięciach świec.", ""]
    return "\n".join(s)


if __name__ == "__main__":
    sys.exit(main())
