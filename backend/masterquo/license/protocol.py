"""PepeMarketWizard License System v1 - shared protocol (server and client).

This file exists twice, byte-for-byte identical (a test checks it):
  license_server/pmw_license/protocol.py      (License API)
  backend/masterquo/license/protocol.py       (bot: CLIENT / OWNER editions)
It contains only public, non-secret definitions: durations, statuses, error codes, the license key format and the
signed-assertion format. Verification needs the server's PUBLIC Ed25519 key only; the private key never leaves the server.

Assertion (compact, JWS-like but fixed algorithm, no header to negotiate):
    token = base64url(payload_json) + "." + base64url(ed25519_signature)
    signed bytes = DOMAIN + payload_json   (payload_json = UTF-8, sorted keys, no spaces)
Payload fields: v, typ, kid, lid (license id), hwid (device fingerprint hash), st (status), dur, act / exp (activation /
expiry, UTC), iat (server time, UTC), nonce (the client's fresh challenge - proves the answer is new, independent of the
local clock).
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
from datetime import datetime, timezone

PROTOCOL_VERSION = 1
DOMAIN = b"PMW-LIC-v1\n"
ASSERTION_TYPE = "PMW-LIC-ASSERT"

DURATIONS = {"24h": 86_400, "72h": 259_200, "7d": 604_800, "31d": 2_678_400}
DURATION_PL = {"24h": "24 godziny", "72h": "72 godziny", "7d": "7 dni", "31d": "31 dni"}
STATUSES = ("CREATED", "ACTIVE", "EXPIRED", "REVOKED")

# machine-readable error codes (same on both sides)
INVALID_LICENSE = "INVALID_LICENSE"
LICENSE_EXPIRED = "LICENSE_EXPIRED"
LICENSE_REVOKED = "LICENSE_REVOKED"
DEVICE_MISMATCH = "DEVICE_MISMATCH"
RATE_LIMITED = "RATE_LIMITED"
INVALID_REQUEST = "INVALID_REQUEST"
UNAUTHORIZED = "UNAUTHORIZED"
NOT_FOUND = "NOT_FOUND"
ERROR_PL = {
    INVALID_LICENSE: "nieprawidłowy klucz licencji",
    LICENSE_EXPIRED: "licencja wygasła",
    LICENSE_REVOKED: "licencja została cofnięta przez administratora",
    DEVICE_MISMATCH: "licencja jest przypisana do innego urządzenia",
    RATE_LIMITED: "zbyt wiele prób – odczekaj chwilę",
    INVALID_REQUEST: "nieprawidłowe zapytanie",
    UNAUTHORIZED: "brak uprawnień administratora",
    NOT_FOUND: "nie znaleziono",
}

# ------------------------------------------------------------------------------------------------ license key
# PMW-XXXXX-XXXXX-XXXXX-XXXXX: 20 characters of Crockford base32 = 100 random bits (secrets module)
KEY_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
KEY_GROUPS, KEY_GROUP_LEN = 4, 5
_KEY_RE = re.compile(r"^PMW-[0-9A-HJKMNP-TV-Z]{5}(-[0-9A-HJKMNP-TV-Z]{5}){3}$")


def generate_key() -> str:
    body = "".join(secrets.choice(KEY_ALPHABET) for _ in range(KEY_GROUPS * KEY_GROUP_LEN))
    return "PMW-" + "-".join(body[i:i + KEY_GROUP_LEN] for i in range(0, len(body), KEY_GROUP_LEN))


def normalize_key(raw: str) -> str | None:
    """User input -> canonical key, or None. Case, spaces and the usual look-alikes (O->0, I/L->1) are tolerated."""
    if not isinstance(raw, str) or len(raw) > 64:
        return None
    s = re.sub(r"[\s_]", "", raw.strip().upper())
    if s.startswith("PMW"):
        s = s[3:]
    s = s.replace("-", "").translate(str.maketrans({"O": "0", "I": "1", "L": "1"}))
    if len(s) != KEY_GROUPS * KEY_GROUP_LEN or any(c not in KEY_ALPHABET for c in s):
        return None
    key = "PMW-" + "-".join(s[i:i + KEY_GROUP_LEN] for i in range(0, len(s), KEY_GROUP_LEN))
    return key if _KEY_RE.match(key) else None


def key_hint(key: str) -> str:
    """Non-secret hint for lists and logs: the last 4 characters only."""
    return "PMW-…-" + key[-4:]


# ------------------------------------------------------------------------------------------------ formats
HWID_RE = re.compile(r"^[0-9a-f]{64}$")
NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
LICENSE_ID_RE = re.compile(r"^LIC-[0-9a-f]{16}$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")


def new_nonce() -> str:
    return secrets.token_urlsafe(24)


def utc_iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(s: str) -> float:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def b64u_dec(s: str) -> bytes:
    if not isinstance(s, str) or not re.fullmatch(r"[A-Za-z0-9_-]*", s):
        raise ValueError("bad base64url")
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def key_id(public_key_raw: bytes) -> str:
    return hashlib.sha256(public_key_raw).hexdigest()[:16]


def canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def encode_assertion(payload: dict, sign) -> str:
    """sign(bytes) -> 64-byte Ed25519 signature (server side, private key)."""
    body = canonical(payload)
    return b64u(body) + "." + b64u(sign(DOMAIN + body))


class AssertionError_(Exception):
    """A signed assertion that must not be trusted (bad format, bad signature, wrong license / device / nonce)."""


def verify_assertion(token: str, public_key_raw: bytes, *, license_id: str | None = None, hwid: str | None = None,
                     nonce: str | None = None) -> dict:
    """Verify the signature with the pinned public key and the binding fields. Returns the payload; raises AssertionError_."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    if not isinstance(token, str) or token.count(".") != 1 or len(token) > 4096:
        raise AssertionError_("FORMAT")
    p64, s64 = token.split(".")
    try:
        body, sig = b64u_dec(p64), b64u_dec(s64)
    except ValueError as exc:
        raise AssertionError_("FORMAT") from exc
    if len(sig) != 64:
        raise AssertionError_("SIGNATURE")
    try:
        Ed25519PublicKey.from_public_bytes(public_key_raw).verify(sig, DOMAIN + body)
    except (InvalidSignature, ValueError) as exc:
        raise AssertionError_("SIGNATURE") from exc
    try:
        payload = json.loads(body.decode("utf-8"))
    except ValueError as exc:
        raise AssertionError_("FORMAT") from exc
    if not isinstance(payload, dict) or payload.get("v") != PROTOCOL_VERSION or payload.get("typ") != ASSERTION_TYPE:
        raise AssertionError_("TYPE")
    if payload.get("kid") != key_id(public_key_raw):
        raise AssertionError_("KEY_ID")
    if license_id is not None and payload.get("lid") != license_id:
        raise AssertionError_("LICENSE_ID")
    if hwid is not None and payload.get("hwid") != hwid:
        raise AssertionError_("DEVICE")
    if nonce is not None and payload.get("nonce") != nonce:
        raise AssertionError_("NONCE")
    for k in ("act", "exp", "iat"):
        try:
            parse_utc(payload.get(k) or "")
        except (TypeError, ValueError) as exc:
            raise AssertionError_("TIME") from exc
    return payload
