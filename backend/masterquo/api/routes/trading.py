"""API routes: handel ręczny, tryby i wykonanie.

register_manual(app, ctx): Lab Trade Pad (adapter zgodności) i Manual Trade Pad PMW-UPD-07 R12
    (9 routes; create_app before the split, 7ba7ab0: lines 609-702)
register_modes(app, ctx): tryb wykonania i ścieżka główna
    (2 routes; create_app before the split, 7ba7ab0: lines 1736-1757)
register_execution(app, ctx): AUTO, STOP nowych wejść, wykonanie decyzji, zamknięcie / adopcja pozycji, MT5, newsy
    (7 routes; create_app before the split, 7ba7ab0: lines 3976-4013)

The handlers are the ones create_app defined before the split (Etap 4 krok B, docs/arch146/ETAP2_PROJEKT.md §3 / §5):
same function names, signatures, decorators, Pydantic models, error codes and body - the block of create_app is copied
verbatim, the only edit is one more dot in a relative import (the package is one level deeper). The create_app locals the
block used (rt, helpers, handlers called by name) are bound from ctx at the top of the function under the same names;
registration order: api/routes/__init__.REGISTRATION.
"""
from __future__ import annotations

from fastapi import Body, HTTPException

from ...execution.modes import ModeError
from ...licensing.gate import LicenseRequired
from ..schemas import CloseReq, ExecReq, ModeReq, OnReq, PrimaryPathReq


