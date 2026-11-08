"""PMW Quant MetaModel (PMW-QUANT-META-1): regularised logistic regression of ONE named event + ridge model of net R, trained only on
rows that were logged at the decision moment (features = what was available then) and labelled later by the plan simulator.

Procedure (no level sees a future label):
1. Rows of one EventSpec task (same task_hash) sorted by decision time; blocks DEV (60 %) -> CAL (20 %) -> TEST (20 %) by time. Purge:
   a row of an earlier block whose label resolved after the next block starts (minus the embargo) is dropped from the earlier block.
2. DEV: expanding walk-forward folds (K=4) with the same purge; inside every fold the scaler, feature screen and model are fitted on the
   fold's train part only. The hyper-parameter (C of the logistic, alpha of the ridge) is picked by the mean OOF log loss / MAE.
   Ablation on the same folds: prior -> plan + context -> + base model outputs (full); the variant is picked on DEV OOF only.
3. Final model fitted on the whole (purged) DEV block. CAL block: calibrators identity / temperature / sigmoid (isotonic only with
   n_cal >= 1000) are compared on a forward split of CAL, the chosen one refitted on the whole CAL block. Residual quantiles of net R
   on CAL give the outcome dispersion interval.
4. Frozen. TEST block evaluated ONCE: log loss, Brier, reliability bins + ECE, AUC vs the prior baseline; net R MAE vs zero / mean
   baselines; strategy metrics of "enter when E[net R] > 0" vs "every candidate" after costs (net R, expectancy, drawdown, turnover)
   with block-bootstrap intervals. The test row ids are recorded; a later training whose TEST overlaps a seen TEST cannot be promoted.
5. Promotion criteria are fixed in CRITERIA before training (stored in the manifest). Status: INSUFFICIENT_EVIDENCE (not trained),
   VALIDATION_FAILED, VALIDATED_SHADOW. SYNTHETIC rows can train a TECHNICAL candidate only - never VALIDATED.
Artifacts are plain JSON (coefficients, scaler, calibrator - no pickle) saved atomically under paths.data_dir()/quant/models with a
manifest (hash, splits, seeds, metrics, criteria, reproduction sample) and an ACTIVE pointer with history (rollback).
"""
from __future__ import annotations

import hashlib
import json
import math
import time
import uuid
from pathlib import Path

import numpy as np

from . import features as F
from . import numeric as N
from .scheduler import write_json_atomic

VERSION = "PMW-QUANT-META-1"
CRITERIA = {"min_dev": 300, "min_cal": 100, "min_test": 100, "min_class_test": 20, "logloss_gain_vs_prior": 0.005, "max_ece": 0.08,
            "ece_bins": 10, "ece_min_bin": 10, "min_fold_win_share": 0.75, "min_feature_coverage": 0.05, "isotonic_min_cal": 1000,
            "min_net_known_share": 0.9, "embargo_s": 0.0, "folds": 4}
C_GRID = (0.01, 0.1, 1.0, 10.0)
ALPHA_GRID = (0.1, 1.0, 10.0, 100.0)
SEED = 20261108


class MetaError(ValueError):
    pass


# ------------------------------------------------------------------------------------------------ data
def matrix(rows: list[dict], names: list[str]) -> np.ndarray:
    out = []
    for r in rows:
        v, m = F.vectorise(r["features"], names)
        out.append(v + m)
    return np.asarray(out, dtype=np.float64).reshape(len(rows), 2 * len(names))


def screen(rows: list[dict], min_cov: float, groups: tuple[str, ...] | None = None) -> list[str]:
    cnt: dict[str, int] = {}
    for r in rows:
        for k in r["features"]:
            if groups is None or k.startswith(groups):
                cnt[k] = cnt.get(k, 0) + 1
    n = max(1, len(rows))
    return sorted(k for k, c in cnt.items() if c / n >= min_cov)


def purge(earlier: list[dict], next_start: float, embargo_s: float) -> list[dict]:
    return [r for r in earlier if r["resolve_ts"] <= next_start - embargo_s]


