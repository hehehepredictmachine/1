"""Kronos installer step 2/2 (runs inside .venv_kronos): download the pinned weights and verify them.

  python -m kronos_runtime.install download --weights-dir DIR [--status-file F]
  python -m kronos_runtime.install verify   --weights-dir DIR [--reference] [--device AUTO|CPU|CUDA] [--status-file F]

download: for NeoQuasar/Kronos-small and NeoQuasar/Kronos-Tokenizer-base at the revisions of lock.py -
  1. the revision must exist (model_info at that commit; the returned sha must equal the pinned commit),
  2. config.json + model.safetensors must be present (a pickle checkpoint is never accepted),
  3. each file is downloaded into DIR/.partial, checked against the SOURCE metadata (LFS sha256 for model.safetensors, git blob sha1
     for config.json) and its size; only when both components pass are they moved into place and kronos_manifest.json is written.
verify: offline - manifest sha256 of every file, load once (eval, no grad), model/tokenizer compatibility, a short real forecast on the
  bundled upstream regression input, timing and device; --reference also compares with the upstream expected outputs (CPU, greedy).
Messages: human lines on stdout ("[KRONOS] ..."), the last line is "RESULT <json>". Nothing here talks to MetaTrader 5.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import lock
from . import manifest as M

os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Reporter:
    def __init__(self, status_file: str | None, total: int):
        self.status_file, self.total, self.step = status_file, total, 0
        self.log: list[str] = []

    def say(self, msg: str, step: int | None = None, state: str = "RUNNING") -> None:
        if step is not None:
            self.step = step
        line = f"[KRONOS] [{self.step}/{self.total}] {msg}"
        print(line, flush=True)
        self.log.append(line)
        self.log = self.log[-80:]
        if self.status_file:
            try:
                p = Path(self.status_file)
                p.parent.mkdir(parents=True, exist_ok=True)
                tmp = p.with_suffix(".tmp")
                tmp.write_text(json.dumps({"state": state, "step": self.step, "total": self.total, "message": msg, "log": self.log,
                                           "updated_at": _now()}, ensure_ascii=False), encoding="utf-8")
                tmp.replace(p)
            except OSError:
                pass


def result(ok: bool, code: str | None, rep: Reporter, **kw) -> int:
    data = {"ok": ok, "code": code, **kw}
    rep.say(("OK" if ok else f"BŁĄD {code}") + (f": {kw.get('error')}" if kw.get("error") else ""), state="DONE" if ok else "FAILED")
    print("RESULT " + json.dumps(data, ensure_ascii=False, default=str), flush=True)
    return 0 if ok else 1


def _classify(exc: Exception) -> str:
    name = type(exc).__name__
    if name in ("RevisionNotFoundError",):
        return "REVISION_NOT_FOUND"
    if name in ("RepositoryNotFoundError", "GatedRepoError"):
        return "REPO_NOT_FOUND"
    if name in ("EntryNotFoundError", "RemoteEntryNotFoundError"):
        return "FILE_MISSING"
    if name in ("LocalEntryNotFoundError", "ConnectionError", "ConnectTimeout", "ReadTimeout", "ProxyError", "SSLError", "OfflineModeIsEnabled",
                "HfHubHTTPError", "HTTPError", "MaxRetryError", "NewConnectionError", "ConnectError", "TimeoutException"):
        return "NETWORK"
    return "DOWNLOAD_ERROR"


def download(weights_dir: str, status_file: str | None) -> int:
    rep = Reporter(status_file, 6)
    try:
        from huggingface_hub import HfApi, hf_hub_download
        import huggingface_hub
    except ImportError as exc:
        rep.say("brak huggingface_hub w .venv_kronos", 1)
        return result(False, "MISSING_DEPENDENCY", rep, error=str(exc))
    if os.environ.get("HF_HUB_OFFLINE") == "1":
        rep.say("HF_HUB_OFFLINE=1 – pobieranie wyłączone", 1)
        return result(False, "NETWORK", rep, error="tryb offline (HF_HUB_OFFLINE=1) – pobranie wag wymaga internetu przy pierwszej instalacji")
    w = Path(weights_dir)
    partial = w / ".partial"
    shutil.rmtree(partial, ignore_errors=True)
    partial.mkdir(parents=True, exist_ok=True)
    api = HfApi()
    comps_out = []
    step = 1
    for c in lock.COMPONENTS:
        rep.say(f"{c['repo']}: sprawdzam rewizję {c['revision']} w źródle {lock.SOURCE}", step)
        try:
            info = api.model_info(c["repo"], revision=c["revision"], files_metadata=True)
        except Exception as exc:  # noqa: BLE001
            return result(False, _classify(exc), rep, error=f"{c['repo']}@{c['revision'][:12]}: {type(exc).__name__}: {exc}"[:400])
        if getattr(info, "sha", None) != c["revision"]:
            return result(False, "REVISION_MISMATCH", rep, error=f"{c['repo']}: źródło zwróciło commit {getattr(info, 'sha', None)} ≠ {c['revision']}")
        sib = {s.rfilename: s for s in (info.siblings or [])}
        if "model.safetensors" not in sib:
            pick = [n for n in sib if n.endswith((".bin", ".pt", ".pth", ".ckpt"))]
            return result(False, "FILE_MISSING", rep, error=f"{c['repo']}: brak model.safetensors w rewizji (pliki pickle {pick} nie są ładowane ze względów bezpieczeństwa)")
        names = list(lock.REQUIRED_FILES) + [n for n in ("README.md",) if n in sib]
        files = []
        step += 1
        dest = partial / lock.component_dir_name(c)
        for name in names:
            s = sib.get(name)
            if s is None:
                return result(False, "FILE_MISSING", rep, error=f"{c['repo']}: brak pliku {name} w rewizji {c['revision'][:12]}")
            size = getattr(s, "size", None)
            rep.say(f"{c['repo']}: pobieram {name}" + (f" ({size / 1e6:.1f} MB)" if size else ""), step)
            t0 = time.time()
            try:
                local = hf_hub_download(c["repo"], name, revision=c["revision"], local_dir=str(dest))
            except Exception as exc:  # noqa: BLE001
                return result(False, _classify(exc), rep, error=f"{c['repo']}/{name}: {type(exc).__name__}: {exc}"[:400])
            p = Path(local)
            lfs = getattr(s, "lfs", None)
            lfs_sha = (lfs.get("sha256") if isinstance(lfs, dict) else getattr(lfs, "sha256", None)) if lfs else None
            if lfs_sha:
                got, check = M.sha256_file(p), "lfs_sha256"
                ok = got == lfs_sha
                src = lfs_sha
            else:
                blob = getattr(s, "blob_id", None)
                got, check = M.git_blob_sha1(p), "git_blob_sha1"
                ok = blob is not None and got == blob
                src = blob
            if not ok:
                return result(False, "CHECKSUM_MISMATCH", rep, error=f"{c['repo']}/{name}: {check} {got[:16]}… ≠ źródło {str(src)[:16]}…")
            if size is not None and p.stat().st_size != size:
                return result(False, "CHECKSUM_MISMATCH", rep, error=f"{c['repo']}/{name}: rozmiar {p.stat().st_size} B ≠ {size} B ze źródła")
            files.append({"name": name, "size": p.stat().st_size, "sha256": M.sha256_file(p), "source_check": check, "source_value": src,
                          "download_s": round(time.time() - t0, 1)})
            rep.say(f"{c['repo']}/{name}: zgodny ze źródłem ({check})", step)
        shutil.rmtree(dest / ".cache", ignore_errors=True)            # huggingface_hub download metadata - not part of the model
        comps_out.append({"kind": c["kind"], "repo": c["repo"], "revision": c["revision"], "dir": lock.component_dir_name(c), "files": files,
                          "card_license": _card_license(dest / "README.md")})
        step += 1
    rep.say("przenoszę pliki na miejsce i zapisuję manifest", 5)
    for c in lock.COMPONENTS:
        final = w / lock.component_dir_name(c)
        shutil.rmtree(final, ignore_errors=True)
        (partial / lock.component_dir_name(c)).replace(final)
    shutil.rmtree(partial, ignore_errors=True)
    import platform
    man = {"schema": lock.MANIFEST_SCHEMA, "installed_at": _now(), "source": lock.SOURCE, "components": comps_out,
           "tools": {"huggingface_hub": huggingface_hub.__version__, "python": sys.version.split()[0], "platform": platform.platform()},
           "license_code": lock.LICENSE}
    M.write(w, man)
    M.verify(w)
    return result(True, None, rep, manifest=str(M.path(w)), components=[{k: x[k] for k in ("repo", "revision")} for x in comps_out])


def _card_license(readme: Path) -> str | None:
    try:
        head = readme.read_text(encoding="utf-8")[:2000]
    except OSError:
        return None
    if head.startswith("---"):
        for line in head.split("\n")[1:40]:
            if line.strip() == "---":
                break
            if line.lower().startswith("license:"):
                return line.split(":", 1)[1].strip()
    return None


def verify(weights_dir: str, status_file: str | None, reference: bool, device: str) -> int:
    rep = Reporter(status_file, 4)
    rep.say("sprawdzam sumy SHA-256 plików z manifestem (offline)", 1)
    try:
        chk = M.verify(weights_dir)
    except M.ManifestError as exc:
        return result(False, exc.code, rep, error=exc.detail)
    from . import engine as E
    rep.say("ładuję model i tokenizer (raz, tryb eval, bez gradientów)", 2)
    eng = E.Engine()
    try:
        info = eng.load(weights_dir, device=device, verify_files=False)
    except E.EngineError as exc:
        return result(False, exc.code, rep, error=exc.detail)
    rep.say(f"urządzenie: {info['device']} ({info.get('device_note') or 'OK'}); ładowanie {info['load_ms']} ms", 3)
    st = eng.selftest(reference=reference)
    rep.say(f"prognoza testowa: {st['smoke']['pred_len']} świec w {st['smoke']['ms']} ms" +
            (f"; zgodność z wynikiem referencyjnym autorów: {st['reference']['status']}" if reference else ""), 4)
    # integrity = checksums; the reference comparison is reported with its size (a float difference on another CPU / library build
    # can flip a greedy token) and is shown to the user, it does not turn verified files into a failed installation
    ok = st["smoke"]["ok"]
    return result(ok, None if ok else "SELFTEST_FAILED", rep, files=chk["files"], load=info, selftest=st)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kronos_runtime.install")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("download")
    d.add_argument("--weights-dir", required=True)
    d.add_argument("--status-file")
    v = sub.add_parser("verify")
    v.add_argument("--weights-dir", required=True)
    v.add_argument("--status-file")
    v.add_argument("--reference", action="store_true")
    v.add_argument("--device", default="AUTO", choices=("AUTO", "CPU", "CUDA"))
    a = ap.parse_args(argv)
    if a.cmd == "download":
        return download(a.weights_dir, a.status_file)
    return verify(a.weights_dir, a.status_file, a.reference, a.device)


if __name__ == "__main__":
    raise SystemExit(main())
