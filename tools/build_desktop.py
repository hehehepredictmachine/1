"""Builds the Windows desktop package of Apollo23 (internal name PepeMarketWizard).

  release/Apollo23_DESKTOP_<ver>.zip                  program folder: PepeMarketWizardDesktop.exe + bundled Python + application
  release/Apollo23_DESKTOP_<ver>.zip.sha256

Contents of the program folder (top folder PepeMarketWizard_Desktop/):
  PepeMarketWizardDesktop.exe   the app (window, engine supervision, tray) - Go + WebView2, built here (cross-compiled)
  runtime/python/               official CPython for Windows x64 (NuGet package "python", hash-pinned below)
  runtime/wheels/               only with --offline: every dependency wheel pinned in requirements-win.txt (no internet on the first start)
  everything tracked in git     engine, panel (frontend/dist), launchers, docs - the same file selection as build_release.py

Without --offline the app installs the dependencies itself on the first start from PyPI with
requirements/requirements-win.txt (--require-hashes). No data/, keys, logs or databases can enter the package (git-tracked
files only + the secret scan of build_release.py). 1.46: like the folder package, the build first runs check_windows_requirements() and
the finished ZIP is checked by tools/verify_release.py (paths, both manifests, forbidden files, secrets in every text entry incl. the
bundled runtime) in a staging folder - it reaches release/ only when that passes.

Requirements of the build machine: git, Go >= 1.23, network (NuGet, Go proxy; PyPI only for --offline). Works on Windows and
Linux (cross-compilation, CGO is not used).

  python tools/build_desktop.py            # online variant (~40 MB)
  python tools/build_desktop.py --offline  # + wheels (~150 MB)
  python tools/build_desktop.py --edition client   # 1.44.0 wersja KLIENTA: Apollo23_DESKTOP_KLIENT_<ver>.zip (bez generatora
                                                   # licencji; wymaga PUBLIC_KEY_HEX – tools/build_release.py edition_entries)
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


def build_exe(ver: str, mode: str = "bot") -> Path:
    """mode 'bot' -> PepeMarketWizardDesktop.exe, 'studio' -> PepeTrainingStudio.exe (same sources, -X main.appMode=studio:
    window + supervision of `python -m masterquo studio`, own port and data folder)."""
    desk = ROOT / "desktop"
    out = ROOT / "build" / ("PepeTrainingStudio.exe" if mode == "studio" else "PepeMarketWizardDesktop.exe")
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
    if mode == "bot":
        subprocess.run(["go", "test", "./..."], cwd=desk, check=True, env=dict(os.environ))  # host platform unit tests
        subprocess.run(["go", "vet", "./..."], cwd=desk, check=True, env=env)
    flags = f"-s -w -H windowsgui -X main.version={ver}" + (" -X main.appMode=studio" if mode == "studio" else "")
    subprocess.run(["go", "build", "-trimpath", "-ldflags", flags, "-o", str(out), "."],
                   cwd=desk, check=True, env=env)
    head = out.read_bytes()[:2]
    if head != b"MZ":
        sys.exit("built file is not a Windows executable")
    return out


def pinned_wheel_hashes() -> set[str]:
    """SHA-256 of every wheel pinned (--hash) in requirements-win.txt."""
    return set(re.findall(r"--hash=sha256:([0-9a-f]{64})", (ROOT / "requirements" / "requirements-win.txt").read_text(encoding="utf-8")))


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
    ap.add_argument("--edition", choices=("owner", "client"), default="owner", help="client = wersja klienta z weryfikacją licencji")
    ap.add_argument("--allow-foreign-key", action="store_true")
    a = ap.parse_args()
    ver = version()
    entries = build_release.edition_entries(a.edition, allow_foreign=a.allow_foreign_key)
    build_release.check_windows_requirements()   # 1.46: same gate as the folder package (was never run for the Windows app package)
    exe = build_exe(ver)
    studio_exe = build_exe(ver, "studio")
    nupkg = fetch_python()
    wheels = fetch_wheels() if a.offline else None

    suffix = "_OFFLINE" if a.offline else ""
    ed = "_KLIENT" if a.edition == "client" else ""
    name = f"Apollo23_DESKTOP{ed}_{ver.replace('.', '_')}{suffix}.zip"      # 1.46: display name in the package file name
    manifest = []

    def fill(z: zipfile.ZipFile) -> None:
        for f, src in entries:
            z.write(src, TOP + f)
            manifest.append(f"{sha256(src)}  {f}")
        z.write(exe, TOP + "PepeMarketWizardDesktop.exe")
        manifest.append(f"{sha256(exe)}  PepeMarketWizardDesktop.exe")
        z.write(studio_exe, TOP + "PepeTrainingStudio.exe")
        manifest.append(f"{sha256(studio_exe)}  PepeTrainingStudio.exe")
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
            # 1.46: build/wheels is a download cache - wheels of earlier releases stay in it; only the ones pinned now are packed
            pinned = pinned_wheel_hashes()
            for w in sorted(wheels.glob("*.whl")):
                d = sha256(w)
                if d not in pinned:
                    print(f"pominięte koło spoza requirements-win.txt (z poprzedniego wydania): {w.name}")
                    continue
                z.write(w, TOP + "runtime/wheels/" + w.name)
                manifest.append(f"{d}  runtime/wheels/{w.name}")
        # the launcher PepeMarketWizard.exe and the .bat installers check for MANIFEST_SHA256.txt (complete unpacking) - same
        # file as in the folder package (program files); MANIFEST_DESKTOP_SHA256.txt below lists every file of this package
        mtext = build_release.manifest_entries(entries, "aplikacja Windows" + (" – wersja klienta" if a.edition == "client" else "")).encode("utf-8")
        z.writestr(TOP + "MANIFEST_SHA256.txt", mtext)
        manifest.append(f"{hashlib.sha256(mtext).hexdigest()}  MANIFEST_SHA256.txt")
        z.writestr(TOP + "MANIFEST_DESKTOP_SHA256.txt",
                   f"# Apollo23 {ver} - aplikacja Windows - SHA-256 każdego pliku paczki (format sha256sum)\n"
                   + "\n".join(manifest) + "\n")
    # 1.46: written in a staging folder, verified there (tools/verify_release.py check_zip, like build_release.py) and only then moved
    # into release/ with its .sha256 - a package that fails verification never reaches release/ (was: never verified at all)
    digest = build_release.publish_zip(name, TOP, fill)
    print(f"{name}: {len(manifest)} files, {(ROOT / 'release' / name).stat().st_size} bytes, sha256 {digest}")


if __name__ == "__main__":
    main()
