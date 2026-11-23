"""Verifies release archives before they are handed out (1.29, §5 of the update package).

  python tools/verify_release.py release/Apollo23_DESKTOP_1_46_0.zip [more.zip ...]
  python tools/verify_release.py --all          every ZIP of the current VERSION in release/

Per archive:
  * every entry name is a safe relative path under one top folder (no absolute path, drive letter, backslash, '..' - ZIP-slip),
    no duplicates, no symlink entries;
  * the <zip>.sha256 next to the archive matches;
  * MANIFEST_SHA256.txt / MANIFEST_DESKTOP_SHA256.txt inside: every listed file exists in the archive with that SHA-256 (and, for the
    desktop manifest, every file of the archive is listed);
  * no forbidden files (data/, databases, .env, keys, leftovers of the removed 1.27-1.29 license system) and no private key /
    API key / token assignment in text entries; no license server or license module (removed in 1.30).
  * 1.46: MANIFEST_SHA256.txt is required (DESKTOP: also MANIFEST_DESKTOP_SHA256.txt) and in the folder package lists every file;
    files that the package's own installers / launcher check for must be present; names differing only in case are refused;
    one secret rule set (SECRET_NAMES, SECRETS, CONFIG_SECRETS, forbidden names) shared with tools/build_release.py.
Exit code 0 only when every archive passes. Nothing is extracted to disk. A damaged archive is a FAIL line, not a traceback.
"""
from __future__ import annotations

import hashlib
import re
import stat
import sys
import zipfile
import zlib
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_NAMES = {"private.key", "licenses.db", "license_owner.json", "signing_key.pem", ".env", "license_owner_key.dpapi", "license_owner_key.local.json",
                   "secrets.json", "secrets.dpapi", "masterquo.sqlite", "config.json"}
FORBIDDEN_SUFFIX = (".sqlite", ".sqlite3", ".db", ".pem", ".key", ".log", ".pyc", ".env")   # 1.46: + .env (secrets.env, prod.env passed)
FORBIDDEN_PARTS = {".git", ".venv", "node_modules", "__pycache__"}
# exact dummy values used by tests to prove that secrets are never returned / logged / exported (not real credentials)
ALLOWED_DUMMIES = {b"sk-ant-api03-SECRETVALUE-1234567890", b"sk-ant-api03-abcdefghijklmnopqrstuvwxyz",
                   b"123456789:AAFakeTelegramTokenForTests_abcdefghijklmn"}
# 1.46: ONE list of secret names for every rule (the scan knew only 2-4 of them): masterquo.secrets_store.ALLOWED (= exports.core.SECRET_NAMES)
# + the secrets of the 1.27-1.29 license server
SECRET_NAMES = ("ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN", "FRED_API_KEY", "MT5_PASSWORD", "COINGLASS_API_KEY",
                "PMW_ADMIN_PASSWORD_HASH", "PMW_SIGNING_KEY")
