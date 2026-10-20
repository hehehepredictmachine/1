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
    d = json.loads(outer["body"])
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


def import_report(raw: bytes) -> dict:
    d = unwrap(raw, REPORT_SCHEMA)
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
    (reports_dir() / f"{rid}.json").write_text(json.dumps(d, indent=1), encoding="utf-8")
    return d


def list_reports() -> list[dict]:
    out = []
    for f in sorted(reports_dir().glob("BR-*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        out.append({"report_id": d["report_id"], "terminal_build": d.get("terminal_build"), "symbol": d.get("symbol"), "tf": d.get("tf"),
                     "instances": len(d.get("instances") or []), "coverage": d.get("coverage"), "capability": d.get("capability"),
                     "imported_at": d.get("imported_at")})
    return out


def get_report(rid: str) -> dict | None:
    if not rid.startswith("BR-") or not all(c.isalnum() or c == "-" for c in rid):
        return None
    f = reports_dir() / f"{rid}.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


# ===================================================================== mappings
def mappings_path() -> Path:
    return reports_dir().parent / "buffer_mappings.json"


def _load_maps() -> dict:
    p = mappings_path()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"mappings": {}, "history": []}


def validate_mapping(m: dict) -> dict:
    missing = [k for k in MAPPING_REQUIRED if m.get(k) in (None, "")]
    problems = []
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
    st = _load_maps()
    ident = json.dumps({k: m.get(k) for k in ("indicator_path", "input_hash", "buffer", "symbol", "tf", "chart_window", "instance")}, sort_keys=True)
    mid = "BM-" + hashlib.sha256(ident.encode()).hexdigest()[:12]
    prev = st["mappings"].get(mid)
    rec = dict(m, mapping_id=mid, mapper_version=(prev or {}).get("mapper_version", 0) + 1, validation=v, saved_at=time.time())
    st["mappings"][mid] = rec
    st["history"].append({"mapping_id": mid, "from": (prev or {}).get("mapper_version"), "to": rec["mapper_version"], "at": rec["saved_at"]})
    tmp = mappings_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1), encoding="utf-8")
    tmp.replace(mappings_path())
    return rec


def rollback_mapping(mid: str) -> dict:
    st = _load_maps()
    if mid not in st["mappings"]:
        raise ValueError("MAPPING_NOT_FOUND")
    st["mappings"].pop(mid)
    st["history"].append({"mapping_id": mid, "removed": True, "at": time.time()})
    mappings_path().write_text(json.dumps(st, indent=1), encoding="utf-8")
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
        mp = mappings().get(d.get("mapping_id"))
        if not mp or mp["mapper_version"] != d.get("mapper_version"):
            return {"status": "MISSING_MAPPING", "reason": "brak zgodnego mapowania w bocie"}
        if mp["validation"]["status"] != "VERIFIED_TECHNICAL":
            return {"status": "MAPPING_INCOMPLETE", "reason": ", ".join(mp["validation"]["missing"] + mp["validation"]["problems"])}
        key = (d["mapping_id"], d.get("epoch"))
        if self.seen.get(key, -1) >= int(d.get("seq", -1)):
            return dict(self.last or {}, status="STALE_SEQUENCE") if self.last else {"status": "STALE_SEQUENCE"}
        if now - float(d.get("heartbeat_utc", 0)) > self.ttl:
            return {"status": "STALE", "reason": "heartbeat starszy niż TTL"}
        rows = []
        for r in d.get("rows") or []:
            v = r.get("raw")
            if v is not None and (not isinstance(v, (int, float)) or not math.isfinite(v)):
                return {"status": "REJECTED", "reason": "NON_FINITE_VALUE"}
            empty = v is None or abs(v) >= EMPTY_VALUE * 0.999 or (mp.get("empty_sentinel") not in (None, "EMPTY_VALUE") and v == mp["empty_sentinel"]
                                                                       and not mp.get("zero_is_valid"))
            rows.append({"source_bar": r.get("source_bar"), "value": None if empty else v, "empty": empty})
        self.seen[key] = int(d["seq"])
        self.last = {"status": "AVAILABLE_UNVALIDATED", "mapping_id": d["mapping_id"], "units": mp["units"], "rows": rows[-200:],
                     "observed_at": d.get("heartbeat_utc"), "known_at_basis": "EXPORT_TIME (historyczne znaczniki nie dostają dawnego known_at)",
                     "role": "DIAGNOSTIC / SHADOW – bez wpływu na decyzje do testu przyrostowego"}
        return self.last
