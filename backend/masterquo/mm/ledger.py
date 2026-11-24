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

    def pending(self, model_id: str | None = None, until: float | None = None, min_source_ts: float | None = None) -> list[dict]:
        q = ("SELECT * FROM predictions WHERE outcome IS NULL" + (" AND model_id=?" if model_id else "") + (" AND matures_at<=?" if until is not None else "")
             + (" AND source_ts>=?" if min_source_ts is not None else ""))
        args = tuple(x for x in (model_id, until, min_source_ts) if x is not None)
        with self._lock:
            return [dict(r) for r in self.c.execute(q + " ORDER BY matures_at", args).fetchall()]

    def mature(self, observed_until: float, resolver, model_id: str | None = None, min_source_ts: float | None = None) -> int:
        """resolver(row) -> outcome dict or None (target data not available yet). Only rows with matures_at <= observed_until.
        1.46 arch (I0358): min_source_ts = the first bar the resolver can see (live window of the bridge). Older unscored rows (e.g. a
        restart after a gap longer than the window) can never be resolved there - they stay in the ledger unscored (nothing is deleted
        or marked) but are no longer re-scanned on every recompute."""
        n = 0
        for r in self.pending(model_id, observed_until, min_source_ts):
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

    def rows(self, model_id: str, scored_only: bool = False, limit: int = 100000, newest: bool = False) -> list[dict]:
        """Rows in time order (source_ts ascending). Default: the OLDEST `limit` rows; newest=True: the NEWEST `limit` rows."""
        q = "SELECT * FROM predictions WHERE model_id=?" + (" AND outcome IS NOT NULL" if scored_only else "")
        # 1.46: ORDER BY ... LIMIT kept the oldest rows - a caller wanting the recent window (live calibration / drift, the ledger view)
        # froze on the start of the history once the ledger exceeded `limit`
        q = f"SELECT * FROM ({q} ORDER BY source_ts DESC LIMIT ?) ORDER BY source_ts" if newest else q + " ORDER BY source_ts LIMIT ?"
        with self._lock:
            out = [dict(r) for r in self.c.execute(q, (model_id, limit)).fetchall()]
        for r in out:
            r["payload"] = json.loads(r["payload"]) if r["payload"] else None
            r["outcome"] = json.loads(r["outcome"]) if r["outcome"] else None
        return out

    def outcome_means(self, model_id: str, keys: tuple[str, ...]) -> dict:
        """1.46: number of scored rows and the mean of numeric / boolean outcome fields over ALL scored rows of a model, aggregated in
        SQLite (no load + JSON decode of the whole history on every call). A field never present -> None."""
        sel = ", ".join(f"AVG(json_extract(outcome, '$.{k}'))" for k in keys)
        with self._lock:
            try:
                r = self.c.execute(f"SELECT COUNT(*){', ' + sel if keys else ''} FROM predictions WHERE model_id=? AND outcome IS NOT NULL",
                                   (model_id,)).fetchone()
                return {"n": int(r[0]), **{k: (None if v is None else float(v)) for k, v in zip(keys, tuple(r)[1:])}}
            except sqlite3.OperationalError:                              # SQLite without JSON1: same numbers in Python
                pass
        rows = self.rows(model_id, scored_only=True, limit=-1)
        out = {"n": len(rows)}
        for k in keys:
            v = [float(x["outcome"][k]) for x in rows if isinstance(x["outcome"], dict) and x["outcome"].get(k) is not None]
            out[k] = sum(v) / len(v) if v else None
        return out

    def summary(self) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self.c.execute(
                "SELECT model_id, COUNT(*) AS n, SUM(outcome IS NOT NULL) AS scored, MIN(source_ts) AS first_ts, MAX(source_ts) AS last_ts "
                "FROM predictions GROUP BY model_id ORDER BY model_id").fetchall()]
