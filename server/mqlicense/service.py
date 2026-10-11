"""Business logic of the license server. Every decision is taken HERE with the SERVER clock (UTC epoch seconds).

Rules (product requirements, not configurable in production):
* a license is valid exactly LICENSE_SECONDS = 259200 s (72 h) from the moment it is GENERATED (created_at), not from
  the first use; expires_at = created_at + 259200 is stored once and never extended (no "renew" for a license -
  reissue creates a NEW key and record);
* the client opens a session for ONE program run (boot_id + one-time nonce); the session holds a signed lease
  (Ed25519 JWT) valid for at most `lease_seconds` (30 s) and never beyond the license expiry; the client renews it with
  the session token (kept in memory only);
* a license allows `max_sessions` concurrent sessions (default 1); a crashed client frees its slot when its lease
  expires (<= 30 s); revocation / session termination is effective at the next renewal (<= 30 s);
* deny by default: unknown, malformed, expired and revoked keys are rejected; unknown and malformed keys get the same
  answer; no "offline mode", no universal key, no grace period.
"""
from __future__ import annotations

import json
import logging

from . import security as sec
from .ratelimit import LIMITS, RateLimiter

log = logging.getLogger("mqlicense")

TELEMETRY_KEYS = {"app_version", "execution_mode", "symbol", "signals_confirmed", "signals_blocked", "trades_closed",
                  "winrate_net_pct", "profit_factor_net", "expectancy_r", "roi_pct", "balance", "equity", "currency", "period",
                  "stats_source", "stats_as_of", "data_quality", "uptime_s"}


class Denied(Exception):
    def __init__(self, code: str, status: int = 403, detail: dict | None = None):
        super().__init__(code)
        self.code, self.status, self.detail = code, status, detail or {}


def J(o) -> str:
    return json.dumps(o, default=str, sort_keys=True, ensure_ascii=False)


def license_status(lic: dict, now: int) -> str:
    if lic.get("revoked_at"):
        return "COFNIETA"
    if now >= lic["expires_at"]:
        return "WYGASLA"
    return "AKTYWNA"


