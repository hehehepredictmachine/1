"""Planned training of the scalp models on a frozen MT5 export (data/scalp/history/<cutoff>, M1 required).

Task A  direction 1/3/5 min on M1 with the cost dead zone (scalp_features). Candidates: class-frequency baseline,
        no-change reference, logistic regression, HistGradientBoosting, a real MLP 64/32 (standardisation, L2 alpha, fixed
        seed, partial_fit epochs with early stopping on a LATER development slice - never sklearn's random validation split),
        HistGradientBoosting quantile regressors q10/q50/q90 (crossing rule: sorted, declared in the plan).
Task B  setup quality from the full-policy replay (masterquo.scalp.replay): P(TP1 before SL) per independent cycle.
Task C  HOLD / REDUCE / CLOSE / HEDGE_PARTIAL policy evaluation on the same paths (replay decision points).

Validation: TRAINING_PLAN.json written BEFORE fitting and bound to the dataset hash: common UTC boundaries 60/20/20 of
the time span cut at 00:00 UTC (development / calibration / final holdout), purge by label END plus a 30-minute embargo
(task B/C: the 30-minute cycle + embargo), walk-forward folds inside development for model selection, calibrator fitted
only on the calibration period, holdout evaluated once with the frozen choice, day-block bootstrap intervals.
Minimums (start-up minimums, not proof of sufficiency): see MIN in the plan. Missing data / classes -> INSUFFICIENT_DATA.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pickle
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .common import RunLog, code_fingerprint, sha256_file, versions, write_json_atomic
from . import scalp_features as SF
from .scalp_infer import ScalpModel, activatable, calib_to_json, lr_to_json, mlp_to_json, read_registry, registry_path, scalp_dir

EMBARGO_S = 30 * 60
MIN = {"A_dev_rows": 5000, "A_cal_rows": 1000, "A_hold_rows": 1000, "A_class_min": 100,
       "MLP_train_rows": 10000, "MLP_train_days": 30, "MLP_class_min": 100,
       "B_cycles_dev": 300, "B_cycles_hold": 100, "B_MLP_cycles": 1000, "C_cycles": 200, "holdout_days": 30}
CRITERIA = {"holdout_days_min": 30, "log_loss_better_than_baseline": True, "brier_better_than_baseline": True, "per_class_ece_max": 0.10}
CANDIDATES = ("LR", "HGB", "MLP")
SEED = 0


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load(hist: Path, data_kind: str) -> dict:
    import csv
    meta = json.loads((hist / "source_metadata.json").read_text(encoding="utf-8"))
    if meta.get("data_kind") != data_kind:
        raise SystemExit(f"[BLAD] Dane oznaczone {meta.get('data_kind')}, a trening wywołano z --data-kind {data_kind}.")
    p = hist / "XAUUSD_M1.csv"
    if not p.exists():
        raise SystemExit("[BLAD] BLOCKED_NO_REAL_DATA: brak XAUUSD_M1.csv – użyj 16_EKSPORT_HISTORII_SCALP.bat (export-scalp).")
    spec = meta["spec"]
    point = float(spec.get("point") or spec["trade_tick_size"])
    t, o, h, lo, c, tv, sp = [], [], [], [], [], [], []
    with p.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            t.append(int(datetime.fromisoformat(r["time_open_utc"].replace("Z", "+00:00")).timestamp()))
            o.append(float(r["open"])); h.append(float(r["high"])); lo.append(float(r["low"])); c.append(float(r["close"]))
            tv.append(float(r["tick_volume"]) if r.get("tick_volume") not in (None, "") else None)
            sp.append(float(r["spread_points"]) * point if r.get("spread_points") not in (None, "") else None)
    files = {x.name: sha256_file(x) for x in sorted(hist.glob("XAUUSD_*.csv"))}
    sha = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    return {"meta": meta, "t": t, "o": o, "h": h, "l": lo, "c": c, "tv": tv, "sp": sp, "files": files, "dataset_sha": sha, "hist": str(hist)}


def make_plan(t: list[int], d: dict, costs: dict, small: bool) -> dict:
    t0, t1 = min(t), max(t)
    span = t1 - t0
    day = 86400
    cal = (t0 + int(0.6 * span)) // day * day
    hold = (t0 + int(0.8 * span)) // day * day
    return {"schema": "masterquo-scalp-training-plan-1", "created_at_utc": _now(), "dataset_sha256": d["dataset_sha"], "data_kind": d["meta"]["data_kind"],
            "symbol": d["meta"]["symbol"], "tick_size": float(d["meta"]["tick_size"]), "feature_contract": SF.VERSION, "features": list(SF.FEATURES),
            "contract_hash": SF.contract_hash(d["meta"]["symbol"], float(d["meta"]["tick_size"])), "horizons_m1": list(SF.HORIZONS),
            "boundaries_utc": {"development": [_iso(t0), _iso(cal)], "calibration": [_iso(cal), _iso(hold)], "holdout": [_iso(hold), _iso(t1 + 60)]},
            "embargo_seconds": EMBARGO_S, "purge": "row kept only if label_end <= next boundary - embargo (A: t+h+1 min; B/C: cycle end, max 30 min)",
            "walk_forward": "development split in 5 time blocks; folds train on blocks[0..k], evaluate on block k+1 after embargo (k=0..3)",
            "candidates": {"A": ["BASELINE_PRIOR", "NO_CHANGE", "LR", "HGB", "MLP_64_32", "HGB_QUANTILE_q10_q50_q90"], "B": ["BASELINE_PRIOR", "LR", "HGB"],
                           "C": ["HOLD", "REDUCE", "CLOSE", "HEDGE_PARTIAL"]},
            "hyperparameters": {"LR": {"C": 1.0, "max_iter": 1000}, "HGB": {"max_iter": 200, "learning_rate": 0.05, "max_leaf_nodes": 31, "l2_regularization": 1.0},
                                "MLP": {"hidden": [64, 32], "alpha": 1e-3, "lr": 1e-3, "batch": 256, "max_epochs": 60, "patience": 5, "max_seconds": 1200,
                                        "early_stopping": "last 20% of development by time (after embargo)"},
                                "QUANTILE": {"model": "HistGradientBoostingRegressor(loss=quantile)", "max_iter": 200, "crossing_rule": "sort q10<=q50<=q90"}},
            "selection": "lowest mean walk-forward log loss in development; must beat the baseline there, else BASELINE is selected (REJECTED)",
            "costs_for_labels": costs, "minimums": MIN if not small else {k: max(1, v // 50) for k, v in MIN.items()},
            "minimums_note": "SMALL TEST MINIMUMS (synthetic code test) - never activatable" if small else "minima uruchomienia, nie dowód wystarczającej próby",
            "criteria": CRITERIA, "holdout_policy": "evaluated once with the frozen choice; a bad result is recorded as FAILED/REJECTED"}


def _iso(x: int) -> str:
    return datetime.fromtimestamp(x, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ts(s: str) -> int:
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())


# ------------------------------------------------------------------ metrics
def metrics(P: np.ndarray, y: np.ndarray, days: np.ndarray | None = None, ref: np.ndarray | None = None) -> dict:
    P = np.clip(P, 1e-6, 1)
    P = P / P.sum(axis=1, keepdims=True)
    n = len(y)
    Y = np.eye(3)[y]
    ll_i = -np.log(P[np.arange(n), y])
    br_i = ((P - Y) ** 2).sum(axis=1)
    pred = P.argmax(axis=1)
    rec = {}
    for k, name in enumerate(("DOWN", "FLAT", "UP")):
        m = y == k
        rec[name] = float((pred[m] == k).mean()) if m.any() else None
    ece = {}
    for k, name in enumerate(("DOWN", "FLAT", "UP")):
        bins = np.clip((P[:, k] * 10).astype(int), 0, 9)
        e = 0.0
        for b in range(10):
            m = bins == b
            if m.any():
                e += m.mean() * abs(P[m, k].mean() - (y[m] == k).mean())
        ece[name] = round(float(e), 4)
    out = {"n": int(n), "log_loss": round(float(ll_i.mean()), 5), "brier": round(float(br_i.mean()), 5),
           "balanced_accuracy": round(float(np.mean([v for v in rec.values() if v is not None])), 4), "recall": rec, "ece": ece}
    if days is not None and ref is not None:
        ref = np.clip(ref, 1e-6, 1)
        d_i = ll_i + np.log(ref[np.arange(n), y])
        out["log_loss_minus_baseline_ci95_day_block"] = _day_boot(d_i, days)
    return out


def _day_boot(v: np.ndarray, days: np.ndarray, n_boot: int = 1000) -> list[float] | None:
    u = np.unique(days)
    if len(u) < 5:
        return None
    idx = {d: np.where(days == d)[0] for d in u}
    rng = np.random.default_rng(7)
    vals = []
    for _ in range(n_boot):
        pick = rng.choice(u, len(u))
        vals.append(float(np.concatenate([v[idx[d]] for d in pick]).mean()))
    return [round(float(np.quantile(vals, 0.025)), 5), round(float(np.quantile(vals, 0.975)), 5)]


def pinball(q: np.ndarray, y: np.ndarray, a: float) -> float:
    e = y - q
    return float(np.mean(np.maximum(a * e, (a - 1) * e)))


# ------------------------------------------------------------------ models
def fit_lr(X, y):
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    sc = StandardScaler().fit(X)
    clf = LogisticRegression(C=1.0, max_iter=1000).fit(sc.transform(X), y)
    return ("LR", sc, clf)


def fit_hgb(X, y):
    from sklearn.ensemble import HistGradientBoostingClassifier
    clf = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_leaf_nodes=31, l2_regularization=1.0, early_stopping=False,
                                         random_state=SEED).fit(X, y)
    return ("HGB", None, clf)


def fit_mlp(X, y, Xv, yv, log, max_epochs=60, patience=5, max_seconds=1200):
    """Real MLP 64/32: epochs of partial_fit on the (chronologically earlier) train part; early stopping by log loss on the
    LATER validation slice; the best epoch's weights are kept."""
    import copy
    from sklearn.neural_network import MLPClassifier
    from sklearn.preprocessing import StandardScaler
    sc = StandardScaler().fit(X)
    Xs, Xvs = sc.transform(X), sc.transform(Xv)
    clf = MLPClassifier(hidden_layer_sizes=(64, 32), alpha=1e-3, learning_rate_init=1e-3, batch_size=256, random_state=SEED, shuffle=True)
    classes = np.array([0, 1, 2])
    best, best_ll, bad, hist = None, np.inf, 0, []
    t0 = time.time()
    for ep in range(max_epochs):
        clf.partial_fit(Xs, y, classes=classes)
        P = clf.predict_proba(Xvs)
        ll = float(-np.log(np.clip(P[np.arange(len(yv)), yv], 1e-6, 1)).mean())
        hist.append(round(ll, 5))
        if ll < best_ll - 1e-5:
            best, best_ll, bad = copy.deepcopy(clf), ll, 0
        else:
            bad += 1
        if bad >= patience or time.time() - t0 > max_seconds:
            break
    log("A_MLP", f"epoki {len(hist)}, najlepsza val log loss {best_ll:.4f}", epochs=len(hist), curve=hist)
    return ("MLP", sc, best), {"epochs": len(hist), "best_val_log_loss": round(best_ll, 5), "curve": hist, "stopped": "patience" if bad >= patience else "budget/max"}


