"""Preprocessor fitted ONLY on the training block and saved with the model (atomic bundle).

* numeric features: float, missing stays NaN (DecisionTreeClassifier >= 1.3 and XGBoost handle NaN natively);
  columns that are entirely missing or constant in the training block are dropped (selection learned on train only);
* categoricals: one-hot with the categories SEEN IN TRAINING; an unseen category gives zeros + `<name>__unknown`=1;
* reference distributions (decile edges + proportions per numeric feature) for drift monitoring (PSI).
"""
from __future__ import annotations

import math

import numpy as np

from .features import CATEGORICAL, FEATURE_SCHEMA_VERSION, SCHEMA

NUMERIC = [f["name"] for f in SCHEMA if f["type"] == "float"]


class Preprocessor:
    def __init__(self):
        self.numeric: list[str] = []
        self.cats: dict[str, list[str]] = {}
        self.columns: list[str] = []
        self.reference: dict[str, dict] = {}
        self.schema_version = FEATURE_SCHEMA_VERSION

    # ------------------------------------------------------------ fit
    def fit(self, rows: list[dict]) -> "Preprocessor":
        self.numeric = []
        for n in NUMERIC:
            vals = np.array([_f(r.get(n)) for r in rows], dtype=float)
            ok = vals[~np.isnan(vals)]
            if ok.size >= max(5, 0.05 * len(rows)) and np.nanstd(ok) > 0:
                self.numeric.append(n)
                qs = np.quantile(ok, np.linspace(0, 1, 11))
                edges = sorted(set(float(x) for x in qs[1:-1]))
                self.reference[n] = {"edges": edges, "props": _props(ok, edges), "missing": float(np.mean(np.isnan(vals)))}
        self.cats = {}
        for c in CATEGORICAL:
            seen = sorted({str(r.get(c)) for r in rows if r.get(c) is not None})
            self.cats[c] = seen
        self.columns = list(self.numeric) + [f"{c}={v}" for c, vs in self.cats.items() for v in vs] + [f"{c}__unknown" for c in self.cats]
        return self

    # ------------------------------------------------------------ transform
    def transform(self, rows: list[dict]) -> np.ndarray:
        X = np.full((len(rows), len(self.columns)), np.nan, dtype=float)
        idx = {c: i for i, c in enumerate(self.columns)}
        for k, r in enumerate(rows):
            for n in self.numeric:
                X[k, idx[n]] = _f(r.get(n))
            for c, vs in self.cats.items():
                v = str(r.get(c))
                for cat in vs:
                    X[k, idx[f"{c}={cat}"]] = 1.0 if v == cat else 0.0
                X[k, idx[f"{c}__unknown"]] = 0.0 if v in vs else 1.0
        return X

    # ------------------------------------------------------------ drift
    def psi(self, rows: list[dict]) -> dict[str, float]:
        out = {}
        for n, ref in self.reference.items():
            vals = np.array([_f(r.get(n)) for r in rows], dtype=float)
            ok = vals[~np.isnan(vals)]
            if ok.size < 30:
                continue
            p, q = np.array(ref["props"]), np.array(_props(ok, ref["edges"]))
            p, q = np.clip(p, 1e-4, None), np.clip(q, 1e-4, None)
            out[n] = float(np.sum((q - p) * np.log(q / p)))
        return out

    # ------------------------------------------------------------ io
    def to_json(self) -> dict:
        return {"schema_version": self.schema_version, "numeric": self.numeric, "cats": self.cats, "columns": self.columns, "reference": self.reference}

    @classmethod
    def from_json(cls, d: dict) -> "Preprocessor":
        p = cls()
        p.schema_version, p.numeric, p.cats, p.columns, p.reference = d["schema_version"], d["numeric"], d["cats"], d["columns"], d["reference"]
        return p


def _f(v) -> float:
    if v is None:
        return math.nan
    try:
        return float(v)
    except (TypeError, ValueError):
        return math.nan


def _props(vals: np.ndarray, edges: list[float]) -> list[float]:
    b = np.searchsorted(np.array(edges), vals, side="right")
    cnt = np.bincount(b, minlength=len(edges) + 1).astype(float)
    return list(cnt / max(1.0, cnt.sum()))
