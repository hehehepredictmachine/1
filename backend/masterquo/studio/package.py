"""Per-task package (PMW-STUDIO-PKG-1): exports/<model_id>/<instrument>/<tf>/<run_id>/ with manifest.json, raw/, dataset/,
feature_schema.json, label_schema.json, splits.json, validation/, training_config.json, artifact/, evaluation/, logs/, REPRODUCE.md.
Work happens in `<run_id>.partial/`; every stage writes into `<stage>.tmp/` and is committed by an atomic rename + a manifest update with
the checksums of its files. Committed stages are immutable - a resume verifies their checksums and continues after them; the package is
renamed to `<run_id>/` only when the last selected stage is committed."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path

VERSION = "PMW-STUDIO-PKG-1"
FINAL_STATES = ("EXPORTED", "VALIDATED", "READY_FOR_TRAINING", "TRAINED", "PACKAGED", "VALIDATION_FAILED", "FEATURES_EXPORTED")


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def atomic_json(p: Path, obj) -> None:
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, p)


def read_json(p: Path, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def checksums(d: Path) -> dict:
    return {str(p.relative_to(d)).replace("\\", "/"): _sha(p) for p in sorted(d.rglob("*")) if p.is_file()}


class Package:
    def __init__(self, root: Path, task: dict, run_id: str):
        self.task, self.run_id = task, run_id
        base = Path(root) / "exports" / task["model_id"].replace(":", "_") / task["instrument"] / str(task["base_tf"])
        self.final = base / run_id
        self.dir = self.final if self.final.exists() else base / (run_id + ".partial")
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "logs").mkdir(exist_ok=True)
        if not (self.dir / "manifest.json").exists():
            atomic_json(self.dir / "manifest.json", {"package": VERSION, "run_id": run_id, "dataset_id": f"DS-{run_id}", "task": task,
                                                      "created_at": time.time(), "stages": {}, "status": "PARTIAL"})

    @property
    def manifest(self) -> dict:
        return read_json(self.dir / "manifest.json", {}) or {}

    def stage_done(self, stage: str) -> bool:
        st = (self.manifest.get("stages") or {}).get(stage)
        if not st or st.get("status") != "COMMITTED":
            return False
        sub = self.dir / st["dir"] if st.get("dir") else None
        for rel, h in (st.get("files") or {}).items():
            p = (sub / rel) if sub else (self.dir / rel)
            if not p.exists() or _sha(p) != h:
                return False                                                     # tampered / incomplete -> redo this stage
        return True

    def tmp(self, stage: str) -> Path:
        d = self.dir / f"{stage}.tmp"
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        return d

    def commit(self, stage: str, tmp: Path | None, info: dict, *, subdir: str | None = None, files: list[str] | None = None) -> None:
        """Atomic: rename tmp -> <subdir>/<stage>, then record checksums in the manifest."""
        rec = {"status": "COMMITTED", "at": time.time(), **info}
        if tmp is not None:
            target = self.dir / (subdir or stage) / stage if subdir else self.dir / stage
            if target.exists():
                shutil.rmtree(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(tmp, target)
            rec["dir"] = str(target.relative_to(self.dir)).replace("\\", "/")
            rec["files"] = checksums(target)
        if files:
            rec["root_files"] = {f: _sha(self.dir / f) for f in files if (self.dir / f).exists()}
        m = self.manifest
        m.setdefault("stages", {})[stage] = rec
        atomic_json(self.dir / "manifest.json", m)

    def fail(self, stage: str, state: str, reason: str) -> None:
        m = self.manifest
        m.setdefault("failures", []).append({"stage": stage, "state": state, "at": time.time(), "reason": reason})
        m["status"] = state
        atomic_json(self.dir / "manifest.json", m)

    def finalize(self, status: str) -> Path:
        m = self.manifest
        m["status"] = status
        m["finished_at"] = time.time()
        m["root_files"] = {p.name: _sha(p) for p in sorted(self.dir.iterdir()) if p.is_file() and p.name != "manifest.json"}
        atomic_json(self.dir / "manifest.json", m)
        if self.dir != self.final and status in FINAL_STATES:
            os.replace(self.dir, self.final)
            self.dir = self.final
        return self.dir

    def log(self, msg: str) -> None:
        with (self.dir / "logs" / "job.log").open("a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%dT%H:%M:%SZ ", time.gmtime()) + msg + "\n")


# committed stage locations (commit(stage, tmp, subdir=...) -> <subdir>/<stage>)
RAW, VAL_RAW, DATASET, VAL_DS, ARTIFACT, EVAL, LOADER = ("raw/export", "validation/validate_raw", "dataset/build_dataset",
                                                        "validation/validate_dataset", "artifact/train", "evaluation/evaluate",
                                                        "evaluation/verify_loader")
