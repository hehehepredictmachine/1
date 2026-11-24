"""Model packages, versions, controlled activation and rollback (PMW-TH-REG-1).

Package = data/trainhub/models/<INSTRUMENT>/<MODEL>_<BASE_TF>_H<h>/<version>/ with
  model.joblib (fitted estimator incl. preprocessing), feature_order.json, feature_schema.json, config.json, metrics.json,
  data_manifest.json (store files + sha256 used for training), deps.json (library versions), inference_sample.json (inputs + the
  probabilities the trained model produced), REPRODUCE.md and package_manifest.json (sha256 of every file).
Training NEVER activates a model. Activation = explicit request + compatibility check (checksums, instrument, feature schema,
library versions) + prediction test (the loaded model must reproduce inference_sample.json) - otherwise INCOMPATIBLE and the
previous active version stays. Rollback restores the previously active version. Packages never contain passwords, tokens or keys.
"""
from __future__ import annotations

import hashlib
import json
import platform
import re
import shutil
import sys
import time
import zipfile
from contextlib import contextmanager
from pathlib import Path

import numpy as np

from ..marketdata.store import atomic_bytes, atomic_json, iso, read_json, sha256_file
from . import features as F

PACKAGE_VERSION = "PMW-TH-PKG-1"
# 1.46: model_key / version become path segments (package_dir) - the same rule as the API's /trainhub/version check (_SAFE)
SAFE_ID = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


def root() -> Path:
    from ..paths import data_dir
    return data_dir() / "trainhub"


def model_key(model_id: str, base_tf: str, horizon: int) -> str:
    return f"{model_id}_{base_tf}_H{int(horizon)}"


def deps() -> dict:
    out = {"python": platform.python_version(), "platform": platform.platform()}
    for m in ("numpy", "sklearn", "joblib", "xgboost", "pyarrow"):
        try:
            mod = __import__(m)
            out[m] = getattr(mod, "__version__", "?")
        except Exception:  # noqa: BLE001
            out[m] = None
    return out


def _mm(v: str | None) -> str | None:
    return ".".join(str(v).split(".")[:2]) if v else None


