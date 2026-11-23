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

import inspect
import json
import logging
import math
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
from . import ids as I
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
                    "assessment_max_age_s": 300.0,
                    # 1.41: confidence estimator. tabicl_v2 = the new default of the 1.41 update (DIRECT_USER_REQUEST: active as soon as the
                    # weights + a labelled context exist, no SHADOW / backtest / win-rate gate, raw = UNCALIBRATED); legacy_logistic = the
                    # 1.35 meta-model artifacts, read with their original meaning. A user choice stored in settings.json is never overwritten.
                    "estimator": "tabicl_v2",
                    "tabicl": {"enabled": True, "autostart": True, "activation_policy": "DIRECT_USER_REQUEST", "context_target": 512,
                               "context_max": 1024, "threads": 2, "auto_reconstruct": True, "reconstruct_days": 30, "max_queue_age_s": 120,
                               "context_refresh_s": 900}}
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
        if not isinstance(d, dict):
            # 1.46: valid JSON that is not an object ([] after a damaged / hand edit) was a TypeError in {**DEFAULT, **d} - it killed the
            # quant-core thread (settings are read outside its try) and /quant/status answered 500
            self.error = f"ustawienia Quant nie są obiektem JSON ({type(d).__name__}) – użyto domyślnych (SHADOW)"
            return json.loads(json.dumps(DEFAULT_SETTINGS))
        out = {**json.loads(json.dumps(DEFAULT_SETTINGS)), **d}
        if out.get("mode") not in MODES:
            self.error, out["mode"] = f"nieznany tryb {out.get('mode')!r} – SHADOW", "SHADOW"
        for k in ("assist", "tabicl"):                      # 1.46: sections read with .get() must stay objects
            if not isinstance(out.get(k), dict):
                self.error, out[k] = f"sekcja {k!r} ustawień Quant nie jest obiektem – domyślna", json.loads(json.dumps(DEFAULT_SETTINGS[k]))
        cs = out.get("cycle_s")
        if isinstance(cs, bool) or not isinstance(cs, (int, float)) or not math.isfinite(cs) or cs <= 0:
            # 1.46: '5s' (ValueError in float()) ended the loop thread; a negative value was a loop without a pause (100 % CPU)
            if cs is not None:
                self.error = f"cycle_s {cs!r} nie jest dodatnią liczbą – 5 s"
            out["cycle_s"] = DEFAULT_SETTINGS["cycle_s"]
        else:
            out["cycle_s"] = min(300.0, max(1.0, float(cs)))
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
        from .tabicl import TabICLService
        self.tabicl = TabICLService(self)                # 1.41 TabICLv2 confidence estimator (own process, async)
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

    def set_estimator(self, kind: str, *, by: str = "panel") -> dict:
        """1.41: tabicl_v2 (raw TabICLv2 confidence, DIRECT_USER_REQUEST) or legacy_logistic (1.35 artifacts, original meaning) -
        the rollback to the previous estimator. Stored in settings.json; the upgrade never overwrites a stored choice."""
        if kind not in ("tabicl_v2", "legacy_logistic"):
            return {"ok": False, "reason": f"nieznany estymator {kind}"}
        s = self.settings.get()
        hist = list(s.get("estimator_history") or [])[-49:]
        hist.append({"at": iso_ts(self.clock()), "from": s.get("estimator"), "to": kind, "by": by})
        s.update(estimator=kind, estimator_history=hist)
        self.settings.put(s)
        if kind == "tabicl_v2":
            self.tabicl.start()
        return {"ok": True, "estimator": kind}

    # ------------------------------------------------------------------ cycle
    def _build_dag(self) -> Dag:
        from ..modelhub import adapters as MA
        d = Dag(max_workers=2)
        d.add("snapshot", lambda c, _: S.build(c["rt"].bridge, instrument=c["inst"], now=c["now"]), owner="quant.snapshot", deadline_s=5.0)
        d.add("base_predictions", lambda c, _: MA.all_predictions(c["rt"], c["inst"]), deps=("snapshot",), owner="modelhub.adapters", deadline_s=20.0)
        d.add("extended_predictions", self._extended, deps=("snapshot",), owner="quant.adapters", deadline_s=25.0)
        # 1.46: the predictions are SOFT dependencies - a timed-out / failed branch no longer throws away the records of the other one
        # (the generation stays complete=False)
        d.add("contract_checks", self._checks, deps=("snapshot",), soft_deps=("base_predictions", "extended_predictions"), owner="quant.checks",
              deadline_s=5.0)
        return d

    def _extended(self, c, deps) -> list[dict]:
        snap = deps["snapshot"]
        m1 = S.last_closed(snap, "M1")
        # 1.46: the cache was keyed by the M1 bar only - after a switch of the instrument (same minute) the scalp A records of the previous
        # instrument went into the new generation; the key is (instrument, bar) and only records of this instrument are reused
        key = (c["inst"], m1["t"]) if m1 is not None else None
        new_m1 = key is not None and key != self._last_m1
        out = A.extended(c["rt"], c["inst"], self.event_gru, with_scalp=new_m1)
        if new_m1:
            self._last_m1 = key
            self._last_scalp = [p for p in out if p.get("canonical_id") == "scalp:A_direction"]
        else:
            out += [p for p in self._last_scalp if p.get("instrument") == c["inst"]]   # scalp A: one inference per closed M1 bar (cached)
        return out

    def _checks(self, c, deps) -> dict:
        snap = deps["snapshot"]
        floor = {tf: (bs[-1]["t"] if bs else None) for tf, bs in (snap.get("bars") or {}).items()}
        base, ext = _prefer_fresh(list(deps.get("base_predictions") or []), list(deps.get("extended_predictions") or []))
        return CK.screen(base + ext, now=c["now"], snapshot_kind=snap.get("data_kind"), generation_floor=floor)

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
        if (self.settings.get().get("tabicl") or {}).get("autostart", True):
            self.tabicl.start()

    def stop(self) -> None:
        self._stop.set()
        self.dag.shutdown()
        self.tabicl.stop()

    def _run(self) -> None:
        last_mature = 0.0
        while not self._stop.is_set():
            try:
                s = self.settings.get()
            except Exception as exc:  # noqa: BLE001 - 1.46: unreadable settings never end the loop thread (SHADOW defaults)
                self.loop["last_error"] = f"settings: {type(exc).__name__}: {exc}"[:300]
                s = json.loads(json.dumps(DEFAULT_SETTINGS))
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
            try:
                wait_s = min(300.0, max(1.0, float(s.get("cycle_s") or 5.0)))
            except (TypeError, ValueError):
                wait_s = 5.0
            self._stop.wait(wait_s)

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
        a.update(task_hash=th, event_id=spec.event_id, plan_hash=spec.plan_hash(), event=spec.task_dict(),
                 plan={"entry": spec.entry, "sl": spec.sl, "targets": [list(map(float, t)) for t in spec.targets]})
        preds, pub = self._eligible_at(float(cd.get("decision_ts") or now))
        rs = getattr(self.rt, "research", None)
        if rs is not None and "research_features" not in cd:       # 1.41 research-module features as known at decision time (as-of)
            try:
                cd = {**cd, "research_features": rs.features_for(inst, float(cd.get("decision_ts") or now))}
            except Exception:  # noqa: BLE001 - missing research features = missing columns, never invented values
                pass
        feats = F.build2(cd, preds)                     # 1.41 FEAT-2 = FEAT-1 (same names / meaning) + price-forecast + research-module columns
        a["sources"] = {"generation": (pub or {}).get("generation"), "eligible": len(preds), "excluded": len((pub or {}).get("excluded") or []),
                        "snapshot_status": ((pub or {}).get("snapshot") or {}).get("status"), "features": len(feats)}
        edges = [v for k, v in feats.items() if k.endswith(":edge")]
        a["conflict"] = {"agree": sum(1 for e in edges if e > 0), "disagree": sum(1 for e in edges if e < 0),
                         "note": "zgodność modeli z tego samego feedu nie jest niezależnym potwierdzeniem"}
        cost_known = spec.cost_price is not None
        a["costs"] = {"cost_price": spec.cost_price, "status": "KNOWN" if cost_known else "UNKNOWN", "spread": "W CENACH (bid/ask)",
                      "basis": "koszt odjęty raz w etykiecie net R; brak drugiego odjęcia"}
        # 1.41 TabICLv2: asynchronous, keyed by THIS plan_hash; the legacy meta-model path below is unchanged
        tb = self.tabicl.submit(cd, spec, feats, (pub or {}).get("generation"))
        a["tabicl"] = tb
        a["confidence"] = {"heuristic_score": cd.get("score"), "confidence_score": tb.get("confidence_score") if tb.get("state") == "READY" else None,
                           "p_event_raw": tb.get("p_event_raw") if tb.get("state") == "READY" else None, "event_id": spec.event_id,
                           "task_hash": th, "plan_hash": a["plan_hash"], "estimator_kind": "tabicl_v2", "state": tb.get("state"),
                           "reason": tb.get("reason"), "context_id": tb.get("context_id"), "calibration_status": "UNCALIBRATED",
                           "computed_at": tb.get("computed_at"), "influence": "RANKING_AND_PRESENTATION" if tb.get("state") == "READY" else "NONE",
                           "note": "surowy wynik modelu (nie zmierzony win rate); bez stałych premii; brak wyniku ≠ 50 %"}
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
                   "generation": (pub or {}).get("generation"), "data_kind": ((pub or {}).get("snapshot") or {}).get("data_kind") or self._bridge_kind(),
                   "matures_at": matures}
            a["row_id"] = row["row_id"]
            if self.ledger.add_row(row):
                self.loop["rows_logged"] += 1
            self.ledger.add_assessment(a)
            with self._lock:
                self.recent = ([a] + self.recent)[:200]
        return a

    def _bridge_kind(self) -> str:
        """1.46: data kind of a row logged before the first published generation (bot start, failed snapshot) - from the bridge itself
        (an explicit synthetic flag only), else UNKNOWN. Such rows were always UNKNOWN and blocked the data_real gate of the task."""
        br = getattr(self.rt, "bridge", None)
        syn = getattr(br, "synthetic", getattr(br, "_synthetic", None)) if br is not None else None
        return ("SYNTHETIC" if syn else "REAL") if isinstance(syn, bool) else "UNKNOWN"

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
        conf = a.get("confidence")
        if conf and conf.get("plan_hash"):
            cur = self.tabicl.lookup(conf["plan_hash"])          # the result may have arrived after the assessment - same plan only
            if cur and cur.get("state") == "READY":
                conf = {**conf, "confidence_score": cur["confidence_score"], "p_event_raw": cur["p_event_raw"], "state": "READY",
                        "context_id": cur.get("context_id"), "computed_at": cur.get("computed_at"), "influence": "RANKING_AND_PRESENTATION"}
        base["confidence"] = conf
        if a.get("status") != "READY":
            return {**base, "state": "NOT_TRAINED" if a.get("status") == "NOT_TRAINED" else "BLOCKED_DATA", "result": None,
                    "unavailable_reason": a.get("reason") or a.get("status")}
        return {**base, "state": "READY", "result": {"p": a["probability"]["p"], "e_net_r": (a.get("ev") or {}).get("e_net_r")},
                "quant_hold": a.get("would_hold"), "assessment_id": a["assessment_id"]}

    def confidence_for(self, strategy_id, side, entry, sl) -> dict | None:
        """1.41: the TabICLv2 confidence of the SAME plan (strategy, side, entry and SL within one price tick of the assessment) from the
        recent assessments - never another plan's value; None when there is none."""
        want = {"BUY": "LONG", "SELL": "SHORT"}.get(str(side), str(side))
        maxage = float(self.settings.get().get("assessment_max_age_s") or 300)
        with self._lock:
            rec = list(self.recent)
        for a in rec:
            if self.clock() - a["created_at"] > maxage or str(a.get("strategy")) != str(strategy_id) or a.get("direction") != want:
                continue
            ev = a.get("event") or {}
            conf = a.get("confidence")
            if not conf:
                continue
            # 1.46: `sl` was never compared - an SH variant with the same market entry and another SL got another plan's confidence; now
            # entry AND SL must match the assessed plan within one tick, otherwise there is no confidence for this plan (None)
            plan = a.get("plan") or {}
            try:
                spec_e, spec_sl = float(plan.get("entry")), float(plan.get("sl"))
                want_e, want_sl = float(entry), float(sl)
            except (TypeError, ValueError):
                continue
            if any(abs(w - v) > 1e-6 * max(1.0, abs(v)) + 0.011 for w, v in ((want_e, spec_e), (want_sl, spec_sl))):
                continue
            cur = self.tabicl.lookup(conf.get("plan_hash") or "")
            if cur and cur.get("state") == "READY":
                conf = {**conf, "confidence_score": cur["confidence_score"], "p_event_raw": cur["p_event_raw"], "state": "READY",
                        "context_id": cur.get("context_id"), "computed_at": cur.get("computed_at"), "influence": "RANKING_AND_PRESENTATION"}
            elif cur:
                conf = {**conf, "state": cur.get("state"), "reason": cur.get("reason")}
            return {k: conf.get(k) for k in ("estimator_kind", "state", "confidence_score", "p_event_raw", "event_id", "plan_hash", "task_hash",
                                             "calibration_status", "context_id", "computed_at", "influence", "reason", "heuristic_score")} | {"event": ev.get("event_id")}
        return None

    # ------------------------------------------------------------------ labels
    def mature(self, now: float | None = None) -> int:
        now = self.clock() if now is None else now
        inst = self.instrument()
        # 1.46: pending() returned the 500 oldest rows of ALL instruments and rows of another instrument are skipped below - with >= 500 of
        # them (after a switch BTC -> XAUUSD) the rows of the current instrument were never labelled. The instrument filter is used when
        # the ledger offers it.
        if "instrument" in inspect.signature(self.ledger.pending).parameters:
            rows = self.ledger.pending(now, instrument=inst)
        else:
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
            if r["instrument"] != inst or (sym_now and getattr(getattr(br, "cfg", None), "symbol", sym_now) != sym_now):
                continue                                              # bars of another instrument buffered now: wait, never mislabel
            if r["decision_ts"] < first - 60:
                self.ledger.label(r["row_id"], "NO_BARS", {"reason": "okno starsze niż bufor M1"}, None)
                n += 1
                continue
            # 1.46: one row whose spec no longer builds (field changed in a newer EventSpec, NaN plan of an older version) raised out of
            # mature() on every call - labelling stopped for good. Such a row is marked INVALID_SPEC (kept, with the reason); any other
            # error of one row leaves it PENDING and the loop goes on.
            try:
                spec_d = json.loads(r["spec_json"])
                spec = EV.EventSpec(**{k: (tuple(map(tuple, v)) if k == "targets" else v) for k, v in spec_d.items() if k not in ("task_hash", "plan_hash")})
            except (EV.EventError, TypeError, ValueError, AttributeError) as exc:
                self.ledger.label(r["row_id"], "INVALID_SPEC", {"reason": f"{type(exc).__name__}: {exc}"[:200]}, None)
                n += 1
                continue
            try:
                lab = EV.simulate(spec, bars, r["decision_ts"], available_until=last_close)
            except Exception as exc:  # noqa: BLE001 - one row never stops the labelling of the others
                self.loop["errors"] += 1
                self.loop["last_error"] = f"mature {r['row_id']}: {type(exc).__name__}: {exc}"[:300]
                continue
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
                "timings": percentiles(self.timings), "execution_allowed": False,
                "estimator": s.get("estimator"), "tabicl": _safe(self.tabicl.status, {})}

    def predictions(self) -> dict:
        pub = self.pub.current() or {}
        return {k: pub.get(k) for k in ("generation", "instrument", "computed_at", "eligible", "excluded", "aliases_dropped")}


