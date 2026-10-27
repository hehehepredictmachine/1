"""Builds the Windows desktop package of PepeMarketWizard.

  release/PepeMarketWizard_DESKTOP_<ver>.zip          program folder: PepeMarketWizardDesktop.exe + bundled Python + application
  release/PepeMarketWizard_DESKTOP_<ver>.zip.sha256

Contents of the program folder (top folder PepeMarketWizard_Desktop/):
  PepeMarketWizardDesktop.exe   the app (window, engine supervision, tray) - Go + WebView2, built here (cross-compiled)
  runtime/python/               official CPython for Windows x64 (NuGet package "python", hash-pinned below)
  runtime/wheels/               only with --offline: every dependency wheel (no internet needed on the first start)
  everything tracked in git     engine, panel (frontend/dist), launchers, docs - the same file selection as build_release.py

Without --offline the app installs the dependencies itself on the first start from PyPI with
requirements/requirements-win.txt (--require-hashes). No data/, keys, logs or databases can enter the package (git-tracked
files only + the secret scan of build_release.py).

Requirements of the build machine: git, Go >= 1.23, network (NuGet, Go proxy; PyPI only for --offline). Works on Windows and
Linux (cross-compilation, CGO is not used).

  python tools/build_desktop.py            # online variant (~40 MB)
  python tools/build_desktop.py --offline  # + wheels (~150 MB)
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build_release  # noqa: E402  (same file selection and secret scan)

PY_VERSION = "3.13.17"
PY_NUPKG_URL = f"https://api.nuget.org/v3-flatcontainer/python/{PY_VERSION}/python.{PY_VERSION}.nupkg"
# SHA-256 of python.3.13.17.nupkg; the file was checked against the SHA-512 published in the NuGet catalog
# (DmZ5KLtPGVc8bNiPZRM7LgeyQ6XHFvM1tWqma7nsb4IyglbSLDop4joCdqxcam14YhH+q1JIkK0eVmKRlsaynA==)
PY_NUPKG_SHA256 = "dce409744b088f94c6e37ba41f8100c384c27e029e843237364c602d30d475e5"
PY_SKIP = ("tools/include/", "tools/libs/")  # C headers / import libraries - not needed to run
TOP = "PepeMarketWizard_Desktop/"
CACHE = ROOT / "build" / "cache"


def version() -> str:
    m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', (ROOT / "backend" / "masterquo" / "version.py").read_text(encoding="utf-8"))
    if not m:
        sys.exit("APP_VERSION not found")
    return m.group(1)


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def fetch_python() -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / f"python.{PY_VERSION}.nupkg"
    if not p.exists() or sha256(p) != PY_NUPKG_SHA256:
        print("download", PY_NUPKG_URL)
        with urllib.request.urlopen(PY_NUPKG_URL, timeout=300) as r:
            data = r.read()
        if hashlib.sha256(data).hexdigest() != PY_NUPKG_SHA256:
            sys.exit("python nupkg: SHA-256 mismatch - refusing to package it")
        p.write_bytes(data)
    return p


def build_exe(ver: str) -> Path:
    desk = ROOT / "desktop"
    out = ROOT / "build" / "PepeMarketWizardDesktop.exe"
    out.parent.mkdir(parents=True, exist_ok=True)
    winres = shutil.which("go-winres") or str(Path(subprocess.run(["go", "env", "GOPATH"], capture_output=True, text=True,
                                                                     check=True).stdout.strip()) / "bin" / "go-winres")
    if Path(winres).exists() or shutil.which("go-winres"):
        nums = ".".join((ver.split(".") + ["0", "0", "0"])[:4])
        subprocess.run([winres, "make", "--in", "winres/winres.json", "--arch", "amd64", "--product-version", nums,
                        "--file-version", nums], cwd=desk, check=True)
    elif not (desk / "rsrc_windows_amd64.syso").exists():
        sys.exit("go-winres missing and no committed rsrc_windows_amd64.syso (go install github.com/tc-hib/go-winres@v0.3.3)")
    env = dict(os.environ, GOOS="windows", GOARCH="amd64", CGO_ENABLED="0")
    subprocess.run(["go", "test", "./..."], cwd=desk, check=True, env=dict(os.environ))  # host platform unit tests
    subprocess.run(["go", "vet", "./..."], cwd=desk, check=True, env=env)
    subprocess.run(["go", "build", "-trimpath", "-ldflags", f"-s -w -H windowsgui -X main.version={ver}", "-o", str(out), "."],
                   cwd=desk, check=True, env=env)
    head = out.read_bytes()[:2]
    if head != b"MZ":
        sys.exit("built file is not a Windows executable")
    return out


def fetch_wheels() -> Path:
    d = ROOT / "build" / "wheels"
    d.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "pip", "download", "--disable-pip-version-check", "--only-binary=:all:", "--no-deps",
                    "--require-hashes", "--platform", "win_amd64", "--python-version", "3.13", "--implementation", "cp",
                    "--abi", "cp313", "-r", str(ROOT / "requirements" / "requirements-win.txt"), "-d", str(d)], check=True)
    return d


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="include dependency wheels (no internet on the first start)")
    a = ap.parse_args()
    ver = version()
    files = build_release.tracked()
    build_release.scan(files)
    exe = build_exe(ver)
    nupkg = fetch_python()
    wheels = fetch_wheels() if a.offline else None

    suffix = "_OFFLINE" if a.offline else ""
    name = f"PepeMarketWizard_DESKTOP_{ver.replace('.', '_')}{suffix}.zip"
    out = ROOT / "release" / name
    out.parent.mkdir(exist_ok=True)
    manifest = []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in files:
            z.write(ROOT / f, TOP + f)
            manifest.append(f"{sha256(ROOT / f)}  {f}")
        z.write(exe, TOP + "PepeMarketWizardDesktop.exe")
        manifest.append(f"{sha256(exe)}  PepeMarketWizardDesktop.exe")
        with zipfile.ZipFile(nupkg) as nz:
            for info in nz.infolist():
                n = info.filename
                if not n.startswith("tools/") or n.endswith("/") or n.startswith(PY_SKIP) or "__pycache__" in n:
                    continue
                data = nz.read(info)
                rel = "runtime/python/" + n[len("tools/"):]
                z.writestr(TOP + rel, data)
                manifest.append(f"{hashlib.sha256(data).hexdigest()}  {rel}")
        if wheels:
            for w in sorted(wheels.glob("*.whl")):
                z.write(w, TOP + "runtime/wheels/" + w.name)
                manifest.append(f"{sha256(w)}  runtime/wheels/{w.name}")
        z.writestr(TOP + "MANIFEST_DESKTOP_SHA256.txt",
                   f"# PepeMarketWizard {ver} - aplikacja Windows - SHA-256 każdego pliku paczki (format sha256sum)\n"
                   + "\n".join(manifest) + "\n")
    digest = sha256(out)
    (out.parent / (name + ".sha256")).write_text(f"{digest}  {name}\n", encoding="utf-8", newline="\n")
    print(f"{name}: {len(manifest)} files, {out.stat().st_size} bytes, sha256 {digest}")


if __name__ == "__main__":
    main()
