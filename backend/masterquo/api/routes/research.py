"""API routes: moduły badawcze.

register(app, ctx): moduły badawcze 1.41
    (10 routes; create_app before the split, 7ba7ab0: lines 2833-2893)

The handlers are the ones create_app defined before the split (Etap 4 krok B, docs/arch146/ETAP2_PROJEKT.md §3 / §5):
same function names, signatures, decorators, Pydantic models, error codes and body - the block of create_app is copied
verbatim, the only edit is one more dot in a relative import (the package is one level deeper). The create_app locals the
block used (rt, helpers, handlers called by name) are bound from ctx at the top of the function under the same names;
registration order: api/routes/__init__.REGISTRATION.
"""
from __future__ import annotations

from fastapi import Body, HTTPException


def register(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 2833-2893: 10 routes."""
    rt = ctx.rt
    _sdf_checkpoint = ctx._sdf_checkpoint
    _research = ctx._research

    # ---- 1.41 research modules (SDformerFlow, cellular feature graph, COA, BChimp, G7 SMC radar, exponential trend channel)
    @app.get("/api/v1/research-modules")
    def research_status():
        return _research().status()

    @app.get("/api/v1/research-modules/settings")
    def research_settings():
        return _research().settings()

    @app.put("/api/v1/research-modules/settings")
    def research_settings_put(body: dict = Body(...)):
        try:
            return _research().update_settings(body, who="panel")
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.get("/api/v1/research-modules/features")
    def research_features(t: float | None = None):
        r = _research()
        inst = rt.sh.instrument()
        return {"instrument": inst, "asof": t, "features": r.features_for(inst, t), "snapshot": r.latest(inst)}

    @app.get("/api/v1/research-modules/feature-graph")
    def research_graph(target: str = "BPC10"):
        return _research().feature_graph(target)

    @app.get("/api/v1/research-modules/optimizer/jobs")
    def research_opt_jobs():
        return {"jobs": _research().optimizer_jobs(), "history": _research().param_history[-50:]}

    @app.post("/api/v1/research-modules/optimizer/run")
    def research_opt_run():
        r = _research()
        c = r.ensure_main_context()
        rows = r._objective_rows(c) if c else []
        if len(rows) < int(r.settings()["optimizer"]["min_mature_examples"]):
            raise HTTPException(409, f"za mało dojrzałych etykiet ({len(rows)}) – optymalizator czeka na dane")
        return r.optimise(c, rows)

    @app.post("/api/v1/research-modules/parameters/rollback")
    def research_rollback():
        return _research().rollback_parameters()

    @app.post("/api/v1/research-modules/sdformerflow/train")
    def research_sdf_train(body: dict = Body(default={})):
        r = _research()
        c = r.ensure_main_context()
        op = str(body.get("op") or "from_scratch")
        if op not in ("from_scratch", "fine_tune", "resume"):
            raise HTTPException(400, "op: from_scratch | fine_tune | resume")
        h1 = c.bars_fn("H1", 6000) if c else []
        ck = _sdf_checkpoint(r, body["checkpoint"]) if body.get("checkpoint") else None      # 1.46: no paths outside the SDF folder
        ck = ck or (r.settings()["sdformer"].get("active_run") if op != "from_scratch" else None)
        ckp = str(r._sdf_dir() / ck) if ck else None
        res = r.start_training(c, h1, op=op, checkpoint=ckp, reason="panel (DIRECT_USER_REQUEST)")
        if not res.get("ok"):
            raise HTTPException(409, res.get("reason"))
        return res

    @app.post("/api/v1/research-modules/sdformerflow/cancel")
    def research_sdf_cancel():
        return _research().cancel_training()
