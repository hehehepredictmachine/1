"""License lifecycle - the server is the only authority on status, expiry, revocation and device binding (UTC).

CREATED --first activation--> ACTIVE (device bound, expiry = activation + duration) --> EXPIRED (time) / REVOKED (admin).
A different device never overwrites a binding (DEVICE_MISMATCH); only the admin reset clears it, the next activation then
binds the new device (the expiry does not change). Every activation / validation answer carries a fresh signed assertion
with the client's nonce. Plaintext keys are returned only by `create`; device tokens are rotated at each activation.
"""
from __future__ import annotations

import hmac
import secrets
import time

from . import protocol as P
from .security import key_hash, new_token, token_hash
from .signing import Signer
from .store import PUBLIC_COLUMNS, Store

HTTP = {P.INVALID_LICENSE: 403, P.LICENSE_EXPIRED: 403, P.LICENSE_REVOKED: 403, P.DEVICE_MISMATCH: 403, P.RATE_LIMITED: 429,
        P.INVALID_REQUEST: 400, P.UNAUTHORIZED: 401, P.NOT_FOUND: 404}
VALIDATE_EVERY_S = 300


class LicenseError(Exception):
    def __init__(self, code: str, message: str | None = None):
        super().__init__(code)
        self.code = code
        self.message = message or P.ERROR_PL.get(code, code)
        self.http = HTTP.get(code, 400)


def _hwid_tag(h: str | None) -> str | None:
    return h[:8] if h else None                         # audit: a short prefix, never the whole fingerprint hash


