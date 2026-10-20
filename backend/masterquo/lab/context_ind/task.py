"""FS_VS_CONTEXT_v1 (VS08) - optional learning variant on the new context readings, task CONTEXT_MOVE_M5_V1: for every closed M5 bar the
raw-market move after h = 3/6/12 M5 bars, r_h = (C[i+h]-C[i])/ATR14_i, classes +-0.15 sqrt(h) (gap inside the window -> excluded). Features
are built AS OF each bar from the incremental engines (VAMD state, FD state, SMC state/events PUBLISHED by that close - never today's final
geometry). Families CLASS_FREQ / LOGREG / XGB through structure_task.Tabular + the shared frozen protocol (holdout 20 %, purged walk-forward,
holdout once). Ablation: core -> +VAMD -> +FD -> +SMC -> full. Deterministic modules are CALIBRATED (<= 24 pre-declared configs, dev only),
never 'trained'. No model -> no_model; nothing activates execution."""
from __future__ import annotations

import hashlib
import json
import math
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .. import structure_task as T
from . import fractal as FD
from . import smc as SM
from . import vamd as VM

TASK = "CONTEXT_MOVE_M5_V1"
SCHEMA = "FS_VS_CONTEXT_v1"
HORIZONS = (3, 6, 12)
STEP = 300
CORE = ["ret1_atr", "ret3_atr", "range_atr"]
VAMD_F = ["vamd_y", "vamd_m", "vamd_alpha", "vamd_ratio", "vamd_known"]
FD_F = ["fd_smooth", "fd_bounded", "fd_trend", "fd_chop", "fd_flags", "fd_known"]
SMC_F = ["smc_trend", "smc_dist_h_atr", "smc_dist_l_atr", "smc_h_active", "smc_l_active", "smc_pending", "smc_age_break", "smc_age_idm", "smc_known"]
FEATS = CORE + VAMD_F + FD_F + SMC_F
ABLATION = {"core": CORE, "+vamd": CORE + VAMD_F, "+fd": CORE + VAMD_F + FD_F, "+smc": FEATS}
CALIB_GRID = ([("VAMD", {"P": p, "base_decay": b}) for p in (5, 10, 20) for b in (0.10, 0.15, 0.25)]
              + [("FD", {"N": n, "S": s}) for n in (20, 30, 50) for s in (3, 5, 8)]
              + [("SMC", {"idm_mode": im, "detect_sweeps": sw, "pb_mode": pm}) for im, sw, pm in
                 (("WICK", True, "WICK"), ("CLOSE", True, "WICK"), ("WICK", False, "WICK"), ("WICK", True, "CLOSE"), ("CLOSE", False, "CLOSE"),
                  ("CLOSE", True, "CLOSE"))])                       # 9 + 9 + 6 = 24 configurations, frozen before any fit


def root(inst: str) -> Path:
    import mq_instruments
    d = mq_instruments.data_dir() / "context_ind" / inst
    d.mkdir(parents=True, exist_ok=True)
    return d


def profile(inst: str) -> dict:
    p = root(inst) / "profile.json"
    base = {"vamd": {}, "fd": {}, "smc": {"idm_mode": "WICK", "detect_sweeps": True, "pb_mode": "WICK"}, "source": "DEFAULT"}
    if p.exists():
        base.update(json.loads(p.read_text(encoding="utf-8")))
    base["hash"] = hashlib.sha256(json.dumps({k: base[k] for k in ("vamd", "fd", "smc")}, sort_keys=True).encode()).hexdigest()[:16]
    return base


def _ts(x) -> float:
    return x if isinstance(x, (int, float)) else datetime.fromisoformat(str(x).replace("Z", "+00:00")).timestamp()


