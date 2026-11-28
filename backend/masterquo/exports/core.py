"""Common export writer (Apollo23 1.46, PMW-EXPORT-1): CSV + JSONL + manifest.json with SHA-256 for every exporter.

One code path for every data source (exports/sources.py builds the rows, this module writes them):
* every dataset is written as CSV and / or JSONL; JSONL keeps real nulls, in CSV an empty cell means null (manifest: csv_null);
* times are UTC ISO-8601 (`*_utc` columns); data from MT5 may carry an extra broker server time column with an explicit `*_server` label and
  the basis is stated per column in the manifest - never an unlabelled local time;
* missing data stays null - NaN / Inf become null, nothing is replaced with 0;
* real and virtual data are never mixed: one dataset = one data kind (REAL / DEMO / VIRTUAL / SIMULATED / GAME / ...), one file per dataset;
* secrets never leave: values matching secret patterns or equal to a secret from SecretStore are replaced with [REDACTED] before writing,
  then the written bytes are scanned again (an export with a secret left in it is deleted and fails);
* an export folder appears atomically (written to a hidden `.partial` folder, then renamed) and is never overwritten.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
import secrets as _secrets
import shutil
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from ..secrets_store import ALLOWED as _SECRET_STORE_NAMES

SCHEMA_VERSION = "PMW-EXPORT-1.0.0"
FORMATS = ("csv", "jsonl")
DATA_KINDS = ("REAL", "DEMO", "VIRTUAL", "SIMULATED", "SYNTHETIC", "GAME", "USER_NOTE", "DERIVED", "REFERENCE", "CONFIG", "STATE", "PROVIDER")
TIME_BASES = ("UTC", "BROKER_SERVER_TIME", "UTC_EPOCH_SECONDS")
NAME_RX = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,63}$")
EXPORT_ID_RX = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,63}-\d{8}T\d{6}Z-[0-9a-f]{6}$")
REDACTED = "[REDACTED]"
# token-like values that must never be exported (Telegram bot token, Anthropic / generic API keys, private keys)
SECRET_PATTERNS = (
    re.compile(r"\b\d{6,12}:[A-Za-z0-9_\-]{30,}\b"),                     # Telegram bot token <id>:<35 chars>
    re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{16,}"),                          # Anthropic API key
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),                  # PEM private key
    # 1.46: was r"\bPMW1-PRIV-..." - a format that does not exist; the owner's licence private key (licensing/owner.py KEY_HEADER +
    # "seed: <64 hex>", the pattern of tools/verify_release.py) was neither redacted nor caught by leaks(). Also the JSON-escaped form.
    # 1.46: the header is written in two parts - this module ships in the CLIENT package, whose check (tools/verify_release.py
    # CLIENT_MARKERS) refuses any backend file containing the owner key header literally (= licence generator code)
    re.compile(r"PMW-OWNER-ED25519-" r"PRIVATE-KEY v1(?:\\r)?(?:\\n|\s)+seed:\s*[0-9a-fA-F]{64}"),
)
SECRET_NAMES = _SECRET_STORE_NAMES      # 1.46 arch (I0118): the SAME tuple as secrets_store.ALLOWED (one source), never a copy


class ExportError(RuntimeError):
    """Export failed (bad parameter, unsafe content, I/O). Never leaves a partial folder behind."""


@dataclass
class Dataset:
    """One output table. `name` becomes the file stem; `data_kind` labels what the rows are (one kind per dataset)."""
    name: str
    rows: list[dict]
    data_kind: str
    columns: list[str] | None = None
    time_columns: dict[str, str] = field(default_factory=dict)      # column -> UTC | BROKER_SERVER_TIME | UTC_EPOCH_SECONDS
    description: str = ""

    def __post_init__(self):
        if not NAME_RX.match(self.name):
            raise ExportError(f"BAD_DATASET_NAME: {self.name}")
        if self.data_kind not in DATA_KINDS:
            raise ExportError(f"BAD_DATA_KIND: {self.data_kind}")
        for c, basis in self.time_columns.items():
            if basis not in TIME_BASES:
                raise ExportError(f"BAD_TIME_BASIS: {c}={basis}")


@dataclass
class Collected:
    """What a source returns: datasets + provenance. status: OK | EMPTY | PARTIAL | UNAVAILABLE (reasons in notes)."""
    datasets: list[Dataset]
    provenance: dict
    status: str = "OK"
    notes: list[str] = field(default_factory=list)
    cleanup: list = field(default_factory=list)       # callables run after writing (e.g. close a read-only SQLite connection of a stream)


# ------------------------------------------------------------------------------------------------------------ value helpers
def utc_iso(value) -> str | None:
    """Epoch seconds / aware datetime / ISO string -> UTC ISO-8601 with Z; None, NaN, naive datetimes and garbage -> None (never a guess)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return None
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value):
            return None
        v = float(value)
        if v > 10_000_000_000:                     # milliseconds
            v /= 1000.0
        return datetime.fromtimestamp(v, timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
        return utc_iso(d)
    return None


def _clean(v):
    """JSON-safe value: NaN/Inf -> None, datetime -> UTC ISO, tuples -> lists, everything else unchanged (bool stays bool)."""
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, datetime):
        return utc_iso(v)
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, dict):
        return {str(k): _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    if isinstance(v, (bytes, bytearray)):
        return None
    return v


def known_secret_values(data_dir: Path | None = None) -> list[str]:
    """Secret values configured in this installation (environment / SecretStore). Used only to redact; never returned anywhere."""
    out: list[str] = []
    try:
        from ..secrets_store import SecretStore
        st = SecretStore(data_dir) if data_dir else SecretStore()
        for n in SECRET_NAMES:
            try:
                v = st.get(n)
            except Exception:  # noqa: BLE001 - an unreadable store means nothing to compare against
                v = None
            if v and len(v) >= 6:
                out.append(v)
    except Exception:  # noqa: BLE001
        pass
    for n in SECRET_NAMES:
        v = os.environ.get(n)
        if v and len(v.strip()) >= 6 and v.strip() not in out:
            out.append(v.strip())
    return out


class Redactor:
    def __init__(self, secret_values: list[str]):
        self.values = sorted({s for s in secret_values if s}, key=len, reverse=True)
        self.count = 0

    def text(self, s: str) -> str:
        for v in self.values:
            if v in s:
                self.count += s.count(v)
                s = s.replace(v, REDACTED)
        for rx in SECRET_PATTERNS:
            s, n = rx.subn(REDACTED, s)
            self.count += n
        return s

    def value(self, v):
        if isinstance(v, str):
            return self.text(v)
        if isinstance(v, dict):
            return {self.text(str(k)): self.value(x) for k, x in v.items()}
        if isinstance(v, list):
            return [self.value(x) for x in v]
        return v

    def leaks(self, blob: str) -> bool:
        return any(v in blob for v in self.values) or any(rx.search(blob) for rx in SECRET_PATTERNS)


def mask_account(key: str | None) -> str | None:
    """server:login -> server:***<last 3 digits of login>; keeps the account distinguishable without exporting the full login."""
    if not key:
        return key
    s = str(key)
    if ":" not in s:
        return "***" + s[-3:] if len(s) > 3 else "***"
    server, login = s.rsplit(":", 1)
    return f"{server}:***{login[-3:]}" if len(login) > 3 else f"{server}:***"


# ------------------------------------------------------------------------------------------------------------ writing
def _columns(ds: Dataset) -> list[str] | None:
    """Columns of a dataset: declared ones (+ any extra key met in a list), the union of keys of a list, None for an undeclared stream."""
    if not isinstance(ds.rows, list):
        return list(ds.columns) if ds.columns else None
    cols: dict[str, None] = dict.fromkeys(ds.columns or [])
    for r in ds.rows:
        for k in r:
            cols.setdefault(str(k), None)
    return list(cols)


def _csv_cell(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, sort_keys=True)
    return v


def _csv_line(values: list) -> str:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerow(values)
    return buf.getvalue()


class _Range:
    def __init__(self):
        self.lo = self.hi = None
        self.basis: list[str] = []

    def add(self, v):
        if isinstance(v, str) and v:
            self.lo = v if self.lo is None or v < self.lo else self.lo
            self.hi = v if self.hi is None or v > self.hi else self.hi

    def result(self) -> dict:
        if self.lo is None:
            return {"from_utc": None, "to_utc": None, "basis": self.basis, "status": "NO_TIMESTAMPS"}
        return {"from_utc": self.lo, "to_utc": self.hi, "basis": self.basis, "status": "OK"}


def _write_dataset(ds: Dataset, folder: Path, fmts: tuple, red: "Redactor", rng: _Range) -> tuple[int, list[str]]:
    """One pass over the rows (a list or a stream), every format written at once; each rendered line is checked for secrets."""
    cols = _columns(ds)
    rows = ds.rows
    if cols is None:                                   # undeclared stream: materialise once to learn the columns
        rows = list(rows)
        cols = _columns(Dataset(ds.name, rows, ds.data_kind))
    utc_cols = [c for c, b in ds.time_columns.items() if b == "UTC"]
    rng.basis += [f"{ds.name}.{c}" for c in utc_cols]
    handles = {f: open(folder / f"{ds.name}.{f}", "w", encoding="utf-8", newline="") for f in fmts}
    n = 0
    try:
        if "csv" in handles and cols:
            handles["csv"].write(_csv_line(cols))
        for raw in rows:
            r = red.value(_clean(dict(raw)))
            extra = [k for k in r if k not in cols]
            if extra:                                  # a stream may only carry declared columns (keeps CSV rectangular)
                raise ExportError(f"UNDECLARED_COLUMNS in {ds.name}: {extra[:5]}")
            for c in utc_cols:
                rng.add(r.get(c))
            for f, h in handles.items():
                line = (json.dumps({c: r.get(c) for c in cols}, ensure_ascii=False, allow_nan=False) + "\n" if f == "jsonl"
                        else _csv_line([_csv_cell(r.get(c)) for c in cols]))
                if red.leaks(line):                    # defence in depth: the rendered bytes are checked again
                    raise ExportError(f"SECRET_DETECTED in {ds.name}.{f}")
                h.write(line)
            n += 1
    finally:
        for h in handles.values():
            h.close()
    return n, cols


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def new_export_id(name: str, now: datetime | None = None) -> str:
    t = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    return f"{name}-{t}-{_secrets.token_hex(3)}"


def exports_root(data_dir: Path | None = None) -> Path:
    from .. import paths
    root = (data_dir or paths.data_dir()) / "exports"
    root.mkdir(parents=True, exist_ok=True)
    return root


def write_export(name: str, col: Collected, *, out_root: Path | None = None, formats=FORMATS, params: dict | None = None,
                 data_dir: Path | None = None, secret_values: list[str] | None = None, now: datetime | None = None) -> dict:
    """Write `col` under <out_root or <data>/exports>/<name>-<UTC stamp>-<rand>/ and return the manifest (also saved as manifest.json)."""
    from ..version import APP_NAME, APP_VERSION, DISPLAY_NAME
    if not NAME_RX.match(name):
        raise ExportError(f"BAD_EXPORT_NAME: {name}")
    fmts = tuple(dict.fromkeys(formats))
    if not fmts or any(f not in FORMATS for f in fmts):
        raise ExportError(f"BAD_FORMAT: {formats} (dozwolone: {FORMATS})")
    names = [d.name for d in col.datasets]
    if len(names) != len(set(names)):
        raise ExportError("DUPLICATE_DATASET_NAME")
    root = Path(out_root) if out_root else exports_root(data_dir)
    root.mkdir(parents=True, exist_ok=True)
    now = now or datetime.now(timezone.utc)
    export_id = new_export_id(name, now)
    final = root / export_id
    tmp = root / f".{export_id}.partial"
    if final.exists() or tmp.exists():
        raise ExportError("EXPORT_EXISTS")
    red = Redactor(known_secret_values(data_dir) if secret_values is None else secret_values)
    files, counts, rng = [], {}, _Range()
    tmp.mkdir(parents=True)
    try:
        for ds in col.datasets:
            n, cols = _write_dataset(ds, tmp, fmts, red, rng)
            counts[ds.name] = n
            for fmt in fmts:
                p = tmp / f"{ds.name}.{fmt}"
                files.append({"path": p.name, "dataset": ds.name, "format": fmt, "rows": n, "bytes": p.stat().st_size,
                              "sha256": sha256_file(p), "data_kind": ds.data_kind, "columns": cols, "time_columns": ds.time_columns,
                              "description": ds.description})
        total = sum(counts.values())
        status = col.status if col.status != "OK" else ("EMPTY" if total == 0 else "OK")
        manifest = {
            "schema_version": SCHEMA_VERSION, "export_id": export_id, "export_name": name, "status": status,
            "created_at_utc": utc_iso(now), "app": {"name": APP_NAME, "display_name": DISPLAY_NAME, "version": APP_VERSION},
            "provenance": _clean(red.value(col.provenance)), "params": _clean(red.value(params or {})), "date_range": rng.result(),
            "row_counts": counts, "total_rows": total, "formats": list(fmts), "files": files,
            "data_kinds": sorted({d.data_kind for d in col.datasets}), "csv_null": "puste pole CSV = null (brak danych, nigdy 0)",
            "time_policy": "kolumny *_utc = UTC ISO-8601; *_server = czas serwera brokera MT5 (etykieta w time_columns); brak czasu = null",
            "redactions": red.count, "notes": list(col.notes),
        }
        mtext = json.dumps(manifest, ensure_ascii=False, indent=1, allow_nan=False)
        if red.leaks(mtext):
            raise ExportError("SECRET_DETECTED in manifest")
        (tmp / "manifest.json").write_text(mtext, encoding="utf-8")
        os.replace(tmp, final)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    finally:
        for fn in col.cleanup:
            try:
                fn()
            except Exception:  # noqa: BLE001 - closing a read-only source never fails the export
                pass
    manifest["path"] = str(final)
    return manifest


def verify_export(folder: Path) -> dict:
    """Recompute every file hash / row count against manifest.json. Returns {ok, problems, manifest}."""
    folder = Path(folder)
    try:
        man = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"ok": False, "problems": [f"MANIFEST_UNREADABLE: {type(exc).__name__}"], "manifest": None}
    problems = []
    if man.get("schema_version") != SCHEMA_VERSION:
        problems.append(f"SCHEMA_VERSION: {man.get('schema_version')}")
    for f in man.get("files") or []:
        p = folder / str(f.get("path"))
        if p.resolve().parent != folder.resolve() or not p.is_file():
            problems.append(f"MISSING_OR_OUTSIDE: {f.get('path')}")
            continue
        if sha256_file(p) != f.get("sha256"):
            problems.append(f"SHA256_MISMATCH: {f['path']}")
        rows = read_rows(p)
        if len(rows) != f.get("rows"):
            problems.append(f"ROW_COUNT: {f['path']} {len(rows)} != {f.get('rows')}")
    return {"ok": not problems, "problems": problems, "manifest": man}


