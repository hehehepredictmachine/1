"""MLService - one owner of the Decision Tree / XGBoost pipeline inside the running app.

Flow:  MT5 bridge -> data validation (EngineService) -> ActiveEngine scan -> SetupTracker events
       -> collector (sample per CONFIRMED setup version, features AS-OF the decision time)
       -> labeller (incremental, closed M1 bars + recorded quotes) -> immutable snapshot
       -> trainer (separate process, lock, timeout, cancel, resume) -> registry (champion/challenger, rollback)
       -> prediction service (contract below) -> decision tree node ML / AUTO ranking (ASSIST)
       -> monitoring (data quality, drift, mature-label Brier) -> DEGRADED -> fallback to strategies without ML.

Prediction contract (MQ-ML-PRED-1.0.0), one per (setup version, model):
  setup_id, setup_version, model_id, model_family, model_version, feature_schema_version, asof_utc, raw_score,
  calibrated_probability, calibration_status, threshold, target_definition, readiness, uncertainty_reason,
  data_quality, explanation_ref
No model -> readiness NOT_READY and probability None (never a fake 50%).
"""
from __future__ import annotations

import collections
import json
import logging
import os
import subprocess
import sys
import threading
import time
from datetime import timedelta
from pathlib import Path

from .. import paths
from ..db.database import dumps
from ..timeutil import iso, parse_iso, utcnow
from . import features as fe
from .dataset import SampleStore
from .registry import Registry

log = logging.getLogger("masterquo.ml")
PRED_CONTRACT = "MQ-ML-PRED-1.0.0"
STATUSES = ("COLLECTING", "WAITING_FOR_LABELS", "TRAINING", "VALIDATING", "SHADOW", "ACTIVE", "DEGRADED", "ERROR")
BACKEND_ROOT = Path(__file__).resolve().parents[2]