class LicenseService:
    def __init__(self, settings, db, clock, limiter: RateLimiter | None = None):
        self.s, self.db, self.clock = settings, db, clock
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

    def _no_anomaly(self) -> None:
        if getattr(self.clock, "anomaly", None):
            raise Denied("SERVER_CLOCK_ANOMALY", 503, {"anomaly": self.clock.anomaly})

    def audit(self, t, *, actor: str, action: str, result: str = "OK", ttype: str | None = None, tid: str | None = None,
              detail: dict | None = None, ip: str | None = None) -> None:
        (t.execute if t is not None else self.db.x)(
            "INSERT INTO audit(at, actor, action, target_type, target_id, result, detail_json, ip) VALUES (?,?,?,?,?,?,?,?)",
            (self.now(), actor, action, ttype, tid, result, None if detail is None else J(detail), ip))

    def _active_sessions(self, t, license_id: str, now: int, exclude: str | None = None) -> int:
        r = t.execute("SELECT COUNT(*) FROM license_sessions WHERE license_id=? AND ended_at IS NULL AND lease_expires_at>? AND id<>?",
                      (license_id, now, exclude or "")).fetchone()
        return int(r[0])

    def _lease(self, lic: dict, sess: dict, now: int) -> tuple[str, int]:
        exp = min(now + int(self.s.lease_seconds), int(lic["expires_at"]))
        claims = {"iss": "mqlicense", "aud": "masterquo-client", "typ": "mq-lease", "sub": lic["id"], "sid": sess["id"],
                  "boot": sess["boot_id"], "iat": now, "nbf": now - 5, "exp": exp, "lic_exp": int(lic["expires_at"]),
                  "max_sessions": int(lic["max_sessions"])}
        return sec.sign_jwt(self._key, claims, self.kid), exp

    # ================================================================= licenses (admin)
    def create_license(self, actor: dict, *, customer_id: str | None = None, note: str | None = None, max_sessions: int | None = None,
                       ip: str | None = None, replaces: str | None = None, _t=None) -> dict:
        self._require(actor, "ADMIN")
        self._no_anomaly()
        ms = int(max_sessions or self.s.default_max_sessions)
        if not 1 <= ms <= 10:
            raise Denied("MAX_SESSIONS_OUT_OF_RANGE", 400)
        key = sec.license_key()
        now = self.now()
        lid = sec.new_id()

        def ins(t):
            if customer_id and not t.execute("SELECT 1 FROM customers WHERE id=?", (customer_id,)).fetchone():
                raise Denied("CUSTOMER_NOT_FOUND", 404)
            t.execute("""INSERT INTO licenses(id, key_hash, key_hint, created_at, expires_at, created_by, customer_id, note, max_sessions, replaces)
                         VALUES (?,?,?,?,?,?,?,?,?,?)""",
                      (lid, sec.key_hash(key, self.s.key_pepper), sec.key_hint(key), now, now + int(self.s.license_seconds), actor["id"],
                       customer_id, (note or "")[:500] or None, ms, replaces))
            self.audit(t, actor=actor["email"], action="LICENSE_CREATE", ttype="license", tid=lid,
                       detail={"customer_id": customer_id, "max_sessions": ms, "expires_at": now + int(self.s.license_seconds), "replaces": replaces},
                       ip=ip)
        if _t is not None:
            ins(_t)
        else:
            with self.db.tx() as t:
                ins(t)
        out = self.get_license(lid)
        out["key"] = key                         # returned ONCE to the creating administrator; only the HMAC is stored
        return out

    def get_license(self, lid: str) -> dict:
        lic = self.db.one("SELECT * FROM licenses WHERE id=?", (lid,))
        if not lic:
            raise Denied("LICENSE_NOT_FOUND", 404)
        return self._view(lic)

    def _view(self, lic: dict) -> dict:
        now = self.now()
        lic = {k: v for k, v in lic.items() if k != "key_hash"}
        lic["status"] = license_status(lic, now)
        lic["remaining_s"] = max(0, int(lic["expires_at"]) - now) if lic["status"] == "AKTYWNA" else 0
        lic["active_sessions"] = int(self.db.one("SELECT COUNT(*) AS n FROM license_sessions WHERE license_id=? AND ended_at IS NULL AND lease_expires_at>?",
                                                 (lic["id"], now))["n"])
        if lic.get("customer_id"):
            c = self.db.one("SELECT name, email FROM customers WHERE id=?", (lic["customer_id"],))
            lic["customer_name"] = (c or {}).get("name")
        return lic

    def list_licenses(self, *, status: str | None = None, q: str | None = None, limit: int = 200, offset: int = 0) -> list[dict]:
        rows = self.db.all("SELECT * FROM licenses ORDER BY created_at DESC LIMIT ? OFFSET ?", (min(int(limit), 1000), max(0, int(offset))))
        out = [self._view(r) for r in rows]
        if status:
            out = [r for r in out if r["status"] == status]
        if q:
            ql = q.lower()
            out = [r for r in out if ql in (r.get("note") or "").lower() or ql in (r.get("customer_name") or "").lower()
                   or ql in r["key_hint"].lower() or ql in r["id"]]
        return out

    def revoke_license(self, actor: dict, lid: str, reason: str, ip: str | None = None) -> dict:
        self._require(actor, "ADMIN")
        if not (reason or "").strip():
            raise Denied("REASON_REQUIRED", 400)
        now = self.now()
        with self.db.tx() as t:
            lic = t.execute("SELECT * FROM licenses WHERE id=?", (lid,)).fetchone()
            if not lic:
                raise Denied("LICENSE_NOT_FOUND", 404)
            if lic["revoked_at"]:
                raise Denied("ALREADY_REVOKED", 409)
            t.execute("UPDATE licenses SET revoked_at=?, revoked_by=?, revoke_reason=? WHERE id=?", (now, actor["id"], reason.strip()[:300], lid))
            n = t.execute("UPDATE license_sessions SET ended_at=?, end_reason='LICENSE_REVOKED' WHERE license_id=? AND ended_at IS NULL",
                          (now, lid)).rowcount
            self.audit(t, actor=actor["email"], action="LICENSE_REVOKE", ttype="license", tid=lid, detail={"reason": reason, "sessions_ended": n}, ip=ip)
        return self.get_license(lid)

    def reissue_license(self, actor: dict, lid: str, reason: str, ip: str | None = None) -> dict:
        """Revokes the old key and creates a NEW license (new key, new record, 72 h from now). The old record stays for audit."""
        self._require(actor, "ADMIN")
        self._no_anomaly()
        old = self.db.one("SELECT * FROM licenses WHERE id=?", (lid,))
        if not old:
            raise Denied("LICENSE_NOT_FOUND", 404)
        if not old["revoked_at"]:
            self.revoke_license(actor, lid, f"REISSUE: {reason or '-'}", ip)
        new = self.create_license(actor, customer_id=old["customer_id"], note=old["note"], max_sessions=old["max_sessions"], ip=ip, replaces=lid)
        self.db.x("UPDATE licenses SET replaced_by=? WHERE id=?", (new["id"], lid))
        self.audit(None, actor=actor["email"], action="LICENSE_REISSUE", ttype="license", tid=lid, detail={"new_id": new["id"]}, ip=ip)
        return new

    def assign_license(self, actor: dict, lid: str, customer_id: str | None, note: str | None = None, ip: str | None = None) -> dict:
        self._require(actor, "ADMIN")
        with self.db.tx() as t:
            if not t.execute("SELECT 1 FROM licenses WHERE id=?", (lid,)).fetchone():
                raise Denied("LICENSE_NOT_FOUND", 404)
            if customer_id and not t.execute("SELECT 1 FROM customers WHERE id=?", (customer_id,)).fetchone():
                raise Denied("CUSTOMER_NOT_FOUND", 404)
            t.execute("UPDATE licenses SET customer_id=?, note=COALESCE(?, note) WHERE id=?", (customer_id, note, lid))
            self.audit(t, actor=actor["email"], action="LICENSE_ASSIGN", ttype="license", tid=lid, detail={"customer_id": customer_id}, ip=ip)
        return self.get_license(lid)

    def set_max_sessions(self, actor: dict, lid: str, max_sessions: int, ip: str | None = None) -> dict:
        self._require(actor, "ADMIN")
        if not 1 <= int(max_sessions) <= 10:
            raise Denied("MAX_SESSIONS_OUT_OF_RANGE", 400)
        with self.db.tx() as t:
            if not t.execute("SELECT 1 FROM licenses WHERE id=?", (lid,)).fetchone():
                raise Denied("LICENSE_NOT_FOUND", 404)
            t.execute("UPDATE licenses SET max_sessions=? WHERE id=?", (int(max_sessions), lid))
            self.audit(t, actor=actor["email"], action="LICENSE_MAX_SESSIONS", ttype="license", tid=lid, detail={"max_sessions": int(max_sessions)}, ip=ip)
        return self.get_license(lid)

    # ================================================================= customers
    def create_customer(self, actor: dict, name: str, email: str | None = None, mt5_login: str | None = None, note: str | None = None,
                        stats_allowed: bool = False, ip: str | None = None) -> dict:
        self._require(actor, "ADMIN")
        if not (name or "").strip():
            raise Denied("NAME_REQUIRED", 400)
        cid = sec.new_id()
        with self.db.tx() as t:
            t.execute("INSERT INTO customers(id, name, email, mt5_login, note, created_at, created_by, stats_allowed) VALUES (?,?,?,?,?,?,?,?)",
                      (cid, name.strip()[:120], (email or "").strip()[:200] or None, (mt5_login or "").strip()[:40] or None, (note or "")[:500] or None,
                       self.now(), actor["id"], 1 if stats_allowed else 0))
            self.audit(t, actor=actor["email"], action="CUSTOMER_CREATE", ttype="customer", tid=cid, ip=ip)
        return self.db.one("SELECT * FROM customers WHERE id=?", (cid,))

    def update_customer(self, actor: dict, cid: str, fields: dict, ip: str | None = None) -> dict:
        self._require(actor, "ADMIN")
        allowed = {k: fields[k] for k in ("name", "email", "mt5_login", "note", "stats_allowed") if k in fields}
        if not allowed:
            raise Denied("NOTHING_TO_UPDATE", 400)
        if "stats_allowed" in allowed:
            allowed["stats_allowed"] = 1 if allowed["stats_allowed"] else 0
        with self.db.tx() as t:
            if not t.execute("SELECT 1 FROM customers WHERE id=?", (cid,)).fetchone():
                raise Denied("CUSTOMER_NOT_FOUND", 404)
            t.execute(f"UPDATE customers SET {', '.join(k + '=?' for k in allowed)} WHERE id=?", (*allowed.values(), cid))
            self.audit(t, actor=actor["email"], action="CUSTOMER_UPDATE", ttype="customer", tid=cid, detail=sorted(allowed), ip=ip)
        return self.db.one("SELECT * FROM customers WHERE id=?", (cid,))

    def list_customers(self) -> list[dict]:
        now = self.now()
        out = self.db.all("SELECT * FROM customers ORDER BY created_at DESC")
        for c in out:
            lic = self.db.all("SELECT * FROM licenses WHERE customer_id=?", (c["id"],))
            c["licenses_total"] = len(lic)
            c["licenses_active"] = sum(1 for x in lic if license_status(x, now) == "AKTYWNA")
        return out

    # ================================================================= client sessions
    def open_session(self, key: str, *, boot_id: str, nonce: str, client_version: str | None = None, client_label: str | None = None,
                     telemetry_opt_in: bool = False, ip: str | None = None) -> dict:
        self._no_anomaly()
        self.limit("client_session_ip", ip or "-")
        if not (isinstance(boot_id, str) and 16 <= len(boot_id) <= 80 and isinstance(nonce, str) and 16 <= len(nonce) <= 80):
            raise Denied("BAD_REQUEST", 400)
        kh = sec.key_hash(key, self.s.key_pepper)
        if kh is None:
            self.audit(None, actor="client", action="SESSION_OPEN", result="LICENSE_INVALID", detail={"why": "FORMAT"}, ip=ip)
            raise Denied("LICENSE_INVALID", 403)
        self.limit("client_session_key", kh[:16])
        now = self.now()
        token = sec.token()
        with self.db.tx() as t:
            if t.execute("SELECT 1 FROM used_nonces WHERE nonce=?", (nonce,)).fetchone():
                raise Denied("NONCE_REUSED", 409)
            t.execute("INSERT INTO used_nonces(nonce, used_at) VALUES (?,?)", (nonce, now))
            t.execute("DELETE FROM used_nonces WHERE used_at<?", (now - 7 * 86400,))
            row = t.execute("SELECT * FROM licenses WHERE key_hash=?", (kh,)).fetchone()
            lic = dict(row) if row else None
            code = None
            if lic is None:
                code = "LICENSE_INVALID"
            elif lic["revoked_at"]:
                code = "LICENSE_REVOKED"
            elif now >= lic["expires_at"]:
                code = "LICENSE_EXPIRED"
            elif self._active_sessions(t, lic["id"], now) >= int(lic["max_sessions"]):
                code = "SESSION_LIMIT_REACHED"
            if code:
                self.audit(t, actor="client", action="SESSION_OPEN", result=code, ttype="license", tid=(lic or {}).get("id"), ip=ip)
                failed = code
            else:
                failed = None
                sid = sec.new_id()
                sess = {"id": sid, "boot_id": boot_id}
                lease, exp = self._lease(lic, sess, now)
                t.execute("""INSERT INTO license_sessions(id, license_id, token_hash, boot_id, created_at, lease_expires_at, last_seen_at,
                             client_version, client_label, ip, telemetry_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                          (sid, lic["id"], sec.sha256(token), boot_id, now, exp, now, (client_version or "")[:40], (client_label or "")[:80], ip,
                           J({"opt_in": bool(telemetry_opt_in)})))
                t.execute("UPDATE licenses SET first_used_at=COALESCE(first_used_at, ?), last_used_at=? WHERE id=?", (now, now, lic["id"]))
                self.audit(t, actor="client", action="SESSION_OPEN", ttype="license", tid=lic["id"], detail={"session_id": sid}, ip=ip)
        if failed:
            raise Denied(failed, 403, {"expires_at": lic["expires_at"]} if failed == "LICENSE_EXPIRED" else {})
        return {"session_id": sid, "session_token": token, "lease": lease, "lease_expires_at": exp, "license_expires_at": lic["expires_at"],
                "license_id": lic["id"], "server_time": now, "renew_every_s": max(5, int(self.s.lease_seconds) // 3), "kid": self.kid}

    def _session_by_token(self, t, token: str) -> dict:
        if not isinstance(token, str) or len(token) < 20:
            raise Denied("SESSION_INVALID", 401)
        r = t.execute("SELECT * FROM license_sessions WHERE token_hash=?", (sec.sha256(token),)).fetchone()
        if not r:
            raise Denied("SESSION_INVALID", 401)
        return dict(r)

    def heartbeat(self, token: str, *, boot_id: str, telemetry: dict | None = None, ip: str | None = None) -> dict:
        """Renews the lease of THIS run. Fails (and the client stops protected modules) when the license expired, was
        revoked, the session was terminated, or - after a lapse - another run took the slot."""
        self._no_anomaly()
        now = self.now()
        with self.db.tx() as t:
            s = self._session_by_token(t, token)
            self.limit("client_heartbeat", s["id"])
            if s["boot_id"] != boot_id:
                raise Denied("SESSION_INVALID", 401)
            if s["ended_at"]:
                raise Denied({"LICENSE_REVOKED": "LICENSE_REVOKED", "ADMIN_TERMINATED": "SESSION_TERMINATED"}.get(s["end_reason"], "SESSION_ENDED"), 403)
            lic = dict(t.execute("SELECT * FROM licenses WHERE id=?", (s["license_id"],)).fetchone())
            code = None
            if lic["revoked_at"]:
                code = "LICENSE_REVOKED"
            elif now >= lic["expires_at"]:
                code = "LICENSE_EXPIRED"
            elif s["lease_expires_at"] <= now and self._active_sessions(t, lic["id"], now, exclude=s["id"]) >= int(lic["max_sessions"]):
                code = "SESSION_LIMIT_REACHED"          # this run lapsed and another run took the slot
            if code:
                t.execute("UPDATE license_sessions SET ended_at=?, end_reason=? WHERE id=?", (now, code, s["id"]))
                self.audit(t, actor="client", action="SESSION_RENEW", result=code, ttype="license", tid=lic["id"], detail={"session_id": s["id"]}, ip=ip)
                failed = code
            else:
                failed = None
                lease, exp = self._lease(lic, s, now)
                tel = json.loads(s["telemetry_json"] or "{}")
                upd_tel = None
                if telemetry and tel.get("opt_in"):
                    clean = {k: v for k, v in telemetry.items() if k in TELEMETRY_KEYS and isinstance(v, (int, float, str)) and len(str(v)) <= 60}
                    upd_tel = J({"opt_in": True, **clean})
                t.execute("UPDATE license_sessions SET lease_expires_at=?, last_seen_at=?, ip=?, telemetry_json=COALESCE(?, telemetry_json), "
                          "telemetry_at=CASE WHEN ? IS NULL THEN telemetry_at ELSE ? END WHERE id=?",
                          (exp, now, ip, upd_tel, upd_tel, now, s["id"]))
                t.execute("UPDATE licenses SET last_used_at=? WHERE id=?", (now, lic["id"]))
        if failed:
            raise Denied(failed, 403)
        return {"lease": lease, "lease_expires_at": exp, "license_expires_at": lic["expires_at"], "server_time": now}

    def end_session(self, token: str, *, boot_id: str, ip: str | None = None) -> dict:
        now = self.now()
        with self.db.tx() as t:
            s = self._session_by_token(t, token)
            if s["boot_id"] != boot_id:
                raise Denied("SESSION_INVALID", 401)
            if not s["ended_at"]:
                t.execute("UPDATE license_sessions SET ended_at=?, end_reason='CLIENT_EXIT' WHERE id=?", (now, s["id"]))
                self.audit(t, actor="client", action="SESSION_END", ttype="license", tid=s["license_id"], detail={"session_id": s["id"]}, ip=ip)
        return {"ok": True}

    def terminate_session(self, actor: dict, sid: str, ip: str | None = None) -> dict:
        self._require(actor, "ADMIN")
        now = self.now()
        with self.db.tx() as t:
            s = t.execute("SELECT * FROM license_sessions WHERE id=?", (sid,)).fetchone()
            if not s:
                raise Denied("SESSION_NOT_FOUND", 404)
            if not s["ended_at"]:
                t.execute("UPDATE license_sessions SET ended_at=?, end_reason='ADMIN_TERMINATED' WHERE id=?", (now, sid))
            self.audit(t, actor=actor["email"], action="SESSION_TERMINATE", ttype="session", tid=sid, detail={"license_id": s["license_id"]}, ip=ip)
        return {"ok": True}

    def list_sessions(self, *, active_only: bool = True, license_id: str | None = None, limit: int = 300) -> list[dict]:
        now = self.now()
        sql = "SELECT s.*, l.key_hint, l.customer_id FROM license_sessions s JOIN licenses l ON l.id=s.license_id WHERE 1=1"
        args: list = []
        if active_only:
            sql += " AND s.ended_at IS NULL AND s.lease_expires_at>?"
            args.append(now)
        if license_id:
            sql += " AND s.license_id=?"
            args.append(license_id)
        rows = self.db.all(sql + " ORDER BY s.created_at DESC LIMIT ?", (*args, min(int(limit), 1000)))
        for r in rows:
            r.pop("token_hash", None)
            r["state"] = "ZAKONCZONA" if r["ended_at"] else ("AKTYWNA" if r["lease_expires_at"] > now else "WYGASLA_DZIERZAWA")
            tel = json.loads(r.pop("telemetry_json") or "{}")
            r["telemetry_opt_in"] = bool(tel.pop("opt_in", False))
            r["telemetry"] = tel or None
        return rows

    # ================================================================= summary / audit / telemetry
    def summary(self) -> dict:
        now = self.now()
        lic = self.db.all("SELECT * FROM licenses")
        st = [license_status(x, now) for x in lic]
        return {"server_time": now, "license_seconds": int(self.s.license_seconds), "lease_seconds": int(self.s.lease_seconds),
                "licenses_active": st.count("AKTYWNA"), "licenses_expired": st.count("WYGASLA"), "licenses_revoked": st.count("COFNIETA"),
                "expiring_6h": sum(1 for x, s in zip(lic, st) if s == "AKTYWNA" and x["expires_at"] - now <= 6 * 3600),
                "created_24h": sum(1 for x in lic if x["created_at"] >= now - 86400),
                "sessions_active": self.db.one("SELECT COUNT(*) AS n FROM license_sessions WHERE ended_at IS NULL AND lease_expires_at>?", (now,))["n"],
                "denied_24h": self.db.one("SELECT COUNT(*) AS n FROM audit WHERE action='SESSION_OPEN' AND result<>'OK' AND at>=?", (now - 86400,))["n"],
                "customers": self.db.one("SELECT COUNT(*) AS n FROM customers")["n"], "clock_anomaly": getattr(self.clock, "anomaly", None),
                "kid": self.kid, "db_migrations": self.db.versions(), "recent_events": self.list_audit(limit=10)}

    def list_audit(self, *, limit: int = 300, action: str | None = None) -> list[dict]:
        if action:
            return self.db.all("SELECT * FROM audit WHERE action=? ORDER BY id DESC LIMIT ?", (action, min(int(limit), 2000)))
        return self.db.all("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (min(int(limit), 2000),))

    def telemetry(self) -> list[dict]:
        """Latest opt-in telemetry per license (only what the client chose to send; customer must allow statistics)."""
        rows = self.db.all("""SELECT s.license_id, s.telemetry_json, s.telemetry_at, l.key_hint, c.name AS customer_name, c.stats_allowed
                              FROM license_sessions s JOIN licenses l ON l.id=s.license_id LEFT JOIN customers c ON c.id=l.customer_id
                              WHERE s.telemetry_at IS NOT NULL ORDER BY s.telemetry_at DESC""")
        seen, out = set(), []
        for r in rows:
            if r["license_id"] in seen or not r["stats_allowed"]:
                continue
            seen.add(r["license_id"])
            tel = json.loads(r["telemetry_json"] or "{}")
            tel.pop("opt_in", None)
            out.append({"license_id": r["license_id"], "key_hint": r["key_hint"], "customer_name": r["customer_name"], "at": r["telemetry_at"], **tel})
        return out

    # ================================================================= administrators
    @staticmethod
    def _require(actor: dict | None, role: str) -> None:
        if not actor:
            raise Denied("NOT_AUTHENTICATED", 401)
        if role == "ADMIN" and actor.get("role") != "ADMIN":
            raise Denied("FORBIDDEN_ROLE", 403)

    def admins_exist(self) -> bool:
        return bool(self.db.one("SELECT 1 AS x FROM admins LIMIT 1"))

    def add_admin(self, email: str, password: str, role: str = "ADMIN", *, actor: str = "cli", bootstrap: bool = False) -> dict:
        """CLI only (bootstrap / add-admin). Returns the TOTP secret and recovery codes ONCE."""
        email = (email or "").strip().lower()
        if "@" not in email or len(email) > 200:
            raise Denied("EMAIL_INVALID", 400)
        if role not in ("ADMIN", "VIEWER"):
            raise Denied("ROLE_INVALID", 400)
        probs = sec.password_problems(password, email)
        if probs:
            raise Denied("PASSWORD_WEAK", 400, {"problems": probs})
        totp = sec.new_totp_secret()
        codes = sec.recovery_codes()
        aid = sec.new_id()
        now = self.now()
        with self.db.tx() as t:
            if bootstrap and t.execute("SELECT 1 FROM admins LIMIT 1").fetchone():
                raise Denied("ALREADY_BOOTSTRAPPED", 409)
            if t.execute("SELECT 1 FROM admins WHERE email=?", (email,)).fetchone():
                raise Denied("EMAIL_TAKEN", 409)
            t.execute("""INSERT INTO admins(id, email, password_hash, role, totp_secret_enc, recovery_json, created_at, password_changed_at)
                         VALUES (?,?,?,?,?,?,?,?)""",
                      (aid, email, sec.hash_password(password), role, self.fernet.encrypt(totp.encode()).decode(), J([sec.sha256(c) for c in codes]), now, now))
            self.audit(t, actor=actor, action="ADMIN_BOOTSTRAP" if bootstrap else "ADMIN_ADD", ttype="admin", tid=aid, detail={"email": email, "role": role})
        import pyotp
        return {"id": aid, "email": email, "role": role, "totp_secret": totp,
                "otpauth_uri": pyotp.TOTP(totp).provisioning_uri(name=email, issuer_name="MasterQUO Licencje"), "recovery_codes": codes}

    def reset_mfa(self, email: str, *, actor: str = "cli") -> dict:
        a = self.db.one("SELECT * FROM admins WHERE email=?", ((email or "").strip().lower(),))
        if not a:
            raise Denied("ADMIN_NOT_FOUND", 404)
        totp = sec.new_totp_secret()
        codes = sec.recovery_codes()
        with self.db.tx() as t:
            t.execute("UPDATE admins SET totp_secret_enc=?, recovery_json=?, failed_logins=0, locked_until=0 WHERE id=?",
                      (self.fernet.encrypt(totp.encode()).decode(), J([sec.sha256(c) for c in codes]), a["id"]))
            t.execute("UPDATE admin_sessions SET revoked_at=? WHERE admin_id=? AND revoked_at IS NULL", (self.now(), a["id"]))
            self.audit(t, actor=actor, action="ADMIN_RESET_MFA", ttype="admin", tid=a["id"])
        import pyotp
        return {"email": a["email"], "totp_secret": totp, "otpauth_uri": pyotp.TOTP(totp).provisioning_uri(name=a["email"], issuer_name="MasterQUO Licencje"),
                "recovery_codes": codes}

    def set_admin_status(self, email: str, status: str, *, actor: str = "cli") -> None:
        if status not in ("ACTIVE", "DISABLED"):
            raise Denied("STATUS_INVALID", 400)
        a = self.db.one("SELECT * FROM admins WHERE email=?", ((email or "").strip().lower(),))
        if not a:
            raise Denied("ADMIN_NOT_FOUND", 404)
        with self.db.tx() as t:
            t.execute("UPDATE admins SET status=? WHERE id=?", (status, a["id"]))
            if status == "DISABLED":
                t.execute("UPDATE admin_sessions SET revoked_at=? WHERE admin_id=? AND revoked_at IS NULL", (self.now(), a["id"]))
            self.audit(t, actor=actor, action=f"ADMIN_{status}", ttype="admin", tid=a["id"])

    def login(self, email: str, password: str, code: str, *, ip: str | None = None, ua: str | None = None) -> dict:
        """Password (Argon2id) + TOTP (or a one-time recovery code). Same error for every failure reason."""
        email = (email or "").strip().lower()[:200]
        self.limit("admin_login_ip", ip or "-")
        self.limit("admin_login_email", email or "-")
        now = self.now()
        a = self.db.one("SELECT * FROM admins WHERE email=?", (email,))
        pw_ok = sec.verify_password(a["password_hash"] if a else None, password or "")
        ok = False
        used_recovery = None
        if a and pw_ok and a["status"] == "ACTIVE" and a["locked_until"] <= now:
            secret = self.fernet.decrypt(a["totp_secret_enc"].encode()).decode()
            if sec.totp_ok(secret, code, now):
                ok = True
            else:
                hashes = json.loads(a["recovery_json"] or "[]")
                h = sec.sha256((code or "").strip().lower())
                if h in hashes:
                    ok, used_recovery = True, [x for x in hashes if x != h]
        if not ok:
            if a:
                fl = a["failed_logins"] + 1
                self.db.x("UPDATE admins SET failed_logins=?, locked_until=? WHERE id=?", (fl, now + 900 if fl >= 5 else a["locked_until"], a["id"]))
            self.audit(None, actor=email or "-", action="ADMIN_LOGIN", result="DENIED", ip=ip)
            raise Denied("LOGIN_FAILED", 401)
        sid = sec.token()
        csrf = sec.token()
        with self.db.tx() as t:
            if used_recovery is not None:
                t.execute("UPDATE admins SET recovery_json=? WHERE id=?", (J(used_recovery), a["id"]))
            if sec.needs_rehash(a["password_hash"]):
                t.execute("UPDATE admins SET password_hash=? WHERE id=?", (sec.hash_password(password), a["id"]))
            t.execute("UPDATE admins SET failed_logins=0, locked_until=0, last_login_at=? WHERE id=?", (now, a["id"]))
            t.execute("""INSERT INTO admin_sessions(id_hash, admin_id, csrf, created_at, expires_at, last_seen_at, ip, user_agent)
                         VALUES (?,?,?,?,?,?,?,?)""", (sec.sha256(sid), a["id"], csrf, now, now + 60 * int(self.s.admin_session_minutes), now, ip, (ua or "")[:200]))
            self.audit(t, actor=email, action="ADMIN_LOGIN", detail={"recovery_code": used_recovery is not None}, ip=ip)
        return {"sid": sid, "csrf": csrf, "admin": {"id": a["id"], "email": a["email"], "role": a["role"]},
                "expires_at": now + 60 * int(self.s.admin_session_minutes)}

    def auth(self, sid: str | None) -> dict:
        if not sid:
            raise Denied("NOT_AUTHENTICATED", 401)
        now = self.now()
        s = self.db.one("""SELECT s.*, a.email, a.role, a.status FROM admin_sessions s JOIN admins a ON a.id=s.admin_id WHERE s.id_hash=?""",
                        (sec.sha256(sid),))
        if not s or s["revoked_at"] or s["expires_at"] <= now or s["status"] != "ACTIVE":
            raise Denied("NOT_AUTHENTICATED", 401)
        if now - s["last_seen_at"] > 30:
            self.db.x("UPDATE admin_sessions SET last_seen_at=? WHERE id_hash=?", (now, s["id_hash"]))
        return {"id": s["admin_id"], "email": s["email"], "role": s["role"], "csrf": s["csrf"], "session_expires_at": s["expires_at"]}

    def logout(self, sid: str | None) -> None:
        if sid:
            self.db.x("UPDATE admin_sessions SET revoked_at=? WHERE id_hash=? AND revoked_at IS NULL", (self.now(), sec.sha256(sid)))

    def change_password(self, actor: dict, old: str, new: str, ip: str | None = None) -> None:
        a = self.db.one("SELECT * FROM admins WHERE id=?", (actor["id"],))
        if not a or not sec.verify_password(a["password_hash"], old or ""):
            raise Denied("LOGIN_FAILED", 401)
        probs = sec.password_problems(new, a["email"])
        if probs:
            raise Denied("PASSWORD_WEAK", 400, {"problems": probs})
        with self.db.tx() as t:
            t.execute("UPDATE admins SET password_hash=?, password_changed_at=? WHERE id=?", (sec.hash_password(new), self.now(), a["id"]))
            self.audit(t, actor=a["email"], action="ADMIN_PASSWORD_CHANGE", ttype="admin", tid=a["id"], ip=ip)

    def list_admins(self) -> list[dict]:
        return self.db.all("SELECT id, email, role, status, created_at, last_login_at FROM admins ORDER BY created_at")
