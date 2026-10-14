"""Planned training of the gold_candles forecasters (5/15/30 min) on a frozen dataset.

Why not `gold_candles.model.train()` as is: it chooses split points per horizon by ROW COUNT (after each horizon's label
filtering) and evaluates the final holdout on every call - repeated runs would let the holdout pick the model. Here:

  1. TRAINING_PLAN.json is written BEFORE any fitting: one set of UTC boundaries (60/20/20 of the TIME span of complete
     feature rows, cut at 00:00 UTC), embargo 30 min, purge by label end, the pre-declared comparisons (class-frequency
     baseline, the same model without pattern flags) and the acceptance criteria. A plan is bound to the dataset hash; an
     existing plan for the same data is reused, never re-cut.
  2. Per horizon h = 1/3/6 M5: logistic regression (fit), separate multinomial calibrator (calibration period), GBR
     quantiles q10/q50/q90 of the ATR-normalised delta (fit) - the reference hyper-parameters, no tuning on the holdout.
  3. Holdout evaluated once per run: Brier, log loss, balanced accuracy, per-class recall/ECE, reliability bins, q10-q90
     coverage, median MAE, baseline and no-pattern comparison with day-block bootstrap intervals, sessions.
  4. Portable JSON artifact in the reference schema (gold_candles.model.forecast() loads it) + registry entry; the runtime
     inference path is re-run on the holdout and must reproduce the training predictions.

Statuses per horizon: INSUFFICIENT_DATA / REJECTED / SHADOW_UNVALIDATED / SHADOW_VALIDATED (all are SHADOW - none allows
an order). Overall: TRAINED_SHADOW (all validated), PARTIAL_VALIDATION, SHADOW_UNVALIDATED, REJECTED or INSUFFICIENT_DATA."""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from .common import RunLog, activate, code_fingerprint, forecast_dir, read_registry, sha256_file, versions, write_json_atomic, write_registry

MIN_ROWS = {"fit": 600, "calibration": 200, "holdout": 250}
MIN_CLASS = 10
EMBARGO_MIN = 30
CRITERIA = {"holdout_days_min": 30, "brier_better_than_baseline": True, "log_loss_better_than_baseline": True, "per_class_ece_max": 0.10}
SESSIONS = (("ASIA_00_08_UTC", 0, 8), ("LONDON_08_13_UTC", 8, 13), ("NEW_YORK_13_21_UTC", 13, 21), ("LATE_21_24_UTC", 21, 24))


def load_dataset(data_dir: Path, data_kind: str):
    from gold_candles.data import Config, read_csv
    meta_p = data_dir / "source_metadata.json"
    if not meta_p.exists():
        raise SystemExit(f"[BLAD] Brak {meta_p} – użyj eksportu bota (11_EKSPORT_HISTORII_XAUUSD.bat).")
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    if meta.get("data_kind", "REAL_USER_DATA") != data_kind:
        raise SystemExit(f"[BLAD] Dane oznaczone {meta.get('data_kind')}, a trening wywołano z --data-kind {data_kind}.")
    symbol, tick = meta["symbol"], float(meta["tick_size"])
    cutoff = meta["cutoff_utc"]
    m5 = read_csv(data_dir / "XAUUSD_M5.csv", 5, cutoff, symbol)
    m30p = data_dir / "XAUUSD_M30.csv"
    m30 = read_csv(m30p, 30, cutoff, symbol) if m30p.exists() else None
    files = {p.name: sha256_file(p) for p in (data_dir / "XAUUSD_M5.csv", m30p) if p.exists()}
    dataset_sha = __import__("hashlib").sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    return m5, m30, Config(symbol=symbol, tick_size=tick), meta, files, dataset_sha