_NAMES = b"|".join(n.encode() for n in SECRET_NAMES)
SECRETS = [
    (re.compile(rb"-----BEGIN (?:ENCRYPTED |RSA |EC |OPENSSH )?PRIVATE KEY-----"), "PRIVATE_KEY"),
    # 1.43.0 generator licencji. 1.46: also in the middle of a line and with an escaped newline (JSON of the key export API) ...
    (re.compile(rb"PMW-OWNER-ED25519-PRIVATE-KEY v1(?:\\r)?(?:\\n|\r?\n)seed: [0-9a-fA-F]{64}"), "PMW_OWNER_PRIVATE_KEY"),
    # ... and a "seed: <64 hex>" / "seed = <64 hex>" line on its own (key file cut or retyped)
    (re.compile(rb"(?<![A-Za-z0-9_])seed[\"']?[ \t]*[:=][ \t]*[\"']?[0-9a-fA-F]{64}(?![0-9a-fA-F])"), "PMW_OWNER_PRIVATE_KEY"),
    (re.compile(rb"sk-ant-[A-Za-z0-9_\-]{20,}"), "ANTHROPIC_KEY"),
    (re.compile(rb"\b\d{6,12}:[A-Za-z0-9_\-]{30,}\b"), "TELEGRAM_TOKEN"),    # 1.46: raw bot token <id>:<35 chars> (as exports.core)
    (re.compile(rb"^(" + _NAMES + rb")=\S+", re.MULTILINE), "SECRET_ASSIGNMENT"),
]
# 1.46: files that hold settings (.env*, scripts, JSON / INI / TOML / YAML / TXT): also "NAME = value", "set NAME=", "export NAME=",
# "$env:NAME =" and "\"NAME\": \"value\"" (values of 6+ characters; %VAR%, $VAR, <placeholder> and empty values are not secrets). Source
# code (.py/.ts/.js) and docs (.md) are not matched by these: tests and READMEs name the variables with dummy / placeholder values.
CONFIG_SUFFIX = (".env", ".bat", ".cmd", ".ps1", ".sh", ".txt", ".json", ".ini", ".cfg", ".conf", ".toml", ".yaml", ".yml",
                 ".properties", ".example")
CONFIG_SECRETS = [
    (re.compile(rb"^[ \t]*(?:set[ \t]+\"?|export[ \t]+|\$env:)?(" + _NAMES + rb")[ \t]*=[ \t]*[\"']?[^\s\"'#$%<]{6,}",
                re.MULTILINE | re.IGNORECASE), "SECRET_ASSIGNMENT"),
    (re.compile(rb"[\"'](" + _NAMES + rb")[\"'][ \t]*:[ \t]*[\"'][^\s\"'$%<]{6,}", re.IGNORECASE), "SECRET_ASSIGNMENT"),
]
_COMPACT_KEY = re.compile(rb"\s*(?:[0-9a-fA-F]{64}|[0-9a-fA-F]{128})\s*")   # owner.parse_key_file: bare seed (64) or seed + public (128)


def safe_name(n: str, top: str) -> str | None:
    if not n or "\\" in n or "\0" in n or n.startswith("/") or re.match(r"^[A-Za-z]:", n):
        return "niebezpieczna ścieżka"
    p = PurePosixPath(n)
    if ".." in p.parts:
        return "ścieżka z '..'"
    if top and not n.startswith(top):
        return f"poza folderem {top}"
    return None


def _manifest(text: str, bad: list[int] | None = None) -> dict[str, str]:
    out = {}
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        # 1.46: upper-case sums and the sha256sum binary form "<hash> *<file>" are read; any other line is reported in `bad` (was
        # skipped silently, so a changed file with such a line was never checked)
        m = re.fullmatch(r"([0-9a-fA-F]{64}) [ *](.+)", line)
        if m:
            out[m.group(2)] = m.group(1).lower()
        elif bad is not None:
            bad.append(n)
    return out


def forbidden_file(rel: str) -> bool:
    """Name rules for one packaged file (relative path inside the package; shared with tools/build_release.py scan())."""
    parts = PurePosixPath(rel).parts
    name = parts[-1]
    runtime = rel.startswith("runtime/python/")          # bundled CPython: stdlib secrets.py, pip's public CA bundle (cacert.pem)
    secret_store = name.startswith("secrets.") and name.endswith((".json", ".dpapi"))   # the app's own secret store (data/secrets.*)
    suffix_bad = name.endswith(FORBIDDEN_SUFFIX) and not (runtime and name.endswith((".pem", ".pyc")))
    env_file = name.startswith(".env") and name != ".env.example"     # 1.46: .env.local, .env.production ... (.env.example: scanned)
    return bool(FORBIDDEN_PARTS & set(parts) - ({"__pycache__"} if runtime else set()) or rel.startswith("data/")
                or name in FORBIDDEN_NAMES or suffix_bad or secret_store or env_file)


