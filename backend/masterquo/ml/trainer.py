"""Training job (runs in a separate process): immutable snapshot -> blocks -> DT + XGB -> calibration -> final test
-> candidate bundles + full report. Promotion is decided afterwards by the registry with rules fixed in config
BEFORE the evaluation (they are copied into the report).
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

UTC = timezone.utc


def _iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def run(snapshot_path: str, cfg: dict, out_dir: str, prior_test_end: str | None, progress=None) -> dict:
    """Pure function of its inputs (used by the subprocess and by tests)."""
    from . import features as fe
    from . import validation as val
    from .dataset import load_snapshot
    from .models import Bundle, Calibrator, train_dt, train_xgb
    from .prep import Preprocessor
    import sklearn
    import xgboost

    def say(phase):
        if progress:
            progress(phase)
    t0 = time.time()
    rows = load_snapshot(snapshot_path)
    rows = [dict(r, **{"f": fe.from_json(json.loads(r["features_json"]))}) for r in rows]
    schema = {r["feature_schema_version"] for r in rows}
    if schema and schema != {fe.FEATURE_SCHEMA_VERSION}:
        return {"status": "FAILED", "reason": f"FEATURE_SCHEMA_MISMATCH:{sorted(schema)}"}
    info, reasons = val.split(rows, embargo_minutes=cfg["embargo_minutes"], min_block=cfg["min_block_samples"], min_class=cfg["min_block_per_class"],
                              test_after=prior_test_end)
    if info is None:
        return {"status": "NOT_READY", "reasons": reasons}
    B = info["blocks"]
    feats = {k: [r["f"] for r in v] for k, v in B.items()}
    ys = {k: np.array([r["label"] for r in v], dtype=int) for k, v in B.items()}
    seed = int(cfg.get("random_state", 42))
    say("TRAINING")
    prep = Preprocessor().fit(feats["fit"])
    X = {k: prep.transform(v) for k, v in feats.items()}
    results = {}
    # ---- Decision Tree: params on walk-forward folds inside FIT+TUNE, final fit on FIT+TUNE
    pre = B["fit"] + B["tune"]
    folds = val.walk_forward(pre, 3, cfg["embargo_minutes"])
    folds_f = [([dict(r["f"], label=r["label"]) for r in tr], [dict(r["f"], label=r["label"]) for r in va]) for tr, va in folds]
    dt, dt_info = train_dt(folds_f, np.vstack([X["fit"], X["tune"]]), np.concatenate([ys["fit"], ys["tune"]]), budget=cfg["dt_tuning_budget"], seed=seed,
                           prep_fit=lambda tr: Preprocessor().fit(tr))
    results["DECISION_TREE"] = (dt, dt_info)
    # ---- XGBoost: early stopping on the later TUNE block
    xg, xg_info = train_xgb(X["fit"], ys["fit"], X["tune"], ys["tune"], budget=cfg["xgb_tuning_budget"], seed=seed, max_trees=cfg["xgb_max_trees"],
                            threads=cfg["xgb_threads"], device=cfg.get("xgb_device", "cpu"))
    results["XGBOOST"] = (xg, xg_info)
    say("VALIDATING")
    base_rate = float(np.concatenate([ys["fit"], ys["tune"]]).mean())
    test_rows = B["test"]
    all_take = np.ones(len(test_rows), dtype=bool)
    no_ml = val.policy_eval(test_rows, all_take)
    strat_prior = {}
    for r in B["fit"] + B["tune"]:
        d = strat_prior.setdefault(r["strategy_id"], [0, 0])
        d[0] += r["label"]
        d[1] += 1
    prior_p = np.array([(strat_prior.get(r["strategy_id"], [0, 0])[0] + base_rate * 10) / (strat_prior.get(r["strategy_id"], [0, 0])[1] + 10) for r in test_rows])
    baselines = {"base_rate": val.classification_metrics(ys["test"], np.full(len(test_rows), base_rate), 0.5),
                 "strategy_prior": val.classification_metrics(ys["test"], prior_p, 0.5), "no_ml_policy": {k: v for k, v in no_ml.items() if k != "values"},
                 "no_ml_bootstrap": val.block_bootstrap(no_ml.get("values", []))}
    out = {"status": "DONE", "snapshot": snapshot_path, "validation": {"version": val.VERSION, "counts": info["counts"], "purged": info["purged"],
                                                                       "windows": info["windows"], "embargo_minutes": cfg["embargo_minutes"]},
           "base_rate": round(base_rate, 4), "baselines": baselines, "models": {}, "promotion_rules": cfg["promotion"],
           "versions": {"sklearn": sklearn.__version__, "xgboost": xgboost.__version__, "numpy": np.__version__, "python": sys.version.split()[0]},
           "feature_schema_version": fe.FEATURE_SCHEMA_VERSION}
    for fam, (model, info_m) in results.items():
        bundle = Bundle(fam, model, prep, Calibrator("NONE"), {"family": fam, "train": info_m})
        raw_cal = bundle.raw(feats["calib"])
        calib = Calibrator.fit(raw_cal, ys["calib"])
        bundle.calib = calib
        p_cal = calib.apply(raw_cal)
        p_cal = raw_cal if p_cal is None else p_cal
        # trading threshold chosen on the CALIBRATION block (before the final test)
        best_thr, best_val = 0.5, None
        for thr in np.linspace(0.3, 0.8, 26):
            pe = val.policy_eval(B["calib"], p_cal >= thr)
            if pe["trades"] >= max(10, int(0.1 * len(B["calib"]))):
                if best_val is None or pe["net_r"] > best_val:
                    best_thr, best_val = float(thr), pe["net_r"]
        raw_t = bundle.raw(feats["test"])
        p_t = calib.apply(raw_t)
        p_eval = raw_t if p_t is None else p_t
        cm = val.classification_metrics(ys["test"], p_eval, best_thr)
        pol = val.policy_eval(test_rows, p_eval >= best_thr)
        bundle.meta.update({"family": fam, "threshold": best_thr, "base_rate": base_rate, "calibration": calib.kind,
                            "feature_schema_version": fe.FEATURE_SCHEMA_VERSION, "test_window": info["windows"]["test"],
                            "trained_at": _iso(), "versions": out["versions"], "target_definition": TARGET})
        mid = f"{fam[:2]}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}"
        path = Path(out_dir) / mid
        bundle.save(path)
        out["models"][fam] = {"model_id": mid, "path": str(path), "train": info_m, "threshold": best_thr, "calibration": calib.kind,
                              "test": cm, "raw_test_brier": val.classification_metrics(ys["test"], raw_t, best_thr)["brier"],
                              "policy": {k: v for k, v in pol.items() if k != "values"}, "policy_bootstrap": val.block_bootstrap(pol.get("values", [])),
                              "by_strategy": val.breakdown(test_rows, p_eval, lambda r: r["strategy_id"]),
                              "by_direction": val.breakdown(test_rows, p_eval, lambda r: r["direction"]),
                              "by_session": val.breakdown(test_rows, p_eval, lambda r: _session(r["asof_utc"])),
                              "by_regime": val.breakdown(test_rows, p_eval, lambda r: r["f"].get("regime"))}
    out["elapsed_s"] = round(time.time() - t0, 1)
    return out


TARGET = ("Czy ten setup, wykonany wg polityki zapisanej przy jego powstaniu (wejście na otwarciu następnej M1, SL/TP/BE/limit czasu, "
          "koszty), zakończy się dodatnim wynikiem netto. 1 = netto > 0, 0 = netto <= 0. To nie jest prawdopodobieństwo wzrostu ceny.")


def _session(asof: str) -> str:
    h = int(asof[11:13])
    return "ASIA" if h < 7 else "LONDON" if h < 12 else "NEW_YORK" if h < 21 else "LATE"


def subprocess_main(job_file: str) -> None:
    """Entry point of the training process. Reads the job, writes the result next to it."""
    job = json.loads(Path(job_file).read_text(encoding="utf-8"))
    os.environ.setdefault("OMP_NUM_THREADS", str(job["cfg"]["xgb_threads"]))
    res_path = Path(job_file).with_suffix(".result.json")
    phase_path = Path(job_file).with_suffix(".phase")

    def progress(p):
        phase_path.write_text(p, encoding="utf-8")
    try:
        res = run(job["snapshot"], job["cfg"], job["out_dir"], job.get("prior_test_end"), progress)
    except Exception as exc:  # reported to the parent; the bot keeps running
        res = {"status": "FAILED", "reason": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-3000:]}
    tmp = res_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(res, default=str), encoding="utf-8")
    tmp.replace(res_path)


if __name__ == "__main__":
    subprocess_main(sys.argv[1])
