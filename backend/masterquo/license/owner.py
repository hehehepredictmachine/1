"""OWNER EDITION - License Manager client of the License API.

Every privileged operation goes to the server's authenticated admin endpoints; this desktop app never touches the license
database. The admin password is sent once to log in and is not stored; the session token lives in memory only (a restart
of the bot = log in again). Only the server address is saved (data/license_owner.json, not a secret).
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from .. import paths
from . import client as C
from . import protocol as P


class OwnerError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


class OwnerLicenseManager:
    def __init__(self, data_dir: Path | None = None, request=None):
        self.cfg_path = Path(data_dir or paths.data_dir()) / "license_owner.json"
        self.request = request or C.request
        self._lock = threading.Lock()
        self._token: str | None = None
        self._exp: float | None = None
        self.username: str | None = None
        try:
            self.url = (json.loads(self.cfg_path.read_text(encoding="utf-8")).get("server_url") or None)
        except (OSError, ValueError):
            self.url = None

    def status(self) -> dict:
        logged = bool(self._token and self._exp and self._exp > time.time())
        return {"server_url": self.url, "logged_in": logged, "username": self.username if logged else None,
                "session_expires_at": P.utc_iso(self._exp) if logged else None, "durations": list(P.DURATIONS),
                "durations_pl": P.DURATION_PL}

    def login(self, url: str, username: str, password: str) -> dict:
        url = (url or "").strip().rstrip("/")
        if not (url.startswith("https://") or url.startswith("http://127.0.0.1") or url.startswith("http://localhost")):
            raise OwnerError("INVALID_REQUEST", "adres serwera licencji musi zaczynać się od https://")
        try:
            out = self.request(url, "/api/v1/admin/login", {"username": username, "password": password})
        except C.ApiError as e:
            raise OwnerError(e.code or "SERVER_UNAVAILABLE", e.message) from None
        with self._lock:
            self.url, self._token, self.username = url, out["token"], out.get("username") or username
            self._exp = P.parse_utc(out["expires_at"])
        self.cfg_path.parent.mkdir(parents=True, exist_ok=True)
        self.cfg_path.write_text(json.dumps({"server_url": url}), encoding="utf-8")
        return self.status()

    def logout(self) -> dict:
        tok = self._token
        with self._lock:
            self._token, self._exp, self.username = None, None, None
        if tok and self.url:
            try:
                self.request(self.url, "/api/v1/admin/logout", {}, token=tok)
            except C.ApiError:
                pass
        return self.status()

    def _call(self, path: str, body: dict | None = None, method: str | None = None) -> dict:
        if not self._token or not self.url:
            raise OwnerError("UNAUTHORIZED", "zaloguj się do serwera licencji")
        try:
            return self.request(self.url, path, body, token=self._token, method=method)
        except C.ApiError as e:
            if e.code == P.UNAUTHORIZED:
                with self._lock:
                    self._token, self._exp = None, None
            raise OwnerError(e.code or "SERVER_UNAVAILABLE", e.message) from None

    def create(self, duration: str, note: str | None = None) -> dict:
        if duration not in P.DURATIONS:
            raise OwnerError("INVALID_REQUEST", "okres: 24h, 72h, 7d albo 31d")
        return self._call("/api/v1/admin/licenses", {"duration": duration, "note": note or None})

    def list(self, status: str | None = None, duration: str | None = None, q: str | None = None, limit: int = 100, offset: int = 0) -> dict:
        from urllib.parse import urlencode
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
