"""Dataset, SAR calibration, reaction models and inference of SCALP_INDICATOR_CONTEXT_V2 (task SCALP_TP1_FIRST_WITHIN_FROZEN_POLICY_V1).

Sample = every qualified cycle of the existing scalp replay (frozen exit policy of the instrument profile) with its decision
time, side and levels; y = 1 when the policy settled TP1 before SL (timeout / ambiguous -> 0 as in the replay). net_R is
kept beside y - P(TP1 first) is NOT P(net_R > 0). External groups are joined as-of their backend availability (archive).

Protocol (frozen before fitting, written to plan.json): chronological blocks FIT 45% / TUNE 15% / CALIBRATION 10% /
POLICY 10% / HOLDOUT 20% with purge (a cycle whose exit is not before the next block start minus the embargo is dropped)
and a 30-minute embargo. Imputation + scaling + model on FIT, model/params choice on TUNE (incl. the SAR grid, every trial
recorded), Platt calibration on CALIBRATION, the usage threshold on POLICY, one evaluation on HOLDOUT. Variants BASE,
BASE+SAR, BASE+IQ_GOLD_GANN, BASE+IQ_STAR_LINES, BASE+PAL02M (blocked) on the same rows; paired day-block bootstrap of the
log-loss difference vs BASE. New models are SHADOW; nothing is promoted or executed.

1.46 arch: the composer gets exactly the live inputs (price = plan ref_close_bid, atr_m5 = plan range.atr_m5, both written by the
replay into the cycle - I0164/I0784); a variant with extra groups is fitted, calibrated, tuned and evaluated ONLY on the rows live
inference can score (every non-BASE group OK - I0168); the artefact records its numpy / scikit-learn versions and a load in another
environment, or an unpicklable file, is a clear ValueError instead of a silent different model (I0170).
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import pickle
import platform
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from ..timeutil import parse_iso
from . import features as F

BLOCKS = (("FIT", 0.45), ("TUNE", 0.15), ("CALIBRATION", 0.10), ("POLICY", 0.10), ("HOLDOUT", 0.20))
EMBARGO_S = 1800
SAR_GRID = [(s, m) for s in (0.01, 0.02, 0.03) for m in (0.1, 0.2, 0.3) if s <= m]
MIN_CYCLES = 150
MIN_HOLDOUT = 20
VARIANTS = (("BASE",), ("BASE", "SAR"), ("BASE", "IQ_GOLD_GANN"), ("BASE", "IQ_STAR_LINES"), ("BASE", "PAL02M"))
PREP_VERSION = 1                                   # layout of the pickled Prep (median + missing flag + z-score); bump on a refactor
ENV_PACKAGES = ("numpy", "scikit-learn")           # pickled objects: major.minor of these must match at load time


_REG_LOCK = threading.Lock()


def root(inst: str) -> Path:
    import mq_instruments
    # 1.46: the asset comes from API bodies (activate / rollback) - '../forecast' rewrote another registry and any value created
    # directories outside the data folder; only a profiled instrument names a folder
    if not isinstance(inst, str) or inst not in mq_instruments.profiles():
        raise ValueError(f"UNKNOWN_INSTRUMENT:{inst}")
    d = mq_instruments.data_dir() / "indicator_context" / inst
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_registry(reg_p: Path, reg: dict) -> None:
    # 1.46: one fixed 'registry.tmp' was shared by every writer (train process, API activate / rollback) - a concurrent writer or a
    # leftover broke the replace; each write has its own temporary file
    tmp = reg_p.with_name(f"{reg_p.stem}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        tmp.write_text(json.dumps(reg, indent=1), encoding="utf-8")
        tmp.replace(reg_p)
    finally:
        tmp.unlink(missing_ok=True)


# ------------------------------------------------------------------ dataset
def _bars(ds: Path, prefix: str, tf: str) -> list[dict]:
    p = ds / f"{prefix}_{tf}.csv"
    if not p.exists():
        return []
    out = []
    with p.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            out.append({"open_utc": r["time_open_utc"], "o": float(r["open"]), "h": float(r["high"]), "l": float(r["low"]), "c": float(r["close"]),
                        "tv": float(r["tick_volume"] or 0), "spread": float(r["spread_points"]) if r.get("spread_points") not in (None, "") else None})
    return out


def build_dataset(inst: str, ds: Path, commission: float | None = None, db=None, log=print) -> dict:
    """Replay of the instrument scalp profile on the export + composer rows for EVERY cycle (no winners-only selection)."""
    from ..scalp import replay, strategy as st
    from .service import ExtIndService
    meta = json.loads((ds / "source_metadata.json").read_text(encoding="utf-8"))
    if meta.get("instrument", "XAUUSD") != inst:
        raise ValueError(f"INSTRUMENT_MISMATCH:{meta.get('instrument')}!={inst}")
    prefix = meta.get("file_prefix") or "XAUUSD"
    point = float(meta["spec"].get("point") or meta["tick_size"])
    m1 = _bars(ds, prefix, "M1")
    if not m1:
        raise ValueError("DATASET_WITHOUT_M1")
    bars = {tf: _bars(ds, prefix, tf) for tf in ("M5", "M15")}
    com = commission if commission is not None else (meta.get("costs") or {}).get("commission_per_lot_side")
    if com is None and inst == "XAUUSD":
        from ..config import ConfigStore
        com = ConfigStore().get().scalp.commission_per_lot_side
    if com is None:
        raise ValueError("COMMISSION_UNKNOWN")
    cs = float(meta["spec"]["trade_contract_size"])
    tick = float(meta["tick_size"])
    costs = {"commission_price_side": com / cs, "slippage_price": 2.0 * tick}
    prof = st.load_profile(instrument=inst)
    rb = [dict(b, spread_price=(b["spread"] * point if b["spread"] is not None else None)) for b in m1]
    t0 = time.time()
    res = replay.run(rb, prof, tick, costs)
    log(f"replay {inst}: {len(res['cycles'])} cykli ({time.time() - t0:.0f}s)")
    ext = ExtIndService(None, db) if db is not None else None
    rows = []
    legacy = {"price": 0, "atr": 0}
    for c in res["cycles"]:
        t = parse_iso(c["decision_time"])
        price, atr = decision_inputs(c, bars, t, legacy)
        rows.append({"setup_id": c["setup_id"], "range_id": c.get("range_id"), "side": c["direction"], "decision_time": c["decision_time"],
                     "fill_time": c["fill_time"], "exit_time": c["exits"][-1]["time"], "price": price, "atr_m5": atr, "base": c.get("features") or {},
                     "y": 1 if c["tp1_before_sl"] else 0, "net_r": c["net_r"], "ambiguous": bool(c.get("ambiguous")),
                     "ext": {a: (ext.as_of(a, inst, t) if ext else None) for a in ("IQ_GOLD_GANN", "IQ_STAR_LINES")}})
    if legacy["price"] or legacy["atr"]:
        log(f"UWAGA: {legacy['price']} cykli bez ref_close_bid i {legacy['atr']} bez range_atr_m5 (stary rekord replay) – wejścia zastępcze, liczone w raporcie")
    return {"instrument": inst, "symbol": meta["symbol"], "dataset_id": meta.get("dataset_id"), "data_kind": meta.get("data_kind"),
            "rows": rows, "bars": bars, "costs": {"commission_per_lot_side": com, **costs}, "profile_id": prof["profile_id"],
            "files_sha256": meta.get("files_sha256"), "legacy_price_rows": legacy["price"], "legacy_atr_rows": legacy["atr"]}


def decision_inputs(c: dict, bars: dict, t: datetime, legacy: dict | None = None) -> tuple[float, float | None]:
    """(price, atr_m5) of one replay cycle exactly as live inference passes them (scalp/service.indicator_context): the Bid close of
    the retest bar (plan ref_close_bid) and the range ATR frozen at arming (plan range.atr_m5). 1.46 arch (I0164/I0784): training used
    the replay FILL (next open + spread + slippage for BUY) and an ATR14 of the 40 M5 closed at the decision - other inputs than live.
    A cycle record without the fields (older replay) falls back to the old values and is COUNTED in `legacy` (never mixed silently)."""
    if c.get("ref_close_bid") is not None:
        price = float(c["ref_close_bid"])
    else:
        price = float(c["fill"])
        if legacy is not None:
            legacy["price"] += 1
    if c.get("range_atr_m5") is not None:
        return price, float(c["range_atr_m5"])
    if legacy is not None:
        legacy["atr"] += 1
    b5 = [b for b in bars.get("M5") or [] if parse_iso(b["open_utc"]) <= t - timedelta(minutes=5)][-40:]
    return price, (ind_atr(b5) if len(b5) >= 15 else None)


def ind_atr(b: list[dict], n: int = 14) -> float | None:
    from ..scalp.indicators import atr
    a = atr([x["h"] for x in b], [x["l"] for x in b], [x["c"] for x in b], n)
    return a[-1]


def matrix(data: dict, spec: dict) -> tuple[np.ndarray, list[dict]]:
    X, info = [], []
    for r in data["rows"]:
        f = F.build_indicator_context_features({"decision_time": parse_iso(r["decision_time"]), "side": r["side"], "price": r["price"],
                                                 "atr_m5": r["atr_m5"], "base": r["base"], "bars": data["bars"], "ext": r["ext"]}, spec)
        X.append(list(f["features"].values()))
        info.append(f["groups"])
    return np.asarray(X, dtype=float).reshape(len(X), len(F.feature_names(spec))), info


# ------------------------------------------------------------------ protocol
def split(rows: list[dict]) -> dict[str, np.ndarray]:
    t = np.array([parse_iso(r["decision_time"]).timestamp() for r in rows])
    e = np.array([parse_iso(r["exit_time"]).timestamp() for r in rows])
    order = np.argsort(t, kind="stable")
    n = len(rows)
    bounds, acc = [], 0.0
    for _, f in BLOCKS:
        acc += f
        bounds.append(min(n, int(round(acc * n))))
    out, start = {}, 0
    for k, (name, _) in enumerate(BLOCKS):
        idx = order[start:bounds[k]]
        if k < len(BLOCKS) - 1 and bounds[k] < n:
            nxt = t[order[bounds[k]]]
            idx = idx[e[idx] < nxt - EMBARGO_S]                    # purge: label must close before the next block (+embargo)
        out[name] = idx
        start = bounds[k]
    return out


class Prep:
    def fit(self, X: np.ndarray):
        self.med = np.nanmedian(np.where(np.isfinite(X), X, np.nan), axis=0)
        self.med = np.where(np.isfinite(self.med), self.med, 0.0)
        Z = self._imp(X)
        self.mu, self.sd = Z.mean(axis=0), Z.std(axis=0)
        self.sd[self.sd < 1e-12] = 1.0
        return self

    def _imp(self, X):
        miss = ~np.isfinite(X)
        Z = np.where(miss, self.med, X)
        return np.hstack([Z, miss.astype(float)])

    def transform(self, X):
        return (self._imp(X) - self.mu) / self.sd


def _ll(y, p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def _ece(y, p, bins=8):
    e = 0.0
    for b in range(bins):
        m = (p >= b / bins) & (p < (b + 1) / bins if b < bins - 1 else p <= 1)
        if m.any():
            e += m.mean() * abs(y[m].mean() - p[m].mean())
    return float(e)


def _fit_model(kind, Z, y, seed=7):
    if kind == "LR":
        from sklearn.linear_model import LogisticRegression
        return LogisticRegression(C=0.5, max_iter=2000).fit(Z, y)
    from sklearn.ensemble import HistGradientBoostingClassifier
    return HistGradientBoostingClassifier(max_iter=120, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=20, l2_regularization=1.0,
                                          early_stopping=False, random_state=seed).fit(Z, y)


def _platt(raw, y):
    from sklearn.linear_model import LogisticRegression
    z = np.log(np.clip(raw, 1e-6, 1 - 1e-6) / (1 - np.clip(raw, 1e-6, 1 - 1e-6))).reshape(-1, 1)
    if len(set(y.tolist())) < 2:
        return (1.0, 0.0)
    m = LogisticRegression(C=1e6, max_iter=1000).fit(z, y)
    return (float(m.coef_[0][0]), float(m.intercept_[0]))


def _apply_platt(raw, ab):
    z = np.log(np.clip(raw, 1e-6, 1 - 1e-6) / (1 - np.clip(raw, 1e-6, 1 - 1e-6)))
    return 1 / (1 + np.exp(-(ab[0] * z + ab[1])))


def _boot_day_diff(days, a, b, reps=1000, seed=11):
    u = sorted(set(days))
    if len(u) < 5:
        return {"status": "INSUFFICIENT_DAYS", "days": len(u)}
    rng = np.random.default_rng(seed)
    by = {d: np.where(days == d)[0] for d in u}
    obs = float(np.mean(a - b))
    sims = []
    for _ in range(reps):
        idx = np.concatenate([by[d] for d in rng.choice(u, size=len(u), replace=True)])
        sims.append(float(np.mean(a[idx] - b[idx])))
    return {"mean_diff": obs, "ci95": [float(np.percentile(sims, 2.5)), float(np.percentile(sims, 97.5))], "days": len(u)}


def run_variant(data: dict, groups: tuple, sp: dict, sar_params=(0.02, 0.2)) -> dict:
    spec = F.default_spec(groups, *sar_params)
    X, ginfo = matrix(data, spec)
    y = np.array([r["y"] for r in data["rows"]], dtype=int)
    nr = np.array([r["net_r"] for r in data["rows"]], dtype=float)
    blocked = [g for g in groups if any(gi.get(g, "").startswith(("BLOCKED", "MISSING")) for gi in ginfo)]
    cover = {g: (float(np.mean([gi.get(g) == "OK" for gi in ginfo])) if ginfo else 0.0) for g in groups}
    if "PAL02M" in groups:
        return {"groups": list(groups), "status": "BLOCKED_IDENTITY_REQUIRED", "coverage": cover}
    if any(cover[g] < 0.5 for g in groups if g != "BASE"):
        return {"groups": list(groups), "status": "BLOCKED_NO_ARCHIVE", "coverage": cover, "blocked_groups": blocked}
    # 1.46 arch (I0168): live inference abstains when a non-BASE group is not OK (ContextModel.predict), so a row with SAR WARMING_UP or
    # IQ MISSING is never scored live - fitting, Platt, the threshold and the holdout use only the rows live can score
    ok = scorable(ginfo, groups)
    excluded = {k: len(sp[k]) - int(ok[sp[k]].sum()) for k, _ in BLOCKS}
    sp = {k: sp[k][ok[sp[k]]] for k, _ in BLOCKS}
    fit, tune, cal, pol, hold = (sp[k] for k, _ in BLOCKS)
    if min(len(fit), len(tune), len(cal), len(pol)) < 10 or len(hold) < MIN_HOLDOUT or len(set(y[fit].tolist())) < 2:
        return {"groups": list(groups), "status": "INSUFFICIENT_DATA", "sizes": {k: int(len(v)) for k, v in sp.items()},
                "excluded_not_scorable": excluded}
    prep = Prep().fit(X[fit])
    Zf, Zt = prep.transform(X[fit]), prep.transform(X[tune])
    cands = {}
    for kind in ("LR", "HGB"):
        m = _fit_model(kind, Zf, y[fit])
        cands[kind] = (m, _ll(y[tune], m.predict_proba(Zt)[:, 1]))
    prior = float(y[fit].mean())
    best = min(cands, key=lambda k: cands[k][1])
    model = cands[best][0]
    ab = _platt(model.predict_proba(prep.transform(X[cal]))[:, 1], y[cal])
    pp = _apply_platt(model.predict_proba(prep.transform(X[pol]))[:, 1], ab)
    thr, best_e = 0.5, -1e9
    for q in np.linspace(0.3, 0.8, 11):
        sel = pp >= q
        if sel.sum() >= 5 and nr[pol][sel].mean() > best_e:
            thr, best_e = float(q), float(nr[pol][sel].mean())
    ph = _apply_platt(model.predict_proba(prep.transform(X[hold]))[:, 1], ab)
    sel = ph >= thr
    return {"groups": list(groups), "status": "EVALUATED", "spec": spec, "model_kind": best, "tune_logloss": {k: v[1] for k, v in cands.items()},
            "prior": prior, "platt": ab, "threshold": thr, "prep": prep, "model": model, "coverage": cover, "excluded_not_scorable": excluded,
            "holdout": {"n": int(len(hold)), "log_loss": _ll(y[hold], ph), "brier": float(np.mean((ph - y[hold]) ** 2)), "ece": _ece(y[hold], ph),
                        "baseline_log_loss": _ll(y[hold], np.full(len(hold), prior)), "selected": int(sel.sum()),
                        "coverage": float(sel.mean()), "net_r_selected_mean": float(nr[hold][sel].mean()) if sel.any() else None,
                        "net_r_all_mean": float(nr[hold].mean())},
            "_ph": ph, "_hold": hold}


def scorable(ginfo: list[dict], groups) -> np.ndarray:
    """Rows live inference would score: every non-BASE group of the variant OK (ContextModel.predict abstains otherwise)."""
    return np.array([all(gi.get(g) == "OK" for g in groups if g != "BASE") for gi in ginfo], dtype=bool).reshape(len(ginfo))


def vs_base(data: dict, r: dict, base: dict) -> dict:
    """Paired day-block bootstrap of the holdout log loss of a variant vs BASE on the SAME rows. 1.46 arch (I0168): the variant holdout
    is a subset of the BASE holdout (only live-scorable rows), so BASE predictions are taken by row index, not by position."""
    pos = {int(i): j for j, i in enumerate(base["_hold"])}
    keep = [j for j, i in enumerate(r["_hold"]) if int(i) in pos]
    hold = np.asarray(r["_hold"])[keep]
    pv = np.asarray(r["_ph"])[keep]
    pb = np.asarray(base["_ph"])[[pos[int(i)] for i in hold]]
    y = np.array([data["rows"][i]["y"] for i in hold], dtype=int)
    days = np.array([data["rows"][i]["decision_time"][:10] for i in hold])
    lv = -(y * np.log(np.clip(pv, 1e-6, 1)) + (1 - y) * np.log(np.clip(1 - pv, 1e-6, 1)))
    lb = -(y * np.log(np.clip(pb, 1e-6, 1)) + (1 - y) * np.log(np.clip(1 - pb, 1e-6, 1)))
    return dict(_boot_day_diff(days, lv, lb), rows=len(hold))


def calibrate_sar(data: dict, sp: dict) -> dict:
    """Frozen grid; every trial recorded; choice on TUNE only (never holdout). The bot's live SAR params are NOT changed.
    1.46 arch (I0168): only rows with SAR OK (scored live) - WARMING_UP rows were median-imputed into the trials."""
    trials = []
    y = np.array([r["y"] for r in data["rows"]], dtype=int)
    _, ginfo = matrix(data, F.default_spec(("SAR",)))
    ok = scorable(ginfo, ("SAR",))
    fit, tune = sp["FIT"][ok[sp["FIT"]]], sp["TUNE"][ok[sp["TUNE"]]]
    if len(fit) < 20 or len(tune) < 10 or len(set(y[fit].tolist())) < 2:
        return {"status": "INSUFFICIENT_DATA", "trials": []}
    for s, m in SAR_GRID:
        X, _ = matrix(data, F.default_spec(("SAR",), s, m))
        prep = Prep().fit(X[fit])
        mdl = _fit_model("LR", prep.transform(X[fit]), y[fit])
        trials.append({"step": s, "max": m, "tune_log_loss": _ll(y[tune], mdl.predict_proba(prep.transform(X[tune]))[:, 1])})
    best = min(trials, key=lambda x: x["tune_log_loss"])
    return {"status": "OK", "grid": SAR_GRID, "trials": trials, "selected": {"step": best["step"], "max": best["max"]},
            "live_default_unchanged": {"step": 0.02, "max": 0.2}}


def train(inst: str, ds: Path, *, commission: float | None = None, db=None, out_dir: Path | None = None, log=print,
          groups: list[str] | None = None) -> dict:
    variants = VARIANTS
    if groups:                                          # 1.46: CLI --groups - BASE + the named groups only (was ignored)
        unknown = sorted(set(groups) - {g for v in VARIANTS for g in v[1:]})
        if unknown:
            raise ValueError("UNKNOWN_GROUPS:" + ",".join(unknown))
        variants = tuple(v for v in VARIANTS if len(v) == 1 or v[1] in groups)
    data = build_dataset(inst, ds, commission, db, log)
    synthetic = data["data_kind"] != "REAL_USER_DATA"
    rid = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "_" + uuid.uuid4().hex[:4] + ("_FIXTURE" if synthetic else "")
    rd = out_dir or (root(inst) / ("fixture_runs" if synthetic else "runs") / rid)
    rd.mkdir(parents=True, exist_ok=True)
    sp = split(data["rows"])
    plan = {"task_id": F.TASK_ID, "schema": F.FEATURE_SCHEMA, "instrument": inst, "blocks": {k: int(len(v)) for k, v in sp.items()},
            "embargo_s": EMBARGO_S, "sar_grid": SAR_GRID, "variants": [list(v) for v in variants], "frozen_at": datetime.now(timezone.utc).isoformat(),
            "label": "y=1 gdy replay zamrożonej polityki rozliczył TP1 przed SL; net_R raportowane obok (to nie P(net_R>0))"}
    (rd / "plan.json").write_text(json.dumps(plan, indent=1), encoding="utf-8")
    rep = {"run_id": rid, "instrument": inst, "dataset_id": data["dataset_id"], "data_kind": data["data_kind"], "cycles": len(data["rows"]),
           "plan": plan, "costs": data["costs"], "profile_id": data["profile_id"], "variants": {}, "role": "fixture_only" if synthetic else "shadow_candidate",
           "legacy_price_rows": data.get("legacy_price_rows", 0), "legacy_atr_rows": data.get("legacy_atr_rows", 0)}
    if len(data["rows"]) < MIN_CYCLES and not synthetic:
        rep.update(status="INSUFFICIENT_DATA", reason=f"cykli {len(data['rows'])} < {MIN_CYCLES}")
    else:
        rep["sar_calibration"] = calibrate_sar(data, sp)
        sel = rep["sar_calibration"].get("selected") or {"step": 0.02, "max": 0.2}
        base = None
        for v in variants:
            r = run_variant(data, v, sp, (sel["step"], sel["max"]) if "SAR" in v else (0.02, 0.2))
            if r["status"] == "EVALUATED" and v == ("BASE",):
                base = r
            if r["status"] == "EVALUATED" and base is not None and v != ("BASE",):
                r["vs_base_log_loss"] = vs_base(data, r, base)
            rep["variants"]["+".join(v)] = {k: x for k, x in r.items() if not k.startswith("_") and k not in ("prep", "model")}
            if r["status"] == "EVALUATED":
                _save_artifact(rd, inst, r, data, rep)
        rep["status"] = "EVALUATED" if base else "INSUFFICIENT_DATA"
        rep["edge_status"] = "NO_VALIDATED_EDGE"           # one holdout + small samples: never an automatic claim
        if base:
            better = [k for k, v in rep["variants"].items() if (v.get("vs_base_log_loss") or {}).get("ci95", [1, 1])[1] < 0]
            rep["variants_better_than_base_ci95"] = better
    (rd / "report.json").write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    reg_p = root(inst) / "registry.json"
    with _REG_LOCK:                                     # 1.46: read-modify-write of the registry is serialised in the process
        reg = json.loads(reg_p.read_text(encoding="utf-8")) if reg_p.exists() else {"schema": "pmw-indicator-context-registry-1", "active": None, "runs": {}}
        reg["runs"][rid] = {"run_dir": str(rd), "status": rep["status"], "role": rep["role"], "created_at": plan["frozen_at"], "data_kind": data["data_kind"],
                            "artifacts": [p.name for p in rd.glob("model_*.json")]}
        _write_registry(reg_p, reg)
    return rep


def _save_artifact(rd: Path, inst: str, r: dict, data: dict, rep: dict) -> None:
    name = "+".join(r["groups"])
    blob = pickle.dumps({"prep": r["prep"], "model": r["model"]})
    (rd / f"model_{name}.pkl").write_bytes(blob)
    man = {"task_id": F.TASK_ID, "feature_schema": F.FEATURE_SCHEMA, "instrument": inst, "symbol": data["symbol"], "side": "BUY+SELL (cecha kierunku znormalizowana)",
           "groups": r["groups"], "feature_order": F.feature_names(r["spec"]), "spec": r["spec"], "model_kind": r["model_kind"], "platt": r["platt"],
           "threshold": r["threshold"], "profile_id": data["profile_id"], "dataset_id": data["dataset_id"], "data_kind": data["data_kind"],
           "role": rep["role"], "pkl_sha256": hashlib.sha256(blob).hexdigest(), "holdout": r["holdout"], "mode": "SHADOW",
           "dependencies": env_versions(), "prep_version": PREP_VERSION}
    # parity: reload exactly what was written and reproduce the holdout predictions of the training code
    m = load_artifact(rd, name, man)
    X, _ = matrix(data, r["spec"])
    p2 = m.predict_raw(X[r["_hold"]])
    man["parity"] = {"max_abs_diff": float(np.max(np.abs(p2 - r["_ph"]))) if len(p2) else 0.0, "rows": int(len(p2))}
    man["parity"]["status"] = "OK" if man["parity"]["max_abs_diff"] <= 1e-9 else "MISMATCH"
    (rd / f"model_{name}.json").write_text(json.dumps(man, indent=1, default=str), encoding="utf-8")


def env_versions() -> dict:
    """Versions the pickled objects depend on (as mm/artifacts._versions)."""
    out = {"python": platform.python_version(), "numpy": np.__version__}
    try:
        import sklearn
        out["scikit-learn"] = sklearn.__version__
    except ImportError:
        out["scikit-learn"] = None
    return out


def _major_minor(v) -> tuple:
    return tuple(str(v or "").split(".")[:2])


def env_mismatch(man: dict) -> list[str]:
    """Packages whose major.minor differs from the artefact's (empty for an older manifest without `dependencies`)."""
    dep = man.get("dependencies")
    if not isinstance(dep, dict):
        return []
    cur = env_versions()
    return [f"{k} {dep.get(k)}!={cur.get(k)}" for k in ENV_PACKAGES if dep.get(k) is not None and _major_minor(dep.get(k)) != _major_minor(cur.get(k))]