def labels(t, c, atr):
    n = len(c)
    Y = np.full((n, len(HORIZONS)), -1, dtype=np.int8)
    R = np.full((n, len(HORIZONS)), np.nan, dtype=np.float32)
    run = np.zeros(n, dtype=np.int64)
    for i in range(1, n):
        run[i] = run[i - 1] + 1 if t[i] - t[i - 1] == STEP else 0
    for j, h in enumerate(HORIZONS):
        b = 0.15 * math.sqrt(h)
        for i in range(n - h):
            a = atr[i]
            if not a or a <= 0 or run[i + h] - run[i] != h:
                continue
            r = (c[i + h] - c[i]) / a
            R[i, j], Y[i, j] = r, (0 if r < -b else 2 if r > b else 1)
    return Y, R


def features(bars: list[dict], tick: float, prof: dict | None = None) -> dict:
    prof = prof or {"vamd": {}, "fd": {}, "smc": {}}
    from ...analysis import structure_v2 as S
    c = np.array([b["c"] for b in bars], float)
    atr = S.atr_series([b["h"] for b in bars], [b["l"] for b in bars], list(c))
    v, f, s = VM.VAMD(prof.get("vamd")), FD.FractalRegime(prof.get("fd"), tick), SM.SMC(tick=tick, **(prof.get("smc") or {}))
    F = np.full((len(bars), len(FEATS)), np.nan)
    last_break = last_idm = None
    for i, b in enumerate(bars):
        t_close = _ts(b["open_utc"]) + STEP
        vr, fr, sr = v.update(b), f.update(b), s.update(b, t_close)
        for e in sr["events"]:
            if e["kind"].startswith(("BOS", "CHOCH")):
                last_break = i
            if e["kind"] == "IDM":
                last_idm = i
        a = atr[i]
        if not a or a <= 0:
            continue
        row = F[i]
        row[0] = (c[i] - c[i - 1]) / a if i >= 1 else 0.0
        row[1] = (c[i] - c[i - 3]) / a if i >= 3 else 0.0
        row[2] = (b["h"] - b["l"]) / a
        if vr.get("status") == "READY":
            row[3:8] = [vr["y"], vr["m"], vr["alpha"], vr["ratio"], 1.0]
        else:
            row[3:8] = [0, 0, 0, 0, 0]
        if fr.get("fd_smooth") is not None:
            row[8:14] = [fr["fd_smooth"], fr["fd_bounded"], float(fr["zone"] == "TREND"), float(fr["zone"] == "CHOP"),
                         float(bool(fr.get("saturated"))) + 2 * float(bool(fr.get("clipped"))), 1.0]
        else:
            row[8:14] = [0, 0, 0, 0, 4.0 if fr.get("zone") == "NO_MOTION" else 0.0, 0]
        sh, sl = sr["slots"]["H"], sr["slots"]["L"]
        tr = {"UP": 1.0, "DOWN": -1.0}.get(sr["trend"], 0.0)
        row[14] = tr
        row[15] = (sh["level"] - c[i]) / a if sh.get("status") == "ACTIVE" else 0.0
        row[16] = (c[i] - sl["level"]) / a if sl.get("status") == "ACTIVE" else 0.0
        row[17], row[18] = float(sh.get("status") == "ACTIVE"), float(sl.get("status") == "ACTIVE")
        row[19] = 1.0 if sr["pending"] else 0.0
        row[20] = min(i - last_break, 100) / 100 if last_break is not None else 1.0
        row[21] = min(i - last_idm, 100) / 100 if last_idm is not None else 1.0
        row[22] = 0.0 if sh.get("status") == "UNSEEDED" else 1.0
    return {"F": F, "t": np.array([_ts(b["open_utc"]) for b in bars]), "c": c, "atr": np.array([x if x else np.nan for x in atr]),
            "smc_hash": s.state_hash()}


