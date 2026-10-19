"""Neural Scalp System (PMW-UPD-04): task SCALP_SETUP_MARKET_V1 for CAUSAL_MTF_TCN_V1 - data adapter, protocol, bundle, registry.

Sample = one scalp candidate of the instrument profile (ScalpMachine plan after the non-neural strategy gates, executable MARKET fill
in the replay - scalp/replay.py is the label policy; the same population as PMW-UPD-03), one side, decision at the close of the
trigger M1 (signal_time; history: availability_basis HISTORICAL_CLOSE_ASSUMPTION).
Outputs for THAT candidate and side:
  events  P(TP1_FIRST), P(SL_FIRST), P(TIMEOUT) - first exit of the cycle within max_hold (sum to 1 only inside one side)
  net_R   expected net result of the whole cycle (partial TP1/TP2, BE, time exit, costs) - MSE head (conditional mean)
A first exit other than TP1/SL/TIME is EARLY_EXIT -> excluded and counted (never forced into a class).
Inputs (snapshot): 128 closed M1 + 32 closed M5 (8 channels each, ATR of the window as unit), last closed M15/H1 rows and the setup
features. Bars with open + TF <= T only. Missing required data -> WARMING_UP / DATA_GAP / INVALID_FEATURES, never zeros.
Protocol = PMW-UPD-03 (ml/scalp_task.py): holdout = last 20 % of calendar time reserved in eval_ledger BEFORE it is read, 4 expanding
outer folds, inner FIT 60 / TUNE 15 / CALIBRATION 15 / POLICY 10 with purge + embargo, temperature per side on CALIBRATION, policy
grid p_tp1_min x net_R_min on POLICY, the frozen bundle (all ensemble members, scaler, temperatures, policy) evaluated once.
"""
from __future__ import annotations

import bisect
import hashlib
import json
import math
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import scalp_net as sn

TASK_ID = "SCALP_SETUP_MARKET_V1"
FEATURE_SCHEMA = "NSS-FEAT-1.0.0"
SEQ_CH = ("ret_atr", "range_atr", "body_atr", "wick_up_atr", "wick_dn_atr", "z20", "logvol_ratio", "spread_atr")
CTX_TF = ("ret4_atr", "range_atr", "z20", "er10", "atr_ratio")
TF_S = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600}
MAX_GAP_S = {"M1": 90 * 60, "M5": 90 * 60}             # daily break of the instrument allowed, a longer hole = DATA_GAP
TRAIN = {"members": [17, 29, 43], "epochs": 60, "batch": 64, "lr": 1e-3, "patience": 7, "budget_minutes": 120}
POLICY_GRID = [(p, e) for p in (0.45, 0.55, 0.65) for e in (0.00, 0.05, 0.10)]
CRITERIA = {"min_fit_tune_per_side": 1000, "min_cal": 200, "min_cal_per_class": 30, "min_eval": 200, "fold_share_logloss_gain": 0.75,
            "min_mean_logloss_gain": 0.002, "max_ece": 0.10, "min_policy_cycles": 100, "min_policy_days": 30, "stress_spread_mult": 1.5,
            "stress_extra_ticks": 1, "max_drawdown_r": 15.0}
NAN = float("nan")


def ctx_names() -> list[str]:
    from ..scalp.strategy import SETUP_FEATURES
    return [f"{tf}_{k}" for tf in ("m15", "h1") for k in CTX_TF] + [f"setup_{k}" for k in SETUP_FEATURES]


def root(inst: str) -> Path:
    import mq_instruments
    d = mq_instruments.data_dir() / "nss" / inst
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ts(s) -> float:
    return s if isinstance(s, (int, float)) else datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()


# ------------------------------------------------------------------ snapshot features (ONE function: dataset, replay, live)
class BarIndex:
    """Closed bars of one TF with a sorted open-time index (as-of lookups without scanning)."""

    def __init__(self, bars: list[dict], tf: str):
        self.tf, self.s = tf, TF_S[tf]
        self.bars = bars
        self.t = [_ts(b["open_utc"]) for b in bars]

    def upto(self, T: float, n: int) -> list[dict]:
        k = bisect.bisect_right(self.t, T - self.s)            # bars whose close (open + TF) <= T
        return self.bars[max(0, k - n):k]


def _atr(bars) -> float:
    r = [b["h"] - b["l"] for b in bars[-14:]]
    return sum(r) / len(r) if r else 0.0


def seq_matrix(bars: list[dict], L: int, tf: str) -> tuple[np.ndarray | None, str]:
    need = L + 20
    if len(bars) < need:
        return None, "WARMING_UP"
    w = bars[-need:]
    ts = [_ts(b["open_utc"]) for b in w]
    if any(b <= a for a, b in zip(ts, ts[1:])):
        return None, "INVALID_FEATURES:DUPLICATE_OR_UNSORTED"
    if any(b - a > MAX_GAP_S[tf] for a, b in zip(ts, ts[1:])):
        return None, "DATA_GAP"
    if any(b.get("spread_price") is None for b in w[-L:]):
        return None, "DATA_GAP:SPREAD_UNKNOWN"
    a = _atr(w)
    if not a or not math.isfinite(a) or a <= 0:
        return None, "INVALID_FEATURES:ZERO_ATR"
    c = np.array([b["c"] for b in w], float)
    tv = np.array([float(b.get("tv") or 0.0) for b in w], float)
    out = np.empty((len(SEQ_CH), L))
    for j in range(L):
        i = 20 + j
        b = w[i]
        win = c[i - 19:i + 1]
        sd = win.std()
        if sd <= 0:
            return None, "INVALID_FEATURES:FLAT_WINDOW"
        out[:, j] = ((c[i] - c[i - 1]) / a, (b["h"] - b["l"]) / a, (b["c"] - b["o"]) / a, (b["h"] - max(b["o"], b["c"])) / a,
                     (min(b["o"], b["c"]) - b["l"]) / a, (c[i] - win.mean()) / sd, math.log((tv[i] + 1) / (tv[i - 19:i + 1].mean() + 1)),
                     b["spread_price"] / a)
    if not np.isfinite(out).all():
        return None, "INVALID_FEATURES:NON_FINITE"
    return out, "OK"


