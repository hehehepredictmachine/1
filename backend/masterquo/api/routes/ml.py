"""API routes: ML.

register(app, ctx): ML (Decision Tree + XGBoost)
    (5 routes; create_app before the split, 7ba7ab0: lines 1832-1858)
register_scalp(app, ctx): SCALP_NET_PROFIT_MARKET_V1 i operacje ML (reload, backfill, cancel, resume, rollback, raporty)
    (16 routes; create_app before the split, 7ba7ab0: lines 3760-3892)

The handlers are the ones create_app defined before the split (Etap 4 krok B, docs/arch146/ETAP2_PROJEKT.md §3 / §5):
same function names, signatures, decorators, Pydantic models, error codes and body - the block of create_app is copied
verbatim, the only edit is one more dot in a relative import (the package is one level deeper). The create_app locals the
block used (rt, helpers, handlers called by name) are bound from ctx at the top of the function under the same names;
registration order: api/routes/__init__.REGISTRATION.
"""
from __future__ import annotations

import json
import os
import sys

from fastapi import HTTPException, Query

from ... import paths
from ...config import ALLOWED_ASSETS
from ..common import body_num
from ..schemas import MLBackfillReq, MLFlagReq, MLModeReq, MLTrainReq


def register(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 1832-1858: 5 routes."""
    rt = ctx.rt

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


def register_scalp(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 3760-3892: 16 routes."""
    rt = ctx.rt
    _train_start = ctx._train_start
    _th_inst = ctx._th_inst

    # ------------------------------------------------------------ PMW-UPD-03 SCALP_NET_PROFIT_MARKET_V1
    @app.get("/api/v1/ml/scalp")
    def ml_scalp_status(asset: str | None = Query(None)):
        inst = asset or rt.cfg.get().assets.active
        if inst not in ALLOWED_ASSETS:
            raise HTTPException(400, "UNKNOWN_INSTRUMENT")              # 1.46: was ValueError UNKNOWN_INSTRUMENT -> 500
        if inst != rt.ml.inst:
            from types import SimpleNamespace

            from ...ml.router import ml_store
            from ...ml.service import MLService
            # 1.46: read-only - constructing an MLService for this GET ran _recover_jobs(): every RUNNING / QUEUED ml_jobs row of the
            # other instrument (e.g. the offline training of the installer, a separate process) was marked INTERRUPTED with an
            # APP_RESTART event on each refresh. scalp_status() only reads self.db.
            db, _root = ml_store(inst, rt.db)
            try:
                return MLService.scalp_status(SimpleNamespace(db=db), inst)
            finally:
                if db is not rt.db:
                    db.close()
        return rt.ml.scalp_status(inst)

    def _ml_scalp_job(args: list[str]):
        import subprocess
        from ...training import core as tc
        kw = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if os.name == "nt" else {"start_new_session": True}

        def start():
            with open(tc.training_dir() / "ml_scalp_jobs.log", "a", encoding="utf-8") as log:               # the child keeps its own handle
                return subprocess.Popen([sys.executable, "-m", "masterquo", "ml-scalp", *args], cwd=str(paths.ROOT_DIR / "backend"), stdout=log,
                                        stderr=subprocess.STDOUT, **kw)
        pr = _train_start("ml_scalp", start)          # 1.46: one ml-scalp job (prepare / train) at a time
        return {"started": True, "job_pid": pr.pid, "args": args}

    @app.post("/api/v1/ml/scalp/prepare")
    def ml_scalp_prepare(body: dict):
        inst = body.get("asset") or rt.cfg.get().assets.active
        if inst not in ALLOWED_ASSETS:
            raise HTTPException(400, "UNKNOWN_INSTRUMENT")
        return _ml_scalp_job(["prepare", "--asset", inst])

    @app.post("/api/v1/ml/scalp/train")
    def ml_scalp_train(body: dict):
        inst = body.get("asset") or rt.cfg.get().assets.active
        if inst not in ALLOWED_ASSETS:
            raise HTTPException(400, "UNKNOWN_INSTRUMENT")
        args = ["train", "--asset", inst, "--activate", "none"]
        comm = body_num(body, "commission", None, float, 0, 1000)      # 1.46: 'abc' was a ValueError -> 500, NaN / negative went to the CLI
        if comm is not None:
            args += ["--commission", str(comm)]
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
        from ...ml import scalp_task as stk
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
        from ...ml import scalp_task as stk
        inst = _th_inst(body.get("asset") or rt.ml.inst)          # 1.46: checked - '../..' created folders outside the data folder
        try:
            return {"ok": True, "selected": stk.select(inst, str(body.get("run_id")), str(body.get("side")), str(body.get("role")))}
        except (ValueError, OSError, KeyError) as exc:
            return {"ok": False, "reason": str(exc)}

    @app.post("/api/v1/ml/scalp/rollback")
    def ml_scalp_rollback(body: dict):
        from ...ml import scalp_task as stk
        inst = _th_inst(body.get("asset") or rt.ml.inst)          # 1.46: checked (folder name)
        try:
            return {"ok": True, "selected": stk.rollback(inst, str(body.get("side")))}
        except (ValueError, OSError) as exc:
            return {"ok": False, "reason": str(exc)}

    @app.post("/api/v1/ml/reload")
    def ml_reload():
        """After offline training (training installer): re-read champion of the active instrument's ML registry."""
        rt.ml.registry.reload()
        rt.ml.clear_prediction_cache()
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
