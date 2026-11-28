"""API routes: wskaźniki.

register(app, ctx): wskaźniki PMW-IND-1
    (9 routes; create_app before the split, 7ba7ab0: lines 2496-2552)

The handlers are the ones create_app defined before the split (Etap 4 krok B, docs/arch146/ETAP2_PROJEKT.md §3 / §5):
same function names, signatures, decorators, Pydantic models, error codes and body - the block of create_app is copied
verbatim, the only edit is one more dot in a relative import (the package is one level deeper). The create_app locals the
block used (rt, helpers, handlers called by name) are bound from ctx at the top of the function under the same names;
registration order: api/routes/__init__.REGISTRATION.
"""
from __future__ import annotations

from fastapi import Body, HTTPException, Query


def register(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 2496-2552: 9 routes."""
    rt = ctx.rt

    # ---------------------------------------------------------------- PMW-IND-1 indicators (1.33) - analytical, read-only
    def _ind_tf(tf):
        t = str(tf or "M5").upper()
        if t not in rt.cfg.get().indicators.avwap_tfs:
            raise HTTPException(400, f"TF_NOT_ENABLED_FOR_AVWAP:{t}")
        return t

    @app.get("/api/v1/indicators/status")
    def indicators_status():
        return rt.indicators.status()

    @app.get("/api/v1/indicators/snapshot")
    def indicators_snapshot(full: bool = Query(False)):
        s = rt.indicators.current_or_refresh()
        if s is None:
            return {"status": "NO_SNAPSHOT", "reason": rt.indicators.state.get("last_error")}
        return s if full else rt.indicators.compact(s)

    @app.post("/api/v1/indicators/refresh")
    def indicators_refresh():
        return rt.indicators.compact(rt.indicators.refresh())

    @app.get("/api/v1/indicators/chart")
    def indicators_chart(tf: str = Query("M5")):
        return rt.indicators.chart(_ind_tf(tf))

    @app.get("/api/v1/indicators/dxy")
    def indicators_dxy():
        s = rt.indicators.current_or_refresh() or {}
        return s.get("dxy") or {"status": "NO_SNAPSHOT"}

    @app.get("/api/v1/indicators/anchors")
    def indicators_anchors(tf: str | None = Query(None)):
        return {"items": rt.indicators.manual_anchors(_ind_tf(tf) if tf else None)}

    @app.post("/api/v1/indicators/anchors")
    def indicators_anchor_add(body: dict = Body(...)):
        tf = _ind_tf(body.get("tf"))
        st = body.get("source_time")
        if not st:
            raise HTTPException(400, "SOURCE_TIME_REQUIRED")
        try:
            from ...indicators import contract as _IC
            _IC.ts(st, strict=True)     # 1.46: naive / out-of-range time -> 400 (the anchor rejects it with strict=True: was a 500)
        except (TypeError, ValueError, OverflowError):
            raise HTTPException(400, "SOURCE_TIME_INVALID") from None
        label = str(body.get("label") or "")[:40] or None
        return rt.indicators.add_manual_anchor(tf, st, label)

    @app.delete("/api/v1/indicators/anchors/{anchor_id}")
    def indicators_anchor_del(anchor_id: str):
        if not rt.indicators.remove_manual_anchor(anchor_id):
            raise HTTPException(404, "ANCHOR_NOT_FOUND")
        return {"ok": True}

    @app.get("/api/v1/indicators/manifest")
    def indicators_manifest():
        return rt.indicators.manifest()
