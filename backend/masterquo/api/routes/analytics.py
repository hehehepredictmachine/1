"""API routes: analityka i formacje.

register(app, ctx): Black-76, analityka 1.13, biblioteka formacji
    (24 routes; create_app before the split, 7ba7ab0: lines 996-1145)

The handlers are the ones create_app defined before the split (Etap 4 krok B, docs/arch146/ETAP2_PROJEKT.md §3 / §5):
same function names, signatures, decorators, Pydantic models, error codes and body - the block of create_app is copied
verbatim, the only edit is one more dot in a relative import (the package is one level deeper). The create_app locals the
block used (rt, helpers, handlers called by name) are bound from ctx at the top of the function under the same names;
registration order: api/routes/__init__.REGISTRATION.
"""
from __future__ import annotations

from fastapi import Body, HTTPException, Query


def register(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 996-1145: 24 routes."""
    rt = ctx.rt

    # ------------------------------------------------------------ PMW-UPD-07 R05 Black-76 (pure maths; HV is never shown as IV)
    @app.post("/api/v1/black76/price")
    def b76_price(body: dict = Body(...)):
        from ...analytics import black76 as B
        try:
            d = B.discount(body.get("rate"), float(body["t_years"]), body.get("discount"))
            return B.price(float(body["forward"]), float(body["strike"]), float(body["sigma"]), float(body["t_years"]), d)
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(400, f"INVALID_INPUT: {exc}") from exc

    @app.post("/api/v1/black76/iv")
    def b76_iv(body: dict = Body(...)):
        from ...analytics import black76 as B
        try:
            d = B.discount(body.get("rate"), float(body["t_years"]), body.get("discount"))
            return dict(B.implied_vol(float(body["premium"]), float(body["forward"]), float(body["strike"]), float(body["t_years"]), d,
                                      str(body.get("kind") or "call")), source="IV_FROM_PREMIUM", version=B.VERSION)
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(400, f"INVALID_INPUT: {exc}") from exc

    @app.post("/api/v1/black76/forward")
    def b76_forward(body: dict = Body(...)):
        from ...analytics import black76 as B
        try:
            return B.forward_from_parity(list(body.get("pairs") or []), float(body.get("discount") or 1.0), exercise_style=str(body.get("exercise_style") or "UNKNOWN"))
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, f"INVALID_INPUT: {exc}") from exc

    @app.get("/api/v1/analytics")
    def analytics_get():
        return {**rt.analytics.summary(), "config": rt.cfg.get().analytics.model_dump()}

    @app.get("/api/v1/analytics/tf/{tf}")
    def analytics_tf(tf: str):
        if tf not in rt.cfg.get().analytics.timeframes:
            raise HTTPException(404, "TF_NOT_CONFIGURED")
        return rt.analytics.tf_state(tf, full=True)

    @app.get("/api/v1/analytics/history")
    def analytics_history(module: str | None = None, tf: str | None = None, limit: int = Query(100, ge=1, le=1000)):
        return {"items": rt.analytics.history(module, tf, limit)}

    @app.get("/api/v1/analytics/diagnostics")
    def analytics_diag():
        return rt.analytics.diagnostics()

    @app.get("/api/v1/patterns/samples")
    def pat_list(symbol: str | None = None, tf: str | None = None, status: str | None = None, rules_version: str | None = None):
        return {"items": rt.analytics.library.list(symbol, tf, status, rules_version), "jobs": rt.analytics.library.jobs(10)}

    @app.post("/api/v1/patterns/samples")
    def pat_add(body: dict = Body(...)):
        """Sample from the chart selection: {tf, start_utc, end_utc, note} - closed bars of the bot's feed (raw OHLCV kept)."""
        tf = str(body.get("tf") or "")
        bars = [b for b in rt.bridge.bars(tf, None, include_forming=False) if b.get("open_utc")] if tf in ("M1", "M5", "M15", "M30", "H1", "H4", "D1") else []
        sel = [{k: b[k] for k in ("open_utc", "o", "h", "l", "c", "tv")} for b in bars if str(body.get("start_utc")) <= b["open_utc"] <= str(body.get("end_utc"))]
        if not sel:
            raise HTTPException(400, "NO_CLOSED_BARS_IN_RANGE")
        r = rt.analytics.library.add_sample(rt.cfg.get().mt5.symbol, tf, sel, "CHART_SELECTION" if not rt.bridge.synthetic else "CHART_SELECTION_SYNTHETIC",
                                            body.get("note"))
        if not r["ok"]:
            raise HTTPException(400, r["error"])
        return r

    @app.get("/api/v1/patterns/samples/{sid}")
    def pat_get(sid: int):
        s = rt.analytics.library.get(sid)
        if not s:
            raise HTTPException(404, "SAMPLE_NOT_FOUND")
        return s

    @app.delete("/api/v1/patterns/samples/{sid}")
    def pat_del(sid: int):
        return {"ok": rt.analytics.library.delete(sid)}

    @app.post("/api/v1/patterns/samples/{sid}/validate")
    def pat_validate_one(sid: int):
        r = rt.analytics.library.validate_one(sid)
        if not r["ok"]:
            raise HTTPException(404, r["error"])
        return r

    @app.post("/api/v1/patterns/validate")
    def pat_validate(body: dict = Body(...)):
        ids = body.get("ids")
        if ids is not None and (not isinstance(ids, list) or not all(isinstance(i, int) for i in ids)):
            raise HTTPException(400, "IDS_MUST_BE_INT_LIST_OR_NULL")
        return rt.analytics.library.start_job(ids)

    @app.get("/api/v1/patterns/jobs/{job_id}")
    def pat_job(job_id: str):
        j = rt.analytics.library.job(job_id)
        if not j:
            raise HTTPException(404, "JOB_NOT_FOUND")
        return j

    @app.post("/api/v1/patterns/jobs/{job_id}/cancel")
    def pat_cancel(job_id: str):
        return {"ok": rt.analytics.library.cancel(job_id)}

    @app.post("/api/v1/patterns/jobs/{job_id}/resume")
    def pat_resume(job_id: str):
        r = rt.analytics.library.resume(job_id)
        if not r["ok"]:
            raise HTTPException(409, r["error"])
        return r

    @app.post("/api/v1/patterns/jobs/{job_id}/export")
    def pat_export_job(job_id: str):
        """Re-export the report from STORED results (no validation)."""
        return rt.analytics.library.export(job_id)

    @app.get("/api/v1/patterns/jobs/{job_id}/results")
    def pat_job_results(job_id: str):
        return {"job_id": job_id, "items": rt.analytics.library.results(job_id)}

    @app.get("/api/v1/patterns/results/{result_id}")
    def pat_result(result_id: str):
        """Saved immutable result for SHOW ON CHART - never re-analyses (REVALIDATE is the explicit POST validate)."""
        r = rt.analytics.library.result(result_id)
        if not r:
            raise HTTPException(404, "RESULT_NOT_FOUND")
        return r

    @app.get("/api/v1/patterns/samples/{sid}/result")
    def pat_sample_result(sid: int):
        r = rt.analytics.library.latest_result(sid)
        if not r:
            raise HTTPException(404, "NO_SAVED_RESULT – najpierw waliduj (VALIDATE / REVALIDATE)")
        return r

    @app.get("/api/v1/patterns/reports/{report_id}")
    def pat_report(report_id: str):
        r = rt.analytics.library.report(report_id)
        if not r:
            raise HTTPException(404, "REPORT_NOT_FOUND")
        return r

    @app.get("/api/v1/patterns/export")
    def pat_export():
        return rt.analytics.library.export_samples()

    @app.post("/api/v1/patterns/import")
    def pat_import(body: dict = Body(...)):
        return rt.analytics.library.import_samples(body)

    @app.get("/api/v1/patterns/live")
    def pat_live():
        a = rt.cfg.get().analytics
        return {"timeframes": {tf: (rt.analytics.state.get(tf) or {}).get("double_bottom") for tf in a.db_timeframes},
                "events": rt.analytics.events(50), "profile": a.db_profile}
