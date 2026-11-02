"""Candle store for training (PMW-MD-1): data/marketdata/<INSTRUMENT>/<TF>/<YYYY-MM>.parquet + the same rows as .csv.

* One row per (instrument, timeframe, bar open time UTC) - merging is idempotent: an identical re-read is a duplicate (counted, not
  stored twice); a re-read with DIFFERENT OHLC for a stored time is a revision conflict - the stored row stays, the conflict is listed
  in the manifest (a training dataset never changes silently under a model that was trained on it).
* Only closed candles are stored (the exporter cuts at the last closed candle); nothing is synthesised: gaps stay gaps.
* Columns: time (UTC epoch s of the bar open), open, high, low, close (broker chart prices, MT5: usually Bid), tick_volume (number of
  price changes - NOT traded volume), spread (points, as recorded by the terminal for the bar), real_volume (0 when the broker does not
  provide it), server_time (raw broker server epoch), dst_ambiguous (1 = the server->UTC conversion was ambiguous at a DST switch).
* Every file is written atomically (temp file + replace); manifest.json lists rows, ranges and sha256 of every file.
Parquet needs pyarrow (requirements-win.txt); without it only CSV is written and the manifest says so.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "PMW-MD-1"
COLUMNS = ("time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume", "server_time", "dst_ambiguous")
INT_COLS = ("time", "tick_volume", "spread", "real_volume", "server_time", "dst_ambiguous")
COLUMN_DOC = {
    "time": "czas otwarcia świecy, UTC (epoch s)", "open": "cena otwarcia wykresu brokera (MT5: zwykle Bid)", "high": "maksimum",
    "low": "minimum", "close": "zamknięcie", "tick_volume": "liczba zmian ceny w świecy – NIE wolumen transakcyjny",
    "spread": "spread w punktach zapisany przez terminal dla świecy (x point = cena); NIE historyczny bid/ask",
    "real_volume": "wolumen rzeczywisty, jeśli broker go podaje (CFD: zwykle 0)", "server_time": "surowy czas serwera brokera (epoch)",
    "dst_ambiguous": "1 = konwersja czasu serwera na UTC niejednoznaczna przy zmianie czasu",
}
TF_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400}


def have_parquet() -> bool:
    try:
        import pyarrow  # noqa: F401
        import pyarrow.parquet  # noqa: F401
        return True
    except ImportError:
        return False


def iso(t: float | None) -> str | None:
    if t is None:
        return None
    return datetime.fromtimestamp(float(t), timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_bytes(p: Path, data: bytes) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".tmp{os.getpid()}")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)


def atomic_json(p: Path, obj) -> None:
    atomic_bytes(p, (json.dumps(obj, indent=1, ensure_ascii=False, default=str) + "\n").encode("utf-8"))


def read_json(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def month_key(t: int) -> str:
    d = datetime.fromtimestamp(int(t), timezone.utc)
    return f"{d.year:04d}-{d.month:02d}"


def default_root() -> Path:
    from ..paths import data_dir
    return data_dir() / "marketdata"


class Store:
    def __init__(self, root: Path | None = None):
        self.root = Path(root or default_root())

    # ------------------------------------------------------------------ paths
    def inst_dir(self, inst: str) -> Path:
        return self.root / inst

    def tf_dir(self, inst: str, tf: str) -> Path:
        return self.root / inst / tf

    def manifest_path(self, inst: str) -> Path:
        return self.inst_dir(inst) / "manifest.json"

    def manifest(self, inst: str) -> dict:
        return read_json(self.manifest_path(inst), None) or {"schema_version": SCHEMA_VERSION, "instrument": inst, "timeframes": {}, "exports": []}

    # ------------------------------------------------------------------ io
    def _read_part(self, inst: str, tf: str, key: str) -> dict[int, tuple]:
        d = self.tf_dir(inst, tf)
        pq_path, csv_path = d / f"{key}.parquet", d / f"{key}.csv"
        rows: dict[int, tuple] = {}
        if pq_path.exists() and have_parquet():
            import pyarrow.parquet as pq
            t = pq.read_table(pq_path).to_pydict()
            for i in range(len(t["time"])):
                rows[int(t["time"][i])] = tuple(t[c][i] for c in COLUMNS)
            return rows
        if csv_path.exists():
            with open(csv_path, newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    rows[int(r["time"])] = tuple(int(r[c] or 0) if c in INT_COLS else float(r[c]) for c in COLUMNS)
        return rows

    def _write_part(self, inst: str, tf: str, key: str, rows: dict[int, tuple]) -> dict:
        d = self.tf_dir(inst, tf)
        ts = sorted(rows)
        cols = {c: [rows[t][i] for t in ts] for i, c in enumerate(COLUMNS)}
        files = {}
        if have_parquet():
            import pyarrow as pa
            import pyarrow.parquet as pq
            schema = pa.schema([(c, pa.int64() if c in INT_COLS else pa.float64()) for c in COLUMNS])
            tbl = pa.table({c: cols[c] for c in COLUMNS}, schema=schema)
            buf = io.BytesIO()
            pq.write_table(tbl, buf, compression="zstd")
            atomic_bytes(d / f"{key}.parquet", buf.getvalue())
            files[f"{tf}/{key}.parquet"] = d / f"{key}.parquet"
        sbuf = io.StringIO()
        w = csv.writer(sbuf, lineterminator="\n")
        w.writerow(("time_utc",) + COLUMNS)
        for t in ts:
            r = rows[t]
            w.writerow((iso(t),) + tuple(r))
        atomic_bytes(d / f"{key}.csv", sbuf.getvalue().encode("utf-8"))
        files[f"{tf}/{key}.csv"] = d / f"{key}.csv"
        return {name: {"sha256": sha256_file(p), "bytes": p.stat().st_size, "rows": len(ts)} for name, p in files.items()}

    def parts(self, inst: str, tf: str) -> list[str]:
        d = self.tf_dir(inst, tf)
        if not d.exists():
            return []
        return sorted({p.stem for p in d.iterdir() if p.suffix in (".parquet", ".csv") and ".tmp" not in p.name})

    # ------------------------------------------------------------------ merge
    def merge(self, inst: str, tf: str, new_rows: list[tuple]) -> dict:
        """Insert rows (tuples in COLUMNS order). Returns counts: added / identical duplicates / revision conflicts (stored row kept)."""
        by_part: dict[str, list[tuple]] = {}
        for r in new_rows:
            by_part.setdefault(month_key(r[0]), []).append(r)
        out = {"added": 0, "duplicates": 0, "conflicts": 0, "conflict_list": [], "files": {}}
        for key, rows in sorted(by_part.items()):
            cur = self._read_part(inst, tf, key)
            changed = False
            for r in rows:
                old = cur.get(int(r[0]))
                if old is None:
                    cur[int(r[0])] = tuple(int(v) if c in INT_COLS else float(v) for c, v in zip(COLUMNS, r))
                    out["added"] += 1
                    changed = True
                elif tuple(round(float(x), 10) for x in old[1:5]) == tuple(round(float(x), 10) for x in r[1:5]):
                    out["duplicates"] += 1
                else:
                    out["conflicts"] += 1
                    if len(out["conflict_list"]) < 100:
                        out["conflict_list"].append({"time_utc": iso(r[0]), "stored_ohlc": list(old[1:5]), "reread_ohlc": list(r[1:5])})
            if changed:
                out["files"].update(self._write_part(inst, tf, key, cur))
        return out

    # ------------------------------------------------------------------ read
    def read(self, inst: str, tf: str, start: float | None = None, end: float | None = None) -> dict:
        """Columns (lists) sorted by time; start inclusive, end exclusive (bar open time)."""
        rows: dict[int, tuple] = {}
        for key in self.parts(inst, tf):
            rows.update(self._read_part(inst, tf, key))
        ts = [t for t in sorted(rows) if (start is None or t >= start) and (end is None or t < end)]
        return {c: [rows[t][i] for t in ts] for i, c in enumerate(COLUMNS)}

    def last_time(self, inst: str, tf: str) -> int | None:
        for key in reversed(self.parts(inst, tf)):
            r = self._read_part(inst, tf, key)
            if r:
                return max(r)
        return None

    def first_time(self, inst: str, tf: str) -> int | None:
        for key in self.parts(inst, tf):
            r = self._read_part(inst, tf, key)
            if r:
                return min(r)
        return None

    # ------------------------------------------------------------------ manifest
    def file_checksums(self, inst: str) -> dict:
        out = {}
        base = self.inst_dir(inst)
        for tf in TF_SECONDS:
            d = base / tf
            if not d.exists():
                continue
            for p in sorted(d.iterdir()):
                if p.suffix in (".parquet", ".csv") and ".tmp" not in p.name:
                    out[f"{tf}/{p.name}"] = {"sha256": sha256_file(p), "bytes": p.stat().st_size}
        return out

    def verify(self, inst: str) -> dict:
        """Checksums of the manifest against the files on disk (a copied / damaged dataset is detected before training)."""
        man = self.manifest(inst)
        listed = man.get("files") or {}
        bad, missing = [], []
        for name, meta in listed.items():
            p = self.inst_dir(inst) / name
            if not p.exists():
                missing.append(name)
            elif sha256_file(p) != meta.get("sha256"):
                bad.append(name)
        return {"ok": not bad and not missing and bool(listed), "files": len(listed), "checksum_mismatch": bad, "missing": missing}

    def write_manifest(self, inst: str, update: dict) -> dict:
        man = self.manifest(inst)
        man.update(update)
        man["schema_version"] = SCHEMA_VERSION
        man["columns"] = COLUMN_DOC
        man["parquet"] = "pyarrow" if have_parquet() else "NIEDOSTĘPNE – brak pakietu pyarrow, zapisano tylko CSV"
        man["files"] = self.file_checksums(inst)
        man["updated_at"] = iso(time.time())
        atomic_json(self.manifest_path(inst), man)
        return man
