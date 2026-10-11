"""License session of one program run.

* the key is passed in memory to `open()` and then dropped (never stored, logged, exported or put in argv/env/URL);
* the server answers with a session token (memory only) and a lease = Ed25519-signed JWT valid <= 30 s, verified here
  with the PINNED public key from config (license.public_key_pem); a lease for another session/run is rejected;
* `renew()` is called by the guard thread every few seconds; when the server refuses (expired, revoked, terminated,
  limit) the guard turns DENIED at once; when the server cannot be reached the current lease stays valid only until its
  own `exp` (<= 30 s) - no offline mode, no grace period;
* local time is never trusted for the license expiry: decisions use the server's lease `exp` mapped onto the local
  monotonic clock at the moment the lease was received.
"""
from __future__ import annotations

import json
import secrets
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

MESSAGES = {
    "LICENSE_INVALID": "Nieprawidłowa licencja (sprawdź, czy wkleiłeś cały klucz MQL72-…).",
    "LICENSE_EXPIRED": "Licencja wygasła (ważna 72 h od wygenerowania). Poproś administratora o nową.",
    "LICENSE_REVOKED": "Licencja została cofnięta przez administratora.",
    "SESSION_LIMIT_REACHED": "Ta licencja jest już używana w innym uruchomieniu (limit jednoczesnych sesji). Zamknij tamten program "
                             "albo odczekaj do 30 s po jego awarii.",
    "SESSION_TERMINATED": "Sesja została zakończona przez administratora.",
    "SESSION_ENDED": "Sesja licencji zakończona.", "SESSION_INVALID": "Sesja licencji nieważna.",
    "RATE_LIMITED": "Za dużo prób – odczekaj kilka minut.", "NONCE_REUSED": "Powtórzone żądanie – spróbuj ponownie.",
    "SERVER_CLOCK_ANOMALY": "Serwer licencji wstrzymał wydawanie dostępu (anomalia zegara serwera).",
    "SERVER_UNREACHABLE": "Brak połączenia z serwerem licencji.", "LEASE_INVALID": "Odpowiedź serwera licencji nie przeszła weryfikacji podpisu.",
    "NOT_CONFIGURED": "Brak konfiguracji serwera licencji (license.server_url i license.public_key_pem w data\\config.json).",
    "INSECURE_URL": "Adres serwera licencji musi używać https:// (http:// tylko dla 127.0.0.1/localhost).",
}
FATAL = {"LICENSE_INVALID", "LICENSE_EXPIRED", "LICENSE_REVOKED", "SESSION_LIMIT_REACHED", "SESSION_TERMINATED", "SESSION_ENDED", "SESSION_INVALID",
         "LEASE_INVALID"}


class LicenseError(Exception):
    def __init__(self, code: str, detail: str | None = None):
        super().__init__(code)
        self.code = code
        self.message = MESSAGES.get(code, code) + (f" ({detail})" if detail else "")


def check_url(url: str) -> str:
    u = urllib.parse.urlparse((url or "").strip())
    if not u.scheme or not u.netloc:
        raise LicenseError("NOT_CONFIGURED")
    if u.scheme == "https":
        return url.rstrip("/")
    if u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost", "::1"):
        return url.rstrip("/")
    raise LicenseError("INSECURE_URL")


def load_public_key(pem: str) -> Ed25519PublicKey:
    try:
        k = serialization.load_pem_public_key((pem or "").strip().encode())
    except Exception:
        raise LicenseError("NOT_CONFIGURED", "klucz publiczny") from None
    if not isinstance(k, Ed25519PublicKey):
        raise LicenseError("NOT_CONFIGURED", "klucz publiczny musi być Ed25519")
    return k


