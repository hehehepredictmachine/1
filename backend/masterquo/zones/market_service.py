"""MarketZonesService (PMW-MZ-SERVICE-1): jobs and live updates behind the "Strefy rynkowe" panel.

Analytical only - this service holds no reference to the execution gateway, risk engine or configuration writer: the
"Wyznacz strefy teraz" button can never open a position or change automatic-trading settings.

* Jobs: one worker thread runs jobs in submission order. A click while an equivalent job (same instrument, its timeframes
  covering the request) is queued or running returns THAT job (multi-click safe); a request for other timeframes supersedes
  the running job's unfinished part. Results are applied per (instrument, timeframe) only when their data time (moment the bars
  were read, then sequence number) is newer than what is already shown - an older result never overwrites a newer one.
* Live mode: one poller for all instruments (no duplicate subscriptions). Each timeframe is recomputed only after ITS candle
  closes (M15 zones after the M15 close); between closes the live quote marks tests / breaches as PRELIMINARY (confirmed or
  dropped at the close). One subscription per instrument - enabling it twice changes nothing.
* Data loss: a failed read keeps the last zones of that timeframe, marked stale with the reason; a later successful read after
  a reconnect recomputes and clears the mark. Status per timeframe: CONNECTED / STALE / NO_DATA / ERROR
  (połączone / dane nieaktualne / brak danych / błąd).
* History: every applied result is stored (data/zones/market_zones.sqlite: snapshots + zone events, idempotent), so the state
  "as of" a past moment can be reconstructed; `at(instrument, as_of)` recomputes from bars cut at as_of.
"""
from __future__ import annotations

import itertools
import json
import sqlite3
import threading
import time
from collections import deque
from pathlib import Path

from ..timeutil import TF_SECONDS
from . import market as MZ
from .series import Series, iso, ts

VERSION = "PMW-MZ-SERVICE-1"
INSTRUMENTS = ("XAUUSD", "BTC")
STATUS_PL = {"CONNECTED": "połączone", "STALE": "dane nieaktualne", "NO_DATA": "brak danych", "ERROR": "błąd", "IDLE": "nie pobierano"}
JOB_PL = {"QUEUED": "w kolejce", "RUNNING": "w toku", "DONE": "gotowe", "FAILED": "błąd", "CANCELLED": "zatrzymane",
          "SUPERSEDED": "zastąpione nowszym", "PARTIAL": "częściowo (część interwałów bez danych)"}
SCHEMA = """
CREATE TABLE IF NOT EXISTS mz_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, instrument TEXT, tf TEXT, seq INTEGER, data_at REAL,
  as_of TEXT, created_at REAL, payload TEXT);
CREATE INDEX IF NOT EXISTS ix_mz_snap ON mz_snapshots(instrument, tf, data_at);
CREATE TABLE IF NOT EXISTS mz_events (id INTEGER PRIMARY KEY AUTOINCREMENT, instrument TEXT, tf TEXT, zone_id TEXT, event TEXT, at TEXT,
  detail TEXT, UNIQUE(instrument, zone_id, event, at));
"""


def _default_dir() -> Path:
    from ..paths import data_dir
    return data_dir() / "zones"


class Job:
    def __init__(self, seq: int, instrument: str, tfs: list[str], reason: str):
        self.seq, self.instrument, self.tfs, self.reason = seq, instrument, list(tfs), reason
        self.id = f"MZJ-{seq}-{instrument}"
        self.status, self.stage, self.progress = "QUEUED", "czeka w kolejce", 0.0
        self.created_at, self.started_at, self.finished_at = time.time(), None, None
        self.error: str | None = None
        self.cancel = threading.Event()
        self.tf_result: dict[str, str] = {}

    def public(self) -> dict:
        return {"job_id": self.id, "seq": self.seq, "instrument": self.instrument, "timeframes": self.tfs, "reason": self.reason,
                "status": self.status, "status_pl": JOB_PL[self.status], "stage": self.stage, "progress": round(self.progress, 3),
                "created_at": iso(self.created_at), "started_at": iso(self.started_at), "finished_at": iso(self.finished_at),
                "duration_s": round((self.finished_at or time.time()) - self.started_at, 2) if self.started_at else None,
                "error": self.error, "timeframe_results": dict(self.tf_result)}


