"""Klucz licencji PMW1 – offline, podpis Ed25519 (PyNaCl / libsodium). 1.43.0.

Format:  "PMW1-" + base64url_bez_paddingu( payload + podpis )
  payload = JSON UTF-8, kolejność pól stała, bez spacji:
            {"v":1,"u":"<użytkownik>","hw":"<HWID>"|null,"iat":<unix s>,"exp":<unix s>|null}
  podpis  = Ed25519( b"PMW1|" + payload ), 64 bajty na końcu blobu (prefiks domeny: podpis licencji nie przyda się do niczego innego).
Odczyt sprawdza zapis kanoniczny base64url (każda zmiana znaku zmienia bajty – inaczej zmiana ostatniego znaku mogłaby nie zmieniać
danych), potem podpis kluczem publicznym właściciela, potem pola. Weryfikacja potrzebuje wyłącznie klucza publicznego (32 bajty).
"""
from __future__ import annotations

import base64
import binascii
import json
import time

from .hwid import HWID_RE

PREFIX = "PMW1-"
VERSION = 1
SIG_LEN = 64
DOMAIN = b"PMW1|"
MAX_USER = 80


class LicenseFormatError(ValueError):
    pass


def _nacl():
    try:
        import nacl.exceptions
        import nacl.signing
        return nacl.signing, nacl.exceptions
    except ImportError as exc:                                     # pragma: no cover - zależność z requirements-win.txt
        raise RuntimeError("brak biblioteki PyNaCl (Ed25519) – zaktualizuj aplikację albo uruchom 01_INSTALUJ.bat") from exc


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def b64u_dec(s: str) -> bytes:
    if not s or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for c in s):
        raise LicenseFormatError("niedozwolone znaki (dozwolone: A–Z, a–z, 0–9, - i _)")
    try:
        raw = base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
    except (binascii.Error, ValueError) as exc:
        raise LicenseFormatError("uszkodzony zapis base64url") from exc
    if b64u(raw) != s:
        raise LicenseFormatError("niekanoniczny zapis base64url (klucz zmieniony)")
    return raw


def encode_payload(user: str, hwid: str | None, iat: int, exp: int | None) -> bytes:
    return json.dumps({"v": VERSION, "u": user, "hw": hwid, "iat": int(iat), "exp": None if exp is None else int(exp)},
                      separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sign_license(signing_key, user: str, hwid: str | None, iat: int, exp: int | None) -> str:
    """signing_key: nacl.signing.SigningKey właściciela."""
    payload = encode_payload(user, hwid, iat, exp)
    sig = signing_key.sign(DOMAIN + payload).signature
    return PREFIX + b64u(payload + sig)


def _check_payload(p) -> list[str]:
    errs = []
    if not isinstance(p, dict):
        return ["dane nie są obiektem JSON"]
    if p.get("v") != VERSION:
        errs.append(f"nieznana wersja licencji: {p.get('v')!r}")
    u = p.get("u")
    if not isinstance(u, str) or not u.strip() or len(u) > MAX_USER:
        errs.append("brak / błędny identyfikator użytkownika")
    hw = p.get("hw")
    if hw is not None and not (isinstance(hw, str) and HWID_RE.match(hw)):
        errs.append("błędny format HWID w licencji")
    iat, exp = p.get("iat"), p.get("exp")
    if not isinstance(iat, int) or isinstance(iat, bool):
        errs.append("brak / błędna data wydania")
    if exp is not None and (not isinstance(exp, int) or isinstance(exp, bool) or (isinstance(iat, int) and exp <= iat)):
        errs.append("błędna data wygaśnięcia")
    return errs


def read_license(key: str, public_key: bytes | None, *, now: float | None = None, hwid: str | None = None) -> dict:
    """Pełny odczyt klucza: dane, poprawność podpisu, wygaśnięcie, zgodność HWID (gdy podany).
    `valid` = format + podpis + pola + nie wygasł + (HWID zgodny, gdy licencja jest przypisana, a hwid podany)."""
    now = time.time() if now is None else now
    out: dict = {"format_ok": False, "signature_ok": False, "payload": None, "user": None, "hwid": None, "iat": None, "exp": None,
                 "perpetual": None, "expired": None, "hwid_match": None, "valid": False, "errors": []}
    k = "".join(str(key or "").split())                           # spacje / nowe linie z kopiowania
    if not k.startswith(PREFIX):
        out["errors"].append(f"klucz musi zaczynać się od „{PREFIX}”")
        return out
    try:
        blob = b64u_dec(k[len(PREFIX):])
    except LicenseFormatError as exc:
        out["errors"].append(str(exc))
        return out
    if len(blob) <= SIG_LEN + 2:
        out["errors"].append("klucz za krótki")
        return out
    payload, sig = blob[:-SIG_LEN], blob[-SIG_LEN:]
    try:
        p = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        p = None
    if p is None:
        out["errors"].append("nie da się odczytać danych licencji (uszkodzony klucz)")
    else:
        out["payload"] = p
        if isinstance(p, dict):
            out.update(user=p.get("u"), hwid=p.get("hw"), iat=p.get("iat"), exp=p.get("exp"))
        errs = _check_payload(p)
        out["errors"] += errs
        out["format_ok"] = not errs
    if public_key is None:
        out["errors"].append("brak klucza publicznego – nie można sprawdzić podpisu")
    else:
        signing, exceptions = _nacl()
        try:
            signing.VerifyKey(bytes(public_key)).verify(DOMAIN + payload, sig)
            out["signature_ok"] = True
        except (exceptions.BadSignatureError, ValueError, TypeError):
            out["errors"].append("PODPIS NIEPRAWIDŁOWY – klucz zmieniony albo wydany innym kluczem prywatnym")
    if out["format_ok"]:
        out["perpetual"] = out["exp"] is None
        out["expired"] = out["exp"] is not None and out["exp"] <= now
        if out["expired"]:
            out["errors"].append("licencja wygasła")
        if hwid is not None and out["hwid"] is not None:
            out["hwid_match"] = out["hwid"] == hwid
            if not out["hwid_match"]:
                out["errors"].append("licencja przypisana do innego komputera (HWID)")
    out["valid"] = bool(out["format_ok"] and out["signature_ok"] and not out["expired"] and out["hwid_match"] is not False)
    return out
