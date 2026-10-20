"""FLOW_CONTEXT_MOVE_M1_V1 (FF07) - shared reaction model on flow-context readings. Labels = the SAME raw-market definition as
STRUCTURE_MOVE_M1_V1 (r_h = (BidClose[i+h]-BidClose[i])/ATR14_i, h = 3/5/15, classes +-0.15 sqrt(h)); targets are never Heikin prices.
Features (schema FLOW_CONTEXT_V1, one causal builder for dataset and runtime):
  Heikin Flow (profile from calibration, default EMA10/EMA5): body/range in ATR, colour, streak, PARTIAL_STARTUP mask, raw-vs-synthetic.
  S/R channels: snapshot recomputed at every 15th closed M1 bar (as-of archive) - nearest support/resistance distance in ATR, width,
    raw score, member count, inside flag, age; the row uses the last snapshot KNOWN at its close (never a later one).
  StopDistance: range/average ratio, average and suggested in ATR units (points converted with point), warmup mask.
  Markov3 / buckets: PREFIX (prequential) predictions - bins/tau fitted on the first WARM bars only, counts updated after scoring;
    fixed-size bucket summary (mean/sd at h=5/15 from the DP, K_effective, support, normalised entropy), so K never changes the width.
Families CLASS_FREQ / LOGREG / XGB (structure_task.Tabular), temperature on CALIBRATION, residual quantiles from CALIBRATION
(CALIBRATED_RESIDUAL_LOCATION). Protocol = structure_task.split (holdout 20 %, 4 purged walk-forward folds); holdout opened once."""
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
from . import heikin as HF
from . import markov as MK
from . import sr_channels as SR
from . import stop_distance as SD

TASK = "FLOW_CONTEXT_MOVE_M1_V1"
SCHEMA = "FLOW_CONTEXT_V1"
FEATS = ["ha_body_atr", "ha_range_atr", "ha_color", "ha_streak", "ha_partial", "raw_minus_ha_atr",
         "sr_sup_dist_atr", "sr_res_dist_atr", "sr_inside", "sr_width_atr", "sr_score", "sr_members", "sr_age", "sr_known",
         "sd_ratio", "sd_avg_atr", "sd_sugg_atr", "sd_known",
         "m3_p_down", "m3_p_flat", "m3_p_up", "m3_entropy", "m3_support", "m3_known",
         "mb_mean5_atr", "mb_sd5_atr", "mb_mean15_atr", "mb_sd15_atr", "mb_k_eff", "mb_entropy", "mb_known"]
ABLATIONS = {"raw_core": [], "+heikin": FEATS[:6], "+sr": FEATS[6:14], "+stopdistance": FEATS[14:18], "+markov3": FEATS[18:24],
             "+buckets": FEATS[24:31]}
WARM = 1000
SR_EVERY = 15
FAMILIES = ("LOGREG", "XGB")


def root(inst: str) -> Path:
    import mq_instruments
    d = mq_instruments.data_dir() / "flow_context" / inst
    d.mkdir(parents=True, exist_ok=True)
    return d


def profile(inst: str) -> dict:
    p = root(inst) / "profile.json"
    base = {"heikin": {"ma1": "EMA", "p1": 10, "ma2": "EMA", "p2": 5}, "stopdistance": {"period": 20, "method": "SMA", "factor": 1.5},
            "sr": {"depth": 10, "width_pct": 5.0, "loopback": 300}, "source": "DEFAULT"}
    if p.exists():
        base.update(json.loads(p.read_text(encoding="utf-8")))
    base["hash"] = hashlib.sha256(json.dumps({k: base[k] for k in ("heikin", "stopdistance", "sr")}, sort_keys=True).encode()).hexdigest()[:16]
    return base


