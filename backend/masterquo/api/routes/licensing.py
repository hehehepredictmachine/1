"""API routes: licencja.

register(app, ctx): licencja (status / aktywacja / sprawdzenie) + trasy właściciela w edycji OWNER
    (3 routes; create_app before the split, 7ba7ab0: lines 3341-3365)

The handlers are the ones create_app defined before the split (Etap 4 krok B, docs/arch146/ETAP2_PROJEKT.md §3 / §5):
same function names, signatures, decorators, Pydantic models, error codes and body - the block of create_app is copied
verbatim, the only edit is one more dot in a relative import (the package is one level deeper). The create_app locals the
block used (rt, helpers, handlers called by name) are bound from ctx at the top of the function under the same names;
registration order: api/routes/__init__.REGISTRATION.
"""
from __future__ import annotations

from fastapi import Body, HTTPException, Query
from fastapi.responses import JSONResponse

from ...licensing.gate import LicenseRequired


def register(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 3341-3365: 3 routes."""
    rt = ctx.rt

    # ------------------------------------------------------------ 1.42.10 Centrum Treningowe Pepe (PMW-TCP-1): jeden widok + kolejka 1 naraz
    # ---------------------------------------------------------------- 1.44.0 LICENCJA
    # Wersja właściciela: generator licencji (api/owner_routes.py – plik NIE wchodzi do paczki klienta).
    # Wersja klienta: status / aktywacja / sprawdzenie przed trybem; reszta API zablokowana w Guard do aktywacji.
    if rt.license.edition == "OWNER":
        from ..owner_routes import register as _register_owner_routes
        _register_owner_routes(app)

    def _lic_payload(st: dict) -> dict:
        return {k: v for k, v in st.items() if k not in ("detail",)}

    @app.get("/api/v1/license/status")
    def license_status(refresh: int = Query(0)):
        return _lic_payload(rt.license.evaluate(refresh_net=True) if refresh else rt.license.state())

    @app.post("/api/v1/license/activate")
    def license_activate(body: dict = Body(default={})):
        key = str(body.get("key") or "")
        if len(key) > 4000:
            raise HTTPException(400, "Klucz jest za długi – to nie jest klucz Apollo23.")
        return _lic_payload(rt.license.activate(key))

    @app.post("/api/v1/license/require")
    def license_require(body: dict = Body(default={})):
        """Przed uruchomieniem trybu (FOREX / CRYPTO; OTC wycofane): 200 albo 402 z powodem."""
        try:
            return _lic_payload(rt.license.require(str(body.get("action") or "")))
        except LicenseRequired as exc:
            return JSONResponse({"error": "LICENSE_REQUIRED", **_lic_payload(exc.state)}, status_code=402)
