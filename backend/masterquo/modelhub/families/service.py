"""FamilyService (PMW-FAM-SERVICE-1): catalog with the three state axes, training jobs in separate processes (queue of one active job
per family+instrument, cancel, orphan detection after restart), activation with integrity + inference-sample check, rollback, use roles,
live predictions in PMW-PRED-2 (cached per closed bar) and the receivers.

Receivers (documented path source -> features -> model -> contract -> receiver -> effect):
  * all_predictions (modelhub/adapters) - every READY prediction of a family whose use is SHADOW or ASSIST; aggregation keeps its own
    rules (one task / horizon / unit per group, no averaging of z-scores with probabilities).
  * SH setup (sh/service.cycle) - `family_context` for every evaluation (observation). In ASSIST only direction families
    (CLASS_PROBABILITIES) may HOLD a READY setup (READY -> WAIT) when P(opposite side) >= assist_hold_threshold; they never create or
    enlarge an entry. VOL_GARCH in ASSIST only fills `family_context.vol` (sigma move over H bars - information; no risk receiver reads
    it in 1.46, limits / sizing / stops never use it). Any other result type has no ASSIST receiver - set_use refuses the role
    (ASSIST_NO_RECEIVER, 1.46 arch I0395 / I0472).
  * decision coordinator (decision/coordinator) - roles of the records (OBSERVE / ASSIST / REQUIRED) on the ACTIVE path and the SH record.
  * panel - catalog, status, last predictions (/api/v1/families). The agent does not read family predictions; declared but unconnected
    receivers (AGENT / RISK / STRATEGY / PORTFOLIO) are Family.PLANNED_RECEIVERS, never Family.RECEIVERS (1.46, I0400 / I0468).
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

# 1.46 arch (I0009): alias knowledge from the canonical registry (an import-free module)
from ...quant import ids as I
from . import base as B
from . import registry

VERSION = "PMW-FAM-SERVICE-1"
log = logging.getLogger(__name__)
# 1.46: families whose predict() needs the bars of every leg - _live() has no such path (only training reads the legs from the archive)
NO_LIVE_PATH = {"PAIR_COINT": "brak ścieżki danych na żywo dla nóg pary (pair_bars) – relacja jest liczona tylko w treningu",
                "STATARB": "brak ścieżki danych na żywo dla nóg koszyka (basket_bars) – reszty są liczone tylko w treningu",
                # 1.46 arch (I0464): _live() has no position source (exposure, entry price, bars in position) - an active PPO artifact was
                # BLOCKED_DATA forever, as if the data were only late
                "RL_PPO": "brak źródła stanu pozycji na żywo (ekspozycja, cena wejścia, świece w pozycji) – propozycja PPO jest liczona tylko "
                          "w treningu i walidacji"}
# 1.46 arch (I0395 / I0472): what the role ASSIST of a family record really does. The only receivers of a family record's role are
# setup_context (CLASS_PROBABILITIES -> HOLD READY -> WAIT; VOLATILITY -> volatility context of the SH view, information) and
# decision.coordinator.evaluate_models (CLASS_PROBABILITIES, a REGRESSION with result.direction - no family publishes one - and
# quant_hold). Every other result type had ASSIST accepted with no effect at all.
ASSIST_EFFECT = {"CLASS_PROBABILITIES": "HOLD_DIRECTION", "VOLATILITY": "CONTEXT_VOL"}
DELEGATED = ("TH_RF", "TH_XGB", "TH_SVM", "SEQ_GRU_EVENT")   # role / artifact owned by trainhub / MM - the family state is not read


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
        self._starting: set[str] = set()                 # 1.46: family+instrument reserved by submit() while its data are prepared
        self._inflight: dict = {}                        # 1.46 arch (I0450): cache key -> Event of the computation in progress
        self._verified: dict = {}                        # 1.46 arch (I0216): (fid, inst, rid) -> (stat signature, verify result)
        self._bg: threading.Thread | None = None         # 1.46 arch (I0790): deep precompute thread (start())
        self._bg_stop = threading.Event()
        self._bg_done: dict = {}                         # (fid, inst) -> cache key of the last background attempt
        self._recover_orphans()

    def _cfg(self):
        return self.cfg_store.get().families

    # ------------------------------------------------------------------ catalog / status
    def assist_effect(self, fid: str) -> str:
        """1.46 arch (I0395 / I0472): HOLD_DIRECTION | CONTEXT_VOL | NONE - what the role ASSIST of this family's record can do."""
        if fid in DELEGATED or fid in NO_LIVE_PATH:
            return "NONE"                                # role owned elsewhere / no live record: ASSIST of the family state has no effect
        return ASSIST_EFFECT.get(self.fams[fid].TASK_TYPE, "NONE")

    def _event_gru_impl(self) -> tuple[str, str | None]:
        """1.46 arch (I0477): the Event GRU computes only in the Quant thread (event_gru_provider) and the Quant loop runs only in a mode
        other than OFF - 'AVAILABLE' without Quant promised a prediction that never came. Read only (status / panel / CLI / inventory);
        predict() keeps reading the provider exactly as before; a failing probe is NO_SOURCE with its reason, never an exception."""
        if getattr(self, "event_gru_provider", None) is None:
            return "NO_SOURCE", "brak dostawcy Event GRU w tym procesie – inferencja działa tylko w wątku Quant działającego bota"
        live = getattr(self, "event_gru_live", None)
        if live is None:
            return "AVAILABLE", None
        try:
            on = bool(live())
        except Exception as exc:  # noqa: BLE001 - e.g. an unreadable quant settings file
            return "NO_SOURCE", f"stan Quant nieczytelny ({type(exc).__name__}: {exc})"[:200]
        return ("AVAILABLE", None) if on else ("NO_SOURCE", "Quant wyłączony (tryb OFF) – inferencja Event GRU działa w wątku Quant")

    def status(self, fid: str, inst: str) -> dict:
        f = self.fams[fid]
        eff = self.assist_effect(fid)
        if fid == I.EVENT_GRU_FAMILY:
            ev = f.status_from_mm(inst)
            impl, why = self._event_gru_impl()
            return {"implementation": impl, "implementation_reason": why, "artifact": ev["artifact"], "use": "SHADOW" if ev.get("version") else "OFF",
                    "mm": ev, "assist_gate_violation": None, "assist_effect": eff}
        impl, why = f.implementation()
        if fid in I.TRAINHUB_FAMILY_ALIASES:
            th = f.trainhub_state(inst)
            return {"implementation": impl, "implementation_reason": why, "artifact": th["artifact"], "use": th["use"], "trainhub": th,
                    "assist_gate_violation": None, "assist_effect": eff}   # trainhub owns the role (no family gate here)
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
        use = st.get("use", "OFF") if active else "OFF"
        # 1.46 D5: a role ASSIST saved before the gate covered activate / rollback may sit on an artifact that would not get it today -
        # shown (reason), never lowered here
        gate = self.store.assist_ok(fid, inst, st.get("active"))[1] if use == "ASSIST" else None
        return {"implementation": impl, "implementation_reason": why, "artifact": art, "use": use,
                "active_run": st.get("active"), "runs": len(runs), "last_run": runs[-1]["run_id"] if runs else None,
                "last_validation": (runs[-1].get("validation") or {}).get("status") if runs else None, "job": job,
                "assist_gate_violation": gate, "assist_effect": eff}

    def catalog(self, inst: str) -> list[dict]:
        out = []
        for fid, f in self.fams.items():
            eff = self.assist_effect(fid)
            try:
                st = self.status(fid, inst)
            except Exception as exc:  # noqa: BLE001
                st = {"implementation": "ERROR", "implementation_reason": str(exc)[:200], "artifact": "NOT_TRAINED", "use": "OFF",
                      "assist_gate_violation": None, "assist_effect": eff}
            out.append({**f.capabilities(), "assist_effect": eff, "status": st, "data_requirements": f.data_requirements()})
        return out

    def _known(self, fid: str) -> None:
        # 1.46: runs / rollback / set_use / cancel / activate checked nothing - GET /runs of an unknown name created folders and state.json
        if fid not in self.fams:
            raise KeyError("FAMILY_UNKNOWN")

    def runs(self, fid: str, inst: str) -> list[dict]:
        self._known(fid)
        return [{k: r.get(k) for k in ("run_id", "created_at", "profile", "data_kind", "validation", "metrics", "data", "seconds", "deps")}
                for r in self.store.runs(fid, inst)]

    # ------------------------------------------------------------------ jobs (separate processes)
    def _job_file(self, fid, inst) -> Path:
        return self.jobs_dir / f"{fid}__{inst}.json"

    def job(self, fid, inst) -> dict | None:
        j = B._read(self._job_file(fid, inst), None)
        if (j and j.get("state") in ("RUNNING", "QUEUED") and not j.get("waiting")   # 1.42.10: proces padł -> FAILED z końcówką logu
                and f"{fid}__{inst}" not in self._starting):                       # 1.46: submit() still preparing - no process yet
            p = self.procs.get(f"{fid}__{inst}")
            dead = (p.poll() is not None) if p is not None else (j.get("pid") and not _alive(j.get("pid")))
            if dead:
                fresh = B._read(self._job_file(fid, inst), None) or j           # proces mógł zdążyć zapisać wynik
                if fresh.get("state") in ("RUNNING", "QUEUED"):
                    fresh.update(state="FAILED", reason="proces treningu zakończył się bez wyniku: " + (self._log_tail(fid, inst) or "brak logu"),
                                 updated_at=self.clock())
                    B._atomic_json(self._job_file(fid, inst), fresh)
                j = fresh
        return j

    def _log_file(self, fid, inst) -> Path:
        return self.jobs_dir / f"{fid}__{inst}.log"

    def _log_tail(self, fid, inst, n: int = 400) -> str:
        try:
            txt = self._log_file(fid, inst).read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return ""
        lines = [x for x in txt.splitlines() if x.strip()]
        err = next((x for x in reversed(lines) if "Error" in x or "Exception" in x), None)
        return (err or (lines[-1] if lines else ""))[-n:]

    def _live_bars_file(self, fid: str, inst: str) -> Path | None:
        """1.42.10: dane świec rodziny pochodzą z archiwum eksportu (marketdata Store). Gdy archiwum ma za mało świec (np. przed pierwszym
        eksportem w Centrum treningu), proces dostaje świece z MT5 na żywo (zamknięte, ten sam format) – zamiast błędu „0 świec”."""
        f = self.fams[fid]
        d = getattr(f, "DATA", {}) or {}
        if d.get("kind") != "BARS" or self.bridge is None:
            return None
        tf, need = d.get("tf") or getattr(f, "TF", "M5"), int(d.get("min_bars") or 0)
        try:
            have = len(self.store_md().read(inst, tf)["time"])
        except Exception:  # noqa: BLE001 - brak archiwum = 0
            have = 0
        if have >= max(need, 1):
            return None
        try:
            m = self.cfg_store.get().assets.mappings.get(inst)
            sym = m.broker_symbol if m and m.broker_symbol else None
            rows = self.bridge.symbol_bars(sym, tf, int(min(20000, max(need * 3, 5000)))) if sym else []
        except Exception:  # noqa: BLE001 - brak połączenia: zostaje komunikat o braku danych
            rows = []
        bars = B.bars_from_bridge([r for r in rows if r.get("closed", True)])
        if len(bars) <= have:
            return None
        out = self.jobs_dir / f"{fid}__{inst}.bars.json"
        syn = getattr(self.bridge, "synthetic", None)       # 1.46: the demo simulator is not REAL data (decides the ASSIST gate)
        B._atomic_json(out, {"source": "MT5_LIVE_BRIDGE", "symbol": sym, "tf": tf, "bars": bars, "synthetic": syn if isinstance(syn, bool) else None})
        return out

    @staticmethod
    def store_md():
        from ...marketdata.store import Store
        return Store()

    def _recover_orphans(self) -> None:
        for p in self.jobs_dir.glob("*.json"):
            j = B._read(p, {}) or {}
            if j.get("state") == "RUNNING" and not _alive(j.get("pid")):
                j.update(state="FAILED", reason="proces treningu zakończył się bez wyniku (restart / awaria) – uruchom ponownie")
                B._atomic_json(p, j)
            elif j.get("state") == "QUEUED" and (j.get("waiting") or not j.get("pid") or not _alive(j.get("pid"))):
                # 1.46: the train_all queue thread does not survive a restart - a QUEUED job (waiting, or never started) waited forever
                j.update(state="CANCELLED", waiting=False, reason="kolejka przerwana restartem aplikacji – uruchom ponownie", updated_at=self.clock())
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
        from . import run as RUN
        why_d = RUN.delegated(fid, inst, profile)
        if why_d:
            # 1.46 (I0475): a family trained elsewhere (trainhub TH_*, MM SEQ_GRU_EVENT) starts no process - the answer run.train would
            # give, at once (as train_all reports it); SEQ_GRU_EVENT ended FAILED NotImplementedError
            impl, why = self.fams[fid].implementation()
            res = {"state": "DELEGATED", "reason": why_d} if impl == "AVAILABLE" else {"state": "BLOCKED", "reason": why}
            B._atomic_json(self._job_file(fid, inst), {**res, "family": fid, "instrument": inst, "profile": profile, "updated_at": self.clock()})
            return {"ok": False, "status": res["state"], "reason": res["reason"]}
        key = f"{fid}__{inst}"
        with self._lock:
            j = self.job(fid, inst)
            if j and j.get("state") == "RUNNING" and _alive(j.get("pid")):
                return {"ok": False, "status": "ALREADY_RUNNING", "job": j}
            own = self.procs.get(key)
            if (own is not None and own.poll() is None) or key in self._starting:   # 1.46: QUEUED until the child writes RUNNING - still one job per family+instrument
                return {"ok": False, "status": "ALREADY_RUNNING", "job": j}
            jf = self._job_file(fid, inst)
            B._atomic_json(jf, {"state": "QUEUED", "family": fid, "instrument": inst, "profile": profile, "submitted_at": self.clock()})
            self.procs.pop(key, None)                            # 1.46: the finished earlier run (poll() set) is not this job
            self._starting.add(key)
        # 1.46: the archive read, the MT5 history fetch (up to 20 000 bars through the MT5 queue) and the bars JSON run WITHOUT the service
        # lock - 1.45.0 held it here and predict() (SH cycle, decision coordinator) waited for the whole preparation. The reservation above
        # keeps one job per family+instrument.
        try:
            from ... import paths
            argv = [sys.executable, "-m", "masterquo.modelhub.families.run", "--family", fid, "--instrument", inst, "--profile", profile,
                    "--job-file", str(jf), "--config", json.dumps(self._job_config())]
            bf = self._live_bars_file(fid, inst)
            if bf is not None:
                argv += ["--bars-file", str(bf)]
            env = dict(os.environ, PYTHONPATH=paths.child_pythonpath(sys.executable), PYTHONIOENCODING="utf-8",   # 1.42.11: numpy w DESKTOP
                       PMW_FAMILIES_DIR=str(self.store.base))
            with self._lock:
                cur = B._read(jf, {}) or {}
                if cur.get("state") == "CANCELLED":              # 1.46: cancelled while the data were prepared - nothing is started
                    return {"ok": False, "status": "CANCELLED", "job": cur}
                log = open(self._log_file(fid, inst), "w", encoding="utf-8")     # 1.42.10: log procesu (był DEVNULL – awaria bez śladu)
                try:
                    p = subprocess.Popen(argv, cwd=str(paths.ROOT_DIR / "backend"), env=env, stdout=log, stderr=subprocess.STDOUT,
                                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0),
                                         start_new_session=os.name != "nt")     # 1.46: own group - cancel ends the whole tree
                except OSError as exc:
                    log.close()
                    B._atomic_json(jf, {"state": "FAILED", "family": fid, "instrument": inst, "reason": f"nie można uruchomić procesu: {exc}"[:300],
                                        "updated_at": self.clock()})
                    return {"ok": False, "status": "FAILED", "reason": str(exc)[:300]}
                log.close()
                self.procs[key] = p
                return {"ok": True, "status": "STARTED", "pid": p.pid}
        except Exception as exc:
            # 1.46: a failed preparation left the job QUEUED without a process - it never changed state until a restart
            B._atomic_json(jf, {"state": "FAILED", "family": fid, "instrument": inst, "profile": profile,
                                "reason": f"przygotowanie danych: {type(exc).__name__}: {exc}"[:300], "updated_at": self.clock()})
            raise
        finally:
            with self._lock:
                self._starting.discard(key)

    def cancel(self, fid: str, inst: str) -> dict:
        self._known(fid)
        p = self.procs.get(f"{fid}__{inst}")
        j = self.job(fid, inst) or {}
        pid = (p.pid if p is not None else None) or j.get("pid")
        # 1.46: the whole process tree - 1.45.0 terminated only the run process; the .venv_deep worker (SEQ_LSTM / SEQ_GRU / RL_PPO) kept
        # training for hours, outside MAX_PARALLEL
        if (p is not None and p.poll() is None) or (pid and _alive(pid)):
            _kill_tree(int(pid), p)
        j.update(state="CANCELLED", reason="anulowano przez użytkownika", updated_at=self.clock())
        B._atomic_json(self._job_file(fid, inst), j)
        return {"ok": True, "status": "CANCELLED"}

    MAX_PARALLEL = 2                                     # 1.42.10: „trenuj wszystkie” – najwyżej 2 procesy naraz (było ~12 równolegle)

    def train_all(self, inst: str, profile: str = "smoke") -> dict:
        """Starts every family that can run; reports started / queued / blocked / delegated separately (never one global 'success').
        1.42.10: at most MAX_PARALLEL family processes at once – the rest wait in a queue and start when a slot frees (on 8-16 GB computers
        a dozen parallel trainings ran out of memory)."""
        out = {"started": [], "queued": [], "blocked": [], "delegated": []}
        todo = []
        for fid, f in self.fams.items():
            if fid == I.EVENT_GRU_FAMILY:
                out["delegated"].append({"family": fid, "reason": "trening w Centrum MM (mm/event_engine)"})
                continue
            if fid in I.TRAINHUB_FAMILY_ALIASES:
                out["delegated"].append({"family": fid, "reason": "trainhub (Centrum treningu)"})
                continue
            impl, why = f.implementation()
            if impl != "AVAILABLE":
                out["blocked"].append({"family": fid, "reason": why})
                continue
            todo.append(fid)
        for fid in todo[:self.MAX_PARALLEL]:
            r = self.submit(fid, inst, profile)
            (out["started"] if r.get("ok") else out["blocked"]).append({"family": fid, **r})
        rest = todo[self.MAX_PARALLEL:]
        for fid in rest:
            B._atomic_json(self._job_file(fid, inst), {"state": "QUEUED", "family": fid, "instrument": inst, "profile": profile,
                                                      "submitted_at": self.clock(), "reason": "w kolejce – start po zwolnieniu miejsca",
                                                      "waiting": True})
            out["queued"].append({"family": fid, "status": "QUEUED"})
        if rest:
            threading.Thread(target=self._drain, args=(inst, profile, rest), name="families-queue", daemon=True).start()
        return out

    def _running(self) -> int:
        # 1.46: a job still preparing its data (no process yet) also takes a MAX_PARALLEL slot
        return sum(1 for p in list(self.procs.values()) if p.poll() is None) + len(self._starting)

    def _drain(self, inst: str, profile: str, rest: list[str]) -> None:
        for fid in rest:
            while self._running() >= self.MAX_PARALLEL:
                time.sleep(2.0)
            if not self.jobs_dir.exists():                       # katalog danych usunięty (np. po zamknięciu) – kończymy kolejkę
                return
            j = B._read(self._job_file(fid, inst), {}) or {}
            if j.get("state") != "QUEUED" or not j.get("waiting"):     # 1.46: cancelled, or started by hand meanwhile - never a second run
                continue
            try:
                self.submit(fid, inst, profile)
            except Exception as exc:  # noqa: BLE001 - jedna rodzina nie zatrzymuje kolejki
                B._atomic_json(self._job_file(fid, inst), {"state": "FAILED", "family": fid, "instrument": inst,
                                                          "reason": f"{type(exc).__name__}: {exc}"[:300], "updated_at": self.clock()})

    # ------------------------------------------------------------------ activation / roles
    def activate(self, fid: str, inst: str, rid: str) -> dict:
        self._known(fid)
        ok, why = self.store.verify(fid, inst, rid)
        if not ok:
            return {"ok": False, "status": "INCOMPATIBLE", "reason": why}
        try:
            self.store.assist_guard(fid, inst, rid, f"aktywowanie artefaktu {rid}")   # 1.46 D5: before the (costly) load + sample
        except B.AssistGate as exc:
            return {"ok": False, "status": "ASSIST_GATE", "reason": str(exc)}
        try:
            art = self.fams[fid].load(self.store.run_dir(fid, inst, rid))
            chk = self._sample_check(fid, art, self.store.run_dir(fid, inst, rid))
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "status": "INCOMPATIBLE", "reason": f"wczytanie / próbka inferencji: {type(exc).__name__}: {exc}"[:300]}
        if not chk["ok"]:
            return {"ok": False, "status": "INCOMPATIBLE", "reason": chk["reason"]}
        try:
            st = self.store.set_active(fid, inst, rid, "panel")
        except B.AssistGate as exc:                              # the role was set to ASSIST meanwhile
            return {"ok": False, "status": "ASSIST_GATE", "reason": str(exc)}
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
        elif fid == "PAIR_COINT" and smp.get("a_last") is not None and smp.get("b_last") is not None:
            got = {"z_last": f._z(art, float(smp["a_last"]), float(smp["b_last"]))}         # 1.46 (I0422); older samples: load only
        elif fid == "STATARB" and smp.get("prices_tail"):
            P = np.asarray(smp["prices_tail"], dtype=float)                                  # 1.46 (I0427)
            got = {"s_scores": [float(x) for x in f._scores(art, np.diff(np.log(P), axis=0))[0]]}
        elif fid in ("SEQ_LSTM", "SEQ_GRU"):
            from . import deep as D
            r = D.call("predict_seq", {"dir": str(d), "x_path": str(d / smp["x_file"])}, timeout=120)
            if not r.get("ok"):
                return {"ok": False, "reason": f"próbka inferencji: {r.get('error')}"}
            got = r["p"]
        elif fid == "RL_PPO":                               # 1.46 (I0466): action probabilities of the saved policy on the stored bars
            from . import deep as D
            r = D.call("predict_ppo", {"dir": str(d), "bars": smp["bars_tail"], "position": float(smp.get("position") or 0.0)}, timeout=120)
            if not r.get("ok"):
                return {"ok": False, "reason": f"próbka inferencji: {r.get('error')}"}
            got = r["probs"]
        else:
            return {"ok": True, "checked": False}
        diff = _maxdiff(got, exp)
        return {"ok": diff <= tol + 1e-12, "max_abs_diff": diff, "tolerance": tol, "checked": True,
                "reason": None if diff <= tol + 1e-12 else f"wynik po wczytaniu różni się od próbki ({diff:.3g} > {tol})"}

    def rollback(self, fid, inst) -> dict:
        self._known(fid)
        st = self.store.rollback(fid, inst)
        self.invalidate(fid, inst)
        return {"ok": True, "state": st}

    def set_use(self, fid, inst, use) -> dict:
        self._known(fid)
        if use == "ASSIST" and self.assist_effect(fid) == "NONE":
            # 1.46 arch (I0395 / I0472): refused before anything is written (API _fam -> 409, CLI -> 3). The gate's own answer first, so
            # an artifact that is not APPROVED / REAL is told exactly what it was told before. A role ASSIST saved earlier is not lowered
            # (it has no effect anyway).
            ok, why = self.store.assist_ok(fid, inst, self.store.state(fid, inst).get("active"))
            if not ok:
                raise ValueError(why)
            raise ValueError(f"ASSIST_NO_RECEIVER: typ wyniku {self.fams[fid].TASK_TYPE} rodziny {fid} nie ma odbiorcy roli ASSIST "
                             "(wstrzymanie READY -> WAIT działa tylko dla rozkładu kierunku, kontekst ryzyka dla zmienności) – rola bez skutku "
                             "nie jest nadawana; użyj SHADOW")
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
            for d in (self._verified, self._bg_done):
                for k in list(d):
                    if (fid is None or k[0] == fid) and (inst is None or k[1] == inst):
                        d.pop(k, None)

    # ------------------------------------------------------------------ live predictions
    def _live(self, f, inst) -> dict:
        live = {}
        tf = f.TF if f.TF and f.TF not in ("EVENT",) else None
        if tf and self.bridge is not None:
            live["bars"] = B.bars_from_bridge(self.bridge.bars(tf, include_forming=False))
        if f.ID == "MICROSTRUCTURE" and self.indicators is not None:
            s = self.indicators.current() or {}
            live["micro_snapshot"] = s.get("microstructure")
            # 1.46 arch (I0191): the values come from the CURRENT book (polled every book_period_s) - the snapshot is recomputed only per
            # closed M1 bar (up to ~60 s old for a 10 s classifier). Without microstructure_now() (stand-ins, old services) or when its
            # book is older than the snapshot's, the snapshot measurement as before. The record keeps the snapshot TIME (_micro_times).
            now_fn = getattr(self.indicators, "microstructure_now", None)
            fresh = None
            if now_fn is not None:
                try:
                    fresh = now_fn()
                except Exception:  # noqa: BLE001 - the snapshot measurement is used instead
                    fresh = None
            if fresh is not None and live["micro_snapshot"]:
                from ...quant import checks as QC
                t_f, t_s = QC.ts(fresh.get("data_time")), QC.ts(live["micro_snapshot"].get("data_time"))
                if t_f is not None and t_s is not None and t_f < t_s:
                    fresh = None
            live["micro"] = fresh if fresh is not None else live["micro_snapshot"]
            q = getattr(self.bridge, "quote", None) or {}
            if q.get("ask") is not None and q.get("bid") is not None:
                live["spread"] = float(q["ask"]) - float(q["bid"])
        if f.ID == "NLP_SENTIMENT" and self.news is not None:
            try:
                live["news"] = self.news.summary().get("news") or []
            except Exception:  # noqa: BLE001
                live["news"] = []
        return live

    def _micro_times(self, live) -> tuple:
        """1.46 arch (I0191; S0 of the first version withdrawn by tightening) -> (data_time, ttl_s, book_data_time) of the MICROSTRUCTURE
        record. data_time stays EXACTLY the 1.46 value - the time of the PMW-IND-1 snapshot measurement - although the values come from
        the current book: the coordinator measures the age of a REQUIRED model from data_time at DECISION time (required_max_age_s), up to
        5 s later from the family cache and later still from the Quant snapshot; a fresher data_time lifted MODEL_REQUIRED_STALE there
        (new entry). ttl_s (Quant) = the book TTL counted from the book actually read, never above the 1.46 state TTL (900 s): Quant
        excludes the record once that book is older than the book TTL and never later than in 1.46. book_data_time = time of that book."""
        from ...quant import checks as QC
        used = live.get("micro") or {}
        rec_t = (live.get("micro_snapshot") or {}).get("data_time") if "micro_snapshot" in live else used.get("data_time")
        try:
            period = float(self.cfg_store.get().indicators.book_period_s)
        except (AttributeError, TypeError, ValueError):
            period = 1.0
        ttl = max(10.0, 5.0 * period)
        t_rec, t_book = QC.ts(rec_t), QC.ts(used.get("data_time"))
        if t_rec is not None and t_book is not None and t_book > t_rec:
            ttl += t_book - t_rec
        return rec_t, min(ttl, QC.STATE_TTL_S), used.get("data_time")

    @staticmethod
    def _micro_snapshot_guard(live) -> tuple[str, str] | None:
        """1.46 arch (I0191, only tightening): the record is never READY where the 1.46 record (the snapshot measurement) was not - a
        snapshot measurement that is not READY gives exactly the 1.46 BLOCKED_DATA and reason, even with a READY current book. Its age is
        not checked here: the record keeps the snapshot data_time (_micro_times), so the coordinator and Quant apply the 1.46 age rules
        themselves, at their own (later) time."""
        if "micro_snapshot" not in live:
            return None
        snap = live.get("micro_snapshot") or {}
        if snap.get("status") != "READY":                          # exactly the 1.46 record of a snapshot without a READY book
            return "BLOCKED_DATA", snap.get("reason") or "Brak danych arkusza"
        return None

    def _artifact(self, fid, inst, rid):
        key = (fid, inst, rid)
        with self._lock:
            if key not in self._loaded:
                self._loaded[key] = self.fams[fid].load(self.store.run_dir(fid, inst, rid))
            return self._loaded[key]

    def _integrity(self, fid, inst, rid) -> tuple[bool, str | None]:
        """1.46 arch (I0216): sha256 of the manifest files was checked only at activation - after a restart the pickle / joblib /
        statsmodels payload was loaded unchecked, and the .venv_deep worker reads model.pt / the PPO pickles on EVERY call. Verified
        before every computation; the hash is recomputed only when a file's (mtime_ns, size) changed (not on every bar)."""
        d = self.store.run_dir(fid, inst, rid)
        man = B._read(d / "manifest.json", {}) or {}
        sig = []
        for name in ["manifest.json"] + sorted(man.get("files") or {}):
            try:
                s = (d / name).stat()
                sig.append((name, s.st_mtime_ns, s.st_size))
            except OSError:
                sig.append((name, None, None))
        sig, key = tuple(sig), (fid, inst, rid)
        with self._lock:
            hit = self._verified.get(key)
        if hit is not None and hit[0] == sig:
            return hit[1]
        res = self.store.verify(fid, inst, rid)
        with self._lock:
            self._verified[key] = (sig, res)
        return res

    @staticmethod
    def _explicit_off(st: dict) -> bool:
        """1.46 arch (I0417 / I0856): OFF chosen by the user (the last USE entry of the history), not the default of a missing state."""
        if st.get("use") != "OFF":
            return False
        last = next((h for h in reversed(st.get("history") or []) if isinstance(h, dict) and h.get("action") == "USE"), None)
        return bool(last) and last.get("use") == "OFF"

    def _hit(self, ck, bar_t):
        c = self._cache.get(ck)
        if c is not None and (bar_t is not None or self.clock() - c["at"] < 5):
            return c["pred"]
        return None

    def last_prediction(self, fid: str, inst: str) -> dict | None:
        """The newest cached record of a family+instrument (no computation) - for the catalog view."""
        with self._lock:
            return next((v["pred"] for k, v in self._cache.items() if k[:2] == (fid, inst)), None)

    INFLIGHT_WAIT_S = 130.0                              # > the 120 s timeout of a .venv_deep call

    def predict(self, fid: str, inst: str, *, background: bool = False) -> dict | None:
        f = self.fams[fid]
        if fid in I.TRAINHUB_FAMILY_ALIASES:
            return None                                          # aliases of trainhub TH_*: the trainhub inference publishes them (one vote)
        if fid == I.EVENT_GRU_FAMILY:
            # 1.35: the Event GRU had no live path (MM only listed its artifact). The Quant scheduler owns its inference; here only the
            # cached READY result is read (no computation in the decision path); nothing READY -> no record, as before.
            prov = getattr(self, "event_gru_provider", None)
            p = prov(inst) if prov is not None else None
            return p if p and p.get("state") == "READY" else None
        st = self.store.state(fid, inst)
        rid, use = st.get("active"), st.get("use", "OFF")
        cfg = self.cfg_store.get()
        symbol = getattr(getattr(cfg, "mt5", None), "symbol", None)
        if fid == "MICROSTRUCTURE" and rid is None and not self._explicit_off(st):
            use = "SHADOW"                                       # measurements need no artifact (unless the user switched them OFF)
        if use == "OFF":
            return None
        if fid in NO_LIVE_PATH:
            # 1.46: _live() never provides pair_bars / basket_bars - an active pair / basket artifact was always BLOCKED_DATA "brak danych
            # jednej z nóg", as if the data were only late
            return f.pred(inst=inst, symbol=symbol, state="DISABLED", reason=NO_LIVE_PATH[fid], run_id=rid, extra={"use": use})
        active = getattr(getattr(cfg, "assets", None), "active", None)
        if active and inst != active and (fid == "MICROSTRUCTURE" or (f.TF and f.TF != "EVENT")):
            # 1.46: bridge.bars() and indicators.current() belong to the ACTIVE instrument - the artifact of another instrument was computed
            # on them and published under its name (as adapters.forecast_predictions does for gold_candles)
            return f.pred(inst=inst, symbol=None, state="DISABLED", reason=f"prognozy liczone dla aktywnego instrumentu ({active})", run_id=rid,
                          extra={"use": use})
        live = self._live(f, inst)
        bar_t = (live.get("bars") or [{}])[-1].get("t") if live.get("bars") else None
        data_t = bar_t
        ttl, extra_t = None, {}
        if fid == "MICROSTRUCTURE":
            data_t, ttl, book_t = self._micro_times(live)
            extra_t = {"book_data_time": book_t}
        elif fid == "NLP_SENTIMENT":
            data_t = max((n.get("first_seen_at") or n.get("published_at") or "" for n in live.get("news") or []), default=None) or None
        ck = (fid, inst, rid, bar_t, use)
        # 1.46 arch (I0450): single-flight per cache key - the cache was checked under the lock but computed without it and without an
        # 'in progress' mark, so the SH cycle, the engine (coordinator), Quant and the API started one .venv_deep worker each for the same
        # bar. A second caller waits for the first computation and gets ITS record (the same model, bar and inputs - the same result);
        # when the first one stored nothing (a background result that is not READY, I0790) the waiter computes itself, exactly as before.
        with self._lock:
            hit = self._hit(ck, bar_t)
            if hit is not None:
                return hit
            if background:                               # I0790: one background attempt per bar (no retry loop of worker processes)
                if bar_t is None or self._bg_done.get(ck[:2]) == ck:
                    return None
                self._bg_done[ck[:2]] = ck
            ev = self._inflight.get(ck)
            owner = ev is None
            if owner:
                ev = self._inflight[ck] = threading.Event()
        if not owner:
            ev.wait(self.INFLIGHT_WAIT_S)
            with self._lock:
                hit = self._hit(ck, bar_t)
            if hit is not None:
                return hit
            return self._compute(f, fid, inst, rid, use, symbol, live, bar_t, data_t, ttl, extra_t, ck, background=False)
        try:
            return self._compute(f, fid, inst, rid, use, symbol, live, bar_t, data_t, ttl, extra_t, ck, background=background)
        finally:
            with self._lock:
                if self._inflight.get(ck) is ev:
                    self._inflight.pop(ck, None)
            ev.set()

    def _compute(self, f, fid, inst, rid, use, symbol, live, bar_t, data_t, ttl, extra_t, ck, *, background: bool) -> dict:
        man = B._read(self.store.run_dir(fid, inst, rid) / "manifest.json", {}) if rid else {}
        # 1.46 D18: the marketdata Store / live bridge write REAL_USER_DATA / SYNTHETIC_TEST / MT5_LIVE_BRIDGE - only the literal 'REAL' /
        # 'SYNTHETIC' were kept, so every record had data_kind None and Quant let a family fitted on synthetic data into a REAL snapshot
        kind = B.kind_class(man.get("data_kind"))
        if kind == "SYNTHETIC" and use == "ASSIST" and man.get("data_kind") != "SYNTHETIC":
            # S0(b) guard: a role ASSIST saved before the gate (status.assist_gate_violation) on a SYNTHETIC_TEST artifact keeps the 1.45
            # value (None) - in a REAL snapshot it stays eligible, so the coordinator with Quant in ASSIST (pub['eligible']) keeps its
            # MODEL_ASSIST_HOLD on the ACTIVE path. The literal 'SYNTHETIC' stays excluded as in 1.45 (REQUIRED never turns MISSING -> PASS).
            kind = None
        impl, why = f.implementation()
        t0 = time.perf_counter()
        integrity = {}
        try:
            if impl != "AVAILABLE":
                # 1.46 arch (I0452): a missing dependency / environment is DISABLED (as modelhub/catalog shows it), a broken one ERROR -
                # 'BLOCKED_DATA' said the data were missing. Both are not READY: REQUIRED blocks and Quant excludes exactly as before.
                raise B.Unavailable("ERROR" if impl == "ERROR" else "DISABLED", why or impl)
            if fid == "MICROSTRUCTURE":
                guard = self._micro_snapshot_guard(live)
                if guard:
                    raise B.Unavailable(*guard)
            if rid:
                ok, bad = self._integrity(fid, inst, rid)
                if not ok and use == "ASSIST":
                    # S0 guard (fail-open): an INCOMPATIBLE record would lift the holds of the role ASSIST (SH READY -> WAIT, ACTIVE
                    # MODEL_ASSIST_HOLD) - the record is computed exactly as in 1.45 and only reports the violation; set SHADOW / OFF or
                    # re-activate an intact artifact.
                    integrity = {"integrity_violation": f"{bad} – plik artefaktu zmieniony po aktywacji (rola ASSIST: wynik liczony jak dotąd)"}
                elif not ok:
                    raise B.Unavailable("INCOMPATIBLE", f"integralność artefaktu: {bad} – plik zmieniony po aktywacji; nie jest wczytywany")
            art = self._artifact(fid, inst, rid) if rid else None
            res = f.predict(art, live)
            calib = {"method": "temperature (walidacja)", "status": "CALIBRATED_DEV"} if f.TASK_TYPE == "CLASS_PROBABILITIES" else None
            pred = f.pred(inst=inst, symbol=symbol, state="READY", result=res, run_id=rid, data_time=data_t, data_kind=kind, calibration=calib,
                          extra={"use": use, "compute_ms": None, **extra_t, **integrity}, ttl_s=ttl)
        except B.Unavailable as u:
            state = u.state if u.state in ("BLOCKED_DATA", "ERROR", "NOT_TRAINED", "STALE", "INCOMPATIBLE", "DISABLED") else "BLOCKED_DATA"
            pred = f.pred(inst=inst, symbol=symbol, state=state, reason=u.reason, run_id=rid, data_time=bar_t, extra={"use": use, **integrity})
        except Exception as exc:  # noqa: BLE001
            pred = f.pred(inst=inst, symbol=symbol, state="ERROR", reason=f"{type(exc).__name__}: {exc}"[:200], run_id=rid,
                          extra={"use": use, **integrity})
        pred["compute_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        if background and pred["state"] != "READY":
            # 1.46 arch (I0790): only a READY background result becomes the bar's result - an error / timeout / transient state is not
            # stored, the decision path computes it itself exactly as before
            return pred
        with self._lock:
            # 1.46: one entry per family+instrument - the key holds the bar time, 1.45.0 kept every bar for weeks
            for k in [k for k in self._cache if k[:2] == ck[:2] and k != ck]:
                self._cache.pop(k, None)
            self._cache[ck] = {"pred": pred, "at": self.clock()}
        return pred

    # ------------------------------------------------------------------ background inference of the .venv_deep families
    PRECOMPUTE_PERIOD_S = 2.0
    HEALTH_REFRESH_S = 540.0                             # deep.health is cached 600 s - refreshed here before it expires

    def precompute_once(self, inst: str) -> int:
        """1.46 arch (I0790): the .venv_deep families (SEQ_LSTM / SEQ_GRU) ran their worker process synchronously in the SH cycle (torch
        import ~2.5 s, up to the 120 s timeout) on the first evaluation after a bar close. The same predict() is computed here right after
        the close and stored under the SAME cache key (family, instrument, run, bar, use) - the SH cycle then reads it; when it is not
        there yet the SH cycle waits for it (single-flight) or computes synchronously exactly as before (same model, bar, result - never
        fail-open). A background error / timeout is not stored as the bar's result. Returns the number of families computed."""
        if not self._cfg().enabled:
            return 0
        n, active = 0, False
        for fid, f in self.fams.items():
            if f.RUNTIME != "DEEP" or fid in NO_LIVE_PATH or fid in DELEGATED:
                continue
            st = self.store.state(fid, inst)
            if not st.get("active") or st.get("use", "OFF") == "OFF":
                continue
            active = True
            try:
                n += self.predict(fid, inst, background=True) is not None
            except Exception:                    # the SH path computes as before
                log.debug("families precompute %s failed", fid, exc_info=True)
        if active:                               # the health check of .venv_deep (implementation()) refreshed before its cache expires
            try:
                from . import deep as D
                age = D.health_age()
                if age is not None and age >= self.HEALTH_REFRESH_S and D.python() is not None:
                    D.health(force=True)
            except Exception:
                log.debug("families precompute: deep health refresh failed", exc_info=True)
        return n

    def _bg_loop(self) -> None:
        while not self._bg_stop.wait(self.PRECOMPUTE_PERIOD_S):
            try:
                inst = getattr(getattr(self.cfg_store.get(), "assets", None), "active", None)
                if inst and self.bridge is not None:
                    self.precompute_once(inst)
            except Exception:                    # the background never stops the bot; the SH path computes as before
                log.debug("families precompute loop failed", exc_info=True)

    def start(self) -> None:
        if self._bg is not None and self._bg.is_alive():
            return
        self._bg_stop.clear()
        self._bg = threading.Thread(target=self._bg_loop, name="families-precompute", daemon=True)
        self._bg.start()

    def stop(self) -> None:
        self._bg_stop.set()

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
    # 1.46: os.kill(pid, 0) on Windows is TerminateProcess(pid, 0) - "is it alive?" killed the training process
    from ...training.core import _pid_alive
    try:
        return bool(pid) and _pid_alive(int(pid))
    except (TypeError, ValueError):
        return False


def _kill_tree(pid: int, proc: subprocess.Popen | None = None) -> None:
    """Ends the process and its children (the .venv_deep worker): taskkill /T on Windows, the process group elsewhere."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=20,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            import signal
            pgid = os.getpgid(pid)
            if pgid == pid:                                      # started by submit() in its own session
                os.killpg(pgid, signal.SIGTERM)
            elif proc is not None:
                proc.terminate()
            else:
                os.kill(pid, signal.SIGTERM)
    except (OSError, subprocess.SubprocessError):
        pass


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