def features(m1: list[dict], point: float, tick: float, prof: dict | None = None) -> dict:
    prof = prof or {"heikin": {}, "stopdistance": {}, "sr": {}}
    n = len(m1)
    c = np.array([b["c"] for b in m1], float)
    from ...analysis import structure_v2 as S
    atr = S.atr_series([b["h"] for b in m1], [b["l"] for b in m1], list(c))
    F = np.full((n, len(FEATS)), np.nan)
    hf = HF.HeikinFlow(prof.get("heikin"), point)
    sd = SD.StopDistance(prof.get("stopdistance"), point, tick)
    piv = SR.pivots(m1, int((prof.get("sr") or {}).get("depth", 10)))
    snap, streak, last_col = None, 0, None
    m3 = md = None
    t = [_ts(b["open_utc"]) for b in m1]
    for i, b in enumerate(m1):
        a = atr[i]
        r = hf.update(b)
        s = sd.update(b)
        if r["color"] == last_col:
            streak += 1
        else:
            streak, last_col = 1, r["color"]
        if i % SR_EVERY == SR_EVERY - 1 and i >= 2 * 10 + 1:
            snap = SR.channels_at(m1[max(0, i - 700):i + 1], min(i, 700), prof.get("sr"), piv=[dict(p, origin_index=p["origin_index"] - max(0, i - 700),
                                  confirmed_index=p["confirmed_index"] - max(0, i - 700)) for p in piv if p["confirmed_index"] <= i
                                  and p["origin_index"] >= max(0, i - 700)])
            snap["_t"] = i
        if i == WARM - 1:
            try:
                m3 = MK.Markov3(point, tick).fit(m1[:WARM])
                md = MK.MarkovDiff(point, 9).fit(m1[:WARM])
            except ValueError:
                m3 = md = None
        if not a or a <= 0:
            continue
        f = F[i]
        f[0], f[1] = (r["c"] - r["o"]) / a, (r["h"] - r["l"]) / a
        f[2] = {"BULL": 1.0, "BEAR": -1.0}.get(r["color"], 0.0)
        f[3] = min(streak, 30) / 30.0
        f[4] = 1.0 if r["quality"] == "PARTIAL_STARTUP" else 0.0
        f[5] = (b["c"] - r["c"]) / a
        if snap is not None:
            nn = SR.nearest(snap, b["c"])
            f[6] = (b["c"] - nn["support"]["hi"]) / a if nn["support"] else 50.0
            f[7] = (nn["resistance"]["lo"] - b["c"]) / a if nn["resistance"] else 50.0
            f[8] = 1.0 if nn["inside"] else 0.0
            top = snap["channels"][0] if snap["channels"] else None
            f[9] = (top["width"] / a) if top else 0.0
            f[10] = (top["score"] / 100.0) if top else 0.0
            f[11] = len(top["members"]) if top else 0.0
            f[12] = min(i - snap["_t"], SR_EVERY) / SR_EVERY
            f[13] = 1.0
        else:
            f[6:13], f[13] = 0.0, 0.0
        if s["average_points"]:
            f[14], f[15], f[16], f[17] = s["range_points"] / s["average_points"], s["average_points"] * point / a, s["suggested_points"] * point / a, 1.0
        else:
            f[14:17], f[17] = 0.0, 0.0
        if m3 is not None and i >= WARM:
            st = m3.step(m1[max(0, i - 3):i + 1])
            if st.get("next"):
                f[18], f[19], f[20] = st["next"]["DOWN"], st["next"]["FLAT"], st["next"]["UP"]
                f[21] = st["entropy_next"]
                s3 = m3.state(st["d_points"])
                f[22] = min(st["support"][s3], 1000) / 1000.0
                f[23] = 1.0
            ds = md.step(m1[i - 1:i + 1], 15, mc=False) if i >= 1 else None
            if ds and ds.get("projection"):
                p5, p15 = ds["projection"]["5"], ds["projection"]["15"]
                f[24], f[25] = p5["mean_points"] * point / a, math.sqrt(p5["var_points2"]) * point / a
                f[26], f[27] = p15["mean_points"] * point / a, math.sqrt(p15["var_points2"]) * point / a
                f[28] = ds["K_effective"]
                f[29] = MK.entropy(ds["state_distributions"][0])
                f[30] = 1.0
            else:
                f[24:30], f[30] = 0.0, 0.0
        else:
            f[18:24] = [1 / 3, 1 / 3, 1 / 3, 1.0, 0.0, 0.0]
            f[24:31] = 0.0
    return {"F": F, "t": np.array(t), "c": c, "atr": np.array([x if x else np.nan for x in atr]), "schema": SCHEMA, "names": FEATS}


