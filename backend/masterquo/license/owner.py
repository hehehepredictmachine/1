"""OWNER EDITION - License Manager client of the License API (1.29: no login screen).

Every privileged operation goes to the server's admin endpoints, signed with this computer's OWNER device key (owner_key.py,
PMW-ADMIN-v1): method, path + query, SHA-256 of the exact body, UTC time and a random nonce. The server accepts the signature only
from a device key the owner trusted from the server's shell (one-time pairing, outside the public API) - nothing to type at start.
The desktop app never touches the license database. Saved locally: the server address (data/license_owner.json, not a secret) and
the device key (DPAPI on Windows). Clock skew against the server is measured from /health and compensated (max 120 s window).
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from urllib.parse import urlencode

from .. import paths
from . import client as C
from . import protocol as P
from .owner_key import OwnerKeyStore, default_label
from .url import valid_license_url

MAIN_DURATIONS = ("72h", "7d", "31d")             # the owner's standard offers; 24h stays available as an advanced option


class OwnerError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


class OwnerLicenseManager:
    def __init__(self, data_dir: Path | None = None, request=None, clock=time.time):
        d = Path(data_dir or paths.data_dir())
        self.cfg_path = d / "license_owner.json"
        self.request = request or C.request
        self.clock = clock
        self.keys = OwnerKeyStore(d)
        self._lock = threading.Lock()
        self.offset = 0.0                                 # server time - local time (measured, not trusted for anything else)
        self.state = {"checked_at": None, "paired": None, "reason": None, "server_version": None}
        try:
            cfg = json.loads(self.cfg_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cfg = {}
        url = cfg.get("server_url") or None
        self.url = url if url and valid_license_url(url) else None
        self.label = cfg.get("label") or default_label()

    # ------------------------------------------------------------------ status / pairing
    def _pair_cmd(self, key) -> str:
        return f'python -m pmw_license admin-keys add --public-key {key.public_b64} --label "{self.label}"'

    def status(self) -> dict:
        key = self.keys.active()
        pend = self.keys.pending()
        return {"server_url": self.url, "auth": "DEVICE_KEY", "device": key.public(), "label": self.label,
                "pairing_command": self._pair_cmd(key), "paired": self.state["paired"], "checked_at": self.state["checked_at"],
                "reason": self.state["reason"], "server_version": self.state["server_version"], "clock_offset_s": round(self.offset, 1),
                "rotation": ({"pending": pend.public(), "pairing_command": self._pair_cmd(pend)} if pend else None),
                "durations": list(MAIN_DURATIONS), "durations_advanced": [d for d in P.DURATIONS if d not in MAIN_DURATIONS],
                "durations_pl": P.DURATION_PL,
                "note": "bez logowania: aplikacja podpisuje żądania kluczem tego komputera; serwer ufa mu po jednorazowym sparowaniu"}

    def set_server(self, url: str, label: str | None = None) -> dict:
        url = (url or "").strip().rstrip("/")
        if not valid_license_url(url):
            raise OwnerError("INVALID_REQUEST", "adres serwera licencji: https://… (http tylko dla 127.0.0.1 / localhost)")
        with self._lock:
            self.url = url
            if label:
                self.label = label.strip()[:60] or self.label
        self.cfg_path.parent.mkdir(parents=True, exist_ok=True)
        self.cfg_path.write_text(json.dumps({"server_url": url, "label": self.label}), encoding="utf-8")
        return self.check()

    def check(self) -> dict:
        """Signed whoami: tells whether the server trusts this device key (paired) - the 'connection' state of the page."""
        if not self.url:
            self.state.update(checked_at=P.utc_iso(self.clock()), paired=None, reason="podaj adres serwera licencji")
            return self.status()
        try:
            who = self._signed("GET", "/api/v1/admin/whoami")
            self.state.update(checked_at=P.utc_iso(self.clock()), paired=True, reason=None, server_version=who.get("version"))
        except OwnerError as e:
            self.state.update(checked_at=P.utc_iso(self.clock()), paired=False if e.code == P.UNAUTHORIZED else None, reason=e.message)
        return self.status()

    def _measure_offset(self) -> None:
        try:
            h = self.request(self.url, "/health", timeout=6)
            self.offset = P.parse_utc(h["server_time"]) - self.clock()
        except (C.ApiError, KeyError, ValueError):
            pass

    def _signed(self, method: str, path: str, body: dict | None = None, key=None) -> dict:
        if not self.url:
            raise OwnerError("NOT_CONFIGURED", "podaj adres serwera licencji")
        key = key or self.keys.active()
        raw = json.dumps(body, separators=(",", ":")).encode("utf-8") if body is not None else None
        for attempt in (0, 1):
            ts = int(self.clock() + self.offset)
            hdr = key.sign_headers(method, path, raw, ts)
            try:
                return self.request(self.url, path, None, raw=raw, headers=hdr, method=method)
            except C.ApiError as e:
                if attempt == 0 and e.code == P.UNAUTHORIZED and "czas żądania" in (e.message or ""):
                    self._measure_offset()                # local clock off by more than 120 s: retry once with the server's time
                    continue
                raise OwnerError(e.code or "SERVER_UNAVAILABLE", e.message) from None
        raise OwnerError("SERVER_UNAVAILABLE", "brak odpowiedzi serwera licencji")

    def _call(self, path: str, body: dict | None = None, method: str | None = None) -> dict:
        out = self._signed(method or ("POST" if body is not None else "GET"), path, body)
        self.state.update(paired=True, reason=None)
        return out

    # ------------------------------------------------------------------ key rotation (lost / replaced computer: see README)
    def rotation(self, action: str) -> dict:
        if action == "begin":
            self.keys.begin_rotation()
            return self.status()
        if action == "cancel":
            self.keys.cancel_rotation()
            return self.status()
        if action != "commit":
            raise OwnerError("INVALID_REQUEST", "akcja: begin | commit | cancel")
        pend = self.keys.pending()
        if pend is None:
            raise OwnerError("INVALID_REQUEST", "brak oczekującego klucza – najpierw rozpocznij rotację")
        self._signed("GET", "/api/v1/admin/whoami", key=pend)          # the new key must already be trusted by the server
        old = self.keys.active()
        self.keys.commit_rotation()
        revoked = None
        try:
            revoked = self._signed("POST", f"/api/v1/admin/keys/{old.kid}/revoke", {"reason": "rotacja klucza urządzenia OWNER"})
        except OwnerError as e:
            revoked = {"status": "NOT_REVOKED", "reason": e.message}
        st = self.check()
        return {**st, "rotation_result": {"new": pend.kid, "old": old.kid, "old_revoked": revoked}}

    def admin_keys(self) -> dict:
        return self._call("/api/v1/admin/keys")

    # ------------------------------------------------------------------ licenses
    def create(self, duration: str, note: str | None = None) -> dict:
        if duration not in P.DURATIONS:
            raise OwnerError("INVALID_REQUEST", "okres: 72h, 7d albo 31d (24h – opcja zaawansowana)")
        return self._call("/api/v1/admin/licenses", {"duration": duration, "note": note or None})

    def list(self, status: str | None = None, duration: str | None = None, q: str | None = None, limit: int = 100, offset: int = 0) -> dict:
        qs = urlencode({k: v for k, v in {"status": status, "duration": duration, "q": q, "limit": limit, "offset": offset}.items() if v not in (None, "")})
        return self._call(f"/api/v1/admin/licenses?{qs}")

    def revoke(self, license_id: str, reason: str | None = None) -> dict:
        self._check_id(license_id)
        return self._call(f"/api/v1/admin/licenses/{license_id}/revoke", {"reason": reason})

    def reset_device(self, license_id: str, reason: str | None = None) -> dict:
        self._check_id(license_id)
        return self._call(f"/api/v1/admin/licenses/{license_id}/reset-device", {"reason": reason})

    def stats(self) -> dict:
        return self._call("/api/v1/admin/stats")

    def audit(self, limit: int = 100) -> dict:
        return self._call(f"/api/v1/admin/audit?limit={int(limit)}")

    @staticmethod
    def _check_id(license_id: str) -> None:
        if not P.LICENSE_ID_RE.match(license_id or ""):
            raise OwnerError("NOT_FOUND", "nieprawidłowy identyfikator licencji")