class ContextModel:
    # closed M5 / M15 bars live inference should pass (SAR window + margin for bars closing after the decision)
    bars_needed = F.SAR_WINDOW + 4

    def __init__(self, man: dict, obj: dict):
        self.man, self.prep, self.model = man, obj["prep"], obj["model"]

    def predict_raw(self, X: np.ndarray) -> np.ndarray:
        return _apply_platt(self.model.predict_proba(self.prep.transform(X))[:, 1], self.man["platt"])

    def predict(self, snap: dict, instrument: str) -> dict:
        if instrument != self.man["instrument"]:
            return {"status": "ABSTAIN", "reason": f"INSTRUMENT_MISMATCH:{self.man['instrument']}"}
        if self.man.get("feature_schema") != F.FEATURE_SCHEMA:
            # 1.46 arch (I0164/I0784): a V1 artefact learned other inputs (fill price, decision ATR) - no silent new semantics, retrain
            return {"status": "ABSTAIN", "reason": f"FEATURE_SCHEMA_MISMATCH:{self.man.get('feature_schema')}!={F.FEATURE_SCHEMA}"}
        f = F.build_indicator_context_features(snap, self.man["spec"])
        if list(f["features"]) != self.man["feature_order"]:
            return {"status": "ABSTAIN", "reason": "FEATURE_SCHEMA_MISMATCH"}
        bad = [g for g, s in f["groups"].items() if g != "BASE" and s != "OK"]
        if bad:
            return {"status": "ABSTAIN", "reason": "GROUPS_NOT_AVAILABLE:" + ",".join(bad)}
        p = float(self.predict_raw(np.asarray([list(f["features"].values())], dtype=float))[0])
        out = {"status": "READY_INFERENCE", "task_id": self.man["task_id"], "p_tp1_first": p, "threshold": self.man["threshold"],
               "groups": self.man["groups"], "role": self.man["role"], "mode": "SHADOW",
               "note": "P(TP1 przed SL w zamrożonej polityce) – nie P(zysk netto); tylko obserwacja"}
        if not isinstance(self.man.get("dependencies"), dict):
            out["warning"] = "ARTIFACT_WITHOUT_DEPENDENCIES: manifest bez wersji numpy/scikit-learn – zgodność środowiska niesprawdzona"
        return out