class MarketZonesService:
    def __init__(self, cfg_store, bridge, *, bus=None, log=None, data_dir: Path | None = None, clock=time.time, poll_s: float = 2.0):
        self.cfg_store, self.bridge, self.bus, self.log, self.clock, self.poll_s = cfg_store, bridge, bus, log, clock, poll_s
        d = Path(data_dir or _default_dir())
        d.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(d / "market_zones.sqlite"), check_same_thread=False, isolation_level=None, timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        self._lock = threading.RLock()
        self._seq = itertools.count(1)
        self._queue: deque[Job] = deque()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._poller: threading.Thread | None = None
        self.jobs: dict[str, Job] = {}                       # job id -> job (bounded)
        self.current_job: dict[str, Job] = {}                # instrument -> newest job
        self.tf: dict[tuple[str, str], dict] = {}            # (inst, tf) -> {"raw": compute_tf result, "data_at", "seq", ...}
        self.status: dict[tuple[str, str], dict] = {}        # (inst, tf) -> data source status
        self.live: dict[str, dict] = {}                      # instrument -> {"tfs": [...], "last_closed": {tf: iso}, "since": iso}
        self.quotes: dict[str, dict] = {}
        self.counters = {"jobs": 0, "deduplicated_clicks": 0, "discarded_older_results": 0, "live_recomputes": 0}
        self._restore()

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        with self._lock:
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._work, name="mzones-jobs", daemon=True)
                self._worker.start()

    def stop_service(self) -> None:
        self._stop.set()
        self._wake.set()

    def _restore(self) -> None:
        """Last stored zones per (instrument, TF): shown after a restart as STALE until the first recomputation."""
        try:
            rows = self.db.execute("SELECT s.* FROM mz_snapshots s JOIN (SELECT instrument, tf, MAX(id) mid FROM mz_snapshots GROUP BY "
                                   "instrument, tf) m ON s.id = m.mid").fetchall()
        except sqlite3.Error:
            return
        for r in rows:
            try:
                raw = json.loads(r["payload"])
            except ValueError:
                continue
            self.tf[(r["instrument"], r["tf"])] = {"raw": raw, "data_at": r["data_at"], "seq": 0, "computed_at": r["created_at"],
                                                   "restored": True}
            self.status[(r["instrument"], r["tf"])] = {"status": "STALE", "reason": "odtworzone z zapisu po restarcie – czeka na przeliczenie",
                                                       "checked_at": None, "last_closed": raw.get("last_closed")}

    # ------------------------------------------------------------------ inputs
    def symbol_for(self, inst: str) -> str | None:
        m = self.cfg_store.get().assets.mappings.get(inst)
        return m.broker_symbol if m and m.broker_symbol else None

    def _read(self, inst: str, tf: str, n: int) -> tuple[list[dict], float, dict]:
        sym = self.symbol_for(inst)
        if not sym:
            raise LookupError(f"brak symbolu brokera dla {inst} – ustaw mapowanie w Ustawieniach (np. XAUUSD-, BTCUSDT-)")
        rows = self.bridge.symbol_bars(sym, tf, n)
        read_at = self.clock()
        meta = {}
        try:
            meta = self.bridge.symbol_meta(sym) or {}
        except Exception:  # noqa: BLE001 - point falls back to 0.01
            meta = {}
        return rows, read_at, meta

    def _classify(self, rows: list[dict], tf: str, now: float) -> dict:
        closed = [b for b in rows if b.get("closed") is not False and b.get("open_utc")]
        if not closed:
            why = ("offset czasu serwera MT5 nie jest jeszcze zmierzony – świece bez czasu UTC nie są używane (poczekaj na notowania)"
                   if rows and not any(b.get("open_utc") for b in rows) else "terminal nie zwrócił zamkniętych świec")
            return {"status": "NO_DATA", "reason": why, "last_closed": None}
        last_close = ts(closed[-1]["open_utc"]) + TF_SECONDS[tf]
        age = now - last_close
        st = "CONNECTED" if age <= 3 * TF_SECONDS[tf] + 30 else "STALE"
        return {"status": st, "reason": None if st == "CONNECTED" else f"ostatnia zamknięta świeca {iso(last_close)} ({int(age // 60)} min temu – "
                "rynek zamknięty albo brak notowań)", "last_closed": iso(last_close), "age_s": round(age, 1)}

    # ------------------------------------------------------------------ jobs
    def request(self, instrument: str, timeframes: list[str] | None = None, reason: str = "manual") -> dict:
        inst = str(instrument).upper()
        if inst not in INSTRUMENTS:
            raise ValueError(f"nieznany instrument {instrument} (dozwolone: {', '.join(INSTRUMENTS)})")
        tfs = [t for t in MZ.TFS if t in (timeframes or MZ.TFS)]
        if not tfs:
            raise ValueError("wybierz co najmniej jeden interwał: M1, M5, M15, M30")
        with self._lock:
            cur = self.current_job.get(inst)
            pending = [j for j in self._queue if j.instrument == inst] + ([cur] if cur and cur.status == "RUNNING" else [])
            for j in pending:
                # a click while an equivalent job is queued or running returns that job; a live recompute after a candle close is
                # merged only into a job that has not started yet (a running job may have read the bars before that close)
                ok_states = ("QUEUED", "RUNNING") if reason == "manual" else ("QUEUED",)
                if j.status in ok_states and set(tfs) <= set(j.tfs) and not j.cancel.is_set():
                    self.counters["deduplicated_clicks"] += 1
                    return {**j.public(), "deduplicated": True}
            if reason == "manual":
                for j in pending:                            # a different manual request supersedes the unfinished ones
                    if j.status in ("QUEUED", "RUNNING") and not j.reason.startswith("live"):
                        j.cancel.set()
                        j.status, j.stage = "SUPERSEDED", "zastąpione nowszym żądaniem"
            job = Job(next(self._seq), inst, tfs, reason)
            self.jobs[job.id] = job
            if len(self.jobs) > 200:
                for k in list(self.jobs)[:50]:
                    if self.jobs[k].status not in ("QUEUED", "RUNNING"):
                        self.jobs.pop(k, None)
            self.current_job[inst] = job
            self._queue.append(job)
            self.counters["jobs"] += 1
        self.start()
        self._wake.set()
        self._publish(inst, job)
        return {**job.public(), "deduplicated": False}

    def stop(self, instrument: str) -> dict:
        """'Zatrzymaj': live updates off + queued / running jobs of the instrument cancelled. Zones already shown stay."""
        inst = str(instrument).upper()
        with self._lock:
            self.live.pop(inst, None)
            n = 0
            for j in list(self._queue) + [self.current_job.get(inst)]:
                if j is not None and j.instrument == inst and j.status in ("QUEUED", "RUNNING"):
                    j.cancel.set()
                    j.status, j.stage = "CANCELLED", "zatrzymane przez użytkownika"
                    j.finished_at = time.time()
                    n += 1
        self._publish(inst, None)
        return {"instrument": inst, "cancelled_jobs": n, "live": False}

    def _work(self) -> None:
        while not self._stop.is_set():
            job = None
            with self._lock:
                while self._queue and job is None:
                    j = self._queue.popleft()
                    if j.status == "QUEUED" and not j.cancel.is_set():
                        job = j
            if job is None:
                self._wake.wait(1.0)
                self._wake.clear()
                continue
            try:
                self._run(job)
            except Exception as exc:  # noqa: BLE001 - a job failure never stops the worker
                job.status, job.error, job.finished_at = "FAILED", f"{type(exc).__name__}: {exc}"[:300], time.time()
            self._publish(job.instrument, job)

    def _run(self, job: Job) -> None:
        inst = job.instrument
        job.status, job.started_at, job.stage = "RUNNING", time.time(), "pobieranie danych"
        steps = 2 * len(job.tfs) + 1
        done = 0
        fresh: dict[str, dict] = {}
        for tf in job.tfs:
            if job.cancel.is_set():
                return
            job.stage = f"{tf}: pobieranie świec"
            try:
                rows, read_at, meta = self._read(inst, tf, MZ.TF_PARAMS[tf]["bars"])
                st = self._classify(rows, tf, read_at)
            except Exception as exc:  # noqa: BLE001 - disconnected terminal, unknown symbol, timeout
                self._mark_stale(inst, tf, "ERROR", f"{type(exc).__name__}: {exc}"[:240])
                job.tf_result[tf] = "ERROR"
                done += 2
                job.progress = done / steps
                continue
            done += 1
            job.progress = done / steps
            if st["status"] == "NO_DATA":
                self._mark_stale(inst, tf, "NO_DATA", st["reason"])
                job.tf_result[tf] = "NO_DATA"
                done += 1
                continue
            job.stage = f"{tf}: wyznaczanie stref"
            point = float(meta.get("point") or 0.01)
            s = Series.from_bars(rows, tf, read_at)
            raw = MZ.compute_tf(s, inst, point, MZ.spread_price(rows, point))
            raw.update(computed_as_of=iso(read_at), data_status=st["status"])
            fresh[tf] = {"raw": raw, "data_at": read_at, "status": st}
            done += 1
            job.progress = done / steps
        if job.cancel.is_set():
            return
        job.stage = "zapis i rysowanie"
        applied = self._apply(job, fresh)
        if job.cancel.is_set():
            return
        job.progress = 1.0
        job.finished_at = time.time()
        failed = [t for t, r in job.tf_result.items() if r in ("ERROR", "NO_DATA")]
        job.status = "DONE" if not failed else ("FAILED" if len(failed) == len(job.tfs) else "PARTIAL")
        job.stage = (f"gotowe: {', '.join(applied)}" if applied else "brak nowych wyników") + (f"; bez danych: {', '.join(failed)}" if failed else "")
        if failed and len(failed) == len(job.tfs):
            job.error = "żaden interwał nie zwrócił danych – pokazane są ostatnie strefy oznaczone jako nieaktualne"

    def _apply(self, job: Job, fresh: dict[str, dict]) -> list[str]:
        applied = []
        with self._lock:
            if job.cancel.is_set():
                return applied
            for tf, f in fresh.items():
                key = (job.instrument, tf)
                old = self.tf.get(key)
                if old and (old["data_at"], old["seq"]) > (f["data_at"], job.seq):
                    self.counters["discarded_older_results"] += 1           # an older result never overwrites a newer one
                    job.tf_result[tf] = "DISCARDED_OLDER"
                    continue
                self.tf[key] = {"raw": f["raw"], "data_at": f["data_at"], "seq": job.seq, "computed_at": time.time(), "restored": False}
                self.status[key] = {**f["status"], "checked_at": iso(f["data_at"])}
                job.tf_result[tf] = "APPLIED"
                applied.append(tf)
                sub = self.live.get(job.instrument)
                if sub is not None and f["raw"].get("last_closed"):
                    sub["last_closed"][tf] = f["raw"]["last_closed"]          # the live poller will not recompute the same close again
        for tf in applied:
            self._persist(job.instrument, tf, job.seq, fresh[tf])
        return applied

    def _mark_stale(self, inst: str, tf: str, status: str, reason: str) -> None:
        with self._lock:
            self.status[(inst, tf)] = {"status": status, "reason": reason, "checked_at": iso(self.clock()),
                                       "last_closed": (self.tf.get((inst, tf)) or {}).get("raw", {}).get("last_closed")}

    def _persist(self, inst: str, tf: str, seq: int, f: dict) -> None:
        raw = f["raw"]
        try:
            with self._lock:
                self.db.execute("BEGIN")
                self.db.execute("INSERT INTO mz_snapshots(instrument, tf, seq, data_at, as_of, created_at, payload) VALUES (?,?,?,?,?,?,?)",
                                (inst, tf, seq, f["data_at"], raw.get("computed_as_of"), time.time(), json.dumps(raw, default=float)))
                self.db.execute("DELETE FROM mz_snapshots WHERE instrument=? AND tf=? AND id NOT IN (SELECT id FROM mz_snapshots WHERE "
                                "instrument=? AND tf=? ORDER BY id DESC LIMIT 200)", (inst, tf, inst, tf))
                for z in raw.get("zones") or []:
                    for e in z.get("events") or []:
                        self.db.execute("INSERT OR IGNORE INTO mz_events(instrument, tf, zone_id, event, at, detail) VALUES (?,?,?,?,?,?)",
                                        (inst, tf, z["id"], e["event"], e["at"], json.dumps({"type": z["type"], "lower": z["lower"],
                                                                                              "upper": z["upper"]})))
                self.db.execute("COMMIT")
        except sqlite3.Error as exc:
            try:
                self.db.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            if self.log:
                self.log.warning("market_zones", f"zapis historii stref nieudany: {exc}")

    # ------------------------------------------------------------------ live
    def set_live(self, instrument: str, enabled: bool, timeframes: list[str] | None = None) -> dict:
        inst = str(instrument).upper()
        if inst not in INSTRUMENTS:
            raise ValueError(f"nieznany instrument {instrument}")
        tfs = [t for t in MZ.TFS if t in (timeframes or MZ.TFS)]
        with self._lock:
            if not enabled:
                self.live.pop(inst, None)
            else:
                cur = self.live.get(inst)
                if cur:
                    cur["tfs"] = tfs                                       # same subscription, updated TF selection
                else:
                    self.live[inst] = {"tfs": tfs, "last_closed": {}, "since": iso(self.clock())}
            if self.live and (self._poller is None or not self._poller.is_alive()):
                self._poller = threading.Thread(target=self._poll_loop, name="mzones-live", daemon=True)
                self._poller.start()
        self.start()
        if enabled:
            self.request(inst, tfs, reason="live:start")
        self._publish(inst, None)
        return {"instrument": inst, "live": enabled, "timeframes": tfs, "subscriptions": len(self.live)}

    def _poll_loop(self) -> None:
        while not self._stop.wait(self.poll_s):
            with self._lock:
                subs = {k: dict(v, tfs=list(v["tfs"])) for k, v in self.live.items()}
            if not subs:
                return
            for inst, sub in subs.items():
                try:
                    self.poll_once(inst, sub["tfs"])
                except Exception as exc:  # noqa: BLE001
                    if self.log:
                        self.log.warning("market_zones", f"live {inst}: {type(exc).__name__}: {exc}"[:200])

    def poll_once(self, inst: str, tfs: list[str]) -> list[str]:
        """One live check: TFs whose newest CLOSED candle changed (or that recovered after a data loss) are recomputed; the live quote
        marks preliminary touches / breaches of visible zones."""
        due = []
        for tf in tfs:
            try:
                rows, read_at, _ = self._read(inst, tf, 3)
            except Exception as exc:  # noqa: BLE001
                self._mark_stale(inst, tf, "ERROR", f"{type(exc).__name__}: {exc}"[:240])
                continue
            st = self._classify(rows, tf, read_at)
            last = st.get("last_closed")
            with self._lock:
                sub = self.live.get(inst)
                if sub is None:
                    return due
                prev = sub["last_closed"].get(tf)
                was_bad = (self.status.get((inst, tf)) or {}).get("status") in ("ERROR", "NO_DATA") or (self.tf.get((inst, tf)) or {}).get("restored")
                if last and (last != prev or was_bad):
                    sub["last_closed"][tf] = last
                    due.append(tf)
                elif st["status"] == "STALE":
                    self.status[(inst, tf)] = {**st, "checked_at": iso(read_at)}
        if due:
            self.counters["live_recomputes"] += 1
            self.request(inst, due, reason="live:" + ",".join(due))
        self._live_quote(inst)
        return due

    def _live_quote(self, inst: str) -> None:
        sym = self.symbol_for(inst)
        if not sym:
            return
        try:
            q = self.bridge.symbol_quote(sym)
        except Exception as exc:  # noqa: BLE001
            self.quotes[inst] = {"status": "ERROR", "reason": f"{type(exc).__name__}"}
            return
        if not q:
            return
        self.quotes[inst] = {**q, "status": "OK", "preliminary": True,
                             "note": "dotknięcia / przełamania z ceny na żywo są wstępne – potwierdzenie po zamknięciu świecy"}

    # ------------------------------------------------------------------ outputs
    def view(self, instrument: str, *, all_zones: bool = False) -> dict:
        inst = str(instrument).upper()
        with self._lock:
            per = {tf: v["raw"] for (i, tf), v in self.tf.items() if i == inst}
            meta = {tf: {k: v for k, v in self.tf[(inst, tf)].items() if k != "raw"} for tf in per}
            status = {tf: dict(self.status.get((inst, tf)) or {"status": "IDLE", "reason": None}) for tf in MZ.TFS}
            job = self.current_job.get(inst)
            live = self.live.get(inst)
        fin = MZ.finalize(per, instrument=inst, symbol=self.symbol_for(inst) or "", as_of=None) if per else {"timeframes": {}, "rules": MZ.RULES,
                                                                                                            "params": MZ.params_for(inst)}
        q = self.quotes.get(inst) or {}
        bid = q.get("bid")
        out_tf = {}
        for tf in MZ.TFS:
            st = status[tf]
            st["status_pl"] = STATUS_PL.get(st.get("status"), st.get("status"))
            r = fin["timeframes"].get(tf)
            stale = st.get("status") in ("ERROR", "NO_DATA", "STALE") or bool((meta.get(tf) or {}).get("restored"))
            if r is None:
                out_tf[tf] = {"status": st, "zones": [], "visible": [], "stale": stale, "computed": False}
                continue
            zones = r["zones"] if all_zones else [z for z in r["zones"] if z["id"] in r["visible"]]
            for z in zones:
                z["stale"] = stale
                if bid is not None and z["state"] in MZ.LIVE:
                    inside = z["lower"] <= bid <= z["upper"]
                    beyond = bid < z["lower"] if z["side"] == "BELOW" else bid > z["upper"]
                    z["live"] = {"price": bid, "touching": inside, "beyond": beyond, "preliminary": True}
            out_tf[tf] = {"status": st, "zones": zones, "visible": r["visible"], "counts": r["counts"], "atr": r.get("atr"),
                          "min_width": r.get("min_width"), "bars": r.get("bars"), "last_closed": r.get("last_closed"),
                          "computed_as_of": r.get("computed_as_of"), "computed_at": iso((meta.get(tf) or {}).get("computed_at")),
                          "stale": stale, "restored": bool((meta.get(tf) or {}).get("restored")), "computed": True}
        return {"instrument": inst, "symbol": self.symbol_for(inst), "version": MZ.VERSION, "timeframes": out_tf,
                "job": job.public() if job else None, "live": {"enabled": bool(live), **(live or {})}, "quote": q or None,
                "rules": MZ.RULES, "params": MZ.params_for(inst), "counters": dict(self.counters), "mode": "ANALYTICAL_ONLY",
                "note": "strefy są informacją analityczną – nie otwierają pozycji i nie zmieniają ustawień handlu"}

    def zone(self, instrument: str, zone_id: str) -> dict | None:
        v = self.view(instrument, all_zones=True)
        for tf, r in v["timeframes"].items():
            for z in r["zones"]:
                if z["id"] == zone_id:
                    with self._lock:
                        ev = [dict(x) for x in self.db.execute("SELECT tf, event, at FROM mz_events WHERE instrument=? AND zone_id=? ORDER BY at",
                                                               (v["instrument"], zone_id)).fetchall()]
                    return {"zone": z, "checklist": checklist(z, r, v.get("quote")), "events": ev, "timeframe_status": r["status"],
                            "rules": MZ.RULES}
        return None

    def job(self, job_id: str) -> dict | None:
        j = self.jobs.get(job_id)
        return j.public() if j else None

    def at(self, instrument: str, as_of: float, timeframes: list[str] | None = None) -> dict:
        """Historical state: bars read now, cut at as_of (no data after as_of enters any calculation)."""
        inst = str(instrument).upper()
        series, spreads, sym = {}, {}, self.symbol_for(inst) or ""
        for tf in [t for t in MZ.TFS if t in (timeframes or MZ.TFS)]:
            rows, _, meta = self._read(inst, tf, MZ.TF_PARAMS[tf]["bars"])
            point = float(meta.get("point") or 0.01)
            series[tf] = Series.from_bars(rows, tf, as_of)
            spreads[tf] = MZ.spread_price([b for b in rows if b.get("open_utc") and ts(b["open_utc"]) + TF_SECONDS[tf] <= as_of], point)
        return MZ.compute(series, instrument=inst, symbol=sym, tick=point if series else 0.01, as_of=as_of, spreads=spreads)

    def events(self, instrument: str, limit: int = 200) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self.db.execute("SELECT * FROM mz_events WHERE instrument=? ORDER BY at DESC LIMIT ?",
                                                     (str(instrument).upper(), int(limit))).fetchall()]

    def _publish(self, inst: str, job: Job | None) -> None:
        if self.bus is None:
            return
        try:
            self.bus.publish("market_zones", {"instrument": inst, "job": job.public() if job else None, "live": inst in self.live})
        except Exception:  # noqa: BLE001
            pass


