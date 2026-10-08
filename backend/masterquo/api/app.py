"""HTTP + WebSocket API (contract /api/v1, version in version.API_CONTRACT_VERSION).

The built web monitor (frontend/dist) is served from the same origin. No CORS is enabled.
"""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from .. import paths, stats
from ..execution.modes import ModeError
from ..timeutil import TIMEFRAMES, iso, utcnow
from ..version import API_CONTRACT_VERSION, APP_NAME, APP_VERSION
from .security import SESSION_COOKIE, LocalSecurity

log = logging.getLogger("masterquo.api")


class ModeReq(BaseModel):
    mode: str
    confirm: str = ""


class OnReq(BaseModel):
    on: bool
    reason: str = "user"


class ExecReq(BaseModel):
    decision_id: str


class CloseReq(BaseModel):
    scope: str = "BOT"
    ticket: int | None = None
    confirm: str


class AskReq(BaseModel):
    question: str = Field(min_length=2, max_length=2000)


class KeyReq(BaseModel):
    api_key: str = Field(min_length=10, max_length=300)


class SecretReq(BaseModel):
    name: str
    value: str | None = None


class MemoryReq(BaseModel):
    status: str


def create_app(rt, port: int) -> FastAPI:
    sec = LocalSecurity(port)
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
            resp: Response = await call_next(request)
            resp.headers["X-Content-Type-Options"] = "nosniff"
            resp.headers["Referrer-Policy"] = "no-referrer"
            resp.headers["X-Frame-Options"] = "DENY"
            resp.headers["Cache-Control"] = "no-store" if path.startswith("/api/") else resp.headers.get("Cache-Control", "no-cache")
            return resp

    app.add_middleware(Guard)

    # ------------------------------------------------------------ page + session
    def _index() -> Response:
        idx = paths.FRONTEND_DIST / "index.html"
        if not idx.exists():
            resp: Response = HTMLResponse("<h1>MasterQUO AI</h1><p>Brak zbudowanego frontendu (frontend/dist). "
                                          "Paczka zawiera gotowy build – sprawdź, czy rozpakowano cały ZIP.</p>", status_code=503)
        else:
            resp = FileResponse(idx, headers={"Cache-Control": "no-cache"})
        sid, _ = sec.new_session()
        resp.set_cookie(SESSION_COOKIE, sid, httponly=True, samesite="strict", secure=False, path="/")
        resp.headers["Content-Security-Policy"] = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                                                   "img-src 'self' data:; connect-src 'self' ws://127.0.0.1:%d ws://localhost:%d; "
                                                   "frame-ancestors 'none'; base-uri 'none'" % (port, port))
        return resp

    @app.get("/")
    def index():
        return _index()

    @app.get("/assets/{name:path}")
    def assets(name: str):
        base = (paths.FRONTEND_DIST / "assets").resolve()
        f = (base / name).resolve()
        if base not in f.parents or not f.is_file():
            raise HTTPException(404)
        return FileResponse(f, headers={"Cache-Control": "public, max-age=31536000, immutable"})

    @app.get("/static/{name:path}")
    def static(name: str):
        base = paths.FRONTEND_DIST.resolve()
        f = (base / name).resolve()
        if base not in f.parents or not f.is_file() or f.suffix not in (".png", ".webp", ".svg", ".ico", ".jpg"):
            raise HTTPException(404)
        return FileResponse(f)

    @app.get("/api/v1/health")
    def health():
        return {"ok": True, "app": APP_NAME, "version": APP_VERSION, "contract": API_CONTRACT_VERSION, "boot_id": rt.bus.boot_id,
                "synthetic": rt.demo, "mt5_state": rt.bridge.state, "time": iso(utcnow())}

    @app.get("/api/v1/session")
    def session(request: Request):
        sid = request.cookies.get(SESSION_COOKIE)
        return {"csrf": sec.csrf_for(sid), "contract": API_CONTRACT_VERSION, "boot_id": rt.bus.boot_id, "port": port}

    # ------------------------------------------------------------ state
    def full_state() -> dict:
        b = rt.bridge
        cfg = rt.cfg.get()
        acct = b.account_status()
        mode = rt.modes.status()
        return {"contract": API_CONTRACT_VERSION, "app_version": APP_VERSION, "seq": rt.bus.seq, "boot_id": rt.bus.boot_id,
                "synthetic": rt.demo or b.synthetic, "server_time": iso(utcnow()),
                "connection": b.connection_status(), "account": acct, "symbol": b.symbol_status_dict(), "quote": b.quote_status(),
                "tf_meta": b.tf_meta(), "analysis": rt.engine.analysis_summary(), "decision": rt.engine.current_decision(),
                "engine": {"last_error": rt.engine.last_error, "cycle_ms": rt.engine.cycle_ms, "full_cycles": rt.engine.full_count},
                "agent": rt.agent.status(), "agent_last": rt.agent.public_result(rt.agent.last_result), "mode": mode,
                "risk_config": cfg.risk.model_dump(), "costs_config": cfg.costs.model_dump(), "strategy_config": cfg.strategy.model_dump(),
                "news": rt.news.summary(), "positions": {"positions": b.positions, "orders": b.orders},
                "managed": rt.db.query("SELECT * FROM managed_positions WHERE state='OPEN'"),
                "attempts": rt.gateway.recent_attempts(15), "paper": rt.paper.account() if mode["mode"] == "PAPER" else None,
                "logs": logs_list(60), "pc_clock": rt.pcclock.snapshot(), "manager": {"reconciled_epoch": rt.manager.reconciled_epoch,
                                                                                     "last_error": rt.manager.last_error},
                "first_run_completed": cfg.first_run_completed}

    def logs_list(limit: int) -> list[dict]:
        return rt.db.query("SELECT id, ts, level, category, code, message FROM app_events ORDER BY id DESC LIMIT ?", (limit,))

    @app.get("/api/v1/state")
    def state():
        return full_state()

    @app.get("/api/v1/candles")
    def candles(tf: str = Query(...)):
        if tf not in TIMEFRAMES:
            raise HTTPException(400, "INVALID_TIMEFRAME")
        return rt.engine.chart(tf)

    @app.get("/api/v1/signals")
    def signals(limit: int = 30):
        from ..engine.lifecycle import public_setup
        setups = [public_setup(r) for r in rt.engine.lifecycle.recent(min(limit, 100))]
        decs = rt.db.query("SELECT decision_id, created_at, setup_id, analysis_direction, signal_stage, decision, execution_permission FROM decisions "
                           "WHERE decision IN ('BUY','SELL') OR signal_stage IN ('CONFIRMED','INVALIDATED','EXPIRED') ORDER BY created_at DESC LIMIT 50")
        trades = rt.db.query("SELECT * FROM trades ORDER BY closed_at DESC LIMIT 50")
        return {"setups": setups, "decisions": decs, "attempts": rt.gateway.recent_attempts(30), "trades": trades}

    @app.get("/api/v1/decision")
    def decision():
        return rt.engine.current_decision()

    @app.get("/api/v1/stats")
    def get_stats(mode: str = "PAPER"):
        if mode not in ("PAPER", "DEMO_EXECUTION", "LIVE_EXECUTION"):
            raise HTTPException(400, "INVALID_MODE")
        b = rt.bridge
        with b._lock:
            deals = list(b.deals)
        ds = b.server_day_start_utc()
        ds_raw = ds.timestamp() + b.clock.offset if ds and b.clock.offset is not None else None
        return {"bot": stats.bot_stats(rt.db, mode, b.account_key), "equity": stats.equity_curve(rt.db, "PAPER" if mode == "PAPER" else "ACCOUNT", b.account_key),
                "account": stats.account_stats(deals, rt.cfg.get().mt5.symbol, ds_raw) if b.account_key else None}

    @app.get("/api/v1/news")
    def news():
        return rt.news.summary()

    @app.get("/api/v1/logs")
    def logs(limit: int = 200):
        return logs_list(min(max(limit, 1), 2000))

    @app.get("/api/v1/config")
    def get_config():
        c = rt.cfg.get().model_dump(mode="json")
        return {"config": c, "secrets": {n: {"source": rt.secrets.source(n), "masked": rt.secrets.mask(n)}
                                         for n in ("ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN", "FRED_API_KEY")},
                "editable_note": "Klucze API są przechowywane lokalnie (Windows DPAPI) i nigdy nie są zwracane przez API."}

    @app.put("/api/v1/config")
    def put_config(patch: dict = Body(...)):
        patch.pop("server", None)
        try:
            old = rt.cfg.get()
            new = rt.cfg.update(patch)
        except Exception as exc:
            raise HTTPException(400, f"INVALID_CONFIG: {exc}") from exc
        rt.db.execute("INSERT INTO settings_audit(ts, change_json) VALUES (?,?)", (iso(utcnow()), json.dumps({"config_patch": patch}, default=str)))
        rt.log.info("CONFIG", "UPDATED", "Zmieniono konfigurację: " + ", ".join(sorted(patch.keys())))
        if (old.mt5.symbol, old.mt5.terminal_path, old.mt5.dxy_symbol) != (new.mt5.symbol, new.mt5.terminal_path, new.mt5.dxy_symbol):
            rt.modes.reset("MT5_CONFIG_CHANGED")
            rt.bridge.state = "RECONNECTING"
            rt.bridge.next_retry = 0
        if old.risk != new.risk and rt.modes.status()["mode"] != "READ_ONLY":
            rt.modes.reset("RISK_LIMITS_CHANGED_RECONFIRM_MODE")
        rt.engine.mark_dirty()
        return get_config()

    @app.post("/api/v1/secrets/anthropic")
    def set_key(req: KeyReq):
        rt.secrets.set("ANTHROPIC_API_KEY", req.api_key)
        rt.log.info("AGENT", "KEY_SET", "Zapisano lokalnie klucz Anthropic (wartość nie jest logowana).")
        return {"ok": True, "masked": rt.secrets.mask("ANTHROPIC_API_KEY")}

    @app.post("/api/v1/secrets")
    def set_secret(req: SecretReq):
        if req.name not in ("TELEGRAM_BOT_TOKEN", "FRED_API_KEY", "ANTHROPIC_API_KEY"):
            raise HTTPException(400, "UNKNOWN_SECRET")
        rt.secrets.set(req.name, req.value)
        return {"ok": True, "source": rt.secrets.source(req.name)}

    # ------------------------------------------------------------ agent
    @app.get("/api/v1/agent")
    def agent_status():
        runs = rt.db.query("SELECT run_id, started_at, finished_at, trigger, snapshot_id, setup_id, model_id, prompt_version, status, error_code, "
                           "latency_ms, input_tokens, output_tokens, est_cost_usd, tool_calls, question FROM agent_runs ORDER BY started_at DESC LIMIT 30")
        return {"status": rt.agent.status(), "last": rt.agent.public_result(rt.agent.last_result), "runs": runs}

    @app.get("/api/v1/agent/models")
    async def agent_models():
        return await rt.agent.list_models()

    @app.post("/api/v1/agent/test")
    async def agent_test():
        return await rt.agent.test_connection()

    @app.post("/api/v1/agent/ask")
    def agent_ask(req: AskReq):
        d = rt.engine.current_decision() or {}
        s = d.get("setup") or {}
        rid = rt.agent.request("USER_QUESTION", snapshot_id=d.get("snapshot_id"), setup_id=s.get("setup_id") if s.get("state") in
                               ("EARLY_SETUP", "QUALIFIED", "ARMED", "TRIGGERED", "CONFIRMED") else None, setup_state=s.get("state"), question=req.question)
        return {"queued": bool(rid), "request_id": rid}

    @app.post("/api/v1/agent/analyze")
    def agent_analyze():
        d = rt.engine.current_decision() or {}
        s = d.get("setup") or {}
        active = s.get("state") in ("EARLY_SETUP", "QUALIFIED", "ARMED", "TRIGGERED", "CONFIRMED")
        trig = "SETUP_CONFIRMED" if s.get("state") == "CONFIRMED" else "MANUAL"
        rid = rt.agent.request(trig, snapshot_id=d.get("snapshot_id"), setup_id=s.get("setup_id") if active else None, setup_state=s.get("state"))
        return {"queued": bool(rid), "request_id": rid}

    @app.get("/api/v1/agent/memory")
    def agent_memory():
        return rt.db.query("SELECT * FROM agent_memory ORDER BY id DESC LIMIT 100")

    @app.post("/api/v1/agent/memory/{mid}")
    def agent_memory_set(mid: int, req: MemoryReq):
        if req.status not in ("ACCEPTED_FOR_OOS_TEST", "REJECTED", "PROPOSED"):
            raise HTTPException(400, "INVALID_STATUS")
        rt.db.execute("UPDATE agent_memory SET status=? WHERE id=?", (req.status, mid))
        rt.log.info("AGENT", "MEMORY_STATUS", f"Propozycja {mid}: {req.status} (nie zmienia strategii LIVE)")
        return {"ok": True}

    # ------------------------------------------------------------ modes & execution
    @app.post("/api/v1/mode")
    def set_mode(req: ModeReq):
        try:
            return rt.modes.set_mode(req.mode, confirm=req.confirm, account=rt.bridge.account_status(), account_key=rt.bridge.account_key,
                                     synthetic=rt.bridge.synthetic)
        except ModeError as exc:
            raise HTTPException(400, str(exc)) from exc
        finally:
            rt.engine.mark_dirty()

    @app.post("/api/v1/auto")
    def set_auto(req: OnReq):
        try:
            return rt.modes.set_auto(req.on)
        except ModeError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/v1/kill")
    def kill(req: OnReq):
        st = rt.modes.set_kill(req.on, req.reason)
        rt.engine.mark_dirty()
        return st

    @app.post("/api/v1/execute")
    def execute(req: ExecReq):
        return rt.gateway.execute(req.decision_id, initiated_by="USER")

    @app.post("/api/v1/positions/close")
    def close_positions(req: CloseReq):
        if req.confirm != "ZAMKNIJ":
            raise HTTPException(400, "CONFIRMATION_REQUIRED_TYPE_ZAMKNIJ")
        return rt.manager.close_positions(req.scope, req.ticket)

    @app.post("/api/v1/positions/{ticket}/adopt")
    def adopt(ticket: int, req: CloseReq):
        if req.confirm != "PRZEJMIJ":
            raise HTTPException(400, "CONFIRMATION_REQUIRED_TYPE_PRZEJMIJ")
        return rt.manager.adopt(ticket)

    @app.post("/api/v1/mt5/reconnect")
    def reconnect():
        rt.bridge.state = "RECONNECTING"
        rt.bridge.next_retry = 0
        return {"ok": True}

    @app.post("/api/v1/news/refresh")
    def news_refresh():
        rt.news.refresh_now()
        return {"ok": True}

    @app.get("/api/v1/diagnostics")
    def diagnostics():
        from ..runtime import platform_info
        b = rt.bridge
        raw = {tf: [x["t_raw"] for x in b.bars(tf, limit=4)] for tf in TIMEFRAMES}
        return {"app": {"version": APP_VERSION, "contract": API_CONTRACT_VERSION, "synthetic": rt.demo}, "platform": platform_info(),
                "connection": b.connection_status(), "symbol": b.symbol_status_dict(), "tf_meta": b.tf_meta(),
                "raw_last_bar_opens": raw, "quote": b.quote_status(), "pc_clock": rt.pcclock.snapshot(),
                "worker": {"calls": rt.worker.calls, "failures": rt.worker.failures, "module_error": rt.worker.module_error},
                "db_schema": rt.db.schema_versions(), "agent": rt.agent.status(), "news": {k: v for k, v in rt.news.summary().items() if k in ("status", "error", "failed_sources")},
                "engine": {"last_error": rt.engine.last_error, "cycle_ms": rt.engine.cycle_ms, "required_bars": rt.engine.required}}

    @app.post("/api/v1/admin/shutdown")
    async def shutdown():
        rt.log.info("APP", "SHUTDOWN_REQUEST", "Żądanie zatrzymania aplikacji")
        loop = asyncio.get_running_loop()
        loop.call_later(0.5, rt.request_shutdown)
        return {"ok": True}

    # ------------------------------------------------------------ websocket
    @app.websocket("/api/v1/ws")
    async def ws(websocket: WebSocket):
        if not sec.host_ok(websocket.headers.get("host")) or not sec.origin_ok(websocket.headers.get("origin")):
            await websocket.close(code=4403)
            return
        sid = websocket.cookies.get(SESSION_COOKIE)
        await websocket.accept()
        try:
            hello = json.loads(await asyncio.wait_for(websocket.receive_text(), timeout=10))
        except (asyncio.TimeoutError, ValueError, WebSocketDisconnect):
            await websocket.close(code=4400)
            return
        if not sec.csrf_ok(sid, hello.get("csrf")):
            await websocket.close(code=4403)
            return
        queue: asyncio.Queue = asyncio.Queue(maxsize=2000)
        unsub = rt.bus.subscribe_async(asyncio.get_running_loop(), queue)
        try:
            last = hello.get("last_seq")
            replay = rt.bus.since(int(last)) if isinstance(last, int) and hello.get("boot_id") == rt.bus.boot_id else None
            if replay is None:
                await websocket.send_text(json.dumps({"type": "resync", "seq": rt.bus.seq, "boot_id": rt.bus.boot_id, "state": full_state()}, default=str))
            else:
                for ev in replay:
                    await websocket.send_text(json.dumps(ev, default=str))
            while True:
                ev = await queue.get()
                if ev.get("type") == "__overflow__":
                    while not queue.empty():
                        queue.get_nowait()
                    await websocket.send_text(json.dumps({"type": "resync", "seq": rt.bus.seq, "boot_id": rt.bus.boot_id, "state": full_state()}, default=str))
                    continue
                await websocket.send_text(json.dumps(ev, default=str))
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            unsub()

    return app