def save_package(inst: str, cfg: dict, trained: dict, ds_desc: dict, store_manifest: dict, dataset_ref: dict | None = None) -> dict:
    import joblib
    res = trained["result"]
    key = model_key(res["model_id"], cfg["base_tf"], cfg["horizon"])
    import uuid
    # unique run id: timestamp + params hash + random suffix; the directory is created exclusively (two trainings in the same second
    # with the same parameters can never write into one package)
    version = (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + hashlib.sha256(json.dumps(res["params"], sort_keys=True).encode()).hexdigest()[:6]
               + "-" + uuid.uuid4().hex[:6])
    d = root() / "models" / inst / key / version
    d.parent.mkdir(parents=True, exist_ok=True)
    d.mkdir(exist_ok=False)
    tmp = d / "model.joblib.tmp"
    joblib.dump({"estimator": trained["model"], "temperature": res["temperature"]}, tmp)
    tmp.replace(d / "model.joblib")
    if res["model_id"] == "TH_XGB" and hasattr(trained["model"], "get_booster"):
        # native XGBoost model next to the full inference package (features + temperature calibration stay in config / joblib)
        trained["model"].get_booster().save_model(str(d / "model_xgb.json"))
    sch = F.schema(cfg["base_tf"])
    atomic_json(d / "feature_order.json", sch["names"])
    atomic_json(d / "feature_schema.json", sch)
    from .learn import MODELS
    conf = {**cfg, "instrument": inst, "model_id": res["model_id"], "model_name": MODELS[res["model_id"]]["name"],
            "model_key": key, "version": version, "params": res["params"], "temperature": res["temperature"],
            "decision_threshold": res["decision_threshold"], "task": "DIRECTION_H", "classes": ["DOWN", "FLAT", "UP"],
            "label": f"klasa ruchu zamknięcia {cfg['base_tf']} za {cfg['horizon']} świec po kosztach (próg max({cfg['k_atr']}xATR14, koszt))",
            "package_version": PACKAGE_VERSION}
    atomic_json(d / "config.json", conf)
    metrics = {k: v for k, v in res.items() if k != "sample"}
    atomic_json(d / "metrics.json", metrics)
    if dataset_ref is None:                       # arch146 I0064: lineage of the training set (training/dataset_ref.py)
        from ..training import dataset_ref as DR
        dataset_ref = DR.from_store(inst, store_manifest, sha256=ds_desc.get("hash"), range_utc=ds_desc.get("range_utc"),
                                    rows=ds_desc.get("rows_usable"))
    atomic_json(d / "data_manifest.json", {"instrument": inst, "symbol": store_manifest.get("symbol"), "data_kind": store_manifest.get("data_kind"),
                                           "dataset": ds_desc, "time_model": store_manifest.get("time_model"),
                                           "costs": store_manifest.get("costs"), "store_schema": store_manifest.get("schema_version"),
                                           "dataset_ref": dataset_ref})
    atomic_json(d / "deps.json", deps())
    atomic_json(d / "inference_sample.json", res["sample"])
    atomic_bytes(d / "REPRODUCE.md", _reproduce(inst, conf, ds_desc).encode("utf-8"))
    files = {p.name: sha256_file(p) for p in sorted(d.iterdir()) if p.is_file() and p.name != "package_manifest.json"}
    atomic_json(d / "package_manifest.json", {"package_version": PACKAGE_VERSION, "instrument": inst, "model_key": key, "version": version,
                                              "created_at": iso(time.time()), "files": files})
    with reg_lock(inst):                          # 1.46: read-modify-write of registry.json under the shared registry lock
        reg = _reg(inst, strict=True)
        reg.setdefault("versions", {}).setdefault(key, []).append(
            version_entry(version=version, created_at=iso(time.time()), model_id=res["model_id"], base_tf=cfg["base_tf"], horizon=cfg["horizon"],
                          data_kind=store_manifest.get("data_kind"), metrics=res, path=str(d.relative_to(root()))))
        _save_reg(inst, reg)
    return {"model_key": key, "version": version, "path": str(d)}


def version_entry(*, version: str, created_at, model_id, base_tf, horizon, data_kind, metrics: dict, path: str | None) -> dict:
    """One registry.json version entry (arch146 I0643: the SAME fields for a trained and for a Studio-imported package - the import wrote
    only version / created_at / source / import_id / package, so dev_skill() was None (weight 0 in the evidence board) and the panel showed
    no metrics and no data kind, a SYNTHETIC Studio package was not marked as such)."""
    return {"version": version, "created_at": created_at, "model_id": model_id, "base_tf": base_tf, "horizon": horizon, "data_kind": data_kind,
            "holdout": metrics.get("holdout"), "walk_forward": {k: v for k, v in (metrics.get("walk_forward") or {}).items() if k != "folds"},
            "trading_eval_holdout": metrics.get("trading_eval_holdout"), "path": path}


def package_entry(inst: str, key: str, version: str) -> dict | None:
    """The version entry rebuilt from the files of a package on disk (config.json, metrics.json, data_manifest.json, package_manifest.json);
    None when the names are not safe path segments or the package has no config / metrics. Read only."""
    if not (SAFE_ID.match(str(key or "")) and SAFE_ID.match(str(version or ""))):
        return None
    d = package_dir(inst, key, version)
    conf, met = read_json(d / "config.json", None), read_json(d / "metrics.json", None)
    if not isinstance(conf, dict) or not isinstance(met, dict):
        return None
    dm = read_json(d / "data_manifest.json", {}) or {}
    man = read_json(d / "package_manifest.json", {}) or {}
    return version_entry(version=version, created_at=man.get("created_at"), model_id=conf.get("model_id") or met.get("model_id"),
                         base_tf=conf.get("base_tf"), horizon=conf.get("horizon"), data_kind=dm.get("data_kind") if isinstance(dm, dict) else None,
                         metrics=met, path=str(d.relative_to(root())))


