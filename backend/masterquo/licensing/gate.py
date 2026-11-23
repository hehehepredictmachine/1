"""CENTRALNA kontrola licencji wersji klienta (1.44.0) – jedno miejsce, wywoływane przy starcie, przed uruchomieniem trybu (FOREX / CRYPTO /
OTC, tryb wykonania), w bramce wykonania (nowe wejścia), w Guard API i okresowo (co 10 min).

Kolejność sprawdzenia:
  1. edycja: wersja właściciela (OWNER) – licencja niepotrzebna;
  2. klucz publiczny wydawcy (client_config.PUBLIC_KEY_HEX) – pusty / zły = błąd konfiguracji;
  3. zapisany klucz (license.dat) – brak = ekran aktywacji;
  4. zegar: czas z internetu (nagłówek Date HTTPS, 3 s) – gdy dostępny, to on liczy wygaśnięcie, a różnica > 24 h względem zegara
     komputera = „błąd zegara systemowego”; bez internetu zegar komputera z ochroną: wcześniejszy od ostatnio zapisanego o > 24 h =
     „wykryto cofnięcie zegara systemowego”;
  5. klucz: prefiks → base64url → podpis → v == 1 → exp → hw == get_hwid() (license_key.check_license).
Plik: %APPDATA%\\PepeMarketWizard\\license.dat (JSON: klucz, data aktywacji, ostatni znany czas). Blokada obejmuje nowe wejścia i API
ekranów; otwarte pozycje dalej chroni SL/TP po stronie brokera, a zarządzanie pozycjami działa bez zmian.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import threading
import time
from pathlib import Path

from . import client_config
from .edition import dev_overrides, edition
from .hwid import get_hwid
from .license_key import check_license, crypto_available, fmt_date
from .nettime import NetClock

DAY = 86400
CLOCK_TOLERANCE_S = 24 * 3600
RECHECK_S = 600
WARN_DAYS = 3

MSG = {
    "NO_PUBLIC_KEY": "Błąd konfiguracji licencji: ta wersja nie ma klucza publicznego wydawcy (PUBLIC_KEY_HEX). Skontaktuj się z wydawcą "
                     "programu.",
    "NO_CRYPTO": "Brak biblioteki kryptograficznej (PyNaCl) – nie można sprawdzić licencji. Uruchom aplikację ponownie (doinstaluje ją) "
                 "albo skontaktuj się z wydawcą.",
    "NO_LICENSE": "Wklej klucz licencyjny, aby uruchomić Apollo23.",
    "CLOCK_ROLLBACK": "Wykryto cofnięcie zegara systemowego. Ustaw poprawną datę i godzinę w Windows (Ustawienia → Czas i język → Ustaw "
                      "czas automatycznie) i uruchom aplikację ponownie.",
    "CLOCK_ERROR": "Błąd zegara systemowego: czas komputera różni się od czasu z internetu o {hours} h. Ustaw poprawną datę i godzinę w "
                   "Windows (Ustawienia → Czas i język → Ustaw czas automatycznie).",
    "HWID_ERROR": "Nie udało się odczytać identyfikatora komputera (HWID) – licencja przypisana do komputera nie może być sprawdzona.",
}


class LicenseRequired(RuntimeError):
    def __init__(self, state: dict, action: str = ""):
        super().__init__(state.get("message") or "Brak ważnej licencji")
        self.state, self.action = state, action


def license_path() -> Path:
    if dev_overrides() and os.environ.get("PMW_LICENSE_FILE"):
        return Path(os.environ["PMW_LICENSE_FILE"])
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "PepeMarketWizard" / "license.dat"
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "PepeMarketWizard" / "license.dat"


def public_key() -> tuple[bytes | None, str | None]:
    """Klucz publiczny wydawcy z client_config.PUBLIC_KEY_HEX (w repozytorium: PMW_TEST_PUBLIC_KEY_HEX dla testów)."""
    v = (os.environ.get("PMW_TEST_PUBLIC_KEY_HEX") if dev_overrides() else None) or client_config.PUBLIC_KEY_HEX
    v = (v or "").strip().lower()
    if not v:
        return None, "PUBLIC_KEY_HEX jest pusty"
    if not re.fullmatch(r"[0-9a-f]{64}", v):
        return None, "PUBLIC_KEY_HEX musi mieć 64 znaki 0-9 a-f"
    return bytes.fromhex(v), None


def _mask(key: str | None) -> str | None:
    return None if not key else (key[:12] + "…" + key[-6:] if len(key) > 24 else key)


def _iso(ts) -> str | None:
    if ts is None:
        return None
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class LicenseGate:
    def __init__(self, *, clock=time.time, net: NetClock | None = None, path: Path | None = None, log=None):
        self.edition = edition()
        self.required = self.edition == "CLIENT"
        self.clock = clock
        self.net = net or NetClock()
        self.path = Path(path) if path else license_path()
        self.log = log
        self._lock = threading.RLock()
        self._state: dict = {}
        self.on_unlock: list = []                                   # wywoływane po przejściu brak licencji -> ważna (start silnika)
        self.on_lock: list = []
        self._monitor: threading.Thread | None = None
        if not self.required:
            self._state = self._owner_state()

    # ------------------------------------------------------------------------------------------------ plik license.dat
    def _read(self) -> dict:
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write(self, d: dict) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + f".{os.getpid()}.tmp")
            tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as exc:
            if self.log is not None:
                self.log.warn("LICENSE", "SAVE_FAILED", f"Nie można zapisać {self.path}: {exc}")

    # ------------------------------------------------------------------------------------------------ ocena
    def _owner_state(self) -> dict:
        return {"edition": "OWNER", "required": False, "valid": True, "code": "OWNER", "message": "Wersja właściciela – licencja niepotrzebna.",
                "checked_at": _iso(self.clock())}

    def _base(self, code: str, message: str, **kw) -> dict:
        try:
            here = get_hwid()
        except Exception:  # noqa: BLE001
            here = None
        st = {"edition": "CLIENT", "required": True, "valid": code == "OK", "code": code, "message": message, "hwid": here,
              "user": None, "license_hwid": None, "perpetual": None, "iat": None, "exp": None, "iat_iso": None, "exp_iso": None,
              "days_left": None, "warn": False, "time_source": None, "key_masked": None, "checked_at": _iso(self.clock())}
        st.update(kw)
        return st

    def _evaluate(self, key: str | None, *, refresh_net: bool = False) -> tuple[dict, dict | None]:
        """(stan, nowe_dane_pliku|None). Nie zapisuje."""
        store = self._read()
        key = key if key is not None else store.get("key")
        pub, perr = public_key()
        if pub is None:
            return self._base("NO_PUBLIC_KEY", MSG["NO_PUBLIC_KEY"], detail=perr), None
        if crypto_available():
            return self._base("NO_CRYPTO", MSG["NO_CRYPTO"]), None
        if not key:
            return self._base("NO_LICENSE", MSG["NO_LICENSE"]), None
        local = self.clock()
        off = self.net.offset(refresh=refresh_net)
        last = store.get("last_seen")
        last = float(last) if isinstance(last, (int, float)) else None
        if off is not None:
            if abs(off) > CLOCK_TOLERANCE_S:
                return self._base("CLOCK_ERROR", MSG["CLOCK_ERROR"].format(hours=round(abs(off) / 3600)), time_source="internet",
                                  key_masked=_mask(key)), None
            now, source = local + off, "internet"
            new_last = now                                          # czas z internetu jest wiarygodny – zastępuje zapis
        else:
            if last is not None and local < last - CLOCK_TOLERANCE_S:
                return self._base("CLOCK_ROLLBACK", MSG["CLOCK_ROLLBACK"], time_source="komputer", key_masked=_mask(key),
                                  last_seen_iso=_iso(last)), None
            now, source = local, "komputer"
            new_last = max(last or 0.0, local)
        try:
            here = get_hwid()
        except Exception:  # noqa: BLE001
            here = None
        r = check_license(key, pub, now=now, hwid=here)
        p = r.get("payload") or {}
        exp = p.get("exp")
        extra = {"user": p.get("u"), "license_hwid": p.get("hw"), "perpetual": (exp is None) if p else None, "iat": p.get("iat"),
                 "exp": exp, "iat_iso": _iso(p.get("iat")), "exp_iso": _iso(exp), "exp_local": fmt_date(exp) if exp else None,
                 "time_source": source, "key_masked": _mask(key)}
        if r["ok"]:
            days = None if exp is None else max(0, math.ceil((exp - now) / DAY))
            extra.update(days_left=days, warn=days is not None and days <= WARN_DAYS)
        if r["code"] == "HWID" and here is None:
            st = self._base("HWID_ERROR", MSG["HWID_ERROR"], **extra)
        else:
            st = self._base(r["code"], r["message"], **extra)
        return st, {**store, "last_seen": new_last}

    def evaluate(self, *, refresh_net: bool = False) -> dict:
        """Sprawdzenie zapisanej licencji (start, okresowo, przed trybem). Aktualizuje ostatni znany czas w license.dat."""
        if not self.required:
            with self._lock:
                self._state = self._owner_state()
                return dict(self._state)
        st, store = self._evaluate(None, refresh_net=refresh_net)
        with self._lock:
            was = bool(self._state.get("valid"))
            if store is not None and store.get("key"):
                self._write(store)
            self._state = st
        self._transition(was, st)
        return dict(st)

    def activate(self, key: str) -> dict:
        """Aktywacja wklejonego klucza. Zły klucz NIE nadpisuje zapisanego (Zmień klucz)."""
        if not self.required:
            return {**self._owner_state(), "activated": False}
        st, store = self._evaluate(key, refresh_net=True)
        if not st["valid"]:
            return {**st, "activated": False}
        with self._lock:
            was = bool(self._state.get("valid"))
            self._write({**(store or {}), "schema": "PMW-LIC-1", "key": "".join(str(key).split()), "activated_at": self.clock()})
            self._state = st
        if self.log is not None:
            self.log.info("LICENSE", "ACTIVATED", f"Licencja aktywna: {st.get('user')}" + (f", do {st.get('exp_local')}" if st.get("exp") else
                                                                                         ", bezterminowa"))
        self._transition(was, st)
        return {**st, "activated": True, "message": "Licencja aktywna."}

    def _transition(self, was: bool, st: dict) -> None:
        now_ok = bool(st.get("valid"))
        if now_ok and not was:
            for fn in list(self.on_unlock):
                try:
                    fn()
                except Exception:  # noqa: BLE001
                    if self.log is not None:
                        self.log.error("LICENSE", "UNLOCK_CALLBACK", "Błąd uruchamiania po aktywacji licencji")
        elif was and not now_ok:
            if self.log is not None:
                self.log.warn("LICENSE", "LOCKED", f"Licencja nieważna ({st.get('code')}): {st.get('message')}")
            for fn in list(self.on_lock):
                try:
                    fn()
                except Exception:  # noqa: BLE001
                    pass

    # ------------------------------------------------------------------------------------------------ dla reszty programu
    def state(self) -> dict:
        with self._lock:
            if not self._state:
                return self.evaluate()
            return dict(self._state)

    @property
    def locked(self) -> bool:
        if not self.required:
            return False
        with self._lock:
            return not self._state.get("valid", False)

    def ok(self) -> bool:
        return not self.locked

    def require(self, action: str = "") -> dict:
        """Wywołanie przed uruchomieniem trybu: świeże sprawdzenie (czas z internetu z pamięci 10 min). Brak ważnej licencji =
        LicenseRequired."""
        st = self.evaluate()
        if not st["valid"]:
            raise LicenseRequired(st, action)
        return st

    def start_monitor(self, stop: threading.Event) -> None:
        if not self.required or self._monitor is not None:
            return

        def loop():
            while not stop.wait(RECHECK_S):
                try:
                    self.evaluate()
                except Exception:  # noqa: BLE001
                    pass
        self._monitor = threading.Thread(target=loop, name="license-monitor", daemon=True)
        self._monitor.start()
