"""Builds MANIFEST_SHA256.txt and two SEPARATE packages from git-tracked files only:

  release/MasterQUO_KLIENT_1_8_0.zip            bot for Windows (no license server, no secrets, no admin rights)
  release/MasterQUO_SERWER_LICENCJI_1_8_0.zip   license server + administrator panel (server/ only, no keys, no database)

Untracked/ignored paths (data/, .venv/, node_modules/, secrets, logs, databases, .env) can never enter a package.
Every packaged text file is scanned for private keys, license keys and secret assignments; a hit aborts the build.
"""
import hashlib
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.8.0"
CLIENT_ZIP = "MasterQUO_KLIENT_1_8_0.zip"
SERVER_ZIP = "MasterQUO_SERWER_LICENCJI_1_8_0.zip"
FORBIDDEN_PARTS = {".venv", ".venv-server", "node_modules", "__pycache__", ".git"}
SERVER_DOCS = ["INSTRUKCJA_WINDOWS_PL.md", "AUDYT_MASTERQUO.md", "CHANGELOG.md"]
# exact dummy values used by tests to prove that secrets are never returned/logged (not real credentials)
ALLOWED_DUMMIES = {b"sk-ant-api03-SECRETVALUE-1234567890"}
SECRET_PATTERNS = [
    (re.compile(rb"-----BEGIN (?:ENCRYPTED |RSA |EC |OPENSSH )?PRIVATE KEY-----"), "PRIVATE_KEY"),
    (re.compile(rb"MQL72(?:-[A-HJ-NP-Z2-9]{5}){10}-[A-HJ-NP-Z2-9]{2}"), "LICENSE_KEY"),
    (re.compile(rb"sk-ant-[A-Za-z0-9_\-]{20,}"), "ANTHROPIC_KEY"),
    (re.compile(rb"^(MQL_KEY_PEPPER|MQL_DATA_KEY|ANTHROPIC_API_KEY|TELEGRAM_BOT_TOKEN)=\S+", re.M), "SECRET_ASSIGNMENT"),
]


def tracked():
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True).stdout
    files = sorted(f for f in out.decode().split("\0") if f)
    return [f for f in files if not f.startswith("release/") and f != "MANIFEST_SHA256.txt"]


def scan(files):
    bad = [f for f in files if FORBIDDEN_PARTS & set(Path(f).parts) or f.startswith(("data/", "server/data/", "server/secrets/"))
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


def write_zip(name, top, files, extra=None):
    out = ROOT / "release" / name
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in files:
            z.write(ROOT / f, top + f)
        for src, dst in (extra or {}).items():          # convenience copies (e.g. server launchers also at the package root)
            z.write(ROOT / src, top + dst)
    print(f"{name}: {len(files)} files, {out.stat().st_size} bytes, sha256 {hashlib.sha256(out.read_bytes()).hexdigest()}")


def main():
    files = tracked()
    client = [f for f in files if not f.startswith("server/")]
    server = [f for f in files if f.startswith("server/")] + [d for d in SERVER_DOCS if d in files]
    scan(client + server)
    assert not any("mqlicense" in f for f in client), "client package must not contain the license server"
    lines = [f"{hashlib.sha256((ROOT / f).read_bytes()).hexdigest()}  {f}" for f in client]
    (ROOT / "MANIFEST_SHA256.txt").write_text(
        f"# MasterQUO AI {VERSION} (klient) - SHA-256 of every packaged file (sha256sum format)\n" + "\n".join(lines) + "\n",
        encoding="utf-8", newline="\n")
    write_zip(CLIENT_ZIP, "MasterQUO_AI/", client + ["MANIFEST_SHA256.txt"])
    # the server .bat files find the server folder themselves, so they also work from the package root
    launchers = {f: Path(f).name for f in server if f.startswith("server/") and f.count("/") == 1 and f.endswith(".bat")}
    write_zip(SERVER_ZIP, "MasterQUO_SERWER_LICENCJI/", server, launchers)


if __name__ == "__main__":
    main()