def _scan_text(b: bytes) -> bytes | None:
    """Bytes to scan: UTF-16 with BOM (PowerShell 5 '>' redirection, Notepad "Unicode") decoded to UTF-8 (1.46: was skipped as binary);
    other content with NUL in the first 4 KiB is binary -> None."""
    if b[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return b.decode("utf-16", errors="replace").encode("utf-8")
    if b"\0" in b[:4096]:
        return None
    return b


def secret_hits(rel: str, b: bytes, owner_seeds: list[bytes] | tuple = ()) -> list[str]:
    """Kinds of secrets found in one packaged file (shared with tools/build_release.py scan()). owner_seeds = owner_seed_markers()."""
    t = _scan_text(b)
    if t is None:
        return []
    name = rel.rsplit("/", 1)[-1].lower()
    rules = SECRETS + (CONFIG_SECRETS if name.startswith(".env") or name.endswith(CONFIG_SUFFIX) else [])
    kinds: list[str] = []
    for rx, kind in rules:
        if kind not in kinds and any(m.group(0) not in ALLOWED_DUMMIES for m in rx.finditer(t)):
            kinds.append(kind)
    if len(t) <= 300 and _COMPACT_KEY.fullmatch(t) and "PMW_OWNER_PRIVATE_KEY" not in kinds:
        kinds.append("PMW_OWNER_PRIVATE_KEY")                      # 1.46: compact key file (accepted by owner.parse_key_file)
    if owner_seeds:
        low = t.lower()
        if any(s in low for s in owner_seeds):
            kinds.append("PMW_OWNER_SEED")
    return kinds


def owner_seed_markers() -> list[bytes]:
    """1.46: the seed (lower-case hex) of the owner's private key kept on THIS computer (masterquo.licensing.owner.owner_dir()/private.key,
    PMW format or compact hex). Every text entry is searched for it, so a copy under any name, in any format or case (also pasted into
    client_config.py instead of the public key) is refused. No key file / no owner module (client copy) -> [] (the rules above still apply)."""
    try:
        backend = str(ROOT / "backend")
        if backend not in sys.path:
            sys.path.insert(0, backend)
        from masterquo.licensing.owner import owner_dir
        p = owner_dir() / "private.key"
        text = p.read_text(encoding="ascii", errors="replace") if p.is_file() else ""
    except Exception:  # noqa: BLE001 - no backend / unreadable key: nothing to compare against
        return []
    m = re.search(r"seed:\s*([0-9a-fA-F]{64})", text) or re.fullmatch(r"\s*([0-9a-fA-F]{64})(?:[0-9a-fA-F]{64})?\s*", text)
    return [m.group(1).lower().encode()] if m else []


_REQ_BAT = re.compile(rb"for %%F in \((.*?)\) do")
_REQ_GO = re.compile(rb"var required = \[\]string\{(.*?)\}", re.DOTALL)


def installer_required(read, files) -> set[str]:
    """1.46: files that the package's own installers (for %%F in (...) lists) and launcher (tools/launcher/main.go `required`) check
    before they start the program - a package without one of them stops with "Niekompletny folder programu"."""
    need: set[str] = set()
    for src, rx, item in (("00_TRENING_START.bat", _REQ_BAT, rb'"([^"]+)"'), ("01_INSTALUJ.bat", _REQ_BAT, rb'"([^"]+)"'),
                          ("INSTALUJ_TRENING.bat", _REQ_BAT, rb'"([^"]+)"'), ("tools/launcher/main.go", _REQ_GO, rb"`([^`]+)`")):
        if src in files:
            m = rx.search(read(src))
            if m:
                need |= {x.decode("utf-8", "replace").replace("\\", "/") for x in re.findall(item, m.group(1))}
    return need


# 1.44.0 paczka KLIENTA (nazwa z „KLIENT”): bez generatora licencji, funkcji podpisywania i klucza prywatnego, z kluczem publicznym wydawcy.
OWNER_ONLY = ("backend/masterquo/licensing/owner.py", "backend/masterquo/licensing/signing.py", "backend/masterquo/api/owner_routes.py",
              "frontend/src/features/system/LicenseGeneratorPanel.tsx", "tests/test_licensing.py", "tests/test_license_client.py",
              "docs/LICENCJE_PMW1_PL.md")
CLIENT_MARKERS = (b"SigningKey", b"sign_license", b"/api/v1/owner/", b"LicenseGeneratorPanel", b"GENERATOR LICENCJI",
                  b"PMW-OWNER-ED25519-PRIVATE-KEY")
PUBKEY_RX = re.compile(rb'^PUBLIC_KEY_HEX\s*=\s*"([^"]*)"', re.M)


def client_problems(read, rels) -> list[str]:
    """read(rel) -> bytes; rels = ścieżki względne plików paczki."""
    out = [f"{r}: plik wersji właściciela w paczce klienta" for r in rels if r in OWNER_ONLY]
    for r in rels:
        if (r.startswith("backend/") and r.endswith(".py")) or r.startswith("frontend/dist/"):
            b = read(r)
            for m in CLIENT_MARKERS:
                if m in b:
                    out.append(f"{r}: kod generatora / podpisywania w paczce klienta ({m.decode()})")
    cfg = "backend/masterquo/licensing/client_config.py"
    if cfg not in rels:
        out.append(f"brak {cfg}")
    else:
        m = PUBKEY_RX.search(read(cfg))
        if not m or not re.fullmatch(rb"[0-9a-fA-F]{64}", m.group(1)):
            out.append(f"{cfg}: PUBLIC_KEY_HEX pusty albo nie ma 64 znaków hex")
    return out


def check_zip(path: Path, top: str | None = None) -> list[str]:
    path = Path(path)
    problems: list[str] = []
    if not path.exists():
        return [f"brak pliku {path}"]
    try:
        _check_zip(path, top, problems)
    except (zipfile.BadZipFile, OSError, RuntimeError, EOFError, NotImplementedError, ValueError, zlib.error) as exc:
        # 1.46: not a ZIP / damaged / encrypted entry / bad encoding = a problem of THIS archive (was a traceback that stopped --all)
        problems.append(f"archiwum nieczytelne: {type(exc).__name__}: {exc}")
    return problems


def _check_zip(path: Path, top: str | None, problems: list[str]) -> None:
    side = path.with_name(path.name + ".sha256")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if not side.exists():
        problems.append("brak pliku .sha256")
    else:
        # 1.46: empty sidecar = problem (was IndexError); BOM (PowerShell 5 "UTF8") and upper-case sums (Get-FileHash, certutil) accepted
        words = side.read_text(encoding="utf-8-sig", errors="replace").split()
        if not words:
            problems.append("pusty plik .sha256")
        elif words[0].lower() != digest:
            problems.append("plik .sha256 nie zgadza się z archiwum")
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        names = [i.filename for i in infos]
        if top is None:
            tops = {n.split("/", 1)[0] + "/" for n in names}
            top = tops.pop() if len(tops) == 1 else ""
            if not top:
                problems.append("więcej niż jeden folder główny")
        if len(set(names)) != len(names):
            problems.append("zduplikowane wpisy")
        elif len({n.casefold() for n in names}) != len(names):
            # 1.46: Windows (NTFS) unpacks backend/A.py and backend/a.py into ONE file - the program would differ from the manifest
            seen: dict[str, str] = {}
            clash = [n for n in names if seen.setdefault(n.casefold(), n) != n]
            problems.append(f"wpisy różniące się tylko wielkością liter: {clash[:5]}")
        files: dict[str, zipfile.ZipInfo] = {}
        for i in infos:
            bad = safe_name(i.filename, top)
            if bad:
                problems.append(f"{i.filename}: {bad}")
                continue
            mode = (i.external_attr >> 16) & 0o170000
            if mode == stat.S_IFLNK:
                problems.append(f"{i.filename}: dowiązanie symboliczne")
            if not i.is_dir():
                files[i.filename[len(top):]] = i
        for rel in files:
            if forbidden_file(rel):
                problems.append(f"{rel}: plik zabroniony w paczce")
        seeds = owner_seed_markers()
        for rel, info in files.items():
            if info.file_size > 20_000_000 or rel.endswith((".png", ".jpg", ".gif", ".webp", ".exe", ".dll", ".pyd", ".whl", ".zip", ".ico", ".woff2", ".ttf")):
                continue
            for kind in secret_hits(rel, z.read(info), seeds):
                problems.append(f"{rel}: {kind}")
        hashes = {}

        def h(rel: str) -> str:
            if rel not in hashes:
                hashes[rel] = hashlib.sha256(z.read(files[rel])).hexdigest()
            return hashes[rel]
        desktop = "DESKTOP" in path.name.upper()
        manifests = ("MANIFEST_SHA256.txt", "MANIFEST_DESKTOP_SHA256.txt")
        for mname in manifests:
            if mname not in files:
                # 1.46: a package without its manifest passed as OK; the installers and the launcher refuse to start without
                # MANIFEST_SHA256.txt, and without MANIFEST_DESKTOP_SHA256.txt nothing checked the files of the Windows app package
                if mname == "MANIFEST_SHA256.txt" or desktop:
                    problems.append(f"brak {mname}")
                continue
            try:
                text = z.read(files[mname]).decode("utf-8-sig")
            except UnicodeDecodeError:
                problems.append(f"{mname}: nieczytelne kodowanie (nie UTF-8)")
                continue
            bad_lines: list[int] = []
            m = _manifest(text, bad_lines)
            if not m:
                problems.append(f"{mname}: pusty lub nieczytelny")
            elif bad_lines:
                problems.append(f"{mname}: nieczytelny wiersz {', '.join(map(str, bad_lines[:5]))}")
            for rel, d in m.items():
                if rel not in files:
                    problems.append(f"{mname}: brak pliku {rel}")
                elif h(rel) != d:
                    problems.append(f"{mname}: inna suma {rel}")
            if mname == "MANIFEST_DESKTOP_SHA256.txt":
                unlisted = [r for r in files if r not in m and r != mname]
                if unlisted:
                    problems.append(f"{mname}: pliki spoza manifestu {unlisted[:5]}")
            elif not desktop:                  # 1.46: folder package = program files + MANIFEST_SHA256.txt listing every one of them
                unlisted = [r for r in files if r not in m and r not in manifests]
                if unlisted:
                    problems.append(f"{mname}: pliki spoza manifestu {unlisted[:5]}")
        missing = sorted(n for n in installer_required(lambda r: z.read(files[r]), files) - set(manifests) if n not in files)
        if missing:
            problems.append(f"brak plików wymaganych przez instalatory / launcher: {missing[:8]}")
        if "KLIENT" in path.name.upper():
            problems += client_problems(lambda r: z.read(files[r]), list(files))
        removed = [r for r in files if r.startswith(("license_server/", "backend/masterquo/license/")) or r == "edition.json"]
        if removed:
            problems.append(f"elementy usuniętego systemu licencji w paczce: {removed[:5]}")


def main(argv: list[str]) -> int:
    if argv == ["--all"]:
        sys.path.insert(0, str(ROOT / "tools"))
        import build_release
        tag = build_release.VERSION.replace(".", "_")
        paths = sorted((ROOT / "release").glob(f"*_{tag}*.zip"))
    else:
        paths = [Path(a) for a in argv]
    if not paths:
        print("brak archiwów do sprawdzenia")
        return 2
    bad = 0
    for p in paths:
        probs = check_zip(p)
        print(f"{'OK  ' if not probs else 'FAIL'} {p.name}" + ("" if not probs else f": {probs[:12]}"))
        bad += bool(probs)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
