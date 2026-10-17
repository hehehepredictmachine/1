"""Frozen validation protocol, per-asset / per-horizon model pipeline, trial registry, single-use holdout and model artifacts
(MQ-LAB-VAL-1.0.0). See VALIDATION_PROTOCOL.md.

Order: protocol frozen (hash) -> data hash -> chronological dev / holdout split (purged at the boundary) -> expanding walk-forward
on dev with purging (label interval overlaps the validation period) + embargo -> every family evaluated on the same folds and
costs -> candidate chosen on dev only -> holdout evaluated ONCE for the frozen candidate (access logged; a second use is refused)
-> artifact. No data or adequate edge -> INSUFFICIENT_EVIDENCE / NO_VALIDATED_EDGE; thresholds are never lowered afterwards.
Every fit (scaler, PCA, GMM, neutralization, MiniRocket biases, calibration, tuning) happens inside the training fold.
"""
from __future__ import annotations

import hashlib
import json
import os
import pickle
import platform
import shutil
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import features as FE
from .edge import block_bootstrap_mean
from .minirocket import MiniRocket
from .nets import SEWSNN, ResNet1D, train as train_net

VERSION = "MQ-LAB-VAL-1.0.0"
FAMILIES = ("DUMMY", "RULE", "LOGREG", "TREE", "MINIROCKET", "XGB", "RESNET1D", "SEW_SNN")
EXPERIMENTS = ("LOGREG_PCA", "LOGREG_GMM_AUG", "LOGREG_NEUTRALIZED")
SEEDS = (11, 23, 37)


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def default_protocol(asset: str, *, tf: str = "M5", horizon: int = 12, side: str = "LONG", k_tp: float = 1.5, k_sl: float = 1.0,
                     holdout_frac: float = 0.2, folds: int = 4, seq_len: int = 32, families=FAMILIES, experiments=EXPERIMENTS,
                     budget: int = 3, min_events: int = 600, p_trade: float = 0.55) -> dict:
    p = {"version": VERSION, "asset": asset, "tf": tf, "horizon_bars": horizon, "side": side, "k_tp_atr": k_tp, "k_sl_atr": k_sl,
         "feature_set": FE.FEATURE_SET, "labels": FE.LABELS, "holdout_frac": holdout_frac, "folds": folds, "embargo_bars": horizon,
         "seq_len": seq_len, "families": list(families), "experiments": list(experiments), "tuning_budget_per_family": budget,
         "seeds": list(SEEDS), "min_events": min_events, "p_trade": p_trade,
         "promotion": {"min_fold_share_beating_dummy": 0.75, "min_logloss_gain_vs_dummy": 0.002, "max_ece": 0.10,
                       "min_trades_dev": max(60, min_events // 10), "expectancy_ci_lower_gt": 0.0, "cost_stress_r": 0.10,
                       "note": "progi ustalone przed badaniem; minimalna liczba transakcji wynika z liczby zdarzeń, nie jest uniwersalna"}}
    p["protocol_id"] = "VP-" + hashlib.sha256(json.dumps(p, sort_keys=True).encode()).hexdigest()[:12]
    return p


# ----------------------------------------------------------------------------- splits
def split_dev_holdout(t_event: np.ndarray, t_end: np.ndarray, frac: float, embargo_s: float) -> tuple[np.ndarray, np.ndarray, float]:
    order = np.argsort(t_event)
    cut = t_event[order[int(len(order) * (1 - frac))]]
    dev = np.where((t_end < cut))[0]                                  # purge: dev labels end before the holdout starts
    hold = np.where(t_event >= cut + embargo_s)[0]
    return dev, hold, float(cut)


def walk_forward(t_event: np.ndarray, t_end: np.ndarray, idx: np.ndarray, k: int, embargo_s: float) -> list[tuple[np.ndarray, np.ndarray]]:
    """Expanding folds on the dev indices. Train = earlier samples whose label END is before (val_start - embargo)."""
    idx = idx[np.argsort(t_event[idx])]
    chunks = np.array_split(idx, k + 1)
    out = []
    for f in range(1, k + 1):
        val = chunks[f]
        if not len(val):
            continue
        v0 = t_event[val].min()
        prior = np.concatenate(chunks[:f])
        train = prior[t_end[prior] < v0 - embargo_s]
        out.append((train, val))
    return out


# ----------------------------------------------------------------------------- metrics
def metrics(p: np.ndarray, y: np.ndarray, r: np.ndarray, p_trade: float, cost_stress: float = 0.0) -> dict:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    ll = float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())
    brier = float(((p - y) ** 2).mean())
    bins = np.clip((p * 10).astype(int), 0, 9)
    ece = float(sum(abs(p[bins == b].mean() - y[bins == b].mean()) * (bins == b).mean() for b in range(10) if (bins == b).any()))
    trade = p >= p_trade
    tr = r[trade] - cost_stress
    try:
        from sklearn.metrics import roc_auc_score
        auc = float(roc_auc_score(y, p)) if len(set(y.tolist())) == 2 else None
    except Exception:
        auc = None
    return {"n": int(len(y)), "base_rate": float(y.mean()), "log_loss": ll, "brier": brier, "ece": ece, "auc": auc,
            "trades": int(trade.sum()), "coverage": float(trade.mean()), "abstentions": int((~trade).sum()),
            "expectancy_r": float(tr.mean()) if len(tr) else None, "win_rate": float((r[trade] > 0).mean()) if trade.any() else None,
            "max_dd_r": _max_dd(tr) if len(tr) else None}


