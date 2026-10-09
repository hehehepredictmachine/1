"""HTTP API of the central server + static admin app (/admin/) and account pages (/account/).

Auth mechanisms:
* browser (admin app, account pages): server-side session, cookie HttpOnly + Secure + SameSite=Strict, CSRF token in the
  X-CSRF header for every state-changing request, Origin check, session id rotated after login / MFA;
* bot client (local MasterQUO backend acting for the logged-in user): bearer CLIENT session token (kept in RAM only);
* device (license heartbeat, operation authorization, telemetry): Ed25519 signature over a single-use server nonce.
Deny by default: every route declares which of these it accepts.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from .service import Central, Denied

log = logging.getLogger("mqcentral.api")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")      # e.g. a "role" field in the registration request is REJECTED


class RegisterReq(Strict):
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)
    display_name: str | None = Field(default=None, max_length=80)


class TokenReq(Strict):
    token: str = Field(max_length=200)


class EmailReq(Strict):
    email: str = Field(max_length=254)


class LoginReq(Strict):
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)
    client: str = Field(default="web", pattern="^(web|bot)$")
    totp: str | None = Field(default=None, max_length=40)


class MfaReq(Strict):
    code: str = Field(max_length=40)


class ChangePwReq(Strict):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


class ResetReq(Strict):
    token: str = Field(max_length=200)
    new_password: str = Field(max_length=256)


class ActivateReq(Strict):
    key: str = Field(max_length=120)
    public_key: str = Field(max_length=400)
    install_id: str = Field(max_length=64)
    device_name: str | None = Field(default=None, max_length=80)
    nonce: str = Field(max_length=100)
    signature: str = Field(max_length=200)


class AuthorizeReq(Strict):
    intent_id: str = Field(max_length=200)
    op: str = Field(pattern="^OPEN$")
    symbol: str | None = Field(default=None, max_length=40)
    side: str | None = Field(default=None, max_length=8)
    volume: float | None = None
    mode: str | None = Field(default=None, max_length=20)


class LinkReq(Strict):
    server: str = Field(max_length=120)
    login: str = Field(max_length=40)
    company: str | None = Field(default=None, max_length=120)
    trade_mode: str = Field(pattern="^(DEMO|REAL|CONTEST)$")
    currency: str = Field(max_length=8)
    currency_digits: int = Field(default=2, ge=0, le=8)
    bot_magic: int | None = None
    consent: bool


class SnapshotReq(Strict):
    account_id: str = Field(max_length=40)
    seq: int = Field(ge=0)
    measured_ms: int
    balance: float
    equity: float
    margin: float | None = None
    margin_free: float | None = None
    currency: str = Field(max_length=8)


class DealsReq(Strict):
    account_id: str = Field(max_length=40)
    batch_id: str | None = Field(default=None, max_length=80)
    deals: list[dict] = Field(default_factory=list, max_length=1000)
    import_: dict | None = Field(default=None, alias="import")
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ChallengeReq(Strict):
    purpose: str = Field(pattern="^(ACTIVATE|DEVICE)$")
    device_id: str | None = Field(default=None, max_length=40)


class InviteReq(Strict):
    email: str = Field(max_length=254)
    display_name: str | None = Field(default=None, max_length=80)


class ReasonReq(Strict):
    reason: str | None = Field(default=None, max_length=200)


class GenLicenseReq(Strict):
    user_id: str = Field(max_length=40)
    note: str | None = Field(default=None, max_length=200)


def parse(model, raw: bytes):
    """Device endpoints read the raw (signed) body: validate it strictly; unknown fields -> 422."""
    from pydantic import ValidationError
    try:
        return model.model_validate_json(raw or b"{}")
    except ValidationError as e:
        raise HTTPException(422, detail=[{"msg": x["msg"], "loc": x["loc"]} for x in e.errors()][:5]) from None


def create_app(central: Central) -> FastAPI:
    s = central.s
    app = FastAPI(title="MasterQUO Central", docs_url="/api/docs" if s.dev else None, redoc_url=None, openapi_url="/api/openapi.json" if s.dev else None)
    cookie_name = "__Host-mq_sess" if s.secure_cookies else "mq_sess"
    origins = set(s.allowed_origins)

    def ip_of(req: Request) -> str:
        if s.trusted_proxy and req.headers.get("x-forwarded-for"):
            return req.headers["x-forwarded-for"].split(",")[0].strip()
        return req.client.host if req.client else "?"

    @app.exception_handler(Denied)
    async def denied(_req: Request, exc: Denied):
        return JSONResponse({"error": exc.code, **({"detail": exc.detail} if exc.detail else {})}, status_code=exc.status,
                            headers={"Retry-After": "60"} if exc.status == 429 else None)

    @app.middleware("http")
    async def guard(req: Request, call_next):
        cl = req.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > s.max_body_bytes:
            return JSONResponse({"error": "BODY_TOO_LARGE"}, status_code=413)
        # cookie-authenticated, state-changing requests: Origin must be ours (+ CSRF checked per route)
        if req.method not in ("GET", "HEAD", "OPTIONS") and req.cookies.get(cookie_name) and not req.headers.get("authorization"):
            o = (req.headers.get("origin") or "").rstrip("/")
            if o not in origins:
                return JSONResponse({"error": "ORIGIN_NOT_ALLOWED"}, status_code=403)
        resp = await call_next(req)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Cache-Control"] = "no-store" if req.url.path.startswith("/api/") else resp.headers.get("Cache-Control", "no-cache")
        resp.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'"
        if s.secure_cookies:
            resp.headers["Strict-Transport-Security"] = "max-age=31536000"
        return resp

    # ------------------------------------------------------------ identity dependencies
    def set_cookie(resp: Response, raw: str) -> None:
        resp.set_cookie(cookie_name, raw, httponly=True, secure=s.secure_cookies, samesite="strict", path="/", max_age=s.session_hours_web * 3600)

    def web_session(req: Request, x_csrf: str | None = Header(default=None)):
        raw = req.cookies.get(cookie_name)
        sess, u = central.authenticate(raw, kind="WEB")
        if req.method not in ("GET", "HEAD") and (not x_csrf or not sess["csrf"] or not __import__("hmac").compare_digest(x_csrf, sess["csrf"])):
            raise Denied("CSRF_INVALID", 403)
        return sess, u

    def user_any(req: Request, authorization: str | None = Header(default=None), x_csrf: str | None = Header(default=None)):
        """Bot client bearer token OR browser session (+CSRF)."""
        if authorization and authorization.startswith("Bearer "):
            return central.authenticate(authorization[7:], kind="CLIENT")
        return web_session(req, x_csrf)

    def admin(ctx=Depends(web_session)):
        sess, u = ctx
        if u["role"] != "ADMIN" or not sess["mfa_ok"]:
            raise Denied("ADMIN_ONLY", 403)                 # also hides whether the resource exists
        return sess, u

    async def device(req: Request, x_mq_device: str | None = Header(default=None), x_mq_nonce: str | None = Header(default=None),
                     x_mq_sig: str | None = Header(default=None)):
        body = await req.body()
        return central.device_auth(x_mq_device or "", x_mq_nonce or "", x_mq_sig or "", req.method, req.url.path, body)

    # ------------------------------------------------------------ public
    @app.get("/api/v1/health")
    def health():
        return {"ok": True, "server_time": central.now(), "clock_anomaly": central.clock.anomaly, "dev": s.dev}

    @app.get("/api/v1/keys")
    def keys():
        return {"issuer": s.issuer, "keys": [{"kid": central.kid, "alg": "EdDSA", "pem": central.public_pem}]}

    @app.post("/api/v1/auth/register", status_code=202)
    def register(r: RegisterReq, req: Request):
        central.register(r.email, r.password, r.display_name, ip_of(req))
        return {"ok": True, "message": "Jeżeli adres jest poprawny, wysłaliśmy wiadomość z dalszymi krokami."}

    @app.post("/api/v1/auth/verify-email")
    def verify(r: TokenReq):
        central.verify_email(r.token)
        return {"ok": True}

    @app.post("/api/v1/auth/resend-verification", status_code=202)
    def resend(r: EmailReq, req: Request):
        central.resend_verification(r.email, ip_of(req))
        return {"ok": True}

    @app.post("/api/v1/auth/login")
    def login(r: LoginReq, req: Request, resp: Response):
        kind = "CLIENT" if r.client == "bot" else "WEB"
        if kind == "WEB" and (req.headers.get("origin") or "").rstrip("/") not in origins:
            raise Denied("ORIGIN_NOT_ALLOWED", 403)          # login CSRF
        out = central.login(r.email, r.password, kind=kind, ip=ip_of(req), ua=req.headers.get("user-agent", ""), totp=r.totp)
        if kind == "WEB":
            set_cookie(resp, out["token"])
            return {"mfa_required": out["mfa_required"], "csrf": out["csrf"], "user": out["user"]}
        return {"token": out["token"], "user": out["user"]}

    @app.post("/api/v1/auth/mfa")
    def mfa(r: MfaReq, req: Request, resp: Response):
        if (req.headers.get("origin") or "").rstrip("/") not in origins:
            raise Denied("ORIGIN_NOT_ALLOWED", 403)
        out = central.complete_mfa(req.cookies.get(cookie_name), r.code, ip_of(req))
        set_cookie(resp, out["token"])
        return {"csrf": out["csrf"], "user": out["user"]}

    @app.get("/api/v1/auth/session")
    def session(req: Request):
        sess, u = central.authenticate(req.cookies.get(cookie_name), kind="WEB", need_mfa=False)
        return {"user": central.public_user(u), "csrf": sess["csrf"], "mfa_ok": bool(sess["mfa_ok"])}

    @app.post("/api/v1/auth/logout")
    def logout(req: Request, resp: Response, authorization: str | None = Header(default=None)):
        central.logout(authorization[7:] if authorization and authorization.startswith("Bearer ") else req.cookies.get(cookie_name))
        resp.delete_cookie(cookie_name, path="/")
        return {"ok": True}

    @app.post("/api/v1/auth/password/change")
    def change_pw(r: ChangePwReq, req: Request, ctx=Depends(user_any)):
        central.change_password(ctx[0], ctx[1], r.current_password, r.new_password, ip_of(req))
        return {"ok": True, "note": "Pozostałe sesje zostały wylogowane. Poświadczenie urządzenia bota pozostaje ważne."}

    @app.post("/api/v1/auth/password/forgot", status_code=202)
    def forgot(r: EmailReq, req: Request):
        central.forgot_password(r.email, ip_of(req))
        return {"ok": True, "message": "Jeżeli konto istnieje, wysłaliśmy link do ustawienia hasła."}

    @app.post("/api/v1/auth/password/reset")
    def reset(r: ResetReq, req: Request):
        central.reset_password(r.token, r.new_password, ip_of(req))
        return {"ok": True}

    # ------------------------------------------------------------ user (own data only - ids come from the session)
    @app.get("/api/v1/me")
    def me(ctx=Depends(user_any)):
        return central.me(ctx[1])

    @app.get("/api/v1/me/stats")
    def my_stats(account_id: str, range: str = "30d", scope: str = "ACCOUNT", symbol: str | None = None,
                 since_ms: int | None = None, until_ms: int | None = None, ctx=Depends(user_any)):
        acc = central.db.one("SELECT user_id FROM trading_accounts WHERE id=?", (account_id,))
        if not acc or acc["user_id"] != ctx[1]["id"]:
            raise Denied("NOT_FOUND", 404)                   # same answer for "foreign" and "missing"
        return central.account_stats(account_id, rng=range, scope=scope, symbol=symbol, since_ms=since_ms, until_ms=until_ms)

    @app.post("/api/v1/device/challenge")
    def challenge(r: ChallengeReq, req: Request, authorization: str | None = Header(default=None)):
        if r.purpose == "ACTIVATE":
            if not authorization or not authorization.startswith("Bearer "):
                raise Denied("NOT_AUTHENTICATED", 401)
            _s, u = central.authenticate(authorization[7:], kind="CLIENT")
            return central.challenge("ACTIVATE", user_id=u["id"], ip=ip_of(req))
        if not r.device_id or not central.db.one("SELECT 1 AS x FROM devices WHERE id=?", (r.device_id,)):
            raise Denied("DEVICE_UNKNOWN", 401)
        return central.challenge("DEVICE", device_id=r.device_id, ip=ip_of(req))

    @app.post("/api/v1/licenses/activate")
    def activate(r: ActivateReq, req: Request, authorization: str | None = Header(default=None)):
        if not authorization or not authorization.startswith("Bearer "):
            raise Denied("NOT_AUTHENTICATED", 401)
        _s, u = central.authenticate(authorization[7:], kind="CLIENT")
        return central.activate(u, r.key, r.public_key, r.install_id, r.device_name, r.nonce, r.signature, ip_of(req))

    # ------------------------------------------------------------ device-signed
    @app.post("/api/v1/device/heartbeat")
    def heartbeat(ctx=Depends(device)):
        return central.heartbeat(*ctx)

    @app.post("/api/v1/ops/authorize")
    async def authorize(req: Request, ctx=Depends(device)):
        r = parse(AuthorizeReq, await req.body())
        return central.authorize_op(ctx[0], ctx[1], r.intent_id, r.op, r.model_dump())

    @app.post("/api/v1/connector/link")
    async def link(req: Request, ctx=Depends(device)):
        r = parse(LinkReq, await req.body())
        return central.link_account(ctx[0], ctx[1], r.model_dump())

    @app.post("/api/v1/connector/unlink")
    def unlink(ctx=Depends(device)):
        central.unlink_account(*ctx)
        return {"ok": True}

    @app.post("/api/v1/telemetry/snapshot")
    async def snapshot(req: Request, ctx=Depends(device)):
        r = parse(SnapshotReq, await req.body())
        return central.snapshot(ctx[0], ctx[1], r.model_dump())

    @app.post("/api/v1/telemetry/deals")
    async def deals(req: Request, ctx=Depends(device)):
        r = parse(DealsReq, await req.body())
        b = r.model_dump(by_alias=True)
        return central.deals(ctx[0], ctx[1], b)

    @app.get("/api/v1/device/status")
    def device_status(ctx=Depends(device)):
        d, u = ctx
        acc = central.db.one("SELECT * FROM trading_accounts WHERE device_id=? AND unlinked_at IS NULL", (d["id"],))
        return {"device_id": d["id"], "account": central.account_view(acc) if acc else None}

    # ------------------------------------------------------------ admin (role ADMIN + MFA + CSRF)
    @app.get("/api/v1/admin/users")
    def a_users(q: str = "", status: str = "", license: str = "", sort: str = "created_at", dir: str = "desc",
                page: int = Query(1, ge=1), size: int = Query(25, ge=1, le=100), ctx=Depends(admin)):
        return central.admin_users(q=q, status=status, lic=license, sort=sort, desc=dir != "asc", page=page, size=size)

    @app.get("/api/v1/admin/users/{uid}")
    def a_user(uid: str, ctx=Depends(admin)):
        return central.admin_user(uid)

    @app.post("/api/v1/admin/users")
    def a_invite(r: InviteReq, req: Request, ctx=Depends(admin)):
        central.limit("admin_write", ctx[1]["id"])
        return central.admin_create_user(ctx[1], r.email, r.display_name, ip_of(req))

    @app.post("/api/v1/admin/users/{uid}/block")
    def a_block(uid: str, r: ReasonReq, req: Request, ctx=Depends(admin)):
        return central.admin_block(ctx[1], uid, True, r.reason, ip_of(req))

    @app.post("/api/v1/admin/users/{uid}/unblock")
    def a_unblock(uid: str, req: Request, ctx=Depends(admin)):
        return central.admin_block(ctx[1], uid, False, None, ip_of(req))

    @app.get("/api/v1/admin/licenses")
    def a_licenses(status: str = "", q: str = "", page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=200), ctx=Depends(admin)):
        return central.admin_licenses(status=status, q=q, page=page, size=size)

    @app.post("/api/v1/admin/licenses")
    def a_generate(r: GenLicenseReq, req: Request, ctx=Depends(admin)):
        central.limit("admin_write", ctx[1]["id"])
        return central.generate_license(ctx[1], r.user_id, r.note, ip_of(req))

    @app.post("/api/v1/admin/licenses/{lid}/revoke")
    def a_revoke(lid: str, r: ReasonReq, req: Request, ctx=Depends(admin)):
        return central.revoke_license(ctx[1], lid, r.reason, ip_of(req))

    @app.post("/api/v1/admin/activations/{aid}/release")
    def a_release(aid: str, r: ReasonReq, req: Request, ctx=Depends(admin)):
        return central.release_seat(ctx[1], aid, r.reason, ip_of(req))

    @app.post("/api/v1/admin/devices/{did}/revoke")
    def a_revoke_dev(did: str, r: ReasonReq, req: Request, ctx=Depends(admin)):
        central.revoke_device(ctx[1], did, r.reason, ip_of(req))
        return {"ok": True}

    @app.get("/api/v1/admin/accounts/{aid}/stats")
    def a_stats(aid: str, range: str = "30d", scope: str = "ACCOUNT", symbol: str | None = None, since_ms: int | None = None,
                until_ms: int | None = None, ctx=Depends(admin)):
        return central.account_stats(aid, rng=range, scope=scope, symbol=symbol or None, since_ms=since_ms, until_ms=until_ms)

    @app.get("/api/v1/admin/audit")
    def a_audit(page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=200), user_id: str | None = None, ctx=Depends(admin)):
        return central.admin_audit(page=page, size=size, user_id=user_id)

    @app.get("/api/v1/admin/system")
    def a_system(ctx=Depends(admin)):
        return {"server_time": central.now(), "clock_anomaly": central.clock.anomaly, "dev": s.dev, "mail_mode": s.mail_mode,
                "db": "PostgreSQL" if central.db.pg else "SQLite (tylko development)", "schema": central.db.versions(), "issuer": s.issuer}

    @app.get("/api/v1/admin/dev-outbox")
    def a_outbox(ctx=Depends(admin)):
        if not s.dev:
            raise Denied("NOT_FOUND", 404)
        return {"items": central.db.q("SELECT * FROM mail_outbox ORDER BY created_at DESC LIMIT 50"),
                "note": "DEV OUTBOX – e-maile NIE zostały wysłane (tylko środowisko developerskie)."}

    # ------------------------------------------------------------ static web (admin app + account pages)
    web = Path(s.admin_web_dir)

    def page(name: str):
        f = web / name
        if not f.exists():
            raise HTTPException(404, "admin-web not built (cd server/admin-web && npm run build)")
        return FileResponse(f, headers={"Cache-Control": "no-cache"})

    @app.get("/")
    def root():
        return RedirectResponse("/admin/")

    @app.get("/admin/")
    def admin_page():
        return page("admin.html")

    @app.get("/account/{rest:path}")
    def account_page(rest: str):
        return page("account.html")

    @app.get("/assets/{name:path}")
    def assets(name: str):
        f = (web / "assets" / name).resolve()
        if not str(f).startswith(str((web / "assets").resolve())) or not f.is_file():
            raise HTTPException(404)
        return FileResponse(f, headers={"Cache-Control": "public, max-age=31536000, immutable"})

    return app
