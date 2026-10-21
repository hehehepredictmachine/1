"""SQLite storage: protected account ids, deals (unique per account + ticket), completed-trade classifications, balance/equity
snapshots, open-position protection state, published messages (dedup + audit), command responses, key/value state."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (account_key TEXT PRIMARY KEY, config_id TEXT, label TEXT, currency TEXT, margin_mode TEXT,
  first_seen REAL, last_sync REAL, last_ok INTEGER, history_from REAL, server_offset_s REAL, offset_source TEXT, baseline_done INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS deals (account_key TEXT NOT NULL, ticket INTEGER NOT NULL, ord INTEGER, time REAL NOT NULL, time_msc INTEGER,
  type INTEGER NOT NULL, entry INTEGER, magic INTEGER, position_id INTEGER, volume REAL, price REAL, profit REAL, commission REAL, swap REAL,
  fee REAL, symbol TEXT, reason INTEGER, PRIMARY KEY (account_key, ticket));
CREATE INDEX IF NOT EXISTS ix_deals_time ON deals(account_key, time);
CREATE TABLE IF NOT EXISTS trades (account_key TEXT NOT NULL, trade_key TEXT NOT NULL, position_id INTEGER, symbol TEXT, side TEXT,
  open_time REAL, close_time REAL, volume REAL, entry_price REAL, exit_price REAL, gross REAL, commission REAL, swap REAL, fee REAL, net REAL,
  classification TEXT, method_version TEXT, updated_at REAL, PRIMARY KEY (account_key, trade_key));
CREATE TABLE IF NOT EXISTS snapshots (account_key TEXT NOT NULL, t REAL NOT NULL, balance REAL, equity REAL, margin REAL, free_margin REAL,
  open_positions INTEGER, PRIMARY KEY (account_key, t));
CREATE TABLE IF NOT EXISTS positions (account_key TEXT NOT NULL, ticket INTEGER NOT NULL, symbol TEXT, side TEXT, volume REAL,
  price_open REAL, sl REAL, tp REAL, updated_at REAL, PRIMARY KEY (account_key, ticket));
CREATE TABLE IF NOT EXISTS published (key TEXT PRIMARY KEY, kind TEXT, account_key TEXT, created_at REAL, status TEXT, attempts INTEGER,
  text TEXT, sent_at REAL, error TEXT);
CREATE TABLE IF NOT EXISTS reports (id INTEGER PRIMARY KEY AUTOINCREMENT, t REAL, chat_id INTEGER, command TEXT, period TEXT,
  method_version TEXT, payload TEXT);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
"""


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self.c = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None, timeout=15)
        self.c.row_factory = sqlite3.Row
        self.c.execute("PRAGMA journal_mode=WAL")
        self.c.executescript(SCHEMA)

    def q(self, sql: str, args=()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self.c.execute(sql, args).fetchall()]

    def one(self, sql: str, args=()) -> dict | None:
        r = self.q(sql, args)
        return r[0] if r else None

    def x(self, sql: str, args=()) -> int:
        with self._lock:
            return self.c.execute(sql, args).rowcount

    def many(self, sql: str, rows: list) -> None:
        with self._lock:
            self.c.execute("BEGIN")
            try:
                self.c.executemany(sql, rows)
                self.c.execute("COMMIT")
            except BaseException:
                self.c.execute("ROLLBACK")
                raise

    # kv
    def get(self, k: str, default=None):
        r = self.one("SELECT v FROM kv WHERE k=?", (k,))
        return json.loads(r["v"]) if r else default

    def put(self, k: str, v) -> None:
        self.x("INSERT INTO kv(k, v) VALUES (?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, json.dumps(v)))

    # accounts
    def upsert_account(self, key: str, **f) -> None:
        cur = self.one("SELECT * FROM accounts WHERE account_key=?", (key,))
        if not cur:
            self.x("INSERT INTO accounts(account_key, first_seen) VALUES (?,?)", (key, time.time()))
        if f:
            self.x(f"UPDATE accounts SET {', '.join(k + '=?' for k in f)} WHERE account_key=?", (*f.values(), key))

    def account(self, key: str) -> dict | None:
        return self.one("SELECT * FROM accounts WHERE account_key=?", (key,))

    # deals
    def add_deals(self, key: str, deals: list[dict]) -> int:
        """Insert new deals; an existing ticket is never duplicated (INSERT OR IGNORE). Returns the number of new deals."""
        before = self.one("SELECT COUNT(*) AS n FROM deals WHERE account_key=?", (key,))["n"]
        self.many("""INSERT OR IGNORE INTO deals(account_key, ticket, ord, time, time_msc, type, entry, magic, position_id, volume, price, profit,
                     commission, swap, fee, symbol, reason) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  [(key, int(d["ticket"]), d.get("order"), float(d["time"]), d.get("time_msc"), int(d["type"]), d.get("entry"), d.get("magic"),
                    d.get("position_id"), d.get("volume"), d.get("price"), d.get("profit"), d.get("commission"), d.get("swap"), d.get("fee"),
                    d.get("symbol"), d.get("reason")) for d in deals])
        return self.one("SELECT COUNT(*) AS n FROM deals WHERE account_key=?", (key,))["n"] - before

    def deals(self, key: str) -> list[dict]:
        return self.q("SELECT * FROM deals WHERE account_key=? ORDER BY time, ticket", (key,))

    # published
    def claim_publish(self, key: str, kind: str, account_key: str | None, text: str) -> bool:
        """True if this event/message was not published before (dedup across restarts)."""
        return self.x("INSERT OR IGNORE INTO published(key, kind, account_key, created_at, status, attempts, text) VALUES (?,?,?,?,?,?,?)",
                      (key, kind, account_key, time.time(), "PENDING", 0, text)) == 1

    def pending(self, limit: int = 20) -> list[dict]:
        return self.q("SELECT * FROM published WHERE status IN ('PENDING','RETRY') ORDER BY created_at LIMIT ?", (limit,))

    def mark(self, key: str, status: str, error: str | None = None) -> None:
        self.x("UPDATE published SET status=?, attempts=attempts+1, sent_at=?, error=? WHERE key=?", (status, time.time(), error, key))
