"""CLIENT EDITION build: turn an OWNER package (zip) or this OWNER installation folder into a CLIENT package for a customer.

  python tools/stamp_client_edition.py --license-url https://licencje.twoja-domena.pl [--public-key <base64>] [--source <zip|folder>]
                                       [--out <file.zip>] [--yes]

What changes (everything else - engine, strategies, models, panel, launchers - stays byte-identical):
  * edition.json -> {"edition": "CLIENT", "license_api": <url>, "public_key": <server PUBLIC key>, "kid": <key id>};
  * backend/masterquo/license/owner.py (License Manager client) and license_server/ are left out;
  * MANIFEST_SHA256.txt / MANIFEST_DESKTOP_SHA256.txt are recomputed for the changed / removed files.
Only files listed in the package manifest are copied (never data/, keys, logs, databases, .venv). The public key comes from
--public-key or from the server (GET /api/v1/public-key) - then compare the printed key id (kid) with the one printed by
`python -m pmw_license init-keys` on YOUR server before handing the package out (a fake server would show another kid).
The result is checked: no private key, no admin password hash, no license database, no owner module.
Standard library only (works with the Python of the Windows package).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from masterquo.license.url import valid_license_url
from masterquo.license import client as license_client
DROP = ("backend/masterquo/license/owner.py",)
DROP_PREFIX = ("license_server/",)
FORBIDDEN = [(re.compile(rb"-----BEGIN (?:ENCRYPTED |RSA |EC |OPENSSH )?PRIVATE KEY-----"), "PRIVATE_KEY"),
             (re.compile(rb"PMW_LIC_ADMIN_PASSWORD_HASH=scrypt\$"), "ADMIN_PASSWORD_HASH"),
             (re.compile(rb"PMW_LIC_KEY_PEPPER=[A-Za-z0-9_\-]{20,}"), "KEY_PEPPER")]
FORBIDDEN_NAMES = ("licenses.db", "license_owner.json", "signing_key.pem", ".env")


def kid_of(pub_raw: bytes) -> str:
    return hashlib.sha256(pub_raw).hexdigest()[:16]


def fetch_public_key(url: str) -> tuple[str, str]:
    d = license_client.request(url, "/api/v1/public-key", timeout=15)
    raw = base64.b64decode(d["public_key"], validate=True)
    if len(raw) != 32 or d.get("alg") != "Ed25519" or d.get("kid") != kid_of(raw):
        raise SystemExit("serwer zwrócił nieprawidłowy klucz publiczny")
    return d["public_key"], d["kid"]


def read_source(src: Path) -> tuple[str, dict[str, bytes]]:
    """(top folder, {relative path: bytes}) of an OWNER package zip or installation folder (files of its manifest only)."""
    files: dict[str, bytes] = {}
    if src.is_file():
        with zipfile.ZipFile(src) as z:
            names = [n for n in z.namelist() if not n.endswith("/")]
            top = names[0].split("/")[0] + "/"
            for n in names:
                if not n.startswith(top):
                    raise SystemExit(f"nieoczekiwana struktura paczki: {n}")
                files[n[len(top):]] = z.read(n)
        return top, files
    man = src / "MANIFEST_SHA256.txt"
    if not man.exists():
        raise SystemExit(f"brak {man} – wskaż folder programu OWNER albo jego paczkę zip")
    listed = [ln.split("  ", 1)[1] for ln in man.read_text(encoding="utf-8").splitlines() if ln and not ln.startswith("#") and "  " in ln]
    dman = src / "MANIFEST_DESKTOP_SHA256.txt"
    if dman.exists():
        listed += [ln.split("  ", 1)[1] for ln in dman.read_text(encoding="utf-8").splitlines() if ln and not ln.startswith("#") and "  " in ln]
    for rel in sorted(set(listed) | {"MANIFEST_SHA256.txt"} | ({"MANIFEST_DESKTOP_SHA256.txt"} if dman.exists() else set())):
        p = src / rel
        if p.is_file():
            files[rel] = p.read_bytes()
    return ("PepeMarketWizard_Desktop/" if dman.exists() else "PepeMarketWizard/"), files


def stamp(files: dict[str, bytes], url: str, pub_b64: str, kid: str) -> dict[str, bytes]:
    out = {k: v for k, v in files.items() if k not in DROP and not k.startswith(DROP_PREFIX)}
    ed = json.loads(out.get("edition.json", b"{}") or b"{}")
    if ed.get("edition") not in ("OWNER", "CLIENT"):
        raise SystemExit("źródło nie jest paczką PepeMarketWizard (brak edition.json)")
    out["edition.json"] = (json.dumps({"edition": "CLIENT", "license_api": url, "public_key": pub_b64, "kid": kid,
                                       "note": "CLIENT EDITION – przygotowana narzędziem stamp_client_edition.py"}, indent=1) + "\n").encode("utf-8")
    for mname in ("MANIFEST_SHA256.txt", "MANIFEST_DESKTOP_SHA256.txt"):
        if mname not in out:
            continue
        lines = []
        for ln in out[mname].decode("utf-8").splitlines():
            if not ln or ln.startswith("#") or "  " not in ln:
                lines.append(ln.replace("(klient)", "(CLIENT)").replace("(OWNER)", "(CLIENT)"))
                continue
            rel = ln.split("  ", 1)[1]
            if rel not in out:
                continue                                          # dropped file
            if rel != "MANIFEST_SHA256.txt":
                lines.append(f"{hashlib.sha256(out[rel]).hexdigest()}  {rel}")
            else:
                lines.append(ln)                                  # fixed below, after MANIFEST_SHA256.txt is final
        out[mname] = ("\n".join(lines) + "\n").encode("utf-8")
    if "MANIFEST_DESKTOP_SHA256.txt" in out:
        h = hashlib.sha256(out["MANIFEST_SHA256.txt"]).hexdigest()
        out["MANIFEST_DESKTOP_SHA256.txt"] = re.sub(rb"^[0-9a-f]{64}  MANIFEST_SHA256\.txt$", f"{h}  MANIFEST_SHA256.txt".encode(),
                                                     out["MANIFEST_DESKTOP_SHA256.txt"], flags=re.M)
    return out


def check(files: dict[str, bytes]) -> list[str]:
    bad = [k for k in files if Path(k).name in FORBIDDEN_NAMES or k in DROP or k.startswith(DROP_PREFIX) or k.startswith("data/")]
    for k, v in files.items():
        if b"\0" in v[:4096]:
            continue
        bad += [f"{k}: {kind}" for rx, kind in FORBIDDEN if rx.search(v)]
    ed = json.loads(files["edition.json"])
    if ed.get("edition") != "CLIENT" or not ed.get("license_api") or not ed.get("public_key"):
        bad.append("edition.json: not a configured CLIENT edition")
    return bad


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="PepeMarketWizard: paczka CLIENT EDITION dla klienta")
    ap.add_argument("--license-url", required=True)
    ap.add_argument("--public-key", default=None, help="klucz publiczny serwera (base64); bez niego pobierany z serwera")
    ap.add_argument("--source", default=str(ROOT), help="paczka OWNER (.zip) albo folder programu OWNER (domyślnie ten folder)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--yes", action="store_true", help="bez pytania o potwierdzenie identyfikatora klucza")
    a = ap.parse_args(argv)
    url = a.license_url.strip().rstrip("/")
    if not valid_license_url(url):
        print("Adres serwera licencji musi zaczynać się od https://", file=sys.stderr)
        return 2
    if a.public_key:
        raw = base64.b64decode(a.public_key, validate=True)
        if len(raw) != 32:
            print("Nieprawidłowy klucz publiczny (oczekiwane 32 bajty Ed25519 w base64).", file=sys.stderr)
            return 2
        pub, kid = a.public_key.strip(), kid_of(raw)
    else:
        pub, kid = fetch_public_key(url)
    print(f"Serwer licencji: {url}\nKlucz publiczny: {pub}\nID klucza (kid): {kid}")
    if not a.yes:
        if input("Czy kid zgadza się z wypisanym przez 'python -m pmw_license init-keys' na Twoim serwerze? [t/N] ").strip().lower() not in ("t", "tak", "y", "yes"):
            print("Przerwano.")
            return 1
    top, files = read_source(Path(a.source))
    out_files = stamp(files, url, pub, kid)
    bad = check(out_files)
    if bad:
        print("Paczka CLIENT nie przeszła kontroli: " + "; ".join(bad), file=sys.stderr)
        return 3
    host = re.sub(r"[^A-Za-z0-9]+", "_", url.split("://", 1)[1]).strip("_")[:40]
    ver = (re.search(rb'APP_VERSION = "([^"]+)"', out_files.get("backend/masterquo/version.py", b"")) or [None, b"x"])[1].decode()
    kind = "DESKTOP_CLIENT" if top.startswith("PepeMarketWizard_Desktop") else "CLIENT"
    out = Path(a.out) if a.out else ROOT / "release" / f"PepeMarketWizard_{kind}_{ver.replace('.', '_')}_{host}.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel in sorted(out_files):
            z.writestr(top + rel, out_files[rel])
    out.write_bytes(buf.getvalue())
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    (out.parent / (out.name + ".sha256")).write_text(f"{digest}  {out.name}\n", encoding="utf-8", newline="\n")
    print(f"Gotowe: {out} ({len(out_files)} plików, sha256 {digest}) – bez modułu właściciela, kluczy prywatnych i danych.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
