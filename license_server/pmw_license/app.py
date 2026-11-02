"""License API (FastAPI). Public: health, public key, activate, validate. Admin (bearer session after login): create / list /
get / revoke / reset-device, stats, audit, logout. Every privileged action is authorized here - nothing is trusted from a
client UI. JSON errors: {"error": {"code", "message"}}; plaintext keys / tokens / passwords are never logged."""
from __future__ import annotations

import hmac
import logging
import time

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from . import VERSION
from . import protocol as P
from .config import Settings
from .security import RateLimiter, new_token, token_hash, verify_password
from .service import LicenseError, LicenseService
from .signing import Signer
from .store import Store

log = logging.getLogger("pmw_license")
MAX_BODY = 4096


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ActivateReq(_M):
    license_key: str = Field(min_length=10, max_length=64)
    hwid_hash: str = Field(min_length=64, max_length=64)
    nonce: str = Field(min_length=16, max_length=64)
    client_version: str = Field("", max_length=32)


class ValidateReq(_M):
    license_id: str = Field(min_length=20, max_length=20)
    hwid_hash: str = Field(min_length=64, max_length=64)
    token: str = Field(min_length=32, max_length=128)
    nonce: str = Field(min_length=16, max_length=64)
    client_version: str = Field("", max_length=32)


class LoginReq(_M):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class CreateReq(_M):
    duration: str = Field(pattern=r"^(24h|72h|7d|31d)$")
    note: str | None = Field(None, max_length=200)


class ReasonReq(_M):
    reason: str | None = Field(None, max_length=200)


def err(code: str, message: str | None = None, http: int | None = None) -> JSONResponse:
    e = LicenseError(code, message)
    return JSONResponse({"error": {"code": e.code, "message": e.message}}, status_code=http or e.http)


