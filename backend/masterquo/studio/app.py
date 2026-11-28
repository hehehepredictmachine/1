"""Pepe Data & Training Studio - FastAPI app (own process / port / data dir). It imports NO bot Runtime, strategies or execution code.
Endpoints under /api/studio/*; the UI is the separate frontend entry studio.html (frontend/dist). Local only (127.0.0.1)."""
from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse

from . import registry as R
from . import settings as S
from .queue import Queue

VERSION = "PMW-STUDIO-1"
DISPLAY_NAME = "Apollo23 Data & Training Studio"          # 1.46: display text only - ids ('PepeTrainingStudio' in /health, exe) unchanged
REPORT_FILES = ("validation/validate_raw/raw.json", "validation/validate_dataset/dataset.json", "evaluation/evaluate/metrics.json",
                "evaluation/verify_loader/loader.json", "raw/export/export_report.json")


def _epoch(name: str, v) -> int | None:
    """1.46: start / end of the requested range as epoch seconds (number or ISO text; a text without a zone = UTC, as the exporter). 1.45.0
    passed the raw value: an ISO string reached `int >= str` in the BOT_CACHE / OFFLINE filter (TypeError -> FAILED)."""
    if v is None or v == "":
        return None
    from ..marketdata.export import _ts
    try:
        t = None if isinstance(v, bool) else _ts(v)
    except (TypeError, ValueError, OverflowError):
        t = None
    if t is None or not math.isfinite(t) or not 0 <= t <= 32503680000:
        raise HTTPException(400, f"{name}: epoch (s) albo data ISO")
    return int(t)


def _imported(b, package: str) -> dict | None:
    """1.46: the bot's import record of THIS package (CANDIDATE) - the import succeeded although its answer never arrived (timeout)."""
    try:
        st, h = b._req("GET", "/api/v1/studio/imports")
    except (RuntimeError, OSError):
        return None
    want = str(Path(package).resolve())
    items = h.get("items") if st == 200 and isinstance(h, dict) else None
    return next((r for r in items or [] if isinstance(r, dict) and r.get("package") == want and r.get("state") == "CANDIDATE"), None)


def _bot_health(port: int) -> dict | None:
    """GET /api/v1/health of the bot (2 s); one implementation in masterquo.localapi (1.46 arch I0080)."""
    from .. import localapi
    return localapi.health(port, 2)


LOCAL_HOSTS = ("127.0.0.1", "localhost")


def _host_name(value: str | None) -> str | None:
    if not value:
        return None
    v = value.strip().lower()
    if v.startswith("["):                                    # [::1]:port - not used by Studio (binds 127.0.0.1)
        return None
    return v.rsplit(":", 1)[0] if v.count(":") == 1 else v


