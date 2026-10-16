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
        cfg = cfg or self.db_cfg()
        sel = [r["id"] for r in self.list()] if ids is None else sorted({int(i) for i in ids})
        version = DB.VERSION_EXT if cfg.get("mode") == "EXTENDED" else DB.VERSION
        job_id = "DBJ-" + uuid.uuid4().hex[:12]
        self.db.execute("""INSERT INTO pattern_jobs(job_id, created_at, kind, sample_ids, config_hash, rules_version, status, total)
                           VALUES (?,?,?,?,?,?,?,?)""", (job_id, iso(utcnow()), "ALL" if ids is None else "SELECTED", json.dumps(sel),
                                                         contract.config_hash(cfg), version, "RUNNING", len(sel)))
        ev = threading.Event()
        with self._lock:
            self._jobs[job_id] = {"cancel": ev}
        threading.Thread(target=self._run, args=(job_id, sel, dict(cfg), version, ev), name=f"db-job-{job_id}", daemon=True).start()
        return {"ok": True, "job_id": job_id, "total": len(sel), "config_hash": contract.config_hash(cfg), "rules_version": version}

    def cancel(self, job_id: str) -> bool:
        j = self._jobs.get(job_id)
        if j:
            j["cancel"].set()
            return True
        return False

    def _run(self, job_id: str, ids: list[int], cfg: dict, version: str, cancel: threading.Event) -> None:
        counts = {s: 0 for s in DB.STATUSES} | {"ERROR": 0, "MISSING": 0}
        rows = []
        status = "COMPLETED"
        try:
            for k, sid in enumerate(ids):
                if cancel.is_set():
                    status = "CANCELLED"
                    break
                s = self.get(sid)
                if not s:
                    counts["MISSING"] += 1                      # deleted sample / gap in ids: reported, not fatal
                    st, res = "MISSING", {"error": "SAMPLE_NOT_FOUND_OR_DELETED"}
                else:
                    r = DB.validate(s["bars"], cfg, symbol=s["symbol"], tf=s["timeframe"], mode_label="offline_full_sample")
                    if r["status"] == "error":
                        st = "ERROR"
                    else:
                        st = r["values"]["status"] if r["values"]["status"] in DB.STATUSES else "ERROR"
                    counts[st] += 1
                    res = r
                self.db.execute("INSERT OR REPLACE INTO pattern_results(job_id, sample_id, status, result) VALUES (?,?,?,?)",
                                (job_id, sid, st, json.dumps(res, default=str)))
                rows.append((sid, s["symbol"] if s else None, s["timeframe"] if s else None, st, res))
                self.db.execute("UPDATE pattern_jobs SET progress=?, counts=? WHERE job_id=?", (k + 1, json.dumps(counts), job_id))
        except Exception as exc:                                 # program error != pattern FAILED
            status = "FAILED_EXECUTION"
            self.db.execute("UPDATE pattern_jobs SET error=? WHERE job_id=?", (f"{type(exc).__name__}: {exc}"[:500], job_id))
        report_id = f"DBR-{utcnow().strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}"
        export = "OK"
        try:
            self._write_report(report_id, job_id, ids, rows, counts, cfg, version, status)
        except OSError as exc:
            export = f"EXPORT_FAILED: {type(exc).__name__}"
        self.db.execute("UPDATE pattern_jobs SET status=?, counts=?, report_id=?, export_status=?, finished_at=? WHERE job_id=?",
                        (status, json.dumps(counts), report_id if export == "OK" else None, export, iso(utcnow()), job_id))
        with self._lock:
            self._jobs.pop(job_id, None)

    def _write_report(self, report_id, job_id, ids, rows, counts, cfg, version, status) -> None:
        d = lib_dir() / "reports"
        base = d / report_id
        if base.with_suffix(".json").exists():                  # collision guard: never overwrite a report
            base = d / f"{report_id}-{uuid.uuid4().hex[:4]}"
        rep = {"report_id": base.name, "job_id": job_id, "created_at": iso(utcnow()), "job_status": status, "complete": status == "COMPLETED",
               "rules_version": version, "config": cfg, "config_hash": contract.config_hash(cfg), "samples_requested": len(ids),
               "samples_processed": len(rows), "counts": counts,
               "results": [{"sample_id": sid, "symbol": sym, "timeframe": tf, "status": st,
                            "pattern_id": (res.get("values") or {}).get("pattern_id") if isinstance(res, dict) else None,
                            "reason": ((res.get("values") or {}).get("reason") if res.get("values") else res.get("reason") or res.get("error")) if isinstance(res, dict) else None,
                            "coordinates": (res.get("values") or {}).get("coordinates") if isinstance(res, dict) else None,
                            "measurements": (res.get("values") or {}).get("measurements") if isinstance(res, dict) else None}
                           for sid, sym, tf, st, res in rows]}
        tmp = base.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(rep, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        tmp.replace(base.with_suffix(".json"))
        with open(base.with_suffix(".csv"), "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh, quoting=csv.QUOTE_MINIMAL)
            w.writerow(["sample_id", "symbol", "timeframe", "status", "pattern_id", "reason", "bottom1", "bottom2", "neckline", "depth"])
            for r in rep["results"]:
                co = r["coordinates"] or {}
                w.writerow([r["sample_id"], r["symbol"], r["timeframe"], r["status"], r["pattern_id"], r["reason"],
                            (co.get("bottom1") or {}).get("price"), (co.get("bottom2") or {}).get("price"), (co.get("neckline") or {}).get("price"),
                            (r["measurements"] or {}).get("depth")])

    def job(self, job_id: str) -> dict | None:
        r = self.db.one("SELECT * FROM pattern_jobs WHERE job_id=?", (job_id,))
        if r:
            r["counts"] = json.loads(r["counts"]) if r.get("counts") else None
            r["sample_ids"] = json.loads(r["sample_ids"])
        return r

    def jobs(self, limit: int = 20) -> list[dict]:
        rows = self.db.query("SELECT job_id, created_at, kind, status, progress, total, counts, report_id, export_status, rules_version, finished_at "
                             "FROM pattern_jobs ORDER BY created_at DESC LIMIT ?", (limit,))
        for r in rows:
            r["counts"] = json.loads(r["counts"]) if r.get("counts") else None
        return rows

    def report(self, report_id: str) -> dict | None:
        if not report_id.replace("-", "").replace("_", "").isalnum():
            return None                                         # no path traversal through the id
        p = lib_dir() / "reports" / f"{report_id}.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
