"""Shadow prediction ledger with label maturation (PMW-MM-LEDGER-1).

One row per issued prediction (model id + artifact + feature schema + typed payload + input quality). A row has a `matures_at` time:
the earliest moment its target is observable (e.g. the close of bar t+h). `mature()` attaches realised outcomes ONLY to rows whose
matures_at <= the time of the newest available observation, exactly once (a scored row is never rescored). Predictions whose horizon
has not elapsed have no outcome. Every prediction is logged regardless of any gate (no filter-dependent sampling).
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS predictions (pred_id TEXT PRIMARY KEY, model_id TEXT NOT NULL, artifact_id TEXT, feature_schema TEXT,
  symbol TEXT, timeframe TEXT, source_ts REAL, available_at REAL, predicted_at REAL, matures_at REAL, horizon TEXT, kind TEXT,
  payload TEXT, quality TEXT, outcome TEXT, matured_at REAL, error TEXT, run_mode TEXT);
CREATE INDEX IF NOT EXISTS ix_pred_model ON predictions(model_id, source_ts);
CREATE INDEX IF NOT EXISTS ix_pred_open ON predictions(matures_at) WHERE outcome IS NULL;
"""


class Ledger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.c = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None, timeout=15)
        self.c.row_factory = sqlite3.Row
        self.c.execute("PRAGMA journal_mode=WAL")
        self.c.executescript(SCHEMA)

    def log(self, *, pred_id: str, model_id: str, artifact_id: str | None, feature_schema: str | None, symbol: str, timeframe: str,
            source_ts: float, available_at: float, matures_at: float, horizon: str, kind: str, payload: dict, quality: str,
            run_mode: str = "SHADOW") -> bool:
        """False when this prediction id already exists (restart / replay must not duplicate a forecast)."""
        if matures_at < available_at:
            raise ValueError("MATURES_BEFORE_AVAILABLE")
        with self._lock:
            cur = self.c.execute("INSERT OR IGNORE INTO predictions(pred_id, model_id, artifact_id, feature_schema, symbol, timeframe, source_ts, "
                                 "available_at, predicted_at, matures_at, horizon, kind, payload, quality, run_mode) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                 (pred_id, model_id, artifact_id, feature_schema, symbol, timeframe, source_ts, available_at, time.time(), matures_at,
                                  horizon, kind, json.dumps(payload, default=float), quality, run_mode))
            return cur.rowcount == 1

    def pending(self, model_id: str | None = None, until: float | None = None) -> list[dict]:
        q = "SELECT * FROM predictions WHERE outcome IS NULL" + (" AND model_id=?" if model_id else "") + (" AND matures_at<=?" if until is not None else "")
        args = tuple(x for x in (model_id, until) if x is not None)
        with self._lock:
            return [dict(r) for r in self.c.execute(q + " ORDER BY matures_at", args).fetchall()]

    def mature(self, observed_until: float, resolver, model_id: str | None = None) -> int:
        """resolver(row) -> outcome dict or None (target data not available yet). Only rows with matures_at <= observed_until."""
        n = 0
        for r in self.pending(model_id, observed_until):
            try:
                out = resolver(r)
            except Exception as exc:  # noqa: BLE001 - one bad row never blocks the queue
                with self._lock:
                    self.c.execute("UPDATE predictions SET error=? WHERE pred_id=?", (f"{type(exc).__name__}: {exc}"[:300], r["pred_id"]))
                continue
            if out is None:
                continue
            with self._lock:
                cur = self.c.execute("UPDATE predictions SET outcome=?, matured_at=? WHERE pred_id=? AND outcome IS NULL",
                                     (json.dumps(out, default=float), time.time(), r["pred_id"]))
                n += cur.rowcount
        return n

    def rows(self, model_id: str, scored_only: bool = False, limit: int = 100000) -> list[dict]:
        q = "SELECT * FROM predictions WHERE model_id=?" + (" AND outcome IS NOT NULL" if scored_only else "") + " ORDER BY source_ts LIMIT ?"
        with self._lock:
            out = [dict(r) for r in self.c.execute(q, (model_id, limit)).fetchall()]
        for r in out:
            r["payload"] = json.loads(r["payload"]) if r["payload"] else None
            r["outcome"] = json.loads(r["outcome"]) if r["outcome"] else None
        return out

    def summary(self) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self.c.execute(
                "SELECT model_id, COUNT(*) AS n, SUM(outcome IS NOT NULL) AS scored, MIN(source_ts) AS first_ts, MAX(source_ts) AS last_ts "
                "FROM predictions GROUP BY model_id ORDER BY model_id").fetchall()]