class MLService:
    def __init__(self, cfg_store, db, bridge, bus, applog, root: Path | None = None, spawn=None):
        self.cfg_store = cfg_store
        self.db = db
        self.bridge = bridge
        self.bus = bus
        self.log = applog
        self.root = root or (paths.data_dir() / "ml")
        (self.root / "models").mkdir(parents=True, exist_ok=True)
        (self.root / "snapshots").mkdir(parents=True, exist_ok=True)
        (self.root / "jobs").mkdir(parents=True, exist_ok=True)
        self.store = SampleStore(db)
        self.registry = Registry(db, self.root / "models")
        self.ticks: collections.deque = collections.deque(maxlen=200_000)   # (epoch s, bid, ask) for SL/TP ordering inside one M1
        self._last_tick_key = None
        self._lock = threading.RLock()
        self._job_lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._job: dict | None = None
        self._stop = threading.Event()
        self._spawn = spawn or self._spawn_process
        self._pred_cache: dict[tuple, dict] = {}
        self.drift: dict = {"status": "NOT_EVALUATED"}
        self.last_label_run: str | None = None
        self.last_check: str | None = None
        self.readiness: dict = {"ready": False, "reasons": ["NOT_CHECKED_YET"]}
        self.last_error: str | None = None
        self._threads: list[threading.Thread] = []
        self.guard = None                      # LicenseGuard (set by runtime); None = no labelling/training
        self._recover_jobs()

    @property
    def cfg(self):
        return self.cfg_store.get().ml

    @property
    def synthetic(self) -> bool:
        return bool(self.bridge.synthetic)

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        for name, fn in (("ml-ticks", self._tick_loop), ("ml-labeler", self._label_loop), ("ml-scheduler", self._sched_loop)):
            t = threading.Thread(target=fn, name=name, daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            proc = self._proc
        if proc and proc.poll() is None:
            proc.terminate()                    # the job stays INTERRUPTED and resumes from its immutable snapshot after restart
            self._finish_job("INTERRUPTED", {"reason": "APP_STOP"})

    def _recover_jobs(self) -> None:
        for j in self.db.query("SELECT * FROM ml_jobs WHERE status IN ('RUNNING','QUEUED')"):
            self.db.execute("UPDATE ml_jobs SET status='INTERRUPTED', finished_at=? WHERE job_id=?", (iso(utcnow()), j["job_id"]))
            self.registry.event("JOB_INTERRUPTED", None, {"job_id": j["job_id"], "reason": "APP_RESTART"})

    # ------------------------------------------------------------ collector
    def on_setup_events(self, events: list, view, now) -> int:
        """Called by ActiveEngine after every scan. Every CONFIRMED setup version becomes a sample - also setups that are
        not selected, blocked by risk/mode or never executed (no 'executed only' selection bias)."""
        if not self.cfg.collect or view is None:
            return 0
        n = 0
        for kind, r in events:
            if kind not in ("NEW_CONFIRMED", "STAGE_CONFIRMED") or not r or not r.get("record"):
                continue
            try:
                rec = dict(r["record"], symbol=r.get("symbol"))
                if self.store.create(rec=rec, setup_id=r["setup_id"], version=int(r["version"]), view=view, asof=now, source="LIVE",
                                     quality="HIGH", feed_id=self._feed_id(), cost=self._cost(), synthetic=self.synthetic):
                    n += 1
            except Exception as exc:                           # a broken sample never stops the bot
                log.exception("ml collector")
                self.last_error = f"COLLECTOR:{type(exc).__name__}:{exc}"[:200]
        return n

    def _feed_id(self) -> str:
        a = self.bridge.account_status() or {}
        return f"{'SYNTHETIC' if self.synthetic else 'MT5'}:{a.get('server') or 'unknown'}:{self.cfg_store.get().mt5.symbol}"

    def _cost(self) -> dict:
        cfg = self.cfg_store.get()
        info = self.bridge.symbol_info or {}
        q = self.bridge.quote_status() or {}
        point = info.get("point") or 0.01
        flags = []
        spread = q.get("spread")
        if spread is None:
            spread = (info.get("spread") or 0) * point
            flags.append("SPREAD_FROM_SYMBOL_INFO")
        slip = (cfg.costs.slippage_stress_points or 0) * point
        cps = cfg.costs.commission_per_lot_per_side
        size = info.get("trade_contract_size") or 100.0
        if cps is None:
            flags.append("COMMISSION_UNKNOWN_ASSUMED_0")
        return {"spread": float(spread), "slippage": float(slip), "commission": float(cps or 0.0) / float(size), "flags": flags}

    # ------------------------------------------------------------ quotes (for ambiguous bars)
    def _tick_loop(self) -> None:
        while not self._stop.is_set():
            try:
                q = self.bridge.quote_status()
                if q and q.get("bid") is not None:
                    key = (q.get("time_msc"), q.get("bid"), q.get("ask"))
                    if key != self._last_tick_key:
                        self._last_tick_key = key
                        ts = (q.get("time_msc") / 1000 - (self.bridge.clock.offset or 0)) if q.get("time_msc") else time.time()
                        self.ticks.append((float(ts), float(q["bid"]), float(q["ask"])))
            except Exception:
                pass
            self._stop.wait(0.5)

    # ------------------------------------------------------------ labeller
    def _label_loop(self) -> None:
        while not self._stop.wait(30):
            try:
                self.label_once()
            except Exception as exc:
                log.exception("ml labeller")
                self.last_error = f"LABELER:{type(exc).__name__}:{exc}"[:200]

    def _licensed(self, scope: str) -> bool:
        return self.guard is not None and self.guard.allows(scope)

    def label_once(self, bars: list[dict] | None = None, now=None) -> dict:
        if not self._licensed("analysis"):
            return {}
        now = now or utcnow()
        if bars is None:
            bars = [b for b in self.bridge.bars("M1", include_forming=False) if b.get("open_utc")]
        done = collections.Counter()
        if not bars:
            return dict(done)
        oldest = parse_iso(bars[0]["open_utc"])
        ticks = list(self.ticks)
        for s in self.store.pending():
            ej = json.loads(s["entry_json"])
            need_from = parse_iso(ej["state"]["last_bar"]) + timedelta(minutes=1) if ej["state"]["last_bar"] else parse_iso(s["asof_utc"])
            if oldest > need_from + timedelta(minutes=1):
                # bars needed for this label are no longer in the terminal buffer (long downtime) -> explicit status, no guess
                self.db.execute("UPDATE ml_samples SET status='MISSING_DATA', exit_reason='M1_HISTORY_NOT_IN_BUFFER', updated_at=? WHERE sample_id=? AND status='PENDING'",
                                (iso(now), s["sample_id"]))
                done["MISSING_DATA"] += 1
                continue
            st = self.store.advance(s["sample_id"], s["entry_json"], bars, ticks, now)
            done[st] += 1
        self.store.attach_realized()
        self.last_label_run = iso(now)
        return dict(done)

    # ------------------------------------------------------------ scheduler
    def _sched_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.check_once()
            except Exception as exc:
                log.exception("ml scheduler")
                self.last_error = f"SCHEDULER:{type(exc).__name__}:{exc}"[:200]
            self._stop.wait(self.cfg.check_interval_seconds)

    def check_once(self) -> dict:
        self.last_check = iso(utcnow())
        if self._job is not None and not self._licensed("ml_train"):
            self.license_lost("LICENSE_NOT_VALID")
        self._poll_job()
        self.readiness = self._readiness()
        if self.readiness["ready"] and not self.cfg.training_paused and self._job is None and self._licensed("ml_train"):
            self.start_training("SCHEDULER")
        self._monitor()
        self.bus.publish("ml", self.status(compact=True))
        return self.readiness

    def _readiness(self) -> dict:
        c = self.cfg
        cnt = self.store.counts(c.use_backfill_approx, self.synthetic)
        reasons = []
        last = self.db.one("SELECT * FROM ml_jobs WHERE kind='TRAIN' AND status='DONE' ORDER BY finished_at DESC LIMIT 1")
        if cnt["unique_setups"] < c.min_labeled_setups:
            reasons.append(f"ETYKIETY_{cnt['unique_setups']}/{c.min_labeled_setups}_UNIKALNYCH_SETUPOW")
        if cnt["pos"] < c.min_per_class:
            reasons.append(f"KLASA_1_{cnt['pos']}/{c.min_per_class}")
        if cnt["neg"] < c.min_per_class:
            reasons.append(f"KLASA_0_{cnt['neg']}/{c.min_per_class}")
        if last:
            d = json.loads(last["detail_json"] or "{}")
            new = cnt["labeled"] - int(d.get("labeled_at_start") or 0)
            if new < c.retrain_after_new_labels:
                reasons.append(f"NOWE_ETYKIETY_{new}/{c.retrain_after_new_labels}")
            hours = (utcnow() - parse_iso(last["finished_at"])).total_seconds() / 3600
            if hours < c.min_hours_between_trainings:
                reasons.append(f"OD_OSTATNIEGO_TRENINGU_{hours:.1f}/{c.min_hours_between_trainings}H")
        last_any = self.db.one("SELECT * FROM ml_jobs WHERE kind='TRAIN' ORDER BY created_at DESC LIMIT 1")
        if last_any and last_any["status"] == "NOT_READY":
            d = json.loads(last_any["detail_json"] or "{}")
            if cnt["labeled"] - int(d.get("labeled_at_start") or 0) < max(25, c.retrain_after_new_labels // 5):
                reasons += ["BLOKI_WALIDACJI:" + r for r in (d.get("reasons") or [])][:6]
        return {"ready": not reasons, "reasons": reasons, "counts": cnt, "checked_at": iso(utcnow()),
                "note": "Gotowość do nauki oznacza tylko spełnione progi danych - nie wytrenowany model."}

    # ------------------------------------------------------------ training jobs
    def license_lost(self, reason: str) -> None:
        """Running training stops at a controlled point: the trainer process only writes files, so stopping it cannot
        corrupt the database; the job is INTERRUPTED (resumable on the same immutable snapshot) and its results are
        NOT registered or promoted."""
        with self._lock:
            proc = self._proc
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass
            self._finish_job("INTERRUPTED", {"reason": "LICENSE_" + reason})

    def start_training(self, initiated_by: str, *, force: bool = False) -> dict:
        if not self._licensed("ml_train"):
            return {"started": False, "reason": "LICENSE_REQUIRED"}
        if not self._job_lock.acquire(blocking=False):
            return {"started": False, "reason": "JOB_LOCKED"}
        try:
            if self._job is not None:
                return {"started": False, "reason": "JOB_ALREADY_RUNNING", "job_id": self._job["job_id"]}
            c = self.cfg
            if not force and not self.readiness.get("ready"):
                return {"started": False, "reason": "NOT_READY", "reasons": self.readiness.get("reasons")}
            cnt = self.store.counts(c.use_backfill_approx, self.synthetic)
            if cnt["labeled"] < 4 * c.min_block_samples:
                return {"started": False, "reason": f"ZA_MALO_ETYKIET_{cnt['labeled']}_POTRZEBA_CO_NAJMNIEJ_{4 * c.min_block_samples}"}
            snap = self.store.snapshot(self.root / "snapshots", include_approx=c.use_backfill_approx, synthetic=self.synthetic)
            job_id = "JOB-" + utcnow().strftime("%Y%m%dT%H%M%S") + "-" + __import__("uuid").uuid4().hex[:4]
            jcfg = {k: getattr(c, k) for k in ("embargo_minutes", "min_block_samples", "min_block_per_class", "dt_tuning_budget", "xgb_tuning_budget",
                                               "xgb_max_trees", "xgb_threads", "xgb_device", "random_state")}
            jcfg["promotion"] = c.promotion.model_dump()
            job = {"job_id": job_id, "snapshot": snap["path"], "snapshot_id": snap["snapshot_id"], "cfg": jcfg, "out_dir": str(self.root / "models"),
                   "prior_test_end": self.registry.last_test_end(), "labeled_at_start": cnt["labeled"], "initiated_by": initiated_by,
                   "manifest": snap}
            job_file = self.root / "jobs" / f"{job_id}.json"
            job_file.write_text(json.dumps(job, default=str), encoding="utf-8")
            self.db.execute("INSERT INTO ml_jobs(job_id, kind, status, created_at, started_at, snapshot_id, detail_json) VALUES (?,?,?,?,?,?,?)",
                            (job_id, "TRAIN", "RUNNING", iso(utcnow()), iso(utcnow()), snap["snapshot_id"],
                             dumps({"labeled_at_start": cnt["labeled"], "initiated_by": initiated_by, "rows": snap["rows"], "phase": "STARTING"})))
            proc = self._spawn(job_file)
            with self._lock:
                self._proc, self._job = proc, dict(job, file=str(job_file), started=time.monotonic())
            self.log.info("ML", "TRAIN_START", f"Trening DT + XGBoost na snapshocie {snap['snapshot_id']} ({snap['rows']} próbek)", {"job_id": job_id})
            return {"started": True, "job_id": job_id, "snapshot_id": snap["snapshot_id"], "rows": snap["rows"]}
        finally:
            self._job_lock.release()

    def _spawn_process(self, job_file: Path):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(BACKEND_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        env["OMP_NUM_THREADS"] = str(self.cfg.xgb_threads)
        kw = {}
        if os.name == "nt":
            kw["creationflags"] = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        else:
            kw["preexec_fn"] = lambda: os.nice(10)
        return subprocess.Popen([sys.executable, "-m", "masterquo.ml.trainer", str(job_file)], cwd=str(BACKEND_ROOT), env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)

    def phase(self) -> str | None:
        with self._lock:
            job = self._job
        if not job:
            return None
        p = Path(job["file"]).with_suffix(".phase")
        try:
            return p.read_text(encoding="utf-8").strip() or "TRAINING"
        except OSError:
            return "TRAINING"

    def _poll_job(self) -> None:
        with self._lock:
            job, proc = self._job, self._proc
        if not job:
            return
        res_path = Path(job["file"]).with_suffix(".result.json")
        if res_path.exists():
            res = json.loads(res_path.read_text(encoding="utf-8"))
            self._handle_result(job, res)
            return
        if proc is not None and proc.poll() is not None:
            self._finish_job("FAILED", {"reason": f"TRAINER_EXIT_{proc.returncode}_WITHOUT_RESULT"})
            return
        if time.monotonic() - job["started"] > self.cfg.train_timeout_minutes * 60:
            if proc is not None:
                proc.kill()
            self._finish_job("FAILED", {"reason": "TIMEOUT"})

    def _handle_result(self, job: dict, res: dict) -> None:
        st = res.get("status")
        if st == "DONE" and not self._licensed("ml_train"):
            self._finish_job("INTERRUPTED", {"reason": "LICENSE_NOT_VALID_RESULTS_NOT_PUBLISHED"})
            return
        if st == "DONE":
            try:
                decisions = self.registry.register(res, job["snapshot_id"], job["cfg"]["promotion"])
            except Exception as exc:
                self._finish_job("FAILED", {"reason": f"REGISTER:{type(exc).__name__}:{exc}"})
                return
            self._pred_cache.clear()
            (self.root / "jobs" / f"{job['job_id']}.report.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
            self._finish_job("DONE", {"decisions": decisions, "validation": res.get("validation"), "baselines": res.get("baselines"),
                                      "elapsed_s": res.get("elapsed_s")})
            promoted = [m for m, d in decisions.items() if d["passed"]]
            self.log.info("ML", "TRAIN_DONE", f"Trening zakończony. Kandydaci: {', '.join(f'{m}:{"OK" if d["passed"] else "ODRZUCONY"}' for m, d in decisions.items())}"
                          + (f"; champion: {self.registry.champion_id}" if promoted else "; champion bez zmian"))
        elif st == "NOT_READY":
            self._finish_job("NOT_READY", {"reasons": res.get("reasons")})
        else:
            self._finish_job("FAILED", {"reason": res.get("reason"), "trace": res.get("trace")})

    def _finish_job(self, status: str, detail: dict) -> None:
        with self._lock:
            job, proc = self._job, self._proc
            self._job, self._proc = None, None
        if proc is not None:
            try:
                proc.wait(timeout=10)            # reap the trainer process (it has already written its result or was killed)
            except Exception:
                pass
        if not job:
            return
        old = json.loads((self.db.one("SELECT detail_json FROM ml_jobs WHERE job_id=?", (job["job_id"],)) or {}).get("detail_json") or "{}")
        old.update(detail)
        self.db.execute("UPDATE ml_jobs SET status=?, finished_at=?, detail_json=? WHERE job_id=?", (status, iso(utcnow()), dumps(old), job["job_id"]))
        if status in ("FAILED", "INTERRUPTED"):
            self.last_error = f"JOB_{status}:{detail.get('reason')}"
            self.log.warn("ML", "TRAIN_" + status, f"Trening {job['job_id']}: {status} ({detail.get('reason')}). Bot działa dalej bez zmiany modelu.")
        elif status == "DONE":
            self.last_error = None

    def cancel(self) -> dict:
        with self._lock:
            proc = self._proc
        if not proc:
            return {"cancelled": False, "reason": "NO_RUNNING_JOB"}
        proc.kill()
        self._finish_job("CANCELLED", {"reason": "USER_CANCEL"})
        return {"cancelled": True}

    def resume_interrupted(self) -> dict:
        """Re-run the last INTERRUPTED job on the SAME immutable snapshot."""
        j = self.db.one("SELECT * FROM ml_jobs WHERE status='INTERRUPTED' ORDER BY created_at DESC LIMIT 1")
        if not j or self._job is not None:
            return {"started": False, "reason": "NOTHING_TO_RESUME" if not j else "JOB_ALREADY_RUNNING"}
        f = self.root / "jobs" / f"{j['job_id']}.json"
        if not f.exists():
            return {"started": False, "reason": "JOB_FILE_MISSING"}
        job = json.loads(f.read_text(encoding="utf-8"))
        Path(f).with_suffix(".result.json").unlink(missing_ok=True)
        self.db.execute("UPDATE ml_jobs SET status='RUNNING', started_at=?, finished_at=NULL WHERE job_id=?", (iso(utcnow()), j["job_id"]))
        proc = self._spawn(f)
        with self._lock:
            self._proc, self._job = proc, dict(job, file=str(f), started=time.monotonic())
        return {"started": True, "job_id": j["job_id"], "resumed": True}

    # ------------------------------------------------------------ backfill from history (separate, APPROX quality)
    backfill_state: dict = {"status": "IDLE"}

    def start_backfill(self, days: int) -> dict:
        if not self._licensed("analysis"):
            return {"started": False, "reason": "LICENSE_REQUIRED"}
        if self.backfill_state.get("status") == "RUNNING":
            return {"started": False, "reason": "BACKFILL_ALREADY_RUNNING"}
        days = max(5, min(int(days), 180))
        self.backfill_state = {"status": "RUNNING", "days": days, "started_at": iso(utcnow())}

        def work():
            from . import backfill
            try:
                if self.synthetic:
                    data, feed = backfill.synthetic_data(days + 30), "SYNTHETIC"
                else:
                    per_day = {"M1": 1440, "M5": 288, "M15": 96, "H1": 24, "H4": 6, "D1": 1}
                    data = backfill.bridge_data(self.bridge, {tf: min(99000, (days + 30) * n + 50) for tf, n in per_day.items()})
                    feed = "MT5"
                res = backfill.run(self.db, data, feed=feed, synthetic=self.synthetic, cost=dict(self._cost(), point=(self.bridge.symbol_info or {}).get("point") or 0.01),
                                   warmup_days=30, progress=lambda p: self.backfill_state.update(progress=p),
                                   should_stop=lambda: self._stop.is_set() or not self._licensed("analysis"))
                self.backfill_state = {"status": "DONE", "result": res, "finished_at": iso(utcnow())}
                self.log.info("ML", "BACKFILL_DONE", f"Backfill {feed}: {res['created']} próbek (jakość APPROX, domyślnie poza treningiem)", res)
            except Exception as exc:
                self.backfill_state = {"status": "FAILED", "reason": f"{type(exc).__name__}: {exc}"[:300]}
                self.log.warn("ML", "BACKFILL_FAILED", f"Backfill nieudany: {exc}")
        threading.Thread(target=work, name="ml-backfill", daemon=True).start()
        return {"started": True, "days": days}

    # ------------------------------------------------------------ settings
    def set_mode(self, mode: str) -> dict:
        if mode not in ("OFF", "SHADOW", "ASSIST"):
            raise ValueError("BAD_ML_MODE")
        old = self.cfg.mode
        self.cfg_store.update({"ml": {"mode": mode}})
        self.db.execute("INSERT INTO settings_audit(ts, change_json) VALUES (?,?)", (iso(utcnow()), dumps({"ml_mode": [old, mode]})))
        self.registry.event("MODE", None, {"from": old, "to": mode})
        self.log.info("ML", "MODE", f"Tryb ML: {old} -> {mode}")
        self.bus.publish("ml", self.status(compact=True))
        return self.status(compact=True)

    def set_collect(self, on: bool) -> dict:
        self.cfg_store.update({"ml": {"collect": bool(on)}})
        self.log.info("ML", "COLLECT", "Zbieranie próbek: " + ("włączone" if on else "wyłączone"))
        return self.status(compact=True)

    def set_paused(self, on: bool) -> dict:
        self.cfg_store.update({"ml": {"training_paused": bool(on)}})
        if on:
            self.cancel()
        self.log.info("ML", "PAUSE", "Trening: " + ("wstrzymany" if on else "wznowiony"))
        return self.status(compact=True)

    def rollback(self) -> dict:
        r = self.registry.rollback()
        self._pred_cache.clear()
        self.log.warn("ML", "ROLLBACK", f"Przywrócono poprzedni model {r['champion']} (wraz z preprocessingiem i kalibratorem)")
        return r

    # ------------------------------------------------------------ predictions
    def predict(self, setup_row: dict | None, view, *, role: str = "CHAMPION") -> dict:
        """Contract for one setup version. Cached per (setup_id, version, model_id); features are computed AS-OF the
        setup's confirmation time when the sample exists (same values as training), else as-of now."""
        c = self.cfg
        base = {"contract": PRED_CONTRACT, "setup_id": (setup_row or {}).get("setup_id"), "setup_version": (setup_row or {}).get("version"),
                "model_id": None, "model_family": None, "model_version": None, "feature_schema_version": fe.FEATURE_SCHEMA_VERSION,
                "asof_utc": None, "raw_score": None, "calibrated_probability": None, "calibration_status": "NONE", "threshold": None,
                "target_definition": "net_R > 0 wg planu setupu (MQ-LABEL-1.0.0)", "readiness": "NOT_READY", "uncertainty_reason": None,
                "data_quality": None, "explanation_ref": None, "ml_mode": c.mode}
        if setup_row is None:
            return dict(base, uncertainty_reason="NO_SETUP")
        bundle = self.registry.champion if role == "CHAMPION" else None
        mid = self.registry.champion_id
        if bundle is None:
            return dict(base, uncertainty_reason=self.registry.load_error or "NO_CHAMPION_MODEL_YET")
        key = (setup_row["setup_id"], setup_row["version"], mid)
        if key in self._pred_cache:
            return self._pred_cache[key]
        rec = setup_row["record"]
        samp = self.db.one("SELECT features_json, asof_utc FROM ml_samples WHERE sample_id=?", (f"{setup_row['setup_id']}:{setup_row['version']}",))
        if samp and samp["features_json"] not in (None, "{}"):
            feats, asof = fe.from_json(json.loads(samp["features_json"])), samp["asof_utc"]
        else:
            if view is None:
                return dict(base, model_id=mid, uncertainty_reason="NO_MARKET_VIEW")
            now = utcnow()
            feats, asof = fe.compute(view, dict(rec, symbol=setup_row.get("symbol")), now), iso(now)
        missing = [k for k in bundle.prep.numeric if feats.get(k) is None or (isinstance(feats.get(k), float) and feats[k] != feats[k])]
        raw = float(bundle.raw([feats])[0])
        cal = bundle.calib.apply(__import__("numpy").array([raw]))
        p = None if cal is None else float(cal[0])
        dq = "OK" if len(missing) <= 0.2 * max(1, len(bundle.prep.numeric)) else "MANY_MISSING_FEATURES"
        unknown = [col for col in bundle.prep.cats if str(feats.get(col)) not in bundle.prep.cats[col]]
        reason = None
        if self.drift.get("status") == "DEGRADED":
            reason = "MODEL_DEGRADED_" + ",".join(self.drift.get("reasons") or [])[:80]
        elif unknown:
            reason = "UNSEEN_CATEGORY_" + ",".join(unknown)
        elif dq != "OK":
            reason = f"MISSING_FEATURES_{len(missing)}"
        ready = "READY" if p is not None and reason is None else ("UNCALIBRATED" if p is None else "DEGRADED")
        out = dict(base, model_id=mid, model_family=bundle.family, model_version=bundle.meta.get("trained_at"), asof_utc=asof, raw_score=round(raw, 5),
                   calibrated_probability=None if p is None else round(p, 4), calibration_status=bundle.calib.kind,
                   threshold=bundle.meta.get("threshold"), readiness=ready, uncertainty_reason=reason, data_quality=dq,
                   missing_features=missing[:12], explanation_ref=f"/api/v1/ml/explain?setup_id={setup_row['setup_id']}&version={setup_row['version']}")
        self._pred_cache[key] = out
        if len(self._pred_cache) > 2000:
            self._pred_cache.clear()
        self.db.execute("""INSERT OR IGNORE INTO ml_predictions(at, setup_id, setup_version, model_id, role, raw_score, calibrated_probability, readiness, contract_json)
                           VALUES (?,?,?,?,?,?,?,?,?)""", (iso(utcnow()), setup_row["setup_id"], setup_row["version"], mid, "CHAMPION", out["raw_score"],
                                                          out["calibrated_probability"], ready, dumps(out)))
        # challengers are scored in SHADOW only (never used by the router)
        for cid, cb in list(self.registry.challengers.items()):
            ck = (setup_row["setup_id"], setup_row["version"], cid)
            if ck in self._pred_cache:
                continue
            try:
                craw = float(cb.raw([feats])[0])
                ccal = cb.calib.apply(__import__("numpy").array([craw]))
                cp = None if ccal is None else round(float(ccal[0]), 4)
                self._pred_cache[ck] = {"model_id": cid, "calibrated_probability": cp}
                self.db.execute("""INSERT OR IGNORE INTO ml_predictions(at, setup_id, setup_version, model_id, role, raw_score, calibrated_probability, readiness, contract_json)
                                   VALUES (?,?,?,?,?,?,?,?,?)""", (iso(utcnow()), setup_row["setup_id"], setup_row["version"], cid, "CHALLENGER_SHADOW",
                                                                  round(craw, 5), cp, "SHADOW", dumps({"model_id": cid, "raw": craw, "p": cp})))
            except Exception:
                pass
        return out

    def gate(self, setup_row: dict | None, view) -> dict:
        """Decision-tree node ML. OFF/SHADOW never block. ASSIST blocks only with a READY, calibrated champion whose
        probability is below the threshold chosen on the calibration block. No/degraded model -> strategies without ML."""
        mode = self.cfg.mode
        if mode == "OFF" or setup_row is None:
            return {"status": "PASS", "mode": mode, "codes": ["ML_OFF" if mode == "OFF" else "ML_NO_SETUP"], "prediction": None}
        pred = self.predict(setup_row, view)
        if mode == "SHADOW":
            return {"status": "PASS", "mode": mode, "codes": ["ML_SHADOW_NOT_GATING"], "prediction": pred}
        if pred["readiness"] != "READY":
            self._fallback_event(pred)
            return {"status": "PASS", "mode": mode, "codes": ["ML_FALLBACK_STRATEGIES_ONLY_" + str(pred.get("uncertainty_reason") or pred["readiness"])[:60]],
                    "prediction": pred}
        thr = pred.get("threshold") or 0.5
        if pred["calibrated_probability"] < thr:
            return {"status": "FAIL", "mode": mode, "codes": ["ML_BELOW_THRESHOLD", f"P_{pred['calibrated_probability']}<{thr}"], "prediction": pred}
        return {"status": "PASS", "mode": mode, "codes": [f"ML_P_{pred['calibrated_probability']}>={thr}"], "prediction": pred}

    _last_fallback = 0.0

    def _fallback_event(self, pred: dict) -> None:
        if time.monotonic() - self._last_fallback > 600:
            self._last_fallback = time.monotonic()
            self.registry.event("FALLBACK", pred.get("model_id"), {"reason": pred.get("uncertainty_reason") or pred.get("readiness")})

    def rank_adjust(self, setup_row: dict, view) -> float:
        """ASSIST only: additive rank bonus for the AUTO selector, scaled by (calibrated p - base rate); 0 otherwise.
        No double counting: the setup score is unchanged, the model only re-orders candidates."""
        if self.cfg.mode != "ASSIST" or self.registry.champion is None:
            return 0.0
        pred = self.predict(setup_row, view)
        if pred["readiness"] != "READY":
            return 0.0
        base = float(self.registry.champion.meta.get("base_rate") or 0.5)
        return round(self.cfg.assist_rank_weight * (pred["calibrated_probability"] - base) * 10, 2)

    def explain(self, setup_id: str, version: int) -> dict:
        from .models import explain_dt, explain_xgb
        b = self.registry.champion
        if b is None:
            return {"available": False, "reason": "NO_CHAMPION_MODEL_YET"}
        s = self.db.one("SELECT features_json FROM ml_samples WHERE sample_id=?", (f"{setup_id}:{version}",))
        if not s or s["features_json"] in (None, "{}"):
            return {"available": False, "reason": "NO_FEATURE_SNAPSHOT_FOR_SETUP_VERSION"}
        row = fe.from_json(json.loads(s["features_json"]))
        out = {"available": True, "model_id": self.registry.champion_id, "family": b.family}
        out["explanation"] = explain_dt(b, row) if b.family == "DECISION_TREE" else explain_xgb(b, row)
        # the other family (challenger) for comparison, if loaded
        for cid, cb in self.registry.challengers.items():
            if cb.family != b.family:
                out["challenger"] = {"model_id": cid, "family": cb.family,
                                     "explanation": explain_dt(cb, row) if cb.family == "DECISION_TREE" else explain_xgb(cb, row)}
                break
        return out

    # ------------------------------------------------------------ monitoring
    def _monitor(self) -> None:
        b = self.registry.champion
        if b is None:
            self.drift = {"status": "NOT_EVALUATED", "reason": "NO_CHAMPION"}
            return
        rows = self.db.query("SELECT features_json FROM ml_samples WHERE created_at >= ? AND features_json != '{}' ORDER BY created_at DESC LIMIT 300",
                             ((self.db.one("SELECT promoted_at FROM ml_models WHERE model_id=?", (self.registry.champion_id,)) or {}).get("promoted_at") or "",))
        psi = b.prep.psi([fe.from_json(json.loads(r["features_json"])) for r in rows])
        top = sorted(psi.items(), key=lambda x: -x[1])[:8]
        reasons = []
        mx = top[0][1] if top else 0.0
        if mx >= self.cfg.drift_psi_degraded:
            reasons.append(f"PSI_{top[0][0]}_{mx:.2f}")
        # mature labels of predictions made by this champion
        m = self.db.query("""SELECT p.calibrated_probability AS p, s.label AS y FROM ml_predictions p JOIN ml_samples s
                             ON s.setup_id = p.setup_id AND s.setup_version = p.setup_version WHERE p.model_id=? AND s.status='LABELED'
                             AND p.calibrated_probability IS NOT NULL""", (self.registry.champion_id,))
        live_brier = None
        test_brier = None
        mrow = self.db.one("SELECT metrics_json FROM ml_models WHERE model_id=?", (self.registry.champion_id,))
        if mrow:
            test_brier = json.loads(mrow["metrics_json"]).get("test", {}).get("brier")
        if len(m) >= 30:
            live_brier = round(sum((r["p"] - r["y"]) ** 2 for r in m) / len(m), 4)
            if test_brier is not None and live_brier > test_brier + self.cfg.degrade_brier_increase:
                reasons.append(f"BRIER_LIVE_{live_brier}_VS_TEST_{test_brier}")
        status = "DEGRADED" if reasons else ("WARN" if mx >= self.cfg.drift_psi_warn else "OK")
        if status == "DEGRADED" and self.drift.get("status") != "DEGRADED":
            self.registry.event("DEGRADED", self.registry.champion_id, {"reasons": reasons})
            self.log.warn("ML", "DEGRADED", "Model zdegradowany (" + ", ".join(reasons) + "). Router wraca do strategii bez ML; zalecany retrening.")
            self._pred_cache.clear()
        self.drift = {"status": status, "reasons": reasons, "psi_top": [{"feature": k, "psi": round(v, 3)} for k, v in top], "samples": len(rows),
                      "mature_predictions": len(m), "live_brier": live_brier, "test_brier": test_brier, "checked_at": iso(utcnow())}

    # ------------------------------------------------------------ status for UI / API
    def status(self, compact: bool = False) -> dict:
        c = self.cfg
        cnt = self.readiness.get("counts") or self.store.counts(c.use_backfill_approx, self.synthetic)
        phase = self.phase()
        champ = self.registry.champion
        if self.registry.load_error or (self.last_error and self.last_error.startswith("JOB_FAILED")):
            st = "ERROR"
        elif phase in ("TRAINING", "STARTING"):
            st = "TRAINING"
        elif phase == "VALIDATING":
            st = "VALIDATING"
        elif champ is not None and self.drift.get("status") == "DEGRADED":
            st = "DEGRADED"
        elif champ is not None:
            st = "ACTIVE" if c.mode == "ASSIST" else "SHADOW"
        elif cnt.get("samples", 0) >= c.min_labeled_setups or (cnt.get("by_status", {}).get("PENDING", 0) and cnt.get("labeled", 0) >= c.min_labeled_setups // 2):
            st = "WAITING_FOR_LABELS"
        else:
            st = "COLLECTING"
        last_q = self.bridge.quote_status() or {}
        out = {"status": st, "mode": c.mode, "collect": c.collect, "training_paused": c.training_paused, "counts": cnt,
               "required": {"min_labeled_setups": c.min_labeled_setups, "min_per_class": c.min_per_class, "retrain_after_new_labels": c.retrain_after_new_labels,
                            "min_hours_between_trainings": c.min_hours_between_trainings},
               "progress": round(min(1.0, cnt.get("unique_setups", 0) / max(1, c.min_labeled_setups)), 3),
               "readiness": self.readiness, "phase": phase, "job": {k: self._job[k] for k in ("job_id", "snapshot_id")} if self._job else None,
               "champion": self.registry.champion_id, "champion_family": champ.family if champ else None,
               "challengers": list(self.registry.challengers), "drift": self.drift, "last_error": self.last_error,
               "last_label_run": self.last_label_run, "last_check": self.last_check, "synthetic": self.synthetic,
               "last_tick_age_s": last_q.get("age_seconds"), "ticks_buffered": len(self.ticks), "backfill": self.backfill_state,
               "note": "Model ocenia setupy strategii; nie generuje własnych sygnałów. Komentarz Claude nie jest etykietą."}
        if not compact:
            out["models"] = self.registry.models()
            out["events"] = self.registry.events()
            out["jobs"] = self.db.query("SELECT job_id, status, created_at, finished_at, snapshot_id, detail_json FROM ml_jobs ORDER BY created_at DESC LIMIT 10")
            out["report"] = self.last_report()
        return out

    def last_report(self) -> dict | None:
        j = self.db.one("SELECT job_id FROM ml_jobs WHERE status='DONE' ORDER BY finished_at DESC LIMIT 1")
        if not j:
            return None
        p = self.root / "jobs" / f"{j['job_id']}.report.json"
        if not p.exists():
            return None
        r = json.loads(p.read_text(encoding="utf-8"))
        return {"job_id": j["job_id"], "validation": r.get("validation"), "baselines": r.get("baselines"), "base_rate": r.get("base_rate"),
                "promotion_rules": r.get("promotion_rules"), "versions": r.get("versions"),
                "models": {f: {k: m.get(k) for k in ("model_id", "threshold", "calibration", "test", "raw_test_brier", "policy", "policy_bootstrap",
                                                    "by_strategy", "by_direction", "by_session", "by_regime", "train")} for f, m in (r.get("models") or {}).items()}}
