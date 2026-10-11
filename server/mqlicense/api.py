"""HTTP API of the license server + static administrator panel (/admin/).

Auth mechanisms (deny by default - every route declares what it accepts):
* client (MasterQUO started with masterquo_start): license key ONLY in the JSON body of POST /api/v1/client/session
  (never in the URL / query / headers), then the session token in the body of renew / end calls;
* administrator panel: server-side session, cookie HttpOnly + SameSite=Strict (+ Secure and __Host- prefix in production),
  CSRF token in the X-CSRF header for every state-changing request, Origin check, roles ADMIN / VIEWER.
Nothing secret is logged: uvicorn access logs are disabled by the CLI (`serve`), the app logs only audit codes.
"""
from __future__ import annotations

import hmac
import logging
from pathlib import Path

from fastapi import Depends, FastAPI, Header, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from . import VERSION
from .service import Denied, LicenseService

log = logging.getLogger("mqlicense.api")
STATIC = Path(__file__).resolve().parent / "static" / "admin"
MAX_BODY = 16 * 1024


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OpenReq(Strict):
    license_key: str = Field(max_length=120)
    boot_id: str = Field(min_length=16, max_length=80)
    nonce: str = Field(min_length=16, max_length=80)
    client_version: str | None = Field(default=None, max_length=40)
    client_label: str | None = Field(default=None, max_length=80)
    telemetry_opt_in: bool = False


class RenewReq(Strict):
    session_token: str = Field(max_length=120)
    boot_id: str = Field(min_length=16, max_length=80)
    telemetry: dict | None = None


class EndReq(Strict):
    session_token: str = Field(max_length=120)
    boot_id: str = Field(min_length=16, max_length=80)


class LoginReq(Strict):
    email: str = Field(max_length=200)
    password: str = Field(max_length=256)
    code: str = Field(max_length=40)


class CreateLicReq(Strict):
    customer_id: str | None = Field(default=None, max_length=40)
    note: str | None = Field(default=None, max_length=500)
    max_sessions: int | None = Field(default=None, ge=1, le=10)


class ReasonReq(Strict):
    reason: str = Field(min_length=1, max_length=300)


class MaxSessReq(Strict):
    max_sessions: int = Field(ge=1, le=10)


class AssignReq(Strict):
    customer_id: str | None = Field(default=None, max_length=40)
    note: str | None = Field(default=None, max_length=500)


class CustomerReq(Strict):
    name: str = Field(min_length=1, max_length=120)
    email: str | None = Field(default=None, max_length=200)
    mt5_login: str | None = Field(default=None, max_length=40)
    note: str | None = Field(default=None, max_length=500)
    stats_allowed: bool = False


class CustomerUpd(Strict):
    name: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=200)
    mt5_login: str | None = Field(default=None, max_length=40)
    note: str | None = Field(default=None, max_length=500)
    stats_allowed: bool | None = None


class PwReq(Strict):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


