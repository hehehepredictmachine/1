"""Klucz licencji PMW1 – offline, podpis Ed25519 (PyNaCl / libsodium). 1.43.0; 1.44.0: tylko ODCZYT i WERYFIKACJA (wspólne dla wersji
właściciela i klienta). Wydawanie kluczy jest wyłącznie w wersji właściciela (licensing/signing.py – poza paczką klienta).

Format:  "PMW1-" + base64url_bez_paddingu( payload + podpis )
  payload = JSON UTF-8: {"v":1,"u":"<użytkownik>","hw":"<HWID>"|null,"iat":<unix s>,"exp":<unix s>|null}
  podpis  = Ed25519( b"PMW1|" + payload ), 64 bajty na końcu blobu (prefiks domeny).
Weryfikacja potrzebuje wyłącznie klucza publicznego (32 bajty).
"""
from __future__ import annotations

import base64
import binascii
import json
import time
from datetime import datetime

from .hwid import HWID_RE

PREFIX = "PMW1-"
VERSION = 1
SIG_LEN = 64
DOMAIN = b"PMW1|"
MAX_USER = 80
_B64U = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")


class LicenseFormatError(ValueError):
    pass


def _verifier():
    try:
        from nacl.exceptions import BadSignatureError
        from nacl.signing import VerifyKey
        return VerifyKey, BadSignatureError
    except ImportError as exc:                                     # pragma: no cover - zależność z requirements-win.txt
        raise RuntimeError("brak biblioteki PyNaCl (Ed25519) – zaktualizuj aplikację albo uruchom 01_INSTALUJ.bat") from exc


def crypto_available() -> str | None:
    """None gdy PyNaCl działa, inaczej opis problemu."""
    try:
        _verifier()
        return None
    except RuntimeError as exc:
        return str(exc)


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def b64u_dec(s: str) -> bytes:
    if not s or any(c not in _B64U for c in s):
        raise LicenseFormatError("niedozwolone znaki (dozwolone: A–Z, a–z, 0–9, - i _)")
    try:
        raw = base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
    except (binascii.Error, ValueError) as exc:
        raise LicenseFormatError("uszkodzony zapis base64url") from exc
    if b64u(raw) != s:
        raise LicenseFormatError("niekanoniczny zapis base64url (klucz zmieniony)")
    return raw


def clean_key(key: str | None) -> str:
    return "".join(str(key or "").split())                         # spacje / nowe linie z kopiowania


def _signature_ok(public_key: bytes, payload: bytes, sig: bytes) -> bool:
    VerifyKey, BadSignatureError = _verifier()
    try:
        VerifyKey(bytes(public_key)).verify(DOMAIN + payload, sig)
        return True
    except (BadSignatureError, ValueError, TypeError):
        return False


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


def fmt_date(ts: int | float | None) -> str:
    """Data dla komunikatów (czas lokalny komputera): 31.03.2027 23:59."""
    return "" if ts is None else datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M")


# ------------------------------------------------------------------------------------------------ weryfikacja (klient)
MESSAGES = {
    "FORMAT": "Nieprawidłowy klucz licencyjny – zły format. Skopiuj cały klucz zaczynający się od „PMW1-”.",
    "SIGNATURE": "Nieprawidłowy klucz licencyjny – podpis się nie zgadza (klucz zmieniony albo nie pochodzi od wydawcy).",
    "VERSION": "Nieprawidłowy klucz licencyjny – nieobsługiwana wersja licencji (zaktualizuj aplikację).",
    "EXPIRED": "Licencja wygasła {date}. Poproś wydawcę o nowy klucz.",
    "HWID": "Klucz jest przypisany do innego komputera. Wyślij wydawcy HWID tego komputera, aby otrzymać właściwy klucz.",
}


def check_license(key: str | None, public_key: bytes, *, now: float | None = None, hwid: str | None = None) -> dict:
    """Weryfikacja klucza w stałej kolejności: prefiks -> base64url -> podpis kluczem publicznym -> v == 1 -> exp (jeśli nie null) ->
    hw (jeśli nie null, musi być równy `hwid` tego komputera). Zwraca {"ok", "code", "message", "payload"}; code: OK / FORMAT / SIGNATURE /
    VERSION / EXPIRED / HWID. Dane (payload) tylko po poprawnym podpisie."""
    now = time.time() if now is None else now
    out = {"ok": False, "code": "FORMAT", "message": MESSAGES["FORMAT"], "payload": None}
    k = clean_key(key)
    if not k.startswith(PREFIX):                                                  # 1. prefiks
        return out
    try:
        blob = b64u_dec(k[len(PREFIX):])                                          # 2. base64url
    except LicenseFormatError:
        return out
    if len(blob) <= SIG_LEN + 2:
        return out
    payload, sig = blob[:-SIG_LEN], blob[-SIG_LEN:]
    if not _signature_ok(public_key, payload, sig):                               # 3. podpis
        out.update(code="SIGNATURE", message=MESSAGES["SIGNATURE"])
        return out
    try:
        p = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        p = None
    if not isinstance(p, dict) or p.get("v") != VERSION:                          # 4. v == 1
        out.update(code="VERSION", message=MESSAGES["VERSION"])
        return out
    if _check_payload(p):
        return out
    out["payload"] = p
    exp = p.get("exp")
    if exp is not None and exp <= now:                                            # 5. exp
        out.update(code="EXPIRED", message=MESSAGES["EXPIRED"].format(date=fmt_date(exp)))
        return out
    hw = p.get("hw")
    if hw is not None and hw != hwid:                                             # 6. hw
        out.update(code="HWID", message=MESSAGES["HWID"])
        return out
    out.update(ok=True, code="OK", message="Licencja aktywna.")
    return out


# ------------------------------------------------------------------------------------------------ pełny odczyt (narzędzie „Sprawdź klucz”)
def read_license(key: str, public_key: bytes | None, *, now: float | None = None, hwid: str | None = None) -> dict:
    """Pełny odczyt klucza do podglądu: dane (także przy złym podpisie – oznaczone), poprawność podpisu, wygaśnięcie, zgodność HWID.
    `valid` = format + podpis + pola + nie wygasł + (HWID zgodny, gdy licencja jest przypisana, a hwid podany)."""
    now = time.time() if now is None else now
    out: dict = {"format_ok": False, "signature_ok": False, "payload": None, "user": None, "hwid": None, "iat": None, "exp": None,
                 "perpetual": None, "expired": None, "hwid_match": None, "valid": False, "errors": []}
    k = clean_key(key)
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
    elif _signature_ok(public_key, payload, sig):
        out["signature_ok"] = True
    else:
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