def _fresher(a: dict, b: dict) -> bool:
    """a was computed later than b (computed_at, then data_time); unknown times never win."""
    for k in ("computed_at", "data_time"):
        ta, tb = CK.ts(a.get(k)), CK.ts(b.get(k))
        if ta is not None and tb is not None and ta != tb:
            return ta > tb
    return False


def _prefer_fresh(base: list[dict], ext: list[dict]) -> tuple[list[dict], list[dict]]:
    """1.46: ids.dedup keeps the FIRST record of one identity - base + extended kept the Event GRU answer of the PREVIOUS cycle (families
    read event_gru.latest before the extended adapters refresh it) and dropped the fresh one as an alias; a fresh ERROR never replaced an
    old READY. When base and extended carry the same identity, the later-computed record takes the base position (the other one is still
    reported as the dropped alias)."""
    if not base or not ext:
        return base, ext
    pos: dict[tuple, int] = {}
    for i, q in enumerate(ext):
        pos.setdefault(I.identity({**q, "canonical_id": I.canonical(q)}), i)
    base, ext = list(base), list(ext)
    for j, p in enumerate(base):
        k = I.identity({**p, "canonical_id": I.canonical(p)})
        i = pos.get(k)
        if i is not None and _fresher(ext[i], p):
            base[j], ext[i] = ext[i], p
            pos.pop(k)                                   # one swap per identity
    return base, ext


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
    # 1.46: a row logged before the first published generation had data_kind UNKNOWN - a few such rows from the start window kept the
    # task out of VALIDATED_SHADOW for good (gate data_real needs kinds == [REAL]). A row of unknown data origin proves nothing: it stays in
    # the ledger but is not training evidence (counted in the result).
    unknown: dict[str, int] = {}
    known = []
    for r in rows:
        if r.get("data_kind") in ("REAL", "SYNTHETIC"):
            known.append(r)
        else:
            unknown[r["task_hash"]] = unknown.get(r["task_hash"], 0) + 1
    if unknown:
        log(f"[QUANT] {inst}: pominięto {sum(unknown.values())} wierszy o nieznanym rodzaju danych (UNKNOWN) – nie są dowodem do treningu")
    rows = known
    by: dict[str, list] = {}
    for r in rows:
        by.setdefault(r["task_hash"], []).append(r)
    if not by:
        log(f"[QUANT] {inst}: brak oznaczonych wierszy w ledgerze – trening nieuruchomiony (INSUFFICIENT_EVIDENCE)")
        return [{"task_hash": task_hash, "status": "INSUFFICIENT_EVIDENCE", "reason": "brak oznaczonych wierszy",
                 "excluded_unknown_data_kind": sum(unknown.values())}]
    out = []
    for th, rs in sorted(by.items()):
        spec = rs[0]["spec"]
        seen = (M.pointer(inst).get("seen_tests") or {}).get(th, [])
        log(f"[QUANT] {inst} zadanie {th} ({spec.get('event_id')}): {len(rs)} wierszy")
        res = M.train(rs, task={"task_hash": th, "event_id": spec.get("event_id")}, crit=crit, seen_tests=seen)
        item = {"task_hash": th, "event_id": spec.get("event_id"), "status": res["status"], "n_rows": len(rs),
                "reason": res["report"].get("reason"), "failed_gates": res["report"].get("failed_gates"),
                "excluded_unknown_data_kind": unknown.get(th, 0)}
        if "model" in res:
            ver = M.save(inst, res, spec=spec)
            M.record_test(inst, th, res["report"]["test_row_ids"])
            item["version"] = ver
            item["test"] = {k: res["report"]["test_once"].get(k) for k in ("log_loss", "prior_log_loss", "ece", "n")}
        log(f"[QUANT]   -> {item['status']} {item.get('version') or ''} {item.get('reason') or ''} {item.get('failed_gates') or ''}")
        out.append(item)
    return out