def ctx_vector(bars: list[dict]) -> tuple[list[float] | None, str]:
    if len(bars) < 30:
        return None, "WARMING_UP"
    c = [b["c"] for b in bars]
    a = _atr(bars)
    a30 = sum(b["h"] - b["l"] for b in bars[-30:]) / 30
    win = np.array(c[-20:])
    if a <= 0 or a30 <= 0 or win.std() <= 0:
        return None, "INVALID_FEATURES:ZERO_ATR"
    path = sum(abs(x - y) for x, y in zip(c[-11:], c[-10:]))
    return [(c[-1] - c[-5]) / a, (bars[-1]["h"] - bars[-1]["l"]) / a, (c[-1] - win.mean()) / win.std(),
            abs(c[-1] - c[-11]) / path if path > 0 else 0.0, a / a30], "OK"


def snapshot(idx: dict, T: float, setup_features: dict, cfg: dict | None = None) -> dict:
    """idx: {"M1": BarIndex, "M5": ..., "M15": ..., "H1": ...}. Returns {status, m1 (C,L1), m5 (C,L5), ctx [..], inputs [...]}."""
    from ..scalp.strategy import SETUP_FEATURES
    cfg = dict(sn.DEFAULT_CFG, **(cfg or {}))
    inputs, st = [], "OK"
    m1, s1 = seq_matrix(idx["M1"].upto(T, cfg["m1_len"] + 20), cfg["m1_len"], "M1")
    m5, s5 = seq_matrix(idx["M5"].upto(T, cfg["m5_len"] + 20), cfg["m5_len"], "M5")
    ctx = []
    for tf in ("M15", "H1"):
        bb = idx[tf].upto(T, 30)
        v, s = ctx_vector(bb)
        inputs.append({"tf": tf, "rows": len(bb), "last_bar_close": bb[-1]["open_utc"] if bb else None, "quality": s})
        if v is None:
            st = s if st == "OK" else st
            v = [NAN] * len(CTX_TF)
        ctx += v
    for tf, b, s in (("M1", m1, s1), ("M5", m5, s5)):
        bb = idx[tf].upto(T, 1)
        inputs.insert(0, {"tf": tf, "rows": cfg[f"{tf.lower()}_len"], "last_bar_close": bb[-1]["open_utc"] if bb else None, "quality": s})
        if b is None and st == "OK":
            st = s
    sf = setup_features or {}
    miss = [k for k in SETUP_FEATURES if not isinstance(sf.get(k), (int, float)) or not math.isfinite(sf[k])]
    if miss and st == "OK":
        st = "INVALID_FEATURES:SETUP"
    ctx += [float(sf.get(k)) if k not in miss else NAN for k in SETUP_FEATURES]
    return {"status": st, "m1": m1, "m5": m5, "ctx": np.array(ctx, float), "inputs": inputs, "schema": FEATURE_SCHEMA}


def index_bars(bars: dict) -> dict:
    return {tf: BarIndex(bars.get(tf) or [], tf) for tf in ("M1", "M5", "M15", "H1")}


# ------------------------------------------------------------------ dataset
EVENT = {"TP1": 0, "SL": 1, "TIME": 2}


def build_dataset(inst: str, ds: Path, commission: float | None = None, cfg: dict | None = None, log=print) -> dict:
    from ..extind.trainer import _bars
    from ..ml import scalp_task as stk
    base = stk.build_dataset(inst, ds, commission, log)
    meta = json.loads((ds / "source_metadata.json").read_text(encoding="utf-8"))
    prefix = meta.get("file_prefix") or "XAUUSD"
    point = float(meta["spec"].get("point") or meta["tick_size"])
    bars = {"M1": base["m1"]}
    for tf in ("M5", "M15", "H1"):
        bars[tf] = [dict(b, spread_price=(b["spread"] * point if b["spread"] is not None else None)) for b in _bars(ds, prefix, tf)]
    idx = index_bars(bars)
    cfg = dict(sn.DEFAULT_CFG, **(cfg or {}))
    keep, M1, M5, CTX, skipped = [], [], [], [], {}
    for r in base["rows"]:
        ev = EVENT.get(r["first_exit"])
        if ev is None:
            skipped["EARLY_EXIT"] = skipped.get("EARLY_EXIT", 0) + 1
            continue
        s = snapshot(idx, _ts(r["signal_time"]), r["setup_features"], cfg)
        if s["status"] != "OK":
            k = s["status"].split(":")[0]
            skipped[k] = skipped.get(k, 0) + 1
            continue
        keep.append(dict(r, event=ev))
        M1.append(s["m1"])
        M5.append(s["m5"])
        CTX.append(s["ctx"])
    log(f"NSS {inst}: {len(keep)} próbek z {len(base['rows'])} kandydatów; pominięte {skipped}")
    arr = {"m1": np.array(M1, float).reshape(len(keep), len(SEQ_CH), cfg["m1_len"]), "m5": np.array(M5, float).reshape(len(keep), len(SEQ_CH), cfg["m5_len"]),
           "ctx": np.array(CTX, float).reshape(len(keep), len(ctx_names())), "side": np.array([0 if r["side"] == "BUY" else 1 for r in keep], int),
           "y": np.array([r["event"] for r in keep], int), "r": np.array([r["net_r"] for r in keep], float)}
    content = hashlib.sha256(b"".join(np.ascontiguousarray(arr[k]).tobytes() for k in ("m1", "m5", "ctx", "side", "y", "r"))).hexdigest()[:16]
    return dict(base, rows=keep, arr=arr, bars=bars, skipped=skipped, cfg=cfg, content_hash=content,
                availability_basis="HISTORICAL_CLOSE_ASSUMPTION", population="kandydaci po bramkach strategii z wykonalnym wejściem MARKET (replay, 1 cykl/cooldown)")