# ------------------------------------------------------------------ calibration (deterministic, dev only)
def calibrate(inst: str, bars: list[dict], tick: float, meta: dict) -> dict:
    dev = bars[: int(0.8 * len(bars))]
    k = int(len(dev) * 0.6)
    ev = dev[k:]
    t = np.array([_ts(b["open_utc"]) for b in ev])
    c = np.array([b["c"] for b in ev])
    from ...analysis import structure_v2 as S
    atr = S.atr_series([b["h"] for b in ev], [b["l"] for b in ev], list(c))
    _, R = labels(t, c, atr)
    trials = []
    for mod, cfg in CALIB_GRID:
        rec = {"module": mod, "config": cfg, "status": "OK"}
        try:
            if mod == "VAMD":
                ys = [x.get("y") for x in VM.series(ev, cfg)]
                ok = [(y, r) for y, r in zip(ys, R[:, 1]) if y is not None and np.isfinite(r)]
                rec["criterion"] = "rank_corr(y, r_6)"
                rec["value"] = float(np.corrcoef(np.argsort(np.argsort([a for a, _ in ok])), np.argsort(np.argsort([b2 for _, b2 in ok])))[0, 1]) if len(ok) > 50 else None
            elif mod == "FD":
                zs = [x.get("zone") for x in FD.series(ev, cfg)]
                tr = [abs(r) for z, r in zip(zs, R[:, 1]) if z == "TREND" and np.isfinite(r)]
                ch = [abs(r) for z, r in zip(zs, R[:, 1]) if z == "CHOP" and np.isfinite(r)]
                rec["criterion"] = "mean|r_6| TREND - CHOP (separacja, bez kierunku)"
                rec["value"] = float(np.mean(tr) - np.mean(ch)) if tr and ch else None
                rec["coverage"] = {"TREND": len(tr), "CHOP": len(ch)}
            else:
                s = SM.run(ev, STEP, tick=tick, **cfg)
                br = [e for e in s.events if e["kind"].startswith(("BOS", "CHOCH"))]
                ft = []
                for e in br:
                    j = e["bar"]
                    if j + 6 < len(c) and atr[j]:
                        ft.append(((c[j + 6] - c[j]) / atr[j]) * (1 if e["kind"].endswith("UP") else -1))
                rec["criterion"] = "follow-through 6 barów po przełamaniu (ATR), bez kosztów – opis, nie edge"
                rec["value"] = float(np.mean(ft)) if ft else None
                rec["n_breaks"] = len(br)
        except Exception as exc:                                     # noqa: BLE001 - failed trials stay in the ledger
            rec.update(status="FAILED", error=type(exc).__name__)
        trials.append(rec)
    chosen = {}
    for mod in ("VAMD", "FD", "SMC"):
        ok = [x for x in trials if x["module"] == mod and x.get("value") is not None]
        if ok:
            chosen[mod] = max(ok, key=lambda x: x["value"])["config"]
    prof = {"vamd": chosen.get("VAMD", {}), "fd": chosen.get("FD", {}), "smc": dict({"idm_mode": "WICK", "detect_sweeps": True, "pb_mode": "WICK"},
                                                                                     **chosen.get("SMC", {})),
            "source": "CALIBRATED_ON_DEV", "data_kind": meta.get("data_kind"), "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    p = root(inst) / "profile.json"
    if p.exists():
        (root(inst) / f"profile_{int(time.time())}.json").write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
    p.write_text(json.dumps(prof, indent=1), encoding="utf-8")
    led = root(inst) / "calibration_trials.jsonl"
    with led.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"at": prof["created_at"], "trials": trials, "chosen": chosen}, default=float) + "\n")
    return {"trials": trials, "chosen": chosen, "grid_size": len(CALIB_GRID), "holdout_read": False, "profile": profile(inst)}


