"""SH target-event model: P(TP2 before SL within the strategy horizon) for exactly the strategy's TP grid and SL rule.
Trained on replay labels of the strategy's OWN setups (sh/replay.py), chronological split with purge, Platt calibration on the
calibration block, holdout evaluated once. Status READY only when the holdout gate passed; otherwise the strategies run in the
predefined LIMITED mode (score only, AUTO blocked)."""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import numpy as np

FEATURES = ["sl_atr1", "tp2_atr5", "atr_ratio", "vamd_m5", "vamd_m1", "fd_trend", "fd_chop", "htf_align", "mode_rev", "side_buy",
            "spread_atr1", "net_rr", "obstacle_tp", "regime_trend", "hour_sin", "hour_cos"]
VERSION = "SH-TPMODEL-1.0.0"


def root(inst: str, strategy: str | None = None) -> Path:
    from .. import paths
    d = paths.data_dir() / "sh" / "models" / inst
    if strategy:
        d = d / strategy
    d.mkdir(parents=True, exist_ok=True)
    return d


def features(setup: dict, snap: dict) -> list[float]:
    vol = snap.get("vol") or {}
    a1, a5 = vol.get("atr_m1") or 1e-9, vol.get("atr_m5") or 1e-9
    ctx = snap.get("ctx") or {}
    side = 1.0 if setup.get("side") == "BUY" else -1.0
    sl = abs((setup.get("entry_ref") or 0) - (setup.get("sl") or 0))
    tp2 = (setup.get("tps") or [{}, {}])[1].get("distance_actual") or 0.0
    s60 = snap.get("structure_H1") or {}
    h = s60.get("major") if s60.get("major") in ("UP", "DOWN") else s60.get("internal")
    import datetime as _d
    hr = _d.datetime.fromtimestamp(setup.get("created_at") or time.time(), tz=_d.timezone.utc).hour
    obs = [x for x in (setup.get("args_against") or []) if "przeszkoda" in x]
    return [sl / a1, tp2 / a5, a1 / a5, (ctx.get("vamd_m5") or 0.0) * side, (ctx.get("vamd_m1") or 0.0) * side,
            float(ctx.get("fd_zone_m5") == "TREND"), float(ctx.get("fd_zone_m5") == "CHOP"),
            float((h == "UP" and side > 0) or (h == "DOWN" and side < 0)) - float((h == "DOWN" and side > 0) or (h == "UP" and side < 0)),
            float(setup.get("mode") == "REVERSAL"), float(side > 0), ((snap.get("data") or {}).get("spread") or 0.0) / a1,
            float(setup.get("net_rr") or 0.0), float(bool(obs)), float(str((snap.get("regime") or {}).get("state", "")).startswith("TREND")),
            float(np.sin(2 * np.pi * hr / 24)), float(np.cos(2 * np.pi * hr / 24))]


def status(inst: str, strategy: str | None = None) -> dict:
    out = {}
    for strat in ([strategy] if strategy else ["SCALPING", "HEDGING"]):
        p = root(inst, strat) / "registry.json"
        if not p.exists():
            out[strat] = {"status": "NOT_TRAINED", "reason": "brak modelu zdarzenia – uruchom trening sh_models (panel Trening / runner)"}
            continue
        reg = json.loads(p.read_text(encoding="utf-8"))
        act = reg.get("active")
        if not act:
            last = (reg.get("runs") or [{}])[-1]
            out[strat] = {"status": "SHADOW_ONLY" if reg.get("runs") else "NOT_TRAINED",
                          "reason": f"ostatni run {last.get('run_id')}: {last.get('verdict')} – nie przeszedł bramki holdout" if last else "brak runów"}
            continue
        out[strat] = {"status": "READY", "reason": f"model {act} (holdout zaliczony)", "version": act}
    if strategy:
        return out[strategy]
    st = [v["status"] for v in out.values()]
    return {"status": "READY" if all(s == "READY" for s in st) else ("SHADOW_ONLY" if "SHADOW_ONLY" in st or "READY" in st else "NOT_TRAINED"),
            "reason": "; ".join(f"{k}: {v['reason']}" for k, v in out.items()), "per_strategy": out}


def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -40, 40)))


def _fit_logreg(X, y, l2=1.0, iters=400, lr=0.1):
    w = np.zeros(X.shape[1])
    b = 0.0
    for _ in range(iters):
        p = _sigmoid(X @ w + b)
        g = p - y
        w -= lr * (X.T @ g / len(y) + l2 * w / len(y))
        b -= lr * g.mean()
    return w, b


