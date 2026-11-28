"""API routes: trening.

register_installer(app, ctx): instalator treningu i panel treningu PMW-SH-1
    (2 routes; create_app before the split, 7ba7ab0: lines 1861-1877)
register_runs(app, ctx): przebiegi treningu (gotowość, historia, raporty, eksport / import, start)
    (12 routes; create_app before the split, 7ba7ab0: lines 3180-3335)
register_pepe(app, ctx): Centrum Treningowe Pepe PMW-TCP-1
    (6 routes; create_app before the split, 7ba7ab0: lines 3367-3405)
register_active(app, ctx): anulowanie, aktywne wersje i rollback treningu
    (3 routes; create_app before the split, 7ba7ab0: lines 3502-3569)

The handlers are the ones create_app defined before the split (Etap 4 krok B, docs/arch146/ETAP2_PROJEKT.md §3 / §5):
same function names, signatures, decorators, Pydantic models, error codes and body - the block of create_app is copied
verbatim, the only edit is one more dot in a relative import (the package is one level deeper). The create_app locals the
block used (rt, helpers, handlers called by name) are bound from ctx at the top of the function under the same names;
registration order: api/routes/__init__.REGISTRATION.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from fastapi import Body, HTTPException, Query, Request
from fastapi.responses import FileResponse

from ... import paths
from ...config import ALLOWED_ASSETS


def register_installer(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 1861-1877: 2 routes."""
    rt = ctx.rt

    # ------------------------------------------------------------ training installer (same backend as the BAT launchers)
    @app.get("/api/v1/training")
    def training_state():
        from ...training import core as tc
        from ...training import panel as tp
        rid = tc.Run.latest()
        st = tp.run_detail(rid) if rid else None
        from ...training.runner import TASKS
        return {"run": st, "profiles": {k: v["label"] for k, v in tc.profiles().items()}, "tasks": [{"kind": k, "title": t} for k, t in TASKS],
                "lock": tp.lock_holder()}

    # ---------------------------------------------------------------- PMW-SH-1 training panel (registry, readiness, history, export)
    @app.get("/api/v1/training/models")
    def training_models(instrument: str = Query(...)):
        from ...training import panel as tp
        if instrument not in ALLOWED_ASSETS:
            raise HTTPException(400, "UNKNOWN_INSTRUMENT")
        return tp.models(rt, instrument)