def _max_dd(x: np.ndarray) -> float:
    eq = np.cumsum(x)
    return float((np.maximum.accumulate(np.concatenate([[0], eq]))[1:] - eq).max())


# ----------------------------------------------------------------------------- model families
class Fitted:
    def __init__(self, family: str, obj, cfg: dict, prep: dict | None = None):
        self.family, self.obj, self.cfg, self.prep = family, obj, cfg, prep or {}

    def predict(self, Xtab: np.ndarray, Xseq: np.ndarray | None, regime: np.ndarray | None = None) -> np.ndarray:
        f, o, pr = self.family, self.obj, self.prep
        if f == "DUMMY":
            return np.full(len(Xtab), o)
        if f == "RULE":
            on = Xtab[:, FE.FEATURES.index("ema_gap_50")] > 0
            return np.where(on, o[1], o[0])
        if f in ("RESNET1D",):
            return o.predict_proba((Xseq - pr["mu"]) / pr["sd"])[:, 1]
        if f == "SEW_SNN":
            return o.predict_proba(((Xseq - pr["mu"]) / pr["sd"]).transpose(0, 2, 1), regime=regime)[:, 1]
        if f == "MINIROCKET":
            Z = pr["mr"].transform(Xseq)
            return o.predict_proba(pr["sc"].transform(Z))[:, 1]
        Z = pr["sc"].transform(Xtab) if "sc" in pr else Xtab
        if "pca" in pr:
            Z = pr["pca"].transform(Z)
        if "neut" in pr:
            Z = Z - pr["neut_fac"](Xtab) @ pr["neut"]
        return o.predict_proba(Z)[:, 1]


def _regime(Xtab):
    return (Xtab[:, FE.FEATURES.index("vol_pct")] > 0.5).astype(float)