# ------------------------------------------------------------------ scaling (fitted on FIT only)
def fit_scaler(arr: dict, idx: np.ndarray) -> dict:
    out = {}
    for k in ("m1", "m5"):
        x = arr[k][idx]
        mu, sd = x.mean(axis=(0, 2)), x.std(axis=(0, 2))
        out[k] = {"mean": mu.tolist(), "std": np.where(sd > 1e-12, sd, 1.0).tolist(), "zero_std": (sd <= 1e-12).tolist()}
    x = arr["ctx"][idx]
    mu, sd = np.nanmean(x, 0), np.nanstd(x, 0)
    out["ctx"] = {"mean": np.where(np.isfinite(mu), mu, 0.0).tolist(), "std": np.where(sd > 1e-12, sd, 1.0).tolist(), "zero_std": (~(sd > 1e-12)).tolist()}
    return out


def scale(sc: dict, m1, m5, ctx):
    a = (m1 - np.array(sc["m1"]["mean"])[None, :, None]) / np.array(sc["m1"]["std"])[None, :, None]
    b = (m5 - np.array(sc["m5"]["mean"])[None, :, None]) / np.array(sc["m5"]["std"])[None, :, None]
    c = (ctx - np.array(sc["ctx"]["mean"])) / np.array(sc["ctx"]["std"])
    return np.clip(a, -10, 10), np.clip(b, -10, 10), np.clip(c, -10, 10)


# ------------------------------------------------------------------ metrics
def _ll3(y, p):
    return float(-np.mean(np.log(np.clip(p[np.arange(len(y)), y], 1e-12, 1)))) if len(y) else NAN


def _ece_top(y, p, bins=10):
    conf, pred = p.max(1), p.argmax(1)
    e, rows = 0.0, []
    for b in range(bins):
        m = (conf >= b / bins) & ((conf < (b + 1) / bins) if b < bins - 1 else (conf <= 1))
        if m.any():
            acc = float((pred[m] == y[m]).mean())
            e += m.mean() * abs(acc - conf[m].mean())
            rows.append({"bin": b, "n": int(m.sum()), "confidence": float(conf[m].mean()), "accuracy": acc})
    return float(e), rows


def _reliability_tp1(y, p, bins=10):
    out = []
    q = p[:, 0]
    for b in range(bins):
        m = (q >= b / bins) & ((q < (b + 1) / bins) if b < bins - 1 else (q <= 1))
        if m.any():
            out.append({"bin": b, "n": int(m.sum()), "p_mean": float(q[m].mean()), "freq": float((y[m] == 0).mean())})
    return out


def _brier3(y, p):
    oh = np.eye(3)[y]
    return float(np.mean(((p - oh) ** 2).sum(1))) if len(y) else NAN


def _dd(x):
    eq = np.cumsum(x)
    return float(np.max(np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:] - eq)) if len(x) else 0.0


# ------------------------------------------------------------------ ensemble model (the deployable unit)
class Ensemble:
    def __init__(self, members: list[sn.CausalMTFTCN], scaler: dict, temps: dict | None = None, policy: dict | None = None):
        self.members, self.scaler, self.temps, self.policy = members, scaler, temps or {}, policy or {}

    def raw(self, m1, m5, ctx, side) -> dict:
        a, b, c = scale(self.scaler, m1, m5, ctx)
        outs = [m.predict(a, b, c, side) for m in self.members]
        return {"proba": np.mean([o["proba"] for o in outs], 0), "net_r": np.mean([o["net_r"] for o in outs], 0)}

    def calibrated(self, proba, side) -> np.ndarray:
        out = proba.copy()
        for s in (0, 1):
            t = self.temps.get(str(s))
            m = np.asarray(side) == s
            if t and t["status"] == "FITTED_ON_CALIBRATION" and m.any():
                out[m] = sn.apply_temperature(proba[m], t["T"])
        return out


