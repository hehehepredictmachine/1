"""SQLite access: per-thread connections, WAL, versioned migrations with automatic backup."""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .. import paths
from ..timeutil import iso, utcnow

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
_MIG_RE = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


class Database:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or (paths.data_dir() / "masterquo.sqlite"))
        self._local = threading.local()
        self._write_lock = threading.RLock()
        self.migrate()

    # -- connections -------------------------------------------------------
    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(str(self.path), timeout=15, isolation_level=None, check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            c.execute("PRAGMA foreign_keys=ON")
            c.execute("PRAGMA busy_timeout=15000")
            self._local.conn = c
        return c

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """Serialized write transaction (BEGIN IMMEDIATE)."""
        with self._write_lock:
            c = self.conn()
            c.execute("BEGIN IMMEDIATE")
            try:
                yield c
            except BaseException:
                c.execute("ROLLBACK")
                raise
            else:
                c.execute("COMMIT")

    def query(self, sql: str, args: tuple | list = ()) -> list[dict]:
        return [dict(r) for r in self.conn().execute(sql, args).fetchall()]

    def one(self, sql: str, args: tuple | list = ()) -> dict | None:
        r = self.conn().execute(sql, args).fetchone()
        return dict(r) if r else None

    def execute(self, sql: str, args: tuple | list = ()) -> int:
        with self.tx() as c:
            cur = c.execute(sql, args)
            return cur.lastrowid or cur.rowcount

    # -- migrations ---------------------------------------------------------
    def migrate(self) -> list[str]:
        existed = self.path.exists() and self.path.stat().st_size > 0
        c = self.conn()
        c.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
        done = {r["version"] for r in c.execute("SELECT version FROM schema_migrations")}
        pending = sorted(p for p in MIGRATIONS_DIR.iterdir() if _MIG_RE.match(p.name) and p.name[:4] not in done)
        if not pending:
            return []
        if existed and done:
            self.backup(reason="pre-migration")
        applied = []
        for p in pending:
            sql = p.read_text(encoding="utf-8")
            with self._write_lock:
                try:
                    c.execute("BEGIN IMMEDIATE")
                    for stmt in _split_sql(sql):
                        c.execute(stmt)
                    c.execute("INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)", (p.name[:4], iso(utcnow())))
                    c.execute("COMMIT")
                except sqlite3.Error as exc:
                    c.execute("ROLLBACK")
                    raise RuntimeError(f"MIGRATION_FAILED:{p.name}:{exc}") from exc
            applied.append(p.name)
        return applied

    def backup(self, reason: str = "manual") -> Path:
        stamp = utcnow().strftime("%Y%m%dT%H%M%SZ")
        target = paths.backups_dir() / f"masterquo_{stamp}_{reason}.sqlite"
        src = sqlite3.connect(str(self.path))
        try:
            dst = sqlite3.connect(str(target))
            with dst:
                src.backup(dst)
            dst.close()
        finally:
            src.close()
        # keep the 20 newest backups
        backups = sorted(paths.backups_dir().glob("masterquo_*.sqlite"))
        for old in backups[:-20]:
            try:
                old.unlink()
            except OSError:
                pass
        return target

    def schema_versions(self) -> list[str]:
        return [r["version"] for r in self.query("SELECT version FROM schema_migrations ORDER BY version")]

    def close(self) -> None:
        c = getattr(self._local, "conn", None)
        if c is not None:
            c.close()
            self._local.conn = None


def _split_sql(sql: str) -> list[str]:
    lines = [ln for ln in sql.splitlines() if not ln.strip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False, default=str)


def copy_file(src: Path, dst: Path) -> None:
    shutil.copy2(src, dst)
