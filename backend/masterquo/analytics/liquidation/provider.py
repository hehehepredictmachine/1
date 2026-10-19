"""CoinGlass API v4 model1 provider (authorised key from the SecretStore / env COINGLASS_API_KEY - never in URL, logs or UI).

Two documented variants, exactly one active per source key (maps of both are never summed):
  PAIR        GET /api/futures/liquidation/heatmap/model1?exchange=&symbol=&range=
  AGGREGATED  GET /api/futures/liquidation/aggregated-heatmap/model1?symbol=&range=
Errors are classified (HTTP status AND the application 'code' in the body): MISSING_API_KEY, UNAUTHORIZED, ENTITLEMENT_REQUIRED,
RATE_LIMITED (Retry-After), TIMEOUT, NETWORK_ERROR, APP_ERROR, UNSUPPORTED_INSTRUMENT, UNSUPPORTED_SCHEMA, TOO_LARGE.
Entitlement (Professional / Enterprise plan per the documentation on 2026-10-18) is NOT assumed - it is checked by the real call.
"""
from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

from .contract import MAX_BYTES

BASE = "https://open-api-v4.coinglass.com"
PATHS = {"PAIR": "/api/futures/liquidation/heatmap/model1", "AGGREGATED": "/api/futures/liquidation/aggregated-heatmap/model1"}
RANGES = ("12h", "24h", "3d", "7d", "30d", "90d", "180d", "1y")


class ProviderError(Exception):
    def __init__(self, code: str, detail: str = "", retry_after: float | None = None):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code, self.detail, self.retry_after = code, detail, retry_after


def build_request(variant: str, symbol: str, range_: str, exchange: str | None, key: str) -> urllib.request.Request:
    if variant not in PATHS:
        raise ProviderError("UNSUPPORTED_SCHEMA", f"wariant {variant}")
    if range_ not in RANGES:
        raise ProviderError("UNSUPPORTED_SCHEMA", f"range {range_}")
    q = {"symbol": symbol, "range": range_}
    if variant == "PAIR":
        if not exchange:
            raise ProviderError("UNSUPPORTED_INSTRUMENT", "wariant PAIR wymaga giełdy")
        q["exchange"] = exchange
    return urllib.request.Request(BASE + PATHS[variant] + "?" + urllib.parse.urlencode(q),
                                  headers={"CG-API-KEY": key, "accept": "application/json", "User-Agent": "PepeMarketWizard"})


def fetch(variant: str, symbol: str, range_: str, exchange: str | None, key: str | None, *, timeout: float = 15.0, opener=None) -> dict:
    """One request; returns {'data': <model1 object>, 'request': {...no key...}, 'http_status'}. Raises ProviderError."""
    if not key:
        raise ProviderError("MISSING_API_KEY", "brak COINGLASS_API_KEY (Ustawienia → źródła / zmienna środowiskowa)")
    req = build_request(variant, symbol, range_, exchange, key)
    op = opener or urllib.request.urlopen
    try:
        with op(req, timeout=timeout) as r:
            raw = r.read(MAX_BYTES + 1)
            status = getattr(r, "status", 200)
    except urllib.error.HTTPError as e:
        ra = e.headers.get("Retry-After") if e.headers else None
        code = {401: "UNAUTHORIZED", 403: "ENTITLEMENT_REQUIRED", 404: "UNSUPPORTED_INSTRUMENT", 429: "RATE_LIMITED"}.get(e.code, f"HTTP_{e.code}")
        raise ProviderError(code, f"HTTP {e.code}", float(ra) if ra and str(ra).isdigit() else None) from None
    except (socket.timeout, TimeoutError):
        raise ProviderError("TIMEOUT", f"> {timeout}s") from None
    except urllib.error.URLError as e:
        raise ProviderError("NETWORK_ERROR", str(e.reason)[:120]) from None
    if len(raw) > MAX_BYTES:
        raise ProviderError("TOO_LARGE", f"> {MAX_BYTES} B")
    try:
        body = json.loads(raw)
    except ValueError:
        raise ProviderError("UNSUPPORTED_SCHEMA", "odpowiedź nie jest JSON") from None
    code, msg = str(body.get("code", "")), str(body.get("msg", ""))[:200]
    if code not in ("0", "200"):
        low = msg.lower()
        kind = ("ENTITLEMENT_REQUIRED" if ("upgrade" in low or "plan" in low or "permission" in low) else
                "UNAUTHORIZED" if ("key" in low or "auth" in low) else
                "UNSUPPORTED_INSTRUMENT" if ("symbol" in low or "not support" in low or "exchange" in low) else
                "RATE_LIMITED" if ("limit" in low or "too many" in low) else "APP_ERROR")
        raise ProviderError(kind, f"code {code}: {msg}")
    data = body.get("data")
    if not data:
        raise ProviderError("UNSUPPORTED_INSTRUMENT", "pusta odpowiedź (brak danych dla instrumentu/zakresu)")
    return {"data": data, "http_status": status, "request": {"variant": variant, "symbol": symbol, "range": range_, "exchange": exchange,
                                                             "endpoint": PATHS[variant], "at": time.time()}}
