"""API routes: Neural Scalp System.

register(app, ctx): Neural Scalp System
    (10 routes; create_app before the split, 7ba7ab0: lines 3688-3757)

The handlers are the ones create_app defined before the split (Etap 4 krok B, docs/arch146/ETAP2_PROJEKT.md §3 / §5):
same function names, signatures, decorators, Pydantic models, error codes and body - the block of create_app is copied
verbatim, the only edit is one more dot in a relative import (the package is one level deeper). The create_app locals the
block used (rt, helpers, handlers called by name) are bound from ctx at the top of the function under the same names;
registration order: api/routes/__init__.REGISTRATION.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi import Body, HTTPException, Query

from ... import paths


def register(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 3688-3757: 10 routes."""
    rt = ctx.rt
    _asset = ctx._asset
    nss_jobs = ctx.nss_jobs
    _nss_job = ctx._nss_job

    # ------------------------------------------------------------ PMW-UPD-04 Neural Scalp System (CAUSAL_MTF_TCN_V1)
    @app.get("/api/v1/lab/neural")
    def nss_state(asset: str | None = Query(None)):
        return rt.nss.public(_asset(asset) if asset else rt.cfg.get().assets.active)

    @app.get("/api/v1/lab/neural/history")
    def nss_history(limit: int = Query(50, ge=1, le=500)):
        return {"asset": rt.nss.inst, "rows": rt.nss.history(limit)}

    @app.get("/api/v1/lab/neural/report")
    def nss_report(asset: str | None = Query(None), run_id: str | None = Query(None)):
        from ...lab import nss
        a = _asset(asset) if asset else rt.cfg.get().assets.active
        p = nss.root(a) / "registry.json"
        reg = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"runs": {}}
        rid = run_id or (sorted(reg["runs"])[-1] if reg["runs"] else None)
        if not rid or rid not in reg["runs"]:
            return {"asset": a, "status": "NO_REPORT"}
        rep = json.loads((Path(reg["runs"][rid]["run_dir"]) / "report.json").read_text(encoding="utf-8"))
        return {"asset": a, "run_id": rid, "report": rep}

    @app.get("/api/v1/lab/neural/jobs")
    def nss_jobs_list():
        return {"jobs": [{"job_id": k, "pid": v.pid, "running": v.poll() is None, "returncode": v.poll()} for k, v in nss_jobs.items()]}

    @app.post("/api/v1/lab/neural/prepare")
    def nss_prepare(body: dict = Body(default={})):
        return _nss_job(["prepare", "--asset", _asset(body.get("asset") or rt.cfg.get().assets.active)])

    @app.post("/api/v1/lab/neural/doctor")
    def nss_doctor(body: dict = Body(default={})):
        import subprocess
        a = _asset(body.get("asset") or rt.cfg.get().assets.active)
        try:
            r = subprocess.run([sys.executable, "-m", "masterquo", "neural-scalp", "doctor", "--asset", a], cwd=str(paths.ROOT_DIR / "backend"),
                               capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:          # 1.46: was an unhandled 500
            return {"status": "ERROR", "reason": "TIMEOUT", "output": "diagnostyka nie zakończyła się w 120 s"}
        try:
            return json.loads(r.stdout)
        except ValueError:
            return {"status": "ERROR", "output": (r.stdout + r.stderr)[-2000:]}

    @app.post("/api/v1/lab/neural/train")
    def nss_train(body: dict = Body(default={})):
        return _nss_job(["train", "--asset", _asset(body.get("asset") or rt.cfg.get().assets.active), "--activate", "none"])

    @app.post("/api/v1/lab/neural/cancel")
    def nss_cancel(body: dict = Body(default={})):
        pr = nss_jobs.get(str(body.get("job_id")))
        if pr is None:
            raise HTTPException(404, "UNKNOWN_JOB")
        if pr.poll() is None:
            pr.terminate()
        return {"ok": True, "job_id": body.get("job_id"), "note": "anulowanie nie podmienia wybranego modelu"}

    @app.post("/api/v1/lab/neural/select")
    def nss_select(body: dict = Body(default={})):
        from ...lab import nss
        try:
            return {"ok": True, "selected": nss.select(_asset(body.get("asset") or rt.cfg.get().assets.active), str(body.get("run_id")), str(body.get("role") or "OBSERVE"))}
        except (ValueError, OSError, KeyError) as exc:
            return {"ok": False, "reason": str(exc)}

    @app.post("/api/v1/lab/neural/rollback")
    def nss_rollback(body: dict = Body(default={})):
        from ...lab import nss
        try:
            return {"ok": True, "selected": nss.rollback(_asset(body.get("asset") or rt.cfg.get().assets.active))}
        except (ValueError, OSError) as exc:
            return {"ok": False, "reason": str(exc)}
