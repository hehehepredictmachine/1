"""Device identity of this installation: random install_id + Ed25519 key pair.

The private key is stored by SecretStore (Windows DPAPI, current-user scope - readable only by the same Windows user on
this machine). The public key is registered at activation; every device request proves possession by signing a
single-use server nonce. A MAC/IP/host name/device_id file alone is never treated as identity.
Non-secret state (device_id, activation_id, owner user_id, issuer, pinned lease public key) lives in data/license/state.json;
editing it cannot grant anything because the server and the signed lease decide.
"""
from __future__ import annotations

import json
import os
import socket
import uuid
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

SECRET_NAME = "MQ_DEVICE_ED25519"


class DeviceIdentity:
    def __init__(self, secrets, directory: Path):
        self.secrets = secrets
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "state.json"

    # ------------------------------------------------------------ non-secret state
    def state(self) -> dict:
        try:
            m = self.path.stat().st_mtime_ns
            if getattr(self, "_cache", None) and self._cache[0] == m:
                return dict(self._cache[1])
            st = json.loads(self.path.read_text(encoding="utf-8"))
            self._cache = (m, st)
            return dict(st)
        except (OSError, ValueError):
            return {}

    def save(self, **kw) -> dict:
        st = self.state()
        st.update(kw)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, indent=1), encoding="utf-8")
        tmp.replace(self.path)
        self._cache = None
        return st

    def install_id(self) -> str:
        st = self.state()
        if not st.get("install_id"):
            st = self.save(install_id=str(uuid.uuid4()))
        return st["install_id"]

    # ------------------------------------------------------------ key pair
    def private_key(self) -> Ed25519PrivateKey:
        pem = self.secrets.get(SECRET_NAME)
        if pem:
            k = serialization.load_pem_private_key(pem.encode(), password=None)
            if isinstance(k, Ed25519PrivateKey):
                return k
        k = Ed25519PrivateKey.generate()
        self.secrets.set(SECRET_NAME, k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                      serialization.NoEncryption()).decode())
        return k

    def public_pem(self) -> str:
        return self.private_key().public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode().strip()

    def protection(self) -> str:
        return "WINDOWS_DPAPI" if getattr(self.secrets, "windows", False) else "LOCAL_FILE_CHMOD_600 (tylko development poza Windows)"

    @staticmethod
    def default_name() -> str:
        return (os.environ.get("COMPUTERNAME") or socket.gethostname() or "PC")[:60]
