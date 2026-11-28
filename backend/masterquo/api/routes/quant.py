"""API routes: Quant Core.

register(app, ctx): PMW Quant Core i TabICLv2
    (11 routes; create_app before the split, 7ba7ab0: lines 2737-2824)
register_models(app, ctx): aktywacja / rollback MetaModelu Quant, inwentarz Quant
    (3 routes; create_app before the split, 7ba7ab0: lines 2969-2996)

The handlers are the ones create_app defined before the split (Etap 4 krok B, docs/arch146/ETAP2_PROJEKT.md §3 / §5):
same function names, signatures, decorators, Pydantic models, error codes and body - the block of create_app is copied
verbatim, the only edit is one more dot in a relative import (the package is one level deeper). The create_app locals the
block used (rt, helpers, handlers called by name) are bound from ctx at the top of the function under the same names;
registration order: api/routes/__init__.REGISTRATION.
"""
from __future__ import annotations

from fastapi import Body, HTTPException, Query

from ..common import body_num


def register(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 2737-2824: 11 routes."""
    rt = ctx.rt
    _asset = ctx._asset
    _th_inst = ctx._th_inst

    # ---------------------------------------------------------------- 1.35 PMW Quant Core (reads the published generation only)
    def _quant():
        q = getattr(rt, "quant", None)
        if q is None:
            raise HTTPException(503, "QUANT_CORE_NOT_RUNNING")
        return q

    @app.get("/api/v1/quant/status")
    def quant_status():
        """Mode, data state, model counts with reasons, meta-model artifacts, ledger evidence, timings - a cached snapshot (no compute)."""
        return _quant().status()

    @app.get("/api/v1/quant/predictions")
    def quant_predictions():
        return _quant().predictions()

    @app.get("/api/v1/quant/assessment")
    def quant_assessments(limit: int = Query(30, ge=1, le=200), asset: str | None = None):
        q = _quant()
        from ...quant.service import with_label_policy
        return {"items": with_label_policy(q.ledger.assessments(limit, instrument=_asset(asset))), "mode": q.mode(),   # 1.46 arch (I0040): one asset
                "note": "brak skalibrowanego wyniku = brak wytrenowanego modelu dla tego zdarzenia (nie 0 %, nie 50 %)"}

    @app.post("/api/v1/quant/assessment")
    def quant_assess(body: dict = Body(...)):
        """Assessment of a given SetupCandidate (evaluation contract) - read-only, not logged, never an order."""
        from ...evaluation import contract as EK
        cand = body.get("candidate") or body
        if not isinstance(cand, dict):
            raise HTTPException(400, "CANDIDATE_INVALID: obiekt wymagany")      # 1.46: a list / text was an AttributeError (.items) -> 500
        try:
            c = EK.SetupCandidate(**{k: v for k, v in cand.items() if k in EK.SetupCandidate.__dataclass_fields__}).validate()
        except (TypeError, EK.ContractError) as exc:
            raise HTTPException(400, f"CANDIDATE_INVALID: {exc}") from None
        return _quant().assess(c.to_dict(), log_row=False)

    @app.get("/api/v1/quant/jobs")
    def quant_jobs():
        q = _quant()
        return {"items": list(q.jobs.values())[-20:], "ledger": q.ledger.counts(q.instrument())}

    @app.post("/api/v1/quant/jobs")
    def quant_train(body: dict = Body(default={})):
        """Explicit training of the meta-model from the Quant ledger (never activates; activation = separate call after validation)."""
        q = _quant()
        if str(body.get("kind") or "TRAIN_METAMODEL") != "TRAIN_METAMODEL":
            raise HTTPException(400, "JOB_KIND_UNKNOWN")
        if any(j["state"] == "RUNNING" for j in q.jobs.values()):
            raise HTTPException(409, "QUANT_JOB_ALREADY_RUNNING")
        inst = _th_inst(body["instrument"]) if body.get("instrument") else None     # 1.46: checked (it becomes a folder name)
        return q.train(inst, body.get("task_hash") or None)

    @app.post("/api/v1/quant/mode")
    def quant_mode(body: dict = Body(...)):
        r = _quant().set_mode(str(body.get("mode") or ""), confirm=bool(body.get("confirm")), by="PANEL")
        if not r.get("ok"):
            raise HTTPException(409, r.get("reason"))
        return r

    # ------------------------------------------------------------------ 1.41 TabICLv2 confidence estimator
    @app.get("/api/v1/quant/tabicl")
    def quant_tabicl():
        return _quant().tabicl.status()

    @app.put("/api/v1/quant/estimator")
    def quant_estimator(body: dict = Body(...)):
        r = _quant().set_estimator(str(body.get("estimator") or ""), by="PANEL")
        if not r.get("ok"):
            raise HTTPException(400, r.get("reason"))
        rt.log.info("QUANT", "ESTIMATOR", f"Estymator confidence: {r['estimator']} (panel).")
        return r

    @app.post("/api/v1/quant/tabicl/reconstruct")
    def quant_tabicl_reconstruct(body: dict = Body(default={})):
        days = body_num(body, "days", 30, int) or 30
        if not 3 <= days <= 365:
            raise HTTPException(400, "DAYS_OUT_OF_RANGE (3..365)")
        r = _quant().tabicl.run_reconstruction(_quant().instrument(), days=days)
        if not r.get("ok"):
            raise HTTPException(409, r.get("reason"))
        return r

    @app.post("/api/v1/quant/tabicl/install")
    def quant_tabicl_install():
        import sys as _sys
        from ... import paths as _P
        from ...tsfm.settings import default_weights_root as _dwr
        argv = [_sys.executable, str(_P.ROOT_DIR / "tools" / "tsfm_setup.py"), "--model", "tabicl", "--root", str(_P.ROOT_DIR), "--weights-root", str(_dwr())]
        return rt.tsfm.start_job_process("install_tabicl", argv)          # 1.46 arch I0089 / I0212: public facade, not _run_job_proc

    ctx._quant = _quant


def register_models(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 2969-2996: 3 routes."""
    rt = ctx.rt
    _th_inst = ctx._th_inst
    _quant = ctx._quant

    @app.post("/api/v1/quant/models/activate")
    def quant_activate(body: dict = Body(...)):
        from ...quant import metamodel as QM
        q = _quant()
        # 1.46: instrument from the body is checked - '../..' made metamodel.root() create folders / ACTIVE.json outside the data folder
        inst = _th_inst(body.get("instrument") or q.instrument())
        try:
            p = QM.activate(inst, str(body.get("task_hash") or ""), str(body.get("version") or ""))
        except (QM.MetaError, OSError, KeyError, ValueError) as exc:
            raise HTTPException(409, f"ACTIVATION_REFUSED: {exc}") from None
        try:                       # 1.46 (additive): which feature semantics the activated MetaModel gets (FEAT-1 / FEAT-3)
            sem = QM.feature_semantics(inst, str(body.get("task_hash") or ""), str(body.get("version") or ""))
        except (QM.MetaError, OSError, KeyError, ValueError) as exc:
            sem = {"feature_version": None, "note": f"{type(exc).__name__}: {exc}"[:200]}
        return {"ok": True, "pointer": p, "feature_semantics": sem}

    @app.post("/api/v1/quant/models/rollback")
    def quant_rollback(body: dict = Body(...)):
        from ...quant import metamodel as QM
        q = _quant()
        return {"ok": True, "pointer": QM.rollback(_th_inst(body.get("instrument") or q.instrument()), str(body.get("task_hash") or ""))}

    @app.get("/api/v1/quant/inventory")
    def quant_inventory():
        from ...quant import inventory as QI
        q = _quant()
        inv = QI.build(rt, q.instrument())
        return {"coverage": inv["coverage"], "entries": inv["entries"], "generated_at": inv["generated_at"]}