def blocks(rows: list[dict], embargo_s: float = 0.0, fr=(0.6, 0.2, 0.2)) -> dict:
    rs = sorted(rows, key=lambda r: (r["decision_ts"], r["row_id"]))
    n = len(rs)
    a, b = int(n * fr[0]), int(n * (fr[0] + fr[1]))
    dev, cal, test = rs[:a], rs[a:b], rs[b:]
    if cal:
        dev = purge(dev, cal[0]["decision_ts"], embargo_s)
    if test:
        cal = purge(cal, test[0]["decision_ts"], embargo_s)
    return {"dev": dev, "cal": cal, "test": test}


def assert_no_future(train: list[dict], val_start: float) -> None:
    bad = [r["row_id"] for r in train if r["resolve_ts"] > val_start]
    if bad:
        raise MetaError(f"LABEL_LEAK:{len(bad)} wierszy treningu rozstrzygniętych po starcie walidacji")


# ------------------------------------------------------------------------------------------------ models (fit with sklearn, predict with numpy)
class Scaler:
    def __init__(self, mean=None, scale=None):
        self.mean, self.scale = mean, scale

    def fit(self, X):
        self.mean = X.mean(axis=0)
        sd = X.std(axis=0)
        self.scale = np.where(sd > 1e-12, sd, 1.0)
        return self

    def t(self, X):
        return (X - self.mean) / self.scale


def fit_logit(X, y, C: float):
    from sklearn.linear_model import LogisticRegression
    if len(set(y.tolist())) < 2:
        raise MetaError("ONE_CLASS_IN_TRAIN")
    sc = Scaler().fit(X)
    m = LogisticRegression(C=C, max_iter=2000)
    m.fit(sc.t(X), y)
    return {"scaler": sc, "coef": m.coef_[0].astype(float), "intercept": float(m.intercept_[0]), "C": C}


def p_logit(mod, X) -> np.ndarray:
    return N.sigmoid(mod["scaler"].t(X) @ mod["coef"] + mod["intercept"])


def fit_ridge(X, y, alpha: float):
    from sklearn.linear_model import Ridge
    sc = Scaler().fit(X)
    m = Ridge(alpha=alpha)
    m.fit(sc.t(X), y)
    return {"scaler": sc, "coef": np.asarray(m.coef_, float), "intercept": float(m.intercept_), "alpha": alpha}


def p_ridge(mod, X) -> np.ndarray:
    return mod["scaler"].t(X) @ mod["coef"] + mod["intercept"]


def fit_calibrator(p, y, kind: str) -> dict:
    p, y = np.asarray(p, float), np.asarray(y, float)
    z = N.logit(p)
    if kind == "identity":
        return {"kind": "identity"}
    if kind == "temperature":
        best = min(np.exp(np.linspace(-2, 2, 81)), key=lambda T: N.log_loss(N.sigmoid(z / T), y))
        return {"kind": "temperature", "T": float(best)}
    if kind == "sigmoid":
        from sklearn.linear_model import LogisticRegression
        if len(set(y.tolist())) < 2:
            raise MetaError("ONE_CLASS_IN_CAL")
        m = LogisticRegression(C=1e6, max_iter=2000).fit(z.reshape(-1, 1), y)
        return {"kind": "sigmoid", "a": float(m.coef_[0][0]), "b": float(m.intercept_[0])}
    if kind == "isotonic":
        from sklearn.isotonic import IsotonicRegression
        ir = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(p, y)
        return {"kind": "isotonic", "x": [float(v) for v in ir.X_thresholds_], "y": [float(v) for v in ir.y_thresholds_]}
    raise MetaError(f"CALIBRATOR_UNKNOWN:{kind}")


def apply_cal(cal: dict, p) -> np.ndarray:
    p = np.asarray(p, float)
    k = cal["kind"]
    if k == "identity":
        return p
    if k == "temperature":
        return N.sigmoid(N.logit(p) / cal["T"])
    if k == "sigmoid":
        return N.sigmoid(cal["a"] * N.logit(p) + cal["b"])
    if k == "isotonic":
        return np.interp(p, cal["x"], cal["y"])
    raise MetaError(f"CALIBRATOR_UNKNOWN:{k}")


