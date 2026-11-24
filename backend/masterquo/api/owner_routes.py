"""GENERATOR LICENCJI – endpointy wersji WŁAŚCICIELA (1.43.0; w osobnym pliku od 1.44.0).
Plik NIE wchodzi do paczki klienta (tools/build_release.py: OWNER_ONLY). Rejestrowane w api/app.py tylko w edycji OWNER.
Klucz prywatny w %APPDATA%\\PepeMarketWizard\\owner (poza programem). Serwer słucha tylko na 127.0.0.1; zmiany i eksport klucza wyłącznie
POST/DELETE z tokenem CSRF (Guard w api/app.py)."""
from __future__ import annotations

from fastapi import Body, FastAPI, HTTPException


def register(app: FastAPI) -> None:
    from ..licensing.owner import LicenseInputError, OwnerLicenses
    lic = OwnerLicenses()

    def _lic(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except LicenseInputError as exc:
            raise HTTPException(400, f"{exc.field}: {exc.message}") from None
        except RuntimeError as exc:                                  # brak PyNaCl
            raise HTTPException(503, f"crypto: {exc}"[:300]) from None

    @app.get("/api/v1/owner/license/state")
    def owner_license_state():
        return lic.state()

    @app.post("/api/v1/owner/license/keys")
    def owner_license_create_keys():
        return _lic(lic.create_keypair)

    @app.post("/api/v1/owner/license/keys/export")
    def owner_license_export_key():
        return _lic(lic.export_key)

    @app.post("/api/v1/owner/license/keys/import")
    def owner_license_import_key(body: dict = Body(default={})):
        if len(str(body.get("content") or "")) > 20000:
            raise HTTPException(400, "key_file: plik za duży – to nie jest kopia klucza Apollo23")
        return _lic(lic.import_key, str(body.get("content") or ""), bool(body.get("replace")))

    @app.get("/api/v1/owner/license/hwid")
    def owner_license_hwid():
        return lic.this_hwid()

    @app.post("/api/v1/owner/license/generate")
    def owner_license_generate(body: dict = Body(default={})):
        v = body.get("validity")
        hw = body.get("hwid")
        # 1.46: a non-text HWID (e.g. a number) reached generate() and its error message ((hwid or "").strip()) -> AttributeError -> 500
        return _lic(lic.generate, str(body.get("user") or ""), None if hw is None else str(hw), bool(body.get("no_hwid")),
                    v if isinstance(v, dict) else None, str(body.get("note") or ""))

    @app.post("/api/v1/owner/license/check")
    def owner_license_check(body: dict = Body(default={})):
        key = str(body.get("key") or "")
        if len(key) > 4000:
            raise HTTPException(400, "key: klucz za długi")
        return _lic(lic.check, key)

    @app.get("/api/v1/owner/licenses")
    def owner_licenses():
        return {"licenses": _lic(lic.list)}

    @app.delete("/api/v1/owner/licenses/{rid}")
    def owner_license_delete(rid: int):
        return _lic(lic.delete, rid)
