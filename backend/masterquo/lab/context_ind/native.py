"""VS07 native adapters: parity of own MQL5 PWM_VAMD / PWM_FractalRegime / PWM_SMCStructure against these Python cores on IDENTICAL OHLC +
inputs. Export (MQL5/Files/PMW/PWM_CONTEXT_EXPORT.txt, written by Scripts/PWM_ContextSelfTest.mq5, atomic tmp+move):
  line 1: header JSON {schema, seq, symbol, tf, tf_s, tick, vamd, fd, smc, seed_origin, build}
  next lines: CSV  bar_time,o,h,l,c,vamd_y,vamd_alpha,fd_bounded,fd_smooth,fd_zone,smc_trend,active_h,active_l,event_mask,pb_h,pb_l,st_h,st_l
              (closed bars from the indicator's first bar; EMPTY -> empty field; zone/trend as declared integer codes)
  last line: #sha256=<hex of all preceding bytes>
Structure is compared as the full per-bar event sequence (mask + confirmed/published prices), never a screenshot. A different seed origin is
PARITY_CONTEXT_MISMATCH. Status axes stay separate: OWN_IMPLEMENTATIONS_MATCH / NATIVE_COMPILED / NATIVE_EXECUTED."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import numpy as np

from . import fractal as FD
from . import smc as SM
from . import vamd as VM

SCHEMA = "PMW-CTX-EXPORT-1"
MAX_BYTES = 8 * 1024 * 1024
FIELDS = ["bar_time", "o", "h", "l", "c", "vamd_y", "vamd_alpha", "fd_bounded", "fd_smooth", "fd_zone", "smc_trend", "active_h", "active_l",
          "event_mask", "pb_h", "pb_l", "st_h", "st_l"]
ZONE = {None: 0, "NO_MOTION": 0, "TREND": 1, "NEUTRAL": 2, "CHOP": 3}
TREND = {"NONE": 0, "UP": 1, "DOWN": -1}
INTS = ("bar_time", "fd_zone", "smc_trend", "event_mask")


class CtxExportError(ValueError):
    pass


def _ts(x) -> float:
    return x if isinstance(x, (int, float)) else datetime.fromisoformat(str(x).replace("Z", "+00:00")).timestamp()


def reference_rows(bars: list[dict], vamd_cfg: dict | None, fd_cfg: dict | None, smc_cfg: dict | None, tick: float, tf_s: int) -> list[dict]:
    v, f, s = VM.VAMD(vamd_cfg), FD.FractalRegime(fd_cfg, tick), SM.SMC(tick=tick, **(smc_cfg or {}))
    out = []
    for b in bars:
        t = _ts(b["open_utc"])
        vr, fr, sr = v.update(b), f.update(b), s.update(b, t + tf_s)
        row = {"bar_time": int(t), "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"],
               "vamd_y": vr.get("y") if vr.get("status") == "READY" else None, "vamd_alpha": vr.get("alpha") if vr.get("status") == "READY" else None,
               "fd_bounded": fr.get("fd_bounded"), "fd_smooth": fr.get("fd_smooth"), "fd_zone": ZONE.get(fr.get("zone"), 0),
               "smc_trend": TREND[sr["trend"]], "event_mask": sr["event_mask"],
               "active_h": sr["slots"]["H"].get("level") if sr["slots"]["H"].get("status") == "ACTIVE" else None,
               "active_l": sr["slots"]["L"].get("level") if sr["slots"]["L"].get("status") == "ACTIVE" else None,
               "pb_h": None, "pb_l": None, "st_h": None, "st_l": None}
        i = len(s.bars) - 1
        for sw in s.pb.ledger[::-1]:
            if sw["confirming_bar"] != i:
                break
            row["pb_h" if sw["side"] == "H" else "pb_l"] = sw["price"]
        for e in sr["events"]:
            if e["kind"] in ("STRUCTURE_H", "STRUCTURE_L"):
                row["st_h" if e["kind"] == "STRUCTURE_H" else "st_l"] = e["price"]
        out.append(row)
    return out


def write_export(path: Path, header: dict, rows: list[dict]) -> None:
    body = json.dumps(dict(header, schema=SCHEMA), separators=(",", ":")) + "\n"
    for r in rows:
        body += ",".join("" if r.get(k) is None else (str(int(r[k])) if k in INTS else repr(float(r[k]))) for k in FIELDS) + "\n"
    tmp = Path(str(path) + ".tmp")
    tmp.write_bytes((body + "#sha256=" + hashlib.sha256(body.encode()).hexdigest() + "\n").encode())
    tmp.replace(path)


def parse_export(raw: bytes) -> dict:
    if len(raw) > MAX_BYTES:
        raise CtxExportError("EXPORT_TOO_LARGE")
    txt = raw.decode("utf-8", errors="strict").replace("\r\n", "\n")
    body, _, tail = txt.rstrip("\n").rpartition("\n")
    if not tail.startswith("#sha256="):
        raise CtxExportError("EXPORT_TRUNCATED")
    if hashlib.sha256((body + "\n").encode()).hexdigest() != tail[8:].strip():
        raise CtxExportError("EXPORT_CHECKSUM_MISMATCH")
    lines = body.split("\n")
    head = json.loads(lines[0])
    if head.get("schema") != SCHEMA:
        raise CtxExportError("EXPORT_SCHEMA_MISMATCH")
    rows = []
    for ln in lines[1:]:
        parts = ln.split(",")
        if len(parts) != len(FIELDS):
            raise CtxExportError("EXPORT_BAD_ROW")
        rows.append({k: (None if v == "" else (int(v) if k in INTS else float(v))) for k, v in zip(FIELDS, parts)})
    return {"header": head, "rows": rows}


def compare(export: dict, tol: float = 1e-7) -> dict:
    h, rows = export["header"], export["rows"]
    if not rows:
        return {"status": "NO_ROWS"}
    if h.get("seed_origin") != rows[0]["bar_time"]:
        return {"status": "PARITY_CONTEXT_MISMATCH", "reason": "eksport nie zaczyna się od pierwszego baru wskaźnika (seed origin)"}
    bars = [{"open_utc": r["bar_time"], "o": r["o"], "h": r["h"], "l": r["l"], "c": r["c"]} for r in rows]
    ref = reference_rows(bars, h.get("vamd"), h.get("fd"), h.get("smc"), float(h["tick"]), int(h["tf_s"]))
    bad = []
    for r, p in zip(rows, ref):
        for k in FIELDS[5:]:
            a, b = r[k], p[k]
            if k in INTS:
                ok = a == b
            elif a is None or b is None:
                ok = a is None and b is None
            else:
                ok = abs(a - b) <= tol * max(1.0, abs(b))
            if not ok:
                bad.append({"bar": r["bar_time"], "field": k, "native": a, "python": b})
    return {"status": "OWN_IMPLEMENTATIONS_MATCH" if not bad else "MISMATCH", "rows": len(rows), "mismatches": len(bad), "first": bad[:8],
            "tolerance_rel": tol, "structure_compare": "pełna sekwencja zdarzeń per bar (event_mask + ceny potwierdzeń/publikacji)"}


def native_status(status_file: Path | None) -> dict:
    if status_file is None or not Path(status_file).exists():
        return {"NATIVE_COMPILED": "NOT_EXECUTED_METAEDITOR_UNAVAILABLE", "NATIVE_EXECUTED": "NATIVE_NOT_EXECUTED"}
    st = json.loads(Path(status_file).read_text(encoding="utf-8"))
    res = st.get("selftest_result", "NATIVE_NOT_EXECUTED")
    live = Path(status_file).parent / "ctx_selftest.txt"                  # self-test runs in the terminal AFTER compilation
    if live.exists():
        txt = live.read_text(errors="replace")
        res = "PASS" if "RESULT=PASS" in txt else ("FAIL" if "RESULT=FAIL" in txt else res)
    return {"NATIVE_COMPILED": "PASS" if st.get("compile_errors") == 0 and st.get("ex5_sha256") else "FAIL",
            "NATIVE_EXECUTED": res, "metaeditor": st.get("log"), "ex5_sha256": st.get("ex5_sha256")}


def frozen_inputs(n: int = 400, seed: int = 14) -> list[dict]:
    r = np.random.default_rng(seed)
    c, out = 2000.0, []
    for i in range(n):
        o = c
        c = round(o + r.normal(0.02 * np.sin(i / 25.0), 0.6), 2)
        out.append({"open_utc": 1_700_000_100 + 300 * i, "o": o, "h": round(max(o, c) + abs(r.normal(0, .25)), 2),
                    "l": round(min(o, c) - abs(r.normal(0, .25)), 2), "c": c})
    return out


def make_golden(path: Path) -> dict:
    """Hand-derived Katz values (independent of the engine) + frozen-input reference rows for the native self-test."""
    import math
    gold = {"katz": [{"prices": [0, 1, 2, 3], "fd_raw": 1.0, "provenance": "monotonic: L=d=3 -> log3/log3 = 1"},
                     {"prices": [0, 1, 0, 1], "fd_raw": None, "fd_bounded": 2.0, "provenance": "L=3, d=1 -> den=log3+log(1/3)=0 -> saturation"},
                     {"prices": [0, 2, 1, 3], "fd_raw": math.log(3) / (math.log(3) + math.log(3 / 5)),
                      "provenance": "L=|2|+|1|+|2|=5, d=max|p-p0|=3 -> raw=log3/(log3+log(3/5))"}],
            "bars": frozen_inputs(), "tick": 0.01, "tf_s": 300}
    gold["reference_rows"] = reference_rows(gold["bars"], None, None, None, 0.01, 300)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(gold, indent=1), encoding="utf-8")
    return gold


def parity(fixtures: Path, status_file: Path | None = None, export: Path | None = None) -> dict:
    out = {"ORIGINAL_SOURCE_PARITY": "NOT_APPLICABLE (własne implementacje wg spec; brak oryginałów do porównania)", **native_status(status_file)}
    f = Path(export) if export else Path(fixtures) / "native_export.txt"
    if f.exists():
        try:
            out["OWN_IMPLEMENTATIONS"] = compare(parse_export(f.read_bytes()))
        except CtxExportError as exc:
            out["OWN_IMPLEMENTATIONS"] = {"status": "REJECTED", "reason": str(exc)}
    else:
        out["OWN_IMPLEMENTATIONS"] = {"status": "NOT_RUN", "reason": "brak eksportu PWM_ContextSelfTest (MetaEditor/terminal niedostępny)"}
    g = Path(fixtures) / "golden.json"
    if g.exists():
        gold = json.loads(g.read_text(encoding="utf-8"))
        errs = []
        for k in gold["katz"]:
            r = FD.katz(k["prices"])
            if k.get("fd_raw") is None:
                errs.append(0.0 if r["fd_raw"] is None and r["fd_bounded"] == k["fd_bounded"] else 1.0)
            else:
                errs.append(abs(r["fd_raw"] - k["fd_raw"]))
        ref = reference_rows(gold["bars"], None, None, None, gold["tick"], gold["tf_s"])
        same = ref == gold["reference_rows"]
        out["PYTHON_VS_GOLDEN"] = {"status": "PASS" if max(errs) < 1e-12 and same else "FAIL", "katz_max_err": max(errs), "reference_rows_equal": same}
    return out
