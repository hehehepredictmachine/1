"""ExtIndService - one background reader of exporter envelopes (no MT5 connection of its own, no orders).

Inbox directories: data/extind/inbox and, on Windows, the MT5 common files folder
(%APPDATA%/MetaQuotes/Terminal/Common/Files/PMW_extind) where mql5/PMW_ExtIndicatorExporter.mq5 writes with FILE_COMMON.
A file whose (source_instance, generation, sequence) was already archived does NOT refresh the heartbeat (re-reading an old
file never makes data younger). Decisions at time D use only snapshots with available_at <= D (as_of).

1.46 arch:
- I0728: the exporter counts generation / sequence from 0 after every OnInit (MT5 / chart restart). A known (generation, sequence)
  with a LATER captured_at_server than everything archived for it is a new exporter session (archived under
  '<source>#S<captured_at_server>'), not a duplicate; an equal or older capture stays a duplicate (re-read file).
- I0729: the exporter re-sends the same objects every 2 s. The same decoded content of the same source within HEARTBEAT_TTL_S of the
  last confirmation does not add a row - it moves last_seen_at / last_sequence / last_captured_at / seen_count of the newest row
  (migration 0030). Nothing is deleted. as_of age_s = time since the last confirmation at or before D (0 inside a confirmed run).
  as_of takes the newest row of EVERY source at or before D and keeps the one confirmed latest at D (one adapter on two charts /
  terminals: a chart closed long ago no longer wins only because it changed its content last; before the deduplication: the newest read).
- I0175: a read whose symbol matches no assets.mappings broker symbol is archived with instrument NULL (invisible to as_of) - it is
  now reported once per symbol (UNMAPPED_SYMBOL) and in status() needs.
- I0077: active_model() hands the indicator-context model to the scalp service (scalp no longer imports extind)."""
from __future__ import annotations

