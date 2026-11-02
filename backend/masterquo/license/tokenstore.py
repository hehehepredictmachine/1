"""Local activation data of the CLIENT edition: license id, device token (from the server), key hint and the last signed
assertion. The license key itself is NOT stored. Windows: DPAPI (current user) in data/license.dpapi; other OS: JSON with
0600 permissions (development). The status is never read from this file - every start validates online."""
from __future__ import annotations

import base64
import json
import os
import sys
import threading
from pathlib import Path

from .. import paths


class TokenStore:
    def __init__(self, directory: Path | None = None):
        d = directory or paths.data_dir()
        self.windows = sys.platform == "win32"
        self.path = Path(d) / ("license.dpapi" if self.windows else "license.local.json")
        self._lock = threading.Lock()

    def load(self) -> dict | None:
        with self._lock:
            if not self.path.exists():
                return None
            try:
                raw = self.path.read_bytes()
                if self.windows:
                    from ..secrets_store import _dpapi
                    raw = _dpapi(base64.b64decode(raw), protect=False)
                d = json.loads(raw.decode("utf-8"))
                return d if isinstance(d, dict) and d.get("license_id") and d.get("token") else None
            except Exception:  # noqa: BLE001 - unreadable / copied from another user -> activate again
                return None

    def save(self, data: dict) -> None:
        raw = json.dumps({k: data.get(k) for k in ("license_id", "token", "key_hint", "kid", "api", "assertion")}).encode("utf-8")
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.windows:
                from ..secrets_store import _dpapi
                raw = base64.b64encode(_dpapi(raw, protect=True))
            tmp = self.path.with_suffix(".tmp")
            fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(raw)
            os.replace(tmp, self.path)

    def clear(self) -> None:
        with self._lock:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