def _ts(x) -> float:
    return x if isinstance(x, (int, float)) else datetime.fromisoformat(str(x).replace("Z", "+00:00")).timestamp()


# ------------------------------------------------------------------ dataset
def build_dataset(inst: str, ds: Path, log=print) -> dict:
    from ...extind.trainer import _bars
    meta = json.loads((ds / "source_metadata.json").read_text(encoding="utf-8"))
    if meta.get("instrument", "XAUUSD") != inst:
        raise ValueError(f"INSTRUMENT_MISMATCH:{meta.get('instrument')}!={inst}")
    tick = float(meta["tick_size"])
    point = float((meta.get("spec") or {}).get("point") or tick)
    m1 = _bars(ds, meta.get("file_prefix") or "XAUUSD", "M1")
    if len(m1) < WARM + 500:
        raise ValueError("BLOCKED_NO_REAL_DATA: za mało świec M1")
    prof = profile(inst)
    t0 = time.time()
    fe = features(m1, point, tick, prof)
    log(f"cechy flow {inst}: {len(m1)} M1 w {time.time() - t0:.0f}s")
    Y, R = T.labels(list(fe["t"]), list(fe["c"]), list(fe["atr"]))
    rows = np.where((np.arange(len(m1)) >= WARM) & np.isfinite(fe["atr"]) & np.isfinite(fe["F"]).all(axis=1))[0]
    did = f"FCD-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:4]}"
    d = root(inst) / "datasets" / did
    d.mkdir(parents=True)
    np.savez(d / "data.npz", F=fe["F"], t=fe["t"], c=fe["c"], atr=fe["atr"], Y=Y, R=R, rows_idx=rows)
    man = {"dataset_id": did, "task": TASK, "schema": SCHEMA, "instrument": inst, "symbol": meta.get("symbol"), "data_kind": meta.get("data_kind"),
           "raw_dataset": str(ds), "tick": tick, "point": point, "profile": prof, "rows": int(len(rows)), "warm_bars": WARM,
           "sha256": hashlib.sha256((d / "data.npz").read_bytes()).hexdigest(), "created_at": datetime.now(timezone.utc).isoformat()}
    (d / "manifest.json").write_text(json.dumps(man, indent=1), encoding="utf-8")
    idx = root(inst) / "datasets" / "index.json"
    lst = json.loads(idx.read_text(encoding="utf-8")) if idx.exists() else []
    lst.append({"dataset_id": did, "profile_hash": prof["hash"]})
    idx.write_text(json.dumps(lst, indent=1), encoding="utf-8")
    return man


def latest(inst: str) -> Path | None:
    idx = root(inst) / "datasets" / "index.json"
    lst = json.loads(idx.read_text(encoding="utf-8")) if idx.exists() else []
    return root(inst) / "datasets" / lst[-1]["dataset_id"] if lst else None


def load(d: Path) -> dict:
    man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    if man["task"] != TASK:
        raise ValueError("TASK_MISMATCH")
    if hashlib.sha256((d / "data.npz").read_bytes()).hexdigest() != man["sha256"]:
        raise ValueError("DATASET_HASH_MISMATCH")
    with np.load(d / "data.npz", allow_pickle=False) as z:
        a = {k: z[k] for k in z.files}
    return {"manifest": dict(man, task=T.TASK_MOVE), "fe": {"F": a["F"], "t": a["t"], "c": a["c"], "atr": a["atr"]}, "Y": a["Y"], "R": a["R"],
            "rows_idx": a["rows_idx"], "flow_manifest": man}


# ------------------------------------------------------------------ training
def _fit(fam, X, Y, R, b):
    if fam == "XGB":
        try:
            import xgboost  # noqa: F401
        except ImportError:
            return None, {"status": "NOT_AVAILABLE", "reason": "xgboost nie jest zainstalowany"}
    m = T.Tabular(fam, Y.shape[1]).fit(X, Y, R, b["FIT"], b["TUNE"])
    cal = b["CALIBRATION"]
    temps = None
    if fam != "CLASS_FREQ" and len(cal):
        P, Q = m.predict(X[cal])
        temps = [T._temperature(P[:, j], Y[cal, j]) for j in range(Y.shape[1])]
        for j in range(Y.shape[1]):                                   # residual offsets from the independent CALIBRATION block
            mm = np.isfinite(R[cal, j])
            if fam != "CLASS_FREQ" and mm.sum() >= 30 and "beta" in m.p[j]:
                q50 = Q[mm, j, 1]
                m.p[j]["res_q"] = np.quantile(R[cal, j][mm] - q50, (0.1, 0.5, 0.9))
    return (m, temps), {"status": "TRAINED"}


