"""Local secret storage for the Anthropic API key and optional Telegram token.

Windows: values are encrypted with DPAPI (CryptProtectData, current user scope) and saved in
data/secrets.dpapi.json - readable only by the same Windows user on the same machine.
Other OS (tests/dev): plain JSON with 0600 permissions, clearly marked.
Environment variables (ANTHROPIC_API_KEY, ...) take precedence when set.

Secrets are never returned by the API, never logged and never written to diagnostics.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import threading
from pathlib import Path

from . import paths

# 1.46 arch (I0118): the ONE source of the secret / variable name lists (before: copies with different sets in exports/core, api/app.py and
# __main__._load_dotenv). tools/verify_release.py keeps its own SUPERSET (+ the license server secrets) - it runs without the backend.
ALLOWED = ("ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN", "FRED_API_KEY", "MT5_PASSWORD", "COINGLASS_API_KEY")   # every secret of this store
# settable through POST /api/v1/secrets (COINGLASS_API_KEY has its own route under the liquidity heatmap settings)
UI_SETTABLE = ("TELEGRAM_BOT_TOKEN", "FRED_API_KEY", "ANTHROPIC_API_KEY", "MT5_PASSWORD")
# the ONLY variables __main__._load_dotenv takes from <root>/.env (deliberately without MT5_PASSWORD / COINGLASS_API_KEY)
DOTENV_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "MASTERQUO_DATA_DIR", "FRED_API_KEY", "TELEGRAM_BOT_TOKEN")


def _dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    buf = ctypes.create_string_buffer(data, len(data))
    inp = BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    out = BLOB()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    ok = fn(ctypes.byref(inp), None, None, None, None, 0x1, ctypes.byref(out))  # UI_FORBIDDEN
    if not ok:
        raise OSError("DPAPI_FAILED")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


class SecretStore:
    def __init__(self, directory: Path | None = None):
        d = directory or paths.data_dir()
        self.windows = sys.platform == "win32"
        self.path = d / ("secrets.dpapi.json" if self.windows else "secrets.local.json")
        self._lock = threading.Lock()

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def get(self, name: str) -> str | None:
        if name not in ALLOWED:
            raise KeyError(name)
        env = os.environ.get(name)
        if env:
            return env.strip()
        raw = self._read().get(name)
        if not raw:
            return None
        return self._decode(raw)

    def _decode(self, raw) -> str | None:
        try:
            if self.windows:
                return _dpapi(base64.b64decode(raw), protect=False).decode("utf-8")
            return str(raw)
        except (OSError, ValueError):
            return None

    def source(self, name: str) -> str:
        if os.environ.get(name):
            return "ENVIRONMENT"
        raw = self._read().get(name)
        if not raw:
            return "MISSING"
        # 1.46: stored but not decryptable (DPAPI of another Windows user / computer, e.g. a moved portable folder) - get() returns None,
        # the panel showed LOCAL_STORE with no mask; UNREADABLE = enter the secret again
        return "LOCAL_STORE" if self._decode(raw) is not None else "UNREADABLE"

    def set(self, name: str, value: str | None) -> None:
        if name not in ALLOWED:
            raise KeyError(name)
        with self._lock:
            data = self._read()
            if not value:
                data.pop(name, None)
            elif self.windows:
                data[name] = base64.b64encode(_dpapi(value.strip().encode("utf-8"), protect=True)).decode()
            else:
                data[name] = value.strip()
            tmp = self.path.with_suffix(".tmp")
            # 1.46: created 0600 before any secret is written (was write_text with the umask mode, usually 0644, chmod only afterwards and
            # its error ignored); fchmod also narrows a stale temp file left by a crash
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            try:
                os.fchmod(fd, 0o600)
            except (OSError, AttributeError):
                pass
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps(data))
            tmp.replace(self.path)

    def mask(self, name: str) -> str | None:
        v = self.get(name)
        if not v:
            return None
        if name == "MT5_PASSWORD":                  # a password is never partially shown
            return "•••"
        return v[:7] + "…" + v[-4:] if len(v) > 14 else "•••"
