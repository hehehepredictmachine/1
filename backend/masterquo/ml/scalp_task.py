"""SCALP_NET_PROFIT_MARKET_V1 (family SCALP_MARKET) - PMW-UPD-03.

Sample = one scalp candidate (ScalpMachine plan that passed the strategy gates and had an executable MARKET fill in the replay of
the instrument profile), one side, decision at the signal bar close. Targets of the SAME full cycle (partial TP1/TP2, BE, time
exit, Bid/Ask, commission, slippage - scalp/replay.py is the label policy):
  y_profit = 1 if net_R > 0 else 0 (exactly 0 -> 0)       net_R regression (conditional mean, reg:squarederror)
Separate classifier + regressor per (instrument, profile_hash, side). XGBoost CPU hist, 6 configs (depth 2/3/4 x lambda 5/10),
early stopping on TUNE, Platt on CALIBRATION, policy p_min x ev_min (9) on POLICY, then ONE evaluation of the frozen bundle on
the holdout (last 20 % of calendar time) reserved in the shared evaluation ledger before it is read.

Development: 4 expanding walk-forward outer folds (each training span split FIT 60 / TUNE 15 / CALIBRATION 15 / POLICY 10, the
next span = evaluation). Purge by label end (+ embargo = max hold), groups of the same range never straddle a boundary.
Baselines: prior, logistic regression, small decision tree; regression: train mean, Ridge. Criteria fixed below (CRITERIA).
Nothing here promotes a model or sends orders; SHADOW_GATE is a hypothetical, displayed policy.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

TASK_ID = "SCALP_NET_PROFIT_MARKET_V1"
FAMILY = "SCALP_MARKET"
CONFIGS = [{"max_depth": d, "reg_lambda": lam} for d in (2, 3, 4) for lam in (5.0, 10.0)]
XGB_FIXED = {"learning_rate": 0.03, "n_estimators": 800, "subsample": 0.8, "colsample_bytree": 0.8, "reg_alpha": 0.1, "min_child_weight": 20,
             "tree_method": "hist", "device": "cpu", "n_jobs": 2, "random_state": 42}
EARLY_STOP = 40
POLICY_GRID = [(p, e) for p in (0.50, 0.55, 0.60) for e in (0.00, 0.05, 0.10)]
CRITERIA = {"min_train_per_side": 1000, "min_cal": 200, "min_cal_per_class": 30, "min_eval": 200, "fold_share_logloss_gain": 0.75,
            "min_mean_logloss_gain": 0.002, "max_ece": 0.10, "min_policy_cycles": 100, "min_policy_days": 30, "stress_spread_mult": 1.5,
            "stress_extra_ticks": 1}


def root(inst: str) -> Path:
    import mq_instruments
    d = mq_instruments.data_dir() / "ml_scalp" / inst
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ts(s: str) -> float:
    return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()


# ------------------------------------------------------------------ dataset (replay of the export, all candidates)
def build_dataset(inst: str, ds: Path, commission: float | None = None, log=print) -> dict:
    from ..extind.trainer import _bars
    from ..scalp import replay, strategy as st
    meta = json.loads((ds / "source_metadata.json").read_text(encoding="utf-8"))
    if meta.get("instrument", "XAUUSD") != inst:
        raise ValueError(f"INSTRUMENT_MISMATCH:{meta.get('instrument')}!={inst}")
    prefix = meta.get("file_prefix") or "XAUUSD"
    point = float(meta["spec"].get("point") or meta["tick_size"])
    tick = float(meta["tick_size"])
    com = commission if commission is not None else (meta.get("costs") or {}).get("commission_per_lot_side")
    com_src = "ARGUMENT" if commission is not None else (meta.get("costs") or {}).get("source")
    if com is None and inst == "XAUUSD":
        from ..config import ConfigStore
        com, com_src = ConfigStore().get().scalp.commission_per_lot_side, "BOT_CONFIG_XAUUSD"
    if com is None:
        raise ValueError("COSTS_UNKNOWN")
    m1 = [dict(b, spread_price=(b["spread"] * point if b["spread"] is not None else None)) for b in _bars(ds, prefix, "M1")]
    if not m1:
        raise ValueError("NO_DATA_M1")
    prof = st.load_profile(instrument=inst)
    if st.V(prof, "entry", "mode", default="MARKET") != "MARKET":
        raise ValueError("UNSUPPORTED_ENTRY_POLICY")
    costs = {"commission_price_side": com / float(meta["spec"]["trade_contract_size"]), "slippage_price": 2.0 * tick}
    t0 = time.time()
    res = replay.run(m1, prof, tick, costs)
    log(f"replay {inst}: {len(res['cycles'])} cykli, {len(res['blocked'])} odrzuconych ({time.time() - t0:.0f}s)")
    rows = [{"setup_id": c["setup_id"], "range_id": c.get("range_id"), "side": c["direction"], "signal_time": c["signal_time"],
             "fill_time": c["fill_time"], "label_end": c["exits"][-1]["time"], "x": c.get("net_features") or {}, "net_r": float(c["net_r"]),
             "y": 1 if c["net_r"] > 0 else 0, "spread": c["spread"], "risk": c["risk_price"], "net_price": c["net_price"], "ambiguous": bool(c["ambiguous"]),
             "first_exit": c["exits"][0]["reason"] if c["exits"] else None, "setup_features": c.get("features") or {}}
            for c in res["cycles"]]
    phash = st.profile_hash(prof)
    return {"instrument": inst, "symbol": meta["symbol"], "dataset_id": meta.get("dataset_id"), "data_kind": meta.get("data_kind"), "rows": rows,
            "blocked": len(res["blocked"]), "profile_id": prof["profile_id"], "profile_hash": phash, "tick": tick,
            "costs": {"commission_per_lot_side": com, "commission_source": com_src, **costs}, "m1": m1, "prof": prof, "replay_costs": costs,
            "precision": "OHLC_APPROX"}


def matrix(rows: list[dict]) -> np.ndarray:
    from ..scalp.strategy import NET_FEATURES
    return np.array([[float(r["x"].get(k, float("nan"))) for k in NET_FEATURES] for r in rows], dtype=float).reshape(len(rows), len(NET_FEATURES))


# ------------------------------------------------------------------ splitting
def _purged(idx: np.ndarray, rows: list[dict], boundary_t: float, embargo_s: float) -> np.ndarray:
    return np.array([i for i in idx if _ts(rows[i]["label_end"]) < boundary_t - embargo_s], dtype=int)


def inner_blocks(idx: np.ndarray, rows: list[dict], embargo_s: float) -> dict:
    """Chronological FIT 60 / TUNE 15 / CALIBRATION 15 / POLICY 10 with purge at each boundary; ranges never straddle."""
    idx = np.array(sorted(idx, key=lambda i: _ts(rows[i]["signal_time"])), dtype=int)
    n = len(idx)
    cuts = [int(n * f) for f in (0.60, 0.75, 0.90)] + [n]
    out, start = {}, 0
    for name, cut in zip(("FIT", "TUNE", "CALIBRATION", "POLICY"), cuts):
        blk = idx[start:cut]
        if cut < n:
            nxt_t = _ts(rows[idx[cut]]["signal_time"])
            nxt_range = rows[idx[cut]].get("range_id")
            blk = _purged(blk, rows, nxt_t, embargo_s)
            blk = np.array([i for i in blk if rows[i].get("range_id") != nxt_range or rows[i].get("range_id") is None], dtype=int)
        out[name] = blk
        start = cut
    return out


def outer_folds(dev: np.ndarray, rows: list[dict], k: int = 4) -> list[tuple[np.ndarray, np.ndarray]]:
    dev = np.array(sorted(dev, key=lambda i: _ts(rows[i]["signal_time"])), dtype=int)
    seg = np.array_split(dev, k + 1)
    return [(np.concatenate(seg[:j + 1]), seg[j + 1]) for j in range(k) if len(seg[j + 1])]


# ------------------------------------------------------------------ models
def _ll(y, p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))) if len(y) else float("nan")


def _ece(y, p, bins=10):
    e = 0.0
    for b in range(bins):
        m = (p >= b / bins) & ((p < (b + 1) / bins) if b < bins - 1 else (p <= 1))
        if m.any():
            e += m.mean() * abs(y[m].mean() - p[m].mean())
    return float(e)


def _platt(raw_margin: np.ndarray, y: np.ndarray) -> dict:
    from sklearn.linear_model import LogisticRegression
    if len(set(y.tolist())) < 2:
        return {"a": 1.0, "b": 0.0, "status": "CALIBRATION_UNVERIFIED"}
    m = LogisticRegression(C=1e6, max_iter=1000).fit(raw_margin.reshape(-1, 1), y)
    return {"a": float(m.coef_[0][0]), "b": float(m.intercept_[0]), "status": "FITTED_ON_CALIBRATION"}


def _cal(margin: np.ndarray, c: dict) -> np.ndarray:
    return 1 / (1 + np.exp(-(c["a"] * margin + c["b"])))


def fit_pair(X, y, r, blocks: dict) -> dict:
    """Choose the XGB config on FIT/TUNE (early stopping on TUNE), refit FIT+TUNE with the fixed number of trees, Platt on
    CALIBRATION, policy (p_min, ev_min) on POLICY. Returns the frozen pair + its training report."""
    import xgboost as xgb
    f, t, c, p = (blocks[k] for k in ("FIT", "TUNE", "CALIBRATION", "POLICY"))
    trials = []
    best = None
    for cfg in CONFIGS:
        clf = xgb.XGBClassifier(objective="binary:logistic", eval_metric="logloss", early_stopping_rounds=EARLY_STOP, **XGB_FIXED, **cfg)
        clf.fit(X[f], y[f], eval_set=[(X[t], y[t])], verbose=False)
        it = int(clf.best_iteration)
        ll = _ll(y[t], clf.predict_proba(X[t], iteration_range=(0, it + 1))[:, 1])
        trials.append({**cfg, "best_iteration": it, "tune_log_loss": ll})
        if best is None or ll < best[0]:
            best = (ll, cfg, it)
    _, cfg, it = best
    ft = np.concatenate([f, t])
    clf = xgb.XGBClassifier(objective="binary:logistic", eval_metric="logloss", **{**XGB_FIXED, "n_estimators": it + 1}, **cfg).fit(X[ft], y[ft])
    reg_probe = xgb.XGBRegressor(objective="reg:squarederror", early_stopping_rounds=EARLY_STOP, **XGB_FIXED, **cfg)
    reg_probe.fit(X[f], r[f], eval_set=[(X[t], r[t])], verbose=False)
    rit = int(reg_probe.best_iteration)
    reg = xgb.XGBRegressor(objective="reg:squarederror", **{**XGB_FIXED, "n_estimators": rit + 1}, **cfg).fit(X[ft], r[ft])
    cal = _platt(clf.predict(X[c], output_margin=True), y[c])
    pp, ev = _cal(clf.predict(X[p], output_margin=True), cal), reg.predict(X[p])
    pol_trials, chosen = [], None
    for pm, em in POLICY_GRID:
        sel = (pp >= pm) & (ev >= em)
        tot = float(r[p][sel].sum()) if sel.any() else 0.0
        pol_trials.append({"p_min": pm, "ev_min": em, "selected": int(sel.sum()), "net_r_total": tot})
        if sel.sum() >= max(5, int(0.1 * len(p))) and (chosen is None or tot > chosen["net_r_total"]):
            chosen = pol_trials[-1]
    return {"clf": clf, "reg": reg, "cfg": cfg, "n_trees_clf": it + 1, "n_trees_reg": rit + 1, "calibrator": cal, "trials": trials,
            "policy_trials": pol_trials, "policy": {"p_min": chosen["p_min"], "ev_min": chosen["ev_min"]} if chosen else None,
            "sizes": {k: int(len(v)) for k, v in blocks.items()}}


def baselines(X, y, r, fit_idx, eval_idx) -> dict:
    from sklearn.linear_model import LogisticRegression, Ridge
    from sklearn.tree import DecisionTreeClassifier
    med = np.nanmedian(np.where(np.isfinite(X[fit_idx]), X[fit_idx], np.nan), axis=0)
    med = np.where(np.isfinite(med), med, 0.0)
    imp = lambda A: np.where(np.isfinite(A), A, med)          # noqa: E731 - train-only imputation for linear / tree baselines
    mu, sd = imp(X[fit_idx]).mean(0), imp(X[fit_idx]).std(0) + 1e-9
    Z = lambda A: (imp(A) - mu) / sd                          # noqa: E731
    out = {"prior": _ll(y[eval_idx], np.full(len(eval_idx), y[fit_idx].mean()))}
    if len(set(y[fit_idx].tolist())) == 2:
        out["logreg"] = _ll(y[eval_idx], LogisticRegression(C=0.5, max_iter=2000).fit(Z(X[fit_idx]), y[fit_idx]).predict_proba(Z(X[eval_idx]))[:, 1])
        out["small_tree"] = _ll(y[eval_idx], DecisionTreeClassifier(max_depth=3, min_samples_leaf=30, random_state=42)
                                .fit(imp(X[fit_idx]), y[fit_idx]).predict_proba(imp(X[eval_idx]))[:, 1])
    out["reg_mean_rmse"] = float(np.sqrt(np.mean((r[eval_idx] - r[fit_idx].mean()) ** 2))) if len(eval_idx) else None
    out["ridge_rmse"] = float(np.sqrt(np.mean((r[eval_idx] - Ridge(alpha=10).fit(Z(X[fit_idx]), r[fit_idx]).predict(Z(X[eval_idx]))) ** 2))) if len(eval_idx) else None
    return out


def _day_boot(days: np.ndarray, x: np.ndarray, reps=2000, seed=7) -> dict:
    u = sorted(set(days.tolist()))
    if len(u) < 5:
        return {"status": "INSUFFICIENT_DAYS", "days": len(u)}
    per = np.array([x[days == d].sum() for d in u])
    rng = np.random.default_rng(seed)
    sims = [float(rng.choice(per, size=len(per), replace=True).mean()) for _ in range(reps)]
    return {"mean_per_day": float(per.mean()), "ci95": [float(np.percentile(sims, 2.5)), float(np.percentile(sims, 97.5))], "days": len(u)}


# ------------------------------------------------------------------ evaluation ledger (shared across tasks / sessions)
def reserve_holdout(db, inst: str, start: str, end: str, artifact_hash: str, task_id: str = TASK_ID) -> dict:
    """Transactional reservation BEFORE the holdout labels are read. An overlapping, already used period of the same market
    (any task / family / name) returns REUSED_PERIOD_EXPLORATORY."""
    prev = db.query("SELECT * FROM eval_ledger WHERE instrument=? AND NOT (period_end <= ? OR period_start >= ?)", (inst, start, end))
    status = "REUSED_PERIOD_EXPLORATORY" if prev else "FRESH"
    db.execute("INSERT INTO eval_ledger(at, instrument, task_id, period_start, period_end, artifact_hash, status) VALUES (?,?,?,?,?,?,?)",
               (datetime.now(timezone.utc).isoformat(), inst, task_id, start, end, artifact_hash, status))
    return {"status": status, "previous": [dict(x) for x in prev][:5]}


# ------------------------------------------------------------------ the run
def train(inst: str, ds: Path, *, commission: float | None = None, db=None, log=print) -> dict:
    data = build_dataset(inst, ds, commission, log)
    synthetic = data["data_kind"] != "REAL_USER_DATA"
    rows = data["rows"]
    rid = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "_" + uuid.uuid4().hex[:4] + ("_FIXTURE" if synthetic else "")
    rd = root(inst) / ("fixture_runs" if synthetic else "runs") / rid
    rd.mkdir(parents=True, exist_ok=True)
    hold_min = data["prof"]["exits"]["max_hold_minutes"]["value"]
    embargo = 60.0 * hold_min
    rep = {"run_id": rid, "task_id": TASK_ID, "family": FAMILY, "instrument": inst, "symbol": data["symbol"], "dataset_id": data["dataset_id"],
           "data_kind": data["data_kind"], "profile_id": data["profile_id"], "profile_hash": data["profile_hash"], "costs": data["costs"],
           "precision": data["precision"], "candidates": len(rows), "criteria": CRITERIA, "embargo_s": embargo,
           "role": "FIXTURE_ONLY" if synthetic else "RESEARCH", "sides": {}, "created_at": datetime.now(timezone.utc).isoformat(),
           "label": "y=1 gdy pełny cykl netto net_R>0 (replay scalp: TP1/TP2/BE/czas, Bid/Ask, prowizja, poślizg); net_R regresja"}
    if not rows:
        rep["status"] = "INSUFFICIENT_EVIDENCE"
        rep["reason"] = "brak kandydatów z wykonalnym wejściem MARKET w replayu"
        _write(rd, rep)
        return _register(inst, rid, rd, rep)
    t_all = np.array([_ts(r["signal_time"]) for r in rows])
    cut = t_all.min() + 0.8 * (t_all.max() - t_all.min())
    X, y, r = matrix(rows), np.array([x["y"] for x in rows]), np.array([x["net_r"] for x in rows])
    for side in ("BUY", "SELL"):
        sidx = np.array([i for i, x in enumerate(rows) if x["side"] == side], dtype=int)
        dev = _purged(np.array([i for i in sidx if t_all[i] < cut], dtype=int), rows, cut, embargo)
        hold = np.array([i for i in sidx if t_all[i] >= cut], dtype=int)
        sr = {"candidates": int(len(sidx)), "development": int(len(dev)), "holdout": int(len(hold))}
        rep["sides"][side] = sr
        if len(dev) < (CRITERIA["min_train_per_side"] if not synthetic else 60) or len(set(y[dev].tolist())) < 2:
            sr.update(status="INSUFFICIENT_EVIDENCE", reason=f"rozwój {len(dev)} < {CRITERIA['min_train_per_side']} kandydatów strony {side}")
            continue
        folds = []
        for tr, ev in outer_folds(dev, rows):
            b = inner_blocks(tr, rows, embargo)
            if min(len(v) for v in b.values()) < 5 or len(set(y[b["FIT"]].tolist())) < 2:
                folds.append({"status": "INSUFFICIENT_EVIDENCE", "sizes": {k: int(len(v)) for k, v in b.items()}})
                continue
            fp = fit_pair(X, y, r, b)
            pe = _cal(fp["clf"].predict(X[ev], output_margin=True), fp["calibrator"])
            base = baselines(X, y, r, np.concatenate([b["FIT"], b["TUNE"]]), ev)
            folds.append({"status": "OK", "sizes": fp["sizes"], "eval_n": int(len(ev)), "log_loss": _ll(y[ev], pe), "ece": _ece(y[ev], pe),
                          "brier": float(np.mean((pe - y[ev]) ** 2)), "baselines": base, "cfg": fp["cfg"],
                          "reg_rmse": float(np.sqrt(np.mean((fp["reg"].predict(X[ev]) - r[ev]) ** 2))), "policy": fp["policy"]})
        ok = [f for f in folds if f["status"] == "OK"]
        gains = [f["baselines"]["prior"] - f["log_loss"] for f in ok]
        sr["folds"] = folds
        sr["development_criteria"] = {
            "fold_share_logloss_gain": float(np.mean([g >= CRITERIA["min_mean_logloss_gain"] for g in gains])) if gains else 0.0,
            "mean_logloss_gain": float(np.mean(gains)) if gains else None,
            "mean_ece": float(np.mean([f["ece"] for f in ok])) if ok else None,
            "regressor_beats_mean": bool(ok) and all(f["reg_rmse"] <= (f["baselines"].get("reg_mean_rmse") or 1e9) for f in ok)}
        # final pair on the whole development with the same chronological scheme, frozen + hashed BEFORE the holdout
        b = inner_blocks(dev, rows, embargo)
        if min(len(v) for v in b.values()) < 5 or len(set(y[b["FIT"]].tolist())) < 2:
            sr.update(status="INSUFFICIENT_EVIDENCE", reason="za mało próbek w blokach finalnego modelu")
            continue
        fp = fit_pair(X, y, r, b)
        bdir = rd / f"bundle_{side}"
        mhash = save_bundle(bdir, fp, rep, side, data)
        sr["model_hash"] = mhash
        sr["policy"] = fp["policy"]
        sr["calibration"] = fp["calibrator"]["status"]
        # one evaluation of the frozen bundle
        if len(hold) == 0:
            sr.update(status="INSUFFICIENT_EVIDENCE", reason="pusty holdout")
            continue
        h0, h1 = min(rows[i]["signal_time"] for i in hold), max(rows[i]["label_end"] for i in hold)
        led = reserve_holdout(db, inst, h0, h1, mhash) if db is not None else {"status": "LEDGER_UNAVAILABLE"}
        bl = load_bundle(bdir)
        out = bl.predict_matrix(X[hold])
        ph, evh = out["p"], out["ev"]
        days = np.array([rows[i]["signal_time"][:10] for i in hold])
        sel = (ph >= fp["policy"]["p_min"]) & (evh >= fp["policy"]["ev_min"]) if fp["policy"] else np.zeros(len(hold), bool)
        stress = np.array([(rows[i]["net_price"] - (CRITERIA["stress_spread_mult"] - 1) * (rows[i]["spread"] or 0) - 2 * CRITERIA["stress_extra_ticks"] * data["tick"])
                           / rows[i]["risk"] for i in hold])
        hb = {"ledger": led, "n": int(len(hold)), "days": int(len(set(days.tolist()))), "log_loss": _ll(y[hold], ph), "ece": _ece(y[hold], ph),
              "brier": float(np.mean((ph - y[hold]) ** 2)), "prior_log_loss": _ll(y[hold], np.full(len(hold), y[dev].mean())),
              "reg_rmse": float(np.sqrt(np.mean((evh - r[hold]) ** 2))), "reg_bias": float(np.mean(evh - r[hold])),
              "policy_selected": int(sel.sum()), "policy_days": int(len(set(days[sel].tolist()))),
              "policy_net_r_mean": float(r[hold][sel].mean()) if sel.any() else None, "baseline_net_r_mean": float(r[hold].mean()),
              "policy_boot": _day_boot(days[sel], r[hold][sel]) if sel.any() else {"status": "NO_SELECTED"},
              "incremental_boot": _day_boot(days, np.where(sel, r[hold], 0.0) - r[hold]),
              "stress_net_r_mean": float(stress[sel].mean()) if sel.any() else None,
              "note": "porównanie na cyklach baseline; pełny replay polityki (zwolnione sloty) – policy_replay w raporcie, gdy dostępny"}
        if fp["policy"]:
            hb["policy_replay"] = policy_replay(data, side, cut, bl)
        dc = sr["development_criteria"]

        passed = (dc["fold_share_logloss_gain"] >= CRITERIA["fold_share_logloss_gain"] and (dc["mean_logloss_gain"] or 0) >= CRITERIA["min_mean_logloss_gain"]
                  and (dc["mean_ece"] or 1) <= CRITERIA["max_ece"] and dc["regressor_beats_mean"] and fp["calibrator"]["status"] == "FITTED_ON_CALIBRATION"
                  and hb["policy_selected"] >= CRITERIA["min_policy_cycles"] and hb["policy_days"] >= CRITERIA["min_policy_days"]
                  and (hb["policy_boot"].get("ci95") or [-1])[0] > 0 and (hb["incremental_boot"].get("ci95") or [-1])[0] > 0
                  and (hb["stress_net_r_mean"] or -1) > 0)
        sr["holdout"] = hb
        sr["status"] = ("FIXTURE_ONLY" if synthetic else "INSUFFICIENT_EVIDENCE" if len(hold) < CRITERIA["min_eval"] else
                        "HOLDOUT_PASSED" if passed and led["status"] == "FRESH" else
                        "REUSED_PERIOD_EXPLORATORY" if passed else "NO_VALIDATED_EDGE")
    sts = [s.get("status") for s in rep["sides"].values()]
    rep["status"] = "EVALUATED" if any(s in ("HOLDOUT_PASSED", "NO_VALIDATED_EDGE", "REUSED_PERIOD_EXPLORATORY", "FIXTURE_ONLY") for s in sts) else "INSUFFICIENT_EVIDENCE"
    _write(rd, rep)
    return _register(inst, rid, rd, rep)


def policy_replay(data: dict, side: str, cut: float, bundle: ScalpBundle) -> dict:
    """Full chronological replay with the frozen policy as a decision filter (rejected candidates do not occupy the one-cycle /
    cooldown slot, so later candidates may be taken) vs the baseline strategy, holdout part, this side only."""
    from ..scalp import replay

    def accept(plan):
        if plan["direction"] != side or _ts(plan["decision_time"]) < cut:
            return True
        o = bundle.predict(plan.get("net_features") or {}, instrument=data["instrument"], profile_hash=data["profile_hash"], side=side)
        return bool(o.get("proposed_filter"))
    res = replay.run(data["m1"], data["prof"], data["tick"], data["replay_costs"], accept=accept)
    ml = [c for c in res["cycles"] if c["direction"] == side and _ts(c["decision_time"]) >= cut]
    base = [r for r in data["rows"] if r["side"] == side and _ts(r["signal_time"]) >= cut]
    days_ml = np.array([c["decision_time"][:10] for c in ml])
    return {"ml_cycles": len(ml), "ml_net_r_total": float(sum(c["net_r"] for c in ml)), "baseline_cycles": len(base),
            "baseline_net_r_total": float(sum(r["net_r"] for r in base)), "ml_boot": _day_boot(days_ml, np.array([c["net_r"] for c in ml])) if ml else {"status": "NO_CYCLES"},
            "rejected_by_policy": sum(1 for b in res["blocked"] if b.get("reason") == "ML_POLICY_REJECTED"),
            "note": "replay OHLC (bez ticków); kalendarz/stan konta historycznie nieodtworzone"}


def _write(rd: Path, rep: dict) -> None:
    tmp = rd / "report.json.tmp"
    tmp.write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, rd / "report.json")


def _register(inst: str, rid: str, rd: Path, rep: dict) -> dict:
    p = root(inst) / "registry.json"
    reg = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"schema": "pmw-ml-scalp-registry-1", "selected": {}, "history": [], "runs": {}}
    reg["runs"][rid] = {"run_dir": str(rd), "status": rep["status"], "role": rep["role"], "sides": {s: {k: v.get(k) for k in ("status", "model_hash")}
                                                                                                 for s, v in rep["sides"].items()}}
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(reg, indent=1), encoding="utf-8")
    os.replace(tmp, p)
    return rep


# ------------------------------------------------------------------ bundle
def save_bundle(d: Path, fp: dict, rep: dict, side: str, data: dict) -> str:
    """classifier.ubj, regressor.ubj (native XGBoost), preprocessor.json (feature order), calibrator.json, policy.json, manifest
    with the hash of every file; atomic (tmp dir + rename). Returns model_hash (hash of the file hashes)."""
    import shutil
    from ..scalp.strategy import NET_FEATURE_SCHEMA, NET_FEATURES
    tmp = d.with_name(d.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    fp["clf"].save_model(str(tmp / "classifier.ubj"))
    fp["reg"].save_model(str(tmp / "regressor.ubj"))
    (tmp / "preprocessor.json").write_text(json.dumps({"feature_schema": NET_FEATURE_SCHEMA, "features": list(NET_FEATURES), "missing": "NaN (native XGBoost)"}), encoding="utf-8")
    (tmp / "calibrator.json").write_text(json.dumps(fp["calibrator"]), encoding="utf-8")
    (tmp / "policy.json").write_text(json.dumps({"policy": fp["policy"], "trials": fp["policy_trials"]}), encoding="utf-8")
    files = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(tmp.iterdir())}
    mhash = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    import sklearn
    import xgboost
    man = {"task_id": TASK_ID, "family": FAMILY, "instrument": rep["instrument"], "symbol": rep["symbol"], "side": side, "profile_id": rep["profile_id"],
           "profile_hash": rep["profile_hash"], "entry_policy": "MARKET", "exit_policy": "scalp/replay.py (profil)", "feature_schema": NET_FEATURE_SCHEMA,
           "cfg": fp["cfg"], "n_trees": {"classifier": fp["n_trees_clf"], "regressor": fp["n_trees_reg"]}, "seed": 42, "trials": fp["trials"],
           "block_sizes": fp["sizes"], "costs": rep["costs"], "dataset_id": rep["dataset_id"], "data_kind": rep["data_kind"], "role": rep["role"],
           "files_sha256": files, "model_hash": mhash, "versions": {"xgboost": xgboost.__version__, "scikit-learn": sklearn.__version__}}
    (tmp / "manifest.json").write_text(json.dumps(man, indent=1, default=str), encoding="utf-8")
    if d.exists():
        shutil.rmtree(d)
    os.replace(tmp, d)
    return mhash


class ScalpBundle:
    def __init__(self, d: Path):
        import xgboost as xgb
        self.dir = d
        self.man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        for f, h in self.man["files_sha256"].items():
            if hashlib.sha256((d / f).read_bytes()).hexdigest() != h:
                raise ValueError(f"ARTIFACT_CHECKSUM_MISMATCH:{f}")
        self.features = json.loads((d / "preprocessor.json").read_text(encoding="utf-8"))["features"]
        self.cal = json.loads((d / "calibrator.json").read_text(encoding="utf-8"))
        self.policy = json.loads((d / "policy.json").read_text(encoding="utf-8"))["policy"]
        self.clf = xgb.XGBClassifier()
        self.clf.load_model(str(d / "classifier.ubj"))
        self.reg = xgb.XGBRegressor()
        self.reg.load_model(str(d / "regressor.ubj"))

    def predict_matrix(self, X: np.ndarray) -> dict:
        m = self.clf.predict(X, output_margin=True)
        return {"margin": m, "p": _cal(m, self.cal), "ev": self.reg.predict(X)}

    def predict(self, net_features: dict, *, instrument: str, profile_hash: str, side: str) -> dict:
        if (instrument, profile_hash, side) != (self.man["instrument"], self.man["profile_hash"], self.man["side"]):
            return {"status": "ABSTAIN", "reason": "MODEL_SCOPE_MISMATCH (instrument/profil/strona)"}
        if set(net_features) != set(self.features):
            return {"status": "ABSTAIN", "reason": "FEATURE_SCHEMA_MISMATCH"}
        X = np.array([[float(net_features[k]) for k in self.features]], dtype=float)
        o = self.predict_matrix(X)
        p, ev = float(o["p"][0]), float(o["ev"][0])
        pol = self.policy
        dec = None if pol is None else bool(p >= pol["p_min"] and ev >= pol["ev_min"])
        return {"status": "READY_INFERENCE", "task_id": TASK_ID, "model_hash": self.man["model_hash"], "raw_margin": float(o["margin"][0]),
                "calibrated_probability": p if self.cal.get("status") == "FITTED_ON_CALIBRATION" else None, "expected_net_r": ev,
                "calibration_status": self.cal.get("status"), "policy": pol, "proposed_filter": dec, "role": self.man["role"],
                "meaning": "P(dodatni wynik netto całego cyklu scalp) i estymata średniego net_R – nie P(wzrost ceny) ani P(TP1 przed SL)"}

    def explain(self, net_features: dict, top: int = 10) -> dict:
        """TreeSHAP (pred_contribs) of the classifier in raw-margin (log-odds) units; bias + sum == raw margin is checked."""
        import xgboost as xgb
        X = np.array([[float(net_features[k]) for k in self.features]], dtype=float)
        booster = self.clf.get_booster()
        contrib = booster.predict(xgb.DMatrix(X, feature_names=list(self.features)), pred_contribs=True)[0]
        margin = float(self.clf.predict(X, output_margin=True)[0])
        total = float(contrib.sum())
        pairs = sorted(zip(self.features, contrib[:-1].tolist(), X[0].tolist()), key=lambda x: -abs(x[1]))
        rest = float(sum(c for _, c, _ in pairs[top:]))
        return {"method": "TreeSHAP (xgboost pred_contribs)", "units": "raw margin (log-odds) klasyfikatora – nie procent", "bias": float(contrib[-1]),
                "top": [{"feature": n, "contribution": c, "value": None if math.isnan(v) else v} for n, c, v in pairs[:top]], "other_features": rest,
                "raw_margin": margin, "sum_check": abs(total - margin) < 1e-4, "model_hash": self.man["model_hash"]}


def load_bundle(d: Path) -> ScalpBundle:
    return ScalpBundle(d)


# ------------------------------------------------------------------ registry: scoped selection (no auto-promotion)
def select(inst: str, run_id: str, side: str, role: str) -> dict:
    if role not in ("OBSERVE", "SHADOW_GATE"):
        raise ValueError("ROLE_INVALID")
    p = root(inst) / "registry.json"
    reg = json.loads(p.read_text(encoding="utf-8"))
    e = reg["runs"].get(run_id)
    if not e or side not in e["sides"] or not e["sides"][side].get("model_hash"):
        raise ValueError("UNKNOWN_RUN_OR_SIDE")
    st = e["sides"][side]["status"]
    if e["role"] == "FIXTURE_ONLY" or st == "FIXTURE_ONLY":
        raise ValueError("FIXTURE_ONLY_NOT_SELECTABLE")
    if role == "SHADOW_GATE" and st != "HOLDOUT_PASSED":
        raise ValueError(f"SHADOW_GATE_REQUIRES_HOLDOUT_PASSED:{st}")
    load_bundle(Path(e["run_dir"]) / f"bundle_{side}")         # verifies every file hash before selection
    reg["history"].append({"side": side, "previous": reg["selected"].get(side), "at": datetime.now(timezone.utc).isoformat()})
    reg["selected"][side] = {"run_id": run_id, "role": role, "model_hash": e["sides"][side]["model_hash"]}
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(reg, indent=1), encoding="utf-8")
    os.replace(tmp, p)
    return reg["selected"]


def rollback(inst: str, side: str) -> dict:
    p = root(inst) / "registry.json"
    reg = json.loads(p.read_text(encoding="utf-8"))
    prev = [h for h in reg["history"] if h["side"] == side]
    if not prev:
        raise ValueError("NO_PREVIOUS_SELECTION")
    h = prev[-1]
    reg["history"].remove(h)
    if h["previous"]:
        reg["selected"][side] = h["previous"]
    else:
        reg["selected"].pop(side, None)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(reg, indent=1), encoding="utf-8")
    os.replace(tmp, p)
    return reg["selected"]


_cache: dict = {}


def selected_bundle(inst: str, side: str) -> tuple[ScalpBundle | None, dict | None]:
    p = root(inst) / "registry.json"
    try:
        st = p.stat().st_mtime
        reg = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, None
    sel = reg.get("selected", {}).get(side)
    if not sel:
        return None, None
    key = (inst, side, sel["model_hash"], st)
    if key not in _cache:
        _cache.clear()
        _cache[key] = load_bundle(Path(reg["runs"][sel["run_id"]]["run_dir"]) / f"bundle_{side}")
    return _cache[key], sel
