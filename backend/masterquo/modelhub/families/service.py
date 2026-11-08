"""FamilyService (PMW-FAM-SERVICE-1): catalog with the three state axes, training jobs in separate processes (queue of one active job
per family+instrument, cancel, orphan detection after restart), activation with integrity + inference-sample check, rollback, use roles,
live predictions in PMW-PRED-2 (cached per closed bar) and the receivers.

Receivers (documented path source -> features -> model -> contract -> receiver -> effect):
  * all_predictions (modelhub/adapters) - every READY prediction of a family whose use is SHADOW or ASSIST; aggregation keeps its own
    rules (one task / horizon / unit per group, no averaging of z-scores with probabilities).
  * SH setup (sh/service.cycle) - `family_context` for every evaluation (observation). In ASSIST only direction families
    (CLASS_PROBABILITIES) may HOLD a READY setup (READY -> WAIT) when P(opposite side) >= assist_hold_threshold; they never create or
    enlarge an entry. VOL_GARCH in ASSIST adds a volatility scenario to the risk view (sigma move over H bars); limits stay as configured.
  * panel / agent - catalog, status, last predictions.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import base as B
from . import registry

VERSION = "PMW-FAM-SERVICE-1"
DIRECTIONAL = ("SEQ_LSTM", "SEQ_GRU", "TS_ARIMA", "TS_SARIMAX")


class FamilyService:
    def __init__(self, cfg_store, bridge=None, *, indicators=None, news=None, store: B.Store | None = None, clock=time.time):
        self.cfg_store, self.bridge, self.indicators, self.news, self.clock = cfg_store, bridge, indicators, news, clock
        self.store = store or B.Store()
        self.fams = registry()
        self._lock = threading.RLock()
        self._cache: dict = {}
        self._loaded: dict = {}
        self.jobs_dir = self.store.base / "_jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.procs: dict[str, subprocess.Popen] = {}
        self._recover_orphans()

    def _cfg(self):
        return self.cfg_store.get().families

    # ------------------------------------------------------------------ catalog / status
    def status(self, fid: str, inst: str) -> dict:
        f = self.fams[fid]
        impl, why = f.implementation()
        if fid in ("TH_RF", "TH_XGB", "TH_SVM"):
            th = f.trainhub_state(inst)
            return {"implementation": impl, "implementation_reason": why, "artifact": th["artifact"], "use": th["use"], "trainhub": th}
        if fid == "SEQ_GRU_EVENT":
            ev = f.status_from_mm(inst)
            return {"implementation": "AVAILABLE", "artifact": ev["artifact"], "use": "SHADOW" if ev.get("version") else "OFF", "mm": ev}
        st = self.store.state(fid, inst)
        runs = self.store.runs(fid, inst)
        active = next((r for r in runs if r["run_id"] == st.get("active")), None)
        job = self.job(fid, inst)
        if job and job.get("state") == "RUNNING":
            art = "TRAINING"
        elif active:
            art = (active.get("validation") or {}).get("status") or "CANDIDATE"
            art = "APPROVED" if art == "APPROVED" else "CANDIDATE" if art != "VALIDATION_FAILED" else "VALIDATION_FAILED"
        elif runs:
            art = "CANDIDATE"
        else:
            art = "NOT_TRAINED"
        return {"implementation": impl, "implementation_reason": why, "artifact": art, "use": st.get("use", "OFF") if active else "OFF",
                "active_run": st.get("active"), "runs": len(runs), "last_run": runs[-1]["run_id"] if runs else None,
                "last_validation": (runs[-1].get("validation") or {}).get("status") if runs else None, "job": job}

    def catalog(self, inst: str) -> list[dict]:
        out = []
        for fid, f in self.fams.items():
            try:
                st = self.status(fid, inst)
            except Exception as exc:  # noqa: BLE001
                st = {"implementation": "ERROR", "implementation_reason": str(exc)[:200], "artifact": "NOT_TRAINED", "use": "OFF"}
            out.append({**f.capabilities(), "status": st, "data_requirements": f.data_requirements()})
        return out

    def runs(self, fid: str, inst: str) -> list[dict]:
        return [{k: r.get(k) for k in ("run_id", "created_at", "profile", "data_kind", "validation", "metrics", "data", "seconds", "deps")}
                for r in self.store.runs(fid, inst)]

    # ------------------------------------------------------------------ jobs (separate processes)
    def _job_file(self, fid, inst) -> Path:
        return self.jobs_dir / f"{fid}__{inst}.json"

    def job(self, fid, inst) -> dict | None:
        return B._read(self._job_file(fid, inst), None)

    def _recover_orphans(self) -> None:
        for p in self.jobs_dir.glob("*.json"):
            j = B._read(p, {}) or {}
            if j.get("state") == "RUNNING" and not _alive(j.get("pid")):
                j.update(state="FAILED", reason="proces treningu zakończył się bez wyniku (restart / awaria) – uruchom ponownie")
                B._atomic_json(p, j)

    def _job_config(self) -> dict:
        c = self._cfg()
        ind_db = None
        if self.indicators is not None:
            ind_db = str(self.indicators.dir / "indicators.sqlite")
        return {"pairs": c.pairs, "basket": c.basket, "indicators_db": ind_db, "nlp_transformer_path": c.nlp_transformer_path}

    def submit(self, fid: str, inst: str, profile: str = "smoke") -> dict:
        if fid not in self.fams:
            raise KeyError("FAMILY_UNKNOWN")
        if profile not in ("smoke", "research", "full"):
            raise ValueError("PROFILE_INVALID")
        with self._lock:
            j = self.job(fid, inst)
            if j and j.get("state") == "RUNNING" and _alive(j.get("pid")):
                return {"ok": False, "status": "ALREADY_RUNNING", "job": j}
            jf = self._job_file(fid, inst)
            B._atomic_json(jf, {"state": "QUEUED", "family": fid, "instrument": inst, "profile": profile, "submitted_at": self.clock()})
            from ... import paths
            argv = [sys.executable, "-m", "masterquo.modelhub.families.run", "--family", fid, "--instrument", inst, "--profile", profile,
                    "--job-file", str(jf), "--config", json.dumps(self._job_config())]
            env = dict(os.environ, PYTHONPATH=str(paths.ROOT_DIR / "backend"), PYTHONIOENCODING="utf-8",
                       PMW_FAMILIES_DIR=str(self.store.base))
            p = subprocess.Popen(argv, cwd=str(paths.ROOT_DIR / "backend"), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0))
            self.procs[f"{fid}__{inst}"] = p
            return {"ok": True, "status": "STARTED", "pid": p.pid}

    def cancel(self, fid: str, inst: str) -> dict:
        p = self.procs.get(f"{fid}__{inst}")
        j = self.job(fid, inst) or {}
        pid = j.get("pid") or (p.pid if p else None)
        if p is not None and p.poll() is None:
            p.terminate()
        elif pid and _alive(pid):
            try:
                os.kill(int(pid), 15)
            except OSError:
                pass
        j.update(state="CANCELLED", reason="anulowano przez użytkownika", updated_at=self.clock())
        B._atomic_json(self._job_file(fid, inst), j)
        return {"ok": True, "status": "CANCELLED"}

    def train_all(self, inst: str, profile: str = "smoke") -> dict:
        """Starts every family that can run; reports started / blocked / delegated separately (never one global 'success')."""
        out = {"started": [], "blocked": [], "delegated": []}
        for fid, f in self.fams.items():
            if fid == "SEQ_GRU_EVENT":
                out["delegated"].append({"family": fid, "reason": "trening w Centrum MM (mm/event_engine)"})
                continue
            if fid in ("TH_RF", "TH_XGB", "TH_SVM"):
                out["delegated"].append({"family": fid, "reason": "trainhub (Centrum treningu)"})
                continue
            impl, why = f.implementation()
            if impl != "AVAILABLE":
                out["blocked"].append({"family": fid, "reason": why})
                continue
            r = self.submit(fid, inst, profile)
            (out["started"] if r.get("ok") else out["blocked"]).append({"family": fid, **r})
        return out

    # ------------------------------------------------------------------ activation / roles
    def activate(self, fid: str, inst: str, rid: str) -> dict:
        ok, why = self.store.verify(fid, inst, rid)
        if not ok:
            return {"ok": False, "status": "INCOMPATIBLE", "reason": why}
        try:
            art = self.fams[fid].load(self.store.run_dir(fid, inst, rid))
            chk = self._sample_check(fid, art, self.store.run_dir(fid, inst, rid))
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "status": "INCOMPATIBLE", "reason": f"wczytanie / próbka inferencji: {type(exc).__name__}: {exc}"[:300]}
        if not chk["ok"]:
            return {"ok": False, "status": "INCOMPATIBLE", "reason": chk["reason"]}
        st = self.store.set_active(fid, inst, rid, "panel")
        self.invalidate(fid, inst)
        return {"ok": True, "status": "ACTIVE", "state": st, "sample_check": chk}

    def _sample_check(self, fid, art, d: Path) -> dict:
        import numpy as np
        m = B._read(d / "manifest.json", {}) or {}
        smp = m.get("sample") or {}
        exp, tol = smp.get("expected"), float(smp.get("tolerance") or 0.0)
        if exp is None:
            return {"ok": True, "checked": False, "reason": "rodzina bez deterministycznej próbki (np. PPO / koszyk) – sprawdzono wczytanie"}
        f = self.fams[fid]
        if fid in ("TS_ARIMA", "VOL_GARCH"):
            got = (f._forecast(art, np.asarray(smp["closes_tail"])))
        elif fid == "TS_SARIMAX":
            got = f._forecast_x(art, np.asarray(smp["closes_tail"]), np.asarray(smp["t_tail"], dtype=float))
        elif fid == "KALMAN_LS":
            got = f._state(art, [{"c": c, "t": t} for c, t in zip(smp["closes_tail"], smp["t_tail"])])
        elif fid == "BREAKOUT":
            got = f._state(art, smp["bars_tail"])
        elif fid == "MICROSTRUCTURE":
            got = f._proba(art, np.asarray(smp["X"])).tolist()
        elif fid == "NLP_SENTIMENT":
            got = f.score(art, smp["texts"]).tolist()
        elif fid in ("SEQ_LSTM", "SEQ_GRU"):
            from . import deep as D
            r = D.call("predict_seq", {"dir": str(d), "x_path": str(d / smp["x_file"])}, timeout=120)
            if not r.get("ok"):
                return {"ok": False, "reason": f"próbka inferencji: {r.get('error')}"}
            got = r["p"]
        else:
            return {"ok": True, "checked": False}
        diff = _maxdiff(got, exp)
        return {"ok": diff <= tol + 1e-12, "max_abs_diff": diff, "tolerance": tol, "checked": True,
                "reason": None if diff <= tol + 1e-12 else f"wynik po wczytaniu różni się od próbki ({diff:.3g} > {tol})"}

    def rollback(self, fid, inst) -> dict:
        st = self.store.rollback(fid, inst)
        self.invalidate(fid, inst)
        return {"ok": True, "state": st}

    def set_use(self, fid, inst, use) -> dict:
        st = self.store.set_use(fid, inst, use)
        self.invalidate(fid, inst)
        return {"ok": True, "state": st}

    def invalidate(self, fid=None, inst=None) -> None:
        with self._lock:
            for k in list(self._cache):
                if (fid is None or k[0] == fid) and (inst is None or k[1] == inst):
                    self._cache.pop(k, None)
            for k in list(self._loaded):
                if (fid is None or k[0] == fid) and (inst is None or k[1] == inst):
                    self._loaded.pop(k, None)

    # ------------------------------------------------------------------ live predictions
    def _live(self, f, inst) -> dict:
        live = {}
        tf = f.TF if f.TF and f.TF not in ("EVENT",) else None
        if tf and self.bridge is not None:
            live["bars"] = B.bars_from_bridge(self.bridge.bars(tf, include_forming=False))
        if f.ID == "MICROSTRUCTURE" and self.indicators is not None:
            s = self.indicators.current() or {}
            live["micro"] = s.get("microstructure")
            q = getattr(self.bridge, "quote", None) or {}
            if q.get("ask") is not None and q.get("bid") is not None:
                live["spread"] = float(q["ask"]) - float(q["bid"])
        if f.ID == "NLP_SENTIMENT" and self.news is not None:
            try:
                live["news"] = self.news.summary().get("news") or []
            except Exception:  # noqa: BLE001
                live["news"] = []
        return live

    def _artifact(self, fid, inst, rid):
        key = (fid, inst, rid)
        with self._lock:
            if key not in self._loaded:
                self._loaded[key] = self.fams[fid].load(self.store.run_dir(fid, inst, rid))
            return self._loaded[key]

    def predict(self, fid: str, inst: str) -> dict | None:
        f = self.fams[fid]
        if fid in ("TH_RF", "TH_XGB", "TH_SVM"):
            return None                                          # aliases of trainhub TH_*: the trainhub inference publishes them (one vote)
        if fid == "SEQ_GRU_EVENT":
            # 1.35: the Event GRU had no live path (MM only listed its artifact). The Quant scheduler owns its inference; here only the
            # cached READY result is read (no computation in the decision path); nothing READY -> no record, as before.
            prov = getattr(self, "event_gru_provider", None)
            p = prov(inst) if prov is not None else None
            return p if p and p.get("state") == "READY" else None
        st = self.store.state(fid, inst)
        rid, use = st.get("active"), st.get("use", "OFF")
        symbol = getattr(getattr(self.cfg_store.get(), "mt5", None), "symbol", None)
        if fid == "MICROSTRUCTURE" and rid is None:
            use = "SHADOW"                                       # measurements need no artifact
        if use == "OFF" and fid != "MICROSTRUCTURE":
            return None
        live = self._live(f, inst)
        bar_t = (live.get("bars") or [{}])[-1].get("t") if live.get("bars") else None
        data_t = bar_t
        if fid == "MICROSTRUCTURE":
            data_t = (live.get("micro") or {}).get("data_time")
        elif fid == "NLP_SENTIMENT":
            data_t = max((n.get("first_seen_at") or n.get("published_at") or "" for n in live.get("news") or []), default=None) or None
        ck = (fid, inst, rid, bar_t, use)
        with self._lock:
            if ck in self._cache and (bar_t is not None or self.clock() - self._cache[ck]["at"] < 5):
                return self._cache[ck]["pred"]
        man = B._read(self.store.run_dir(fid, inst, rid) / "manifest.json", {}) if rid else {}
        kind = man.get("data_kind") if man.get("data_kind") in ("REAL", "SYNTHETIC") else None
        impl, why = f.implementation()
        t0 = time.perf_counter()
        try:
            if impl != "AVAILABLE":
                raise B.Unavailable("BLOCKED_DATA", why)
            art = self._artifact(fid, inst, rid) if rid else None
            res = f.predict(art, live)
            calib = {"method": "temperature (walidacja)", "status": "CALIBRATED_DEV"} if f.TASK_TYPE == "CLASS_PROBABILITIES" else None
            pred = f.pred(inst=inst, symbol=symbol, state="READY", result=res, run_id=rid, data_time=data_t, data_kind=kind, calibration=calib,
                          extra={"use": use, "compute_ms": None})
        except B.Unavailable as u:
            state = u.state if u.state in ("BLOCKED_DATA", "ERROR", "NOT_TRAINED", "STALE", "INCOMPATIBLE") else "BLOCKED_DATA"
            pred = f.pred(inst=inst, symbol=symbol, state=state, reason=u.reason, run_id=rid, data_time=bar_t, extra={"use": use})
        except Exception as exc:  # noqa: BLE001
            pred = f.pred(inst=inst, symbol=symbol, state="ERROR", reason=f"{type(exc).__name__}: {exc}"[:200], run_id=rid, extra={"use": use})
        pred["compute_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        with self._lock:
            self._cache[ck] = {"pred": pred, "at": self.clock()}
        return pred

    def predictions(self, inst: str) -> list[dict]:
        if not self._cfg().enabled:
            return []
        out = []
        for fid in self.fams:
            try:
                p = self.predict(fid, inst)
            except Exception:  # noqa: BLE001
                p = None
            if p is not None:
                out.append(p)
        return out

    # ------------------------------------------------------------------ receivers
    def setup_context(self, su: dict, inst: str) -> dict:
        """Context for one SH evaluation + the ASSIST effect. Returns {'context': [...], 'hold': reason|None, 'vol': {...}|None}."""
        thr = float(self._cfg().assist_hold_threshold)
        ctx, hold, vol = [], None, None
        side = su.get("side")
        for p in self.predictions(inst):
            use = p.get("use")
            item = {"family": p.get("family"), "state": p["state"], "use": use, "task_type": p["task_type"], "result": p.get("result"),
                    "reason": p.get("unavailable_reason")}
            ctx.append(item)
            if p["state"] != "READY" or use != "ASSIST":
                continue
            r = p["result"]
            if p["task_type"] == "CLASS_PROBABILITIES" and side in ("BUY", "SELL") and isinstance(r, dict):
                opp = r.get("DOWN") if side == "BUY" else r.get("UP")
                if opp is not None and opp >= thr and hold is None:
                    hold = f"{p['family']} (ASSIST): P({'DOWN' if side == 'BUY' else 'UP'}) = {opp:.2f} ≥ {thr:.2f}"
            elif p["task_type"] == "VOLATILITY" and isinstance(r, dict):
                vol = {"family": p["family"], "sigma_h": r.get("sigma"), "price_move_1sigma": r.get("price_move_1sigma"), "horizon_bars": r.get("horizon_bars")}
        return {"context": ctx, "hold": hold, "vol": vol, "threshold": thr}


def apply_to_setup(su: dict, fc: dict) -> dict:
    """ASSIST receiver on a SH setup: may only turn READY into WAIT (with the reason in the checklist); never creates an entry."""
    su = dict(su)
    su["family_context"] = {k: fc.get(k) for k in ("context", "vol", "threshold")}
    if fc.get("hold") and su.get("status") == "READY":
        su["checklist"] = list(su.get("checklist") or []) + [{"key": "families_assist", "label": "Modele w roli ASSIST", "status": "WAIT",
                                                               "detail": fc["hold"]}]
        su["status"], su["status_reason"] = "WAIT", "wstrzymane przez model ASSIST: " + fc["hold"]
    return su


def _alive(pid) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def _maxdiff(a, b) -> float:
    import numpy as np
    if isinstance(a, dict) and isinstance(b, dict):
        ds = [_maxdiff(a[k], b.get(k)) for k in a if k in b]
        return max(ds) if ds else 0.0
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return float(np.max(np.abs(np.asarray(a, dtype=float) - np.asarray(b, dtype=float)))) if len(a) else 0.0
    if isinstance(a, str) or isinstance(b, str):
        return 0.0 if a == b else float("inf")
    if a is None or b is None:
        return 0.0 if a is b else float("inf")
    return abs(float(a) - float(b))
