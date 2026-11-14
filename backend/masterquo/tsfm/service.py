"""Chronos-2 and Granite TTM forecasts in the bot (1.37; 1.40: Granite TTM replaced FinCast) - OBSERVE by default, never an order.

Data path (the SAME as Kronos - no second terminal connection, no new data source):
  closed bars of the existing MT5 bridge -> kronos.quality.check (closed only, order, duplicates, gaps, NaN/Inf, OHLC geometry, staleness)
  -> kronos.calendar (future candle times from the broker's real session slots: no weekend / break candles) -> ONE immutable snapshot
  per (instrument, timeframe, last closed bar) shared by both models -> JSON line -> long-lived model process (`python -m
  tsfm_runtime.worker` from .venv_chronos2 / .venv_granite, weights loaded once) -> forecast -> stored BEFORE its outcome.

Load control: a forecast only after a NEW closed bar of an enabled (model, instrument, timeframe) or on demand; one bounded queue for both
models processed by ONE executor thread (the models never run at the same time -> no shared-GPU OOM, CPU threads not oversubscribed); a
newer bar replaces a waiting older job (dedup on (model, instrument, timeframe)); timeouts kill and restart the process with back-off; a
heartbeat (ping) checks an idle process; the MT5 bridge, the UI and the order path never wait for a model.
A result that arrives after a NEWER bar closed is stored but never shown as current (`superseded`). Failures (not installed, checksum,
wrong checkpoint, out of memory, timeout, MT5 disconnected, stale / bad data, uncertain calendar) give a state with a reason and NO value.

Output meaning (kept, never re-labelled): close-only REGRESSION in price units; point = Chronos-2 median / Granite TTM point (point_kind);
model quantiles (uncalibrated on the user's data); direction UP / FLAT / DOWN from the point at H by the explicit neutral band rule
(the same rule as Kronos). No probability is derived from it.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import sys
import threading
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

from .. import paths
from ..kronos import calendar as CAL  # noqa: F401 - used through the shared helpers
from ..kronos import quality as Q
from ..kronos.service import KronosService
from ..timeutil import TF_SECONDS, iso, parse_iso, utcnow
from .settings import MODEL_IDS, PATHS, RETIRED_IDS as RETIRED, SettingsStore, default_weights_root, find_python, tsfm_dir

log = logging.getLogger("masterquo.tsfm")

STATUS_PL = {"NOT_INSTALLED": "nie zainstalowano środowiska modelu (przycisk „Zainstaluj” albo 38_MODELE_CHRONOS2_GRANITE.bat)",
             "NO_WEIGHTS": "brak zweryfikowanych wag modelu", "DISABLED": "model wyłączony w ustawieniach", "INSTALLING": "instalacja w toku",
             "STARTING": "uruchamianie procesu modelu", "LOADING": "ładowanie wag (raz na proces)", "READY": "model załadowany",
             "ERROR": "błąd modelu", "IDLE": "zainstalowany – proces uruchomi się przy pierwszej prognozie"}
TARGET_PL = {"RESOURCE_PAUSED": "wstrzymane przez Memory Governor (za mało pamięci)", "READY": "prognoza aktualna", "WAITING": "czeka na zamkniętą świecę", "QUEUED": "w kolejce", "RUNNING": "liczenie",
             "MODEL_UNAVAILABLE": "model niedostępny", "NO_SYMBOL": "brak symbolu brokera", "MT5_DISCONNECTED": "MT5 rozłączony",
             "STALE": "dane nieaktualne", "BLOCK": "dane odrzucone (jakość)", "WARMUP": "za mało świec", "ERROR": "błąd", "DISABLED": "wyłączony",
             "CALENDAR_UNCERTAIN": "niepewny kalendarz sesji", "SESSION_BREAK": "przerwa w notowaniach"}
DIR_PL = {"UP": "wzrost", "DOWN": "spadek", "FLAT": "bocznie"}
NAMES = {"chronos2": "Chronos-2", "granite_ttm": "Granite TTM", "fincast": "FinCast (wycofany)"}
RETIRED_PL = "wycofany w 1.40 – zastąpiony przez Granite TTM; historia prognoz zachowana, model nie jest uruchamiany"


class ModelWorker:
    """One long-lived inference process of one model (spawn on demand, load once, heartbeat, timeout -> kill + back-off)."""

    def __init__(self, svc: "TsfmService", mid: str):
        self.svc, self.mid = svc, mid
        self.proc: subprocess.Popen | None = None
        self._io = threading.Lock()
        self.info: dict | None = None
        self.load_info: dict | None = None
        self.load_key = None
        self.retry_at = 0.0
        self.backoff = 30.0
        self.state = {"status": "IDLE", "code": None, "reason": None, "updated_at": None}
        self.starts = 0
        self.last_ok = 0.0
        self.timings: list[float] = []
        self.errlog = None
        self.last_used = time.monotonic()            # last forecast request (heartbeat pings do not count) - idle release by the governor

    def set_state(self, status: str, reason: str | None = None, code: str | None = None) -> None:
        self.state = {"status": status, "code": code, "reason": reason, "updated_at": iso(utcnow())}

    def kill(self) -> None:
        p, self.proc = self.proc, None
        self.load_info, self.load_key = None, None
        if p and p.poll() is None:
            try:
                p.stdin.write('{"cmd":"quit"}\n')
                p.stdin.flush()
                p.wait(timeout=10)
            except Exception:  # noqa: BLE001
                p.kill()
        if p is not None:
            for f in (p.stdin, p.stdout):
                try:
                    f.close()
                except Exception:  # noqa: BLE001
                    pass
        if self.errlog is not None:
            self.errlog.close()
            self.errlog = None

    def ask(self, req: dict, timeout: float) -> dict:
        """One request -> its response (matched by id). Timeout: the process is killed (its state is unknown) - no late answer is used."""
        with self._io:
            p = self.proc
            if p is None or p.poll() is not None:
                raise RuntimeError("proces modelu nie działa")
            rid = uuid.uuid4().hex[:12]
            p.stdin.write(json.dumps({**req, "id": rid}, allow_nan=False) + "\n")
            p.stdin.flush()
            box: dict = {}

            def read():
                while True:
                    line = p.stdout.readline()
                    if not line:
                        box["eof"] = True
                        return
                    try:
                        msg = json.loads(line)
                    except ValueError:
                        continue
                    if msg.get("id") == rid:
                        box["msg"] = msg
                        return
            th = threading.Thread(target=read, daemon=True)
            th.start()
            th.join(timeout)
            if "msg" in box:
                return box["msg"]
            if box.get("eof"):
                raise RuntimeError("proces modelu zakończył się (np. brak pamięci)")
        self.kill()
        raise TimeoutError(f"TIMEOUT {timeout:.0f}s")

    def ensure(self) -> bool:
        s = self.svc.settings.get()
        c = s.models[self.mid]
        threads = self.svc.threads_for(self.mid, c)
        key = (str(self.svc.weights_root()), c.device, threads, c.checkpoint)
        if self.proc and self.proc.poll() is None and self.load_info and self.load_key == key:
            return True
        if self.proc and self.load_key != key:
            self.kill()
        if time.monotonic() < self.retry_at:
            return False
        py = find_python(self.mid, c)
        if not py:
            self.set_state("NOT_INSTALLED", STATUS_PL["NOT_INSTALLED"], "NOT_INSTALLED")
            return False
        from tsfm_runtime import manifest as M
        ms = M.summary(self.svc.weights_root(), self.mid)
        if not ms["installed"]:
            self.set_state("NO_WEIGHTS", ms["reason"], "NO_WEIGHTS")
            return False
        self.set_state("STARTING", STATUS_PL["STARTING"])
        env = dict(os.environ, PYTHONPATH=str(paths.ROOT_DIR / "backend"), PYTHONIOENCODING="utf-8", HF_HUB_OFFLINE="1",
                   HF_HUB_DISABLE_TELEMETRY="1", MASTERQUO_DATA_DIR=str(paths.data_dir()))
        errlog = self.errlog = open(paths.logs_dir() / f"tsfm_{self.mid}_worker.log", "a", encoding="utf-8")
        try:
            self.proc = subprocess.Popen([py, "-m", "tsfm_runtime.worker", "--model", self.mid], cwd=str(paths.ROOT_DIR / "backend"), env=env,
                                         text=True, encoding="utf-8", stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errlog, bufsize=1,
                                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as exc:
            errlog.close()
            return self.fail("WORKER_START", f"nie można uruchomić {py}: {exc}")
        self.starts += 1
        try:
            hello = self.ask({"cmd": "hello"}, 120)
            if not hello.get("ok"):
                return self.fail(hello.get("code") or "WORKER", hello.get("error"))
            self.info = {k: hello.get(k) for k in ("runtime", "versions", "cuda", "pid")} | {"python": py}
            self.set_state("LOADING", STATUS_PL["LOADING"])
            t0 = time.monotonic()
            r = self.ask({"cmd": "load", "weights_root": str(self.svc.weights_root()), "device": c.device, "threads": threads, "verify_files": True,
                          "checkpoint": c.checkpoint, "finetune_dir": str(tsfm_dir() / "finetuned" / self.mid)}, c.load_timeout_s)
        except (TimeoutError, RuntimeError, ValueError) as exc:
            return self.fail("WORKER_TIMEOUT" if isinstance(exc, TimeoutError) else "WORKER", str(exc))
        if not r.get("ok"):
            return self.fail(r.get("code") or "LOAD_ERROR", r.get("error"))
        self.load_info, self.load_key, self.backoff = r["info"], key, 30.0
        self.load_info["cold_start_s"] = round(time.monotonic() - t0, 1)
        gov = getattr(self.svc, "governor", None)
        if gov is not None:
            gov.record(self.mid, load_ms=r["info"].get("load_ms"))
        self.set_state("READY", STATUS_PL["READY"])
        self.last_ok = time.monotonic()
        self.svc.applog.info("TSFM", "LOADED", f"{NAMES[self.mid]} załadowany: {r['info'].get('params')} parametrów, urządzenie "
                                               f"{r['info'].get('device')} ({r['info'].get('device_note') or 'OK'}), {r['info'].get('load_ms')} ms.")
        return True

    def fail(self, code: str, detail: str | None) -> bool:
        self.kill()
        self.retry_at = time.monotonic() + self.backoff
        self.backoff = min(1800.0, self.backoff * 2)
        self.set_state("ERROR", f"{code}: {detail}"[:400] if detail else code, code)
        try:
            self.svc.applog.warning("TSFM", code, f"{NAMES[self.mid]} niedostępny: {detail}"[:300])
        except Exception:  # noqa: BLE001
            pass
        return False

    def heartbeat(self) -> None:
        if self.proc is None or self.proc.poll() is not None or not self.load_info or time.monotonic() - self.last_ok < 120:
            return
        try:
            r = self.ask({"cmd": "ping"}, 30)
            if r.get("ok"):
                self.last_ok = time.monotonic()
                self.load_info["rss_mb_now"] = r.get("rss_mb")
        except (TimeoutError, RuntimeError):
            self.fail("HEARTBEAT", "proces modelu nie odpowiada – restart przy następnej prognozie")

    def timing(self) -> dict:
        xs = sorted(self.timings[-200:])
        if not xs:
            return {"n": 0}
        pick = lambda q: xs[min(len(xs) - 1, int(q * (len(xs) - 1) + 0.5))]  # noqa: E731
        return {"n": len(xs), "p50_ms": pick(0.5), "p95_ms": pick(0.95), "max_ms": xs[-1]}


class TsfmService:
    # the data helpers of the Kronos service (same bridge, same symbol mapping, same calendar / meta caches) - one implementation
    symbol = KronosService.symbol
    data_kind = KronosService.data_kind
    _bars = KronosService._bars
    _calendar = KronosService._calendar
    _point = KronosService._point

    def __init__(self, cfg_store, bridge, db, bus, log_, *, clock=time.time, settings: SettingsStore | None = None):
        self.cfg_store, self.bridge, self.db, self.bus, self.applog, self.clock = cfg_store, bridge, db, bus, log_, clock
        self.settings = settings or SettingsStore()
        self.workers = {m: ModelWorker(self, m) for m in MODEL_IDS}
        self._qlock = threading.Condition()
        self.exec_lock = threading.RLock()                # one request at a time per service (live forecasts + validation)
        self._stop = threading.Event()
        self.queue: OrderedDict = OrderedDict()           # (mid, inst, tf) -> job
        self.running: tuple | None = None
        self.targets: dict[tuple, dict] = {}               # (inst, tf) -> data target (shared snapshot)
        self.mstate: dict[tuple, dict] = {}                # (mid, inst, tf) -> {"state", "reason", "last_key"}
        self.latest: dict[tuple, dict] = {}                # (mid, inst, tf) -> forecast
        self.context_tail: dict[tuple, list] = {}
        self.counters = {"enqueued": 0, "deduplicated": 0, "dropped_queue_full": 0, "done": 0, "errors": 0, "timeouts": 0, "superseded": 0}
        self._cal: dict = {}
        self._meta: dict = {}
        self.jobs: dict[str, dict | None] = {}
        self._job_procs: dict[str, subprocess.Popen] = {}
        self._threads: list[threading.Thread] = []
        self.kronos = None                                 # KronosService (runtime) - for the three-model comparison only
        self.listeners: list = []

    # ================================================================== lifecycle
    def start(self) -> None:
        for name, fn in (("tsfm-sched", self._loop), ("tsfm-exec", self._exec_loop)):
            th = threading.Thread(target=fn, name=name, daemon=True)
            th.start()
            self._threads.append(th)

    def stop(self) -> None:
        self._stop.set()
        with self._qlock:
            self._qlock.notify_all()
        for w in self.workers.values():
            w.kill()
        for p in list(self._job_procs.values()):
            if p.poll() is None:
                p.terminate()

    def threads_for(self, mid: str, c) -> int:
        """CPU threads of a model process: the explicit setting, else the resource profile (Memory Governor), else all cores but one."""
        if c.cpu_threads:
            return int(c.cpu_threads)
        gov = getattr(self, "governor", None)
        if gov is not None:
            return gov.threads_for(mid)
        return max(1, (os.cpu_count() or 2) - 1)

    def weights_root(self) -> Path:
        s = self.settings.get()
        return Path(s.weights_root) if s.weights_root else default_weights_root()

    def env_status(self, mid: str) -> dict:
        from tsfm_runtime import lock as L
        from tsfm_runtime import manifest as M
        c = self.settings.get().models[mid]
        py = find_python(mid, c)
        ms = M.summary(self.weights_root(), mid)
        pin = L.model(mid)
        return {"python": py, "python_found": py is not None, "weights_root": str(self.weights_root()), "weights_installed": ms["installed"],
                "weights_reason": ms.get("reason"), "installed_at": ms.get("installed_at"),
                "pinned": {k: pin[k] for k in ("repo", "revision", "variant", "params_upstream", "license", "code", "venv")},
                "fingerprint": L.fingerprint(mid)}

    # ================================================================== scheduler (one data read per closed bar, shared by both models)
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
                for w in self.workers.values():
                    if self.running is None:
                        w.heartbeat()
            except Exception as exc:  # noqa: BLE001 - a model never affects the bot
                log.exception("tsfm tick")
                for w in self.workers.values():
                    w.set_state("ERROR", f"{type(exc).__name__}: {exc}"[:300], "TICK")
            self._stop.wait(2.0)

    def _ms(self, k: tuple) -> dict:
        return self.mstate.setdefault(k, {"state": "WAITING", "reason": None, "last_key": None})

    def _wanted(self, s) -> dict[tuple, list[str]]:
        out: dict[tuple, list[str]] = {}
        for mid, c in s.models.items():
            if not c.enabled:
                continue
            for i in c.instruments:
                for tf in c.timeframes:
                    out.setdefault((i, tf), []).append(mid)
        return out

    def tick(self, force: tuple | None = None) -> None:
        s = self.settings.get()
        ready_models = []
        for mid, w in self.workers.items():
            c = s.models[mid]
            if not c.enabled:
                if w.proc:
                    w.kill()
                w.set_state("DISABLED", STATUS_PL["DISABLED"], "DISABLED")
                continue
            if (self.jobs.get(f"install_{mid}") or {}).get("state") == "RUNNING":
                w.set_state("INSTALLING", STATUS_PL["INSTALLING"])
                continue
            env = self.env_status(mid)
            if not env["python_found"]:
                w.set_state("NOT_INSTALLED", STATUS_PL["NOT_INSTALLED"], "NOT_INSTALLED")
            elif not env["weights_installed"]:
                w.set_state("NO_WEIGHTS", env["weights_reason"], "NO_WEIGHTS")
            else:
                if w.state["status"] in ("NOT_INSTALLED", "NO_WEIGHTS", "DISABLED", "INSTALLING"):
                    w.set_state("IDLE", STATUS_PL["IDLE"])
                ready_models.append(mid)
        wanted = self._wanted(s)
        for k in list(self.targets):
            if k not in wanted:
                self.targets.pop(k, None)
        conn = (self.bridge.connection_status() or {}).get("state") == "CONNECTED"
        now = self.clock()
        for (inst, tf), mids in wanted.items():
            mids = [m for m in mids if m in ready_models]
            for m in wanted[(inst, tf)]:
                if m not in mids:
                    self._ms((m, inst, tf)).update(state="MODEL_UNAVAILABLE", reason=self.workers[m].state.get("reason"))
            if mids:
                self._check_target(inst, tf, mids, s, conn, now, force=(force == (inst, tf)))

    def _target(self, key: tuple) -> dict:
        return self.targets.setdefault(key, {"instrument": key[0], "timeframe": key[1], "state": "WAITING", "reason": None, "next_check": 0.0,
                                             "quality": None, "symbol": None, "checked_at": None, "snapshot_id": None, "bar_key": None})

    def _check_target(self, inst: str, tf: str, mids: list[str], s, connected: bool, now: float, force: bool = False) -> None:
        t = self._target((inst, tf))
        sym, why = self.symbol(inst)
        t["symbol"] = sym

        def all_models(state, reason):
            t.update(state=state, reason=reason)
            for m in mids:
                self._ms((m, inst, tf)).update(state=state, reason=reason)
        if not sym:
            return all_models("NO_SYMBOL", why)
        if not connected:
            return all_models("MT5_DISCONNECTED", "MT5 rozłączony – nowe prognozy wstrzymane; ostatnia prognoza nie jest aktualna")
        if not force and now < t["next_check"]:
            return
        tf_sec = TF_SECONDS[tf]
        t["checked_at"] = iso(utcnow())
        try:
            bars = self._bars(sym, tf, s.lookback + 60)
        except Exception as exc:  # noqa: BLE001
            t["next_check"] = now + 30
            return all_models("ERROR", f"świece z MT5 niedostępne: {type(exc).__name__}: {exc}"[:240])
        cal, cal_err = self._calendar(sym, tf)
        q = Q.check(bars, tf_sec, now_utc=now, lookback=s.lookback, min_context=s.min_context, calendar=cal, volume_setting="AUTO",
                    max_staleness_bars=s.max_staleness_bars)
        t["quality"] = {k: q[k] for k in ("status", "issues", "n", "forming_excluded", "duplicates_dropped", "invalid", "gaps", "last_close_age_s",
                                         "volume_source", "volume_source_pl")}
        self.settle(inst, tf, [b for b in bars if b.get("closed")])
        last = q["bars"][-1] if q["bars"] else None
        if last and last.get("open_utc"):
            nxt = parse_iso(last["open_utc"]).timestamp() + 2 * tf_sec + 3
            t["next_check"] = min(max(now + 5, nxt), now + tf_sec)
        else:
            t["next_check"] = now + 30
        if cal is None:
            return all_models("ERROR", cal_err)
        if q["status"] in ("BLOCK", "WARMUP", "STALE"):
            return all_models(q["status"], "; ".join(i["reason"] for i in q["issues"] if i["level"] == q["status"]) or q["status"])
        bar_key = last["open_utc"]
        snap = self._snapshot_id(sym, tf, q["bars"])
        t.update(state="READY", reason=None, snapshot_id=snap, bar_key=bar_key)
        for m in mids:
            ms = self._ms((m, inst, tf))
            if ms["last_key"] == bar_key and not force:
                fc = self.latest.get((m, inst, tf))
                if fc and fc["last_bar_open_utc"] == bar_key:
                    ms.update(state="READY", reason=None)
                continue
            if self.enqueue({"model": m, "instrument": inst, "timeframe": tf, "symbol": sym, "bar_key": bar_key, "bars": q["bars"],
                             "quality": t["quality"], "calendar": cal, "snapshot_id": snap, "enqueued_at": now}):
                ms.update(state="QUEUED", reason=None)

    @staticmethod
    def _snapshot_id(sym: str, tf: str, bars: list[dict]) -> str:
        h = hashlib.sha256()
        h.update(f"{sym}|{tf}|{len(bars)}".encode())
        for b in bars[-600:]:
            h.update(f"{b.get('open_utc')}|{b['o']}|{b['h']}|{b['l']}|{b['c']}|{b.get('tv')}".encode())
        return "SNP-" + h.hexdigest()[:16]

    def enqueue(self, job: dict) -> bool:
        k = (job["model"], job["instrument"], job["timeframe"])
        with self._qlock:
            if k in self.queue:
                self.counters["deduplicated"] += 1
                self.queue.pop(k)
            elif len(self.queue) >= self.settings.get().queue_max:
                self.counters["dropped_queue_full"] += 1
                self._ms(k).update(state="WAITING", reason="kolejka pełna – prognoza przy następnej świecy")
                return False
            self.queue[k] = job
            self.counters["enqueued"] += 1
            self._qlock.notify()
        return True

    def refresh(self, mid: str, inst: str, tf: str) -> dict:
        s = self.settings.get()
        c = s.models.get(mid)
        if c is None or inst not in c.instruments or tf not in c.timeframes or not c.enabled:
            return {"ok": False, "reason": f"{NAMES.get(mid, mid)}: {inst} {tf} nie jest włączony w ustawieniach"}
        if self.running == (mid, inst, tf) or (mid, inst, tf) in self.queue:
            return {"ok": False, "reason": "prognoza już liczona / w kolejce (ochrona przed przeciążeniem)"}
        self._ms((mid, inst, tf))["last_key"] = None
        self._target((inst, tf))["next_check"] = 0.0
        self.tick(force=(inst, tf))
        return {"ok": True, "target": self.target_view((mid, inst, tf))}

    # ================================================================== execution (ONE thread for both models)
    def _exec_loop(self) -> None:
        while not self._stop.is_set():
            with self._qlock:
                while not self.queue and not self._stop.is_set():
                    self._qlock.wait(1.0)
                if self._stop.is_set():
                    return
                k, job = self.queue.popitem(last=False)
                self.running = k
            try:
                with self.exec_lock:
                    self.run_job(job)
            except Exception as exc:  # noqa: BLE001
                log.exception("tsfm job")
                self.counters["errors"] += 1
                self._ms(k).update(state="ERROR", reason=f"{type(exc).__name__}: {exc}"[:300])
            finally:
                self.running = None

    def run_job(self, job: dict) -> dict | None:
        mid, inst, tf = job["model"], job["instrument"], job["timeframe"]
        k = (mid, inst, tf)
        ms = self._ms(k)
        s = self.settings.get()
        c = s.models[mid]
        w = self.workers[mid]
        gov = getattr(self, "governor", None)
        loaded = bool(w.proc and w.proc.poll() is None and w.load_info)
        if gov is not None:
            ok, why = gov.admit(mid, loaded=loaded)
            if not ok:
                ms.update(state="RESOURCE_PAUSED", reason=why)                  # never a neutral value: the forecast is simply not there
                return None
        ms.update(state="RUNNING", reason=None)
        w.last_used = time.monotonic()
        with (gov.heavy(mid) if gov is not None else _nullslot()) as slot:
            if not slot:
                ms.update(state="RESOURCE_PAUSED", reason="slot ciężkiej inferencji zajęty zbyt długo – prognoza przy następnej świecy")
                return None
            return self._run_job_loaded(job, k, ms, s, c, w)

    def _run_job_loaded(self, job, k, ms, s, c, w) -> dict | None:
        mid, inst, tf = k
        if not w.ensure():
            ms.update(state="MODEL_UNAVAILABLE", reason=w.state.get("reason"))
            return None
        bars, tf_sec = job["bars"], TF_SECONDS[tf]
        H = int(s.horizon_bars[tf])
        last = bars[-1]
        last_raw = int(last["t_raw"])
        off = last_raw - int(parse_iso(last["open_utc"]).timestamp())
        y_raw, cinfo = job["calendar"].future(last_raw, tf_sec, H)
        if y_raw is None:
            ms.update(state=cinfo["status"], reason=cinfo["reason"], last_key=job["bar_key"])
            return None
        ctx = min(c.context_len, len(bars))
        req = {"cmd": "predict", "close": [float(b["c"]) for b in bars[-ctx:]], "pred_len": H, "context_len": ctx, "profile": c.profile,
               "quantiles": s.quantiles, "freq_tf": tf}
        if c.profile == "CLOSE_OHLCV_PAST_V1":
            vsrc = job["quality"]["volume_source"]
            vol = [float(b.get("rv") or 0) for b in bars[-ctx:]] if vsrc == "REAL_VOLUME" else \
                [float(b.get("tv") or 0) for b in bars[-ctx:]] if vsrc == "TICK_VOLUME" else None
            req["covariates"] = {"open": [b["o"] for b in bars[-ctx:]], "high": [b["h"] for b in bars[-ctx:]], "low": [b["l"] for b in bars[-ctx:]],
                                 "volume": vol}
        try:
            r = w.ask(req, c.request_timeout_s)
        except TimeoutError as exc:
            self.counters["timeouts"] += 1
            w.fail("TIMEOUT", f"{exc}: prognoza przekroczyła {c.request_timeout_s:.0f} s – proces zrestartowany")
            ms.update(state="ERROR", reason=f"TIMEOUT: prognoza przekroczyła {c.request_timeout_s:.0f} s", last_key=job["bar_key"])
            return None
        except (RuntimeError, ValueError) as exc:
            w.fail("WORKER", str(exc))
            ms.update(state="ERROR", reason=str(exc)[:300])
            return None
        if not r.get("ok"):
            self.counters["errors"] += 1
            if r.get("code") in ("RESOURCE_LIMIT",):
                w.fail(r["code"], r.get("error"))
            ms.update(state="ERROR", reason=f"{r.get('code')}: {r.get('error')}"[:400], last_key=job["bar_key"])
            return None
        w.timings.append(float(r.get("ms") or 0))
        w.last_ok = w.last_used = time.monotonic()
        gov = getattr(self, "governor", None)
        if gov is not None:
            gov.record(mid, ms=r.get("ms"))
        fc = self._forecast(job, r, y_raw, off, H, s, cinfo, ctx)
        tgt = self._target((inst, tf))
        superseded = tgt.get("bar_key") not in (None, job["bar_key"])           # a newer bar closed while the model was computing
        fc["superseded"] = superseded
        self.record(fc)
        if superseded:
            self.counters["superseded"] += 1
            ms.update(state="WAITING", reason="wynik dla starszej świecy (w trakcie liczenia zamknęła się nowa) – zapisany, nieaktualny")
            return fc
        self.latest[k] = fc
        self.context_tail[(inst, tf)] = [{"t": b["open_utc"], "c": b["c"]} for b in bars[-120:]]
        ms.update(state="READY", reason=None, last_key=job["bar_key"])
        self.counters["done"] += 1
        self._publish()
        for fn in list(self.listeners):
            try:
                fn(fc)
            except Exception:  # noqa: BLE001
                log.exception("tsfm listener")
        return fc

    def _forecast(self, job, r, y_raw, off, H, s, cinfo, ctx) -> dict:
        from tsfm_runtime import lock as L
        mid, bars, tf = job["model"], job["bars"], job["timeframe"]
        last = bars[-1]
        pt, digits = self._point(job["symbol"])
        a = Q.atr(bars, 14)
        band = max(s.direction_band_atr * (a or 0.0), s.direction_band_min_points * (pt or 0.0))
        last_close = float(last["c"])
        point = [float(x) for x in r["point"]]
        pc = point[-1]
        delta = pc - last_close
        direction = "UP" if delta > band else "DOWN" if delta < -band else "FLAT"
        times = [iso(datetime.fromtimestamp(raw - off, tz=timezone.utc)) for raw in y_raw]
        qv = (r.get("quantiles") or {}).get("values") or {}
        path = [{"t_utc": t, "point": point[i], "median": (r.get("median") or [None] * H)[i], **{f"q{k}": v[i] for k, v in qv.items()}}
                for i, t in enumerate(times)]
        kind, kind_pl = self.data_kind()
        tf_sec = TF_SECONDS[tf]
        close_t = parse_iso(last["open_utc"]).timestamp() + tf_sec
        load = self.workers[mid].load_info or {}
        pin = L.model(mid)
        return {"id": uuid.uuid4().hex[:16], "model_id": mid, "model_name": pin["name"], "variant": pin["variant"], "model_revision": pin["revision"],
                "fingerprint": L.fingerprint(mid), "params": load.get("params"), "profile": r.get("profile") or "CLOSE_V1",
                "preprocessing": ("PMW-TSFM-PRE-2 (zamknięte świece z kontroli jakości, bez uzupełniania luk; normalizacja z-score wyłącznie z okna "
                                  "kontekstu w procesie modelu, odwracana na wyjściu)") if mid == "granite_ttm" else
                "PMW-TSFM-PRE-1 (zamknięte świece z kontroli jakości, bez normalizacji po stronie bota, bez uzupełniania luk)",
                "normalization": r.get("normalization"), "checkpoint": load.get("checkpoint") or "BASE",
                "feature_schema": f"TSFM_{r.get('profile') or 'CLOSE_V1'}", "snapshot_id": job["snapshot_id"], "instrument": job["instrument"],
                "symbol": job["symbol"], "data_source": kind_pl, "data_kind": kind, "timeframe": tf, "horizon_bars": H, "context_bars": ctx,
                "created_at": iso(utcnow()), "last_bar_open_utc": last["open_utc"],
                "last_bar_close_utc": iso(datetime.fromtimestamp(close_t, tz=timezone.utc)), "data_available_at": iso(datetime.fromtimestamp(close_t, tz=timezone.utc)),
                "valid_until": iso(datetime.fromtimestamp(close_t + tf_sec * s.max_staleness_bars, tz=timezone.utc)),
                "target_times": times, "target": "close", "task_type": "REGRESSION", "unit": "price", "point_kind": r.get("point_kind"),
                "last_close": last_close, "pred_close_h": pc, "median_close_h": (r.get("median") or [None])[-1], "path": path,
                "quantile_levels": (r.get("quantiles") or {}).get("levels"), "quantile_crossing_steps": (r.get("quantiles") or {}).get("crossing_steps"),
                "delta_price": delta, "delta_pct": (delta / last_close * 100.0) if last_close else None, "direction": direction,
                "direction_pl": DIR_PL[direction], "neutral_band": band,
                "band_rule": f"bocznie, gdy |zmiana| ≤ max({s.direction_band_atr} × ATR14({tf}), {s.direction_band_min_points} × point)",
                "atr14": a, "point": pt, "digits": digits, "device": r.get("device"), "compute_ms": r.get("ms"), "input_hash": r.get("input_hash"),
                "freq_class": r.get("freq_class"), "quality": job["quality"], "calendar": cinfo, "state": "READY",
                "calibration": {"status": "UNCALIBRATED", "note": "kwantyle modelu nie były kalibrowane na danych brokera" if r.get("quantiles")
                                else "prognoza punktowa – brak kwantyli; nie jest prawdopodobieństwem"},
                "mode": "SHADOW", "execution_permission": False,
                "note": "prognoza close (nie świece OHLC); kierunek z reguły pasma neutralnego – nie jest prawdopodobieństwem"}

    # ================================================================== ledger + settlement
    def record(self, fc: dict) -> None:
        settings = {"quantiles": fc["quantile_levels"], "band_rule": fc["band_rule"], "superseded": fc.get("superseded", False)}
        self.db.execute(
            """INSERT OR IGNORE INTO tsfm_forecasts(forecast_id, model_id, model_name, model_revision, fingerprint, profile, snapshot_id, created_at,
               instrument, symbol, data_source, timeframe, horizon_bars, context_bars, last_bar_open_utc, data_available_at, valid_until, last_close,
               point_kind, pred_close_h, median_close_h, delta_price, direction, neutral_band, path_json, quantiles_json, input_hash, device,
               compute_ms, data_kind, quality_status, settings_json, outcome_status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (fc["id"], fc["model_id"], fc["model_name"], fc["model_revision"], fc["fingerprint"], fc["profile"], fc["snapshot_id"], fc["created_at"],
             fc["instrument"], fc["symbol"], fc["data_source"], fc["timeframe"], fc["horizon_bars"], fc["context_bars"], fc["last_bar_open_utc"],
             fc["data_available_at"], fc["valid_until"], fc["last_close"], fc["point_kind"], fc["pred_close_h"], fc["median_close_h"], fc["delta_price"],
             fc["direction"], fc["neutral_band"], json.dumps([{"t_utc": p["t_utc"], "c": p["point"]} for p in fc["path"]]),
             json.dumps({"levels": fc["quantile_levels"], "path": [{k: v for k, v in p.items() if k.startswith("q")} for p in fc["path"]]}),
             fc["input_hash"], fc["device"], fc["compute_ms"], fc["data_kind"], fc["quality"]["status"], json.dumps(settings), "PENDING"))

    def settle(self, inst: str, tf: str, closed_bars: list[dict]) -> int:
        """PENDING forecasts whose last target bar is closed: actual closes of EXACTLY the target times from real closed bars; a missing
        target bar -> NO_DATA (never interpolated). Point error, naive (last price) error, pinball loss of the quantiles at H, 80 % coverage."""
        closes = {b["open_utc"]: float(b["c"]) for b in closed_bars if b.get("open_utc")}
        if not closes:
            return 0
        last_open, first_open = max(closes), min(closes)
        rows = self.db.query("SELECT * FROM tsfm_forecasts WHERE outcome_status='PENDING' AND instrument=? AND timeframe=? LIMIT 400", (inst, tf))
        n = 0
        for r in rows:
            path = json.loads(r["path_json"])
            if path[-1]["t_utc"] > last_open:
                continue
            if r["last_bar_open_utc"] < first_open:
                st, out = "OUT_OF_BUFFER", {}
            else:
                act = [closes.get(x["t_utc"]) for x in path]
                if act[-1] is None:
                    st, out = "NO_DATA", {"missing_steps": sum(1 for a in act if a is None)}
                else:
                    band = r["neutral_band"] or 0.0
                    d = act[-1] - r["last_close"]
                    dir_act = "UP" if d > band else "DOWN" if d < -band else "FLAT"
                    errs = [abs(x["c"] - a) for x, a in zip(path, act) if a is not None]
                    qj = json.loads(r["quantiles_json"] or "null") or {}
                    qh = (qj.get("path") or [{}])[-1]
                    pin = None
                    if qh:
                        y = act[-1]
                        pin = sum(max(float(lv) * (y - v), (float(lv) - 1) * (y - v)) for lv, v in ((k[1:], v) for k, v in qh.items())) / len(qh)
                    cov = None
                    if "q0.1" in qh and "q0.9" in qh:
                        cov = int(qh["q0.1"] <= act[-1] <= qh["q0.9"])
                    st = "SETTLED"
                    out = {"actual_close_h": act[-1], "abs_err_h": abs(r["pred_close_h"] - act[-1]), "naive_abs_err_h": abs(r["last_close"] - act[-1]),
                           "path_mae": sum(errs) / len(errs), "steps_with_data": len(errs), "direction_actual": dir_act, "pinball_h": pin,
                           "covered_80": cov, "direction_hit": None if (r["direction"] == "FLAT" or dir_act == "FLAT") else int(r["direction"] == dir_act)}
            self.db.execute("""UPDATE tsfm_forecasts SET outcome_status=?, actual_close_h=?, abs_err_h=?, naive_abs_err_h=?, path_mae=?, pinball_h=?,
                               covered_80=?, direction_actual=?, direction_hit=?, outcome_json=?, settled_at=? WHERE id=?""",
                            (st, out.get("actual_close_h"), out.get("abs_err_h"), out.get("naive_abs_err_h"), out.get("path_mae"), out.get("pinball_h"),
                             out.get("covered_80"), out.get("direction_actual"), out.get("direction_hit"), json.dumps(out), iso(utcnow()), r["id"]))
            n += 1
        return n

    def history(self, mid: str | None = None, inst: str | None = None, tf: str | None = None, limit: int = 100) -> list[dict]:
        q, a = "SELECT * FROM tsfm_forecasts WHERE 1=1", []
        for col, v in (("model_id", mid), ("instrument", inst), ("timeframe", tf)):
            if v:
                q, a = q + f" AND {col}=?", a + [v]
        rows = self.db.query(q + " ORDER BY id DESC LIMIT ?", tuple(a + [limit]))
        for r in rows:
            r["path"] = json.loads(r.pop("path_json") or "[]")
            r["quantiles"] = json.loads(r.pop("quantiles_json") or "null")
            r["outcome"] = json.loads(r.pop("outcome_json")) if r.get("outcome_json") else None
            r["settings"] = json.loads(r.pop("settings_json") or "{}")
        return rows

    def scorecard(self, mid: str, inst: str, tf: str) -> dict:
        out = {}
        for label, kinds in (("REAL", ("MT5", "MT5_DEMO", "MT5_REAL")), ("SYNTHETIC", ("SYNTHETIC",))):
            ph = ",".join("?" * len(kinds))
            rows = self.db.query(f"SELECT * FROM tsfm_forecasts WHERE model_id=? AND instrument=? AND timeframe=? AND outcome_status='SETTLED' "
                                 f"AND data_kind IN ({ph}) ORDER BY id DESC LIMIT 5000", (mid, inst, tf, *kinds))
            pend = self.db.one(f"SELECT COUNT(*) AS n FROM tsfm_forecasts WHERE model_id=? AND instrument=? AND timeframe=? AND outcome_status='PENDING' "
                               f"AND data_kind IN ({ph})", (mid, inst, tf, *kinds))["n"]
            if not rows:
                out[label] = {"settled": 0, "pending": pend}
                continue
            rows = rows[::-1]
            h = rows[0]["horizon_bars"] or 1
            nonover = rows[::h]
            hits = [r["direction_hit"] for r in rows if r["direction_hit"] is not None]
            cov = [r["covered_80"] for r in rows if r["covered_80"] is not None]
            out[label] = {"settled": len(rows), "pending": pend, "mae_h": _mean(r["abs_err_h"] for r in rows),
                          "naive_mae_h": _mean(r["naive_abs_err_h"] for r in rows), "pinball_h": _mean(r["pinball_h"] for r in rows),
                          "coverage_80": (sum(cov) / len(cov)) if cov else None, "direction_evaluated": len(hits),
                          "direction_hit_rate": (sum(hits) / len(hits)) if hits else None,
                          "non_overlapping": {"n": len(nonover), "mae_h": _mean(r["abs_err_h"] for r in nonover),
                                              "naive_mae_h": _mean(r["naive_abs_err_h"] for r in nonover)},
                          "note": "kolejne prognozy co świecę mają nakładające się horyzonty – wiarygodniejszy jest podzbiór bez nakładania i raport walidacji"}
        return out

    # ================================================================== views
    def target_view(self, k: tuple) -> dict:
        mid, inst, tf = k
        ms = self._ms(k)
        t = self._target((inst, tf))
        fc = self.latest.get(k)
        current = bool(fc) and ms["state"] == "READY" and fc["last_bar_open_utc"] == ms.get("last_key") == t.get("bar_key")
        return {"model": mid, "instrument": inst, "timeframe": tf, "symbol": t.get("symbol"), "state": ms["state"], "reason": ms["reason"],
                "state_pl": TARGET_PL.get(ms["state"], ms["state"]), "quality": t.get("quality"), "checked_at": t.get("checked_at"),
                "snapshot_id": t.get("snapshot_id"), "forecast_current": current, "forecast_id": fc["id"] if fc else None,
                "queued": k in self.queue, "running": self.running == k}

    def is_current(self, k: tuple) -> bool:
        return self.target_view(k)["forecast_current"]

    def forecast(self, mid: str, inst: str, tf: str) -> dict:
        k = (mid, inst, tf)
        fc = self.latest.get(k)
        tv = self.target_view(k)
        return {"target": tv, "forecast": fc, "is_current": tv["forecast_current"], "context": self.context_tail.get((inst, tf), []),
                "scorecard": self.scorecard(mid, inst, tf),
                "stale_note": None if (fc is None or tv["forecast_current"]) else
                f"prognoza z {fc['created_at']} dla świecy {fc['last_bar_open_utc']} NIE jest aktualna ({tv['state_pl']}: {tv['reason'] or ''})"}

    def compare(self, inst: str, tf: str) -> dict:
        """The three models side by side for the SAME instrument, timeframe, last closed bar and horizon (otherwise listed as not comparable).
        Agreement is described (k of n agree) - never turned into a probability or an average."""
        rows = []
        tgt = self._target((inst, tf))
        H = int(self.settings.get().horizon_bars[tf])
        kr = self.kronos
        if kr is not None:
            fc = kr.latest.get((inst, tf))
            cur = bool(fc) and kr.target_view((inst, tf))["forecast_current"]
            from kronos_runtime import lock as LK
            rows.append({"model": "kronos", "name": LK.MODEL_NAME, "available": bool(fc), "current": cur,
                         "last_bar_open_utc": (fc or {}).get("last_bar_open_utc"), "horizon_bars": (fc or {}).get("horizon_bars"),
                         "point_kind": "sample", "pred_close_h": (fc or {}).get("pred_close_h"), "direction": (fc or {}).get("direction"),
                         "delta_price": (fc or {}).get("delta_price"), "q10_h": ((fc or {}).get("uncertainty") or {}).get("close_quantiles", {}).get("q10", [None])[-1]
                         if (fc or {}).get("uncertainty") else None,
                         "q90_h": ((fc or {}).get("uncertainty") or {}).get("close_quantiles", {}).get("q90", [None])[-1] if (fc or {}).get("uncertainty") else None,
                         "reason": None if cur else kr.target_view((inst, tf)).get("reason")})
        for mid in MODEL_IDS:
            fc = self.latest.get((mid, inst, tf))
            tv = self.target_view((mid, inst, tf))
            last = (fc or {}).get("path", [{}])[-1] if fc else {}
            rows.append({"model": mid, "name": NAMES[mid], "available": bool(fc), "current": tv["forecast_current"],
                         "last_bar_open_utc": (fc or {}).get("last_bar_open_utc"), "horizon_bars": (fc or {}).get("horizon_bars"),
                         "point_kind": (fc or {}).get("point_kind"), "pred_close_h": (fc or {}).get("pred_close_h"), "direction": (fc or {}).get("direction"),
                         "delta_price": (fc or {}).get("delta_price"), "q10_h": last.get("q0.1"), "q90_h": last.get("q0.9"),
                         "reason": None if tv["forecast_current"] else tv["reason"]})
        ref_bar = tgt.get("bar_key")
        comparable = [r for r in rows if r["current"] and r["last_bar_open_utc"] == ref_bar and r["horizon_bars"] == H]
        for r in rows:
            r["comparable"] = r in comparable
        dirs = [r["direction"] for r in comparable]
        summary = None
        if comparable:
            cnt = {"UP": dirs.count("UP"), "DOWN": dirs.count("DOWN"), "FLAT": dirs.count("FLAT")}
            top = max(cnt.values())
            leads = [d for d, c in cnt.items() if c == top]
            lead = leads[0] if len(leads) == 1 else None                      # a tie has no leading direction
            head = (f"{top} z {len(comparable)} modeli wskazuje {DIR_PL[lead]}" if lead else
                    f"brak przewagi kierunku ({len(comparable)} modele: w górę {cnt['UP']}, w dół {cnt['DOWN']}, bocznie {cnt['FLAT']})")
            summary = {"n": len(comparable), "up": cnt["UP"], "down": cnt["DOWN"], "flat": cnt["FLAT"], "leading": lead,
                       "agree": top if lead else None, "conflict": cnt["UP"] > 0 and cnt["DOWN"] > 0,
                       "text": f"{head} – zgodność modeli liczących na tych samych świecach nie jest niezależnym potwierdzeniem ani prawdopodobieństwem"}
        return {"instrument": inst, "timeframe": tf, "horizon_bars": H, "last_bar_open_utc": ref_bar, "rows": rows, "summary": summary,
                "rule": "porównywane są tylko prognozy aktualne dla tej samej ostatniej świecy, interwału i horyzontu; brak walidacji = brak wag i łączenia"}

    def public(self) -> dict:
        s = self.settings.get()
        from tsfm_runtime import lock as L
        out = {}
        for mid, w in self.workers.items():
            c = s.models[mid]
            pin = L.model(mid)
            out[mid] = {"model_id": mid, "name": NAMES[mid], "variant": pin["variant"], "repo": pin["repo"], "revision": pin["revision"],
                        "params_upstream": pin["params_upstream"], "license": pin["license"], "status": w.state["status"],
                        "status_pl": STATUS_PL.get(w.state["status"], w.state["status"]), "code": w.state.get("code"), "reason": w.state.get("reason"),
                        "updated_at": w.state.get("updated_at"), "worker": w.info, "load": w.load_info, "timing": w.timing(), "restarts": w.starts,
                        "enabled": c.enabled, "instruments": c.instruments, "timeframes": c.timeframes, "profile": c.profile, "context_len": c.context_len,
                        "device": c.device, "use": {p: c.use[p].model_dump() for p in PATHS}, "env": self.env_status(mid),
                        "targets": [self.target_view((mid, i, tf)) for i in c.instruments for tf in c.timeframes],
                        "jobs": {n: (j and {x: j.get(x) for x in ("state", "message", "step", "total", "updated_at", "code")})
                                 for n, j in self.jobs.items() if n.endswith(mid)}}
        return {"version": "PMW-TSFM-1", "mode": "SHADOW", "execution_permission": False, "models": out, "horizon_bars": s.horizon_bars,
                "quantiles": s.quantiles, "queue": [list(k) for k in self.queue], "running": list(self.running) if self.running else None,
                "counters": dict(self.counters), "settings_error": self.settings.load_error,
                "jobs": {"validation": (lambda j: j and {x: j.get(x) for x in ("state", "message", "step", "total", "updated_at", "code")})(self.jobs.get("validation"))},
                "retired": {k: {"name": NAMES.get(k, k), "status": "RETIRED", "status_pl": RETIRED_PL, "history_count": self._count(k),
                                "settings": (s.retired.get(k) or {}).get("settings")} for k in RETIRED},
                "settings_history": self.settings.history(20),
                "memory_note": "pomiar procesów modeli: panel Zasoby (Memory Governor); Granite TTM ok. 0,35 GB, Chronos-2 ok. 1 GB, Kronos-base ok. 1,1 GB"}

    def _count(self, mid: str) -> int:
        try:
            return int(self.db.one("SELECT COUNT(*) AS n FROM tsfm_forecasts WHERE model_id=?", (mid,))["n"])
        except Exception:  # noqa: BLE001
            return 0

    def _publish(self) -> None:
        try:
            self.bus.publish("tsfm", {"updated_at": iso(utcnow()), "latest": {f"{k[0]}|{k[1]}|{k[2]}": v["id"] for k, v in self.latest.items()}})
        except Exception:  # noqa: BLE001
            pass

    # ================================================================== install / verify / validation jobs (separate processes / thread)
    def _run_job_proc(self, name: str, argv: list[str], env: dict | None = None, on_done=None) -> dict:
        cur = self.jobs.get(name)
        if cur and cur.get("state") == "RUNNING":
            return {"ok": False, "reason": f"{name} już trwa"}
        status_file = tsfm_dir() / f"{name}_status.json"
        try:
            status_file.unlink()
        except OSError:
            pass
        job = {"state": "RUNNING", "message": "start", "step": 0, "total": None, "log": [], "started_at": iso(utcnow()), "result": None,
               "updated_at": iso(utcnow())}
        self.jobs[name] = job

        def run():
            logf = paths.logs_dir() / f"tsfm_{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
            job["log_file"] = str(logf)
            try:
                p = subprocess.Popen(argv + ["--status-file", str(status_file)], cwd=str(paths.ROOT_DIR), text=True, encoding="utf-8", errors="replace",
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env or dict(os.environ, PYTHONIOENCODING="utf-8"),
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except OSError as exc:
                job.update(state="FAILED", message=f"nie można uruchomić: {exc}", code="START", updated_at=iso(utcnow()))
                return
            self._job_procs[name] = p
            with open(logf, "w", encoding="utf-8") as lf:
                for line in p.stdout:
                    lf.write(line)
                    line = line.rstrip()
                    if line.startswith("RESULT "):
                        try:
                            job["result"] = json.loads(line[7:])
                        except ValueError:
                            pass
                    elif line:
                        job["log"] = (job["log"] + [line])[-60:]
                        job["message"] = line[-300:]
                    try:
                        st = json.loads(status_file.read_text(encoding="utf-8"))
                        job.update(step=st.get("step"), total=st.get("total"))
                    except (OSError, ValueError):
                        pass
                    job["updated_at"] = iso(utcnow())
            rc = p.wait()
            res = job.get("result") or {}
            ok = rc == 0 and res.get("ok", rc == 0)
            job.update(state="DONE" if ok else "FAILED", rc=rc, code=None if ok else (res.get("code") or f"RC_{rc}"),
                       message=(job["message"] if ok else (res.get("error") or job["message"])), updated_at=iso(utcnow()))
            self._job_procs.pop(name, None)
            if on_done:
                on_done(ok, job)
            self._publish()

        threading.Thread(target=run, name=f"tsfm-{name}", daemon=True).start()
        return {"ok": True, "job": name}

    def start_install(self, mid: str) -> dict:
        if mid not in MODEL_IDS:
            return {"ok": False, "reason": "INVALID_MODEL"}
        self.workers[mid].kill()
        argv = [sys.executable, str(paths.ROOT_DIR / "tools" / "tsfm_setup.py"), "--model", mid, "--root", str(paths.ROOT_DIR),
                "--weights-root", str(self.weights_root())]

        def done(ok, job):
            w = self.workers[mid]
            w.retry_at, w.backoff = 0.0, 30.0
            self.applog.info("TSFM", "INSTALL", f"Instalacja {NAMES[mid]}: {'OK' if ok else 'BŁĄD ' + str(job.get('code'))}.")
        return self._run_job_proc(f"install_{mid}", argv, on_done=done)

    def start_verify(self, mid: str) -> dict:
        if mid not in MODEL_IDS:
            return {"ok": False, "reason": "INVALID_MODEL"}
        c = self.settings.get().models[mid]
        py = find_python(mid, c)
        if not py:
            return {"ok": False, "reason": STATUS_PL["NOT_INSTALLED"]}
        env = dict(os.environ, PYTHONPATH=str(paths.ROOT_DIR / "backend"), PYTHONIOENCODING="utf-8", HF_HUB_OFFLINE="1")
        argv = [py, "-m", "tsfm_runtime.install", "verify", "--model", mid, "--weights-root", str(self.weights_root()), "--selftest",
                "--device", c.device]
        return self._run_job_proc(f"verify_{mid}", argv, env=env)

    def start_validation(self, inst: str, tf: str, max_origins: int = 200) -> dict:
        from . import validation as V
        cur = self.jobs.get("validation")
        if cur and cur.get("state") == "RUNNING":
            return {"ok": False, "reason": "walidacja już trwa"}
        job = {"state": "RUNNING", "message": f"walidacja {inst} {tf}: start", "step": 0, "total": None, "started_at": iso(utcnow()),
               "updated_at": iso(utcnow()), "instrument": inst, "timeframe": tf, "report_id": None}
        self.jobs["validation"] = job

        def prog(i, n, msg=""):
            job.update(step=i, total=n, message=f"walidacja {inst} {tf}: {i}/{n} {msg}", updated_at=iso(utcnow()))

        def run():
            try:
                rep = V.run(self, inst, tf, max_origins=max_origins, progress=prog)
                job.update(state="DONE" if rep.get("status") == "DONE" else "FAILED", report_id=rep.get("report_id"),
                           message=rep.get("summary_text") or rep.get("reason"), code=None if rep.get("status") == "DONE" else rep.get("status"),
                           updated_at=iso(utcnow()))
            except Exception as exc:  # noqa: BLE001
                log.exception("tsfm validation")
                job.update(state="FAILED", code="EXCEPTION", message=f"{type(exc).__name__}: {exc}"[:300], updated_at=iso(utcnow()))
            self._publish()

        threading.Thread(target=run, name="tsfm-validation", daemon=True).start()
        return {"ok": True, "job": "validation"}

    def job(self, name: str) -> dict | None:
        j = self.jobs.get(name)
        return dict(j) if j else None

    # ================================================================== decision roles
    def set_use(self, mid: str, path: str, use: str, *, timeframe: str | None = None, confirm: bool = False) -> dict:
        """OBSERVE at any time; ASSIST / REQUIRED only with a positive walk-forward report on REAL data for the CURRENT binding (model
        fingerprint, symbol, timeframe, horizon, context, profile, band) of every enabled instrument + explicit confirmation."""
        from . import validation as V
        s = self.settings.get()
        if mid not in MODEL_IDS or path not in PATHS:
            return {"ok": False, "reason": "INVALID_MODEL_OR_PATH"}
        c = s.models[mid]
        tf = timeframe or c.use[path].timeframe
        if use == "OBSERVE":
            self.settings.update({"models": {mid: {"use": {path: {"use": "OBSERVE", "timeframe": tf, "validation_report": None, "confirmed_at": None}}}}})
            return {"ok": True, "use": "OBSERVE"}
        if use not in ("ASSIST", "REQUIRED"):
            return {"ok": False, "reason": "INVALID_USE"}
        if not confirm:
            return {"ok": False, "reason": f"CONFIRMATION_REQUIRED: {NAMES[mid]} jako {use} dla {path} wymaga świadomego potwierdzenia"}
        if tf not in c.timeframes:
            return {"ok": False, "reason": f"TIMEFRAME_DISABLED: {NAMES[mid]} nie liczy {tf}"}
        reps = {i: V.latest_report(i, tf) for i in c.instruments}
        bad = []
        for i, r in reps.items():
            v = ((r or {}).get("models") or {}).get(mid, {}).get("verdict") or {}
            if not v.get("positive"):
                bad.append(f"{i} {tf}: {v.get('reason') or 'brak raportu walidacji walk-forward'}")
                continue
            d = V.binding_diff((r.get("bindings") or {}).get(mid), V.binding(self, mid, i, tf))
            if d:
                bad.append(f"{i} {tf}: raport nieaktualny ({'; '.join(d)[:200]})")
        if bad:
            return {"ok": False, "reason": "VALIDATION_REQUIRED: " + "; ".join(bad)}
        ids = ",".join(r["report_id"] for r in reps.values())
        self.settings.update({"models": {mid: {"use": {path: {"use": use, "timeframe": tf, "validation_report": ids, "confirmed_at": iso(utcnow())}}}}})
        self.applog.info("TSFM", "USE", f"{NAMES[mid]}: {path} = {use} ({tf}), raporty {ids}.")
        return {"ok": True, "use": use, "reports": ids}


class _nullslot:
    def __enter__(self):
        return True

    def __exit__(self, *a):
        return False


def _mean(it) -> float | None:
    xs = [float(x) for x in it if x is not None]
    return sum(xs) / len(xs) if xs else None