import hashlib
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
        self.heartbeat_by_inst: dict[tuple[str, str | None], dict] = {}   # 1.46: (adapter, instrument) - one adapter on two charts
        self.errors: list[dict] = []
        self.files_seen: dict[str, float] = {}
        self.unmapped: dict[tuple[str, str], dict] = {}                     # (adapter, symbol) -> reads without an instrument
        self._sessions: dict[str, str] = {}                                 # base source -> source_instance of the current exporter session
        self._current: dict[str, dict] = {}                                 # source_instance -> newest row (content hash, last confirmation)

    def active_model(self, inst: str, why: list | None = None):
        """Active indicator-context model (extind.trainer) of the instrument or None - the scalp service asks the injected service
        instead of importing extind (1.46 arch I0077: one dependency direction extind -> scalp)."""
        from . import trainer
        return trainer.active_model(inst, why)

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

    def _note_unmapped(self, adapter: str, symbol: str, name: str, now: datetime) -> None:
        """1.46 arch (I0175): a read archived without an instrument is invisible to as_of / status(instrument) - say so once per symbol."""
        k = (adapter, symbol)
        u = self.unmapped.get(k)
        if u is None:
            self._err(name, f"UNMAPPED_SYMBOL:{symbol}")
            u = self.unmapped[k] = {"adapter": adapter, "symbol": symbol, "first_at": iso(now), "count": 0}
        u.update(count=u["count"] + 1, last_at=iso(now))

    def _current_row(self, src: str) -> dict | None:
        """Newest archived row of one source_instance (cached): content hash, last confirmation, last sequence / capture."""
        cur = self._current.get(src)
        if cur is None:
            r = self.db.one("SELECT * FROM extind_snapshots WHERE source_instance=? ORDER BY available_at DESC, sequence DESC LIMIT 1", (src,))
            if r is None:
                return None
            cur = self._current[src] = {
                "snapshot_id": r["snapshot_id"], "seen_at": r.get("last_seen_at") or r["received_at"],
                "content": _content_hash(r["instrument"], r["mapping_status"], r["time_status"], r["mapping_version"], r["product_version"],
                                         r["levels"], r["windows"], r["events"]),
                "last_sequence": r["last_sequence"] if r.get("last_sequence") is not None else r["sequence"],
                "last_captured_at": r["last_captured_at"] if r.get("last_captured_at") is not None else r["captured_at_server"]}
        return cur

    def _source_for(self, base: str, env: dict) -> str | None:
        """source_instance this envelope is archived under, or None for an already archived / older read (heartbeat unchanged).
        1.46 arch (I0728): the exporter numbers generation / sequence from 0 after every OnInit - a sequence that is already archived
        (or behind the newest row) with a LATER capture, or the same sequence with another envelope, is a new exporter session."""
        src = self._sessions.get(base)
        if src is None:                                    # after a restart of the bot: the session archived last for this chart
            row = self.db.one("SELECT source_instance FROM extind_snapshots WHERE source_instance=? OR (source_instance>=? AND source_instance<?) "
                              "ORDER BY available_at DESC LIMIT 1", (base, base + "#S", base + "#T"))
            src = self._sessions[base] = row["source_instance"] if row else base
        seq, cap = env["sequence"], env["captured_at_server"]
        cur = self._current_row(src)
        hit = self.db.one("SELECT sequence, last_sequence, envelope_sha256, captured_at_server FROM extind_snapshots WHERE source_instance=? "
                          "AND sequence<=? ORDER BY sequence DESC LIMIT 1", (src, seq))
        covered = hit is not None and (hit["last_sequence"] if hit["last_sequence"] is not None else hit["sequence"]) >= seq
        if not covered and (cur is None or seq > cur["last_sequence"]):
            if cur is not None and cur["last_captured_at"] is not None and cap < cur["last_captured_at"]:
                return None                                # captured before the newest archived read (older file of another session)
            return src                                     # the next read of the current exporter session
        newer = cur is not None and cur["last_captured_at"] is not None and cap > cur["last_captured_at"]
        if covered and hit["sequence"] == seq and hit["envelope_sha256"] != env["checksum"] and cap >= (hit["captured_at_server"] or 0):
            newer = True                                   # the same (sequence) but another envelope, not an older capture
        if not newer:
            return None                                    # re-read / older file: never makes data younger
        new = f"{base}#S{cap}"
        if new == src:
            return None
        self._sessions[base] = new
        return new

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
                try:
                    raw = f.read_bytes()
                except OSError as exc:
                    self.files_seen.pop(str(f), None)            # 1.46: read again on the next scan
                    self._err(f.name, f"{type(exc).__name__}: {exc}")
                    continue
                try:
                    n += self.ingest_bytes(raw, f.name, now)
                except Exception as exc:  # noqa: BLE001 - 1.46: one bad file is rejected alone, the scan of the others goes on
                    self._err(f.name, f"{type(exc).__name__}: {exc}")
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
        base = f"{env['terminal_fingerprint']}:{env['chart_id']}:{adapter}"
        src = self._source_for(base, env)
        if src is None:
            return 0                                          # duplicate sequence: no new observation, heartbeat unchanged
        if inst is None:
            self._note_unmapped(adapter, env["symbol"], name, now)
        ms, m = mp.mapping_status(adapter, env)
        man = mp.manifest(adapter)
        dec = mp.decode(env, m, self._offset()) if m and man.get("identity_status") == "IDENTIFIED" else \
            {"levels": [], "windows": [], "events": [], "time_status": "NOT_DECODED"}
        lv, wn, evs = json.dumps(dec["levels"]), json.dumps(dec["windows"]), json.dumps(dec["events"])
        pver, mver = (env.get("product") or {}).get("version"), (m or {}).get("version")
        content = _content_hash(inst, ms, dec["time_status"], mver, pver, lv, wn, evs)
        cur = self._current_row(src)
        stamp = iso(now)
        if cur is not None and cur["content"] == content and 0 <= (now - parse_iso(cur["seen_at"])).total_seconds() <= HEARTBEAT_TTL_S:
            # I0729: the same content confirmed again - the newest row is extended (no new row every 2 s)
            sid = cur["snapshot_id"]
            self.db.execute("UPDATE extind_snapshots SET last_seen_at=?, last_sequence=?, last_captured_at=?, seen_count=COALESCE(seen_count, 1)+1 "
                            "WHERE snapshot_id=?", (stamp, env["sequence"], env["captured_at_server"], sid))
            cur.update(seen_at=stamp, last_sequence=env["sequence"], last_captured_at=env["captured_at_server"])
        else:
            sid = "XS-" + uuid.uuid4().hex[:16]
            self.db.execute("""INSERT INTO extind_snapshots(snapshot_id, adapter, source_instance, instrument, symbol, chart_id, tf, generation, sequence,
                               product_version, mapping_version, mapping_status, time_status, captured_at_server, received_at, available_at, levels, windows,
                               events, objects_count, envelope_sha256, last_seen_at, last_sequence, last_captured_at, seen_count)
                               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (sid, adapter, src, inst, env["symbol"], str(env["chart_id"]), env["tf"], env["generation"], env["sequence"],
                             pver, mver, ms, dec["time_status"], env["captured_at_server"], stamp, stamp, lv, wn, evs,
                             len(env["objects"]), env["checksum"], stamp, env["sequence"], env["captured_at_server"], 1))
            self._current[src] = {"snapshot_id": sid, "content": content, "seen_at": stamp, "last_sequence": env["sequence"],
                                  "last_captured_at": env["captured_at_server"]}
        self.heartbeat[adapter] = {"at": iso(now), "source_instance": src, "sequence": env["sequence"], "generation": env["generation"],
                                   "symbol": env["symbol"], "instrument": inst, "objects": len(env["objects"]),
                                   "inventory": [{"name": o["name"], "type": o["type"]} for o in env["objects"][:200]]}
        self.heartbeat_by_inst[(adapter, inst)] = self.heartbeat[adapter]
        if self.bus:
            self.bus.publish("extind", {"adapter": adapter, "snapshot_id": sid})
        return 1

    # ------------------------------------------------------------------ point-in-time reads
    def as_of(self, adapter: str, instrument: str, t: datetime, approved_only: bool = True) -> dict | None:
        w = " FROM extind_snapshots WHERE adapter=? AND instrument=?"
        if approved_only:
            w += " AND mapping_status='MAPPING_APPROVED' AND time_status='OK'"
        tu = parse_iso(iso(t))
        args = (adapter, instrument)
        r = self._newest_at(w, args, tu)
        if r is None:
            return None
        # 1.46 arch (I0729, review 2): a row stands for a run of identical reads of ONE source (available_at = the first read), so the
        # newest available_at is the source that last CHANGED its content, not the one that last confirmed something - with one adapter
        # on two charts / terminals of the instrument a chart closed long ago won over the live one. The read known at t is the newest
        # row of every source at or before t, keyed by its last confirmation at or before t (ties: the newer content, as before). Rows of
        # one source never overlap, so another source can only win when the newest row's run ended before t.
        if self._confirmed(r, tu) < tu:
            for c in self._per_source(w, args, tu, self._confirmed(r, tu)):
                if self._key(c, tu) > self._key(r, tu):
                    r = c
        for k in ("levels", "windows", "events"):
            r[k] = json.loads(r[k])
        # a row without last_seen_at (older archive) is one read, as before; fields describing confirmations AFTER t are not part of
        # the point-in-time read
        conf = self._confirmed(r, tu)
        for k in ("last_seen_at", "last_sequence", "last_captured_at", "seen_count"):
            r.pop(k, None)
        r["confirmed_at"] = iso(conf)
        r["age_s"] = (t - conf).total_seconds()
        return r

    @staticmethod
    def _confirmed(r: dict, tu: datetime) -> datetime:
        """Last confirmation of the row's content at or before tu (inside a confirmed run: tu; runs have gaps <= HEARTBEAT_TTL_S)."""
        avail = parse_iso(r["available_at"])
        seen = parse_iso(r["last_seen_at"]) if r.get("last_seen_at") else avail
        return max(avail, min(tu, seen))

    @classmethod
    def _key(cls, r: dict, tu: datetime) -> tuple:
        return cls._confirmed(r, tu), parse_iso(r["available_at"]), r["sequence"]

    def _newest_at(self, w: str, args: tuple, tu: datetime) -> dict | None:
        """Newest row (available_at, sequence) with available_at <= tu.
        1.46: available_at is ISO text with or without a fraction ('...:00.400000Z' < '...:00Z' as text): a snapshot received 0.4 s
        AFTER a decision at a full second passed 'available_at <= D' (look-ahead) and the order inside one second was reversed.
        The index still selects whole seconds; inside a second the stamps are compared as times."""
        sec = tu.strftime("%Y-%m-%dT%H:%M:%S")                    # stored stamps: 'YYYY-MM-DDTHH:MM:SS[.ffffff]Z' ('.', 'Z' < '~')

        def second(s: str) -> list[dict]:
            return self.db.query("SELECT *" + w + " AND available_at >= ? AND available_at < ?", (*args, s, s + "~"))
        rows = [x for x in second(sec) if parse_iso(x["available_at"]) <= tu]
        if not rows:                                               # the newest earlier second: every stamp in it is before t
            prev = self.db.one("SELECT substr(available_at, 1, 19) AS s" + w + " AND available_at < ? ORDER BY available_at DESC LIMIT 1",
                               (*args, sec))
            rows = second(prev["s"]) if prev else []
        return max(rows, key=lambda x: (parse_iso(x["available_at"]), x["sequence"])) if rows else None

    def _per_source(self, w: str, args: tuple, tu: datetime, floor: datetime) -> list[dict]:
        """The newest row with available_at <= tu of every source_instance of the (adapter, instrument) rows whose last confirmation is
        not before floor (only those can win). The sources are walked by one index seek each (migration 0030: idx_extind_asof_source)
        in a single statement, not by scanning the archive."""
        sec = tu.strftime("%Y-%m-%dT%H:%M:%S")
        best: dict[str, dict] = {}

        def newer(x: dict, y: dict | None) -> bool:
            return y is None or (parse_iso(x["available_at"]), x["sequence"]) > (parse_iso(y["available_at"]), y["sequence"])
        for x in self.db.query("SELECT *" + w + " AND available_at >= ? AND available_at < ?", (*args, sec, sec + "~")):
            if parse_iso(x["available_at"]) <= tu and newer(x, best.get(x["source_instance"])):     # t's second: compared as times
                best[x["source_instance"]] = x
        sids = self.db.query("WITH RECURSIVE src(s) AS (SELECT (SELECT MIN(source_instance)" + w + ") UNION ALL SELECT (SELECT MIN(source_instance)"
                             + w + " AND source_instance > src.s) FROM src WHERE src.s IS NOT NULL) SELECT s, (SELECT snapshot_id" + w
                             + " AND source_instance = src.s AND available_at < ? ORDER BY available_at DESC, sequence DESC LIMIT 1) AS sid"
                             " FROM src WHERE s IS NOT NULL", (*args, *args, *args, sec))
        ids = [x["sid"] for x in sids if x["sid"] is not None and x["s"] not in best]
        fsec = floor.strftime("%Y-%m-%dT%H:%M:%S")
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            for x in self.db.query("SELECT * FROM extind_snapshots WHERE snapshot_id IN (" + ",".join("?" * len(chunk)) + ") AND "
                                   "(COALESCE(last_seen_at, available_at) >= ? OR length(available_at) = 20)", (*chunk, fsec)):
                if len(x["available_at"]) == 20:   # 'SSZ' is the EARLIEST stamp of its second but sorts after 'SS.ffffffZ'
                    s1 = x["available_at"][:19]
                    x = max(self.db.query("SELECT *" + w + " AND source_instance=? AND available_at >= ? AND available_at < ?",
                                          (*args, x["source_instance"], s1, s1 + "~")), key=lambda y: (parse_iso(y["available_at"]), y["sequence"]))
                best[x["source_instance"]] = x
        return list(best.values())

    def status(self, instrument: str | None = None, now: datetime | None = None) -> dict:
        now = now or utcnow()
        out = {}
        # 1.46: status(instrument) is the status of THIS instrument's chart (heartbeat, last read, archive); None = every chart (CLI)
        w, args = (" AND instrument=?", (instrument,)) if instrument is not None else ("", ())
        for a in ADAPTERS:
            man = mp.manifest(a)
            hb = self.heartbeat.get(a) if instrument is None else self.heartbeat_by_inst.get((a, instrument))
            last = self.db.one("SELECT * FROM extind_snapshots WHERE adapter=?" + w + " ORDER BY received_at DESC LIMIT 1", (a, *args))
            # 1.46 arch (I0729): approved READS (a row counts every confirmation of its content), as before the deduplication
            cnt = int(self.db.one("SELECT COALESCE(SUM(COALESCE(seen_count, 1)), 0) AS n FROM extind_snapshots WHERE adapter=?" + w
                                  + " AND mapping_status='MAPPING_APPROVED'", (a, *args))["n"])
            ms, _ = mp.mapping_status(a, None)
            live_ms = last["mapping_status"] if last else None     # 1.46: mapping status of the newest read (product version checked)
            ident = man.get("identity_status")
            if ident != "IDENTIFIED":
                source = ident
            elif not last:
                source = "SOURCE_MISSING"
            elif hb is None or (now - parse_iso(hb["at"])).total_seconds() > HEARTBEAT_TTL_S:
                source = "STALE"
            else:
                source = "RECEIVING"
            runtime = "READY_RUNTIME" if source == "RECEIVING" and ms == "MAPPING_APPROVED" and live_ms == "MAPPING_APPROVED" else "NOT_READY"
            needs = []
            if ident == "BLOCKED_IDENTITY_REQUIRED":
                needs.append("pełna identyfikacja PAL02M: producent, platforma, wersja, wyjścia, licencja (data/extind/manifests/PAL02M.json)")
            if ident == "DECODER_NOT_IMPLEMENTED":
                needs.append("zaufany dekoder dla zidentyfikowanego narzędzia (kod projektu)")
            if source == "SOURCE_MISSING":
                needs.append("licencjonowany wskaźnik na wykresie MT5 + PMW_ExtIndicatorExporter (mql5/) z tym adapterem")
            if ms != "MAPPING_APPROVED" and ident == "IDENTIFIED":
                needs.append("mapping obiektów zatwierdzony po porównaniu liczb z wykresem")
            if live_ms == "MAPPING_VERSION_CHANGED" and ident == "IDENTIFIED":
                needs.append("nowa wersja produktu na wykresie – ponowne zatwierdzenie mappingu (odczyty nowej wersji nie są używane)")
            if cnt < 200:
                needs.append(f"archiwum point-in-time: {cnt} zatwierdzonych odczytów (do treningu potrzeba ciągłej rejestracji na żywo)")
            for u in sorted((u for (ad, _s), u in self.unmapped.items() if ad == a), key=lambda x: x["symbol"]):
                needs.append(f"symbol {u['symbol']} z eksportera nie jest zmapowany w Ustawienia → assets.mappings (odczyty zapisane bez "
                             f"instrumentu, niewidoczne dla modelu: {u['count']})")
            out[a] = {"adapter": a, "title": man.get("title"), "implementation_status": "IMPLEMENTED_INGEST_MAPPING_ARCHIVE",
                      "identity_status": ident, "source_status": source, "mapping_status": ms, "live_mapping_status": live_ms,
                      "runtime_status": runtime,
                      "dataset_status": "READY_FOR_DATASET" if cnt >= 200 else "BLOCKED_NO_ARCHIVE",
                      "training_status": "BLOCKED_NO_DATA" if cnt < 200 else "TRAINING_PIPELINE_IMPLEMENTED",
                      "validation_status": "NOT_VALIDATED", "mode": "OBSERVE", "archived_approved": cnt, "heartbeat": hb and {k: hb[k] for k in
                      ("at", "sequence", "generation", "symbol", "instrument", "objects")},
                      "last_snapshot_id": last and last["snapshot_id"], "needs": needs, "manifest": {k: man.get(k) for k in
                      ("product_id", "platform", "url", "interface", "buffers_documented", "interface_note")}}
        return {"adapters": out, "inbox_dirs": [str(d) for d in inbox_dirs()], "errors": self.errors[-10:],
                "unmapped_symbols": [dict(u) for u in self.unmapped.values()]}


def _content_hash(inst, ms, time_status, mapping_version, product_version, levels: str, windows: str, events: str) -> str:
    """Identity of one decoded read (instrument, mapping / time status, versions, decoded objects) - equal hash = the same observation."""
    key = json.dumps([inst, ms, time_status, None if mapping_version is None else str(mapping_version), product_version, levels, windows, events])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()
