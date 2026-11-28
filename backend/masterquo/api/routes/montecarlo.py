"""API routes: Monte Carlo.

register(app, ctx): Monte Carlo ścieżek ceny
    (4 routes; create_app before the split, 7ba7ab0: lines 3447-3500)

The handlers are the ones create_app defined before the split (Etap 4 krok B, docs/arch146/ETAP2_PROJEKT.md §3 / §5):
same function names, signatures, decorators, Pydantic models, error codes and body - the block of create_app is copied
verbatim, the only edit is one more dot in a relative import (the package is one level deeper). The create_app locals the
block used (rt, helpers, handlers called by name) are bound from ctx at the top of the function under the same names;
registration order: api/routes/__init__.REGISTRATION.
"""
from __future__ import annotations

from fastapi import HTTPException, Query


def register(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 3447-3500: 4 routes."""
    rt = ctx.rt

    # ------------------------------------------------------------ 1.25 Monte Carlo of price paths (own thread, closed M1 bars of the bridge)
    @app.get("/api/v1/montecarlo/status")
    def montecarlo_status():
        return rt.montecarlo.status()

    @app.get("/api/v1/montecarlo/validations/{run_id}/report")
    def montecarlo_validation_report(run_id: str):
        """1.42: read-only - the stored report.json of one Monte Carlo validation run (reliability / Brier for the MODELS & BACKTEST
        screen). Only a run listed in the instrument's registry is served; nothing is computed or changed."""
        import json as _json
        import re as _re
        from ...montecarlo import validate as _MV
        if not _re.fullmatch(r"MC-[0-9A-Za-z\-]{8,64}", run_id):
            raise HTTPException(400, "INVALID_RUN_ID")
        inst, _ = rt.montecarlo.context()
        d = _MV.root(inst)
        try:
            reg = _json.loads((d / "registry.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            reg = {}
        if run_id not in (reg.get("runs") or {}):
            raise HTTPException(404, "NOT_RUN")
        f = d / "runs" / run_id / "report.json"
        try:
            return {"run_id": run_id, "instrument": inst, "summary": reg["runs"][run_id], "report": _json.loads(f.read_text(encoding="utf-8"))}
        except (OSError, ValueError):
            raise HTTPException(404, "REPORT_FILE_MISSING")

    @app.get("/api/v1/montecarlo/scenarios")
    def montecarlo_scenarios(horizon: int = Query(60, ge=5, le=240)):
        """P(price reaches +X / -X within the horizon) for X = 2.5 / 3 / 5 / 7.5 / 10 (price move, not account profit)."""
        return rt.montecarlo.compute(None, horizon=horizon)            # sync endpoint: FastAPI thread pool, computation in the MC thread

    @app.post("/api/v1/montecarlo/run")
    def montecarlo_run(body: dict):
        side = str(body.get("side") or "").upper()
        if side not in ("BUY", "SELL"):
            raise HTTPException(400, "BAD_SIDE")
        try:
            sl = float(body["sl_distance"])
            tps = [float(x) for x in (body.get("tp_distances") or [])]
            horizon = int(body.get("horizon") or 60)
            n_paths = int(body.get("n_paths") or 2000)
            entry = float(body["entry"]) if body.get("entry") not in (None, "") else None
        except (KeyError, TypeError, ValueError, OverflowError):      # 1.46: OverflowError (horizon: Infinity) was a 500
            raise HTTPException(400, "BAD_PLAN")
        if not (0 < sl <= 1e6 and tps and len(tps) <= 8 and all(0 < x <= 1e6 for x in tps) and 5 <= horizon <= 240 and 200 <= n_paths <= 20000):
            raise HTTPException(400, "BAD_PLAN")
        variant = body.get("variant")
        if variant not in (None, "IID", "BLOCK", "REGIME"):
            raise HTTPException(400, "BAD_VARIANT")
        plan = rt.montecarlo.plan_for(side, sl, tps, entry=entry, horizon=horizon)
        if plan is None:
            return {"status": "NO_QUOTE", "reason": "brak aktualnego notowania Bid/Ask – podaj cenę wejścia albo połącz MT5"}
        return rt.montecarlo.compute([plan], horizon=horizon, variant=variant, n_paths=n_paths)
