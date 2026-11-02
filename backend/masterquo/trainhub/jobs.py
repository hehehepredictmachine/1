"""Training Center job queue (PMW-TH-JOBS-1).

* Persistent jobs (data/trainhub/jobs.sqlite): QUEUED -> RUNNING -> SUCCEEDED / FAILED / CANCELLED (INTERRUPTED after a restart).
* One job at a time (resource limit). An identical queued / running job is returned instead of a duplicate.
* EXPORT runs in the bot process on the bridge (MT5 history requests at low priority in the MT5 worker queue - the panel and the
  live analysis keep running). DATASET / TRAIN / EVALUATE / FULL run in a SEPARATE PROCESS (python -m masterquo.trainhub.worker)
  with a lower OS priority, thread limits and (Windows) a memory cap - training never runs in the panel / inference process.
* Cancel: the job is flagged; an export stops after the current chunk (resumable), a training process is terminated.
* Nothing here activates a model, changes trading settings or sends orders.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from ..marketdata.store import iso

KINDS = ("EXPORT", "DATASET", "TRAIN", "EVALUATE", "FULL")
KIND_PL = {"EXPORT": "Eksport danych", "DATASET": "Przygotowanie datasetu", "TRAIN": "Trening + ocena + zapis", "EVALUATE": "Ocena wersji",
           "FULL": "Cały proces"}
STATUS_PL = {"QUEUED": "w kolejce", "RUNNING": "w toku", "SUCCEEDED": "zakończone", "FAILED": "błąd", "CANCELLED": "anulowane",
             "INTERRUPTED": "przerwane (restart)"}
SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, kind TEXT, instrument TEXT, params TEXT, status TEXT, stage TEXT, progress REAL,
  created_at REAL, started_at REAL, finished_at REAL, pid INTEGER, cancel INTEGER DEFAULT 0, result TEXT, error TEXT, log TEXT, dedup TEXT);
CREATE INDEX IF NOT EXISTS ix_jobs_status ON jobs(status, created_at);
"""


def db_path() -> Path:
    from .registry import root
    p = root() / "jobs.sqlite"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


class _Res:
    def __init__(self, rows: list, rowcount: int):
        self.rows, self.rowcount = rows, rowcount

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class SafeDB:
    """One SQLite connection shared by the API threads and the queue thread: every statement runs under one lock and its rows are
    fetched inside it (a shared connection used concurrently raises 'bad parameter or other API misuse')."""

    def __init__(self, conn: sqlite3.Connection):
        self.c, self.lock = conn, threading.RLock()

    def execute(self, sql: str, params=()) -> _Res:
        with self.lock:
            cur = self.c.execute(sql, params)
            return _Res(cur.fetchall() if cur.description else [], cur.rowcount)


