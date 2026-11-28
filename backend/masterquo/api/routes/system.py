"""API routes: system i aplikacja desktop.

register_diagnostics(app, ctx): diagnostyka
    (1 routes; create_app before the split, 7ba7ab0: lines 4015-4025)
register(app, ctx): zasoby systemu, presety strategii, aplikacja desktop, zamknięcie
    (9 routes; create_app before the split, 7ba7ab0: lines 4069-4150)

The handlers are the ones create_app defined before the split (Etap 4 krok B, docs/arch146/ETAP2_PROJEKT.md §3 / §5):
same function names, signatures, decorators, Pydantic models, error codes and body - the block of create_app is copied
verbatim, the only edit is one more dot in a relative import (the package is one level deeper). The create_app locals the
block used (rt, helpers, handlers called by name) are bound from ctx at the top of the function under the same names;
registration order: api/routes/__init__.REGISTRATION.
"""
from __future__ import annotations

import asyncio

from fastapi import HTTPException

from ... import desktop, presets, sysres
from ...timeutil import TIMEFRAMES
from ...version import API_CONTRACT_VERSION, APP_VERSION
from ..schemas import DesktopPrefsReq, PresetReq, StrategyModeReq


def register_diagnostics(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 4015-4025: 1 routes."""
    rt = ctx.rt

    @app.get("/api/v1/diagnostics")
    def diagnostics():
        from ...runtime import platform_info
        b = rt.bridge
        raw = {tf: [x["t_raw"] for x in b.bars(tf, limit=4)] for tf in TIMEFRAMES}
        return {"app": {"version": APP_VERSION, "contract": API_CONTRACT_VERSION, "synthetic": rt.demo}, "platform": platform_info(),
                "connection": b.connection_status(), "symbol": b.symbol_status_dict(), "tf_meta": b.tf_meta(),
                "raw_last_bar_opens": raw, "quote": b.quote_status(), "pc_clock": rt.pcclock.snapshot(),
                "worker": {"calls": rt.worker.calls, "failures": rt.worker.failures, "module_error": rt.worker.module_error},
                "db_schema": rt.db.schema_versions(), "agent": rt.agent.status(), "news": {k: v for k, v in rt.news.summary().items() if k in ("status", "error", "failed_sources")},
                "engine": {"last_error": rt.engine.last_error, "cycle_ms": rt.engine.cycle_ms, "required_bars": rt.engine.required}}


def register(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 4069-4150: 9 routes."""
    rt = ctx.rt
    get_config = ctx.get_config
    put_config = ctx.put_config
    strategy_mode = ctx.strategy_mode

    # ------------------------------------------------------------ desktop application (Windows shell): window, autostart, restart
    # ---------------------------------------------------------------- 1.32 Control Tower: resources, strategy presets
    @app.get("/api/v1/system/resources")
    def system_resources():
        return sysres.snapshot()

    preset_store = rt.api_services.presets                              # Etap 4 (krok A): owned by the composition root (rt.api_services)

    @app.get("/api/v1/presets/strategy")
    def presets_list():
        cur = rt.cfg.get().model_dump(mode="json")
        return {"items": preset_store.list(), "current": presets.snapshot(cur), "defaults": presets.defaults(),
                "fields": [f"{a}.{b}" for a, b in presets.FIELDS],
                "note": "Preset = nazwana kopia ustawień wyboru strategii, progów setupu i filtrów wejść. Wczytanie zapisuje je tą samą drogą co "
                        "Ustawienia (walidacja); tryb wykonania, limity ryzyka i dane rachunku nie są częścią presetu."}

    @app.post("/api/v1/presets/strategy")
    def presets_save(req: PresetReq):
        try:
            item = preset_store.save(req.name, rt.cfg.get().model_dump(mode="json"))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        rt.log.info("CONFIG", "PRESET_SAVED", f"Zapisano preset strategii „{item['name']}”.")
        return item

    @app.post("/api/v1/presets/strategy/load")
    def presets_load(req: PresetReq):
        item = preset_store.get(req.name)
        if not item:
            raise HTTPException(404, "PRESET_NOT_FOUND")
        out = _apply_preset(item.get("values") or {})
        rt.log.info("CONFIG", "PRESET_LOADED", f"Wczytano preset strategii „{req.name}”.")
        return out

    @app.post("/api/v1/presets/strategy/reset")
    def presets_reset():
        out = _apply_preset(presets.defaults())
        rt.log.info("CONFIG", "PRESET_RESET", "Przywrócono domyślne ustawienia sterowania strategią.")
        return out

    def _apply_preset(values: dict) -> dict:
        """Strategy selection goes through its own endpoint (setup view + selector reset, as the panel switch does); the other
        fields through the validated config write."""
        values = dict(values)
        mode, manual = values.pop("active.strategy_mode", None), values.pop("active.manual_strategy_id", None)
        out = put_config(presets.patch_of(values))
        cur = rt.cfg.get().active
        if mode in ("AUTO", "MANUAL") and (mode, manual if mode == "MANUAL" else None) != (cur.strategy_mode, cur.manual_strategy_id):
            strategy_mode(StrategyModeReq(strategy_mode=mode, manual_strategy_id=manual if mode == "MANUAL" else None))
            out = get_config()
        return out

    @app.get("/api/v1/desktop")
    def desktop_get():
        return desktop.info()

    @app.post("/api/v1/desktop/prefs")
    def desktop_prefs(req: DesktopPrefsReq):
        try:
            out = desktop.save_prefs(req.close_action, req.autostart, req.start_minimized)
        except desktop.DesktopError as exc:
            raise HTTPException(400, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(500, f"AUTOSTART_REGISTRY_ERROR: {exc}") from exc
        rt.log.info("APP", "DESKTOP_PREFS", f"Praca aplikacji: zamknięcie okna={req.close_action}, autostart={req.autostart}, "
                    f"start w tle={req.start_minimized}")
        return out

    @app.post("/api/v1/desktop/restart-engine")
    async def desktop_restart():
        try:
            desktop.request_restart()
        except desktop.DesktopError as exc:
            raise HTTPException(400, str(exc)) from exc
        rt.log.info("APP", "ENGINE_RESTART_REQUEST", "Ponowne uruchomienie silnika na żądanie panelu")
        asyncio.get_running_loop().call_later(0.5, rt.request_shutdown)
        return {"ok": True}

    @app.post("/api/v1/admin/shutdown")
    async def shutdown():
        rt.log.info("APP", "SHUTDOWN_REQUEST", "Żądanie zatrzymania aplikacji")
        loop = asyncio.get_running_loop()
        loop.call_later(0.5, rt.request_shutdown)
        return {"ok": True}
