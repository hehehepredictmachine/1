"""API routes: strefy.

register(app, ctx): mapa stref i „Strefy rynkowe” 1.28
    (10 routes; create_app before the split, 7ba7ab0: lines 1887-1978)

The handlers are the ones create_app defined before the split (Etap 4 krok B, docs/arch146/ETAP2_PROJEKT.md §3 / §5):
same function names, signatures, decorators, Pydantic models, error codes and body - the block of create_app is copied
verbatim, the only edit is one more dot in a relative import (the package is one level deeper). The create_app locals the
block used (rt, helpers, handlers called by name) are bound from ctx at the top of the function under the same names;
registration order: api/routes/__init__.REGISTRATION.
"""
from __future__ import annotations

from fastapi import HTTPException, Query

from ..schemas import MarketZonesLiveReq, MarketZonesReq


def register(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 1887-1978: 10 routes."""
    rt = ctx.rt

    @app.get("/api/v1/zones/map")
    def zones_map(tf: str = Query("ALL"), as_of: str | None = Query(None), full: bool = Query(False)):
        if tf not in ("ALL", "M5", "M15"):
            raise HTTPException(400, "INVALID_TF")
        from ...zones.series import ts as _ts
        if as_of:
            try:
                t = _ts(as_of)
            except ValueError as exc:
                raise HTTPException(400, "INVALID_AS_OF") from exc
            zm = rt.zones.at(t)
        else:
            zm = rt.zones.current_or_refresh()
        if zm is None:
            return {"status": "NO_MAP", "reason": rt.zones.state.get("last_error")}
        return zm if full else rt.zones.chart_view(zm, tf)

    # ---------------------------------------------------------------- 1.28 "Strefy rynkowe" (M1/M5/M15/M30, analytical only)
    def _mz_tfs(tfs):
        from ...zones.market import TFS as _MZTFS
        bad = [t for t in (tfs or []) if t not in _MZTFS]
        if bad:
            raise HTTPException(400, f"INVALID_TF:{','.join(bad)}")
        return tfs

    @app.get("/api/v1/market-zones")
    def market_zones(instrument: str = Query("XAUUSD"), all: bool = Query(False)):
        try:
            return rt.market_zones.view(instrument, all_zones=all)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/v1/market-zones/compute")
    def market_zones_compute(req: MarketZonesReq):
        try:
            return rt.market_zones.request(req.instrument, _mz_tfs(req.timeframes), reason="manual")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/v1/market-zones/live")
    def market_zones_live(req: MarketZonesLiveReq):
        try:
            return rt.market_zones.set_live(req.instrument, req.enabled, _mz_tfs(req.timeframes))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/v1/market-zones/stop")
    def market_zones_stop(req: MarketZonesReq):
        return rt.market_zones.stop(req.instrument)

    @app.get("/api/v1/market-zones/job/{job_id}")
    def market_zones_job(job_id: str):
        j = rt.market_zones.job(job_id)
        if j is None:
            raise HTTPException(404, "JOB_NOT_FOUND")
        return j

    @app.get("/api/v1/market-zones/zone/{zone_id}")
    def market_zones_zone(zone_id: str, instrument: str = Query("XAUUSD")):
        d = rt.market_zones.zone(instrument, zone_id)
        if d is None:
            raise HTTPException(404, "ZONE_NOT_FOUND")
        return d

    @app.get("/api/v1/market-zones/events")
    def market_zones_events(instrument: str = Query("XAUUSD"), limit: int = Query(200, ge=1, le=2000)):
        return {"items": rt.market_zones.events(instrument, limit)}

    @app.get("/api/v1/market-zones/bars")
    def market_zones_bars(instrument: str = Query("XAUUSD"), tf: str = Query("M5"), count: int = Query(300, ge=30, le=1500)):
        _mz_tfs([tf])
        sym = rt.market_zones.symbol_for(instrument.upper())
        if not sym:
            return {"status": "NO_SYMBOL", "bars": [], "reason": f"brak symbolu brokera dla {instrument}"}
        try:
            rows = rt.bridge.symbol_bars(sym, tf, count)
        except Exception as exc:  # noqa: BLE001 - disconnected terminal: the panel keeps the last drawing marked stale
            return {"status": "ERROR", "bars": [], "reason": f"{type(exc).__name__}: {exc}"[:200]}
        return {"status": "OK", "symbol": sym, "tf": tf, "bars": [{k: b.get(k) for k in ("open_utc", "o", "h", "l", "c", "tv", "spread", "closed")}
                                                                   for b in rows if b.get("open_utc")]}

    @app.get("/api/v1/market-zones/as-of")
    def market_zones_as_of(as_of: str, instrument: str = Query("XAUUSD"), tf: str | None = Query(None)):
        from ...zones.series import ts as _ts
        try:
            t = _ts(as_of)
        except ValueError as exc:
            raise HTTPException(400, "INVALID_AS_OF") from exc
        try:
            return rt.market_zones.at(instrument, t, _mz_tfs([tf]) if tf else None)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(503, f"{type(exc).__name__}: {exc}"[:200]) from exc
