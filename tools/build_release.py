"""Builds MANIFEST_SHA256.txt and the package from git-tracked files only:

  release/Apollo23_<ver>.zip              the bot (all strategies, signals, panel) + training installers for Windows; no secrets
  (+ .sha256 next to the ZIP)
1.30: the license system was removed at the user's request. 1.44.0: two editions again, offline licences (Ed25519, no server):
  release/Apollo23_<ver>.zip                   OWNER  – wersja właściciela (z generatorem licencji)
  release/Apollo23_KLIENT_<ver>.zip            CLIENT – python tools/build_release.py --edition client: bez generatora, funkcji
                                               podpisywania i historii licencji; panel zbudowany z PMW_EDITION=CLIENT (kod generatora
                                               wycięty przy kompilacji); wymaga PUBLIC_KEY_HEX w backend/masterquo/licensing/client_config.py;
                                               1.46: + znacznik edycji klienta backend/masterquo/licensing/_edition.py (tylko w paczce klienta)
The Windows application package is built by tools/build_desktop.py from the same file list (--edition client as well).

Untracked/ignored paths (data/, .venv/, node_modules/, secrets, logs, databases, .env) can never enter a package.
Every packaged text file is scanned for private keys and secret assignments; a hit aborts the build (1.46: the rules of
tools/verify_release.py - one list of secret names, owner key formats, forbidden key / database names).

A copy WITHOUT .git (GitHub "Download ZIP", an unpacked package) builds from the explicit file list of MANIFEST_SHA256.txt
(the previous build's list; files on disk that are not in it are reported, not packed). After writing, the ZIP is verified
(tools/verify_release.py rules: no absolute / ../ paths, manifest hashes, no secrets). 1.46: the ZIP is written and verified in a
staging folder release/.<name>.*.tmp (ignored by git) and moved into release/ only when verification passed - a failed build leaves no
package and never overwrites the previous release of the version; the root MANIFEST_SHA256.txt is written after that as well.
"""
import argparse
import ast
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.45.0"
# 1.46: package file names carry the display name Apollo23 (the folder inside the ZIP, exe names, data paths and ids stay PepeMarketWizard)
APP_ZIP = f"Apollo23_{VERSION.replace('.', '_')}.zip"   # derived from VERSION (a stale constant overwrote the previous release)
FORBIDDEN_PARTS = {".venv", "node_modules", "__pycache__", ".git"}
# 1.46: secret patterns, test dummies and forbidden names live in ONE place - tools/verify_release.py (SECRETS, CONFIG_SECRETS,
# ALLOWED_DUMMIES, forbidden_file); the old 3-pattern list here did not know the owner key, FRED / CoinGlass / MT5, *.key or *.db


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
    # 1.42: archive/ (old UI 1.41) and update_1_42/ (update package, reference HTML, screenshots) never go into a release
    # 1.46: tools/research/ = one-off research scripts with paths of a past session (and their raw results), never packaged
    return [f for f in files if not f.startswith(("release/", "frog_wizard_bot/", "archive/", "update_1_42/", "update_charts/", "update_intro3d/",
                                                  "tools/research/")) and f != "MANIFEST_SHA256.txt"]


def scan(files):
    vr = _verify_module()
    # 1.46: + the name rules of tools/verify_release.py (private.key, licenses.db, *.key, *.db, config.json, .env.*)
    bad = [f for f in files if FORBIDDEN_PARTS & set(Path(f).parts) or f.startswith("data/")
           or f.endswith((".env", ".sqlite", ".sqlite3", ".log", ".pem")) or Path(f).name.startswith("secrets.") or vr.forbidden_file(f)]
    if bad:
        sys.exit(f"forbidden paths tracked: {bad}")
    seeds = vr.owner_seed_markers()
    hits = []
    for f in files:
        # 1.46: the content rules of tools/verify_release.py (owner key in every form, every secret name, raw Telegram token, UTF-16)
        hits += [(f, kind) for kind in vr.secret_hits(f, (ROOT / f).read_bytes(), seeds)]
    if hits:
        sys.exit(f"secret-like content in packaged files: {hits}")


