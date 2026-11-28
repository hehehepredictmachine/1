"""API routes: eksport historii MT5.

register(app, ctx): eksport historii MT5 do treningu
    (5 routes; create_app before the split, 7ba7ab0: lines 3408-3444)

The handlers are the ones create_app defined before the split (Etap 4 krok B, docs/arch146/ETAP2_PROJEKT.md §3 / §5):
same function names, signatures, decorators, Pydantic models, error codes and body - the block of create_app is copied
verbatim, the only edit is one more dot in a relative import (the package is one level deeper). The create_app locals the
block used (rt, helpers, handlers called by name) are bound from ctx at the top of the function under the same names;
registration order: api/routes/__init__.REGISTRATION.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, Query

from ... import paths
from ...config import ALLOWED_ASSETS


def register(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 3408-3444: 5 routes."""
    rt = ctx.rt

    # ------------------------------------------------------------ 1.25 export of MT5 history for training (own process, read only)
    def _default_symbol(inst: str):
        c = rt.cfg.get()
        m = c.assets.mappings.get(inst)
        return m.broker_symbol if m and m.broker_symbol else (c.mt5.symbol if inst == "XAUUSD" else None)

    @app.post("/api/v1/export/start")
    def export_start(body: dict):
        from ...training import export_job as EJ
        try:
            return EJ.start(body, demo=rt.demo, default_symbol=_default_symbol)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.get("/api/v1/export/status")
    def export_status():
        from ...training import export_job as EJ
        return EJ.status()

    @app.post("/api/v1/export/cancel")
    def export_cancel():
        from ...training import export_job as EJ
        return EJ.cancel()

    @app.get("/api/v1/export/datasets")
    def export_datasets(instrument: str = Query(...)):
        from ...training import export_job as EJ
        if instrument not in ALLOWED_ASSETS:
            raise HTTPException(400, "UNKNOWN_INSTRUMENT")
        return {"instrument": instrument, "datasets": EJ.datasets(instrument), "default_symbol": _default_symbol(instrument)}

    @app.get("/api/v1/export/readiness")
    def export_readiness(dataset: str = Query(...)):
        from ...training import requirements as RQ
        d = Path(dataset).resolve()
        if paths.data_dir().resolve() not in d.parents:
            raise HTTPException(400, "BAD_DIR")
        return RQ.check_dataset(d)
