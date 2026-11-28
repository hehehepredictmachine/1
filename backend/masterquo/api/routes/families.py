"""API routes: rodziny modeli.

register(app, ctx): status decyzji i rodziny modeli PMW-FAM-1
    (11 routes; create_app before the split, 7ba7ab0: lines 2668-2734)

The handlers are the ones create_app defined before the split (Etap 4 krok B, docs/arch146/ETAP2_PROJEKT.md §3 / §5):
same function names, signatures, decorators, Pydantic models, error codes and body - the block of create_app is copied
verbatim, the only edit is one more dot in a relative import (the package is one level deeper). The create_app locals the
block used (rt, helpers, handlers called by name) are bound from ctx at the top of the function under the same names;
registration order: api/routes/__init__.REGISTRATION.
"""
from __future__ import annotations

import json

from fastapi import Body, HTTPException, Query

from .. import deps as _deps


def register(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 2668-2734: 11 routes."""
    rt = ctx.rt

    # ---------------------------------------------------------------- PMW-FAM-1 model families (1.33)
    def _fam_inst(instrument):
        return _deps.instrument(instrument, normalize=True, default=lambda: rt.cfg.get().assets.active, error_code="INSTRUMENT_INVALID")

    def _fam(fn, *a, **k):
        try:
            return fn(*a, **k)
        except KeyError as exc:
            raise HTTPException(404, str(exc).strip("'")) from None
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.get("/api/v1/decision/status")
    def decision_status():
        """PMW-ARC-1: last decision of each path, live risk reservations, recent execution intents and decision records."""
        arc = getattr(rt, "arc", None)
        if arc is None:
            raise HTTPException(503, "DECISION_COORDINATOR_NOT_RUNNING")
        return arc.status()

    @app.get("/api/v1/decision/records/{record_id}")
    def decision_record(record_id: str):
        r = rt.db.one("SELECT record_json FROM decision_records WHERE record_id=?", (record_id,))
        if not r:
            raise HTTPException(404, "RECORD_NOT_FOUND")
        return json.loads(r["record_json"])

    @app.get("/api/v1/families")
    def families_catalog(instrument: str | None = Query(None)):
        inst = _fam_inst(instrument)
        return {"instrument": inst, "items": rt.families.catalog(inst),
                "axes": {"implementation": "dostępność kodu/zależności", "artifact": "artefakt i walidacja", "use": "OFF / SHADOW / ASSIST"},
                "note": "READY = zdolność zwrócenia wyniku, nie zgoda na handel ani dowód rentowności"}

    @app.get("/api/v1/families/{fid}/runs")
    def families_runs(fid: str, instrument: str | None = Query(None)):
        return {"items": _fam(rt.families.runs, fid, _fam_inst(instrument))}

    @app.post("/api/v1/families/{fid}/train")
    def families_train(fid: str, body: dict = Body(default={})):
        return _fam(rt.families.submit, fid, _fam_inst(body.get("instrument")), str(body.get("profile") or "smoke"))

    @app.post("/api/v1/families/train-all")
    def families_train_all(body: dict = Body(default={})):
        return _fam(rt.families.train_all, _fam_inst(body.get("instrument")), str(body.get("profile") or "smoke"))

    @app.post("/api/v1/families/{fid}/cancel")
    def families_cancel(fid: str, body: dict = Body(default={})):
        return _fam(rt.families.cancel, fid, _fam_inst(body.get("instrument")))

    @app.post("/api/v1/families/{fid}/activate")
    def families_activate(fid: str, body: dict = Body(...)):
        r = _fam(rt.families.activate, fid, _fam_inst(body.get("instrument")), str(body.get("run_id") or ""))
        if not r.get("ok"):
            raise HTTPException(409, r.get("reason"))
        return r

    @app.post("/api/v1/families/{fid}/rollback")
    def families_rollback(fid: str, body: dict = Body(default={})):
        return _fam(rt.families.rollback, fid, _fam_inst(body.get("instrument")))

    @app.post("/api/v1/families/{fid}/use")
    def families_use(fid: str, body: dict = Body(...)):
        return _fam(rt.families.set_use, fid, _fam_inst(body.get("instrument")), str(body.get("use") or "").upper())

    @app.get("/api/v1/families/predictions")
    def families_predictions(instrument: str | None = Query(None)):
        return {"items": rt.families.predictions(_fam_inst(instrument))}
