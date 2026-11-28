"""API routes: ocena.

register(app, ctx): ocena kandydatów (eval)
    (4 routes; create_app before the split, 7ba7ab0: lines 3124-3141)

The handlers are the ones create_app defined before the split (Etap 4 krok B, docs/arch146/ETAP2_PROJEKT.md §3 / §5):
same function names, signatures, decorators, Pydantic models, error codes and body - the block of create_app is copied
verbatim, the only edit is one more dot in a relative import (the package is one level deeper). The create_app locals the
block used (rt, helpers, handlers called by name) are bound from ctx at the top of the function under the same names;
registration order: api/routes/__init__.REGISTRATION.
"""
from __future__ import annotations

from fastapi import HTTPException, Query


def register(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 3124-3141: 4 routes."""
    rt = ctx.rt

    @app.get("/api/v1/eval/status")
    def eval_status():
        return rt.evaluation.status()

    @app.get("/api/v1/eval/assessments")
    def eval_assessments(engine: str | None = Query(None), limit: int = Query(50, ge=1, le=500)):
        from ...evaluation.contract import ENGINES
        if engine is not None and engine not in ENGINES:
            raise HTTPException(400, "UNKNOWN_ENGINE")
        return {"items": rt.evaluation.assessments(engine, limit), "mode": "SHADOW"}

    @app.get("/api/v1/eval/report")
    def eval_report():
        return rt.evaluation.report()

    @app.get("/api/v1/eval/exposure")
    def eval_exposure():
        return rt.evaluation.exposure()
