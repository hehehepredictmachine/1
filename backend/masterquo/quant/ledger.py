"""Quant ledger (PMW-QUANT-LEDGER-1): one row per setup candidate at the decision moment (features as available THEN, EventSpec,
snapshot generation), labelled later by the plan simulator on closed bars. Separate sqlite file under paths.data_dir()/quant - the
existing evaluation ledger is not modified. Rows of an unfinished horizon stay PENDING (never a loss / timeout)."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

VERSION = "PMW-QUANT-LEDGER-1"
SCHEMA = """
CREATE TABLE IF NOT EXISTS rows(
  row_id TEXT PRIMARY KEY, instrument TEXT, engine TEXT, strategy TEXT, direction TEXT, decision_ts REAL, task_hash TEXT, event_id TEXT,
  spec_json TEXT, features_json TEXT, snapshot_id TEXT, generation INTEGER, data_kind TEXT, matures_at REAL, status TEXT,
  label_json TEXT, resolve_ts REAL, y INTEGER, net_r REAL, created_at REAL);
CREATE INDEX IF NOT EXISTS rows_status ON rows(status, matures_at);
CREATE INDEX IF NOT EXISTS rows_task ON rows(instrument, task_hash, status);
CREATE TABLE IF NOT EXISTS assessments(
  assessment_id TEXT PRIMARY KEY, row_id TEXT, created_at REAL, mode TEXT, engine TEXT, strategy TEXT, direction TEXT, payload_json TEXT);
CREATE INDEX IF NOT EXISTS ass_recent ON assessments(created_at);
"""


class QuantLedger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.c = sqlite3.connect(str(self.path), check_same_thread=False, timeout=10)
        self.c.row_factory = sqlite3.Row
        with self._lock:
            self.c.execute("PRAGMA journal_mode=WAL")
            self.c.executescript(SCHEMA)
            self.c.commit()

    def add_row(self, r: dict) -> bool:
        with self._lock:
            cur = self.c.execute("""INSERT OR IGNORE INTO rows(row_id, instrument, engine, strategy, direction, decision_ts, task_hash, event_id, spec_json,
                                    features_json, snapshot_id, generation, data_kind, matures_at, status, created_at)
                                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'PENDING',?)""",
                                 (r["row_id"], r["instrument"], r["engine"], r["strategy"], r["direction"], r["decision_ts"], r["task_hash"], r["event_id"],
                                  json.dumps(r["spec"]), json.dumps(r["features"]), r.get("snapshot_id"), r.get("generation"), r.get("data_kind"),
                                  r["matures_at"], time.time()))
            self.c.commit()
            return cur.rowcount == 1

    def pending(self, now: float, limit: int = 500) -> list[dict]:
        with self._lock:
            return [dict(x) for x in self.c.execute("SELECT * FROM rows WHERE status='PENDING' AND matures_at<=? ORDER BY matures_at LIMIT ?",
                                                     (now, limit)).fetchall()]

    def label(self, row_id: str, status: str, label: dict | None, resolve_ts: float | None) -> None:
        y = None if not label or label.get("y_event") is None else int(bool(label["y_event"]))
        with self._lock:
            self.c.execute("UPDATE rows SET status=?, label_json=?, resolve_ts=?, y=?, net_r=? WHERE row_id=?",
                           (status, json.dumps(label) if label else None, resolve_ts, y, (label or {}).get("net_r"), row_id))
            self.c.commit()

    def training_rows(self, instrument: str, task_hash: str | None = None) -> list[dict]:
        q = "SELECT * FROM rows WHERE status='LABELLED' AND instrument=? AND y IS NOT NULL" + (" AND task_hash=?" if task_hash else "")
        with self._lock:
            rs = [dict(x) for x in self.c.execute(q, (instrument, task_hash) if task_hash else (instrument,)).fetchall()]
        return [{"row_id": r["row_id"], "decision_ts": r["decision_ts"], "resolve_ts": r["resolve_ts"], "features": json.loads(r["features_json"]),
                 "y": r["y"], "net_r": r["net_r"], "data_kind": r["data_kind"], "task_hash": r["task_hash"], "spec": json.loads(r["spec_json"])} for r in rs]

    def counts(self, instrument: str | None = None) -> dict:
        q = "SELECT task_hash, event_id, engine, status, COUNT(*) n, MIN(decision_ts) t0, MAX(decision_ts) t1, SUM(y) pos FROM rows" + \
            (" WHERE instrument=?" if instrument else "") + " GROUP BY task_hash, event_id, engine, status"
        with self._lock:
            rs = [dict(x) for x in self.c.execute(q, (instrument,) if instrument else ()).fetchall()]
        tasks: dict = {}
        for r in rs:
            t = tasks.setdefault(r["task_hash"], {"task_hash": r["task_hash"], "event_id": r["event_id"], "engine": r["engine"], "by_status": {},
                                                  "positives": 0, "from": r["t0"], "to": r["t1"]})
            t["by_status"][r["status"]] = r["n"]
            t["positives"] += int(r["pos"] or 0)
            t["from"], t["to"] = min(t["from"], r["t0"]), max(t["to"], r["t1"])
        return {"tasks": list(tasks.values()), "total": sum(r["n"] for r in rs)}

    def add_assessment(self, a: dict) -> None:
        with self._lock:
            self.c.execute("INSERT OR REPLACE INTO assessments VALUES (?,?,?,?,?,?,?,?)",
                           (a["assessment_id"], a.get("row_id"), a["created_at"], a["mode"], a.get("engine"), a.get("strategy"), a.get("direction"),
                            json.dumps(a, default=str)))
            self.c.execute("DELETE FROM assessments WHERE created_at < ?", (time.time() - 30 * 86400,))
            self.c.commit()

    def assessments(self, limit: int = 50) -> list[dict]:
        with self._lock:
            return [json.loads(x["payload_json"]) for x in self.c.execute("SELECT payload_json FROM assessments ORDER BY created_at DESC LIMIT ?",
                                                                           (int(limit),)).fetchall()]