def load_artifact(rd: Path, name: str, man: dict | None = None) -> ContextModel:
    man = man or json.loads((rd / f"model_{name}.json").read_text(encoding="utf-8"))
    blob = (rd / f"model_{name}.pkl").read_bytes()
    if hashlib.sha256(blob).hexdigest() != man["pkl_sha256"]:
        raise ValueError("ARTIFACT_CHECKSUM_MISMATCH")
    # 1.46 arch (I0170): sha256 only proves the file is the one written - pickled sklearn / Prep objects of another numpy / scikit-learn
    # (major.minor) may load with another behaviour; a manifest without `dependencies` (older run) still loads, predict() warns
    bad = env_mismatch(man)
    if bad:
        raise ValueError("ARTIFACT_ENV_MISMATCH:" + ",".join(bad))
    try:
        obj = pickle.loads(blob)
    except (AttributeError, ImportError, IndexError, EOFError, TypeError, pickle.UnpicklingError) as exc:
        raise ValueError(f"ARTIFACT_UNREADABLE:{type(exc).__name__}: {exc}"[:200]) from exc
    if not isinstance(obj, dict) or "prep" not in obj or "model" not in obj:
        raise ValueError("ARTIFACT_UNREADABLE:brak prep/model")
    return ContextModel(man, obj)


