"""HTTPS calls to the License API (stdlib urllib; the OS certificate store through `truststore` when available).
Short timeouts - the bot never waits long for the license server; a failure is reported as SERVER_UNAVAILABLE upstream."""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request

from .url import valid_license_url

TIMEOUT_S = 8.0


class ApiError(Exception):
    """The server answered with a machine-readable error (code) or could not be reached (code=None)."""

    def __init__(self, code: str | None, message: str, http: int | None = None):
        super().__init__(message)
        self.code, self.message, self.http = code, message, http


def _ctx() -> ssl.SSLContext:
    try:
        import truststore
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:  # noqa: BLE001 - fall back to Python's default trust store
        return ssl.create_default_context()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never forward license keys or bearer tokens to a redirect destination."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(base: str, path: str, body: dict | None = None, *, token: str | None = None, method: str | None = None,
            timeout: float = TIMEOUT_S, raw: bytes | None = None, headers: dict | None = None) -> dict:
    """raw: exact body bytes (signed admin requests sign these bytes); headers: extra headers (admin signature)."""
    if not valid_license_url(base) or not path.startswith("/") or path.startswith("//"):
        raise ApiError("INVALID_REQUEST", "nieprawidłowy adres serwera licencji")
    url = base.rstrip("/") + path
    data = raw if raw is not None else (json.dumps(body).encode("utf-8") if body is not None else None)
    extra = headers or {}
    headers = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "PepeMarketWizard-License/1", **extra}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, method=method or ("POST" if data is not None else "GET"), headers=headers)
    try:
        opener = urllib.request.build_opener(_NoRedirect(), urllib.request.HTTPSHandler(context=_ctx()))
        with opener.open(req, timeout=timeout) as r:
            raw = r.read(65536)
        return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        if 300 <= e.code < 400:                        # redirects are never followed (a key / token must not reach another host)
            raise ApiError("REDIRECT_REFUSED", f"serwer licencji odpowiedział przekierowaniem {e.code} – adres musi wskazywać bezpośrednio "
                                               "usługę (bez przekierowań); popraw adres w konfiguracji", e.code) from None
        try:
            err = (json.loads(e.read(8192) or b"{}").get("error") or {})
        except ValueError:
            err = {}
        raise ApiError(err.get("code") or f"HTTP_{e.code}", err.get("message") or f"serwer licencji odpowiedział {e.code}", e.code) from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        raise ApiError(None, f"brak połączenia z serwerem licencji ({type(e).__name__})") from None
