"""Builds MANIFEST_SHA256.txt and release/MasterQUO_Accounts_Licensing_48H.zip from git-tracked files only.

Untracked/ignored paths (data/, .venv/, node_modules/, .env, secrets, logs) can never enter the package.
The archive separates three parts:
  1_DLA_KLIENTOW/MasterQUO_AI/          bot + monitor for customers (no server, no admin app, no tests)
  2_SERWER_ADMINISTRATORA/server/       central server + MasterQUO License Manager (never given to customers)
  3_ROZWOJ_I_TESTY/MasterQUO_AI/        full source tree with tests (developer only)
"""
import hashlib
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ZIP_NAME = "MasterQUO_Accounts_Licensing_48H.zip"
FORBIDDEN_PARTS = {".venv", "node_modules", "__pycache__", ".git", "dev-data", "secrets", "backups"}
CLIENT_EXCLUDE_PREFIX = ("server/", "tests/", "archive/")
CLIENT_EXCLUDE = {"INSTRUKCJA_ADMINISTRATOR.md", "05_TESTY_OFFLINE.bat", "tools/run_tests.py", "tools/build_release.py"}
# Test fixtures only (tests/test_app_process.py, tests/test_agent.py checks that secrets are masked) - not a real key.
FAKE_KEYS = {"sk-ant-api03-SECRETVALUE-1234567890", "sk-ant-test-not-a-real-key"}
SECRET_RX = re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----|sk-ant-[A-Za-z0-9_-]{8,}|MQL1-[A-Z2-7]{52}")

README = """MasterQUO 1.4.0 - konta, panel administratora, licencje 48 h
============================================================

1_DLA_KLIENTOW/MasterQUO_AI       - paczka, ktora dajesz klientom (bot + monitor). Bez serwera, panelu admina i testow.
                                    Instrukcja: INSTRUKCJA_UZYTKOWNIK.md, START_TUTAJ_PL.md.
2_SERWER_ADMINISTRATORA/server    - TYLKO dla Ciebie: serwer kont i licencji + MasterQUO License Manager (/admin/).
                                    Instrukcje: server/README_SERWER_PL.md, INSTRUKCJA_ADMINISTRATOR.md.
                                    NIE przekazuj tej czesci klientom.
3_ROZWOJ_I_TESTY/MasterQUO_AI     - pelne zrodla z testami (dla programisty), raport RAPORT_1_4_LICENCJE.md.

Paczka nie zawiera: kluczy prywatnych, hasel, plikow .env, prawdziwych licencji, baz uzytkownikow, .venv ani node_modules.
Klucze podpisu i konto administratora tworzysz na serwerze (gen-keys, bootstrap-admin).
Serwer NIE jest wdrozony publicznie - wdrozenie (domena, HTTPS, SMTP, PostgreSQL) opisuje README_SERWER_PL.md.
"""


def tracked():
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True).stdout
    files = sorted(f for f in out.decode().split("\0") if f)
    return [f for f in files if not f.startswith("release/") and f != "MANIFEST_SHA256.txt"]


def check(files):
    bad = [f for f in files if FORBIDDEN_PARTS & set(Path(f).parts) or f.startswith("data/")
           or f.endswith((".env", ".sqlite", ".log", ".pem", ".key")) or Path(f).name.startswith("secrets.")]
    if bad:
        sys.exit(f"forbidden paths tracked: {bad}")
    for f in files:
        if f.endswith(".zip"):
            continue
        for m in SECRET_RX.findall((ROOT / f).read_bytes()):
            if m.decode() not in FAKE_KEYS:
                sys.exit(f"possible secret in {f}: {m[:24]!r}")


def main():
    files = tracked()
    check(files)
    lines = [f"{hashlib.sha256((ROOT / f).read_bytes()).hexdigest()}  {f}" for f in files]
    (ROOT / "MANIFEST_SHA256.txt").write_text(
        "# MasterQUO AI 1.4.0 - SHA-256 of every source file (sha256sum format)\n" + "\n".join(lines) + "\n",
        encoding="utf-8", newline="\n")
    client = [f for f in files if not f.startswith(CLIENT_EXCLUDE_PREFIX) and f not in CLIENT_EXCLUDE]
    server = [f for f in files if f.startswith("server/")]
    out = ROOT / "release" / ZIP_NAME
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr("CZYTAJ_NAJPIERW.txt", README)
        for f in client:
            z.write(ROOT / f, "1_DLA_KLIENTOW/MasterQUO_AI/" + f)
        for f in server:
            z.write(ROOT / f, "2_SERWER_ADMINISTRATORA/" + f)
        z.write(ROOT / "INSTRUKCJA_ADMINISTRATOR.md", "2_SERWER_ADMINISTRATORA/INSTRUKCJA_ADMINISTRATOR.md")
        for f in files + ["MANIFEST_SHA256.txt"]:
            if f.endswith(".zip"):
                continue  # old archives stay in the repository only
            z.write(ROOT / f, "3_ROZWOJ_I_TESTY/MasterQUO_AI/" + f)
    print(f"client {len(client)}, server {len(server)}, dev {len(files)} files; {out} {out.stat().st_size} bytes")
    print("zip sha256", hashlib.sha256(out.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