def fit_family(family: str, Xtr, Xseq_tr, ytr, Xin=None, Xseq_in=None, yin=None, *, seed: int, budget: int) -> Fitted:
    """Fit one family on the training fold; hyper-parameters chosen on the inner (time-later) part of that fold."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    if family == "DUMMY":
        return Fitted(family, float(ytr.mean()), {})
    if family == "RULE":
        on = Xtr[:, FE.FEATURES.index("ema_gap_50")] > 0
        return Fitted(family, (float(ytr[~on].mean()) if (~on).any() else float(ytr.mean()),
                               float(ytr[on].mean()) if on.any() else float(ytr.mean())), {"rule": "ema_gap_50 > 0"})
    if Xin is None:                               # inner split = last 25% of the training fold (chronological)
        cut = int(len(ytr) * 0.75)
        Xin, Xseq_in, yin = Xtr[cut:], (Xseq_tr[cut:] if Xseq_tr is not None else None), ytr[cut:]
        Xtr, Xseq_tr, ytr = Xtr[:cut], (Xseq_tr[:cut] if Xseq_tr is not None else None), ytr[:cut]

    def ll(p, y):
        p = np.clip(p, 1e-6, 1 - 1e-6)
        return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())
    best = None
    if family in ("LOGREG", "LOGREG_PCA", "LOGREG_GMM_AUG", "LOGREG_NEUTRALIZED"):
        sc = StandardScaler().fit(Xtr)
        prep = {"sc": sc}
        Ztr, Zin = sc.transform(Xtr), sc.transform(Xin)
        ytr_fit = ytr
        if family == "LOGREG_PCA":
            from sklearn.decomposition import PCA
            pca = PCA(n_components=0.95, random_state=seed).fit(Ztr)
            prep["pca"] = pca
            prep["pca_explained"] = pca.explained_variance_ratio_.tolist()
            Ztr, Zin = pca.transform(Ztr), pca.transform(Zin)
        if family == "LOGREG_NEUTRALIZED":
            fac = lambda X: np.column_stack([X[:, FE.FEATURES.index("ema_gap_50")], X[:, FE.FEATURES.index("atr_rel")]])  # noqa: E731
            Ftr = fac(Xtr)
            B, *_ = np.linalg.lstsq(np.column_stack([Ftr, np.ones(len(Ftr))]), Ztr, rcond=None)
            prep["neut"] = B[:2]
            prep["neut_fac"] = fac
            Ztr = Ztr - Ftr @ B[:2]
            Zin = Zin - fac(Xin) @ B[:2]
        if family == "LOGREG_GMM_AUG":
            from sklearn.mixture import GaussianMixture
            aug = []
            for cls in (0, 1):
                m = ytr == cls
                if m.sum() >= 20:
                    g = GaussianMixture(n_components=min(4, int(m.sum() // 10)), random_state=seed).fit(Ztr[m])
                    s, _ = g.sample(int(m.sum() // 2))
                    aug.append((s, np.full(len(s), cls)))
            if aug:                                  # synthetic rows ONLY in the training fold, never in validation/holdout
                Ztr = np.vstack([Ztr] + [a[0] for a in aug])
                ytr_fit = np.concatenate([ytr] + [a[1] for a in aug])
                prep["gmm_synthetic_rows"] = int(sum(len(a[1]) for a in aug))
        for C in (0.01, 0.1, 1.0)[:budget]:
            m = LogisticRegression(C=C, max_iter=500).fit(Ztr, ytr_fit)
            s = ll(m.predict_proba(Zin)[:, 1], yin)
            if best is None or s < best[0]:
                best = (s, C)
        Zall = np.vstack([Ztr, Zin])
        yall = np.concatenate([ytr_fit, yin])
        return Fitted(family, LogisticRegression(C=best[1], max_iter=500).fit(Zall, yall), {"C": best[1]}, prep)
    if family == "TREE":
        from sklearn.tree import DecisionTreeClassifier
        for dpt in (2, 3, 5)[:budget]:
            m = DecisionTreeClassifier(max_depth=dpt, min_samples_leaf=30, random_state=seed).fit(Xtr, ytr)
            s = ll(m.predict_proba(Xin)[:, 1], yin)
            if best is None or s < best[0]:
                best = (s, dpt)
        return Fitted(family, DecisionTreeClassifier(max_depth=best[1], min_samples_leaf=30, random_state=seed)
                      .fit(np.vstack([Xtr, Xin]), np.concatenate([ytr, yin])), {"max_depth": best[1]})
    if family == "XGB":
        import xgboost as xgb
        for dpt in (2, 3, 4)[:budget]:
            m = xgb.XGBClassifier(n_estimators=200, max_depth=dpt, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
                                  random_state=seed, n_jobs=2, early_stopping_rounds=20, eval_metric="logloss")
            m.fit(Xtr, ytr, eval_set=[(Xin, yin)], verbose=False)
            s = ll(m.predict_proba(Xin)[:, 1], yin)
            if best is None or s < best[0]:
                best = (s, dpt, int(m.best_iteration or 200))
        m = xgb.XGBClassifier(n_estimators=max(10, best[2] + 1), max_depth=best[1], learning_rate=0.05, subsample=0.8,
                              colsample_bytree=0.8, random_state=seed, n_jobs=2)
        return Fitted(family, m.fit(np.vstack([Xtr, Xin]), np.concatenate([ytr, yin])), {"max_depth": best[1], "trees": best[2] + 1})
    if family == "MINIROCKET":
        mr = MiniRocket(num_features=1008, seed=seed).fit(Xseq_tr)
        Ztr, Zin = mr.transform(Xseq_tr), mr.transform(Xseq_in)
        sc = StandardScaler().fit(Ztr)
        for C in (0.001, 0.01, 0.1)[:budget]:
            m = LogisticRegression(C=C, max_iter=1000).fit(sc.transform(Ztr), ytr)
            s = ll(m.predict_proba(sc.transform(Zin))[:, 1], yin)
            if best is None or s < best[0]:
                best = (s, C)
        m = LogisticRegression(C=best[1], max_iter=1000).fit(sc.transform(np.vstack([Ztr, Zin])), np.concatenate([ytr, yin]))
        return Fitted(family, m, {"C": best[1], "features": int(Ztr.shape[1])}, {"mr": mr, "sc": sc})
    if family in ("RESNET1D", "SEW_SNN"):
        mu = Xseq_tr.mean(axis=(0, 2), keepdims=True)
        sd = Xseq_tr.std(axis=(0, 2), keepdims=True) + 1e-9
        a, b = (Xseq_tr - mu) / sd, (Xseq_in - mu) / sd
        if family == "RESNET1D":
            m = ResNet1D(a.shape[1], width=12, blocks=2, seed=seed)
            hist = train_net(m, a, ytr, b, yin, epochs=20, lr=3e-3, seed=seed)
        else:
            m = SEWSNN(a.shape[1], hidden=16, seed=seed, energy_lambda=0.01, router=True)
            hist = train_net(m, a.transpose(0, 2, 1), ytr, b.transpose(0, 2, 1), yin, epochs=15, lr=5e-3, seed=seed,
                             regime=_regime(Xtr), regime_v=_regime(Xin))
        return Fitted(family, m, {"curve": hist["curve"], **m.cfg}, {"mu": mu, "sd": sd})
    raise ValueError("UNKNOWN_FAMILY:" + family)


# ----------------------------------------------------------------------------- artifacts
class ArtifactMismatch(ValueError):
    pass


def save_artifact(root: Path, fitted: Fitted, manifest: dict) -> Path:
    """Atomic: write into a tmp dir, hash, then rename. The manifest pins asset, instrument, source, horizon, feature schema,
    cut-off, params, seeds, code version, metrics and dependency versions."""
    import sklearn
    root.mkdir(parents=True, exist_ok=True)
    mid = manifest["model_id"]
    tmp = root / (mid + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir()
    blob = pickle.dumps({"family": fitted.family, "obj": fitted.obj, "cfg": fitted.cfg,
                         "prep": {k: v for k, v in fitted.prep.items() if k != "neut_fac"}})
    (tmp / "model.pkl").write_bytes(blob)
    manifest = {**manifest, "sha256": hashlib.sha256(blob).hexdigest(),
                "dependencies": {"python": platform.python_version(), "numpy": np.__version__, "scikit-learn": sklearn.__version__}}
    (tmp / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    final = root / mid
    if final.exists():
        shutil.rmtree(final)
    os.replace(tmp, final)
    return final


def load_artifact(path: Path, *, asset: str, feature_set: str) -> tuple[Fitted, dict]:
    man = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    if man.get("asset") != asset:
        raise ArtifactMismatch(f"ASSET_MISMATCH:{man.get('asset')}!={asset}")
    if man.get("feature_set") != feature_set or man.get("features") != FE.FEATURES:
        raise ArtifactMismatch("FEATURE_SCHEMA_MISMATCH")
    blob = (path / "model.pkl").read_bytes()
    if hashlib.sha256(blob).hexdigest() != man.get("sha256"):
        raise ArtifactMismatch("ARTIFACT_CHECKSUM_MISMATCH")
    d = pickle.loads(blob)
    prep = d["prep"]
    if d["family"] == "LOGREG_NEUTRALIZED":
        prep["neut_fac"] = lambda X: np.column_stack([X[:, FE.FEATURES.index("ema_gap_50")], X[:, FE.FEATURES.index("atr_rel")]])
    return Fitted(d["family"], d["obj"], d["cfg"], prep), man


# ----------------------------------------------------------------------------- the study
class Study:
    """One asset x horizon study on the given closed bars. `db` = trial registry + holdout log."""

    def __init__(self, db, protocol: dict, bars: list[dict], *, point: float, data_source: str, instrument_id: str | None,
                 log=None, progress=None, cancel=None):
        self.db, self.p, self.bars = db, protocol, bars
        self.point, self.source, self.instrument_id = point, data_source, instrument_id
        self.log = log or (lambda m: None)
        self.progress = progress or (lambda done, total, msg: None)
        self.cancel = cancel or (lambda: False)
        self.data_hash = FE.dataset_hash(bars)

    def _trial(self, family: str, status: str, metrics_: dict | None, config: dict, seeds, note: str = "") -> str:
        tid = "TR-" + uuid.uuid4().hex[:12]
        self.db.execute("INSERT INTO lab_trials(trial_id, created_at, asset, horizon, model_family, protocol_id, data_hash, config, seeds, status, metrics, note) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (tid, now(), self.p["asset"], f"{self.p['tf']}x{self.p['horizon_bars']}", family, self.p["protocol_id"], self.data_hash,
                         json.dumps(config, default=str)[:20000], json.dumps(list(seeds)), status, json.dumps(metrics_, default=str), note))
        return tid

    def prepare(self) -> dict:
        p = self.p
        fm = FE.feature_matrix(self.bars, p["tf"])
        lb = FE.triple_barrier(self.bars, p["tf"], side=p["side"], horizon=p["horizon_bars"], k_tp=p["k_tp_atr"], k_sl=p["k_sl_atr"], point=self.point)
        ok = (~fm["warmup"]) & (lb["y"] >= 0) & (np.arange(len(self.bars)) >= p["seq_len"])
        idx = np.where(ok)[0]
        return {"fm": fm, "lb": lb, "idx": idx}

    def run(self) -> dict:
        p = self.p
        t0 = time.perf_counter()
        prep = self.prepare()
        fm, lb, idx = prep["fm"], prep["lb"], prep["idx"]
        res = {"protocol": p, "protocol_id": p["protocol_id"], "asset": p["asset"], "data_hash": self.data_hash, "data_source": self.source,
               "instrument_id": self.instrument_id, "samples": int(len(idx)), "ambiguous_same_bar": int(lb["ambiguous"][idx].sum()),
               "label_spec": lb["spec"], "families": {}, "controls": {}, "started_at": now()}
        if len(idx) < p["min_events"]:
            res["verdict"] = "INSUFFICIENT_EVIDENCE"
            res["reason"] = f"{len(idx)} zdarzeń < min_events {p['min_events']}"
            self._trial("ALL", "INSUFFICIENT_EVIDENCE", None, p, p["seeds"], res["reason"])
            return res
        X = fm["X"][idx]
        Xs = FE.sequences(fm["X"], idx, p["seq_len"])
        y = lb["y"][idx].astype(int)
        r = lb["r"][idx]
        te, tl = fm["t_event"][idx], lb["t_label_end"][idx]
        emb = p["embargo_bars"] * FE.TF_SEC[p["tf"]]
        dev, hold, cut = split_dev_holdout(te, tl, p["holdout_frac"], emb)
        res.update(dev_samples=int(len(dev)), holdout_samples=int(len(hold)),
                   holdout_hash=hashlib.sha256(json.dumps([float(x) for x in te[hold]]).encode()).hexdigest()[:16],
                   holdout_from=datetime.fromtimestamp(cut, timezone.utc).isoformat(), period={
                       "from": datetime.fromtimestamp(te.min(), timezone.utc).isoformat(), "to": datetime.fromtimestamp(te.max(), timezone.utc).isoformat()})
        folds = walk_forward(te, tl, dev, p["folds"], emb)
        fams = list(p["families"]) + list(p["experiments"])
        total = len(fams) * len(folds) * len(p["seeds"])
        done = 0
        oof: dict[str, dict] = {}
        for fam in fams:
            fold_m, preds = [], {}
            status, note = "COMPLETED", ""
            try:
                for (tr, va) in folds:
                    ps = []
                    for sd in (p["seeds"] if fam in ("MINIROCKET", "RESNET1D", "SEW_SNN", "XGB", "LOGREG_GMM_AUG", "TREE") else p["seeds"][:1]):
                        if self.cancel():
                            raise InterruptedError("CANCELLED")
                        f = fit_family(fam, X[tr], Xs[tr], y[tr], seed=sd, budget=p["tuning_budget_per_family"])
                        ps.append(f.predict(X[va], Xs[va], _regime(X[va])))
                        done += 1
                        self.progress(done, total, f"{fam}")
                    pv = np.mean(ps, axis=0)                      # pre-fixed seed set averaged - no lucky seed
                    fold_m.append(metrics(pv, y[va], r[va], p["p_trade"]))
                    for i, v in zip(va, pv):
                        preds[int(i)] = float(v)
            except InterruptedError:
                status, note = "CANCELLED", "anulowano"
            except Exception as exc:  # a failing family is recorded, never hidden
                status, note = "FAILED", f"{type(exc).__name__}: {exc}"[:300]
            agg = self._aggregate(fold_m)
            res["families"][fam] = {"status": status, "note": note, "folds": fold_m, **agg}
            oof[fam] = preds
            self._trial(fam, status, agg, {"family": fam, "protocol_id": p["protocol_id"]}, p["seeds"], note)
            if status == "CANCELLED":
                res["verdict"] = "CANCELLED"
                return res
        res["controls"] = self._controls(X, Xs, y, r, folds)
        cand = self._select(res, oof, y, r)
        res["candidate"] = cand
        res["verdict"] = cand["verdict"]
        if cand["verdict"] == "CANDIDATE_PASSED_DEV":
            res["holdout"] = self.holdout_once(cand["family"], X, Xs, y, r, dev, hold, res["holdout_hash"])
            res["verdict"] = "HOLDOUT_PASSED" if res["holdout"].get("passed") else "NO_VALIDATED_EDGE"
        res["seconds"] = round(time.perf_counter() - t0, 1)
        res["finished_at"] = now()
        return res

    @staticmethod
    def _aggregate(fold_m: list[dict]) -> dict:
        if not fold_m:
            return {}
        keys = ("log_loss", "brier", "ece", "auc", "expectancy_r", "coverage")
        out = {}
        for k in keys:
            v = [m[k] for m in fold_m if m.get(k) is not None]
            out[k + "_mean"] = float(np.mean(v)) if v else None
            out[k + "_std"] = float(np.std(v)) if v else None
        out["trades_total"] = int(sum(m["trades"] for m in fold_m))
        return out

    def _controls(self, X, Xs, y, r, folds) -> dict:
        """Negative controls (a model must NOT beat the dummy here):
        PERMUTED_BLOCK_LABELS - labels shuffled in blocks of 50 (keeps autocorrelation, breaks the feature link);
        FUTURE_SHIFTED_LABELS - each row paired with the label of the row 10 x H later (not knowable from current features);
        rows whose shifted label would come from the validation period are purged from training."""
        rng = np.random.default_rng(99)
        k = self.p["horizon_bars"] * 10
        out = {}
        for name in ("PERMUTED_BLOCK_LABELS", "FUTURE_SHIFTED_LABELS"):
            lls, dum = [], []
            for tr, va in folds:
                if name == "PERMUTED_BLOCK_LABELS":
                    b = 50
                    blocks = [y[i:i + b] for i in range(0, len(y), b)]
                    rng.shuffle(blocks)
                    yy, trk, vak = np.concatenate(blocks), tr, va
                else:
                    yy = np.concatenate([y[k:], np.full(k, -1)])
                    trk = tr[tr + k < va.min()]
                    vak = va[(va + k) < len(y)]
                if len(trk) < 50 or len(vak) < 20:
                    continue
                f = fit_family("LOGREG", X[trk], Xs[trk], yy[trk], seed=11, budget=2)
                pv = f.predict(X[vak], Xs[vak])
                lls.append(metrics(pv, yy[vak], r[vak], self.p["p_trade"])["log_loss"])
                dum.append(metrics(np.full(len(vak), yy[trk].mean()), yy[vak], r[vak], self.p["p_trade"])["log_loss"])
            gain = float(np.mean(np.array(dum) - np.array(lls))) if lls else None
            out[name] = {"logloss_gain_vs_dummy": gain, "folds": len(lls),
                         "suspicious": bool(gain is not None and gain > self.p["promotion"]["min_logloss_gain_vs_dummy"])}
        return out

    def _select(self, res: dict, oof: dict, y, r) -> dict:
        p, pr = self.p, self.p["promotion"]
        dummy = res["families"].get("DUMMY", {}).get("folds") or []
        best = None
        table = []
        for fam, d in res["families"].items():
            if fam == "DUMMY" or d.get("status") != "COMPLETED" or not d.get("folds"):
                continue
            gains = [dm["log_loss"] - fm["log_loss"] for dm, fm in zip(dummy, d["folds"])]
            share = float(np.mean([g >= pr["min_logloss_gain_vs_dummy"] for g in gains])) if gains else 0.0
            ids = sorted(oof[fam])
            pv = np.array([oof[fam][i] for i in ids])
            tr = pv >= p["p_trade"]
            rr = r[ids][tr] - pr["cost_stress_r"]
            boot = block_bootstrap_mean(rr.tolist()) if len(rr) >= 10 else {"status": "INSUFFICIENT_EVIDENCE"}
            ok = (share >= pr["min_fold_share_beating_dummy"] and (d.get("ece_mean") or 1) <= pr["max_ece"]
                  and int(tr.sum()) >= pr["min_trades_dev"] and boot.get("ci95") is not None and boot["ci95"][0] > pr["expectancy_ci_lower_gt"])
            row = {"family": fam, "fold_share_beating_dummy": share, "mean_gain": float(np.mean(gains)) if gains else None,
                   "oof_trades": int(tr.sum()), "expectancy_after_stress": boot.get("mean"), "ci95": boot.get("ci95"), "eligible": bool(ok)}
            table.append(row)
            if ok and (best is None or row["mean_gain"] > best["mean_gain"]):
                best = row
        if any(c.get("suspicious") for c in res["controls"].values()):
            return {"verdict": "NO_VALIDATED_EDGE", "reason": "KONTROLA_PERMUTACYJNA_LUB_OPOZNIONA_PODEJRZANA – możliwy przeciek; wymaga dochodzenia",
                    "table": table}
        if best is None:
            return {"verdict": "NO_VALIDATED_EDGE", "reason": "żadna rodzina nie spełniła z góry ustalonych kryteriów na danych rozwojowych",
                    "table": table}
        return {"verdict": "CANDIDATE_PASSED_DEV", "family": best["family"], "table": table}

    def holdout_once(self, family, X, Xs, y, r, dev, hold, holdout_hash) -> dict:
        used = self.db.one("SELECT * FROM lab_holdout_access WHERE asset=? AND horizon=? AND holdout_hash=?",
                           (self.p["asset"], f"{self.p['tf']}x{self.p['horizon_bars']}", holdout_hash))
        if used:
            return {"refused": "HOLDOUT_ALREADY_USED", "previous": used}
        f = fit_family(family, X[dev], Xs[dev], y[dev], seed=self.p["seeds"][0], budget=self.p["tuning_budget_per_family"])
        m = metrics(f.predict(X[hold], Xs[hold], _regime(X[hold])), y[hold], r[hold], self.p["p_trade"], self.p["promotion"]["cost_stress_r"])
        dm = metrics(np.full(len(hold), y[dev].mean()), y[hold], r[hold], self.p["p_trade"])
        passed = (dm["log_loss"] - m["log_loss"]) >= self.p["promotion"]["min_logloss_gain_vs_dummy"] and (m["expectancy_r"] or -1) > 0
        out = {"family": family, "metrics": m, "dummy": dm, "passed": bool(passed)}
        self.db.execute("INSERT INTO lab_holdout_access(at, asset, horizon, protocol_id, holdout_hash, candidate_id, result) VALUES (?,?,?,?,?,?,?)",
                        (now(), self.p["asset"], f"{self.p['tf']}x{self.p['horizon_bars']}", self.p["protocol_id"], holdout_hash, family,
                         json.dumps(out, default=str)))
        return out


# ----------------------------------------------------------------------------- background job (one per asset)
class LabTrainer:
    def __init__(self, db, root: Path, log=None):
        self.db, self.root, self.log = db, Path(root), log
        self.jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def start(self, asset: str, bars: list[dict], *, point: float, data_source: str, instrument_id: str | None, protocol: dict,
              artifact_family: str = "auto") -> dict:
        with self._lock:
            if any(j["status"] == "RUNNING" for j in self.jobs.values()):
                return {"started": False, "reason": "JOB_ALREADY_RUNNING"}
            jid = "LJOB-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:4]
            job = {"job_id": jid, "asset": asset, "status": "RUNNING", "progress": 0, "total": 0, "stage": "start", "logs": [],
                   "started_at": now(), "protocol_id": protocol["protocol_id"], "data_source": data_source, "cancel": False}
            self.jobs[jid] = job
        threading.Thread(target=self._run, args=(job, bars, point, data_source, instrument_id, protocol, artifact_family),
                         name="lab-train", daemon=True).start()
        return {"started": True, "job_id": jid}

    def cancel(self, jid: str) -> dict:
        j = self.jobs.get(jid)
        if not j:
            return {"ok": False, "reason": "UNKNOWN_JOB"}
        j["cancel"] = True
        return {"ok": True}

    def _run(self, job, bars, point, source, instrument_id, protocol, artifact_family):
        def prog(d, t, msg):
            job.update(progress=d, total=t, stage=msg)

        def logl(m):
            job["logs"] = (job["logs"] + [f"{now()} {m}"])[-200:]
        try:
            logl(f"start {protocol['asset']} {protocol['tf']}x{protocol['horizon_bars']} źródło={source} świec={len(bars)}")
            st = Study(self.db, protocol, bars, point=point, data_source=source, instrument_id=instrument_id, progress=prog,
                       cancel=lambda: job["cancel"])
            res = st.run()
            out = self.root / "studies"
            out.mkdir(parents=True, exist_ok=True)
            f = out / f"{job['job_id']}.json"
            tmp = f.with_suffix(".tmp")
            tmp.write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
            os.replace(tmp, f)                                           # checkpoint / result written atomically
            job["result_file"] = str(f)
            job["verdict"] = res.get("verdict")
            fam = res.get("candidate", {}).get("family") if artifact_family == "auto" else artifact_family
            if fam and res.get("samples", 0) >= protocol["min_events"]:
                prepd = st.prepare()
                idx = prepd["idx"]
                X = prepd["fm"]["X"][idx]
                Xs = FE.sequences(prepd["fm"]["X"], idx, protocol["seq_len"])
                y = prepd["lb"]["y"][idx].astype(int)
                fitted = fit_family(fam, X, Xs, y, seed=protocol["seeds"][0], budget=protocol["tuning_budget_per_family"])
                synthetic = source != "MT5"
                role = "fixture_only" if synthetic else ("shadow" if res.get("verdict") == "HOLDOUT_PASSED" else "research")
                mid = f"LM-{protocol['asset']}-{protocol['tf']}x{protocol['horizon_bars']}-{fam}-{uuid.uuid4().hex[:6]}"
                man = {"model_id": mid, "model_version": VERSION, "asset": protocol["asset"], "instrument_id": instrument_id, "data_source": source,
                       "horizon": f"{protocol['tf']}x{protocol['horizon_bars']}", "family": fam, "feature_set": FE.FEATURE_SET, "features": FE.FEATURES,
                       "seq_channels": FE.SEQ_CHANNELS, "seq_len": protocol["seq_len"], "label_spec": res.get("label_spec"),
                       "cutoff": res.get("period", {}).get("to"), "protocol_id": protocol["protocol_id"], "params": fitted.cfg,
                       "seeds": protocol["seeds"], "verdict": res.get("verdict"), "role": role, "trained_at": now(),
                       "metrics": {k: v for k, v in (res.get("families", {}).get(fam) or {}).items() if k != "folds"}}
                p = save_artifact(self.root / "models" / protocol["asset"], fitted, man)
                job["artifact"] = str(p)
                job["model_id"] = mid
                logl(f"artefakt {mid} rola={role}")
            job["status"] = "CANCELLED" if res.get("verdict") == "CANCELLED" else "COMPLETED"
            logl(f"koniec: {res.get('verdict')}")
        except Exception as exc:  # a failed challenger never stops the live analysis
            job["status"] = "FAILED"
            job["error"] = f"{type(exc).__name__}: {exc}"[:400]
            logl("BŁĄD " + job["error"])
        finally:
            job["finished_at"] = now()

    def public(self) -> list[dict]:
        return [{k: v for k, v in j.items() if k != "cancel"} for j in sorted(self.jobs.values(), key=lambda j: j["started_at"], reverse=True)][:10]

    def models(self, asset: str) -> list[dict]:
        d = self.root / "models" / asset
        out = []
        if d.exists():
            for m in sorted(d.iterdir()):
                f = m / "manifest.json"
                if f.exists() and not m.name.endswith(".tmp"):
                    man = json.loads(f.read_text(encoding="utf-8"))
                    out.append({**{k: man.get(k) for k in ("model_id", "asset", "family", "horizon", "role", "verdict", "data_source", "trained_at",
                                                            "cutoff", "protocol_id", "instrument_id")},
                                "curve": (man.get("params") or {}).get("curve"), "metrics": man.get("metrics"), "path": m.name})
        return sorted(out, key=lambda x: x.get("trained_at") or "", reverse=True)
