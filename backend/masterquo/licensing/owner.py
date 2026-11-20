"""Generator licencji właściciela (1.43.0) – para kluczy Ed25519, wydawanie kluczy PMW1, historia, sprawdzanie.

Folder właściciela (POZA folderem programu i repozytorium; nigdy w paczce):
  Windows: %APPDATA%\\PepeMarketWizard\\owner        inne: $XDG_CONFIG_HOME|~/.config/PepeMarketWizard/owner
  (PMW_OWNER_DIR nadpisuje – testy)
    private.key    klucz prywatny (ziarno Ed25519, 32 bajty hex) + klucz publiczny – zapis atomowy, na POSIX chmod 600
    licenses.db    historia wydanych licencji (SQLite)
Klucz prywatny nie jest wkompilowany w kod ani wysyłany nigdzie poza jawny eksport kopii zapasowej (POST, CSRF, tylko 127.0.0.1).
Bez logowania i haseł – to narzędzie właściciela na jego komputerze.
"""
from __future__ import annotations

import os
import re
import sqlite3
import sys
import threading
import time
from datetime import date, datetime, timezone
from pathlib import Path

from . import license_key as LK
from .hwid import HWID_FORMAT_PL, get_hwid, hwid_sources, normalize_hwid

KEY_HEADER = "PMW-OWNER-ED25519-PRIVATE-KEY v1"
PRESET_DAYS = (7, 30, 90, 365)


class LicenseInputError(ValueError):
    """Błąd danych od użytkownika – `field` wskazuje pole formularza."""

    def __init__(self, field: str, message: str):
        super().__init__(f"{field}: {message}")
        self.field, self.message = field, message


def owner_dir() -> Path:
    if os.environ.get("PMW_OWNER_DIR"):
        return Path(os.environ["PMW_OWNER_DIR"])
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "PepeMarketWizard" / "owner"
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "PepeMarketWizard" / "owner"


def _signing():
    return LK._nacl()[0]


def _key_text(seed: bytes, pub: bytes, created: str) -> str:
    return f"{KEY_HEADER}\nseed: {seed.hex()}\npublic: {pub.hex()}\ncreated: {created}\n"


def parse_key_file(text: str) -> tuple[bytes, bytes]:
    """Kopia zapasowa (format PMW) albo samo ziarno 64 hex (lub 128 hex: ziarno + publiczny, jak w libsodium) -> (ziarno, publiczny).
    Klucz publiczny zapisany w pliku musi zgadzać się z wyliczonym z ziarna (wykrywa uszkodzony / sklejony plik)."""
    t = (text or "").strip()
    if not t:
        raise LicenseInputError("key_file", "plik jest pusty")
    seed_hex = pub_hex = None
    if t.startswith(KEY_HEADER):
        for line in t.splitlines()[1:]:
            k, _, v = line.partition(":")
            if k.strip() == "seed":
                seed_hex = v.strip()
            elif k.strip() == "public":
                pub_hex = v.strip()
    else:
        compact = re.sub(r"\s+", "", t)
        if re.fullmatch(r"[0-9a-fA-F]{64}", compact):
            seed_hex = compact
        elif re.fullmatch(r"[0-9a-fA-F]{128}", compact):
            seed_hex, pub_hex = compact[:64], compact[64:]
    if not seed_hex or not re.fullmatch(r"[0-9a-fA-F]{64}", seed_hex):
        raise LicenseInputError("key_file", "to nie jest klucz prywatny PepeMarketWizard (brak ziarna Ed25519)")
    seed = bytes.fromhex(seed_hex)
    pub = bytes(_signing().SigningKey(seed).verify_key)
    if pub_hex is not None and (not re.fullmatch(r"[0-9a-fA-F]{64}", pub_hex) or bytes.fromhex(pub_hex) != pub):
        raise LicenseInputError("key_file", "plik uszkodzony – klucz publiczny nie pasuje do prywatnego")
    return seed, pub


def _write_private(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="ascii", newline="\n") as f:
        f.write(text)
    os.replace(tmp, p)
    if os.name != "nt":
        os.chmod(p, 0o600)