def _train_ensemble(data: dict, blocks: dict, cfg: dict, train: dict, log, deadline: float) -> tuple[Ensemble, dict]:
    arr = data["arr"]
    sc = fit_scaler(arr, blocks["FIT"])
    a, b, c = scale(sc, arr["m1"], arr["m5"], arr["ctx"])
    sd = {"m1": a, "m5": b, "ctx": c, "side": arr["side"], "y": arr["y"], "r": arr["r"]}
    members, hist = [], {}
    for seed in train["members"]:
        net = sn.CausalMTFTCN(len(SEQ_CH), len(SEQ_CH), arr["ctx"].shape[1], cfg, seed=seed)
        h = sn.fit(net, sd, blocks["FIT"], blocks["TUNE"], epochs=train["epochs"], batch=train["batch"], lr=train["lr"], patience=train["patience"],
                   seed=seed, cancel=lambda: time.time() > deadline)
        members.append(net)
        hist[str(seed)] = h
        log(f"  członek seed={seed}: epoki {h['epochs_run']}, najlepsza {h['best_epoch']}")
    ens = Ensemble(members, sc)
    cal = blocks["CALIBRATION"]
    raw = ens.raw(arr["m1"][cal], arr["m5"][cal], arr["ctx"][cal], arr["side"][cal])
    for s in (0, 1):
        m = arr["side"][cal] == s
        ens.temps[str(s)] = sn.temperature(np.log(np.clip(raw["proba"][m], 1e-12, 1)), arr["y"][cal][m])
    pol = blocks["POLICY"]
    rp = ens.raw(arr["m1"][pol], arr["m5"][pol], arr["ctx"][pol], arr["side"][pol])
    pp = ens.calibrated(rp["proba"], arr["side"][pol])
    trials, chosen = [], {}
    for s in (0, 1):
        m = arr["side"][pol] == s
        best = None
        for pm, em in POLICY_GRID:
            sel = m & (pp[:, 0] >= pm) & (rp["net_r"] >= em)
            tot = float(arr["r"][pol][sel].sum()) if sel.any() else 0.0
            trials.append({"side": s, "p_tp1_min": pm, "net_r_min": em, "selected": int(sel.sum()), "net_r_total": tot})
            if sel.sum() >= max(5, int(0.1 * m.sum())) and tot > 0 and (best is None or tot > best["net_r_total"]):
                best = trials[-1]
        chosen[str(s)] = {"p_tp1_min": best["p_tp1_min"], "net_r_min": best["net_r_min"]} if best else None
    ens.policy = chosen
    return ens, {"history": hist, "policy_trials": trials, "temperatures": ens.temps, "sizes": {k: int(len(v)) for k, v in blocks.items()}}


def _baselines(data: dict, fit_idx: np.ndarray, ev: np.ndarray) -> dict:
    from sklearn.linear_model import LogisticRegression, Ridge
    arr = data["arr"]
    out = {}
    for s in (0, 1):
        f, e = fit_idx[arr["side"][fit_idx] == s], ev[arr["side"][ev] == s]
        if not len(f) or not len(e):
            continue
        prior = np.bincount(arr["y"][f], minlength=3) / len(f)
        res = {"prior_log_loss": _ll3(arr["y"][e], np.tile(np.clip(prior, 1e-6, 1), (len(e), 1))), "mean_net_r_rmse": float(np.sqrt(np.mean((arr["r"][e] - arr["r"][f].mean()) ** 2)))}
        X = lambda i: np.nan_to_num(np.concatenate([arr["ctx"][i], arr["m1"][i][:, :, -1], arr["m5"][i][:, :, -1]], 1))  # noqa: E731
        mu, sd = X(f).mean(0), X(f).std(0) + 1e-9
        if len(set(arr["y"][f].tolist())) == 3:
            lr = LogisticRegression(C=0.5, max_iter=3000).fit((X(f) - mu) / sd, arr["y"][f])
            res["logreg_log_loss"] = _ll3(arr["y"][e], lr.predict_proba((X(e) - mu) / sd))
        res["ridge_net_r_rmse"] = float(np.sqrt(np.mean((Ridge(alpha=10).fit((X(f) - mu) / sd, arr["r"][f]).predict((X(e) - mu) / sd) - arr["r"][e]) ** 2)))
        out[str(s)] = res
    out["task_b"] = "NOT_COMPARABLE (inna populacja/etykieta – P(TP1 przed SL) modelu B, bez net_R i TIMEOUT)"
    out["resnet1d"] = _resnet_baseline(data, fit_idx, ev)
    return out


def _resnet_baseline(data: dict, fit_idx, ev) -> dict:
    """Existing lab ResNet1D adapted to the same 3-class task on the M1 sequence (single variant, small budget)."""
    from .nets import ResNet1D, train as nets_train
    arr = data["arr"]
    if len(set(arr["y"][fit_idx].tolist())) < 3:
        return {"status": "INSUFFICIENT_EVIDENCE"}
    sc = fit_scaler(arr, fit_idx)
    x, _, _ = scale(sc, arr["m1"], arr["m5"], arr["ctx"])
    k = max(1, int(len(fit_idx) * 0.85))
    m = ResNet1D(x.shape[1], width=8, blocks=2, n_cls=3, seed=17)
    nets_train(m, x[fit_idx[:k]], arr["y"][fit_idx[:k]], x[fit_idx[k:]], arr["y"][fit_idx[k:]], epochs=15, lr=3e-3, patience=3, seed=17)
    p = m.predict_proba(x[ev])
    return {"status": "OK", "log_loss": _ll3(arr["y"][ev], p), "note": "obie strony razem, tylko sekwencja M1"}


# ------------------------------------------------------------------ the run
def train(inst: str, ds: Path, *, commission: float | None = None, db=None, cfg: dict | None = None, train_cfg: dict | None = None, log=print) -> dict:
    data = build_dataset(inst, ds, commission, cfg, log)
    return run_protocol(inst, data, db=db, train_cfg=train_cfg, log=log)


