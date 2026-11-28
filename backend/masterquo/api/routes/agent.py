"""API routes: agent.

register(app, ctx): agent
    (7 routes; create_app before the split, 7ba7ab0: lines 1692-1733)

The handlers are the ones create_app defined before the split (Etap 4 krok B, docs/arch146/ETAP2_PROJEKT.md §3 / §5):
same function names, signatures, decorators, Pydantic models, error codes and body - the block of create_app is copied
verbatim, the only edit is one more dot in a relative import (the package is one level deeper). The create_app locals the
block used (rt, helpers, handlers called by name) are bound from ctx at the top of the function under the same names;
registration order: api/routes/__init__.REGISTRATION.
"""
from __future__ import annotations

from fastapi import HTTPException

from ..schemas import AskReq, MemoryReq


def register(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 1692-1733: 7 routes."""
    rt = ctx.rt

    # ------------------------------------------------------------ agent
    @app.get("/api/v1/agent")
    def agent_status():
        runs = rt.db.query("SELECT run_id, started_at, finished_at, trigger, snapshot_id, setup_id, model_id, prompt_version, status, error_code, "
                           "latency_ms, input_tokens, output_tokens, est_cost_usd, tool_calls, question FROM agent_runs ORDER BY started_at DESC LIMIT 30")
        return {"status": rt.agent.status(), "last": rt.agent.public_result(rt.agent.last_result), "runs": runs}

    @app.get("/api/v1/agent/models")
    async def agent_models():
        return await rt.agent.list_models()

    @app.post("/api/v1/agent/test")
    async def agent_test():
        return await rt.agent.test_connection()

    @app.post("/api/v1/agent/ask")
    def agent_ask(req: AskReq):
        d = rt.engine.current_decision() or {}
        s = d.get("setup") or {}
        rid = rt.agent.request("USER_QUESTION", snapshot_id=d.get("snapshot_id"), setup_id=s.get("setup_id") if s.get("state") in
                               ("EARLY_SETUP", "QUALIFIED", "ARMED", "TRIGGERED", "CONFIRMED") else None, setup_state=s.get("state"), question=req.question)
        return {"queued": bool(rid), "request_id": rid}

    @app.post("/api/v1/agent/analyze")
    def agent_analyze():
        d = rt.engine.current_decision() or {}
        s = d.get("setup") or {}
        active = s.get("state") in ("EARLY_SETUP", "QUALIFIED", "ARMED", "TRIGGERED", "CONFIRMED")
        trig = "SETUP_CONFIRMED" if s.get("state") == "CONFIRMED" else "MANUAL"
        rid = rt.agent.request(trig, snapshot_id=d.get("snapshot_id"), setup_id=s.get("setup_id") if active else None, setup_state=s.get("state"))
        return {"queued": bool(rid), "request_id": rid}

    @app.get("/api/v1/agent/memory")
    def agent_memory():
        return rt.db.query("SELECT * FROM agent_memory ORDER BY id DESC LIMIT 100")

    @app.post("/api/v1/agent/memory/{mid}")
    def agent_memory_set(mid: int, req: MemoryReq):
        if req.status not in ("ACCEPTED_FOR_OOS_TEST", "REJECTED", "PROPOSED"):
            raise HTTPException(400, "INVALID_STATUS")
        rt.db.execute("UPDATE agent_memory SET status=? WHERE id=?", (req.status, mid))
        rt.log.info("AGENT", "MEMORY_STATUS", f"Propozycja {mid}: {req.status} (nie zmienia strategii LIVE)")
        return {"ok": True}
