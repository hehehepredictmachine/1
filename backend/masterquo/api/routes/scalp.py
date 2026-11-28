"""API routes: scalp.

register(app, ctx): profil scalp (SHADOW)
    (1 routes; create_app before the split, 7ba7ab0: lines 1147-1151)
register_dashboard(app, ctx): Multi TimeFrame Scalping Dashboard
    (4 routes; create_app before the split, 7ba7ab0: lines 3638-3671)

The handlers are the ones create_app defined before the split (Etap 4 krok B, docs/arch146/ETAP2_PROJEKT.md §3 / §5):
same function names, signatures, decorators, Pydantic models, error codes and body - the block of create_app is copied
verbatim, the only edit is one more dot in a relative import (the package is one level deeper). The create_app locals the
block used (rt, helpers, handlers called by name) are bound from ctx at the top of the function under the same names;
registration order: api/routes/__init__.REGISTRATION.
"""
from __future__ import annotations

from fastapi import HTTPException, Query
from fastapi.responses import JSONResponse


def register(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 1147-1151: 1 routes."""
    rt = ctx.rt

    @app.get("/api/v1/scalp")
    def scalp_get():
        """Scalp profile (M5 Range -> M1 Sweep/Reclaim -> Retest) + hedge controller in SHADOW: MTF, setup, indicators, adapters,
        forecasts, hedge/risk, training and the separate validity statuses. Never an order permission."""
        return {**rt.scalp.public(), "config": rt.cfg.get().scalp.model_dump(), "profile": rt.scalp.prof, "registry": rt.scalp.registry()}


def register_dashboard(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 3638-3671: 4 routes."""
    rt = ctx.rt
    _asset = ctx._asset

    # ------------------------------------------------------------ PMW-UPD-05 Multi TimeFrame Scalping Dashboard
    @app.get("/api/v1/scalp/dashboard")
    def mtf_dashboard(asset: str | None = Query(None), snapshot_id: str | None = Query(None)):
        a = _asset(asset) if asset else rt.cfg.get().assets.active
        if a != rt.scalp.inst:
            return {"asset": a, "status": "ASSET_NOT_ACTIVE", "snapshot": None, "health": None}
        import mq_instruments
        if a not in mq_instruments.profiles():
            return {"asset": a, "status": "UNSUPPORTED_STRATEGY_PROFILE", "snapshot": None, "health": rt.mtf.health}
        snap = rt.mtf.get(snapshot_id)
        if snapshot_id and snap is None:
            return {"asset": a, "status": "ARCHIVE_SNAPSHOT_UNAVAILABLE", "snapshot_id": snapshot_id, "snapshot": None, "health": rt.mtf.health}
        if snap is not None and snap.get("asset") != a:
            snap = None
        return {"asset": a, "status": "OK" if snap else "NO_SNAPSHOT", "snapshot": snap, "health": rt.mtf.health or rt.mtf.heartbeat(),
                "scalp_status": rt.scalp.state.get("status"), "scalp_reason": rt.scalp.state.get("reason")}

    @app.get("/api/v1/scalp/dashboard/chart")
    def mtf_chart(tf: str = Query(...), snapshot_id: str = Query(...), bars: int = Query(400, ge=50, le=600)):
        r = rt.mtf.chart(tf, snapshot_id, bars)
        if r.get("status") == "SNAPSHOT_EXPIRED":
            return JSONResponse(r, status_code=410)
        return r

    @app.get("/api/v1/scalp/dashboard/snapshots")
    def mtf_snapshots(setup_id: str | None = Query(None), cursor: str | None = Query(None), limit: int = Query(50, ge=1, le=200)):
        rows = rt.mtf.snapshots(setup_id, limit, cursor)
        return {"asset": rt.scalp.inst, "rows": rows, "next_cursor": rows[-1]["computed_at"] if len(rows) == limit else None}

    @app.get("/api/v1/scalp/dashboard/snapshots/{sid}")
    def mtf_snapshot(sid: str):
        snap = rt.mtf.get(sid)
        if snap is None:
            raise HTTPException(404, "ARCHIVE_SNAPSHOT_UNAVAILABLE")
        return snap
