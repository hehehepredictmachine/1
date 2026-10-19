"""Double Bottom pattern library: stored samples (raw OHLCV of the user's selection), single validation, library-wide
validation jobs (VALIDATE SELECTED / VALIDATE ALL) with job_id, progress, cancel and partial state, reports and export.

* Raw samples are never modified by validation; results and reports live in separate tables / files.
* A job freezes the list of sample ids and the configuration (config_hash) at start - later edits do not mix in.
* Every sample is validated by the SAME function as a single validation (analytics.double_bottom.validate) on its own bars.
* Data errors of a sample are counted as ERRORS, not as FAILED patterns.
* Computation success and export success are separate fields; a cancelled job is reported as CANCELLED (partial), never as
  complete. Report ids are new for every job; CSV fields are written by the csv module (quoting / escaping).
"""
from __future__ import annotations

import csv
import hashlib
import json
import threading
import uuid
from pathlib import Path

from .. import paths
from ..timeutil import iso, utcnow
from . import contract, double_bottom as DB


def lib_dir() -> Path:
    d = paths.data_dir() / "pattern_library"
    (d / "reports").mkdir(parents=True, exist_ok=True)
    return d


def _sha(bars: list[dict]) -> str:
    return hashlib.sha256(json.dumps([[b["open_utc"], b["o"], b["h"], b["l"], b["c"], b.get("tv")] for b in bars]).encode()).hexdigest()


def _clean_bars(bars: list[dict]) -> list[dict]:
    return [{"open_utc": str(b["open_utc"]), "o": float(b["o"]), "h": float(b["h"]), "l": float(b["l"]), "c": float(b["c"]),
             "tv": None if b.get("tv") is None else float(b["tv"])} for b in bars]