# ------------------------------------------------------------------ dataset / training
def build_dataset(inst: str, ds: Path, log=print) -> dict:
    from ...extind.trainer import _bars
    meta = json.loads((ds / "source_metadata.json").read_text(encoding="utf-8"))
    tick = float(meta["tick_size"])
    m5 = _bars(ds, meta.get("file_prefix") or "XAUUSD", "M5")
    if len(m5) < 400:
        raise ValueError("BLOCKED_NO_REAL_DATA: za mało świec M5")
    prof = profile(inst)
    fe = features(m5, tick, prof)
    Y, R = labels(fe["t"], fe["c"], fe["atr"])
    rows = np.where((np.arange(len(m5)) >= 80) & np.isfinite(fe["atr"]) & np.isfinite(fe["F"]).all(axis=1))[0]
    did = f"CXD-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:4]}"
    d = root(inst) / "datasets" / did
    d.mkdir(parents=True)
    np.savez(d / "data.npz", F=fe["F"], t=fe["t"], c=fe["c"], atr=fe["atr"], Y=Y, R=R, rows_idx=rows)
    man = {"dataset_id": did, "task": TASK, "schema": SCHEMA, "features": FEATS, "instrument": inst, "data_kind": meta.get("data_kind"), "tick": tick,
           "profile": prof, "rows": int(len(rows)), "raw_dataset": str(ds), "smc_hash": fe["smc_hash"],
           "sha256": hashlib.sha256((d / "data.npz").read_bytes()).hexdigest(), "created_at": datetime.now(timezone.utc).isoformat()}
    (d / "manifest.json").write_text(json.dumps(man, indent=1), encoding="utf-8")
    (root(inst) / "datasets" / "latest.txt").write_text(did, encoding="utf-8")
    log(f"dataset {did}: {len(rows)} wierszy M5")
    return man


def latest(inst: str) -> Path | None:
    p = root(inst) / "datasets" / "latest.txt"
    return root(inst) / "datasets" / p.read_text(encoding="utf-8").strip() if p.exists() else None


def _load(d: Path) -> dict:
    man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    if hashlib.sha256((d / "data.npz").read_bytes()).hexdigest() != man["sha256"]:
        raise ValueError("DATASET_HASH_MISMATCH")
    with np.load(d / "data.npz", allow_pickle=False) as z:
        a = {k: z[k] for k in z.files}
    # T.split expects horizons in M1 minutes for the embargo; scale M5 rows by passing times (labels end = t + h*300)
    return {"manifest": dict(man, task=T.TASK_MOVE), "fe": {"F": a["F"], "t": a["t"], "c": a["c"], "atr": a["atr"]}, "Y": a["Y"], "R": a["R"],
            "rows_idx": a["rows_idx"], "ctx_manifest": man}