def publish_zip(name: str, top: str, fill) -> str:
    """1.46: writes release/<name> through a staging folder: fill(zipfile) writes the entries into release/.<name>.*.tmp/<name> (ignored by
    git), the .sha256 is written next to it, verify() checks both there, and only then are they moved into release/. A failed verification
    (sys.exit) leaves nothing behind and never overwrites the published package of the same version (was: written first, verified after).
    Returns the SHA-256 of the published ZIP."""
    rel = ROOT / "release"
    rel.mkdir(exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{name}.", suffix=".tmp", dir=rel))
    try:
        tmp = stage / name
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            fill(z)
        digest = hashlib.sha256(tmp.read_bytes()).hexdigest()
        side = stage / (name + ".sha256")
        side.write_text(f"{digest}  {name}\n", encoding="utf-8", newline="\n")
        verify(tmp, top)
        os.replace(tmp, rel / name)
        os.replace(side, rel / (name + ".sha256"))
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return digest


def write_zip(name, top, files, data: dict[str, bytes] | None = None):
    """data: content of a listed file taken from memory instead of disk (1.46: the new MANIFEST_SHA256.txt before it is written)."""
    data = data or {}

    def fill(z):
        for f in files:
            if f in data:
                z.writestr(top + f, data[f])
            else:
                z.write(ROOT / f, top + f)
    digest = publish_zip(name, top, fill)
    print(f"{name}: {len(files)} files, {(ROOT / 'release' / name).stat().st_size} bytes, sha256 {digest}")


def manifest_text(files, label: str = "klient") -> str:
    """MANIFEST_SHA256.txt of the program files - required by the launcher and the installers (complete unpacking check)."""
    lines = [f"{hashlib.sha256((ROOT / f).read_bytes()).hexdigest()}  {f}" for f in files]
    return f"# Apollo23 {VERSION} ({label}) - SHA-256 of every packaged file (sha256sum format)\n" + "\n".join(lines) + "\n"


# ------------------------------------------------------------------------------------------------ 1.44.0 edycje
CLIENT_CONFIG = "backend/masterquo/licensing/client_config.py"


def _verify_module():
    sys.path.insert(0, str(ROOT / "tools"))
    import verify_release
    return verify_release


def client_public_key(allow_foreign: bool = False) -> str:
    """PUBLIC_KEY_HEX z client_config.py – pusty / zły = czytelny błąd i brak paczki. Gdy na tym komputerze jest klucz właściciela:
    wpis nie może być jego kluczem PRYWATNYM i powinien być jego kluczem publicznym (inaczej licencje z tego generatora nie zadziałają)."""
    tree = ast.parse((ROOT / CLIENT_CONFIG).read_text(encoding="utf-8"))
    val = next((n.value.value for n in tree.body if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "PUBLIC_KEY_HEX" for t in n.targets)
                and isinstance(n.value, ast.Constant)), None)
    v = (val or "").strip().lower()
    if not v:
        sys.exit(f"BŁĄD: {CLIENT_CONFIG}: PUBLIC_KEY_HEX jest pusty.\n"
                 "Wklej klucz publiczny z wersji właściciela (panel systemowy → zakładka „Generator licencji” → Klucz publiczny (hex) → Kopiuj).\n"
                 "Paczka klienta NIE została zbudowana.")
    if not re.fullmatch(r"[0-9a-f]{64}", v):
        sys.exit(f"BŁĄD: {CLIENT_CONFIG}: PUBLIC_KEY_HEX musi mieć dokładnie 64 znaki 0-9 a-f (jest {len(v)}). Paczka klienta NIE została zbudowana.")
    try:
        sys.path.insert(0, str(ROOT / "backend"))
        from masterquo.licensing.owner import owner_dir, parse_key_file
        kp = owner_dir() / "private.key"
        if kp.exists():
            seed, pub = parse_key_file(kp.read_text(encoding="ascii"))
            if v == seed.hex():
                sys.exit("BŁĄD KRYTYCZNY: PUBLIC_KEY_HEX to Twój klucz PRYWATNY! Wklej klucz PUBLICZNY. Paczka NIE została zbudowana.")
            if v != pub.hex() and not allow_foreign:
                sys.exit(f"BŁĄD: PUBLIC_KEY_HEX nie pasuje do klucza właściciela na tym komputerze ({kp}) – licencje wydane tutaj nie "
                         "zadziałałyby w tej paczce. Wklej klucz publiczny z zakładki „Generator licencji” albo użyj --allow-foreign-key.")
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - brak PyNaCl / klucza na maszynie budującej: sprawdzenie zgodności pominięte
        print(f"uwaga: zgodności PUBLIC_KEY_HEX z kluczem właściciela nie sprawdzono ({type(exc).__name__})")
    return v


def build_client_frontend() -> Path:
    """Panel klienta: vite build z PMW_EDITION=CLIENT (kod generatora licencji wycięty przy kompilacji) do build/client_dist."""
    out = ROOT / "build" / "client_dist"
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if not npx:
        sys.exit("BŁĄD: brak Node.js (npx) – panel klienta musi zostać zbudowany z PMW_EDITION=CLIENT. Paczka klienta NIE została zbudowana.")
    r = subprocess.run([npx, "vite", "build", "--outDir", str(out), "--emptyOutDir"], cwd=ROOT / "frontend",
                       env=dict(os.environ, PMW_EDITION="CLIENT"), capture_output=True, text=True)
    if r.returncode != 0 or not (out / "index.html").exists():
        sys.exit("BŁĄD: budowanie panelu klienta nieudane:\n" + (r.stdout + r.stderr)[-3000:])
    return out