def version_info(inst: str, key: str, v: dict) -> dict:
    """A registry entry with the metadata of its package: an entry written by a Studio import before 1.46 arch (no walk_forward) is
    completed from the package files (read only - registry.json is not rewritten); fields present in the entry win."""
    if not isinstance(v, dict) or "walk_forward" in v:
        return v
    pe = package_entry(inst, key, v.get("version"))
    return v if pe is None else {**{k: x for k, x in pe.items() if k != "created_at"}, **v}


def _reproduce(inst: str, conf: dict, ds: dict) -> str:
    return (f"# Odtworzenie modelu {conf['model_key']} ({inst}) – wersja {conf['version']}\n\n"
            f"1. Dane: magazyn świec `data/marketdata/{inst}` z plikami i sumami SHA-256 z `data_manifest.json` (dataset {ds.get('hash')}).\n"
            f"   Eksport: `python -m masterquo trainhub export --instrument {inst}` (przyrostowo) albo import folderu z innej maszyny.\n"
            f"2. Trening: `python -m masterquo trainhub train --instrument {inst} --models {conf['model_id']} --base-tf {conf['base_tf']} "
            f"--horizon {conf['horizon']} --k-atr {conf['k_atr']} --seed {conf.get('seed', 7)}`"
            + (f" --from {conf['start']}" if conf.get("start") else "") + (f" --to {conf['end']}" if conf.get("end") else "") + "\n"
            "3. Wersje bibliotek: `deps.json`. Te same dane + te same wersje + ten sam seed = te same metryki (z dokładnością do arytmetyki "
            "zmiennoprzecinkowej platformy).\n4. Aktywacja: wyłącznie ręcznie w Centrum treningu (test zgodności i predykcji).\n")


def _reg_path(inst: str) -> Path:
    return root() / "models" / inst / "registry.json"


def _reg(inst: str, *, strict: bool = False) -> dict:
    """strict=True inside reg_lock for every writer (1.46 arch): an unreadable registry.json raised nothing and was rewritten with only
    the new change (every version, the active packages and the history were lost) - masterquo/registry_io.py."""
    from .. import registry_io as RIO
    return RIO.read_json(_reg_path(inst), lambda: {"versions": {}, "active": {}, "history": []}, strict=strict)


def _save_reg(inst: str, reg: dict) -> None:
    _reg_path(inst).parent.mkdir(parents=True, exist_ok=True)
    atomic_json(_reg_path(inst), reg)


def register_imported_version(inst: str, key: str, entry: dict) -> None:
    """1.46 arch: a version copied in from a Studio package - the same locked, strict read-modify-write as save_package (the importer
    wrote registry.json through _reg/_save_reg without reg_lock: a concurrent training or activation lost its change)."""
    with reg_lock(inst):
        reg = _reg(inst, strict=True)
        reg.setdefault("versions", {}).setdefault(key, []).append(dict(entry))
        _save_reg(inst, reg)


@contextmanager
def reg_lock(inst: str, timeout_s: float = 60.0):
    """1.46: registry.json was rewritten read-modify-write without any lock while the training process (save_package) and the panel
    (activate / rollback / deactivate / remove_version) wrote it concurrently - the later writer dropped the other's new version or
    activation. One exclusive OS file lock per instrument (models/<inst>/registry.lock) plus a thread lock; re-entrant in the same
    thread. 1.46 arch: the implementation moved to masterquo/registry_io.file_lock (one lock for every registry of the bot)."""
    from .. import registry_io as RIO
    with RIO.file_lock(_reg_path(inst).with_name("registry.lock"), timeout_s):
        yield


def registry(inst: str) -> dict:
    return _reg(inst)


def package_dir(inst: str, key: str, version: str) -> Path:
    return root() / "models" / inst / key / version


