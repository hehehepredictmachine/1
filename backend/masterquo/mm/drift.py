"""Drift / data-quality monitoring and explicit retraining triggers (PMW-MM-DRIFT-1).

Reference distributions are stored with each artifact (train-period feature quantiles). A trigger may only RECOMMEND a candidate
training job (`action = SCHEDULE_CANDIDATE`); it never replaces a validated artifact and never touches execution.
"""
from __future__ import annotations

import time

import numpy as np

VERSION = "PMW-MM-DRIFT-1"
DEFAULT_POLICY = {"psi_warn": 0.10, "psi_alert": 0.25, "residual_ratio_alert": 1.5, "coverage_drop_alert": 0.15, "max_artifact_age_days": 30,
                  "min_recent": 200}


def reference_bins(x: np.ndarray, n_bins: int = 10) -> np.ndarray:
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    if len(x) < n_bins * 5:
        return np.array([])
    edges = np.unique(np.quantile(x, np.linspace(0, 1, n_bins + 1)))
    return edges


def psi(edges: np.ndarray, ref: np.ndarray, cur: np.ndarray) -> float | None:
    if len(edges) < 3:
        return None
    ref, cur = np.asarray(ref, float), np.asarray(cur, float)
    ref, cur = ref[np.isfinite(ref)], cur[np.isfinite(cur)]
    if not len(ref) or not len(cur):
        return None
    inner = edges[1:-1]
    a = np.bincount(np.searchsorted(inner, ref, side="right"), minlength=len(edges) - 1) / len(ref)
    b = np.bincount(np.searchsorted(inner, cur, side="right"), minlength=len(edges) - 1) / len(cur)
    a, b = np.clip(a, 1e-6, None), np.clip(b, 1e-6, None)
    return float(((b - a) * np.log(b / a)).sum())


def evaluate(*, feature_ref: dict, feature_cur: dict, ref_abs_err: float | None, cur_abs_err: float | None, ref_coverage: float | None,
             cur_coverage: float | None, artifact_created_at: float | None, policy: dict | None = None) -> dict:
    pol = {**DEFAULT_POLICY, **(policy or {})}
    reasons, per = [], {}
    for name, (edges, ref) in feature_ref.items():
        cur = feature_cur.get(name)
        if cur is None or len(cur) < pol["min_recent"]:
            per[name] = None
            continue
        v = psi(np.asarray(edges), np.asarray(ref), np.asarray(cur))
        per[name] = v
        if v is not None and v >= pol["psi_alert"]:
            reasons.append(f"INPUT_DRIFT:{name}:psi={v:.3f}")
    if ref_abs_err and cur_abs_err and cur_abs_err > pol["residual_ratio_alert"] * ref_abs_err:
        reasons.append(f"RESIDUAL_DRIFT:{cur_abs_err / ref_abs_err:.2f}x")
    if ref_coverage is not None and cur_coverage is not None and ref_coverage - cur_coverage > pol["coverage_drop_alert"]:
        reasons.append(f"CALIBRATION_DEGRADED:{ref_coverage:.3f}->{cur_coverage:.3f}")
    if artifact_created_at and (time.time() - artifact_created_at) / 86400 > pol["max_artifact_age_days"]:
        reasons.append("STALE_ARTIFACT")
    return {"version": VERSION, "policy": pol, "psi": per, "reasons": reasons,
            "action": "SCHEDULE_CANDIDATE" if reasons else "NONE",
            "note": "wyzwalacz tylko planuje trening kandydata; nie podmienia zwalidowanego artefaktu i nie dotyka wykonania"}
