"""Decision Tree and XGBoost for one shared target, calibrators, model bundles and explanations.

Both models are real, trainable estimators:
* sklearn.tree.DecisionTreeClassifier - interpretable baseline; max_depth, min_samples_leaf, min_samples_split,
  class_weight and ccp_alpha chosen on chronological walk-forward folds (fixed tuning budget, random_state saved).
  It is re-trained on new labelled snapshots - it is NOT an online (partial_fit) learner.
* xgboost.XGBClassifier - regularised boosting (reg_lambda/alpha, subsample, colsample_bytree, learning_rate,
  max_depth, n_estimators) with early stopping on the chronologically LATER tune block; CPU `hist` by default,
  limited threads; scale_pos_weight from the fit block. Saved in the native UBJ format.
Calibration is fitted on the separate calibration block (isotonic with enough data, otherwise sigmoid on the logit).
A bundle = model + preprocessor + calibrator + metadata, swapped atomically.
"""
from __future__ import annotations

import json
import math
import random
from pathlib import Path

import numpy as np

from .prep import Preprocessor

FAMILIES = ("DECISION_TREE", "XGBOOST")


# ----------------------------------------------------------------------------- calibration
class Calibrator:
    def __init__(self, kind: str = "NONE", params: dict | None = None):
        self.kind, self.params = kind, params or {}

    @classmethod
    def fit(cls, raw: np.ndarray, y: np.ndarray) -> "Calibrator":
        pos, neg = int(y.sum()), int(len(y) - y.sum())
        if pos < 5 or neg < 5:
            return cls("NONE", {"reason": "CALIBRATION_BLOCK_ONE_CLASS_OR_TOO_SMALL"})
        if len(y) >= 200 and min(pos, neg) >= 30:
            from sklearn.isotonic import IsotonicRegression
            iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(raw, y)
            return cls("ISOTONIC", {"x": [float(v) for v in iso.X_thresholds_], "y": [float(v) for v in iso.y_thresholds_]})
        from sklearn.linear_model import LogisticRegression
        z = _logit(raw).reshape(-1, 1)
        lr = LogisticRegression(C=1e6, max_iter=1000).fit(z, y)
        return cls("SIGMOID", {"a": float(lr.coef_[0][0]), "b": float(lr.intercept_[0])})

    def apply(self, raw: np.ndarray) -> np.ndarray | None:
        if self.kind == "ISOTONIC":
            return np.interp(raw, self.params["x"], self.params["y"])
        if self.kind == "SIGMOID":
            return 1 / (1 + np.exp(-(self.params["a"] * _logit(raw) + self.params["b"])))
        return None

    def to_json(self) -> dict:
        return {"kind": self.kind, "params": self.params}

    @classmethod
    def from_json(cls, d: dict) -> "Calibrator":
        return cls(d["kind"], d.get("params"))


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


# ----------------------------------------------------------------------------- training
def _ll(y, p) -> float:
    from sklearn.metrics import log_loss
    if len(set(y.tolist())) < 2:
        return math.inf
    return float(log_loss(y, np.clip(p, 1e-6, 1 - 1e-6), labels=[0, 1]))


def dt_grid(budget: int, seed: int) -> list[dict]:
    grid = [{"max_depth": d, "min_samples_leaf": leaf, "min_samples_split": 2 * leaf, "class_weight": cw, "ccp_alpha": a}
            for d in (2, 3, 4, 5, 6, 8) for leaf in (20, 40, 80) for cw in (None, "balanced") for a in (0.0, 0.0005, 0.002)]
    random.Random(seed).shuffle(grid)
    return grid[:budget]