def verify_package(inst: str, key: str, version: str) -> dict:
    d = package_dir(inst, key, version)
    man = read_json(d / "package_manifest.json", None)
    if man is None:
        return {"ok": False, "reason": "brak package_manifest.json"}
    bad = [n for n, h in man["files"].items() if not (d / n).exists() or sha256_file(d / n) != h]
    if bad:
        return {"ok": False, "reason": f"sumy kontrolne niezgodne: {', '.join(bad)}"}
    if man.get("instrument") != inst:
        return {"ok": False, "reason": f"paczka dla {man.get('instrument')}, nie {inst}"}
    return {"ok": True}


def compatibility(inst: str, key: str, version: str) -> dict:
    """Checks before loading: package integrity, instrument, feature schema of THIS code, library versions."""
    d = package_dir(inst, key, version)
    checks = []
    v = verify_package(inst, key, version)
    checks.append({"check": "integralność paczki (sha256)", "ok": v["ok"], "detail": v.get("reason")})
    conf = read_json(d / "config.json", {}) or {}
    sch = read_json(d / "feature_schema.json", {}) or {}
    cur = F.schema(conf.get("base_tf") or "M5")
    checks.append({"check": "wersja schematu cech", "ok": sch.get("version") == F.FEATURE_SCHEMA and sch.get("hash") == cur["hash"],
                   "detail": f"paczka {sch.get('version')}/{sch.get('hash')}, kod {F.FEATURE_SCHEMA}/{cur['hash']}"})
    checks.append({"check": "kolejność cech", "ok": (read_json(d / "feature_order.json", []) or []) == cur["names"], "detail": None})
    dp, now = read_json(d / "deps.json", {}) or {}, deps()
    for lib in ("sklearn", "numpy") + (("xgboost",) if conf.get("model_id") == "TH_XGB" else ()):
        ok = _mm(dp.get(lib)) == _mm(now.get(lib)) and now.get(lib) is not None
        checks.append({"check": f"wersja {lib}", "ok": ok, "detail": f"paczka {dp.get(lib)}, środowisko {now.get(lib)}"})
    return {"ok": all(c["ok"] for c in checks), "checks": checks}


def load(inst: str, key: str, version: str):
    """Loads a package only after the compatibility check; raises on mismatch (inference is blocked, never silently degraded)."""
    comp = compatibility(inst, key, version)
    if not comp["ok"]:
        raise IncompatiblePackage("; ".join(f"{c['check']}: {c['detail']}" for c in comp["checks"] if not c["ok"]))
    import joblib
    d = package_dir(inst, key, version)
    obj = joblib.load(d / "model.joblib")
    return obj, read_json(d / "config.json", {}), read_json(d / "feature_schema.json", {})


class IncompatiblePackage(RuntimeError):
    pass


def predict_loaded(obj: dict, X: np.ndarray) -> np.ndarray:
    from .learn import calibrate, proba3
    return calibrate(proba3(obj["estimator"], X), obj["temperature"])


def prediction_test(inst: str, key: str, version: str) -> dict:
    from .learn import proba3
    d = package_dir(inst, key, version)
    obj, conf, _ = load(inst, key, version)
    smp = read_json(d / "inference_sample.json", {}) or {}
    X = np.asarray(smp.get("X") or [], dtype=float)
    if not len(X):
        return {"ok": False, "reason": "brak próbki inferencji w paczce"}
    got = proba3(obj["estimator"], X)
    diff = float(np.max(np.abs(got - np.asarray(smp["p_raw"], dtype=float))))
    out = {"ok": diff <= 1e-9, "max_abs_diff": diff, "rows": int(len(X))}
    if smp.get("p_final") is not None:                     # the FINAL output (raw -> temperature calibration) is compared too
        fin = predict_loaded(obj, X)
        dfin = float(np.max(np.abs(fin - np.asarray(smp["p_final"], dtype=float))))
        out.update(max_abs_diff_final=dfin, ok=out["ok"] and dfin <= 1e-9)
    return out