# ------------------------------------------------------------------------------------------------ walk-forward on DEV
def folds(dev: list[dict], k: int, embargo_s: float) -> list[tuple[list[dict], list[dict]]]:
    n = len(dev)
    edges = [int(n * i / (k + 1)) for i in range(k + 2)]
    out = []
    for i in range(1, k + 1):
        va = dev[edges[i]:edges[i + 1]]
        if not va:
            continue
        tr = purge(dev[:edges[i]], va[0]["decision_ts"], embargo_s)
        assert_no_future(tr, va[0]["decision_ts"] - embargo_s)
        out.append((tr, va))
    return out


def _variant_groups(v: str):
    return {"plan_context": ("plan:", "ctx:"), "full": None}[v]


def oof(dev: list[dict], crit: dict) -> dict:
    """OOF log loss per variant x C, ridge MAE per alpha, fold-level gains vs prior; everything fitted per fold."""
    fl = folds(dev, crit["folds"], crit["embargo_s"])
    res = {"folds": len(fl), "variants": {}, "ridge": {}}
    prior_ll = []
    for tr, va in fl:
        yt, yv = np.array([r["y"] for r in tr], float), np.array([r["y"] for r in va], float)
        pr = float(np.clip(yt.mean(), 1e-6, 1 - 1e-6))
        prior_ll.append(N.log_loss(np.full(len(yv), pr), yv))
    res["prior"] = {"fold_log_loss": prior_ll, "mean": float(np.mean(prior_ll)) if prior_ll else None}
    for v in ("plan_context", "full"):
        for C in C_GRID:
            lls, wins = [], 0
            for (tr, va), pll in zip(fl, prior_ll):
                names = screen(tr, crit["min_feature_coverage"], _variant_groups(v))
                if not names:
                    lls = None
                    break
                yt, yv = np.array([r["y"] for r in tr], float), np.array([r["y"] for r in va], float)
                try:
                    mod = fit_logit(matrix(tr, names), yt, C)
                except MetaError:
                    lls = None
                    break
                ll = N.log_loss(np.clip(p_logit(mod, matrix(va, names)), 1e-9, 1 - 1e-9), yv)
                lls.append(ll)
                wins += ll < pll
            if lls:
                res["variants"].setdefault(v, {})[str(C)] = {"mean_log_loss": float(np.mean(lls)), "fold_log_loss": lls, "fold_wins_vs_prior": wins}
    known = [r for r in dev if r.get("net_r") is not None]
    if len(known) >= 50:
        fk = folds(known, crit["folds"], crit["embargo_s"])
        for a in ALPHA_GRID:
            maes, base = [], []
            for tr, va in fk:
                names = screen(tr, crit["min_feature_coverage"])
                if not names:
                    continue
                mod = fit_ridge(matrix(tr, names), np.array([r["net_r"] for r in tr], float), a)
                yv = np.array([r["net_r"] for r in va], float)
                maes.append(N.regression_metrics(p_ridge(mod, matrix(va, names)), yv)["mae"])
                base.append(N.regression_metrics(np.full(len(yv), np.mean([r["net_r"] for r in tr])), yv)["mae"])
            if maes:
                res["ridge"][str(a)] = {"mean_mae": float(np.mean(maes)), "mean_baseline_mae": float(np.mean(base))}
    return res


# ------------------------------------------------------------------------------------------------ training
def _hash_rows(rows) -> str:
    h = hashlib.sha256()
    for r in rows:
        h.update(f"{r['row_id']}|{r['decision_ts']}|{r['y']}|{r.get('net_r')}".encode())
    return h.hexdigest()[:16]