def run_protocol(inst: str, data: dict, *, db=None, train_cfg: dict | None = None, log=print) -> dict:
    """The frozen protocol on a prepared dataset (build_dataset output, or a generated table in the code tests)."""
    from ..ml import scalp_task as stk
    tcfg = dict(TRAIN, **(train_cfg or {}))
    deadline = time.time() + 60 * tcfg["budget_minutes"]
    arr, rows = data["arr"], data["rows"]
    synthetic = data["data_kind"] != "REAL_USER_DATA"
    rid = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "_" + uuid.uuid4().hex[:4] + ("_FIXTURE" if synthetic else "")
    rd = root(inst) / ("fixture_runs" if synthetic else "runs") / rid
    rd.mkdir(parents=True, exist_ok=True)
    embargo = 60.0 * data["prof"]["exits"]["max_hold_minutes"]["value"]
    rep = {"run_id": rid, "task_id": TASK_ID, "architecture_id": sn.ARCH_ID, "feature_schema": FEATURE_SCHEMA, "instrument": inst, "symbol": data["symbol"],
           "dataset_id": data["dataset_id"], "data_kind": data["data_kind"], "content_hash": data["content_hash"], "profile_id": data["profile_id"],
           "profile_hash": data["profile_hash"], "costs": data["costs"], "precision": "OHLC_APPROX", "availability_basis": data["availability_basis"],
           "population": data["population"], "candidates": len(rows), "skipped": data["skipped"], "criteria": CRITERIA, "train": tcfg, "cfg": data["cfg"],
           "class_order": list(sn.CLASSES), "embargo_s": embargo, "role": "FIXTURE_ONLY" if synthetic else "RESEARCH", "sides": {}, "folds": [],
           "created_at": datetime.now(timezone.utc).isoformat(), "ambiguous_share": float(np.mean([r["ambiguous"] for r in rows])) if rows else None}
    if len(rows) < 30:
        rep.update(status="INSUFFICIENT_EVIDENCE", reason=f"{len(rows)} próbek z kompletnymi danymi")
        return _finish(inst, rid, rd, rep)
    t_all = np.array([_ts(r["signal_time"]) for r in rows])
    cut = t_all.min() + 0.8 * (t_all.max() - t_all.min())
    dev = stk._purged(np.where(t_all < cut)[0], rows, cut, embargo)
    hold = np.where(t_all >= cut)[0]
    min_side = CRITERIA["min_fit_tune_per_side"] if not synthetic else 20
    folds = []
    for k, (tr, ev) in enumerate(stk.outer_folds(dev, rows)):
        b = stk.inner_blocks(tr, rows, embargo)
        sizes = {kk: int(len(v)) for kk, v in b.items()}
        ft = np.concatenate([b["FIT"], b["TUNE"]])
        if min(sizes.values()) < 5 or min(int((arr["side"][ft] == s).sum()) for s in (0, 1)) < min_side:
            folds.append({"fold": k, "status": "INSUFFICIENT_EVIDENCE", "sizes": sizes})
            continue
        if time.time() > deadline:
            folds.append({"fold": k, "status": "BUDGET_EXCEEDED"})
            break
        log(f"fold {k + 1}: {sizes}, ocena {len(ev)}")
        ens, info = _train_ensemble(data, b, data["cfg"], tcfg, log, deadline)
        raw = ens.raw(arr["m1"][ev], arr["m5"][ev], arr["ctx"][ev], arr["side"][ev])
        pe = ens.calibrated(raw["proba"], arr["side"][ev])
        base = _baselines(data, ft, ev)
        per = {}
        for s in (0, 1):
            m = arr["side"][ev] == s
            if m.any():
                per[str(s)] = {"n": int(m.sum()), "log_loss": _ll3(arr["y"][ev][m], pe[m]), "ece": _ece_top(arr["y"][ev][m], pe[m])[0],
                               "net_r_rmse": float(np.sqrt(np.mean((raw["net_r"][m] - arr["r"][ev][m]) ** 2)))}
        folds.append({"fold": k, "status": "OK", "sizes": sizes, "eval_n": int(len(ev)), "sides": per, "baselines": base, "policy": ens.policy,
                      "temperatures": ens.temps, "history": info["history"]})
    rep["folds"] = folds
    if time.time() > deadline:
        rep.update(status="BUDGET_EXCEEDED", reason=f"przekroczony budżet {tcfg['budget_minutes']} min – brak finalnego artefaktu")
        return _finish(inst, rid, rd, rep)
    b = stk.inner_blocks(dev, rows, embargo)
    if min(len(v) for v in b.values()) < 5:
        rep.update(status="INSUFFICIENT_EVIDENCE", reason="za mało próbek w blokach finalnego modelu")
        return _finish(inst, rid, rd, rep)
    log("finalny kandydat (rozwój) …")
    ens, info = _train_ensemble(data, b, data["cfg"], tcfg, log, deadline)
    rep["final"] = {"sizes": info["sizes"], "temperatures": info["temperatures"], "policy": ens.policy, "policy_trials": info["policy_trials"],
                    "history": info["history"]}
    bdir = rd / "bundle"
    mhash = save_bundle(bdir, ens, rep, data)
    rep["model_hash"] = mhash
    bl = load_bundle(bdir)                                           # the runtime loader, hash verified - this is what is evaluated
    if not len(hold):
        rep.update(status="INSUFFICIENT_EVIDENCE", reason="pusty holdout")
        return _finish(inst, rid, rd, rep)
    h0, h1 = rows[hold[0]]["signal_time"], max(rows[i]["label_end"] for i in hold)
    led = stk.reserve_holdout(db, inst, h0, h1, mhash, TASK_ID) if db is not None else {"status": "LEDGER_UNAVAILABLE"}
    rep["ledger"] = led
    raw = bl.ens.raw(arr["m1"][hold], arr["m5"][hold], arr["ctx"][hold], arr["side"][hold])
    ph = bl.ens.calibrated(raw["proba"], arr["side"][hold])
    days = np.array([rows[i]["signal_time"][:10] for i in hold])
    for s, nm in ((0, "BUY"), (1, "SELL")):
        m = arr["side"][hold] == s
        y, r, p, ev_ = arr["y"][hold][m], arr["r"][hold][m], ph[m], raw["net_r"][m]
        okf = [f for f in folds if f["status"] == "OK" and str(s) in f["sides"]]
        gains = [f["baselines"][str(s)]["prior_log_loss"] - f["sides"][str(s)]["log_loss"] for f in okf if str(s) in f["baselines"]]
        dc = {"fold_share_logloss_gain": float(np.mean([g >= CRITERIA["min_mean_logloss_gain"] for g in gains])) if gains else 0.0,
              "mean_logloss_gain": float(np.mean(gains)) if gains else None, "folds_ok": len(okf)}
        pol = ens.policy.get(str(s))
        sel = (p[:, 0] >= pol["p_tp1_min"]) & (ev_ >= pol["net_r_min"]) if pol else np.zeros(len(y), bool)
        hi = hold[m]
        stress = np.array([(rows[i]["net_price"] - (CRITERIA["stress_spread_mult"] - 1) * (rows[i]["spread"] or 0) - 2 * CRITERIA["stress_extra_ticks"] * data["tick"])
                           / rows[i]["risk"] for i in hi])
        ece, rel = _ece_top(y, p)
        hb = {"n": int(m.sum()), "days": int(len(set(days[m].tolist()))), "class_counts": np.bincount(y, minlength=3).tolist(), "log_loss": _ll3(y, p),
              "prior_log_loss": _ll3(y, np.tile(np.clip(np.bincount(arr["y"][dev][arr["side"][dev] == s], minlength=3) / max(1, (arr["side"][dev] == s).sum()), 1e-6, 1), (len(y), 1))),
              "brier": _brier3(y, p), "ece_top": ece, "reliability_top": rel, "reliability_tp1": _reliability_tp1(y, p),
              "net_r_rmse": float(np.sqrt(np.mean((ev_ - r) ** 2))) if len(r) else None, "net_r_mae": float(np.mean(np.abs(ev_ - r))) if len(r) else None,
              "net_r_bias": float(np.mean(ev_ - r)) if len(r) else None, "policy": pol, "policy_selected": int(sel.sum()),
              "policy_days": int(len(set(days[m][sel].tolist()))), "coverage": float(sel.mean()) if len(sel) else 0.0,
              "policy_net_r_mean": float(r[sel].mean()) if sel.any() else None, "baseline_net_r_mean": float(r.mean()) if len(r) else None,
              "policy_boot": stk._day_boot(days[m][sel], r[sel]) if sel.any() else {"status": "NO_SELECTED"},
              "incremental_boot": stk._day_boot(days[m], np.where(sel, r, 0.0) - r), "skipped_wins_r": float(r[~sel & (r > 0)].sum()),
              "avoided_losses_r": float(-r[~sel & (r <= 0)].sum()), "stress_net_r_mean": float(stress[sel].mean()) if sel.any() else None,
              "policy_max_dd_r": _dd(r[sel]), "baseline_max_dd_r": _dd(r)}
        if pol:
            hb["policy_replay"] = policy_replay(data, s, cut, bl) if data.get("m1") else {"status": "NOT_RUN_NO_BARS"}
        tcal = ens.temps.get(str(s), {})
        passed = (dc["fold_share_logloss_gain"] >= CRITERIA["fold_share_logloss_gain"] and (dc["mean_logloss_gain"] or 0) >= CRITERIA["min_mean_logloss_gain"]
                  and tcal.get("status") == "FITTED_ON_CALIBRATION" and hb["ece_top"] <= CRITERIA["max_ece"]
                  and hb["policy_selected"] >= CRITERIA["min_policy_cycles"] and hb["policy_days"] >= CRITERIA["min_policy_days"]
                  and (hb["policy_boot"].get("ci95") or [-1])[0] > 0 and (hb["incremental_boot"].get("ci95") or [-1])[0] > 0
                  and (hb["stress_net_r_mean"] or -1) > 0 and hb["policy_max_dd_r"] <= CRITERIA["max_drawdown_r"])
        status = ("FIXTURE_ONLY" if synthetic else "INSUFFICIENT_EVIDENCE" if hb["n"] < CRITERIA["min_eval"] else
                  "HOLDOUT_PASSED" if passed and led["status"] == "FRESH" else "REUSED_PERIOD_EXPLORATORY" if passed else "NO_VALIDATED_EDGE")
        rep["sides"][nm] = {"status": status, "development_criteria": dc, "holdout": hb, "calibration": tcal.get("status")}
    rep["status"] = "EVALUATED"
    return _finish(inst, rid, rd, rep)


