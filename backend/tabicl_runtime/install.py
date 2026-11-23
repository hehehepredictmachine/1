"""Installer / verifier of the TabICLv2 checkpoint (stdlib for download; --selftest needs .venv_tabicl).

  python -m tabicl_runtime.install download --weights-root DIR [--status-file F]
  python -m tabicl_runtime.install verify   --weights-root DIR [--selftest]
Same rules as tsfm_runtime.install: <file>.part resumed with HTTP Range, size + SHA-256 checked before the rename, manifest written last.
The last stdout line is `RESULT {json}`.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

from tsfm_runtime.install import _check, _download          # one implementation of the resumable, checksum-verified download
from tsfm_runtime import manifest as TM

from . import RUNTIME_VERSION, lock


def model_dir(weights_root) -> Path:
    return Path(weights_root) / "tabicl_v2" / lock.component_dir_name()


def manifest_path(weights_root) -> Path:
    return Path(weights_root) / "tabicl_v2" / lock.MANIFEST_NAME


def verify(weights_root) -> dict:
    d = model_dir(weights_root)
    files, bad = [], []
    for f in lock.PIN["files"]:
        why = _check(d / f["name"], f)
        if why:
            bad.append(f"{f['name']}: {why}")
        else:
            files.append({"file": f["name"], "size": f["size"], "sha256": TM.sha256_file(d / f["name"])})
    man = None
    try:
        man = json.loads(manifest_path(weights_root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        bad.append("brak manifestu instalacji")
    if man and man.get("fingerprint") != lock.fingerprint():
        bad.append("manifest innej wersji checkpointu")
    return {"ok": not bad, "files": files, "problems": bad, "dir": str(d), "fingerprint": lock.fingerprint()}


def download(weights_root, status_file: str | None = None, retries: int = 4, from_dir: str | None = None) -> dict:
    d = model_dir(weights_root)
    d.mkdir(parents=True, exist_ok=True)
    for f in lock.PIN["files"]:
        p = d / f["name"]
        if _check(p, f) is None:
            print(f"{f['name']}: już zainstalowany i zgodny – pomijam", flush=True)
            continue
        part = p.with_name(p.name + ".part")
        url = f"{lock.SOURCE}/{lock.PIN['repo']}/resolve/{lock.PIN['revision']}/{f['name']}"
        err = None
        if from_dir:                                          # offline: a copy of earlier downloaded files, verified exactly like a download
            import shutil
            src = next((x for x in (Path(from_dir) / f["name"], Path(from_dir) / lock.component_dir_name() / f["name"]) if x.is_file()), None)
            if src is None:
                return {"ok": False, "code": "SOURCE_MISSING", "error": f"brak {f['name']} w {from_dir}"}
            shutil.copyfile(src, part)
            retries = -1
        for attempt in range(retries + 1):
            try:
                _download(url, part, f["size"], status_file, f["name"])
                err = None
                break
            except Exception as exc:  # noqa: BLE001
                err = f"{type(exc).__name__}: {exc}"[:240]
                # 1.46: no 'ponowienie 5/4' + 30 s sleep after the LAST attempt; 401 / 403 / 404 are permanent - not retried. A complete
                # .part (HTTP 416 on every run) is handled by the shared _download (verified without a request, 416 -> start from zero).
                if attempt >= retries or (isinstance(exc, urllib.error.HTTPError) and exc.code in (401, 403, 404)):
                    break
                print(f"{f['name']}: przerwane pobieranie ({err}) – ponowienie {attempt + 1}/{retries}", flush=True)
                time.sleep(min(30, 2 ** (attempt + 1)))
        if err:
            return {"ok": False, "code": "NETWORK", "error": f"{f['name']}: {err} (częściowy plik zachowany – wznowienie przy kolejnym uruchomieniu)"}
        why = _check(part, f)
        if why:
            part.unlink(missing_ok=True)
            return {"ok": False, "code": "CHECKSUM", "error": f"{f['name']}: {why} – plik odrzucony"}
        part.replace(p)
    man = {"schema": lock.MANIFEST_SCHEMA, "model_id": "tabicl_v2", "repo": lock.PIN["repo"], "revision": lock.PIN["revision"],
           "checkpoint": lock.PIN["checkpoint"], "license": lock.PIN["license"], "code": lock.PIN["code"], "fingerprint": lock.fingerprint(),
           "installed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "runtime": RUNTIME_VERSION,
           "files": [{"name": f["name"], "size": f["size"], "sha256": f["sha256"]} for f in lock.PIN["files"]]}
    mp = manifest_path(weights_root)
    tmp = mp.with_suffix(".tmp")
    tmp.write_text(json.dumps(man, indent=2), encoding="utf-8")
    tmp.replace(mp)
    return {"ok": True, "model": "tabicl_v2", "dir": str(d), "fingerprint": lock.fingerprint()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="tabicl_runtime.install")
    ap.add_argument("cmd", choices=["download", "verify"])
    ap.add_argument("--weights-root", required=True)
    ap.add_argument("--status-file")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--from-dir")
    a = ap.parse_args(argv)
    if a.cmd == "download":
        r = download(a.weights_root, a.status_file, from_dir=a.from_dir)
    else:
        r = verify(a.weights_root)
        if r["ok"] and a.selftest:
            from .engine import Engine
            e = Engine()
            try:
                r["load"] = e.load(a.weights_root)
                r["selftest"] = e.selftest()
                r["ok"] = bool(r["selftest"].get("ok"))
            except Exception as exc:  # noqa: BLE001
                r.update(ok=False, code=getattr(exc, "code", "EXCEPTION"), error=f"{type(exc).__name__}: {exc}"[:400])
    print("RESULT " + json.dumps(r, ensure_ascii=False), flush=True)
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
