"""API routes: Kronos / Chronos-2 / Granite.

register_kronos(app, ctx): Kronos
    (12 routes; create_app before the split, 7ba7ab0: lines 2214-2313)
register_foundation(app, ctx): Chronos-2 / Granite TTM, Memory Governor (zasoby), Granite w Centrum treningu
    (19 routes; create_app before the split, 7ba7ab0: lines 2316-2493)

The handlers are the ones create_app defined before the split (Etap 4 krok B, docs/arch146/ETAP2_PROJEKT.md §3 / §5):
same function names, signatures, decorators, Pydantic models, error codes and body - the block of create_app is copied
verbatim, the only edit is one more dot in a relative import (the package is one level deeper). The create_app locals the
block used (rt, helpers, handlers called by name) are bound from ctx at the top of the function under the same names;
registration order: api/routes/__init__.REGISTRATION.
"""
from __future__ import annotations

import re

from fastapi import Body, HTTPException, Query

from ..common import body_num


def register_kronos(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 2214-2313: 12 routes."""
    rt = ctx.rt
    _th_inst = ctx._th_inst

    # ------------------------------------------------------------------ Kronos (NeoQuasar/Kronos-small since 1.42.8; Kronos-base 1.37-1.42.7)
    # 1.46 arch (I0007): the timeframes the Kronos settings allow (kronos/settings.TF) - M3 was missing here (an enabled M3 gave 400).
    # Only the tf parameter of the two read-only GET routes (forecast / history) is validated with it; nothing is queued or forced.
    from ...kronos.settings import TF_ALL as _KR_TF

    def _kr_tf(tf: str) -> str:
        tf = tf.upper() if isinstance(tf, str) else ""        # 1.46: a number was an AttributeError (.upper) -> 500
        if tf not in _KR_TF:
            raise HTTPException(400, "TIMEFRAME_NOT_ALLOWED")
        return tf

    @app.get("/api/v1/kronos")
    def kronos_status():
        from kronos_runtime import lock as _KL
        kr = rt.kronos
        return {**kr.public(), "env": kr.env_status(), "settings": kr.settings.get().model_dump(mode="json"),
                "model": {"repo": _KL.MODEL["repo"], "revision": _KL.MODEL["revision"], "max_context": _KL.MAX_CONTEXT},
                "tokenizer": {"repo": _KL.TOKENIZER["repo"], "revision": _KL.TOKENIZER["revision"]}, "license": _KL.LICENSE,
                "data_kind": kr.data_kind()[0], "data_source": kr.data_kind()[1]}

    @app.get("/api/v1/kronos/forecast")
    def kronos_forecast(instrument: str = Query("XAUUSD"), tf: str = Query("M5")):
        return rt.kronos.forecast(_th_inst(instrument), _kr_tf(tf))

    @app.get("/api/v1/kronos/history")
    def kronos_history(instrument: str = Query("XAUUSD"), tf: str | None = Query(None), limit: int = Query(100, ge=1, le=2000)):
        return {"items": rt.kronos.history(_th_inst(instrument), _kr_tf(tf) if tf else None, limit)}

    @app.put("/api/v1/kronos/settings")
    def kronos_settings_put(body: dict = Body(...)):
        if "strategy_use" in body:
            raise HTTPException(400, "STRATEGY_USE_ONLY_VIA_/api/v1/kronos/strategy-use")
        try:
            s = rt.kronos.settings.update(body)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"INVALID_SETTINGS: {exc}"[:500]) from exc
        rt.log.info("KRONOS", "SETTINGS", "Zmieniono ustawienia Kronos: " + ", ".join(sorted(body))[:200])
        return {"ok": True, "settings": s.model_dump(mode="json")}

    @app.post("/api/v1/kronos/enable")
    def kronos_enable(body: dict = Body(...)):
        on = bool(body.get("on"))
        rt.kronos.settings.update({"enabled": on})
        rt.log.info("KRONOS", "ENABLE", f"Kronos {'włączony' if on else 'wyłączony'} (tryb SHADOW).")
        return {"ok": True, "enabled": on}

    @app.post("/api/v1/kronos/install")
    def kronos_install(body: dict = Body(default={})):
        cuda = body.get("cuda")
        if cuda not in (None, "", "cu126", "cu128"):
            raise HTTPException(400, "CUDA_VARIANT_NOT_ALLOWED")
        r = rt.kronos.start_install(cuda or None)
        if not r.get("ok"):
            raise HTTPException(409, r.get("reason"))
        return r

    @app.post("/api/v1/kronos/verify")
    def kronos_verify():
        r = rt.kronos.start_verify(reference=True)
        if not r.get("ok"):
            raise HTTPException(409, r.get("reason"))
        return r

    @app.get("/api/v1/kronos/job/{name}")
    def kronos_job(name: str):
        if name not in ("install", "verify", "validation"):
            raise HTTPException(404, "UNKNOWN_JOB")
        return {"job": rt.kronos.job(name)}

    @app.post("/api/v1/kronos/refresh")
    def kronos_refresh(body: dict = Body(...)):
        r = rt.kronos.refresh(_th_inst(str(body.get("instrument", ""))), _kr_tf(str(body.get("tf", ""))))
        if not r.get("ok"):
            raise HTTPException(409, r.get("reason"))
        return r

    @app.post("/api/v1/kronos/validate")
    def kronos_validate(body: dict = Body(...)):
        n = body_num(body, "max_origins", 300, int)
        if not 20 <= n <= 2000:
            raise HTTPException(400, "MAX_ORIGINS_OUT_OF_RANGE")
        r = rt.kronos.start_validation(_th_inst(str(body.get("instrument", ""))), _kr_tf(str(body.get("tf", ""))), n)
        if not r.get("ok"):
            raise HTTPException(409, r.get("reason"))
        return r

    @app.get("/api/v1/kronos/validation")
    def kronos_validation(instrument: str = Query("XAUUSD"), tf: str = Query("M5")):
        from ...kronos import validation as _KV
        rep = _KV.latest_report(_th_inst(instrument), _kr_tf(tf))
        if rep:
            rep = {k: v for k, v in rep.items() if k != "rows"} | {"rows_tail": (rep.get("rows") or [])[-50:]}
        return {"report": rep}

    @app.post("/api/v1/kronos/strategy-use")
    def kronos_strategy_use(body: dict = Body(...)):
        strat = str(body.get("strategy", "")).upper()
        use = str(body.get("use", "")).upper()
        tf = body.get("timeframe")
        r = rt.kronos.set_strategy_use(strat, use, timeframe=_kr_tf(tf) if tf else None, confirm=bool(body.get("confirm")))
        if not r.get("ok"):
            raise HTTPException(409, r.get("reason"))
        return r


def register_foundation(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 2316-2493: 19 routes."""
    rt = ctx.rt
    _th_inst = ctx._th_inst

    # ------------------------------------------------------------------ 1.37 Chronos-2 / 1.40 Granite TTM (+ three-model comparison with Kronos)
    _TS_TF = ("M1", "M3", "M5", "M15", "M30", "H1")

    def _ts_tf(tf: str) -> str:
        tf = tf.upper() if isinstance(tf, str) else ""        # 1.46: a number was an AttributeError (.upper) -> 500
        if tf not in _TS_TF:
            raise HTTPException(400, "TIMEFRAME_NOT_ALLOWED")
        return tf

    def _ts_mid(m: str, history: bool = False) -> str:
        m = m.lower() if isinstance(m, str) else ""           # 1.46: a number was an AttributeError (.lower) -> 500
        if m not in ("chronos2", "granite_ttm", "tirex2") and not (history and m == "fincast"):   # fincast: RETIRED in 1.40 - history only
            raise HTTPException(400, "MODEL_RETIRED" if m == "fincast" else "MODEL_NOT_ALLOWED")
        return m

    # ------------------------------------------------------------------ 1.40 Memory Governor / AI scheduler (resources)
    @app.get("/api/v1/resources")
    def resources_get():
        """RAM of the computer, memory of the bot + every model process (current / peak), level, profile, inference p50 / p95, events."""
        if rt.governor is None:
            raise HTTPException(503, "GOVERNOR_UNAVAILABLE")
        return rt.governor.public()

    @app.put("/api/v1/resources/profile")
    def resources_profile(body: dict = Body(...)):
        from ...resources.governor import PROFILE_KEYS
        prof = str(body.get("profile") or "")
        if prof not in ("LOW_MEMORY_16GB", "LOW_MEMORY_12GB", "LOW_MEMORY_8GB", "AUTO", "ECO", "BALANCED", "MANUAL"):
            raise HTTPException(400, "PROFILE_UNKNOWN")
        manual = body.get("manual") or {}
        if not isinstance(manual, dict) or any(k not in PROFILE_KEYS for k in manual):
            raise HTTPException(400, "MANUAL_KEYS_UNKNOWN")
        before = rt.cfg.get().resources.model_dump(mode="json")
        try:
            rt.cfg.update({"resources": {"profile": prof, "manual": manual if prof == "MANUAL" else before.get("manual", {})}})
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"INVALID_RESOURCES: {exc}"[:300]) from exc
        rt.log.info("RESOURCES", "PROFILE", f"Profil zasobów: {before.get('profile')} → {prof}" + (f" ({manual})" if prof == "MANUAL" else ""))
        if rt.governor is None:
            raise HTTPException(503, "GOVERNOR_UNAVAILABLE")
        rt.governor.record_event("PROFILE", f"profil {before.get('profile')} → {prof}")
        return rt.governor.public()

    @app.get("/api/v1/models/foundation")
    def tsfm_status():
        """Status of the three foundation models in one place: Kronos (existing service) + Chronos-2 + Granite TTM (+ retired FinCast)."""
        from kronos_runtime import lock as _KL
        kr = rt.kronos
        return {**rt.tsfm.public(), "settings": rt.tsfm.settings.get().model_dump(mode="json"),
                "kronos": {"name": _KL.MODEL_NAME, "repo": _KL.MODEL["repo"], "revision": _KL.MODEL["revision"], "params_upstream": _KL.MODEL["params_upstream"],
                           "status": kr.state.get("status"), "reason": kr.state.get("reason"), "load": kr.load_info, "legacy": list(_KL.LEGACY),
                           "largest_public_note": "1.42.8: używany Kronos-small (24,7M, ok. 0,5 GB RAM) – prognoza dostępna także przy małej ilości wolnej pamięci; Kronos-base (102,3M) – historia 1.37–1.42.7"},
                "data_kind": rt.tsfm.data_kind()[0], "data_source": rt.tsfm.data_kind()[1]}

    @app.get("/api/v1/models/foundation/forecast")
    def tsfm_forecast(model: str = Query(...), instrument: str = Query("XAUUSD"), tf: str = Query("M5")):
        return rt.tsfm.forecast(_ts_mid(model), _th_inst(instrument), _ts_tf(tf))

    @app.get("/api/v1/models/foundation/compare")
    def tsfm_compare(instrument: str = Query("XAUUSD"), tf: str = Query("M5")):
        return rt.tsfm.compare(_th_inst(instrument), _ts_tf(tf))

    @app.get("/api/v1/models/foundation/history")
    def tsfm_history(model: str | None = Query(None), instrument: str = Query("XAUUSD"), tf: str | None = Query(None),
                     limit: int = Query(100, ge=1, le=2000)):
        return {"items": rt.tsfm.history(_ts_mid(model, history=True) if model else None, _th_inst(instrument), _ts_tf(tf) if tf else None, limit)}

    @app.put("/api/v1/models/foundation/settings")
    def tsfm_settings_put(body: dict = Body(...)):
        def has_use(d):
            return isinstance(d, dict) and any(k == "use" or has_use(v) for k, v in d.items())
        if has_use(body.get("models")):
            raise HTTPException(400, "USE_ONLY_VIA_/api/v1/models/foundation/use")
        if any(isinstance(v, dict) and "checkpoint" in v for v in (body.get("models") or {}).values()) or "retired" in body:
            raise HTTPException(400, "CHECKPOINT_ONLY_VIA_/api/v1/models/foundation/granite/activate")
        try:
            s = rt.tsfm.settings.update(body)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"INVALID_SETTINGS: {exc}"[:500]) from exc
        rt.log.info("TSFM", "SETTINGS", "Zmieniono ustawienia Chronos-2/Granite TTM: " + ", ".join(sorted(body))[:200])
        return {"ok": True, "settings": s.model_dump(mode="json")}

    @app.post("/api/v1/models/foundation/install")
    def tsfm_install(body: dict = Body(...)):
        r = rt.tsfm.start_install(_ts_mid(body.get("model")))
        if not r.get("ok"):
            raise HTTPException(409, r.get("reason"))
        return r

    @app.post("/api/v1/models/foundation/verify")
    def tsfm_verify(body: dict = Body(...)):
        r = rt.tsfm.start_verify(_ts_mid(body.get("model")))
        if not r.get("ok"):
            raise HTTPException(409, r.get("reason"))
        return r

    @app.post("/api/v1/models/foundation/refresh")
    def tsfm_refresh(body: dict = Body(...)):
        r = rt.tsfm.refresh(_ts_mid(body.get("model")), _th_inst(str(body.get("instrument", ""))), _ts_tf(str(body.get("tf", ""))))
        if not r.get("ok"):
            raise HTTPException(409, r.get("reason"))
        return r

    @app.post("/api/v1/models/foundation/validate")
    def tsfm_validate(body: dict = Body(...)):
        n = body_num(body, "max_origins", 200, int)
        if not 20 <= n <= 1000:
            raise HTTPException(400, "MAX_ORIGINS_OUT_OF_RANGE")
        r = rt.tsfm.start_validation(_th_inst(str(body.get("instrument", ""))), _ts_tf(str(body.get("tf", ""))), n)
        if not r.get("ok"):
            raise HTTPException(409, r.get("reason"))
        return r

    # ---- 1.40 Granite TTM in the Training Center (export, fine-tune job, versions, activation, rollback)
    @app.get("/api/v1/models/foundation/granite")
    def granite_get():
        from ...tsfm import granite_train as _GT
        c = rt.tsfm.settings.get().models["granite_ttm"]
        return {"checkpoint": c.checkpoint, "runs": _GT.runs(), "job": rt.tsfm.job("granite_train"),
                "rule": "trening nie startuje z botem; aktywacja tylko ręczna i tylko z werdyktem IMPROVED_VS_BASE na niewidzianych danych; powrót = BASE"}

    @app.post("/api/v1/models/foundation/granite/train")
    def granite_train(body: dict = Body(...)):
        from ...tsfm import granite_train as _GT
        epochs = body_num(body, "epochs", 6, int)
        if not 1 <= epochs <= 30:
            raise HTTPException(400, "EPOCHS_OUT_OF_RANGE")
        trading = getattr(rt.modes, "mode", "SIGNALS") in ("AUTO_DEMO", "AUTO_LIVE")
        r = _GT.start(rt.tsfm, _th_inst(str(body.get("instrument", ""))), _ts_tf(str(body.get("tf", ""))), epochs=epochs,
                      confirm_during_trading=bool(body.get("confirm_during_trading")), trading_active=trading)
        if not r.get("ok"):
            raise HTTPException(409, r.get("reason"))
        return r

    @app.post("/api/v1/models/foundation/granite/cancel")
    def granite_cancel():
        from ...tsfm import granite_train as _GT
        r = _GT.cancel(rt.tsfm)
        if not r.get("ok"):
            raise HTTPException(409, r.get("reason"))
        return r

    @app.post("/api/v1/models/foundation/granite/activate")
    def granite_activate(body: dict = Body(...)):
        from ...tsfm import granite_train as _GT
        rid = str(body.get("run_id") or "")
        if not re.match(r"^GTR-[0-9A-Za-z_-]{6,64}$", rid):
            raise HTTPException(400, "RUN_ID_INVALID")
        r = _GT.activate(rt.tsfm, rid)
        if not r.get("ok"):
            raise HTTPException(409, r.get("reason"))
        return r

    @app.post("/api/v1/models/foundation/granite/rollback")
    def granite_rollback():
        from ...tsfm import granite_train as _GT
        return _GT.rollback(rt.tsfm)

    @app.get("/api/v1/models/foundation/job/{name}")
    def tsfm_job(name: str):
        if not re.match(r"^(install|verify)_(chronos2|granite_ttm|tirex2|tabicl)$|^validation$|^granite_train$", name):
            raise HTTPException(400, "JOB_UNKNOWN")
        return {"job": rt.tsfm.job(name)}

    @app.get("/api/v1/models/foundation/validation")
    def tsfm_validation(instrument: str = Query("XAUUSD"), tf: str = Query("M5")):
        from ...tsfm import validation as _TV
        rep = _TV.latest_report(_th_inst(instrument), _ts_tf(tf))
        if rep:
            rep = {k: v for k, v in rep.items() if k != "rows"} | {"rows_tail": (rep.get("rows") or [])[-50:]}
        return {"report": rep}

    @app.post("/api/v1/models/foundation/use")
    def tsfm_use(body: dict = Body(...)):
        r = rt.tsfm.set_use(_ts_mid(body.get("model")), str(body.get("path", "")).upper(), str(body.get("use", "")).upper(),
                            timeframe=_ts_tf(body["timeframe"]) if body.get("timeframe") else None, confirm=bool(body.get("confirm")))
        if not r.get("ok"):
            raise HTTPException(409, r.get("reason"))
        return r
