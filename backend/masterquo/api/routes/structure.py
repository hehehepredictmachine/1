"""API routes: struktura rynku.

register(app, ctx): Structure Intelligence, sekcje R21-R25, Flow Context, VAMD / FD / SMC / Buffer Inspector, zadania SI
    (41 routes; create_app before the split, 7ba7ab0: lines 705-993)

The handlers are the ones create_app defined before the split (Etap 4 krok B, docs/arch146/ETAP2_PROJEKT.md §3 / §5):
same function names, signatures, decorators, Pydantic models, error codes and body - the block of create_app is copied
verbatim, the only edit is one more dot in a relative import (the package is one level deeper). The create_app locals the
block used (rt, helpers, handlers called by name) are bound from ctx at the top of the function under the same names;
registration order: api/routes/__init__.REGISTRATION.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import Body, HTTPException, Query


def register(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 705-993: 41 routes."""
    rt = ctx.rt
    _asset = ctx._asset
    _check_asset = ctx._check_asset

    # ------------------------------------------------------------ PMW-UPD-07 structure intelligence (GET never trains)
    def _si_inst(asset):
        a = asset or rt.cfg.get().assets.active
        _check_asset(a, "STRUCTURE_INTELLIGENCE")
        return a

    @app.get("/api/v1/structure-intelligence")
    def si_latest():
        snap = rt.si.last
        return {"snapshot": snap, "status": "OK" if snap else "NO_SNAPSHOT_YET",
                "jobs": [rt.si.job(j) for j in list(rt.si.jobs)[-5:]]}

    @app.get("/api/v1/structure-intelligence/snapshots/{sid}")
    def si_snapshot(sid: str):
        r = rt.db.one("SELECT payload FROM si_snapshots WHERE snapshot_id=?", (sid,))
        if not r:
            raise HTTPException(404, "SNAPSHOT_NOT_FOUND")
        return json.loads(r["payload"])

    @app.get("/api/v1/structure-intelligence/forecasts")
    def si_forecasts(asset: str | None = None, limit: int = Query(50, ge=1, le=500)):
        return {"items": rt.si.forecasts(_si_inst(asset), limit)}

    @app.get("/api/v1/structure-intelligence/models")
    def si_models(asset: str | None = None):
        from ...lab import structure_task as T
        a = _si_inst(asset)
        reg = T._reg(a)
        return {"instrument": a, "shadow": reg.get("shadow"), "runs": reg.get("runs"), "holdout_access": list((reg.get("holdout_access") or {}).keys()),
                "indicator_profile": T.indicator_profile(a), "families": list(T.FAMILIES_ALL), "execution": "NEVER_AUTOMATIC"}

    @app.post("/api/v1/structure-intelligence/models/select")
    def si_select(body: dict = Body(...)):
        from ...lab import structure_task as T
        try:
            return T.select_shadow(_si_inst(body.get("asset")), str(body.get("candidate_id")))
        except (ValueError, OSError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/v1/structure-intelligence/models/rollback")
    def si_rollback(body: dict = Body(...)):
        from ...lab import structure_task as T
        try:
            return T.rollback(_si_inst(body.get("asset")), str(body.get("task") or T.TASK_MOVE))
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/v1/structure-intelligence/neutralization")
    def si_neutral(asset: str | None = None, limit: int = Query(120, ge=1, le=2000)):
        return rt.si.neutralization(_si_inst(asset), limit)

    @app.get("/api/v1/structure-intelligence/quotes")
    def si_quotes():
        return rt.si.quotes_public()

    @app.get("/api/v1/structure-intelligence/quote-forecasts")
    def si_quote_fc(limit: int = Query(100, ge=1, le=1000), asset: str | None = None):
        # 1.46 arch (I0030 / I0040): only the requested asset (default: the active one and its current symbol = the QuoteEngine context)
        cfg = rt.cfg.get()
        a = _asset(asset)
        if a == cfg.assets.active:
            return {"items": rt.si.quote_forecasts(limit, context=f"{a}|{cfg.mt5.symbol}")}
        return {"items": rt.si.quote_forecasts(limit, instrument=a)}

    @app.get("/api/v1/structure-intelligence/quote-quality")
    def si_quote_q():
        return rt.si.quote_quality()

    # ------------------------------------------------------------ PMW-UPD-09 R21-R25 sections (read-only; GET never trains)
    def _mkey(asset, tf):
        a = _si_inst(asset)
        if tf not in ("M1", "M5", "M15", "H1"):
            raise HTTPException(400, "TF_INVALID")
        k = rt.si.market.keys.get((a, tf))
        if k is None:
            raise HTTPException(404, "NO_MARKET_STATE_YET (sekcja powstaje przy pierwszym snapshocie Structure Intelligence)")
        return k

    @app.get("/api/v1/structure-intelligence/regimes")
    def si_regimes(asset: str | None = None, tf: str = "M1", limit: int = Query(300, ge=1, le=600)):
        return rt.si.market.regimes(_mkey(asset, tf), limit)

    @app.get("/api/v1/structure-intelligence/swings")
    def si_swings(asset: str | None = None, tf: str = "M1", as_of: float | None = None, limit: int = Query(120, ge=1, le=600)):
        return rt.si.market.swings(_mkey(asset, tf), as_of, limit)

    @app.get("/api/v1/structure-intelligence/swings/{sid}")
    def si_swing(sid: str, asset: str | None = None, as_of: float | None = None):
        r = rt.si.market.swing(_si_inst(asset), sid, as_of)
        if r is None:
            raise HTTPException(404, "SWING_NOT_FOUND (kontekst usunięty albo spoza okna)")
        return r

    @app.get("/api/v1/structure-intelligence/smma")
    def si_smma(asset: str | None = None, tf: str = "M1", limit: int = Query(200, ge=1, le=600)):
        return rt.si.market.smma(_mkey(asset, tf), limit)

    @app.get("/api/v1/structure-intelligence/zscore")
    def si_zscore(asset: str | None = None, tf: str = "M1", mode: str = "INCLUSIVE_N", n: int = Query(20, ge=2, le=500)):
        if mode not in ("INCLUSIVE_N", "PREVIOUS_N"):
            raise HTTPException(400, "ZSCORE_MODE_INVALID")
        return rt.si.market.zscore(_mkey(asset, tf), mode, n)

    @app.get("/api/v1/structure-intelligence/native-status")
    def si_native(asset: str | None = None):
        return rt.si.native_status(_si_inst(asset))

    @app.get("/api/v1/structure-intelligence/model-diagnostics")
    def si_model_diag(asset: str | None = None, run: str | None = None):
        from ...lab import structure_task as T
        a = _si_inst(asset)
        reg = T._reg(a)
        rid = run or (sorted(reg["runs"])[-1] if reg["runs"] else None)
        if not rid or rid not in reg["runs"]:
            return {"status": "NO_RUNS"}
        rp = Path(reg["runs"][rid]["run_dir"]) / "report.json"
        rep = json.loads(rp.read_text(encoding="utf-8")) if rp.exists() else {}
        diag = {}
        for f in rep.get("folds", []):
            for fam, res in (f.get("families") or {}).items():
                for r in res:
                    if r.get("diagnostics"):
                        diag.setdefault(fam, []).append({"fold": f["fold"], "seed": r.get("seed"), "status": r.get("status"), **r["diagnostics"]})
        return {"run_id": rid, "role": rep.get("role"), "spike_profile": rep.get("spike_profile"), "transform": rep.get("transform"),
                "diagnostics": diag, "status": rep.get("status")}

    # ------------------------------------------------------------ PMW-UPD-11 flow context (read-only; GET never trains)
    def _fkey(asset, tf):
        a = _si_inst(asset)
        if tf not in ("M1", "M5", "M15", "H1"):
            raise HTTPException(400, "TF_INVALID")
        k = rt.si.flow.keys.get((a, tf))
        if k is None:
            raise HTTPException(404, "NO_FLOW_STATE_YET (powstaje przy pierwszym snapshocie)")
        return k

    @app.get("/api/v1/flow-context")
    def fc_summary(asset: str | None = None):
        a = _si_inst(asset)
        return {"instrument": a, "tfs": {tf: rt.si.flow.summary(k) for (i, tf), k in rt.si.flow.keys.items() if i == a},
                "profile": __import__("masterquo.lab.flow_context.task", fromlist=["profile"]).profile(a)}

    @app.get("/api/v1/flow-context/series")
    def fc_series(asset: str | None = None, tf: str = "M15", limit: int = Query(300, ge=1, le=800)):
        return rt.si.flow.series(_fkey(asset, tf), limit)

    @app.get("/api/v1/flow-context/channels")
    def fc_channels(asset: str | None = None, tf: str = "M15", as_of: str | None = None, mode: str = "CURRENT_MAP_FULL_WIDTH"):
        if mode not in ("CURRENT_MAP_FULL_WIDTH", "HISTORY_AS_KNOWN"):
            raise HTTPException(400, "MODE_INVALID")
        return rt.si.flow.channels(_fkey(asset, tf), as_of, mode)

    @app.get("/api/v1/flow-context/markov")
    def fc_markov(asset: str | None = None):
        return rt.si.flow.markov(_fkey(asset, "M1"))

    @app.get("/api/v1/flow-context/stopdistance")
    def fc_stop(asset: str | None = None, tf: str = "M15", entry: float | None = None, side: str | None = None, strategy_sl_points: float | None = None):
        return rt.si.flow.stopdistance(_fkey(asset, tf), entry, side, strategy_sl_points)

    @app.get("/api/v1/flow-context/native")
    def fc_native(asset: str | None = None):
        a = _si_inst(asset)
        return rt.si.flow.native(a, rt.cfg.get().mt5.symbol)

    @app.get("/api/v1/flow-context/models")
    def fc_models(asset: str | None = None):
        from ...lab.flow_context import task as FT
        a = _si_inst(asset)
        reg = FT._reg(a)
        return {"instrument": a, "runs": reg["runs"], "shadow": reg["shadow"], "families": list(FT.FAMILIES), "task": FT.TASK, "schema": FT.SCHEMA,
                "execution": "NEVER_AUTOMATIC"}

    # ------------------------------------------------------------ PMW-UPD-14 VAMD / FD / SMC / Buffer Inspector (GET never trains)
    def _ckey(asset, tf):
        a = _si_inst(asset)
        if tf not in ("M1", "M5", "M15", "H1"):
            raise HTTPException(400, "TF_INVALID")
        k = rt.si.ctx.keys.get((a, tf))
        if k is None:
            raise HTTPException(404, "NO_CONTEXT_STATE_YET (powstaje przy pierwszym snapshocie)")
        return k

    @app.get("/api/v1/lab/context")
    def ctx_summary(asset: str | None = None):
        from ...lab.context_ind import task as CT
        a = _si_inst(asset)
        return {"instrument": a, "tfs": {tf: rt.si.ctx.summary(k) for (i, tf), k in rt.si.ctx.keys.items() if i == a}, "profile": CT.profile(a)}

    @app.get("/api/v1/lab/vamd")
    def ctx_vamd(asset: str | None = None, tf: str = "M5", limit: int = Query(300, ge=1, le=600)):
        return rt.si.ctx.vamd(_ckey(asset, tf), limit)

    @app.get("/api/v1/lab/fractal-regime")
    def ctx_fd(asset: str | None = None, tf: str = "M5", limit: int = Query(300, ge=1, le=600)):
        return rt.si.ctx.fractal(_ckey(asset, tf), limit)

    @app.get("/api/v1/lab/smc")
    def ctx_smc(asset: str | None = None, tf: str = "M5", as_of: float | None = None, limit: int = Query(300, ge=1, le=800)):
        return rt.si.ctx.smc(_ckey(asset, tf), as_of, limit)

    @app.get("/api/v1/lab/buffers/reports")
    def buf_reports():
        from ...lab.context_ind import buffers as BF
        return {"reports": BF.list_reports(), "note": "raporty importowane z PWM_BufferInspector (MT5); panel nie skanuje terminala zdalnie"}

    @app.get("/api/v1/lab/buffers/reports/{rid}")
    def buf_report(rid: str):
        from ...lab.context_ind import buffers as BF
        r = BF.get_report(rid)
        if r is None:
            raise HTTPException(404, "REPORT_NOT_FOUND")
        return r

    @app.post("/api/v1/lab/buffers/reports/import")
    def buf_import(body: dict = Body(...)):
        from ...extind.contract import EnvelopeError
        from ...lab.context_ind import buffers as BF
        files = os.environ.get("MQ_MT5_FILES_DIR")
        name = str(body.get("file") or "PWM_BUFFER_REPORT.json")
        if not files or not name.replace("_", "").replace("-", "").replace(".", "").isalnum() or not name.endswith(".json"):
            raise HTTPException(400, "FILE_NOT_WHITELISTED_OR_NO_FILES_DIR")
        p = Path(files) / "PMW" / name
        if not p.exists():
            raise HTTPException(404, "REPORT_FILE_MISSING (uruchom PWM_BufferInspector w MT5)")
        try:
            d = BF.import_report(p.read_bytes())
        except EnvelopeError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"report_id": d["report_id"], "coverage": d["coverage"], "instances": len(d.get("instances") or [])}

    @app.get("/api/v1/lab/buffers/mappings")
    def buf_mappings():
        from ...lab.context_ind import buffers as BF
        return {"mappings": BF.mappings(), "required": list(BF.MAPPING_REQUIRED)}

    @app.post("/api/v1/lab/buffers/mappings/validate")
    def buf_validate(body: dict = Body(...)):
        from ...lab.context_ind import buffers as BF
        return BF.validate_mapping(body)

    @app.post("/api/v1/lab/buffers/mappings")
    def buf_save(body: dict = Body(...)):
        from ...lab.context_ind import buffers as BF
        return BF.save_mapping({k: body.get(k) for k in BF.MAPPING_REQUIRED + ("chart_window", "instance", "notes")})

    @app.post("/api/v1/lab/buffers/mappings/{mid}/rollback")
    def buf_rollback(mid: str):
        from ...lab.context_ind import buffers as BF
        try:
            return BF.rollback_mapping(mid)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/api/v1/lab/buffers/source")
    def buf_source(tf: str = "M5"):
        return rt.si.ctx.external(rt.cfg.get().mt5.symbol, tf)

    @app.post("/api/v1/lab/context/calibrate")
    def ctx_calibrate(body: dict = Body(default={})):
        kind = {"calibrate": "context_calibrate", "dataset": "context_dataset", "train": "context_train"}.get(str(body.get("step") or "calibrate"))
        if kind is None:
            raise HTTPException(400, "STEP_INVALID")
        try:
            return rt.si.start_job(kind, {k: body.get(k) for k in ("asset", "families", "profile")})
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/v1/structure-intelligence/quality")
    def si_quality(asset: str | None = None):
        return rt.si.quality(_si_inst(asset))

    @app.post("/api/v1/structure-intelligence/jobs")
    def si_job_start(body: dict = Body(...)):
        try:
            return rt.si.start_job(str(body.get("kind")), {k: body.get(k) for k in ("asset", "task", "families", "profile", "experiment", "sew_operators", "days",
                                                                                  "encoder", "attention", "transform")})
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/v1/structure-intelligence/jobs/{jid}")
    def si_job(jid: str):
        j = rt.si.job(jid)
        if not j:
            raise HTTPException(404, "JOB_NOT_FOUND")
        return j

    @app.post("/api/v1/structure-intelligence/jobs/{jid}/cancel")
    def si_job_cancel(jid: str):
        return {"ok": rt.si.cancel(jid)}
