"""ClaudeAgent - a real Claude API integration (official `anthropic` SDK), not a trained model.

Agent = model + versioned system prompt + read-only tools over a frozen snapshot + memory of
past setups/lessons + hard permission limits. The loop is a manual tool_use/tool_result loop
(append-only history, so thinking blocks stay valid), with a structured JSON final answer
(`output_config.format` json_schema). If the model rejects structured outputs, the answer is
validated with pydantic and repaired at most once; an invalid answer never passes the AI gate.

Event driven (new setup, TRIGGERED, CONFIRMED, terminal setup, hourly context, user question),
rate-limited, budgeted. Failures (no key, bad key, timeout, rate limit, unknown model, offline)
produce an honest status; nothing is ever fabricated as AI output.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
import uuid
from datetime import timedelta
from pathlib import Path

from pydantic import ValidationError

from ..db.database import dumps
from ..timeutil import iso, parse_iso, utcnow


def _registry_ids() -> set[str]:
    from ..strategies.registry import STRATEGIES
    return set(STRATEGIES)
from .schema import OUTPUT_SCHEMA, AgentAssessment, record
from .tools import TOOL_DEFS, Toolbox

log = logging.getLogger("masterquo.agent")
PROMPT_FILE = Path(__file__).resolve().parent / "prompts" / "MASTERQUO_AGENT_SYSTEM_PROMPT.md"
FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"


def load_prompt() -> tuple[str, str]:
    text = PROMPT_FILE.read_text(encoding="utf-8")
    m = re.search(r"PROMPT_VERSION:\s*([A-Za-z0-9_.\-]+)", text)
    version = m.group(1) if m else "UNVERSIONED"
    body = re.sub(r"<!--.*?-->", "", text, flags=re.S).strip()
    return body, version


class ClaudeAgent:
    def __init__(self, cfg_store, secrets, db, bus, applog, context_provider):
        self.guard = None                                 # LicenseGuard (set by runtime); None = agent disabled
        self.cfg_store = cfg_store
        self.secrets = secrets
        self.db = db
        self.bus = bus
        self.log = applog
        self.context_provider = context_provider  # (snapshot_id|None) -> frozen ctx dict | None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.queue: asyncio.Queue | None = None
        self._client = None
        self._client_key_hash = None
        self.state = "NOT_STARTED"
        self.state_detail: str | None = None
        self.backoff_until = 0.0
        self.last_auto_run = 0.0
        self.last_user_run = 0.0
        self.disable_fallback = False
        self.no_structured: set[str] = set()
        self.no_effort: set[str] = set()
        self.by_setup: dict[str, dict] = {}       # setup_id -> latest applied result
        self._started_seq: dict[str, int] = {}     # setup_id -> latest started run seq
        self._seq = 0
        self.pending: dict[str, dict] = {}
        self.last_result: dict | None = None
        self.last_run_meta: dict | None = None

    # ------------------------------------------------------------ config
    @property
    def cfg(self):
        return self.cfg_store.get().agent

    def model(self) -> str | None:
        import os
        return self.cfg.model or os.environ.get("ANTHROPIC_MODEL") or None

    def _client_get(self):
        import anthropic
        key = self.secrets.get("ANTHROPIC_API_KEY")
        if not key:
            return None
        h = hashlib.sha256(key.encode()).hexdigest()
        if self._client is None or h != self._client_key_hash:
            self._client = anthropic.AsyncAnthropic(api_key=key, timeout=self.cfg.request_timeout_seconds, max_retries=1)
            self._client_key_hash = h
        return self._client

    def spent_today(self) -> float:
        start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        r = self.db.one("SELECT COALESCE(SUM(est_cost_usd),0) AS s FROM agent_runs WHERE started_at >= ?", (iso(start),))
        return float(r["s"] or 0)

    def status(self) -> dict:
        key_src = self.secrets.source("ANTHROPIC_API_KEY")
        st = self.state
        if not self.cfg.enabled:
            st = "DISABLED"
        elif key_src == "MISSING":
            st = "AI_UNAVAILABLE_NO_KEY"
        elif not self.model():
            st = "MODEL_NOT_CONFIGURED"
        return {"state": st, "detail": self.state_detail, "model": self.model(), "key_source": key_src,
                "key_masked": self.secrets.mask("ANTHROPIC_API_KEY"), "effort": self.cfg.effort,
                "spent_today_usd_estimate": round(self.spent_today(), 4), "daily_budget_usd": self.cfg.daily_budget_usd,
                "required_for_entry": self.policy() == "REQUIRED", "gate_policy": self.policy(), "pending": list(self.pending.values()),
                "backoff_seconds": max(0, round(self.backoff_until - time.monotonic(), 1)), "last_run": self.last_run_meta,
                "cost_note": "Koszt to szacunek z cennika zapisanego w konfiguracji (stan 2026-10-06), nie faktura."}

    # ------------------------------------------------------------ scheduling (thread-safe entry points)
    def attach(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.queue = asyncio.Queue(maxsize=50)
        self.state = "IDLE"
        loop.create_task(self._worker())

    def request(self, trigger: str, *, snapshot_id: str | None, setup_id: str | None, setup_state: str | None,
                question: str | None = None) -> str | None:
        if self.loop is None or self.queue is None:
            return None
        if self.guard is None or not self.guard.allows("agent"):
            return None                                   # no Claude calls without a valid license
        key = f"{trigger}:{setup_id}:{setup_state}:{question or ''}"
        if key in self.pending:
            return self.pending[key]["request_id"]
        rid = "AGQ-" + uuid.uuid4().hex[:12]
        req = {"request_id": rid, "trigger": trigger, "snapshot_id": snapshot_id, "setup_id": setup_id,
               "setup_state": setup_state, "question": question, "queued_at": iso(utcnow()), "key": key}
        self.pending[key] = {k: req[k] for k in ("request_id", "trigger", "setup_id", "queued_at")}
        self.loop.call_soon_threadsafe(self._enqueue, req)
        return rid

    def _enqueue(self, req: dict) -> None:
        try:
            self.queue.put_nowait(req)
        except asyncio.QueueFull:
            self.pending.pop(req["key"], None)

    async def _worker(self) -> None:
        while True:
            req = await self.queue.get()
            try:
                await self._handle(req)
            except Exception as exc:  # keep the worker alive
                log.exception("agent run crashed")
                self.state, self.state_detail = "ERROR", f"{type(exc).__name__}: {exc}"[:200]
            finally:
                self.pending.pop(req["key"], None)
                self.bus.publish("agent", self.status())

    # ------------------------------------------------------------ gates
    def _preflight(self, req: dict) -> str | None:
        if self.guard is None or not self.guard.allows("agent"):
            return "LICENSE_REQUIRED"
        if not self.cfg.enabled:
            return "AGENT_DISABLED"
        if self.secrets.get("ANTHROPIC_API_KEY") is None:
            return "AI_UNAVAILABLE_NO_KEY"
        if not self.model():
            return "MODEL_NOT_CONFIGURED"
        if time.monotonic() < self.backoff_until:
            return "RATE_LIMIT_BACKOFF"
        if self.spent_today() >= self.cfg.daily_budget_usd:
            return "DAILY_BUDGET_EXHAUSTED"
        now = time.monotonic()
        if req["trigger"] == "USER_QUESTION":
            if now - self.last_user_run < 10:
                return "USER_QUESTION_RATE_LIMIT"
        elif req["trigger"] not in ("SETUP_CONFIRMED",) and now - self.last_auto_run < self.cfg.min_interval_seconds:
            return "MIN_INTERVAL"
        return None

    def policy(self) -> str:
        return "ADVISORY" if not self.cfg.required_for_entry else self.cfg.gate_policy

    def gate_for(self, setup: dict | None, *, session_epoch: int, account_key: str | None, now_iso: str) -> dict:
        """AI gate for the decision tree, according to agent.gate_policy.

        REQUIRED: only a fresh, matching, agreeing assessment passes.
        VETO:     only an explicit disagreement blocks; while an assessment is awaited the gate waits
                  up to ai_wait_seconds after confirmation, then passes (AI_NO_VETO_*).
        ADVISORY: never blocks.
        """
        pol = self.policy()
        if pol == "ADVISORY":
            return {"status": "NOT_REQUIRED", "reason_codes": ["AI_NOT_REQUIRED_BY_CONFIG"]}
        g = self._strict_gate(setup, session_epoch=session_epoch, account_key=account_key, now_iso=now_iso)
        if pol == "REQUIRED" or g["status"] in ("PASS", "DISAGREE"):
            return g
        if not setup or setup["state"] != "CONFIRMED":
            return g
        codes = g.get("reason_codes") or []
        waiting = g["status"] == "PENDING" and any(c in ("AI_ASSESSMENT_RUNNING", "AI_ASSESSMENT_MISSING") for c in codes)
        if waiting:
            try:
                age = (parse_iso(now_iso) - parse_iso(setup["state_changed_at"])).total_seconds()
            except (TypeError, ValueError, KeyError):
                age = None
            if age is not None and age < self.cfg.ai_wait_seconds:
                return {**g, "reason_codes": codes + [f"AI_VETO_WAIT_{int(self.cfg.ai_wait_seconds)}S"]}
        return {"status": "NOT_REQUIRED", "reason_codes": ["AI_NO_VETO_" + (codes[0] if codes else g["status"])],
                "agent_decision_id": g.get("agent_decision_id")}

    def _strict_gate(self, setup: dict | None, *, session_epoch: int, account_key: str | None, now_iso: str) -> dict:
        pre = None
        if not self.cfg.enabled:
            pre = "AGENT_DISABLED"
        elif self.secrets.get("ANTHROPIC_API_KEY") is None:
            pre = "AI_UNAVAILABLE_NO_KEY"
        elif not self.model():
            pre = "MODEL_NOT_CONFIGURED"
        if pre:
            return {"status": "UNAVAILABLE", "reason_codes": [pre]}
        if not setup or setup["state"] != "CONFIRMED":
            return {"status": "PENDING", "reason_codes": ["AI_EVALUATES_CONFIRMED_SETUPS_ONLY"]}
        res = self.by_setup.get(setup["setup_id"])
        if not res:
            busy = any(p.get("setup_id") == setup["setup_id"] for p in self.pending.values())
            return {"status": "PENDING", "reason_codes": ["AI_ASSESSMENT_RUNNING" if busy else "AI_ASSESSMENT_MISSING"]}
        codes = []
        if res["status"] != "OK":
            return {"status": "FAIL", "reason_codes": ["AI_RUN_" + res["status"]], "agent_decision_id": res.get("decision_id")}
        rec = res["record"]
        if res["session_epoch"] != session_epoch or res["account_key"] != account_key:
            codes.append("AI_ASSESSMENT_FOR_OTHER_SESSION")
        if res["setup_state"] != "CONFIRMED" or res["setup_state_changed_at"] != setup["state_changed_at"]:
            codes.append("AI_ASSESSMENT_FOR_OLDER_SETUP_STATE")
        if parse_iso(rec["expires_at_utc"]) <= parse_iso(now_iso):
            codes.append("AI_ASSESSMENT_EXPIRED")
        if rec.get("setup_id") != setup["setup_id"]:
            codes.append("AI_SETUP_ID_MISMATCH")
        if codes:
            return {"status": "PENDING", "reason_codes": codes, "agent_decision_id": rec["decision_id"]}
        want = "BUY" if setup["direction"] == "LONG" else "SELL"
        if rec["proposed_action"] != want:
            return {"status": "DISAGREE", "reason_codes": ["AI_PROPOSES_" + rec["proposed_action"]], "agent_decision_id": rec["decision_id"],
                    "expires_at": rec["expires_at_utc"]}
        return {"status": "PASS", "reason_codes": [], "agent_decision_id": rec["decision_id"], "expires_at": rec["expires_at_utc"],
                "model_id": rec.get("model_id")}

    # ------------------------------------------------------------ run
    async def _handle(self, req: dict) -> None:
        why = self._preflight(req)
        if why:
            if req["trigger"] in ("USER_QUESTION", "SETUP_CONFIRMED") or why not in ("MIN_INTERVAL",):
                self.state_detail = why
            if req["trigger"] == "SETUP_CONFIRMED" and req["setup_id"]:
                # the gate must show why the confirmed setup has no AI assessment
                self.by_setup[req["setup_id"]] = {"status": why, "decision_id": None}
            self._store_skipped(req, why)
            return
        ctx = self.context_provider(req["snapshot_id"]) or self.context_provider(None)
        if not ctx:
            self._store_skipped(req, "NO_ANALYSIS_CONTEXT")
            return
        self._seq += 1
        seq = self._seq
        if req["setup_id"]:
            self._started_seq[req["setup_id"]] = seq
        if req["trigger"] == "USER_QUESTION":
            self.last_user_run = time.monotonic()
        else:
            self.last_auto_run = time.monotonic()
        self.state, self.state_detail = "RUNNING", req["trigger"]
        self.bus.publish("agent", self.status())
        result = await self.run_once(req, ctx)
        # A late answer never overrides a newer run for the same setup.
        if req["setup_id"] and self._started_seq.get(req["setup_id"]) != seq:
            result["status_note"] = "SUPERSEDED_BY_NEWER_RUN"
        elif req["setup_id"]:
            self.by_setup[req["setup_id"]] = result
        if result["status"] == "OK":
            self.last_result = result
            self.state, self.state_detail = "OK", None
            self._remember(result, req)
        else:
            self.state, self.state_detail = result["status"], result.get("error")
        self.bus.publish("agent_result", self.public_result(result))

    def public_result(self, r: dict | None) -> dict | None:
        if not r:
            return None
        return {k: r.get(k) for k in ("run_id", "status", "error", "trigger", "snapshot_id", "setup_id", "setup_state", "record",
                                      "model_id", "latency_ms", "usage", "est_cost_usd", "tool_calls", "finished_at", "question")}

    def _store_skipped(self, req: dict, why: str) -> None:
        now = iso(utcnow())
        self.db.execute("""INSERT INTO agent_runs(run_id, started_at, finished_at, trigger, snapshot_id, setup_id, model_requested, prompt_version,
                           status, error_code, question) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                        ("AGR-" + uuid.uuid4().hex[:16], now, now, req["trigger"], req["snapshot_id"], req["setup_id"], self.model(),
                         load_prompt()[1], "SKIPPED", why, req.get("question")))

    def _remember(self, result: dict, req: dict) -> None:
        rec = result["record"]
        now = iso(utcnow())
        for lesson in rec.get("lessons") or []:
            self.db.execute("INSERT INTO agent_memory(created_at, kind, setup_id, status, content_json) VALUES (?,?,?,?,?)",
                            (now, "LESSON", req["setup_id"], "RECORDED", dumps({"text": lesson, "run_id": result["run_id"]})))
        for prop in rec.get("playbook_proposals") or []:
            self.db.execute("INSERT INTO agent_memory(created_at, kind, setup_id, status, content_json) VALUES (?,?,?,?,?)",
                            (now, "PLAYBOOK_PROPOSAL", req["setup_id"], "PROPOSED", dumps({**prop, "run_id": result["run_id"],
                             "promotion_rule": "Wymaga testu M06R/M06T na danych OOS + forward DEMO i zatwierdzenia użytkownika; nie zmienia LIVE."})))

    def _cost(self, model: str, usage: dict) -> float | None:
        price = self.cfg.price_per_mtok.get(model)
        if not price:
            return None
        pin, pout = price
        cost = (usage.get("input_tokens", 0) * pin + usage.get("cache_creation_input_tokens", 0) * pin * 1.25 +
                usage.get("cache_read_input_tokens", 0) * pin * 0.1 + usage.get("output_tokens", 0) * pout) / 1_000_000
        return round(cost, 6)

    def _user_message(self, req: dict, ctx: dict) -> str:
        setup = ctx.get("setup")
        lines = [f"Snapshot: {ctx['snapshot_id']} (as_of_utc {ctx['as_of']}), symbol brokera {ctx['symbol']}.",
                 f"Wyzwalacz analizy: {req['trigger']}.",
                 f"Jakość danych: {ctx['dq']['data_quality']}, rynek: {ctx['dq']['market_state']}."]
        if setup:
            lines.append(f"Aktywny setup: {setup['setup_id']} {setup['strategy_id']} ({setup['profile']}) {setup['direction']} "
                         f"etap M10A {setup['state']} na {setup['setup_tf']}.")
        else:
            lines.append("Brak aktywnego setupu – oceń kontekst i scenariusze; proposed_action nie może być BUY/SELL.")
        if req["trigger"] == "SETUP_TERMINAL":
            lines.append("Setup zakończył się – zaproponuj wnioski (lessons) i ewentualnie propozycje zmian playbooka.")
        if req.get("question"):
            lines.append("Pytanie użytkownika (odpowiedz w answer_pl, w granicach zasad; nie zmienia blokad):\n<<<\n"
                         + req["question"][:2000] + "\n>>>")
        lines.append("Użyj narzędzi, a następnie zwróć wyłącznie obiekt JSON zgodny ze schematem.")
        return "\n".join(lines)

    async def run_once(self, req: dict, ctx: dict) -> dict:
        import anthropic
        system, prompt_version = load_prompt()
        model = self.model()
        client = self._client_get()
        run_id = "AGR-" + uuid.uuid4().hex[:16]
        started = utcnow()
        t0 = time.monotonic()
        toolbox = Toolbox(ctx, self.cfg.max_tool_calls)
        messages: list = [{"role": "user", "content": self._user_message(req, ctx)}]
        usage_total = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        served_model = None
        status, error, final_text, assessment = "ERROR", None, None, None
        repaired = False
        use_structured = model not in self.no_structured
        try:
            for _turn in range(self.cfg.max_tool_calls + 4):
                resp = await self._create(client, model, system, messages, use_structured)
                served_model = getattr(resp, "model", served_model)
                u = getattr(resp, "usage", None)
                if u is not None:
                    for k in usage_total:
                        usage_total[k] += int(getattr(u, k, 0) or 0)
                messages.append({"role": "assistant", "content": resp.content})  # append-only (thinking blocks preserved)
                sr = resp.stop_reason
                if sr == "refusal":
                    status, error = "REFUSED", str(getattr(getattr(resp, "stop_details", None), "category", None))
                    break
                if sr == "max_tokens":
                    status, error = "INVALID_OUTPUT", "MAX_TOKENS_TRUNCATED"
                    break
                if sr == "pause_turn":
                    continue
                tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
                if sr == "tool_use" and tool_uses:
                    results = []
                    for tu in tool_uses:
                        text, is_err = toolbox.run(tu.name, tu.input if isinstance(tu.input, dict) else {})
                        results.append({"type": "tool_result", "tool_use_id": tu.id, "content": text, **({"is_error": True} if is_err else {})})
                    messages.append({"role": "user", "content": results})
                    continue
                final_text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", None) == "text").strip()
                try:
                    assessment = AgentAssessment.model_validate(json.loads(_extract_json(final_text)))
                    # a proposed strategy must exist in the registry; it is a suggestion only (never applied automatically)
                    if assessment.preferred_strategy_id and assessment.preferred_strategy_id not in _registry_ids():
                        assessment.reason_codes.append("AGENT_PROPOSED_UNKNOWN_STRATEGY_" + assessment.preferred_strategy_id[:12])
                        assessment.preferred_strategy_id = None
                    status = "OK"
                except (ValueError, ValidationError) as exc:
                    if repaired:
                        status, error = "INVALID_OUTPUT", f"SCHEMA_VALIDATION_FAILED: {str(exc)[:200]}"
                        break
                    repaired = True
                    messages.append({"role": "user", "content": "Odpowiedź nie przeszła walidacji schematu: " + str(exc)[:800]
                                     + "\nZwróć poprawiony, kompletny obiekt JSON (bez dodatkowego tekstu)."})
                    continue
                break
            else:
                status, error = "INVALID_OUTPUT", "TURN_LIMIT"
        except anthropic.AuthenticationError:
            status, error = "AUTH_ERROR", "Nieprawidłowy klucz API (401)."
        except anthropic.PermissionDeniedError as e:
            status, error = "PERMISSION_DENIED", str(getattr(e, "message", e))[:200]
        except anthropic.NotFoundError:
            status, error = "MODEL_UNAVAILABLE", f"Model '{model}' niedostępny dla tego klucza."
        except anthropic.RateLimitError as e:
            retry = 60.0
            try:
                retry = float(e.response.headers.get("retry-after", "60"))
            except (TypeError, ValueError, AttributeError):
                pass
            self.backoff_until = time.monotonic() + retry
            status, error = "RATE_LIMITED", f"Limit API, ponowienie za {int(retry)} s."
        except anthropic.APITimeoutError:
            status, error = "TIMEOUT", f"Przekroczono {self.cfg.request_timeout_seconds:.0f} s."
        except anthropic.APIConnectionError:
            status, error = "NETWORK", "Brak połączenia z API (internet/proxy)."
        except anthropic.BadRequestError as e:
            status, error = "BAD_REQUEST", str(getattr(e, "message", e))[:300]
        except anthropic.APIStatusError as e:
            status, error = "API_ERROR", f"HTTP {getattr(e, 'status_code', '?')}"
        latency = int((time.monotonic() - t0) * 1000)
        cost = self._cost(served_model or model, usage_total)
        now = utcnow()
        rec = None
        if status == "OK" and assessment is not None:
            if assessment.snapshot_id != ctx["snapshot_id"] or (ctx.get("setup") or {}).get("setup_id") != assessment.setup_id:
                status, error = "INVALID_OUTPUT", "SNAPSHOT_OR_SETUP_ID_MISMATCH"
            else:
                did = "AGD-" + hashlib.sha256((run_id + ctx["snapshot_id"]).encode()).hexdigest()[:20]
                exp = parse_iso(ctx["as_of"]) + timedelta(seconds=self.cfg.decision_ttl_seconds)
                rec = record(assessment, decision_id=did, as_of=ctx["as_of"], expires_at=iso(exp),
                             model_id=served_model or model, prompt_version=prompt_version)
        setup = ctx.get("setup") or {}
        result = {"run_id": run_id, "status": status, "error": error, "trigger": req["trigger"], "snapshot_id": ctx["snapshot_id"],
                  "setup_id": setup.get("setup_id"), "setup_state": setup.get("state"), "setup_state_changed_at": setup.get("state_changed_at"),
                  "session_epoch": ctx["session_epoch"], "account_key": ctx.get("account_key"), "record": rec,
                  "model_id": served_model or model, "latency_ms": latency, "usage": usage_total, "est_cost_usd": cost,
                  "tool_calls": toolbox.log, "finished_at": iso(now), "question": req.get("question"), "decision_id": (rec or {}).get("decision_id")}
        self.last_run_meta = {"run_id": run_id, "status": status, "model_id": served_model or model, "latency_ms": latency,
                              "finished_at": iso(now), "est_cost_usd": cost, "trigger": req["trigger"], "error": error,
                              "input_tokens": usage_total["input_tokens"], "output_tokens": usage_total["output_tokens"]}
        self.db.execute("""INSERT INTO agent_runs(run_id, started_at, finished_at, trigger, snapshot_id, setup_id, model_requested, model_id,
                           prompt_version, status, error_code, latency_ms, input_tokens, output_tokens, cache_read_tokens, est_cost_usd,
                           tool_calls, output_json, question) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (run_id, iso(started), iso(now), req["trigger"], ctx["snapshot_id"], setup.get("setup_id"), model, served_model,
                         prompt_version, status, error, latency, usage_total["input_tokens"], usage_total["output_tokens"],
                         usage_total["cache_read_input_tokens"], cost, len(toolbox.log), dumps(rec) if rec else None, req.get("question")))
        lvl = "INFO" if status == "OK" else "WARNING"
        self.log.write(lvl, "AGENT", status, f"Agent Claude: {status}" + (f" – {rec['proposed_action']} ({rec['analysis_direction']})" if rec else
                                                                       (f" – {error}" if error else "")))
        return result

    async def _create(self, client, model: str, system: str, messages: list, structured: bool):
        import anthropic
        oc: dict = {}
        if model not in self.no_effort:
            oc["effort"] = self.cfg.effort
        if structured:
            oc["format"] = {"type": "json_schema", "schema": OUTPUT_SCHEMA}
        kw = dict(model=model, max_tokens=self.cfg.max_tokens, system=system, tools=TOOL_DEFS, messages=messages,
                  cache_control={"type": "ephemeral"})
        if oc:
            kw["output_config"] = oc
        use_fb = self.cfg.use_refusal_fallback and not self.disable_fallback and model in FALLBACK_MODELS
        try:
            if use_fb:
                return await client.beta.messages.create(**kw, betas=[FALLBACK_BETA], fallbacks="default")
            return await client.messages.create(**kw)
        except anthropic.BadRequestError as e:
            msg = str(getattr(e, "message", e)).lower()
            if use_fb and "fallback" in msg:
                self.disable_fallback = True
            elif "effort" in msg and model not in self.no_effort:
                self.no_effort.add(model)
            elif structured and ("output_config" in msg or "format" in msg or "schema" in msg):
                self.no_structured.add(model)
            else:
                raise
            return await self._create(client, model, system, messages, structured and model not in self.no_structured)

    # ------------------------------------------------------------ config tests
    async def list_models(self) -> dict:
        import anthropic
        client = self._client_get()
        if client is None:
            return {"ok": False, "error": "AI_UNAVAILABLE_NO_KEY", "models": []}
        try:
            out = []
            async for m in client.models.list():
                out.append({"id": m.id, "display_name": getattr(m, "display_name", m.id)})
            return {"ok": True, "models": out}
        except anthropic.AuthenticationError:
            return {"ok": False, "error": "AUTH_ERROR", "models": []}
        except anthropic.APIConnectionError:
            return {"ok": False, "error": "NETWORK", "models": []}
        except anthropic.APIStatusError as e:
            return {"ok": False, "error": f"HTTP_{e.status_code}", "models": []}

    async def test_connection(self) -> dict:
        import anthropic
        client = self._client_get()
        model = self.model()
        if client is None:
            return {"ok": False, "error": "AI_UNAVAILABLE_NO_KEY"}
        if not model:
            return {"ok": False, "error": "MODEL_NOT_CONFIGURED"}
        try:
            m = await client.models.retrieve(model)
            self.state, self.state_detail = "IDLE", None
            return {"ok": True, "model": m.id, "display_name": getattr(m, "display_name", None)}
        except anthropic.NotFoundError:
            return {"ok": False, "error": "MODEL_UNAVAILABLE", "model": model}
        except anthropic.AuthenticationError:
            self.state = "AUTH_ERROR"
            return {"ok": False, "error": "AUTH_ERROR"}
        except anthropic.APIConnectionError:
            return {"ok": False, "error": "NETWORK"}
        except anthropic.APIStatusError as e:
            return {"ok": False, "error": f"HTTP_{e.status_code}"}


def _extract_json(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S)
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j < i:
        raise ValueError("NO_JSON_OBJECT")
    return t[i:j + 1]
