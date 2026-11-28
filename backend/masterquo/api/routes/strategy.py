"""API routes: strategie i preferencje.

register(app, ctx): wybór strategii AUTO, preferencje widoku setupów i dźwigni, szczegóły setupów
    (7 routes; create_app before the split, 7ba7ab0: lines 1760-1829)
register_selection(app, ctx): przełączniki strategii, profil, dziennik wyboru, playbook
    (4 routes; create_app before the split, 7ba7ab0: lines 3894-3937)

The handlers are the ones create_app defined before the split (Etap 4 krok B, docs/arch146/ETAP2_PROJEKT.md §3 / §5):
same function names, signatures, decorators, Pydantic models, error codes and body - the block of create_app is copied
verbatim, the only edit is one more dot in a relative import (the package is one level deeper). The create_app locals the
block used (rt, helpers, handlers called by name) are bound from ctx at the top of the function under the same names;
registration order: api/routes/__init__.REGISTRATION.
"""
from __future__ import annotations

import json

from fastapi import HTTPException

from ... import paths
from ..schemas import (
    LeverageReq,
    ProfileReq,
    SetupViewReq,
    StrategyModeReq,
    StrategyToggleReq,
)


def register(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 1760-1829: 7 routes."""
    rt = ctx.rt

    # ------------------------------------------------------------ AUTO strategy selection (separate from order execution)
    def media_dir():
        d = paths.data_dir() / "assets" / "masterquo"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @app.get("/api/v1/strategy/auto")
    def strategy_auto():
        return rt.engine.active.status()

    @app.post("/api/v1/strategy/mode")
    def strategy_mode(req: StrategyModeReq):
        if req.strategy_mode == "MANUAL" and not req.manual_strategy_id:
            raise HTTPException(400, "MANUAL_REQUIRES_STRATEGY_ID")
        try:
            rt.cfg.update({"active": {"strategy_mode": req.strategy_mode,
                                      "manual_strategy_id": req.manual_strategy_id if req.strategy_mode == "MANUAL" else None}})
        except Exception as exc:
            raise HTTPException(400, f"INVALID: {exc}") from exc
        # legacy switch -> the same per-account setup view the engine uses (one source)
        rt.prefs.set("setup_view", {"mode": "SELECTED" if req.strategy_mode == "MANUAL" else "AUTO", "strategy_id": req.manual_strategy_id})
        rt.engine.active.selector.reset("STRATEGY_MODE_CHANGED")
        rt.log.info("AUTO", "STRATEGY_MODE", f"Wybór strategii: {req.strategy_mode}" + (f" ({req.manual_strategy_id})" if req.strategy_mode == "MANUAL" else "")
                    + ". Tryb wykonywania zleceń bez zmian.")
        rt.engine.mark_dirty()
        return rt.engine.active.status(compact=True)

    # ------------------------------------------------------------ setup view + leverage (per account) and scenario details
    @app.get("/api/v1/prefs")
    def prefs_get():
        from ...prefs import LEVERAGE_CHOICES
        return {**rt.prefs.all(), "exposure": rt.prefs.exposure_limit(), "leverage_choices": list(LEVERAGE_CHOICES)}

    @app.post("/api/v1/prefs/setup-view")
    def prefs_setup_view(req: SetupViewReq):
        from ...prefs import PrefsError
        try:
            v = rt.prefs.set("setup_view", req.model_dump())
        except PrefsError as exc:
            raise HTTPException(400, str(exc)) from exc
        if v["mode"] != "ALL":
            rt.engine.active.selector.reset("SETUP_VIEW_CHANGED")
        rt.log.info("AUTO", "SETUP_VIEW", f"Wybór setupu: {v['mode']}" + (f" {v['strategy_id']}" if v["mode"] == "SELECTED" else "")
                    + " (nie wymusza sygnału ani zlecenia; wszystkie filtry obowiązują).")
        return prefs_get()

    @app.post("/api/v1/prefs/leverage")
    def prefs_leverage(req: LeverageReq):
        from ...prefs import PrefsError
        try:
            v = rt.prefs.set("leverage", req.model_dump())
        except PrefsError as exc:
            raise HTTPException(400, str(exc)) from exc
        rt.log.info("RISK", "LEVERAGE_LIMIT", ("Limit ekspozycji: AUTO (dźwignia rachunku z MT5)" if v["mode"] == "AUTO" else f"Limit ekspozycji ustawiony w bocie: 1:{v['limit']}")
                    + " – nie zmienia dźwigni u brokera; dotyczy przyszłych decyzji, istniejące pozycje bez zmian.")
        return prefs_get()

    @app.get("/api/v1/setups")
    def setups_list(include_terminal: bool = True):
        from ...engine import setup_details
        return setup_details.scenarios(rt.engine, include_terminal=include_terminal)

    @app.get("/api/v1/setups/{setup_id}/details")
    def setup_detail(setup_id: str):
        from ...engine import setup_details
        if len(setup_id) > 120:
            raise HTTPException(400, "SETUP_ID_INVALID")
        out = setup_details.details(rt.engine, setup_id)
        if out is None:
            raise HTTPException(404, "SETUP_NOT_FOUND")
        return out

    ctx.media_dir = media_dir
    ctx.strategy_mode = strategy_mode


def register_selection(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 3894-3937: 4 routes."""
    rt = ctx.rt

    @app.post("/api/v1/strategy/toggle")
    def strategy_toggle(req: StrategyToggleReq):
        from ...strategies import registry as _reg
        if req.strategy_id not in _reg.STRATEGIES:
            raise HTTPException(400, "UNKNOWN_STRATEGY_ID")
        cur = rt.cfg.get().active.strategies.get(req.strategy_id)
        # 1.46 (I0852): without a stored toggle the default trade flag is the registry default used by trade_allowed (engine/active.py) -
        # signal-only S11/S12 no longer start trading when only 'scan' is switched; an explicit req.trade is still honoured
        patch = {"scan": cur.scan if cur else True, "trade": cur.trade if cur else (req.strategy_id not in _reg.DEFAULT_NO_TRADE)}
        if req.scan is not None:
            patch["scan"] = req.scan
        if req.trade is not None:
            patch["trade"] = req.trade
        rt.cfg.update({"active": {"strategies": {req.strategy_id: patch}}})
        rt.log.info("AUTO", "STRATEGY_TOGGLE", f"{req.strategy_id}: skanuj={'TAK' if patch['scan'] else 'NIE'}, handel={'TAK' if patch['trade'] else 'NIE'}")
        rt.engine.mark_dirty()
        return rt.engine.active.status(compact=True)

    @app.post("/api/v1/strategy/profile")
    def strategy_profile(req: ProfileReq):
        rt.cfg.update({"active": {"profile": req.profile}})
        rt.engine.active.selector.reset("PROFILE_CHANGED")
        rt.log.info("AUTO", "PROFILE", f"Profil wykrywania: {req.profile}")
        rt.engine.mark_dirty()
        return rt.engine.active.status(compact=True)

    @app.get("/api/v1/strategy/selection-log")
    def selection_log(limit: int = 30):
        return {"log": rt.engine.active.selection_log(max(1, min(limit, 200)))}

    @app.get("/api/v1/playbook")
    def playbook(limit: int = 100):
        rows = rt.db.query("SELECT setup_id, strategy_id, strategy_version, direction, timeframe, stage, status, version, score, first_seen_at, first_price, "
                           "updated_at, terminal_reason, terminal_at, synthetic, record_json, history_json FROM strategy_setups ORDER BY first_seen_at DESC LIMIT ?",
                           (max(1, min(limit, 500)),))
        trades = {t["setup_id"]: t for t in rt.db.query("SELECT setup_id, mode, side, net_pnl, gross_pnl, opened_at, closed_at FROM trades WHERE setup_id LIKE 'MQA-%'")}
        out = []
        for r in rows:
            rec = json.loads(r.pop("record_json"))
            hist = json.loads(r.pop("history_json"))
            out.append({**r, "context": {"regime": rec.get("regime"), "horizon": rec.get("horizon"), "countertrend": rec.get("countertrend")},
                        "hypothesis": rec.get("strategy_name"), "plan": {k: rec.get(k) for k in ("entry_plan", "stop_loss", "targets", "invalidation_level", "exit_rules")},
                        "score": rec.get("score"), "missing": rec.get("missing_confirmations"), "history": hist, "result": trades.get(r["setup_id"]) or "brak danych"})
        return {"cards": out, "note": "Karty obejmują także setupy anulowane, unieważnione i wygasłe – nie tylko wybrane sukcesy."}
