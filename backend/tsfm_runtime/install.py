"""Installer / verifier of the Chronos-2 and FinCast weights (stdlib only for `download`; `selftest` needs the model environment).

  python -m tsfm_runtime.install download --model chronos2|fincast --weights-root DIR [--from-dir DIR] [--status-file F]
  python -m tsfm_runtime.install verify   --model chronos2|fincast --weights-root DIR [--selftest] [--status-file F]

download: every pinned file goes to <file>.part (resumed with an HTTP Range request after an interrupted transfer), is checked against
the pinned size and SHA-256 (LFS) / git blob sha1, and only then renamed to its final name. A file already present and matching is kept
(re-running the installer is safe and offline). The manifest is written LAST and atomically - without it the model is never READY.
No internet / not enough disk / a wrong checksum -> an error with the reason and NO manifest. --from-dir copies already downloaded files
(e.g. from another machine) and verifies them exactly like a download.
verify: offline recomputation of every SHA-256; with --selftest a real load + inference + parity check in the model's own process.
The last stdout line is `RESULT {json}` (read by the bot's job runner).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from . import RUNTIME_VERSION, lock
from . import manifest as M

CHUNK = 1 << 22


def _status(path: str | None, **kw) -> None:
    if not path:
        return
    try:
        Path(path).write_text(json.dumps(kw), encoding="utf-8")
    except OSError:
        pass


def _check(p: Path, f: dict) -> str | None:
    """None when the file matches the pin, else the reason."""
    if not p.is_file():
        return "brak pliku"
    if p.stat().st_size != f["size"]:
        return f"rozmiar {p.stat().st_size} B ≠ {f['size']} B"
    if f.get("sha256"):
        got = M.sha256_file(p)
        return None if got == f["sha256"] else f"SHA-256 {got[:16]}… ≠ {f['sha256'][:16]}…"
    got = M.git_blob_sha1(p)
    return None if got == f["git_blob_sha1"] else f"git blob {got[:12]}… ≠ {f['git_blob_sha1'][:12]}…"


def _download(url: str, part: Path, size: int, status_file: str | None, label: str) -> None:
    have = part.stat().st_size if part.exists() else 0
    if have > size:
        part.unlink()
        have = 0
    req = urllib.request.Request(url, headers={"User-Agent": f"PepeMarketWizard-tsfm/{RUNTIME_VERSION}"})
    if have:
        req.add_header("Range", f"bytes={have}-")
    with urllib.request.urlopen(req, timeout=60) as r:
        if have and r.status != 206:                 # server ignored the range -> start again
            have = 0
            mode = "wb"
        else:
            mode = "ab" if have else "wb"
        t0, last = time.time(), 0.0
        with open(part, mode) as out:
            while True:
                b = r.read(CHUNK)
                if not b:
                    break
                out.write(b)
                have += len(b)
                if time.time() - last > 2:
                    last = time.time()
                    mbps = have / max(1e-6, time.time() - t0) / 1e6
                    print(f"{label}: {have / 1e6:.0f} / {size / 1e6:.0f} MB ({mbps:.1f} MB/s)", flush=True)
                    _status(status_file, step=have, total=size, file=label)


def download(mid: str, weights_root: str, from_dir: str | None = None, status_file: str | None = None, retries: int = 4) -> dict:
    pin = lock.model(mid)
    d = M.model_dir(weights_root, mid)
    d.mkdir(parents=True, exist_ok=True)
    need = sum(f["size"] for f in pin["files"] if _check(d / f["name"], f) is not None)
    free = shutil.disk_usage(d).free
    if need and free < need * 1.05 + 200e6:
        return {"ok": False, "code": "DISK_SPACE", "error": f"za mało miejsca na dysku: potrzeba {need / 1e9:.2f} GB (+zapas), wolne {free / 1e9:.2f} GB w {d}"}
    files = []
    for f in pin["files"]:
        p = d / f["name"]
        why = _check(p, f)
        if why is None:
            print(f"{f['name']}: już zainstalowany i zgodny – pomijam", flush=True)
        else:
            part = p.with_name(p.name + ".part")
            if from_dir:
                src = Path(from_dir) / f["name"]
                if not src.is_file():
                    src = Path(from_dir) / lock.component_dir_name(pin) / f["name"]
                if not src.is_file():
                    return {"ok": False, "code": "SOURCE_MISSING", "error": f"brak {f['name']} w {from_dir}"}
                print(f"{f['name']}: kopiowanie z {src}", flush=True)
                shutil.copyfile(src, part)
            else:
                url = f"{lock.SOURCE}/{pin['repo']}/resolve/{pin['revision']}/{f['name']}"
                err = None
                for attempt in range(retries + 1):
                    try:
                        _download(url, part, f["size"], status_file, f["name"])
                        err = None
                        break
                    except Exception as exc:  # noqa: BLE001 - network: resume on the next attempt
                        err = f"{type(exc).__name__}: {exc}"[:240]
                        print(f"{f['name']}: przerwane pobieranie ({err}) – ponowienie {attempt + 1}/{retries}", flush=True)
                        time.sleep(min(30, 2 ** (attempt + 1)))
                if err:
                    return {"ok": False, "code": "NETWORK", "error": f"{f['name']}: {err} (częściowy plik zachowany – kolejne uruchomienie wznowi pobieranie)"}
            why = _check(part, f)
            if why is not None:
                part.unlink(missing_ok=True)
                return {"ok": False, "code": "CHECKSUM", "error": f"{f['name']}: {why} – plik odrzucony"}
            part.replace(p)
        files.append({"name": f["name"], "size": f["size"], "sha256": M.sha256_file(p),
                      "source_check": "lfs_sha256" if f.get("sha256") else "git_blob_sha1", "source_value": f.get("sha256") or f.get("git_blob_sha1")})
    man = {"schema": lock.MANIFEST_SCHEMA, "model_id": mid, "name": pin["name"], "variant": pin["variant"], "repo": pin["repo"],
           "revision": pin["revision"], "license": pin["license"], "params_upstream": pin["params_upstream"], "code": pin["code"],
           "installed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": lock.SOURCE, "dir": lock.component_dir_name(pin),
           "files": files, "runtime": RUNTIME_VERSION, "fingerprint": lock.fingerprint(mid)}
    M.write(weights_root, mid, man)
    return {"ok": True, "model": mid, "files": len(files), "dir": str(d), "fingerprint": man["fingerprint"]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="tsfm_runtime.install")
    ap.add_argument("cmd", choices=["download", "verify"])
    ap.add_argument("--model", required=True, choices=list(lock.MODELS))
    ap.add_argument("--weights-root", required=True)
    ap.add_argument("--from-dir")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--device", default="AUTO")
    ap.add_argument("--status-file")
    a = ap.parse_args(argv)
    if a.cmd == "download":
        res = download(a.model, a.weights_root, a.from_dir, a.status_file)
    else:
        try:
            res = {"ok": True, "integrity": M.verify(a.weights_root, a.model)}
        except M.ManifestError as exc:
            res = {"ok": False, "code": exc.code, "error": exc.detail}
        if res["ok"] and a.selftest:
            from . import engines as E
            try:
                eng = E.make(a.model)
                res["load"] = eng.load(a.weights_root, device=a.device)
                res["selftest"] = eng.selftest()
                res["ok"] = bool(res["selftest"]["smoke"]["ok"]) and res["selftest"]["parity"]["status"] == "PASS"
                if not res["ok"]:
                    res["code"] = "SELFTEST"
            except E.EngineError as exc:
                res.update(ok=False, code=exc.code, error=exc.detail)
    print("RESULT " + json.dumps(res, ensure_ascii=False), flush=True)
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
