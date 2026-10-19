"""NeuralScalpService - runtime of the Neural Scalp System (PMW-UPD-04), part of the lab lifecycle.

Own M1 clock (independent of the lab M5 key): ScalpService hands over
  * on_m1(bars, ...)          after every new closed M1 -> context telemetry of the encoders (latest wins, CONTEXT_ONLY)
  * submit(plan, bars, ...)   every strategy candidate BEFORE any model filter, as a frozen copy (never the mutable plan)
Work runs in one worker thread with a bounded queue (8 items, oldest dropped); a request older than TIMEOUT_S at dequeue is
TIMEOUT, a request of an older session / instrument / model is discarded. The inference record is written to the database
BEFORE the WS event 'lab_neural' is published; a DB failure is reported (NOT_ARCHIVED) and never shown as a registered decision.
OBSERVE (default) and SHADOW_GATE never change the scalp gates, risk, sizing or orders - there is no path to the gateway here.
"""
from __future__ import annotations

import collections
import copy
import hashlib
import json
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

from ..timeutil import iso, utcnow
from . import nss

QUEUE_MAX = 8
TIMEOUT_S = 2.0
CONTEXT_TTL_S = 60 + 15                       # next expected M1 close + documented receive tolerance
SCHEMA_VERSION = "PMW-NSS-SNAPSHOT-1"