def _iso(ts: float | None) -> str | None:
    return None if ts is None else datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class OwnerLicenses:
    def __init__(self, base: Path | None = None, clock=time.time):
        self.base = Path(base) if base else owner_dir()
        self.clock = clock
        self._lock = threading.RLock()

    # ------------------------------------------------------------------------------------------------ pliki
    @property
    def key_path(self) -> Path:
        return self.base / "private.key"

    @property
    def db_path(self) -> Path:
        return self.base / "licenses.db"

    def _db(self) -> sqlite3.Connection:
        self.base.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(self.db_path, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("CREATE TABLE IF NOT EXISTS licenses (id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT NOT NULL, hwid TEXT, "
                  "iat INTEGER NOT NULL, exp INTEGER, note TEXT NOT NULL DEFAULT '', license_key TEXT NOT NULL UNIQUE, "
                  "public_key TEXT NOT NULL, created_at INTEGER NOT NULL)")
        return c

    def _load(self) -> tuple[bytes, bytes] | None:
        try:
            text = self.key_path.read_text(encoding="ascii")
        except FileNotFoundError:
            return None
        except (OSError, UnicodeDecodeError) as exc:
            raise LicenseInputError("keys", f"nie można odczytać klucza prywatnego ({self.key_path}): {exc}") from exc
        return parse_key_file(text)

    def _signer(self):
        k = self._load()
        if k is None:
            raise LicenseInputError("keys", "brak pary kluczy – najpierw kliknij „Utwórz parę kluczy”")
        return _signing().SigningKey(k[0]), k[1]

    # ------------------------------------------------------------------------------------------------ klucze
    def state(self) -> dict:
        nacl_ok, nacl_err = True, None
        try:
            LK._nacl()
        except RuntimeError as exc:
            nacl_ok, nacl_err = False, str(exc)
        pub = created = None
        err = None
        if nacl_ok:
            try:
                k = self._load()
                pub = k[1].hex() if k else None
                if k:
                    for line in self.key_path.read_text(encoding="ascii").splitlines():
                        if line.startswith("created:"):
                            created = line.split(":", 1)[1].strip()
            except LicenseInputError as exc:
                err = exc.message
        return {"schema": "PMW-LICGEN-1", "crypto_ok": nacl_ok, "crypto_error": nacl_err, "has_key": pub is not None,
                "public_key": pub, "key_created": created, "key_error": err, "owner_dir": str(self.base),
                "key_path": str(self.key_path), "preset_days": list(PRESET_DAYS), "hwid_format": HWID_FORMAT_PL}

    def create_keypair(self) -> dict:
        with self._lock:
            if self.key_path.exists():
                raise LicenseInputError("keys", "para kluczy już istnieje – nowa unieważniłaby wszystkie wydane licencje")
            sk = _signing().SigningKey.generate()
            _write_private(self.key_path, _key_text(bytes(sk), bytes(sk.verify_key), _iso(self.clock())))
            return self.state()

    def export_key(self) -> dict:
        k = self._load()
        if k is None:
            raise LicenseInputError("keys", "brak klucza do eksportu")
        stamp = datetime.fromtimestamp(self.clock()).strftime("%Y%m%d")
        return {"filename": f"PepeMarketWizard_klucz_prywatny_{stamp}.key", "content": self.key_path.read_text(encoding="ascii"),
                "public_key": k[1].hex()}

    def import_key(self, content: str, replace: bool = False) -> dict:
        seed, pub = parse_key_file(content)
        with self._lock:
            cur = self._load() if self.key_path.exists() else None
            if cur is not None and cur[1] == pub:
                return {**self.state(), "imported": False, "same_key": True}
            if cur is not None and not replace:
                raise LicenseInputError("key_file", "na tym komputerze jest INNY klucz prywatny – zastąpienie unieważni licencje wydane "
                                                    "obecnym kluczem. Potwierdź zastąpienie (stary klucz zostanie zachowany jako kopia).")
            backup = None
            if cur is not None:
                backup = self.key_path.with_name(f"private.key.bak-{datetime.fromtimestamp(self.clock()).strftime('%Y%m%d-%H%M%S')}")
                _write_private(backup, self.key_path.read_text(encoding="ascii"))
            _write_private(self.key_path, _key_text(seed, pub, _iso(self.clock())))
            return {**self.state(), "imported": True, "previous_key_backup": str(backup) if backup else None}

    # ------------------------------------------------------------------------------------------------ licencje
    def _expiry(self, validity: dict | None, iat: int) -> int | None:
        v = validity or {}
        kind = v.get("kind")
        if kind == "perpetual":
            return None
        if kind == "days":
            try:
                d = int(v.get("days"))
            except (TypeError, ValueError):
                d = 0
            if d not in PRESET_DAYS:
                raise LicenseInputError("validity", f"ważność: {', '.join(map(str, PRESET_DAYS))} dni, własna data albo bezterminowa")
            return iat + d * 86400
        if kind == "date":
            try:
                day = date.fromisoformat(str(v.get("date") or ""))
            except ValueError:
                raise LicenseInputError("validity", "wybierz datę wygaśnięcia w kalendarzu") from None
            end = int(datetime(day.year, day.month, day.day, 23, 59, 59).astimezone().timestamp())   # koniec dnia, czas tego komputera
            if end <= iat:
                raise LicenseInputError("validity", "data wygaśnięcia jest z przeszłości")
            return end
        raise LicenseInputError("validity", "wybierz ważność licencji")

    def generate(self, user: str, hwid: str | None, no_hwid: bool, validity: dict | None, note: str = "") -> dict:
        u = (user or "").strip()
        if not u:
            raise LicenseInputError("user", "podaj nazwę / ID użytkownika")
        if len(u) > LK.MAX_USER or any(ord(c) < 32 for c in u):
            raise LicenseInputError("user", f"nazwa / ID: najwyżej {LK.MAX_USER} znaków, bez znaków sterujących")
        hw = None
        if not no_hwid:
            hw = normalize_hwid(hwid)
            if hw is None:
                raise LicenseInputError("hwid", ("podaj HWID albo zaznacz „bez przypisania HWID”" if not (hwid or "").strip()
                                                 else "błędny format HWID – wymagany " + HWID_FORMAT_PL))
        note = (note or "").strip()
        if len(note) > 500:
            raise LicenseInputError("note", "notatka: najwyżej 500 znaków")
        iat = int(self.clock())
        exp = self._expiry(validity, iat)
        with self._lock:
            sk, pub = self._signer()
            key = LK.sign_license(sk, u, hw, iat, exp)
            with self._db() as c:
                cur = c.execute("INSERT INTO licenses (user, hwid, iat, exp, note, license_key, public_key, created_at) VALUES (?,?,?,?,?,?,?,?)",
                                (u, hw, iat, exp, note, key, pub.hex(), iat))
                rid = cur.lastrowid
            c.close()
        return self._row_out({"id": rid, "user": u, "hwid": hw, "iat": iat, "exp": exp, "note": note, "license_key": key,
                              "public_key": pub.hex()}, pub.hex())

    def _row_out(self, r: dict, pub_now: str | None) -> dict:
        exp = r.get("exp")
        expired = exp is not None and exp <= self.clock()
        return {"id": r["id"], "user": r["user"], "hwid": r["hwid"], "iat": r["iat"], "exp": exp, "iat_iso": _iso(r["iat"]),
                "exp_iso": _iso(exp), "note": r.get("note") or "", "key": r["license_key"], "status": "WYGASLA" if expired else "AKTYWNA",
                "status_pl": "wygasła" if expired else "aktywna", "perpetual": exp is None,
                "signed_with_current_key": pub_now is not None and r.get("public_key") == pub_now}

    def list(self) -> list[dict]:
        try:
            k = self._load()
        except LicenseInputError:
            k = None
        pub = k[1].hex() if k else None
        if not self.db_path.exists():
            return []
        with self._db() as c:
            rows = [dict(r) for r in c.execute("SELECT * FROM licenses ORDER BY iat DESC, id DESC LIMIT 10000")]
        c.close()
        return [self._row_out(r, pub) for r in rows]

    def delete(self, rid: int) -> dict:
        if not self.db_path.exists():
            return {"deleted": 0}
        with self._db() as c:
            n = c.execute("DELETE FROM licenses WHERE id = ?", (int(rid),)).rowcount
        c.close()
        return {"deleted": n}

    def check(self, key: str) -> dict:
        try:
            k = self._load()
        except LicenseInputError:
            k = None
        try:
            here = get_hwid()
        except Exception:  # noqa: BLE001
            here = None
        r = LK.read_license(key, k[1] if k else None, now=self.clock())
        r["iat_iso"], r["exp_iso"] = _iso(r["iat"]) if isinstance(r["iat"], int) else None, _iso(r["exp"]) if isinstance(r["exp"], int) else None
        r["this_computer"] = (r["hwid"] == here) if (r["hwid"] and here) else None
        r["checked_with"] = k[1].hex() if k else None
        return r

    @staticmethod
    def this_hwid() -> dict:
        try:
            return {"hwid": get_hwid(), "sources": hwid_sources()}
        except Exception as exc:  # noqa: BLE001
            return {"hwid": None, "sources": hwid_sources(), "error": str(exc)[:200]}
