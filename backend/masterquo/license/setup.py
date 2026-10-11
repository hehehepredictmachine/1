"""Terminal setup of the license SERVER address and its PUBLIC key (once per computer).

Runs automatically at masterquo_start when the configuration is missing (interactive terminal only), or on demand:
`python -m masterquo license-setup` / 09_KONFIGURACJA_LICENCJI.bat. The public key is downloaded from the server and
pinned only after the user confirms its fingerprint (the "klucz podpisu" shown in the administrator panel), or pasted
directly. Nothing secret is stored: no license key, no token.
"""
from __future__ import annotations

import hashlib
import json
import ssl
import sys
import urllib.request

from .client import LicenseError, check_url, load_public_key

DEFAULT_URL = "http://127.0.0.1:8790"


def fingerprint(pem: str) -> str:
    return hashlib.sha256(pem.encode()).hexdigest()[:16]          # same as the server's kid (security.kid_of)


def _pem_from_line(line: str) -> str | None:
    body = "".join(line.replace("-----BEGIN PUBLIC KEY-----", "").replace("-----END PUBLIC KEY-----", "").split())
    if not body.startswith("MCowBQYDK2Vw"):                           # Ed25519 SubjectPublicKeyInfo prefix
        return None
    pem = f"-----BEGIN PUBLIC KEY-----\n{body}\n-----END PUBLIC KEY-----\n"
    try:
        load_public_key(pem)
    except LicenseError:
        return None
    return pem


def fetch_key(url: str, timeout: float = 10.0) -> str:
    ctx = ssl.create_default_context() if url.startswith("https://") else None
    with urllib.request.urlopen(url + "/api/v1/keys", timeout=timeout, context=ctx) as r:
        keys = json.loads(r.read().decode()).get("keys") or []
    if not keys:
        raise LicenseError("NOT_CONFIGURED", "serwer nie zwrócił klucza")
    return keys[0]["pem"]


def run(cfg_store, stdin=None, stdout=None) -> bool:
    stdin = stdin or sys.stdin
    out = stdout or sys.stdout

    def ask(q: str) -> str:
        out.write(q)
        out.flush()
        return (stdin.readline() or "").strip()
    out.write("\n========== MasterQUO - konfiguracja serwera licencji (jednorazowo) ==========\n"
              "Podaj adres serwera licencji od administratora. Dla serwera na tym komputerze nacisnij Enter.\n")
    url = ask(f"Adres serwera [{DEFAULT_URL}]: ") or DEFAULT_URL
    try:
        url = check_url(url)
    except LicenseError as e:
        out.write(f"[BLAD] {e.message}\n")
        return False
    try:
        pem = fetch_key(url)
    except Exception as e:  # noqa: BLE001
        out.write(f"[BLAD] Nie mozna polaczyc sie z {url} ({type(e).__name__}). Czy serwer licencji jest uruchomiony?\n")
        return False
    fp = fingerprint(pem)
    out.write(f"\nSerwer podal klucz podpisu o odcisku: {fp}\n"
              "Porownaj go z panelem administratora (Podsumowanie -> 'klucz podpisu').\n")
    ans = ask("Wpisz T jesli sie zgadza (albo wklej klucz publiczny MCowBQ... od administratora): ")
    if ans.upper() in ("T", "TAK", "Y", "YES") or ans == fp:
        chosen = pem
    elif _pem_from_line(ans):
        chosen = _pem_from_line(ans)
        if fingerprint(chosen) != fp:
            out.write("[BLAD] Wklejony klucz NIE zgadza sie z kluczem serwera - konfiguracja nie zostala zapisana.\n")
            return False
    else:
        out.write("Nie potwierdzono klucza - konfiguracja nie zostala zapisana.\n")
        return False
    cfg_store.set_license_server(url, chosen)
    out.write(f"[OK] Zapisano: {url} (klucz {fp}). Zmiana pozniej: 09_KONFIGURACJA_LICENCJI.bat\n")
    return True
