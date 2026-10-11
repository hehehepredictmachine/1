"""SQLite storage (WAL, foreign keys, BEGIN IMMEDIATE for every write transaction) with versioned migrations.
A single API process is the supported deployment (see README_SERWER_PL.md); writes are serialised by SQLite."""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parent / "migrations"


class DB:
    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._wlock = threading.RLock()
        self.migrate()

    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "c", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=30, isolation_level=None, check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA foreign_keys=ON")
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA busy_timeout=30000")
            self._local.c = c
        return c

    def one(self, sql: str, args=()) -> dict | None:
        r = self.conn().execute(sql, args).fetchone()
        return dict(r) if r else None

    def all(self, sql: str, args=()) -> list[dict]:
        return [dict(r) for r in self.conn().execute(sql, args).fetchall()]

    def x(self, sql: str, args=()) -> int:
        with self._wlock:
            return self.conn().execute(sql, args).rowcount

    @contextmanager
    def tx(self):
        """Exclusive write transaction (atomic session registration, revocation)."""
        with self._wlock:
            c = self.conn()
            c.execute("BEGIN IMMEDIATE")
            try:
                yield c
                c.execute("COMMIT")
            except BaseException:
                c.execute("ROLLBACK")
                raise

    def migrate(self) -> list[str]:
        c = self.conn()
        c.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        done = {r["version"] for r in c.execute("SELECT version FROM schema_migrations")}
        applied = []
        for f in sorted(MIGRATIONS.glob("*.sql")):
            v = f.name[:4]
            if v in done:
                continue
            with self.tx() as t:
                for stmt in [s.strip() for s in "\n".join(l.split("--")[0] for l in f.read_text(encoding="utf-8").splitlines()).split(";")]:
                    if stmt:
                        t.execute(stmt)
                t.execute("INSERT INTO schema_migrations(version) VALUES (?)", (v,))
            applied.append(v)
        return applied

    def versions(self) -> list[str]:
        return [r["version"] for r in self.all("SELECT version FROM schema_migrations ORDER BY version")]

    def backup(self, dest: str) -> None:
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(dest) as out:
            self.conn().backup(out)