def create_app(svc: LicenseService) -> FastAPI:
    s = svc.s
    dev = s.env != "prod"
    app = FastAPI(title="MasterQUO License Server", version=VERSION, docs_url="/api/docs" if dev else None, redoc_url=None,
                  openapi_url="/api/openapi.json" if dev else None)
    cookie = "__Host-mql_admin" if s.secure_cookies else "mql_admin"
    origins = {o.rstrip("/") for o in s.allowed_origins} | ({s.public_url.rstrip("/")} if s.public_url else set())

    def ip_of(req: Request) -> str:
        if s.trust_proxy and req.headers.get("x-forwarded-for"):
            return req.headers["x-forwarded-for"].split(",")[0].strip()[:64]
        return req.client.host if req.client else "?"

    def origin_ok(req: Request) -> bool:
        o = (req.headers.get("origin") or "").rstrip("/")
        if o in origins:
            return True
        # same-origin request from the panel served by this server (no proxy rewriting the host)
        host = req.headers.get("host") or ""
        return bool(o) and o.split("://", 1)[-1] == host and (dev or o.startswith("https://"))

    @app.exception_handler(Denied)
    async def denied(_req: Request, exc: Denied):
        return JSONResponse({"error": exc.code, **({"detail": exc.detail} if exc.detail else {})}, status_code=exc.status,
                            headers={"Retry-After": "60"} if exc.status == 429 else None)

    @app.middleware("http")
    async def guard(req: Request, call_next):
        cl = req.headers.get("content-length")
        if req.url.query and req.url.path.startswith("/api/v1/client/"):
            resp = JSONResponse({"error": "QUERY_NOT_ALLOWED"}, status_code=400)     # secrets never travel in URLs
        elif cl and (not cl.isdigit() or int(cl) > MAX_BODY):
            resp = JSONResponse({"error": "BODY_TOO_LARGE"}, status_code=413)
        elif req.method not in ("GET", "HEAD", "OPTIONS") and req.url.path.startswith("/api/v1/admin/") and not origin_ok(req):
            resp = JSONResponse({"error": "ORIGIN_NOT_ALLOWED"}, status_code=403)
        else:
            resp = await call_next(req)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["Content-Security-Policy"] = ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
                                                   "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if s.secure_cookies:
            resp.headers["Strict-Transport-Security"] = "max-age=31536000"
        return resp

    # ------------------------------------------------------------ identities
    def admin_any(req: Request, x_csrf: str | None = Header(default=None)) -> dict:
        a = svc.auth(req.cookies.get(cookie))
        if req.method not in ("GET", "HEAD") and (not x_csrf or not hmac.compare_digest(x_csrf, a["csrf"])):
            raise Denied("CSRF_INVALID", 403)
        return a

    def admin_rw(a: dict = Depends(admin_any)) -> dict:
        if a["role"] != "ADMIN":
            raise Denied("FORBIDDEN_ROLE", 403)
        return a

    # ------------------------------------------------------------ public
    @app.get("/api/v1/health")
    def health():
        return {"ok": True, "version": VERSION, "server_time": svc.now(), "clock_anomaly": getattr(svc.clock, "anomaly", None),
                "license_seconds": int(s.license_seconds), "env": s.env}

    @app.get("/api/v1/keys")
    def keys():
        return {"keys": [{"kid": svc.kid, "alg": "EdDSA", "pem": svc.public_pem}]}

    # ------------------------------------------------------------ client (MasterQUO)
    @app.post("/api/v1/client/session")
    def client_open(r: OpenReq, req: Request):
        return svc.open_session(r.license_key, boot_id=r.boot_id, nonce=r.nonce, client_version=r.client_version, client_label=r.client_label,
                                telemetry_opt_in=r.telemetry_opt_in, ip=ip_of(req))

    @app.post("/api/v1/client/renew")
    def client_renew(r: RenewReq, req: Request):
        return svc.heartbeat(r.session_token, boot_id=r.boot_id, telemetry=r.telemetry, ip=ip_of(req))

    @app.post("/api/v1/client/end")
    def client_end(r: EndReq, req: Request):
        return svc.end_session(r.session_token, boot_id=r.boot_id, ip=ip_of(req))

    # ------------------------------------------------------------ administrator session
    @app.post("/api/v1/admin/login")
    def login(r: LoginReq, req: Request, resp: Response):
        out = svc.login(r.email, r.password, r.code, ip=ip_of(req), ua=req.headers.get("user-agent"))
        resp.set_cookie(cookie, out["sid"], httponly=True, secure=s.secure_cookies, samesite="strict", path="/",
                        max_age=60 * int(s.admin_session_minutes))
        return {"admin": out["admin"], "csrf": out["csrf"], "expires_at": out["expires_at"]}

    @app.get("/api/v1/admin/me")
    def me(a: dict = Depends(admin_any)):
        return {"admin": {k: a[k] for k in ("id", "email", "role")}, "csrf": a["csrf"], "session_expires_at": a["session_expires_at"],
                "server_time": svc.now()}

    @app.post("/api/v1/admin/logout")
    def logout(req: Request, resp: Response, a: dict = Depends(admin_any)):
        svc.logout(req.cookies.get(cookie))
        resp.delete_cookie(cookie, path="/")
        return {"ok": True}

    @app.post("/api/v1/admin/password")
    def change_pw(r: PwReq, req: Request, a: dict = Depends(admin_any)):
        svc.change_password(a, r.current_password, r.new_password, ip_of(req))
        return {"ok": True}

    # ------------------------------------------------------------ administrator data
    @app.get("/api/v1/admin/summary")
    def summary(a: dict = Depends(admin_any)):
        return svc.summary()

    @app.get("/api/v1/admin/licenses")
    def licenses(status: str | None = Query(default=None, max_length=20), q: str | None = Query(default=None, max_length=80),
                 page: int = Query(default=1, ge=1, le=10000), per_page: int = Query(default=50, ge=1, le=200), a: dict = Depends(admin_any)):
        if status or q:                                   # filters are applied on the full list, then paginated
            rows = svc.list_licenses(status=status or None, q=q or None, limit=1000)
            return {"licenses": rows[(page - 1) * per_page: page * per_page], "page": page, "per_page": per_page, "total": len(rows)}
        total = svc.db.one("SELECT COUNT(*) AS n FROM licenses")["n"]
        return {"licenses": svc.list_licenses(limit=per_page, offset=(page - 1) * per_page), "page": page, "per_page": per_page, "total": total}

    @app.post("/api/v1/admin/licenses")
    def create_license(r: CreateLicReq, req: Request, a: dict = Depends(admin_rw)):
        return svc.create_license(a, customer_id=r.customer_id, note=r.note, max_sessions=r.max_sessions, ip=ip_of(req))

    @app.get("/api/v1/admin/licenses/{lid}")
    def license_detail(lid: str, a: dict = Depends(admin_any)):
        return {"license": svc.get_license(lid), "sessions": svc.list_sessions(active_only=False, license_id=lid, limit=100)}

    @app.post("/api/v1/admin/licenses/{lid}/revoke")
    def revoke(lid: str, r: ReasonReq, req: Request, a: dict = Depends(admin_rw)):
        return svc.revoke_license(a, lid, r.reason, ip_of(req))

    @app.post("/api/v1/admin/licenses/{lid}/reissue")
    def reissue(lid: str, r: ReasonReq, req: Request, a: dict = Depends(admin_rw)):
        return svc.reissue_license(a, lid, r.reason, ip_of(req))

    @app.post("/api/v1/admin/licenses/{lid}/max-sessions")
    def max_sessions(lid: str, r: MaxSessReq, req: Request, a: dict = Depends(admin_rw)):
        return svc.set_max_sessions(a, lid, r.max_sessions, ip_of(req))

    @app.post("/api/v1/admin/licenses/{lid}/assign")
    def assign(lid: str, r: AssignReq, req: Request, a: dict = Depends(admin_rw)):
        return svc.assign_license(a, lid, r.customer_id, r.note, ip_of(req))

    @app.get("/api/v1/admin/sessions")
    def sessions(active_only: bool = True, a: dict = Depends(admin_any)):
        return {"sessions": svc.list_sessions(active_only=active_only)}

    @app.post("/api/v1/admin/sessions/{sid}/terminate")
    def terminate(sid: str, req: Request, a: dict = Depends(admin_rw)):
        return svc.terminate_session(a, sid, ip_of(req))

    @app.get("/api/v1/admin/customers")
    def customers(a: dict = Depends(admin_any)):
        return {"customers": svc.list_customers()}

    @app.post("/api/v1/admin/customers")
    def create_customer(r: CustomerReq, req: Request, a: dict = Depends(admin_rw)):
        return svc.create_customer(a, r.name, r.email, r.mt5_login, r.note, r.stats_allowed, ip_of(req))

    @app.post("/api/v1/admin/customers/{cid}")
    def update_customer(cid: str, r: CustomerUpd, req: Request, a: dict = Depends(admin_rw)):
        return svc.update_customer(a, cid, r.model_dump(exclude_none=True), ip_of(req))

    @app.get("/api/v1/admin/audit")
    def audit(action: str | None = Query(default=None, max_length=40), a: dict = Depends(admin_any)):
        return {"audit": svc.list_audit(action=action)}

    @app.get("/api/v1/admin/telemetry")
    def telemetry(a: dict = Depends(admin_any)):
        return {"telemetry": svc.telemetry()}

    @app.get("/api/v1/admin/admins")
    def admins(a: dict = Depends(admin_rw)):
        return {"admins": svc.list_admins()}

    # ------------------------------------------------------------ static panel
    @app.get("/favicon.ico")
    def favicon():
        return Response(status_code=204)

    @app.get("/")
    def root():
        return RedirectResponse("/admin/")

    @app.get("/admin/")
    def admin_index():
        return FileResponse(STATIC / "index.html", media_type="text/html")

    @app.get("/admin/{name}")
    def admin_asset(name: str):
        p = (STATIC / name).resolve()
        if p.parent != STATIC.resolve() or not p.is_file() or p.suffix not in (".js", ".css", ".svg", ".html"):
            return JSONResponse({"error": "NOT_FOUND"}, status_code=404)
        return FileResponse(p)

    return app
