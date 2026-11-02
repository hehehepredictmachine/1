"""Ed25519 signing key of the License API. The PRIVATE key is a server-only file (PEM, PKCS8, chmod 600); clients get the
32-byte PUBLIC key (base64) embedded in the CLIENT build and verify every assertion with it."""
from __future__ import annotations

import base64
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from . import protocol as P


class Signer:
    def __init__(self, private_key: Ed25519PrivateKey):
        self._key = private_key
        self.public_raw = private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.kid = P.key_id(self.public_raw)
        self.public_b64 = base64.b64encode(self.public_raw).decode("ascii")

    def sign(self, data: bytes) -> bytes:
        return self._key.sign(data)

    def assertion(self, payload: dict) -> str:
        return P.encode_assertion({**payload, "kid": self.kid}, self.sign)

    @classmethod
    def load(cls, path: Path) -> "Signer":
        key = serialization.load_pem_private_key(Path(path).read_bytes(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("klucz podpisu musi być kluczem Ed25519")
        return cls(key)

    @classmethod
    def generate(cls) -> "Signer":
        return cls(Ed25519PrivateKey.generate())

    def write_private(self, path: Path) -> None:
        path = Path(path)
        if path.exists():
            raise FileExistsError(f"{path} już istnieje – nie nadpisuję klucza podpisu (klienci mają w paczce jego klucz publiczny)")
        path.parent.mkdir(parents=True, exist_ok=True)
        pem = self._key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(pem)