def train(inst: str, d: Path, families: list[str], profile_name: str = "standard", db=None, log=print, cancel=None, ablation: bool = True) -> dict:
    data = load(d)
    man = data["flow_manifest"]
    cur = profile(inst)
    if man["profile"]["hash"] != cur["hash"]:
        return {"status": "STALE_DATASET", "reason": f"profil zmieniony ({man['profile']['hash']} → {cur['hash']})",
                "rebuild": f"python -m masterquo flow-context dataset --asset {inst} --latest"}
    prof = T.PROFILES[profile_name]
    sp = T.split(data)
    b = data["rows_idx"]
    X, Y, R = data["fe"]["F"][b], data["Y"][b].astype(np.int64), data["R"][b].astype(np.float64)
    synthetic = man["data_kind"] != "REAL_USER_DATA"
    rid = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "_" + uuid.uuid4().hex[:4] + ("_FIXTURE" if synthetic else "")
    rd = root(inst) / ("fixture_runs" if synthetic else "runs") / rid
    rd.mkdir(parents=True)
    ev = T.evidence(data, sp, T.TASK_MOVE)
    rep = {"run_id": rid, "task_id": TASK, "schema": SCHEMA, "protocol_id": T.PROTOCOL_ID, "split_hash": sp["hash"], "dataset_id": man["dataset_id"],
           "data_kind": man["data_kind"], "profile": profile_name, "flow_profile": man["profile"], "families": families, "evidence": ev,
           "role": "TEST_ONLY" if synthetic else "RESEARCH", "holdout_from": sp["cut"], "folds": [], "ablations": {},
           "created_at": datetime.now(timezone.utc).isoformat(), "classes": ["DOWN", "FLAT", "UP"], "horizons": list(T.HORIZONS),
           "targets": "raw market BidClose (nigdy Heikin)"}
    fams = ["CLASS_FREQ"] + [f for f in families if f in FAMILIES]
    for f in sp["folds"][-int(prof.get("max_folds") or 4):]:
        if cancel and cancel():
            rep["status"] = "CANCELLED"
            break
        bl = f["blocks"]
        if min(len(v) for v in bl.values()) < 5 or not len(f["eval"]):
            rep["folds"].append({"fold": f["fold"], "status": "INSUFFICIENT_EVIDENCE"})
            continue
        if prof.get("max_fit_rows"):
            bl = dict(bl, FIT=bl["FIT"][-prof["max_fit_rows"]:])
        evr = f["eval"][: prof["max_eval_rows"]] if prof.get("max_eval_rows") else f["eval"]
        fr = {"fold": f["fold"], "status": "OK", "families": {}}
        for fam in fams:
            model, info = _fit(fam, X, Y, R, bl)
            if model is None:
                fr["families"][fam] = info
                continue
            m, temps = model
            P, Q = m.predict(X[evr])
            if temps:
                P = np.stack([T._apply_T(P[:, j], temps[j]["T"]) for j in range(P.shape[1])], axis=1)
            fr["families"][fam] = {"status": "TRAINED", "calibration": temps, "metrics": T.metrics(P, Q, Y[evr], R[evr])}
            log(f"flow fold {f['fold'] + 1} {fam}")
        if ablation and "LOGREG" in fams:
            for name in ABLATIONS:
                cols = [FEATS.index(x) for k, v in ABLATIONS.items() if list(ABLATIONS).index(k) <= list(ABLATIONS).index(name) for x in v]
                Xa = X[:, cols] if cols else np.zeros((len(X), 1))
                m2 = T.Tabular("LOGREG", Y.shape[1]).fit(Xa, Y, R, bl["FIT"], bl["TUNE"])
                P2, Q2 = m2.predict(Xa[evr])
                rep["ablations"].setdefault(name, []).append({"fold": f["fold"], "metrics": T.metrics(P2, Q2, Y[evr], R[evr])})
        rep["folds"].append(fr)
    rep["comparison"] = T._compare({"folds": [{"status": x.get("status"), "families": {k: [v] for k, v in x.get("families", {}).items()}}
                                              for x in rep["folds"]]})
    rep.setdefault("status", "EVALUATED_DEV" if ev["status"] == "OK" else "INSUFFICIENT_EVIDENCE")
    rep["edge_status"] = "NO_VALIDATED_EDGE"
    from ...ml import scalp_task as stk
    fb = stk.inner_blocks(sp["dev"], sp["rows"], sp["embargo_s"])
    rep["candidates"] = {}
    if rep["status"] != "CANCELLED" and min(len(v) for v in fb.values()) >= 5:
        for fam in [f for f in families if f in FAMILIES]:
            model, info = _fit(fam, X, Y, R, fb)
            if model is None:
                rep["candidates"][fam] = info
                continue
            rep["candidates"][fam] = save_candidate(rd / "models" / fam, fam, model, rep, man)
    rep["run_dir"] = str(rd)
    (rd / "report.json").write_text(json.dumps(rep, indent=1, default=T._jd), encoding="utf-8")
    reg = _reg(inst)
    reg["runs"][rid] = {"run_dir": str(rd), "status": rep["status"], "role": rep["role"], "created_at": rep["created_at"]}
    _save_reg(inst, reg)
    return rep


