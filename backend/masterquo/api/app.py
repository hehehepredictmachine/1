"""HTTP + WebSocket API (contract /api/v1, version in version.API_CONTRACT_VERSION).

The built web monitor (frontend/dist) is served from the same origin. No CORS is enabled.

Etap 4 (krok B, docs/arch146/ETAP2_PROJEKT.md §3 / §5): create_app keeps the security middleware (Guard), the lifespan and the
page + session part; the route handlers live in api/routes/<domain>.py (registered in the order of the blocks of create_app
before the split, api/routes/__init__.REGISTRATION). Every name importable from this module before the split still is
(request models from api/schemas.py, route constants from their route module - aliasy zgodności).
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

from .. import desktop, paths, presets, stats, sysres  # noqa: F401 - Etap 4 (krok B): old names kept (used by api/routes/*)
from ..config import ALLOWED_ASSETS  # noqa: F401 - Etap 4 (krok B): old name kept
from ..execution.modes import ModeError  # noqa: F401 - Etap 4 (krok B): old name kept
from ..licensing.gate import LicenseRequired  # noqa: F401 - Etap 4 (krok B): old name kept
from ..media.gifinfo import gif_info  # noqa: F401 - Etap 4 (krok B): old name kept
from ..secrets_store import ALLOWED as _SECRETS_ALLOWED  # noqa: F401 - Etap 4 (krok B): old name kept
from ..secrets_store import UI_SETTABLE as _SECRETS_UI_SETTABLE  # noqa: F401 - Etap 4 (krok B): old name kept
from ..stats import deals_coverage_from_utc  # noqa: F401 - 1.46 arch I0081: old name kept
from ..timeutil import TIMEFRAMES, iso, utcnow  # noqa: F401 - Etap 4 (krok B): TIMEFRAMES old name kept
from ..version import API_CONTRACT_VERSION, APP_NAME, APP_VERSION, DISPLAY_NAME
from . import deps as _deps  # noqa: F401 - 1.46 arch I0087: one instrument validator; Etap 4 (krok B): old name kept
from . import routes as _routes
from .common import body_num  # noqa: F401 - 1.46 arch I0081: old name kept
from .routes.appearance import MAX_GIF_BYTES, MEDIA_SLOTS  # noqa: F401 - Etap 4 (krok B): moved to api/routes/appearance.py, old names kept
from .routes.market import SYMBOL_RX  # noqa: F401 - Etap 4 (krok B): moved to api/routes/market.py, old name kept
from .routes.studio import STUDIO_LAUNCH_WAIT_S  # noqa: F401 - Etap 4 (krok B): moved to api/routes/studio.py, old name kept
from .schemas import (  # noqa: F401 - Etap 4 (krok B): request models moved to api/schemas.py, old names kept
    AskReq,
    AssetActiveReq,
    AssetConfirmReq,
    CloseReq,
    DesktopPrefsReq,
    ExecReq,
    KeyReq,
    LeverageReq,
    MarketZonesLiveReq,
    MarketZonesReq,
    MemoryReq,
    MLBackfillReq,
    MLFlagReq,
    MLModeReq,
    MLTrainReq,
    ModeReq,
    OnReq,
    PresetReq,
    PrimaryPathReq,
    ProfileReq,
    SecretReq,
    SetupViewReq,
    StrategyModeReq,
    StrategyToggleReq,
    TelegramTemplateReq,
    TrainJobReq,
    TrainVersionReq,
)
from .security import SESSION_COOKIE, LocalSecurity  # noqa: F401 - Etap 4 (krok A): LocalSecurity built by runtime.compose_api_services; old name kept

log = logging.getLogger("masterquo.api")


def create_app(rt, port: int) -> FastAPI:
    sec = _api_services(rt, port).security          # Etap 4 (krok A): built by the composition root (runtime.compose_api_services)
    rt.security = sec

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        rt.attach_loop(asyncio.get_running_loop())
        yield

    app = FastAPI(title=APP_NAME, version=APP_VERSION, docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    class Guard(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            if not sec.host_ok(request.headers.get("host")):
                return JSONResponse({"error": "HOST_NOT_ALLOWED"}, status_code=421)
            path = request.url.path
            if request.method not in ("GET", "HEAD", "OPTIONS"):
                if path == "/api/v1/admin/shutdown" and request.headers.get("x-mq-shutdown") == sec.shutdown_token:
                    return await call_next(request)
                if not sec.origin_ok(request.headers.get("origin")):
                    return JSONResponse({"error": "ORIGIN_NOT_ALLOWED"}, status_code=403)
                if not sec.csrf_ok(request.cookies.get(SESSION_COOKIE), request.headers.get("x-mq-csrf")):
                    return JSONResponse({"error": "CSRF_OR_SESSION_INVALID"}, status_code=403)
            elif path.startswith("/api/v1/") and path not in ("/api/v1/health",) and not sec.csrf_for(request.cookies.get(SESSION_COOKIE)):
                return JSONResponse({"error": "SESSION_REQUIRED_OPEN_MONITOR_PAGE"}, status_code=401)
            elif path.startswith("/api/") and path not in ("/api/v1/health",) \
                    and (request.headers.get("sec-fetch-site") or "").lower() in ("cross-site", "same-site"):
                # 1.46: SameSite=Strict does not separate ports - a page of ANOTHER local app (http://127.0.0.1:<other port>) is same-site and
                # its <img src> / no-cors fetch carried the session cookie into GETs with side effects (exports, ZIP files, SVP snapshot,
                # license refresh). A browser marks such a request; the panel (same-origin), a typed URL (none) and non-browser
                # clients (no header) are unaffected.
                return JSONResponse({"error": "CROSS_SITE_REQUEST_REFUSED"}, status_code=403)
            # 1.44.0 wersja klienta bez ważnej licencji: działa tylko ekran aktywacji (status / aktywacja), sesja, zdrowie i zamknięcie –
            # API ekranów FOREX / CRYPTO (OTC wycofane), trybów i handlu odpowiada 402 (frontend wraca do ekranu licencji).
            if rt.license.locked and path.startswith("/api/") and not path.startswith("/api/v1/license/") \
                    and path not in ("/api/v1/health", "/api/v1/session", "/api/v1/admin/shutdown"):
                st = rt.license.state()
                return JSONResponse({"error": "LICENSE_REQUIRED", "code": st.get("code"), "message": st.get("message")}, status_code=402)
            resp: Response = await call_next(request)
            resp.headers["X-Content-Type-Options"] = "nosniff"
            resp.headers["Referrer-Policy"] = "no-referrer"
            resp.headers["X-Frame-Options"] = "DENY"
            resp.headers["Cache-Control"] = "no-store" if path.startswith("/api/") else resp.headers.get("Cache-Control", "no-cache")
            return resp

    app.add_middleware(Guard)

    # ------------------------------------------------------------ page + session
    def _index(request: Request | None = None) -> Response:
        idx = paths.FRONTEND_DIST / "index.html"
        if not idx.exists():
            # 1.46: display name of the rebrand (was 'MasterQUO AI'); internal identifiers unchanged
            resp: Response = HTMLResponse(f"<h1>{DISPLAY_NAME}</h1><p>Brak zbudowanego frontendu (frontend/dist). "
                                          "Paczka zawiera gotowy build – sprawdź, czy rozpakowano cały ZIP.</p>", status_code=503)
        else:
            resp = FileResponse(idx, media_type="text/html", headers={"Cache-Control": "no-cache"})
        cur = request.cookies.get(SESSION_COOKIE) if request is not None else None
        site = (request.headers.get("sec-fetch-site") or "").lower() if request is not None else ""
        if cur and sec.csrf_for(cur):
            pass                                        # 1.46: a reload keeps its session (no new one per GET /)
        elif site in ("cross-site", "same-site"):
            pass                                        # 1.46: a request started by ANOTHER site never creates (and evicts) sessions
        else:
            sid, _ = sec.new_session()
            resp.set_cookie(SESSION_COOKIE, sid, httponly=True, samesite="strict", secure=False, path="/")
        resp.headers["Content-Security-Policy"] = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                                                   "img-src 'self' data: blob:; connect-src 'self' ws://127.0.0.1:%d ws://localhost:%d; "
                                                   "frame-ancestors 'none'; base-uri 'none'" % (port, port))
        return resp

    @app.get("/")
    def index(request: Request):
        return _index(request)

    # 1.46: explicit MIME of the panel files - without media_type Starlette asks mimetypes, which on Windows reads the registry
    # (HKCR\.js "Content Type"); software that set .js to text/plain made WebView2 refuse the module script (nosniff) -> empty panel
    _MIME = {".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".html": "text/html", ".json": "application/json",
             ".map": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".webp": "image/webp", ".jpg": "image/jpeg",
             ".jpeg": "image/jpeg", ".gif": "image/gif", ".ico": "image/x-icon", ".wasm": "application/wasm", ".woff2": "font/woff2",
             ".woff": "font/woff", ".ttf": "font/ttf", ".txt": "text/plain", ".mp4": "video/mp4", ".webm": "video/webm"}

    @app.get("/assets/{name:path}")
    def assets(name: str):
        base = (paths.FRONTEND_DIST / "assets").resolve()
        f = (base / name).resolve()
        if base not in f.parents or not f.is_file():
            raise HTTPException(404)
        return FileResponse(f, media_type=_MIME.get(f.suffix.lower()), headers={"Cache-Control": "public, max-age=31536000, immutable"})

    @app.get("/static/{name:path}")
    def static(name: str):
        base = paths.FRONTEND_DIST.resolve()
        f = (base / name).resolve()
        if base not in f.parents or not f.is_file() or f.suffix not in (".png", ".webp", ".svg", ".ico", ".jpg", ".gif"):
            raise HTTPException(404)
        return FileResponse(f, media_type=_MIME.get(f.suffix.lower()))

    @app.get("/api/v1/health")
    def health():
        return {"ok": True, "app": APP_NAME, "display_name": DISPLAY_NAME, "version": APP_VERSION, "contract": API_CONTRACT_VERSION, "boot_id": rt.bus.boot_id,
                "synthetic": rt.demo, "mt5_state": rt.bridge.state, "time": iso(utcnow()),
                "start_failures": [f["part"] for f in getattr(rt, "start_failures", [])]}

    @app.get("/api/v1/session")
    def session(request: Request):
        sid = request.cookies.get(SESSION_COOKIE)
        return {"csrf": sec.csrf_for(sid), "contract": API_CONTRACT_VERSION, "boot_id": rt.bus.boot_id, "port": port}

    # ------------------------------------------------------------ route modules (Etap 4 krok B: api/routes/<domain>.py)
    # Same handlers, registered in the order of the blocks of create_app before the split (Starlette matches routes in order);
    # ctx carries the create_app locals the blocks share (rt, sec, port, helpers and handlers used by name).
    _routes.register_all(app, _routes.Ctx(rt=rt, sec=sec, port=port))

    from .wf32_routes import register as _wf32_register
    _wf32_register(app, rt)               # Apollo23 workflow v3.2 (TASK 001-025)
    from .export_routes import register as _exports_register
    _exports_register(app, rt)            # 1.46: data exporters (GET /api/v1/exports/...), write only into <data>/exports
    return app


def _api_services(rt, port: int):
    """Etap 4 (krok A, docs/arch146/ETAP2_PROJEKT.md §5): the objects create_app built in its own body before Etap 4 (LocalSecurity, the
    training / NSS child-process registries, the strategy preset store) and the TASK 007 indicator engine of wf32_routes come from the
    composition root. A Runtime builds them (Runtime.compose_api: one new set per create_app call, as before; rt.api_services and
    rt.security); any other runtime object (tests, tools/routes_inventory with a MagicMock) gets a set from the same function
    (runtime.compose_api_services), published as rt.api_services exactly as create_app publishes rt.security."""
    from .. import runtime as _runtime
    if isinstance(rt, _runtime.Runtime):
        return rt.compose_api(port)
    svc = _runtime.compose_api_services(port)
    rt.api_services = svc
    return svc
