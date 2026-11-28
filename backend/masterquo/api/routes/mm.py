"""API routes: master models.

register_status(app, ctx): master models - status
    (1 routes; create_app before the split, 7ba7ab0: lines 1880-1885)
register_live(app, ctx): master models - widok SHADOW, zadanie, ledger, rollback
    (4 routes; create_app before the split, 7ba7ab0: lines 3143-3178)

The handlers are the ones create_app defined before the split (Etap 4 krok B, docs/arch146/ETAP2_PROJEKT.md §3 / §5):
same function names, signatures, decorators, Pydantic models, error codes and body - the block of create_app is copied
verbatim, the only edit is one more dot in a relative import (the package is one level deeper). The create_app locals the
block used (rt, helpers, handlers called by name) are bound from ctx at the top of the function under the same names;
registration order: api/routes/__init__.REGISTRATION.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import Body, HTTPException, Query

from .. import deps as _deps


def register_status(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 1880-1885: 1 routes."""
    rt = ctx.rt

    # ---------------------------------------------------------------- PMW-MM master models (inventory, SHADOW live view, ledger, rollback)
    def _mm_inst(instrument: str) -> str:
        return _deps.instrument(instrument, error_code="UNKNOWN_INSTRUMENT")      # 1.46 arch (I0087): as given (no upper), as before

    @app.get("/api/v1/mm/status")
    def mm_status(instrument: str = Query("XAUUSD")):
        return rt.mm.status(_mm_inst(instrument))

    ctx._mm_inst = _mm_inst


def register_live(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 3143-3178: 4 routes."""
    rt = ctx.rt
    _mm_inst = ctx._mm_inst

    @app.get("/api/v1/mm/live")
    def mm_live(instrument: str = Query("XAUUSD")):
        return rt.mm.live(_mm_inst(instrument))

    @app.get("/api/v1/mm/job")
    def mm_job(instrument: str = Query("XAUUSD"), job: str = Query(...)):
        from ...mm import inventory as mi
        from ...mm.orchestrator import GRAPH
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
        led = rt.mm.ledger(_mm_inst(instrument))
        lim = min(max(limit, 1), 2000)
        # 1.46: the NEWEST `limit` predictions (the oldest came back and the fresh SHADOW predictions never appeared), in time order.
        # 1.46 arch (I0089): through Ledger.rows(newest=True) - the same query and JSON decoding under the ledger's own lock (was inline
        # here on led._lock / led.c)
        rows = led.rows(model, limit=lim, newest=True)
        return {"summary": led.summary(), "rows": rows}

    @app.post("/api/v1/mm/rollback")
    def mm_rollback(body: dict = Body(...)):
        from ...mm import artifacts as ma
        try:
            return {"ok": True, "pointer": ma.rollback(_mm_inst(body.get("instrument", "")), str(body.get("model", "")))}
        except ma.ArtifactError as exc:
            return {"ok": False, "reason": str(exc)}