def save_candidate(d: Path, fam: str, model, rep: dict, man: dict) -> dict:
    m, temps = model
    d.mkdir(parents=True, exist_ok=False)
    arrs = {"mu": m.mu, "sd": m.sd}
    if fam == "XGB":
        for j, pj in m.p.items():
            pj["W"].save_model(str(d / f"xgb_h{j}.json"))
            arrs[f"beta_{j}"], arrs[f"resq_{j}"] = pj["beta"], pj["res_q"]
    else:
        for j, pj in m.p.items():
            arrs[f"W_{j}"], arrs[f"beta_{j}"], arrs[f"resq_{j}"] = pj["W"], pj["beta"], pj["res_q"]
    np.savez(d / "tabular.npz", **arrs)
    meta = {"task_id": TASK, "schema": SCHEMA, "features": FEATS, "family": fam, "instrument": man["instrument"], "profile_hash": man["profile"]["hash"],
            "calibration": temps, "role": rep["role"], "dataset_id": man["dataset_id"], "classes": rep["classes"], "horizons": rep["horizons"],
            "n_heads": m.H, "model_hash": hashlib.sha256((d / "tabular.npz").read_bytes()).hexdigest()}
    (d / "candidate.json").write_text(json.dumps(meta, indent=1, default=T._jd), encoding="utf-8")
    return {"candidate_id": f"{rep['run_id']}-{fam}", "model_hash": meta["model_hash"], "status": "TRAINED", "role": rep["role"]}


def load_candidate(d: Path) -> tuple[dict, object]:
    meta = json.loads((d / "candidate.json").read_text(encoding="utf-8"))
    if hashlib.sha256((d / "tabular.npz").read_bytes()).hexdigest() != meta["model_hash"]:
        raise ValueError("MODEL_HASH_MISMATCH")
    if meta.get("schema") != SCHEMA or meta.get("features") != FEATS:
        raise ValueError("INCOMPATIBLE_ARTIFACT: schemat cech")
    m = T.Tabular(meta["family"], meta["n_heads"])
    with np.load(d / "tabular.npz", allow_pickle=False) as z:
        m.mu, m.sd = z["mu"], z["sd"]
        for j in range(m.H):
            if meta["family"] == "XGB":
                import xgboost as xgb
                clf = xgb.XGBClassifier()
                clf.load_model(str(d / f"xgb_h{j}.json"))
                m.p[j] = {"W": clf, "beta": z[f"beta_{j}"], "res_q": z[f"resq_{j}"]}
            else:
                m.p[j] = {"W": z[f"W_{j}"], "beta": z[f"beta_{j}"], "res_q": z[f"resq_{j}"]}
    return meta, m


