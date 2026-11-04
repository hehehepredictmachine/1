"""Kronos forecasts in the bot - SHADOW observation by default, never an order.

Data path: closed bars from the EXISTING bridge (MT5Worker queue - no second terminal connection; the active symbol is read from the
bridge's own buffer, the other instrument through bridge.symbol_bars) -> quality.check -> calendar (future candle times) -> JSON line
-> isolated process `python -m kronos_runtime.worker` from .venv_kronos (PyTorch, model loaded once, eval, no gradients) -> forecast.

Load control: a forecast is computed only after a NEW closed bar of an enabled (instrument, timeframe) or on demand; the queue keeps at
most one job per target (a newer bar replaces a waiting older one = deduplication) and at most `queue_max` targets; one forecast at a
time with a timeout (the worker is killed and restarted with back-off); the MT5 bridge and the panel never wait for the model.
Failures (no environment, no weights, checksum, incompatible pair, MT5 disconnected, stale / bad data, uncertain session calendar,
timeout, GPU error) give a state with a reason and NO forecast; an older forecast is shown as not current, never as new.
Every forecast is stored BEFORE its outcome (kronos_forecasts) and settled later only from real closed bars of the exact target times.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
import uuid
import zlib
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

from .. import paths
from ..timeutil import TF_SECONDS, iso, parse_iso, utcnow
from . import calendar as CAL
from . import quality as Q
from .settings import SettingsStore, default_weights_dir, find_python, kronos_dir

log = logging.getLogger("masterquo.kronos")

STATUS_PL = {"NOT_INSTALLED": "nie zainstalowano środowiska .venv_kronos (przycisk „Zainstaluj model Kronos” albo 33_KRONOS_INSTALUJ.bat)",
             "NO_WEIGHTS": "brak zweryfikowanych wag modelu / tokenizera (instalacja niepełna)", "DISABLED": "wyłączony w ustawieniach",
             "INSTALLING": "instalacja w toku", "STARTING": "uruchamianie procesu modelu", "LOADING": "ładowanie modelu i tokenizera",
             "READY": "model załadowany – prognozy po każdej nowej zamkniętej świecy", "ERROR": "błąd modelu"}
TARGET_PL = {"READY": "prognoza aktualna", "WAITING": "czeka na zamkniętą świecę / kolejkę", "QUEUED": "w kolejce", "RUNNING": "liczenie",
             "NO_SYMBOL": "brak potwierdzonego symbolu brokera", "MT5_DISCONNECTED": "MT5 rozłączony", "STALE": "dane nieaktualne",
             "WARMUP": "za mało zamkniętych świec", "BLOCK": "dane odrzucone przez kontrolę jakości", "CALENDAR_UNCERTAIN": "niepewny kalendarz sesji",
             "CALENDAR_INSUFFICIENT": "za krótka historia do kalendarza sesji", "CALENDAR_NO_SESSION": "brak sesji w horyzoncie",
             "ERROR": "błąd", "MODEL_UNAVAILABLE": "model niedostępny", "DISABLED": "wyłączony"}
DIR_PL = {"UP": "wzrost", "DOWN": "spadek", "FLAT": "bocznie"}
USABLE_MAPPING = ("CONFIRMED", "USER_SPECIFIED", "AUTO_DETECTED")


class KronosService:
    def __init__(self, cfg_store, bridge, db, bus, log_, *, clock=time.time, settings: SettingsStore | None = None):
        self.cfg_store, self.bridge, self.db, self.bus, self.applog, self.clock = cfg_store, bridge, db, bus, log_, clock
        self.settings = settings or SettingsStore()
        self.proc: subprocess.Popen | None = None
        self._io = threading.Lock()
        self._qlock = threading.Condition()
        self._stop = threading.Event()
        self.queue: OrderedDict = OrderedDict()            # (inst, tf) -> job (one per target; newest bar wins)
        self.running: tuple | None = None
        self.targets: dict[tuple, dict] = {}
        self.latest: dict[tuple, dict] = {}
        self.context_tail: dict[tuple, list] = {}
        self.worker_info: dict | None = None
        self.load_info: dict | None = None
        self.load_key = None
        self.retry_at = 0.0
        self.backoff = 30.0
        self.state = {"status": "STARTING", "code": None, "reason": None, "updated_at": None}
        self.counters = {"enqueued": 0, "deduplicated": 0, "dropped_queue_full": 0, "done": 0, "errors": 0, "timeouts": 0, "worker_starts": 0}
        self._cal: dict[tuple, tuple] = {}
        self._meta: dict[str, tuple] = {}
        self.jobs: dict[str, dict | None] = {"install": None, "verify": None, "validation": None}
        self._job_procs: dict[str, subprocess.Popen] = {}
        self._threads: list[threading.Thread] = []
        self.listeners: list = []

    # ================================================================== lifecycle
    def start(self) -> None:
        for name, fn in (("kronos-sched", self._loop), ("kronos-exec", self._exec_loop)):
            th = threading.Thread(target=fn, name=name, daemon=True)
            th.start()
            self._threads.append(th)

    def stop(self) -> None:
        self._stop.set()
        with self._qlock:
            self._qlock.notify_all()
        self._kill()
        for p in list(self._job_procs.values()):
            if p.poll() is None:
                p.terminate()

    # ================================================================== paths / environment
    def weights_dir(self) -> Path:
        s = self.settings.get()
        return Path(s.weights_dir) if s.weights_dir else default_weights_dir()

    def env_status(self) -> dict:
        from kronos_runtime import lock as L
        from kronos_runtime import manifest as M
        s = self.settings.get()
        py = find_python(s)
        ms = M.summary(self.weights_dir())
        return {"python": py, "python_found": py is not None, "weights_dir": str(self.weights_dir()), "weights_installed": ms["installed"],
                "weights_reason": ms.get("reason"), "installed_at": ms.get("installed_at"),
                "pinned": [{k: c[k] for k in ("kind", "repo", "revision")} for c in L.COMPONENTS],
                "manifest_components": ms.get("components")}

    # ================================================================== worker process
    def _kill(self) -> None:
        p, self.proc = self.proc, None
        self.load_info, self.load_key = None, None
        if p and p.poll() is None:
            try:
                p.stdin.write('{"cmd":"quit"}\n')
                p.stdin.flush()
                p.wait(timeout=5)
            except Exception:  # noqa: BLE001
                p.kill()

    def _ask(self, req: dict, timeout: float) -> dict:
        with self._io:
            p = self.proc
            if not p or p.poll() is not None:
                raise RuntimeError("WORKER_NOT_RUNNING")
            req = {**req, "id": uuid.uuid4().hex[:12]}
            p.stdin.write(json.dumps(req, allow_nan=False) + "\n")
            p.stdin.flush()
            box: dict = {}
            th = threading.Thread(target=lambda: box.update(line=p.stdout.readline()), daemon=True)
            th.start()
            th.join(timeout)
            if th.is_alive() or not box.get("line"):
                self.counters["timeouts" if th.is_alive() else "errors"] += 1
                self._kill()
                raise TimeoutError("WORKER_TIMEOUT" if th.is_alive() else "WORKER_EXITED")
            resp = json.loads(box["line"])
            if resp.get("id") != req["id"]:
                self._kill()
                raise RuntimeError("WORKER_PROTOCOL_DESYNC")
            return resp

    def _set_state(self, status: str, reason: str | None = None, code: str | None = None) -> None:
        changed = (status, reason, code) != (self.state["status"], self.state.get("reason"), self.state.get("code"))
        self.state.update(status=status, reason=reason, code=code, updated_at=iso(utcnow()))
        if changed:
            self._publish()

    def _load_key(self, s) -> tuple:
        return (str(self.weights_dir()), s.device, s.max_context, s.cpu_threads)

    def _threads_default(self) -> int:
        return max(1, min(4, (os.cpu_count() or 2) // 2))

    def ensure_worker(self) -> bool:
        """Spawn + load once; back-off after a failure. Returns True when a loaded model is available."""
        s = self.settings.get()
        if self.proc and self.proc.poll() is None and self.load_info and self.load_key == self._load_key(s):
            return True
        if self.proc and self.load_key != self._load_key(s):
            self._kill()                                                    # device / path / threads changed -> reload
        if time.monotonic() < self.retry_at:
            return False
        py = find_python(s)
        if not py:
            self._set_state("NOT_INSTALLED", STATUS_PL["NOT_INSTALLED"], "NOT_INSTALLED")
            return False
        from kronos_runtime import manifest as M
        ms = M.summary(self.weights_dir())
        if not ms["installed"]:
            self._set_state("NO_WEIGHTS", ms["reason"], "NO_WEIGHTS")
            return False
        self._set_state("STARTING", STATUS_PL["STARTING"])
        env = dict(os.environ, PYTHONPATH=str(paths.ROOT_DIR / "backend"), PYTHONIOENCODING="utf-8", HF_HUB_OFFLINE="1",
                   HF_HUB_DISABLE_TELEMETRY="1", MASTERQUO_DATA_DIR=str(paths.data_dir()))
        errlog = open(paths.logs_dir() / "kronos_worker.log", "a", encoding="utf-8")       # library warnings / tracebacks
        try:
            self.proc = subprocess.Popen([py, "-m", "kronos_runtime.worker"], cwd=str(paths.ROOT_DIR / "backend"), env=env, text=True,
                                         encoding="utf-8", stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errlog, bufsize=1,
                                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as exc:
            errlog.close()
            return self._fail("WORKER_START", f"nie można uruchomić {py}: {exc}")
        finally:
            pass
        self.counters["worker_starts"] += 1
        try:
            hello = self._ask({"cmd": "hello"}, 120)
            if not hello.get("ok"):
                return self._fail(hello.get("code") or "WORKER", hello.get("error"))
            self.worker_info = {k: hello.get(k) for k in ("runtime", "versions", "cuda", "pid")} | {"python": py}
            self._set_state("LOADING", STATUS_PL["LOADING"])
            r = self._ask({"cmd": "load", "weights_dir": str(self.weights_dir()), "device": s.device, "max_context": s.max_context,
                           "threads": s.cpu_threads or self._threads_default(), "verify_files": True}, s.load_timeout_s)
        except (TimeoutError, RuntimeError, ValueError) as exc:
            return self._fail("WORKER_TIMEOUT" if isinstance(exc, TimeoutError) else "WORKER", str(exc))
        if not r.get("ok"):
            return self._fail(r.get("code") or "LOAD_ERROR", r.get("error"))
        self.load_info, self.load_key, self.backoff = r["info"], self._load_key(s), 30.0
        self._set_state("READY", STATUS_PL["READY"])
        self.applog.info("KRONOS", "LOADED", f"Kronos załadowany: urządzenie {r['info']['device']} ({r['info'].get('device_note') or 'OK'}), "
                         f"{r['info']['load_ms']} ms, proces {self.proc.pid if self.proc else '?'}.")
        return True

    def _fail(self, code: str, detail: str | None) -> bool:
        self._kill()
        self.retry_at = time.monotonic() + self.backoff
        self.backoff = min(900.0, self.backoff * 2)
        self._set_state("ERROR", f"{code}: {detail}"[:400] if detail else code, code)
        self.applog.warning("KRONOS", code, f"Kronos niedostępny: {detail}"[:300]) if hasattr(self.applog, "warning") else None
        return False

    # ================================================================== symbols / data
    def symbol(self, inst: str) -> tuple[str | None, str | None]:
        m = self.cfg_store.get().assets.mappings.get(inst)
        if m is None or not m.broker_symbol:
            return None, f"{inst}: brak symbolu brokera – wybierz go w Ustawienia → Mapowanie instrumentów"
        if m.status not in USABLE_MAPPING:
            return None, f"{inst}: symbol {m.broker_symbol} ma status {m.status} – potwierdź wybór w Ustawienia → Mapowanie instrumentów"
        return m.broker_symbol, None

    def data_kind(self) -> tuple[str, str]:
        if getattr(self.bridge, "synthetic", False):
            return "SYNTHETIC", "SYNTETYCZNE (symulator terminala – nie notowania rynku)"
        acc = self.bridge.account_status() or {}
        tm = acc.get("trade_mode")
        if tm == "DEMO":
            return "MT5_DEMO", "MT5 – notowania serwera brokera, rachunek DEMO"
        if tm == "REAL":
            return "MT5_REAL", "MT5 – notowania serwera brokera, rachunek REAL"
        return "MT5", "MT5 – notowania serwera brokera"

    def _bars(self, sym: str, tf: str, n: int) -> list[dict]:
        if sym == self.cfg_store.get().mt5.symbol:
            b = self.bridge.bars(tf, limit=n, include_forming=True)            # the bridge's own buffer: no extra terminal call
            if sum(1 for x in b if x.get("closed")) >= n - 60:
                return b
        return self.bridge.symbol_bars(sym, tf, n)

    def _calendar(self, sym: str, tf: str):
        src = "M5" if tf == "M1" else tf
        key = (sym, tf)
        hit = self._cal.get(key)
        if hit and self.clock() - hit[0] < 6 * 3600:
            return hit[1], hit[2]
        count = int(min(8100, 28 * 86400 // TF_SECONDS[src]))
        try:
            bars = self.bridge.symbol_bars(sym, src, count)
        except Exception as exc:  # noqa: BLE001
            return None, f"historia do kalendarza sesji niedostępna: {type(exc).__name__}: {exc}"[:200]
        cal = CAL.Calendar([int(b["t_raw"]) for b in bars if b.get("closed")], CAL.slot_seconds(TF_SECONDS[tf]))
        self._cal[key] = (self.clock(), cal, None)
        return cal, None

    def _point(self, sym: str) -> tuple[float | None, int | None]:
        hit = self._meta.get(sym)
        if hit and self.clock() - hit[0] < 3600:
            return hit[1], hit[2]
        try:
            m = self.bridge.symbol_meta(sym) or {}
        except Exception:  # noqa: BLE001
            m = {}
        pt, dg = m.get("point"), m.get("digits")
        self._meta[sym] = (self.clock(), pt, dg)
        return pt, dg

    # ================================================================== scheduler
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001 - the model never affects the bot
                log.exception("kronos tick")
                self._set_state("ERROR", f"{type(exc).__name__}: {exc}"[:300], "TICK")
            self._stop.wait(2.0)

    def tick(self, force_target: tuple | None = None) -> None:
        s = self.settings.get()
        if self.jobs["install"] and self.jobs["install"].get("state") == "RUNNING":
            self._set_state("INSTALLING", STATUS_PL["INSTALLING"])
            return
        if not s.enabled:
            if self.proc:
                self._kill()
            self._set_state("DISABLED", STATUS_PL["DISABLED"], "DISABLED")
            for k in list(self.targets):
                self.targets[k].update(state="DISABLED", reason="Kronos wyłączony w ustawieniach")
            return
        env = self.env_status()
        if not env["python_found"]:
            self._set_state("NOT_INSTALLED", STATUS_PL["NOT_INSTALLED"], "NOT_INSTALLED")
        elif not env["weights_installed"]:
            self._set_state("NO_WEIGHTS", env["weights_reason"], "NO_WEIGHTS")
        elif self.state["status"] in ("NOT_INSTALLED", "NO_WEIGHTS", "DISABLED", "INSTALLING", "STARTING"):
            self._set_state("STARTING", "model zainstalowany – proces uruchomi się przy pierwszej prognozie")
        conn = (self.bridge.connection_status() or {}).get("state") == "CONNECTED"
        now = self.clock()
        wanted = {(i, tf) for i in s.instruments for tf in s.timeframes}
        for k in list(self.targets):
            if k not in wanted:
                self.targets.pop(k, None)
        if not (env["python_found"] and env["weights_installed"]):
            for k in wanted:                                               # nothing installed: no terminal reads, no queue
                self._target(k).update(state="MODEL_UNAVAILABLE", reason=self.state.get("reason"))
            return
        for inst in s.instruments:
            for tf in s.timeframes:
                self._check_target(inst, tf, s, conn, now, force=(force_target == (inst, tf)))

    def _target(self, key: tuple) -> dict:
        return self.targets.setdefault(key, {"instrument": key[0], "timeframe": key[1], "state": "WAITING", "reason": None, "last_key": None,
                                             "next_check": 0.0, "quality": None, "symbol": None, "checked_at": None})

    def _check_target(self, inst: str, tf: str, s, connected: bool, now: float, force: bool = False) -> None:
        key = (inst, tf)
        t = self._target(key)
        sym, why = self.symbol(inst)
        t["symbol"] = sym
        if not sym:
            t.update(state="NO_SYMBOL", reason=why)
            return
        if not connected:
            t.update(state="MT5_DISCONNECTED", reason="MT5 rozłączony – nowe prognozy wstrzymane; ostatnia prognoza nie jest aktualna")
            return
        if not force and now < t["next_check"]:
            return
        tf_sec = TF_SECONDS[tf]
        t["checked_at"] = iso(utcnow())
        try:
            bars = self._bars(sym, tf, s.lookback + 60)
        except Exception as exc:  # noqa: BLE001
            t.update(state="ERROR", reason=f"świece z MT5 niedostępne: {type(exc).__name__}: {exc}"[:240], next_check=now + 30)
            return
        cal, cal_err = self._calendar(sym, tf)
        q = Q.check(bars, tf_sec, now_utc=now, lookback=s.lookback, min_context=s.min_context, calendar=cal, volume_setting=s.volume_source,
                    max_staleness_bars=s.max_staleness_bars)
        t["quality"] = {k: q[k] for k in ("status", "issues", "n", "forming_excluded", "duplicates_dropped", "invalid", "gaps", "last_close_age_s",
                                         "volume_source", "volume_source_pl", "amount_source", "amount_source_pl")}
        self.settle(inst, tf, [b for b in bars if b.get("closed")])
        last = q["bars"][-1] if q["bars"] else None
        if last and last.get("open_utc"):
            nxt = parse_iso(last["open_utc"]).timestamp() + 2 * tf_sec + 3       # a few seconds after the next bar is expected to close
            t["next_check"] = min(max(now + 5, nxt), now + tf_sec)             # at most one read per bar (+ the stale / closed-market case)
        else:
            t["next_check"] = now + 30
        if cal is None:
            t.update(state="ERROR", reason=cal_err)
            return
        if q["status"] in ("BLOCK", "WARMUP", "STALE"):
            t.update(state=q["status"], reason="; ".join(i["reason"] for i in q["issues"] if i["level"] == q["status"]) or q["status"])
            return
        bar_key = last["open_utc"]
        if bar_key == t["last_key"] and not force:
            if key in self.latest and self.latest[key]["last_bar_open_utc"] == bar_key:
                t.update(state="READY", reason=None)
            return
        self.enqueue({"instrument": inst, "timeframe": tf, "symbol": sym, "bar_key": bar_key, "bars": q["bars"], "quality": t["quality"],
                      "calendar": cal, "force": force, "enqueued_at": now})
        t.update(state="QUEUED", reason=None)

    def enqueue(self, job: dict) -> bool:
        k = (job["instrument"], job["timeframe"])
        with self._qlock:
            if k in self.queue:
                self.counters["deduplicated"] += 1                              # newer bar replaces the waiting one
                self.queue.pop(k)
            elif len(self.queue) >= self.settings.get().queue_max:
                self.counters["dropped_queue_full"] += 1
                self._target(k).update(state="WAITING", reason="kolejka pełna – prognoza przy następnej świecy")
                return False
            self.queue[k] = job
            self.counters["enqueued"] += 1
            self._qlock.notify()
        return True

    def refresh(self, inst: str, tf: str) -> dict:
        """On demand (panel button): re-read the bars now and queue a forecast for the CURRENT last closed bar."""
        s = self.settings.get()
        if inst not in s.instruments or tf not in s.timeframes:
            return {"ok": False, "reason": f"{inst} {tf} nie jest włączony w ustawieniach Kronos"}
        self._target((inst, tf))["last_key"] = None
        self.tick(force_target=(inst, tf))
        return {"ok": True, "target": self.target_view((inst, tf))}

    # ================================================================== execution
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
                self.run_job(job)
            except Exception as exc:  # noqa: BLE001
                log.exception("kronos job")
                self.counters["errors"] += 1
                self._target(k).update(state="ERROR", reason=f"{type(exc).__name__}: {exc}"[:300])
            finally:
                self.running = None

    def run_job(self, job: dict) -> dict | None:
        k = (job["instrument"], job["timeframe"])
        t = self._target(k)
        s = self.settings.get()
        t.update(state="RUNNING", reason=None)
        if not self.ensure_worker():
            t.update(state="MODEL_UNAVAILABLE", reason=self.state.get("reason"))
            return None
        tf, bars = job["timeframe"], job["bars"]
        tf_sec = TF_SECONDS[tf]
        H = int(s.horizon_bars[tf])
        last = bars[-1]
        last_raw = int(last["t_raw"])
        off = last_raw - int(parse_iso(last["open_utc"]).timestamp())           # server offset of these bars (s)
        y_raw, cinfo = job["calendar"].future(last_raw, tf_sec, H)
        if y_raw is None:
            t.update(state=cinfo["status"], reason=cinfo["reason"], last_key=job["bar_key"])
            return None

        def fmt(raw: int) -> str:
            sec = raw if s.timestamp_basis == "SERVER" else raw - off
            return datetime.fromtimestamp(sec, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        vsrc = job["quality"]["volume_source"]
        vol = None
        if vsrc == "REAL_VOLUME":
            vol = [float(b.get("rv") or 0) for b in bars]
        elif vsrc == "TICK_VOLUME":
            vol = [float(b.get("tv") or 0) for b in bars]
        seed = zlib.crc32(f"{job['instrument']}|{tf}|{job['bar_key']}".encode())
        req = {"cmd": "predict", "candles": {"t": [fmt(int(b["t_raw"])) for b in bars], "open": [b["o"] for b in bars], "high": [b["h"] for b in bars],
                                             "low": [b["l"] for b in bars], "close": [b["c"] for b in bars], "volume": vol},
               "y_t": [fmt(r) for r in y_raw], "pred_len": H, "T": s.temperature, "top_k": s.top_k, "top_p": s.top_p, "seed": seed, "paths": s.paths}
        try:
            r = self._ask(req, s.request_timeout_s + (s.request_timeout_s * s.paths if s.paths else 0))
        except TimeoutError as exc:
            self.retry_at = time.monotonic() + 10
            t.update(state="ERROR", reason=f"{exc}: prognoza przekroczyła {s.request_timeout_s:.0f} s – proces modelu zrestartowany", last_key=job["bar_key"])
            return None
        except (RuntimeError, ValueError) as exc:
            t.update(state="ERROR", reason=str(exc)[:300])
            return None
        if not r.get("ok"):
            self.counters["errors"] += 1
            t.update(state="ERROR", reason=f"{r.get('code')}: {r.get('error')}"[:400], last_key=job["bar_key"])
            return None
        fc = self._forecast(job, r, y_raw, off, H, s, cinfo)
        self.latest[k] = fc
        self.context_tail[k] = [{"t": b["open_utc"], "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"]} for b in bars[-120:]]
        t.update(state="READY", reason=None, last_key=job["bar_key"])
        self.counters["done"] += 1
        self.record(fc)
        self._publish()
        for fn in list(self.listeners):
            try:
                fn(fc)
            except Exception:  # noqa: BLE001
                log.exception("kronos listener")
        return fc

    def _forecast(self, job, r, y_raw, off, H, s, cinfo) -> dict:
        bars, tf = job["bars"], job["timeframe"]
        last = bars[-1]
        p = r["pred"]
        pt, digits = self._point(job["symbol"])
        a = Q.atr(bars, 14)
        band = max(s.direction_band_atr * (a or 0.0), s.direction_band_min_points * (pt or 0.0))
        last_close = float(last["c"])
        pc = float(p["close"][-1])
        delta = pc - last_close
        direction = "UP" if delta > band else "DOWN" if delta < -band else "FLAT"
        steps = []
        bad_geom = 0
        for i, raw in enumerate(y_raw):
            o, h, low, c = p["open"][i], p["high"][i], p["low"][i], p["close"][i]
            if h < max(o, c) or low > min(o, c) or h < low:
                bad_geom += 1
            steps.append({"t_utc": iso(datetime.fromtimestamp(raw - off, tz=timezone.utc)), "o": o, "h": h, "l": low, "c": c,
                          "v": (p.get("volume") or [None] * len(y_raw))[i]})
        kind, kind_pl = self.data_kind()
        comps = {c["kind"]: c for c in (self.load_info or {}).get("components") or []}
        return {"id": uuid.uuid4().hex[:16], "instrument": job["instrument"], "symbol": job["symbol"], "timeframe": tf, "horizon_bars": H,
                "created_at": iso(utcnow()), "last_bar_open_utc": last["open_utc"],
                "last_bar_close_utc": iso(datetime.fromtimestamp(parse_iso(last["open_utc"]).timestamp() + TF_SECONDS[tf], tz=timezone.utc)),
                "last_close": last_close, "pred": steps, "pred_close_h": pc, "delta_price": delta,
                "delta_pct": (delta / last_close * 100.0) if last_close else None, "direction": direction, "direction_pl": DIR_PL[direction],
                "neutral_band": band, "band_rule": f"bocznie, gdy |zmiana| ≤ max({s.direction_band_atr} × ATR14({tf}), {s.direction_band_min_points} × point)",
                "atr14": a, "point": pt, "digits": digits, "uncertainty": r.get("paths"), "device": r.get("device"), "device_note": r.get("device_note"),
                "compute_ms": r.get("ms"), "seed": r.get("seed"), "sampling": r.get("sampling"), "context_bars": r.get("context_bars"),
                "model": comps.get("model"), "tokenizer": comps.get("tokenizer"), "runtime": (self.worker_info or {}).get("runtime"),
                "quality": job["quality"], "calendar": cinfo, "timestamp_basis": s.timestamp_basis, "data_kind": kind, "data_source": kind_pl,
                "ohlc_inconsistent_steps": bad_geom, "mode": "SHADOW", "execution_permission": False,
                "note": "pojedyncza próbkowana ścieżka modelu (sample_count=1) – nie jest pewnością ani skalibrowanym prawdopodobieństwem"}

    # ================================================================== ledger + settlement
    def record(self, fc: dict) -> None:
        self.db.execute(
            """INSERT OR IGNORE INTO kronos_forecasts(forecast_id, created_at, instrument, symbol, timeframe, horizon_bars, last_bar_open_utc,
               last_close, pred_close_h, delta_price, direction, neutral_band, path_json, uncertainty_json, model_revision, tokenizer_revision,
               device, compute_ms, data_kind, volume_source, quality_status, settings_json, outcome_status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (fc["id"], fc["created_at"], fc["instrument"], fc["symbol"], fc["timeframe"], fc["horizon_bars"], fc["last_bar_open_utc"], fc["last_close"],
             fc["pred_close_h"], fc["delta_price"], fc["direction"], fc["neutral_band"],
             json.dumps([{"t_utc": x["t_utc"], "c": x["c"]} for x in fc["pred"]]), json.dumps(fc["uncertainty"]) if fc["uncertainty"] else None,
             (fc.get("model") or {}).get("revision"), (fc.get("tokenizer") or {}).get("revision"), fc["device"], fc["compute_ms"], fc["data_kind"],
             fc["quality"]["volume_source"], fc["quality"]["status"], json.dumps({"sampling": fc["sampling"], "basis": fc["timestamp_basis"]}), "PENDING"))

    def settle(self, inst: str, tf: str, closed_bars: list[dict]) -> int:
        """Settle PENDING forecasts whose last target bar is already closed: per-step actual closes from REAL closed bars of exactly
        those times. Missing target bar (session break the calendar did not foresee, data hole) -> NO_DATA, never interpolated."""
        if not closed_bars:
            return 0
        closes = {b["open_utc"]: float(b["c"]) for b in closed_bars if b.get("open_utc")}
        if not closes:
            return 0                                                        # no UTC times yet (server offset unknown) - nothing to settle
        last_open = max(closes)
        first_open = min(closes)
        rows = self.db.query("SELECT * FROM kronos_forecasts WHERE outcome_status='PENDING' AND instrument=? AND timeframe=? LIMIT 200", (inst, tf))
        n = 0
        for r in rows:
            path = json.loads(r["path_json"])
            final_t = path[-1]["t_utc"]
            if final_t > last_open:
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
                    st = "SETTLED"
                    out = {"actual_close_h": act[-1], "abs_err_h": abs(r["pred_close_h"] - act[-1]), "naive_abs_err_h": abs(r["last_close"] - act[-1]),
                           "path_mae": sum(errs) / len(errs), "steps_with_data": len(errs), "direction_actual": dir_act,
                           "direction_hit": None if (r["direction"] == "FLAT" or dir_act == "FLAT") else int(r["direction"] == dir_act)}
            self.db.execute("""UPDATE kronos_forecasts SET outcome_status=?, actual_close_h=?, abs_err_h=?, naive_abs_err_h=?, path_mae=?,
                               direction_actual=?, direction_hit=?, outcome_json=?, settled_at=? WHERE id=?""",
                            (st, out.get("actual_close_h"), out.get("abs_err_h"), out.get("naive_abs_err_h"), out.get("path_mae"),
                             out.get("direction_actual"), out.get("direction_hit"), json.dumps(out), iso(utcnow()), r["id"]))
            n += 1
        return n

    def history(self, inst: str | None = None, tf: str | None = None, limit: int = 100) -> list[dict]:
        q, a = "SELECT * FROM kronos_forecasts WHERE 1=1", []
        if inst:
            q, a = q + " AND instrument=?", a + [inst]
        if tf:
            q, a = q + " AND timeframe=?", a + [tf]
        rows = self.db.query(q + " ORDER BY id DESC LIMIT ?", tuple(a + [limit]))
        for r in rows:
            r["path"] = json.loads(r.pop("path_json") or "[]")
            r["uncertainty"] = json.loads(r.pop("uncertainty_json")) if r.get("uncertainty_json") else None
            r["outcome"] = json.loads(r.pop("outcome_json")) if r.get("outcome_json") else None
        return rows

    def scorecard(self, inst: str, tf: str) -> dict:
        """Live SHADOW comparison with the actual move - only settled rows from real (non-synthetic) data count; synthetic separately."""
        out = {}
        for label, kinds in (("REAL", ("MT5", "MT5_DEMO", "MT5_REAL")), ("SYNTHETIC", ("SYNTHETIC",))):
            ph = ",".join("?" * len(kinds))
            rows = self.db.query(f"SELECT * FROM kronos_forecasts WHERE instrument=? AND timeframe=? AND outcome_status='SETTLED' AND data_kind IN ({ph}) "
                                 "ORDER BY id DESC LIMIT 5000", (inst, tf, *kinds))
            pend = self.db.one(f"SELECT COUNT(*) AS n FROM kronos_forecasts WHERE instrument=? AND timeframe=? AND outcome_status='PENDING' "
                               f"AND data_kind IN ({ph})", (inst, tf, *kinds))["n"]
            if not rows:
                out[label] = {"settled": 0, "pending": pend}
                continue
            rows = rows[::-1]
            h = rows[0]["horizon_bars"] or 1
            nonover = rows[::h]                                                 # every H-th forecast: horizons do not overlap
            hits = [r["direction_hit"] for r in rows if r["direction_hit"] is not None]
            out[label] = {"settled": len(rows), "pending": pend, "mae_h": _mean(r["abs_err_h"] for r in rows),
                          "naive_mae_h": _mean(r["naive_abs_err_h"] for r in rows), "direction_evaluated": len(hits),
                          "direction_hit_rate": (sum(hits) / len(hits)) if hits else None,
                          "non_overlapping": {"n": len(nonover), "mae_h": _mean(r["abs_err_h"] for r in nonover),
                                              "naive_mae_h": _mean(r["naive_abs_err_h"] for r in nonover)},
                          "note": "kolejne prognozy co świecę mają nakładające się horyzonty – nie są niezależnymi obserwacjami; "
                                  "wiarygodniejszy jest podzbiór bez nakładania (co H-tą prognozę) i raport walidacji walk-forward"}
        return out

    # ================================================================== views
    def target_view(self, k: tuple) -> dict:
        t = self._target(k)
        fc = self.latest.get(k)
        current = bool(fc) and t["state"] == "READY" and fc["last_bar_open_utc"] == t.get("last_key")
        return {**{x: t.get(x) for x in ("instrument", "timeframe", "symbol", "state", "reason", "quality", "checked_at")},
                "state_pl": TARGET_PL.get(t["state"], t["state"]), "forecast_current": current,
                "forecast_id": fc["id"] if fc else None, "queued": k in self.queue, "running": self.running == k}

    def forecast(self, inst: str, tf: str) -> dict:
        k = (inst, tf)
        fc = self.latest.get(k)
        tv = self.target_view(k)
        return {"target": tv, "forecast": fc, "is_current": tv["forecast_current"], "context": self.context_tail.get(k, []),
                "scorecard": self.scorecard(inst, tf),
                "stale_note": None if (fc is None or tv["forecast_current"]) else
                f"prognoza z {fc['created_at']} dla świecy {fc['last_bar_open_utc']} NIE jest aktualna ({tv['state_pl']}: {tv['reason'] or ''})"}

    def public(self) -> dict:
        s = self.settings.get()
        return {"status": self.state["status"], "status_pl": STATUS_PL.get(self.state["status"], self.state["status"]), "code": self.state.get("code"),
                "reason": self.state.get("reason"), "updated_at": self.state.get("updated_at"), "mode": "SHADOW", "execution_permission": False,
                "decision_use": {k: v.use for k, v in s.strategy_use.items()}, "worker": self.worker_info, "load": self.load_info,
                "targets": [self.target_view(k) for k in sorted(self.targets)], "queue": [list(k) for k in self.queue], "running": list(self.running) if self.running else None,
                "counters": dict(self.counters), "jobs": {k: (v and {x: v.get(x) for x in ("state", "message", "step", "total", "updated_at", "code")})
                                                          for k, v in self.jobs.items()},
                "settings_error": self.settings.load_error}

    def _publish(self) -> None:
        try:
            self.bus.publish("kronos", {"status": self.state["status"], "updated_at": iso(utcnow()),
                                        "targets": {f"{k[0]}|{k[1]}": {"state": v["state"], "forecast_id": (self.latest.get(k) or {}).get("id")}
                                                    for k, v in self.targets.items()}})
        except Exception:  # noqa: BLE001
            pass

    # ================================================================== install / verify jobs (separate processes)
    def _run_job_proc(self, name: str, argv: list[str], env: dict | None = None, on_done=None) -> dict:
        if self.jobs.get(name) and self.jobs[name].get("state") == "RUNNING":
            return {"ok": False, "reason": f"{name} już trwa"}
        status_file = kronos_dir() / f"{name}_status.json"
        try:
            status_file.unlink()
        except OSError:
            pass
        job = {"state": "RUNNING", "message": "start", "step": 0, "total": None, "log": [], "started_at": iso(utcnow()), "result": None,
               "status_file": str(status_file), "updated_at": iso(utcnow())}
        self.jobs[name] = job
        if name == "install":
            self._kill()

        def run():
            logf = paths.logs_dir() / f"kronos_{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
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

        threading.Thread(target=run, name=f"kronos-{name}", daemon=True).start()
        return {"ok": True, "job": name}

    def start_install(self, cuda: str | None = None) -> dict:
        argv = [sys.executable, str(paths.ROOT_DIR / "tools" / "kronos_setup.py"), "--root", str(paths.ROOT_DIR), "--weights-dir", str(self.weights_dir())]
        if cuda:
            argv += ["--cuda", cuda]

        def done(ok, job):
            self.retry_at = 0.0
            self.backoff = 30.0
            self.applog.info("KRONOS", "INSTALL", f"Instalacja Kronos: {'OK' if ok else 'BŁĄD ' + str(job.get('code'))}.")
        return self._run_job_proc("install", argv, on_done=done)

    def start_verify(self, reference: bool = True) -> dict:
        s = self.settings.get()
        py = find_python(s)
        if not py:
            return {"ok": False, "reason": STATUS_PL["NOT_INSTALLED"]}
        env = dict(os.environ, PYTHONPATH=str(paths.ROOT_DIR / "backend"), PYTHONIOENCODING="utf-8", HF_HUB_OFFLINE="1")
        argv = [py, "-m", "kronos_runtime.install", "verify", "--weights-dir", str(self.weights_dir()), "--device", s.device]
        if reference:
            argv.append("--reference")
        return self._run_job_proc("verify", argv, env=env)

    def job(self, name: str) -> dict | None:
        j = self.jobs.get(name)
        return dict(j) if j else None

    def start_validation(self, inst: str, tf: str, max_origins: int = 300) -> dict:
        """Walk-forward on the user's bars in a background thread with its OWN model process (live forecasts keep running)."""
        from . import validation as V
        cur = self.jobs.get("validation")
        if cur and cur.get("state") == "RUNNING":
            return {"ok": False, "reason": "walidacja już trwa"}
        job = {"state": "RUNNING", "message": f"walidacja {inst} {tf}: start", "step": 0, "total": None, "started_at": iso(utcnow()),
               "updated_at": iso(utcnow()), "instrument": inst, "timeframe": tf, "report_id": None}
        self.jobs["validation"] = job

        def prog(i, n):
            job.update(step=i, total=n, message=f"walidacja {inst} {tf}: {i}/{n} punktów startu", updated_at=iso(utcnow()))

        def run():
            try:
                rep = V.run(self, inst, tf, max_origins=max_origins, progress=prog)
                job.update(state="DONE" if rep.get("status") == "DONE" else "FAILED", report_id=rep.get("report_id"),
                           message=(rep.get("verdict") or {}).get("reason"), code=None if rep.get("status") == "DONE" else rep.get("status"),
                           updated_at=iso(utcnow()))
            except Exception as exc:  # noqa: BLE001
                log.exception("kronos validation")
                job.update(state="FAILED", code="EXCEPTION", message=f"{type(exc).__name__}: {exc}"[:300], updated_at=iso(utcnow()))
            self._publish()

        threading.Thread(target=run, name="kronos-validation", daemon=True).start()
        return {"ok": True, "job": "validation"}

    # ================================================================== strategy use
    def set_strategy_use(self, strategy: str, use: str, *, timeframe: str | None = None, confirm: bool = False) -> dict:
        from . import validation as V
        s = self.settings.get()
        if strategy not in s.strategy_use:
            return {"ok": False, "reason": "INVALID_STRATEGY"}
        cur = s.strategy_use[strategy]
        tf = timeframe or cur.timeframe
        if use == "OBSERVE":
            self.settings.update({"strategy_use": {strategy: {"use": "OBSERVE", "timeframe": tf, "validation_report": None, "confirmed_at": None}}})
            return {"ok": True, "use": "OBSERVE"}
        if use != "REQUIRED":
            return {"ok": False, "reason": "INVALID_USE"}
        if not confirm:
            return {"ok": False, "reason": "CONFIRMATION_REQUIRED: włączenie Kronosa jako obowiązkowego warunku wymaga świadomego potwierdzenia"}
        insts = s.instruments
        reps = {i: V.latest_report(i, tf) for i in insts}
        missing = [i for i, r in reps.items() if not (r and r.get("verdict", {}).get("positive"))]
        if missing:
            why = "; ".join(f"{i} {tf}: " + ((reps[i] or {}).get("verdict", {}).get("reason") or "brak raportu walidacji walk-forward") for i in missing)
            return {"ok": False, "reason": "VALIDATION_REQUIRED: " + why}
        ids = ",".join(r["report_id"] for r in reps.values())
        self.settings.update({"strategy_use": {strategy: {"use": "REQUIRED", "timeframe": tf, "validation_report": ids, "confirmed_at": iso(utcnow())}}})
        self.applog.info("KRONOS", "STRATEGY_USE", f"{strategy}: Kronos {tf} ustawiony jako obowiązkowy warunek (raporty {ids}).")
        return {"ok": True, "use": "REQUIRED", "reports": ids}


def _mean(it) -> float | None:
    xs = [float(x) for x in it if x is not None]
    return sum(xs) / len(xs) if xs else None
