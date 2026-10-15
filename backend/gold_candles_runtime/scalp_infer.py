"""Loading and inference of scalp models (shared by the trainer's runtime check and the worker command `scalp_forecast`).

Portable JSON for logistic regression, MLP and calibrators (numpy only). Tree models (HistGradientBoosting) are stored
with pickle and are loaded ONLY when their sha256 equals the value written by our own trainer into the registry entry -
no arbitrary / untrusted pickle is ever opened."""
from __future__ import annotations

import json
import os
import pickle
from pathlib import Path

import numpy as np

from .common import data_dir, sha256_file


def scalp_dir() -> Path:
    d = data_dir() / "scalp"
    d.mkdir(parents=True, exist_ok=True)
    return d


def registry_path() -> Path:
    return scalp_dir() / "registry.json"


def read_registry() -> dict:
    p = registry_path()
    if not p.exists():
        return {"schema": "masterquo-scalp-registry-1", "active": None, "history": [], "runs": {}}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"schema": "masterquo-scalp-registry-1", "active": None, "history": [], "runs": {}, "error": "REGISTRY_UNREADABLE"}


def activatable(entry: dict, contract: str | None) -> tuple[bool, str | None]:
    if entry.get("data_kind") != "REAL_USER_DATA" and not (entry.get("data_kind") == "SYNTHETIC_TEST" and os.environ.get("MQ_FORECAST_TEST_ALLOW_SYNTHETIC") == "1"):
        return False, "NOT_REAL_USER_DATA"
    if entry.get("task_a_status") in (None, "INSUFFICIENT_DATA"):
        return False, "TASK_A_NOT_TRAINED"
    for f, sha in (entry.get("artifacts") or {}).items():
        p = Path(entry["run_dir"]) / f
        if not p.exists() or sha256_file(p) != sha:
            return False, f"ARTIFACT_CHECKSUM_MISMATCH:{f}"
    if contract and entry.get("contract_hash") != contract:
        return False, "CONTRACT_MISMATCH"
    return True, None


# ------------------------------------------------------------------ portable models
def lr_to_json(scaler, clf) -> dict:
    return {"type": "LR", "mean": scaler.mean_.tolist(), "scale": scaler.scale_.tolist(), "coef": clf.coef_.tolist(), "intercept": clf.intercept_.tolist(),
            "classes": [int(x) for x in clf.classes_]}


def mlp_to_json(scaler, clf) -> dict:
    return {"type": "MLP", "mean": scaler.mean_.tolist(), "scale": scaler.scale_.tolist(), "coefs": [w.tolist() for w in clf.coefs_],
            "intercepts": [b.tolist() for b in clf.intercepts_], "activation": clf.activation, "classes": [int(x) for x in clf.classes_]}


def _softmax(z):
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


def predict_json(m: dict, X: np.ndarray) -> np.ndarray:
    Z = (X - np.asarray(m["mean"])) / np.asarray(m["scale"])
    if m["type"] == "LR":
        P = _softmax(Z @ np.asarray(m["coef"]).T + np.asarray(m["intercept"]))
    elif m["type"] == "MLP":
        a = Z
        for k, (W, b) in enumerate(zip(m["coefs"], m["intercepts"])):
            a = a @ np.asarray(W) + np.asarray(b)
            if k < len(m["coefs"]) - 1:
                a = np.maximum(a, 0.0) if m["activation"] == "relu" else np.tanh(a)
        P = _softmax(a)
    else:
        raise ValueError(m["type"])
    return _full(P, m["classes"])


def _full(P, classes):
    out = np.full((P.shape[0], 3), 1e-6)
    for j, c in enumerate(classes):
        out[:, c] = P[:, j]
    return out / out.sum(axis=1, keepdims=True)


