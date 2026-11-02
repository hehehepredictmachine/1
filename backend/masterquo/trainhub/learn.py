"""Models, metrics and the training procedure (PMW-TH-LEARN-1).

Trainable models of this pipeline (task DIRECTION_H, 3 classes after costs; one model per instrument and base TF):
  TH_BASELINE - class frequencies of the training rows (the baseline every model is compared with);
  TH_LOGREG   - standardisation + multinomial logistic regression, C chosen on purged walk-forward folds;
  TH_HGB      - histogram gradient boosting (depth / learning rate chosen on the folds);
  TH_XGB      - XGBoost (CPU), only when the xgboost package is installed.
Procedure: hyper-parameters by mean walk-forward log loss on DEVELOPMENT rows -> temperature calibration fitted on the
out-of-fold predictions -> decision threshold for the cost-aware evaluation chosen on the out-of-fold predictions -> final fit on all
development rows -> ONE evaluation on the untouched final test (holdout): log loss, Brier, accuracy, balanced accuracy, skill vs the
baseline, calibration error before / after calibration, stability across folds and a cost-aware trading evaluation.
Accuracy is not profitability: the trading evaluation subtracts the recorded spread, commission and the slippage assumption and is
reported separately; nothing here promises a win rate or a return.
"""
from __future__ import annotations

import math
import time

import numpy as np

MODELS = {
    "TH_BASELINE": {"name": "Bazowy – częstości klas", "grid": [{}]},
    "TH_LOGREG": {"name": "Regresja logistyczna (wieloklasowa)", "grid": [{"C": c} for c in (0.05, 0.3, 1.0, 3.0)]},
    "TH_HGB": {"name": "Gradient boosting (histogramowy)", "grid": [{"max_depth": 3, "learning_rate": 0.05, "max_iter": 150},
                                                                    {"max_depth": 5, "learning_rate": 0.05, "max_iter": 200}]},
    "TH_XGB": {"name": "XGBoost (CPU)", "grid": [{"max_depth": 3, "learning_rate": 0.05, "n_estimators": 200},
                                                  {"max_depth": 5, "learning_rate": 0.05, "n_estimators": 250}]},
}


def available() -> dict[str, bool]:
    try:
        import xgboost  # noqa: F401
        xgb = True
    except Exception:  # noqa: BLE001
        xgb = False
    return {"TH_BASELINE": True, "TH_LOGREG": True, "TH_HGB": True, "TH_XGB": xgb}


class Prior:
    """Baseline: class frequencies of the training rows."""

    def __init__(self):
        self.p = np.ones(3) / 3

    def fit(self, X, y):
        c = np.bincount(y, minlength=3).astype(float) + 1.0
        self.p = c / c.sum()
        self.classes_ = np.arange(3)
        return self

    def predict_proba(self, X):
        return np.tile(self.p, (len(X), 1))


def make(model_id: str, params: dict, seed: int):
    if model_id == "TH_BASELINE":
        return Prior()
    if model_id == "TH_LOGREG":
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        return make_pipeline(StandardScaler(), LogisticRegression(C=params["C"], max_iter=500, random_state=seed))
    if model_id == "TH_HGB":
        from sklearn.ensemble import HistGradientBoostingClassifier
        return HistGradientBoostingClassifier(max_depth=params["max_depth"], learning_rate=params["learning_rate"], max_iter=params["max_iter"],
                                              l2_regularization=1.0, early_stopping=False, random_state=seed)
    if model_id == "TH_XGB":
        from xgboost import XGBClassifier
        return XGBClassifier(max_depth=params["max_depth"], learning_rate=params["learning_rate"], n_estimators=params["n_estimators"],
                             subsample=0.8, colsample_bytree=0.8, objective="multi:softprob", num_class=3, tree_method="hist",
                             random_state=seed, n_jobs=1, verbosity=0)
    raise ValueError(f"nieznany model {model_id}")


def fit(model_id: str, params: dict, X, y, seed: int):
    m = make(model_id, params, seed)
    if model_id == "TH_XGB" and len(np.unique(y)) < 3:
        # XGBoost needs every class present; add one zero-weight row per missing class (does not change the fit)
        miss = [k for k in range(3) if k not in set(y.tolist())]
        X = np.vstack([X] + [X[:1]] * len(miss))
        w = np.concatenate([np.ones(len(y)), np.zeros(len(miss))])
        y = np.concatenate([y, np.array(miss)])
        return m.fit(X, y, sample_weight=w)
    return m.fit(X, y)


