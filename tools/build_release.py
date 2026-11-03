"""Builds MANIFEST_SHA256.txt and the package from git-tracked files only:

  release/PepeMarketWizard_OWNER_<ver>.zip            OWNER EDITION: bot (all strategies, signals, panel) + License Manager +
                                                      training installers for Windows; no license gate, no secrets
  release/PepeMarketWizard_LICENSE_SERVER_<ver>.zip   License API for your server (license_server/ + docs); no keys / database
  (+ .sha256 of each ZIP, outside the ZIP)
CLIENT EDITION packages are made by the owner from an OWNER package with tools/stamp_client_edition.py
(PRZYGOTUJ_PACZKE_KLIENTA.bat) - they need the address and the PUBLIC key of the owner's license server.

Untracked/ignored paths (data/, .venv/, node_modules/, secrets, logs, databases, .env) can never enter a package.
Every packaged text file is scanned for private keys and secret assignments; a hit aborts the build.

1.29: a copy WITHOUT .git (GitHub "Download ZIP", an unpacked package) builds from the explicit file list of MANIFEST_SHA256.txt
(the previous build's list; files on disk that are not in it are reported, not packed). The license server is a separate product:
without git it is packed from license_server/ with the same exclusions, and a copy without that folder skips it with a message.
After writing, every ZIP is verified (tools/verify_release.py rules: no absolute / ../ paths, manifest hashes, no secrets).
"""
import hashlib
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.29.0"
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


SAFE_REL = re.compile(r"^(?!/)(?![A-Za-z]:)(?!.*(?:^|/)\.\.(?:/|$))[^\\\0]+$")      # relative, forward slashes, no '..'
SERVER_DOCS = ["docs/LICENCJE_SYSTEM_1_27_PL.md"]


def _git_list(*paths):
    """git ls-files, or None when this copy has no git metadata or git is not installed (then the explicit list is used)."""
    if not (ROOT / ".git").exists():
        return None
    try:
        out = subprocess.run(["git", "ls-files", "-z", *paths], cwd=ROOT, check=True, capture_output=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return sorted(f for f in out.decode().split("\0") if f)


def manifest_list(name: str = "MANIFEST_SHA256.txt") -> list[str]:
    """Explicit file list of a copy without git: the paths of MANIFEST_SHA256.txt (format sha256sum). Every path must be a safe
    relative path and exist; anything else stops the build (an incomplete copy must not become a release)."""
    p = ROOT / name
    if not p.exists():
        sys.exit(f"brak .git i brak {name} – nie wiadomo, które pliki należą do paczki (pobierz kopię z historią git albo pełną paczkę)")
    files, missing = [], []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        digest, sep, f = line.partition("  ")
        if not sep or not re.fullmatch(r"[0-9a-f]{64}", digest) or not SAFE_REL.match(f):
            sys.exit(f"{name}: nieprawidłowy wiersz: {line[:100]!r}")
        if not (ROOT / f).is_file():
            missing.append(f)
        files.append(f)
    if missing:
        sys.exit(f"{name}: brak {len(missing)} plików z listy, np. {missing[:5]} – kopia jest niekompletna")
    listed = set(files)
    extra = [str(q.relative_to(ROOT)).replace("\\", "/") for d in ("backend", "frontend/src", "docs", "tools", "desktop") if (ROOT / d).is_dir()
             for q in (ROOT / d).rglob("*") if q.is_file() and not (FORBIDDEN_PARTS & set(q.relative_to(ROOT).parts))]
    extra = sorted(x for x in extra if x not in listed and not x.endswith((".pyc", ".log", ".sqlite", ".tsbuildinfo")))
    if extra:
        print(f"UWAGA: {len(extra)} plików na dysku nie ma na liście {name} – nie wejdą do paczki (np. {extra[:8]})")
    return sorted(listed)


def tracked():
    files = _git_list()
    if files is None:
        print("brak .git – lista plików z MANIFEST_SHA256.txt (jawna lista poprzedniego wydania)")
        files = manifest_list()
    # Frog Wizard and the License API are separate products (the license server never ships inside the bot)
    return [f for f in files if not f.startswith(("release/", "frog_wizard_bot/", "license_server/")) and f != "MANIFEST_SHA256.txt"]


def server_files():
    """Files of the License API package, or None when this copy has no license_server/ (an unpacked bot package)."""
    files = _git_list("license_server")
    if files is None:
        d = ROOT / "license_server"
        if not d.is_dir():
            return None
        print("brak .git – serwer licencji z katalogu license_server/ (bez danych, baz, .env, logów, kluczy)")
        files = sorted(str(q.relative_to(ROOT)).replace("\\", "/") for q in d.rglob("*") if q.is_file()
                       and not (FORBIDDEN_PARTS & set(q.relative_to(ROOT).parts)) and "data" not in q.relative_to(d).parts
                       and not q.name.endswith((".pyc", ".sqlite", ".sqlite3", ".db", ".log", ".pem", ".key")) and q.name != ".env"
                       and not q.name.startswith("secrets."))
    return files + [f for f in SERVER_DOCS if (ROOT / f).is_file()]


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
    verify(ROOT / "release" / OWNER_ZIP, "PepeMarketWizard/")
    srv = server_files()
    if srv is None:
        print(f"{SERVER_ZIP}: pominięto – w tej kopii nie ma katalogu license_server/ (serwer licencji jest osobną paczką)")
        return
    scan(srv)
    write_zip(SERVER_ZIP, "PepeMarketWizard_LicenseServer/", srv)
    verify(ROOT / "release" / SERVER_ZIP, "PepeMarketWizard_LicenseServer/")


def verify(path: Path, top: str) -> None:
    sys.path.insert(0, str(ROOT / "tools"))
    import verify_release
    problems = verify_release.check_zip(path, top)
    if problems:
        sys.exit(f"{path.name}: weryfikacja nieudana: {problems[:10]}")
    print(f"{path.name}: weryfikacja OK (ścieżki, manifest, sekrety, plik .sha256)")


if __name__ == "__main__":
    main()
