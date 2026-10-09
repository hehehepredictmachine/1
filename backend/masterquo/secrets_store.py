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

ALLOWED = ("MQ_DEVICE_ED25519", "ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN", "FRED_API_KEY")


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
        try:
            if self.windows:
                return _dpapi(base64.b64decode(raw), protect=False).decode("utf-8")
            return str(raw)
        except (OSError, ValueError):
            return None

    def source(self, name: str) -> str:
        if os.environ.get(name):
            return "ENVIRONMENT"
        return "LOCAL_STORE" if self._read().get(name) else "MISSING"

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
            tmp.write_text(json.dumps(data), encoding="utf-8")
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            tmp.replace(self.path)

    def mask(self, name: str) -> str | None:
        v = self.get(name)
        if not v:
            return None
        return v[:7] + "…" + v[-4:] if len(v) > 14 else "•••"
