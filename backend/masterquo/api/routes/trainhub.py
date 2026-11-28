"""API routes: Centrum treningu.

register(app, ctx): Centrum treningu + rejestr modeli 1.28, komponenty 1.41
    (20 routes; create_app before the split, 7ba7ab0: lines 1981-2185)

The handlers are the ones create_app defined before the split (Etap 4 krok B, docs/arch146/ETAP2_PROJEKT.md §3 / §5):
same function names, signatures, decorators, Pydantic models, error codes and body - the block of create_app is copied
verbatim, the only edit is one more dot in a relative import (the package is one level deeper). The create_app locals the
block used (rt, helpers, handlers called by name) are bound from ctx at the top of the function under the same names;
registration order: api/routes/__init__.REGISTRATION.
"""
from __future__ import annotations

import re

from fastapi import Body, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response

from ...config import ALLOWED_ASSETS
from .. import deps as _deps
from ..schemas import TrainJobReq, TrainVersionReq


def register(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 1981-2185: 20 routes."""
    rt = ctx.rt
    _research = ctx._research

    # ---------------------------------------------------------------- 1.28 Centrum treningu + rejestr modeli (wspólny kontrakt)
    def _th_inst(x: str) -> str:
        # 1.46: a number / object was an AttributeError (.upper) -> 500; 1.46 arch (I0087): one validator, same code / normalisation
        return _deps.instrument(x, normalize=True, error_code="INSTRUMENT_NOT_ALLOWED")

    _SAFE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")

    # ---- 1.41 Training Center components (dispatch by component kind): TH_SDFORMERFLOW (weights), ETC_LOG_CHANNEL (transform config)
    def _comp():
        return _research().components

    def _cid(cid: str) -> str:
        # 1.46: an unknown component id was a KeyError (export.zip -> 500) or silently acted on ETC_LOG_CHANNEL (activate / rollback / cancel)
        from ...research.components import COMPONENTS
        if cid not in COMPONENTS:
            raise HTTPException(404, "UNKNOWN_COMPONENT")
        return cid

    def _sdf_checkpoint(r, ck) -> str:
        """1.46: a checkpoint from the request is a version id directly in the SDformerFlow folder with last.pt (as activate_sdf checks).
        An absolute / '..' path made the worker unpickle any file (torch.load weights_only=False) and write a resume anywhere; a number
        was a TypeError -> 500."""
        if not isinstance(ck, str) or not _SAFE.match(ck):
            raise HTTPException(400, "CHECKPOINT_INVALID")
        d = r._sdf_dir() / ck
        if d.parent != r._sdf_dir() or not (d / "last.pt").is_file():
            raise HTTPException(400, "CHECKPOINT_NOT_FOUND")
        return ck

    @app.get("/api/v1/trainhub/components")
    def th_components():
        return _comp().status()

    @app.post("/api/v1/trainhub/components/{cid}/jobs")
    def th_component_job(cid: str, body: dict = Body(default={})):
        if _cid(cid) == "TH_SDFORMERFLOW" and body.get("checkpoint"):
            _sdf_checkpoint(_research(), body.get("checkpoint"))
        try:
            r = _comp().start_job(cid, str(body.get("kind") or "").upper(), body)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        if not r.get("ok", True):
            raise HTTPException(409, r.get("reason") or r.get("state"))
        return r

    @app.post("/api/v1/trainhub/components/{cid}/cancel")
    def th_component_cancel(cid: str):
        return _comp().cancel(_cid(cid))

    @app.post("/api/v1/trainhub/components/{cid}/activate")
    def th_component_activate(cid: str, body: dict = Body(...)):
        c = _comp()
        r = c.activate_sdf(str(body.get("version"))) if _cid(cid) == "TH_SDFORMERFLOW" else c.etc_activate(str(body.get("version")))
        if not r.get("ok"):
            raise HTTPException(409, r.get("reason") or "aktywacja nieudana")
        return r

    @app.post("/api/v1/trainhub/components/{cid}/rollback")
    def th_component_rollback(cid: str):
        c = _comp()
        r = c.rollback_sdf() if _cid(cid) == "TH_SDFORMERFLOW" else c.etc_rollback()
        if not r.get("ok"):
            raise HTTPException(409, r.get("reason"))
        return r

    @app.get("/api/v1/trainhub/components/{cid}/export.zip")
    def th_component_export(cid: str, version: str):
        try:
            data = _comp().export_zip(_cid(cid), version)
        except FileNotFoundError:
            raise HTTPException(404, "brak wersji")
        return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{cid}_{version}.zip"'})

    @app.post("/api/v1/trainhub/components/{cid}/import")
    async def th_component_import(cid: str, request: Request):
        from starlette.concurrency import run_in_threadpool
        _cid(cid)
        data = await request.body()
        if not data or len(data) > 200 * 1024 * 1024:
            raise HTTPException(400, "puste lub zbyt duże archiwum")
        try:
            # 1.46: unzip + sha256 + disk writes of up to 200 MB ran IN the event loop - every request (STOP, close) and the WebSocket
            # quotes waited for the import; now in the worker pool
            return await run_in_threadpool(_comp().import_zip, cid, data)
        except (ValueError, KeyError, __import__("zipfile").BadZipFile) as exc:
            raise HTTPException(400, f"import odrzucony: {exc}")

    @app.get("/api/v1/trainhub/status")
    def trainhub_status():
        from ...marketdata.store import Store
        from ...trainhub import learn as _L
        from ...trainhub import pipeline as _P
        st = Store()
        data = {}
        for i in ALLOWED_ASSETS:
            man = st.manifest(i)
            data[i] = {"symbol": man.get("symbol") or rt.market_zones.symbol_for(i), "data_kind": man.get("data_kind"),
                       "timeframes": man.get("timeframes") or {}, "last_export": man.get("last_export"), "costs": man.get("costs"),
                       "time_model": man.get("time_model"), "updated_at": man.get("updated_at"), "parquet": man.get("parquet")}
        return {"jobs": rt.trainhub.list(30), "queue": rt.trainhub.status(), "data": data, "models": {k: {"name": v["name"], "available": _L.available()[k]}
                                                                                                         for k, v in _L.MODELS.items()},
                "defaults": _P.DEFAULTS, "note": "trening nie aktywuje modeli; aktywacja ręczna po teście zgodności i predykcji"}

    @app.post("/api/v1/trainhub/jobs")
    def trainhub_submit(req: TrainJobReq):
        try:
            return rt.trainhub.submit(req.kind, _th_inst(req.instrument), req.params)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/v1/trainhub/jobs")
    def trainhub_jobs(limit: int = Query(50, ge=1, le=500)):
        return {"items": rt.trainhub.list(limit)}

    @app.get("/api/v1/trainhub/jobs/{jid}")
    def trainhub_job(jid: str):
        j = rt.trainhub.get(jid)
        if j is None:
            raise HTTPException(404, "JOB_NOT_FOUND")
        return {**j, "log_tail": rt.trainhub.log_tail(jid, 120)}

    @app.post("/api/v1/trainhub/jobs/{jid}/cancel")
    def trainhub_cancel(jid: str):
        try:
            return rt.trainhub.cancel(jid)
        except KeyError as exc:
            raise HTTPException(404, "JOB_NOT_FOUND") from exc

    @app.get("/api/v1/trainhub/data")
    def trainhub_data(instrument: str = Query("XAUUSD")):
        from ...marketdata.store import Store, read_json
        st = Store()
        i = _th_inst(instrument)
        return {"manifest": st.manifest(i), "quality": read_json(st.inst_dir(i) / "quality_report.json", None), "verify": st.verify(i)}

    @app.get("/api/v1/trainhub/registry")
    def trainhub_registry(instrument: str = Query("XAUUSD")):
        from ...trainhub import registry as _R
        return _R.summary(_th_inst(instrument))

    @app.get("/api/v1/trainhub/version")
    def trainhub_version(instrument: str, model_key: str, version: str):
        from ...marketdata.store import read_json
        from ...trainhub import registry as _R
        i = _th_inst(instrument)
        if not (_SAFE.match(model_key) and _SAFE.match(version)):
            raise HTTPException(400, "INVALID_ID")
        d = _R.package_dir(i, model_key, version)
        if not d.exists():
            raise HTTPException(404, "VERSION_NOT_FOUND")
        return {"config": read_json(d / "config.json", {}), "metrics": read_json(d / "metrics.json", {}), "deps": read_json(d / "deps.json", {}),
                "data_manifest": read_json(d / "data_manifest.json", {}), "compatibility": _R.compatibility(i, model_key, version),
                "evaluations": read_json(d.parent / f"{version}.evaluations.json", [])}

    @app.post("/api/v1/trainhub/activate")
    def trainhub_activate(req: TrainVersionReq):
        from ...trainhub import registry as _R
        i = _th_inst(req.instrument)
        if not req.version:
            raise HTTPException(400, "VERSION_REQUIRED")
        out = _R.activate(i, req.model_key, req.version, reason="panel – Centrum treningu")
        rt.trainhub_inference.invalidate(i)
        return out

    @app.post("/api/v1/trainhub/rollback")
    def trainhub_rollback(req: TrainVersionReq):
        from ...trainhub import registry as _R
        i = _th_inst(req.instrument)
        out = _R.rollback(i, req.model_key)
        rt.trainhub_inference.invalidate(i)
        return out

    @app.post("/api/v1/trainhub/deactivate")
    def trainhub_deactivate(req: TrainVersionReq):
        from ...trainhub import registry as _R
        i = _th_inst(req.instrument)
        out = _R.deactivate(i, req.model_key)
        rt.trainhub_inference.invalidate(i)
        return out

    @app.get("/api/v1/trainhub/package.zip")
    def trainhub_package_zip(instrument: str, model_key: str, version: str):
        from ...trainhub import registry as _R
        i = _th_inst(instrument)
        if not (_SAFE.match(model_key) and _SAFE.match(version)):
            raise HTTPException(400, "INVALID_ID")
        out = _R.root() / "exports" / f"{i}_{model_key}_{version}.zip"
        try:
            _R.export_zip(i, model_key, version, out)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(409, f"{type(exc).__name__}: {exc}"[:200]) from exc
        return FileResponse(out, media_type="application/zip", filename=out.name)

    @app.get("/api/v1/trainhub/dataset.zip")
    def trainhub_dataset_zip(instrument: str, base_tf: str = "M5", horizon: int = 6):
        from ...trainhub import pipeline as _P
        from ...trainhub import registry as _R
        i = _th_inst(instrument)
        if base_tf not in ("M1", "M5", "M15", "M30"):
            raise HTTPException(400, "INVALID_TF")
        out = _R.root() / "exports" / f"{i}_dataset_{base_tf}_H{int(horizon)}.zip"
        try:
            _P.export_dataset_zip(i, {"base_tf": base_tf, "horizon": int(horizon)}, out)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        return FileResponse(out, media_type="application/zip", filename=out.name)

    ctx._th_inst = _th_inst
    ctx._sdf_checkpoint = _sdf_checkpoint
