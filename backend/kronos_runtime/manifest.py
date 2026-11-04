"""Manifest of installed Kronos files (stdlib only).

<weights_dir>/kronos_manifest.json, written by the installer after every file matched its SOURCE metadata:
  {"schema", "installed_at", "source", "components": [{"repo", "revision", "dir", "files": [{"name", "size", "sha256",
   "source_check": "lfs_sha256" | "git_blob_sha1", "source_value"}]}], "tools": {...}}
verify() recomputes the sha256 of every file locally (offline) - a changed or truncated file is reported, never loaded.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from . import lock


class ManifestError(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def sha256_file(p: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def git_blob_sha1(p: Path) -> str:
    """Git object id of a (non-LFS) file - what the Hugging Face API returns as blob_id for small files."""
    data = Path(p).read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def path(weights_dir: str | os.PathLike) -> Path:
    return Path(weights_dir) / lock.MANIFEST_NAME


def read(weights_dir) -> dict | None:
    p = path(weights_dir)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write(weights_dir, data: dict) -> Path:
    p = path(weights_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)
    return p


def component_dirs(weights_dir) -> dict:
    """{"model": Path, "tokenizer": Path} for the pinned pair."""
    w = Path(weights_dir)
    return {c["kind"]: w / lock.component_dir_name(c) for c in lock.COMPONENTS}


def summary(weights_dir) -> dict:
    """Cheap status for the bot (no hashing): installed? which revisions? what is missing."""
    m = read(weights_dir)
    if m is None:
        return {"installed": False, "reason": f"brak {lock.MANIFEST_NAME} w {weights_dir} – model nie został zainstalowany"}
    if m.get("schema") != lock.MANIFEST_SCHEMA:
        return {"installed": False, "reason": f"nieznany format manifestu ({m.get('schema')})"}
    if m.get("fixture") and os.environ.get("MQ_KRONOS_ALLOW_FIXTURE") != "1":
        # test fixture (random weights in the official layout) - never accepted as the real model outside the test suite
        return {"installed": False, "reason": "manifest testowy (losowe wagi z testów) – to nie jest zainstalowany model Kronos"}
    comps = {c.get("kind"): c for c in m.get("components") or []}
    missing = []
    for c in lock.COMPONENTS:
        got = comps.get(c["kind"])
        if not got or got.get("repo") != c["repo"] or got.get("revision") != c["revision"]:
            missing.append(f"{c['kind']}: {c['repo']}@{c['revision'][:12]} (manifest: {got and got.get('repo')}@{(got or {}).get('revision', '')[:12]})")
            continue
        d = component_dirs(weights_dir)[c["kind"]]
        for f in got.get("files") or []:
            if not (d / f["name"]).is_file():
                missing.append(f"{c['kind']}: brak pliku {f['name']}")
    if missing:
        return {"installed": False, "reason": "niekompletna instalacja: " + "; ".join(missing), "manifest": m}
    return {"installed": True, "reason": None, "manifest": m, "installed_at": m.get("installed_at"),
            "components": [{k: comps[c["kind"]].get(k) for k in ("kind", "repo", "revision")} for c in lock.COMPONENTS]}


def verify(weights_dir) -> dict:
    """Offline integrity check: every file of the manifest exists with the recorded sha256. Raises ManifestError."""
    s = summary(weights_dir)
    if not s["installed"]:
        raise ManifestError("NO_WEIGHTS", s["reason"])
    dirs = component_dirs(weights_dir)
    checked = []
    for comp in s["manifest"]["components"]:
        names = {f["name"] for f in comp.get("files") or []}
        for need in lock.REQUIRED_FILES:
            if need not in names:
                raise ManifestError("NO_WEIGHTS", f"{comp['repo']}: manifest bez pliku {need}")
        for f in comp["files"]:
            p = dirs[comp["kind"]] / f["name"]
            if p.stat().st_size != f["size"]:
                raise ManifestError("CHECKSUM", f"{comp['repo']}/{f['name']}: rozmiar {p.stat().st_size} B ≠ {f['size']} B z manifestu")
            got = sha256_file(p)
            if got != f["sha256"]:
                raise ManifestError("CHECKSUM", f"{comp['repo']}/{f['name']}: SHA-256 {got[:16]}… ≠ {f['sha256'][:16]}… z manifestu (plik zmieniony)")
            checked.append({"file": f"{comp['repo']}/{f['name']}", "sha256": got, "size": f["size"]})
    return {"ok": True, "files": checked}