def policy_replay(data: dict, s: int, cut: float, bl: "NSSBundle") -> dict:
    """Chronological replay with the frozen NSS policy as a decision filter (one cycle / cooldown kept, rejected candidates free the
    slot) vs the baseline strategy, holdout part, this side."""
    from ..scalp import replay
    side = "BUY" if s == 0 else "SELL"
    idx = index_bars(data["bars"])

    def accept(plan):
        if plan["direction"] != side or _ts(plan["decision_time"]) < cut:
            return True
        o = bl.predict(snapshot(idx, plan["decision_ts"], plan.get("features") or {}, bl.cfg), instrument=data["instrument"],
                       profile_hash=data["profile_hash"], side=side)
        return bool(o.get("candidate_output", {}).get("proposed_filter_result"))
    res = replay.run(data["m1"], data["prof"], data["tick"], data["replay_costs"], accept=accept)
    ml = [c for c in res["cycles"] if c["direction"] == side and _ts(c["decision_time"]) >= cut]
    base = [r for r in data["rows"] if r["side"] == side and _ts(r["signal_time"]) >= cut]
    return {"nss_cycles": len(ml), "nss_net_r_total": float(sum(c["net_r"] for c in ml)), "baseline_cycles": len(base),
            "baseline_net_r_total": float(sum(r["net_r"] for r in base)), "nss_max_dd_r": _dd(np.array([c["net_r"] for c in ml])),
            "rejected_by_policy": sum(1 for b in res["blocked"] if b.get("reason") == "ML_POLICY_REJECTED"), "note": "replay OHLC (bez ticków)"}


