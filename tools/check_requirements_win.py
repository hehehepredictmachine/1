"""Simulates the Windows installs of every hash-pinned requirements file (1.34.1 - the 1.33.0 / 1.34.0 packages failed on Windows:
statsmodels 0.15 needs formulaic -> interface-meta, wrapt, which were not pinned, and `pip install --require-hashes` stops at the first
unpinned dependency). The check resolves for x86_64-pc-windows-msvc with Windows environment markers (a pip run on Linux would
evaluate the markers for Linux and report wrong packages), for CPython 3.13 (bundled with the desktop app) and 3.12, and installs the
wheels into a temporary folder with hash checking - exactly what 01_INSTALUJ.bat / the desktop app / the extra installers do.

  python tools/check_requirements_win.py            (needs `uv` - pip install uv - and network access to PyPI)
Exit 0 = every file installs on both versions; 1 = a file fails (the uv message names the package); 2 = uv not available."""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ["requirements-win.txt", "requirements-deep-win.txt", "requirements-kronos-win.txt", "requirements-candles-win.txt",
         "requirements-chronos2-win.txt", "requirements-fincast-win.txt"]                     # 1.37: Chronos-2 / FinCast environments


def uv() -> list[str] | None:
    """The uv installed next to this Python first (pip install uv) - uv >= 0.13 models Windows x64 as platform_machine "AMD64" like
    CPython on Windows; older builds used "x86_64" and reported e.g. hf-xet (huggingface-hub marker) that pip on Windows never installs."""
    local = Path(sys.executable).with_name("uv.exe" if sys.platform == "win32" else "uv")
    exe = str(local) if local.exists() else shutil.which("uv")
    if exe:
        return [exe]
    try:
        import uv as _uv  # noqa: F401
        return [sys.executable, "-m", "uv"]
    except ImportError:
        return None


def main() -> int:
    u = uv()
    if not u:
        print("uv niedostępny – pip install uv", file=sys.stderr)
        return 2
    bad = 0
    for f in FILES:
        for py in ("3.13", "3.12"):
            with tempfile.TemporaryDirectory() as td:
                r = subprocess.run([*u, "pip", "install", "-r", str(ROOT / "requirements" / f), "--require-hashes", "--only-binary", ":all:",
                                    "--python-platform", "x86_64-pc-windows-msvc", "--python-version", py, "--target", td, "-q"],
                                   capture_output=True, text=True, timeout=1800)
                n = sum(1 for p in Path(td).glob("*.dist-info"))
            ok = r.returncode == 0
            bad += not ok
            msg = (r.stderr or r.stdout).strip().splitlines()[-1:] if not ok else []
            print(f"{'OK  ' if ok else 'FAIL'} {f} cp{py.replace('.', '')}: {n} pakietów" + (f" – {msg[0]}" if msg else ""), flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