def predict_binary_json(m: dict, X: np.ndarray) -> np.ndarray:
    """P(class 1) of a portable binary LR / MLP."""
    Z = (X - np.asarray(m["mean"])) / np.asarray(m["scale"])
    if m["type"] == "LR":
        z = Z @ np.asarray(m["coef"]).T + np.asarray(m["intercept"])
    else:
        z = Z
        for k, (W, b) in enumerate(zip(m["coefs"], m["intercepts"])):
            z = z @ np.asarray(W) + np.asarray(b)
            if k < len(m["coefs"]) - 1:
                z = np.maximum(z, 0.0) if m["activation"] == "relu" else np.tanh(z)
    z = np.asarray(z)
    if z.ndim == 2 and z.shape[1] == 2:
        return _softmax(z)[:, 1]
    return 1.0 / (1.0 + np.exp(-z.reshape(-1)))


def platt(cal: dict | None, p: np.ndarray) -> np.ndarray:
    if not cal:
        return p
    lg = np.log(np.clip(p, 1e-6, 1 - 1e-6) / np.clip(1 - p, 1e-6, 1))
    return 1.0 / (1.0 + np.exp(-(cal["a"] * lg + cal["b"])))


class SetupModel:
    """Task-B model: P(TP1 before SL) for one setup + calibrator + threshold chosen in development."""

    def __init__(self, entry: dict):
        sm = entry["setup_model"]
        rd = Path(entry["run_dir"])
        self.spec = sm
        if sm["selected"] in ("LR", "MLP"):
            self.m = json.loads((rd / sm["file"]).read_text(encoding="utf-8"))
        elif sm["selected"] == "HGB":
            self.m = load_pickle_verified(rd / sm["file"], entry["artifacts"][sm["file"]])
        else:
            self.m = None

    def predict(self, X: np.ndarray) -> np.ndarray:
        if self.m is None:
            return np.full(len(X), self.spec["prior"])
        p = predict_binary_json(self.m, X) if isinstance(self.m, dict) else self.m.predict_proba(X)[:, list(self.m.classes_).index(1)]
        return platt(self.spec.get("calibrator"), p)


def calib_to_json(clf) -> dict:
    return {"coef": clf.coef_.tolist(), "intercept": clf.intercept_.tolist(), "classes": [int(x) for x in clf.classes_]}


def calibrate(c: dict | None, P: np.ndarray) -> np.ndarray:
    if not c:
        return P
    L = np.log(np.clip(P, 1e-6, 1.0))
    return _full(_softmax(L @ np.asarray(c["coef"]).T + np.asarray(c["intercept"])), c["classes"])


def load_pickle_verified(path: Path, sha: str):
    if sha256_file(path) != sha:
        raise RuntimeError(f"CHECKSUM_MISMATCH:{path.name}")
    with open(path, "rb") as f:
        return pickle.load(f)                          # own artifact, checksum verified against our registry


class ScalpModel:
    """Active task-A model: per horizon the selected classifier + calibrator + quantile regressors."""

    def __init__(self, entry: dict):
        self.entry = entry
        rd = Path(entry["run_dir"])
        arts = entry["artifacts"]
        self.h = {}
        for hz, spec in entry["models"].items():
            m = {"selected": spec["selected"]}
            if spec["selected"] in ("LR", "MLP"):
                m["clf"] = json.loads((rd / spec["file"]).read_text(encoding="utf-8"))
            elif spec["selected"] == "HGB":
                m["clf"] = load_pickle_verified(rd / spec["file"], arts[spec["file"]])
            else:
                m["prior"] = np.asarray(spec["prior"])
            m["cal"] = spec.get("calibrator")
            m["q"] = load_pickle_verified(rd / spec["quantiles_file"], arts[spec["quantiles_file"]]) if spec.get("quantiles_file") else None
            self.h[hz] = m

    def predict(self, X: np.ndarray) -> dict:
        out = {}
        for hz, m in self.h.items():
            if "prior" in m:
                P = np.tile(m["prior"], (len(X), 1))
            elif isinstance(m["clf"], dict):
                P = predict_json(m["clf"], X)
            else:
                P = _full(m["clf"].predict_proba(X), [int(c) for c in m["clf"].classes_])
            P = calibrate(m["cal"], P)
            Q = None
            if m["q"] is not None:
                Q = np.sort(np.column_stack([m["q"][k].predict(X) for k in ("q10", "q50", "q90")]), axis=1)   # pre-declared non-crossing rule
            out[hz] = {"P": P, "Q": Q}
        return out