def proba3(m, X) -> np.ndarray:
    p = np.asarray(m.predict_proba(X), dtype=float)
    cls = list(getattr(m, "classes_", range(p.shape[1])))
    out = np.full((len(X), 3), 1e-9)
    for j, c in enumerate(cls):
        out[:, int(c)] = p[:, j]
    out /= out.sum(axis=1, keepdims=True)
    return out


# ------------------------------------------------------------------------------------------------ metrics
def logloss(p, y) -> float:
    return float(-np.mean(np.log(np.clip(p[np.arange(len(y)), y], 1e-12, 1.0))))


def brier(p, y) -> float:
    oh = np.eye(3)[y]
    return float(np.mean(np.sum((p - oh) ** 2, axis=1)))


def ece(p, y, bins: int = 10) -> dict:
    conf = p.max(axis=1)
    pred = p.argmax(axis=1)
    hit = (pred == y).astype(float)
    edges = np.linspace(1 / 3, 1.0, bins + 1)
    tot, rows = 0.0, []
    for a, b in zip(edges[:-1], edges[1:]):
        m = (conf >= a) & (conf < b if b < 1 else conf <= b)
        if m.sum():
            gap = abs(hit[m].mean() - conf[m].mean())
            tot += m.sum() / len(y) * gap
            rows.append({"from": round(float(a), 3), "to": round(float(b), 3), "n": int(m.sum()), "confidence": round(float(conf[m].mean()), 4),
                         "accuracy": round(float(hit[m].mean()), 4)})
    return {"ece": round(float(tot), 5), "bins": rows}


def metrics(p, y) -> dict:
    pred = p.argmax(axis=1)
    rec = [float((pred[y == k] == k).mean()) for k in range(3) if (y == k).any()]
    return {"n": int(len(y)), "log_loss": round(logloss(p, y), 5), "brier": round(brier(p, y), 5), "accuracy": round(float((pred == y).mean()), 4),
            "balanced_accuracy": round(float(np.mean(rec)), 4) if rec else None, "ece": ece(p, y)["ece"]}


def temperature(p, y) -> float:
    """T minimising the log loss of softmax(log p / T) on development out-of-fold predictions."""
    lp = np.log(np.clip(p, 1e-12, 1))

    def ll(T):
        z = lp / T
        z = z - z.max(axis=1, keepdims=True)
        q = np.exp(z)
        q /= q.sum(axis=1, keepdims=True)
        return logloss(q, y)
    grid = np.exp(np.linspace(math.log(0.3), math.log(4.0), 60))
    best = min(grid, key=ll)
    return float(best)


def calibrate(p, T: float) -> np.ndarray:
    z = np.log(np.clip(p, 1e-12, 1)) / T
    z = z - z.max(axis=1, keepdims=True)
    q = np.exp(z)
    return q / q.sum(axis=1, keepdims=True)


def trade_eval(p, fwd, cost, atr, thr: float) -> dict:
    """Cost-aware evaluation of the simple rule 'P(UP)-P(DOWN) > thr -> long for H candles, < -thr -> short' (one position per row,
    overlapping - a measure of the signal, not an executable backtest). Result in ATR units after costs."""
    edge = p[:, 2] - p[:, 0]
    side = np.where(edge > thr, 1, np.where(edge < -thr, -1, 0))
    m = side != 0
    if not m.any():
        return {"threshold": thr, "trades": 0, "mean_net_atr": None, "hit_rate_net": None, "sum_net_atr": 0.0, "max_drawdown_atr": 0.0}
    net = (side[m] * fwd[m] - cost[m]) / atr[m]
    eq = np.cumsum(net)
    dd = float(np.max(np.maximum.accumulate(np.concatenate([[0], eq])) - np.concatenate([[0], eq])))
    return {"threshold": thr, "trades": int(m.sum()), "mean_net_atr": round(float(net.mean()), 5), "hit_rate_net": round(float((net > 0).mean()), 4),
            "sum_net_atr": round(float(net.sum()), 3), "max_drawdown_atr": round(dd, 3), "long": int((side == 1).sum()), "short": int((side == -1).sum())}


def choose_threshold(p, fwd, cost, atr) -> float:
    best, best_v = 0.2, -1e9
    for thr in (0.05, 0.1, 0.15, 0.2, 0.3, 0.4):
        r = trade_eval(p, fwd, cost, atr, thr)
        if r["trades"] >= max(30, int(0.02 * len(p))) and r["mean_net_atr"] is not None and r["mean_net_atr"] > best_v:
            best, best_v = thr, r["mean_net_atr"]
    return best


