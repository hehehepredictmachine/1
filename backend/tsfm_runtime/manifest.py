"""Manifest of installed Chronos-2 / FinCast files (stdlib only).

<weights_root>/<model_id>/tsfm_manifest.json, written by the installer only after every file matched the pinned SOURCE metadata of
lock.py (size + LFS sha256 / git blob sha1):
  {"schema", "model_id", "repo", "revision", "installed_at", "dir", "files": [{"name", "size", "sha256", "source_check", "source_value"}]}
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


def sha256_file(p: Path, chunk: int = 1 << 22) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def git_blob_sha1(p: Path) -> str:
    data = Path(p).read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def model_root(weights_root, mid: str) -> Path:
    return Path(weights_root) / mid


def model_dir(weights_root, mid: str) -> Path:
    return model_root(weights_root, mid) / lock.component_dir_name(lock.model(mid))


def path(weights_root, mid: str) -> Path:
    return model_root(weights_root, mid) / lock.MANIFEST_NAME


def read(weights_root, mid: str) -> dict | None:
    try:
        return json.loads(path(weights_root, mid).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write(weights_root, mid: str, data: dict) -> Path:
    p = path(weights_root, mid)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)                                     # atomic: the model is READY only after the whole manifest exists
    return p


def summary(weights_root, mid: str) -> dict:
    """Cheap status (no hashing): installed? which revision? what is missing."""
    m = read(weights_root, mid)
    pin = lock.model(mid)
    if m is None:
        return {"installed": False, "reason": f"brak {lock.MANIFEST_NAME} – {pin['name']} nie został zainstalowany (instalator pobiera wagi)"}
    if m.get("schema") != lock.MANIFEST_SCHEMA:
        return {"installed": False, "reason": f"nieznany format manifestu ({m.get('schema')})"}
    if m.get("fixture") and os.environ.get("MQ_TSFM_ALLOW_FIXTURE") != "1":
        return {"installed": False, "reason": "manifest testowy (pliki z testów) – to nie jest zainstalowany model"}
    if m.get("repo") != pin["repo"] or m.get("revision") != pin["revision"]:
        return {"installed": False, "reason": f"zainstalowana inna rewizja ({m.get('repo')}@{str(m.get('revision'))[:12]}) niż przypięta "
                                              f"{pin['repo']}@{pin['revision'][:12]} – uruchom instalator (kontrolowana aktualizacja)", "manifest": m}
    d = model_dir(weights_root, mid)
    missing = [f["name"] for f in m.get("files") or [] if not (d / f["name"]).is_file()]
    need = [n for n in pin["required_files"] if n not in {f["name"] for f in m.get("files") or []}]
    if missing or need:
        return {"installed": False, "reason": "niekompletna instalacja: brak " + ", ".join(missing + need), "manifest": m}
    return {"installed": True, "reason": None, "manifest": m, "installed_at": m.get("installed_at"), "repo": m["repo"], "revision": m["revision"]}


def verify(weights_root, mid: str) -> dict:
    """Offline integrity check: every file exists with the size and sha256 of the manifest AND of the pin. Raises ManifestError."""
    s = summary(weights_root, mid)
    if not s["installed"]:
        raise ManifestError("NO_WEIGHTS", s["reason"])
    pin = {f["name"]: f for f in lock.model(mid)["files"]}
    d = model_dir(weights_root, mid)
    checked = []
    for f in s["manifest"]["files"]:
        p = d / f["name"]
        size = p.stat().st_size
        if size != f["size"] or (f["name"] in pin and size != pin[f["name"]]["size"]):
            raise ManifestError("CHECKSUM", f"{f['name']}: rozmiar {size} B ≠ {f['size']} B z manifestu")
        got = sha256_file(p)
        if got != f["sha256"]:
            raise ManifestError("CHECKSUM", f"{f['name']}: SHA-256 {got[:16]}… ≠ {f['sha256'][:16]}… z manifestu (plik zmieniony)")
        if pin.get(f["name"], {}).get("sha256") and got != pin[f["name"]]["sha256"]:
            raise ManifestError("CHECKSUM", f"{f['name']}: SHA-256 {got[:16]}… ≠ przypiętej {pin[f['name']]['sha256'][:16]}…")
        checked.append({"file": f["name"], "sha256": got, "size": size})
    return {"ok": True, "files": checked}