def train_dt(folds, X_full, y_full, *, budget: int, seed: int, prep_fit) -> tuple[object, dict]:
    """Choose params by mean log loss over walk-forward folds (each fold re-fits its own preprocessor), then fit on FIT+TUNE."""
    from sklearn.tree import DecisionTreeClassifier
    trials = []
    for params in dt_grid(budget, seed):
        losses = []
        for tr, va in folds:
            if len(tr) < 30 or len(va) < 10:
                continue
            pp = prep_fit(tr)
            ytr = np.array([r["label"] for r in tr])
            if len(set(ytr.tolist())) < 2:
                continue
            m = DecisionTreeClassifier(random_state=seed, **params).fit(pp.transform(tr), ytr)
            losses.append(_ll(np.array([r["label"] for r in va]), m.predict_proba(pp.transform(va))[:, 1]))
        if losses:
            trials.append((float(np.mean(losses)), params))
    if not trials:
        best = {"max_depth": 3, "min_samples_leaf": 40, "min_samples_split": 80, "class_weight": "balanced", "ccp_alpha": 0.0}
        score = None
    else:
        score, best = min(trials, key=lambda t: t[0])
    model = DecisionTreeClassifier(random_state=seed, **best).fit(X_full, y_full)
    return model, {"params": best, "walk_forward_logloss": score, "trials": len(trials), "random_state": seed}


def xgb_grid(budget: int, seed: int) -> list[dict]:
    grid = [{"max_depth": d, "learning_rate": lr, "subsample": ss, "colsample_bytree": cs, "reg_lambda": lam, "min_child_weight": mcw}
            for d in (2, 3, 4) for lr in (0.03, 0.08) for ss in (0.7, 0.9) for cs in (0.6, 0.9) for lam in (1.0, 5.0) for mcw in (5, 20)]
    random.Random(seed).shuffle(grid)
    return grid[:budget]


def train_xgb(X_fit, y_fit, X_tune, y_tune, *, budget: int, seed: int, max_trees: int, threads: int, device: str) -> tuple[object, dict]:
    import xgboost as xgb
    pos, neg = max(1, int(y_fit.sum())), max(1, int(len(y_fit) - y_fit.sum()))
    best = None
    for params in xgb_grid(budget, seed):
        m = xgb.XGBClassifier(n_estimators=max_trees, early_stopping_rounds=30, eval_metric="logloss", tree_method="hist", device=device,
                              n_jobs=threads, random_state=seed, scale_pos_weight=neg / pos, **params)
        m.fit(X_fit, y_fit, eval_set=[(X_tune, y_tune)], verbose=False)
        score = _ll(y_tune, m.predict_proba(X_tune)[:, 1])
        if best is None or score < best[0]:
            best = (score, params, m)
    score, params, model = best
    return model, {"params": params, "tune_logloss": score, "best_iteration": int(model.best_iteration), "trials": budget, "random_state": seed,
                   "scale_pos_weight": round(neg / pos, 4), "xgboost_version": xgb.__version__, "device": device, "threads": threads}