def train(inst: str, strategy: str, samples: list[dict], *, embargo_s: float, min_n: int = 200, log=print, allow_promotion: bool = True,
          provenance: dict | None = None) -> dict:
    """samples: [{t, x: [features], y: 0/1}] in time order (labels from the strategy replay). Chronological split
    60 % fit / 20 % calibration / 20 % holdout, purge embargo_s between blocks; scaler and model on FIT only; Platt on CAL;
    holdout touched once. Gate: holdout Brier better than the base rate by > 2 SE (paired) AND ≥ min_n samples."""
    rid = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + hashlib.sha1(os.urandom(8)).hexdigest()[:4]
    d = root(inst, strategy)
    reg_p = d / "registry.json"
    reg = json.loads(reg_p.read_text(encoding="utf-8")) if reg_p.exists() else {"active": None, "runs": [], "history": []}
    rec = {"run_id": rid, "version": VERSION, "n": len(samples), "created_at": time.time(), "features": FEATURES, "provenance": provenance or {},
           "seed": "deterministyczny (regresja logistyczna, bez losowości)", "promoted": False}
    if len(samples) < min_n:
        rec.update(verdict="INSUFFICIENT_DATA", reason=f"{len(samples)} < {min_n} setupów z etykietą")
        reg["runs"].append(rec)
        _save_reg(reg_p, reg)
        log(f"sh_tp_model {inst}/{strategy}: INSUFFICIENT_DATA ({len(samples)} < {min_n})")
        return rec
    t = np.array([s["t"] for s in samples], float)
    X = np.array([s["x"] for s in samples], float)
    y = np.array([s["y"] for s in samples], float)
    n = len(y)
    i1, i2 = int(0.6 * n), int(0.8 * n)
    fit = np.where(t < t[i1] - embargo_s)[0]
    cal = np.where((t >= t[i1]) & (t < t[i2] - embargo_s))[0]
    hold = np.where(t >= t[i2])[0]
    mu, sd = X[fit].mean(0), X[fit].std(0) + 1e-9
    Z = (X - mu) / sd
    w, b = _fit_logreg(Z[fit], y[fit])
    raw = Z @ w + b
    a, c = _fit_logreg(raw[cal].reshape(-1, 1), y[cal], l2=0.01)            # Platt on the calibration block only
    p = _sigmoid(raw * a[0] + c)
    base = y[fit].mean()
    brier_h = float(np.mean((p[hold] - y[hold]) ** 2))
    brier_base = float(np.mean((base - y[hold]) ** 2))
    bins = np.clip((p[hold] * 5).astype(int), 0, 4)
    calib = [{"bin": int(k), "n": int((bins == k).sum()), "p_mean": float(p[hold][bins == k].mean()), "y_rate": float(y[hold][bins == k].mean())}
             for k in range(5) if (bins == k).any()]
    # gate: holdout Brier better than the base rate by a margin that is significant for this sample (paired difference
    # > 2 standard errors) - a pure-noise model can beat the base rate by chance and must not be promoted
    dlt = (base - y[hold]) ** 2 - (p[hold] - y[hold]) ** 2
    se = float(dlt.std(ddof=1) / np.sqrt(len(dlt))) if len(dlt) > 1 else float("inf")
    passed = float(dlt.mean()) > 2.0 * se and len(hold) >= max(30, min_n // 5)
    rec.update(split={"fit": int(len(fit)), "cal": int(len(cal)), "holdout": int(len(hold)), "embargo_s": embargo_s},
               holdout={"brier": brier_h, "brier_base_rate": brier_base, "brier_gain": float(dlt.mean()), "brier_gain_se": se, "base_rate": float(base), "calibration": calib},
               verdict="HOLDOUT_PASSED" if passed else "HOLDOUT_FAILED")
    np.savez(d / f"{rid}.npz", mu=mu, sd=sd, w=w, b=np.array([b]), a=a, c=np.array([c]))
    rec["sha256"] = hashlib.sha256((d / f"{rid}.npz").read_bytes()).hexdigest()
    if passed and not allow_promotion:
        rec["reason"] = "dane syntetyczne/testowe – model techniczny, bez promocji"
    reg["runs"].append(rec)
    if passed and allow_promotion:                                          # promotion is atomic; previous kept for rollback
        reg["history"].append({"from": reg.get("active"), "to": rid, "at": time.time()})
        reg["active"] = rid
        rec["promoted"] = True
    _save_reg(reg_p, reg)
    log(f"sh_tp_model {inst}/{strategy}: {rec['verdict']} (holdout Brier {brier_h:.4f} vs base {brier_base:.4f})")
    return rec


def _save_reg(reg_p: Path, reg: dict) -> None:
    tmp = reg_p.with_suffix(".tmp")
    tmp.write_text(json.dumps(reg, indent=1), encoding="utf-8")
    os.replace(tmp, reg_p)


def _reg(inst: str, strategy: str) -> tuple[Path, dict]:
    reg_p = root(inst, strategy) / "registry.json"
    reg = json.loads(reg_p.read_text(encoding="utf-8")) if reg_p.exists() else {"active": None, "runs": [], "history": []}
    return reg_p, reg


def rollback(inst: str, strategy: str) -> dict:
    reg_p, reg = _reg(inst, strategy)
    if not reg.get("history"):
        raise ValueError("BRAK_HISTORII")
    h = reg["history"].pop()
    reg["active"] = h["from"]
    _save_reg(reg_p, reg)
    return {"active": reg["active"]}


def compatible(run: dict) -> tuple[bool, str]:
    if run.get("features") != FEATURES:
        return False, "schemat cech niezgodny z bieżącą wersją"
    if str(run.get("version", "")).split(".")[0] != VERSION.split(".")[0]:
        return False, f"wersja {run.get('version')} niezgodna z {VERSION}"
    return True, "zgodny"


def promote(inst: str, strategy: str, run_id: str) -> dict:
    """Explicit promotion of a stored run: only HOLDOUT_PASSED on real data, compatible schema and intact file. Atomic, reversible."""
    reg_p, reg = _reg(inst, strategy)
    run = next((r for r in reg["runs"] if r["run_id"] == run_id), None)
    if not run:
        raise ValueError("BRAK_RUNU")
    ok, why = compatible(run)
    if not ok:
        raise ValueError("NIEZGODNY:" + why)
    if run.get("verdict") != "HOLDOUT_PASSED":
        raise ValueError(f"RUN_NIE_PRZESZEDŁ_BRAMKI:{run.get('verdict')}")
    if (run.get("provenance") or {}).get("data_kind") not in (None, "REAL_USER_DATA"):
        raise ValueError("DANE_TESTOWE_BEZ_PROMOCJI")
    f = root(inst, strategy) / f"{run_id}.npz"
    if not f.exists() or hashlib.sha256(f.read_bytes()).hexdigest() != run.get("sha256"):
        raise ValueError("PLIK_MODELU_USZKODZONY")
    if reg.get("active") == run_id:
        return {"active": run_id, "changed": False}
    reg["history"].append({"from": reg.get("active"), "to": run_id, "at": time.time(), "by": "promote"})
    reg["active"] = run_id
    _save_reg(reg_p, reg)
    return {"active": run_id, "changed": True}


def import_run(inst: str, strategy: str, run: dict, npz_bytes: bytes) -> dict:
    """Import of an exported run (never activated by the import): checksum and schema compatibility are verified; the run is
    stored as a candidate and can be promoted explicitly."""
    if hashlib.sha256(npz_bytes).hexdigest() != run.get("sha256"):
        raise ValueError("SUMA_KONTROLNA_NIEZGODNA")
    ok, why = compatible(run)
    reg_p, reg = _reg(inst, strategy)
    if any(r["run_id"] == run["run_id"] for r in reg["runs"]):
        return {"imported": False, "reason": "RUN_JUŻ_ISTNIEJE", "compatible": ok}
    f = root(inst, strategy) / f"{run['run_id']}.npz"
    tmp = f.with_suffix(".tmp")
    tmp.write_bytes(npz_bytes)
    os.replace(tmp, f)
    reg["runs"].append({**run, "imported_at": time.time(), "imported": True, "promoted": False, "compatible": ok, "compatibility": why})
    _save_reg(reg_p, reg)
    return {"imported": True, "compatible": ok, "compatibility": why, "active_unchanged": reg.get("active")}


def predict(inst: str, strategy: str, x: list[float]) -> dict:
    reg_p = root(inst, strategy) / "registry.json"
    if not reg_p.exists():
        return {"status": "NOT_TRAINED"}
    reg = json.loads(reg_p.read_text(encoding="utf-8"))
    act = reg.get("active")
    if not act:
        return {"status": "NOT_TRAINED"}
    run = next(r for r in reg["runs"] if r["run_id"] == act)
    f = root(inst, strategy) / f"{act}.npz"
    if hashlib.sha256(f.read_bytes()).hexdigest() != run.get("sha256") or run.get("features") != FEATURES:
        return {"status": "INCOMPATIBLE", "reason": "hash lub schemat cech niezgodny"}
    with np.load(f, allow_pickle=False) as z:
        raw = ((np.array(x) - z["mu"]) / z["sd"]) @ z["w"] + z["b"][0]
        p = float(_sigmoid(raw * z["a"][0] + z["c"][0]))
    return {"status": "READY", "p": p, "version": act}
