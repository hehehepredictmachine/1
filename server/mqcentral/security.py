"""Cryptographic primitives - only vetted libraries (argon2-cffi, cryptography, PyJWT, pyotp); nothing home-made."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
import uuid
from pathlib import Path

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

# Argon2id - OWASP minimum is m=19 MiB, t=2, p=1; we use 64 MiB / t=3 / p=4 (tune with `python -m mqcentral hash-bench`).
PH = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, salt_len=16)
_DUMMY = PH.hash("not-a-real-password-dummy-for-timing")


def new_id() -> str:
    return str(uuid.uuid4())


def hash_password(pw: str) -> str:
    return PH.hash(pw)


def verify_password(stored: str | None, pw: str) -> bool:
    """Constant-ish work also for unknown accounts (verifies against a dummy hash)."""
    try:
        return PH.verify(stored or _DUMMY, pw) and stored is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(stored: str) -> bool:
    try:
        return PH.check_needs_rehash(stored)
    except InvalidHashError:
        return True


def password_problems(pw: str, email: str = "") -> list[str]:
    out = []
    if len(pw) < 12:
        out.append("Hasło musi mieć co najmniej 12 znaków")
    if len(pw) > 256:
        out.append("Hasło jest za długie (max 256)")
    if email and email.split("@")[0].lower() in pw.lower() and len(email.split("@")[0]) >= 4:
        out.append("Hasło nie może zawierać nazwy z adresu e-mail")
    return out


def token() -> str:
    """256-bit random token (URL-safe)."""
    return secrets.token_urlsafe(32)


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def consteq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


# ----------------------------------------------------------------------------- license keys
_ALPH = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"         # 32 symbols, no 0/O/1/I


def license_key() -> str:
    """MQL1-xxxxx-... : 256 bits from `secrets` (52 base-32 symbols = 260 bits of capacity), grouped by 5 for reading."""
    n = int.from_bytes(secrets.token_bytes(32), "big")
    chars = []
    for _ in range(52):
        n, r = divmod(n, 32)
        chars.append(_ALPH[r])
    body = "".join(chars)
    return "MQL1-" + "-".join(body[i:i + 5] for i in range(0, len(body), 5))


def normalize_key(k: str) -> str:
    k = "".join(ch for ch in k.strip().upper() if ch.isalnum())
    if k.startswith("MQL1"):
        k = k[4:]
    return "MQL1-" + "-".join(k[i:i + 5] for i in range(0, len(k), 5))


def key_hash(k: str) -> str:
    return sha256(normalize_key(k))


def key_hint(k: str) -> str:
    n = normalize_key(k)
    return f"MQL1-…{n.replace('-', '')[-4:]}"


# ----------------------------------------------------------------------------- TOTP + recovery codes
def fernet(data_key: str) -> Fernet:
    return Fernet(data_key.encode())


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_ok(secret: str, code: str, now: float | None = None) -> bool:
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    return len(code) == 6 and pyotp.TOTP(secret).verify(code, for_time=now or time.time(), valid_window=1)


def recovery_codes(n: int = 10) -> list[str]:
    return ["-".join(secrets.token_hex(3) for _ in range(3)) for _ in range(n)]


# ----------------------------------------------------------------------------- Ed25519 keys (lease signing, devices)
def gen_signing_key(path: Path) -> str:
    k = Ed25519PrivateKey.generate()
    pem = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pem)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return public_pem(k.public_key())


def load_signing_key(path: str) -> Ed25519PrivateKey:
    k = serialization.load_pem_private_key(Path(path).read_bytes(), password=None)
    if not isinstance(k, Ed25519PrivateKey):
        raise ValueError("signing key must be Ed25519")
    return k


def public_pem(pub: Ed25519PublicKey) -> str:
    return pub.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()


def kid_of(pem: str) -> str:
    return sha256(pem)[:16]


def load_public(pem: str) -> Ed25519PublicKey:
    k = serialization.load_pem_public_key(pem.encode())
    if not isinstance(k, Ed25519PublicKey):
        raise ValueError("ED25519_PUBLIC_KEY_REQUIRED")
    return k


def device_message(method: str, path: str, nonce: str, body: bytes) -> bytes:
    return f"MQDEV1\n{method.upper()}\n{path}\n{nonce}\n{hashlib.sha256(body).hexdigest()}".encode()


def verify_device_sig(pub_pem: str, msg: bytes, sig_b64: str) -> bool:
    try:
        load_public(pub_pem).verify(base64.b64decode(sig_b64), msg)
        return True
    except Exception:
        return False


def sign_jwt(key: Ed25519PrivateKey, claims: dict, kid: str) -> str:
    return jwt.encode(claims, key, algorithm="EdDSA", headers={"kid": kid, "typ": "JWT"})
