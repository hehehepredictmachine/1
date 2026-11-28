"""Helpers of create_app that a route block uses by name BEFORE the block that defined them (Etap 4 krok B).

In create_app every helper was a local defined once and read at call time, wherever it stood. Split into register functions
called in order, a block can only bind names that already exist: lab.register (POST /api/v1/lab/train with
task_id SCALP_SETUP_MARKET_V1) calls _nss_job of the Neural Scalp System block and trainhub.register (_comp) calls
_research of the research modules block - both registered later. These statements are defined here, first, verbatim
(nss_jobs is the same rt.api_services registry of the composition root, read once per create_app as before) and published on
ctx; their section comments stay in routes/nss.py and routes/research.py.
"""
from __future__ import annotations

import os
import sys

from fastapi import HTTPException

from ... import paths


def define(ctx) -> None:
    """Define _research, nss_jobs and _nss_job (create_app before the split: research block / Neural Scalp System block)."""
    rt = ctx.rt

    def _research():
        r = getattr(rt, "research", None)
        if r is None:
            raise HTTPException(503, "moduły badawcze niedostępne (błąd startu – patrz logs/engine_console.log)")
        return r

    nss_jobs: dict = rt.api_services.nss_jobs                           # Etap 4 (krok A): owned by the composition root (rt.api_services)

    def _nss_job(args: list[str]):
        import subprocess
        from ...training import core as tc
        if any(pr.poll() is None for pr in nss_jobs.values()):
            return {"started": False, "reason": "JOB_RUNNING – jedno ciężkie zadanie NSS naraz"}
        jid = "NSSJ-" + __import__("uuid").uuid4().hex[:8]
        log = open(tc.training_dir() / f"nss_{jid}.log", "a", encoding="utf-8")
        kw = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if os.name == "nt" else {"start_new_session": True}
        nss_jobs[jid] = subprocess.Popen([sys.executable, "-m", "masterquo", "neural-scalp", *args], cwd=str(paths.ROOT_DIR / "backend"), stdout=log,
                                         stderr=subprocess.STDOUT, **kw)
        return {"started": True, "job_id": jid, "args": args}

    ctx._research = _research
    ctx.nss_jobs = nss_jobs
    ctx._nss_job = _nss_job