def active_model(inst: str, why: list | None = None) -> ContextModel | None:
    """Active SHADOW model of the instrument or None; `why` (optional list) receives the reason a registered model is not loadable."""
    try:
        reg_p = root(inst) / "registry.json"              # 1.46: unknown instrument (ValueError from root) = no model
        reg = json.loads(reg_p.read_text(encoding="utf-8"))
        a = reg.get("active")
        if not a:
            return None
        return load_artifact(Path(reg["runs"][a["run_id"]]["run_dir"]), a["variant"])
    except (OSError, ValueError, KeyError) as exc:
        if why is not None and not isinstance(exc, FileNotFoundError):
            why.append(f"{type(exc).__name__}: {exc}"[:200])
        return None


def activate(inst: str, run_id: str, variant: str) -> dict:
    reg_p = root(inst) / "registry.json"
    with _REG_LOCK:
        reg = json.loads(reg_p.read_text(encoding="utf-8"))
        e = reg["runs"].get(run_id)
        if not e or f"model_{variant}.json" not in e["artifacts"]:
            raise ValueError("UNKNOWN_RUN_OR_VARIANT")
        man = json.loads((Path(e["run_dir"]) / f"model_{variant}.json").read_text(encoding="utf-8"))
        if man["role"] == "fixture_only" or man["parity"]["status"] != "OK":
            raise ValueError("NOT_ACTIVATABLE_FIXTURE_OR_PARITY")
        if man.get("feature_schema") != F.FEATURE_SCHEMA:            # 1.46 arch (I0164/I0784): V1 inputs differ from live - retrain first
            raise ValueError(f"NOT_ACTIVATABLE_SCHEMA:{man.get('feature_schema')}!={F.FEATURE_SCHEMA}")
        load_artifact(Path(e["run_dir"]), variant, man)            # 1.46 arch (I0170): env mismatch / unreadable pickle -> refused, registry untouched
        reg.setdefault("history", []).append(reg.get("active"))
        reg["active"] = {"run_id": run_id, "variant": variant, "mode": "SHADOW"}
        _write_registry(reg_p, reg)
    return reg["active"]


def rollback(inst: str) -> dict | None:
    reg_p = root(inst) / "registry.json"
    with _REG_LOCK:
        reg = json.loads(reg_p.read_text(encoding="utf-8"))
        reg["active"] = (reg.get("history") or [None]).pop() if reg.get("history") else None
        _write_registry(reg_p, reg)
    return reg["active"]