def activate(inst: str, key: str, version: str, *, reason: str = "panel") -> dict:
    reg = _reg(inst)
    if not any(v["version"] == version for v in reg.get("versions", {}).get(key, [])):
        return {"ok": False, "status": "NOT_FOUND", "reason": f"brak wersji {version} modelu {key}"}
    # 1.46: the slow checks below run WITHOUT the registry lock; the registry is re-read under the lock afterwards - 1.45.0 saved the copy
    # read here, erasing a version the training process had added (or an activation / rollback done) in the meantime
    comp = compatibility(inst, key, version)
    if not comp["ok"]:
        return {"ok": False, "status": "INCOMPATIBLE", "compatibility": comp, "reason": "test zgodności nie przeszedł – aktywna wersja bez zmian"}
    try:
        pt = prediction_test(inst, key, version)
    except Exception as exc:  # noqa: BLE001
        pt = {"ok": False, "reason": f"{type(exc).__name__}: {exc}"[:300]}
    if not pt["ok"]:
        return {"ok": False, "status": "INCOMPATIBLE", "compatibility": comp, "prediction_test": pt,
                "reason": "test predykcji po wczytaniu nie przeszedł – aktywna wersja bez zmian"}
    with reg_lock(inst):
        reg = _reg(inst, strict=True)
        if not any(v["version"] == version for v in reg.get("versions", {}).get(key, [])):
            return {"ok": False, "status": "NOT_FOUND", "reason": f"wersja {version} modelu {key} usunięta w trakcie aktywacji"}
        prev = reg.setdefault("active", {}).get(key)
        reg["active"][key] = version
        reg.setdefault("history", []).append({"at": iso(time.time()), "model_key": key, "action": "ACTIVATE", "version": version, "previous": prev,
                                              "reason": reason, "prediction_test": pt})
        _save_reg(inst, reg)
    return {"ok": True, "status": "ACTIVE", "model_key": key, "version": version, "previous": prev, "compatibility": comp, "prediction_test": pt}


def _active_chain(reg: dict, key: str) -> list:
    """1.46: the versions active one after another (oldest first), replayed from the history: ACTIVATE pushes, ROLLBACK pops back to its
    target, DEACTIVATE empties the chain (nothing was active)."""
    st: list = []
    for h in reg.get("history") or []:
        if h.get("model_key") != key:
            continue
        a, v = h.get("action"), h.get("version")
        if a == "ACTIVATE" and v:
            if not st or st[-1] != v:
                st.append(v)
        elif a == "ROLLBACK":
            if st:
                st.pop()
            while st and v and st[-1] != v:
                st.pop()
            if v is None:
                st.clear()
            elif not st:
                st.append(v)
        elif a == "DEACTIVATE":
            st.clear()
    return st


