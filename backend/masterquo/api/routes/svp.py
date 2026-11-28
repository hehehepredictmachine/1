"""API routes: Session Volume Profile.

register(app, ctx): Session Volume Profile + strefy
    (24 routes; create_app before the split, 7ba7ab0: lines 2999-3122)

The handlers are the ones create_app defined before the split (Etap 4 krok B, docs/arch146/ETAP2_PROJEKT.md §3 / §5):
same function names, signatures, decorators, Pydantic models, error codes and body - the block of create_app is copied
verbatim, the only edit is one more dot in a relative import (the package is one level deeper). The create_app locals the
block used (rt, helpers, handlers called by name) are bound from ctx at the top of the function under the same names;
registration order: api/routes/__init__.REGISTRATION.
"""
from __future__ import annotations

from fastapi import Body, HTTPException, Query

from ...timeutil import TIMEFRAMES


def register(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 2999-3122: 24 routes."""
    rt = ctx.rt

    # ---------------------------------------------------------------- PMW-SVP-1 Session Volume Profile + zones (1.33) - analytical
    def _svp(fn, *a, **k):
        try:
            return fn(*a, **k)
        except KeyError as exc:
            raise HTTPException(404, str(exc).strip("'")) from None
        except (ValueError, TypeError) as exc:                         # 1.46: TypeError (lower: null) was a 500
            raise HTTPException(400, str(exc)) from None

    @app.get("/api/v1/svp/status")
    def svp_status():
        return rt.svp.status()

    @app.get("/api/v1/svp/profiles")
    def svp_profiles():
        return {"items": rt.svp.profiles()}

    @app.post("/api/v1/svp/profiles")
    def svp_profile_create(body: dict = Body(...)):
        return _svp(rt.svp.create_profile, body)

    @app.patch("/api/v1/svp/profiles/{pid}")
    def svp_profile_update(pid: str, body: dict = Body(...)):
        return _svp(rt.svp.update_profile, pid, body)

    @app.delete("/api/v1/svp/profiles/{pid}")
    def svp_profile_delete(pid: str):
        if not rt.svp.delete_profile(pid):
            raise HTTPException(404, "PROFILE_NOT_FOUND")
        return {"ok": True}

    @app.post("/api/v1/svp/profiles/{pid}/copy-settings")
    def svp_profile_copy(pid: str, body: dict = Body(...)):
        return _svp(rt.svp.copy_settings, str(body.get("from") or ""), pid)

    @app.get("/api/v1/svp/profiles/{pid}/compute")
    def svp_profile_compute(pid: str):
        return _svp(rt.svp.compute, pid)

    @app.post("/api/v1/svp/profiles/{pid}/freeze")
    def svp_profile_freeze(pid: str):
        return _svp(rt.svp.freeze, pid)

    @app.post("/api/v1/svp/profiles/{pid}/live")
    def svp_profile_live(pid: str, body: dict = Body(...)):
        return _svp(rt.svp.set_live, pid, bool(body.get("on")))

    @app.post("/api/v1/svp/profiles/{pid}/ai-live")
    def svp_profile_ai_live(pid: str, body: dict = Body(...)):
        return _svp(rt.svp.set_ai_live, pid, bool(body.get("on")))

    @app.post("/api/v1/svp/profiles/{pid}/zones-now")
    def svp_zones_now(pid: str):
        return _svp(rt.svp.algo_now, pid)

    @app.post("/api/v1/svp/profiles/{pid}/ai-propose")
    async def svp_ai_propose(pid: str):
        if rt.svp.profile(pid) is None:
            raise HTTPException(404, "PROFILE_NOT_FOUND")
        return await rt.svp.ai_propose(pid)

    @app.get("/api/v1/svp/visible")
    def svp_visible(tf: str = Query("M5"), t0: str = Query(...), t1: str = Query(...), bin_ticks: int = Query(50, ge=1, le=100000),
                    va_pct: float = Query(0.70, gt=0.3, lt=1.0)):
        if tf not in TIMEFRAMES:
            raise HTTPException(400, "TF_INVALID")
        return _svp(rt.svp.visible, tf, t0, t1, bin_ticks=bin_ticks, va_pct=va_pct)

    @app.get("/api/v1/svp/zones")
    def svp_zones(source: str | None = Query(None), profile_id: str | None = Query(None), as_of: str | None = Query(None)):
        if source and source not in ("MANUAL", "ALGORITHM", "AI"):
            raise HTTPException(400, "SOURCE_INVALID")
        from ...svp import engine as _SE
        try:
            t = _SE._ts(as_of) if as_of else None
        except ValueError:
            raise HTTPException(400, "INVALID_AS_OF: ISO-8601 albo sekundy epoki") from None     # 1.46: was an unhandled 500
        return {"items": rt.svp.zones(source=source, profile_id=profile_id, as_of=t)}

    @app.post("/api/v1/svp/zones")
    def svp_zone_create(body: dict = Body(...)):
        return _svp(rt.svp.create_manual, body)

    @app.patch("/api/v1/svp/zones/{zid}")
    def svp_zone_edit(zid: str, body: dict = Body(...)):
        return _svp(rt.svp.edit_zone, zid, body)

    @app.delete("/api/v1/svp/zones/{zid}")
    def svp_zone_delete(zid: str):
        if not rt.svp.delete_zone(zid):
            raise HTTPException(404, "ZONE_NOT_FOUND")
        return {"ok": True}

    @app.get("/api/v1/svp/zones/{zid}/history")
    def svp_zone_history(zid: str):
        return {"items": rt.svp.zone_history(zid)}

    @app.post("/api/v1/svp/clear-auto")
    def svp_clear_auto(body: dict = Body(default={})):
        return {"deactivated": rt.svp.clear_auto(body.get("profile_id"))}

    @app.get("/api/v1/svp/ai-jobs")
    def svp_ai_jobs(limit: int = Query(50, ge=1, le=500)):
        return {"items": rt.svp.ai_jobs(limit)}

    @app.get("/api/v1/zones/status")
    def zones_status():
        return rt.zones.status()

    @app.get("/api/v1/zones/events")
    def zones_events(limit: int = Query(100, ge=1, le=1000)):
        return {"items": rt.zones.events(limit)}

    @app.get("/api/v1/zones/profiles")
    def zones_profiles():
        zm = rt.zones.current_or_refresh()
        if zm is None:
            return {"status": "NO_MAP", "reason": rt.zones.state.get("last_error")}
        return {"profiles": zm.get("profiles"), "context": zm.get("context"), "volume_source": zm.get("volume_source"), "as_of": zm.get("as_of")}

    @app.get("/api/v1/zones/context")
    def zones_context(direction: str = Query(...), entry: float = Query(...), stop: float | None = Query(None), cost: float = Query(0.0)):
        if direction not in ("LONG", "SHORT"):
            raise HTTPException(400, "INVALID_DIRECTION")
        return rt.zones.context_for(direction=direction, entry=entry, stop=stop, cost_price=cost) or {"status": "NO_MAP"}