def create_app(settings: Settings | None = None, *, clock=time.time, signer: Signer | None = None, store: Store | None = None,
               limiter: RateLimiter | None = None) -> FastAPI:
    s = settings or Settings()
    probs = s.problems() if signer is None else [p for p in s.problems() if "klucza podpisu" not in p]
    if probs and s.env == "production":
        raise RuntimeError("Konfiguracja serwera licencji niekompletna:\n- " + "\n- ".join(probs))
    signer = signer or Signer.load(s.signing_key)
    store = store or Store(s.database)
    svc = LicenseService(store, signer, s.key_pepper, clock=clock)
    rl = limiter or RateLimiter()
    app = FastAPI(title="PepeMarketWizard License API", version=VERSION, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.svc, app.state.store, app.state.signer = svc, store, signer

    def ip_of(req: Request) -> str:
        if s.trust_proxy:
            fwd = req.headers.get("x-forwarded-for")
            if fwd:
                return fwd.split(",")[-1].strip()[:64]
        return (req.client.host if req.client else "?")[:64]

    @app.middleware("http")
    async def limits(req: Request, call_next):
        cl = req.headers.get("content-length")
        if cl and (not cl.isdigit() or int(cl) > MAX_BODY):
            return err(P.INVALID_REQUEST, "zapytanie za duże", 413)
        resp = await call_next(req)
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        return resp

    @app.exception_handler(RequestValidationError)
    async def bad_request(_req, _exc):
        return err(P.INVALID_REQUEST)

    @app.exception_handler(LicenseError)
    async def license_error(_req, exc: LicenseError):
        return err(exc.code, exc.message)

    def limit(req: Request, bucket: str, n: int) -> None:
        if not rl.allow(bucket, ip_of(req), n):
            store.audit(clock(), "client", "RATE_LIMITED", ok=False, ip=ip_of(req), details={"bucket": bucket})
            raise LicenseError(P.RATE_LIMITED)

    # ------------------------------------------------------------------ public
    @app.get("/health")
    def health():
        return {"status": "ok", "service": "pmw-license", "version": VERSION, "server_time": P.utc_iso(clock())}

    @app.get("/api/v1/public-key")
    def public_key():
        return {"alg": "Ed25519", "kid": signer.kid, "public_key": signer.public_b64, "protocol": P.PROTOCOL_VERSION}

    @app.post("/api/v1/licenses/activate")
    def activate(body: ActivateReq, req: Request):
        limit(req, "activate", max(1, s.rate_public_per_min // 3))      # activation is rarer than validation: tighter limit
        return svc.activate(body.license_key, body.hwid_hash, nonce=body.nonce, client_version=body.client_version, ip=ip_of(req))

    @app.post("/api/v1/licenses/validate")
    def validate(body: ValidateReq, req: Request):
        limit(req, "validate", s.rate_public_per_min)
        return svc.validate(body.license_id, body.hwid_hash, body.token, nonce=body.nonce, client_version=body.client_version, ip=ip_of(req))

    # ------------------------------------------------------------------ admin
    @app.post("/api/v1/admin/login")
    def login(body: LoginReq, req: Request):
        limit(req, "login", s.rate_login_per_min)
        now = clock()
        user_ok = bool(s.admin_user) and hmac.compare_digest(body.username.encode(), s.admin_user.encode())
        pass_ok = verify_password(body.password, s.admin_password_hash) if s.admin_password_hash else False
        if not (user_ok and pass_ok):
            store.audit(now, body.username[:64] or "?", "ADMIN_LOGIN", ok=False, ip=ip_of(req))
            raise LicenseError(P.UNAUTHORIZED, "nieprawidłowy login lub hasło")
        tok = new_token()
        exp = now + s.admin_session_hours * 3600
        with store.tx() as c:
            c.execute("DELETE FROM admin_sessions WHERE expires_at < ?", (now,))
            c.execute("INSERT INTO admin_sessions(token_hash, username, created_at, expires_at, ip) VALUES (?,?,?,?,?)",
                      (token_hash(tok), s.admin_user, now, exp, ip_of(req)))
            store.audit(now, s.admin_user, "ADMIN_LOGIN", ok=True, ip=ip_of(req), conn=c)
        return {"token": tok, "expires_at": P.utc_iso(exp), "username": s.admin_user}

    def admin(req: Request, authorization: str | None = Header(None)) -> str:
        if not authorization or not authorization.startswith("Bearer ") or len(authorization) > 300:
            store.audit(clock(), "?", "ADMIN_UNAUTHORIZED", ok=False, ip=ip_of(req), details={"path": req.url.path})
            raise LicenseError(P.UNAUTHORIZED)
        r = store.one("SELECT username, expires_at FROM admin_sessions WHERE token_hash=?", (token_hash(authorization[7:].strip()),))
        if not r or r["expires_at"] <= clock():
            store.audit(clock(), "?", "ADMIN_UNAUTHORIZED", ok=False, ip=ip_of(req), details={"path": req.url.path, "why": "session"})
            raise LicenseError(P.UNAUTHORIZED, "sesja administratora wygasła – zaloguj się ponownie")
        return r["username"]

    @app.post("/api/v1/admin/logout")
    def logout(req: Request, user: str = Depends(admin), authorization: str | None = Header(None)):
        with store.tx() as c:
            c.execute("DELETE FROM admin_sessions WHERE token_hash=?", (token_hash(authorization[7:].strip()),))
            store.audit(clock(), user, "ADMIN_LOGOUT", ip=ip_of(req), conn=c)
        return {"ok": True}

    @app.post("/api/v1/admin/licenses")
    def create(body: CreateReq, req: Request, user: str = Depends(admin)):
        return svc.create(body.duration, actor=user, note=body.note, ip=ip_of(req))

    @app.get("/api/v1/admin/licenses")
    def list_(status: str | None = None, duration: str | None = None, q: str | None = None, limit: int = 50, offset: int = 0,
              user: str = Depends(admin)):
        if (status and status not in P.STATUSES) or (duration and duration not in P.DURATIONS) or (q and len(q) > 64):
            raise LicenseError(P.INVALID_REQUEST)
        return svc.list(status=status, duration=duration, q=q, limit=limit, offset=offset)

    @app.get("/api/v1/admin/licenses/{license_id}")
    def get(license_id: str, user: str = Depends(admin)):
        if not P.LICENSE_ID_RE.match(license_id):
            raise LicenseError(P.NOT_FOUND)
        return svc.get(license_id)

    @app.post("/api/v1/admin/licenses/{license_id}/revoke")
    def revoke(license_id: str, req: Request, body: ReasonReq | None = None, user: str = Depends(admin)):
        if not P.LICENSE_ID_RE.match(license_id):
            raise LicenseError(P.NOT_FOUND)
        return svc.revoke(license_id, actor=user, reason=(body.reason if body else None), ip=ip_of(req))

    @app.post("/api/v1/admin/licenses/{license_id}/reset-device")
    def reset_device(license_id: str, req: Request, body: ReasonReq | None = None, user: str = Depends(admin)):
        if not P.LICENSE_ID_RE.match(license_id):
            raise LicenseError(P.NOT_FOUND)
        return svc.reset_device(license_id, actor=user, reason=(body.reason if body else None), ip=ip_of(req))

    @app.get("/api/v1/admin/stats")
    def stats(user: str = Depends(admin)):
        return svc.stats()

    @app.get("/api/v1/admin/audit")
    def audit(limit: int = 100, license_id: str | None = None, user: str = Depends(admin)):
        return {"items": svc.audit_log(limit, license_id)}

    return app
