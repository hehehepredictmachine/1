"""TraderLifeGame backup import (Apollo23 1.46) - restores an export made by `export-trader-life-game`.

Rules (no user data is ever lost):
* the export folder is verified first (manifest schema, SHA-256 and row count of every file) and must be a `trader-life-game` export;
* ADDITIVE and IDEMPOTENT: rows are inserted with INSERT OR IGNORE on the table's own keys (ledger idempotency keys, primary keys);
  an existing row is never updated or deleted, an existing profile is kept; importing the same backup twice changes nothing;
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


def _rows(folder: Path, table: str) -> list[dict]:
    p = folder / f"{table}.jsonl"
    if not p.is_file():
        return []
    with open(p, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


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
              "profile": None, "pre_import_copy": None, "database": str(dbp)}
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
            for t in IMPORT_ORDER:
                if t not in TLG_KINDS:
                    continue
                cols = [r["name"] for r in conn.execute(f'PRAGMA table_info("{t}")').fetchall()]
                derived = {f"{c}_utc" for c in TLG_EPOCH_COLS}
                ins = skipped = rejected = 0
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