class NeuralScalpService:
    def __init__(self, db, bus, log, instrument: str = "XAUUSD"):
        self.db, self.bus, self.log = db, bus, log
        self.inst = instrument
        self.q: collections.deque = collections.deque(maxlen=QUEUE_MAX)
        self._ctx_job = None
        self._cv = threading.Condition()
        self._stop = threading.Event()
        self._th = None
        self.seq = 0
        self.epoch = None
        self.last = None                      # last published snapshot (candidate)
        self.context = None                   # last context-only snapshot
        self.stats = {"queued": 0, "dropped_full": 0, "timeouts": 0, "stale_discarded": 0, "errors": 0, "not_archived": 0, "lat_ms": []}
        self.worker_status = "STOPPED"

    # -------------------------------------------------- lifecycle
    def start(self) -> None:
        if self._th and self._th.is_alive():
            return
        self._stop.clear()
        self._th = threading.Thread(target=self._loop, name="nss-worker", daemon=True)
        self._th.start()
        self.worker_status = "RUNNING"

    def stop(self) -> None:
        self._stop.set()
        with self._cv:
            self._cv.notify_all()
        if self._th:
            self._th.join(timeout=3)
        self.worker_status = "STOPPED"

    def reset(self, instrument: str, epoch) -> None:
        """Asset / account / session change: pending work of the old state is dropped, old answers are rejected."""
        with self._cv:
            if instrument != self.inst or epoch != self.epoch:
                self.stats["stale_discarded"] += len(self.q)
                self.q.clear()
                self._ctx_job = None
                self.inst, self.epoch = instrument, epoch
                self.last, self.context = None, None

    # -------------------------------------------------- producers (ScalpService thread - never waits for inference)
    @staticmethod
    def _tail(bars: dict) -> dict:
        n = {"M1": 200, "M5": 80, "M15": 40, "H1": 40}
        return {tf: [dict(b) for b in (bars.get(tf) or [])[-k:]] for tf, k in n.items()}

    def on_m1(self, bars: dict, *, instrument: str, epoch, point: float) -> None:
        self.reset(instrument, epoch)
        with self._cv:
            self._ctx_job = {"bars": self._with_spread(self._tail(bars), point), "instrument": instrument, "epoch": epoch, "at": time.time()}
            self._cv.notify()

    def submit(self, plan: dict, bars: dict, *, instrument: str, profile_hash: str, epoch, point: float, mode: str = "OBSERVE") -> dict:
        self.reset(instrument, epoch)
        rid = "NR-" + uuid.uuid4().hex[:12]
        job = {"request_id": rid, "plan": copy.deepcopy({k: plan.get(k) for k in ("setup_id", "range_id", "direction", "decision_ts", "decision_time", "sl", "tp1",
                                                                                 "tp2", "entry_mode", "features", "fill_shadow", "sizing", "economics", "limit_wait_m1")}),
               "bars": self._with_spread(self._tail(bars), point), "instrument": instrument, "profile_hash": profile_hash, "epoch": epoch, "mode": mode,
               "enqueued": time.time()}
        with self._cv:
            if len(self.q) == QUEUE_MAX:
                self.stats["dropped_full"] += 1
            self.q.append(job)
            self.stats["queued"] += 1
            self._cv.notify()
        return {"status": "QUEUED", "request_id": rid}

    @staticmethod
    def _with_spread(bars: dict, point: float) -> dict:
        for tf, bb in bars.items():
            for b in bb:
                if "spread_price" not in b:
                    b["spread_price"] = b["spread"] * point if b.get("spread") is not None else None
        return bars

    # -------------------------------------------------- worker
    def _loop(self) -> None:
        while not self._stop.is_set():
            with self._cv:
                while not self.q and self._ctx_job is None and not self._stop.is_set():
                    self._cv.wait(timeout=1.0)
                job = self.q.popleft() if self.q else None
                ctx = None if job else self._ctx_job
                if ctx is not None:
                    self._ctx_job = None
            try:
                if job:
                    self._candidate(job)
                elif ctx:
                    self._context(ctx)
            except Exception as exc:  # noqa: BLE001 - the worker never dies on one request
                self.stats["errors"] += 1
                if self.log:
                    self.log.error("NSS", "WORKER", f"{type(exc).__name__}: {exc}"[:300])

    def _current(self, job) -> bool:
        return job["instrument"] == self.inst and job["epoch"] == self.epoch

    def _context(self, job) -> None:
        if not self._current(job):
            self.stats["stale_discarded"] += 1
            return
        b, sel = nss.selected_bundle(job["instrument"])
        T = time.time()
        snap = nss.snapshot(nss.index_bars(job["bars"]), T, {}, b.cfg if b else None)
        layers = b.context_layers(snap) if b else None
        now = utcnow()
        self.context = {"schema_version": SCHEMA_VERSION, "task_id": nss.TASK_ID, "asset": job["instrument"], "telemetry_scope": "CONTEXT_ONLY",
                        "output_status": "NO_CANDIDATE", "candidate_output": None, "session_epoch": str(job["epoch"]),
                        "model_hash": b.man["model_hash"] if b else None, "mode": sel["role"] if sel else None,
                        "technical_status": "NO_MODEL" if not b else "READY_INFERENCE" if layers else
                        next((i["quality"].split(":")[0] for i in snap["inputs"] if i["quality"] != "OK" and i["tf"] in ("M1", "M5")), "WARMING_UP"),
                        "inputs": snap["inputs"], "layers": layers, "computed_at": iso(now), "expires_at": iso(now + timedelta(seconds=CONTEXT_TTL_S))}

    def _candidate(self, job) -> None:
        t_deq = time.time()
        if not self._current(job):
            self.stats["stale_discarded"] += 1
            return
        plan = job["plan"]
        side = plan["direction"]
        base = {"schema_version": SCHEMA_VERSION, "task_id": nss.TASK_ID, "asset": job["instrument"], "instrument_id": job["instrument"],
                "profile_hash": job["profile_hash"], "setup_id": plan["setup_id"], "side": side, "telemetry_scope": "CANDIDATE",
                "request_id": job["request_id"], "session_epoch": str(job["epoch"]), "signal_time": plan["decision_time"],
                "input_available_at": iso(datetime.fromtimestamp(job["enqueued"], timezone.utc)), "data_precision": "M1_OHLC_CLOSED"}
        queue_ms = (t_deq - job["enqueued"]) * 1000
        b, sel = nss.selected_bundle(job["instrument"])
        t0 = time.perf_counter()
        snap = nss.snapshot(nss.index_bars(job["bars"]), plan["decision_ts"], plan.get("features") or {}, b.cfg if b else None)
        feat_ms = (time.perf_counter() - t0) * 1000
        shash = hashlib.sha256(json.dumps({"m1": None if snap["m1"] is None else snap["m1"].round(8).tolist(), "m5": None if snap["m5"] is None else snap["m5"].round(8).tolist(),
                                           "ctx": [None if v != v else round(v, 8) for v in snap["ctx"].tolist()], "plan": plan}, default=str).encode()).hexdigest()[:16]
        if queue_ms > TIMEOUT_S * 1000:
            self.stats["timeouts"] += 1
            out = {"technical_status": "TIMEOUT", "reason": f"żądanie czekało {queue_ms:.0f} ms > {TIMEOUT_S * 1000:.0f} ms – wynik nie trafia do bieżącej polityki"}
        elif b is None:
            out = {"technical_status": "NO_MODEL", "reason": "brak wybranego modelu NSS (Modele i trening → Neural System)"}
        else:
            out = b.predict(snap, instrument=job["instrument"], profile_hash=job["profile_hash"], side=side, entry_mode=plan.get("entry_mode") or "MARKET",
                            telemetry=True)
        now = utcnow()
        mode = sel["role"] if sel else "OBSERVE"
        gated = bool(sel and mode == "SHADOW_GATE" and side in (sel.get("gated_sides") or []))
        if out.get("candidate_output"):
            co = out["candidate_output"]
            co.update(setup_id=plan["setup_id"], tp1=plan["tp1"], sl=plan["sl"], horizon_minutes=None,
                      filter_reasons=[] if gated else ["tylko obserwacja – polityka SHADOW_GATE nieaktywna dla tej strony"],
                      validity=iso(now + timedelta(seconds=120)))
        rec = dict(base, inference_id="NI-" + uuid.uuid4().hex[:16], snapshot_hash=shash, model_hash=out.get("model_hash"), mode=mode,
                   shadow_gate_active=gated, technical_status=out["technical_status"], evidence_status=self._evidence(sel), reasons=[out["reason"]] if out.get("reason") else [],
                   decision_time=iso(datetime.fromtimestamp(t_deq, timezone.utc)), computed_at=iso(now), expires_at=iso(now + timedelta(seconds=120)),
                   inputs=snap["inputs"], layers=out.get("layers"), candidate_output=out.get("candidate_output"), ensemble_member_ids=out.get("ensemble_member_ids"),
                   telemetry_member=out.get("telemetry_member"),
                   architecture=b.ens.members[0].architecture() if b else nss.static_architecture(),
                   timings={"feature_ms": round(feat_ms, 2), "queue_ms": round(queue_ms, 2), "inference_ms": out.get("inference_ms"),
                            "total_ms": round((time.time() - job["enqueued"]) * 1000, 2)})
        self.seq += 1
        rec["seq"] = self.seq
        try:
            self.db.execute("""INSERT OR IGNORE INTO nss_inferences(inference_id, request_id, task_id, instrument, profile_hash, setup_id, side, signal_time,
                               decision_time, computed_at, expires_at, session_epoch, model_hash, snapshot_hash, mode, technical_status, output, plan, timings)
                               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (rec["inference_id"], rec["request_id"], nss.TASK_ID, rec["asset"], rec["profile_hash"], rec["setup_id"], side, rec["signal_time"],
                             rec["decision_time"], rec["computed_at"], rec["expires_at"], rec["session_epoch"], rec["model_hash"], shash, mode,
                             rec["technical_status"], json.dumps(rec.get("candidate_output")), json.dumps(plan, default=str), json.dumps(rec["timings"])))
            rec["archived"] = True
        except Exception as exc:  # noqa: BLE001
            self.stats["not_archived"] += 1
            rec.update(archived=False, reasons=rec["reasons"] + [f"NOT_ARCHIVED: {exc}"[:200]])
        if not self._current(job):                  # instrument / session changed during the computation
            self.stats["stale_discarded"] += 1
            return
        self.stats["lat_ms"] = (self.stats["lat_ms"] + [rec["timings"]["total_ms"]])[-200:]
        self.last = rec
        self.bus.publish("lab_neural", {k: rec.get(k) for k in ("inference_id", "request_id", "seq", "asset", "setup_id", "side", "technical_status", "mode",
                                                                "model_hash", "snapshot_hash", "computed_at", "expires_at", "archived")}
                         | {"p": (rec.get("candidate_output") or {}).get("calibrated_probabilities"), "net_r": (rec.get("candidate_output") or {}).get("expected_net_R")})

    @staticmethod
    def _evidence(sel) -> str:
        if not sel:
            return "NO_MODEL"
        return "HOLDOUT_PASSED" if sel.get("gated_sides") else "NO_VALIDATED_EDGE_OR_RESEARCH"

    # -------------------------------------------------- labels (written later, never rewriting the prediction)
    def pending(self, limit: int = 50) -> list[dict]:
        return self.db.query("SELECT inference_id, plan FROM nss_inferences WHERE instrument=? AND label_status='PENDING' ORDER BY computed_at LIMIT ?",
                             (self.inst, limit))

    def label(self, inference_id: str, status: str, out: dict | None) -> None:
        if status == "SETTLED" and out and out.get("net_r") is not None:
            first = out["exits"][0]["reason"] if out.get("exits") else None
            ev = {"TP1": "TP1_FIRST", "SL": "SL_FIRST", "TIME": "TIMEOUT"}.get(first, "EARLY_EXIT")
            self.db.execute("UPDATE nss_inferences SET label_status='LABELED', label_event=?, label_net_r=?, label_end=?, label_available_at=? WHERE inference_id=?",
                            (ev, out["net_r"], out["label_end"], iso(utcnow()), inference_id))
        else:
            self.db.execute("UPDATE nss_inferences SET label_status=? WHERE inference_id=?",
                            ("NO_EXECUTABLE_ENTRY" if status == "MISSED_LIMIT" else "DATA_GAP", inference_id))

    # -------------------------------------------------- read side
    def public(self, asset: str) -> dict:
        if asset != self.inst:
            return {"asset": asset, "status": "ASSET_NOT_ACTIVE", "reason": f"NSS liczy dla aktywnego instrumentu {self.inst}", "snapshot": None, "context": None}
        b, sel = nss.selected_bundle(asset)
        now = utcnow()

        def fresh(x):
            if not x:
                return None
            exp = datetime.fromisoformat(x["expires_at"].replace("Z", "+00:00"))
            return dict(x, historical=exp < now)
        lat = sorted(self.stats["lat_ms"])
        p95 = lat[int(0.95 * (len(lat) - 1))] if lat else None
        p = nss.root(asset) / "registry.json"
        reg = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"runs": {}, "selected": None, "history": []}
        return {"asset": asset, "task_id": nss.TASK_ID, "architecture_id": nss.sn.ARCH_ID, "worker_status": self.worker_status, "queue": len(self.q),
                "stats": {k: v for k, v in self.stats.items() if k != "lat_ms"} | {"latency_p95_ms": p95, "n_latency": len(lat)},
                "selected": sel, "model": b.man if b else None, "snapshot": fresh(self.last), "context": fresh(self.context),
                "architecture": b.ens.members[0].architecture() if b else nss.static_architecture(), "trained": b is not None,
                "runs": dict(sorted(reg.get("runs", {}).items())[-10:]), "history_len": len(reg.get("history") or []),
                "criteria": nss.CRITERIA, "train_config": nss.TRAIN}

    def history(self, limit: int = 50) -> list[dict]:
        return self.db.query("SELECT inference_id, setup_id, side, signal_time, computed_at, model_hash, snapshot_hash, mode, technical_status, output, "
                             "label_status, label_event, label_net_r FROM nss_inferences WHERE instrument=? ORDER BY computed_at DESC LIMIT ?", (self.inst, limit))