class PatternLibrary:
    def __init__(self, db, cfg_fn):
        self.db, self.cfg_fn = db, cfg_fn
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------ samples
    def add_sample(self, symbol: str, tf: str, bars: list[dict], origin: str, note: str | None = None) -> dict:
        try:
            bars = _clean_bars(bars)
        except (KeyError, TypeError, ValueError) as exc:
            return {"ok": False, "error": f"MALFORMED_BARS: {type(exc).__name__}"}
        bad = DB.check_bars(bars)
        if bad:
            return {"ok": False, "error": bad}
        if not 10 <= len(bars) <= 2000:
            return {"ok": False, "error": "SAMPLE_SIZE_10_2000"}
        sha = _sha(bars)
        ex = self.db.one("SELECT id FROM pattern_samples WHERE symbol=? AND timeframe=? AND start_utc=? AND end_utc=? AND data_sha256=?",
                         (symbol, tf, bars[0]["open_utc"], bars[-1]["open_utc"], sha))
        if ex:
            return {"ok": True, "id": ex["id"], "duplicate": True}
        self.db.execute("""INSERT INTO pattern_samples(created_at, symbol, timeframe, start_utc, end_utc, bars, data_sha256, origin, note)
                           VALUES (?,?,?,?,?,?,?,?,?)""", (iso(utcnow()), symbol, tf, bars[0]["open_utc"], bars[-1]["open_utc"], json.dumps(bars), sha,
                                                           origin, (note or "")[:500]))
        row = self.db.one("SELECT id FROM pattern_samples WHERE data_sha256=? AND symbol=? AND timeframe=? AND start_utc=?",
                          (sha, symbol, tf, bars[0]["open_utc"]))
        return {"ok": True, "id": row["id"], "duplicate": False, "bars": len(bars), "data_sha256": sha}

    def list(self, symbol: str | None = None, tf: str | None = None, status: str | None = None, rules_version: str | None = None) -> list[dict]:
        rows = self.db.query("SELECT id, created_at, symbol, timeframe, start_utc, end_utc, data_sha256, origin, note FROM pattern_samples WHERE deleted=0 ORDER BY id")
        rows = [r for r in rows if (not symbol or r["symbol"] == symbol) and (not tf or r["timeframe"] == tf)]
        last = {}
        for r in self.db.query("""SELECT pr.sample_id, pr.status, pj.rules_version, pj.job_id, pj.finished_at FROM pattern_results pr
                                  JOIN pattern_jobs pj ON pj.job_id = pr.job_id ORDER BY pr.id"""):
            last[r["sample_id"]] = r
        for r in rows:
            lr = last.get(r["id"])
            r["last_status"], r["last_rules_version"], r["last_job"] = (lr["status"], lr["rules_version"], lr["job_id"]) if lr else (None, None, None)
        if status:
            rows = [r for r in rows if r["last_status"] == status]
        if rules_version:
            rows = [r for r in rows if r["last_rules_version"] == rules_version]
        return rows

    def get(self, sid: int) -> dict | None:
        r = self.db.one("SELECT * FROM pattern_samples WHERE id=? AND deleted=0", (sid,))
        if r:
            r["bars"] = json.loads(r["bars"])
        return r

    def delete(self, sid: int) -> bool:
        return bool(self.db.execute("UPDATE pattern_samples SET deleted=1 WHERE id=? AND deleted=0", (sid,)))

    def export_samples(self) -> dict:
        return {"schema": "mq-pattern-library-1", "exported_at": iso(utcnow()),
                "samples": [{k: v for k, v in self.get(r["id"]).items() if k != "deleted"} for r in self.list()]}

    def import_samples(self, payload: dict) -> dict:
        if not isinstance(payload, dict) or payload.get("schema") != "mq-pattern-library-1" or not isinstance(payload.get("samples"), list):
            return {"ok": False, "error": "INVALID_FORMAT (oczekiwano schema mq-pattern-library-1)"}
        added = dup = 0
        errors = []
        for k, s in enumerate(payload["samples"][:5000]):
            try:
                r = self.add_sample(str(s["symbol"]), str(s["timeframe"]), s["bars"], "IMPORT", s.get("note"))
            except (KeyError, TypeError) as exc:
                r = {"ok": False, "error": type(exc).__name__}
            if not r["ok"]:
                errors.append({"index": k, "error": r["error"]})
            elif r.get("duplicate"):
                dup += 1
            else:
                added += 1
        return {"ok": True, "added": added, "duplicates_kept_existing": dup, "errors": errors}

    # ------------------------------------------------------------ validation
    def db_cfg(self) -> dict:
        return self.cfg_fn()

    def validate_one(self, sid: int, cfg: dict | None = None) -> dict:
        s = self.get(sid)
        if not s:
            return {"ok": False, "error": "SAMPLE_NOT_FOUND"}
        r = DB.validate(s["bars"], cfg or self.db_cfg(), symbol=s["symbol"], tf=s["timeframe"], mode_label="offline_full_sample")
        return {"ok": True, "sample_id": sid, "result": r}

    def start_job(self, ids: list[int] | None, cfg: dict | None = None) -> dict:
        """Freeze the manifest (sample ids + their data sha256 + symbol/TF, full-precision config, rules version) BEFORE any
        validation. Samples are immutable rows (delete = soft flag), so the manifest reproduces the exact input later."""
        cfg = cfg or self.db_cfg()
        sel = [r["id"] for r in self.list()] if ids is None else sorted({int(i) for i in ids})
        version = DB.VERSION_BUF if cfg.get("mode") == "BUFFERED" else DB.VERSION_EXT if cfg.get("mode") == "EXTENDED" else DB.VERSION
        job_id = "DBJ-" + uuid.uuid4().hex[:12]
        items = []
        for sid in sel:
            r = self.db.one("SELECT id, symbol, timeframe, data_sha256 FROM pattern_samples WHERE id=? AND deleted=0", (sid,))
            items.append({"sample_id": sid, "sample_sha": r["data_sha256"] if r else None, "symbol": r["symbol"] if r else None,
                          "timeframe": r["timeframe"] if r else None})
        manifest = {"schema": "mq-db-job-manifest-1", "job_id": job_id, "rules_version": version, "config": dict(cfg),
                    "config_hash": contract.config_hash(cfg), "items": items, "created_at": iso(utcnow())}
        msha = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
        self.db.execute("""INSERT INTO pattern_jobs(job_id, created_at, kind, sample_ids, config_hash, rules_version, status, total, manifest, manifest_sha)
                           VALUES (?,?,?,?,?,?,?,?,?,?)""", (job_id, iso(utcnow()), "ALL" if ids is None else "SELECTED", json.dumps(sel),
                                                             contract.config_hash(cfg), version, "RUNNING", len(sel), json.dumps(manifest), msha))
        self._spawn(job_id)
        return {"ok": True, "job_id": job_id, "total": len(sel), "config_hash": contract.config_hash(cfg), "rules_version": version, "manifest_sha": msha,
                "message": "Biblioteka pusta – zadanie zakończy się COMPLETED z total=0" if not sel else None}

    def _spawn(self, job_id: str) -> None:
        ev = threading.Event()
        with self._lock:
            self._jobs[job_id] = {"cancel": ev}
        threading.Thread(target=self._run, args=(job_id, ev), name=f"db-job-{job_id}", daemon=True).start()

    def mark_interrupted(self) -> int:
        """Startup: a RUNNING/QUEUED job without a live thread was interrupted (process restart) - never reported as complete."""
        live = set(self._jobs)
        rows = self.db.query("SELECT job_id FROM pattern_jobs WHERE status IN ('RUNNING','QUEUED')")
        n = 0
        for r in rows:
            if r["job_id"] not in live:
                self.db.execute("UPDATE pattern_jobs SET status='INTERRUPTED' WHERE job_id=?", (r["job_id"],))
                n += 1
        return n

    def resume(self, job_id: str) -> dict:
        j = self.db.one("SELECT status, manifest FROM pattern_jobs WHERE job_id=?", (job_id,))
        if not j:
            return {"ok": False, "error": "JOB_NOT_FOUND"}
        if j["status"] not in ("INTERRUPTED", "CANCELLED", "FAILED_EXECUTION"):
            return {"ok": False, "error": f"NOT_RESUMABLE: {j['status']}"}
        if not j["manifest"]:
            return {"ok": False, "error": "LEGACY_JOB_WITHOUT_MANIFEST"}
        self.db.execute("UPDATE pattern_jobs SET status='RUNNING', resumed=resumed+1, finished_at=NULL WHERE job_id=?", (job_id,))
        self._spawn(job_id)
        return {"ok": True, "job_id": job_id, "resumed": True}

    def cancel(self, job_id: str) -> bool:
        j = self._jobs.get(job_id)
        if j:
            j["cancel"].set()
            return True
        return False

    @staticmethod
    def _result_id(job_id: str, sid: int) -> str:
        return "DBRES-" + hashlib.sha256(f"{job_id}|{sid}".encode()).hexdigest()[:16]

    def _counts(self, job_id: str) -> dict:
        counts = {s: 0 for s in DB.STATUSES} | {"ERROR": 0, "MISSING": 0}
        for r in self.db.query("SELECT status, COUNT(*) AS n FROM pattern_results WHERE job_id=? GROUP BY status", (job_id,)):
            counts[r["status"]] = counts.get(r["status"], 0) + r["n"]
        return counts

    def _run(self, job_id: str, cancel: threading.Event) -> None:
        j = self.db.one("SELECT manifest FROM pattern_jobs WHERE job_id=?", (job_id,))
        man = json.loads(j["manifest"])
        cfg, items = man["config"], man["items"]
        self.db.execute("UPDATE pattern_jobs SET status='RUNNING' WHERE job_id=?", (job_id,))
        done = {r["sample_id"] for r in self.db.query("SELECT sample_id FROM pattern_results WHERE job_id=?", (job_id,))}
        status = "COMPLETED"
        try:
            for it in items:
                if it["sample_id"] in done:
                    continue                                    # resume: same manifest, no duplicated results
                if cancel.is_set():
                    status = "CANCELLED"
                    break
                sid = it["sample_id"]
                s = self.db.one("SELECT * FROM pattern_samples WHERE id=?", (sid,))   # deleted later -> still reproducible from the row
                if not s or it["sample_sha"] is None or s["data_sha256"] != it["sample_sha"]:
                    st, res = "MISSING", {"error": "SAMPLE_NOT_FOUND" if not s else "SAMPLE_REVISION_MISMATCH"}
                else:
                    r = DB.validate(json.loads(s["bars"]), cfg, symbol=s["symbol"], tf=s["timeframe"], mode_label="offline_full_sample")
                    st = "ERROR" if r["status"] == "error" else (r["values"]["status"] if r["values"]["status"] in DB.STATUSES else "ERROR")
                    res = r
                usable = (res.get("values") or {}).get("usable_at") if isinstance(res, dict) else None
                self.db.execute("INSERT OR IGNORE INTO pattern_results(job_id, sample_id, status, result, result_id, sample_sha, usable_at, created_at) "
                                "VALUES (?,?,?,?,?,?,?,?)", (job_id, sid, st, json.dumps(res, default=str), self._result_id(job_id, sid), it["sample_sha"],
                                                            usable, iso(utcnow())))
                c = self._counts(job_id)
                self.db.execute("UPDATE pattern_jobs SET progress=?, counts=? WHERE job_id=?", (sum(c.values()), json.dumps(c), job_id))
        except Exception as exc:                                 # program error != pattern FAILED
            status = "FAILED_EXECUTION"
            self.db.execute("UPDATE pattern_jobs SET error=? WHERE job_id=?", (f"{type(exc).__name__}: {exc}"[:500], job_id))
        c = self._counts(job_id)
        self.db.execute("UPDATE pattern_jobs SET status=?, counts=?, progress=?, finished_at=? WHERE job_id=?",
                        (status, json.dumps(c), sum(c.values()), iso(utcnow()), job_id))
        self.export(job_id)                                     # export success is separate from validation success
        with self._lock:
            self._jobs.pop(job_id, None)

    def export(self, job_id: str) -> dict:
        """(Re)write the JSON + CSV report from STORED results - no validation is run. A failure keeps the results (EXPORT_FAILED)."""
        j = self.job(job_id)
        if not j:
            return {"ok": False, "error": "JOB_NOT_FOUND"}
        report_id = f"DBR-{utcnow().strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}"
        try:
            rid = self._write_report(report_id, j)
            self.db.execute("UPDATE pattern_jobs SET report_id=?, export_status='OK' WHERE job_id=?", (rid, job_id))
            return {"ok": True, "report_id": rid}
        except OSError as exc:
            self.db.execute("UPDATE pattern_jobs SET export_status=? WHERE job_id=?", (f"EXPORT_FAILED: {type(exc).__name__}", job_id))
            return {"ok": False, "error": f"EXPORT_FAILED: {type(exc).__name__}"}

    def results(self, job_id: str) -> list[dict]:
        rows = self.db.query("SELECT result_id, sample_id, status, sample_sha, usable_at, created_at FROM pattern_results WHERE job_id=? ORDER BY sample_id", (job_id,))
        return rows

    def result(self, result_id: str) -> dict | None:
        r = self.db.one("SELECT pr.*, pj.rules_version, pj.config_hash, pj.manifest_sha FROM pattern_results pr JOIN pattern_jobs pj ON pj.job_id=pr.job_id "
                        "WHERE pr.result_id=?", (result_id,))
        if r:
            r["result"] = json.loads(r["result"])
        return r

    def latest_result(self, sid: int) -> dict | None:
        r = self.db.one("SELECT result_id FROM pattern_results WHERE sample_id=? AND result_id IS NOT NULL ORDER BY id DESC LIMIT 1", (sid,))
        return self.result(r["result_id"]) if r else None

    @staticmethod
    def _safe_cell(v):
        """Spreadsheet-safe cell: text starting with = + - @ TAB CR is prefixed with ' (formula injection)."""
        if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
            return "'" + v
        return v

    def _write_report(self, report_id, j) -> str:
        d = lib_dir() / "reports"
        base = d / report_id
        if base.with_suffix(".json").exists():                  # collision guard: never overwrite a report
            base = d / f"{report_id}-{uuid.uuid4().hex[:4]}"
        man = json.loads(j["manifest"]) if j.get("manifest") else None
        rows = self.db.query("SELECT pr.result_id, pr.sample_id, pr.status, pr.result, ps.symbol, ps.timeframe FROM pattern_results pr "
                             "LEFT JOIN pattern_samples ps ON ps.id = pr.sample_id WHERE pr.job_id=? ORDER BY pr.sample_id", (j["job_id"],))
        counts = j["counts"] or {}
        processed = sum(counts.values())
        res = []
        for r in rows:
            x = json.loads(r["result"])
            v = x.get("values") or {}
            res.append({"result_id": r["result_id"], "sample_id": r["sample_id"], "symbol": r["symbol"], "timeframe": r["timeframe"], "status": r["status"],
                        "pattern_id": v.get("pattern_id"), "reason": v.get("reason") if v else x.get("reason") or x.get("error"),
                        "coordinates": v.get("coordinates"), "measurements": v.get("measurements"), "usable_at": v.get("usable_at")})
        rep = {"report_id": base.name, "job_id": j["job_id"], "created_at": iso(utcnow()), "job_status": j["status"], "complete": j["status"] == "COMPLETED",
               "rules_version": j["rules_version"], "manifest_sha": j.get("manifest_sha"), "config": (man or {}).get("config"), "config_hash": j["config_hash"],
               "source": "pattern_library (manual selection – nie rynkowy win rate)", "samples_requested": j["total"], "processed": processed,
               "pending": j["total"] - processed, "counts": counts, "results": res,
               "message": "Biblioteka pusta (total=0)" if j["total"] == 0 else None}
        tmp = base.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(rep, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        tmp.replace(base.with_suffix(".json"))
        head = ["result_id", "sample_id", "symbol", "timeframe", "status", "pattern_id", "reason", "bottom1", "bottom2", "neckline", "depth", "usable_at"]

        def line(r):
            co = r["coordinates"] or {}
            return [r["result_id"], r["sample_id"], r["symbol"], r["timeframe"], r["status"], r["pattern_id"], r["reason"], (co.get("bottom1") or {}).get("price"),
                    (co.get("bottom2") or {}).get("price"), (co.get("neckline") or {}).get("price"), (r["measurements"] or {}).get("depth"), r["usable_at"]]
        with open(base.with_suffix(".csv"), "w", newline="", encoding="utf-8") as fh:          # machine-readable (exact values)
            w = csv.writer(fh, quoting=csv.QUOTE_MINIMAL)
            w.writerow(head)
            for r in res:
                w.writerow(line(r))
        with open(base.parent / f"{base.name}_sheet.csv", "w", newline="", encoding="utf-8-sig") as fh:   # spreadsheet-safe copy
            w = csv.writer(fh, quoting=csv.QUOTE_ALL)
            w.writerow(head)
            for r in res:
                w.writerow([self._safe_cell(x) for x in line(r)])
        return base.name

    def job(self, job_id: str) -> dict | None:
        r = self.db.one("SELECT * FROM pattern_jobs WHERE job_id=?", (job_id,))
        if r:
            r["counts"] = json.loads(r["counts"]) if r.get("counts") else None
            r["sample_ids"] = json.loads(r["sample_ids"])
            r["processed"] = sum((r["counts"] or {}).values())
            r["pending"] = r["total"] - r["processed"]
        return r

    def jobs(self, limit: int = 20) -> list[dict]:
        rows = self.db.query("SELECT job_id, created_at, kind, status, progress, total, counts, report_id, export_status, rules_version, finished_at, manifest_sha "
                             "FROM pattern_jobs ORDER BY created_at DESC LIMIT ?", (limit,))
        for r in rows:
            r["counts"] = json.loads(r["counts"]) if r.get("counts") else None
        return rows

    def report(self, report_id: str) -> dict | None:
        if not report_id.replace("-", "").replace("_", "").isalnum():
            return None                                         # no path traversal through the id
        p = lib_dir() / "reports" / f"{report_id}.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