def rollback(inst: str, key: str) -> dict:
    reg = _reg(inst)
    cur = (reg.get("active") or {}).get(key)
    if not cur:
        return {"ok": False, "status": "NOTHING_TO_ROLLBACK", "active": None, "previous": None, "reason": f"brak aktywnej wersji {key} – nie ma czego cofać"}
    # 1.46: the previous version comes from the chain of activations - 1.45.0 looked only at the LAST ACTIVATE entry, so a second rollback
    # (whose last ACTIVATE was the version just rolled back) found nothing and silently DISABLED the model with status ROLLED_BACK
    known = {v.get("version") for v in (reg.get("versions") or {}).get(key, [])}
    st = _active_chain(reg, key)
    if st and st[-1] == cur:
        cand = [v for v in reversed(st[:-1]) if v != cur]
    else:                                                  # history inconsistent with the active version (older files): 1.45.0 rule
        hist = [h for h in reg.get("history", []) if h["model_key"] == key and h["action"] == "ACTIVATE"]
        cand = [hist[-1]["previous"]] if hist and hist[-1]["version"] == cur and hist[-1].get("previous") else []
    prev = next((v for v in cand if v in known), None)
    if not prev:
        return {"ok": False, "status": "NOTHING_TO_ROLLBACK", "active": cur, "previous": None,
                "reason": "brak wcześniejszej aktywnej wersji – aktywna wersja bez zmian (wyłączenie modelu: „Dezaktywuj”)"}
    comp = compatibility(inst, key, prev)
    if not comp["ok"]:
        return {"ok": False, "status": "INCOMPATIBLE", "reason": "poprzednia wersja niezgodna z bieżącym kodem", "compatibility": comp}
    with reg_lock(inst):
        reg = _reg(inst, strict=True)
        if (reg.get("active") or {}).get(key) != cur:
            return {"ok": False, "status": "CONFLICT", "active": (reg.get("active") or {}).get(key), "previous": None,
                    "reason": "aktywna wersja zmieniła się w trakcie – rollback nie wykonany, odśwież i ponów"}
        reg.setdefault("active", {})[key] = prev
        reg.setdefault("history", []).append({"at": iso(time.time()), "model_key": key, "action": "ROLLBACK", "version": prev, "previous": cur})
        _save_reg(inst, reg)
    return {"ok": True, "status": "ROLLED_BACK", "active": prev, "previous": cur}


def deactivate(inst: str, key: str) -> dict:
    with reg_lock(inst):                          # 1.46: under the registry lock (see reg_lock)
        reg = _reg(inst, strict=True)
        cur = (reg.get("active") or {}).pop(key, None)
        reg.setdefault("history", []).append({"at": iso(time.time()), "model_key": key, "action": "DEACTIVATE", "version": None, "previous": cur})
        _save_reg(inst, reg)
    return {"ok": True, "status": "DISABLED", "previous": cur}


def export_zip(inst: str, key: str, version: str, out: Path) -> Path:
    d = package_dir(inst, key, version)
    v = verify_package(inst, key, version)
    if not v["ok"]:
        raise IncompatiblePackage(v["reason"])
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(d.iterdir()):
            if p.is_file():
                z.write(p, f"{inst}_{key}_{version}/{p.name}")
    return out


def remove_version(inst: str, key: str, version: str) -> None:
    with reg_lock(inst):                          # 1.46: the active check and the write see the same registry (see reg_lock)
        reg = _reg(inst, strict=True)
        if (reg.get("active") or {}).get(key) == version:
            raise ValueError("nie można usunąć aktywnej wersji")
        reg.setdefault("versions", {})[key] = [v for v in reg.get("versions", {}).get(key, []) if v["version"] != version]
        _save_reg(inst, reg)
    shutil.rmtree(package_dir(inst, key, version), ignore_errors=True)


NO_SERVICE_REASON = "serwis inferencji Centrum treningu nie działa w tym procesie – brak predykcji aktywnej wersji"