def make_plan(times: pd.Series, dataset_sha: str, config, context_source: str) -> dict:
    t0, t1 = times.min(), times.max()
    span = t1 - t0
    cal = (t0 + span * 0.60).floor("D")
    hold = (t0 + span * 0.80).floor("D")
    if not (t0 < cal < hold < t1):
        raise SystemExit("[BLAD] Za krótki zakres czasu na podział 60/20/20 z granicami dziennymi.")
    return {"schema": "masterquo-forecast-training-plan-1", "created_at_utc": pd.Timestamp.now(tz="UTC").isoformat(), "dataset_sha256": dataset_sha,
            "symbol": config.symbol, "tick_size": config.tick_size, "context_source": context_source,
            "feature_rows_first_utc": t0.isoformat(), "feature_rows_last_utc": t1.isoformat(),
            "boundaries_utc": {"calibration_start": cal.isoformat(), "holdout_start": hold.isoformat()},
            "split_rule": "60% / 20% / 20% of the time span of complete feature rows, cut at 00:00 UTC; identical for all horizons",
            "embargo_minutes": EMBARGO_MIN, "purge": "fit: label_end < calibration_start - embargo; calibration: label_end < holdout_start - embargo",
            "horizons_m5": [1, 3, 6], "label": "delta_h=future_close_h-close_now; FLAT if |delta_h| <= 0.20*ATR14_M5 known at t; continuous M5 only",
            "models": {"primary": "reference: StandardScaler + LogisticRegression(C=0.5, balanced) + multinomial calibrator(C=0.1) + GBR quantile (q10/q50/q90, 80 trees, depth 2, lr 0.05)",
                       "comparisons_declared_before_training": ["class-frequency baseline (fit priors)", "same model without pattern_* features"]},
            "selection": "no hyper-parameter search; the holdout is evaluated once and never used to choose features, thresholds or models",
            "minimums": {"rows": MIN_ROWS, "per_class": MIN_CLASS}, "acceptance_criteria": CRITERIA,
            "note": "Price-forecast criteria only; not strategy profitability, not P(TP before SL)."}


def _fit_classifier(xfit, yfit, xcal, ycal):
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    scaler = StandardScaler().fit(xfit)
    clf = LogisticRegression(C=.5, max_iter=2000, class_weight="balanced", random_state=17).fit(scaler.transform(xfit), yfit)
    raw_cal = clf.predict_proba(scaler.transform(xcal))
    cal = LogisticRegression(C=.1, max_iter=2000, random_state=17).fit(np.log(np.clip(raw_cal, 1e-12, 1)), ycal)
    return scaler, clf, cal


def _predict(scaler, clf, cal, x):
    raw = clf.predict_proba(scaler.transform(x))
    return cal.predict_proba(np.log(np.clip(raw, 1e-12, 1)))


def _row_scores(y, prob):
    obs = np.eye(3)[y]
    return np.sum((prob - obs) ** 2, axis=1), -np.log(np.clip(prob[np.arange(len(y)), y], 1e-12, 1))


def block_bootstrap(days: np.ndarray, a: np.ndarray, b: np.ndarray, reps: int = 2000, seed: int = 7) -> dict:
    """Mean difference a-b with whole TRADING DAYS resampled (overlapping 5/15/30 min forecasts are dependent)."""
    uniq = np.unique(days)
    idx = {d: np.flatnonzero(days == d) for d in uniq}
    rng = np.random.default_rng(seed)
    diffs = []
    for _ in range(reps):
        pick = rng.choice(uniq, size=len(uniq), replace=True)
        rows = np.concatenate([idx[d] for d in pick])
        diffs.append(float(np.mean(a[rows] - b[rows])))
    diffs = np.sort(diffs)
    return {"mean_diff": float(np.mean(a - b)), "ci95": [float(np.quantile(diffs, .025)), float(np.quantile(diffs, .975))], "days": int(len(uniq)), "reps": reps}


