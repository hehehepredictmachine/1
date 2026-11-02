"""Admin authentication, hashing helpers and rate limiting.

* Admin password: scrypt (hashlib, N=2^15, r=8, p=1, 16-byte salt) stored as `scrypt$N$r$p$salt$hash`; compared in constant
  time. The password itself is never stored or logged.
* Admin sessions: random 256-bit bearer tokens; only SHA-256 of the token is stored; limited lifetime.
* License keys: HMAC-SHA256(server pepper, canonical key). Device tokens: SHA-256.
* Rate limits: sliding window per (bucket, client IP), in memory (one API process - see README for several workers).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import time
from collections import defaultdict, deque

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 15, 8, 1


def hash_password(password: str) -> str:
    if not isinstance(password, str) or len(password) < 12:
        raise ValueError("hasło administratora musi mieć co najmniej 12 znaków")
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, maxmem=64 * 1024 * 1024, dklen=32)
    b = lambda x: base64.b64encode(x).decode("ascii")  # noqa: E731
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${b(salt)}${b(h)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        kind, n, r, p, salt, want = stored.split("$")
        if kind != "scrypt":
            return False
        got = hashlib.scrypt(password.encode("utf-8"), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                             maxmem=64 * 1024 * 1024, dklen=32)
        return hmac.compare_digest(got, base64.b64decode(want))
    except (ValueError, TypeError, AttributeError):
        return False


def key_hash(pepper: str, canonical_key: str) -> str:
    return hmac.new(pepper.encode("utf-8"), canonical_key.encode("utf-8"), hashlib.sha256).hexdigest()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


class RateLimiter:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.hits: dict[tuple[str, str], deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, bucket: str, ip: str, limit: int, window: float = 60.0) -> bool:
        now = self.clock()
        with self.lock:
            q = self.hits[(bucket, ip)]
            while q and q[0] <= now - window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            if len(self.hits) > 50_000:                      # bounded memory under a flood of distinct IPs
                for k in [k for k, v in self.hits.items() if not v or v[-1] <= now - window][:10_000]:
                    self.hits.pop(k, None)
            return True
