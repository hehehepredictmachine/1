"""Persistent Studio queue (PMW-STUDIO-QUEUE-1) in sqlite: one job = one task + one operation + one package. Sequential: at most ONE
running job, additionally guarded by the cross-process export lock (other Studio instances, the bot's export). Dedup of identical
QUEUED / RUNNING submissions, reorder, delete of QUEUED, pause (between chunks / stages), cancel, resume, heartbeat, recovery after a
crash (RUNNING with a dead worker -> INTERRUPTED, resumable from the last committed stage)."""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from . import settings as S
from .lock import Lock, _alive

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (job_id TEXT PRIMARY KEY, task_key TEXT, op TEXT, source TEXT, profile TEXT, state TEXT, stage TEXT,
  progress TEXT, package TEXT, error TEXT, order_idx REAL, created_at REAL, started_at REAL, finished_at REAL, pid INTEGER, heartbeat REAL,
  pause INTEGER DEFAULT 0, cancel INTEGER DEFAULT 0, run_id TEXT, depends_on TEXT);
"""
ACTIVE = ("QUEUED", "RUNNING", "EXPORTING", "VALIDATING_RAW", "BUILDING_DATASET", "VALIDATING_DATASET", "TRAINING", "EVALUATING", "PACKAGING")
log = logging.getLogger(__name__)


def _dedup_source(source: dict) -> str:
    """1.46: the source WITHOUT the frozen cutoff (app.source_for stamps int(time.time()) into every submission - two submissions of the same
    task a second apart never matched, so the documented QUEUED / RUNNING dedup never worked through the API)."""
    return json.dumps({k: v for k, v in (source or {}).items() if k != "cutoff"}, sort_keys=True)


class Queue:
    def __init__(self, db_path: Path | None = None, *, lock_path: Path | None = None, python: str | None = None, env: dict | None = None):
        self.path = Path(db_path or (S.data_dir() / "queue.sqlite"))
        self.db = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None, timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        self.lock = Lock(lock_path or S.export_lock_path(), app="PepeTrainingStudio")
        self.python = python or sys.executable
        self.env = env or {}
        self._mu = threading.RLock()
        self.proc: subprocess.Popen | None = None
        self.current: str | None = None
        self._stop = threading.Event()
        self.recover()

    def submit(self, task_key: str, op: str, *, source: dict, profile: str = "smoke") -> dict:
        with self._mu:
            rows = self.db.execute(f"SELECT job_id, state, source FROM jobs WHERE task_key=? AND op=? AND state IN ({','.join('?' * len(ACTIVE))}) "
                                   "ORDER BY order_idx", (task_key, op, *ACTIVE)).fetchall()
            want = _dedup_source(source)
            dup = next((r for r in rows if _dedup_source(json.loads(r["source"] or "{}")) == want), None)   # 1.46: cutoff ignored
            if dup:
                return {"ok": True, "deduplicated": True, "job_id": dup["job_id"], "state": dup["state"]}
            jid = "JOB-" + uuid.uuid4().hex[:10]
            mx = self.db.execute("SELECT COALESCE(MAX(order_idx), 0) m FROM jobs").fetchone()["m"]
            self.db.execute("INSERT INTO jobs(job_id, task_key, op, source, profile, state, order_idx, created_at, run_id) VALUES (?,?,?,?,?,?,?,?,?)",
                            (jid, task_key, op, json.dumps(source, sort_keys=True), profile, "QUEUED", mx + 1, time.time(),
                             time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex[:6]))
            return {"ok": True, "job_id": jid, "state": "QUEUED"}

    def submit_many(self, task_keys: list[str], op: str, *, source: dict, profile: str = "smoke") -> list[dict]:
        return [self.submit(k, op, source=source, profile=profile) for k in task_keys]          # separate jobs, in the given order

    @staticmethod
    def _row(r) -> dict:
        d = dict(r)
        d["source"], d["progress"] = json.loads(d["source"] or "{}"), json.loads(d["progress"] or "{}")
        return d

    def jobs(self, limit: int = 200) -> list[dict]:
        # 1.46: QUEUED in queue order, then the running job, then the rest NEWEST first - 1.45.0 sorted finished jobs by order_idx ascending
        # (oldest first), so after `limit` jobs the running and the latest finished ones were cut off (UI showed neither).
        # One shared connection: every statement under _mu (1.45.0 read without it from the API thread pool and the queue thread at once ->
        # wrong / empty rows, sqlite InterfaceError).
        act = ",".join("?" * (len(ACTIVE) - 1))
        with self._mu:
            rows = self.db.execute(f"SELECT * FROM jobs ORDER BY CASE WHEN state='QUEUED' THEN 0 WHEN state IN ({act}) THEN 1 ELSE 2 END, "
                                   "CASE WHEN state='QUEUED' THEN order_idx END, COALESCE(finished_at, started_at, created_at) DESC, "
                                   "created_at DESC LIMIT ?", (*ACTIVE[1:], limit)).fetchall()
            return [self._row(r) for r in rows]

    def job(self, jid: str) -> dict | None:
        with self._mu:                                                       # 1.46: shared connection - see jobs()
            r = self.db.execute("SELECT * FROM jobs WHERE job_id=?", (jid,)).fetchone()
            return self._row(r) if r else None

    def move(self, jid: str, before: str | None) -> bool:
        with self._mu:
            j = self.job(jid)
            if not j or j["state"] != "QUEUED":
                return False
            if before:
                b = self.job(before)
                if not b:
                    return False
                # 1.46: halfway between `before` and the job right ahead of it - b-0.5 could tie with another job moved the same way
                # (the tie fell to created_at: A,C,B -> C before B twice gave C,A,B)
                prev = self.db.execute("SELECT MAX(order_idx) m FROM jobs WHERE order_idx < ? AND job_id NOT IN (?, ?)",
                                       (b["order_idx"], jid, before)).fetchone()["m"]
                idx = (b["order_idx"] + (prev if prev is not None else b["order_idx"] - 1)) / 2.0
            else:
                idx = self.db.execute("SELECT COALESCE(MAX(order_idx), 0) m FROM jobs").fetchone()["m"] + 1
            self.db.execute("UPDATE jobs SET order_idx=? WHERE job_id=?", (idx, jid))
            return True

    def delete(self, jid: str) -> bool:
        with self._mu:
            return self.db.execute("DELETE FROM jobs WHERE job_id=? AND state IN ('QUEUED','CANCELLED','PAUSED','INTERRUPTED')", (jid,)).rowcount > 0

    def pause(self, jid: str) -> bool:
        with self._mu:
            return self.db.execute("UPDATE jobs SET pause=1 WHERE job_id=?", (jid,)).rowcount > 0

    def cancel(self, jid: str) -> bool:
        with self._mu:
            n = self.db.execute("UPDATE jobs SET cancel=1 WHERE job_id=?", (jid,)).rowcount
            j = self.job(jid)
            if j and j["state"] == "QUEUED":
                self.db.execute("UPDATE jobs SET state='CANCELLED', finished_at=? WHERE job_id=?", (time.time(), jid))
            return n > 0

    def resume(self, jid: str) -> bool:
        with self._mu:
            return self.db.execute("UPDATE jobs SET state='QUEUED', pause=0, cancel=0, error=NULL WHERE job_id=? AND state IN "
                                   "('PAUSED','INTERRUPTED','FAILED')", (jid,)).rowcount > 0

    def transferred(self, jid: str, info: dict) -> None:
        """1.46: the transfer endpoint wrote to the shared connection without _mu (see jobs())."""
        with self._mu:
            self.db.execute("UPDATE jobs SET state='TRANSFERRED', progress=? WHERE job_id=?", (json.dumps(info, default=str), jid))

    def recover(self) -> None:
        with self._mu:
            for r in self.db.execute(f"SELECT job_id, pid FROM jobs WHERE state IN ({','.join('?' * (len(ACTIVE) - 1))})", ACTIVE[1:]).fetchall():
                if not _alive(r["pid"]):
                    self.db.execute("UPDATE jobs SET state='INTERRUPTED', error='proces zadania zakończył się bez wyniku (restart / awaria) – Wznów' "
                                    "WHERE job_id=?", (r["job_id"],))

    def next_job(self) -> dict | None:
        with self._mu:
            r = self.db.execute("SELECT job_id FROM jobs WHERE state='QUEUED' ORDER BY order_idx, created_at LIMIT 1").fetchone()
            return self.job(r["job_id"]) if r else None

    def busy(self) -> dict | None:
        """Who holds the export lock (another Studio / the bot export) when we do not."""
        if self.lock.held:
            return None
        o = self.lock.owner()
        return o if o and not self.lock.stale(o) else None

    def step(self) -> str:
        """One scheduler tick: poll the running job or start the next one."""
        with self._mu:
            if self.proc is not None:
                rc = self.proc.poll()
                if rc is None:
                    self.lock.heartbeat()
                    self.db.execute("UPDATE jobs SET heartbeat=? WHERE job_id=?", (time.time(), self.current))
                    return "RUNNING"
                j = self.job(self.current)
                if j and j["state"] in ACTIVE:
                    self.db.execute("UPDATE jobs SET state='FAILED', error=?, finished_at=? WHERE job_id=?",
                                    (f"proces zakończony kodem {rc} bez statusu", time.time(), self.current))
                self.proc, self.current = None, None
                self.lock.release()
            j = self.next_job()
            if not j:
                return "IDLE"
            ok, owner = self.lock.acquire(j["job_id"])
            if not ok:
                return f"BUSY:{(owner or {}).get('app')}:{(owner or {}).get('job')}"
            self.db.execute("UPDATE jobs SET state='RUNNING', started_at=?, pid=NULL, heartbeat=? WHERE job_id=?", (time.time(), time.time(), j["job_id"]))
            # 1.46: own session on POSIX (process group = the job's whole tree) so a cancel ends the stage children too - see _kill_tree()
            self.proc = subprocess.Popen([self.python, "-m", "masterquo.studio.jobrun", str(self.path), j["job_id"]], env=dict(os.environ, **self.env),
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0),
                                         start_new_session=os.name != "nt")
            try:
                from ..training.core import limit_child
                limit_child(self.proc)                           # arch146 I0069: the one RAM budget (Studio jobs had no cap)
            except Exception:  # noqa: BLE001, S110 - the cap is best effort
                pass
            self.current = j["job_id"]
            self.db.execute("UPDATE jobs SET pid=? WHERE job_id=?", (self.proc.pid, j["job_id"]))
            return "STARTED"

    def _kill_tree(self) -> None:
        """1.46: end the job process AND its children. 1.45.0 terminated only the jobrun process - the stage subprocesses (runner export
        with its own MT5 session up to 6 h, verify_loader, runner training steps) kept running orphaned while step() already released the
        export lock and started the next job next to them. Windows: taskkill /T (the process tree); POSIX: the job's own process group."""
        p = self.proc
        if p is None or p.poll() is not None:
            return
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False)
            elif os.getpgid(p.pid) == p.pid:                                 # started with start_new_session -> the group is the job tree
                import signal
                os.killpg(p.pid, signal.SIGTERM)
        except (OSError, subprocess.SubprocessError):
            pass
        if p.poll() is None:
            p.terminate()

    def kill_current_if_cancelled(self) -> None:
        if self.proc is None:
            return
        j = self.job(self.current)
        if j and j["cancel"] and self.proc.poll() is None:
            time.sleep(2)                                                     # the job checks cancel between chunks; then terminate
            with self._mu:
                if self.proc is not None and self.proc.poll() is None:
                    self._kill_tree()
                    self.db.execute("UPDATE jobs SET state='CANCELLED', finished_at=? WHERE job_id=?", (time.time(), self.current))

    def loop(self, period: float = 1.0) -> None:
        last = None
        while not self._stop.wait(period):
            try:
                self.kill_current_if_cancelled()
                self.step()
                last = None
            except Exception as exc:
                if repr(exc) != last:                                         # 1.46: logged (once per distinct error) instead of `pass`
                    last = repr(exc)
                    log.exception("studio queue tick failed")

    def start(self) -> None:
        threading.Thread(target=self.loop, name="studio-queue", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
