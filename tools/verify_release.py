"""Verifies release archives before they are handed out (1.29, §5 of the update package).

  python tools/verify_release.py release/PepeMarketWizard_DESKTOP_1_30_0.zip [more.zip ...]
  python tools/verify_release.py --all          every ZIP of the current VERSION in release/

Per archive:
  * every entry name is a safe relative path under one top folder (no absolute path, drive letter, backslash, '..' - ZIP-slip),
    no duplicates, no symlink entries;
  * the <zip>.sha256 next to the archive matches;
  * MANIFEST_SHA256.txt / MANIFEST_DESKTOP_SHA256.txt inside: every listed file exists in the archive with that SHA-256 (and, for the
    desktop manifest, every file of the archive is listed);
  * no forbidden files (data/, databases, .env, keys, leftovers of the removed 1.27-1.29 license system) and no private key /
    API key / token assignment in text entries; no license server or license module (removed in 1.30).
Exit code 0 only when every archive passes. Nothing is extracted to disk.
"""
from __future__ import annotations

import hashlib
import re
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_NAMES = {"licenses.db", "license_owner.json", "signing_key.pem", ".env", "license_owner_key.dpapi", "license_owner_key.local.json",
                   "secrets.json", "secrets.dpapi", "masterquo.sqlite", "config.json"}
FORBIDDEN_SUFFIX = (".sqlite", ".sqlite3", ".db", ".pem", ".key", ".log", ".pyc")
FORBIDDEN_PARTS = {".git", ".venv", "node_modules", "__pycache__"}
ALLOWED_DUMMIES = {b"sk-ant-api03-SECRETVALUE-1234567890"}
SECRETS = [
    (re.compile(rb"-----BEGIN (?:ENCRYPTED |RSA |EC |OPENSSH )?PRIVATE KEY-----"), "PRIVATE_KEY"),
    (re.compile(rb"sk-ant-[A-Za-z0-9_\-]{20,}"), "ANTHROPIC_KEY"),
    (re.compile(rb"^(ANTHROPIC_API_KEY|TELEGRAM_BOT_TOKEN|PMW_ADMIN_PASSWORD_HASH|PMW_SIGNING_KEY)=\S+", re.M), "SECRET_ASSIGNMENT"),
]


def safe_name(n: str, top: str) -> str | None:
    if not n or "\\" in n or "\0" in n or n.startswith("/") or re.match(r"^[A-Za-z]:", n):
        return "niebezpieczna ścieżka"
    p = PurePosixPath(n)
    if ".." in p.parts:
        return "ścieżka z '..'"
    if top and not n.startswith(top):
        return f"poza folderem {top}"
    return None


def _manifest(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        d, sep, f = line.partition("  ")
        if sep and re.fullmatch(r"[0-9a-f]{64}", d):
            out[f] = d
    return out


def check_zip(path: Path, top: str | None = None) -> list[str]:
    path = Path(path)
    problems: list[str] = []
    if not path.exists():
        return [f"brak pliku {path}"]
    side = path.with_name(path.name + ".sha256")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if not side.exists():
        problems.append("brak pliku .sha256")
    elif side.read_text(encoding="utf-8").split()[0] != digest:
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
            parts = PurePosixPath(rel).parts
            name = parts[-1]
            runtime = rel.startswith("runtime/python/")          # bundled CPython: stdlib secrets.py, pip's public CA bundle (cacert.pem)
            secret_store = name.startswith("secrets.") and name.endswith((".json", ".dpapi"))   # the app's own secret store (data/secrets.*)
            suffix_bad = name.endswith(FORBIDDEN_SUFFIX) and not (runtime and name.endswith((".pem", ".pyc")))
            if FORBIDDEN_PARTS & set(parts) - ({"__pycache__"} if runtime else set()) or rel.startswith("data/") or name in FORBIDDEN_NAMES \
                    or suffix_bad or secret_store:
                problems.append(f"{rel}: plik zabroniony w paczce")
        for rel, info in files.items():
            if info.file_size > 20_000_000 or rel.endswith((".png", ".jpg", ".gif", ".webp", ".exe", ".dll", ".pyd", ".whl", ".zip", ".ico", ".woff2", ".ttf")):
                continue
            b = z.read(info)
            if b"\0" in b[:4096]:
                continue
            for rx, kind in SECRETS:
                if any(m.group(0) not in ALLOWED_DUMMIES for m in rx.finditer(b)):
                    problems.append(f"{rel}: {kind}")
        hashes = {}

        def h(rel: str) -> str:
            if rel not in hashes:
                hashes[rel] = hashlib.sha256(z.read(files[rel])).hexdigest()
            return hashes[rel]
        for mname in ("MANIFEST_SHA256.txt", "MANIFEST_DESKTOP_SHA256.txt"):
            if mname not in files:
                continue
            m = _manifest(z.read(files[mname]).decode("utf-8"))
            if not m:
                problems.append(f"{mname}: pusty lub nieczytelny")
            for rel, d in m.items():
                if rel not in files:
                    problems.append(f"{mname}: brak pliku {rel}")
                elif h(rel) != d:
                    problems.append(f"{mname}: inna suma {rel}")
            if mname == "MANIFEST_DESKTOP_SHA256.txt":
                unlisted = [r for r in files if r not in m and r != mname]
                if unlisted:
                    problems.append(f"{mname}: pliki spoza manifestu {unlisted[:5]}")
        removed = [r for r in files if r.startswith(("license_server/", "backend/masterquo/license/")) or r == "edition.json"]
        if removed:
            problems.append(f"elementy usuniętego systemu licencji w paczce: {removed[:5]}")
    return problems


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