def checklist(z: dict, tf_view: dict, quote: dict | None) -> dict:
    """Description of one zone against explicit criteria. It describes the zone; it is NOT an entry signal."""
    atr = z.get("atr") or 0.0
    width = z["upper"] - z["lower"]
    spread = (quote or {}).get("spread")
    price = (quote or {}).get("bid") or tf_view.get("price")
    dist = None
    if price is not None:
        dist = 0.0 if z["lower"] <= price <= z["upper"] else min(abs(price - z["lower"]), abs(price - z["upper"]))
    items = [
        {"label": "Strefa potwierdzona (nie wstępna)", "ok": not z.get("preliminary"), "value": "wstępna" if z.get("preliminary") else "potwierdzona"},
        {"label": "Stan aktywna lub testowana", "ok": z["state"] in ("ACTIVE", "TESTED"), "value": z["state_pl"]},
        {"label": "Dane źródłowe aktualne", "ok": not tf_view.get("stale"), "value": (tf_view.get("status") or {}).get("status_pl")},
        {"label": "Niezależne testy <= 2 (kolejne testy osłabiają strefę)", "ok": z.get("tests", 0) <= 2, "value": z.get("tests", 0), "threshold": 2},
        {"label": "Konfluencja z >= 1 innym interwałem", "ok": (z.get("confluence") or {}).get("count", 0) >= 1,
         "value": ", ".join((z.get("confluence") or {}).get("timeframes") or []) or "brak"},
        {"label": "Szerokość <= 1,0 ATR", "ok": bool(atr) and width <= atr, "value": round(width / atr, 2) if atr else None, "threshold": 1.0},
        {"label": "Spread <= 25 % szerokości strefy (bieżące bid/ask)", "ok": None if spread is None else spread <= 0.25 * width,
         "value": spread, "threshold": round(0.25 * width, 6)},
        {"label": "Cena w odległości <= 2 ATR", "ok": None if dist is None or not atr else dist <= 2 * atr,
         "value": round(dist / atr, 2) if dist is not None and atr else None, "threshold": 2.0},
    ]
    if z["type"] in ("EQH", "EQL"):
        items.append({"label": "Obszar płynności wnioskowany z OHLC (nie zmierzony, nie zlecenia)", "ok": None, "value": "informacja"})
    return {"items": items, "passed": sum(1 for i in items if i["ok"] is True), "evaluated": sum(1 for i in items if i["ok"] is not None),
            "note": "checklista opisuje strefę – nie jest sygnałem wejścia ani prawdopodobieństwem"}