def train(rows: list[dict], *, task: dict, crit: dict | None = None, seen_tests: list[list[str]] | None = None, data_kind: str = "REAL") -> dict:
    """rows: [{row_id, decision_ts, resolve_ts, features, y (0/1), net_r|None, data_kind}] of ONE task. -> {"status", "model"?, "report"}."""
    crit = {**CRITERIA, **(crit or {})}
    t0 = time.perf_counter()
    rows = [r for r in rows if r.get("y") in (0, 1, True, False)]
    for r in rows:
        r["y"] = int(r["y"])
    rep = {"version": VERSION, "criteria": crit, "n_rows": len(rows), "task": task, "seed": SEED}
    kinds = sorted({r.get("data_kind") or "UNKNOWN" for r in rows})
    rep["data_kinds"] = kinds
    B = blocks(rows, crit["embargo_s"])
    rep["blocks"] = {k: {"n": len(v), "from": v[0]["decision_ts"] if v else None, "to": v[-1]["decision_ts"] if v else None,
                         "positives": int(sum(r["y"] for r in v))} for k, v in B.items()}
    short = [f"{k}:{len(B[k])}<{crit['min_' + k]}" for k in ("dev", "cal", "test") if len(B[k]) < crit["min_" + k]]
    if short:
        rep["status"], rep["reason"] = "INSUFFICIENT_EVIDENCE", "za mało dojrzałych, oznaczonych wierszy: " + ", ".join(short)
        return {"status": "INSUFFICIENT_EVIDENCE", "report": rep}
    dev, cal, test = B["dev"], B["cal"], B["test"]
    if len({r["y"] for r in dev}) < 2:
        rep["status"], rep["reason"] = "INSUFFICIENT_EVIDENCE", "jedna klasa w bloku DEV"
        return {"status": "INSUFFICIENT_EVIDENCE", "report": rep}
    assert_no_future(dev, cal[0]["decision_ts"] - crit["embargo_s"])
    assert_no_future(cal, test[0]["decision_ts"] - crit["embargo_s"])
    o = oof(dev, crit)
    rep["dev_oof"] = o
    cands = [(v, C, d) for v, cs in o["variants"].items() for C, d in cs.items()]
    if not cands:
        rep["status"], rep["reason"] = "INSUFFICIENT_EVIDENCE", "żaden wariant nie dał się dopasować w foldach DEV"
        return {"status": "INSUFFICIENT_EVIDENCE", "report": rep}
    v_best, C_best, d_best = min(cands, key=lambda x: x[2]["mean_log_loss"])
    rep["selected"] = {"variant": v_best, "C": float(C_best), "dev_oof_log_loss": d_best["mean_log_loss"], "prior_dev_oof_log_loss": o["prior"]["mean"]}
    rep["ablation_dev_oof"] = {"prior": o["prior"]["mean"], **{v: min(d["mean_log_loss"] for d in cs.values()) for v, cs in o["variants"].items()}}
    names = screen(dev, crit["min_feature_coverage"], _variant_groups(v_best))
    Xd, yd = matrix(dev, names), np.array([r["y"] for r in dev], float)
    mod = fit_logit(Xd, yd, float(C_best))
    # calibration (forward split inside CAL to choose, then refit on all CAL)
    Xc, yc = matrix(cal, names), np.array([r["y"] for r in cal], float)
    pc = p_logit(mod, Xc)
    half = len(cal) // 2
    kinds_c = ["identity", "temperature", "sigmoid"] + (["isotonic"] if len(cal) >= crit["isotonic_min_cal"] else [])
    cmp = {}
    for k in kinds_c:
        try:
            cl = fit_calibrator(pc[:half], yc[:half], k)
            cmp[k] = N.log_loss(np.clip(apply_cal(cl, pc[half:]), 1e-9, 1 - 1e-9), yc[half:])
        except MetaError as exc:
            cmp[k] = None
            rep.setdefault("calibration_errors", {})[k] = str(exc)
    ok = {k: v for k, v in cmp.items() if v is not None}
    kind = min(ok, key=ok.get) if ok else "identity"
    calib = fit_calibrator(pc, yc, kind)
    rep["calibration"] = {"compared_forward_on_cal": cmp, "chosen": kind, "params": calib, "n_cal": len(cal)}
    # net R head
    ridge = None
    known_dev = [r for r in dev if r.get("net_r") is not None]
    share = len([r for r in rows if r.get("net_r") is not None]) / max(1, len(rows))
    rep["net_r_known_share"] = share
    if o["ridge"] and share >= crit["min_net_known_share"]:
        a_best = min(o["ridge"], key=lambda a: o["ridge"][a]["mean_mae"])
        ridge = fit_ridge(matrix(known_dev, names), np.array([r["net_r"] for r in known_dev], float), float(a_best))
        kc = [r for r in cal if r.get("net_r") is not None]
        res_c = np.array([r["net_r"] for r in kc], float) - p_ridge(ridge, matrix(kc, names)) if kc else np.array([])
        ridge["resid_q"] = [float(np.quantile(res_c, 0.1)), float(np.quantile(res_c, 0.9))] if len(res_c) >= 20 else None
        rep["net_r_model"] = {"alpha": float(a_best), "dev_oof": o["ridge"][a_best], "resid_q10_q90_cal": ridge["resid_q"]}
    else:
        rep["net_r_model"] = {"status": "NOT_TRAINED", "reason": f"znany net R w {share:.0%} wierszy (< {crit['min_net_known_share']:.0%}) lub za mało wierszy"}
    # ---- frozen: single TEST evaluation
    Xt, yt = matrix(test, names), np.array([r["y"] for r in test], float)
    pt = np.clip(apply_cal(calib, p_logit(mod, Xt)), 1e-9, 1 - 1e-9)
    prior = float(np.clip(np.mean(np.concatenate([yd, yc])), 1e-6, 1 - 1e-6))
    rel = N.reliability(pt, yt, crit["ece_bins"], crit["ece_min_bin"])
    tm = {"n": len(test), "positives": int(yt.sum()), "log_loss": N.log_loss(pt, yt), "brier": N.brier(pt, yt), "auc": N.auc(pt, yt),
          "ece": rel["ece"], "reliability": rel["bins"], "prior": prior, "prior_log_loss": N.log_loss(np.full(len(yt), prior), yt),
          "prior_brier": N.brier(np.full(len(yt), prior), yt)}
    test_ids = [r["row_id"] for r in test]
    tm["row_ids_hash"] = hashlib.sha256("|".join(test_ids).encode()).hexdigest()[:16]
    if ridge is not None:
        kt = [r for r in test if r.get("net_r") is not None]
        if len(kt) >= 10:
            Xk = matrix(kt, names)
            pr_ = p_ridge(ridge, Xk)
            yr = np.array([r["net_r"] for r in kt], float)
            take = pr_ > 0
            tm["net_r"] = {"model": N.regression_metrics(pr_, yr), "baseline_zero": N.regression_metrics(np.zeros(len(yr)), yr),
                           "baseline_dev_mean": N.regression_metrics(np.full(len(yr), np.mean([r["net_r"] for r in known_dev])), yr)}
            if ridge.get("resid_q"):
                lo, hi = pr_ + ridge["resid_q"][0], pr_ + ridge["resid_q"][1]
                tm["net_r"]["outcome_interval_80_coverage"] = float(np.mean((yr >= lo) & (yr <= hi)))
            strat = {"all": _strategy(yr), "model_ev_positive": _strategy(yr[take]) if take.any() else {"n": 0}}
            strat["turnover_share"] = float(take.mean())
            tm["strategy_after_costs"] = strat
    rep["test_once"] = tm
    # ---- promotion
    gates = {"data_real": kinds == ["REAL"], "logloss_gain_vs_prior": tm["log_loss"] < tm["prior_log_loss"] - crit["logloss_gain_vs_prior"],
             "ece": tm["ece"] is not None and tm["ece"] <= crit["max_ece"],
             "classes_in_test": min(tm["positives"], len(test) - tm["positives"]) >= crit["min_class_test"],
             "fold_stability": d_best["fold_wins_vs_prior"] / max(1, o["folds"]) >= crit["min_fold_win_share"],
             "test_block_fresh": not any(set(test_ids) & set(s) for s in (seen_tests or []))}
    rep["gates"] = gates
    status = "VALIDATED_SHADOW" if all(gates.values()) else "VALIDATION_FAILED"
    rep["status"] = status
    rep["failed_gates"] = [k for k, v in gates.items() if not v]
    model = {"version": VERSION, "feature_names": names, "feature_schema": F.schema(names), "scaler": {"mean": mod["scaler"].mean.tolist(),
             "scale": mod["scaler"].scale.tolist()}, "logit": {"coef": mod["coef"].tolist(), "intercept": mod["intercept"], "C": mod["C"]},
             "calibrator": calib, "prior": prior, "event_id": task.get("event_id"), "task_hash": task.get("task_hash"),
             "ridge": None if ridge is None else {"scaler": {"mean": ridge["scaler"].mean.tolist(), "scale": ridge["scaler"].scale.tolist()},
                                                  "coef": ridge["coef"].tolist(), "intercept": ridge["intercept"], "alpha": ridge["alpha"],
                                                  "resid_q": ridge.get("resid_q")}}
    rep["train_s"] = round(time.perf_counter() - t0, 3)
    rep["data_hash"] = _hash_rows(rows)
    rep["test_row_ids"] = test_ids
    rep["reproduction"] = [{"row_id": r["row_id"], "features": r["features"], "out": predict(model, r["features"])} for r in test[:5]]
    return {"status": status, "model": model, "report": rep}


