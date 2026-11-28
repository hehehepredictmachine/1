"""API routes: SCALPING / HEDGING.

register(app, ctx): SCALPING / HEDGING PMW-SH-1, telemetria, cienie scalp / prognoz, przeładowanie prognoz
    (21 routes; create_app before the split, 7ba7ab0: lines 1154-1404)

The handlers are the ones create_app defined before the split (Etap 4 krok B, docs/arch146/ETAP2_PROJEKT.md §3 / §5):
same function names, signatures, decorators, Pydantic models, error codes and body - the block of create_app is copied
verbatim, the only edit is one more dot in a relative import (the package is one level deeper). The create_app locals the
block used (rt, helpers, handlers called by name) are bound from ctx at the top of the function under the same names;
registration order: api/routes/__init__.REGISTRATION.
"""
from __future__ import annotations

import json
import re
import time

from fastapi import Body, HTTPException, Query

from ... import paths
from ...config import ALLOWED_ASSETS


def register(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 1154-1404: 21 routes."""
    rt = ctx.rt
    _asset = ctx._asset

    # ------------------------------------------------------------------ PMW-SH-1 SCALPING / HEDGING
    _telemetry_cache: dict = {"t": 0.0, "models": None}

    @app.get("/api/v1/telemetry")
    def telemetry():
        """Compact, read-only view for the main menu's model-flow maps: real publishing activity per event topic (count, last time),
        the model registry with each module's status (cached 15 s - probing is not free), the SCALPING / HEDGING service state and
        the engine's decision nodes. No values are invented: a missing part is null."""
        from ...sh import models as SHM
        inst = rt.sh.instrument()
        now = time.time()
        if _telemetry_cache["models"] is None or now - _telemetry_cache["t"] > 15 or _telemetry_cache.get("inst") != inst:
            try:
                mx = SHM.matrix(rt, inst)
                _telemetry_cache.update(t=now, inst=inst, models={"mode": mx.get("mode"), "rows": [
                    {k: r.get(k) for k in ("id", "name", "kind", "output", "group", "train", "status", "reason")} |
                    {"roles": {st: (r.get(st) or {}) for st in ("SCALPING", "HEDGING")}} for r in mx["rows"]]})
            except Exception as exc:  # noqa: BLE001 - the menu shows the error instead of a fake registry
                _telemetry_cache.update(t=now, inst=inst, models={"mode": None, "rows": [], "error": f"{type(exc).__name__}: {exc}"[:200]})
        sh = rt.sh.public()
        ev = {k: {"status": v.get("status"), "status_reason": v.get("status_reason"), "side": v.get("side"),
                  "score": (v.get("score") or {}).get("value") if isinstance(v.get("score"), dict) else v.get("score")}
              for k, v in (sh.get("last_eval") or {}).items()}
        d = getattr(rt.engine, "decision", None) or {}
        return {"server_time": time.time(), "boot_id": rt.bus.boot_id, "seq": rt.bus.seq, "instrument": inst, "topics": rt.bus.activity(),
                "models": _telemetry_cache["models"],
                "sh": {"status": sh.get("status"), "reason": sh.get("reason"), "mode": sh.get("mode"), "last_eval": ev},
                "engine": {"decision": d.get("decision"), "signal_stage": d.get("signal_stage"), "data_quality": d.get("data_quality"),
                           "tree": [{"node": n.get("node"), "status": n.get("status")} for n in (d.get("decision_tree") or [])]} if d else None}

    @app.get("/api/v1/sh")
    def sh_get():
        """Strategy panel: service state, last evaluation per strategy (checklist, levels, models, risk, coordination), open plans
        with position / basket state, single config source with hash, model matrix and the event-model status."""
        from ...sh import config as SHC, models as SHM, tpmodel as SHT
        inst = rt.sh.instrument()
        st = rt.sh.public()
        return {**{k: v for k, v in st.items() if k != "snapshot"}, "config": SHC.load(), "config_errors": SHC.validate(SHC.load()),
                "models": SHM.matrix(rt, inst), "tp_model": SHT.status(inst), "snapshot": rt.sh.snapshot, "server_time": time.time()}

    @app.get("/api/v1/sh/scenario")
    def sh_scenario(strategy: str = Query("SCALPING"), volume: float | None = Query(None, gt=0, le=1000)):
        """Price-move scenario 2.5-10 USD on top of the strategy's setup: per level the move, leg volume, account result from the tick
        value, spread / commission / slippage separately, Monte Carlo P(TP before SL) (model or calibrated) and the models each
        with its own event. Analysis only - orders stay with the SCALPING cycle."""
        if strategy not in ("SCALPING", "HEDGING"):
            raise HTTPException(400, "BAD_STRATEGY")
        from ...sh import scenario as SHS
        return SHS.build(rt, strategy, volume)

    _SH_TFS = ("M1", "M3", "M5", "M15", "H1")

    def _sh_vid(v):
        from ...sh.pack import catalog as _CAT
        if v is None:
            return None
        if v not in _CAT.IDS and v not in ("LEGACY_SCALPING", "LEGACY_HEDGING"):
            raise HTTPException(400, "STRATEGY_ID_UNKNOWN")
        return v

    def _sh_tf(v):
        if v is None:
            return None
        if v not in _SH_TFS:
            raise HTTPException(400, "INVALID_TIMEFRAME")
        return v

    @app.get("/api/v1/sh/signals")
    def sh_signals(strategy: str | None = None, strategy_id: str | None = None, tf: str | None = None, symbol: str | None = None,
                   limit: int = Query(100, ge=1, le=1000)):
        """SH signal history; 1.38 filters: strategy (family), strategy_id (PMW_.. or LEGACY_SCALPING / LEGACY_HEDGING), tf, symbol."""
        if strategy is not None and strategy not in ("SCALPING", "HEDGING"):
            raise HTTPException(400, "BAD_STRATEGY")
        rows = rt.sh.store.recent_signals(strategy, 0.0, limit, strategy_id=_sh_vid(strategy_id), tf=_sh_tf(tf), symbol=symbol)
        return {"items": rt.sh.store.signals_with_levels(rows)}

    @app.get("/api/v1/sh/strategies")
    def sh_strategies():
        """Catalog of the 20 variants (one owner of names / TFs / parameters / readiness / validation) + the live evaluation state."""
        from ...sh.pack import catalog as _CAT
        pk = getattr(rt.sh, "pack", None)
        out = {**_CAT.public(), "live": pk.public() if pk is not None else None}
        try:                                              # 1.39: VOL_GARCH state for HG09 (volatility_method VOL_GARCH) - read only
            out["garch"] = rt.sh.garch_artifact(rt.sh.instrument() or "XAUUSD")
        except Exception as exc:  # noqa: BLE001 - the catalog stays available
            out["garch"] = {"status": "ERROR", "error": type(exc).__name__}
        return out

    @app.post("/api/v1/sh/strategies/config")
    def sh_strategies_config(body: dict = Body(...)):
        """Variant parameter override (validated, versioned). New candidates only - open plans keep their frozen variant."""
        from ...sh.pack import catalog as _CAT
        try:
            cfg = _CAT.save_override(body, who="panel")
        except (ValueError, KeyError, TypeError, AttributeError) as exc:      # w2 (I0818): a bad type is a 400, never a 500
            raise HTTPException(400, str(exc)[:400])
        rt.log.info("SH", "PACK_CONFIG", f"Zmiana konfiguracji pakietu 20 wariantów – hash {cfg['hash']}")
        return _CAT.public(cfg)

    @app.get("/api/v1/sh/pack/stats")
    def sh_pack_stats(strategy_id: str | None = None):
        """Closed plans of the variants grouped by variant / TF / execution mode (PAPER is never mixed with AUTO_DEMO / AUTO_LIVE).
        Whole-cycle results (one plan = one result, partials are not separate wins); R from the plan's own initial risk."""
        vid = _sh_vid(strategy_id)
        rows = rt.db.query("SELECT strategy_id, signal_tf, exec_mode, result FROM sh_plans WHERE strategy_id IS NOT NULL AND result IS NOT NULL"
                           + (" AND strategy_id=?" if vid else ""), (vid,) if vid else ())
        out: dict = {}
        for r in rows:
            res = json.loads(r["result"]) if r.get("result") else {}
            k = f"{r['strategy_id']}|{r['signal_tf']}|{r['exec_mode']}"
            g = out.setdefault(k, {"strategy_id": r["strategy_id"], "signal_tf": r["signal_tf"], "exec_mode": r["exec_mode"], "n": 0, "wins": 0,
                                   "sum_r": 0.0, "n_r": 0, "net_money": 0.0, "n_money": 0, "hedge_activations": 0})
            g["n"] += 1
            if res.get("r_multiple") is not None:
                g["n_r"] += 1
                g["sum_r"] += float(res["r_multiple"])
                g["wins"] += 1 if float(res["r_multiple"]) > 0 else 0
            if res.get("net_money") is not None:   # 1.46: a plan without a money result was summed as 0 (a group of such plans showed 0.00)
                g["n_money"] += 1
                g["net_money"] += float(res["net_money"])
            g["hedge_activations"] += int(res.get("hedge_activations") or 0)
        for g in out.values():
            g["expectancy_r"] = round(g["sum_r"] / g["n_r"], 4) if g["n_r"] else None
            g["net_money"] = round(g["net_money"], 2) if g["n_money"] else None      # missing = null, never 0 (n_money = coverage)
        return {"items": sorted(out.values(), key=lambda x: (x["strategy_id"], x["signal_tf"] or "", x["exec_mode"])),
                "note": "wynik całego cyklu planu; PAPER oddzielnie od rachunku – nie jest walidacją OOS (patrz replay pakietu)"}

    @app.get("/api/v1/sh/pack/evaluations")
    def sh_pack_evaluations(strategy_id: str | None = None, tf: str | None = None):
        """Current evaluation of every variant x signal TF (READY / WAIT / NO_TRADE / INVALIDATED / EXPIRED with reason codes). Read-only:
        a GET never runs a scan, a training or an order."""
        pk = getattr(rt.sh, "pack", None)
        if pk is None:
            return {"items": []}
        vid, f = _sh_vid(strategy_id), _sh_tf(tf)
        items = []
        for (k, stf), su in sorted(pk.last.items()):
            if (vid and k != vid) or (f and stf != f):
                continue
            items.append({k2: su.get(k2) for k2 in ("strategy_id", "strategy", "signal_id", "side", "status", "status_reason", "entry_ref", "sl",
                                                  "tps", "valid_until", "checklist", "risk", "coordination", "created_at")} | {"pack": su.get("pack")})
        return {"items": items, "timing": pk.timing()}

    @app.get("/api/v1/sh/signals/{sid}")
    def sh_signal(sid: str):
        r = rt.sh.store.signal(sid)
        if not r:
            raise HTTPException(404)
        return r

    @app.get("/api/v1/plans/chart")
    def plans_chart(layer: str = Query("SCALP"), history: int = Query(10, ge=0, le=100), strategy_id: str | None = None, tf: str | None = None,
                    plan_id: str | None = None, symbol: str | None = None, family: str | None = None):
        """PMW-PLAN-1 chart layers: Pepe Scalp Plan (SCALPING) / Pepe Hedge Plan (HEDGING) - levels from the strategy plan and fills.
        1.38: layer=PACK (or any strategy_id / tf / plan_id filter) -> PMW-PLAN-2 views of the 20 variants (family from layer SCALP/HEDGE)."""
        from ...plans import service as _PS
        if layer.upper() == "PACK" or strategy_id or tf or plan_id:
            fam = {"SCALP": "SCALPING", "HEDGE": "HEDGING", "SCALPING": "SCALPING", "HEDGING": "HEDGING"}.get((family or layer).upper())
            # 1.46: basket plans are 'PL-BK' + 20 hex (sh/service.py) - the filter refused existing basket plans with PLAN_ID_INVALID
            if plan_id is not None and not re.match(r"^PL-(BK[0-9a-f]{20}|[0-9a-f]{14})$", plan_id):
                raise HTTPException(400, "PLAN_ID_INVALID")
            return _PS.collect_pack(rt.sh, strategy_id=_sh_vid(strategy_id), family=fam, tf=_sh_tf(tf), plan_id=plan_id, history=history, symbol=symbol)
        strat = {"SCALP": "SCALPING", "HEDGE": "HEDGING", "SCALPING": "SCALPING", "HEDGING": "HEDGING"}.get(layer.upper())
        if strat is None:
            raise HTTPException(400, "LAYER_INVALID")
        return _PS.collect(rt.sh, strat, history=history)

    @app.get("/api/v1/sh/plans")
    def sh_plans(open_only: bool = False, limit: int = Query(50, ge=1, le=500)):
        q = rt.sh.quote(time.time())
        if open_only:
            return {"items": [rt.sh.plan_view(p, q) for p in rt.sh.store.open_plans()]}
        rows = rt.db.query("SELECT plan_id FROM sh_plans ORDER BY created_at DESC LIMIT ?", (limit,))
        return {"items": [rt.sh.plan_view(rt.sh.store.plan(r["plan_id"]), q) for r in rows]}

    @app.get("/api/v1/sh/plans/{pid}")
    def sh_plan(pid: str):
        r = rt.sh.store.plan(pid)
        if not r:
            raise HTTPException(404)
        v = rt.sh.plan_view(r, rt.sh.quote(time.time()))
        v.update(result=r.get("result"), actions=rt.sh.store.actions(pid), events=rt.sh.store.events(pid))
        return v

    @app.post("/api/v1/sh/plans/{pid}/close")
    def sh_plan_close(pid: str):
        """Explicit, user-confirmed close of one SH plan (primary + hedge) through its state machine (no Execution Lock since 1.24; the plan account must match)."""
        r = rt.sh.close_plan(pid, "MANUAL_CLOSE")
        rt.log.warn("SH", "MANUAL_CLOSE", f"Zamknięcie planu {pid} na żądanie: {r}")
        return r

    @app.get("/api/v1/sh/validation")
    def sh_validation(instrument: str = Query("XAUUSD")):
        """Validation reports of the SH strategies on REAL exported data (written by `sh train`); absent = not run yet."""
        if instrument not in ALLOWED_ASSETS:
            raise HTTPException(400, "UNKNOWN_INSTRUMENT")
        out = {}
        for strat in ("SCALPING", "HEDGING"):
            p = paths.data_dir() / "sh" / "validation" / f"{instrument}_{strat}.json"
            try:
                out[strat] = {"status": "VERIFIED_REPLAY", "report": json.loads(p.read_text(encoding="utf-8"))} if p.exists() else \
                    {"status": "NOT_RUN", "reason": "brak raportu walidacji na danych z terminala – uruchom zadanie sh_models (30_SH_WALIDACJA.bat)"}
            except (OSError, ValueError) as exc:
                out[strat] = {"status": "ERROR", "reason": str(exc)[:200]}
        return {"instrument": instrument, "strategies": out}

    @app.get("/api/v1/sh/config")
    def sh_config_get():
        from ...sh import config as SHC
        return SHC.load()

    @app.post("/api/v1/sh/config")
    def sh_config_set(body: dict = Body(...)):
        """Panel change of the single SH config source (validated, versioned). Open plans keep their frozen parameters."""
        from ...sh import config as SHC
        try:
            cfg = SHC.save_override(body, who="panel")
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        rt.log.info("SH", "CONFIG", f"Zmiana konfiguracji SH – wersja {cfg['_override_version']}, hash {cfg['_hash']}")
        return cfg

    @app.post("/api/v1/sh/config/rollback")
    def sh_config_rollback():
        from ...sh import config as SHC
        try:
            return SHC.rollback_override()
        except ValueError as exc:
            raise HTTPException(409, str(exc))

    @app.get("/api/v1/sh/chart")
    def sh_chart(tf: str = Query("M1"), limit: int = Query(240, ge=20, le=1000)):
        if tf not in ("M1", "M3", "M5", "M15"):
            raise HTTPException(400, "INVALID_TIMEFRAME")
        bars = [b for b in rt.bridge.bars(tf, limit, include_forming=True) if b.get("open_utc")]
        return {"tf": tf, "bars": bars, "quote": rt.sh.quote(time.time()), "last_eval": rt.sh.last_eval,
                "open_plans": [rt.sh.plan_view(p, rt.sh.quote(time.time())) for p in rt.sh.store.open_plans()]}

    @app.get("/api/v1/scalp/shadow")
    def scalp_shadow(limit: int = Query(100, ge=1, le=1000), asset: str | None = None):
        # 1.46 arch (I0040): rows of the requested asset only (default: the active one), like the summary next to them
        return {"items": rt.scalp.recent(limit, instrument=_asset(asset)), "summary": rt.scalp.summary()}

    @app.get("/api/v1/forecast/shadow")
    def forecast_shadow(limit: int = Query(100, ge=1, le=1000), asset: str | None = None):
        return {"items": rt.forecast.recent(limit, instrument=_asset(asset))}

    @app.post("/api/v1/forecast/reload")
    def forecast_reload():
        rt.forecast.reload()
        rt.log.info("FORECAST", "RELOAD", "Przeładowanie modelu prognoz – nowa wersja od następnej zamkniętej świecy M5.")
        return {"ok": True}