def reliability(y, prob, bins=8) -> dict:
    from gold_candles.model import CLASS_NAMES
    out = {}
    edges = np.linspace(0, 1, bins + 1)
    for c, name in enumerate(CLASS_NAMES):
        rows = []
        for lo, hi in zip(edges[:-1], edges[1:]):
            m = (prob[:, c] >= lo) & (prob[:, c] < (hi if hi < 1 else 1.000001))
            if m.any():
                rows.append({"bin": [float(lo), float(hi)], "n": int(m.sum()), "mean_p": float(prob[m, c].mean()), "observed": float((y[m] == c).mean())})
        out[name] = rows
    return out


def horizon_status(rep: dict, data_kind: str) -> tuple[str, list[str]]:
    c, b = rep["calibrated"], rep["baseline"]
    why = []
    if not (c["brier_multiclass_sum"] < b["brier_multiclass_sum"]):
        why.append("Brier nie lepszy od baseline częstości klas")
    if not (c["log_loss"] < b["log_loss"]):
        why.append("log loss nie lepszy od baseline częstości klas")
    if why:
        return "REJECTED", why
    if data_kind != "REAL_USER_DATA":
        return "SHADOW_UNVALIDATED", ["dane SYNTHETIC_TEST – wynik nie ma znaczenia rynkowego"]
    if rep["holdout_days"] < CRITERIA["holdout_days_min"]:
        why.append(f"holdout {rep['holdout_days']} dni < {CRITERIA['holdout_days_min']}")
    worst = max(v for v in c["per_class_ece"].values())
    if worst > CRITERIA["per_class_ece_max"]:
        why.append(f"per-class ECE {worst:.3f} > {CRITERIA['per_class_ece_max']}")
    return ("SHADOW_UNVALIDATED", why) if why else ("SHADOW_VALIDATED", ["kryteria jakości prognozy ceny spełnione (nie dotyczy rentowności strategii)"])