def _strategy(netr: np.ndarray) -> dict:
    if len(netr) == 0:
        return {"n": 0}
    out = {"n": int(len(netr)), "net_r_sum": float(netr.sum()), "expectancy_r": float(netr.mean()), "max_drawdown_r": N.max_drawdown(netr),
           "win_share": float(np.mean(netr > 0))}
    if len(netr) >= 10:
        out["expectancy_ci90"] = N.block_bootstrap(netr, n_boot=500)
    return out


# ------------------------------------------------------------------------------------------------ inference
def predict(model: dict, feats: dict) -> dict:
    names = model["feature_names"]
    v, m = F.vectorise(feats, names)
    X = np.asarray([v + m], float)
    sc = model["scaler"]
    z = ((X - np.asarray(sc["mean"])) / np.asarray(sc["scale"])) @ np.asarray(model["logit"]["coef"]) + model["logit"]["intercept"]
    p = float(apply_cal(model["calibrator"], N.sigmoid(z))[0])
    out = {"p_event": p, "event_id": model.get("event_id"), "missing_features": [n for n, mm in zip(names, m) if mm],
           "coverage": 1 - sum(m) / max(1, len(names))}
    r = model.get("ridge")
    if r:
        rs = r["scaler"]
        e = float((((X - np.asarray(rs["mean"])) / np.asarray(rs["scale"])) @ np.asarray(r["coef"]) + r["intercept"])[0])
        out["e_net_r"] = e
        out["outcome_interval_80"] = [e + r["resid_q"][0], e + r["resid_q"][1]] if r.get("resid_q") else None
    else:
        out["e_net_r"], out["outcome_interval_80"] = None, None
    for k in ("p_event", "e_net_r"):
        if out[k] is not None and not math.isfinite(out[k]):
            raise MetaError(f"NON_FINITE_OUTPUT:{k}")
    return out


