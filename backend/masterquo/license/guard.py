"""LicenseGuard - the single license check of the bot.

OWNER edition: always authorized (no network), the License Manager is available instead.
CLIENT edition (online only, no offline grace):
  * startup: validation against the License API; until it succeeds new trading actions are blocked;
  * every `interval` seconds (default 300) a background validation;
  * `authorize_new_order()` - called by the three places that open NEW positions (S01-S12 gateway, manual orders, SCALPING /
    HEDGING primary entries) - validates online right before the order; any failure blocks that order;
  * between validations the expiry is enforced on the server's clock (iat + elapsed monotonic time);
  * every answer must carry a valid Ed25519 signature of the pinned public key, this license, this device and the nonce
    sent in that very request - an unsigned / old / foreign answer is TAMPERED.
A license / network failure never closes open positions: SL/TP, partial exits, break-even moves and hedge legs of existing
plans keep running; only new entries stop (and new-signal notifications to Telegram).
"""
from __future__ import annotations

import logging
import threading
import time

from ..version import APP_VERSION
from . import client as C
from . import protocol as P
from .edition import Edition, load
from .hwid import HwidError, fingerprint
from .tokenstore import TokenStore

log = logging.getLogger("masterquo.license")
STATUS_PL = {
    "OWNER": "OWNER EDITION – licencja nie jest wymagana",
    "NOT_CONFIGURED": "paczka CLIENT bez konfiguracji serwera licencji",
    "NOT_ACTIVATED": "licencja nieaktywowana – wpisz klucz",
    "CHECKING": "sprawdzanie licencji…",
    "ACTIVE": "licencja aktywna",
    "INVALID": "nieprawidłowy klucz albo urządzenie wymaga ponownej aktywacji",
    "EXPIRED": "licencja wygasła",
    "REVOKED": "licencja cofnięta przez administratora",
    "DEVICE_MISMATCH": "licencja przypisana do innego urządzenia",
    "SERVER_UNAVAILABLE": "brak połączenia z serwerem licencji",
    "RATE_LIMITED": "zbyt wiele prób – serwer licencji chwilowo odmawia",
    "TAMPERED": "odpowiedź serwera licencji nie przeszła weryfikacji podpisu",
    "HWID_ERROR": "nie udało się odczytać identyfikatora urządzenia",
}
ERROR_STATUS = {P.INVALID_LICENSE: "INVALID", P.LICENSE_EXPIRED: "EXPIRED", P.LICENSE_REVOKED: "REVOKED",
                P.DEVICE_MISMATCH: "DEVICE_MISMATCH", P.RATE_LIMITED: "RATE_LIMITED"}


