"""TraderLifeGame backup import (Apollo23 1.46) - restores an export made by `export-trader-life-game`.

Rules (no user data is ever lost):
* the export folder is verified first (manifest schema, SHA-256 and row count of every file) and must be a `trader-life-game` export;
* ADDITIVE and IDEMPOTENT: rows are inserted with INSERT OR IGNORE on the table's own keys (ledger idempotency keys, primary keys);
  an existing row is never updated or deleted, an existing profile is kept; importing the same backup twice changes nothing;
* tables numbered by AUTOINCREMENT (events, ledgers, quiz, notes, simulator, coach memory) are matched on their identity (idempotency key or
  the columns that never change after insert), not on the local id; a backup id is kept only when it is free, otherwise the row gets a new
  id and sim_trades follow their session (old session id -> id in this database);
* REVERSIBLE: before the first write the current game.sqlite is copied (SQLite backup API) to <data>/backups/tlg-before-import-<UTC>.sqlite;
* only columns that exist in the current table are accepted (column names are checked against PRAGMA table_info - never taken blindly);
* one transaction: either every table is imported or nothing is.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .core import ExportError, verify_export
from .sources import TLG_EPOCH_COLS, TLG_KINDS

IMPORT_ORDER = ("profile", "events", "xp_ledger", "gold_ledger", "skills", "quest_claims", "academy", "quiz", "journal", "notes",
                "sim_sessions", "sim_trades", "inventory", "coach_memory")
# 1.46: identity of rows in AUTOINCREMENT tables. The id is only a local number: in a game that already had its own rows ids 1..N were taken,
# INSERT OR IGNORE silently dropped the backup rows with the same numbers (other keys - XP, Gold, notes, sessions lost) and attached sim_trades
# to the LOCAL session with the same number. Identity = idempotency key, or the columns that are never updated after the insert (a re-import
# after playing on - cursor moved, trade closed - is still recognised as the same row).
_IDENTITY = {"events": ("key",), "xp_ledger": ("key",), "gold_ledger": ("key",), "quiz": ("level", "ts", "score", "passed"),
             "notes": ("kind", "ts", "data"), "coach_memory": ("ts", "text"),
             "sim_sessions": ("symbol", "tf", "bars", "start_cursor", "virtual_start", "provenance", "created_at"),
             "sim_trades": ("session_id", "side", "size", "entry", "sl", "tp", "opened_idx")}


def _rows(folder: Path, table: str) -> list[dict]:
    p = folder / f"{table}.jsonl"
    if not p.is_file():
        return []
    with open(p, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _import_by_identity(conn, t: str, data: dict, seen: dict, new_ids: set, sess_map: dict) -> tuple[str, int | None]:
    """1.46: one row of an AUTOINCREMENT table -> ("inserted" | "existing" | "renumbered" | "rejected", id in this database).
    The k-th backup row with a given identity matches the k-th row with that identity which existed before this import (identical rows,
    e.g. two equal trades of one session, are not collapsed)."""
    data = dict(data)
    old_id = data.pop("id", None)
    if t == "sim_trades":
        sid = sess_map.get(data.get("session_id"))
        if sid is None:                                   # its session is not in the backup (or was rejected): never attach to a foreign one
            return "rejected", None
        data["session_id"] = sid
    cols = _IDENTITY[t]
    ident = tuple(data.get(c) for c in cols)
    where = " AND ".join(f'"{c}" IS ?' for c in cols)
    pre = [i for (i,) in conn.execute(f'SELECT id FROM "{t}" WHERE {where} ORDER BY id', ident).fetchall() if i not in new_ids]
    k = seen.get(ident, 0)
    seen[ident] = k + 1
    if k < len(pre):
        return "existing", pre[k]
    free = old_id is not None and conn.execute(f'SELECT 1 FROM "{t}" WHERE id = ?', (old_id,)).fetchone() is None
    if free:
        data["id"] = old_id                               # exact restore keeps the numbers (event keys "note:<id>", "sim:<id>" refer to them)
    keys = list(data)
    try:
        cur = conn.execute(f'INSERT INTO "{t}"(' + ", ".join(f'"{k}"' for k in keys) + ") VALUES(" + ", ".join("?" * len(keys)) + ")",
                           [data[k] for k in keys])
    except sqlite3.IntegrityError:
        return "rejected", None
    new_ids.add(cur.lastrowid)
    return ("inserted" if free or old_id is None else "renumbered"), cur.lastrowid


def import_backup(folder: Path, data_dir: Path, *, dry_run: bool = False, now: datetime | None = None) -> dict:
    from ..trader_life_game.service import _DDL, SCHEMA_VERSION
    folder = Path(folder)
    ver = verify_export(folder)
    if not ver["ok"]:
        raise ExportError(f"BACKUP_INVALID: {'; '.join(ver['problems'])[:400]}")
    man = ver["manifest"]
    if man.get("export_name") != "trader-life-game":
        raise ExportError(f"NOT_A_TLG_BACKUP: {man.get('export_name')}")
    if "jsonl" not in (man.get("formats") or []):
        raise ExportError("BACKUP_NEEDS_JSONL: import czyta pliki .jsonl (typy danych bez strat)")
    src_ver = (man.get("provenance") or {}).get("game_schema_version")
    if src_ver is not None and str(src_ver) != str(SCHEMA_VERSION):
        raise ExportError(f"GAME_SCHEMA_MISMATCH: kopia {src_ver}, aplikacja {SCHEMA_VERSION} (brak migracji – import wstrzymany)")
    game_dir = Path(data_dir) / "trader_life_game"
    dbp = game_dir / "game.sqlite"
    now = now or datetime.now(timezone.utc)
    report = {"backup_export_id": man.get("export_id"), "dry_run": dry_run, "inserted": {}, "skipped_existing": {}, "rejected": {},
              "renumbered": {}, "profile": None, "pre_import_copy": None, "database": str(dbp)}
    existed = dbp.exists()
    if not dry_run:
        game_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(":memory:" if dry_run and not existed else str(dbp), timeout=15, isolation_level=None)
    try:
        conn.row_factory = sqlite3.Row
        if existed and not dry_run:
            bdir = Path(data_dir) / "backups"
            bdir.mkdir(parents=True, exist_ok=True)
            copy = bdir / f"tlg-before-import-{now.strftime('%Y%m%dT%H%M%SZ')}.sqlite"
            n = 1
            while copy.exists():
                copy = bdir / f"tlg-before-import-{now.strftime('%Y%m%dT%H%M%SZ')}-{n}.sqlite"
                n += 1
            dst = sqlite3.connect(str(copy))
            try:
                conn.backup(dst)
            finally:
                dst.close()
            report["pre_import_copy"] = str(copy)
        if not dry_run or not existed:
            conn.executescript(_DDL)                                    # CREATE IF NOT EXISTS - additive, never alters existing tables
            conn.execute("INSERT OR IGNORE INTO meta(k, v) VALUES('schema_version', ?)", (str(SCHEMA_VERSION),))
        conn.execute("BEGIN IMMEDIATE")
        try:
            sess_map: dict = {}                                       # 1.46: backup sim_sessions.id -> id in this database
            for t in IMPORT_ORDER:
                if t not in TLG_KINDS:
                    continue
                cols = [r["name"] for r in conn.execute(f'PRAGMA table_info("{t}")').fetchall()]
                derived = {f"{c}_utc" for c in TLG_EPOCH_COLS}
                ins = skipped = rejected = renumbered = 0
                seen: dict = {}
                new_ids: set = set()
                if t == "profile" and conn.execute("SELECT 1 FROM profile WHERE id = 1").fetchone():
                    report["profile"] = "KEPT_EXISTING (istniejący profil nie jest nadpisywany)"
                    report["skipped_existing"][t] = len(_rows(folder, t))
                    continue
                for r in _rows(folder, t):
                    data = {k: v for k, v in r.items() if k not in derived}
                    unknown = [k for k in data if k not in cols]
                    if unknown or not data:
                        rejected += 1
                        continue
                    if t in _IDENTITY:                                # 1.46: never match AUTOINCREMENT rows on the local id
                        res, local_id = _import_by_identity(conn, t, data, seen, new_ids, sess_map)
                        if t == "sim_sessions" and local_id is not None and data.get("id") is not None:
                            sess_map[data["id"]] = local_id
                        if res == "rejected":
                            rejected += 1
                        elif res == "existing":
                            skipped += 1
                        else:
                            ins += 1
                            renumbered += res == "renumbered"
                        continue
                    keys = list(data)
                    sql = f'INSERT OR IGNORE INTO "{t}"(' + ", ".join(f'"{k}"' for k in keys) + ") VALUES(" + ", ".join("?" * len(keys)) + ")"
                    try:
                        cur = conn.execute(sql, [data[k] for k in keys])
                    except sqlite3.IntegrityError:
                        rejected += 1
                        continue
                    if cur.rowcount == 1:
                        ins += 1
                    else:
                        skipped += 1
                if t == "profile" and ins:
                    report["profile"] = "IMPORTED"
                report["inserted"][t], report["skipped_existing"][t], report["rejected"][t] = ins, skipped, rejected
                if renumbered:
                    report["renumbered"][t] = renumbered              # inserted under a new id: the backup id was taken by another row
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("ROLLBACK" if dry_run else "COMMIT")
    finally:
        conn.close()
    report["total_inserted"] = sum(report["inserted"].values())
    report["note"] = ("podgląd – nic nie zapisano" if dry_run else
                      "przywrócenie stanu sprzed importu: zatrzymaj aplikację i skopiuj pre_import_copy w miejsce game.sqlite")
    return report