def train(inst: str, d: Path, families=("LOGREG", "XGB"), profile_name: str = "standard", db=None, log=print) -> dict:
    data = _load(d)
    man = data["ctx_manifest"]
    if man["profile"]["hash"] != profile(inst)["hash"]:
        return {"status": "STALE_DATASET", "reason": "profil kalibracji zmieniony – zbuduj dataset ponownie"}
    prof = T.PROFILES[profile_name]
    sp = T.split(data)
    b = data["rows_idx"]
    X, Y, R = data["fe"]["F"][b], data["Y"][b].astype(np.int64), data["R"][b].astype(np.float64)
    syn = man["data_kind"] != "REAL_USER_DATA"
    rid = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "_" + uuid.uuid4().hex[:4] + ("_FIXTURE" if syn else "")
    rd = root(inst) / ("fixture_runs" if syn else "runs") / rid
    rd.mkdir(parents=True)
    rep = {"run_id": rid, "task_id": TASK, "schema": SCHEMA, "dataset_id": man["dataset_id"], "role": "TEST_ONLY" if syn else "RESEARCH",
           "split_hash": sp["hash"], "holdout_from": sp["cut"], "folds": [], "ablations": {}, "families": list(families),
           "horizons_m5": list(HORIZONS), "created_at": datetime.now(timezone.utc).isoformat(), "edge_status": "NO_VALIDATED_EDGE"}
    fams = ["CLASS_FREQ"] + [f for f in families if f in ("LOGREG", "XGB")]
    for f in sp["folds"][-int(prof.get("max_folds") or 4):]:
        bl = f["blocks"]
        if min(len(v) for v in bl.values()) < 5 or not len(f["eval"]):
            rep["folds"].append({"fold": f["fold"], "status": "INSUFFICIENT_EVIDENCE"})
            continue
        fr = {"fold": f["fold"], "status": "OK", "families": {}}
        for fam in fams:
            if fam == "XGB":
                try:
                    import xgboost  # noqa: F401
                except ImportError:
                    fr["families"][fam] = {"status": "NOT_AVAILABLE"}
                    continue
            m = T.Tabular(fam, len(HORIZONS)).fit(X, Y, R, bl["FIT"], bl["TUNE"])
            P, Q = m.predict(X[f["eval"]])
            fr["families"][fam] = {"status": "TRAINED", "metrics": T.metrics(P, Q, Y[f["eval"]], R[f["eval"]])}
        for name, cols in ABLATION.items():
            idx = [FEATS.index(x) for x in cols]
            m2 = T.Tabular("LOGREG", len(HORIZONS)).fit(X[:, idx], Y, R, bl["FIT"], bl["TUNE"])
            P2, Q2 = m2.predict(X[f["eval"]][:, idx])
            rep["ablations"].setdefault(name, []).append({"fold": f["fold"], "metrics": T.metrics(P2, Q2, Y[f["eval"]], R[f["eval"]])})
        rep["folds"].append(fr)
        log(f"context fold {f['fold'] + 1}")
    rep["status"] = "EVALUATED_DEV" if any(x.get("status") == "OK" for x in rep["folds"]) else "INSUFFICIENT_EVIDENCE"
    from ...ml import scalp_task as stk
    fb = stk.inner_blocks(sp["dev"], sp["rows"], sp["embargo_s"])
    rep["candidates"] = {}
    if min(len(v) for v in fb.values()) >= 5:
        for fam in [f for f in families if f == "LOGREG"]:
            m = T.Tabular(fam, len(HORIZONS)).fit(X, Y, R, fb["FIT"], fb["TUNE"])
            md = rd / "models" / fam
            md.mkdir(parents=True)
            np.savez(md / "tabular.npz", mu=m.mu, sd=m.sd, **{f"W_{j}": m.p[j]["W"] for j in m.p}, **{f"beta_{j}": m.p[j]["beta"] for j in m.p},
                     **{f"resq_{j}": m.p[j]["res_q"] for j in m.p})
            meta = {"task_id": TASK, "schema": SCHEMA, "features": FEATS, "family": fam, "role": rep["role"], "instrument": inst,
                    "profile_hash": man["profile"]["hash"], "model_hash": hashlib.sha256((md / "tabular.npz").read_bytes()).hexdigest()}
            (md / "candidate.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
            rep["candidates"][fam] = {"candidate_id": f"{rid}-{fam}", "model_hash": meta["model_hash"], "role": rep["role"]}
    rep["run_dir"] = str(rd)
    (rd / "report.json").write_text(json.dumps(rep, indent=1, default=T._jd), encoding="utf-8")
    return rep


def load_candidate(d: Path):
    meta = json.loads((d / "candidate.json").read_text(encoding="utf-8"))
    if hashlib.sha256((d / "tabular.npz").read_bytes()).hexdigest() != meta["model_hash"] or meta.get("features") != FEATS:
        raise ValueError("INCOMPATIBLE_ARTIFACT")
    m = T.Tabular(meta["family"], len(HORIZONS))
    with np.load(d / "tabular.npz", allow_pickle=False) as z:
        m.mu, m.sd = z["mu"], z["sd"]
        for j in range(len(HORIZONS)):
            m.p[j] = {"W": z[f"W_{j}"], "beta": z[f"beta_{j}"], "res_q": z[f"resq_{j}"]}
    return meta, m
