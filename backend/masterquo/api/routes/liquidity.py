"""API routes: płynność.

register(app, ctx): Session Sweep Boxes + Liquidation Heatmap
    (6 routes; create_app before the split, 7ba7ab0: lines 3572-3635)

The handlers are the ones create_app defined before the split (Etap 4 krok B, docs/arch146/ETAP2_PROJEKT.md §3 / §5):
same function names, signatures, decorators, Pydantic models, error codes and body - the block of create_app is copied
verbatim, the only edit is one more dot in a relative import (the package is one level deeper). The create_app locals the
block used (rt, helpers, handlers called by name) are bound from ctx at the top of the function under the same names;
registration order: api/routes/__init__.REGISTRATION.
"""
from __future__ import annotations

from fastapi import Body, HTTPException, Query


def register(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 3572-3635: 6 routes."""
    rt = ctx.rt
    _asset = ctx._asset

    # ------------------------------------------------------------ PMW-UPD-06 Session Sweep Boxes + Liquidation Heatmap
    @app.get("/api/v1/liquidity/sessions")
    def liq_sessions(tf: str = Query("M5"), profile: str | None = Query(None), days: int = Query(2, ge=0, le=5)):
        from ...analytics import session_engine as se
        if profile is not None and profile not in se.PROFILES:
            raise HTTPException(400, "UNKNOWN_PROFILE")
        if tf not in ("M1", "M5", "M15", "M30", "H1"):
            raise HTTPException(400, "UNKNOWN_TF")
        cfg = rt.cfg.get()
        base = cfg.liquidity.sessions_base_tf                          # geometry from ONE base TF; the chart TF only changes presentation
        bars = [b for b in rt.bridge.bars(base, 3000 if base == "M1" else 1000, include_forming=False) if b.get("open_utc")]
        r = rt.liquidity.sessions(bars, 60 if base == "M1" else 300, cfg.assets.active, None, profile, days)
        return dict(r, asset=cfg.assets.active, view_tf=tf, base_tf=base, session_epoch=str(getattr(rt.bridge, "session_epoch", None)),
                    history_from=bars[0]["open_utc"] if bars else None)

    @app.get("/api/v1/liquidity/heatmap")
    def liq_heatmap(asset: str | None = Query(None), as_of: str | None = Query(None), max_cells: int = Query(20000, ge=0, le=100000)):
        return rt.liquidity.heatmap_public(_asset(asset), as_of, max_cells)

    @app.get("/api/v1/liquidity/context")
    def liq_context(setup_side: str | None = Query(None)):
        from ...analytics import liquidity_context as lc
        cfg = rt.cfg.get()
        a = cfg.assets.active
        base = cfg.liquidity.sessions_base_tf
        bars = [b for b in rt.bridge.bars(base, 3000 if base == "M1" else 1000, include_forming=False) if b.get("open_utc")]
        sess = rt.liquidity.sessions(bars, 60 if base == "M1" else 300, a)
        hm = rt.liquidity.heatmap_public(a, None, 0)
        hm.pop("grid", None)
        m5 = [b for b in rt.bridge.bars("M5", 60, include_forming=False) if b.get("open_utc")]
        a5 = (sum(x["h"] - x["l"] for x in m5[-14:]) / 14) if len(m5) >= 14 else None
        return dict(lc.evaluate(boxes=sess["boxes"], heatmap=hm, price=m5[-1]["c"] if m5 else None, atr_m5=a5,
                                setup={"side": setup_side} if setup_side in ("BUY", "SELL") else None), asset=a, rules=lc.RULES)

    @app.put("/api/v1/liquidity/source")
    def liq_source(body: dict = Body(default={})):
        a = _asset(body.get("asset"))
        cur = rt.cfg.get().liquidity.sources.get(a)
        patch = {k: body[k] for k in ("enabled", "variant", "source_symbol", "exchange", "range", "contract_type") if k in body}
        if "mapping" in body and body["mapping"] != "UNMAPPED":
            raise HTTPException(400, "MAPPING_REQUIRES_VALIDATED_BASIS_ADAPTER")
        try:
            merged = dict(cur.model_dump() if cur else {}, **patch)
            rt.cfg.update({"liquidity": {"sources": {a: merged}}})
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, str(exc)[:300]) from None
        return {"ok": True, "source": rt.cfg.get().liquidity.sources[a].model_dump()}

    @app.put("/api/v1/liquidity/key")
    def liq_key(body: dict = Body(default={})):
        key = body.get("key")
        if key is not None and not isinstance(key, str):
            raise HTTPException(400, "INVALID_KEY")          # 1.46: a non-text key was an AttributeError (.strip) -> 500
        rt.secrets.set("COINGLASS_API_KEY", (key or "").strip() or None)
        return {"ok": True, "key_status": rt.secrets.source("COINGLASS_API_KEY")}          # the key itself is never returned

    @app.post("/api/v1/liquidity/poll")
    def liq_poll():
        # 1.46: the forced poll passed a clock 1e9 s ahead, which poll_once also stored as the base of the NEXT due time - the background
        # loop never polled that source again until a restart (the heatmap silently stopped). Now: every source is due now (manual =
        # forced, as before) and the next time is counted from the real clock.
        nxt = getattr(rt.liquidity, "_next", None)
        if isinstance(nxt, dict):
            nxt.clear()
        return {"polled": rt.liquidity.poll_once(), "imported": rt.liquidity.scan_inbox()}
