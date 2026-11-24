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
import math
import time
from pathlib import Path

import numpy as np

from .. import native_selftest as NS
from . import heikin as HF
from . import sr_channels as SR
from . import stop_distance as SD

SCHEMA = "PMW-FLOW-EXPORT-1"
# 1.46: was 8 MB - MQ_FlowCollector with the default InpBars=0 (full history, needed for parity) writes ~190-300 B per bar (18 fields,
# DoubleToString(v, 10)), so 100k bars (MT5 default 'Max bars in chart') = 18-30 MB and the feed / parity were always REJECTED.
MAX_BYTES = 64 * 1024 * 1024
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
    if not isinstance(head, dict) or head.get("schema") != SCHEMA:          # 1.46: a non-object header was an AttributeError (500)
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
        try:                                         # 1.46: seq null/'abc' or written_at_utc null were a 500 in GET /flow-context/native
            seq, written = int(h.get("seq", -1)), float(h.get("written_at_utc", 0))
            if not math.isfinite(written):
                raise ValueError("written_at_utc")
        except (TypeError, ValueError, OverflowError):
            return {"status": "REJECTED", "reason": "HEADER_FORMAT"}
        if seq <= self.last_seq:
            return {"status": "STALE_SEQUENCE", "last": self.last}
        if now - written > self.max_age:
            return {"status": "REJECTED", "reason": "EXPORT_TOO_OLD"}
        self.last_seq = seq
        self.last = {"status": "IMPORTED", "header": h, "rows": len(ex["rows"]), "last_row": ex["rows"][-1] if ex["rows"] else None,
                     "role": "SHADOW_AUDIT", "clock_basis": h.get("clock_basis", "BROKER_WALL_TIME")}
        return self.last


SR_KEYS = ("depth", "retention", "loopback", "width_pct", "max_selected", "source")
SR_LAST_ROWS = 2000              # MQ_SRChannels computes the last 2000 closed bars on its first calculation (older rows stay EMPTY)


def _compare_sr(h: dict, rows: list[dict], bars: list[dict], tol_price: float, last: int) -> tuple[dict, list[dict]]:
    """1.46 arch I0517: the S/R columns (nearest support / resistance / inside band of MQ_SRChannels, relative to each closed bar's own
    close) against sr_channels.channels_at + nearest on the same OHLC. Only with the indicator configuration in the header ('sr', written
    by MQ_FlowCollector) - without it NOT_COMPARED, never a guessed configuration."""
    cfg = h.get("sr")
    if not isinstance(cfg, dict):
        return {"status": "NOT_COMPARED (brak konfiguracji 'sr' w nagłówku eksportu – stary kolektor)"}, []
    cfg = {k: cfg[k] for k in SR_KEYS if k in cfg}
    c = SR.validate(cfg)
    piv = SR.pivots(bars, int(c["depth"]), c["source"])          # all pivots once; channels_at keeps those confirmed at <= t
    start = max(0, len(rows) - last)
    bad = []
    for i in range(start, len(rows)):
        r = rows[i]
        nr = SR.nearest(SR.channels_at(bars, i, cfg, piv=piv), bars[i]["c"])
        for kind, pre in (("support", "sup"), ("resistance", "res"), ("inside", "in")):
            band = nr[kind]
            for k, v in ((f"{pre}_lo", band["lo"] if band else None), (f"{pre}_hi", band["hi"] if band else None)):
                if (v is None) != (r[k] is None) or (v is not None and abs(r[k] - v) > tol_price * max(1.0, abs(v))):
                    bad.append({"bar": r["bar_time"], "field": k, "native": r[k], "python": v})
    return {"status": "MATCH" if not bad else "MISMATCH", "rows_compared": len(rows) - start, "first_row": start, "mismatches": len(bad),
            "config": cfg}, bad


def compare(export: dict, tol_price: float = 1e-6, tol_points: float = 1e-6, sr_last: int = SR_LAST_ROWS) -> dict:
    """Recompute Heikin/StopDistance (every row) and the S/R bands (last `sr_last` rows, when the header declares 'sr') in Python on the
    SAME raw OHLC from the export (same seed origin) and compare per bar."""
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
    sr, sr_bad = _compare_sr(h, rows, bars, tol_price, sr_last)
    return {"status": "OWN_IMPLEMENTATIONS_MATCH" if not bad and not sr_bad else "MISMATCH", "rows": len(rows), "mismatches": len(bad) + len(sr_bad),
            "first": (bad + sr_bad)[:5], "tolerance": {"price_rel": tol_price, "points_rel": tol_points},
            "sr_status": sr["status"], "sr_mismatches": len(sr_bad), "sr": sr}


def native_status(status_file: Path | None) -> dict:
    """1.46 arch (I0519): 28_FLOW_CONTEXT.bat writes the status before the self-test runs in the terminal - flow_selftest.txt of this build
    (not older than the status file) is read live (lab/native_selftest.py)."""
    if status_file is None or not Path(status_file).exists():
        return {"NATIVE_COMPILED": NS.NOT_COMPILED, "NATIVE_EXECUTED": NS.NOT_EXECUTED}
    st = json.loads(Path(status_file).read_text(encoding="utf-8"))
    res, _ = NS.executed(st, Path(status_file), "flow_selftest.txt")
    return {"NATIVE_COMPILED": "PASS" if st.get("compile_errors") == 0 and st.get("ex5_sha256") else "FAIL",
            "NATIVE_EXECUTED": res, "ex5_sha256": st.get("ex5_sha256")}


def parity(fixtures: Path, status_file: Path | None = None, export: Path | None = None) -> dict:
    """export: the collector's file (MQL5/Files/PMW/PMW_FLOW_EXPORT.txt) when given and present, else <fixtures>/native_export.txt
    (1.46 arch I0518: only the fixture name was read - the collector's export had to be copied / renamed by hand)."""
    out = {"ORIGINAL_SOURCE_PARITY": "UNVERIFIED (QCL/SR/StopDistance MQ5 nieodczytane)", **native_status(status_file)}
    f = Path(export) if export is not None and Path(export).exists() else Path(fixtures) / "native_export.txt"
    out["export_file"] = str(f)
    if f.exists():
        try:
            out["OWN_IMPLEMENTATIONS"] = compare(parse_export(f.read_bytes()))
        except (FlowExportError, ValueError, TypeError, KeyError) as exc:    # 1.46: bad numbers / header in the export (was FlowExportError only)
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
