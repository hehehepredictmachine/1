"""Pepe Data & Training Studio - FastAPI app (own process / port / data dir). It imports NO bot Runtime, strategies or execution code.
Endpoints under /api/studio/*; the UI is the separate frontend entry studio.html (frontend/dist). Local only (127.0.0.1)."""
from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse

from . import registry as R
from . import settings as S
from .queue import Queue

VERSION = "PMW-STUDIO-1"
REPORT_FILES = ("validation/validate_raw/raw.json", "validation/validate_dataset/dataset.json", "evaluation/evaluate/metrics.json",
                "evaluation/verify_loader/loader.json", "raw/export/export_report.json")


def _bot_health(port: int) -> dict | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/health", timeout=2) as r:
            return json.loads(r.read())
    except Exception:  # noqa: BLE001
        return None


def create_app(queue: Queue | None = None, *, start_worker: bool = True) -> FastAPI:
    from .. import paths
    from ..config import ConfigStore
    from ..version import APP_VERSION
    os.environ.setdefault("MASTERQUO_DATA_DIR", str(S.data_dir()))       # Studio's own registries / logs - never the bot's
    cfg = ConfigStore()
    q = queue or Queue(env={"MASTERQUO_DATA_DIR": str(S.data_dir()), "MQ_STUDIO_DATA_DIR": str(S.data_dir()),
                            "MQ_BOT_DATA_DIR": str(S.bot_data_dir())})
    app = FastAPI(title="Pepe Data & Training Studio", version=APP_VERSION)
    app.state.queue = q
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
        src = {"mode": m, "cutoff": int(time.time()), "start": body.get("start"), "end": body.get("end")}
        if m == "BOT_CACHE":
            src["store_root"] = str(S.bot_data_dir(s) / "marketdata")
        if m == "OFFLINE":
            if not body.get("store_root"):
                raise HTTPException(400, "OFFLINE wymaga store_root (magazyn świec)")
            src["store_root"] = str(body["store_root"])
        if m == "SYNTHETIC":
            src["days"] = int(body.get("days") or 30)
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
        return {"bot": {"running": bool(bot), "health": bot, "port": s["bot_port"], "data_dir": str(S.bot_data_dir(s))},
                "mt5_package": mt5, "envs": envs, "studio_data_dir": str(S.data_dir()), "export_lock": q.lock.owner(),
                "mode_hint": "BOT_CACHE" if bot else "MT5_DIRECT", "settings": s}

    @app.post("/api/studio/settings")
    def settings_save(body: dict = Body(...)):
        return S.save(body)

    @app.get("/api/studio/models")
    def models(instrument: str | None = Query(None)):
        rows = [dict(t, operations=R.operations(t)) for t in R.tasks(cfg) if instrument in (None, t["instrument"])]
        return {"items": rows, "count": len(rows)}

    @app.get("/api/studio/matrix")
    def matrix():
        m = R.matrix(cfg)
        (S.data_dir() / "MODEL_DATA_MATRIX.json").write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
        return m

    @app.post("/api/studio/jobs")
    def submit(body: dict = Body(...)):
        keys = body.get("task_keys") or ([body["task_key"]] if body.get("task_key") else [])
        if not keys:
            raise HTTPException(400, "task_key(s) wymagane")
        known = R.by_key(cfg)
        bad = [k for k in keys if k not in known]
        if bad:
            raise HTTPException(404, f"nieznane zadania: {bad}")
        op = str(body.get("op") or "FULL_PROCESS").upper()
        for k in keys:
            if op not in R.operations(known[k]):
                raise HTTPException(409, f"operacja {op} niedostępna dla {k} ({known[k]['category']}, {known[k]['state']})")
        src = source_for(body.get("source"), body)
        return {"items": q.submit_many(keys, op, source=src, profile=str(body.get("profile") or S.load()["profile"]))}

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
            from ..train_all import Bot
            b = Bot(int(s["bot_port"]))
            b.login()
            st, res = b._req("POST", "/api/v1/studio/import", {"package": j["package"]}, timeout=120)
            if st != 200 or not (isinstance(res, dict) and res.get("ok")):
                raise HTTPException(409, f"bot odrzucił import: {res}")
            q.db.execute("UPDATE jobs SET state='TRANSFERRED', progress=? WHERE job_id=?", (json.dumps(res, default=str), jid))
            return {"ok": True, "via": "BOT_API", "import": res}
        inbox = S.bot_data_dir(s) / "studio_inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        ptr = inbox / f"{jid}.json"
        tmp = ptr.with_suffix(".tmp")
        tmp.write_text(json.dumps({"package": j["package"], "job_id": jid, "at": time.time()}), encoding="utf-8")
        tmp.replace(ptr)
        q.db.execute("UPDATE jobs SET state='TRANSFERRED', progress=? WHERE job_id=?", (json.dumps({"via": "INBOX", "pointer": str(ptr)}), jid))
        return {"ok": True, "via": "INBOX", "pointer": str(ptr), "note": "bot zaimportuje paczkę przy następnym starcie (kandydat, nieaktywny)"}

    @app.get("/", response_class=HTMLResponse)
    def index():
        p = paths.ROOT_DIR / "frontend" / "dist" / "studio.html"
        if p.exists():
            return FileResponse(p)
        return HTMLResponse("<h1>Pepe Data &amp; Training Studio</h1><p>Brak zbudowanego interfejsu (frontend/dist/studio.html). API: /api/studio/health</p>")

    from fastapi.staticfiles import StaticFiles
    assets = paths.ROOT_DIR / "frontend" / "dist" / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")
    return app


def serve(port: int | None = None) -> int:
    import uvicorn
    s = S.load()
    p = int(port or s["port"])
    print(f"[PepeTrainingStudio] http://127.0.0.1:{p}/  (dane: {S.data_dir()})", flush=True)
    uvicorn.run(create_app(), host="127.0.0.1", port=p, log_level="warning")
    return 0
