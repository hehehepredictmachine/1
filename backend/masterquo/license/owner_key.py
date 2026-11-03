"""OWNER device key (PMW-ADMIN-v1): the Ed25519 key with which this OWNER installation signs License API admin requests - no login
screen, no password in daily use. Created on first use. The private key is stored only on this computer:
Windows - DPAPI of the current user (data/license_owner_key.dpapi; useless on another account or computer);
other systems (development / tests) - JSON with 0600 permissions (license_owner_key.local.json).
The server trusts the PUBLIC key only after the owner adds it from the server's shell (`python -m pmw_license admin-keys add`).
Rotation: a pending key is created, paired the same way, verified, then becomes the active key (the old one is revoked).
This module is OWNER-only: the CLIENT package does not contain it (tools/stamp_client_edition.py drops it).
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import socket
import sys
import threading
import time
from pathlib import Path

from .. import paths
from . import protocol as P


def _new_private() -> bytes:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    return Ed25519PrivateKey.generate().private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                                      serialization.NoEncryption())


def _public(priv: bytes) -> bytes:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    return Ed25519PrivateKey.from_private_bytes(priv).public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


class DeviceKey:
    def __init__(self, priv: bytes, created_at: float):
        self.priv, self.created_at = priv, created_at
        self.public_raw = _public(priv)
        self.public_b64 = base64.b64encode(self.public_raw).decode("ascii")
        self.kid = P.admin_key_id(self.public_raw)

    def sign_headers(self, method: str, path_qs: str, body: bytes | None, ts: int) -> dict:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        nonce = secrets.token_urlsafe(24)
        sig = Ed25519PrivateKey.from_private_bytes(self.priv).sign(P.admin_canonical(method, path_qs, body or b"", ts, nonce, self.kid))
        return dict(zip(P.ADMIN_HEADERS, (self.kid, str(int(ts)), nonce, P.b64u(sig))))

    def public(self) -> dict:
        return {"kid": self.kid, "public_key": self.public_b64, "created_at": P.utc_iso(self.created_at)}


class OwnerKeyStore:
    def __init__(self, directory: Path | None = None):
        d = Path(directory or paths.data_dir())
        self.windows = sys.platform == "win32"
        self.path = d / ("license_owner_key.dpapi" if self.windows else "license_owner_key.local.json")
        self._lock = threading.Lock()

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        raw = self.path.read_bytes()
        if self.windows:
            from ..secrets_store import _dpapi
            raw = _dpapi(base64.b64decode(raw), protect=False)
        d = json.loads(raw.decode("utf-8"))
        return d if isinstance(d, dict) else {}

    def _write(self, d: dict) -> None:
        raw = json.dumps(d).encode("utf-8")
        if self.windows:
            from ..secrets_store import _dpapi
            raw = base64.b64encode(_dpapi(raw, protect=True))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
        os.replace(tmp, self.path)

    @staticmethod
    def _key(entry: dict | None) -> DeviceKey | None:
        if not entry:
            return None
        return DeviceKey(base64.b64decode(entry["private_key"]), float(entry.get("created_at") or 0))

    def active(self, create: bool = True) -> DeviceKey | None:
        with self._lock:
            d = self._read()
            if not d.get("active") and create:
                d["active"] = {"private_key": base64.b64encode(_new_private()).decode("ascii"), "created_at": time.time()}
                self._write(d)
            return self._key(d.get("active"))

    def pending(self) -> DeviceKey | None:
        with self._lock:
            return self._key(self._read().get("pending"))

    def begin_rotation(self) -> DeviceKey:
        with self._lock:
            d = self._read()
            if not d.get("pending"):
                d["pending"] = {"private_key": base64.b64encode(_new_private()).decode("ascii"), "created_at": time.time()}
                self._write(d)
            return self._key(d["pending"])

    def commit_rotation(self) -> tuple[DeviceKey, DeviceKey | None]:
        with self._lock:
            d = self._read()
            if not d.get("pending"):
                raise ValueError("brak oczekującego klucza")
            old = d.get("active")
            d["previous"], d["active"] = old, d.pop("pending")
            self._write(d)
            return self._key(d["active"]), self._key(old)

    def cancel_rotation(self) -> None:
        with self._lock:
            d = self._read()
            if d.pop("pending", None) is not None:
                self._write(d)


def default_label() -> str:
    try:
        host = socket.gethostname()[:40]
    except OSError:
        host = "PC"
    return f"OWNER {host}"
