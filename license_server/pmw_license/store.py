"""Persistence behind a small repository (SQLite now; the same methods can be backed by PostgreSQL later).

Only hashes are stored: license keys (HMAC-SHA256 with the server pepper), device tokens and admin session tokens (SHA-256).
Administrator device keys are PUBLIC keys only (their private parts never leave the OWNER computer).
Plaintext keys exist only in the one response that creates them. Writes are transactions (BEGIN IMMEDIATE), activation is
protected by a conditional UPDATE so two concurrent activations cannot both bind a device.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS licenses (
        license_id   TEXT PRIMARY KEY,
        key_hash     TEXT NOT NULL UNIQUE,
        key_hint     TEXT NOT NULL,
        duration     TEXT NOT NULL CHECK (duration IN ('24h','72h','7d','31d')),
        status       TEXT NOT NULL CHECK (status IN ('CREATED','ACTIVE','EXPIRED','REVOKED')),
        note         TEXT,
        created_at   REAL NOT NULL,
        created_by   TEXT NOT NULL,
        activated_at REAL,
        expires_at   REAL,
        hwid_hash    TEXT,
        token_hash   TEXT,
        bound_at     REAL,
        last_seen_at REAL,
        client_version TEXT,
        revoked_at   REAL,
        revoke_reason TEXT)""",
    "CREATE INDEX IF NOT EXISTS ix_licenses_status ON licenses(status)",
    """CREATE TABLE IF NOT EXISTS admin_sessions (
        token_hash TEXT PRIMARY KEY, username TEXT NOT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL, ip TEXT)""",
    """CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, license_id TEXT,
        ok INTEGER NOT NULL, ip TEXT, details TEXT)""",
    "CREATE INDEX IF NOT EXISTS ix_audit_ts ON audit_log(ts)",
    # v2 (1.29): administrator device keys (OWNER app, Ed25519 public keys added from the server shell) + replay store of their nonces
    """CREATE TABLE IF NOT EXISTS admin_keys (
        kid TEXT PRIMARY KEY, public_key TEXT NOT NULL UNIQUE, label TEXT, created_at REAL NOT NULL, created_by TEXT NOT NULL,
        revoked_at REAL, revoke_reason TEXT, last_used_at REAL)""",
    """CREATE TABLE IF NOT EXISTS admin_nonces (
        kid TEXT NOT NULL, nonce TEXT NOT NULL, ts REAL NOT NULL, PRIMARY KEY (kid, nonce))""",
    "CREATE INDEX IF NOT EXISTS ix_admin_nonces_ts ON admin_nonces(ts)",
]
SCHEMA_VERSION = 2
PUBLIC_COLUMNS = ("license_id", "key_hint", "duration", "status", "note", "created_at", "created_by", "activated_at", "expires_at",
                  "bound_at", "last_seen_at", "client_version", "revoked_at", "revoke_reason")


class Store:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None, timeout=10)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            for stmt in SCHEMA:
                self.conn.execute(stmt)
            if self.conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == 0:
                self.conn.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
            else:                                                # upgrade in place (only additive tables - a v1 server can still read it)
                self.conn.execute("UPDATE schema_version SET version=? WHERE version<?", (SCHEMA_VERSION, SCHEMA_VERSION))
        try:
            if str(path) != ":memory:":
                self.path.chmod(0o600)
        except OSError:
            pass

    # ------------------------------------------------------------------ helpers
    def tx(self):
        store = self

        class _Tx:
            def __enter__(self):
                store.lock.acquire()
                store.conn.execute("BEGIN IMMEDIATE")
                return store.conn

            def __exit__(self, et, ev, tb):
                try:
                    store.conn.execute("ROLLBACK" if et else "COMMIT")
                finally:
                    store.lock.release()
                return False
        return _Tx()

    def one(self, sql: str, args=()) -> dict | None:
        with self.lock:
            r = self.conn.execute(sql, args).fetchone()
        return dict(r) if r else None

    def all(self, sql: str, args=()) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    # ------------------------------------------------------------------ audit
    def audit(self, ts: float, actor: str, action: str, *, license_id: str | None = None, ok: bool = True, ip: str | None = None,
              details: dict | None = None, conn=None) -> None:
        sql = "INSERT INTO audit_log(ts, actor, action, license_id, ok, ip, details) VALUES (?,?,?,?,?,?,?)"
        args = (ts, actor[:64], action, license_id, 1 if ok else 0, ip, json.dumps(details or {}, ensure_ascii=False)[:2000])
        if conn is not None:
            conn.execute(sql, args)
        else:
            with self.lock:
                self.conn.execute(sql, args)

    def backup(self, dest: Path | str) -> Path:
        """Consistent online snapshot of the database (SQLite backup API) - safe while the API is running."""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        out = sqlite3.connect(str(dest))
        try:
            with self.lock:
                self.conn.backup(out)
        finally:
            out.close()
        try:
            dest.chmod(0o600)
        except OSError:
            pass
        return dest
