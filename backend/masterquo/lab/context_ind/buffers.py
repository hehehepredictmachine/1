"""VS06 Buffer Inspector + bridge (Python side). Producers: mql5/ContextIndicators/Scripts/PWM_BufferInspector.mq5 (one-off report)
and Indicators/PWM_IndicatorBridge.mq5 (continuous export of VERIFIED mappings only). Both use the outer envelope of extind.contract
({envelope, checksum = sha256(body text), body}) with their own schemas:
  pmw-bufreport-1   report: terminal build, capability probe per buffer type, charts/windows/instances (duplicate short names flagged),
                    per buffer READABLE/PENDING/UNREADABLE + streaming stats (count, finite/nonempty/zero, min/max, small-int set,
                    density, last values/times) and the scan range (FULL 0..511 or PARTIAL_INDEX_RANGE).
  pmw-bufbridge-1   bridge: mapping_id/version, source identity, epoch/seq, symbol/tf, rows of closed bars {source_bar, raw, empty} +
                    heartbeat; observed time = export time (never back-dated to the arrow's origin).
Heuristic type (LINE_LIKE / SPARSE_EVENT_LIKE / INTEGER_STATE_LIKE / EMPTY_OBSERVED / UNKNOWN) is a hypothesis with confidence/reasons,
never a declared role. A mapping becomes VERIFIED only with every decision field present (units, direction semantics, empty sentinel and
whether 0 is valid, shift policy incl. PLOT_SHIFT, confirmation/repaint policy, source identity); otherwise MAPPING_INCOMPLETE and the source
is diagnostic only. Nothing here derives BUY/SELL from colours, executes text or loads pickle; paths are whitelisted."""
from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
from pathlib import Path

from ...extind.contract import EnvelopeError, checksum

REPORT_SCHEMA = "pmw-bufreport-1"
BRIDGE_SCHEMA = "pmw-bufbridge-1"
EMPTY_VALUE = 1.7976931348623157e308
MAX_BYTES = 4_000_000
TYPES = ("LINE_LIKE", "SPARSE_EVENT_LIKE", "INTEGER_STATE_LIKE", "EMPTY_OBSERVED", "UNKNOWN")
MAPPING_REQUIRED = ("indicator_path", "input_hash", "buffer", "units", "direction_semantics", "empty_sentinel", "zero_is_valid", "shift_policy",
                    "plot_shift", "confirmation_policy", "symbol", "tf")
_TEXT_FIELDS = ("indicator_path", "input_hash", "units", "direction_semantics", "shift_policy", "confirmation_policy", "symbol", "tf")
_MAP_LOCK = threading.RLock()             # 1.46: save/rollback were unlocked load-modify-write from the FastAPI thread pool