def train_horizon(h, m5, x, usable, plan, trees, log):
    from gold_candles.features import make_labels
    from gold_candles.model import export_logistic, export_quantile, logistic_probability, metrics, quantile_prediction
    from sklearn.ensemble import GradientBoostingRegressor
    labels, delta, label_end = make_labels(m5, h)
    valid = usable & labels.notna() & delta.notna() & label_end.notna()
    xx = x.loc[valid].reset_index(drop=True)
    yy = labels.loc[valid].astype(int).reset_index(drop=True)
    dd = delta.loc[valid].reset_index(drop=True)
    times = m5.time_close_utc.loc[valid].reset_index(drop=True)
    ends = label_end.loc[valid].reset_index(drop=True)
    cal_start = pd.Timestamp(plan["boundaries_utc"]["calibration_start"])
    hold_start = pd.Timestamp(plan["boundaries_utc"]["holdout_start"])
    emb = pd.Timedelta(minutes=plan["embargo_minutes"])
    masks = {"fit": (times < cal_start) & (ends < cal_start - emb),
             "calibration": (times >= cal_start) & (times < hold_start) & (ends < hold_start - emb),
             "holdout": times >= hold_start}
    counts = {k: {"rows": int(m.sum()), "classes": {n: int((yy[m] == c).sum()) for c, n in enumerate(("DOWN", "FLAT", "UP"))}} for k, m in masks.items()}
    missing = []
    for k, m in masks.items():
        if m.sum() < MIN_ROWS[k]:
            missing.append(f"{k}: {int(m.sum())} wierszy < {MIN_ROWS[k]} (brakuje {MIN_ROWS[k] - int(m.sum())})")
        for n, v in counts[k]["classes"].items():
            if v < MIN_CLASS:
                missing.append(f"{k}: klasa {n} {v} < {MIN_CLASS}")
    if missing:
        log(f"h{h}", "INSUFFICIENT_DATA – " + "; ".join(missing))
        return None, {"status": "INSUFFICIENT_DATA", "reasons": missing, "counts": counts}
    fit, cal, hold = masks["fit"], masks["calibration"], masks["holdout"]
    log(f"h{h}", f"fit {int(fit.sum())} / kalibracja {int(cal.sum())} / holdout {int(hold.sum())}")
    scaler, clf, calib = _fit_classifier(xx[fit], yy[fit], xx[cal], yy[cal])
    prob = _predict(scaler, clf, calib, xx[hold])
    ytrue = yy[hold].to_numpy()
    prior = np.bincount(yy[fit], minlength=3) / fit.sum()
    base = np.repeat(prior[None, :], hold.sum(), axis=0)
    nopat = [c for c in xx.columns if not c.startswith("pattern_")]
    s2, c2, k2 = _fit_classifier(xx.loc[fit, nopat], yy[fit], xx.loc[cal, nopat], yy[cal])
    prob_np = _predict(s2, c2, k2, xx.loc[hold, nopat])
    days = times[hold].dt.floor("D").astype(str).to_numpy()
    bm, lm = _row_scores(ytrue, prob)
    bb, lb = _row_scores(ytrue, base)
    bn, ln = _row_scores(ytrue, prob_np)
    hours = times[hold].dt.hour.to_numpy()
    sessions = {}
    for name, a, b in SESSIONS:
        m = (hours >= a) & (hours < b)
        if m.sum() >= 30 and len(np.unique(ytrue[m])) == 3:
            sessions[name] = {"n": int(m.sum()), "model": metrics(ytrue[m], prob[m]), "baseline_brier": float(bb[m].mean())}
        else:
            sessions[name] = {"n": int(m.sum()), "note": "za mało próbek lub brak wszystkich klas"}
    rep = {"split": plan["boundaries_utc"], "fit_samples": int(fit.sum()), "calibration_samples": int(cal.sum()), "holdout_samples": int(hold.sum()),
           "fit_range_utc": [times[fit].min().isoformat(), times[fit].max().isoformat()],
           "fit_labels_end_utc": ends[fit].max().isoformat(), "calibration_labels_end_utc": ends[cal].max().isoformat(),
           "holdout_first_feature_utc": times[hold].min().isoformat(), "holdout_last_feature_utc": times[hold].max().isoformat(),
           "holdout_days": int(len(np.unique(days))), "counts": counts,
           "calibrated": metrics(ytrue, prob), "baseline": metrics(ytrue, base), "no_pattern_model": metrics(ytrue, prob_np),
           "reliability": reliability(ytrue, prob),
           "uncertainty_day_block_bootstrap": {"brier_model_minus_baseline": block_bootstrap(days, bm, bb),
                                               "log_loss_model_minus_baseline": block_bootstrap(days, lm, lb),
                                               "brier_model_minus_no_pattern": block_bootstrap(days, bm, bn),
                                               "log_loss_model_minus_no_pattern": block_bootstrap(days, lm, ln)},
           "sessions": sessions}
    native = {"mean": scaler.mean_.tolist(), "scale": scaler.scale_.tolist(), "classifier": export_logistic(clf), "calibrator": export_logistic(calib),
              "quantiles": {}, "knowledge_cutoff_utc": ends[cal].max().isoformat()}
    xhold = xx[hold].to_numpy()
    qs = []
    for q in (.1, .5, .9):
        log(f"h{h}", f"kwantyl q{int(q * 100)}")
        qm = GradientBoostingRegressor(loss="quantile", alpha=q, n_estimators=trees, max_depth=2, learning_rate=.05, random_state=17).fit(xx[fit], dd[fit])
        ex = export_quantile(qm)
        pred = quantile_prediction(xhold, ex)
        if not np.allclose(pred, qm.predict(xx[hold]), rtol=1e-10, atol=1e-10):
            raise SystemExit("[BLAD] PORTABLE_QUANTILE_EXPORT_VERIFICATION_FAILED")
        native["quantiles"][str(q)] = ex
        qs.append(pred)
    ordered = np.sort(np.column_stack(qs), axis=1)
    truth = dd[hold].to_numpy()
    rep["quantiles"] = {"central_80pct_empirical_coverage": float(((truth >= ordered[:, 0]) & (truth <= ordered[:, 2])).mean()),
                        "median_mae_atr": float(np.abs(truth - ordered[:, 1]).mean()),
                        "quantile_crossing_fraction_before_rearrangement": float((np.diff(np.column_stack(qs), axis=1) < 0).any(axis=1).mean())}
    nat = logistic_probability(np.log(np.clip(logistic_probability((xhold - scaler.mean_) / scaler.scale_, native["classifier"]), 1e-12, 1)), native["calibrator"])
    if not np.allclose(nat, prob, rtol=1e-10, atol=1e-10):
        raise SystemExit("[BLAD] PORTABLE_CLASSIFIER_EXPORT_VERIFICATION_FAILED")
    return native, rep


