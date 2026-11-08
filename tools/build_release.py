"""Builds MANIFEST_SHA256.txt and the package from git-tracked files only:

  release/PepeMarketWizard_<ver>.zip      the bot (all strategies, signals, panel) + training installers for Windows; no secrets
  (+ .sha256 next to the ZIP)
1.30: the license system was removed at the user's request - one edition, no OWNER / CLIENT packages, no license server.
The Windows application package is built by tools/build_desktop.py from the same file list.

Untracked/ignored paths (data/, .venv/, node_modules/, secrets, logs, databases, .env) can never enter a package.
Every packaged text file is scanned for private keys and secret assignments; a hit aborts the build.

A copy WITHOUT .git (GitHub "Download ZIP", an unpacked package) builds from the explicit file list of MANIFEST_SHA256.txt
(the previous build's list; files on disk that are not in it are reported, not packed). After writing, the ZIP is verified
(tools/verify_release.py rules: no absolute / ../ paths, manifest hashes, no secrets).
"""
import hashlib
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.35.0"
APP_ZIP = f"PepeMarketWizard_{VERSION.replace('.', '_')}.zip"   # derived from VERSION (a stale constant overwrote the previous release)
FORBIDDEN_PARTS = {".venv", "node_modules", "__pycache__", ".git"}
# exact dummy values used by tests to prove that secrets are never returned/logged (not real credentials)
ALLOWED_DUMMIES = {b"sk-ant-api03-SECRETVALUE-1234567890"}
SECRET_PATTERNS = [
    (re.compile(rb"-----BEGIN (?:ENCRYPTED |RSA |EC |OPENSSH )?PRIVATE KEY-----"), "PRIVATE_KEY"),
    (re.compile(rb"sk-ant-[A-Za-z0-9_\-]{20,}"), "ANTHROPIC_KEY"),
    (re.compile(rb"^(ANTHROPIC_API_KEY|TELEGRAM_BOT_TOKEN)=\S+", re.M), "SECRET_ASSIGNMENT"),
]


SAFE_REL = re.compile(r"^(?!/)(?![A-Za-z]:)(?!.*(?:^|/)\.\.(?:/|$))[^\\\0]+$")      # relative, forward slashes, no '..'


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
    # Frog Wizard is a separate product
    return [f for f in files if not f.startswith(("release/", "frog_wizard_bot/")) and f != "MANIFEST_SHA256.txt"]


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


def check_windows_requirements() -> None:
    """1.34.1: a package is never built with a requirements file that does not install on Windows (tools/check_requirements_win.py).
    Without uv / network the check is reported as NOT RUN - it never counts as passed."""
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "check_requirements_win.py")], capture_output=True, text=True)
    print(r.stdout.strip())
    if r.returncode == 2:
        print("UWAGA: kontrola instalacji Windows NIE została uruchomiona (brak uv) – pip install uv", file=sys.stderr)
    elif r.returncode != 0:
        sys.exit("requirements dla Windows nie instalują się – paczka nie zostanie zbudowana:\n" + r.stdout + r.stderr)


def main():
    files = tracked()
    scan(files)
    check_windows_requirements()
    (ROOT / "MANIFEST_SHA256.txt").write_text(manifest_text(files, "program"), encoding="utf-8", newline="\n")
    write_zip(APP_ZIP, "PepeMarketWizard/", files + ["MANIFEST_SHA256.txt"])
    verify(ROOT / "release" / APP_ZIP, "PepeMarketWizard/")


def verify(path: Path, top: str) -> None:
    sys.path.insert(0, str(ROOT / "tools"))
    import verify_release
    problems = verify_release.check_zip(path, top)
    if problems:
        sys.exit(f"{path.name}: weryfikacja nieudana: {problems[:10]}")
    print(f"{path.name}: weryfikacja OK (ścieżki, manifest, sekrety, plik .sha256)")


if __name__ == "__main__":
    main()
