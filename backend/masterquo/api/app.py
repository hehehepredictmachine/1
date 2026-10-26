"""HTTP + WebSocket API (contract /api/v1, version in version.API_CONTRACT_VERSION).

The built web monitor (frontend/dist) is served from the same origin. No CORS is enabled.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from .. import paths, stats
from ..execution.modes import ModeError
from ..media.gifinfo import gif_info
from ..timeutil import TIMEFRAMES, iso, utcnow
from ..version import API_CONTRACT_VERSION, APP_NAME, APP_VERSION
from .security import SESSION_COOKIE, LocalSecurity

log = logging.getLogger("masterquo.api")


class AssetConfirmReq(BaseModel):
    asset: str
    broker_symbol: str


class AssetActiveReq(BaseModel):
    asset: str


class LockReq(BaseModel):
    lock: str
    phrase: str | None = None


class ModeReq(BaseModel):
    mode: str
    confirm: str = ""


class PrimaryPathReq(BaseModel):
    instrument: str
    path: str


class OnReq(BaseModel):
    on: bool
    reason: str = "user"


class ExecReq(BaseModel):
    decision_id: str


class CloseReq(BaseModel):
    scope: str = "BOT"
    ticket: int | None = None
    confirm: str


SYMBOL_RX = r"^[A-Za-z0-9._#&$!+\-]{1,40}$"


class AskReq(BaseModel):
    question: str = Field(min_length=2, max_length=2000)


class KeyReq(BaseModel):
    api_key: str = Field(min_length=10, max_length=300)


class SecretReq(BaseModel):
    name: str
    value: str | None = None


class MLModeReq(BaseModel):
    mode: str = Field(pattern="^(OFF|SHADOW|ASSIST)$")


class MLTrainReq(BaseModel):
    include_approx: bool | None = None          # per job only (training installer); config ml.use_backfill_approx stays untouched


class MLBackfillReq(BaseModel):
    days: int = Field(30, ge=5, le=180)


class MLFlagReq(BaseModel):
    on: bool


class StrategyModeReq(BaseModel):
    strategy_mode: str = Field(pattern="^(AUTO|MANUAL)$")
    manual_strategy_id: str | None = Field(default=None, max_length=4)


class StrategyToggleReq(BaseModel):
    strategy_id: str = Field(pattern="^S[0-9]{2}$")          # checked against the registry in the endpoint (S11, S12 included)
    scan: bool | None = None
    trade: bool | None = None


class ProfileReq(BaseModel):
    profile: str = Field(pattern="^(ACTIVE|ORIGINAL)$")


MEDIA_SLOTS = {"background": ("background-matrix.gif", "background-matrix-static.webp"), "frog": ("frog-dance.gif", "frog-dance-static.png")}
MAX_GIF_BYTES = 15 * 1024 * 1024


class SetupViewReq(BaseModel):
    mode: str = Field(pattern="^(AUTO|SELECTED|ALL)$")
    strategy_id: str | None = Field(default=None, max_length=4)
    focus_setup_id: str | None = Field(default=None, max_length=120)


class LeverageReq(BaseModel):
    mode: str = Field(pattern="^(AUTO|MANUAL)$")
    limit: int | None = Field(default=None, ge=1, le=1000)


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
                                                   "img-src 'self' data: blob:; connect-src 'self' ws://127.0.0.1:%d ws://localhost:%d; "
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
        if base not in f.parents or not f.is_file() or f.suffix not in (".png", ".webp", ".svg", ".ico", ".jpg", ".gif"):
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
                "prefs": {**rt.prefs.all(), "exposure": rt.prefs.exposure_limit()},
                "engine": {"last_error": rt.engine.last_error, "cycle_ms": rt.engine.cycle_ms, "full_cycles": rt.engine.full_count},
                "agent": rt.agent.status(), "agent_last": rt.agent.public_result(rt.agent.last_result), "mode": mode,
                "risk_config": cfg.risk.model_dump(), "costs_config": cfg.costs.model_dump(), "strategy_config": cfg.strategy.model_dump(),
                "news": rt.news.summary(), "positions": {"positions": b.positions, "orders": b.orders},
                "managed": rt.db.query("SELECT * FROM managed_positions WHERE state='OPEN'"),
                "attempts": rt.gateway.recent_attempts(15), "paper": rt.paper.account() if mode["mode"] == "PAPER" else None,
                "logs": logs_list(60), "pc_clock": rt.pcclock.snapshot(), "manager": {"reconciled_epoch": rt.manager.reconciled_epoch,
                                                                                     "last_error": rt.manager.last_error},
                "first_run_completed": cfg.first_run_completed,
                "auto": rt.engine.active.status(compact=True), "active_config": cfg.active.model_dump(mode="json"),
                "ml": rt.ml.status(compact=True), "markets": rt.scanner.summary(),
                "bot_signals": {**rt.signals.status(), **rt.signals.list(limit=40)},
                "assets": rt.assets.state(), "execution_lock": cfg.execution.lock, "lab": rt.lab.summary(cfg.assets.active),
                "lab_neural": _nss_compact(cfg.assets.active)}

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

    @app.get("/api/v1/volatility")
    def volatility():
        return rt.engine.volatility()

    # ------------------------------------------------------------ 1.10: walls for strategies, IV import, structure (S/R, range, patterns)
    @app.get("/api/v1/timeframes")
    def timeframes():
        """TF registry (role per TF) + which TFs each strategy needs - the chart pages are built from this, never from a
        hard-coded list. Data status per TF from the engine's data-quality gate."""
        from ..strategies import registry as _reg
        from ..timeutil import TF_REGISTRY
        dq = (rt.engine.dq or {}).get("timeframes") or {}
        strat = {d["strategy_id"]: {"setup_tfs": d["setup_tfs"], "required_tfs": d["required_tfs"], "context_tf": d["context_tf"], "name": d["name"]}
                 for d in _reg.describe()}
        return {"timeframes": [{"tf": tf, "seconds": v["seconds"], "role": v["role"], "core": v["core"],
                                "data": (dq.get(tf) or {}).get("status"), "closed_bars": (dq.get(tf) or {}).get("closed_bars"),
                                "required": (dq.get(tf) or {}).get("required"), "used_by": sorted(sid for sid, x in strat.items()
                                                                                                     if tf in x["setup_tfs"] or tf in x["required_tfs"] or tf == x["context_tf"])}
                               for tf, v in TF_REGISTRY.items()], "strategies": strat}

    @app.get("/api/v1/forecast")
    def forecast_get():
        """SHADOW candle analytics + price forecasts 5/15/30 + Double Retest v2 research state. Never an order permission."""
        return {**rt.forecast.public(), "registry": rt.forecast.registry(), "training": rt.forecast.training_status(),
                "config": rt.cfg.get().forecast.model_dump(), "shadow_summary": rt.forecast.shadow_summary()}

    # ------------------------------------------------------------ 1.13 analytics + pattern library (observational)
    # ------------------------------------------------------------ 1.14 lab (XAUUSD / BTC)
    def _nss_compact(asset: str) -> dict | None:
        snap = (rt.nss.last or {}) if getattr(rt, "nss", None) is not None and rt.nss.inst == asset else {}
        return {k: snap.get(k) for k in ("inference_id", "seq", "asset", "setup_id", "side", "technical_status", "mode", "model_hash", "computed_at",
                                         "expires_at")} if snap else None

    def _asset(asset: str | None) -> str:
        a = asset or rt.cfg.get().assets.active
        if a not in ("XAUUSD", "BTC"):
            raise HTTPException(403, f"ASSET_NOT_ALLOWED:{a}")
        return a

    @app.get("/api/v1/lab")
    def lab_state(asset: str | None = None):
        return rt.lab.public(_asset(asset))

    @app.get("/api/v1/lab/traceability")
    def lab_trace():
        from ..lab import traceability
        return {"rows": traceability.ROWS, "summary": traceability.summary()}

    @app.get("/api/v1/lab/memory")
    def lab_memory(tf: str = Query(...), t: str = Query(...)):
        from ..lab.sessions import memory_sequence
        if tf not in TIMEFRAMES:
            raise HTTPException(400, "INVALID_TIMEFRAME")
        by = {x: [b for b in rt.bridge.bars(x, 500, include_forming=False) if b.get("open_utc")] for x in ("M1", "M5", "M15", "M30", "H1", "H4", "D1")}
        return {"asset": rt.cfg.get().assets.active, **memory_sequence(by, tf, t)}

    @app.post("/api/v1/lab/train")
    def lab_train(body: dict = Body(default={})):
        from ..lab.protocol import default_protocol, FAMILIES, EXPERIMENTS
        a = _asset(body.get("asset"))
        if body.get("task_id") == "SCALP_SETUP_MARKET_V1":           # PMW-UPD-04 NSS: same jobs view, own child process, activate=none
            return _nss_job(["train", "--asset", a, "--activate", "none"])
        if a != rt.cfg.get().assets.active:
            raise HTTPException(409, "TRAIN_ONLY_ACTIVE_ASSET")
        sym = rt.assets.check_asset(a, "TRAINING")
        if rt.bridge.state != "CONNECTED":
            raise HTTPException(409, "MT5_NOT_CONNECTED")
        fams = [f for f in (body.get("families") or FAMILIES) if f in FAMILIES]
        exps = [e for e in (body.get("experiments") if body.get("experiments") is not None else EXPERIMENTS) if e in EXPERIMENTS]
        bars = [b for b in rt.bridge.symbol_bars(sym, "M5", int(min(max(body.get("bars") or 20000, 2000), 100000))) if b.get("closed") and b.get("open_utc")]
        prot = default_protocol(a, families=fams, experiments=exps, min_events=int(body.get("min_events") or 600))
        meta = rt.bridge.symbol_meta(sym) or {}
        src = "SYNTHETIC" if (rt.demo or rt.bridge.synthetic or rt.cfg.get().synthetic_demo) else "MT5"
        return rt.lab.trainer.start(a, bars, point=float(meta.get("point") or 0.01), data_source=src,
                                    instrument_id=rt.assets.instrument(a)["instrument_id"], protocol=prot,
                                    artifact_family=body.get("artifact_family") if (body.get("artifact_family") in fams or body.get("artifact_family") == "ALL") else "auto")

    @app.get("/api/v1/lab/jobs")
    def lab_jobs():
        return {"jobs": rt.lab.trainer.public()}

    @app.post("/api/v1/lab/jobs/{jid}/cancel")
    def lab_cancel(jid: str):
        return rt.lab.trainer.cancel(jid)

    # ------------------------------------------------------------ PMW-UPD-02: IQ Gold Gann / IQ Star Lines / PAL02M / SAR
    @app.get("/api/v1/indicator-context")
    def indicator_context_status():
        from ..extind import trainer as ict
        inst = rt.cfg.get().assets.active
        reg_p = ict.root(inst) / "registry.json"
        reg = json.loads(reg_p.read_text(encoding="utf-8")) if reg_p.exists() else {"active": None, "runs": {}}
        runs = {k: v for k, v in sorted(reg.get("runs", {}).items())[-10:]}
        return {"instrument": inst, "sources": rt.extind.status(inst), "sar": {"profile": "MQ_SAR_WILDER_PROFILE_V1", "live_params": {"step": 0.02, "max": 0.2},
                "implementation_status": "VERIFIED_REFERENCE_TESTS", "weights_training": "NOT_APPLICABLE", "calibration": "GRID_ON_TRAIN_FOLD (indicator-context calibrate-sar)",
                "mt5_parity": "MT5_PARITY_NOT_RUN"}, "model": {"active": reg.get("active"), "runs": runs,
                "task_id": "SCALP_TP1_FIRST_WITHIN_FROZEN_POLICY_V1", "schema": "SCALP_INDICATOR_CONTEXT_V1"}}

    @app.get("/api/v1/indicator-context/chart")
    def indicator_context_chart(tf: str = Query("M5")):
        from ..scalp.indicators import SAR_PROFILE, sar_points
        from ..timeutil import utcnow as _now
        b = [x for x in rt.bridge.bars(tf, 600, include_forming=False) if x.get("open_utc")]
        sar = None
        if len(b) >= 2:
            pts = sar_points([x["h"] for x in b], [x["l"] for x in b], 0.02, 0.2)
            sar = {"profile": SAR_PROFILE, "params": {"step": 0.02, "max": 0.2},
                   "points": [{"t": b[i]["open_utc"], "sar": p["sar"], "trend": p["trend"], "flip": p["flip"]} for i, p in enumerate(pts) if p]}
        inst = rt.cfg.get().assets.active
        lv = []
        for a, short in (("IQ_GOLD_GANN", "IQ Gann"), ("IQ_STAR_LINES", "IQ Star")):
            snap = rt.extind.as_of(a, inst, _now())
            for x in (snap or {}).get("levels") or []:
                if x.get("kind") == "LEVEL" and x.get("price") is not None:
                    lv.append({"price": x["price"], "title": f"{short}: {x.get('role')}", "adapter": a, "snapshot_id": snap["snapshot_id"],
                               "known_at": snap["available_at"]})
        return {"tf": tf, "instrument": inst, "sar": sar, "ext_levels": lv}

    @app.get("/api/v1/indicator-context/inventory")
    def indicator_context_inventory(adapter: str = Query(...)):
        if adapter not in ("IQ_GOLD_GANN", "IQ_STAR_LINES", "PAL02M"):
            raise HTTPException(400, "UNKNOWN_ADAPTER")
        from ..extind import mapping as emp
        return {"adapter": adapter, "heartbeat": rt.extind.heartbeat.get(adapter), "mapping": emp.mapping(adapter), "manifest": emp.manifest(adapter)}

    @app.put("/api/v1/indicator-context/mapping")
    def indicator_context_mapping(body: dict):
        from ..extind import mapping as emp
        a = body.get("adapter")
        if a not in ("IQ_GOLD_GANN", "IQ_STAR_LINES"):
            raise HTTPException(400, "MAPPING_ONLY_FOR_IDENTIFIED_IQ")
        try:
            return emp.save_mapping(a, body)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/v1/indicator-context/train")
    def indicator_context_train(body: dict):
        """Separate process (never in the bot); POST returns at once, the result is in the registry/report."""
        import subprocess
        inst = body.get("asset") or rt.cfg.get().assets.active
        if inst not in ("XAUUSD", "BTC"):
            raise HTTPException(400, "UNKNOWN_INSTRUMENT")
        from ..training import core as tc
        log = open(tc.training_dir() / "indicator_context_train.log", "a", encoding="utf-8")
        kw = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if os.name == "nt" else {"start_new_session": True}
        cmd = [sys.executable, "-m", "masterquo", "indicator-context", "train", "--asset", inst]
        if body.get("commission") is not None:
            cmd += ["--commission", str(float(body["commission"]))]
        subprocess.Popen(cmd, cwd=str(paths.ROOT_DIR / "backend"), stdout=log, stderr=subprocess.STDOUT, **kw)
        return {"started": True, "instrument": inst}

    @app.post("/api/v1/indicator-context/activate")
    def indicator_context_activate(body: dict):
        from ..extind import trainer as ict
        try:
            return {"ok": True, "active": ict.activate(body.get("asset") or rt.cfg.get().assets.active, str(body.get("run_id")), str(body.get("variant")))}
        except (ValueError, OSError, KeyError) as exc:
            return {"ok": False, "reason": str(exc)}

    @app.post("/api/v1/indicator-context/rollback")
    def indicator_context_rollback(body: dict):
        from ..extind import trainer as ict
        try:
            return {"ok": True, "active": ict.rollback(body.get("asset") or rt.cfg.get().assets.active)}
        except (ValueError, OSError) as exc:
            return {"ok": False, "reason": str(exc)}

    @app.get("/api/v1/lab/models")
    def lab_models(asset: str | None = None):
        a = _asset(asset)
        return {"asset": a, "models": rt.lab.trainer.models(a)}

    @app.get("/api/v1/lab/studies/{jid}")
    def lab_study(jid: str):
        if not _re.fullmatch(r"LJOB-[0-9TZ]+-[0-9a-f]{4}", jid):
            raise HTTPException(400, "INVALID_JOB_ID")
        f = rt.lab.trainer.root / "studies" / f"{jid}.json"
        if not f.exists():
            raise HTTPException(404, "NO_STUDY")
        return json.loads(f.read_text(encoding="utf-8"))

    @app.get("/api/v1/lab/trials")
    def lab_trials(asset: str | None = None):
        a = _asset(asset)
        return {"asset": a, "trials": rt.db.query("SELECT trial_id, created_at, horizon, model_family, protocol_id, data_hash, status, metrics, note "
                                                  "FROM lab_trials WHERE asset=? ORDER BY created_at DESC LIMIT 200", (a,)),
                "holdout_access": rt.db.query("SELECT * FROM lab_holdout_access WHERE asset=? ORDER BY at DESC LIMIT 50", (a,))}

    @app.post("/api/v1/lab/zones")
    def lab_zone_add(body: dict = Body(...)):
        a = body.get("asset") or rt.cfg.get().assets.active
        rt.assets.check_asset(a, "ZONES")
        try:
            return rt.lab.zones.add_manual(a, str(body["tf"]), str(body["kind"]), float(body["top"]), float(body["bottom"]), str(body["origin_time"]))
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, f"INVALID_ZONE: {exc}") from exc

    @app.patch("/api/v1/lab/zones/{zone_id}")
    def lab_zone_patch(zone_id: str, body: dict = Body(...)):
        try:
            return rt.lab.zones.patch(zone_id, int(body["expected_revision"]), top=body.get("top"), bottom=body.get("bottom"), state=body.get("state"),
                                      blacklist=body.get("blacklist"), reason=str(body.get("reason") or ""))
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.delete("/api/v1/lab/zones/{zone_id}")
    def lab_zone_delete(zone_id: str, expected_revision: int):
        try:
            return rt.lab.zones.delete(zone_id, expected_revision)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/v1/lab/zones/diagnostics")
    def lab_zone_diag(asset: str | None = None):
        a = asset or rt.cfg.get().assets.active
        return rt.lab.zones.diagnostics(a)

    @app.get("/api/v1/lab/zones")
    def lab_zones(asset: str | None = None):
        a = _asset(asset)
        return {"asset": a, "zones": rt.lab.zones.list_asof(a)[-100:], "events": rt.lab.zones.events[-10:], "snapshot": rt.lab.zones.snapshot_status.get(a)}

    @app.get("/api/v1/lab/repaint")
    def lab_repaint():
        return {"report": rt.lab.repaint.report(),
                "recent": rt.db.query("SELECT asset, module, tf, bar_open, observed_at, change FROM lab_repaint ORDER BY id DESC LIMIT 50")}

    @app.post("/api/v1/lab/tradepad")
    def lab_tradepad(body: dict = Body(...)):
        from ..lab.edge import trade_pad_plan
        a = rt.cfg.get().assets.active
        sym = rt.assets.check_asset(a, "TRADEPAD")
        meta = rt.bridge.symbol_meta(sym)
        if not meta:
            raise HTTPException(409, "NO_SYMBOL_METADATA")
        meta = {**meta, **{k: (rt.bridge.symbol_info or {}).get(k) for k in ("volume_min", "volume_step")}}
        try:
            plan = trade_pad_plan(side=str(body.get("side")), entry=float(body["entry"]), sl=float(body["sl"]), tp=float(body["tp"]),
                                  lots=float(body.get("lots") or 0.01), meta=meta, quote=rt.bridge.quote_status(),
                                  commission_per_lot_side=float(rt.cfg.get().scalp.commission_per_lot_side or 0))
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, f"INVALID_PLAN: {exc}") from exc
        return {"asset": a, "broker_symbol": sym, **plan, "execution_lock": rt.cfg.get().execution.lock}

    @app.post("/api/v1/lab/tradepad/execute")
    def lab_tradepad_execute(body: dict = Body(default={})):
        """Compatibility adapter: explicit routing to the Manual Pad gates (intent required; LOCKED still blocks real mutations)."""
        iid = body.get("intent_id")
        if not iid:
            raise HTTPException(400, "INTENT_REQUIRED: POST /api/v1/manual/plan → /api/v1/manual/intents → /execute")
        return manual_execute(str(iid), {"action_revision": body.get("action_revision", 1)})

    # ------------------------------------------------------------ PMW-UPD-07 R12 Manual Trade Pad (explicit user actions only)
    @app.post("/api/v1/manual/plan")
    def manual_plan(body: dict = Body(...)):
        from ..execution.manual import PlanError
        try:
            return rt.manual.plan(body)
        except PlanError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/v1/manual/intents")
    def manual_intent(body: dict = Body(...)):
        from ..execution.manual import PlanError
        try:
            return rt.manual.create_intent(str(body.get("plan_id")))
        except PlanError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/v1/manual/intents")
    def manual_intents():
        return {"items": rt.manual.intents(30)}

    @app.get("/api/v1/manual/intents/{iid}")
    def manual_intent_get(iid: str):
        r = rt.manual.intent(iid)
        if not r:
            raise HTTPException(404, "INTENT_NOT_FOUND")
        return r

    @app.post("/api/v1/manual/intents/{iid}/execute")
    def manual_execute(iid: str, body: dict = Body(default={})):
        from ..execution.manual import PlanError
        try:
            return rt.manual.execute(iid, int(body.get("action_revision") or 1))
        except PlanError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/v1/manual/intents/{iid}/manage")
    def manual_manage(iid: str, body: dict = Body(...)):
        from ..execution.manual import PlanError
        try:
            return rt.manual.manage(iid, str(body.get("action")), int(body.get("action_revision") or 1), offset_points=float(body.get("offset_points") or 0),
                                    volume=None if body.get("volume") is None else float(body["volume"]))
        except PlanError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/v1/manual/reconcile")
    def manual_reconcile():
        return rt.manual.reconcile()

    # ------------------------------------------------------------ PMW-UPD-07 structure intelligence (GET never trains)
    def _si_inst(asset):
        a = asset or rt.cfg.get().assets.active
        rt.assets.check_asset(a, "STRUCTURE_INTELLIGENCE")
        return a

    @app.get("/api/v1/structure-intelligence")
    def si_latest():
        snap = rt.si.last
        return {"snapshot": snap, "status": "OK" if snap else "NO_SNAPSHOT_YET",
                "jobs": [rt.si.job(j) for j in list(rt.si.jobs)[-5:]]}

    @app.get("/api/v1/structure-intelligence/snapshots/{sid}")
    def si_snapshot(sid: str):
        r = rt.db.one("SELECT payload FROM si_snapshots WHERE snapshot_id=?", (sid,))
        if not r:
            raise HTTPException(404, "SNAPSHOT_NOT_FOUND")
        return json.loads(r["payload"])

    @app.get("/api/v1/structure-intelligence/forecasts")
    def si_forecasts(asset: str | None = None, limit: int = Query(50, ge=1, le=500)):
        return {"items": rt.si.forecasts(_si_inst(asset), limit)}

    @app.get("/api/v1/structure-intelligence/models")
    def si_models(asset: str | None = None):
        from ..lab import structure_task as T
        a = _si_inst(asset)
        reg = T._reg(a)
        return {"instrument": a, "shadow": reg.get("shadow"), "runs": reg.get("runs"), "holdout_access": list((reg.get("holdout_access") or {}).keys()),
                "indicator_profile": T.indicator_profile(a), "families": list(T.FAMILIES_ALL), "execution": "NEVER_AUTOMATIC"}

    @app.post("/api/v1/structure-intelligence/models/select")
    def si_select(body: dict = Body(...)):
        from ..lab import structure_task as T
        try:
            return T.select_shadow(_si_inst(body.get("asset")), str(body.get("candidate_id")))
        except (ValueError, OSError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/v1/structure-intelligence/models/rollback")
    def si_rollback(body: dict = Body(...)):
        from ..lab import structure_task as T
        try:
            return T.rollback(_si_inst(body.get("asset")), str(body.get("task") or T.TASK_MOVE))
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/v1/structure-intelligence/neutralization")
    def si_neutral(asset: str | None = None, limit: int = Query(120, ge=1, le=2000)):
        return rt.si.neutralization(_si_inst(asset), limit)

    @app.get("/api/v1/structure-intelligence/quotes")
    def si_quotes():
        return rt.si.quotes_public()

    @app.get("/api/v1/structure-intelligence/quote-forecasts")
    def si_quote_fc(limit: int = Query(100, ge=1, le=1000)):
        return {"items": rt.si.quote_forecasts(limit)}

    @app.get("/api/v1/structure-intelligence/quote-quality")
    def si_quote_q():
        return rt.si.quote_quality()

    # ------------------------------------------------------------ PMW-UPD-09 R21-R25 sections (read-only; GET never trains)
    def _mkey(asset, tf):
        a = _si_inst(asset)
        if tf not in ("M1", "M5", "M15", "H1"):
            raise HTTPException(400, "TF_INVALID")
        k = rt.si.market.keys.get((a, tf))
        if k is None:
            raise HTTPException(404, "NO_MARKET_STATE_YET (sekcja powstaje przy pierwszym snapshocie Structure Intelligence)")
        return k

    @app.get("/api/v1/structure-intelligence/regimes")
    def si_regimes(asset: str | None = None, tf: str = "M1", limit: int = Query(300, ge=1, le=600)):
        return rt.si.market.regimes(_mkey(asset, tf), limit)

    @app.get("/api/v1/structure-intelligence/swings")
    def si_swings(asset: str | None = None, tf: str = "M1", as_of: float | None = None, limit: int = Query(120, ge=1, le=600)):
        return rt.si.market.swings(_mkey(asset, tf), as_of, limit)

    @app.get("/api/v1/structure-intelligence/swings/{sid}")
    def si_swing(sid: str, asset: str | None = None, as_of: float | None = None):
        r = rt.si.market.swing(_si_inst(asset), sid, as_of)
        if r is None:
            raise HTTPException(404, "SWING_NOT_FOUND (kontekst usunięty albo spoza okna)")
        return r

    @app.get("/api/v1/structure-intelligence/smma")
    def si_smma(asset: str | None = None, tf: str = "M1", limit: int = Query(200, ge=1, le=600)):
        return rt.si.market.smma(_mkey(asset, tf), limit)

    @app.get("/api/v1/structure-intelligence/zscore")
    def si_zscore(asset: str | None = None, tf: str = "M1", mode: str = "INCLUSIVE_N", n: int = Query(20, ge=2, le=500)):
        if mode not in ("INCLUSIVE_N", "PREVIOUS_N"):
            raise HTTPException(400, "ZSCORE_MODE_INVALID")
        return rt.si.market.zscore(_mkey(asset, tf), mode, n)

    @app.get("/api/v1/structure-intelligence/native-status")
    def si_native(asset: str | None = None):
        return rt.si.native_status(_si_inst(asset))

    @app.get("/api/v1/structure-intelligence/model-diagnostics")
    def si_model_diag(asset: str | None = None, run: str | None = None):
        from ..lab import structure_task as T
        a = _si_inst(asset)
        reg = T._reg(a)
        rid = run or (sorted(reg["runs"])[-1] if reg["runs"] else None)
        if not rid or rid not in reg["runs"]:
            return {"status": "NO_RUNS"}
        rp = Path(reg["runs"][rid]["run_dir"]) / "report.json"
        rep = json.loads(rp.read_text(encoding="utf-8")) if rp.exists() else {}
        diag = {}
        for f in rep.get("folds", []):
            for fam, res in (f.get("families") or {}).items():
                for r in res:
                    if r.get("diagnostics"):
                        diag.setdefault(fam, []).append({"fold": f["fold"], "seed": r.get("seed"), "status": r.get("status"), **r["diagnostics"]})
        return {"run_id": rid, "role": rep.get("role"), "spike_profile": rep.get("spike_profile"), "transform": rep.get("transform"),
                "diagnostics": diag, "status": rep.get("status")}

    # ------------------------------------------------------------ PMW-UPD-11 flow context (read-only; GET never trains)
    def _fkey(asset, tf):
        a = _si_inst(asset)
        if tf not in ("M1", "M5", "M15", "H1"):
            raise HTTPException(400, "TF_INVALID")
        k = rt.si.flow.keys.get((a, tf))
        if k is None:
            raise HTTPException(404, "NO_FLOW_STATE_YET (powstaje przy pierwszym snapshocie)")
        return k

    @app.get("/api/v1/flow-context")
    def fc_summary(asset: str | None = None):
        a = _si_inst(asset)
        return {"instrument": a, "tfs": {tf: rt.si.flow.summary(k) for (i, tf), k in rt.si.flow.keys.items() if i == a},
                "profile": __import__("masterquo.lab.flow_context.task", fromlist=["profile"]).profile(a)}

    @app.get("/api/v1/flow-context/series")
    def fc_series(asset: str | None = None, tf: str = "M15", limit: int = Query(300, ge=1, le=800)):
        return rt.si.flow.series(_fkey(asset, tf), limit)

    @app.get("/api/v1/flow-context/channels")
    def fc_channels(asset: str | None = None, tf: str = "M15", as_of: str | None = None, mode: str = "CURRENT_MAP_FULL_WIDTH"):
        if mode not in ("CURRENT_MAP_FULL_WIDTH", "HISTORY_AS_KNOWN"):
            raise HTTPException(400, "MODE_INVALID")
        return rt.si.flow.channels(_fkey(asset, tf), as_of, mode)

    @app.get("/api/v1/flow-context/markov")
    def fc_markov(asset: str | None = None):
        return rt.si.flow.markov(_fkey(asset, "M1"))

    @app.get("/api/v1/flow-context/stopdistance")
    def fc_stop(asset: str | None = None, tf: str = "M15", entry: float | None = None, side: str | None = None, strategy_sl_points: float | None = None):
        return rt.si.flow.stopdistance(_fkey(asset, tf), entry, side, strategy_sl_points)

    @app.get("/api/v1/flow-context/native")
    def fc_native(asset: str | None = None):
        a = _si_inst(asset)
        return rt.si.flow.native(a, rt.cfg.get().mt5.symbol)

    @app.get("/api/v1/flow-context/models")
    def fc_models(asset: str | None = None):
        from ..lab.flow_context import task as FT
        a = _si_inst(asset)
        reg = FT._reg(a)
        return {"instrument": a, "runs": reg["runs"], "shadow": reg["shadow"], "families": list(FT.FAMILIES), "task": FT.TASK, "schema": FT.SCHEMA,
                "execution": "NEVER_AUTOMATIC"}

    # ------------------------------------------------------------ PMW-UPD-14 VAMD / FD / SMC / Buffer Inspector (GET never trains)
    def _ckey(asset, tf):
        a = _si_inst(asset)
        if tf not in ("M1", "M5", "M15", "H1"):
            raise HTTPException(400, "TF_INVALID")
        k = rt.si.ctx.keys.get((a, tf))
        if k is None:
            raise HTTPException(404, "NO_CONTEXT_STATE_YET (powstaje przy pierwszym snapshocie)")
        return k

    @app.get("/api/v1/lab/context")
    def ctx_summary(asset: str | None = None):
        from ..lab.context_ind import task as CT
        a = _si_inst(asset)
        return {"instrument": a, "tfs": {tf: rt.si.ctx.summary(k) for (i, tf), k in rt.si.ctx.keys.items() if i == a}, "profile": CT.profile(a)}

    @app.get("/api/v1/lab/vamd")
    def ctx_vamd(asset: str | None = None, tf: str = "M5", limit: int = Query(300, ge=1, le=600)):
        return rt.si.ctx.vamd(_ckey(asset, tf), limit)

    @app.get("/api/v1/lab/fractal-regime")
    def ctx_fd(asset: str | None = None, tf: str = "M5", limit: int = Query(300, ge=1, le=600)):
        return rt.si.ctx.fractal(_ckey(asset, tf), limit)

    @app.get("/api/v1/lab/smc")
    def ctx_smc(asset: str | None = None, tf: str = "M5", as_of: float | None = None, limit: int = Query(300, ge=1, le=800)):
        return rt.si.ctx.smc(_ckey(asset, tf), as_of, limit)

    @app.get("/api/v1/lab/buffers/reports")
    def buf_reports():
        from ..lab.context_ind import buffers as BF
        return {"reports": BF.list_reports(), "note": "raporty importowane z PWM_BufferInspector (MT5); panel nie skanuje terminala zdalnie"}

    @app.get("/api/v1/lab/buffers/reports/{rid}")
    def buf_report(rid: str):
        from ..lab.context_ind import buffers as BF
        r = BF.get_report(rid)
        if r is None:
            raise HTTPException(404, "REPORT_NOT_FOUND")
        return r

    @app.post("/api/v1/lab/buffers/reports/import")
    def buf_import(body: dict = Body(...)):
        from ..extind.contract import EnvelopeError
        from ..lab.context_ind import buffers as BF
        files = os.environ.get("MQ_MT5_FILES_DIR")
        name = str(body.get("file") or "PWM_BUFFER_REPORT.json")
        if not files or not name.replace("_", "").replace("-", "").replace(".", "").isalnum() or not name.endswith(".json"):
            raise HTTPException(400, "FILE_NOT_WHITELISTED_OR_NO_FILES_DIR")
        p = Path(files) / "PMW" / name
        if not p.exists():
            raise HTTPException(404, "REPORT_FILE_MISSING (uruchom PWM_BufferInspector w MT5)")
        try:
            d = BF.import_report(p.read_bytes())
        except EnvelopeError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"report_id": d["report_id"], "coverage": d["coverage"], "instances": len(d.get("instances") or [])}

    @app.get("/api/v1/lab/buffers/mappings")
    def buf_mappings():
        from ..lab.context_ind import buffers as BF
        return {"mappings": BF.mappings(), "required": list(BF.MAPPING_REQUIRED)}

    @app.post("/api/v1/lab/buffers/mappings/validate")
    def buf_validate(body: dict = Body(...)):
        from ..lab.context_ind import buffers as BF
        return BF.validate_mapping(body)

    @app.post("/api/v1/lab/buffers/mappings")
    def buf_save(body: dict = Body(...)):
        from ..lab.context_ind import buffers as BF
        return BF.save_mapping({k: body.get(k) for k in BF.MAPPING_REQUIRED + ("chart_window", "instance", "notes")})

    @app.post("/api/v1/lab/buffers/mappings/{mid}/rollback")
    def buf_rollback(mid: str):
        from ..lab.context_ind import buffers as BF
        try:
            return BF.rollback_mapping(mid)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/api/v1/lab/buffers/source")
    def buf_source(tf: str = "M5"):
        return rt.si.ctx.external(rt.cfg.get().mt5.symbol, tf)

    @app.post("/api/v1/lab/context/calibrate")
    def ctx_calibrate(body: dict = Body(default={})):
        kind = {"calibrate": "context_calibrate", "dataset": "context_dataset", "train": "context_train"}.get(str(body.get("step") or "calibrate"))
        if kind is None:
            raise HTTPException(400, "STEP_INVALID")
        try:
            return rt.si.start_job(kind, {k: body.get(k) for k in ("asset", "families", "profile")})
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/v1/structure-intelligence/quality")
    def si_quality(asset: str | None = None):
        return rt.si.quality(_si_inst(asset))

    @app.post("/api/v1/structure-intelligence/jobs")
    def si_job_start(body: dict = Body(...)):
        try:
            return rt.si.start_job(str(body.get("kind")), {k: body.get(k) for k in ("asset", "task", "families", "profile", "experiment", "sew_operators", "days",
                                                                                  "encoder", "attention", "transform")})
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/v1/structure-intelligence/jobs/{jid}")
    def si_job(jid: str):
        j = rt.si.job(jid)
        if not j:
            raise HTTPException(404, "JOB_NOT_FOUND")
        return j

    @app.post("/api/v1/structure-intelligence/jobs/{jid}/cancel")
    def si_job_cancel(jid: str):
        return {"ok": rt.si.cancel(jid)}

    # ------------------------------------------------------------ PMW-UPD-07 R05 Black-76 (pure maths; HV is never shown as IV)
    @app.post("/api/v1/black76/price")
    def b76_price(body: dict = Body(...)):
        from ..analytics import black76 as B
        try:
            d = B.discount(body.get("rate"), float(body["t_years"]), body.get("discount"))
            return B.price(float(body["forward"]), float(body["strike"]), float(body["sigma"]), float(body["t_years"]), d)
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(400, f"INVALID_INPUT: {exc}") from exc

    @app.post("/api/v1/black76/iv")
    def b76_iv(body: dict = Body(...)):
        from ..analytics import black76 as B
        try:
            d = B.discount(body.get("rate"), float(body["t_years"]), body.get("discount"))
            return dict(B.implied_vol(float(body["premium"]), float(body["forward"]), float(body["strike"]), float(body["t_years"]), d,
                                      str(body.get("kind") or "call")), source="IV_FROM_PREMIUM", version=B.VERSION)
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(400, f"INVALID_INPUT: {exc}") from exc

    @app.post("/api/v1/black76/forward")
    def b76_forward(body: dict = Body(...)):
        from ..analytics import black76 as B
        try:
            return B.forward_from_parity(list(body.get("pairs") or []), float(body.get("discount") or 1.0), exercise_style=str(body.get("exercise_style") or "UNKNOWN"))
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, f"INVALID_INPUT: {exc}") from exc

    @app.get("/api/v1/analytics")
    def analytics_get():
        return {**rt.analytics.summary(), "config": rt.cfg.get().analytics.model_dump()}

    @app.get("/api/v1/analytics/tf/{tf}")
    def analytics_tf(tf: str):
        if tf not in rt.cfg.get().analytics.timeframes:
            raise HTTPException(404, "TF_NOT_CONFIGURED")
        return rt.analytics.tf_state(tf, full=True)

    @app.get("/api/v1/analytics/history")
    def analytics_history(module: str | None = None, tf: str | None = None, limit: int = Query(100, ge=1, le=1000)):
        return {"items": rt.analytics.history(module, tf, limit)}

    @app.get("/api/v1/analytics/diagnostics")
    def analytics_diag():
        return rt.analytics.diagnostics()

    @app.get("/api/v1/patterns/samples")
    def pat_list(symbol: str | None = None, tf: str | None = None, status: str | None = None, rules_version: str | None = None):
        return {"items": rt.analytics.library.list(symbol, tf, status, rules_version), "jobs": rt.analytics.library.jobs(10)}

    @app.post("/api/v1/patterns/samples")
    def pat_add(body: dict = Body(...)):
        """Sample from the chart selection: {tf, start_utc, end_utc, note} - closed bars of the bot's feed (raw OHLCV kept)."""
        tf = str(body.get("tf") or "")
        bars = [b for b in rt.bridge.bars(tf, None, include_forming=False) if b.get("open_utc")] if tf in ("M1", "M5", "M15", "M30", "H1", "H4", "D1") else []
        sel = [{k: b[k] for k in ("open_utc", "o", "h", "l", "c", "tv")} for b in bars if str(body.get("start_utc")) <= b["open_utc"] <= str(body.get("end_utc"))]
        if not sel:
            raise HTTPException(400, "NO_CLOSED_BARS_IN_RANGE")
        r = rt.analytics.library.add_sample(rt.cfg.get().mt5.symbol, tf, sel, "CHART_SELECTION" if not rt.bridge._synthetic else "CHART_SELECTION_SYNTHETIC",
                                            body.get("note"))
        if not r["ok"]:
            raise HTTPException(400, r["error"])
        return r

    @app.get("/api/v1/patterns/samples/{sid}")
    def pat_get(sid: int):
        s = rt.analytics.library.get(sid)
        if not s:
            raise HTTPException(404, "SAMPLE_NOT_FOUND")
        return s

    @app.delete("/api/v1/patterns/samples/{sid}")
    def pat_del(sid: int):
        return {"ok": rt.analytics.library.delete(sid)}

    @app.post("/api/v1/patterns/samples/{sid}/validate")
    def pat_validate_one(sid: int):
        r = rt.analytics.library.validate_one(sid)
        if not r["ok"]:
            raise HTTPException(404, r["error"])
        return r

    @app.post("/api/v1/patterns/validate")
    def pat_validate(body: dict = Body(...)):
        ids = body.get("ids")
        if ids is not None and (not isinstance(ids, list) or not all(isinstance(i, int) for i in ids)):
            raise HTTPException(400, "IDS_MUST_BE_INT_LIST_OR_NULL")
        return rt.analytics.library.start_job(ids)

    @app.get("/api/v1/patterns/jobs/{job_id}")
    def pat_job(job_id: str):
        j = rt.analytics.library.job(job_id)
        if not j:
            raise HTTPException(404, "JOB_NOT_FOUND")
        return j

    @app.post("/api/v1/patterns/jobs/{job_id}/cancel")
    def pat_cancel(job_id: str):
        return {"ok": rt.analytics.library.cancel(job_id)}

    @app.post("/api/v1/patterns/jobs/{job_id}/resume")
    def pat_resume(job_id: str):
        r = rt.analytics.library.resume(job_id)
        if not r["ok"]:
            raise HTTPException(409, r["error"])
        return r

    @app.post("/api/v1/patterns/jobs/{job_id}/export")
    def pat_export_job(job_id: str):
        """Re-export the report from STORED results (no validation)."""
        return rt.analytics.library.export(job_id)

    @app.get("/api/v1/patterns/jobs/{job_id}/results")
    def pat_job_results(job_id: str):
        return {"job_id": job_id, "items": rt.analytics.library.results(job_id)}

    @app.get("/api/v1/patterns/results/{result_id}")
    def pat_result(result_id: str):
        """Saved immutable result for SHOW ON CHART - never re-analyses (REVALIDATE is the explicit POST validate)."""
        r = rt.analytics.library.result(result_id)
        if not r:
            raise HTTPException(404, "RESULT_NOT_FOUND")
        return r

    @app.get("/api/v1/patterns/samples/{sid}/result")
    def pat_sample_result(sid: int):
        r = rt.analytics.library.latest_result(sid)
        if not r:
            raise HTTPException(404, "NO_SAVED_RESULT – najpierw waliduj (VALIDATE / REVALIDATE)")
        return r

    @app.get("/api/v1/patterns/reports/{report_id}")
    def pat_report(report_id: str):
        r = rt.analytics.library.report(report_id)
        if not r:
            raise HTTPException(404, "REPORT_NOT_FOUND")
        return r

    @app.get("/api/v1/patterns/export")
    def pat_export():
        return rt.analytics.library.export_samples()

    @app.post("/api/v1/patterns/import")
    def pat_import(body: dict = Body(...)):
        return rt.analytics.library.import_samples(body)

    @app.get("/api/v1/patterns/live")
    def pat_live():
        a = rt.cfg.get().analytics
        return {"timeframes": {tf: (rt.analytics.state.get(tf) or {}).get("double_bottom") for tf in a.db_timeframes},
                "events": rt.analytics.events(50), "profile": a.db_profile}

    @app.get("/api/v1/scalp")
    def scalp_get():
        """Scalp profile (M5 Range -> M1 Sweep/Reclaim -> Retest) + hedge controller in SHADOW: MTF, setup, indicators, adapters,
        forecasts, hedge/risk, training and the separate validity statuses. Never an order permission."""
        return {**rt.scalp.public(), "config": rt.cfg.get().scalp.model_dump(), "profile": rt.scalp.prof, "registry": rt.scalp.registry()}

    # ------------------------------------------------------------------ PMW-SH-1 SCALPING / HEDGING
    @app.get("/api/v1/sh")
    def sh_get():
        """Strategy panel: service state, last evaluation per strategy (checklist, levels, models, risk, coordination), open plans
        with position / basket state, single config source with hash, model matrix and the event-model status."""
        from ..sh import config as SHC, models as SHM, tpmodel as SHT
        inst = rt.sh.instrument()
        st = rt.sh.public()
        return {**{k: v for k, v in st.items() if k != "snapshot"}, "config": SHC.load(), "config_errors": SHC.validate(SHC.load()),
                "models": SHM.matrix(rt, inst), "tp_model": SHT.status(inst), "snapshot": rt.sh.snapshot, "server_time": time.time()}

    @app.get("/api/v1/sh/signals")
    def sh_signals(strategy: str | None = None, limit: int = Query(100, ge=1, le=1000)):
        return {"items": rt.sh.store.recent_signals(strategy, 0.0, limit)}

    @app.get("/api/v1/sh/signals/{sid}")
    def sh_signal(sid: str):
        r = rt.sh.store.signal(sid)
        if not r:
            raise HTTPException(404)
        return r

    @app.get("/api/v1/sh/plans")
    def sh_plans(open_only: bool = False, limit: int = Query(50, ge=1, le=500)):
        q = rt.sh.quote(time.time())
        if open_only:
            return {"items": [rt.sh.plan_view(p, q) for p in rt.sh.store.open_plans()]}
        rows = rt.db.query("SELECT plan_id FROM sh_plans ORDER BY created_at DESC LIMIT ?", (limit,))
        return {"items": [rt.sh.plan_view(rt.sh.store.plan(r["plan_id"]), q) for r in rows]}

    @app.get("/api/v1/sh/plans/{pid}")
    def sh_plan(pid: str):
        r = rt.sh.store.plan(pid)
        if not r:
            raise HTTPException(404)
        v = rt.sh.plan_view(r, rt.sh.quote(time.time()))
        v.update(result=r.get("result"), actions=rt.sh.store.actions(pid), events=rt.sh.store.events(pid))
        return v

    @app.post("/api/v1/sh/plans/{pid}/close")
    def sh_plan_close(pid: str):
        """Explicit, user-confirmed close of one SH plan (primary + hedge) through its state machine; Execution Lock applies."""
        r = rt.sh.close_plan(pid, "MANUAL_CLOSE")
        rt.log.warn("SH", "MANUAL_CLOSE", f"Zamknięcie planu {pid} na żądanie: {r}")
        return r

    @app.get("/api/v1/sh/validation")
    def sh_validation(instrument: str = Query("XAUUSD")):
        """Validation reports of the SH strategies on REAL exported data (written by `sh train`); absent = not run yet."""
        if instrument not in ("XAUUSD", "BTC"):
            raise HTTPException(400, "UNKNOWN_INSTRUMENT")
        out = {}
        for strat in ("SCALPING", "HEDGING"):
            p = paths.data_dir() / "sh" / "validation" / f"{instrument}_{strat}.json"
            try:
                out[strat] = {"status": "VERIFIED_REPLAY", "report": json.loads(p.read_text(encoding="utf-8"))} if p.exists() else \
                    {"status": "NOT_RUN", "reason": "brak raportu walidacji na danych z terminala – uruchom zadanie sh_models (30_SH_WALIDACJA.bat)"}
            except (OSError, ValueError) as exc:
                out[strat] = {"status": "ERROR", "reason": str(exc)[:200]}
        return {"instrument": instrument, "strategies": out}

    @app.get("/api/v1/sh/config")
    def sh_config_get():
        from ..sh import config as SHC
        return SHC.load()

    @app.post("/api/v1/sh/config")
    def sh_config_set(body: dict = Body(...)):
        """Panel change of the single SH config source (validated, versioned). Open plans keep their frozen parameters."""
        from ..sh import config as SHC
        try:
            cfg = SHC.save_override(body, who="panel")
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        rt.log.info("SH", "CONFIG", f"Zmiana konfiguracji SH – wersja {cfg['_override_version']}, hash {cfg['_hash']}")
        return cfg

    @app.post("/api/v1/sh/config/rollback")
    def sh_config_rollback():
        from ..sh import config as SHC
        try:
            return SHC.rollback_override()
        except ValueError as exc:
            raise HTTPException(409, str(exc))

    @app.get("/api/v1/sh/chart")
    def sh_chart(tf: str = Query("M1"), limit: int = Query(240, ge=20, le=1000)):
        if tf not in ("M1", "M5", "M15"):
            raise HTTPException(400, "INVALID_TIMEFRAME")
        bars = [b for b in rt.bridge.bars(tf, limit, include_forming=True) if b.get("open_utc")]
        return {"tf": tf, "bars": bars, "quote": rt.sh.quote(time.time()), "last_eval": rt.sh.last_eval,
                "open_plans": [rt.sh.plan_view(p, rt.sh.quote(time.time())) for p in rt.sh.store.open_plans()]}

    @app.get("/api/v1/scalp/shadow")
    def scalp_shadow(limit: int = Query(100, ge=1, le=1000)):
        return {"items": rt.scalp.recent(limit), "summary": rt.scalp.summary()}

    @app.get("/api/v1/forecast/shadow")
    def forecast_shadow(limit: int = Query(100, ge=1, le=1000)):
        return {"items": rt.forecast.recent(limit)}

    @app.post("/api/v1/forecast/reload")
    def forecast_reload():
        rt.forecast.reload()
        rt.log.info("FORECAST", "RELOAD", "Przeładowanie modelu prognoz – nowa wersja od następnej zamkniętej świecy M5.")
        return {"ok": True}

    @app.get("/api/v1/walls")
    def walls_get():
        snap = {k: v for k, v in (rt.walls.last or {}).items() if not k.startswith("_")}
        return {"status": rt.walls.status(), "snapshot": snap,
                "note": "HV_PROXY = zmienność historyczna brokera jako przybliżenie – nie zmienność implikowana. Walls to pasma konwencji log-zwrotu, nie prognoza."}

    @app.post("/api/v1/walls/iv-import")
    def walls_iv_import(body: dict = Body(...)):
        from ..analysis import iv_import
        text = str(body.get("text") or "")
        if not text or len(text) > 1_000_000:
            raise HTTPException(400, "IV_IMPORT_EMPTY_OR_TOO_LARGE")
        try:
            rows = iv_import.parse_text(text, body.get("format"))
        except Exception as exc:
            raise HTTPException(400, f"IV_IMPORT_PARSE_ERROR: {type(exc).__name__}") from exc
        rep = iv_import.store(rt.db, rows, imported_by="MONITOR")
        rt.log.info("WALLS", "IV_IMPORT", f"Import IV: przyjęto {rep['accepted']}, odrzucono {len(rep['rejected'])}, już zapisane {rep['already_stored']} "
                    "(użycie od available_at; dotyczy przyszłych snapshotów).")
        rt.engine.mark_dirty()
        return rep

    @app.get("/api/v1/structure")
    def structure(tf: str = Query("M5")):
        if tf not in TIMEFRAMES:
            raise HTTPException(400, "INVALID_TIMEFRAME")
        return rt.engine.structure(tf)

    # ------------------------------------------------------------ markets (scanner) and AI signals
    import re as _re

    def _sym(symbol: str) -> str:
        if not _re.fullmatch(SYMBOL_RX, symbol or ""):
            raise HTTPException(400, "INVALID_SYMBOL")
        return symbol

    # ------------------------------------------------------------ 1.14 assets (XAUUSD / BTC) and Execution Lock
    @app.get("/api/v1/assets")
    def assets_state(refresh: bool = False):
        if refresh:
            rt.assets.refresh()
        return rt.assets.state()

    @app.get("/api/v1/assets/{asset}/candidates")
    def assets_candidates(asset: str):
        try:
            return {"asset": asset, "candidates": rt.assets.candidates(asset),
                    "note": "Kandydaci wg metadanych terminala (currency_base/profit). Nic nie jest wybierane automatycznie."}
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(409, f"{type(exc).__name__}: {exc}") from exc

    @app.post("/api/v1/assets/confirm")
    def assets_confirm(req: AssetConfirmReq):
        if not _re.fullmatch(SYMBOL_RX, req.broker_symbol or ""):
            raise HTTPException(400, "INVALID_SYMBOL")
        try:
            st = rt.assets.confirm(req.asset, req.broker_symbol)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        rt.db.execute("INSERT INTO settings_audit(ts, change_json) VALUES (?,?)", (iso(utcnow()), json.dumps({"asset_confirm": req.model_dump()})))
        return st

    @app.post("/api/v1/assets/active")
    def assets_active(req: AssetActiveReq):
        old = rt.cfg.get().mt5.symbol
        try:
            st = rt.assets.switch(req.asset)
        except PermissionError as exc:
            raise HTTPException(409, str(exc)) from exc
        rt.db.execute("INSERT INTO settings_audit(ts, change_json) VALUES (?,?)", (iso(utcnow()), json.dumps({"active_asset": req.asset})))
        if rt.cfg.get().mt5.symbol != old:
            rt.modes.reset("ACTIVE_ASSET_CHANGED")
            rt.bridge.state = "RECONNECTING"
            rt.bridge.next_retry = 0
        rt.engine.mark_dirty()
        rt.bus.publish("assets", st)
        return st

    UNLOCK_PHRASE = "ODBLOKUJ WYKONANIE ZLECEN"

    @app.get("/api/v1/execution/lock")
    def exec_lock():
        c = rt.cfg.get().execution
        return {"lock": c.lock, "changed_at": c.lock_changed_at, "blocked_attempts": rt.worker.locked_attempts,
                "unlock_phrase_required": UNLOCK_PHRASE,
                "note": "LOCKED: żadna ścieżka (AUTO, zarządzanie pozycją, Trade Pad, API) nie wysyła order_send do terminala."}

    @app.post("/api/v1/execution/lock")
    def exec_lock_set(req: LockReq):
        if req.lock not in ("LOCKED", "UNLOCKED_BY_USER"):
            raise HTTPException(400, "INVALID_LOCK")
        if req.lock == "UNLOCKED_BY_USER" and (req.phrase or "").strip().upper() != UNLOCK_PHRASE:
            raise HTTPException(403, "UNLOCK_PHRASE_REQUIRED")
        rt.cfg.update({"execution": {"lock": req.lock, "lock_changed_at": iso(utcnow())}})
        rt.db.execute("INSERT INTO settings_audit(ts, change_json) VALUES (?,?)", (iso(utcnow()), json.dumps({"execution_lock": req.lock})))
        rt.log.warn("EXECUTION", "LOCK_" + req.lock, "Execution Lock: " + ("ZABLOKOWANE" if req.lock == "LOCKED" else "odblokowane przez użytkownika"))
        rt.engine.mark_dirty()
        rt.bus.publish("execution_lock", {"lock": req.lock})
        return exec_lock()

    @app.get("/api/v1/markets")
    def markets():
        return rt.scanner.summary()

    @app.post("/api/v1/markets/scan")
    def markets_scan():
        if rt.bridge.state != "CONNECTED":
            raise HTTPException(503, "MT5_NOT_CONNECTED")
        rt.scanner.scan_now()
        return {"queued": True}

    @app.get("/api/v1/markets/symbols")
    def markets_symbols(all: bool = False):
        try:
            return {"symbols": rt.bridge.list_symbols(visible_only=not all)}
        except Exception as exc:
            raise HTTPException(503, f"SYMBOLS_UNAVAILABLE: {exc}") from exc

    @app.get("/api/v1/markets/detail")
    def markets_detail(symbol: str = Query(...), fresh: bool = False):
        _sym(symbol)
        r = None if fresh else rt.scanner.get(symbol)
        if r is None:
            try:
                r = rt.scanner.analyze_symbol(symbol)
            except Exception as exc:
                raise HTTPException(404, f"SYMBOL_UNAVAILABLE: {exc}") from exc
        return r

    @app.get("/api/v1/markets/chart")
    def markets_chart(symbol: str = Query(...), tf: str = Query("H1"), bars: int = Query(300, ge=50, le=1500)):
        _sym(symbol)
        if tf not in TIMEFRAMES:
            raise HTTPException(400, "INVALID_TIMEFRAME")
        try:
            meta = rt.bridge.symbol_meta(symbol, select=rt.cfg.get().markets.source != "MARKET_WATCH")
            if meta is None:
                raise ValueError("SYMBOL_NOT_FOUND")
            data = rt.bridge.symbol_bars(symbol, tf, bars)
            from ..engine import volzones
            vol = volzones.compute(rt.bridge.symbol_bars(symbol, "D1", 420), rt.cfg.get().volatility, digits=int(meta.get("digits") or 5),
                                   quote=rt.bridge.symbol_quote(symbol, meta.get("point")))
        except Exception as exc:
            raise HTTPException(404, f"SYMBOL_UNAVAILABLE: {exc}") from exc
        sig = rt.signals.list(symbol=symbol, limit=10)["items"]
        return {"symbol": symbol, "tf": tf, "meta": meta, "bars": data, "volatility": vol,
                "bot_signals": [x for x in sig if x["status"] == "OPEN"][:3], "synthetic": rt.bridge.synthetic}

    @app.get("/api/v1/signal-history")
    def signal_history(strategy: str | None = None, status: str | None = None, tf: str | None = None, limit: int = Query(100, ge=1, le=1000)):
        where, args = ["synthetic=?"], [int(bool(rt.bridge.synthetic))]
        for col, val in (("strategy_id", strategy), ("status", status), ("entry_tf", tf)):
            if val:
                where.append(f"{col}=?")
                args.append(val)
        rows = rt.db.query(f"SELECT record_json FROM signal_history WHERE {' AND '.join(where)} ORDER BY updated_at DESC LIMIT ?", (*args, limit))
        return {"items": [json.loads(r["record_json"]) for r in rows]}

    @app.get("/api/v1/context-tf")
    def context_tf_view():
        d = rt.engine.current_decision() or {}
        return {"context": d.get("context_tf"), "signal": d.get("signal")}

    @app.get("/api/v1/bot-signals")
    def bot_signals(symbol: str | None = None, limit: int = Query(50, ge=1, le=500), rejected: bool = True):
        if symbol:
            _sym(symbol)
        return {**rt.signals.list(symbol=symbol, limit=limit, include_rejected=rejected), **rt.signals.status()}

    @app.get("/api/v1/bot-signals/{signal_id}")
    def bot_signal_get(signal_id: str):
        r = rt.signals.get(signal_id)
        if not r:
            raise HTTPException(404, "NOT_FOUND")
        return r

    @app.get("/api/v1/signals")
    def signals(limit: int = 30):
        from ..engine.lifecycle import public_setup
        legacy = [public_setup(r) for r in rt.engine.lifecycle.recent(min(limit, 100))]
        active = [{"setup_id": r["setup_id"], "created_at": r["first_seen_at"], "strategy_id": r["record"]["strategy_id"],
                   "profile": f"ACTIVE {r['record']['timeframe']}", "direction": r["record"]["direction"],
                   "state": r["stage"] if r["status"] == "ACTIVE" else r["status"], "invalidation_level": r["record"].get("invalidation_level"),
                   "terminal_reason": r.get("terminal_reason"), "synthetic": bool(r["record"].get("synthetic"))}
                  for r in rt.engine.active.tracker.recent(min(limit, 100))]
        setups = sorted(active + legacy, key=lambda x: x["created_at"] or "", reverse=True)[:limit]
        decs = rt.db.query("SELECT decision_id, created_at, setup_id, analysis_direction, signal_stage, decision, execution_permission FROM decisions "
                           "WHERE decision IN ('BUY','SELL') OR signal_stage IN ('CONFIRMED','INVALIDATED','EXPIRED') ORDER BY created_at DESC LIMIT 50")
        trades = rt.db.query("SELECT * FROM trades ORDER BY closed_at DESC LIMIT 50")
        return {"setups": setups, "decisions": decs, "attempts": rt.gateway.recent_attempts(30), "trades": trades}

    @app.get("/api/v1/decision")
    def decision():
        return rt.engine.current_decision()

    @app.get("/api/v1/stats")
    def get_stats(mode: str = "PAPER"):
        if mode not in ("PAPER", "AUTO_DEMO", "AUTO_LIVE"):
            raise HTTPException(400, "INVALID_MODE")
        b = rt.bridge
        with b._lock:
            deals = list(b.deals)
        ds = b.server_day_start_utc()
        ds_raw = ds.timestamp() + b.clock.offset if ds and b.clock.offset is not None else None
        return {"bot": stats.bot_stats(rt.db, mode, b.account_key), "engines": stats.engine_stats(rt.db, mode, b.account_key),
                "equity": stats.equity_curve(rt.db, "PAPER" if mode == "PAPER" else "ACCOUNT", b.account_key),
                "account": stats.account_stats(deals, rt.cfg.get().mt5.symbol, ds_raw) if b.account_key else None,
                "account_roi": stats.account_roi(rt.db, b.account_key, deals, b.clock.offset)}

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
                                         for n in ("ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN", "FRED_API_KEY", "MT5_PASSWORD")},
                "editable_note": "Klucze API są przechowywane lokalnie (Windows DPAPI) i nigdy nie są zwracane przez API."}

    @app.put("/api/v1/config")
    def put_config(patch: dict = Body(...)):
        patch.pop("server", None)
        # 1.14: asset mapping / active asset / Execution Lock change only through their dedicated, checked endpoints
        patch.pop("assets", None)
        m5 = patch.get("mt5") or {}
        m5.pop("analytical_alias", None)
        if m5.get("symbol"):                       # symbol typed in Ustawienia -> becomes the active asset's broker symbol
            patch.setdefault("assets", {})["mappings"] = {rt.cfg.get().assets.active: {"broker_symbol": m5["symbol"], "status": "USER_SPECIFIED"}}
        if isinstance(patch.get("execution"), dict) and ({"lock", "lock_changed_at"} & set(patch["execution"])):
            raise HTTPException(400, "USE_EXECUTION_LOCK_ENDPOINT")
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
        if old.risk != new.risk:
            rt.log.info("CONFIG", "RISK_LIMITS_CHANGED", "Zmieniono limity ryzyka – obowiązują od następnej decyzji.")
        rt.engine.mark_dirty()
        return get_config()

    @app.post("/api/v1/secrets/anthropic")
    def set_key(req: KeyReq):
        rt.secrets.set("ANTHROPIC_API_KEY", req.api_key)
        rt.log.info("AGENT", "KEY_SET", "Zapisano lokalnie klucz Anthropic (wartość nie jest logowana).")
        return {"ok": True, "masked": rt.secrets.mask("ANTHROPIC_API_KEY")}

    @app.post("/api/v1/secrets")
    def set_secret(req: SecretReq):
        if req.name not in ("TELEGRAM_BOT_TOKEN", "FRED_API_KEY", "ANTHROPIC_API_KEY", "MT5_PASSWORD"):
            raise HTTPException(400, "UNKNOWN_SECRET")
        rt.secrets.set(req.name, req.value)
        if req.name == "MT5_PASSWORD":                 # new password: try to connect again (value never logged)
            rt.log.info("MT5", "PASSWORD_SET", "Zapisano lokalnie hasło MT5 (wartość nie jest logowana).")
            if rt.bridge.state != "CONNECTED":
                rt.bridge.next_retry = 0
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

    @app.post("/api/v1/mode/primary-path")
    def set_primary_path(req: PrimaryPathReq):
        try:
            return rt.modes.set_primary_path(req.instrument, req.path)
        except ModeError as exc:
            raise HTTPException(400, str(exc)) from exc
        finally:
            rt.engine.mark_dirty()

    # ------------------------------------------------------------ AUTO strategy selection (separate from order execution)
    def media_dir():
        d = paths.data_dir() / "assets" / "masterquo"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @app.get("/api/v1/strategy/auto")
    def strategy_auto():
        return rt.engine.active.status()

    @app.post("/api/v1/strategy/mode")
    def strategy_mode(req: StrategyModeReq):
        if req.strategy_mode == "MANUAL" and not req.manual_strategy_id:
            raise HTTPException(400, "MANUAL_REQUIRES_STRATEGY_ID")
        try:
            rt.cfg.update({"active": {"strategy_mode": req.strategy_mode,
                                      "manual_strategy_id": req.manual_strategy_id if req.strategy_mode == "MANUAL" else None}})
        except Exception as exc:
            raise HTTPException(400, f"INVALID: {exc}") from exc
        # legacy switch -> the same per-account setup view the engine uses (one source)
        rt.prefs.set("setup_view", {"mode": "SELECTED" if req.strategy_mode == "MANUAL" else "AUTO", "strategy_id": req.manual_strategy_id})
        rt.engine.active.selector.reset("STRATEGY_MODE_CHANGED")
        rt.log.info("AUTO", "STRATEGY_MODE", f"Wybór strategii: {req.strategy_mode}" + (f" ({req.manual_strategy_id})" if req.strategy_mode == "MANUAL" else "")
                    + ". Tryb wykonywania zleceń bez zmian.")
        rt.engine.mark_dirty()
        return rt.engine.active.status(compact=True)

    # ------------------------------------------------------------ setup view + leverage (per account) and scenario details
    @app.get("/api/v1/prefs")
    def prefs_get():
        from ..prefs import LEVERAGE_CHOICES
        return {**rt.prefs.all(), "exposure": rt.prefs.exposure_limit(), "leverage_choices": list(LEVERAGE_CHOICES)}

    @app.post("/api/v1/prefs/setup-view")
    def prefs_setup_view(req: SetupViewReq):
        from ..prefs import PrefsError
        try:
            v = rt.prefs.set("setup_view", req.model_dump())
        except PrefsError as exc:
            raise HTTPException(400, str(exc)) from exc
        if v["mode"] != "ALL":
            rt.engine.active.selector.reset("SETUP_VIEW_CHANGED")
        rt.log.info("AUTO", "SETUP_VIEW", f"Wybór setupu: {v['mode']}" + (f" {v['strategy_id']}" if v["mode"] == "SELECTED" else "")
                    + " (nie wymusza sygnału ani zlecenia; wszystkie filtry obowiązują).")
        return prefs_get()

    @app.post("/api/v1/prefs/leverage")
    def prefs_leverage(req: LeverageReq):
        from ..prefs import PrefsError
        try:
            v = rt.prefs.set("leverage", req.model_dump())
        except PrefsError as exc:
            raise HTTPException(400, str(exc)) from exc
        rt.log.info("RISK", "LEVERAGE_LIMIT", ("Limit ekspozycji: AUTO (dźwignia rachunku z MT5)" if v["mode"] == "AUTO" else f"Limit ekspozycji ustawiony w bocie: 1:{v['limit']}")
                    + " – nie zmienia dźwigni u brokera; dotyczy przyszłych decyzji, istniejące pozycje bez zmian.")
        return prefs_get()

    @app.get("/api/v1/setups")
    def setups_list(include_terminal: bool = True):
        from ..engine import setup_details
        return setup_details.scenarios(rt.engine, include_terminal=include_terminal)

    @app.get("/api/v1/setups/{setup_id}/details")
    def setup_detail(setup_id: str):
        from ..engine import setup_details
        if len(setup_id) > 120:
            raise HTTPException(400, "SETUP_ID_INVALID")
        out = setup_details.details(rt.engine, setup_id)
        if out is None:
            raise HTTPException(404, "SETUP_NOT_FOUND")
        return out

    # ------------------------------------------------------------ ML (Decision Tree + XGBoost)
    @app.get("/api/v1/ml/status")
    def ml_status():
        return rt.ml.status()

    @app.post("/api/v1/ml/mode")
    def ml_mode(req: MLModeReq):
        try:
            return rt.ml.set_mode(req.mode)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/v1/ml/collect")
    def ml_collect(req: MLFlagReq):
        return rt.ml.set_collect(req.on)

    @app.post("/api/v1/ml/pause")
    def ml_pause(req: MLFlagReq):
        return rt.ml.set_paused(req.on)

    @app.post("/api/v1/ml/train")
    def ml_train(req: MLTrainReq | None = None):
        """'Trenuj teraz': skips the waiting time/new-label threshold but never the data minimums of the validation blocks."""
        if rt.cfg.get().ml.training_paused:
            raise HTTPException(409, "TRAINING_PAUSED")
        res = rt.ml.start_training("USER", force=True, include_approx=req.include_approx if req else None)
        rt.bus.publish("ml", rt.ml.status(compact=True))
        return res

    # ------------------------------------------------------------ training installer (same backend as the BAT launchers)
    @app.get("/api/v1/training")
    def training_state():
        from ..training import core as tc
        from ..training import panel as tp
        rid = tc.Run.latest()
        st = tp.run_detail(rid) if rid else None
        from ..training.runner import TASKS
        return {"run": st, "profiles": {k: v["label"] for k, v in tc.profiles().items()}, "tasks": [{"kind": k, "title": t} for k, t in TASKS],
                "lock": tp.lock_holder()}

    # ---------------------------------------------------------------- PMW-SH-1 training panel (registry, readiness, history, export)
    @app.get("/api/v1/training/models")
    def training_models(instrument: str = Query(...)):
        from ..training import panel as tp
        if instrument not in ("XAUUSD", "BTC"):
            raise HTTPException(400, "UNKNOWN_INSTRUMENT")
        return tp.models(rt, instrument)

    # ---------------------------------------------------------------- PMW-MM master models (inventory, SHADOW live view, ledger, rollback)
    def _mm_inst(instrument: str) -> str:
        if instrument not in ("XAUUSD", "BTC"):
            raise HTTPException(400, "UNKNOWN_INSTRUMENT")
        return instrument

    @app.get("/api/v1/mm/status")
    def mm_status(instrument: str = Query("XAUUSD")):
        return rt.mm.status(_mm_inst(instrument))

    @app.get("/api/v1/eval/status")
    def eval_status():
        return rt.evaluation.status()

    @app.get("/api/v1/eval/assessments")
    def eval_assessments(engine: str | None = Query(None), limit: int = Query(50, ge=1, le=500)):
        from ..evaluation.contract import ENGINES
        if engine is not None and engine not in ENGINES:
            raise HTTPException(400, "UNKNOWN_ENGINE")
        return {"items": rt.evaluation.assessments(engine, limit), "mode": "SHADOW"}

    @app.get("/api/v1/eval/report")
    def eval_report():
        return rt.evaluation.report()

    @app.get("/api/v1/eval/exposure")
    def eval_exposure():
        return rt.evaluation.exposure()

    @app.get("/api/v1/mm/live")
    def mm_live(instrument: str = Query("XAUUSD")):
        return rt.mm.live(_mm_inst(instrument))

    @app.get("/api/v1/mm/job")
    def mm_job(instrument: str = Query("XAUUSD"), job: str = Query(...)):
        from ..mm import inventory as mi
        from ..mm.orchestrator import GRAPH
        if job not in {g[0] for g in GRAPH}:
            raise HTTPException(400, "UNKNOWN_JOB")
        rep = mi.latest_report(_mm_inst(instrument))
        if not rep or not rep.get("run_dir"):
            return {"status": "NOT_RUN", "reason": "brak przebiegu master models dla instrumentu (trening: zadanie master_models)"}
        p = Path(rep["run_dir"]) / f"{job}.json"
        if not p.exists():
            return {"status": "NOT_RUN", "reason": f"zadanie {job} nie zostało wykonane w ostatnim przebiegu"}
        return {"status": "OK", "run_id": rep.get("run_id"), "data_kind": (rep.get("snapshot") or {}).get("data_kind"),
                "result": json.loads(p.read_text(encoding="utf-8"))}

    @app.get("/api/v1/mm/ledger")
    def mm_ledger(instrument: str = Query("XAUUSD"), model: str = Query("gpr_logret:LIVE"), limit: int = 200):
        led = rt.mm._ledger(_mm_inst(instrument))
        rows = led.rows(model, limit=min(max(limit, 1), 2000))
        return {"summary": led.summary(), "rows": rows[-min(max(limit, 1), 2000):]}

    @app.post("/api/v1/mm/rollback")
    def mm_rollback(body: dict = Body(...)):
        from ..mm import artifacts as ma
        try:
            return {"ok": True, "pointer": ma.rollback(_mm_inst(body.get("instrument", "")), str(body.get("model", "")))}
        except ma.ArtifactError as exc:
            return {"ok": False, "reason": str(exc)}

    @app.get("/api/v1/training/readiness")
    def training_readiness(instrument: str = Query(...)):
        from ..training import panel as tp
        if instrument not in ("XAUUSD", "BTC"):
            raise HTTPException(400, "UNKNOWN_INSTRUMENT")
        return tp.readiness(rt, instrument)

    @app.get("/api/v1/training/runs")
    def training_runs(limit: int = Query(50, ge=1, le=500)):
        from ..training import panel as tp
        return {"items": tp.runs(limit)}

    def _rid_ok(rid: str) -> str:
        from ..training import core as tc
        if not re.fullmatch(r"[A-Za-z0-9_\-]{6,80}", rid) or not (tc.runs_dir() / rid / "state.json").exists():
            raise HTTPException(404)
        return rid

    @app.get("/api/v1/training/runs/{rid}")
    def training_run(rid: str):
        from ..training import panel as tp
        return tp.run_detail(_rid_ok(rid))

    @app.get("/api/v1/training/runs/{rid}/log")
    def training_run_log(rid: str, task: str = Query(...), nbytes: int = Query(20000, ge=1000, le=500000)):
        from ..training import panel as tp
        try:
            return tp.task_log(_rid_ok(rid), task, nbytes)
        except StopIteration:
            raise HTTPException(404, "UNKNOWN_TASK")

    @app.get("/api/v1/training/runs/{rid}/report")
    def training_run_report(rid: str):
        from ..training import core as tc
        p = tc.runs_dir() / _rid_ok(rid) / "report.html"
        if not p.exists():
            raise HTTPException(404, "REPORT_NOT_READY")
        return FileResponse(p, media_type="text/html")

    @app.get("/api/v1/training/compare")
    def training_compare(a: str = Query(...), b: str = Query(...)):
        from ..training import panel as tp
        return tp.compare(_rid_ok(a), _rid_ok(b))

    @app.post("/api/v1/training/resume")
    def training_resume(body: dict = Body(default={})):
        import subprocess
        from ..training import core as tc
        from ..training import panel as tp
        h = tp.lock_holder()
        if h and h.get("alive"):
            return {"started": False, "reason": f"TRAINING_ALREADY_RUNNING:{h.get('run_id')}"}
        rid = body.get("run_id") or tc.Run.latest()
        if not rid:
            return {"started": False, "reason": "NO_RUN"}
        _rid_ok(rid)
        log = open(tc.training_dir() / "panel_start.log", "a", encoding="utf-8")
        kw = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if os.name == "nt" else {"start_new_session": True}
        subprocess.Popen([sys.executable, "-m", "masterquo", "training", "resume", rid], cwd=str(paths.ROOT_DIR / "backend"),
                         env=dict(os.environ, MQ_NO_BROWSER="1"), stdout=log, stderr=subprocess.STDOUT, **kw)
        return {"started": True, "run_id": rid}

    @app.post("/api/v1/training/export")
    def training_export(body: dict = Body(...)):
        from ..training import panel as tp
        inst = body.get("instrument")
        if inst not in ("XAUUSD", "BTC"):
            raise HTTPException(400, "UNKNOWN_INSTRUMENT")
        try:
            r = tp.export_package(inst, str(body.get("scope") or "all"), body.get("run_id"))
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        r["download"] = f"/api/v1/training/exports/{r['file']}"
        rt.log.info("TRAINING", "EXPORT", f"Pakiet treningowy {r['file']} ({r['files']} plików, braki: {len(r['missing'])})")
        return r

    @app.get("/api/v1/training/exports/{name}")
    def training_export_file(name: str):
        from ..training import panel as tp
        if not re.fullmatch(r"PMW_TRENING_[A-Za-z0-9_\-]+\.zip", name):
            raise HTTPException(404)
        p = tp.exports_dir() / name
        if not p.exists():
            raise HTTPException(404)
        return FileResponse(p, media_type="application/zip", filename=name)

    @app.post("/api/v1/training/import")
    async def training_import(request: Request):
        from ..training import panel as tp
        data = await request.body()
        if not data or len(data) > 512 * 2**20:
            raise HTTPException(400, "EMPTY_OR_TOO_LARGE")
        try:
            return tp.import_package(data)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.post("/api/v1/training/sh/promote")
    def training_sh_promote(body: dict = Body(...)):
        from ..sh import tpmodel as TM
        inst, strat, rid = body.get("instrument"), body.get("strategy"), body.get("run_id")
        if inst not in ("XAUUSD", "BTC") or strat not in ("SCALPING", "HEDGING") or not rid:
            raise HTTPException(400, "BAD_REQUEST")
        try:
            r = TM.promote(inst, strat, str(rid))
        except ValueError as exc:
            return {"ok": False, "reason": str(exc)}
        rt.log.warn("TRAINING", "SH_PROMOTE", f"sh_tp_model {inst}/{strat}: aktywny {r['active']}")
        return {"ok": True, **r}

    @app.post("/api/v1/training/start")
    def training_start(body: dict):
        """Starts `masterquo training run` as a separate process (never inside the bot process; no orders, lock untouched)."""
        import subprocess
        from ..training import core as tc
        insts = ",".join(i for i in ("XAUUSD", "BTC") if i in (body.get("instruments") or []))
        if not insts:
            raise HTTPException(400, "NO_INSTRUMENT")
        prof = body.get("profile") or "PELNY_TRENING"
        if prof not in tc.profiles():
            raise HTTPException(400, "BAD_PROFILE")
        cmd = [sys.executable, "-m", "masterquo", "training", "run", "--instruments", insts, "--profile", prof, "--origin", "panel"]
        if body.get("tasks"):                                  # one model / a subset (export, QC, activation and bot always run)
            from ..training.runner import TASKS
            sel = [t for t in body["tasks"] if t in {k for k, _ in TASKS}]
            if not sel:
                raise HTTPException(400, "BAD_TASKS")
            cmd += ["--tasks", ",".join(sel)]
        for k, flag in (("months", "--months"), ("symbol_xauusd", "--symbol-xauusd"), ("symbol_btc", "--symbol-btc"),
                        ("commission_xauusd", "--commission-xauusd"), ("commission_btc", "--commission-btc")):
            if body.get(k) not in (None, ""):
                cmd += [flag, str(body[k])]
        if rt.demo:
            cmd.append("--demo")
        held = None
        try:
            import json as _j
            cur = _j.loads(tc.lock_path().read_text(encoding="utf-8"))
            held = cur.get("run_id") if tc._pid_alive(int(cur.get("pid", 0))) else None
        except (OSError, ValueError):
            pass
        if held:
            return {"started": False, "reason": f"TRAINING_ALREADY_RUNNING:{held}"}
        log = open(tc.training_dir() / "panel_start.log", "a", encoding="utf-8")
        kw = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if os.name == "nt" else {"start_new_session": True}
        subprocess.Popen(cmd, cwd=str(paths.ROOT_DIR / "backend"), env=dict(os.environ, MQ_NO_BROWSER="1"), stdout=log, stderr=subprocess.STDOUT, **kw)
        return {"started": True}

    @app.post("/api/v1/training/cancel")
    def training_cancel():
        from ..training import core as tc
        rid = tc.Run.latest()
        if not rid:
            return {"ok": False, "reason": "NO_RUN"}
        (tc.runs_dir() / rid / "CANCEL").write_text(tc.now(), encoding="utf-8")
        return {"ok": True, "run_id": rid}

    @app.get("/api/v1/training/active")
    def training_active(instrument: str = Query(...)):
        import json as _j
        import mq_instruments as mi
        from ..lab.protocol import read_pointer
        from ..ml.router import ml_store
        if instrument not in mi.profiles():
            raise HTTPException(400, "UNKNOWN_INSTRUMENT")
        out = {}
        for fam in ("forecast", "scalp"):
            try:
                reg = _j.loads((mi.root(fam, instrument) / "registry.json").read_text(encoding="utf-8"))
                e = (reg.get("runs") or {}).get(reg.get("active") or "", {})
                out[fam] = {"active": reg.get("active"), "status": e.get("overall_status") or e.get("task_a_status"), "history": (reg.get("history") or [])[-3:]}
            except (OSError, ValueError):
                out[fam] = {"active": None}
        if instrument == rt.ml.inst:
            out["ml"] = {"active": rt.ml.registry.champion_id}
        else:
            db, root = ml_store(instrument, rt.db)
            row = db.one("SELECT model_id FROM ml_models WHERE status='CHAMPION'")
            out["ml"] = {"active": row["model_id"] if row else None}
        ptr = read_pointer(paths.data_dir() / "lab", instrument)
        out["lab"] = {"pinned": ptr["active"], "models": [{k: m.get(k) for k in ("model_id", "family", "role", "verdict")} for m in rt.lab.trainer.models(instrument)][:20]}
        return {"instrument": instrument, "families": out}

    @app.post("/api/v1/training/rollback")
    def training_rollback(body: dict):
        import subprocess
        inst, fam = body.get("instrument"), str(body.get("family") or "")
        if inst not in ("XAUUSD", "BTC") or not (fam in ("forecast", "scalp", "ml") or fam.startswith(("lab:", "sh:"))):
            raise HTTPException(400, "BAD_REQUEST")
        if fam.startswith("sh:"):
            from ..sh import tpmodel as TM
            if fam[3:] not in ("SCALPING", "HEDGING"):
                raise HTTPException(400, "BAD_REQUEST")
            try:
                return {"ok": True, "result": TM.rollback(inst, fam[3:])}
            except ValueError as exc:
                return {"ok": False, "reason": str(exc)}
        if fam == "ml" and inst == rt.ml.inst:
            try:
                return {"ok": True, "result": rt.ml.rollback()}
            except ValueError as exc:
                return {"ok": False, "reason": str(exc)}
        r = subprocess.run([sys.executable, "-m", "masterquo", "training", "rollback", "--instrument", inst, "--family", fam],
                           cwd=str(paths.ROOT_DIR / "backend"), capture_output=True, text=True, timeout=300)
        rt.forecast.reload()
        return {"ok": r.returncode == 0, "output": (r.stdout + r.stderr)[-800:]}

    # ------------------------------------------------------------ PMW-UPD-06 Session Sweep Boxes + Liquidation Heatmap
    @app.get("/api/v1/liquidity/sessions")
    def liq_sessions(tf: str = Query("M5"), profile: str | None = Query(None), days: int = Query(2, ge=0, le=5)):
        from ..analytics import session_engine as se
        if profile is not None and profile not in se.PROFILES:
            raise HTTPException(400, "UNKNOWN_PROFILE")
        if tf not in ("M1", "M5", "M15", "M30", "H1"):
            raise HTTPException(400, "UNKNOWN_TF")
        cfg = rt.cfg.get()
        base = cfg.liquidity.sessions_base_tf                          # geometry from ONE base TF; the chart TF only changes presentation
        bars = [b for b in rt.bridge.bars(base, 3000 if base == "M1" else 1000, include_forming=False) if b.get("open_utc")]
        r = rt.liquidity.sessions(bars, 60 if base == "M1" else 300, cfg.assets.active, None, profile, days)
        return dict(r, asset=cfg.assets.active, view_tf=tf, base_tf=base, session_epoch=str(getattr(rt.bridge, "session_epoch", None)),
                    history_from=bars[0]["open_utc"] if bars else None)

    @app.get("/api/v1/liquidity/heatmap")
    def liq_heatmap(asset: str | None = Query(None), as_of: str | None = Query(None), max_cells: int = Query(20000, ge=0, le=100000)):
        return rt.liquidity.heatmap_public(_asset(asset), as_of, max_cells)

    @app.get("/api/v1/liquidity/context")
    def liq_context(setup_side: str | None = Query(None)):
        from ..analytics import liquidity_context as lc
        cfg = rt.cfg.get()
        a = cfg.assets.active
        base = cfg.liquidity.sessions_base_tf
        bars = [b for b in rt.bridge.bars(base, 3000 if base == "M1" else 1000, include_forming=False) if b.get("open_utc")]
        sess = rt.liquidity.sessions(bars, 60 if base == "M1" else 300, a)
        hm = rt.liquidity.heatmap_public(a, None, 0)
        hm.pop("grid", None)
        m5 = [b for b in rt.bridge.bars("M5", 60, include_forming=False) if b.get("open_utc")]
        a5 = (sum(x["h"] - x["l"] for x in m5[-14:]) / 14) if len(m5) >= 14 else None
        return dict(lc.evaluate(boxes=sess["boxes"], heatmap=hm, price=m5[-1]["c"] if m5 else None, atr_m5=a5,
                                setup={"side": setup_side} if setup_side in ("BUY", "SELL") else None), asset=a, rules=lc.RULES)

    @app.put("/api/v1/liquidity/source")
    def liq_source(body: dict = Body(default={})):
        a = _asset(body.get("asset"))
        cur = rt.cfg.get().liquidity.sources.get(a)
        patch = {k: body[k] for k in ("enabled", "variant", "source_symbol", "exchange", "range", "contract_type") if k in body}
        if "mapping" in body and body["mapping"] != "UNMAPPED":
            raise HTTPException(400, "MAPPING_REQUIRES_VALIDATED_BASIS_ADAPTER")
        try:
            merged = dict(cur.model_dump() if cur else {}, **patch)
            rt.cfg.update({"liquidity": {"sources": {a: merged}}})
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, str(exc)[:300]) from None
        return {"ok": True, "source": rt.cfg.get().liquidity.sources[a].model_dump()}

    @app.put("/api/v1/liquidity/key")
    def liq_key(body: dict = Body(default={})):
        rt.secrets.set("COINGLASS_API_KEY", (body.get("key") or "").strip() or None)
        return {"ok": True, "key_status": rt.secrets.source("COINGLASS_API_KEY")}          # the key itself is never returned

    @app.post("/api/v1/liquidity/poll")
    def liq_poll():
        import time as _t
        return {"polled": rt.liquidity.poll_once(_t.monotonic() + 10**9), "imported": rt.liquidity.scan_inbox()}

    # ------------------------------------------------------------ PMW-UPD-05 Multi TimeFrame Scalping Dashboard
    @app.get("/api/v1/scalp/dashboard")
    def mtf_dashboard(asset: str | None = Query(None), snapshot_id: str | None = Query(None)):
        a = _asset(asset) if asset else rt.cfg.get().assets.active
        if a != rt.scalp.inst:
            return {"asset": a, "status": "ASSET_NOT_ACTIVE", "snapshot": None, "health": None}
        import mq_instruments
        if a not in mq_instruments.profiles():
            return {"asset": a, "status": "UNSUPPORTED_STRATEGY_PROFILE", "snapshot": None, "health": rt.mtf.health}
        snap = rt.mtf.get(snapshot_id)
        if snapshot_id and snap is None:
            return {"asset": a, "status": "ARCHIVE_SNAPSHOT_UNAVAILABLE", "snapshot_id": snapshot_id, "snapshot": None, "health": rt.mtf.health}
        if snap is not None and snap.get("asset") != a:
            snap = None
        return {"asset": a, "status": "OK" if snap else "NO_SNAPSHOT", "snapshot": snap, "health": rt.mtf.health or rt.mtf.heartbeat(),
                "scalp_status": rt.scalp.state.get("status"), "scalp_reason": rt.scalp.state.get("reason")}

    @app.get("/api/v1/scalp/dashboard/chart")
    def mtf_chart(tf: str = Query(...), snapshot_id: str = Query(...), bars: int = Query(400, ge=50, le=600)):
        r = rt.mtf.chart(tf, snapshot_id, bars)
        if r.get("status") == "SNAPSHOT_EXPIRED":
            return JSONResponse(r, status_code=410)
        return r

    @app.get("/api/v1/scalp/dashboard/snapshots")
    def mtf_snapshots(setup_id: str | None = Query(None), cursor: str | None = Query(None), limit: int = Query(50, ge=1, le=200)):
        rows = rt.mtf.snapshots(setup_id, limit, cursor)
        return {"asset": rt.scalp.inst, "rows": rows, "next_cursor": rows[-1]["computed_at"] if len(rows) == limit else None}

    @app.get("/api/v1/scalp/dashboard/snapshots/{sid}")
    def mtf_snapshot(sid: str):
        snap = rt.mtf.get(sid)
        if snap is None:
            raise HTTPException(404, "ARCHIVE_SNAPSHOT_UNAVAILABLE")
        return snap

    # ------------------------------------------------------------ PMW-UPD-04 Neural Scalp System (CAUSAL_MTF_TCN_V1)
    nss_jobs: dict = {}

    def _nss_job(args: list[str]):
        import subprocess
        from ..training import core as tc
        if any(pr.poll() is None for pr in nss_jobs.values()):
            return {"started": False, "reason": "JOB_RUNNING – jedno ciężkie zadanie NSS naraz"}
        jid = "NSSJ-" + __import__("uuid").uuid4().hex[:8]
        log = open(tc.training_dir() / f"nss_{jid}.log", "a", encoding="utf-8")
        kw = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if os.name == "nt" else {"start_new_session": True}
        nss_jobs[jid] = subprocess.Popen([sys.executable, "-m", "masterquo", "neural-scalp", *args], cwd=str(paths.ROOT_DIR / "backend"), stdout=log,
                                         stderr=subprocess.STDOUT, **kw)
        return {"started": True, "job_id": jid, "args": args}

    @app.get("/api/v1/lab/neural")
    def nss_state(asset: str | None = Query(None)):
        return rt.nss.public(_asset(asset) if asset else rt.cfg.get().assets.active)

    @app.get("/api/v1/lab/neural/history")
    def nss_history(limit: int = Query(50, ge=1, le=500)):
        return {"asset": rt.nss.inst, "rows": rt.nss.history(limit)}

    @app.get("/api/v1/lab/neural/report")
    def nss_report(asset: str | None = Query(None), run_id: str | None = Query(None)):
        from ..lab import nss
        a = _asset(asset) if asset else rt.cfg.get().assets.active
        p = nss.root(a) / "registry.json"
        reg = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"runs": {}}
        rid = run_id or (sorted(reg["runs"])[-1] if reg["runs"] else None)
        if not rid or rid not in reg["runs"]:
            return {"asset": a, "status": "NO_REPORT"}
        rep = json.loads((Path(reg["runs"][rid]["run_dir"]) / "report.json").read_text(encoding="utf-8"))
        return {"asset": a, "run_id": rid, "report": rep}

    @app.get("/api/v1/lab/neural/jobs")
    def nss_jobs_list():
        return {"jobs": [{"job_id": k, "pid": v.pid, "running": v.poll() is None, "returncode": v.poll()} for k, v in nss_jobs.items()]}

    @app.post("/api/v1/lab/neural/prepare")
    def nss_prepare(body: dict = Body(default={})):
        return _nss_job(["prepare", "--asset", _asset(body.get("asset") or rt.cfg.get().assets.active)])

    @app.post("/api/v1/lab/neural/doctor")
    def nss_doctor(body: dict = Body(default={})):
        import subprocess
        a = _asset(body.get("asset") or rt.cfg.get().assets.active)
        r = subprocess.run([sys.executable, "-m", "masterquo", "neural-scalp", "doctor", "--asset", a], cwd=str(paths.ROOT_DIR / "backend"),
                           capture_output=True, text=True, timeout=120)
        try:
            return json.loads(r.stdout)
        except ValueError:
            return {"status": "ERROR", "output": (r.stdout + r.stderr)[-2000:]}

    @app.post("/api/v1/lab/neural/train")
    def nss_train(body: dict = Body(default={})):
        return _nss_job(["train", "--asset", _asset(body.get("asset") or rt.cfg.get().assets.active), "--activate", "none"])

    @app.post("/api/v1/lab/neural/cancel")
    def nss_cancel(body: dict = Body(default={})):
        pr = nss_jobs.get(str(body.get("job_id")))
        if pr is None:
            raise HTTPException(404, "UNKNOWN_JOB")
        if pr.poll() is None:
            pr.terminate()
        return {"ok": True, "job_id": body.get("job_id"), "note": "anulowanie nie podmienia wybranego modelu"}

    @app.post("/api/v1/lab/neural/select")
    def nss_select(body: dict = Body(default={})):
        from ..lab import nss
        try:
            return {"ok": True, "selected": nss.select(_asset(body.get("asset") or rt.cfg.get().assets.active), str(body.get("run_id")), str(body.get("role") or "OBSERVE"))}
        except (ValueError, OSError, KeyError) as exc:
            return {"ok": False, "reason": str(exc)}

    @app.post("/api/v1/lab/neural/rollback")
    def nss_rollback(body: dict = Body(default={})):
        from ..lab import nss
        try:
            return {"ok": True, "selected": nss.rollback(_asset(body.get("asset") or rt.cfg.get().assets.active))}
        except (ValueError, OSError) as exc:
            return {"ok": False, "reason": str(exc)}

    # ------------------------------------------------------------ PMW-UPD-03 SCALP_NET_PROFIT_MARKET_V1
    @app.get("/api/v1/ml/scalp")
    def ml_scalp_status(asset: str | None = Query(None)):
        inst = asset or rt.cfg.get().assets.active
        if inst != rt.ml.inst:
            from ..ml.router import ml_store
            from ..ml.service import MLService
            db, root = ml_store(inst, rt.db)
            return MLService(rt.cfg, db, rt.bridge, rt.bus, rt.log, root=root, instrument=inst).scalp_status(inst)
        return rt.ml.scalp_status(inst)

    def _ml_scalp_job(args: list[str]):
        import subprocess
        from ..training import core as tc
        log = open(tc.training_dir() / "ml_scalp_jobs.log", "a", encoding="utf-8")
        kw = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if os.name == "nt" else {"start_new_session": True}
        pr = subprocess.Popen([sys.executable, "-m", "masterquo", "ml-scalp", *args], cwd=str(paths.ROOT_DIR / "backend"), stdout=log,
                              stderr=subprocess.STDOUT, **kw)
        return {"started": True, "job_pid": pr.pid, "args": args}

    @app.post("/api/v1/ml/scalp/prepare")
    def ml_scalp_prepare(body: dict):
        inst = body.get("asset") or rt.cfg.get().assets.active
        if inst not in ("XAUUSD", "BTC"):
            raise HTTPException(400, "UNKNOWN_INSTRUMENT")
        return _ml_scalp_job(["prepare", "--asset", inst])

    @app.post("/api/v1/ml/scalp/train")
    def ml_scalp_train(body: dict):
        inst = body.get("asset") or rt.cfg.get().assets.active
        if inst not in ("XAUUSD", "BTC"):
            raise HTTPException(400, "UNKNOWN_INSTRUMENT")
        args = ["train", "--asset", inst, "--activate", "none"]
        if body.get("commission") is not None:
            args += ["--commission", str(float(body["commission"]))]
        return _ml_scalp_job(args)

    @app.get("/api/v1/ml/scalp/predictions")
    def ml_scalp_predictions(limit: int = Query(50, ge=1, le=500), before: str | None = Query(None)):
        q, prm = "SELECT * FROM ml_scalp_predictions WHERE instrument=?", [rt.ml.inst]
        if before:
            q += " AND computed_at < ?"
            prm.append(before)
        return {"predictions": rt.ml.db.query(q + " ORDER BY computed_at DESC LIMIT ?", (*prm, limit))}

    @app.get("/api/v1/ml/scalp/explain")
    def ml_scalp_explain(prediction_id: str = Query(...)):
        from ..ml import scalp_task as stk
        pr = rt.ml.db.one("SELECT * FROM ml_scalp_predictions WHERE prediction_id=?", (prediction_id,))
        if not pr:
            raise HTTPException(404, "UNKNOWN_PREDICTION")
        smp = rt.ml.db.one("SELECT features FROM ml_scalp_samples WHERE sample_id=?", (pr["sample_id"],))
        b, sel = stk.selected_bundle(pr["instrument"], pr["side"])
        if b is None or b.man["model_hash"] != pr["model_hash"]:
            return {"status": "MODEL_CHANGED", "reason": "model tej predykcji nie jest już wybrany – wyjaśnienie nie zostanie zmieszane z innym modelem"}
        return dict(b.explain(json.loads(smp["features"])), prediction_id=prediction_id, snapshot_hash=pr["snapshot_hash"])

    @app.post("/api/v1/ml/scalp/select")
    def ml_scalp_select(body: dict):
        from ..ml import scalp_task as stk
        try:
            return {"ok": True, "selected": stk.select(body.get("asset") or rt.ml.inst, str(body.get("run_id")), str(body.get("side")), str(body.get("role")))}
        except (ValueError, OSError, KeyError) as exc:
            return {"ok": False, "reason": str(exc)}

    @app.post("/api/v1/ml/scalp/rollback")
    def ml_scalp_rollback(body: dict):
        from ..ml import scalp_task as stk
        try:
            return {"ok": True, "selected": stk.rollback(body.get("asset") or rt.ml.inst, str(body.get("side")))}
        except (ValueError, OSError) as exc:
            return {"ok": False, "reason": str(exc)}

    @app.post("/api/v1/ml/reload")
    def ml_reload():
        """After offline training (training installer): re-read champion of the active instrument's ML registry."""
        rt.ml.registry.reload()
        rt.ml._pred_cache.clear()
        return {"ok": True, "instrument": rt.ml.inst, "champion": rt.ml.registry.champion_id}

    @app.post("/api/v1/ml/backfill")
    def ml_backfill(req: MLBackfillReq):
        return rt.ml.start_backfill(req.days)

    @app.post("/api/v1/ml/cancel")
    def ml_cancel():
        return rt.ml.cancel()

    @app.post("/api/v1/ml/resume")
    def ml_resume():
        return rt.ml.resume_interrupted()

    @app.post("/api/v1/ml/rollback")
    def ml_rollback():
        try:
            return rt.ml.rollback()
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/v1/ml/models")
    def ml_models():
        return {"models": rt.ml.registry.models(50), "events": rt.ml.registry.events(50)}

    @app.get("/api/v1/ml/report")
    def ml_report():
        return rt.ml.last_report() or {"available": False, "reason": "NO_COMPLETED_TRAINING"}

    @app.get("/api/v1/ml/explain")
    def ml_explain(setup_id: str = Query(...), version: int = Query(...)):
        return rt.ml.explain(setup_id, version)

    @app.get("/api/v1/ml/predict")
    def ml_predict(setup_id: str = Query(...)):
        row = rt.engine.active.tracker.get(setup_id)
        if not row:
            raise HTTPException(404, "UNKNOWN_SETUP")
        return rt.ml.predict(row, rt.engine.active.view)

    @app.post("/api/v1/strategy/toggle")
    def strategy_toggle(req: StrategyToggleReq):
        from ..strategies import registry as _reg
        if req.strategy_id not in _reg.STRATEGIES:
            raise HTTPException(400, "UNKNOWN_STRATEGY_ID")
        cur = rt.cfg.get().active.strategies.get(req.strategy_id)
        patch = {"scan": cur.scan if cur else True, "trade": cur.trade if cur else True}
        if req.scan is not None:
            patch["scan"] = req.scan
        if req.trade is not None:
            patch["trade"] = req.trade
        rt.cfg.update({"active": {"strategies": {req.strategy_id: patch}}})
        rt.log.info("AUTO", "STRATEGY_TOGGLE", f"{req.strategy_id}: skanuj={'TAK' if patch['scan'] else 'NIE'}, handel={'TAK' if patch['trade'] else 'NIE'}")
        rt.engine.mark_dirty()
        return rt.engine.active.status(compact=True)

    @app.post("/api/v1/strategy/profile")
    def strategy_profile(req: ProfileReq):
        rt.cfg.update({"active": {"profile": req.profile}})
        rt.engine.active.selector.reset("PROFILE_CHANGED")
        rt.log.info("AUTO", "PROFILE", f"Profil wykrywania: {req.profile}")
        rt.engine.mark_dirty()
        return rt.engine.active.status(compact=True)

    @app.get("/api/v1/strategy/selection-log")
    def selection_log(limit: int = 30):
        return {"log": rt.engine.active.selection_log(max(1, min(limit, 200)))}

    @app.get("/api/v1/playbook")
    def playbook(limit: int = 100):
        rows = rt.db.query("SELECT setup_id, strategy_id, strategy_version, direction, timeframe, stage, status, version, score, first_seen_at, first_price, "
                           "updated_at, terminal_reason, terminal_at, synthetic, record_json, history_json FROM strategy_setups ORDER BY first_seen_at DESC LIMIT ?",
                           (max(1, min(limit, 500)),))
        trades = {t["setup_id"]: t for t in rt.db.query("SELECT setup_id, mode, side, net_pnl, gross_pnl, opened_at, closed_at FROM trades WHERE setup_id LIKE 'MQA-%'")}
        out = []
        for r in rows:
            rec = json.loads(r.pop("record_json"))
            hist = json.loads(r.pop("history_json"))
            out.append({**r, "context": {"regime": rec.get("regime"), "horizon": rec.get("horizon"), "countertrend": rec.get("countertrend")},
                        "hypothesis": rec.get("strategy_name"), "plan": {k: rec.get(k) for k in ("entry_plan", "stop_loss", "targets", "invalidation_level", "exit_rules")},
                        "score": rec.get("score"), "missing": rec.get("missing_confirmations"), "history": hist, "result": trades.get(r["setup_id"]) or "brak danych"})
        return {"cards": out, "note": "Karty obejmują także setupy anulowane, unieważnione i wygasłe – nie tylko wybrane sukcesy."}

    @app.get("/api/v1/appearance/assets")
    def appearance_assets():
        out = {}
        for slot, (anim, static_name) in MEDIA_SLOTS.items():
            user = media_dir() / anim
            built = paths.FRONTEND_DIST / "assets" / "masterquo" / anim
            info = gif_info(user.read_bytes()) if user.is_file() else (gif_info(built.read_bytes()) if built.is_file() else None)
            out[slot] = {"animated_available": user.is_file() or built.is_file(), "source": "USER_UPLOAD" if user.is_file() else ("BUILT_IN" if built.is_file() else "NONE"),
                         "animated_url": f"/media/masterquo/{slot}?v={int(user.stat().st_mtime) if user.is_file() else 0}",
                         "static_url": f"/static/assets/masterquo/{static_name}", "gif": info}
        return out

    @app.post("/api/v1/appearance/upload")
    async def appearance_upload(request: Request, slot: str = Query(..., pattern="^(background|frog)$")):
        data = await request.body()
        if len(data) > MAX_GIF_BYTES:
            raise HTTPException(413, "FILE_TOO_LARGE")
        info = gif_info(data)
        if not info:
            raise HTTPException(400, "NOT_A_GIF")
        target = media_dir() / MEDIA_SLOTS[slot][0]
        tmp = target.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(target)
        rt.log.info("UI", "ASSET_UPLOADED", f"Wgrano GIF ({slot}): {info['width']}×{info['height']}, {info['frames']} klatek, pętla {info['loop_duration_ms']} ms")
        return {"ok": True, "slot": slot, "gif": info}

    @app.get("/media/masterquo/{slot}")
    def media(slot: str):
        if slot not in MEDIA_SLOTS:
            raise HTTPException(404)
        name = MEDIA_SLOTS[slot][0]
        for f in (media_dir() / name, paths.FRONTEND_DIST / "assets" / "masterquo" / name):
            if f.is_file():
                return FileResponse(f, media_type="image/gif", headers={"Cache-Control": "no-cache"})
        raise HTTPException(404)

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