class LicenseClient:
    def __init__(self, server_url: str, public_key_pem: str, *, client_version: str = "", timeout: float = 10.0,
                 telemetry_opt_in: bool = False, mono=time.monotonic):
        self.url = check_url(server_url)
        self.pub = load_public_key(public_key_pem)
        self.client_version = client_version
        self.timeout = timeout
        self.telemetry_opt_in = telemetry_opt_in
        self.mono = mono
        self.boot_id = secrets.token_hex(16)              # identifies THIS run; a new start = a new boot id and a new paste
        self._token: str | None = None
        self.session_id: str | None = None
        self.license_id: str | None = None
        self.lease_claims: dict | None = None
        self.lease_valid_until_mono = 0.0
        self.license_expires_at: int | None = None
        self.server_time: int | None = None
        self.renew_every = 10.0

    # ------------------------------------------------------------ transport
    def _post(self, path: str, body: dict) -> dict:
        data = json.dumps(body).encode()
        req = urllib.request.Request(self.url + path, data=data, method="POST",
                                     headers={"Content-Type": "application/json", "User-Agent": f"MasterQUO/{self.client_version}"})
        ctx = ssl.create_default_context() if self.url.startswith("https://") else None
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=ctx) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            try:
                code = json.loads(e.read().decode()).get("error") or f"HTTP_{e.code}"
            except Exception:
                code = f"HTTP_{e.code}"
            raise LicenseError(code) from None
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise LicenseError("SERVER_UNREACHABLE", type(e).__name__) from None

    def _accept_lease(self, lease: str, t_sent: float) -> None:
        try:
            c = jwt.decode(lease, self.pub, algorithms=["EdDSA"], audience="masterquo-client", issuer="mqlicense",
                           options={"require": ["exp", "iat", "sub", "sid"], "verify_exp": False, "verify_iat": False, "verify_nbf": False})
        except jwt.PyJWTError:
            raise LicenseError("LEASE_INVALID") from None
        if c.get("typ") != "mq-lease" or c.get("boot") != self.boot_id or (self.session_id and c.get("sid") != self.session_id):
            raise LicenseError("LEASE_INVALID")
        if self.lease_claims and int(c["iat"]) <= int(self.lease_claims["iat"]):
            raise LicenseError("LEASE_INVALID")            # replayed / older lease never extends access
        ttl = int(c["exp"]) - int(c["iat"])                # server-clock duration; mapped onto the local monotonic clock
        if ttl <= 0 or ttl > 120:
            raise LicenseError("LEASE_INVALID")
        self.lease_claims = c
        self.session_id = c["sid"]
        self.license_id = c["sub"]
        self.license_expires_at = int(c["lic_exp"])
        self.server_time = int(c["iat"])
        self.lease_valid_until_mono = t_sent + ttl         # counted from the moment the request was SENT (conservative)

    # ------------------------------------------------------------ API
    def open(self, license_key: str) -> dict:
        t0 = self.mono()
        r = self._post("/api/v1/client/session", {"license_key": license_key, "boot_id": self.boot_id, "nonce": secrets.token_hex(16),
                                                  "client_version": self.client_version[:40], "telemetry_opt_in": bool(self.telemetry_opt_in)})
        self._token = r.get("session_token")
        self.renew_every = float(max(3, min(int(r.get("renew_every_s") or 10), 10)))
        self._accept_lease(r.get("lease") or "", t0)
        return self.status()

    def renew(self, telemetry: dict | None = None) -> dict:
        if not self._token:
            raise LicenseError("SESSION_INVALID")
        t0 = self.mono()
        r = self._post("/api/v1/client/renew", {"session_token": self._token, "boot_id": self.boot_id,
                                                "telemetry": telemetry if self.telemetry_opt_in else None})
        self._accept_lease(r.get("lease") or "", t0)
        return self.status()

    def end(self) -> None:
        if self._token:
            try:
                self._post("/api/v1/client/end", {"session_token": self._token, "boot_id": self.boot_id})
            except LicenseError:
                pass
            self._token = None
        self.lease_valid_until_mono = 0.0

    def lease_ok(self) -> bool:
        return self._token is not None and self.mono() < self.lease_valid_until_mono

    def status(self) -> dict:
        left = self.lease_valid_until_mono - self.mono()
        lic_left = None
        if self.license_expires_at is not None and self.server_time is not None and self.lease_claims:
            # server time now ~ lease iat + elapsed since the lease was received
            elapsed = self.mono() - (self.lease_valid_until_mono - (int(self.lease_claims["exp"]) - int(self.lease_claims["iat"])))
            lic_left = max(0, int(self.license_expires_at - (self.server_time + elapsed)))
        return {"session_id": self.session_id, "license_id": self.license_id, "license_expires_at": self.license_expires_at,
                "license_seconds_left": lic_left, "lease_seconds_left": round(max(0.0, left), 1), "lease_ok": self.lease_ok()}

    def __repr__(self) -> str:                             # never print tokens
        return f"<LicenseClient session={self.session_id} lease_ok={self.lease_ok()}>"