def run(args) -> int:
    from gold_candles.data import clean_json
    from gold_candles.features import feature_frame
    from gold_candles.model import SCHEMA
    data_dir = Path(args.data_dir)
    m5, m30, config, meta, files, dataset_sha = load_dataset(data_dir, args.data_kind)
    run_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "_" + dataset_sha[:8] + ("_SYN" if args.data_kind != "REAL_USER_DATA" else "")
    out = Path(args.out) if args.out else forecast_dir() / "runs" / run_id
    out.mkdir(parents=True, exist_ok=True)
    log = RunLog(out / "run_log.jsonl")
    log("start", f"run {run_id}, dane {data_dir}, {len(m5)} M5 / {0 if m30 is None else len(m30)} M30, tick {config.tick_size}",
        argv=sys.argv, interpreter=sys.executable, versions=versions())
    x, _ = feature_frame(m5, m30, config)
    usable = x.notna().all(axis=1)
    log("features", f"{int(usable.sum())} kompletnych wierszy cech z {len(x)} (warmup / luki odrzucone)")
    plan_p = data_dir / "TRAINING_PLAN.json"
    if plan_p.exists():
        plan = json.loads(plan_p.read_text(encoding="utf-8"))
        if plan.get("dataset_sha256") != dataset_sha:
            raise SystemExit("[BLAD] TRAINING_PLAN.json należy do innego zbioru danych – nowy eksport wymaga nowego katalogu.")
        log("plan", "używam zamrożonego planu " + str(plan_p))
    else:
        plan = make_plan(m5.time_close_utc[usable], dataset_sha, config, x.attrs["context_source"])
        write_json_atomic(plan_p, plan)
        log("plan", f"zapisano plan PRZED treningiem: {plan['boundaries_utc']}")
    write_json_atomic(out / "TRAINING_PLAN.json", plan)
    if int(usable.sum()) < 1500:
        reasons = [f"kompletnych wierszy cech {int(usable.sum())} < 1500 (brakuje {1500 - int(usable.sum())})"]
        summary = {"run_id": run_id, "overall_status": "INSUFFICIENT_DATA", "reasons": reasons}
        write_json_atomic(out / "forecast_validation.json", summary)
        log("end", "INSUFFICIENT_DATA")
        return 4
    models, reports, hstat = {}, {}, {}
    for h in (1, 3, 6):
        ck = out / f"checkpoint_h{h}.json"
        if ck.exists():
            saved = json.loads(ck.read_text(encoding="utf-8"))
            native, rep = saved["native"], saved["report"]
            log(f"h{h}", "wznowiono z checkpointu")
        else:
            native, rep = train_horizon(h, m5, x, usable, plan, args.trees, log)
            write_json_atomic(ck, {"native": native, "report": rep})
        if native is None:
            hstat[str(h)] = {"status": rep["status"], "reasons": rep["reasons"]}
            reports[str(h * 5)] = rep
            continue
        st, why = horizon_status(rep, args.data_kind)
        rep["status"], rep["status_reasons"] = st, why
        rep["probability_quality_candidate"] = st == "SHADOW_VALIDATED"
        native["report"] = rep
        models[str(h)] = native
        reports[str(h * 5)] = rep
        hstat[str(h)] = {"status": st, "reasons": why}
        log(f"h{h}", f"{st}: Brier {rep['calibrated']['brier_multiclass_sum']:.4f} vs baseline {rep['baseline']['brier_multiclass_sum']:.4f}, "
                     f"logloss {rep['calibrated']['log_loss']:.4f} vs {rep['baseline']['log_loss']:.4f}, dni holdoutu {rep['holdout_days']}")
    sts = [v["status"] for v in hstat.values()]
    overall = ("INSUFFICIENT_DATA" if all(s == "INSUFFICIENT_DATA" for s in sts) else
               "TRAINED_SHADOW" if all(s == "SHADOW_VALIDATED" for s in sts) else
               "REJECTED" if all(s in ("REJECTED", "INSUFFICIENT_DATA") for s in sts) else
               "PARTIAL_VALIDATION" if any(s == "SHADOW_VALIDATED" for s in sts) else "SHADOW_UNVALIDATED")
    fp = code_fingerprint()
    artifact = {"schema": SCHEMA, "config": asdict(config), "contract_hash": config.contract_hash(), "feature_names": list(x.columns),
                "context_source": x.attrs["context_source"], "created_at_utc": pd.Timestamp.now(tz="UTC").isoformat(), "data_kind": args.data_kind,
                "validation_status": "RESEARCH_ONLY_NOT_STRATEGY_VALIDATION", "versions": versions(), "models": models,
                "run_id": run_id, "dataset_sha256": dataset_sha, "code": fp, "plan_boundaries_utc": plan["boundaries_utc"]}
    model_p = out / "forecast_model.json"
    write_json_atomic(model_p, artifact)
    # the bot's inference path must reproduce the training predictions on the holdout
    runtime = runtime_check(model_p, m5, m30, config, plan, log) if len(models) == 3 else {"status": "SKIPPED_NOT_ALL_HORIZONS"}
    summary = clean_json({"run_id": run_id, "overall_status": overall, "horizon_status": hstat, "data_kind": args.data_kind, "symbol": config.symbol,
                          "tick_size": config.tick_size, "m30_source": x.attrs["context_source"], "dataset_sha256": dataset_sha, "dataset_files": files,
                          "source_metadata": meta, "feature_rows": int(usable.sum()), "horizons": reports, "runtime_check": runtime,
                          "strategy_validation": "STRATEGY_BACKTEST_NOT_AVAILABLE",
                          "meaning": "Future close direction / distribution only; not P(TP before SL), not win rate, not EV; no order permission."})
    write_json_atomic(out / "forecast_validation.json", summary)
    reg = read_registry()
    knowledge = max((m["knowledge_cutoff_utc"] for m in models.values()), default=None)
    reg["runs"][run_id] = {"run_id": run_id, "created_at_utc": artifact["created_at_utc"], "model_path": str(model_p.resolve()),
                           "artifact_sha256": sha256_file(model_p), "validation_path": str((out / "forecast_validation.json").resolve()),
                           "data_kind": args.data_kind, "data_dir": str(data_dir.resolve()), "symbol": config.symbol, "tick_size": config.tick_size, "m30_source": x.attrs["context_source"],
                           "contract_hash": config.contract_hash(), "code": fp, "dataset_sha256": dataset_sha, "feature_names": list(x.columns),
                           "label_threshold_atr": config.neutral_atr, "horizons_m5": [1, 3, 6], "horizons_trained": sorted(models), "versions": versions(),
                           "knowledge_cutoff_utc": knowledge, "train_range_utc": [plan["feature_rows_first_utc"], plan["boundaries_utc"]["calibration_start"]],
                           "horizon_status": {k: v["status"] for k, v in hstat.items()}, "overall_status": overall,
                           "training_seconds": round(time.monotonic() - log.t0, 1)}
    write_registry(reg)
    log("registry", f"zapisano run {run_id}: {overall}")
    if args.activate and args.data_kind == "REAL_USER_DATA" and len(models) == 3 and runtime.get("status") == "OK":
        activate(run_id, reason="po treningu, wszystkie horyzonty, zgodny kontrakt")
        log("registry", f"aktywny model obserwacyjny SHADOW: {run_id}")
    log("end", f"{overall}; artefakty w {out}")
    return 0


