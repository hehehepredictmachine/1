"""PMW Quant Core service (PMW-QUANT-SERVICE-1) - own thread in the runtime, independent of the panel.

Cycle (every `cycle_s`, default 5 s; nothing heavy on the MT5 / API / coordinator threads):
  snapshot (MarketBridge buffers, QC) -> base predictions (modelhub.adapters.all_predictions: trainhub, Kronos, families, gold_candles)
  + extended adapters (quant/adapters.py: rules, indicators, DXY, zones, MC, MM, Event GRU, scalp A, lab) -> contract / alias / time
  checks -> atomic publication of the generation (data/quant/snapshot.json). API reads only the published generation.
Setup candidates (EvaluationService listener) -> ledger row with the decision-time features + EventSpec, and a SHADOW assessment when a
VALIDATED_SHADOW meta-model exists for the task; matured rows are labelled by the plan simulator (quant/events.py).
Modes (data/quant/settings.json): OFF | SHADOW (default) | ASSIST. ASSIST requires a VALIDATED_SHADOW active model for the instrument AND
an explicit activation by the user (`quant mode ASSIST --confirm` / POST /api/v1/quant/mode with confirm); installation and training
never switch it on. ASSIST can only HOLD an existing candidate through the DecisionCoordinator (MODEL_QUANT_HOLD); it creates no order
path, changes no limit and never turns WAIT into ENTER. execution_allowed is always False here.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from pathlib import Path

import numpy as np

from .. import paths
from ..timeutil import from_epoch, iso
from . import adapters as A
from . import checks as CK
from . import events as EV
from . import features as F
from . import metamodel as M
from . import snapshot as S
from . import units as U
from .ledger import QuantLedger
from .scheduler import Dag, Publisher, write_json_atomic

VERSION = "PMW-QUANT-SERVICE-1"


def iso_ts(t: float) -> str:
    return iso(from_epoch(float(t)))
MODES = ("OFF", "SHADOW", "ASSIST")
DEFAULT_SETTINGS = {"mode": "SHADOW", "assist": {"activated": False, "activated_at": None, "activated_by": None}, "cycle_s": 5.0,
                    "assessment_max_age_s": 300.0}
log = logging.getLogger("masterquo.quant")


def qdir() -> Path:
    p = paths.data_dir() / "quant"
    p.mkdir(parents=True, exist_ok=True)
    return p


class Settings:
    def __init__(self, path: Path):
        self.path = path
        self.error = None

    def get(self) -> dict:
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return json.loads(json.dumps(DEFAULT_SETTINGS))
        except (OSError, ValueError) as exc:
            self.error = f"ustawienia Quant nieczytelne ({type(exc).__name__}) – użyto domyślnych (SHADOW)"
            return json.loads(json.dumps(DEFAULT_SETTINGS))
        out = {**json.loads(json.dumps(DEFAULT_SETTINGS)), **d}
        if out.get("mode") not in MODES:
            self.error, out["mode"] = f"nieznany tryb {out.get('mode')!r} – SHADOW", "SHADOW"
        return out

    def put(self, d: dict) -> None:
        write_json_atomic(self.path, d)


class QuantService:
    def __init__(self, rt, *, data_dir: Path | None = None, clock=time.time):
        self.rt, self.clock = rt, clock
        base = Path(data_dir) if data_dir else qdir()
        base.mkdir(parents=True, exist_ok=True)
        self.base = base
        self.settings = Settings(base / "settings.json")
        self.ledger = QuantLedger(base / "ledger.sqlite")
        self.pub = Publisher(base / "snapshot.json")
        self.event_gru = A.EventGRU()
        self.gen = 0
        self.dag = self._build_dag()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._models: dict = {}                         # (inst, task_hash) -> (version, model) cache; dropped on pointer change
        self._last_m1 = None
        self._last_scalp: list[dict] = []
        self.recent: list[dict] = []                    # last assessments (memory) for the coordinator lookup
        self.jobs: dict[str, dict] = {}
        self.loop = {"cycles": 0, "errors": 0, "last_error": None, "last_cycle_at": None, "matured": 0, "rows_logged": 0, "rows_skipped": 0}
        self.timings: dict[str, list[float]] = {}

    # ------------------------------------------------------------------ settings / mode
    def mode(self) -> str:
        return self.settings.get()["mode"]

    def instrument(self) -> str:
        try:
            return self.rt.sh.instrument()
        except Exception:  # noqa: BLE001
            return "XAUUSD"

    def validated_active(self, inst: str) -> dict:
        p = M.pointer(inst)
        out = {}
        for th, ver in (p.get("active") or {}).items():
            try:
                _, man = M.load(inst, th, ver)
                if man["status"] == "VALIDATED_SHADOW":
                    out[th] = ver
            except Exception:  # noqa: BLE001 - an incompatible / broken artifact is not active evidence
                continue
        return out

    def assist_active(self) -> bool:
        s = self.settings.get()
        return s["mode"] == "ASSIST" and bool((s.get("assist") or {}).get("activated")) and bool(self.validated_active(self.instrument()))

    def set_mode(self, mode: str, *, confirm: bool = False, by: str = "CLI") -> dict:
        mode = str(mode).upper()
        if mode not in MODES:
            return {"ok": False, "reason": f"nieznany tryb {mode}"}
        s = self.settings.get()
        if mode == "ASSIST":
            act = self.validated_active(self.instrument())
            if not act:
                return {"ok": False, "reason": "ASSIST wymaga aktywnego, zwalidowanego (VALIDATED_SHADOW) meta-modelu dla instrumentu – brak"}
            if not confirm:
                return {"ok": False, "reason": "ASSIST wymaga jawnego potwierdzenia użytkownika (confirm=true / --confirm)"}
            s["assist"] = {"activated": True, "activated_at": iso_ts(self.clock()), "activated_by": by, "models": act}
        else:
            s["assist"] = {"activated": False, "activated_at": None, "activated_by": None}
        s["mode"] = mode
        self.settings.put(s)
        return {"ok": True, "mode": mode, "assist": s["assist"]}

    # ------------------------------------------------------------------ cycle
    def _build_dag(self) -> Dag:
        from ..modelhub import adapters as MA
        d = Dag(max_workers=2)
        d.add("snapshot", lambda c, _: S.build(c["rt"].bridge, instrument=c["inst"], now=c["now"]), owner="quant.snapshot", deadline_s=5.0)
        d.add("base_predictions", lambda c, _: MA.all_predictions(c["rt"], c["inst"]), deps=("snapshot",), owner="modelhub.adapters", deadline_s=20.0)
        d.add("extended_predictions", self._extended, deps=("snapshot",), owner="quant.adapters", deadline_s=25.0)
        d.add("contract_checks", self._checks, deps=("snapshot", "base_predictions", "extended_predictions"), owner="quant.checks", deadline_s=5.0)
        return d

    def _extended(self, c, deps) -> list[dict]:
        snap = deps["snapshot"]
        m1 = S.last_closed(snap, "M1")
        new_m1 = m1 is not None and m1["t"] != self._last_m1
        out = A.extended(c["rt"], c["inst"], self.event_gru, with_scalp=new_m1)
        if new_m1:
            self._last_m1 = m1["t"]
            self._last_scalp = [p for p in out if p.get("canonical_id") == "scalp:A_direction"]
        else:
            out += self._last_scalp                       # scalp A: one inference per closed M1 bar (cached between bars)
        return out

    def _checks(self, c, deps) -> dict:
        snap = deps["snapshot"]
        floor = {tf: (bs[-1]["t"] if bs else None) for tf, bs in (snap.get("bars") or {}).items()}
        return CK.screen(deps["base_predictions"] + deps["extended_predictions"], now=c["now"], snapshot_kind=snap.get("data_kind"),
                         generation_floor=floor)

    def cycle(self) -> dict:
        inst = self.instrument()
        now = self.clock()
        with self._lock:
            self.gen += 1
            gen = self.gen
        r = self.dag.run({"rt": self.rt, "inst": inst, "now": now, "gen": gen}, gen)
        for name, t in r["tasks"].items():
            self.timings.setdefault(name, []).append(t["ms"])
            self.timings[name] = self.timings[name][-500:]
        self.timings.setdefault("_cycle", []).append(r["cycle_ms"])
        self.timings["_cycle"] = self.timings["_cycle"][-500:]
        snap = (r["tasks"].get("snapshot") or {}).get("value")
        chk = (r["tasks"].get("contract_checks") or {}).get("value") or {"eligible": [], "excluded": [], "aliases_dropped": []}
        payload = {"version": VERSION, "generation": gen, "instrument": inst, "computed_at": now, "complete": r["complete"], "cycle_ms": r["cycle_ms"],
                   "tasks": {k: {x: v.get(x) for x in ("status", "reason", "ms", "owner")} for k, v in r["tasks"].items()},
                   "snapshot": S.summary(snap) if snap else None, "eligible": chk["eligible"], "excluded": chk["excluded"],
                   "aliases_dropped": chk["aliases_dropped"], "mode": self.mode(), "execution_allowed": False}
        self.pub.publish(payload)
        self.loop["cycles"] += 1
        self.loop["last_cycle_at"] = now
        return payload

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="quant-core", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.dag.shutdown()

    def _run(self) -> None:
        last_mature = 0.0
        while not self._stop.is_set():
            s = self.settings.get()
            if s["mode"] != "OFF":
                try:
                    self.cycle()
                except Exception as exc:  # noqa: BLE001 - the loop never dies; the error is visible in status
                    self.loop["errors"] += 1
                    self.loop["last_error"] = f"{type(exc).__name__}: {exc}"[:300]
                    log.exception("quant cycle failed")
                if self.clock() - last_mature >= 30:
                    last_mature = self.clock()
                    try:
                        self.mature()
                    except Exception as exc:  # noqa: BLE001
                        self.loop["last_error"] = f"mature: {type(exc).__name__}: {exc}"[:300]
            self._stop.wait(float(s.get("cycle_s") or 5.0))

    # ------------------------------------------------------------------ candidates
    def _eligible_at(self, t: float) -> tuple[list[dict], dict | None]:
        pub = self.pub.current()
        if not pub:
            return [], None
        out = []
        for p in pub["eligible"]:
            av = CK.ts(p.get("available_at")) or CK.ts(p.get("data_time"))
            if av is not None and av <= t + CK.CLOCK_TOLERANCE_S:            # only what was available at the decision
                out.append(p)
        return out, pub

    def _model(self, inst: str, th: str):
        ver = (M.pointer(inst).get("active") or {}).get(th)
        if not ver:
            return None, None, None
        with self._lock:
            hit = self._models.get((inst, th))
            if hit and hit[0] == ver:
                return hit
        try:
            model, man = M.load(inst, th, ver)
        except Exception as exc:  # noqa: BLE001
            return ver, None, {"status": "INCOMPATIBLE", "reason": str(exc)[:200]}
        if man["status"] != "VALIDATED_SHADOW":
            return ver, None, {"status": man["status"], "reason": "artefakt bez zaakceptowanej walidacji"}
        with self._lock:
            self._models[(inst, th)] = (ver, model, man)
        return ver, model, man

    def assess(self, cd: dict, *, mode: str | None = None, log_row: bool = False, evidence: dict | None = None) -> dict:
        """Assessment of one candidate dict (evaluation SetupCandidate.to_dict()). Cheap: dot products on the published snapshot."""
        mode = mode or self.mode()
        now = self.clock()
        inst = str(cd.get("instrument") or self.instrument())
        a = {"assessment_id": "QA-" + uuid.uuid4().hex[:14], "created_at": now, "mode": mode, "engine": cd.get("engine"), "strategy": cd.get("strategy_id"),
             "direction": cd.get("direction"), "candidate_key": cd.get("candidate_key") or cd.get("setup_id"), "decision_ts": cd.get("decision_ts"), "execution_allowed": False,
             "heuristic_score": cd.get("score"), "data_quality": cd.get("data_quality")}
        try:
            spec = EV.spec_from_candidate(cd)
        except (EV.EventError, KeyError, TypeError, ValueError) as exc:
            a.update(status="INVALID_PLAN", reason=f"plan poza EventSpec: {exc}"[:200])
            return a
        th = spec.task_hash()
        a.update(task_hash=th, event_id=spec.event_id, plan_hash=spec.plan_hash(), event=spec.task_dict())
        preds, pub = self._eligible_at(float(cd.get("decision_ts") or now))
        feats = F.build(cd, preds)
        a["sources"] = {"generation": (pub or {}).get("generation"), "eligible": len(preds), "excluded": len((pub or {}).get("excluded") or []),
                        "snapshot_status": ((pub or {}).get("snapshot") or {}).get("status"), "features": len(feats)}
        edges = [v for k, v in feats.items() if k.endswith(":edge")]
        a["conflict"] = {"agree": sum(1 for e in edges if e > 0), "disagree": sum(1 for e in edges if e < 0),
                         "note": "zgodność modeli z tego samego feedu nie jest niezależnym potwierdzeniem"}
        cost_known = spec.cost_price is not None
        a["costs"] = {"cost_price": spec.cost_price, "status": "KNOWN" if cost_known else "UNKNOWN", "spread": "W CENACH (bid/ask)",
                      "basis": "koszt odjęty raz w etykiecie net R; brak drugiego odjęcia"}
        ver, model, man = self._model(inst, th)
        if model is None:
            n = self.ledger.counts(inst)
            task = next((t for t in n["tasks"] if t["task_hash"] == th), None)
            a.update(status="NOT_TRAINED" if not ver else (man or {}).get("status", "INCOMPATIBLE"),
                     reason=("brak wytrenowanego modelu dla tego zdarzenia" if not ver else (man or {}).get("reason")),
                     probability=None, ev=None, evidence={"ledger_rows_for_task": (task or {}).get("by_status", {}), "positives": (task or {}).get("positives")})
        else:
            try:
                out = M.predict(model, feats)
            except M.MetaError as exc:
                a.update(status="ERROR", reason=str(exc), probability=None, ev=None)
                out = None
            if out is not None:
                a["status"] = "READY"
                a["model"] = {"version": ver, "calibrator": model["calibrator"]["kind"], "feature_schema": model["feature_schema"],
                              "test": {k: ((man.get("report") or {}).get("test_once") or {}).get(k) for k in ("log_loss", "prior_log_loss", "ece", "n")}}
                a["probability"] = {"p": out["p_event"], "event_id": spec.event_id, "status": "CALIBRATED_VALIDATED", "coverage": out["coverage"],
                                    "missing_features": out["missing_features"][:20], "interval": None,
                                    "interval_reason": "brak zwalidowanej metody przedziału dla pojedynczej predykcji"}
                R = spec.R
                tg = [(float(p), float(w)) for p, w in spec.targets]
                ev = {"e_net_r": out["e_net_r"], "method": "MODEL_E_NET_R (etykiety netto po kosztach)" if out["e_net_r"] is not None else None,
                      "outcome_interval_80": out["outcome_interval_80"], "interval_kind": "rozrzut przyszłego wyniku (kwantyle reszt CAL)",
                      "parameter_uncertainty": None, "parameter_uncertainty_reason": "nie estymowano – brak zwalidowanej metody"}
                if len(tg) == 1 and not spec.be_after:
                    g = (abs(tg[0][0] - spec.entry) - (spec.cost_price or 0.0)) / R
                    lr_ = (R + (spec.cost_price or 0.0)) / R
                    if g > 0 and spec.event_id == "TP1_BEFORE_STOP":
                        b = U.binary_ev(out["p_event"], g, lr_)
                        ev["binary"] = {**b, "status": "NET_VALIDATED_COSTS" if cost_known else "SCENARIO_UNKNOWN_COSTS"}
                else:
                    ev["binary"] = {"status": "EV_NEEDS_SCENARIOS", "reason": "plan z częściowymi wyjściami / BE – P(zdarzenia) nie jest rozkładem wypłat"}
                if not cost_known and ev["e_net_r"] is not None:
                    ev["status"] = "SCENARIO_UNKNOWN_COSTS"
                a["ev"] = ev
                hold = None
                if not cost_known:
                    hold = None                                       # unknown costs: never a validated net gate
                elif ev["e_net_r"] is not None and ev["e_net_r"] <= 0:
                    hold = f"Quant: E[net R] = {ev['e_net_r']:.3f} ≤ 0 (model {ver})"
                elif (ev.get("binary") or {}).get("break_even_p") is not None and out["p_event"] < ev["binary"]["break_even_p"]:
                    hold = f"Quant: P({spec.event_id}) = {out['p_event']:.3f} < próg {ev['binary']['break_even_p']:.3f}"
                a["would_hold"] = hold
                a["influence"] = "HOLD" if (mode == "ASSIST" and hold) else "NONE"
                a["contributions"] = M.contributions(model, feats)
        if log_row:
            matures = float(cd["decision_ts"]) + float(cd["horizon_s"])
            row = {"row_id": str(cd.get("candidate_key") or cd.get("setup_id")) + ":" + th, "instrument": inst, "engine": cd.get("engine"), "strategy": cd.get("strategy_id"),
                   "direction": cd.get("direction"), "decision_ts": float(cd["decision_ts"]), "task_hash": th, "event_id": spec.event_id,
                   "spec": spec.to_dict(), "features": feats, "snapshot_id": ((pub or {}).get("snapshot") or {}).get("snapshot_id"),
                   "generation": (pub or {}).get("generation"), "data_kind": ((pub or {}).get("snapshot") or {}).get("data_kind") or "UNKNOWN",
                   "matures_at": matures}
            a["row_id"] = row["row_id"]
            if self.ledger.add_row(row):
                self.loop["rows_logged"] += 1
            self.ledger.add_assessment(a)
            with self._lock:
                self.recent = ([a] + self.recent)[:200]
        return a

    def on_candidate(self, c, ad: dict | None = None) -> None:
        """EvaluationService listener (after its own ledger write). Never raises into the caller."""
        try:
            if self.mode() == "OFF":
                return
            cd = c.to_dict() if hasattr(c, "to_dict") else dict(c)
            if hasattr(c, "key"):
                cd["candidate_key"] = c.key()
            self.assess(cd, log_row=True)
        except Exception as exc:  # noqa: BLE001
            self.loop["rows_skipped"] += 1
            self.loop["last_error"] = f"on_candidate: {type(exc).__name__}: {exc}"[:300]

    # ------------------------------------------------------------------ coordinator interface (ASSIST only)
    def coordinator_predictions(self, inst: str) -> list[dict]:
        pub = self.pub.current() or {}
        if pub.get("instrument") != inst:
            return []
        return [dict(p, model_id=p.get("family") or p.get("canonical_id")) for p in pub.get("eligible") or []]

    def coordinator_entry(self, path: str, *, cand: dict | None = None, setup: dict | None = None) -> dict | None:
        base = {"family": "quant:metamodel", "use": "ASSIST", "task_type": "EVENT_PROBABILITY", "data_time": iso_ts(self.clock())}
        if cand is not None:
            a = self.assess(cand, mode="ASSIST")
        else:
            maxage = float(self.settings.get().get("assessment_max_age_s") or 300)
            sid = str((setup or {}).get("strategy_id") or "")
            want = (setup or {}).get("direction")
            with self._lock:
                a = next((x for x in self.recent if x.get("engine") == "ACTIVE_S01_S12" and str(x.get("strategy")) == sid and x.get("direction") == want
                          and self.clock() - x["created_at"] <= maxage), None)
            if a is None:
                return {**base, "state": "BLOCKED_DATA", "result": None, "unavailable_reason": "brak bieżącej oceny Quant dla tego kandydata"}
        if a.get("status") != "READY":
            return {**base, "state": "NOT_TRAINED" if a.get("status") == "NOT_TRAINED" else "BLOCKED_DATA", "result": None,
                    "unavailable_reason": a.get("reason") or a.get("status")}
        return {**base, "state": "READY", "result": {"p": a["probability"]["p"], "e_net_r": (a.get("ev") or {}).get("e_net_r")},
                "quant_hold": a.get("would_hold"), "assessment_id": a["assessment_id"]}

    # ------------------------------------------------------------------ labels
    def mature(self, now: float | None = None) -> int:
        now = self.clock() if now is None else now
        rows = self.ledger.pending(now)
        if not rows:
            return 0
        br = self.rt.bridge
        raw = br.bars("M1", include_forming=False)
        bars = S.normalise(raw, "M1")
        if not bars:
            return 0
        pt = float((getattr(br, "symbol_info", None) or {}).get("point") or 0.0)
        for b, r in zip(bars, [x for x in raw if x.get("closed", True) and x.get("open_utc")]):
            b["spread_price"] = r["spread"] * pt if r.get("spread") is not None and pt else None
        first, last_close = bars[0]["t"], bars[-1]["close_t"]
        sym_now = getattr(br, "buffer_symbol", None)
        n = 0
        for r in rows:
            spec_d = json.loads(r["spec_json"])
            if r["instrument"] != self.instrument() or (sym_now and getattr(getattr(br, "cfg", None), "symbol", sym_now) != sym_now):
                continue                                              # bars of another instrument buffered now: wait, never mislabel
            if r["decision_ts"] < first - 60:
                self.ledger.label(r["row_id"], "NO_BARS", {"reason": "okno starsze niż bufor M1"}, None)
                n += 1
                continue
            spec = EV.EventSpec(**{k: (tuple(map(tuple, v)) if k == "targets" else v) for k, v in spec_d.items() if k not in ("task_hash", "plan_hash")})
            lab = EV.simulate(spec, bars, r["decision_ts"], available_until=last_close)
            if not lab.get("mature"):
                continue
            if lab.get("scenario") == "NO_BARS" or lab.get("y_event") is None:
                self.ledger.label(r["row_id"], "NO_BARS", lab, None)
            else:
                fills = lab.get("fills") or []
                resolve = max([float(f["t"]) + 60 for f in fills] or [r["decision_ts"] + spec.horizon_s])
                self.ledger.label(r["row_id"], "LABELLED", lab, resolve)
            n += 1
        self.loop["matured"] += n
        return n

    # ------------------------------------------------------------------ training (explicit call only)
    def train(self, inst: str | None = None, task_hash: str | None = None, *, background: bool = True, crit: dict | None = None) -> dict:
        inst = inst or self.instrument()
        jid = "QJ-" + uuid.uuid4().hex[:10]
        job = {"job_id": jid, "kind": "TRAIN_METAMODEL", "instrument": inst, "task_hash": task_hash, "state": "RUNNING", "started_at": self.clock(),
               "log": [], "results": [], "steps": ["dane z ledgera", "bloki DEV/CAL/TEST + purge", "OOF walk-forward", "kalibracja", "test jednokrotny",
                                                    "artefakt"]}
        self.jobs[jid] = job

        def work():
            try:
                job["results"] = train_from_ledger(self.ledger, inst, task_hash, crit=crit, log=job["log"].append)
                job["state"] = "DONE"
            except Exception as exc:  # noqa: BLE001
                job["state"], job["error"] = "FAILED", f"{type(exc).__name__}: {exc}"[:300]
            job["finished_at"] = self.clock()
            write_json_atomic(self.base / "jobs" / f"{jid}.json", job)
            with self._lock:
                self._models.clear()
        if background:
            threading.Thread(target=work, name="quant-train", daemon=True).start()
        else:
            work()
        return job

    # ------------------------------------------------------------------ read side
    def status(self) -> dict:
        inst = self.instrument()
        pub = self.pub.current() or {}
        el, ex = pub.get("eligible") or [], pub.get("excluded") or []
        by_reason: dict = {}
        for p in ex:
            k = str((p.get("eligibility") or {}).get("reason") or "?").split(":")[0]
            by_reason[k] = by_reason.get(k, 0) + 1
        s = self.settings.get()
        return {"version": VERSION, "instrument": inst, "mode": s["mode"], "assist": s.get("assist"), "assist_active": self.assist_active(),
                "settings_error": self.settings.error, "generation": pub.get("generation"), "complete": pub.get("complete"),
                "computed_at": pub.get("computed_at"), "cycle_ms": pub.get("cycle_ms"), "tasks": pub.get("tasks"), "snapshot": pub.get("snapshot"),
                "models": {"eligible": len(el), "excluded": len(ex), "excluded_by_reason": by_reason, "aliases_dropped": len(pub.get("aliases_dropped") or []),
                           "ready_ids": sorted({p.get("canonical_id") for p in el})},
                "setup_scoped": _safe(lambda: A.setup_scoped(self.rt, inst), []),
                "metamodel": {"active": M.pointer(inst).get("active"), "validated_active": self.validated_active(inst), "versions": M.list_versions(inst)[-20:]},
                "ledger": self.ledger.counts(inst), "loop": dict(self.loop), "jobs": [{k: j.get(k) for k in ("job_id", "state", "started_at", "finished_at",
                                                                                                          "error")} for j in self.jobs.values()][-10:],
                "timings": percentiles(self.timings), "execution_allowed": False}

    def predictions(self) -> dict:
        pub = self.pub.current() or {}
        return {k: pub.get(k) for k in ("generation", "instrument", "computed_at", "eligible", "excluded", "aliases_dropped")}

    def bench(self, n: int = 20) -> dict:
        t0 = time.perf_counter()
        for _ in range(n):
            self.cycle()
        out = {"cycles": n, "wall_s": round(time.perf_counter() - t0, 3), "timings": percentiles(self.timings)}
        return out


def percentiles(tim: dict) -> dict:
    out = {}
    for k, v in tim.items():
        if v:
            a = np.asarray(v, float)
            out[k] = {"n": len(v), "p50_ms": round(float(np.percentile(a, 50)), 3), "p95_ms": round(float(np.percentile(a, 95)), 3),
                      "p99_ms": round(float(np.percentile(a, 99)), 3), "max_ms": round(float(a.max()), 3)}
    return out


def _safe(fn, default):
    try:
        return fn()
    except Exception:  # noqa: BLE001
        return default


def train_from_ledger(ledger: QuantLedger, inst: str, task_hash: str | None = None, *, crit: dict | None = None, log=print) -> list[dict]:
    rows = ledger.training_rows(inst, task_hash)
    by: dict[str, list] = {}
    for r in rows:
        by.setdefault(r["task_hash"], []).append(r)
    if not by:
        log(f"[QUANT] {inst}: brak oznaczonych wierszy w ledgerze – trening nieuruchomiony (INSUFFICIENT_EVIDENCE)")
        return [{"task_hash": task_hash, "status": "INSUFFICIENT_EVIDENCE", "reason": "brak oznaczonych wierszy"}]
    out = []
    for th, rs in sorted(by.items()):
        spec = rs[0]["spec"]
        seen = (M.pointer(inst).get("seen_tests") or {}).get(th, [])
        log(f"[QUANT] {inst} zadanie {th} ({spec.get('event_id')}): {len(rs)} wierszy")
        res = M.train(rs, task={"task_hash": th, "event_id": spec.get("event_id")}, crit=crit, seen_tests=seen)
        item = {"task_hash": th, "event_id": spec.get("event_id"), "status": res["status"], "n_rows": len(rs),
                "reason": res["report"].get("reason"), "failed_gates": res["report"].get("failed_gates")}
        if "model" in res:
            ver = M.save(inst, res, spec=spec)
            M.record_test(inst, th, res["report"]["test_row_ids"])
            item["version"] = ver
            item["test"] = {k: res["report"]["test_once"].get(k) for k in ("log_loss", "prior_log_loss", "ece", "n")}
        log(f"[QUANT]   -> {item['status']} {item.get('version') or ''} {item.get('reason') or ''} {item.get('failed_gates') or ''}")
        out.append(item)
    return out