def _guard(app) -> None:
    """1.46: same local-request rules as the bot API (api/app.py Guard), minus the session: the Host header must be the loopback name
    (DNS-rebinding protection - a page served from attacker.example resolving to 127.0.0.1 sends Host: attacker.example) and a state-
    changing request coming from a browser must carry a loopback Origin. Studio binds 127.0.0.1 only."""
    from fastapi.responses import JSONResponse
    from starlette.middleware.base import BaseHTTPMiddleware

    class StudioGuard(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            if _host_name(request.headers.get("host")) not in LOCAL_HOSTS:
                return JSONResponse({"error": "HOST_NOT_ALLOWED"}, status_code=421)
            if request.method not in ("GET", "HEAD", "OPTIONS"):
                origin = request.headers.get("origin")
                if origin is not None and _host_name(origin.split("://", 1)[-1]) not in LOCAL_HOSTS:
                    return JSONResponse({"error": "ORIGIN_NOT_ALLOWED"}, status_code=403)
            resp = await call_next(request)
            resp.headers["X-Frame-Options"] = "DENY"
            resp.headers["X-Content-Type-Options"] = "nosniff"
            return resp
    app.add_middleware(StudioGuard)


def create_app(queue: Queue | None = None, *, start_worker: bool = True) -> FastAPI:
    from .. import paths
    from ..version import APP_VERSION
    os.environ.setdefault("MASTERQUO_DATA_DIR", str(S.data_dir()))       # Studio's own registries / logs - never the bot's
    # 1.46: the BOT's configuration, read-only, on every request (broker symbols, MT5, family pairs). 1.45.0: ConfigStore() here created a
    # default <studio>/config.json and ignored the user's mappings; None = no bot config (symbols UNAVAILABLE)
    cfg = S.bot_config
    q = queue or Queue(env={"MASTERQUO_DATA_DIR": str(S.data_dir()), "MQ_STUDIO_DATA_DIR": str(S.data_dir()),
                            "MQ_BOT_DATA_DIR": str(S.bot_data_dir())})
    app = FastAPI(title=DISPLAY_NAME, version=APP_VERSION)
    app.state.queue = q
    _guard(app)
    if start_worker:
        q.start()

    def source_for(mode: str | None, body: dict) -> dict:
        s = S.load()
        bot = _bot_health(int(s["bot_port"]))
        m = (mode or "AUTO").upper()
        if m == "AUTO":
            m = "BOT_CACHE" if bot else "MT5_DIRECT"
        if m not in ("BOT_CACHE", "MT5_DIRECT", "OFFLINE", "SYNTHETIC"):
            raise HTTPException(400, "źródło: AUTO|BOT_CACHE|MT5_DIRECT|OFFLINE|SYNTHETIC")
        src = {"mode": m, "cutoff": int(time.time()), "start": _epoch("start", body.get("start")), "end": _epoch("end", body.get("end"))}
        if src["start"] is not None and src["end"] is not None and src["end"] <= src["start"]:
            raise HTTPException(400, "end musi być późniejszy niż start")
        if m == "BOT_CACHE":
            src["store_root"] = str(S.bot_data_dir(s) / "marketdata")
        if m == "OFFLINE":
            if not body.get("store_root"):
                raise HTTPException(400, "OFFLINE wymaga store_root (magazyn świec)")
            src["store_root"] = str(body["store_root"])
        if m == "SYNTHETIC":
            d = body.get("days") or 30
            # 1.46: 'abc' was int() -> ValueError -> 500
            if isinstance(d, bool) or not isinstance(d, (int, str)) or not str(d).strip().isdigit() or not 1 <= int(str(d).strip()) <= 3650:
                raise HTTPException(400, "days: liczba całkowita 1–3650")
            src["days"] = int(str(d).strip())
        src["indicators_db"] = str(S.bot_data_dir(s) / "indicators" / "indicators.sqlite")
        return src

    @app.get("/api/studio/health")
    def health():
        return {"ok": True, "app": "PepeTrainingStudio", "studio": VERSION, "version": APP_VERSION, "data_dir": str(S.data_dir()),
                "orders": "NEVER (Studio nie wysyła ani nie modyfikuje zleceń)"}

    @app.get("/api/studio/connections")
    def connections():
        s = S.load()
        bot = _bot_health(int(s["bot_port"]))
        try:
            import MetaTrader5  # noqa: F401
            mt5 = "AVAILABLE"
        except Exception:  # noqa: BLE001
            mt5 = "NOT_INSTALLED (Windows + MetaTrader5)"
        envs = {e: (paths.ROOT_DIR / e).exists() for e in (".venv", ".venv_deep", ".venv_kronos", ".venv_candles")}
        return {"bot": {"running": bool(bot), "health": bot, "port": s["bot_port"], "port_source": s.get("bot_port_source"),   # I0125
                        "data_dir": str(S.bot_data_dir(s))},
                "mt5_package": mt5, "envs": envs, "studio_data_dir": str(S.data_dir()), "export_lock": q.lock.owner(),
                "mode_hint": "BOT_CACHE" if bot else "MT5_DIRECT", "settings": s}

    @app.post("/api/studio/settings")
    def settings_save(body: dict = Body(...)):
        try:
            return S.save(body)
        except ValueError as exc:                                         # 1.46: validated settings (bad port / profile / dir -> 400)
            raise HTTPException(400, str(exc)) from None

    @app.get("/api/studio/models")
    def models(instrument: str | None = Query(None)):
        rows = [dict(t, operations=R.operations(t)) for t in R.tasks(cfg()) if instrument in (None, t["instrument"])]
        return {"items": rows, "count": len(rows)}

    @app.get("/api/studio/matrix")
    def matrix():
        m = R.matrix(cfg())
        (S.data_dir() / "MODEL_DATA_MATRIX.json").write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
        return m

    @app.post("/api/studio/jobs")
    def submit(body: dict = Body(...)):
        keys = body.get("task_keys") or ([body["task_key"]] if body.get("task_key") else [])
        if not keys:
            raise HTTPException(400, "task_key(s) wymagane")
        known = R.by_key(cfg())
        bad = [k for k in keys if k not in known]
        if bad:
            raise HTTPException(404, f"nieznane zadania: {bad}")
        op = str(body.get("op") or "FULL_PROCESS").upper()
        for k in keys:
            if op not in R.operations(known[k]):
                raise HTTPException(409, f"operacja {op} niedostępna dla {k} ({known[k]['category']}, {known[k]['state']})")
        profile = str(body.get("profile") or S.load()["profile"])
        if profile not in S.PROFILES:                                     # 1.46: was accepted and failed only inside the job
            raise HTTPException(400, f"profile: {'|'.join(S.PROFILES)}")
        src = source_for(body.get("source"), body)
        return {"items": q.submit_many(keys, op, source=src, profile=profile)}

    @app.get("/api/studio/jobs")
    def jobs(limit: int = Query(200, ge=1, le=1000)):
        return {"items": q.jobs(limit), "running": q.current, "busy_by_other": q.busy()}

    @app.post("/api/studio/jobs/{jid}/{action}")
    def job_action(jid: str, action: str, body: dict = Body(default={})):
        if action == "transfer":
            return transfer(jid)
        fn = {"pause": q.pause, "cancel": q.cancel, "resume": q.resume, "delete": q.delete}.get(action)
        if action == "move":
            ok = q.move(jid, body.get("before"))
        elif fn is None:
            raise HTTPException(400, "akcja: pause|cancel|resume|delete|move|transfer")
        else:
            ok = fn(jid)
        if not ok:
            raise HTTPException(409, "akcja niedostępna w obecnym stanie zadania")
        return {"ok": True, "job": q.job(jid)}

    @app.get("/api/studio/jobs/{jid}/report")
    def report(jid: str):
        j = q.job(jid)
        if not j or not j.get("package"):
            raise HTTPException(404, "brak paczki")
        d = Path(j["package"])
        rep = {"manifest": json.loads((d / "manifest.json").read_text(encoding="utf-8")) if (d / "manifest.json").exists() else None}
        for name in REPORT_FILES:
            if (d / name).exists():
                rep[name] = json.loads((d / name).read_text(encoding="utf-8"))
        return rep

    def transfer(jid: str):
        """Hand the package to the bot: running -> its API (session + CSRF, as the panel), off -> inbox imported at the next bot start."""
        j = q.job(jid)
        if not j or j["state"] != "PACKAGED":
            raise HTTPException(409, "przekazać można tylko paczkę po pozytywnym teście loadera (stan PACKAGED)")
        s = S.load()
        if _bot_health(int(s["bot_port"])):
            from ..localapi import Bot
            b = Bot(int(s["bot_port"]))
            # 1.46: a failed bot session / connection / timeout was a 500; an import that succeeded while its answer timed out left the job
            # PACKAGED for good (a retry got 409 'already exists') - the bot's import record of this package now completes the transfer
            try:
                b.login()
                st, res = b._req("POST", "/api/v1/studio/import", {"package": j["package"]}, timeout=120)
            except (RuntimeError, OSError) as exc:
                raise HTTPException(503, f"bot niedostępny ({type(exc).__name__}: {exc})"[:300]) from None
            if st != 200 or not (isinstance(res, dict) and res.get("ok")):
                prev = _imported(b, j["package"])
                if prev is None:
                    raise HTTPException(409, f"bot odrzucił import: {res}")
                res = prev
            q.transferred(jid, res)
            return {"ok": True, "via": "BOT_API", "import": res}
        inbox = S.bot_data_dir(s) / "studio_inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        ptr = inbox / f"{jid}.json"
        tmp = ptr.with_suffix(".tmp")
        tmp.write_text(json.dumps({"package": j["package"], "job_id": jid, "at": time.time()}), encoding="utf-8")
        tmp.replace(ptr)
        q.transferred(jid, {"via": "INBOX", "pointer": str(ptr)})
        return {"ok": True, "via": "INBOX", "pointer": str(ptr), "note": "bot zaimportuje paczkę przy następnym starcie (kandydat, nieaktywny)"}

    @app.get("/", response_class=HTMLResponse)
    def index():
        p = paths.ROOT_DIR / "frontend" / "dist" / "studio.html"
        if p.exists():
            return FileResponse(p)
        return HTMLResponse(f"<h1>{DISPLAY_NAME.replace('&', '&amp;')}</h1><p>Brak zbudowanego interfejsu (frontend/dist/studio.html). API: /api/studio/health</p>")

    from fastapi.staticfiles import StaticFiles
    assets = paths.ROOT_DIR / "frontend" / "dist" / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")
    return app


def _same_dir(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


def serve(port: int | None = None) -> int:
    import uvicorn
    s = S.load()
    p = int(port or s["port"])
    sd = S.data_dir()
    # 1.46 (I0105): the bot's modules imported here (trainhub.registry, families.Store, ...) write to paths.data_dir() =
    # MASTERQUO_DATA_DIR. create_app only set it with setdefault, so a manual `python -m masterquo studio` in a shell where it pointed
    # at the BOT's data wrote Studio registries / logs into the bot's folder. The CLI entry now forces the Studio data dir; a Studio
    # data dir that IS the bot's data dir is refused (Studio must never share the bot's registries).
    if _same_dir(sd, S.bot_data_dir(s)):
        print(f"[{DISPLAY_NAME}] BŁĄD: katalog danych Studio ({sd}) jest katalogiem danych bota – ustaw osobny MQ_STUDIO_DATA_DIR",
              flush=True)
        return 2
    prev = os.environ.get("MASTERQUO_DATA_DIR")
    if prev and not _same_dir(Path(prev), sd):
        print(f"[{DISPLAY_NAME}] uwaga: MASTERQUO_DATA_DIR={prev} zastąpione katalogiem danych Studio {sd}", flush=True)
    os.environ["MASTERQUO_DATA_DIR"] = str(sd)
    print(f"[{DISPLAY_NAME}] http://127.0.0.1:{p}/  (dane: {sd})", flush=True)
    uvicorn.run(create_app(), host="127.0.0.1", port=p, log_level="warning")
    return 0
