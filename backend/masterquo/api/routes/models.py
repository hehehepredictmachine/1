"""API routes: katalog modeli.

register(app, ctx): katalog modeli, predykcje, dowody
    (3 routes; create_app before the split, 7ba7ab0: lines 2187-2209)

The handlers are the ones create_app defined before the split (Etap 4 krok B, docs/arch146/ETAP2_PROJEKT.md §3 / §5):
same function names, signatures, decorators, Pydantic models, error codes and body - the block of create_app is copied
verbatim, the only edit is one more dot in a relative import (the package is one level deeper). The create_app locals the
block used (rt, helpers, handlers called by name) are bound from ctx at the top of the function under the same names;
registration order: api/routes/__init__.REGISTRATION.
"""
from __future__ import annotations

from fastapi import HTTPException, Query


def register(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 2187-2209: 3 routes."""
    rt = ctx.rt
    _th_inst = ctx._th_inst

    @app.get("/api/v1/models/catalog")
    def models_catalog(instrument: str = Query("XAUUSD")):
        from ...modelhub import catalog as _CAT
        return _CAT.build(rt, _th_inst(instrument))

    @app.get("/api/v1/models/predictions")
    def models_predictions(instrument: str = Query("XAUUSD")):
        from ...modelhub import adapters as _AD
        from ...quant import ids as _I
        i = _th_inst(instrument)
        # 1.46 arch (I0009): + canonical_id (additive) on a COPY of each record - the cached dicts are shared with SH / Quant / the coordinator
        return {"instrument": i, "items": [{**p, "canonical_id": _I.canonical(p)} for p in _AD.all_predictions(rt, i)], "contract": "PMW-PRED-1"}

    @app.get("/api/v1/models/evidence")
    def models_evidence(instrument: str = Query("XAUUSD"), strategy: str = Query("SCALPING")):
        """Diagnostic view (no consumer in the panels): evidence groups per correlation group of modelhub.aggregate.ROUTES (per TF); the
        SH matrix shows the Training Center models as the summary row th_direction with these groups in group_by_tf (w2 I0006)."""
        from ...modelhub import aggregate as _AG
        i = _th_inst(instrument)
        if strategy not in ("SCALPING", "HEDGING"):
            raise HTTPException(400, "INVALID_STRATEGY")
        from ...modelhub import adapters as _AD
        return _AG.evidence(_AD.all_predictions(rt, i), strategy, i)