def _finish(inst: str, rid: str, rd: Path, rep: dict) -> dict:
    tmp = rd / "report.json.tmp"
    tmp.write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, rd / "report.json")
    p = root(inst) / "registry.json"
    reg = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"schema": "pmw-nss-registry-1", "selected": None, "history": [], "runs": {}}
    reg["runs"][rid] = {"run_dir": str(rd), "status": rep["status"], "role": rep["role"], "model_hash": rep.get("model_hash"), "profile_hash": rep.get("profile_hash"),
                        "sides": {k: v.get("status") for k, v in rep.get("sides", {}).items()}}
    _write_reg(p, reg)
    return rep


def _write_reg(p: Path, reg: dict) -> None:
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(reg, indent=1), encoding="utf-8")
    os.replace(tmp, p)


# ------------------------------------------------------------------ bundle (JSON + NPZ, allow_pickle=False)
def save_bundle(d: Path, ens: Ensemble, rep: dict, data: dict) -> str:
    import shutil
    tmp = d.with_name(d.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    ids = []
    for m in ens.members:
        mid = f"member_{m.cfg['seed']}"
        np.savez(tmp / f"{mid}.npz", **m.p)
        ids.append(mid)
    (tmp / "preprocessor.json").write_text(json.dumps({"feature_schema": FEATURE_SCHEMA, "seq_channels": list(SEQ_CH), "ctx_features": ctx_names(),
                                                       "scaler": ens.scaler, "clip": 10}), encoding="utf-8")
    (tmp / "calibration.json").write_text(json.dumps({"method": "temperature on log(mean member P), per side", "temperatures": ens.temps}), encoding="utf-8")
    (tmp / "policy.json").write_text(json.dumps({"policy": ens.policy, "grid": POLICY_GRID}), encoding="utf-8")
    files = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(tmp.iterdir())}
    mhash = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    m0 = ens.members[0]
    man = {"task_id": TASK_ID, "architecture_id": sn.ARCH_ID, "instrument": rep["instrument"], "symbol": rep["symbol"], "profile_id": rep["profile_id"],
           "profile_hash": rep["profile_hash"], "entry_policy": "MARKET", "class_order": list(sn.CLASSES), "cfg": {k: v for k, v in m0.cfg.items() if k != "seed"},
           "members": ids, "aggregation": "mean of member probabilities, then temperature per side; net_R = mean of members",
           "params_per_member": m0.n_params(), "macs_per_member": m0.macs(), "role": rep["role"], "data_kind": rep["data_kind"], "dataset_id": rep["dataset_id"],
           "content_hash": rep["content_hash"], "costs": rep["costs"], "files_sha256": files, "model_hash": mhash, "trained_until": None,
           "label": "first exit TP1/SL/TIME within max_hold + net_R of the full cycle (scalp/replay.py)"}
    (tmp / "manifest.json").write_text(json.dumps(man, indent=1, default=str), encoding="utf-8")
    if d.exists():
        shutil.rmtree(d)
    os.replace(tmp, d)
    return mhash