def _write_atomic(p: Path, txt: str) -> None:
    """1.46: unique tmp + os.replace - a fixed '.tmp' name was shared by concurrent writers and rollback / report import wrote in place."""
    tmp = p.with_name(f".{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(txt, encoding="utf-8")
    os.replace(tmp, p)


def wrap(schema: str, body: dict) -> bytes:
    txt = json.dumps(dict(body, schema_version=schema), ensure_ascii=False, separators=(",", ":"))
    return json.dumps({"envelope": schema, "checksum": checksum(txt), "body": txt}, ensure_ascii=False).encode("utf-8")


def unwrap(raw: bytes, schema: str) -> dict:
    if len(raw) > MAX_BYTES:
        raise EnvelopeError("ENVELOPE_TOO_LARGE")
    try:
        outer = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise EnvelopeError("ENVELOPE_NOT_JSON") from exc
    if not isinstance(outer, dict) or outer.get("envelope") != schema or not isinstance(outer.get("body"), str):
        raise EnvelopeError("ENVELOPE_FORMAT")
    if checksum(outer["body"]) != outer.get("checksum"):
        raise EnvelopeError("CHECKSUM_MISMATCH")
    try:
        d = json.loads(outer["body"])
    except ValueError as exc:                                   # 1.46: a non-JSON body with a matching checksum was a 500
        raise EnvelopeError("BODY_NOT_JSON") from exc
    if not isinstance(d, dict) or d.get("schema_version") != schema:
        raise EnvelopeError("SCHEMA_UNSUPPORTED")
    return d


# ===================================================================== heuristics (same rules as the MQL5 inspector)
def classify(values: list[float | None], empty_sentinel: float | None = None) -> dict:
    """values oldest->newest as read (EMPTY_VALUE -> None). Returns hypothesis + confidence + reasons; never a declared role."""
    vals = [None if (v is None or abs(v) >= EMPTY_VALUE * 0.999 or (empty_sentinel is not None and v == empty_sentinel)) else v for v in values]
    n = len(vals)
    fin = [v for v in vals if v is not None and math.isfinite(v)]
    if n == 0:
        return {"type": "UNKNOWN", "confidence": 0.0, "reasons": ["NO_SAMPLES"]}
    if not fin:
        return {"type": "EMPTY_OBSERVED", "confidence": 0.6 if n >= 200 else 0.3,
                "reasons": ["brak niepustych wartości w próbce (mała próbka nie dowodzi braku sygnałów)" if n < 200 else "pusty w całej próbce"]}
    density = len(fin) / n
    ints = all(float(v).is_integer() for v in fin)
    uniq = len(set(fin))
    zeros = sum(1 for v in fin if v == 0)
    st = {"density": density, "unique": uniq, "zeros": zeros, "min": min(fin), "max": max(fin)}
    if density < 0.2:
        return {"type": "SPARSE_EVENT_LIKE", "confidence": 0.6 if n >= 200 else 0.35, "stats": st,
                "reasons": ["rzadkie niepuste wartości – może to być znacznik, nie musi być strzałką"], "alternatives": ["UNKNOWN"]}
    if ints and uniq <= 8:
        return {"type": "INTEGER_STATE_LIKE", "confidence": 0.5, "stats": st,
                "reasons": ["małe liczby całkowite – może to być indeks koloru, stan albo linia; 0/1 nie potwierdza COLOR_INDEX"],
                "alternatives": ["LINE_LIKE", "UNKNOWN"]}
    if density >= 0.8:
        return {"type": "LINE_LIKE", "confidence": 0.6, "stats": st, "reasons": ["gęsta seria ciągła"], "alternatives": ["UNKNOWN"]}
    return {"type": "UNKNOWN", "confidence": 0.2, "stats": st, "reasons": ["mieszany wzorzec"]}


# ===================================================================== reports
def reports_dir() -> Path:
    import mq_instruments
    d = mq_instruments.data_dir() / "context_ind" / "buffer_reports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _num_or_none(v) -> bool:
    return v is None or (isinstance(v, (int, float)) and not isinstance(v, bool))


def _check_report(d: dict) -> None:
    """1.46: structure of the report body - instances/buffers that are not objects or a non-numeric sample were an
    AttributeError/TypeError (500 in POST /lab/buffers/reports/import) instead of a rejected report."""
    inst = d.get("instances")
    if inst is not None and (not isinstance(inst, list) or not all(isinstance(i, dict) for i in inst)):
        raise EnvelopeError("REPORT_FORMAT:instances")
    for i in inst or []:
        bufs = i.get("buffers")
        if bufs is not None and (not isinstance(bufs, list) or not all(isinstance(b, dict) for b in bufs)):
            raise EnvelopeError("REPORT_FORMAT:buffers")
        for b in bufs or []:
            if "sample" in b and (not isinstance(b["sample"], list) or not all(_num_or_none(v) for v in b["sample"])):
                raise EnvelopeError("REPORT_FORMAT:sample")
    if d.get("scan_range") is not None and not isinstance(d["scan_range"], dict):
        raise EnvelopeError("REPORT_FORMAT:scan_range")


def import_report(raw: bytes) -> dict:
    d = unwrap(raw, REPORT_SCHEMA)
    _check_report(d)
    inst = d.get("instances") or []
    names = [i.get("short_name") for i in inst]
    for i in inst:
        i["ambiguous"] = names.count(i.get("short_name")) > 1                 # duplicate short names are never merged
        for b in i.get("buffers") or []:
            if b.get("status") == "READABLE" and "sample" in b:
                b["hypothesis"] = classify(b["sample"])
            elif b.get("status") != "READABLE":
                b["hypothesis"] = {"type": "UNKNOWN", "confidence": 0.0, "reasons": [f"status {b.get('status')}"]}
    rng = d.get("scan_range") or {}
    d["coverage"] = "FULL_0_511" if rng.get("from") == 0 and rng.get("to") == 511 else "PARTIAL_INDEX_RANGE"
    rid = "BR-" + hashlib.sha256(raw).hexdigest()[:16]
    d["report_id"] = rid
    d["imported_at"] = time.time()
    _write_atomic(reports_dir() / f"{rid}.json", json.dumps(d, indent=1))   # 1.46: atomic (a cut write broke list_reports for good)
    return d


def _read_report(f: Path) -> dict | None:
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def list_reports() -> list[dict]:
    out = []
    for f in sorted(reports_dir().glob("BR-*.json")):
        d = _read_report(f)
        if d is None:                       # 1.46: one unreadable BR-*.json was a permanent 500 for the whole list; the file is kept as is
            out.append({"report_id": f.stem, "status": "CORRUPT", "instances": 0})
            continue
        out.append({"report_id": d.get("report_id") or f.stem, "terminal_build": d.get("terminal_build"), "symbol": d.get("symbol"), "tf": d.get("tf"),
                     "instances": len(d.get("instances") or []), "coverage": d.get("coverage"), "capability": d.get("capability"),
                     "imported_at": d.get("imported_at")})
    return out


def get_report(rid: str) -> dict | None:
    if not rid.startswith("BR-") or not all(c.isalnum() or c == "-" for c in rid):
        return None
    f = reports_dir() / f"{rid}.json"
    if not f.exists():
        return None
    return _read_report(f) or {"report_id": rid, "status": "CORRUPT", "instances": []}      # 1.46: no 500 on a damaged report


# ===================================================================== mappings
def mappings_path() -> Path:
    return reports_dir().parent / "buffer_mappings.json"


def _load_maps(strict: bool = False) -> dict:
    p = mappings_path()
    if not p.exists():
        return {"mappings": {}, "history": []}
    try:
        st = json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        st = None
    if not isinstance(st, dict) or not isinstance(st.get("mappings"), dict) or not isinstance(st.get("history"), list):
        # 1.46: a damaged buffer_mappings.json was a 500 in every mapping route and /lab/buffers/source. Reads see no mappings;
        # writes refuse instead of overwriting the user's file.
        if strict:
            raise ValueError("MAPPINGS_CORRUPT")
        return {"mappings": {}, "history": [], "corrupt": True}
    return st


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _type_problems(m: dict) -> list[str]:
    """1.46: field types were not checked - buffer 'abc' / 3.7, zero_is_valid 'false' (truthy), any plot_shift or sentinel got
    VERIFIED_TECHNICAL. Values outside the type are a problem (MAPPING_INCOMPLETE); missing fields are reported separately."""
    bad = []
    if m.get("buffer") not in (None, "") and (isinstance(m["buffer"], bool) or not isinstance(m["buffer"], int)):
        bad.append("buffer")
    if m.get("zero_is_valid") not in (None, "") and not isinstance(m["zero_is_valid"], bool):
        bad.append("zero_is_valid")
    ps = m.get("plot_shift")
    if ps not in (None, "", "UNKNOWN") and (isinstance(ps, bool) or not isinstance(ps, int)):
        bad.append("plot_shift")
    es = m.get("empty_sentinel")
    if es not in (None, "", "EMPTY_VALUE") and not _is_num(es):
        bad.append("empty_sentinel")
    bad += [k for k in _TEXT_FIELDS if m.get(k) not in (None, "") and not isinstance(m[k], str)]
    return [f"FIELD_TYPE_INVALID:{k}" for k in bad]


def validate_mapping(m: dict) -> dict:
    missing = [k for k in MAPPING_REQUIRED if m.get(k) in (None, "")]
    problems = _type_problems(m)
    if m.get("plot_shift") == "UNKNOWN":
        problems.append("PLOT_SHIFT_UNKNOWN (brak automatycznego odczytu PLOT_SHIFT obcego wskaźnika – wymagany jawny preset)")
    if m.get("direction_semantics") in ("COLOR_GUESS", "AUTO"):
        problems.append("DIRECTION_FROM_COLOR_NOT_ALLOWED")
    if isinstance(m.get("buffer"), int) and not 0 <= m["buffer"] <= 511:
        problems.append("BUFFER_OUT_OF_RANGE")
    status = "VERIFIED_TECHNICAL" if not missing and not problems else "MAPPING_INCOMPLETE"
    return {"status": status, "missing": missing, "problems": problems,
            "note": "techniczna weryfikacja mapowania nie jest certyfikacją sygnału ani zgodą na handel"}


def save_mapping(m: dict) -> dict:
    v = validate_mapping(m)
    with _MAP_LOCK:
        return _save_mapping_locked(m, v)


def _save_mapping_locked(m: dict, v: dict) -> dict:
    st = _load_maps(strict=True)
    ident = json.dumps({k: m.get(k) for k in ("indicator_path", "input_hash", "buffer", "symbol", "tf", "chart_window", "instance")}, sort_keys=True)
    mid = "BM-" + hashlib.sha256(ident.encode()).hexdigest()[:12]
    prev = st["mappings"].get(mid)
    rec = dict(m, mapping_id=mid, mapper_version=(prev or {}).get("mapper_version", 0) + 1, validation=v, saved_at=time.time())
    st["mappings"][mid] = rec
    st["history"].append({"mapping_id": mid, "from": (prev or {}).get("mapper_version"), "to": rec["mapper_version"], "at": rec["saved_at"]})
    _write_atomic(mappings_path(), json.dumps(st, indent=1))
    return rec


def rollback_mapping(mid: str) -> dict:
    with _MAP_LOCK:                                       # 1.46: locked + atomic (was an unlocked in-place write_text)
        st = _load_maps(strict=True)
        if mid not in st["mappings"]:
            raise ValueError("MAPPING_NOT_FOUND")
        st["mappings"].pop(mid)
        st["history"].append({"mapping_id": mid, "removed": True, "at": time.time()})
        _write_atomic(mappings_path(), json.dumps(st, indent=1))
    return {"ok": True}


def mappings() -> dict:
    return _load_maps()["mappings"]


# ===================================================================== bridge import (whitelisted dir, idempotent)
class BridgeImporter:
    NAME = "PWM_BUFFER_BRIDGE.json"

    def __init__(self, files_dir: str | None, ttl_s: float = 600.0):
        self.dir = Path(files_dir) if files_dir else None
        self.ttl = ttl_s
        self.seen: dict = {}
        self.last: dict | None = None

    def poll(self, symbol: str, tf: str, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        if self.dir is None or not self.dir.is_dir():
            return {"status": "UNAVAILABLE", "reason": "brak MQ_MT5_FILES_DIR – źródło zewnętrzne niedostępne; własne VAMD/FD/SMC działają"}
        p = self.dir / "PMW" / self.NAME
        if p.resolve().parent != (self.dir / "PMW").resolve():
            return {"status": "REJECTED", "reason": "PATH_NOT_WHITELISTED"}
        if not p.exists():
            return {"status": "UNAVAILABLE", "reason": "brak pliku mostka"}
        try:
            d = unwrap(p.read_bytes(), BRIDGE_SCHEMA)
        except (EnvelopeError, ValueError) as exc:
            return {"status": "REJECTED", "reason": str(exc)}
        if d.get("symbol") != symbol or d.get("tf") != tf:
            return {"status": "REJECTED", "reason": "CONTEXT_MISMATCH"}
        # 1.46: seq 'x', heartbeat null/NaN, rows of non-objects or a list mapping_id were a 500 in GET /lab/buffers/source
        try:
            if not isinstance(d.get("mapping_id"), str) or isinstance(d.get("epoch"), (list, dict)):
                raise TypeError("FIELD_TYPE")
            seq, hb = int(d.get("seq", -1)), float(d.get("heartbeat_utc", 0))
            rows_in = d.get("rows") or []
            if not math.isfinite(hb) or not isinstance(rows_in, list) or not all(isinstance(r, dict) for r in rows_in):
                raise TypeError("FIELD_TYPE")
        except (TypeError, ValueError, OverflowError):
            return {"status": "REJECTED", "reason": "FIELD_TYPE"}
        mp = mappings().get(d["mapping_id"])
        if not mp or mp["mapper_version"] != d.get("mapper_version"):
            return {"status": "MISSING_MAPPING", "reason": "brak zgodnego mapowania w bocie"}
        if mp["validation"]["status"] != "VERIFIED_TECHNICAL":
            return {"status": "MAPPING_INCOMPLETE", "reason": ", ".join(mp["validation"]["missing"] + mp["validation"]["problems"])}
        key = (d["mapping_id"], d.get("epoch"))
        if self.seen.get(key, -1) >= seq:
            return dict(self.last or {}, status="STALE_SEQUENCE") if self.last else {"status": "STALE_SEQUENCE"}
        if now - hb > self.ttl:
            return {"status": "STALE", "reason": "heartbeat starszy niż TTL"}
        zero_ok = mp.get("zero_is_valid") is True
        sent = mp.get("empty_sentinel")
        rows = []
        for r in rows_in:
            v = r.get("raw")
            if v is not None and (not isinstance(v, (int, float)) or not math.isfinite(v)):
                return {"status": "REJECTED", "reason": "NON_FINITE_VALUE"}
            # 1.46: zero_is_valid=False was honoured only when the sentinel itself was 0 - with EMPTY_VALUE a raw 0 came out as a real 0.0
            empty = (v is None or abs(v) >= EMPTY_VALUE * 0.999 or (v == 0 and not zero_ok)
                     or (sent not in (None, "EMPTY_VALUE") and v == sent and not (v == 0 and zero_ok)))
            rows.append({"source_bar": r.get("source_bar"), "value": None if empty else v, "empty": empty})
        self.seen[key] = seq
        self.last = {"status": "AVAILABLE_UNVALIDATED", "mapping_id": d["mapping_id"], "units": mp["units"], "rows": rows[-200:],
                     "observed_at": d.get("heartbeat_utc"), "known_at_basis": "EXPORT_TIME (historyczne znaczniki nie dostają dawnego known_at)",
                     "role": "DIAGNOSTIC / SHADOW – bez wpływu na decyzje do testu przyrostowego"}
        return self.last