def status_of(inst: str, model_id: str | None = None, rt=None) -> dict:
    """arch146 I0010: ONE state of the trainhub models of an instrument - the catalog (modelhub/catalog), the SH probe th_direction
    (sh/models), the Quant inventory and the TH_RF / TH_XGB / TH_SVM family view computed it four times with different results (an active
    version without a prediction was SHADOW_ONLY / BLOCKED_DATA / SHADOW_ONLY / CANDIDATE). Read only; never raises for a missing service.

    model_id: one trainhub model (TH_LOGREG ...) or None = every model (the SH row th_direction). Package keys always match '<model_id>_'.
    rt: the running bot (trainhub jobs + live predictions) or None = no live view (generated report, the SH cycle's own matrix).
    Returns {state, reason, cause, active, versions}; state in the catalog vocabulary (modelhub/contract.STATES): TRAINING | DISABLED |
    READY | BLOCKED_DATA | INCOMPATIBLE | ERROR | NOT_TRAINED; cause tells the consumers apart what one state covers:
    TRAINING, NO_LIBRARY, NO_ACTIVE (versions, none active), NO_LIVE_VIEW (rt None), NO_SERVICE (bot without the inference service),
    SERVICE_ERROR, PREDICTION (state of the live prediction), WAITING (active, no prediction yet), None (READY / NOT_TRAINED)."""
    reg = registry(inst)
    pref = (model_id + "_") if model_id else ""
    keys = [k for k in (reg.get("versions") or {}) if k.startswith(pref)]
    act = {k: v for k, v in (reg.get("active") or {}).items() if k.startswith(pref)}
    nver = sum(len((reg.get("versions") or {}).get(k) or []) for k in keys)
    out = {"active": act, "versions": keys, "n_versions": nver}

    def res(state, reason, cause=None):
        return {"state": state, "reason": reason, "cause": cause, **out}
    if model_id:
        running = set()
        try:
            tc = getattr(rt, "trainhub", None) if rt is not None else None
            if tc is not None:
                for j in tc.list(20):
                    if j["status"] in ("RUNNING", "QUEUED") and j["instrument"] == inst and j["kind"] in ("TRAIN", "FULL"):
                        running.update((j.get("params") or {}).get("models") or ["TH_BASELINE", "TH_LOGREG", "TH_HGB"])
        except Exception:  # noqa: BLE001, S110 - the job list is optional
            pass
        if model_id in running:
            return res("TRAINING", "zadanie treningu w Centrum treningu", "TRAINING")
        from .learn import available
        if not available().get(model_id):
            return res("DISABLED", "biblioteka modelu niedostępna w tym środowisku", "NO_LIBRARY")
    if act:
        desc = ", ".join(f"{k}={v}" for k, v in act.items())
        if rt is None:
            return res("DISABLED", NO_SERVICE_REASON, "NO_LIVE_VIEW")
        try:
            inf = getattr(rt, "trainhub_inference", None)
            if inf is None:
                return res("DISABLED", NO_SERVICE_REASON, "NO_SERVICE")
            preds = {p.get("model_key"): p for p in inf.predictions(inst)}
        except Exception as exc:  # noqa: BLE001
            return res("ERROR", f"inferencja Centrum treningu: {type(exc).__name__}: {exc}"[:200], "SERVICE_ERROR")
        ps = [preds.get(k) for k in act]
        bad = [p for p in ps if p and p.get("state") != "READY"]
        if bad:
            return res(bad[0]["state"], bad[0].get("unavailable_reason"), "PREDICTION")
        if all(ps):
            return res("READY", "aktywna wersja: " + desc)
        # 1.46: READY means a result exists (PMW-PRED-2) - an active version without any prediction yet is waiting for data
        return res("BLOCKED_DATA", "aktywna wersja bez predykcji (czeka na pierwszą zamkniętą świecę): " + desc, "WAITING")
    if keys:
        # 1.46: the message said "none inactive" (= all active) in the branch where NO version is active
        return res("DISABLED", f"{nver} wersji, żadna nie jest aktywna – aktywacja ręczna w Centrum treningu", "NO_ACTIVE")
    return res("NOT_TRAINED", "brak paczki – trening w Centrum treningu")


def summary(inst: str) -> dict:
    reg = _reg(inst)
    out = []
    for key, vers in (reg.get("versions") or {}).items():
        act = (reg.get("active") or {}).get(key)
        for v in vers:
            out.append({**version_info(inst, key, v), "model_key": key, "active": v["version"] == act})   # arch146 I0643: old imports
    def _when(v):                                   # 1.46: tolerant to a numeric created_at written by Studio 1.45.0 imports
        c = v.get("created_at")
        if isinstance(c, (int, float)):
            from ..marketdata.store import iso as _iso
            return _iso(c)
        return str(c or "")
    return {"instrument": inst, "versions": sorted(out, key=_when, reverse=True), "active": reg.get("active") or {},
            "history": (reg.get("history") or [])[-30:], "python": sys.version.split()[0]}
