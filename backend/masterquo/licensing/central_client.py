"""HTTPS client of the central MasterQUO server (stdlib urllib, certificate validation ALWAYS on).

Plain http:// is accepted only for 127.0.0.1/localhost AND only when config.central.allow_insecure_localhost is set
(local development / tests). Nothing here ever disables TLS verification.
"""
from __future__ import annotations

import base64
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


class CentralError(Exception):
    def __init__(self, code: str, status: int = 0, detail: dict | None = None):
        super().__init__(code)
        self.code, self.status, self.detail = code, status, detail or {}

    @property
    def network(self) -> bool:
        return self.status == 0


def device_message(method: str, path: str, nonce: str, body: bytes) -> bytes:
    import hashlib
    return f"MQDEV1\n{method.upper()}\n{path}\n{nonce}\n{hashlib.sha256(body).hexdigest()}".encode()


def _ssl_context() -> ssl.SSLContext:
    try:
        import truststore                      # Windows certificate store (corporate proxies, local CAs)
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:
        return ssl.create_default_context()


class CentralClient:
    def __init__(self, base_url: str, *, allow_insecure_localhost: bool = False, timeout: float = 10.0):
        u = urllib.parse.urlparse(base_url.strip())
        if u.scheme == "https":
            pass
        elif u.scheme == "http" and allow_insecure_localhost and u.hostname in ("127.0.0.1", "localhost", "::1"):
            pass
        else:
            raise CentralError("CENTRAL_URL_MUST_BE_HTTPS")
        self.base = f"{u.scheme}://{u.netloc}"
        self.timeout = timeout
        self._ctx = _ssl_context() if u.scheme == "https" else None

    def _req(self, method: str, path: str, body: dict | None = None, headers: dict | None = None, raw: bytes | None = None) -> dict:
        data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
        h = {"Accept": "application/json", "User-Agent": "MasterQUO-Bot"}
        if data is not None:
            h["Content-Type"] = "application/json"
        h.update(headers or {})
        r = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(r, timeout=self.timeout, context=self._ctx) as resp:
                return json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                j = json.loads(e.read() or b"{}")
            except ValueError:
                j = {}
            raise CentralError(str(j.get("error") or (j.get("detail") and "VALIDATION_ERROR") or f"HTTP_{e.code}"), e.code, j.get("detail")
                               if isinstance(j.get("detail"), dict) else {}) from None
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise CentralError("CENTRAL_UNREACHABLE", 0, {"why": type(e).__name__}) from None

    # ------------------------------------------------------------ user (bearer CLIENT session)
    def login(self, email: str, password: str, totp: str | None = None) -> dict:
        return self._req("POST", "/api/v1/auth/login", {"email": email, "password": password, "client": "bot", "totp": totp or None})

    def logout(self, token: str) -> None:
        try:
            self._req("POST", "/api/v1/auth/logout", {}, {"Authorization": f"Bearer {token}"})
        except CentralError:
            pass

    def register(self, email: str, password: str, display_name: str | None) -> dict:
        return self._req("POST", "/api/v1/auth/register", {"email": email, "password": password, "display_name": display_name})

    def forgot(self, email: str) -> dict:
        return self._req("POST", "/api/v1/auth/password/forgot", {"email": email})

    def change_password(self, token: str, current: str, new: str) -> dict:
        return self._req("POST", "/api/v1/auth/password/change", {"current_password": current, "new_password": new}, {"Authorization": f"Bearer {token}"})

    def me(self, token: str) -> dict:
        return self._req("GET", "/api/v1/me", headers={"Authorization": f"Bearer {token}"})

    def activate(self, token: str, key: str, priv: Ed25519PrivateKey, public_pem: str, install_id: str, device_name: str) -> dict:
        import hashlib
        ch = self._req("POST", "/api/v1/device/challenge", {"purpose": "ACTIVATE"}, {"Authorization": f"Bearer {token}"})
        norm = "".join(c for c in key.strip().upper() if c.isalnum())
        norm = norm[4:] if norm.startswith("MQL1") else norm
        norm = "MQL1-" + "-".join(norm[i:i + 5] for i in range(0, len(norm), 5))
        kh = hashlib.sha256(norm.encode()).hexdigest()
        sig = base64.b64encode(priv.sign(device_message("POST", "/api/v1/licenses/activate", ch["nonce"], (kh + "|" + install_id).encode()))).decode()
        return self._req("POST", "/api/v1/licenses/activate", {"key": key, "public_key": public_pem, "install_id": install_id, "device_name": device_name,
                                                               "nonce": ch["nonce"], "signature": sig}, {"Authorization": f"Bearer {token}"})

    # ------------------------------------------------------------ device-signed (proof of possession, single-use nonce)
    def device_call(self, priv: Ed25519PrivateKey, device_id: str, method: str, path: str, body: dict | None = None) -> tuple[dict, float, float]:
        """Returns (json, t_start_mono, t_end_mono). t_start is taken BEFORE the request that produces the lease."""
        ch = self._req("POST", "/api/v1/device/challenge", {"purpose": "DEVICE", "device_id": device_id})
        raw = b"" if body is None else json.dumps(body).encode()
        sig = base64.b64encode(priv.sign(device_message(method, path, ch["nonce"], raw))).decode()
        t0 = time.monotonic()
        out = self._req(method, path, None, {"X-MQ-Device": device_id, "X-MQ-Nonce": ch["nonce"], "X-MQ-Sig": sig}, raw=raw if method != "GET" else None)
        return out, t0, time.monotonic()