def connect(path: Path | None = None) -> sqlite3.Connection:
    c = sqlite3.connect(str(path or db_path()), timeout=30, isolation_level=None, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript(SCHEMA)
    return c


def update(c: sqlite3.Connection, jid: str, **kw) -> None:
    if not kw:
        return
    cols = ", ".join(f"{k}=?" for k in kw)
    vals = [json.dumps(v, default=str, ensure_ascii=False) if k in ("result", "params") else v for k, v in kw.items()]
    c.execute(f"UPDATE jobs SET {cols} WHERE id=?", (*vals, jid))


def row(c: sqlite3.Connection, jid: str) -> dict | None:
    r = c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
    return public(dict(r)) if r else None


def public(r: dict) -> dict:
    out = dict(r)
    for k in ("params", "result"):
        try:
            out[k] = json.loads(out[k]) if out.get(k) else None
        except ValueError:
            pass
    out["kind_pl"] = KIND_PL.get(out["kind"], out["kind"])
    out["status_pl"] = STATUS_PL.get(out["status"], out["status"])
    for k in ("created_at", "started_at", "finished_at"):
        out[k + "_iso"] = iso(out[k]) if out.get(k) else None
    if out.get("started_at"):
        out["duration_s"] = round((out.get("finished_at") or time.time()) - out["started_at"], 1)
    out.pop("dedup", None)
    return out


class TrainingCenter:
    def __init__(self, cfg_store, bridge, *, bus=None, log=None, poll_s: float = 0.5, python: str | None = None):
        self.cfg_store, self.bridge, self.bus, self.log, self.poll_s = cfg_store, bridge, bus, log, poll_s
        self.python = python or sys.executable
        self.db = SafeDB(connect())
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self.proc: subprocess.Popen | None = None
        self.current: str | None = None
        n = self.db.execute("UPDATE jobs SET status='INTERRUPTED', finished_at=?, error='przerwane – bot został zatrzymany w trakcie' "
                            "WHERE status IN ('RUNNING')", (time.time(),)).rowcount
        self.recovered = n

    # ------------------------------------------------------------------ api
    def submit(self, kind: str, instrument: str, params: dict | None = None) -> dict:
        kind = kind.upper()
        if kind not in KINDS:
            raise ValueError(f"nieznany rodzaj zadania {kind}")
        inst = instrument.upper()
        if inst not in ("XAUUSD", "BTC"):
            raise ValueError("instrument XAUUSD albo BTC (trenowane i oceniane osobno)")
        params = dict(params or {})
        dedup = json.dumps([kind, inst, params], sort_keys=True, default=str)
        with self._lock:
            ex = self.db.execute("SELECT id FROM jobs WHERE dedup=? AND status IN ('QUEUED','RUNNING')", (dedup,)).fetchone()
            if ex:
                return {**row(self.db, ex["id"]), "deduplicated": True}
            jid = f"TJ-{time.strftime('%Y%m%dT%H%M%S', time.gmtime())}-{uuid.uuid4().hex[:6]}"
            from .registry import root
            logp = root() / "logs" / f"{jid}.log"
            logp.parent.mkdir(parents=True, exist_ok=True)
            self.db.execute("INSERT INTO jobs(id, kind, instrument, params, status, stage, progress, created_at, log, dedup) VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (jid, kind, inst, json.dumps(params, default=str), "QUEUED", "czeka w kolejce", 0.0, time.time(), str(logp), dedup))
        self.start()
        self._wake.set()
        self._publish(jid)
        return {**row(self.db, jid), "deduplicated": False}

    def list(self, limit: int = 50) -> list[dict]:
        return [public(dict(r)) for r in self.db.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (int(limit),)).fetchall()]

    def get(self, jid: str) -> dict | None:
        return row(self.db, jid)

    def log_tail(self, jid: str, lines: int = 200) -> str:
        r = self.get(jid)
        if not r or not r.get("log") or not Path(r["log"]).exists():
            return ""
        txt = Path(r["log"]).read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(txt[-lines:])

    def cancel(self, jid: str) -> dict:
        with self._lock:
            r = self.get(jid)
            if r is None:
                raise KeyError(jid)
            if r["status"] == "QUEUED":
                update(self.db, jid, status="CANCELLED", finished_at=time.time(), stage="anulowane przed startem", cancel=1)
            elif r["status"] == "RUNNING":
                update(self.db, jid, cancel=1, stage="anulowanie…")
                if self.current == jid and self.proc is not None and self.proc.poll() is None:
                    self._kill(self.proc)
        self._publish(jid)
        return self.get(jid)

    # ------------------------------------------------------------------ worker
    def start(self) -> None:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._loop, name="trainhub-jobs", daemon=True)
                self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self.proc is not None and self.proc.poll() is None:
            self._kill(self.proc)

    def _loop(self) -> None:
        while not self._stop.is_set():
            r = self.db.execute("SELECT id FROM jobs WHERE status='QUEUED' ORDER BY created_at LIMIT 1").fetchone()
            if r is None:
                self._wake.wait(2.0)
                self._wake.clear()
                continue
            jid = r["id"]
            try:
                self._run(jid)
            except Exception as exc:  # noqa: BLE001 - a failing job never stops the queue
                update(self.db, jid, status="FAILED", error=f"{type(exc).__name__}: {exc}"[:600], finished_at=time.time())
                self._log(jid, f"[BŁĄD] {type(exc).__name__}: {exc}")
            self.current = None
            self._publish(jid)

    def _log(self, jid: str, msg: str) -> None:
        r = self.get(jid)
        if r and r.get("log"):
            with open(r["log"], "a", encoding="utf-8") as f:
                f.write(f"{iso(time.time())} {msg}\n")

    def _cancelled(self, jid: str) -> bool:
        r = self.db.execute("SELECT cancel FROM jobs WHERE id=?", (jid,)).fetchone()
        return bool(r and r["cancel"])

    def _run(self, jid: str) -> None:
        job = self.get(jid)
        self.current = jid
        update(self.db, jid, status="RUNNING", started_at=time.time(), stage="start", progress=0.01)
        self._publish(jid)
        params = job["params"] or {}
        result: dict = {}
        if job["kind"] in ("EXPORT", "FULL") and params.get("export", True):
            result["export"] = self._export(jid, job["instrument"], params)
            if result["export"].get("status") != "COMPLETE":
                st = "CANCELLED" if result["export"].get("status") == "CANCELLED" else "FAILED"
                update(self.db, jid, status=st, result=result, error=result["export"].get("reason"), finished_at=time.time(),
                       stage="eksport przerwany – ponowienie wznowi od pobranych partii")
                return
            if job["kind"] == "EXPORT":
                update(self.db, jid, status="SUCCEEDED", result=result, progress=1.0, finished_at=time.time(), stage="eksport zakończony")
                return
        update(self.db, jid, result=result)
        self._child(jid)

    def _export(self, jid: str, inst: str, params: dict) -> dict:
        from ..marketdata import export as EX
        from ..marketdata.sources import BridgeSource
        from ..marketdata.store import Store
        cfg = self.cfg_store.get()
        m = cfg.assets.mappings.get(inst)
        sym = m.broker_symbol if m and m.broker_symbol else None
        if not sym:
            return {"status": "FAILED", "reason": f"brak symbolu brokera dla {inst} – ustaw mapowanie w Ustawieniach"}
        update(self.db, jid, stage=f"eksport {inst} ({sym})")
        self._log(jid, f"Eksport {inst} {sym} tryb={params.get('mode', 'incremental')} interwały={params.get('timeframes') or 'M1,M5,M15,M30'}")

        def prog(p):
            update(self.db, jid, progress=round(0.05 + 0.45 * p["chunk"] / max(1, p["chunks"]), 3),
                   stage=f"eksport {p['tf']}: partia {p['chunk']}/{p['chunks']} (+{p['rows_added']} świec)")
            self._log(jid, f"eksport {p['tf']} {p['window_utc'][0]} – {p['window_utc'][1]}: +{p['rows_added']}")
        try:
            res = EX.run(BridgeSource(self.bridge), Store(), inst, sym, timeframes=params.get("timeframes") or EX.EXPORT_TFS,
                         mode=params.get("mode", "incremental"), start=params.get("start"), end=params.get("end"),
                         lookback_days=float(params.get("lookback_days") or 90), cfg=cfg, progress=prog, cancel=lambda: self._cancelled(jid))
        except EX.ExportBusy as exc:
            return {"status": "FAILED", "reason": str(exc)}
        except Exception as exc:  # noqa: BLE001
            return {"status": "FAILED", "reason": f"{type(exc).__name__}: {exc}"[:400]}
        self._log(jid, f"Eksport: {res['status']} {json.dumps({tf: {k: v[k] for k in ('added', 'duplicates', 'conflicts', 'invalid')} for tf, v in res['timeframes'].items()})}")
        return {k: v for k, v in res.items() if k != "source"}

    def _child(self, jid: str) -> None:
        from .registry import root
        job = self.get(jid)
        th = str(max(1, (os.cpu_count() or 2) // 2))
        env = dict(os.environ, PYTHONIOENCODING="utf-8", OMP_NUM_THREADS=th, MKL_NUM_THREADS=th, OPENBLAS_NUM_THREADS=th, MQ_TRAINING="1")
        from .. import paths
        env["PYTHONPATH"] = str(paths.ROOT_DIR / "backend")
        env["MASTERQUO_DATA_DIR"] = str(paths.data_dir())
        kw: dict = {}
        if os.name == "nt":
            kw["creationflags"] = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        else:
            kw["preexec_fn"] = lambda: os.nice(10)
        logf = open(job["log"], "a", encoding="utf-8")
        try:
            self.proc = subprocess.Popen([self.python, "-m", "masterquo.trainhub.worker", str(db_path()), jid], env=env, stdout=logf,
                                         stderr=subprocess.STDOUT, cwd=str(paths.ROOT_DIR / "backend"), **kw)
            try:
                from ..training.core import _job_limit
                _job_limit(self.proc, int(os.environ.get("MQ_RAM_BUDGET_MB") or 6144))
            except Exception:  # noqa: BLE001
                pass
            update(self.db, jid, pid=self.proc.pid)
            while self.proc.poll() is None:
                if self._stop.wait(self.poll_s):
                    self._kill(self.proc)
                    break
                if self._cancelled(jid):
                    self._kill(self.proc)
                self._publish(jid, quiet=True)
            rc = self.proc.returncode
        finally:
            logf.close()
        r = self.get(jid)
        if r["status"] == "RUNNING":                          # the child did not record its end (killed / crashed)
            if self._cancelled(jid):
                update(self.db, jid, status="CANCELLED", finished_at=time.time(), stage="anulowane – proces treningu zatrzymany")
            else:
                update(self.db, jid, status="FAILED", finished_at=time.time(), error=f"proces treningu zakończył się kodem {rc}")
        self.proc = None

    @staticmethod
    def _kill(p: subprocess.Popen) -> None:
        try:
            p.terminate()
            p.wait(timeout=10)
        except Exception:  # noqa: BLE001
            try:
                p.kill()
            except Exception:  # noqa: BLE001
                pass

    def _publish(self, jid: str, quiet: bool = False) -> None:
        if self.bus is None:
            return
        try:
            r = self.get(jid)
            self.bus.publish("trainhub", {"job_id": jid, "status": r and r["status"], "progress": r and r["progress"], "stage": r and r["stage"]})
        except Exception:  # noqa: BLE001
            pass

    def status(self) -> dict:
        r = self.get(self.current) if self.current else None
        return {"running": r, "queued": self.db.execute("SELECT COUNT(*) n FROM jobs WHERE status='QUEUED'").fetchone()["n"],
                "recovered_interrupted": self.recovered, "process_isolated": True,
                "note": "trening w osobnym procesie o niższym priorytecie; jedno zadanie naraz"}