# ------------------------------------------------------------------------------------------------ procedure
def train_one(model_id: str, ds: dict, sp: dict, seed: int = 7, progress=None, cancel=None) -> dict:
    X, y = ds["X"], ds["y"]
    grid = MODELS[model_id]["grid"]
    t0 = time.time()
    cv = []
    for gi, params in enumerate(grid):
        oof_p, oof_i, fold_m = [], [], []
        for fi, f in enumerate(sp["folds"]):
            if cancel and cancel():
                raise InterruptedError("anulowano")
            m = fit(model_id, params, X[f["train"]], y[f["train"]], seed)
            p = proba3(m, X[f["test"]])
            base = Prior().fit(X[f["train"]], y[f["train"]]).predict_proba(X[f["test"]])
            mm = metrics(p, y[f["test"]])
            mm["baseline_log_loss"] = round(logloss(base, y[f["test"]]), 5)
            fold_m.append(mm)
            oof_p.append(p)
            oof_i.append(f["test"])
            if progress:
                progress({"stage": "walk-forward", "model": model_id, "config": gi + 1, "configs": len(grid), "fold": fi + 1, "folds": len(sp["folds"])})
        cv.append({"params": params, "folds": fold_m, "mean_log_loss": float(np.mean([m["log_loss"] for m in fold_m])),
                   "oof_p": np.vstack(oof_p), "oof_i": np.concatenate(oof_i)})
    best = min(cv, key=lambda c: c["mean_log_loss"])
    oy = y[best["oof_i"]]
    T = temperature(best["oof_p"], oy) if model_id != "TH_BASELINE" else 1.0
    oof_cal = calibrate(best["oof_p"], T)
    thr = choose_threshold(oof_cal, ds["fwd"][best["oof_i"]], ds["cost"][best["oof_i"]], ds["atr"][best["oof_i"]])
    dev = sp["dev"]
    final = fit(model_id, best["params"], X[dev], y[dev], seed)
    hold = sp["holdout"]
    p_raw = proba3(final, X[hold])
    p_cal = calibrate(p_raw, T)
    base_h = Prior().fit(X[dev], y[dev]).predict_proba(X[hold])
    fm = best["folds"]
    beats = [m["log_loss"] < m["baseline_log_loss"] for m in fm]
    hold_m = metrics(p_cal, y[hold])
    hold_m["baseline_log_loss"] = round(logloss(base_h, y[hold]), 5)
    hold_m["skill_vs_baseline"] = round(1 - hold_m["log_loss"] / hold_m["baseline_log_loss"], 5) if hold_m["baseline_log_loss"] else None
    res = {"model_id": model_id, "params": best["params"], "temperature": T, "decision_threshold": thr,
           "cv": [{"params": c["params"], "mean_log_loss": round(c["mean_log_loss"], 5)} for c in cv],
           "walk_forward": {"folds": fm, "mean_log_loss": round(best["mean_log_loss"], 5),
                            "std_log_loss": round(float(np.std([m["log_loss"] for m in fm])), 5),
                            "mean_baseline_log_loss": round(float(np.mean([m["baseline_log_loss"] for m in fm])), 5),
                            "folds_beating_baseline": f"{sum(beats)}/{len(beats)}",
                            "dev_skill_vs_baseline": round(1 - best["mean_log_loss"] / float(np.mean([m["baseline_log_loss"] for m in fm])), 5)},
           "holdout": hold_m, "holdout_raw_uncalibrated": metrics(p_raw, y[hold]),
           "calibration": {"method": "temperature (fit on development out-of-fold predictions)", "T": round(T, 4),
                           "ece_before": ece(p_raw, y[hold])["ece"], "ece_after": ece(p_cal, y[hold])["ece"], "reliability_after": ece(p_cal, y[hold])["bins"]},
           "trading_eval_holdout": trade_eval(p_cal, ds["fwd"][hold], ds["cost"][hold], ds["atr"][hold], thr),
           "class_counts_holdout": {c: int((y[hold] == i).sum()) for i, c in enumerate(("DOWN", "FLAT", "UP"))},
           "train_seconds": round(time.time() - t0, 2),
           "sample": {"X": X[hold][:40].tolist(), "p_raw": p_raw[:40].tolist()}}
    return {"result": res, "model": final}
