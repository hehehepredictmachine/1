"""API routes: rynek, aktywa i sygnały.

register(app, ctx): ściany, struktura, aktywa, Execution Lock (wycofany), skaner rynków, sygnały, decyzja, statystyki, newsy, logi
    (23 routes; create_app before the split, 7ba7ab0: lines 1406-1621)

The handlers are the ones create_app defined before the split (Etap 4 krok B, docs/arch146/ETAP2_PROJEKT.md §3 / §5):
same function names, signatures, decorators, Pydantic models, error codes and body - the block of create_app is copied
verbatim, the only edit is one more dot in a relative import (the package is one level deeper). The create_app locals the
block used (rt, helpers, handlers called by name) are bound from ctx at the top of the function under the same names;
registration order: api/routes/__init__.REGISTRATION.
"""
from __future__ import annotations

import json

from fastapi import Body, HTTPException, Query

from ... import stats
from ...timeutil import TIMEFRAMES, iso, utcnow
from ..schemas import AssetActiveReq, AssetConfirmReq

SYMBOL_RX = r"^[A-Za-z0-9._#&$!+\-]{1,40}$"


def register(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 1406-1621: 23 routes."""
    rt = ctx.rt
    logs_list = ctx.logs_list

    @app.get("/api/v1/walls")
    def walls_get():
        snap = {k: v for k, v in (rt.walls.last or {}).items() if not k.startswith("_")}
        return {"status": rt.walls.status(), "snapshot": snap,
                "note": "HV_PROXY = zmienność historyczna brokera jako przybliżenie – nie zmienność implikowana. Walls to pasma konwencji log-zwrotu, nie prognoza."}

    @app.post("/api/v1/walls/iv-import")
    def walls_iv_import(body: dict = Body(...)):
        from ...analysis import iv_import
        text = str(body.get("text") or "")
        if not text or len(text) > 1_000_000:
            raise HTTPException(400, "IV_IMPORT_EMPTY_OR_TOO_LARGE")
        try:
            rows = iv_import.parse_text(text, body.get("format"))
        except Exception as exc:
            raise HTTPException(400, f"IV_IMPORT_PARSE_ERROR: {type(exc).__name__}") from exc
        rep = iv_import.store(rt.db, rows, imported_by="MONITOR")
        rt.log.info("WALLS", "IV_IMPORT", f"Import IV: przyjęto {rep['accepted']}, odrzucono {len(rep['rejected'])}, już zapisane {rep['already_stored']} "
                    "(użycie od available_at; dotyczy przyszłych snapshotów).")
        rt.engine.mark_dirty()
        return rep

    @app.get("/api/v1/structure")
    def structure(tf: str = Query("M5")):
        if tf not in TIMEFRAMES:
            raise HTTPException(400, "INVALID_TIMEFRAME")
        return rt.engine.structure(tf)

    # ------------------------------------------------------------ markets (scanner) and AI signals
    import re as _re

    def _sym(symbol: str) -> str:
        if not _re.fullmatch(SYMBOL_RX, symbol or ""):
            raise HTTPException(400, "INVALID_SYMBOL")
        return symbol

    # ------------------------------------------------------------ 1.14 assets (XAUUSD / BTC) and Execution Lock
    @app.get("/api/v1/assets")
    def assets_state(refresh: bool = False):
        if refresh:
            rt.assets.refresh()
        return rt.assets.state()

    @app.get("/api/v1/assets/{asset}/candidates")
    def assets_candidates(asset: str):
        try:
            return {"asset": asset, "candidates": rt.assets.candidates(asset),
                    "note": "Kandydaci wg metadanych terminala (currency_base/profit). Nic nie jest wybierane automatycznie."}
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(409, f"{type(exc).__name__}: {exc}") from exc

    @app.post("/api/v1/assets/confirm")
    def assets_confirm(req: AssetConfirmReq):
        if not _re.fullmatch(SYMBOL_RX, req.broker_symbol or ""):
            raise HTTPException(400, "INVALID_SYMBOL")
        try:
            st = rt.assets.confirm(req.asset, req.broker_symbol)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        rt.db.execute("INSERT INTO settings_audit(ts, change_json) VALUES (?,?)", (iso(utcnow()), json.dumps({"asset_confirm": req.model_dump()})))
        return st

    @app.post("/api/v1/assets/active")
    def assets_active(req: AssetActiveReq):
        old = rt.cfg.get().mt5.symbol
        try:
            st = rt.assets.switch(req.asset)
        except PermissionError as exc:
            raise HTTPException(409, str(exc)) from exc
        rt.db.execute("INSERT INTO settings_audit(ts, change_json) VALUES (?,?)", (iso(utcnow()), json.dumps({"active_asset": req.asset})))
        if rt.cfg.get().mt5.symbol != old:
            rt.modes.reset("ACTIVE_ASSET_CHANGED")
            rt.bridge.request_reconnect("ACTIVE_ASSET_CHANGED")
        rt.engine.mark_dirty()
        rt.bus.publish("assets", st)
        try:                                              # w2 (I0748, informative): open SH plans of another symbol are not managed now
            w = rt.sh.open_plans_warning(rt.sh.store, rt.cfg.get().mt5.symbol)
        except Exception:  # noqa: BLE001 - the switch itself already happened
            w = None
        return dict(st, sh_open_plans_warning=w) if w and isinstance(st, dict) else st

    LOCK_NOTE = ("Execution Lock został wycofany (1.24, decyzja użytkownika). O wysyłce zleceń decydują: tryb wykonania, potwierdzony "
                 "rachunek (DEMO / REAL), STOP nowych wejść, limity ryzyka użytkownika, aktualne dane i warunki brokera.")

    @app.get("/api/v1/execution/lock")
    def exec_lock():
        """Compatibility read for older monitors: the lock no longer exists and blocks nothing."""
        return {"lock": "WITHDRAWN", "note": LOCK_NOTE}

    @app.post("/api/v1/execution/lock")
    def exec_lock_set():
        raise HTTPException(410, "EXECUTION_LOCK_WITHDRAWN")

    @app.get("/api/v1/markets")
    def markets():
        return rt.scanner.summary()

    @app.post("/api/v1/markets/scan")
    def markets_scan():
        if rt.bridge.state != "CONNECTED":
            raise HTTPException(503, "MT5_NOT_CONNECTED")
        rt.scanner.scan_now()
        return {"queued": True}

    @app.get("/api/v1/markets/symbols")
    def markets_symbols(all: bool = False):
        try:
            return {"symbols": rt.bridge.list_symbols(visible_only=not all)}
        except Exception as exc:
            raise HTTPException(503, f"SYMBOLS_UNAVAILABLE: {exc}") from exc

    @app.get("/api/v1/markets/detail")
    def markets_detail(symbol: str = Query(...), fresh: bool = False):
        _sym(symbol)
        r = None if fresh else rt.scanner.get(symbol)
        if r is None:
            try:
                r = rt.scanner.analyze_symbol(symbol)
            except Exception as exc:
                raise HTTPException(404, f"SYMBOL_UNAVAILABLE: {exc}") from exc
        return r

    @app.get("/api/v1/markets/chart")
    def markets_chart(symbol: str = Query(...), tf: str = Query("H1"), bars: int = Query(300, ge=50, le=1500)):
        _sym(symbol)
        if tf not in TIMEFRAMES:
            raise HTTPException(400, "INVALID_TIMEFRAME")
        try:
            meta = rt.bridge.symbol_meta(symbol, select=rt.cfg.get().markets.source != "MARKET_WATCH")
            if meta is None:
                raise ValueError("SYMBOL_NOT_FOUND")
            data = rt.bridge.symbol_bars(symbol, tf, bars)
            from ...engine import volzones
            vol = volzones.compute(rt.bridge.symbol_bars(symbol, "D1", 420), rt.cfg.get().volatility, digits=int(meta.get("digits") or 5),
                                   quote=rt.bridge.symbol_quote(symbol, meta.get("point")))
        except Exception as exc:
            raise HTTPException(404, f"SYMBOL_UNAVAILABLE: {exc}") from exc
        sig = rt.signals.list(symbol=symbol, limit=10)["items"]
        return {"symbol": symbol, "tf": tf, "meta": meta, "bars": data, "volatility": vol,
                "bot_signals": [x for x in sig if x["status"] == "OPEN"][:3], "synthetic": rt.bridge.synthetic}

    @app.get("/api/v1/signal-history")
    def signal_history(strategy: str | None = None, status: str | None = None, tf: str | None = None, limit: int = Query(100, ge=1, le=1000)):
        where, args = ["synthetic=?"], [int(bool(rt.bridge.synthetic))]
        for col, val in (("strategy_id", strategy), ("status", status), ("entry_tf", tf)):
            if val:
                where.append(f"{col}=?")
                args.append(val)
        rows = rt.db.query(f"SELECT record_json FROM signal_history WHERE {' AND '.join(where)} ORDER BY updated_at DESC LIMIT ?", (*args, limit))
        return {"items": [json.loads(r["record_json"]) for r in rows]}

    @app.get("/api/v1/context-tf")
    def context_tf_view():
        d = rt.engine.current_decision() or {}
        return {"context": d.get("context_tf"), "signal": d.get("signal")}

    @app.get("/api/v1/bot-signals")
    def bot_signals(symbol: str | None = None, limit: int = Query(50, ge=1, le=500), rejected: bool = True):
        if symbol:
            _sym(symbol)
        return {**rt.signals.list(symbol=symbol, limit=limit, include_rejected=rejected), **rt.signals.status()}

    @app.get("/api/v1/bot-signals/{signal_id}")
    def bot_signal_get(signal_id: str):
        r = rt.signals.get(signal_id)
        if not r:
            raise HTTPException(404, "NOT_FOUND")
        return r

    @app.get("/api/v1/signals")
    def signals(limit: int = 30):
        from ...engine.lifecycle import public_setup
        limit = max(1, limit)                       # 1.46: a negative limit reached SQLite as LIMIT -1 = the WHOLE setups table
        legacy = [public_setup(r) for r in rt.engine.lifecycle.recent(min(limit, 100))]
        active = [{"setup_id": r["setup_id"], "created_at": r["first_seen_at"], "strategy_id": r["record"]["strategy_id"],
                   "profile": f"ACTIVE {r['record']['timeframe']}", "direction": r["record"]["direction"],
                   "state": r["stage"] if r["status"] == "ACTIVE" else r["status"], "invalidation_level": r["record"].get("invalidation_level"),
                   "terminal_reason": r.get("terminal_reason"), "synthetic": bool(r["record"].get("synthetic"))}
                  for r in rt.engine.active.tracker.recent(min(limit, 100))]
        setups = sorted(active + legacy, key=lambda x: x["created_at"] or "", reverse=True)[:limit]
        decs = rt.db.query("SELECT decision_id, created_at, setup_id, analysis_direction, signal_stage, decision, execution_permission FROM decisions "
                           "WHERE decision IN ('BUY','SELL') OR signal_stage IN ('CONFIRMED','INVALIDATED','EXPIRED') ORDER BY created_at DESC LIMIT 50")
        trades = rt.db.query("SELECT * FROM trades ORDER BY closed_at DESC LIMIT 50")
        return {"setups": setups, "decisions": decs, "attempts": rt.gateway.recent_attempts(30), "trades": trades}

    @app.get("/api/v1/decision")
    def decision():
        return rt.engine.current_decision()

    @app.get("/api/v1/stats")
    def get_stats(mode: str = "PAPER"):
        if mode not in ("PAPER", "AUTO_DEMO", "AUTO_LIVE"):
            raise HTTPException(400, "INVALID_MODE")
        b = rt.bridge
        # 1.46: ROI counted deposits older than the deal history (deals_history_days) as profit -> the deals copy and their coverage come
        # from ONE atomic snapshot under the bridge lock; 1.46 arch (I0081): one ROI function shared with the Telegram report
        snap = stats.bridge_deals_snapshot(b)
        deals = snap[0]
        ds = b.server_day_start_utc()
        ds_raw = ds.timestamp() + b.clock.offset if ds and b.clock.offset is not None else None
        return {"bot": stats.bot_stats(rt.db, mode, b.account_key), "engines": stats.engine_stats(rt.db, mode, b.account_key),
                "equity": stats.equity_curve(rt.db, "PAPER" if mode == "PAPER" else "ACCOUNT", b.account_key),
                "account": stats.account_stats(deals, rt.cfg.get().mt5.symbol, ds_raw) if b.account_key else None,
                "account_roi": stats.account_roi_for_bridge(rt.db, b, snapshot=snap)}

    @app.get("/api/v1/news")
    def news():
        return rt.news.summary()

    @app.get("/api/v1/logs")
    def logs(limit: int = 200):
        return logs_list(min(max(limit, 1), 2000))