class LicenseService:
    def __init__(self, store: Store, signer: Signer, pepper: str, *, clock=time.time):
        self.store, self.signer, self.pepper, self.clock = store, signer, pepper, clock

    # ------------------------------------------------------------------ admin
    def create(self, duration: str, *, actor: str, note: str | None = None, ip: str | None = None) -> dict:
        if duration not in P.DURATIONS:
            raise LicenseError(P.INVALID_REQUEST, "nieznany okres licencji")
        now = self.clock()
        for _ in range(5):                                 # a key-hash collision is practically impossible; retry anyway
            key = P.generate_key()
            lid = "LIC-" + secrets.token_hex(8)
            try:
                with self.store.tx() as c:
                    c.execute("""INSERT INTO licenses(license_id, key_hash, key_hint, duration, status, note, created_at, created_by)
                                 VALUES (?,?,?,?,?,?,?,?)""", (lid, key_hash(self.pepper, key), P.key_hint(key), duration, "CREATED",
                                                                (note or "")[:200] or None, now, actor))
                    self.store.audit(now, actor, "LICENSE_CREATED", license_id=lid, ip=ip, details={"duration": duration}, conn=c)
                break
            except Exception as exc:  # noqa: BLE001 - sqlite3.IntegrityError on the unique hash
                if "UNIQUE" not in str(exc):
                    raise
        else:
            raise LicenseError(P.INVALID_REQUEST, "nie udało się wygenerować unikalnego klucza")
        row = self.get(lid)
        return {**row, "license_key": key}                 # the only time the plaintext key exists outside the admin's screen

    def get(self, license_id: str) -> dict:
        r = self.store.one(f"SELECT {', '.join(PUBLIC_COLUMNS)}, hwid_hash IS NOT NULL AS device_bound FROM licenses WHERE license_id=?",
                           (license_id,))
        if not r:
            raise LicenseError(P.NOT_FOUND, "nie ma takiej licencji")
        return self._public(self._expire_if_due(r))

    def list(self, *, status: str | None = None, duration: str | None = None, q: str | None = None, limit: int = 50, offset: int = 0) -> dict:
        self._expire_all()
        where, args = [], []
        if status:
            where.append("status=?")
            args.append(status)
        if duration:
            where.append("duration=?")
            args.append(duration)
        if q:
            where.append("(license_id LIKE ? OR key_hint LIKE ? OR note LIKE ?)")
            args += [f"%{q}%"] * 3
        w = (" WHERE " + " AND ".join(where)) if where else ""
        total = self.store.one(f"SELECT COUNT(*) AS n FROM licenses{w}", args)["n"]
        rows = self.store.all(f"SELECT {', '.join(PUBLIC_COLUMNS)}, hwid_hash IS NOT NULL AS device_bound FROM licenses{w} "
                              "ORDER BY created_at DESC LIMIT ? OFFSET ?", (*args, max(1, min(limit, 200)), max(0, offset)))
        return {"items": [self._public(r) for r in rows], "total": total, "limit": limit, "offset": offset}

    def stats(self) -> dict:
        self._expire_all()
        rows = self.store.all("SELECT status, COUNT(*) AS n FROM licenses GROUP BY status")
        by = {s: 0 for s in P.STATUSES}
        by.update({r["status"]: r["n"] for r in rows})
        dur = {r["duration"]: r["n"] for r in self.store.all("SELECT duration, COUNT(*) AS n FROM licenses GROUP BY duration")}
        return {"by_status": by, "by_duration": dur, "total": sum(by.values()), "server_time": P.utc_iso(self.clock())}

    def revoke(self, license_id: str, *, actor: str, reason: str | None = None, ip: str | None = None) -> dict:
        now = self.clock()
        with self.store.tx() as c:
            r = c.execute("SELECT status FROM licenses WHERE license_id=?", (license_id,)).fetchone()
            if not r:
                raise LicenseError(P.NOT_FOUND, "nie ma takiej licencji")
            c.execute("UPDATE licenses SET status='REVOKED', revoked_at=?, revoke_reason=?, token_hash=NULL WHERE license_id=?",
                      (now, (reason or "")[:200] or None, license_id))
            self.store.audit(now, actor, "LICENSE_REVOKED", license_id=license_id, ip=ip, details={"previous": r["status"], "reason": reason}, conn=c)
        return self.get(license_id)

    def reset_device(self, license_id: str, *, actor: str, reason: str | None = None, ip: str | None = None) -> dict:
        now = self.clock()
        with self.store.tx() as c:
            r = c.execute("SELECT status, hwid_hash FROM licenses WHERE license_id=?", (license_id,)).fetchone()
            if not r:
                raise LicenseError(P.NOT_FOUND, "nie ma takiej licencji")
            c.execute("UPDATE licenses SET hwid_hash=NULL, token_hash=NULL, bound_at=NULL WHERE license_id=?", (license_id,))
            self.store.audit(now, actor, "DEVICE_RESET", license_id=license_id, ip=ip,
                             details={"previous_device": _hwid_tag(r["hwid_hash"]), "reason": reason}, conn=c)
        return self.get(license_id)

    def audit_log(self, limit: int = 100, license_id: str | None = None) -> list[dict]:
        q, args = "SELECT ts, actor, action, license_id, ok, ip, details FROM audit_log", []
        if license_id:
            q += " WHERE license_id=?"
            args.append(license_id)
        return [{**r, "ts": P.utc_iso(r["ts"])} for r in self.store.all(q + " ORDER BY id DESC LIMIT ?", (*args, max(1, min(limit, 500))))]

    # ------------------------------------------------------------------ client
    def activate(self, raw_key: str, hwid: str, *, nonce: str, client_version: str = "", ip: str | None = None) -> dict:
        self._check_client(hwid, nonce)
        key = P.normalize_key(raw_key)
        now = self.clock()
        if not key:
            self.store.audit(now, "client", "ACTIVATE", ok=False, ip=ip, details={"error": P.INVALID_LICENSE, "why": "format"})
            raise LicenseError(P.INVALID_LICENSE)
        kh = key_hash(self.pepper, key)
        token = new_token()
        err, lid, row, action = None, None, None, None
        with self.store.tx() as c:                         # errors are raised after the commit (expiry update + audit survive)
            r = c.execute("SELECT * FROM licenses WHERE key_hash=?", (kh,)).fetchone()
            if not r:
                err = P.INVALID_LICENSE
            else:
                r = dict(r)
                lid = r["license_id"]
                err = self._state_error(r, now, c)
            if not err:
                if r["status"] == "CREATED":                 # first activation: binds the device and starts the clock
                    n = c.execute("""UPDATE licenses SET status='ACTIVE', activated_at=?, expires_at=?, hwid_hash=?, token_hash=?, bound_at=?,
                                     last_seen_at=?, client_version=? WHERE license_id=? AND status='CREATED'""",
                                  (now, now + P.DURATIONS[r["duration"]], hwid, token_hash(token), now, now, client_version[:32], lid)).rowcount
                    action = "ACTIVATED_FIRST"
                elif r["hwid_hash"] is None:                   # after an admin reset: bind the new device, expiry unchanged
                    n = c.execute("UPDATE licenses SET hwid_hash=?, token_hash=?, bound_at=?, last_seen_at=?, client_version=? "
                                  "WHERE license_id=? AND hwid_hash IS NULL", (hwid, token_hash(token), now, now, client_version[:32], lid)).rowcount
                    action = "ACTIVATED_REBOUND"
                elif hmac.compare_digest(r["hwid_hash"], hwid):  # the same device again: new device token
                    n = c.execute("UPDATE licenses SET token_hash=?, last_seen_at=?, client_version=? WHERE license_id=?",
                                  (token_hash(token), now, client_version[:32], lid)).rowcount
                    action = "ACTIVATED_AGAIN"
                else:
                    n, err = 0, P.DEVICE_MISMATCH
                if not err and n != 1:                       # lost a race with a concurrent activation - the binding stands
                    err = P.DEVICE_MISMATCH
            if not err:
                self.store.audit(now, "client", action, license_id=lid, ip=ip, details={"device": _hwid_tag(hwid), "client": client_version[:32]}, conn=c)
                row = dict(c.execute("SELECT * FROM licenses WHERE license_id=?", (lid,)).fetchone())
        if err:
            self.store.audit(now, "client", "ACTIVATE", license_id=lid, ok=False, ip=ip, details={"error": err, "device": _hwid_tag(hwid)})
            raise LicenseError(err)
        return self._answer(row, nonce, now, token=token)

    def validate(self, license_id: str, hwid: str, token: str, *, nonce: str, client_version: str = "", ip: str | None = None) -> dict:
        self._check_client(hwid, nonce)
        if not isinstance(license_id, str) or not P.LICENSE_ID_RE.match(license_id) or not isinstance(token, str) or not P.TOKEN_RE.match(token):
            raise LicenseError(P.INVALID_REQUEST)
        now = self.clock()
        err, row = None, None
        with self.store.tx() as c:
            r = c.execute("SELECT * FROM licenses WHERE license_id=?", (license_id,)).fetchone()
            if not r:
                err = P.INVALID_LICENSE
            else:
                r = dict(r)
                err = self._state_error(r, now, c)
                if not err and (r["hwid_hash"] is None or not hmac.compare_digest(r["hwid_hash"], hwid)):
                    err = P.DEVICE_MISMATCH
                if not err and (r["token_hash"] is None or not hmac.compare_digest(r["token_hash"], token_hash(token))):
                    err = P.INVALID_LICENSE                   # a token from before a reset / re-activation: activate again
            if not err:
                c.execute("UPDATE licenses SET last_seen_at=?, client_version=? WHERE license_id=?", (now, client_version[:32], license_id))
                row = dict(c.execute("SELECT * FROM licenses WHERE license_id=?", (license_id,)).fetchone())
        if err:
            self.store.audit(now, "client", "VALIDATE", license_id=license_id if r else None, ok=False, ip=ip, details={"error": err})
            raise LicenseError(err)
        return self._answer(row, nonce, now)

    # ------------------------------------------------------------------ internals
    @staticmethod
    def _check_client(hwid, nonce) -> None:
        if not isinstance(hwid, str) or not P.HWID_RE.match(hwid) or not isinstance(nonce, str) or not P.NONCE_RE.match(nonce):
            raise LicenseError(P.INVALID_REQUEST)

    def _state_error(self, r: dict, now: float, c) -> str | None:
        if r["status"] == "REVOKED":
            return P.LICENSE_REVOKED
        if r["status"] == "ACTIVE" and r["expires_at"] is not None and r["expires_at"] <= now:
            c.execute("UPDATE licenses SET status='EXPIRED' WHERE license_id=? AND status='ACTIVE'", (r["license_id"],))
            self.store.audit(now, "system", "LICENSE_EXPIRED", license_id=r["license_id"], conn=c)
            r["status"] = "EXPIRED"
        if r["status"] == "EXPIRED":
            return P.LICENSE_EXPIRED
        return None

    def _answer(self, row: dict, nonce: str, now: float, token: str | None = None) -> dict:
        payload = {"v": P.PROTOCOL_VERSION, "typ": P.ASSERTION_TYPE, "lid": row["license_id"], "hwid": row["hwid_hash"], "st": "ACTIVE",
                   "dur": row["duration"], "act": P.utc_iso(row["activated_at"]), "exp": P.utc_iso(row["expires_at"]), "iat": P.utc_iso(now),
                   "nonce": nonce}
        out = {"status": "ACTIVE", "license_id": row["license_id"], "duration": row["duration"], "activated_at": payload["act"],
               "expires_at": payload["exp"], "server_time": payload["iat"], "validate_every_seconds": VALIDATE_EVERY_S,
               "key_hint": row["key_hint"], "assertion": self.signer.assertion(payload)}
        if token:
            out["token"] = token
        return out

    def _expire_if_due(self, r: dict) -> dict:
        if r["status"] == "ACTIVE" and r.get("expires_at") is not None and r["expires_at"] <= self.clock():
            self._expire_all()
            r = {**r, "status": "EXPIRED"}
        return r

    def _expire_all(self) -> None:
        now = self.clock()
        due = self.store.all("SELECT license_id FROM licenses WHERE status='ACTIVE' AND expires_at <= ?", (now,))
        if not due:
            return
        with self.store.tx() as c:
            for d in due:
                if c.execute("UPDATE licenses SET status='EXPIRED' WHERE license_id=? AND status='ACTIVE'", (d["license_id"],)).rowcount:
                    self.store.audit(now, "system", "LICENSE_EXPIRED", license_id=d["license_id"], conn=c)

    @staticmethod
    def _public(r: dict) -> dict:
        out = {k: r.get(k) for k in PUBLIC_COLUMNS}
        for k in ("created_at", "activated_at", "expires_at", "bound_at", "last_seen_at", "revoked_at"):
            out[k] = P.utc_iso(out[k]) if out.get(k) is not None else None
        out["device_bound"] = bool(r.get("device_bound"))
        out["duration_pl"] = P.DURATION_PL.get(out["duration"])
        return out