class NSSBundle:
    def __init__(self, d: Path):
        self.dir = d
        self.man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        if self.man.get("architecture_id") != sn.ARCH_ID or self.man.get("task_id") != TASK_ID:
            raise ValueError("ARTIFACT_TASK_OR_ARCH_MISMATCH")
        for f, h in self.man["files_sha256"].items():
            if hashlib.sha256((d / f).read_bytes()).hexdigest() != h:
                raise ValueError(f"ARTIFACT_CHECKSUM_MISMATCH:{f}")
        pre = json.loads((d / "preprocessor.json").read_text(encoding="utf-8"))
        if pre["feature_schema"] != FEATURE_SCHEMA or pre["seq_channels"] != list(SEQ_CH) or pre["ctx_features"] != ctx_names():
            raise ValueError("FEATURE_SCHEMA_MISMATCH")
        self.cfg = self.man["cfg"]
        members = []
        for mid in self.man["members"]:
            net = sn.CausalMTFTCN(self.cfg["c_m1"], self.cfg["c_m5"], self.cfg["c_ctx"], self.cfg, seed=int(mid.split("_")[1]))
            with np.load(d / f"{mid}.npz", allow_pickle=False) as z:
                if set(z.files) != set(net.p):
                    raise ValueError("ARTIFACT_PARAMS_MISMATCH")
                for k in net.p:
                    if z[k].shape != net.p[k].shape:
                        raise ValueError(f"ARTIFACT_SHAPE_MISMATCH:{k}")
                    net.p[k] = z[k].copy()
            members.append(net)
        cal = json.loads((d / "calibration.json").read_text(encoding="utf-8"))["temperatures"]
        pol = json.loads((d / "policy.json").read_text(encoding="utf-8"))["policy"]
        self.ens = Ensemble(members, pre["scaler"], cal, pol)

    def predict(self, snap: dict, *, instrument: str, profile_hash: str, side: str, entry_mode: str = "MARKET", telemetry: bool = False) -> dict:
        """One inference for one candidate. Scope / schema / data checks BEFORE any forward."""
        if instrument != self.man["instrument"] or profile_hash != self.man["profile_hash"]:
            return {"technical_status": "ERROR", "reason": "MODEL_SCOPE_MISMATCH (instrument/profil)"}
        if entry_mode != "MARKET":
            return {"technical_status": "UNSUPPORTED_ENTRY_POLICY", "reason": "NSS V1 obsługuje tylko wejście MARKET"}
        if snap["status"] != "OK":
            return {"technical_status": snap["status"].split(":")[0], "reason": snap["status"]}
        if side not in ("BUY", "SELL"):
            return {"technical_status": "ERROR", "reason": "SIDE_INVALID"}
        s = 0 if side == "BUY" else 1
        e = self.ens
        a, b, c = scale(e.scaler, snap["m1"][None], snap["m5"][None], snap["ctx"][None])
        t0 = time.perf_counter()
        outs, layers = [], None
        for i, m in enumerate(e.members):
            if telemetry and i == 0:
                o = m.infer_with_telemetry(a, b, c, [s])
                layers = o["layers"]
            else:
                o = m.predict(a, b, c, [s])
            outs.append(o)
        raw_p = np.mean([o["proba"] for o in outs], 0)
        net = float(np.mean([o["net_r"][0] for o in outs]))
        inf_ms = (time.perf_counter() - t0) * 1000
        t = e.temps.get(str(s)) or {}
        calp = sn.apply_temperature(raw_p, t["T"])[0].tolist() if t.get("status") == "FITTED_ON_CALIBRATION" else None
        pol = (e.policy or {}).get(str(s))
        prop = None if (pol is None or calp is None) else bool(calp[0] >= pol["p_tp1_min"] and net >= pol["net_r_min"])
        return {"technical_status": "READY_INFERENCE", "model_hash": self.man["model_hash"], "ensemble_member_ids": self.man["members"],
                "telemetry_member": self.man["members"][0] if telemetry else None, "layers": layers, "inference_ms": round(inf_ms, 2),
                "candidate_output": {"side": side, "class_order": list(sn.CLASSES), "raw_logits": outs[0]["logits"][0].tolist() if len(outs) == 1 else None,
                                     "raw_probabilities": raw_p[0].tolist(), "calibrated_probabilities": calp, "calibration_status": t.get("status", "CALIBRATION_UNVERIFIED"),
                                     "expected_net_R": net, "policy_thresholds": pol, "proposed_filter_result": prop,
                                     "outcome_definition": "pierwsze wyjście cyklu w czasie profilu: TP1 przed SL / SL przed TP1 / limit czasu; net_R = cały cykl po kosztach"}}

    def context_layers(self, snap: dict) -> list[dict] | None:
        if snap["m1"] is None or snap["m5"] is None:
            return None
        a, b, _ = scale(self.ens.scaler, snap["m1"][None], snap["m5"][None], np.zeros((1, len(ctx_names()))))
        return self.ens.members[0].context_telemetry(a, b)


def load_bundle(d: Path) -> NSSBundle:
    return NSSBundle(d)


# ------------------------------------------------------------------ registry: explicit selection (no auto-promotion)
def select(inst: str, run_id: str, role: str) -> dict:
    if role not in ("OBSERVE", "SHADOW_GATE"):
        raise ValueError("ROLE_INVALID")
    p = root(inst) / "registry.json"
    reg = json.loads(p.read_text(encoding="utf-8"))
    e = reg["runs"].get(run_id)
    if not e or not e.get("model_hash"):
        raise ValueError("UNKNOWN_RUN_OR_NO_ARTIFACT")
    if e["role"] == "FIXTURE_ONLY":
        raise ValueError("FIXTURE_ONLY_NOT_SELECTABLE")
    if role == "SHADOW_GATE" and "HOLDOUT_PASSED" not in (e.get("sides") or {}).values():
        raise ValueError("SHADOW_GATE_REQUIRES_HOLDOUT_PASSED")
    load_bundle(Path(e["run_dir"]) / "bundle")
    reg["history"].append({"previous": reg.get("selected"), "at": datetime.now(timezone.utc).isoformat()})
    reg["selected"] = {"run_id": run_id, "role": role, "model_hash": e["model_hash"],
                       "gated_sides": [s for s, v in (e.get("sides") or {}).items() if v == "HOLDOUT_PASSED"] if role == "SHADOW_GATE" else []}
    _write_reg(p, reg)
    return reg["selected"]


def rollback(inst: str) -> dict | None:
    p = root(inst) / "registry.json"
    reg = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"history": []}
    if not reg.get("history"):
        raise ValueError("NO_PREVIOUS_SELECTION")
    h = reg["history"].pop()
    reg["selected"] = h["previous"]
    _write_reg(p, reg)
    return reg["selected"]


_cache: dict = {}


def selected_bundle(inst: str) -> tuple[NSSBundle | None, dict | None]:
    p = root(inst) / "registry.json"
    try:
        mt = p.stat().st_mtime
        reg = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, None
    sel = reg.get("selected")
    if not sel:
        return None, None
    key = (inst, sel["model_hash"], mt)
    if key not in _cache:
        _cache.clear()
        _cache[key] = load_bundle(Path(reg["runs"][sel["run_id"]]["run_dir"]) / "bundle")
    return _cache[key], sel


def static_architecture(inst: str | None = None) -> dict:
    """Definition of the architecture without weights (panel: 'Brak wytrenowanego modelu')."""
    return sn.CausalMTFTCN(len(SEQ_CH), len(SEQ_CH), len(ctx_names()), seed=17).architecture()
