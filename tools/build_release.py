"""Builds MANIFEST_SHA256.txt and the package from git-tracked files only:

  release/PepeMarketWizard_KLIENT_1_22_0.zip         bot 1.22.0 (SCALPING/HEDGING + panel Neural Cyberpunk + master models SHADOW + ocena setupów SHADOW + ścieżka główna + strażnik portfela + mapa stref PMW) + training installers for Windows (no license, no secrets)
  release/PepeMarketWizard_KLIENT_1_22_0.zip.sha256  SHA-256 of the ZIP (outside the ZIP)

Untracked/ignored paths (data/, .venv/, node_modules/, secrets, logs, databases, .env) can never enter a package.
Every packaged text file is scanned for private keys and secret assignments; a hit aborts the build.
"""
import hashlib
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.22.0"
CLIENT_ZIP = "PepeMarketWizard_KLIENT_1_21_0.zip"
FORBIDDEN_PARTS = {".venv", "node_modules", "__pycache__", ".git"}
# exact dummy values used by tests to prove that secrets are never returned/logged (not real credentials)
ALLOWED_DUMMIES = {b"sk-ant-api03-SECRETVALUE-1234567890"}
SECRET_PATTERNS = [
    (re.compile(rb"-----BEGIN (?:ENCRYPTED |RSA |EC |OPENSSH )?PRIVATE KEY-----"), "PRIVATE_KEY"),
    (re.compile(rb"sk-ant-[A-Za-z0-9_\-]{20,}"), "ANTHROPIC_KEY"),
    (re.compile(rb"^(ANTHROPIC_API_KEY|TELEGRAM_BOT_TOKEN)=\S+", re.M), "SECRET_ASSIGNMENT"),
]


def tracked():
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True).stdout
    files = sorted(f for f in out.decode().split("\0") if f)
    return [f for f in files if not f.startswith(("release/", "frog_wizard_bot/")) and f != "MANIFEST_SHA256.txt"]   # Frog Wizard = separate product


def scan(files):
    bad = [f for f in files if FORBIDDEN_PARTS & set(Path(f).parts) or f.startswith("data/")
           or f.endswith((".env", ".sqlite", ".sqlite3", ".log", ".pem")) or Path(f).name.startswith("secrets.")]
    if bad:
        sys.exit(f"forbidden paths tracked: {bad}")
    hits = []
    for f in files:
        b = (ROOT / f).read_bytes()
        if b"\0" in b[:4096]:
            continue
        for rx, kind in SECRET_PATTERNS:
            if any(m.group(0) not in ALLOWED_DUMMIES for m in rx.finditer(b)):
                hits.append((f, kind))
    if hits:
        sys.exit(f"secret-like content in packaged files: {hits}")


def write_zip(name, top, files):
    out = ROOT / "release" / name
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in files:
            z.write(ROOT / f, top + f)
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    (out.parent / (name + ".sha256")).write_text(f"{digest}  {name}\n", encoding="utf-8", newline="\n")
    print(f"{name}: {len(files)} files, {out.stat().st_size} bytes, sha256 {digest}")


def main():
    files = tracked()
    client = files
    scan(client)
    lines = [f"{hashlib.sha256((ROOT / f).read_bytes()).hexdigest()}  {f}" for f in client]
    (ROOT / "MANIFEST_SHA256.txt").write_text(
        f"# PepeMarketWizard {VERSION} (klient) - SHA-256 of every packaged file (sha256sum format)\n" + "\n".join(lines) + "\n",
        encoding="utf-8", newline="\n")
    write_zip(CLIENT_ZIP, "PepeMarketWizard/", client + ["MANIFEST_SHA256.txt"])


if __name__ == "__main__":
    main()
