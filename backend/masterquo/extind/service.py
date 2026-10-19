"""ExtIndService - one background reader of exporter envelopes (no MT5 connection of its own, no orders).

Inbox directories: data/extind/inbox and, on Windows, the MT5 common files folder
(%APPDATA%/MetaQuotes/Terminal/Common/Files/PMW_extind) where mql5/PMW_ExtIndicatorExporter.mq5 writes with FILE_COMMON.
A file whose (source_instance, generation, sequence) was already archived does NOT refresh the heartbeat (re-reading an old
file never makes data younger). Decisions at time D use only snapshots with available_at <= D (as_of)."""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path

from ..timeutil import iso, parse_iso, utcnow
from . import contract, mapping as mp

ADAPTERS = ("IQ_GOLD_GANN", "IQ_STAR_LINES", "PAL02M")
HEARTBEAT_TTL_S = 30.0


def inbox_dirs() -> list[Path]:
    out = [mp.ext_root() / "inbox"]
    app = os.environ.get("APPDATA")
    if app:
        out.append(Path(app) / "MetaQuotes" / "Terminal" / "Common" / "Files" / "PMW_extind")
    extra = os.environ.get("MQ_EXTIND_INBOX")
    if extra:
        out.append(Path(extra))
    return out


class ExtIndService:
    def __init__(self, cfg_store, db, bridge=None, bus=None, log=None):
        self.cfg_store, self.db, self.bridge, self.bus, self.log = cfg_store, db, bridge, bus, log
        self._stop = threading.Event()
        self.heartbeat: dict[str, dict] = {}
        self.errors: list[dict] = []
        self.files_seen: dict[str, float] = {}

    def start(self) -> None:
        threading.Thread(target=self._loop, name="extind-ingest", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(2.0):
            try:
                self.scan()
            except Exception as exc:  # noqa: BLE001 - ingest never stops prices or the strategy
                self._err("SCAN", f"{type(exc).__name__}: {exc}")

    def _err(self, f: str, reason: str) -> None:
        self.errors = (self.errors + [{"at": iso(utcnow()), "file": f, "reason": reason[:200]}])[-50:]

    def _instrument(self, symbol: str) -> str | None:
        try:
            for inst, m in self.cfg_store.get().assets.mappings.items():
                if m.broker_symbol == symbol:
                    return inst
        except Exception:  # noqa: BLE001
            pass
        return None

    def _offset(self) -> float | None:
        clk = getattr(self.bridge, "clock", None)
        return getattr(clk, "offset", None) if clk is not None and getattr(clk, "verified", True) else None

    def scan(self, now: datetime | None = None) -> int:
        n = 0
        for d in inbox_dirs():
            if not d.exists():
                continue
            for f in sorted(d.glob("*.json")):
                try:
                    st = f.stat()
                except OSError:
                    continue
                if self.files_seen.get(str(f)) == st.st_mtime:
                    continue
                self.files_seen[str(f)] = st.st_mtime
                n += self.ingest_bytes(f.read_bytes(), f.name, now)
        return n

    def ingest_bytes(self, raw: bytes, name: str = "<bytes>", now: datetime | None = None) -> int:
        now = now or utcnow()
        try:
            env = contract.validate(raw)
        except contract.EnvelopeError as exc:
            self._err(name, str(exc))                       # the last good snapshot stays untouched
            return 0
        adapter = env["adapter_id"]
        if adapter not in ADAPTERS:
            self._err(name, f"UNKNOWN_ADAPTER:{adapter}")
            return 0
        inst = self._instrument(env["symbol"])
        src = f"{env['terminal_fingerprint']}:{env['chart_id']}:{adapter}"
        if self.db.one("SELECT 1 AS x FROM extind_snapshots WHERE source_instance=? AND generation=? AND sequence=?",
                       (src, env["generation"], env["sequence"])):
            return 0                                          # duplicate sequence: no new observation, heartbeat unchanged
        ms, m = mp.mapping_status(adapter, env)
        man = mp.manifest(adapter)
        dec = mp.decode(env, m, self._offset()) if m and man.get("identity_status") == "IDENTIFIED" else \
            {"levels": [], "windows": [], "events": [], "time_status": "NOT_DECODED"}
        sid = "XS-" + uuid.uuid4().hex[:16]
        self.db.execute("""INSERT INTO extind_snapshots(snapshot_id, adapter, source_instance, instrument, symbol, chart_id, tf, generation, sequence,
                           product_version, mapping_version, mapping_status, time_status, captured_at_server, received_at, available_at, levels, windows,
                           events, objects_count, envelope_sha256) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (sid, adapter, src, inst, env["symbol"], str(env["chart_id"]), env["tf"], env["generation"], env["sequence"],
                         (env.get("product") or {}).get("version"), (m or {}).get("version"), ms, dec["time_status"], env["captured_at_server"],
                         iso(now), iso(now), json.dumps(dec["levels"]), json.dumps(dec["windows"]), json.dumps(dec["events"]),
                         len(env["objects"]), env["checksum"]))
        self.heartbeat[adapter] = {"at": iso(now), "source_instance": src, "sequence": env["sequence"], "generation": env["generation"],
                                   "symbol": env["symbol"], "instrument": inst, "objects": len(env["objects"]),
                                   "inventory": [{"name": o["name"], "type": o["type"]} for o in env["objects"][:200]]}
        if self.bus:
            self.bus.publish("extind", {"adapter": adapter, "snapshot_id": sid})
        return 1

    # ------------------------------------------------------------------ point-in-time reads
    def as_of(self, adapter: str, instrument: str, t: datetime, approved_only: bool = True) -> dict | None:
        q = "SELECT * FROM extind_snapshots WHERE adapter=? AND instrument=? AND available_at <= ?"
        if approved_only:
            q += " AND mapping_status='MAPPING_APPROVED' AND time_status='OK'"
        r = self.db.one(q + " ORDER BY available_at DESC, sequence DESC LIMIT 1", (adapter, instrument, iso(t)))
        if not r:
            return None
        for k in ("levels", "windows", "events"):
            r[k] = json.loads(r[k])
        r["age_s"] = (t - parse_iso(r["available_at"])).total_seconds()
        return r

    def status(self, instrument: str | None = None, now: datetime | None = None) -> dict:
        now = now or utcnow()
        out = {}
        for a in ADAPTERS:
            man = mp.manifest(a)
            hb = self.heartbeat.get(a)
            last = self.db.one("SELECT * FROM extind_snapshots WHERE adapter=? ORDER BY received_at DESC LIMIT 1", (a,))
            cnt = self.db.one("SELECT COUNT(*) AS n FROM extind_snapshots WHERE adapter=? AND mapping_status='MAPPING_APPROVED'", (a,))["n"]
            ms, _ = mp.mapping_status(a, None)
            ident = man.get("identity_status")
            if ident != "IDENTIFIED":
                source = ident
            elif not last:
                source = "SOURCE_MISSING"
            elif hb is None or (now - parse_iso(hb["at"])).total_seconds() > HEARTBEAT_TTL_S:
                source = "STALE"
            else:
                source = "RECEIVING"
            runtime = "READY_RUNTIME" if source == "RECEIVING" and ms == "MAPPING_APPROVED" else "NOT_READY"
            needs = []
            if ident == "BLOCKED_IDENTITY_REQUIRED":
                needs.append("pełna identyfikacja PAL02M: producent, platforma, wersja, wyjścia, licencja (data/extind/manifests/PAL02M.json)")
            if ident == "DECODER_NOT_IMPLEMENTED":
                needs.append("zaufany dekoder dla zidentyfikowanego narzędzia (kod projektu)")
            if source == "SOURCE_MISSING":
                needs.append("licencjonowany wskaźnik na wykresie MT5 + PMW_ExtIndicatorExporter (mql5/) z tym adapterem")
            if ms != "MAPPING_APPROVED" and ident == "IDENTIFIED":
                needs.append("mapping obiektów zatwierdzony po porównaniu liczb z wykresem")
            if cnt < 200:
                needs.append(f"archiwum point-in-time: {cnt} zatwierdzonych odczytów (do treningu potrzeba ciągłej rejestracji na żywo)")
            out[a] = {"adapter": a, "title": man.get("title"), "implementation_status": "IMPLEMENTED_INGEST_MAPPING_ARCHIVE",
                      "identity_status": ident, "source_status": source, "mapping_status": ms, "runtime_status": runtime,
                      "dataset_status": "READY_FOR_DATASET" if cnt >= 200 else "BLOCKED_NO_ARCHIVE",
                      "training_status": "BLOCKED_NO_DATA" if cnt < 200 else "TRAINING_PIPELINE_IMPLEMENTED",
                      "validation_status": "NOT_VALIDATED", "mode": "OBSERVE", "archived_approved": cnt, "heartbeat": hb and {k: hb[k] for k in
                      ("at", "sequence", "generation", "symbol", "instrument", "objects")},
                      "last_snapshot_id": last and last["snapshot_id"], "needs": needs, "manifest": {k: man.get(k) for k in
                      ("product_id", "platform", "url", "interface", "buffers_documented", "interface_note")}}
        return {"adapters": out, "inbox_dirs": [str(d) for d in inbox_dirs()], "errors": self.errors[-10:]}
