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
# 1.46: families whose predict() needs the bars of every leg - _live() has no such path (only training reads the legs from the archive)
NO_LIVE_PATH = {"PAIR_COINT": "brak ścieżki danych na żywo dla nóg pary (pair_bars) – relacja jest liczona tylko w treningu",
                "STATARB": "brak ścieżki danych na żywo dla nóg koszyka (basket_bars) – reszty są liczone tylko w treningu"}


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
        use = st.get("use", "OFF") if active else "OFF"
        # 1.46 D5: a role ASSIST saved before the gate covered activate / rollback may sit on an artifact that would not get it today -
        # shown (reason), never lowered here
        gate = self.store.assist_ok(fid, inst, st.get("active"))[1] if use == "ASSIST" else None
        return {"implementation": impl, "implementation_reason": why, "artifact": art, "use": use,
                "active_run": st.get("active"), "runs": len(runs), "last_run": runs[-1]["run_id"] if runs else None,
                "last_validation": (runs[-1].get("validation") or {}).get("status") if runs else None, "job": job,
                "assist_gate_violation": gate}

    def catalog(self, inst: str) -> list[dict]:
        out = []
        for fid, f in self.fams.items():
            try:
                st = self.status(fid, inst)
            except Exception as exc:  # noqa: BLE001
                st = {"implementation": "ERROR", "implementation_reason": str(exc)[:200], "artifact": "NOT_TRAINED", "use": "OFF"}
            out.append({**f.capabilities(), "status": st, "data_requirements": f.data_requirements()})
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
        self._known(fid)
        st = self.store.rollback(fid, inst)
        self.invalidate(fid, inst)
        return {"ok": True, "state": st}

    def set_use(self, fid, inst, use) -> dict:
        self._known(fid)
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
        cfg = self.cfg_store.get()
        symbol = getattr(getattr(cfg, "mt5", None), "symbol", None)
        if fid == "MICROSTRUCTURE" and rid is None:
            use = "SHADOW"                                       # measurements need no artifact
        if use == "OFF" and fid != "MICROSTRUCTURE":
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
        if fid == "MICROSTRUCTURE":
            data_t = (live.get("micro") or {}).get("data_time")
        elif fid == "NLP_SENTIMENT":
            data_t = max((n.get("first_seen_at") or n.get("published_at") or "" for n in live.get("news") or []), default=None) or None
        ck = (fid, inst, rid, bar_t, use)
        with self._lock:
            if ck in self._cache and (bar_t is not None or self.clock() - self._cache[ck]["at"] < 5):
                return self._cache[ck]["pred"]
        man = B._read(self.store.run_dir(fid, inst, rid) / "manifest.json", {}) if rid else {}
        # 1.46 D18: the marketdata Store / live bridge write REAL_USER_DATA / SYNTHETIC_TEST / MT5_LIVE_BRIDGE - only the literal 'REAL' /
        # 'SYNTHETIC' were kept, so every record had data_kind None and Quant let a family fitted on synthetic data into a REAL snapshot
        kind = B.kind_class(man.get("data_kind"))
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
            # 1.46: one entry per family+instrument - the key holds the bar time, 1.45.0 kept every bar for weeks
            for k in [k for k in self._cache if k[:2] == ck[:2] and k != ck]:
                self._cache.pop(k, None)
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