# ----------------------------------------------------------------------------- bundle
class Bundle:
    def __init__(self, family: str, model, prep: Preprocessor, calib: Calibrator, meta: dict):
        self.family, self.model, self.prep, self.calib, self.meta = family, model, prep, calib, meta

    def raw(self, rows: list[dict]) -> np.ndarray:
        X = self.prep.transform(rows)
        if self.family == "XGBOOST":
            it = self.meta.get("train", {}).get("best_iteration")
            return self.model.predict_proba(X, iteration_range=(0, it + 1) if it is not None else None)[:, 1]
        return self.model.predict_proba(X)[:, 1]

    def save(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        if self.family == "XGBOOST":
            self.model.save_model(str(path / "model.ubj"))
        else:
            import joblib
            joblib.dump(self.model, path / "model.joblib")
            (path / "tree_structure.json").write_text(json.dumps(export_tree(self.model, self.prep.columns)), encoding="utf-8")
        (path / "preprocessor.json").write_text(json.dumps(self.prep.to_json()), encoding="utf-8")
        (path / "calibrator.json").write_text(json.dumps(self.calib.to_json()), encoding="utf-8")
        (path / "meta.json").write_text(json.dumps(self.meta, indent=1, default=str), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Bundle":
        meta = json.loads((path / "meta.json").read_text(encoding="utf-8"))
        fam = meta["family"]
        if fam == "XGBOOST":
            import xgboost as xgb
            model = xgb.XGBClassifier()
            model.load_model(str(path / "model.ubj"))
        else:
            import joblib
            model = joblib.load(path / "model.joblib")
        prep = Preprocessor.from_json(json.loads((path / "preprocessor.json").read_text(encoding="utf-8")))
        calib = Calibrator.from_json(json.loads((path / "calibrator.json").read_text(encoding="utf-8")))
        return cls(fam, model, prep, calib, meta)


# ----------------------------------------------------------------------------- explanations
def export_tree(model, columns: list[str]) -> dict:
    t = model.tree_
    nodes = []
    for i in range(t.node_count):
        leaf = t.children_left[i] == t.children_right[i]
        nodes.append({"id": i, "leaf": bool(leaf), "feature": None if leaf else columns[t.feature[i]], "threshold": None if leaf else float(t.threshold[i]),
                      "left": int(t.children_left[i]), "right": int(t.children_right[i]), "n": int(t.n_node_samples[i]),
                      "class_fraction": [round(float(x), 4) for x in t.value[i][0] / max(1e-12, t.value[i][0].sum())],
                      "missing_go_to_left": bool(getattr(t, "missing_go_to_left", [0] * t.node_count)[i])})
    return {"nodes": nodes, "depth": int(model.get_depth()), "leaves": int(model.get_n_leaves())}


def explain_dt(bundle: Bundle, row: dict) -> dict:
    X = bundle.prep.transform([row])
    m = bundle.model
    t = m.tree_
    path = m.decision_path(X).indices.tolist()
    steps = []
    for node in path:
        if t.children_left[node] == t.children_right[node]:
            frac = t.value[node][0] / max(1e-12, t.value[node][0].sum())
            n = int(t.n_node_samples[node])
            return {"steps": steps, "leaf": int(node), "leaf_samples": n, "leaf_class_fraction": {"0": round(float(frac[0]), 4), "1": round(float(frac[1]), 4)},
                    "small_leaf": n < 30, "note": "Udział klas w liściu to obserwacje treningowe (z wagami klas, jeśli użyte) – nie pewność."}
        col = bundle.prep.columns[t.feature[node]]
        val = X[0, t.feature[node]]
        thr = float(t.threshold[node])
        if math.isnan(val):
            went = "lewo (brak wartości)" if getattr(t, "missing_go_to_left", [True] * t.node_count)[node] else "prawo (brak wartości)"
        else:
            went = "lewo (≤ próg)" if val <= thr else "prawo (> próg)"
        steps.append({"node": int(node), "feature": col, "value": None if math.isnan(val) else round(float(val), 5), "threshold": round(thr, 5), "branch": went})
    return {"steps": steps}


def explain_xgb(bundle: Bundle, row: dict, top: int = 10) -> dict:
    import xgboost as xgb
    X = bundle.prep.transform([row])
    it = bundle.meta.get("train", {}).get("best_iteration")
    contrib = bundle.model.get_booster().predict(xgb.DMatrix(X, feature_names=None), pred_contribs=True,
                                                  iteration_range=(0, it + 1) if it is not None else (0, 0))[0]
    names = bundle.prep.columns + ["(bias)"]
    pairs = sorted(zip(names, contrib.tolist(), list(X[0]) + [None]), key=lambda x: -abs(x[1]))
    return {"method": "TreeSHAP (xgboost pred_contribs, log-odds)", "bias": round(float(contrib[-1]), 4),
            "top": [{"feature": n, "contribution": round(c, 4), "value": None if v is None or (isinstance(v, float) and math.isnan(v)) else round(float(v), 5)}
                    for n, c, v in pairs if n != "(bias)"][:top],
            "note": "Wkłady opisują model, nie przyczynowość rynku."}
