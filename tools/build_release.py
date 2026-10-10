"""Builds MANIFEST_SHA256.txt and release/MasterQUO_CLAUDE_MT5_BROWSER_FULL.zip from git-tracked files only.

Untracked/ignored paths (data/, .venv/, node_modules/, secrets, logs) can never enter the package.
"""
import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ZIP_NAME = "MasterQUO_IV_WALLS_1_3_1.zip"
TOP = "MasterQUO_AI/"
FORBIDDEN_PARTS = {".venv", "node_modules", "__pycache__", ".git"}


def tracked():
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True).stdout
    files = sorted(f for f in out.decode().split("\0") if f)
    return [f for f in files if not f.startswith("release/") and f != "MANIFEST_SHA256.txt"]


def main():
    files = tracked()
    bad = [f for f in files if FORBIDDEN_PARTS & set(Path(f).parts) or f.startswith("data/")
           or f.endswith((".env", ".sqlite", ".log")) or Path(f).name.startswith("secrets.")]
    if bad:
        sys.exit(f"forbidden paths tracked: {bad}")
    lines = []
    for f in files:
        h = hashlib.sha256((ROOT / f).read_bytes()).hexdigest()
        lines.append(f"{h}  {f}")
    (ROOT / "MANIFEST_SHA256.txt").write_text(
        "# MasterQUO AI 1.3.1 - SHA-256 of every packaged file (sha256sum format)\n" + "\n".join(lines) + "\n",
        encoding="utf-8", newline="\n")
    out = ROOT / "release" / ZIP_NAME
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in files + ["MANIFEST_SHA256.txt"]:
            z.write(ROOT / f, TOP + f)
    print(f"{len(files)} files, manifest written, {out} {out.stat().st_size} bytes")
    print("zip sha256", hashlib.sha256(out.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