def runtime_check(model_p: Path, m5, m30, config, plan, log, sample: int = 40) -> dict:
    """Loads the saved JSON with the reference loader and runs gold_candles.model.forecast() on the last closed snapshot of
    each sampled holdout time (exactly what the bot's worker does), comparing with the in-memory predictions."""
    from gold_candles.model import forecast, load_model
    model = load_model(model_p)
    hold_start = pd.Timestamp(plan["boundaries_utc"]["holdout_start"])
    idx = np.flatnonzero((m5.time_close_utc >= hold_start).to_numpy())
    if len(idx) == 0:
        return {"status": "NO_HOLDOUT_ROWS"}
    pick = idx[np.linspace(0, len(idx) - 1, min(sample, len(idx))).astype(int)]
    t0 = time.perf_counter()
    ok = warm = 0
    for i in pick:
        cut = m5.time_close_utc.iloc[i]
        sub5 = m5.iloc[: i + 1]
        sub30 = None if m30 is None else m30.loc[m30.time_close_utc <= cut]
        r = forecast(sub5, sub30, config, model)
        if r.get("status") == "SHADOW_RESEARCH_FORECAST":
            p = [sum(v["probabilities"].values()) for v in r["probabilities"].values()]
            q = [v["close_price_quantiles"] for v in r["probabilities"].values()]
            if all(abs(s - 1) < 1e-9 for s in p) and all(x["q10"] <= x["q50"] <= x["q90"] for x in q):
                ok += 1
        else:
            warm += 1
    ms = (time.perf_counter() - t0) * 1000 / len(pick)
    log("runtime", f"inference przez ścieżkę bota: {ok}/{len(pick)} poprawnych, {warm} warmup/brak, {ms:.1f} ms / prognozę")
    return {"status": "OK" if ok > 0 and ok + warm == len(pick) else "FAILED", "checked": int(len(pick)), "valid": ok, "warmup_or_stale": warm,
            "mean_latency_ms": round(ms, 2)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Planowany trening prognoz XAUUSD 5/15/30 min (SHADOW, bez zleceń).")
    ap.add_argument("--data-dir", help="katalog eksportu bota (XAUUSD_M5.csv, XAUUSD_M30.csv, source_metadata.json)")
    ap.add_argument("--latest", action="store_true", help="najnowszy katalog z data/forecast/history")
    ap.add_argument("--out", help="katalog runu (domyślnie data/forecast/runs/<run_id>)")
    ap.add_argument("--trees", type=int, default=80)
    ap.add_argument("--data-kind", choices=("REAL_USER_DATA", "SYNTHETIC_TEST"), default="REAL_USER_DATA")
    ap.add_argument("--no-activate", dest="activate", action="store_false")
    args = ap.parse_args(argv)
    if args.latest and not args.data_dir:
        hist = sorted((forecast_dir() / "history").glob("*/source_metadata.json"))
        if not hist:
            print("[BLAD] BLOCKED_NO_REAL_DATA: brak eksportu w data/forecast/history – uruchom 11_EKSPORT_HISTORII_XAUUSD.bat przy działającym MT5.")
            return 3
        args.data_dir = str(hist[-1].parent)
    if not args.data_dir:
        ap.error("--data-dir albo --latest")
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
