"""Business logic of the central server. Every decision about rights is taken HERE with the server clock.

Deny by default: every public method checks the caller identity it receives (user from a server-side session or a
device proven by an Ed25519 signature); user_id is never taken from the request body.
"""
from __future__ import annotations

import json
import logging

from . import mail as mailtpl
from . import security as sec
from . import stats as st
from .ratelimit import LIMITS, RateLimiter

log = logging.getLogger("mqcentral")
SCOPES = ["analysis", "setups", "ml_train", "agent", "trade_open", "telemetry"]


class Denied(Exception):
    def __init__(self, code: str, status: int = 403, detail: dict | None = None):
        super().__init__(code)
        self.code, self.status, self.detail = code, status, detail or {}


def J(o) -> str:
    return json.dumps(o, default=str, sort_keys=True)


class Central:
    def __init__(self, settings, db, clock, mailer=None, limiter: RateLimiter | None = None):
        self.s, self.db, self.clock = settings, db, clock
        self.mail = mailer or mailtpl.Mailer(settings, db, clock)
        self.rl = limiter or RateLimiter()
        self._key = sec.load_signing_key(settings.signing_key_file)
        self.public_pem = sec.public_pem(self._key.public_key())
        self.kid = sec.kid_of(self.public_pem)
        self.fernet = sec.fernet(settings.data_key)

    # ================================================================= helpers
    def now(self) -> int:
        return self.clock.now()

    def limit(self, kind: str, key: str) -> None:
        n, w = LIMITS[kind]
        if not self.rl.hit(f"{kind}:{key}", n, w):
            raise Denied("RATE_LIMITED", 429)

    def audit(self, t, *, actor: dict | None, action: str, target_user: str | None = None, ttype: str | None = None, tid: str | None = None,
              before=None, after=None, ip: str | None = None) -> None:
        (t.x if t else self.db.x)("""INSERT INTO audit_events(id, at, actor_user_id, actor_role, action, target_user_id, target_type, target_id,
                                     before_json, after_json, ip) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                                  (sec.new_id(), self.now(), (actor or {}).get("id"), (actor or {}).get("role"), action, target_user, ttype, tid,
                                   None if before is None else J(before), None if after is None else J(after), ip))

    def _link(self, path: str, tok: str) -> str:
        return f"{self.s.issuer}{path}#token={tok}"          # fragment: the token is not sent in request lines / proxy logs

    def _new_user_token(self, t, user_id: str, purpose: str, ttl: int) -> str:
        tok = sec.token()
        t.x("UPDATE user_tokens SET used_at=? WHERE user_id=? AND purpose=? AND used_at IS NULL", (self.now(), user_id, purpose))
        t.x("INSERT INTO user_tokens(token_hash, user_id, purpose, created_at, expires_at) VALUES (?,?,?,?,?)",
            (sec.sha256(tok), user_id, purpose, self.now(), self.now() + ttl))
        return tok

    def _use_token(self, t, tok: str, purposes: tuple[str, ...]) -> dict:
        r = t.one("SELECT * FROM user_tokens WHERE token_hash=? FOR UPDATE", (sec.sha256(tok or ""),))
        if not r or r["purpose"] not in purposes or r["used_at"] is not None or self.now() >= r["expires_at"]:
            raise Denied("TOKEN_INVALID_OR_EXPIRED", 400)
        t.x("UPDATE user_tokens SET used_at=? WHERE token_hash=?", (self.now(), r["token_hash"]))
        return r

    @staticmethod
    def public_user(u: dict) -> dict:
        return {k: u.get(k) for k in ("id", "email", "display_name", "status", "role", "created_at", "email_verified_at", "totp_enabled")}

    # ================================================================= registration / verification
    def register(self, email: str, password: str, display_name: str | None, ip: str) -> None:
        """Always the same answer (no account enumeration). Never creates a license."""
        email = (email or "").strip().lower()
        self.limit("register_ip", ip)
        if "@" not in email or len(email) > 254:
            raise Denied("EMAIL_INVALID", 400)
        probs = sec.password_problems(password, email)
        if probs:
            raise Denied("PASSWORD_WEAK", 400, {"problems": probs})
        with self.db.tx() as t:
            ex = t.one("SELECT * FROM users WHERE email=?", (email,))
            if ex:
                subj, body = mailtpl.exists_mail()
                to_send = (email, subj, body)
            else:
                uid = sec.new_id()
                t.x("""INSERT INTO users(id, email, display_name, password_hash, status, role, created_at, password_changed_at)
                       VALUES (?,?,?,?, 'PENDING_VERIFICATION', 'USER', ?, ?)""",
                    (uid, email, (display_name or "")[:80] or None, sec.hash_password(password), self.now(), self.now()))
                tok = self._new_user_token(t, uid, "VERIFY_EMAIL", 24 * 3600)
                self.audit(t, actor=None, action="USER_REGISTERED", target_user=uid, ttype="user", tid=uid, after={"status": "PENDING_VERIFICATION"}, ip=ip)
                subj, body = mailtpl.verify_mail(self._link("/account/verify", tok))
                to_send = (email, subj, body)
        self.mail.send(*to_send)

    def verify_email(self, tok: str) -> None:
        with self.db.tx() as t:
            r = self._use_token(t, tok, ("VERIFY_EMAIL",))
            u = t.one("SELECT * FROM users WHERE id=? FOR UPDATE", (r["user_id"],))
            if u["status"] == "PENDING_VERIFICATION":
                t.x("UPDATE users SET status='ACTIVE', email_verified_at=? WHERE id=?", (self.now(), u["id"]))
            self.audit(t, actor=None, action="EMAIL_VERIFIED", target_user=u["id"], ttype="user", tid=u["id"], before={"status": u["status"]},
                       after={"status": "ACTIVE" if u["status"] == "PENDING_VERIFICATION" else u["status"]})

    def resend_verification(self, email: str, ip: str) -> None:
        email = (email or "").strip().lower()
        self.limit("forgot_email", email)
        self.limit("forgot_ip", ip)
        u = self.db.one("SELECT * FROM users WHERE email=?", (email,))
        if not u or u["status"] != "PENDING_VERIFICATION":
            return
        with self.db.tx() as t:
            tok = self._new_user_token(t, u["id"], "VERIFY_EMAIL", 24 * 3600)
        self.mail.send(email, *mailtpl.verify_mail(self._link("/account/verify", tok)))

    # ================================================================= login / sessions
    def login(self, email: str, password: str, *, kind: str, ip: str, ua: str, totp: str | None = None) -> dict:
        email = (email or "").strip().lower()
        self.limit("login_ip", ip)
        self.limit("login_email", email)
        u = self.db.one("SELECT * FROM users WHERE email=?", (email,))
        ok = sec.verify_password(u["password_hash"] if u else None, password or "")
        if not ok or not u:
            raise Denied("INVALID_CREDENTIALS", 401)
        if u["status"] == "BLOCKED":
            raise Denied("ACCOUNT_BLOCKED", 403)
        if u["status"] == "PENDING_VERIFICATION":
            raise Denied("EMAIL_NOT_VERIFIED", 403)
        if sec.needs_rehash(u["password_hash"]):
            self.db.x("UPDATE users SET password_hash=? WHERE id=?", (sec.hash_password(password), u["id"]))
        mfa_needed = u["role"] == "ADMIN"
        if mfa_needed and not u["totp_enabled"]:
            raise Denied("ADMIN_MFA_NOT_CONFIGURED", 403)
        mfa_ok = 0
        if mfa_needed and kind == "CLIENT":
            if not totp or not self._check_second_factor(u, totp):
                raise Denied("MFA_REQUIRED", 401)
            mfa_ok = 1
        self.rl.reset(f"login_email:{email}")
        raw = sec.token()
        hours = self.s.session_hours_web if kind == "WEB" else self.s.session_hours_client
        csrf = sec.token() if kind == "WEB" else None
        self.db.x("""INSERT INTO sessions(id_hash, user_id, kind, csrf, mfa_ok, created_at, last_seen_at, expires_at, ip, user_agent)
                     VALUES (?,?,?,?,?,?,?,?,?,?)""",
                  (sec.sha256(raw), u["id"], kind, csrf, int(mfa_ok or not mfa_needed), self.now(), self.now(), self.now() + hours * 3600, ip, (ua or "")[:200]))
        self.audit(None, actor=u, action="LOGIN", target_user=u["id"], ttype="session", after={"kind": kind, "mfa_pending": bool(mfa_needed and not mfa_ok)}, ip=ip)
        return {"token": raw, "csrf": csrf, "mfa_required": bool(mfa_needed and not mfa_ok), "user": self.public_user(u)}

    def _check_second_factor(self, u: dict, code: str) -> bool:
        if not u.get("totp_secret_enc"):
            return False
        secret = self.fernet.decrypt(u["totp_secret_enc"].encode()).decode()
        if sec.totp_ok(secret, code, self.clock.wall()):
            return True
        h = sec.sha256(code.strip().lower())
        rc = self.db.one("SELECT * FROM recovery_codes WHERE user_id=? AND code_hash=? AND used_at IS NULL", (u["id"], h))
        if rc:
            self.db.x("UPDATE recovery_codes SET used_at=? WHERE id=?", (self.now(), rc["id"]))
            self.audit(None, actor=u, action="RECOVERY_CODE_USED", target_user=u["id"])
            return True
        return False

    def complete_mfa(self, raw: str, code: str, ip: str) -> dict:
        """Second step for web admins. Rotates the session id (new token) after the privilege change."""
        sess = self._session_row(raw)
        if not sess:
            raise Denied("NOT_AUTHENTICATED", 401)
        self.limit("mfa_session", sess["id_hash"])
        u = self.db.one("SELECT * FROM users WHERE id=?", (sess["user_id"],))
        if not self._check_second_factor(u, code):
            raise Denied("MFA_INVALID", 401)
        new_raw, csrf = sec.token(), sec.token()
        with self.db.tx() as t:
            t.x("UPDATE sessions SET revoked_at=? WHERE id_hash=?", (self.now(), sess["id_hash"]))
            t.x("""INSERT INTO sessions(id_hash, user_id, kind, csrf, mfa_ok, created_at, last_seen_at, expires_at, ip, user_agent)
                   VALUES (?,?,?,?,1,?,?,?,?,?)""", (sec.sha256(new_raw), u["id"], sess["kind"], csrf, self.now(), self.now(),
                                                    self.now() + self.s.session_hours_web * 3600, ip, sess["user_agent"]))
            self.audit(t, actor=u, action="MFA_OK", target_user=u["id"], ttype="session", ip=ip)
        return {"token": new_raw, "csrf": csrf, "user": self.public_user(u)}

    def _session_row(self, raw: str | None) -> dict | None:
        if not raw:
            return None
        s = self.db.one("SELECT * FROM sessions WHERE id_hash=?", (sec.sha256(raw),))
        if not s or s["revoked_at"] is not None or self.now() >= s["expires_at"]:
            return None
        return s

    def authenticate(self, raw: str | None, *, kind: str | None = None, need_mfa: bool = True) -> tuple[dict, dict]:
        """Session -> (session, user). Re-checks the user's status on EVERY request (block takes effect immediately)."""
        s = self._session_row(raw)
        if not s or (kind and s["kind"] != kind):
            raise Denied("NOT_AUTHENTICATED", 401)
        u = self.db.one("SELECT * FROM users WHERE id=?", (s["user_id"],))
        if not u or u["status"] != "ACTIVE":
            raise Denied("ACCOUNT_NOT_ACTIVE", 403)
        if need_mfa and not s["mfa_ok"]:
            raise Denied("MFA_REQUIRED", 401)
        if self.now() - s["last_seen_at"] > 60:
            self.db.x("UPDATE sessions SET last_seen_at=? WHERE id_hash=?", (self.now(), s["id_hash"]))
        return s, u

    def logout(self, raw: str | None) -> None:
        s = self._session_row(raw)
        if s:
            self.db.x("UPDATE sessions SET revoked_at=? WHERE id_hash=?", (self.now(), s["id_hash"]))

    def change_password(self, sess: dict, u: dict, current: str, new: str, ip: str) -> None:
        """Revokes all OTHER sessions (web + bot client). Device credentials stay valid (separate, revocable by the admin)."""
        if not sec.verify_password(u["password_hash"], current or ""):
            raise Denied("INVALID_CREDENTIALS", 401)
        probs = sec.password_problems(new, u["email"])
        if probs:
            raise Denied("PASSWORD_WEAK", 400, {"problems": probs})
        with self.db.tx() as t:
            t.x("UPDATE users SET password_hash=?, password_changed_at=? WHERE id=?", (sec.hash_password(new), self.now(), u["id"]))
            t.x("UPDATE sessions SET revoked_at=? WHERE user_id=? AND id_hash<>? AND revoked_at IS NULL", (self.now(), u["id"], sess["id_hash"]))
            self.audit(t, actor=u, action="PASSWORD_CHANGED", target_user=u["id"], ip=ip)

    def forgot_password(self, email: str, ip: str) -> None:
        email = (email or "").strip().lower()
        self.limit("forgot_ip", ip)
        if not self.rl.hit(f"forgot_email:{email}", *LIMITS["forgot_email"]):
            return                                              # same answer, no mail
        u = self.db.one("SELECT * FROM users WHERE email=?", (email,))
        if not u or u["status"] == "BLOCKED":
            return
        with self.db.tx() as t:
            tok = self._new_user_token(t, u["id"], "RESET_PASSWORD", 3600)
        self.mail.send(email, *mailtpl.reset_mail(self._link("/account/reset", tok)))

    def reset_password(self, tok: str, new: str, ip: str) -> None:
        """Reset or first password after an admin invitation. All sessions are revoked."""
        with self.db.tx() as t:
            r = self._use_token(t, tok, ("RESET_PASSWORD", "INVITE"))
            u = t.one("SELECT * FROM users WHERE id=? FOR UPDATE", (r["user_id"],))
            probs = sec.password_problems(new, u["email"])
            if probs:
                raise Denied("PASSWORD_WEAK", 400, {"problems": probs})
            status = u["status"]
            if status == "PENDING_VERIFICATION":
                status = "ACTIVE"                                 # the link proved control of the mailbox
            t.x("UPDATE users SET password_hash=?, password_changed_at=?, status=?, email_verified_at=COALESCE(email_verified_at, ?) WHERE id=?",
                (sec.hash_password(new), self.now(), status, self.now(), u["id"]))
            t.x("UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL", (self.now(), u["id"]))
            self.audit(t, actor=None, action="PASSWORD_RESET" if r["purpose"] == "RESET_PASSWORD" else "INVITE_ACCEPTED",
                       target_user=u["id"], before={"status": u["status"]}, after={"status": status}, ip=ip)

    # ================================================================= admin bootstrap / roles (CLI only)
    def bootstrap_admin(self, email: str, password: str) -> dict:
        email = email.strip().lower()
        if self.db.one("SELECT 1 AS x FROM users WHERE role='ADMIN'"):
            raise Denied("ADMIN_ALREADY_EXISTS", 409)
        probs = sec.password_problems(password, email)
        if probs:
            raise Denied("PASSWORD_WEAK", 400, {"problems": probs})
        secret = sec.new_totp_secret()
        codes = sec.recovery_codes()
        uid = sec.new_id()
        with self.db.tx() as t:
            if t.one("SELECT 1 AS x FROM users WHERE email=?", (email,)):
                t.x("UPDATE users SET role='ADMIN', status='ACTIVE', password_hash=?, totp_secret_enc=?, totp_enabled=1, email_verified_at=COALESCE(email_verified_at, ?) WHERE email=?",
                    (sec.hash_password(password), self.fernet.encrypt(secret.encode()).decode(), self.now(), email))
                uid = t.one("SELECT id FROM users WHERE email=?", (email,))["id"]
            else:
                t.x("""INSERT INTO users(id, email, password_hash, status, role, created_at, email_verified_at, password_changed_at, totp_secret_enc, totp_enabled)
                       VALUES (?,?,?,'ACTIVE','ADMIN',?,?,?,?,1)""",
                    (uid, email, sec.hash_password(password), self.now(), self.now(), self.now(), self.fernet.encrypt(secret.encode()).decode()))
            for c in codes:
                t.x("INSERT INTO recovery_codes(id, user_id, code_hash) VALUES (?,?,?)", (sec.new_id(), uid, sec.sha256(c)))
            self.audit(t, actor={"id": "CLI", "role": "SYSTEM"}, action="ADMIN_BOOTSTRAP", target_user=uid, after={"role": "ADMIN"})
        import pyotp
        return {"user_id": uid, "totp_uri": pyotp.TOTP(secret).provisioning_uri(email, issuer_name="MasterQUO License Manager"),
                "totp_secret": secret, "recovery_codes": codes}

    def set_role(self, email: str, role: str, actor: str = "CLI") -> None:
        if role not in ("USER", "ADMIN"):
            raise Denied("BAD_ROLE", 400)
        with self.db.tx() as t:
            u = t.one("SELECT * FROM users WHERE email=? FOR UPDATE", (email.strip().lower(),))
            if not u:
                raise Denied("NO_SUCH_USER", 404)
            t.x("UPDATE users SET role=? WHERE id=?", (role, u["id"]))
            t.x("UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL", (self.now(), u["id"]))   # new privileges -> new session
            self.audit(t, actor={"id": actor, "role": "SYSTEM"}, action="ROLE_CHANGED", target_user=u["id"], before={"role": u["role"]}, after={"role": role})

    # ================================================================= licenses (admin)
    def _require_clock(self) -> None:
        if self.clock.anomaly:
            raise Denied("SERVER_CLOCK_ANOMALY", 503, {"reason": self.clock.anomaly})

    def generate_license(self, admin: dict, user_id: str, note: str | None, ip: str) -> dict:
        """Server-side generator: 256-bit key from `secrets`; only the hash is stored; the key is returned ONCE."""
        self._require_clock()
        key = sec.license_key()
        lid = sec.new_id()
        with self.db.tx() as t:
            u = t.one("SELECT * FROM users WHERE id=?", (user_id,))
            if not u:
                raise Denied("NO_SUCH_USER", 404)
            t.x("""INSERT INTO licenses(id, user_id, key_hash, key_hint, type, duration_s, status, note, created_by, created_at)
                   VALUES (?,?,?,?, 'STD_48H', ?, 'ISSUED', ?, ?, ?)""",
                (lid, user_id, sec.key_hash(key), sec.key_hint(key), self.s.license_seconds, (note or "")[:200] or None, admin["id"], self.now()))
            self.audit(t, actor=admin, action="LICENSE_GENERATED", target_user=user_id, ttype="license", tid=lid,
                       after={"status": "ISSUED", "type": "STD_48H", "key_hint": sec.key_hint(key), "note": note}, ip=ip)
        return {"license": self.license_view(self.db.one("SELECT * FROM licenses WHERE id=?", (lid,))), "key": key,
                "warning": "Pełny klucz jest pokazany tylko teraz. Serwer przechowuje wyłącznie jego skrót."}

    def revoke_license(self, admin: dict, lid: str, reason: str | None, ip: str) -> dict:
        with self.db.tx() as t:
            lic = t.one("SELECT * FROM licenses WHERE id=? FOR UPDATE", (lid,))
            if not lic:
                raise Denied("NO_SUCH_LICENSE", 404)
            if lic["status"] == "REVOKED":
                return self.license_view(lic)
            t.x("UPDATE licenses SET status='REVOKED', revoked_at=?, revoked_by=?, revoke_reason=? WHERE id=?",
                (self.now(), admin["id"], (reason or "")[:200], lid))
            self.audit(t, actor=admin, action="LICENSE_REVOKED", target_user=lic["user_id"], ttype="license", tid=lid,
                       before={"status": self.status_of(lic)}, after={"status": "REVOKED", "reason": reason}, ip=ip)
        return self.license_view(self.db.one("SELECT * FROM licenses WHERE id=?", (lid,)))

    def release_seat(self, admin: dict, activation_id: str, reason: str | None, ip: str) -> dict:
        """Computer replaced: the old device credential is revoked, the license may be activated again ONLY until its
        original expires_at (dates are never reset)."""
        with self.db.tx() as t:
            a = t.one("SELECT * FROM license_activations WHERE id=? FOR UPDATE", (activation_id,))
            if not a:
                raise Denied("NO_SUCH_ACTIVATION", 404)
            if a["released_at"] is None:
                t.x("UPDATE license_activations SET released_at=?, release_reason=?, released_by=? WHERE id=?",
                    (self.now(), (reason or "SEAT_RESET")[:200], admin["id"], activation_id))
            t.x("UPDATE devices SET revoked_at=COALESCE(revoked_at, ?), revoke_reason=COALESCE(revoke_reason, 'SEAT_RESET') WHERE id=?", (self.now(), a["device_id"]))
            t.x("UPDATE trading_accounts SET unlinked_at=COALESCE(unlinked_at, ?) WHERE device_id=?", (self.now(), a["device_id"]))
            lic = t.one("SELECT * FROM licenses WHERE id=?", (a["license_id"],))
            self.audit(t, actor=admin, action="SEAT_RESET", target_user=a["user_id"], ttype="activation", tid=activation_id,
                       before={"device_id": a["device_id"], "released": a["released_at"] is not None},
                       after={"released": True, "license_expires_at": lic["expires_at"]}, ip=ip)
        return {"released": True, "license": self.license_view(lic)}

    def revoke_device(self, admin: dict, device_id: str, reason: str | None, ip: str) -> None:
        with self.db.tx() as t:
            d = t.one("SELECT * FROM devices WHERE id=? FOR UPDATE", (device_id,))
            if not d:
                raise Denied("NO_SUCH_DEVICE", 404)
            t.x("UPDATE devices SET revoked_at=COALESCE(revoked_at, ?), revoke_reason=? WHERE id=?", (self.now(), (reason or "ADMIN")[:200], device_id))
            t.x("UPDATE license_activations SET released_at=?, release_reason='DEVICE_REVOKED', released_by=? WHERE device_id=? AND released_at IS NULL",
                (self.now(), admin["id"], device_id))
            t.x("UPDATE trading_accounts SET unlinked_at=COALESCE(unlinked_at, ?) WHERE device_id=?", (self.now(), device_id))
            self.audit(t, actor=admin, action="DEVICE_REVOKED", target_user=d["user_id"], ttype="device", tid=device_id,
                       before={"revoked": d["revoked_at"] is not None}, after={"revoked": True, "reason": reason}, ip=ip)

    def status_of(self, lic: dict) -> str:
        """Authoritative status, evaluated with the server clock on every call (a sweeper is only cosmetic)."""
        if lic["status"] == "REVOKED":
            return "REVOKED"
        if lic["activated_at"] is None:
            return "ISSUED"
        return "ACTIVE" if self.now() < lic["expires_at"] else "EXPIRED"

    def license_view(self, lic: dict) -> dict:
        stt = self.status_of(lic)
        return {"id": lic["id"], "user_id": lic["user_id"], "key_hint": lic["key_hint"], "type": lic["type"], "status": stt, "note": lic["note"],
                "created_at": lic["created_at"], "activated_at": lic["activated_at"], "expires_at": lic["expires_at"],
                "remaining_s": max(0, lic["expires_at"] - self.now()) if lic["expires_at"] and stt == "ACTIVE" else 0,
                "revoked_at": lic["revoked_at"], "revoke_reason": lic["revoke_reason"], "duration_s": lic["duration_s"]}

    def sweep_expired(self) -> int:
        """Auxiliary: persists EXPIRED. Its failure can never extend validity (status_of decides)."""
        return self.db.x("UPDATE licenses SET status='EXPIRED' WHERE status='ACTIVE' AND expires_at <= ?", (self.now(),))

    # ================================================================= devices: challenge + proof of possession
    def challenge(self, purpose: str, *, user_id: str | None = None, device_id: str | None = None, ip: str = "") -> dict:
        self.limit("challenge_device", device_id or user_id or ip)
        n = sec.token()
        self.db.x("INSERT INTO device_nonces(nonce, purpose, user_id, device_id, created_at, expires_at) VALUES (?,?,?,?,?,?)",
                  (n, purpose, user_id, device_id, self.now(), self.now() + 60))
        return {"nonce": n, "expires_in": 60, "server_time": self.now()}

    def _consume_nonce(self, t, nonce: str, purpose: str, *, user_id: str | None = None, device_id: str | None = None) -> None:
        r = t.one("SELECT * FROM device_nonces WHERE nonce=? FOR UPDATE", (nonce or "",))
        if (not r or r["purpose"] != purpose or r["used_at"] is not None or self.now() >= r["expires_at"]
                or (user_id and r["user_id"] != user_id) or (device_id and r["device_id"] != device_id)):
            raise Denied("NONCE_INVALID_OR_REPLAYED", 401)
        t.x("UPDATE device_nonces SET used_at=? WHERE nonce=?", (self.now(), nonce))

    def device_auth(self, device_id: str, nonce: str, sig: str, method: str, path: str, body: bytes) -> tuple[dict, dict]:
        """Proof of possession of the device private key over (method, path, single-use nonce, body hash)."""
        d = self.db.one("SELECT * FROM devices WHERE id=?", (device_id or "",))
        if not d:
            raise Denied("DEVICE_UNKNOWN", 401)
        with self.db.tx() as t:
            self._consume_nonce(t, nonce, "DEVICE", device_id=device_id)
        if not sec.verify_device_sig(d["public_key"], sec.device_message(method, path, nonce, body), sig or ""):
            raise Denied("DEVICE_SIGNATURE_INVALID", 401)
        if d["revoked_at"] is not None:
            raise Denied("DEVICE_REVOKED", 403)
        u = self.db.one("SELECT * FROM users WHERE id=?", (d["user_id"],))
        if not u or u["status"] != "ACTIVE":
            raise Denied("ACCOUNT_NOT_ACTIVE", 403)
        self.db.x("UPDATE devices SET last_seen_at=? WHERE id=?", (self.now(), device_id))
        return d, u

    # ================================================================= activation (atomic, idempotent)
    def activate(self, user: dict, key: str, public_key_pem: str, install_id: str, device_name: str | None, nonce: str, sig: str, ip: str) -> dict:
        self._require_clock()
        self.limit("activate_user", user["id"])
        try:
            sec.load_public(public_key_pem)
        except Exception:
            raise Denied("DEVICE_KEY_INVALID", 400)
        # proof of possession of the new device key, bound to this user's activation nonce and the key itself
        msg = sec.device_message("POST", "/api/v1/licenses/activate", nonce, (sec.key_hash(key) + "|" + install_id).encode())
        if not sec.verify_device_sig(public_key_pem, msg, sig):
            raise Denied("DEVICE_SIGNATURE_INVALID", 401)
        with self.db.tx() as t:
            self._consume_nonce(t, nonce, "ACTIVATE", user_id=user["id"])
            lic = t.one("SELECT * FROM licenses WHERE key_hash=? FOR UPDATE", (sec.key_hash(key),))
            if not lic or lic["user_id"] != user["id"]:
                self.audit(t, actor=user, action="ACTIVATION_REJECTED", target_user=user["id"], after={"reason": "NOT_FOUND_FOR_ACCOUNT"}, ip=ip)
                raise Denied("LICENSE_NOT_FOUND_FOR_ACCOUNT", 404)
            stt = self.status_of(lic)
            if stt in ("REVOKED", "EXPIRED"):
                raise Denied("LICENSE_" + stt, 403, {"expires_at": lic["expires_at"]})
            dev = t.one("SELECT * FROM devices WHERE user_id=? AND public_key=?", (user["id"], public_key_pem.strip()))
            if dev and dev["revoked_at"] is not None:
                raise Denied("DEVICE_REVOKED", 403)
            seat = t.one("SELECT * FROM license_activations WHERE license_id=? AND released_at IS NULL FOR UPDATE", (lic["id"],))
            if seat and (not dev or seat["device_id"] != dev["id"]):
                raise Denied("SEAT_IN_USE", 409, {"hint": "Licencja jest aktywna na innym komputerze. Administrator może zwolnić stanowisko."})
            if not dev:
                dev = {"id": sec.new_id()}
                t.x("INSERT INTO devices(id, user_id, public_key, install_id, name, created_at) VALUES (?,?,?,?,?,?)",
                    (dev["id"], user["id"], public_key_pem.strip(), install_id[:64], (device_name or "")[:80] or None, self.now()))
            if seat:                                            # retry from the same device: idempotent
                act_id = seat["id"]
            else:
                act_id = sec.new_id()
                t.x("INSERT INTO license_activations(id, license_id, device_id, user_id, created_at) VALUES (?,?,?,?,?)",
                    (act_id, lic["id"], dev["id"], user["id"], self.now()))
            if lic["activated_at"] is None:                     # FIRST activation starts the 48 h - exactly once
                t.x("UPDATE licenses SET status='ACTIVE', activated_at=?, expires_at=? WHERE id=? AND activated_at IS NULL",
                    (self.now(), self.now() + lic["duration_s"], lic["id"]))
                self.audit(t, actor=user, action="LICENSE_ACTIVATED", target_user=user["id"], ttype="license", tid=lic["id"],
                           before={"status": "ISSUED"}, after={"status": "ACTIVE", "activated_at": self.now(), "expires_at": self.now() + lic["duration_s"],
                                                               "device_id": dev["id"]}, ip=ip)
            elif not seat:
                self.audit(t, actor=user, action="LICENSE_REACTIVATED_SAME_TERM", target_user=user["id"], ttype="license", tid=lic["id"],
                           after={"device_id": dev["id"], "expires_at": lic["expires_at"]}, ip=ip)
        lic = self.db.one("SELECT * FROM licenses WHERE id=?", (lic["id"],))
        return {"activation_id": act_id, "device_id": dev["id"], "license": self.license_view(lic), "server_time": self.now(),
                "lease_public_key": self.public_pem, "kid": self.kid, "issuer": self.s.issuer}

    # ================================================================= heartbeat -> lease
    def _active_seat(self, device: dict) -> tuple[dict, dict]:
        a = self.db.one("SELECT * FROM license_activations WHERE device_id=? AND released_at IS NULL ORDER BY created_at DESC LIMIT 1", (device["id"],))
        if not a:
            raise Denied("NO_ACTIVE_ACTIVATION", 403)
        lic = self.db.one("SELECT * FROM licenses WHERE id=?", (a["license_id"],))
        stt = self.status_of(lic)
        if stt != "ACTIVE":
            raise Denied("LICENSE_" + stt, 403, {"expires_at": lic["expires_at"], "license_id": lic["id"]})
        return a, lic

    def heartbeat(self, device: dict, user: dict) -> dict:
        self._require_clock()
        self.limit("heartbeat_device", device["id"])
        a, lic = self._active_seat(device)
        now = self.now()
        exp = min(now + self.s.lease_seconds, lic["expires_at"])
        claims = {"iss": self.s.issuer, "aud": "masterquo-bot", "sub": user["id"], "lic": lic["id"], "act": a["id"], "dev": device["id"],
                  "scope": SCOPES, "iat": now, "nbf": now, "exp": exp, "lic_exp": lic["expires_at"], "jti": sec.new_id()}
        return {"lease": sec.sign_jwt(self._key, claims, self.kid), "server_time": now, "license": self.license_view(lic),
                "user": {"id": user["id"], "email": user["email"]}}

    def authorize_op(self, device: dict, user: dict, intent_id: str, op: str, detail: dict) -> dict:
        """Fresh online authorization for ONE opening order intent. Single use per (activation, intent)."""
        self._require_clock()
        self.limit("authorize_device", device["id"])
        if op != "OPEN" or not intent_id or len(intent_id) > 200:
            raise Denied("BAD_OPERATION", 400)
        a, lic = self._active_seat(device)
        now = self.now()
        exp = min(now + self.s.op_token_seconds, lic["expires_at"])
        jti = sec.new_id()
        with self.db.tx() as t:
            if t.one("SELECT 1 AS x FROM op_authorizations WHERE activation_id=? AND intent_id=?", (a["id"], intent_id)):
                raise Denied("INTENT_ALREADY_AUTHORIZED", 409)
            t.x("INSERT INTO op_authorizations(jti, activation_id, intent_id, op, detail_json, created_at, expires_at) VALUES (?,?,?,?,?,?,?)",
                (jti, a["id"], intent_id, op, J({k: detail.get(k) for k in ("symbol", "side", "volume", "mode")}), now, exp))
        claims = {"iss": self.s.issuer, "aud": "masterquo-bot-op", "sub": user["id"], "act": a["id"], "dev": device["id"], "op": op,
                  "intent": intent_id, "iat": now, "nbf": now, "exp": exp, "jti": jti}
        return {"op_token": sec.sign_jwt(self._key, claims, self.kid), "server_time": now, "expires_at": exp}

    # ================================================================= connector: account link + telemetry
    def link_account(self, device: dict, user: dict, body: dict) -> dict:
        self._active_seat(device)
        if body.get("consent") is not True:
            raise Denied("CONSENT_REQUIRED", 400)
        server, login = str(body.get("server") or "").strip()[:120], str(body.get("login") or "").strip()[:40]
        if not server or not login.isdigit():
            raise Denied("ACCOUNT_IDENTITY_INVALID", 400)
        tm = body.get("trade_mode")
        if tm not in ("DEMO", "REAL", "CONTEST"):
            raise Denied("TRADE_MODE_INVALID", 400)
        with self.db.tx() as t:
            cur = t.one("SELECT * FROM trading_accounts WHERE device_id=? AND unlinked_at IS NULL FOR UPDATE", (device["id"],))
            if cur and cur["server"] == server and cur["login"] == login:
                return {"account_id": cur["id"], "history_status": cur["history_status"], "history_to_ms": cur["history_to_ms"], "relinked": False}
            if cur:                                             # explicit switch: never merge history/balances
                t.x("UPDATE trading_accounts SET unlinked_at=? WHERE id=?", (self.now(), cur["id"]))
            aid = sec.new_id()
            t.x("""INSERT INTO trading_accounts(id, user_id, device_id, server, login, company, trade_mode, currency, currency_digits, bot_magic, linked_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (aid, user["id"], device["id"], server, login, str(body.get("company") or "")[:120], tm, str(body.get("currency") or "")[:8],
                 int(body.get("currency_digits") or 2), int(body["bot_magic"]) if body.get("bot_magic") is not None else None, self.now()))
            self.audit(t, actor=user, action="TRADING_ACCOUNT_LINKED", target_user=user["id"], ttype="trading_account", tid=aid,
                       before={"previous": cur["id"] if cur else None}, after={"server": server, "login": login, "trade_mode": tm})
        return {"account_id": aid, "history_status": "NOT_STARTED", "history_to_ms": None, "relinked": True}

    def unlink_account(self, device: dict, user: dict) -> None:
        self.db.x("UPDATE trading_accounts SET unlinked_at=? WHERE device_id=? AND unlinked_at IS NULL", (self.now(), device["id"]))
        self.audit(None, actor=user, action="TRADING_ACCOUNT_UNLINKED", target_user=user["id"], ttype="device", tid=device["id"])

    def _own_account(self, device: dict, account_id: str) -> dict:
        acc = self.db.one("SELECT * FROM trading_accounts WHERE id=?", (account_id or "",))
        if not acc or acc["device_id"] != device["id"] or acc["unlinked_at"] is not None:
            raise Denied("ACCOUNT_NOT_LINKED_TO_DEVICE", 403)
        return acc

    def snapshot(self, device: dict, user: dict, b: dict) -> dict:
        self.limit("snapshot_device", device["id"])
        self._active_seat(device)
        acc = self._own_account(device, b.get("account_id"))
        try:
            seq, ms = int(b["seq"]), int(b["measured_ms"])
            bal, eq = float(b["balance"]), float(b["equity"])
            cur = str(b["currency"])[:8]
        except (KeyError, TypeError, ValueError):
            raise Denied("SNAPSHOT_INVALID", 400)
        now_ms = self.now() * 1000
        if ms > now_ms + 120_000 or ms < now_ms - 7 * 86400_000 or not (-1e12 < bal < 1e12) or not (-1e12 < eq < 1e12) or seq < 0:
            raise Denied("SNAPSHOT_OUT_OF_RANGE", 400)
        if acc["currency"] and cur != acc["currency"]:
            raise Denied("CURRENCY_MISMATCH", 400)
        stale = acc["last_measured_ms"] is not None and (ms <= acc["last_measured_ms"] or (acc["last_seq"] is not None and seq <= acc["last_seq"]))
        with self.db.tx() as t:
            if t.one("SELECT 1 AS x FROM account_snapshots WHERE account_id=? AND seq=?", (acc["id"], seq)):
                return {"accepted": False, "duplicate": True}
            t.x("""INSERT INTO account_snapshots(account_id, seq, measured_ms, received_at, balance, equity, margin, margin_free, currency, stale_on_arrival)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""", (acc["id"], seq, ms, self.now(), bal, eq, b.get("margin"), b.get("margin_free"), cur, int(stale)))
            if not stale:                                        # an older packet never replaces a newer balance
                t.x("""UPDATE trading_accounts SET last_seq=?, last_measured_ms=?, last_received_at=?, last_balance=?, last_equity=?, last_currency=?
                       WHERE id=?""", (seq, ms, self.now(), bal, eq, cur, acc["id"]))
        return {"accepted": True, "stale": stale}

    def deals(self, device: dict, user: dict, b: dict) -> dict:
        self.limit("deals_device", device["id"])
        self._active_seat(device)
        acc = self._own_account(device, b.get("account_id"))
        ds = b.get("deals") or []
        if not isinstance(ds, list) or len(ds) > 1000:
            raise Denied("DEALS_BATCH_INVALID", 400)
        new = 0
        with self.db.tx() as t:
            for d in ds:
                try:
                    row = (acc["id"], str(int(d["ticket"])), str(d.get("order") or ""), str(d.get("position_id") or ""), int(d["time_ms"]), int(d["type"]),
                           int(d["entry"]), float(d["volume"]), float(d.get("price") or 0), float(d.get("profit") or 0), float(d.get("commission") or 0),
                           float(d.get("swap") or 0), float(d.get("fee") or 0), str(d.get("symbol") or "")[:40], int(d.get("magic") or 0),
                           str(d.get("comment") or "")[:64], self.now())
                except (KeyError, TypeError, ValueError):
                    raise Denied("DEAL_INVALID", 400)
                if not (0 <= row[5] <= 30 and 0 <= row[6] <= 3 and row[7] >= 0):
                    raise Denied("DEAL_OUT_OF_RANGE", 400)
                if t.one("SELECT 1 AS x FROM trade_deals WHERE account_id=? AND ticket=?", (acc["id"], row[1])):
                    continue                                    # idempotent: duplicates are ignored
                t.x("""INSERT INTO trade_deals(account_id, ticket, order_ticket, position_id, time_ms, type, entry, volume, price, profit, commission,
                       swap, fee, symbol, magic, comment, received_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", row)
                new += 1
            imp = b.get("import") or {}
            if imp:
                frm, to = imp.get("from_ms"), imp.get("to_ms")
                status = "COMPLETE" if imp.get("complete") else ("INCOMPLETE" if imp.get("incomplete") else "IMPORTING")
                t.x("""UPDATE trading_accounts SET history_status=?, history_from_ms=COALESCE(?, history_from_ms),
                       history_to_ms=CASE WHEN history_to_ms IS NULL OR ? > history_to_ms THEN ? ELSE history_to_ms END WHERE id=?""",
                    (status, frm, to or 0, to, acc["id"]))
        if new:
            self.rebuild_cycles(acc["id"])
        a2 = self.db.one("SELECT history_status, history_to_ms FROM trading_accounts WHERE id=?", (acc["id"],))
        return {"accepted": new, "duplicates": len(ds) - new, **a2}

    def rebuild_cycles(self, account_id: str) -> None:
        acc = self.db.one("SELECT * FROM trading_accounts WHERE id=?", (account_id,))
        deals = self.db.q("SELECT * FROM trade_deals WHERE account_id=?", (account_id,))
        cyc = st.reconstruct(deals, acc["bot_magic"])
        with self.db.tx() as t:
            t.x("DELETE FROM reconstructed_trades WHERE account_id=?", (account_id,))
            for c in cyc:
                t.x("""INSERT INTO reconstructed_trades(account_id, cycle_id, position_id, symbol, direction, status, outcome, open_ms, close_ms, volume,
                       gross, commission, swap, fee, net, bot, note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (account_id, c["cycle_id"], c["position_id"], c["symbol"], c["direction"], c["status"],
                     st.outcome(c["net"], acc["currency_digits"]) if c["status"] == "COMPLETE" else None, c["open_ms"], c["close_ms"], c["volume"],
                     c["gross"], c["commission"], c["swap"], c["fee"], c["net"], c["bot"], c["note"]))

    # ================================================================= statistics (owner or admin)
    RANGES = {"7d": 7 * 86400, "30d": 30 * 86400, "all": None}

    def account_stats(self, account_id: str, *, rng: str = "30d", scope: str = "ACCOUNT", symbol: str | None = None,
                      since_ms: int | None = None, until_ms: int | None = None) -> dict:
        acc = self.db.one("SELECT * FROM trading_accounts WHERE id=?", (account_id,))
        if not acc:
            raise Denied("NO_SUCH_ACCOUNT", 404)
        if rng == "custom":
            if since_ms is None or until_ms is None or until_ms <= since_ms:
                raise Denied("BAD_RANGE", 400)
        else:
            if rng not in self.RANGES:
                raise Denied("BAD_RANGE", 400)
            since_ms = None if self.RANGES[rng] is None else (self.now() - self.RANGES[rng]) * 1000
            until_ms = None
        if scope not in ("ACCOUNT", "BOT"):
            raise Denied("BAD_SCOPE", 400)
        cyc = self.db.q("SELECT * FROM reconstructed_trades WHERE account_id=?", (account_id,))
        deals = self.db.q("SELECT time_ms, type, profit, commission, fee FROM trade_deals WHERE account_id=?", (account_id,))
        r = st.win_ratio(cyc, deals, digits=acc["currency_digits"], since_ms=since_ms, until_ms=until_ms, scope=scope, symbol=symbol)
        r.update(range=rng, currency=acc["currency"], trade_mode=acc["trade_mode"], history_status=acc["history_status"],
                 history_from_ms=acc["history_from_ms"], history_to_ms=acc["history_to_ms"], source="Dane z konektora MT5 klienta (nie niezależny audyt brokera)")
        if acc["history_status"] != "COMPLETE":
            r["complete"] = False
        return r

    def account_view(self, acc: dict) -> dict:
        age = (self.now() - acc["last_received_at"]) if acc["last_received_at"] else None
        live = acc["unlinked_at"] is None and age is not None and age <= 60
        return {"id": acc["id"], "server": acc["server"], "login": acc["login"], "company": acc["company"],
                "trade_mode": {"REAL": "LIVE"}.get(acc["trade_mode"], acc["trade_mode"]), "currency": acc["last_currency"] or acc["currency"],
                "balance": acc["last_balance"], "equity": acc["last_equity"], "measured_ms": acc["last_measured_ms"], "received_at": acc["last_received_at"],
                "data_age_s": age, "data_fresh": live, "linked_at": acc["linked_at"], "unlinked_at": acc["unlinked_at"],
                "history_status": acc["history_status"], "device_id": acc["device_id"]}

    # ================================================================= user self-service views
    def me(self, u: dict) -> dict:
        lics = self.db.q("SELECT * FROM licenses WHERE user_id=? ORDER BY created_at DESC", (u["id"],))
        devs = self.db.q("SELECT id, name, created_at, last_seen_at, revoked_at FROM devices WHERE user_id=? ORDER BY created_at DESC", (u["id"],))
        accs = self.db.q("SELECT * FROM trading_accounts WHERE user_id=? ORDER BY linked_at DESC", (u["id"],))
        return {"user": self.public_user(u), "licenses": [self.license_view(x) for x in lics], "devices": devs,
                "accounts": [self.account_view(a) for a in accs]}

    # ================================================================= admin views
    def admin_users(self, *, q: str = "", status: str = "", lic: str = "", sort: str = "created_at", desc: bool = True, page: int = 1, size: int = 25) -> dict:
        rows = self.db.q("SELECT * FROM users")
        out = []
        for u in rows:
            if q and q.lower() not in (u["email"] + " " + (u["display_name"] or "")).lower():
                continue
            if status and u["status"] != status:
                continue
            lics = [self.license_view(x) for x in self.db.q("SELECT * FROM licenses WHERE user_id=? ORDER BY created_at DESC", (u["id"],))]
            best = next((x for x in lics if x["status"] == "ACTIVE"), None) or next((x for x in lics if x["status"] == "ISSUED"), None) or (lics[0] if lics else None)
            if lic and (best or {}).get("status", "NONE") != lic:
                continue
            acc = self.db.one("SELECT * FROM trading_accounts WHERE user_id=? AND unlinked_at IS NULL ORDER BY linked_at DESC LIMIT 1", (u["id"],)) \
                or self.db.one("SELECT * FROM trading_accounts WHERE user_id=? ORDER BY linked_at DESC LIMIT 1", (u["id"],))
            av = self.account_view(acc) if acc else None
            wr = self.account_stats(acc["id"]) if acc else None
            dev = self.db.one("SELECT * FROM devices WHERE user_id=? AND revoked_at IS NULL ORDER BY last_seen_at DESC LIMIT 1", (u["id"],))
            conn_age = (self.now() - dev["last_seen_at"]) if dev and dev["last_seen_at"] else None
            out.append({"user": self.public_user(u), "account": av,
                        "win_ratio": None if not wr else {k: wr[k] for k in ("win_ratio", "wins", "losses", "neutral", "range", "complete", "incomplete_cycles")},
                        "license": best, "connector": {"status": "ONLINE" if conn_age is not None and conn_age <= 90 else ("OFFLINE" if dev else "NONE"),
                                                       "last_seen_at": dev["last_seen_at"] if dev else None, "age_s": conn_age}})
        key = {"email": lambda r: r["user"]["email"], "created_at": lambda r: r["user"]["created_at"] or 0,
               "balance": lambda r: (r["account"] or {}).get("balance") or -1e18, "win_ratio": lambda r: ((r["win_ratio"] or {}).get("win_ratio") or -1),
               "expires_at": lambda r: (r["license"] or {}).get("expires_at") or 0, "last_data": lambda r: (r["account"] or {}).get("received_at") or 0,
               "status": lambda r: r["user"]["status"]}.get(sort)
        if key is None:
            raise Denied("BAD_SORT", 400)
        out.sort(key=key, reverse=desc)
        size = max(1, min(int(size), 100))
        total = len(out)
        page = max(1, int(page))
        return {"total": total, "page": page, "size": size, "items": out[(page - 1) * size: page * size],
                "note": "Balance i win ratio pochodzą z konektora MT5 klienta; waluty nie są sumowane."}

    def admin_user(self, uid: str) -> dict:
        u = self.db.one("SELECT * FROM users WHERE id=?", (uid,))
        if not u:
            raise Denied("NO_SUCH_USER", 404)
        lics = [self.license_view(x) for x in self.db.q("SELECT * FROM licenses WHERE user_id=? ORDER BY created_at DESC", (uid,))]
        acts = self.db.q("SELECT * FROM license_activations WHERE user_id=? ORDER BY created_at DESC", (uid,))
        devs = self.db.q("SELECT id, name, install_id, created_at, last_seen_at, revoked_at, revoke_reason FROM devices WHERE user_id=? ORDER BY created_at DESC", (uid,))
        accs = self.db.q("SELECT * FROM trading_accounts WHERE user_id=? ORDER BY linked_at DESC", (uid,))
        audit = self.db.q("SELECT * FROM audit_events WHERE target_user_id=? ORDER BY at DESC LIMIT 100", (uid,))
        return {"user": self.public_user(u) | {"blocked_reason": u["blocked_reason"]}, "licenses": lics, "activations": acts, "devices": devs,
                "accounts": [self.account_view(a) | {"stats_30d": self.account_stats(a["id"])} for a in accs], "audit": audit}

    def admin_create_user(self, admin: dict, email: str, display_name: str | None, ip: str) -> dict:
        email = (email or "").strip().lower()
        if "@" not in email:
            raise Denied("EMAIL_INVALID", 400)
        with self.db.tx() as t:
            if t.one("SELECT 1 AS x FROM users WHERE email=?", (email,)):
                raise Denied("EMAIL_EXISTS", 409)
            uid = sec.new_id()
            t.x("INSERT INTO users(id, email, display_name, status, role, created_at) VALUES (?,?,?, 'PENDING_VERIFICATION', 'USER', ?)",
                (uid, email, (display_name or "")[:80] or None, self.now()))
            tok = self._new_user_token(t, uid, "INVITE", 72 * 3600)
            self.audit(t, actor=admin, action="USER_INVITED", target_user=uid, ttype="user", tid=uid, after={"email": email}, ip=ip)
        self.mail.send(email, *mailtpl.invite_mail(self._link("/account/reset", tok)))
        return {"user_id": uid, "invited": True}

    def admin_block(self, admin: dict, uid: str, block: bool, reason: str | None, ip: str) -> dict:
        if uid == admin["id"] and block:
            raise Denied("CANNOT_BLOCK_SELF", 400)
        with self.db.tx() as t:
            u = t.one("SELECT * FROM users WHERE id=? FOR UPDATE", (uid,))
            if not u:
                raise Denied("NO_SUCH_USER", 404)
            new = "BLOCKED" if block else ("ACTIVE" if u["email_verified_at"] else "PENDING_VERIFICATION")
            t.x("UPDATE users SET status=?, blocked_at=?, blocked_reason=? WHERE id=?", (new, self.now() if block else None, (reason or "")[:200] if block else None, uid))
            if block:
                t.x("UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL", (self.now(), uid))
            self.audit(t, actor=admin, action="USER_BLOCKED" if block else "USER_UNBLOCKED", target_user=uid, ttype="user", tid=uid,
                       before={"status": u["status"]}, after={"status": new, "reason": reason}, ip=ip)
        return self.public_user(self.db.one("SELECT * FROM users WHERE id=?", (uid,)))

    def admin_licenses(self, *, status: str = "", q: str = "", page: int = 1, size: int = 50) -> dict:
        rows = self.db.q("SELECT l.*, u.email FROM licenses l JOIN users u ON u.id = l.user_id ORDER BY l.created_at DESC")
        items = []
        for r in rows:
            v = self.license_view(r) | {"email": r["email"]}
            if status and v["status"] != status:
                continue
            if q and q.lower() not in (r["email"] + " " + r["key_hint"] + " " + (r["note"] or "")).lower():
                continue
            act = self.db.one("SELECT id, device_id, created_at FROM license_activations WHERE license_id=? AND released_at IS NULL", (r["id"],))
            items.append(v | {"active_activation": act})
        size = max(1, min(int(size), 200))
        return {"total": len(items), "page": page, "size": size, "items": items[(page - 1) * size: page * size]}

    def admin_audit(self, *, page: int = 1, size: int = 50, user_id: str | None = None) -> dict:
        size = max(1, min(int(size), 200))
        where, args = ("WHERE target_user_id=?", (user_id,)) if user_id else ("", ())
        total = self.db.one(f"SELECT COUNT(*) AS n FROM audit_events {where}", args)["n"]
        rows = self.db.q(f"SELECT * FROM audit_events {where} ORDER BY at DESC LIMIT {size} OFFSET {(max(1, page) - 1) * size}", args)
        return {"total": total, "page": page, "size": size, "items": rows}
