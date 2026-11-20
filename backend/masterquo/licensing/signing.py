"""WYDAWANIE kluczy licencji PMW1 – TYLKO wersja właściciela (1.44.0). Plik NIE wchodzi do paczki klienta
(tools/build_release.py: OWNER_ONLY; tools/verify_release.py odrzuca paczkę klienta, w której jest).
Format klucza i weryfikacja: license_key.py (wspólne)."""
from __future__ import annotations

import json

from .license_key import DOMAIN, PREFIX, VERSION, b64u


def nacl_signing():
    try:
        import nacl.signing
        return nacl.signing
    except ImportError as exc:                                     # pragma: no cover - zależność z requirements-win.txt
        raise RuntimeError("brak biblioteki PyNaCl (Ed25519) – zaktualizuj aplikację albo uruchom 01_INSTALUJ.bat") from exc


def encode_payload(user: str, hwid: str | None, iat: int, exp: int | None) -> bytes:
    return json.dumps({"v": VERSION, "u": user, "hw": hwid, "iat": int(iat), "exp": None if exp is None else int(exp)},
                      separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sign_license(signing_key, user: str, hwid: str | None, iat: int, exp: int | None) -> str:
    """signing_key: nacl.signing.SigningKey właściciela."""
    payload = encode_payload(user, hwid, iat, exp)
    sig = signing_key.sign(DOMAIN + payload).signature
    return PREFIX + b64u(payload + sig)