def _reg(inst: str) -> dict:
    p = root(inst) / "registry.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"runs": {}, "shadow": {}, "history": [], "holdout_access": {}}


def _save_reg(inst: str, reg: dict) -> None:
    p = root(inst) / "registry.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(reg, indent=1), encoding="utf-8")
    tmp.replace(p)


def evaluate_holdout(inst: str, candidate_id: str, protocol_id: str, db=None) -> dict:
    if protocol_id != T.PROTOCOL_ID:
        raise ValueError("PROTOCOL_MISMATCH")
    reg = _reg(inst)
    if candidate_id in reg["holdout_access"]:
        return dict(reg["holdout_access"][candidate_id], status="ALREADY_EVALUATED")
    rid = next((r for r in reg["runs"] if candidate_id.startswith(r + "-")), None)
    if rid is None:
        raise ValueError("RUN_NOT_FOUND")
    fam = candidate_id[len(rid) + 1:]
    rd = Path(reg["runs"][rid]["run_dir"])
    rep = json.loads((rd / "report.json").read_text(encoding="utf-8"))
    meta, m = load_candidate(rd / "models" / fam)
    data = load(root(inst) / "datasets" / rep["dataset_id"])
    sp = T.split(data)
    if sp["hash"] != rep["split_hash"]:
        raise ValueError("SPLIT_MISMATCH")
    hold = sp["hold"]
    from ...ml import scalp_task as stk
    led = stk.reserve_holdout(db, inst, sp["rows"][hold[0]]["signal_time"], sp["rows"][hold[-1]]["label_end"], meta["model_hash"], TASK) \
        if db is not None else {"status": "LEDGER_UNAVAILABLE"}
    b = data["rows_idx"]
    X, Y, R = data["fe"]["F"][b], data["Y"][b], data["R"][b]
    P, Q = m.predict(X[hold])
    if meta["calibration"]:
        P = np.stack([T._apply_T(P[:, j], meta["calibration"][j]["T"]) for j in range(P.shape[1])], axis=1)
    out = {"candidate_id": candidate_id, "ledger": led, "metrics": T.metrics(P, Q, Y[hold], R[hold]), "role": meta["role"],
           "edge_status": "NO_VALIDATED_EDGE (ocena ruchu ≠ polityka z kosztami)", "at": datetime.now(timezone.utc).isoformat()}
    reg["holdout_access"][candidate_id] = out
    _save_reg(inst, reg)
    return dict(out, status="EVALUATED_ONCE")


def select_shadow(inst: str, candidate_id: str) -> dict:
    reg = _reg(inst)
    rid = next((r for r in reg["runs"] if candidate_id.startswith(r + "-")), None)
    if rid is None:
        raise ValueError("RUN_NOT_FOUND")
    d = Path(reg["runs"][rid]["run_dir"]) / "models" / candidate_id[len(rid) + 1:]
    meta, _ = load_candidate(d)
    if meta["role"] == "TEST_ONLY":
        raise ValueError("TEST_ONLY_ARTIFACT")
    prev = reg["shadow"].get(TASK)
    reg["shadow"][TASK] = {"candidate_id": candidate_id, "dir": str(d), "model_hash": meta["model_hash"]}
    reg["history"].append({"from": prev, "to": candidate_id, "at": datetime.now(timezone.utc).isoformat()})
    _save_reg(inst, reg)
    return {"ok": True, "shadow": reg["shadow"][TASK], "execution": "NEVER_AUTOMATIC"}


def rollback(inst: str) -> dict:
    reg = _reg(inst)
    if not reg["history"]:
        raise ValueError("NO_HISTORY")
    prev = reg["history"][-1]["from"]
    if prev is None:
        reg["shadow"].pop(TASK, None)
    else:
        reg["shadow"][TASK] = prev
    reg["history"].append({"from": reg["history"][-1]["to"], "to": prev["candidate_id"] if prev else None, "rollback": True,
                           "at": datetime.now(timezone.utc).isoformat()})
    _save_reg(inst, reg)
    return {"ok": True, "shadow": reg["shadow"].get(TASK)}
