"""FF06 native adapters: parity of own MQL5 indicators vs the Python cores on frozen fixtures, and a read-only importer of the
MQ_FlowCollector export (MQL5/Files/PMW/PMW_FLOW_EXPORT.txt). Export format (text, atomic tmp+move):
  line 1: header JSON {schema, seq, symbol, tf, point, tick, clock_basis, heikin, stopdistance, sr, abi, build}
  next lines: CSV rows  bar_time,o,h,l,c,ha_o,ha_h,ha_l,ha_c,sd_range,sd_avg,sd_sugg,sup_lo,sup_hi,res_lo,res_hi,in_lo,in_hi  (closed bars,
  shift >= 1, EMPTY -> empty field)
  last line: #sha256=<hex of all preceding bytes>
Statuses are separate: OWN_IMPLEMENTATIONS_MATCH / ORIGINAL_SOURCE_PARITY_UNVERIFIED / NATIVE_COMPILED / NATIVE_EXECUTED; a different seed
origin or history length is PARITY_CONTEXT_MISMATCH, never a loose allclose."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import numpy as np

from . import heikin as HF
from . import stop_distance as SD

SCHEMA = "PMW-FLOW-EXPORT-1"
MAX_BYTES = 8 * 1024 * 1024
FIELDS = ["bar_time", "o", "h", "l", "c", "ha_o", "ha_h", "ha_l", "ha_c", "sd_range", "sd_avg", "sd_sugg", "sup_lo", "sup_hi", "res_lo", "res_hi",
          "in_lo", "in_hi"]


class FlowExportError(ValueError):
    pass


def parse_export(raw: bytes) -> dict:
    if len(raw) > MAX_BYTES:
        raise FlowExportError("EXPORT_TOO_LARGE")
    txt = raw.decode("utf-8", errors="strict")
    body, _, tail = txt.rstrip("\n").rpartition("\n")
    if not tail.startswith("#sha256="):
        raise FlowExportError("EXPORT_TRUNCATED")
    if hashlib.sha256((body + "\n").encode()).hexdigest() != tail[8:].strip():
        raise FlowExportError("EXPORT_CHECKSUM_MISMATCH")
    lines = body.split("\n")
    head = json.loads(lines[0])
    if head.get("schema") != SCHEMA:
        raise FlowExportError("EXPORT_SCHEMA_MISMATCH")
    rows = []
    for ln in lines[1:]:
        parts = ln.split(",")
        if len(parts) != len(FIELDS):
            raise FlowExportError("EXPORT_BAD_ROW")
        rows.append({k: (None if v == "" else (int(v) if k == "bar_time" else float(v))) for k, v in zip(FIELDS, parts)})
    return {"header": head, "rows": rows}


def write_export(path: Path, header: dict, rows: list[dict]) -> None:
    """Python writer of the same format (fixtures / tests)."""
    body = json.dumps(dict(header, schema=SCHEMA), separators=(",", ":")) + "\n"
    for r in rows:
        body += ",".join("" if r.get(k) is None else (str(int(r[k])) if k == "bar_time" else repr(float(r[k]))) for k in FIELDS) + "\n"
    tmp = Path(str(path) + ".tmp")
    tmp.write_bytes((body + "#sha256=" + hashlib.sha256(body.encode()).hexdigest() + "\n").encode())
    tmp.replace(path)


class FlowImporter:
    NAME = "PMW_FLOW_EXPORT.txt"

    def __init__(self, files_dir: str | None, symbol: str, tf: str = "M15", max_age_s: float = 3600.0):
        self.dir = Path(files_dir) if files_dir else None
        self.symbol, self.tf, self.max_age = symbol, tf, max_age_s
        self.last_seq = -1
        self.last = None

    def poll(self, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        if self.dir is None or not self.dir.is_dir():
            return {"status": "NATIVE_FEED_UNAVAILABLE", "reason": "brak MQ_MT5_FILES_DIR"}
        p = (self.dir / "PMW" / self.NAME)
        if p.resolve().parent != (self.dir / "PMW").resolve():
            return {"status": "REJECTED", "reason": "PATH_NOT_WHITELISTED"}
        if not p.exists():
            return {"status": "NATIVE_FEED_UNAVAILABLE", "reason": "brak eksportu kolektora"}
        try:
            ex = parse_export(p.read_bytes())
        except (FlowExportError, ValueError) as exc:
            return {"status": "REJECTED", "reason": str(exc)}
        h = ex["header"]
        if h.get("symbol") != self.symbol or h.get("tf") != self.tf:
            return {"status": "REJECTED", "reason": "CONTEXT_MISMATCH"}
        if int(h.get("seq", -1)) <= self.last_seq:
            return {"status": "STALE_SEQUENCE", "last": self.last}
        if now - float(h.get("written_at_utc", 0)) > self.max_age:
            return {"status": "REJECTED", "reason": "EXPORT_TOO_OLD"}
        self.last_seq = int(h["seq"])
        self.last = {"status": "IMPORTED", "header": h, "rows": len(ex["rows"]), "last_row": ex["rows"][-1] if ex["rows"] else None,
                     "role": "SHADOW_AUDIT", "clock_basis": h.get("clock_basis", "BROKER_WALL_TIME")}
        return self.last


def compare(export: dict, tol_price: float = 1e-6, tol_points: float = 1e-6) -> dict:
    """Recompute Heikin/StopDistance in Python on the SAME raw OHLC from the export (same seed origin) and compare per bar."""
    h = export["header"]
    rows = export["rows"]
    bars = [{"open_utc": r["bar_time"], "o": r["o"], "h": r["h"], "l": r["l"], "c": r["c"]} for r in rows]
    if not bars:
        return {"status": "NO_ROWS"}
    if h.get("seed_origin") != rows[0]["bar_time"]:
        return {"status": "PARITY_CONTEXT_MISMATCH", "reason": "eksport nie zaczyna się od początku historii wskaźnika (seed origin) – użyj InpBars=0"}
    hf = HF.heikin_series(bars, h.get("heikin"), h["point"])["rows"]
    sd = SD.series(bars, h.get("stopdistance"), h["point"], h.get("tick"))
    bad = []
    for i, r in enumerate(rows):
        for k, v in (("ha_o", hf[i]["o"]), ("ha_h", hf[i]["h"]), ("ha_l", hf[i]["l"]), ("ha_c", hf[i]["c"])):
            if r[k] is None or abs(r[k] - v) > tol_price * max(1.0, abs(v)):
                bad.append({"bar": r["bar_time"], "field": k, "native": r[k], "python": v})
        for k, v in (("sd_range", sd[i]["range_points"]), ("sd_avg", sd[i]["average_points"]), ("sd_sugg", sd[i]["suggested_points"])):
            if (v is None) != (r[k] is None) or (v is not None and abs(r[k] - v) > tol_points * max(1.0, abs(v))):
                bad.append({"bar": r["bar_time"], "field": k, "native": r[k], "python": v})
    return {"status": "OWN_IMPLEMENTATIONS_MATCH" if not bad else "MISMATCH", "rows": len(rows), "mismatches": len(bad), "first": bad[:5],
            "tolerance": {"price_rel": tol_price, "points_rel": tol_points}}


def native_status(status_file: Path | None) -> dict:
    if status_file is None or not Path(status_file).exists():
        return {"NATIVE_COMPILED": "NOT_COMPILED_NO_METAEDITOR", "NATIVE_EXECUTED": "NATIVE_NOT_EXECUTED"}
    st = json.loads(Path(status_file).read_text(encoding="utf-8"))
    return {"NATIVE_COMPILED": "PASS" if st.get("compile_errors") == 0 and st.get("ex5_sha256") else "FAIL",
            "NATIVE_EXECUTED": st.get("selftest_result", "NATIVE_NOT_EXECUTED"), "ex5_sha256": st.get("ex5_sha256")}


def parity(fixtures: Path, status_file: Path | None = None) -> dict:
    out = {"ORIGINAL_SOURCE_PARITY": "UNVERIFIED (QCL/SR/StopDistance MQ5 nieodczytane)", **native_status(status_file)}
    f = Path(fixtures) / "native_export.txt"
    if f.exists():
        try:
            out["OWN_IMPLEMENTATIONS"] = compare(parse_export(f.read_bytes()))
        except FlowExportError as exc:
            out["OWN_IMPLEMENTATIONS"] = {"status": "REJECTED", "reason": str(exc)}
    else:
        out["OWN_IMPLEMENTATIONS"] = {"status": "NOT_RUN", "reason": "brak eksportu natywnego kolektora (MetaEditor/terminal niedostępny)"}
    g = Path(fixtures) / "golden.json"
    if g.exists():
        gold = json.loads(g.read_text(encoding="utf-8"))
        rows = HF.heikin_series(gold["bars"], gold["heikin"], gold["point"])["rows"]
        err = max(abs(r["c"] - e) for r, e in zip(rows, gold["expected_ha_close"]))
        out["PYTHON_VS_GOLDEN"] = {"status": "PASS" if err < 1e-9 else "FAIL", "max_abs_err": err, "provenance": gold.get("provenance")}
    return out


def make_golden(path: Path) -> dict:
    """Golden fixture with HAND-derived expected values (P1=P2=1 SMA: HA from raw OHLC directly) - independent of the MA engine."""
    bars = [{"open_utc": 1_700_000_000 + 60 * i, "o": o, "h": h, "l": l_, "c": c}
            for i, (o, h, l_, c) in enumerate([(10, 12, 9, 11), (11, 13, 10, 12), (12, 12.5, 9.5, 10), (10, 11, 8, 9)])]
    ha_c = [(b["o"] + b["h"] + b["l"] + b["c"]) / 4 for b in bars]
    gold = {"bars": bars, "heikin": {"ma1": "SMA", "p1": 1, "ma2": "SMA", "p2": 1}, "point": 0.01, "expected_ha_close": ha_c,
            "provenance": "ręcznie: HA_close=(O+H+L+C)/4 przy P1=P2=1 (identity MA)"}
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(gold, indent=1), encoding="utf-8")
    return gold


def frozen_inputs(n: int = 300, seed: int = 3) -> list[dict]:
    r = np.random.default_rng(seed)
    c, out = 2000.0, []
    for i in range(n):
        o = c
        c = round(o + r.normal(0, 0.5), 2)
        out.append({"open_utc": 1_700_000_000 + 900 * i, "o": o, "h": round(max(o, c) + abs(r.normal(0, .2)), 2), "l": round(min(o, c) - abs(r.normal(0, .2)), 2), "c": c})
    return out
