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


def save_package(inst: str, cfg: dict, trained: dict, ds_desc: dict, store_manifest: dict) -> dict:
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
    atomic_json(d / "data_manifest.json", {"instrument": inst, "symbol": store_manifest.get("symbol"), "data_kind": store_manifest.get("data_kind"),
                                           "dataset": ds_desc, "time_model": store_manifest.get("time_model"),
                                           "costs": store_manifest.get("costs"), "store_schema": store_manifest.get("schema_version")})
    atomic_json(d / "deps.json", deps())
    atomic_json(d / "inference_sample.json", res["sample"])
    atomic_bytes(d / "REPRODUCE.md", _reproduce(inst, conf, ds_desc).encode("utf-8"))
    files = {p.name: sha256_file(p) for p in sorted(d.iterdir()) if p.is_file() and p.name != "package_manifest.json"}
    atomic_json(d / "package_manifest.json", {"package_version": PACKAGE_VERSION, "instrument": inst, "model_key": key, "version": version,
                                              "created_at": iso(time.time()), "files": files})
    with reg_lock(inst):                          # 1.46: read-modify-write of registry.json under the shared registry lock
        reg = _reg(inst)
        reg.setdefault("versions", {}).setdefault(key, []).append({"version": version, "created_at": iso(time.time()), "model_id": res["model_id"],
                                                                    "base_tf": cfg["base_tf"], "horizon": cfg["horizon"], "data_kind": store_manifest.get("data_kind"),
                                                                    "holdout": res["holdout"], "walk_forward": {k: v for k, v in res["walk_forward"].items() if k != "folds"},
                                                                    "trading_eval_holdout": res["trading_eval_holdout"], "path": str(d.relative_to(root()))})
        _save_reg(inst, reg)
    return {"model_key": key, "version": version, "path": str(d)}


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


def _reg(inst: str) -> dict:
    return read_json(_reg_path(inst), None) or {"versions": {}, "active": {}, "history": []}


def _save_reg(inst: str, reg: dict) -> None:
    _reg_path(inst).parent.mkdir(parents=True, exist_ok=True)
    atomic_json(_reg_path(inst), reg)


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
        reg = _reg(inst)
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
        reg = _reg(inst)
        if (reg.get("active") or {}).get(key) != cur:
            return {"ok": False, "status": "CONFLICT", "active": (reg.get("active") or {}).get(key), "previous": None,
                    "reason": "aktywna wersja zmieniła się w trakcie – rollback nie wykonany, odśwież i ponów"}
        reg.setdefault("active", {})[key] = prev
        reg.setdefault("history", []).append({"at": iso(time.time()), "model_key": key, "action": "ROLLBACK", "version": prev, "previous": cur})
        _save_reg(inst, reg)
    return {"ok": True, "status": "ROLLED_BACK", "active": prev, "previous": cur}


def deactivate(inst: str, key: str) -> dict:
    with reg_lock(inst):                          # 1.46: under the registry lock (see reg_lock)
        reg = _reg(inst)
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
        reg = _reg(inst)
        if (reg.get("active") or {}).get(key) == version:
            raise ValueError("nie można usunąć aktywnej wersji")
        reg.setdefault("versions", {})[key] = [v for v in reg.get("versions", {}).get(key, []) if v["version"] != version]
        _save_reg(inst, reg)
    shutil.rmtree(package_dir(inst, key, version), ignore_errors=True)


def summary(inst: str) -> dict:
    reg = _reg(inst)
    out = []
    for key, vers in (reg.get("versions") or {}).items():
        act = (reg.get("active") or {}).get(key)
        for v in vers:
            out.append({**v, "model_key": key, "active": v["version"] == act})
    def _when(v):                                   # 1.46: tolerant to a numeric created_at written by Studio 1.45.0 imports
        c = v.get("created_at")
        if isinstance(c, (int, float)):
            from ..marketdata.store import iso as _iso
            return _iso(c)
        return str(c or "")
    return {"instrument": inst, "versions": sorted(out, key=_when, reverse=True), "active": reg.get("active") or {},
            "history": (reg.get("history") or [])[-30:], "python": sys.version.split()[0]}
