"""API routes: koszyki.

register(app, ctx): profile rynków + koszyki (OTC wycofane)
    (12 routes; create_app before the split, 7ba7ab0: lines 2897-2967)

The handlers are the ones create_app defined before the split (Etap 4 krok B, docs/arch146/ETAP2_PROJEKT.md §3 / §5):
same function names, signatures, decorators, Pydantic models, error codes and body - the block of create_app is copied
verbatim, the only edit is one more dot in a relative import (the package is one level deeper). The create_app locals the
block used (rt, helpers, handlers called by name) are bound from ctx at the top of the function under the same names;
registration order: api/routes/__init__.REGISTRATION.
"""
from __future__ import annotations

from fastapi import Body, HTTPException
from fastapi.responses import JSONResponse


def register(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 2897-2967: 12 routes."""
    rt = ctx.rt

    # ---- 1.41 market profiles + baskets (active catalog since TASK 020: 6 baskets / 60 strategies / 2 profiles; OTC retired) - signals,
    # plans, manual tickets - no orders
    def _baskets():
        b = getattr(rt, "baskets", None)
        if b is None:
            raise HTTPException(503, "koszyki niedostępne (błąd startu – patrz logs/engine_console.log)")
        return b

    @app.get("/api/v1/baskets")
    def baskets_list(basket: str | None = None):
        b = _baskets()
        return {"status": b.status(), "baskets": b.basket_view(basket)}

    @app.get("/api/v1/baskets/catalog")
    def baskets_catalog():
        from ...baskets import catalog as _BC
        return _BC.manifest()

    @app.get("/api/v1/baskets/settings")
    def baskets_settings():
        return _baskets().settings()

    @app.put("/api/v1/baskets/settings")
    def baskets_settings_put(body: dict = Body(...)):
        try:
            return _baskets().update_settings(body)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.get("/api/v1/baskets/signals")
    def baskets_signals(basket: str | None = None, limit: int = 100):
        return {"signals": _baskets().ledger.recent(basket, min(500, max(1, limit)))}

    @app.get("/api/v1/baskets/declared/{profile}")
    def baskets_declared(profile: str):
        return {"items": _baskets().ledger.declared(profile)}

    @app.post("/api/v1/baskets/declared/{profile}")
    def baskets_declare(profile: str, body: dict = Body(...)):
        if profile == "OTC_GOLD_POCKETOPTION":
            return JSONResponse(_OTC_RETIRED, status_code=410)
        if profile != "CRYPTO_FOMO_PERPS":
            raise HTTPException(400, "deklaracja ekspozycji tylko dla FOMO (FOREX: pozycje z terminala; OTC wycofane)")
        need = ("instrument", "side", "size")       # 1.46: the OTC field branch was unreachable since OTC was retired (410 above)
        miss = [k for k in need if body.get(k) in (None, "")]
        if miss:
            raise HTTPException(400, f"brak pól: {miss}")
        return {"id": _baskets().ledger.declare(profile, str(body.get("kind") or "PERP"), body)}

    @app.delete("/api/v1/baskets/declared/{item_id}")
    def baskets_undeclare(item_id: str):
        _baskets().ledger.close_declared(item_id)
        return {"ok": True}

    _OTC_RETIRED = {"error": "RETIRED_PROFILE", "profile_id": "OTC_GOLD_POCKETOPTION",
                    "message": "Strategie OTC zostały wycofane (Apollo23, TASK 020). Historia zostaje tylko do odczytu."}

    @app.get("/api/v1/baskets/otc")
    def baskets_otc():
        """TASK 020: retired - read-only legacy status (no scanning, no polling); stored OTC history is untouched on disk."""
        return {**_OTC_RETIRED, "state": "RETIRED", "history": "READ_ONLY", "legacy_history_provider": {"enabled": False}}

    @app.put("/api/v1/baskets/otc/meta")
    def baskets_otc_meta(body: dict = Body(...)):
        return JSONResponse(_OTC_RETIRED, status_code=410)

    @app.post("/api/v1/baskets/otc/ticks")
    def baskets_otc_ticks(body: dict = Body(...)):
        return JSONResponse(_OTC_RETIRED, status_code=410)

    @app.post("/api/v1/baskets/otc/payoff")
    def baskets_otc_payoff(body: dict = Body(...)):
        return JSONResponse(_OTC_RETIRED, status_code=410)