def register_manual(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 609-702: 9 routes."""
    rt = ctx.rt
    _check_asset = ctx._check_asset

    @app.post("/api/v1/lab/tradepad")
    def lab_tradepad(body: dict = Body(...)):
        from ...lab.edge import trade_pad_plan
        a = rt.cfg.get().assets.active
        sym = _check_asset(a, "TRADEPAD")
        meta = rt.bridge.symbol_meta(sym)
        if not meta:
            raise HTTPException(409, "NO_SYMBOL_METADATA")
        meta = {**meta, **{k: (rt.bridge.symbol_info or {}).get(k) for k in ("volume_min", "volume_step")}}
        comm_side = rt.cfg.get().scalp.commission_per_lot_side             # None = UNKNOWN (config.py)
        # 1.46: P&L currency vs account currency - the P&L (profit currency, e.g. USD on XAUUSD) was netted with the commission (account
        # currency) at a silent rate 1.0 because the account currency was never passed (PLN account: 1000 USD - 40 PLN = 960). Unknown
        # account currency -> trade_pad_plan labels the legacy numbers NOT_VERIFIED.
        acct_ccy = (rt.bridge.account_status() or {}).get("currency")
        acct_ccy = acct_ccy if isinstance(acct_ccy, str) and acct_ccy.strip() else None
        try:
            plan = trade_pad_plan(side=str(body.get("side")), entry=float(body["entry"]), sl=float(body["sl"]), tp=float(body["tp"]),
                                  lots=float(body.get("lots") or 0.01), meta=meta, quote=rt.bridge.quote_status(),
                                  commission_per_lot_side=float(comm_side or 0), account_currency=acct_ccy)
        except (KeyError, ValueError, TypeError) as exc:                  # 1.46: TypeError (entry: null) was a 500
            raise HTTPException(400, f"INVALID_PLAN: {exc}") from exc
        if comm_side is None:
            # 1.46: an UNKNOWN commission was simulated as 0 - P/L at TP / SL and the round-turn cost looked known. Missing = null, never 0.
            plan.update(pnl_at_tp=None, pnl_at_sl=None, commission_round_turn=None, cost_status="UNAVAILABLE", cost_reason="COMMISSION_UNKNOWN")
        return {"asset": a, "broker_symbol": sym, **plan}

    @app.post("/api/v1/lab/tradepad/execute")
    def lab_tradepad_execute(body: dict = Body(default={})):
        """Compatibility adapter: explicit routing to the Manual Pad gates (intent required)."""
        iid = body.get("intent_id")
        if not iid:
            raise HTTPException(400, "INTENT_REQUIRED: POST /api/v1/manual/plan → /api/v1/manual/intents → /execute")
        return manual_execute(str(iid), {"action_revision": body.get("action_revision", 1)})

    # ------------------------------------------------------------ PMW-UPD-07 R12 Manual Trade Pad (explicit user actions only)
    @app.post("/api/v1/manual/plan")
    def manual_plan(body: dict = Body(...)):
        from ...execution.manual import PlanError
        try:
            return rt.manual.plan(body)
        except PlanError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/v1/manual/intents")
    def manual_intent(body: dict = Body(...)):
        from ...execution.manual import PlanError
        try:
            return rt.manual.create_intent(str(body.get("plan_id")))
        except PlanError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/v1/manual/intents")
    def manual_intents():
        return {"items": rt.manual.intents(30)}

    @app.get("/api/v1/manual/intents/{iid}")
    def manual_intent_get(iid: str):
        r = rt.manual.intent(iid)
        if not r:
            raise HTTPException(404, "INTENT_NOT_FOUND")
        return r

    def _manual_arg(key: str, parse):
        """1.46: a Manual Pad value that 1.45 could not parse (ValueError / TypeError / OverflowError -> HTTP 500, nothing sent) is a 400
        with the field name. The parsing is the 1.45 one: every value that reached the Manual Pad (and order_send) in 1.45 is unchanged."""
        try:
            return parse()
        except (TypeError, ValueError, OverflowError):
            raise HTTPException(400, f"INVALID_{key.upper()}") from None

    @app.post("/api/v1/manual/intents/{iid}/execute")
    def manual_execute(iid: str, body: dict = Body(default={})):
        from ...execution.manual import PlanError
        rev = _manual_arg("action_revision", lambda: int(body.get("action_revision") or 1))
        try:
            return rt.manual.execute(iid, rev)
        except PlanError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/v1/manual/intents/{iid}/manage")
    def manual_manage(iid: str, body: dict = Body(...)):
        from ...execution.manual import PlanError
        action = str(body.get("action"))
        rev = _manual_arg("action_revision", lambda: int(body.get("action_revision") or 1))
        off = _manual_arg("offset_points", lambda: float(body.get("offset_points") or 0))
        vol = _manual_arg("volume", lambda: None if body.get("volume") is None else float(body["volume"]))
        try:
            return rt.manual.manage(iid, action, rev, offset_points=off, volume=vol)
        except PlanError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/v1/manual/reconcile")
    def manual_reconcile():
        return rt.manual.reconcile()


def register_modes(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 1736-1757: 2 routes."""
    rt = ctx.rt

    # ------------------------------------------------------------ modes & execution
    @app.post("/api/v1/mode")
    def set_mode(req: ModeReq):
        try:
            rt.license.require("zmiana trybu wykonania")              # 1.44.0: centralna kontrola licencji przed uruchomieniem trybu
        except LicenseRequired as exc:
            raise HTTPException(402, exc.state.get("message") or "Brak ważnej licencji") from None
        try:
            return rt.modes.set_mode(req.mode, confirm=req.confirm, account=rt.bridge.account_status(), account_key=rt.bridge.account_key,
                                     synthetic=rt.bridge.synthetic)
        except ModeError as exc:
            raise HTTPException(400, str(exc)) from exc
        finally:
            rt.engine.mark_dirty()

    @app.post("/api/v1/mode/primary-path")
    def set_primary_path(req: PrimaryPathReq):
        try:
            return rt.modes.set_primary_path(req.instrument, req.path)
        except ModeError as exc:
            raise HTTPException(400, str(exc)) from exc
        finally:
            rt.engine.mark_dirty()


def register_execution(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 3976-4013: 7 routes."""
    rt = ctx.rt

    @app.post("/api/v1/auto")
    def set_auto(req: OnReq):
        try:
            return rt.modes.set_auto(req.on)
        except ModeError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/v1/kill")
    def kill(req: OnReq):
        st = rt.modes.set_kill(req.on, req.reason)
        rt.engine.mark_dirty()
        return st

    @app.post("/api/v1/execute")
    def execute(req: ExecReq):
        return rt.gateway.execute(req.decision_id, initiated_by="USER")

    @app.post("/api/v1/positions/close")
    def close_positions(req: CloseReq):
        if req.confirm != "ZAMKNIJ":
            raise HTTPException(400, "CONFIRMATION_REQUIRED_TYPE_ZAMKNIJ")
        return rt.manager.close_positions(req.scope, req.ticket)

    @app.post("/api/v1/positions/{ticket}/adopt")
    def adopt(ticket: int, req: CloseReq):
        if req.confirm != "PRZEJMIJ":
            raise HTTPException(400, "CONFIRMATION_REQUIRED_TYPE_PRZEJMIJ")
        return rt.manager.adopt(ticket)

    @app.post("/api/v1/mt5/reconnect")
    def reconnect():
        rt.bridge.request_reconnect("USER_REQUEST")
        return {"ok": True}

    @app.post("/api/v1/news/refresh")
    def news_refresh():
        rt.news.refresh_now()
        return {"ok": True}