def read_rows(p: Path) -> list[dict]:
    """Rows of an exported file (JSONL: parsed objects; CSV: dicts of strings)."""
    p = Path(p)
    with open(p, encoding="utf-8", newline="") as f:
        if p.suffix == ".jsonl":
            return [json.loads(line) for line in f if line.strip()]
        return list(csv.DictReader(f))


def list_exports(data_dir: Path | None = None, name: str | None = None, limit: int = 50) -> list[dict]:
    root = exports_root(data_dir)
    out = []
    for d in sorted((p for p in root.iterdir() if p.is_dir() and EXPORT_ID_RX.match(p.name)), key=lambda p: p.name, reverse=True):
        try:
            m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if name and m.get("export_name") != name:
            continue
        out.append({k: m.get(k) for k in ("export_id", "export_name", "status", "created_at_utc", "total_rows", "row_counts", "date_range")})
        if len(out) >= limit:
            break
    return out


def export_dir(export_id: str, data_dir: Path | None = None) -> Path:
    """Folder of an export by id - id validated by regex, result guaranteed to be a direct child of <data>/exports (no traversal)."""
    if not isinstance(export_id, str) or not EXPORT_ID_RX.match(export_id):
        raise ExportError("BAD_EXPORT_ID")
    root = exports_root(data_dir)
    p = (root / export_id).resolve()
    if p.parent != root.resolve() or not p.is_dir():
        raise ExportError("EXPORT_NOT_FOUND")
    return p
