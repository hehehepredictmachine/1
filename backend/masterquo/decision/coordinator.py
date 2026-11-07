"""Decision Coordinator (PMW-ARC-1) - one place where a strategy candidate of EITHER path becomes a final decision.

Order of evaluation (each step may only make the verdict stricter - nothing after the strategy can create or upgrade an entry):
1. StrategyCandidate.base_verdict from the strategy (ACTIVE: execution_permission ALLOWED -> ENTER; SH: status READY -> ENTER).
2. Gates already computed by the path (mode / risk / portfolio / data quality) -> their reason codes, verdict BLOCKED.
3. Model roles:
   * OBSERVE  - recorded with influence NONE (SHADOW families, Kronos, indicators, DXY, SVP context);
   * ASSIST   - a READY direction forecast with P(opposite side) >= families.assist_hold_threshold holds the entry
                (ACTIVE: ENTER -> BLOCKED "MODEL_ASSIST_HOLD"; SH: READY -> WAIT, the existing SH receiver) - never upgrades;
   * REQUIRED - decision.required_models: the model must be READY, fresh (age <= required_max_age_s) and must not contradict the side,
                otherwise MODEL_REQUIRED_UNAVAILABLE / _STALE / _CONTRARY blocks the entry. Default: no REQUIRED model.
4. DecisionRecord persisted (decision_records, unique per path+source+inputs) - the audit trail used by replay and the panel.
Execution then goes through IntentLedger (dedup + shared reservation) - see ledger.py.
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone

from ..timeutil import iso, utcnow
from . import contracts as K
from .ledger import IntentLedger, RiskBook


def _age_s(data_time, now: float) -> float | None:
    if not data_time:
        return None
    try:
        if isinstance(data_time, (int, float)):
            t = float(data_time)
        else:
            t = datetime.fromisoformat(str(data_time).replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()
        return max(0.0, now - t)
    except (TypeError, ValueError):
        return None


def role_of(pred: dict, required: set[str]) -> str:
    if pred.get("family") in required or pred.get("model_id") in required:
        return "REQUIRED"
    return "ASSIST" if pred.get("use") == "ASSIST" else "OBSERVE"


def evaluate_models(preds: list[dict], side: str, *, required: set[str], assist_threshold: float, max_age_s: float,
                    now: float, assist_enabled: bool = True) -> tuple[list[dict], list[str]]:
    """-> (ModelForecast list, blocking reason codes). Pure function (replay uses it on stored inputs)."""
    out, reasons = [], []
    seen = set()
    for p in preds or []:
        mid = str(p.get("family") or p.get("model_id") or "?")
        seen.add(mid)
        role = role_of(p, required)
        res = p.get("result") if p.get("state") == "READY" else None
        age = _age_s(p.get("data_time"), now)
        influence, why = "NONE", None
        opp = None
        if isinstance(res, dict) and p.get("task_type") == "CLASS_PROBABILITIES" and side in ("BUY", "SELL"):
            opp = res.get("DOWN") if side == "BUY" else res.get("UP")
        if role == "ASSIST" and assist_enabled and opp is not None and opp >= assist_threshold:
            influence, why = "HOLD", f"P({'DOWN' if side == 'BUY' else 'UP'})={opp:.2f}>={assist_threshold:.2f}"
            reasons.append(f"MODEL_ASSIST_HOLD:{mid}")
        elif role == "REQUIRED":
            if p.get("state") != "READY":
                influence, why = "BLOCK", f"stan {p.get('state')}"
                reasons.append(f"MODEL_REQUIRED_UNAVAILABLE:{mid}")
            elif age is None or age > max_age_s:
                influence, why = "BLOCK", "brak czasu danych" if age is None else f"wiek {age:.0f}s > {max_age_s:.0f}s"
                reasons.append(f"MODEL_REQUIRED_STALE:{mid}")
            elif opp is not None and opp >= 0.5:
                influence, why = "BLOCK", f"P(przeciwny)={opp:.2f}"
                reasons.append(f"MODEL_REQUIRED_CONTRARY:{mid}")
            else:
                influence = "PASS"
        out.append(K.make("ModelForecast", model_id=mid, role=role, state=str(p.get("state")), task_type=str(p.get("task_type")),
                          result=res, data_time=None if p.get("data_time") is None else str(p.get("data_time")),
                          age_s=None if age is None else round(age, 1), influence=influence, reason=why or p.get("unavailable_reason")))
    for mid in sorted(required - seen):
        out.append(K.make("ModelForecast", model_id=mid, role="REQUIRED", state="MISSING", task_type="UNKNOWN", result=None, influence="BLOCK",
                          reason="model REQUIRED nie zwrócił prognozy"))
        reasons.append(f"MODEL_REQUIRED_UNAVAILABLE:{mid}")
    return out, reasons


def final_verdict(base: str, gate_reasons: list[str], model_reasons: list[str]) -> str:
    if base != "ENTER":
        return base
    if gate_reasons or model_reasons:
        return "BLOCKED"
    return "ENTER"


class DecisionCoordinator:
    def __init__(self, db, cfg_store, *, families=None, instrument_fn=None, clock=time.time):
        self.db = db
        self.cfg_store = cfg_store
        self.families = families
        self.instrument_fn = instrument_fn or (lambda: getattr(cfg_store.get().mt5, "symbol", "XAUUSD"))
        self.clock = clock
        self.book = RiskBook(db, cfg_store, clock=clock)
        self.intents = IntentLedger(db, self.book)
        self.last: dict[str, dict] = {}

    def _cfg(self):
        return getattr(self.cfg_store.get(), "decision", None)

    def enabled(self) -> bool:
        c = self._cfg()
        return bool(c is None or c.enabled)

    def _preds(self) -> list[dict]:
        if self.families is None:
            return []
        try:
            return self.families.predictions(self.instrument_fn())
        except Exception:  # noqa: BLE001 - models never freeze a decision; REQUIRED then reports MISSING
            return []

    def decide(self, cand: dict, *, gates: dict, mode: str, account_key: str | None, preds: list[dict] | None = None,
               persist: bool = True) -> dict:
        """cand: StrategyCandidate; gates: {name: [reason codes]}; -> DecisionRecord (persisted once per inputs)."""
        errs = K.validate("StrategyCandidate", cand)
        if errs:
            raise K.ContractViolation("StrategyCandidate: " + ",".join(errs[:8]))
        c = self._cfg()
        fam_cfg = getattr(self.cfg_store.get(), "families", None)
        required = set(getattr(c, "required_models", []) or [])
        preds = self._preds() if preds is None else preds
        assist_ok = cand["path"] == "SH" or bool(getattr(c, "assist_on_active", True))
        models, mreasons = evaluate_models(preds, cand["side"], required=required,
                                           assist_threshold=float(getattr(fam_cfg, "assist_hold_threshold", 0.6)),
                                           max_age_s=float(getattr(c, "required_max_age_s", 900.0)), now=self.clock(), assist_enabled=assist_ok)
        greasons = [r for v in gates.values() for r in (v or [])]
        verdict = final_verdict(cand["base_verdict"], greasons, mreasons)
        core = {k: cand.get(k) for k in ("path", "strategy_id", "source_id", "side", "base_verdict", "reasons")}   # prices move every tick
        h = K.inputs_hash({"cand": core, "gates": gates, "models": [(m["model_id"], m["state"], m["influence"]) for m in models],
                           "mode": mode, "acct": account_key})
        rec = K.make("DecisionRecord", record_id="DR-" + uuid.uuid4().hex[:16], created_at=iso(utcnow()), path=cand["path"],
                     source_id=cand["source_id"], strategy_id=cand["strategy_id"], symbol=cand["symbol"], account_key=account_key,
                     mode=mode if mode in K.MODES else "SIGNALS", side=cand["side"], base_verdict=cand["base_verdict"], final_verdict=verdict,
                     reason_codes=list(cand.get("reasons") or []) + greasons + mreasons, models=models, gates=gates, inputs_hash=h)
        if persist:
            prev = self.db.one("SELECT record_id FROM decision_records WHERE path=? AND source_id=? AND inputs_hash=?",
                               (rec["path"], rec["source_id"], h))
            if prev:
                rec["record_id"] = prev["record_id"]
            else:
                self.db.execute("""INSERT OR IGNORE INTO decision_records(record_id, created_at, path, source_id, strategy_id, symbol, account_key, mode,
                                   direction, base_verdict, final_verdict, reason_codes, models_json, inputs_hash, record_json)
                                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                (rec["record_id"], rec["created_at"], rec["path"], rec["source_id"], rec["strategy_id"], rec["symbol"], account_key,
                                 rec["mode"], rec["side"], rec["base_verdict"], verdict, json.dumps(rec["reason_codes"]),
                                 json.dumps(models), h, json.dumps(rec, default=str)))
        self.last[cand["path"]] = rec
        return rec

    # ------------------------------------------------------------------ path adapters
    def model_gate_active(self, setup: dict | None) -> dict | None:
        """Main path: model roles for the CURRENT setup -> {'status': PASS|FAIL, 'codes', 'models'} (a decision-tree node), None = no node."""
        c = self._cfg()
        if not self.enabled() or not setup or setup.get("direction") not in ("LONG", "SHORT"):
            return None
        required = set(getattr(c, "required_models", []) or [])
        fam_cfg = getattr(self.cfg_store.get(), "families", None)
        side = "BUY" if setup["direction"] == "LONG" else "SELL"
        models, reasons = evaluate_models(self._preds(), side, required=required, assist_threshold=float(getattr(fam_cfg, "assist_hold_threshold", 0.6)),
                                          max_age_s=float(getattr(c, "required_max_age_s", 900.0)), now=self.clock(),
                                          assist_enabled=bool(getattr(c, "assist_on_active", True)))
        if not models:
            return None
        return {"status": "FAIL" if reasons else "PASS", "codes": reasons, "models": models}

    def active_candidate(self, d: dict) -> dict:
        side = {"LONG": "BUY", "SHORT": "SELL"}.get(d.get("analysis_direction"), "NONE")
        risk = d.get("risk") or {}
        su = d.get("setup") or {}
        fails = [n["node"] for n in d.get("decision_tree") or [] if n.get("status") != "PASS"]
        base = "ENTER" if (d.get("execution_permission") == "ALLOWED" or fails == ["MODELS"]) else \
            ("WAIT" if d.get("decision") == "WAIT" else "NO_TRADE")
        tg = risk.get("targets") or []
        return K.make("StrategyCandidate", path="ACTIVE", strategy_id=str(su.get("strategy_id") or "ACTIVE"), source_id=str(d["decision_id"]),
                      symbol=str(d.get("symbol")), side=side, base_verdict=base, entry=_f(risk.get("entry")), sl=_f(risk.get("stop_loss")),
                      tp=_f(tg[-1].get("price")) if tg else None, risk_money=_f(risk.get("modeled_loss")), volume=_f(risk.get("lots")),
                      reasons=[] if base == "ENTER" else [r for r in d.get("reason_codes") or [] if not r.startswith("MODEL_")][:12])

    def record_active(self, d: dict, mode: str, model_gate: dict | None) -> dict | None:
        """Persist the DecisionRecord of a NEW main-path decision (the engine calls it when content_hash changes)."""
        if not self.enabled():
            return None
        try:
            cand = self.active_candidate(d)
            gates = {"mode": list((d.get("mode_gate") or {}).get("reason_codes") or [])} if cand["base_verdict"] == "ENTER" else {}
            preds = [{"family": m["model_id"], "state": m["state"], "use": "ASSIST" if m["role"] == "ASSIST" else "SHADOW",
                      "task_type": m["task_type"], "result": m["result"], "data_time": m["data_time"], "unavailable_reason": m["reason"]}
                     for m in (model_gate or {}).get("models") or []]
            rec = self.decide(cand, gates=gates, mode=mode, account_key=d.get("account_key"), preds=preds)
            d["decision_record"] = {"record_id": rec["record_id"], "final_verdict": rec["final_verdict"],
                                    "models": [{k: m[k] for k in ("model_id", "role", "state", "influence", "reason")} for m in rec["models"]]}
            return rec
        except K.ContractViolation as exc:
            d["decision_record"] = {"error": str(exc)[:200]}
            return None

    def sh_candidate(self, su: dict, risk: dict | None) -> dict:
        side = su.get("side") if su.get("side") in ("BUY", "SELL") else "NONE"
        base = "ENTER" if su.get("status") == "READY" else ("WAIT" if su.get("status") == "WAIT" else "NO_TRADE")
        tps = su.get("tps") or []
        return K.make("StrategyCandidate", path="SH", strategy_id=str(su.get("strategy")), source_id=str(su.get("signal_id") or su.get("strategy")),
                      symbol=str(su.get("symbol") or self.instrument_fn()), side=side, base_verdict=base, entry=_f(su.get("entry_ref")),
                      sl=_f(su.get("sl")), tp=_f(tps[-1].get("price")) if tps else None, risk_money=_f((risk or {}).get("risk_money")),
                      volume=_f((risk or {}).get("volume")), reasons=[] if base == "ENTER" else [str(su.get("status_reason") or "")][:1])

    def record_sh(self, su: dict, risk: dict | None, mode: str, account_key: str | None, coord: dict | None = None) -> dict | None:
        """SH path: the SH receivers (families ASSIST hold, Kronos, arbitration) already ran on `su`; record the final decision."""
        if not self.enabled():
            return None
        try:
            fc = (su.get("family_context") or {}).get("context") or []
            preds = [{"family": x.get("family"), "state": x.get("state"), "use": x.get("use"), "task_type": x.get("task_type"),
                      "result": x.get("result"), "unavailable_reason": x.get("reason")} for x in fc]
            gates = {"coordination": [] if not coord or coord.get("allowed", True) else [str(coord.get("reason") or "ARBITRATION")]}
            return self.decide(self.sh_candidate(su, risk), gates=gates, mode=mode, account_key=account_key, preds=preds)
        except K.ContractViolation:
            return None

    def sync(self) -> dict:
        try:
            return self.intents.sync()
        except Exception as exc:  # noqa: BLE001
            return {"error": f"{type(exc).__name__}: {exc}"[:160]}

    def status(self) -> dict:
        return {"version": K.VERSION, "enabled": self.enabled(), "last": {k: {x: v.get(x) for x in ("record_id", "final_verdict", "reason_codes", "created_at")}
                                                                           for k, v in self.last.items()},
                "reservations_live": self.book.live(), "intents": self.intents.recent(20),
                "records": self.db.query("SELECT record_id, created_at, path, source_id, strategy_id, direction, base_verdict, final_verdict, reason_codes "
                                         "FROM decision_records ORDER BY created_at DESC LIMIT 30")}


def _f(v):
    try:
        x = float(v)
        return x if x == x and abs(x) != float("inf") else None
    except (TypeError, ValueError):
        return None
