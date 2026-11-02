"""HTTPS calls to the License API (stdlib urllib; the OS certificate store through `truststore` when available).
Short timeouts - the bot never waits long for the license server; a failure is reported as SERVER_UNAVAILABLE upstream."""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request

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


def request(base: str, path: str, body: dict | None = None, *, token: str | None = None, method: str | None = None,
            timeout: float = TIMEOUT_S) -> dict:
    url = base.rstrip("/") + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "PepeMarketWizard-License/1"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, method=method or ("POST" if data is not None else "GET"), headers=headers)
    try:
        kw = {"context": _ctx()} if url.startswith("https://") else {}
        with urllib.request.urlopen(req, timeout=timeout, **kw) as r:
            raw = r.read(65536)
        return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            err = (json.loads(e.read(8192) or b"{}").get("error") or {})
        except ValueError:
            err = {}
        raise ApiError(err.get("code") or f"HTTP_{e.code}", err.get("message") or f"serwer licencji odpowiedział {e.code}", e.code) from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        raise ApiError(None, f"brak połączenia z serwerem licencji ({type(e).__name__})") from None