def contributions(model: dict, feats: dict, top: int = 8) -> list[dict]:
    """Linear trace of the logit: (value - mean) / scale * coef per input (incl. masks) - 'what had influence and why'."""
    names = model["feature_names"]
    v, m = F.vectorise(feats, names)
    x = np.asarray(v + m, float)
    sc = model["scaler"]
    c = (x - np.asarray(sc["mean"])) / np.asarray(sc["scale"]) * np.asarray(model["logit"]["coef"])
    labels = names + ["m:" + n for n in names]
    idx = np.argsort(-np.abs(c))[:top]
    return [{"input": labels[i], "value": float(x[i]), "logit_contribution": float(c[i])} for i in idx if abs(c[i]) > 1e-12]


# ------------------------------------------------------------------------------------------------ artifacts
def root(inst: str) -> Path:
    from .. import paths
    p = paths.data_dir() / "quant" / "models" / inst
    p.mkdir(parents=True, exist_ok=True)
    return p


def save(inst: str, res: dict, *, spec: dict) -> str:
    th = spec["task_hash"]
    ver = time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + "-" + uuid.uuid4().hex[:6]
    d = root(inst) / th / ver
    d.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(res["model"], sort_keys=True, allow_nan=False)
    (d / "model.json").write_text(blob, encoding="utf-8")
    man = {"model": "quant:metamodel", "version": ver, "instrument": inst, "status": res["status"], "task_hash": th, "event_spec": spec,
           "feature_schema": res["model"]["feature_schema"], "sha256": hashlib.sha256(blob.encode()).hexdigest(), "created_at": time.time(),
           "report": res["report"], "runtime": {"numpy": np.__version__, "meta_version": VERSION}}
    write_json_atomic(d / "manifest.json", man)
    return ver


