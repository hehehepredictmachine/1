"""API routes: stan bota i dane wykresu.

register(app, ctx): stan bota (/state), świece, zmienność, rejestr TF, prognozy świec; pomocniki _asset / _check_asset / _nss_compact
    (5 routes; create_app before the split, 7ba7ab0: lines 284-375)

The handlers are the ones create_app defined before the split (Etap 4 krok B, docs/arch146/ETAP2_PROJEKT.md §3 / §5):
same function names, signatures, decorators, Pydantic models, error codes and body - the block of create_app is copied
verbatim, the only edit is one more dot in a relative import (the package is one level deeper). The create_app locals the
block used (rt, helpers, handlers called by name) are bound from ctx at the top of the function under the same names;
registration order: api/routes/__init__.REGISTRATION.
"""
from __future__ import annotations

from fastapi import HTTPException, Query

from ...config import ALLOWED_ASSETS
from ...timeutil import TIMEFRAMES, iso, utcnow
from ...version import API_CONTRACT_VERSION, APP_VERSION


def register(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 284-375: 5 routes."""
    rt = ctx.rt

    # ------------------------------------------------------------ state
    def full_state() -> dict:
        b = rt.bridge
        cfg = rt.cfg.get()
        acct = b.account_status()
        mode = rt.modes.status()
        return {"contract": API_CONTRACT_VERSION, "app_version": APP_VERSION, "seq": rt.bus.seq, "boot_id": rt.bus.boot_id,
                "synthetic": rt.demo or b.synthetic, "server_time": iso(utcnow()),
                "connection": b.connection_status(), "account": acct, "symbol": b.symbol_status_dict(), "quote": b.quote_status(),
                "tf_meta": b.tf_meta(), "analysis": rt.engine.analysis_summary(), "decision": rt.engine.current_decision(),
                "prefs": {**rt.prefs.all(), "exposure": rt.prefs.exposure_limit()},
                "engine": {"last_error": rt.engine.last_error, "cycle_ms": rt.engine.cycle_ms, "full_cycles": rt.engine.full_count},
                "agent": rt.agent.status(), "agent_last": rt.agent.public_result(rt.agent.last_result), "mode": mode,
                "risk_config": cfg.risk.model_dump(), "costs_config": cfg.costs.model_dump(), "strategy_config": cfg.strategy.model_dump(),
                "news": rt.news.summary(), "positions": {"positions": b.positions, "orders": b.orders},
                "managed": rt.db.query("SELECT * FROM managed_positions WHERE state='OPEN'"),
                "attempts": rt.gateway.recent_attempts(15), "paper": rt.paper.account() if mode["mode"] == "PAPER" else None,
                "logs": logs_list(60), "pc_clock": rt.pcclock.snapshot(), "manager": {"reconciled_epoch": rt.manager.reconciled_epoch,
                                                                                     "last_error": rt.manager.last_error},
                "first_run_completed": cfg.first_run_completed,
                "auto": rt.engine.active.status(compact=True), "active_config": cfg.active.model_dump(mode="json"),
                "ml": rt.ml.status(compact=True), "markets": rt.scanner.summary(),
                "bot_signals": {**rt.signals.status(), **rt.signals.list(limit=40)},
                "assets": rt.assets.state(), "lab": rt.lab.summary(cfg.assets.active),
                "lab_neural": _nss_compact(cfg.assets.active)}

    def logs_list(limit: int) -> list[dict]:
        return rt.db.query("SELECT id, ts, level, category, code, message FROM app_events ORDER BY id DESC LIMIT ?", (limit,))

    @app.get("/api/v1/state")
    def state():
        return full_state()

    def _walls_last() -> dict:
        """The walls snapshot S12 works on - rt.walls.last, read exactly like GET /api/v1/walls. Never WallsService.snapshot() / context()
        / store.freeze from an API thread (they compute, version and store snapshots - that is the engine thread's job)."""
        snap = {k: v for k, v in (getattr(rt.walls, "last", None) or {}).items() if not k.startswith("_")}
        return snap or {"status": "NO_SNAPSHOT_YET", "walls": []}

    @app.get("/api/v1/candles")
    def candles(tf: str = Query(...)):
        if tf not in TIMEFRAMES:
            raise HTTPException(400, "INVALID_TIMEFRAME")
        # 1.46 arch (I0109): the chart also gets the S12 walls snapshot (same object as /api/v1/walls, signed by snapshot_id) - the
        # 'volatility' bands stay the panel's model pricing (cfg.volatility, chart only)
        return {**rt.engine.chart(tf), "walls_snapshot": _walls_last()}

    @app.get("/api/v1/volatility")
    def volatility():
        return rt.engine.volatility()

    # ------------------------------------------------------------ 1.10: walls for strategies, IV import, structure (S/R, range, patterns)
    @app.get("/api/v1/timeframes")
    def timeframes():
        """TF registry (role per TF) + which TFs each strategy needs - the chart pages are built from this, never from a
        hard-coded list. Data status per TF from the engine's data-quality gate."""
        from ...strategies import registry as _reg
        from ...timeutil import TF_REGISTRY
        dq = (rt.engine.dq or {}).get("timeframes") or {}
        strat = {d["strategy_id"]: {"setup_tfs": d["setup_tfs"], "required_tfs": d["required_tfs"], "context_tf": d["context_tf"], "name": d["name"]}
                 for d in _reg.describe()}
        return {"timeframes": [{"tf": tf, "seconds": v["seconds"], "role": v["role"], "core": v["core"],
                                "data": (dq.get(tf) or {}).get("status"), "closed_bars": (dq.get(tf) or {}).get("closed_bars"),
                                "required": (dq.get(tf) or {}).get("required"), "used_by": sorted(sid for sid, x in strat.items()
                                                                                                     if tf in x["setup_tfs"] or tf in x["required_tfs"] or tf == x["context_tf"])}
                               for tf, v in TF_REGISTRY.items()], "strategies": strat}

    @app.get("/api/v1/forecast")
    def forecast_get():
        """SHADOW candle analytics + price forecasts 5/15/30 + Double Retest v2 research state. Never an order permission."""
        return {**rt.forecast.public(), "registry": rt.forecast.registry(), "training": rt.forecast.training_status(),
                "config": rt.cfg.get().forecast.model_dump(), "shadow_summary": rt.forecast.shadow_summary()}

    # ------------------------------------------------------------ 1.13 analytics + pattern library (observational)
    # ------------------------------------------------------------ 1.14 lab (XAUUSD / BTC)
    def _nss_compact(asset: str) -> dict | None:
        snap = (rt.nss.last or {}) if getattr(rt, "nss", None) is not None and rt.nss.inst == asset else {}
        return {k: snap.get(k) for k in ("inference_id", "seq", "asset", "setup_id", "side", "technical_status", "mode", "model_hash", "computed_at",
                                         "expires_at")} if snap else None

    def _asset(asset: str | None) -> str:
        a = asset or rt.cfg.get().assets.active
        if a not in ALLOWED_ASSETS:
            raise HTTPException(403, f"ASSET_NOT_ALLOWED:{a}")
        return a

    def _check_asset(a, path: str) -> str:
        # 1.46: SymbolNotAllowed (a PermissionError) from the asset registry was not caught - an asset outside the list (403) or one without
        # a broker symbol (409, e.g. BTC unmapped) answered 500 in Structure Intelligence / flow / lab / trade pad routes
        try:
            return rt.assets.check_asset(a, path)
        except PermissionError as exc:
            raise HTTPException(403 if str(exc).startswith("ASSET_NOT_ALLOWED") else 409, str(exc)) from None

    ctx.full_state = full_state
    ctx.logs_list = logs_list
    ctx._asset = _asset
    ctx._check_asset = _check_asset