class LicenseGuard:
    def __init__(self, edition: Edition | None = None, *, bus=None, applog=None, store: TokenStore | None = None, request=None,
                 interval: float = 300.0, mono=time.monotonic, hwid_fn=fingerprint, client_version: str = APP_VERSION):
        self.edition = edition or load()
        self.bus, self.applog = bus, applog
        self.store = store
        self.request = request or C.request
        self.interval = float(interval)
        self.mono = mono
        self.hwid_fn = hwid_fn
        self.client_version = client_version
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ok_mono: float | None = None              # monotonic time of the last successful validation
        self._fail_mono: float | None = None            # monotonic time of the last failed check
        self._srv_at: tuple[float, float] | None = None  # (server time of the last answer, monotonic time it arrived)
        self.state: dict = {"status": "OWNER" if self.edition.is_owner else "CHECKING", "reason": None, "license_id": None,
                            "key_hint": None, "duration": None, "activated_at": None, "expires_at": None, "server_time": None,
                            "checked_at": None, "last_trigger": None}
        if not self.edition.is_owner:
            if self.edition.problem:
                self._set("NOT_CONFIGURED", self.edition.problem)
            elif not self._local():
                self._set("NOT_ACTIVATED", None)

    # ------------------------------------------------------------------ public API
    @property
    def is_owner(self) -> bool:
        return self.edition.is_owner

    def authorized(self) -> bool:
        """Cheap check (UI, notifications): OWNER, or CLIENT with an ACTIVE answer not older than interval + 90 s and not expired."""
        if self.edition.is_owner:
            return True
        with self._lock:
            if self.state["status"] != "ACTIVE" or self._ok_mono is None:
                return False
            if self.mono() - self._ok_mono > self.interval + 90:
                return False
            return not self._expired_now()

    def authorize_new_order(self, context: str = "ORDER") -> tuple[bool, str]:
        """Online validation right before a NEW position is opened. Returns (allowed, reason)."""
        if self.edition.is_owner:
            return True, "OWNER_EDITION"
        with self._lock:                                  # a fresh denial is reused for 20 s (an AUTO loop must not flood the server);
            st0, fail_at = self.state["status"], self._fail_mono   # an ALLOW always needs a new online answer
        if st0 not in ("ACTIVE", "CHECKING") and fail_at is not None and self.mono() - fail_at < 20:
            return False, f"LICENCJA_{st0}: {self.state.get('reason') or STATUS_PL.get(st0, '')}"
        st = self.validate_now(trigger=f"przed zleceniem ({context})")
        if st["status"] == "ACTIVE":
            return True, "LICENSE_ACTIVE"
        return False, f"LICENCJA_{st['status']}: {st.get('reason') or STATUS_PL.get(st['status'], '')}"

    def activate(self, raw_key: str) -> dict:
        if self.edition.is_owner:
            return self.public()
        if self.edition.problem:
            return self._set("NOT_CONFIGURED", self.edition.problem)
        key = P.normalize_key(raw_key or "")
        if not key:
            return self._set("INVALID", "klucz ma nieprawidłowy format (PMW-XXXXX-XXXXX-XXXXX-XXXXX)")
        try:
            hw = self.hwid_fn()
        except HwidError as e:
            return self._set("HWID_ERROR", str(e))
        nonce = P.new_nonce()
        self._set("CHECKING", "aktywacja…", publish=True)
        try:
            out = self.request(self.edition.license_api, "/api/v1/licenses/activate",
                               {"license_key": key, "hwid_hash": hw, "nonce": nonce, "client_version": self.client_version})
        except C.ApiError as e:
            return self._fail(e, "activate")
        try:
            pl = P.verify_assertion(out.get("assertion") or "", self.edition.public_key_raw, license_id=out.get("license_id"), hwid=hw,
                                    nonce=nonce)
        except P.AssertionError_ as e:
            return self._set("TAMPERED", f"weryfikacja podpisu nie powiodła się ({e})")
        if not out.get("token") or not P.TOKEN_RE.match(out["token"]):
            return self._set("TAMPERED", "brak tokenu urządzenia w odpowiedzi")
        if self.store:
            self.store.save({"license_id": pl["lid"], "token": out["token"], "key_hint": P.key_hint(key), "kid": self.edition.kid,
                             "api": self.edition.license_api, "assertion": out["assertion"]})
        self._log("info", "AKTYWACJA", f"Licencja aktywowana ({P.key_hint(key)}, {pl['dur']}, ważna do {pl['exp']})")
        return self._ok(pl, P.key_hint(key), "aktywacja")

    def validate_now(self, trigger: str = "ręcznie") -> dict:
        if self.edition.is_owner:
            return self.public()
        if self.edition.problem:
            return self._set("NOT_CONFIGURED", self.edition.problem)
        loc = self._local()
        if not loc:
            return self._set("NOT_ACTIVATED", None)
        try:
            hw = self.hwid_fn()
        except HwidError as e:
            return self._set("HWID_ERROR", str(e))
        nonce = P.new_nonce()
        with self._lock:
            self.state["last_trigger"] = trigger
        try:
            out = self.request(self.edition.license_api, "/api/v1/licenses/validate",
                               {"license_id": loc["license_id"], "hwid_hash": hw, "token": loc["token"], "nonce": nonce,
                                "client_version": self.client_version})
        except C.ApiError as e:
            return self._fail(e, "validate", key_hint=loc.get("key_hint"), license_id=loc["license_id"])
        try:
            pl = P.verify_assertion(out.get("assertion") or "", self.edition.public_key_raw, license_id=loc["license_id"], hwid=hw, nonce=nonce)
        except P.AssertionError_ as e:
            return self._set("TAMPERED", f"weryfikacja podpisu nie powiodła się ({e})", key_hint=loc.get("key_hint"))
        return self._ok(pl, loc.get("key_hint"), trigger)

    def forget(self) -> dict:
        """Remove the local activation (e.g. to enter another key). The server binding is unchanged."""
        if self.store:
            self.store.clear()
        with self._lock:
            self._ok_mono = None
        if self.edition.is_owner:
            return self.public()
        return self._set("NOT_ACTIVATED", "lokalna aktywacja usunięta", key_hint=None, license_id=None)

    def public(self) -> dict:
        with self._lock:
            st = dict(self.state)
            if st["status"] == "ACTIVE" and not self.authorized():
                st["status"], st["reason"] = ("EXPIRED", "minął termin licencji") if self._expired_now() else ("SERVER_UNAVAILABLE", "brak aktualnej walidacji")
            st.update(edition=self.edition.public(), authorized=self.authorized(), status_pl=STATUS_PL.get(st["status"], st["status"]),
                      validate_every_seconds=int(self.interval), protects="nowe wejścia (S01–S12, ręczne, SCALPING/HEDGING) i powiadomienia o nowych sygnałach",
                      positions_note="Otwarte pozycje nie są zamykane z powodu licencji – SL/TP i zarządzanie pozycjami działają dalej.")
            return st

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self.edition.is_owner or self._thread:
            return
        self._thread = threading.Thread(target=self._loop, name="license-guard", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        self.validate_now(trigger="start programu")
        while not self._stop.wait(self.interval):
            try:
                self.validate_now(trigger="okresowo")
            except Exception:  # noqa: BLE001 - the guard thread never dies; status stays not authorized
                log.exception("license validation failed")
                self._set("SERVER_UNAVAILABLE", "błąd sprawdzania licencji")

    # ------------------------------------------------------------------ internals
    def _local(self) -> dict | None:
        d = self.store.load() if self.store else None
        if d and (d.get("kid") not in (None, self.edition.kid) or d.get("api") not in (None, self.edition.license_api)):
            return None                                  # activation of another server / key: activate again
        return d

    def _expired_now(self) -> bool:
        exp = self.state.get("expires_at")
        if not exp or not self._srv_at:
            return False
        srv, at = self._srv_at
        return srv + (self.mono() - at) >= P.parse_utc(exp)

    def _ok(self, pl: dict, key_hint: str | None, trigger: str) -> dict:
        with self._lock:
            self._ok_mono = self.mono()
            self._srv_at = (P.parse_utc(pl["iat"]), self._ok_mono)
            prev = self.state["status"]
            self.state.update(license_id=pl["lid"], key_hint=key_hint, duration=pl["dur"], activated_at=pl["act"], expires_at=pl["exp"],
                              server_time=pl["iat"])
        if prev != "ACTIVE":
            self._log("info", "AKTYWNA", f"Licencja aktywna do {pl['exp']} ({trigger})")
        return self._set("ACTIVE", None)

    def _fail(self, e: C.ApiError, what: str, **kw) -> dict:
        status = ERROR_STATUS.get(e.code or "", "SERVER_UNAVAILABLE" if e.code is None else "INVALID")
        with self._lock:
            self._ok_mono = None
            self._fail_mono = self.mono()
        return self._set(status, e.message, **kw)

    def _set(self, status: str, reason: str | None, publish: bool = True, **kw) -> dict:
        with self._lock:
            prev = (self.state["status"], self.state["reason"])
            self.state.update(status=status, reason=reason, checked_at=P.utc_iso(time.time()), **kw)
            if status not in ("ACTIVE", "CHECKING", "OWNER"):
                self._ok_mono = None
                self._fail_mono = self.mono()
        if prev[0] != status and status not in ("ACTIVE", "CHECKING", "OWNER"):
            self._log("warn", status, f"Licencja: {STATUS_PL.get(status, status)}" + (f" – {reason}" if reason else "")
                      + " – nowe wejścia zablokowane, otwarte pozycje bez zmian")
        out = self.public()
        if publish and self.bus is not None:
            try:
                self.bus.publish("license", out)
            except Exception:  # noqa: BLE001
                pass
        return out

    def _log(self, level: str, code: str, msg: str) -> None:
        if self.applog is not None:
            try:
                getattr(self.applog, level)("LICENSE", code, msg)
                return
            except Exception:  # noqa: BLE001
                pass
        getattr(log, "warning" if level == "warn" else "info")(msg)
