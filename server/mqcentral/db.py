"""Database access for the central server.

* PostgreSQL (psycopg 3) - production: several clients, row locks (SELECT ... FOR UPDATE), real concurrency.
* SQLite - explicitly limited LOCAL DEVELOPMENT / tests only (one writer, BEGIN IMMEDIATE serialises transactions).
SQL in the code uses `?` placeholders; they are translated to `%s` for psycopg. Rows are dicts.
"""
from __future__ import annotations

import re
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

MIGRATIONS = Path(__file__).resolve().parent / "migrations"
_MIG = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


class Cursorish:
    """Uniform transaction handle (sqlite3 / psycopg)."""

    def __init__(self, db: "Database", raw):
        self.db, self.raw = db, raw

    def q(self, sql: str, args: tuple | list = ()) -> list[dict]:
        cur = self.raw.execute(self.db.sql(sql), tuple(args))
        if cur.description is None:
            return []
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def one(self, sql: str, args: tuple | list = ()) -> dict | None:
        r = self.q(sql, args)
        return r[0] if r else None

    def x(self, sql: str, args: tuple | list = ()) -> int:
        cur = self.raw.execute(self.db.sql(sql), tuple(args))
        return cur.rowcount or 0


class Database:
    def __init__(self, url: str):
        self.url = url
        self.pg = url.startswith(("postgresql://", "postgres://"))
        if not self.pg and not url.startswith("sqlite:///"):
            raise ValueError("MQC_DATABASE_URL must be postgresql://... or sqlite:///path (development only)")
        self._local = threading.local()
        self._lock = threading.RLock()            # SQLite: one writer at a time

    # ------------------------------------------------------------ connections
    def _connect(self):
        if self.pg:
            import psycopg
            return psycopg.connect(self.url, autocommit=True)
        path = self.url[len("sqlite:///"):]
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA busy_timeout=30000")
        return c

    def conn(self):
        c = getattr(self._local, "c", None)
        if c is None or (self.pg and c.closed):
            c = self._connect()
            self._local.c = c
        return c

    def sql(self, s: str) -> str:
        if self.pg:
            return s.replace("?", "%s")
        return s.replace(" FOR UPDATE", "")       # SQLite: the whole transaction is already exclusive

    # ------------------------------------------------------------ api
    @contextmanager
    def tx(self) -> Iterator[Cursorish]:
        """Write transaction. PostgreSQL: use `... FOR UPDATE` in selects to lock rows; SQLite: BEGIN IMMEDIATE."""
        c = self.conn()
        if self.pg:
            with c.transaction():
                yield Cursorish(self, c)
        else:
            with self._lock:
                c.execute("BEGIN IMMEDIATE")
                try:
                    yield Cursorish(self, c)
                except BaseException:
                    c.execute("ROLLBACK")
                    raise
                else:
                    c.execute("COMMIT")

    def q(self, sql: str, args: tuple | list = ()) -> list[dict]:
        return Cursorish(self, self.conn()).q(sql, args)

    def one(self, sql: str, args: tuple | list = ()) -> dict | None:
        r = self.q(sql, args)
        return r[0] if r else None

    def x(self, sql: str, args: tuple | list = ()) -> int:
        if self.pg:
            return Cursorish(self, self.conn()).x(sql, args)
        with self._lock:
            return Cursorish(self, self.conn()).x(sql, args)

    # ------------------------------------------------------------ migrations
    def migrate(self) -> list[str]:
        c = self.conn()
        c.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at BIGINT NOT NULL)")
        done = {r["version"] for r in self.q("SELECT version FROM schema_migrations")}
        applied = []
        import time
        for f in sorted(MIGRATIONS.glob("*.sql")):
            m = _MIG.match(f.name)
            if not m or m.group(1) in done:
                continue
            text = f.read_text(encoding="utf-8")
            if self.pg:
                text = text.replace("/*SQLITE_ONLY*/", "--")
            else:
                text = text.replace("/*PG_ONLY*/", "--")
            with self.tx() as t:
                for stmt in strip_comments(text).split(";"):
                    if stmt.strip():
                        t.raw.execute(stmt)
                t.x("INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)", (m.group(1), int(time.time())))
            applied.append(m.group(1))
        return applied

    def versions(self) -> list[str]:
        return [r["version"] for r in self.q("SELECT version FROM schema_migrations ORDER BY version")]

    def close(self) -> None:
        c = getattr(self._local, "c", None)
        if c is not None:
            c.close()
            self._local.c = None


def strip_comments(sql: str) -> str:
    """Removes `--` comments (whole-line and trailing). Migration files contain no string literals with `--`."""
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())
