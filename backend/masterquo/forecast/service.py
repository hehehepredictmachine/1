"""SHADOW candle analytics and price forecasts (gold_candles) inside the bot - observation only.

Data path: the bot's OWN closed M5/M30 bars (MarketBridge, same session, same UTC conversion as the export used for
training) -> JSON lines -> isolated worker process (.venv_candles: pandas / scikit-learn pinned by the reference module)
-> report. The worker never opens MT5; this service never calls initialize()/shutdown(). The model is loaded once in the
worker; analysis runs only after a NEW closed M5 (M30 of the same moment is part of the same bar snapshot). Any failure
gives a readable status (NO_CANDLE_ENV, NO_MODEL, WARMUP, STALE_DATA, CONTRACT_MISMATCH, FORECAST_UNAVAILABLE) - never a
crash of the monitor or of position handling, and never an order: execution_permission is always false.

Every SHADOW forecast is stored BEFORE its outcome is known (forecast_shadow, unique per run/time/horizon - restarts do not
duplicate) and scored later from the bot's closed M5 bars of the exact target time."""
from __future__ import annotations

import json
import math
import os
import subprocess
import threading
import time
from datetime import timedelta
from pathlib import Path

from .. import paths
from ..timeutil import iso, parse_iso, utcnow
from . import double_retest

STATUS_PL = {"DISABLED": "wyłączone w konfiguracji", "NO_CANDLE_ENV": "brak środowiska .venv_candles (uruchom 10_PROGNOZY_INSTALUJ.bat)",
             "STARTING": "uruchamianie procesu analityki", "NO_MODEL": "brak wytrenowanego, zgodnego modelu",
             "WARMUP": "za mało zamkniętych świec do cech (warmup) albo niespójny kontekst M30",
             "STALE_DATA": "dane M5 nieaktualne", "CONTRACT_MISMATCH": "model niezgodny z symbolem / tick size / kodem cech – wymagany nowy trening",
             "MODEL_FROM_FUTURE": "model wytrenowany na danych późniejszych niż analizowana chwila", "SYMBOL_SPEC": "symbol nie potwierdzony jako XAU/USD",
             "FORECAST_UNAVAILABLE": "analityka niedostępna (błąd procesu) – ochrona pozycji działa bez zmian", "SHADOW": "prognoza obserwacyjna SHADOW",
             "NO_DATA": "brak zamkniętych świec M5/M30 z MT5"}
CLASSES = ("DOWN", "FLAT", "UP")


def candle_python(cfg) -> str | None:
    cands = [os.environ.get("MQ_CANDLES_PYTHON"), cfg.forecast.python_path,
             str(paths.ROOT_DIR / ".venv_candles" / "Scripts" / "python.exe"), str(paths.ROOT_DIR / ".venv_candles" / "bin" / "python")]
    return next((c for c in cands if c and Path(c).exists()), None)