def register_runs(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 3180-3335: 12 routes."""
    rt = ctx.rt

    @app.get("/api/v1/training/readiness")
    def training_readiness(instrument: str = Query(...)):
        from ...training import panel as tp
        if instrument not in ALLOWED_ASSETS:
            raise HTTPException(400, "UNKNOWN_INSTRUMENT")
        return tp.readiness(rt, instrument)

    @app.get("/api/v1/training/runs")
    def training_runs(limit: int = Query(50, ge=1, le=500)):
        from ...training import panel as tp
        return {"items": tp.runs(limit)}

    def _rid_ok(rid: str) -> str:
        from ...training import core as tc
        # 1.46: a non-text run_id (body of /training/resume) was a TypeError in re.fullmatch -> 500
        if not isinstance(rid, str) or not re.fullmatch(r"[A-Za-z0-9_\-]{6,80}", rid) or not (tc.runs_dir() / rid / "state.json").exists():
            raise HTTPException(404)
        return rid

    @app.get("/api/v1/training/runs/{rid}")
    def training_run(rid: str):
        from ...training import panel as tp
        return tp.run_detail(_rid_ok(rid))

    @app.get("/api/v1/training/runs/{rid}/log")
    def training_run_log(rid: str, task: str = Query(...), nbytes: int = Query(20000, ge=1000, le=500000)):
        from ...training import panel as tp
        try:
            return tp.task_log(_rid_ok(rid), task, nbytes)
        except StopIteration:
            raise HTTPException(404, "UNKNOWN_TASK")

    @app.get("/api/v1/training/runs/{rid}/report")
    def training_run_report(rid: str):
        from ...training import core as tc
        p = tc.runs_dir() / _rid_ok(rid) / "report.html"
        if not p.exists():
            raise HTTPException(404, "REPORT_NOT_READY")
        return FileResponse(p, media_type="text/html")

    @app.get("/api/v1/training/compare")
    def training_compare(a: str = Query(...), b: str = Query(...)):
        from ...training import panel as tp
        return tp.compare(_rid_ok(a), _rid_ok(b))

    @app.post("/api/v1/training/resume")
    def training_resume(body: dict = Body(default={})):
        import subprocess
        from ...training import core as tc
        from ...training import panel as tp
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
        from ...training import panel as tp
        inst = body.get("instrument")
        if inst not in ALLOWED_ASSETS:
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
        from ...training import panel as tp
        if not re.fullmatch(r"PMW_TRENING_[A-Za-z0-9_\-]+\.zip", name):
            raise HTTPException(404)
        p = tp.exports_dir() / name
        if not p.exists():
            raise HTTPException(404)
        return FileResponse(p, media_type="application/zip", filename=name)

    @app.post("/api/v1/training/import")
    async def training_import(request: Request):
        from starlette.concurrency import run_in_threadpool

        from ...training import panel as tp
        data = await request.body()
        if not data or len(data) > 512 * 2**20:
            raise HTTPException(400, "EMPTY_OR_TOO_LARGE")
        try:
            return await run_in_threadpool(tp.import_package, data)      # 1.46: up to 512 MB unpacked + hashed outside the event loop
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.post("/api/v1/training/sh/promote")
    def training_sh_promote(body: dict = Body(...)):
        from ...sh import tpmodel as TM
        inst, strat, rid = body.get("instrument"), body.get("strategy"), body.get("run_id")
        if inst not in ALLOWED_ASSETS or strat not in ("SCALPING", "HEDGING") or not rid:
            raise HTTPException(400, "BAD_REQUEST")
        try:
            r = TM.promote(inst, strat, str(rid))
        except ValueError as exc:
            return {"ok": False, "reason": str(exc)}
        rt.log.warn("TRAINING", "SH_PROMOTE", f"sh_tp_model {inst}/{strat}: aktywny {r['active']}")
        return {"ok": True, **r}

    @app.post("/api/v1/training/start")
    def training_start(body: dict):
        """Starts `masterquo training run` as a separate process (never inside the bot process; no orders, execution mode untouched)."""
        import subprocess
        from ...training import core as tc
        insts = ",".join(i for i in ALLOWED_ASSETS if i in (body.get("instruments") or []))
        if not insts:
            raise HTTPException(400, "NO_INSTRUMENT")
        prof = body.get("profile") or "PELNY_TRENING"
        if prof not in tc.profiles():
            raise HTTPException(400, "BAD_PROFILE")
        cmd = [sys.executable, "-m", "masterquo", "training", "run", "--instruments", insts, "--profile", prof, "--origin", "panel"]
        if body.get("tasks"):                                  # one model / a subset (export, QC, activation and bot always run)
            from ...training.runner import TASKS
            sel = [t for t in body["tasks"] if t in {k for k, _ in TASKS}]
            if not sel:
                raise HTTPException(400, "BAD_TASKS")
            cmd += ["--tasks", ",".join(sel)]
        for k, flag in (("months", "--months"), ("symbol_xauusd", "--symbol-xauusd"), ("symbol_btc", "--symbol-btc"),
                        ("commission_xauusd", "--commission-xauusd"), ("commission_btc", "--commission-btc")):
            if body.get(k) not in (None, ""):
                cmd += [flag, str(body[k])]
        for k, flag in (("dataset_xauusd", "--dataset-xauusd"), ("dataset_btc", "--dataset-btc")):   # export made in the panel
            if body.get(k):
                d = Path(str(body[k])).resolve()
                if paths.data_dir().resolve() not in d.parents:
                    raise HTTPException(400, "BAD_DIR")
                cmd += [flag, str(d)]
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


def register_pepe(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 3367-3405: 6 routes."""
    rt = ctx.rt

    @app.get("/api/v1/pepe-training")
    def pepe_training_status():
        return rt.pepe_training.status()

    @app.post("/api/v1/pepe-training/train")
    def pepe_training_train(body: dict = Body(default={})):
        units = body.get("units")
        if units != "ALL" and not (isinstance(units, list) and units):
            raise HTTPException(400, "UNITS: lista identyfikatorów albo \"ALL\"")
        try:
            return rt.pepe_training.enqueue(units, body.get("instruments"))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.put("/api/v1/pepe-training/settings")
    def pepe_training_settings(body: dict = Body(default={})):
        try:
            return rt.pepe_training.set_settings(body)
        except ValueError as exc:
            raise HTTPException(400, str(exc)[:200])

    @app.post("/api/v1/pepe-training/cancel")
    def pepe_training_cancel():
        return rt.pepe_training.cancel()

    @app.post("/api/v1/pepe-training/remove")
    def pepe_training_remove(body: dict = Body(default={})):
        return rt.pepe_training.remove(str(body.get("id") or ""))

    @app.get("/api/v1/pepe-training/log")
    def pepe_training_log(lines: int = Query(80, ge=10, le=400)):
        from ...training import core as tc
        out = {}
        for name, f in (("center", tc.training_dir() / "pepe_center.log"),):
            try:
                out[name] = f.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
            except OSError:
                out[name] = []
        return out


def register_active(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 3502-3569: 3 routes."""
    rt = ctx.rt

    @app.post("/api/v1/training/cancel")
    def training_cancel():
        from ...training import core as tc
        rid = tc.Run.latest()
        if not rid:
            return {"ok": False, "reason": "NO_RUN"}
        (tc.runs_dir() / rid / "CANCEL").write_text(tc.now(), encoding="utf-8")
        return {"ok": True, "run_id": rid}

    @app.get("/api/v1/training/active")
    def training_active(instrument: str = Query(...)):
        import json as _j
        import mq_instruments as mi
        from ...lab.protocol import read_pointer
        from ...ml.router import ml_store
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
            try:
                row = db.one("SELECT model_id FROM ml_models WHERE status='CHAMPION'")
            finally:
                # 1.46 arch (I0096): the Database built here for an inactive instrument was never closed (one per request). Only that
                # ad-hoc instance is closed (its connection of THIS request thread) - never the main database nor the active ML service's
                if db is not rt.db and db is not getattr(getattr(rt.ml, "cur", None), "db", None):
                    db.close()
            out["ml"] = {"active": row["model_id"] if row else None}
        ptr = read_pointer(paths.data_dir() / "lab", instrument)
        out["lab"] = {"pinned": ptr["active"], "models": [{k: m.get(k) for k in ("model_id", "family", "role", "verdict")} for m in rt.lab.trainer.models(instrument)][:20]}
        return {"instrument": instrument, "families": out}

    @app.post("/api/v1/training/rollback")
    def training_rollback(body: dict):
        import subprocess
        inst, fam = body.get("instrument"), str(body.get("family") or "")
        if inst not in ALLOWED_ASSETS or not (fam in ("forecast", "scalp", "ml") or fam.startswith(("lab:", "sh:"))):
            raise HTTPException(400, "BAD_REQUEST")
        if fam.startswith("sh:"):
            from ...sh import tpmodel as TM
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
        try:
            r = subprocess.run([sys.executable, "-m", "masterquo", "training", "rollback", "--instrument", inst, "--family", fam],
                               cwd=str(paths.ROOT_DIR / "backend"), capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired:          # 1.46: was an unhandled 500 and the forecast models were not re-read
            rt.forecast.reload()
            return {"ok": False, "reason": "TIMEOUT", "output": "rollback nie zakończył się w 300 s"}
        rt.forecast.reload()
        return {"ok": r.returncode == 0, "output": (r.stdout + r.stderr)[-800:]}