def load(inst: str, task_hash: str, ver: str) -> tuple[dict, dict]:
    d = root(inst) / task_hash / ver
    man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    blob = (d / "model.json").read_text(encoding="utf-8")
    if hashlib.sha256(blob.encode()).hexdigest() != man.get("sha256"):
        raise MetaError("ARTIFACT_CHECKSUM_MISMATCH")
    model = json.loads(blob)
    if model.get("version") != VERSION:
        raise MetaError(f"INCOMPATIBLE_VERSION:{model.get('version')}")
    if model.get("feature_schema") != F.schema(model["feature_names"]) or not model["feature_schema"].startswith(F.VERSION):
        raise MetaError("INCOMPATIBLE_FEATURE_SCHEMA")
    for s in (man.get("report") or {}).get("reproduction") or []:                 # save/load/predict reproduction
        got = predict(model, s["features"])
        if abs(got["p_event"] - s["out"]["p_event"]) > 1e-9:
            raise MetaError("REPRODUCTION_MISMATCH")
    return model, man


def _ptr(inst: str) -> Path:
    return root(inst) / "ACTIVE.json"


def pointer(inst: str) -> dict:
    try:
        return json.loads(_ptr(inst).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"active": {}, "history": [], "seen_tests": {}}


def activate(inst: str, task_hash: str, ver: str) -> dict:
    model, man = load(inst, task_hash, ver)
    if man["status"] != "VALIDATED_SHADOW":
        raise MetaError(f"NOT_VALIDATED:{man['status']}")
    p = pointer(inst)
    prev = p["active"].get(task_hash)
    if prev:
        p["history"].append({"task_hash": task_hash, "version": prev, "replaced_at": time.time()})
    p["active"][task_hash] = ver
    write_json_atomic(_ptr(inst), p)
    return p


def rollback(inst: str, task_hash: str) -> dict:
    p = pointer(inst)
    hist = [h for h in p["history"] if h["task_hash"] == task_hash]
    if hist:
        last = hist[-1]
        p["history"].remove(last)
        p["active"][task_hash] = last["version"]
    else:
        p["active"].pop(task_hash, None)
    write_json_atomic(_ptr(inst), p)
    return p


def record_test(inst: str, task_hash: str, ids: list[str]) -> None:
    p = pointer(inst)
    p.setdefault("seen_tests", {}).setdefault(task_hash, []).append(ids)
    write_json_atomic(_ptr(inst), p)


def list_versions(inst: str) -> list[dict]:
    out = []
    for m in sorted(root(inst).glob("*/*/manifest.json")):
        try:
            man = json.loads(m.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rep = man.get("report") or {}
        out.append({"task_hash": man["task_hash"], "version": man["version"], "status": man["status"], "created_at": man.get("created_at"),
                    "n_rows": rep.get("n_rows"), "failed_gates": rep.get("failed_gates"), "test": {k: (rep.get("test_once") or {}).get(k) for k in
                                                                                                  ("log_loss", "prior_log_loss", "ece", "n")}})
    return out
