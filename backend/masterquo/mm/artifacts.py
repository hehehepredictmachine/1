"""Immutable model artifacts + atomic SHADOW pointer with rollback (PMW-MM-ARTIFACTS-1).

Layout: <data>/mm[/instruments/<INST>]/artifacts/<model_id>/<artifact_id>/{state.npz, manifest.json}
        <data>/mm[...]/SHADOW_ACTIVE.json  {active: {model_id: artifact_id}, history: [...], events: [...]}

* State is numpy arrays (npz, allow_pickle=False) + JSON config - no pickle, so loading an artifact cannot execute code.
* An artifact id is unique (time + random suffix); a directory is written to <id>.tmp and renamed once complete. Nothing ever
  overwrites an existing artifact, so the previous known-good one stays loadable.
* The manifest pins model id/type, feature schema, target, snapshot id, split intervals, hyper-parameters, optimizer config, seeds,
  library versions, metrics, calibration, gates and warnings. Loading verifies the checksum and the declared instrument/schema.
* "Shadow promotion" only moves the SHADOW pointer (observation + comparison). There is no live pointer in this module.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import platform
import shutil
import time
import uuid
from pathlib import Path

import numpy as np

VERSION = "PMW-MM-ARTIFACTS-1"
STATUSES = ("CANDIDATE", "VALIDATION_FAILED", "VALIDATED_SHADOW", "TECHNICAL_TEST_ONLY")


class ArtifactError(ValueError):
    pass


def root(inst: str) -> Path:
    import mq_instruments as mi
    return mi.root("mm", inst)


def _versions() -> dict:
    import scipy
    import sklearn
    return {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__, "scikit-learn": sklearn.__version__}


def save(inst: str, model_id: str, state: dict, manifest: dict) -> str:
    arrays = {k: np.asarray(v) for k, v in state.items()}
    for k, v in arrays.items():
        if v.dtype == object:
            raise ArtifactError(f"OBJECT_ARRAY_NOT_ALLOWED:{k}")
    buf = io.BytesIO()
    np.savez(buf, **arrays)
    blob = buf.getvalue()
    aid = f"{model_id}-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:6]}"
    base = root(inst) / "artifacts" / model_id
    base.mkdir(parents=True, exist_ok=True)
    tmp = base / (aid + ".tmp")
    tmp.mkdir()
    (tmp / "state.npz").write_bytes(blob)
    man = {"schema": VERSION, **manifest, "model_id": model_id, "artifact_id": aid, "instrument": inst, "created_at": time.time(),
           "sha256": hashlib.sha256(blob).hexdigest(), "arrays": {k: list(v.shape) for k, v in arrays.items()}, "dependencies": _versions()}
    man.setdefault("status", "CANDIDATE")
    if man["status"] not in STATUSES:
        raise ArtifactError(f"STATUS_INVALID:{man['status']}")
    (tmp / "manifest.json").write_text(json.dumps(man, indent=1, default=str), encoding="utf-8")
    final = base / aid
    if final.exists():
        shutil.rmtree(tmp)
        raise ArtifactError("ARTIFACT_EXISTS")                 # never overwrite
    os.replace(tmp, final)
    return aid


def path(inst: str, model_id: str, aid: str) -> Path:
    return root(inst) / "artifacts" / model_id / aid


def load(inst: str, model_id: str, aid: str, *, feature_schema: str | None = None) -> tuple[dict, dict]:
    p = path(inst, model_id, aid)
    if not (p / "manifest.json").exists():
        raise ArtifactError(f"UNKNOWN_ARTIFACT:{aid}")
    man = json.loads((p / "manifest.json").read_text(encoding="utf-8"))
    if man.get("instrument") != inst:
        raise ArtifactError(f"INSTRUMENT_MISMATCH:{man.get('instrument')}!={inst}")
    if feature_schema is not None and man.get("feature_schema") != feature_schema:
        raise ArtifactError(f"FEATURE_SCHEMA_MISMATCH:{man.get('feature_schema')}!={feature_schema}")
    blob = (p / "state.npz").read_bytes()
    if hashlib.sha256(blob).hexdigest() != man.get("sha256"):
        raise ArtifactError("ARTIFACT_CHECKSUM_MISMATCH")
    with np.load(io.BytesIO(blob), allow_pickle=False) as z:
        state = {k: z[k] for k in z.files}
    return state, man


def list_artifacts(inst: str, model_id: str | None = None) -> list[dict]:
    base = root(inst) / "artifacts"
    out = []
    for d in sorted(base.glob(f"{model_id or '*'}/*/manifest.json")):
        try:
            m = json.loads(d.read_text(encoding="utf-8"))
            out.append({k: m.get(k) for k in ("model_id", "artifact_id", "status", "created_at", "snapshot_id", "data_kind", "metrics", "gates")})
        except (OSError, ValueError):
            continue
    return out


# ------------------------------------------------------------------------------------------- SHADOW pointer
def _ptr_path(inst: str) -> Path:
    return root(inst) / "SHADOW_ACTIVE.json"


def read_pointer(inst: str) -> dict:
    try:
        return json.loads(_ptr_path(inst).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"active": {}, "history": [], "events": []}


def _write_ptr(inst: str, ptr: dict) -> None:
    p = _ptr_path(inst)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(ptr, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def promote_shadow(inst: str, model_id: str, aid: str, reason: str) -> dict:
    """Only an artifact whose manifest says VALIDATED_SHADOW (all gates passed) can become the SHADOW pointer."""
    _, man = load(inst, model_id, aid)
    if man.get("status") != "VALIDATED_SHADOW":
        raise ArtifactError(f"NOT_VALIDATED:{man.get('status')}")
    ptr = read_pointer(inst)
    prev = ptr["active"].get(model_id)
    if prev and prev != aid:
        ptr["history"].append({"model_id": model_id, "artifact_id": prev, "at": time.time()})
    ptr["active"][model_id] = aid
    ptr["events"].append({"at": time.time(), "model_id": model_id, "from": prev, "to": aid, "reason": reason})
    _write_ptr(inst, ptr)
    return ptr


def rollback(inst: str, model_id: str) -> dict:
    ptr = read_pointer(inst)
    hist = [h for h in ptr["history"] if h["model_id"] == model_id and (path(inst, model_id, h["artifact_id"]) / "manifest.json").exists()]
    if not hist:
        raise ArtifactError(f"NO_PREVIOUS_ARTIFACT:{model_id}")
    last = hist[-1]
    ptr["history"].remove(last)
    cur = ptr["active"].get(model_id)
    ptr["active"][model_id] = last["artifact_id"]
    ptr["events"].append({"at": time.time(), "model_id": model_id, "from": cur, "to": last["artifact_id"], "reason": "ROLLBACK"})
    _write_ptr(inst, ptr)
    return ptr
