"""Builds MANIFEST_SHA256.txt and the package from git-tracked files only:

  release/PepeMarketWizard_OWNER_<ver>.zip            OWNER EDITION: bot (all strategies, signals, panel) + License Manager +
                                                      training installers for Windows; no license gate, no secrets
  release/PepeMarketWizard_LICENSE_SERVER_<ver>.zip   License API for your server (license_server/ + docs); no keys / database
  (+ .sha256 of each ZIP, outside the ZIP)
CLIENT EDITION packages are made by the owner from an OWNER package with tools/stamp_client_edition.py
(PRZYGOTUJ_PACZKE_KLIENTA.bat) - they need the address and the PUBLIC key of the owner's license server.

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
VERSION = "1.27.0"
OWNER_ZIP = f"PepeMarketWizard_OWNER_{VERSION.replace('.', '_')}.zip"   # derived from VERSION (a stale constant overwrote the previous release)
SERVER_ZIP = f"PepeMarketWizard_LICENSE_SERVER_{VERSION.replace('.', '_')}.zip"
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
    # Frog Wizard and the License API are separate products (the license server never ships inside the bot)
    return [f for f in files if not f.startswith(("release/", "frog_wizard_bot/", "license_server/")) and f != "MANIFEST_SHA256.txt"]


def server_files():
    out = subprocess.run(["git", "ls-files", "-z", "license_server"], cwd=ROOT, check=True, capture_output=True).stdout
    return sorted(f for f in out.decode().split("\0") if f) + ["docs/LICENCJE_SYSTEM_1_27_PL.md"]


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


def manifest_text(files, label: str = "klient") -> str:
    """MANIFEST_SHA256.txt of the program files - required by the launcher and the installers (complete unpacking check)."""
    lines = [f"{hashlib.sha256((ROOT / f).read_bytes()).hexdigest()}  {f}" for f in files]
    return f"# PepeMarketWizard {VERSION} ({label}) - SHA-256 of every packaged file (sha256sum format)\n" + "\n".join(lines) + "\n"


def main():
    files = tracked()
    client = files                     # the bot's program files (OWNER edition; CLIENT packages are stamped from them)
    scan(client)
    import json
    if json.loads((ROOT / "edition.json").read_text(encoding="utf-8")).get("edition") != "OWNER":
        sys.exit("edition.json of the repository must be OWNER (CLIENT packages: tools/stamp_client_edition.py)")
    (ROOT / "MANIFEST_SHA256.txt").write_text(manifest_text(client, "OWNER"), encoding="utf-8", newline="\n")
    write_zip(OWNER_ZIP, "PepeMarketWizard/", client + ["MANIFEST_SHA256.txt"])
    srv = server_files()
    scan(srv)
    write_zip(SERVER_ZIP, "PepeMarketWizard_LicenseServer/", srv)


if __name__ == "__main__":
    main()
