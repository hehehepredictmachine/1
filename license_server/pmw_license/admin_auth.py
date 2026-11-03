"""Administrator authentication by OWNER device key (PMW-ADMIN-v1) - no login screen, no password in daily use.

* Trust: a device PUBLIC key is added only from the server's shell (`python -m pmw_license admin-keys add ...`), never through
  the public API. The private key stays on the OWNER computer (DPAPI on Windows).
* Request check: known, non-revoked kid -> |server time - timestamp| <= 120 s -> Ed25519 signature over method, path + query,
  SHA-256 of the exact body bytes, timestamp, nonce and kid -> nonce not used before (stored in SQLite with the request time;
  PRIMARY KEY (kid, nonce) makes two concurrent replays fail atomically, and the store survives a restart).
* Separation: admin keys never sign licenses; the license-signing key never authenticates an administrator.
"""
from __future__ import annotations

import base64
import sqlite3

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from . import protocol as P
from .service import LicenseError

NONCE_TTL_S = 4 * P.ADMIN_MAX_SKEW_S


def parse_public_key(b64: str) -> bytes:
    try:
        raw = base64.b64decode((b64 or "").strip(), validate=True)
    except (ValueError, TypeError):
        raise ValueError("klucz publiczny administratora: nieprawidłowy base64") from None
    if len(raw) != 32:
        raise ValueError("klucz publiczny administratora: oczekiwane 32 bajty Ed25519")
    Ed25519PublicKey.from_public_bytes(raw)
    return raw


def add_key(store, public_b64: str, label: str | None, actor: str, now: float) -> dict:
    raw = parse_public_key(public_b64)
    kid = P.admin_key_id(raw)
    with store.tx() as c:
        row = c.execute("SELECT kid, revoked_at FROM admin_keys WHERE kid=?", (kid,)).fetchone()
        if row and row["revoked_at"] is None:
            return {"kid": kid, "status": "ALREADY_TRUSTED"}
        if row:
            raise ValueError("ten klucz został wcześniej odwołany – wygeneruj nowy klucz urządzenia (rotacja)")
        c.execute("INSERT INTO admin_keys(kid, public_key, label, created_at, created_by) VALUES (?,?,?,?,?)",
                  (kid, base64.b64encode(raw).decode("ascii"), (label or "")[:80] or None, now, actor[:64]))
        store.audit(now, actor, "ADMIN_KEY_ADDED", ok=True, details={"kid": kid, "label": (label or "")[:80]}, conn=c)
    return {"kid": kid, "status": "TRUSTED"}


def revoke_key(store, kid: str, actor: str, now: float, reason: str | None = None) -> dict:
    with store.tx() as c:
        row = c.execute("SELECT revoked_at FROM admin_keys WHERE kid=?", (kid,)).fetchone()
        if not row:
            raise LicenseError(P.NOT_FOUND, "nieznany klucz administratora")
        if row["revoked_at"] is None:
            c.execute("UPDATE admin_keys SET revoked_at=?, revoke_reason=? WHERE kid=?", (now, (reason or "")[:200] or None, kid))
            c.execute("DELETE FROM admin_nonces WHERE kid=?", (kid,))
            store.audit(now, actor, "ADMIN_KEY_REVOKED", ok=True, details={"kid": kid}, conn=c)
    return {"kid": kid, "status": "REVOKED"}


def list_keys(store) -> list[dict]:
    return store.all("SELECT kid, label, created_at, created_by, revoked_at, revoke_reason, last_used_at FROM admin_keys ORDER BY created_at")


def verify(store, headers, method: str, path_qs: str, body: bytes, now: float) -> dict:
    """Returns {kid, label} of the authenticated device or raises LicenseError(UNAUTHORIZED, reason)."""
    kid, ts_s, nonce, sig = (headers.get(h) for h in P.ADMIN_HEADERS)
    if not (kid and ts_s and nonce and sig):
        raise LicenseError(P.UNAUTHORIZED, "brak podpisu urządzenia administratora")
    if not P.ADMIN_KID_RE.match(kid) or not P.ADMIN_NONCE_RE.match(nonce) or not ts_s.isdigit() or len(sig) > 200:
        raise LicenseError(P.UNAUTHORIZED, "nieprawidłowy format podpisu administratora")
    row = store.one("SELECT public_key, label, revoked_at FROM admin_keys WHERE kid=?", (kid,))
    if not row or row["revoked_at"] is not None:
        raise LicenseError(P.UNAUTHORIZED, "klucz urządzenia nie jest zaufany na tym serwerze (sparuj urządzenie albo klucz odwołano)")
    ts = int(ts_s)
    if abs(now - ts) > P.ADMIN_MAX_SKEW_S:
        raise LicenseError(P.UNAUTHORIZED, "czas żądania administratora poza dozwolonym oknem – sprawdź zegar komputera (UTC)")
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(row["public_key"])).verify(
            P.b64u_dec(sig), P.admin_canonical(method, path_qs, body, ts, nonce, kid))
    except (InvalidSignature, ValueError):
        raise LicenseError(P.UNAUTHORIZED, "nieprawidłowy podpis administratora") from None
    try:
        with store.tx() as c:
            c.execute("DELETE FROM admin_nonces WHERE ts < ?", (now - NONCE_TTL_S,))
            c.execute("INSERT INTO admin_nonces(kid, nonce, ts) VALUES (?,?,?)", (kid, nonce, now))
            c.execute("UPDATE admin_keys SET last_used_at=? WHERE kid=?", (now, kid))
    except sqlite3.IntegrityError:
        raise LicenseError(P.UNAUTHORIZED, "powtórzone żądanie administratora (nonce już użyty)") from None
    return {"kid": kid, "label": row["label"]}
