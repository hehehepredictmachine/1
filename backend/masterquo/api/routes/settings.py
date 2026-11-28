"""API routes: konfiguracja i sekrety.

register(app, ctx): konfiguracja i sekrety
    (4 routes; create_app before the split, 7ba7ab0: lines 1623-1689)

The handlers are the ones create_app defined before the split (Etap 4 krok B, docs/arch146/ETAP2_PROJEKT.md §3 / §5):
same function names, signatures, decorators, Pydantic models, error codes and body - the block of create_app is copied
verbatim, the only edit is one more dot in a relative import (the package is one level deeper). The create_app locals the
block used (rt, helpers, handlers called by name) are bound from ctx at the top of the function under the same names;
registration order: api/routes/__init__.REGISTRATION.
"""
from __future__ import annotations

import json

from fastapi import Body, HTTPException

from ...secrets_store import ALLOWED as _SECRETS_ALLOWED
from ...secrets_store import UI_SETTABLE as _SECRETS_UI_SETTABLE
from ...timeutil import iso, utcnow
from ..schemas import KeyReq, SecretReq


def register(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 1623-1689: 4 routes."""
    rt = ctx.rt

    @app.get("/api/v1/config")
    def get_config():
        c = rt.cfg.get().model_dump(mode="json")
        return {"config": c, "secrets": {n: {"source": rt.secrets.source(n), "masked": rt.secrets.mask(n)}
                                         for n in _SECRETS_ALLOWED},          # 1.46 arch (I0118): every stored secret (masked only)
                "editable_note": "Klucze API są przechowywane lokalnie (Windows DPAPI) i nigdy nie są zwracane przez API."}

    @app.put("/api/v1/config")
    def put_config(patch: dict = Body(...)):
        patch.pop("server", None)
        # 1.14: asset mapping / active asset / Execution Lock change only through their dedicated, checked endpoints
        patch.pop("assets", None)
        m5 = patch.get("mt5") or {}
        if not isinstance(m5, dict):
            raise HTTPException(400, "INVALID_CONFIG: mt5")      # 1.46: a non-object mt5 section was an AttributeError (.pop) -> 500
        m5.pop("analytical_alias", None)
        active = rt.cfg.get().assets.active
        cur_map = rt.cfg.get().assets.mappings.get(active)
        # 1.46: the settings dialog always sends the whole mt5 section back - an UNCHANGED symbol downgraded a CONFIRMED mapping to
        # USER_SPECIFIED on every save (risk limits, Telegram...), which silently switched off the CONTRACT_SPEC_CHANGED check. Only a
        # new symbol (or one typed over an unmapped / proposed entry) becomes the user's mapping now.
        unchanged = cur_map is not None and cur_map.broker_symbol == m5.get("symbol") and cur_map.status in ("CONFIRMED", "USER_SPECIFIED",
                                                                                                             "AUTO_DETECTED")
        if m5.get("symbol") and not unchanged:     # symbol typed in Ustawienia -> becomes the active asset's broker symbol
            patch.setdefault("assets", {})["mappings"] = {active: {"broker_symbol": m5["symbol"], "status": "USER_SPECIFIED"}}
        ex_patch = patch.get("execution")
        if isinstance(ex_patch, dict):
            # the execution mode and its account binding change only through POST /api/v1/mode (account confirmation) -
            # never through a generic config write, so automatic orders cannot be switched on silently. Values equal to the
            # current ones (a settings form sending the section back unchanged) are dropped; a different value is refused.
            cur_ex = rt.cfg.get().execution
            for k in ("mode", "bound_account", "mode_note"):
                if k in ex_patch:
                    if ex_patch[k] != getattr(cur_ex, k, None):
                        raise HTTPException(400, "USE_MODE_ENDPOINT")
                    ex_patch.pop(k)
        try:
            old = rt.cfg.get()
            new = rt.cfg.update(patch)
        except Exception as exc:
            raise HTTPException(400, f"INVALID_CONFIG: {exc}") from exc
        rt.db.execute("INSERT INTO settings_audit(ts, change_json) VALUES (?,?)", (iso(utcnow()), json.dumps({"config_patch": patch}, default=str)))
        rt.log.info("CONFIG", "UPDATED", "Zmieniono konfigurację: " + ", ".join(sorted(patch.keys())))
        if (old.mt5.symbol, old.mt5.terminal_path, old.mt5.dxy_symbol) != (new.mt5.symbol, new.mt5.terminal_path, new.mt5.dxy_symbol):
            rt.modes.reset("MT5_CONFIG_CHANGED")
            rt.bridge.request_reconnect("MT5_CONFIG_CHANGED")
        if old.risk != new.risk:
            rt.log.info("CONFIG", "RISK_LIMITS_CHANGED", "Zmieniono limity ryzyka – obowiązują od następnej decyzji.")
        rt.engine.mark_dirty()
        return get_config()

    @app.post("/api/v1/secrets/anthropic")
    def set_key(req: KeyReq):
        rt.secrets.set("ANTHROPIC_API_KEY", req.api_key)
        rt.log.info("AGENT", "KEY_SET", "Zapisano lokalnie klucz Anthropic (wartość nie jest logowana).")
        return {"ok": True, "masked": rt.secrets.mask("ANTHROPIC_API_KEY")}

    @app.post("/api/v1/secrets")
    def set_secret(req: SecretReq):
        if req.name not in _SECRETS_UI_SETTABLE:          # 1.46 arch (I0118): the same 4 names as before (one source)
            raise HTTPException(400, "UNKNOWN_SECRET")
        rt.secrets.set(req.name, req.value)
        if req.name == "MT5_PASSWORD":                 # new password: try to connect again (value never logged)
            rt.log.info("MT5", "PASSWORD_SET", "Zapisano lokalnie hasło MT5 (wartość nie jest logowana).")
            if rt.bridge.state != "CONNECTED":
                rt.bridge.retry_now()                  # 1.46 arch (I0089): was a direct write of bridge.next_retry
        return {"ok": True, "source": rt.secrets.source(req.name)}

    ctx.get_config = get_config
    ctx.put_config = put_config