class ForecastService:
    def __init__(self, cfg_store, bridge, db, bus, log):
        self.cfg_store, self.bridge, self.db, self.bus, self.log = cfg_store, bridge, db, bus, log
        self.proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_key: str | None = None
        self.retry_at = 0.0
        self.machine = double_retest.DoubleRetest()
        self.state: dict = {"status": "STARTING", "status_pl": STATUS_PL["STARTING"], "mode": "SHADOW", "execution_permission": False,
                            "report": None, "model": None, "setup_v2": None, "updated_at": None, "latency_ms": None, "worker": None}

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="forecast-shadow", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._kill()

    def reload(self) -> None:
        """New model activated: the worker drops its cache; the next closed M5 uses the new version (never mid-bar)."""
        try:
            self._ask({"cmd": "reload"}, 10)
        except Exception:
            self._kill()
        self.last_key = None

    def _kill(self) -> None:
        p, self.proc = self.proc, None
        if p and p.poll() is None:
            try:
                p.stdin.write('{"cmd":"quit"}\n')
                p.stdin.flush()
                p.wait(timeout=3)
            except Exception:
                p.kill()

    def _spawn(self) -> bool:
        cfg = self.cfg_store.get()
        py = candle_python(cfg)
        if not py:
            self._set("NO_CANDLE_ENV", None)
            return False
        env = dict(os.environ, PYTHONPATH=str(paths.ROOT_DIR / "backend"), MASTERQUO_DATA_DIR=str(paths.data_dir()), PYTHONIOENCODING="utf-8")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.proc = subprocess.Popen([py, "-m", "gold_candles_runtime.worker"], cwd=str(paths.ROOT_DIR / "backend"), env=env, text=True,
                                     encoding="utf-8", stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=1,
                                     creationflags=flags)
        hello = self._ask({"cmd": "hello"}, 60)
        self.state["worker"] = {"python": py, "runtime": hello.get("runtime"), "versions": hello.get("versions"), "pid": self.proc.pid}
        self.log.info("FORECAST", "WORKER_STARTED", f"Analityka świec SHADOW: proces {self.proc.pid} ({py}).")
        return True

    def _ask(self, req: dict, timeout: float) -> dict:
        with self._lock:
            if not self.proc or self.proc.poll() is not None:
                raise RuntimeError("WORKER_NOT_RUNNING")
            self.proc.stdin.write(json.dumps(req, allow_nan=False) + "\n")
            self.proc.stdin.flush()
            box: dict = {}
            th = threading.Thread(target=lambda: box.update(line=self.proc.stdout.readline()), daemon=True)
            th.start()
            th.join(timeout)
            if th.is_alive() or not box.get("line"):
                self._kill()
                raise RuntimeError("WORKER_TIMEOUT_OR_EXIT")
            return json.loads(box["line"])

    def _set(self, status: str, reason: str | None, **kw) -> None:
        self.state.update(status=status, status_pl=STATUS_PL.get(status, status), reason=reason, updated_at=iso(utcnow()), **kw)
        self.bus.publish("forecast", self.public())

    def public(self) -> dict:
        return {k: v for k, v in self.state.items()}

    # ------------------------------------------------------------ main loop
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:                    # never let analytics affect the bot
                self._set("FORECAST_UNAVAILABLE", f"{type(exc).__name__}: {exc}"[:300])
                self._kill()
                self.retry_at = time.monotonic() + 30
            self._stop.wait(2.0)

    def tick(self) -> None:
        cfg = self.cfg_store.get()
        if not cfg.forecast.enabled:
            if self.state["status"] != "DISABLED":
                self._kill()
                self._set("DISABLED", None)
            return
        m5 = [b for b in self.bridge.bars("M5", cfg.forecast.m5_bars, include_forming=False) if b.get("open_utc")]
        m30 = [b for b in self.bridge.bars("M30", cfg.forecast.m30_bars, include_forming=False) if b.get("open_utc")]
        if not m5 or not m30:
            if self.state["status"] != "NO_DATA":
                self._set("NO_DATA", "brak zamkniętych świec z bieżącej sesji MT5")
            return
        key = f"{m5[-1]['open_utc']}|{m30[-1]['open_utc']}|{m5[-1].get('revision')}"
        self.score_due(m5)
        if key == self.last_key:
            return
        if (not self.proc or self.proc.poll() is not None):
            if time.monotonic() < self.retry_at:
                return
            if not self._spawn():
                self.retry_at = time.monotonic() + 60
                return
        info = self.bridge.symbol_info or {}
        if info.get("currency_base") not in (None, "XAU") or info.get("currency_profit") not in (None, "USD"):
            self._set("SYMBOL_SPEC", f"{info.get('currency_base')}/{info.get('currency_profit')}")
            self.last_key = key
            return
        tick = float(info.get("trade_tick_size") or 0) or 0.01
        q = self.bridge.quote_status() or {}
        quote = {"bid": q.get("bid"), "ask": q.get("ask"), "time_utc": q.get("time_utc"), "age_seconds": q.get("age_seconds"),
                 "valid": bool(q.get("bid") and q.get("ask") and (q.get("age_seconds") or 99) <= 2 and q["bid"] <= q["ask"])}
        as_of = iso(utcnow())
        req = {"cmd": "analyze", "symbol": cfg.mt5.symbol, "tick_size": tick, "as_of": as_of, "quote": quote, "flags_tail": len(m5),
               "m5": [{k: b[k] for k in ("open_utc", "o", "h", "l", "c", "tv")} for b in m5],
               "m30": [{k: b[k] for k in ("open_utc", "o", "h", "l", "c", "tv")} for b in m30]}
        t0 = time.perf_counter()
        ans = self._ask(req, cfg.forecast.request_timeout_seconds)
        rt_ms = round((time.perf_counter() - t0) * 1000, 1)
        self.last_key = key
        status = ans.get("status") or "FORECAST_UNAVAILABLE"
        setup = self.machine.update(m5, m30, {f["time_open_utc"]: f["names"] for f in ans.get("flags_tail") or []}, tick)
        self._set(status, ans.get("reason") or ans.get("error"), report=ans.get("report"), model=ans.get("model"), setup_v2=setup,
                  latency_ms={"worker": ans.get("latency_ms"), "round_trip": rt_ms}, worker_peak_rss_mb=ans.get("peak_rss_mb"),
                  bars={"m5_last_open_utc": m5[-1]["open_utc"], "m30_last_open_utc": m30[-1]["open_utc"], "m5": len(m5), "m30": len(m30)},
                  shadow=self.shadow_summary())
        if status == "SHADOW":
            self.record(ans)

    # ------------------------------------------------------------ shadow log + scoring
    def record(self, ans: dict) -> None:
        rep, model = ans.get("report") or {}, ans.get("model") or {}
        fc = rep.get("forecast") or {}
        run_id = model.get("run_id")
        if not run_id:
            return
        hs = model.get("horizon_status") or {}
        for h in (fc.get("probabilities") or {}).values():
            p = h["probabilities"]
            q = h.get("close_price_quantiles") or {}
            self.db.execute("""INSERT OR IGNORE INTO forecast_shadow(created_at, run_id, feature_time_utc, horizon_minutes, target_time_utc, close_now,
                               neutral_band, p_down, p_flat, p_up, q10, q50, q90, session_check, horizon_status, outcome_status)
                               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (iso(utcnow()), run_id, fc["feature_time_utc"], h["horizon_minutes"], h["target_time_utc"], rep.get("chart_close"),
                             h["neutral_band_price"], p["DOWN"], p["FLAT"], p["UP"], q.get("q10"), q.get("q50"), q.get("q90"), h.get("session_check"),
                             hs.get(str(h["horizon_minutes"] // 5)), "PENDING"))

    def score_due(self, m5: list[dict]) -> None:
        """Outcome = close of the M5 bar that CLOSES exactly at target time, with every M5 between present (continuous)."""
        if not m5:
            return
        closes = {parse_iso(b["open_utc"]) + timedelta(minutes=5): b["c"] for b in m5}
        last_close = max(closes)
        rows = self.db.query("SELECT * FROM forecast_shadow WHERE outcome_status='PENDING' AND target_time_utc <= ? LIMIT 200",
                             (iso(last_close),))
        for r in rows:
            t, tgt = parse_iso(r["feature_time_utc"]), parse_iso(r["target_time_utc"])
            steps = [t + timedelta(minutes=5 * k) for k in range(1, r["horizon_minutes"] // 5 + 1)]
            if min(closes) > t:
                st, close, cls = "OUT_OF_BUFFER", None, None
            elif all(s in closes for s in steps):
                close = closes[tgt]
                d = close - r["close_now"]
                cls = "UP" if d > r["neutral_band"] else "DOWN" if d < -r["neutral_band"] else "FLAT"
                st = "SCORED"
            else:
                st, close, cls = "NO_CONTINUOUS_DATA", None, None
            self.db.execute("UPDATE forecast_shadow SET outcome_close=?, outcome_class=?, outcome_status=?, scored_at=? WHERE id=?",
                            (close, cls, st, iso(utcnow()), r["id"]))

    def shadow_summary(self) -> dict:
        out = {}
        for h in (5, 15, 30):
            rows = self.db.query("SELECT * FROM forecast_shadow WHERE horizon_minutes=? AND outcome_status='SCORED' ORDER BY id DESC LIMIT 2000", (h,))
            pend = self.db.one("SELECT COUNT(*) AS n FROM forecast_shadow WHERE horizon_minutes=? AND outcome_status='PENDING'", (h,))["n"]
            if not rows:
                out[str(h)] = {"scored": 0, "pending": pend}
                continue
            br = ll = cov = 0.0
            for r in rows:
                p = [r["p_down"], r["p_flat"], r["p_up"]]
                y = CLASSES.index(r["outcome_class"])
                br += sum((p[i] - (1.0 if i == y else 0.0)) ** 2 for i in range(3))
                ll += -math.log(max(p[y], 1e-12))
                if r["q10"] is not None:
                    cov += 1.0 if r["q10"] <= r["outcome_close"] <= r["q90"] else 0.0
            n = len(rows)
            out[str(h)] = {"scored": n, "pending": pend, "brier": round(br / n, 4), "log_loss": round(ll / n, 4), "q10_q90_coverage": round(cov / n, 3),
                           "days": len({r["feature_time_utc"][:10] for r in rows}),
                           "note": "ocena SHADOW na żywo – nakładające się prognozy nie są niezależnymi transakcjami"}
        return out

    def recent(self, limit: int = 100) -> list[dict]:
        return self.db.query("SELECT * FROM forecast_shadow ORDER BY id DESC LIMIT ?", (limit,))

    def registry(self) -> dict:
        p = paths.data_dir() / "forecast" / "registry.json"
        try:
            reg = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"active": None, "runs": {}, "note": "brak rejestru – trening nie był uruchomiony na tym komputerze"}
        return {"active": reg.get("active"), "history": reg.get("history"),
                "runs": {k: {x: v.get(x) for x in ("created_at_utc", "data_kind", "overall_status", "horizon_status", "knowledge_cutoff_utc",
                                                   "train_range_utc", "tick_size", "m30_source", "dataset_sha256", "contract_hash")}
                         for k, v in sorted(reg.get("runs", {}).items())[-10:]}}

    def training_status(self) -> dict:
        h = sorted((paths.data_dir() / "forecast" / "history").glob("*/source_metadata.json"))
        st = paths.data_dir() / "forecast" / "TRAINING_STATUS.json"
        return {"history_exports": [str(x.parent.name) for x in h[-5:]],
                "latest_export": json.loads(h[-1].read_text(encoding="utf-8")) if h else None,
                "status_file": json.loads(st.read_text(encoding="utf-8")) if st.exists() else None,
                "blocked": None if h else "BLOCKED_NO_REAL_DATA – brak eksportu historii (11_EKSPORT_HISTORII_XAUUSD.bat przy działającym MT5)"}