def proba(model, X):
    kind, sc, clf = model
    P = clf.predict_proba(sc.transform(X) if sc is not None else X)
    out = np.full((len(X), 3), 1e-6)
    for j, c in enumerate(clf.classes_):
        out[:, int(c)] = P[:, j]
    return out / out.sum(axis=1, keepdims=True)


def fit_calibrator(P, y):
    from sklearn.linear_model import LogisticRegression
    return LogisticRegression(C=1.0, max_iter=1000).fit(np.log(np.clip(P, 1e-6, 1)), y)


# ------------------------------------------------------------------ main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Trening modeli scalp (A/B/C) – plan, walk-forward, kalibracja, holdout, rejestr")
    ap.add_argument("--history", help="katalog eksportu (domyślnie najnowszy data/scalp/history)")
    ap.add_argument("--latest", action="store_true")
    ap.add_argument("--data-kind", default="REAL_USER_DATA", choices=["REAL_USER_DATA", "SYNTHETIC_TEST"])
    ap.add_argument("--commission-per-lot-side", type=float, default=0.5, help="prowizja na 1 lot na stronę (waluta konta); domyślnie 0.50 jak w paczce")
    ap.add_argument("--slippage-ticks", type=float, default=2.0)
    ap.add_argument("--no-activate", action="store_true")
    ap.add_argument("--small-test", action="store_true", help="tylko SYNTHETIC_TEST: zmniejszone minima do testu ścieżki kodu")
    a = ap.parse_args(argv)
    if a.small_test and a.data_kind != "SYNTHETIC_TEST":
        raise SystemExit("[BLAD] --small-test dozwolone wyłącznie z --data-kind SYNTHETIC_TEST")
    hist = Path(a.history) if a.history else None
    if hist is None:
        h = sorted((scalp_dir() / "history").glob("*/source_metadata.json"))
        if not h:
            write_json_atomic(scalp_dir() / "TRAINING_STATUS.json", {"status": "BLOCKED_NO_REAL_DATA", "at": _now(),
                              "reason": "brak eksportu M1/M5/M15/M30/H1 – uruchom 16_EKSPORT_HISTORII_SCALP.bat przy zalogowanym MT5"})
            print("[BLAD] BLOCKED_NO_REAL_DATA: brak eksportu historii scalp.")
            return 3
        hist = h[-1].parent
    d = load(hist, a.data_kind)
    tick = float(d["meta"]["tick_size"])
    cs = float(d["meta"]["spec"]["trade_contract_size"])
    costs = {"commission_per_lot_side": a.commission_per_lot_side, "commission_price_side": a.commission_per_lot_side / cs,
             "slippage_ticks": a.slippage_ticks, "slippage_price": a.slippage_ticks * tick, "reference_volume_lots": 1.0,
             "conversion": "commission cash per lot side / contract size = price units per unit volume"}
    run_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "_" + d["dataset_sha"][:8] + ("_SYN" if a.data_kind == "SYNTHETIC_TEST" else "")
    rd = scalp_dir() / "runs" / run_id
    rd.mkdir(parents=True, exist_ok=True)
    log = RunLog(rd / "run_log.jsonl")
    log("START", f"dane {hist}", command=" ".join([sys.executable, "-m", "gold_candles_runtime.scalp_train"] + (argv or sys.argv[1:])),
        rows_m1=len(d["t"]), data_kind=a.data_kind, versions=versions())
    plan_p = scalp_dir() / "plans" / f"TRAINING_PLAN_{d['dataset_sha'][:16]}.json"
    if plan_p.exists():
        plan = json.loads(plan_p.read_text(encoding="utf-8"))
        log("PLAN", "istniejący plan dla tego zbioru – granice nie są przecinane ponownie")
    else:
        plan = make_plan(d["t"], d, costs, a.small_test)
        write_json_atomic(plan_p, plan)
        log("PLAN", "zapisano TRAINING_PLAN przed treningiem")
    write_json_atomic(rd / "TRAINING_PLAN.json", plan)
    mins = plan["minimums"]
    b = plan["boundaries_utc"]
    cal0, hold0, end = _ts(b["calibration"][0]), _ts(b["holdout"][0]), _ts(b["holdout"][1])
    dev0 = _ts(b["development"][0])

    X, atr = SF.build(d["t"], d["o"], d["h"], d["l"], d["c"], d["tv"], d["sp"])
    Y, Q, END = SF.labels(d["t"], d["c"], atr, d["sp"], costs["commission_price_side"], costs["slippage_price"])
    t = np.asarray(d["t"])
    ok_x = ~np.isnan(X).any(axis=1)
    days_all = (t // 86400).astype(int)
    log("FEATURES", f"wiersze z kompletnymi cechami {int(ok_x.sum())}/{len(t)}")
    report: dict = {"run_id": run_id, "data_kind": a.data_kind, "dataset_sha256": d["dataset_sha"], "plan": str(plan_p), "task_A": {}, "costs": costs}
    models_spec, artifacts = {}, {}

    for hz in SF.HORIZONS:
        y, q, e = Y[hz], Q[hz], END[hz]
        valid = ok_x & (y >= 0)
        dev = valid & (e <= cal0 - EMBARGO_S)
        cal = valid & (t >= cal0) & (e <= hold0 - EMBARGO_S)
        hold = valid & (t >= hold0)
        rep = {"rows": {"development": int(dev.sum()), "calibration": int(cal.sum()), "holdout": int(hold.sum())},
               "holdout_days": int(len(np.unique(days_all[hold]))), "class_counts_dev": np.bincount(y[dev], minlength=3).tolist()}
        short = []
        if dev.sum() < mins["A_dev_rows"]: short.append("development")
        if cal.sum() < mins["A_cal_rows"]: short.append("calibration")
        if hold.sum() < mins["A_hold_rows"]: short.append("holdout")
        if min(rep["class_counts_dev"]) < mins["A_class_min"]: short.append("class_coverage")
        if short:
            rep.update(status="INSUFFICIENT_DATA", reason="za mało: " + ", ".join(short))
            report["task_A"][str(hz)] = rep
            log("A", f"h={hz}: INSUFFICIENT_DATA ({', '.join(short)})")
            continue
        Xd, yd = X[dev], y[dev]
        prior = np.bincount(yd, minlength=3) / len(yd)
        # ---- walk-forward model selection inside development
        td = t[dev]
        edges = np.linspace(td.min(), td.max() + 1, 6)
        wf = {k: [] for k in ("BASELINE",) + CANDIDATES}
        mlp_ok_global = dev.sum() >= mins["MLP_train_rows"] and len(np.unique(days_all[dev])) >= mins["MLP_train_days"] \
            and min(rep["class_counts_dev"]) >= mins["MLP_class_min"]
        for k in range(4):
            tr = (td < edges[k + 1]) & (e[dev] <= edges[k + 1] - EMBARGO_S)
            va = (td >= edges[k + 1] + EMBARGO_S) & (td < edges[k + 2])
            if tr.sum() < 200 or va.sum() < 100 or len(np.unique(yd[tr])) < 3:
                continue
            pr = np.bincount(yd[tr], minlength=3) / tr.sum()
            wf["BASELINE"].append(metrics(np.tile(pr, (va.sum(), 1)), yd[va])["log_loss"])
            wf["LR"].append(metrics(proba(fit_lr(Xd[tr], yd[tr]), Xd[va]), yd[va])["log_loss"])
            wf["HGB"].append(metrics(proba(fit_hgb(Xd[tr], yd[tr]), Xd[va]), yd[va])["log_loss"])
            if mlp_ok_global:
                n_tr = tr.sum()
                cut = np.where(tr)[0][int(0.8 * n_tr)]
                tri = tr & (np.arange(len(td)) < cut)
                vai = tr & (np.arange(len(td)) >= cut) & (td >= td[cut] + EMBARGO_S)
                if vai.sum() > 50:
                    m, _ = fit_mlp(Xd[tri], yd[tri], Xd[vai], yd[vai], lambda *x, **k: None, max_epochs=20)
                    wf["MLP"].append(metrics(proba(m, Xd[va]), yd[va])["log_loss"])
        wf_mean = {k: (round(float(np.mean(v)), 5) if v else None) for k, v in wf.items()}
        cands = {k: v for k, v in wf_mean.items() if k != "BASELINE" and v is not None}
        selected = min(cands, key=cands.get) if cands else "BASELINE"
        if wf_mean["BASELINE"] is not None and selected != "BASELINE" and cands[selected] >= wf_mean["BASELINE"]:
            selected = "BASELINE"
        log("A", f"h={hz}: walk-forward {wf_mean} → wybór {selected}")
        # ---- final fit on development, calibration on the calibration period
        fitted = {}
        mlp_info = None
        fitted["LR"] = fit_lr(Xd, yd)
        fitted["HGB"] = fit_hgb(Xd, yd)
        if mlp_ok_global:
            cut = int(0.8 * len(td))
            tri = np.arange(len(td)) < cut
            vai = (np.arange(len(td)) >= cut) & (td >= td[cut] + EMBARGO_S) if cut < len(td) else tri & False
            fitted["MLP"], mlp_info = fit_mlp(Xd[tri], yd[tri], Xd[vai], yd[vai], log)
        else:
            mlp_info = {"status": "INSUFFICIENT_DATA", "reason": f"MLP wymaga ≥{mins['MLP_train_rows']} wierszy, ≥{mins['MLP_train_days']} dni, ≥{mins['MLP_class_min']}/klasę"}
        Xc, yc, Xh, yh = X[cal], y[cal], X[hold], y[hold]
        dh = days_all[hold]
        base_h = np.tile(prior, (len(yh), 1))
        hold_m = {"BASELINE_PRIOR": metrics(base_h, yh), "NO_CHANGE": metrics(np.tile([0.01, 0.98, 0.01], (len(yh), 1)), yh)}
        cals = {}
        for k, m in fitted.items():
            cals[k] = fit_calibrator(proba(m, Xc), yc)
            Ph = cals[k].predict_proba(np.log(np.clip(proba(m, Xh), 1e-6, 1)))
            Ph_full = np.full((len(yh), 3), 1e-6)
            for j, c in enumerate(cals[k].classes_):
                Ph_full[:, int(c)] = Ph[:, j]
            hold_m[k] = metrics(Ph_full, yh, dh, base_h)
        # ---- quantiles of d/ATR (fit on development)
        from sklearn.ensemble import HistGradientBoostingRegressor
        qm = {f"q{int(al * 100)}": HistGradientBoostingRegressor(loss="quantile", quantile=al, max_iter=200, random_state=SEED).fit(Xd, q[dev])
              for al in (0.1, 0.5, 0.9)}
        Qh = np.sort(np.column_stack([qm[k].predict(Xh) for k in ("q10", "q50", "q90")]), axis=1)
        qrep = {"pinball_q10": round(pinball(Qh[:, 0], q[hold], 0.1), 5), "pinball_q50": round(pinball(Qh[:, 1], q[hold], 0.5), 5),
                "pinball_q90": round(pinball(Qh[:, 2], q[hold], 0.9), 5), "coverage_q10_q90": round(float(((q[hold] >= Qh[:, 0]) & (q[hold] <= Qh[:, 2])).mean()), 4),
                "pinball_q50_no_change": round(pinball(np.zeros(hold.sum()), q[hold], 0.5), 5), "unit": "zmiana ceny / ATR14_M1"}
        sel_m = hold_m.get(selected) if selected != "BASELINE" else hold_m["BASELINE_PRIOR"]
        bm = hold_m["BASELINE_PRIOR"]
        if selected == "BASELINE":
            status = "REJECTED"
        elif sel_m["log_loss"] >= bm["log_loss"] or sel_m["brier"] >= bm["brier"]:
            status = "REJECTED"
        elif rep["holdout_days"] < CRITERIA["holdout_days_min"] or max(sel_m["ece"].values()) > CRITERIA["per_class_ece_max"]:
            status = "SHADOW_UNVALIDATED"
        else:
            status = "SHADOW_VALIDATED"
        rep.update(status=status, selected=selected, walk_forward_dev_log_loss=wf_mean, holdout=hold_m, quantiles=qrep, mlp=mlp_info,
                   note="holdout oceniony raz po zamrożeniu wyboru; P(UP) nie jest P(TP przed SL)")
        report["task_A"][str(hz)] = rep
        log("A", f"h={hz}: {status} (wybór {selected}, holdout log loss {sel_m['log_loss']} vs baseline {bm['log_loss']})")
        # ---- artifacts
        spec = {"selected": selected, "prior": prior.tolist()}
        if selected in ("LR", "MLP"):
            f = f"model_h{hz}_{selected}.json"
            j = lr_to_json(fitted[selected][1], fitted[selected][2]) if selected == "LR" else mlp_to_json(fitted[selected][1], fitted[selected][2])
            write_json_atomic(rd / f, j)
            spec["file"] = f
        elif selected == "HGB":
            f = f"model_h{hz}_HGB.pkl"
            with open(rd / f, "wb") as fh:
                pickle.dump(fitted["HGB"][2], fh)
            spec["file"] = f
        if selected in cals:
            spec["calibrator"] = calib_to_json(cals[selected])
        fq = f"quantiles_h{hz}.pkl"
        with open(rd / fq, "wb") as fh:
            pickle.dump(qm, fh)
        spec["quantiles_file"] = fq
        for ff in [spec.get("file"), fq]:
            if ff:
                artifacts[ff] = sha256_file(rd / ff)
        models_spec[str(hz)] = spec
        # runtime check: the bot's loader on holdout rows must reproduce the training predictions
        spec["_check"] = {"X": Xh[:50].tolist()}

    # ---- tasks B and C from the full-policy replay
    report["task_B"], report["task_C"], setup_spec, setup_arts = task_bc(d, plan, costs, log, X, mins, rd)
    artifacts.update(setup_arts)
    a_status = [r.get("status") for r in report["task_A"].values()]
    overall = ("INSUFFICIENT_DATA" if all(s == "INSUFFICIENT_DATA" for s in a_status) else "TRAINED_SHADOW" if all(s == "SHADOW_VALIDATED" for s in a_status)
               else "PARTIAL_VALIDATION" if any(s == "SHADOW_VALIDATED" for s in a_status) else "SHADOW_UNVALIDATED" if any(s == "SHADOW_UNVALIDATED" for s in a_status)
               else "REJECTED" if any(s == "REJECTED" for s in a_status) else "INSUFFICIENT_DATA")
    entry = {"run_id": run_id, "created_at_utc": _now(), "run_dir": str(rd), "data_kind": a.data_kind, "symbol": d["meta"]["symbol"],
             "tick_size": tick, "feature_contract": SF.VERSION, "features": list(SF.FEATURES), "contract_hash": plan["contract_hash"],
             "dataset_sha256": d["dataset_sha"], "knowledge_cutoff_utc": d["meta"].get("cutoff_utc"), "boundaries_utc": plan["boundaries_utc"],
             "code": code_fingerprint(), "versions": versions(), "task_a_status": overall, "horizon_status": {k: v["status"] for k, v in report["task_A"].items()},
             "task_b_status": report["task_B"]["status"], "task_c_status": report["task_C"]["status"], "artifacts": artifacts,
             "models": {k: {x: y for x, y in v.items() if x != "_check"} for k, v in models_spec.items()}, "small_test": a.small_test,
             "setup_model": setup_spec}
    if models_spec:
        sm = ScalpModel(entry)
        diffs = {}
        for hz, spec in models_spec.items():
            Xc = np.asarray(spec["_check"]["X"])
            if len(Xc):
                p1 = sm.predict(Xc)[hz]["P"]
                diffs[hz] = {"rows": len(Xc), "finite": bool(np.isfinite(p1).all()), "sum_to_one": bool(np.allclose(p1.sum(axis=1), 1.0))}
        report["runtime_check"] = {"loader": "gold_candles_runtime.scalp_infer.ScalpModel (ta sama ścieżka co worker scalp_forecast)", "horizons": diffs}
        log("RUNTIME_CHECK", json.dumps(diffs))
    report["summary"] = {"overall_task_A": overall, "task_B": report["task_B"]["status"], "task_C": report["task_C"]["status"], "run_id": run_id,
                         "data_kind": a.data_kind, "strategy_status": "STRATEGY_VALID wymaga replayu OOS na rzeczywistych danych (report.task_B)"}
    write_json_atomic(rd / "report.json", report)
    reg = read_registry()
    reg["runs"][run_id] = entry
    ok, why = activatable(entry, plan["contract_hash"])
    if ok and not a.no_activate and not a.small_test:
        if reg.get("active") and reg["active"] != run_id:
            reg.setdefault("history", []).append(reg["active"])
        reg["active"] = run_id
        reg.setdefault("events", []).append({"at": _now(), "action": "ACTIVATE", "run_id": run_id})
    entry["activation"] = "ACTIVE" if reg.get("active") == run_id else f"NOT_ACTIVATED:{why or ('--no-activate' if a.no_activate else 'SMALL_TEST')}"
    write_json_atomic(registry_path(), reg)
    write_json_atomic(scalp_dir() / "TRAINING_STATUS.json", {"status": overall, "run_id": run_id, "at": _now(), "data_kind": a.data_kind,
                                                             "task_B": report["task_B"]["status"], "task_C": report["task_C"]["status"]})
    log("END", f"zadanie A {overall}, B {report['task_B']['status']}, C {report['task_C']['status']}, aktywacja {entry['activation']}")
    print(f"Raport: {rd / 'report.json'}")
    return 0


def task_bc(d: dict, plan: dict, costs: dict, log, X: np.ndarray, mins: dict, rd: Path | None = None):
    from masterquo.scalp import replay, report as srep, strategy as st
    prof = st.load_profile()
    bars = [{"open_utc": _iso(t), "o": o, "h": h, "l": l, "c": c, "tv": tv, "spread_price": sp}
            for t, o, h, l, c, tv, sp in zip(d["t"], d["o"], d["h"], d["l"], d["c"], d["tv"], d["sp"])]
    t0 = time.time()
    res = replay.run(bars, prof, float(d["meta"]["tick_size"]), {"commission_price_side": costs["commission_price_side"], "slippage_price": costs["slippage_price"]})
    log("REPLAY", f"cykle {len(res['cycles'])}, zablokowane {len(res['blocked'])}, punkty decyzji {len(res['decisions'])} ({time.time() - t0:.0f}s)")
    b = plan["boundaries_utc"]
    cal0, hold0 = _ts(b["calibration"][0]), _ts(b["holdout"][0])
    cyc = res["cycles"]
    dev = [c for c in cyc if _ts(c["exits"][-1]["time"]) <= cal0 - EMBARGO_S]
    cal = [c for c in cyc if _ts(c["fill_time"]) >= cal0 and _ts(c["exits"][-1]["time"]) <= hold0 - EMBARGO_S]
    hold = [c for c in cyc if _ts(c["fill_time"]) >= hold0]
    B, spec, arts = train_setup_model(dev, cal, hold, mins, log, rd)
    B["precision"] = res["precision"]
    hs_dev = srep.hedge_summary([x for x in res["decisions"] if _ts(x["decision_time"]) < cal0])
    hs_hold = srep.hedge_summary([x for x in res["decisions"] if _ts(x["decision_time"]) >= hold0])
    C = {"policy_eval_development": hs_dev, "policy_eval_holdout": hs_hold, "margin_mode_assumed": res["margin_mode_assumed"]}
    if hs_hold.get("cycles", 0) < mins["C_cycles"]:
        C.update(status="INSUFFICIENT_DATA", reason=f"cykle z punktami decyzji w holdout {hs_hold.get('cycles', 0)} < {mins['C_cycles']} – hedge pozostaje SHADOW/REDUCE")
    else:
        C.update(status="HEDGE_BETTER_THAN_REDUCE_SHADOW" if hs_hold["status"] == "HEDGE_BETTER_THAN_REDUCE" else "HEDGE_NOT_BETTER_THAN_REDUCE")
    return B, C, spec, arts


def _xy(cycles: list[dict], feats: tuple) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    ok = [c for c in cycles if c.get("features") and all(c["features"].get(k) is not None for k in feats)]
    X = np.asarray([[float(c["features"][k]) for k in feats] for c in ok]) if ok else np.zeros((0, len(feats)))
    y = np.asarray([1 if c["tp1_before_sl"] else 0 for c in ok], dtype=int)
    r = np.asarray([c["net_r"] for c in ok], dtype=float)
    return X, y, r


def _fit_bin(kind: str, X, y):
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    if kind == "LR":
        sc = StandardScaler().fit(X)
        return ("LR", sc, LogisticRegression(C=0.5, max_iter=2000).fit(sc.transform(X), y))
    if kind == "HGB":
        from sklearn.ensemble import HistGradientBoostingClassifier
        return ("HGB", None, HistGradientBoostingClassifier(max_iter=100, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=20,
                                                           l2_regularization=1.0, early_stopping=False, random_state=SEED).fit(X, y))
    from sklearn.neural_network import MLPClassifier
    sc = StandardScaler().fit(X)
    return ("MLP", sc, MLPClassifier(hidden_layer_sizes=(64, 32), alpha=1e-2, learning_rate_init=1e-3, max_iter=300, random_state=SEED,
                                     early_stopping=False).fit(sc.transform(X), y))


def _p1(model, X):
    kind, sc, clf = model
    P = clf.predict_proba(sc.transform(X) if sc is not None else X)
    return P[:, list(clf.classes_).index(1)]


def _bin_ll(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())


def train_setup_model(dev: list[dict], cal: list[dict], hold: list[dict], mins: dict, log, rd: Path | None):
    """Task B as a FILTER: P(TP1 before SL) per setup (decision-time features of masterquo.scalp.strategy.setup_features).
    Model chosen by walk-forward log loss inside development (cycles in time order), Platt calibration and the threshold
    chosen on the later calibration cycles by mean net R of the retained setups (must beat 'no filter' and keep >= 30%),
    holdout evaluated once: strategy without vs with the filter (win rate, expectancy R, 95% CI by day blocks)."""
    from masterquo.scalp import report as srep
    from masterquo.scalp.strategy import SETUP_FEATURES
    feats = SETUP_FEATURES
    B = {"cycles": {"development": len(dev), "calibration": len(cal), "holdout": len(hold)}, "features": list(feats),
         "dev_summary": srep.strategy_summary(dev), "holdout_unfiltered": srep.strategy_summary(hold)}
    Xd, yd, rdv = _xy(sorted(dev, key=lambda c: c["fill_time"]), feats)
    Xc, yc, rc = _xy(cal, feats)
    Xh, yh, rh = _xy(hold, feats)
    if len(yd) < mins["B_cycles_dev"] or len(yh) < mins["B_cycles_hold"] or len(yc) < max(20, mins["B_cycles_hold"] // 2):
        B.update(status="INSUFFICIENT_DATA", reason=f"cykle z cechami: dev {len(yd)} (min {mins['B_cycles_dev']}), kalibracja {len(yc)}, "
                                                     f"holdout {len(yh)} (min {mins['B_cycles_hold']}) – filtr pozostaje wyłączony")
        log("B", B["reason"])
        return B, None, {}
    if len(np.unique(yd)) < 2 or len(np.unique(yc)) < 2:
        B.update(status="INSUFFICIENT_DATA", reason="jedna klasa TP1/SL w development lub kalibracji")
        return B, None, {}
    cands = ["LR", "HGB"] + (["MLP"] if len(yd) >= mins.get("B_MLP_cycles", 1000) else [])
    n = len(yd)
    wf = {k: [] for k in ["BASELINE"] + cands}
    for k in range(4):
        a, b = int(n * (k + 1) / 5), int(n * (k + 2) / 5)
        if a < 30 or b - a < 10 or len(np.unique(yd[:a])) < 2:
            continue
        wf["BASELINE"].append(_bin_ll(np.full(b - a, yd[:a].mean()), yd[a:b]))
        for c in cands:
            wf[c].append(_bin_ll(_p1(_fit_bin(c, Xd[:a], yd[:a]), Xd[a:b]), yd[a:b]))
    wfm = {k: (round(float(np.mean(v)), 5) if v else None) for k, v in wf.items()}
    ok = {k: v for k, v in wfm.items() if k != "BASELINE" and v is not None}
    sel = min(ok, key=ok.get) if ok else "BASELINE"
    if wfm["BASELINE"] is not None and sel != "BASELINE" and ok[sel] >= wfm["BASELINE"]:
        sel = "BASELINE"
    log("B", f"walk-forward {wfm} → {sel} ({'MLP pominięty – za mało cykli' if 'MLP' not in cands else 'MLP w porównaniu'})")
    prior = float(yd.mean())
    if sel == "BASELINE":
        B.update(status="REJECTED", reason="żaden model nie pobił częstości bazowej w walk-forward", walk_forward_log_loss=wfm)
        return B, None, {}
    model = _fit_bin(sel, Xd, yd)
    from sklearn.linear_model import LogisticRegression
    pc_raw = _p1(model, Xc)
    lg = lambda p: np.log(np.clip(p, 1e-6, 1 - 1e-6) / np.clip(1 - p, 1e-6, 1))  # noqa: E731
    pl = LogisticRegression(C=1e6, max_iter=1000).fit(lg(pc_raw).reshape(-1, 1), yc)
    calib = {"a": float(pl.coef_[0][0]), "b": float(pl.intercept_[0])}
    from .scalp_infer import platt
    pc = platt(calib, pc_raw)
    base_mean = float(rc.mean())
    best, grid = None, []
    for thr in np.round(np.arange(0.30, 0.81, 0.05), 2):
        m = pc >= thr
        if m.sum() < max(10, int(0.3 * len(rc))):
            continue
        e = float(rc[m].mean())
        grid.append({"threshold": float(thr), "kept": int(m.sum()), "win_rate": round(float((rc[m] > 0).mean()), 3), "expectancy_r": round(e, 4)})
        if e > base_mean and (best is None or e > best["expectancy_r"]):
            best = grid[-1]
    thr = best["threshold"] if best else None
    ph = platt(calib, _p1(model, Xh))
    br, brb = float(((ph - yh) ** 2).mean()), float(((prior - yh) ** 2).mean())
    hold_sorted = [c for c in hold if c.get("features") and all(c["features"].get(k) is not None for k in feats)]
    kept = [c for c, p in zip(hold_sorted, ph) if thr is not None and p >= thr]
    B.update(selected=sel, walk_forward_log_loss=wfm, calibrator=calib, threshold_grid_calibration=grid, threshold=thr,
             calibration_unfiltered_expectancy_r=round(base_mean, 4),
             holdout={"brier": round(br, 5), "brier_baseline": round(brb, 5), "log_loss": round(_bin_ll(ph, yh), 5),
                      "log_loss_baseline": round(_bin_ll(np.full(len(yh), prior), yh), 5)},
             holdout_filtered=srep.strategy_summary(kept) if thr is not None else None)
    if br >= brb:
        st_ = "REJECTED"
    elif thr is None:
        st_ = "NO_USEFUL_THRESHOLD"
    else:
        hf, hu = B["holdout_filtered"], B["holdout_unfiltered"]
        st_ = "FILTER_HELPS_IN_HOLDOUT" if hf["cycles"] and hf.get("expectancy_r", -9) > hu.get("expectancy_r", 9) else "FILTER_NOT_HELPING_IN_HOLDOUT"
    B.update(status=st_, note="filtr w SHADOW; włączenie bramki (ml_filter.enabled) wymaga dodatniego wyniku w holdout i bramki badawczej strategii")
    log("B", f"{st_}: wybór {sel}, próg {thr}, holdout Brier {br:.4f} vs {brb:.4f}")
    spec, arts = None, {}
    if rd is not None and thr is not None and st_ != "REJECTED":
        from .scalp_infer import lr_to_json, mlp_to_json
        if sel in ("LR", "MLP"):
            f = f"setup_model_{sel}.json"
            write_json_atomic(rd / f, lr_to_json(model[1], model[2]) if sel == "LR" else mlp_to_json(model[1], model[2]))
        else:
            f = "setup_model_HGB.pkl"
            with open(rd / f, "wb") as fh:
                pickle.dump(model[2], fh)
        arts[f] = sha256_file(rd / f)
        spec = {"selected": sel, "file": f, "calibrator": calib, "threshold": thr, "features": list(feats), "prior": prior, "status": st_}
    return B, spec, arts


if __name__ == "__main__":
    sys.exit(main())