def client_marker() -> Path:
    """1.46: client edition marker (masterquo/licensing/edition.py: the file exists = CLIENT). Without it an empty owner.py added to a client
    package (or left over from an older owner / 1.43 install) made it an OWNER edition: no licence required, PMW_TEST_* overrides active.
    Written into the git-ignored build/ folder and packed ONLY into client packages - never into the repository or an owner package."""
    p = ROOT / "build" / "client_marker" / "_edition.py"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# 1.46: znacznik edycji klienta - masterquo/licensing/edition.py: ten plik istnieje = wersja KLIENTA\n"
                 'EDITION = "CLIENT"\n', encoding="utf-8", newline="\n")
    return p


def edition_entries(edition: str = "owner", *, allow_foreign: bool = False) -> list[tuple[str, Path]]:
    """[(ścieżka w paczce, plik źródłowy)] dla edycji. OWNER = pliki z gita; CLIENT = bez plików właściciela, panel klienta zamiast
    frontend/dist, kontrola: brak kodu generatora / podpisywania (te same reguły co tools/verify_release.py)."""
    files = tracked()
    scan(files)
    if edition == "owner":
        return [(f, ROOT / f) for f in files]
    vr = _verify_module()
    client_public_key(allow_foreign)
    dist = build_client_frontend()
    keep = [f for f in files if f not in vr.OWNER_ONLY and not f.startswith("frontend/dist/") and f != vr.CLIENT_EDITION_MARKER]
    entries = [(f, ROOT / f) for f in keep]
    entries += [("frontend/dist/" + p.relative_to(dist).as_posix(), p) for p in sorted(dist.rglob("*")) if p.is_file()]
    entries.append((vr.CLIENT_EDITION_MARKER, client_marker()))
    src = dict(entries)
    rels = [r for r, _ in entries]
    bad = vr.client_problems(lambda r: src[r].read_bytes(), rels) + vr.edition_problems(rels, client=True)
    if bad:
        sys.exit("BŁĄD: paczka klienta zawierałaby elementy wersji właściciela:\n" + "\n".join(bad[:20]))
    return entries


def manifest_entries(entries, label: str) -> str:
    lines = [f"{hashlib.sha256(src.read_bytes()).hexdigest()}  {rel}" for rel, src in entries]
    return f"# Apollo23 {VERSION} ({label}) - SHA-256 of every packaged file (sha256sum format)\n" + "\n".join(lines) + "\n"


def write_zip_entries(name, top, entries, extra: dict[str, bytes]):
    def fill(z):
        for rel, src in entries:
            z.write(src, top + rel)
        for rel, data in extra.items():
            z.writestr(top + rel, data)
    digest = publish_zip(name, top, fill)              # 1.46: staged + verified before it replaces release/<name>
    print(f"{name}: {len(entries) + len(extra)} files, {(ROOT / 'release' / name).stat().st_size} bytes, sha256 {digest}")


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
    ap = argparse.ArgumentParser()
    ap.add_argument("--edition", choices=("owner", "client"), default="owner", help="client = paczka klienta z weryfikacją licencji")
    ap.add_argument("--allow-foreign-key", action="store_true", help="PUBLIC_KEY_HEX może nie pasować do klucza właściciela na tym komputerze")
    a = ap.parse_args()
    if a.edition == "client":
        entries = edition_entries("client", allow_foreign=a.allow_foreign_key)
        check_windows_requirements()
        name = f"Apollo23_KLIENT_{VERSION.replace('.', '_')}.zip"
        write_zip_entries(name, "PepeMarketWizard/", entries,      # verified inside (publish_zip)
                          {"MANIFEST_SHA256.txt": manifest_entries(entries, "program – wersja klienta").encode("utf-8")})
        return
    files = tracked()
    scan(files)
    check_windows_requirements()
    mtext = manifest_text(files, "program")
    # 1.46: the package takes the new manifest from memory and is verified before it is published; the root MANIFEST_SHA256.txt (the
    # explicit file list of copies without git) is overwritten only after that - a failed build changes neither
    write_zip(APP_ZIP, "PepeMarketWizard/", files + ["MANIFEST_SHA256.txt"], {"MANIFEST_SHA256.txt": mtext.encode("utf-8")})
    (ROOT / "MANIFEST_SHA256.txt").write_text(mtext, encoding="utf-8", newline="\n")


def verify(path: Path, top: str) -> None:
    sys.path.insert(0, str(ROOT / "tools"))
    import verify_release
    problems = verify_release.check_zip(path, top)
    if problems:
        sys.exit(f"{path.name}: weryfikacja nieudana: {problems[:10]}")
    print(f"{path.name}: weryfikacja OK (ścieżki, manifest, sekrety, plik .sha256)")


if __name__ == "__main__":
    main()
