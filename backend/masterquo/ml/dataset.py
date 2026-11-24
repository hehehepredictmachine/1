"""Persistent dataset of setup samples (table ml_samples, SQLite WAL) and immutable training snapshots.

Why SQLite: the bot already keeps all state in one local SQLite database with WAL, versioned migrations
and backups; samples are small rows (~5 KB), writes are idempotent (`INSERT OR IGNORE` on sample_id) and
the growth is bounded (one row per CONFIRMED setup). Training never reads the live table: it reads a
gzip-compressed JSONL snapshot written once (immutable, SHA-256 in the manifest).

Unit of learning = a setup at its decision point (first CONFIRMED). Every CONFIRMED setup becomes a
sample - also the ones not selected by AUTO or blocked by risk/AI/mode (no "executed only" bias).
Versions of one setup share group_id; correlated setups of one market event share event_id.
"""
from __future__ import annotations

import gzip
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from ..db.database import dumps
from ..timeutil import iso, utcnow
from . import features as fe
from . import labels as lb

UTC = timezone.utc
TRAINABLE = ("LABELED",)


class SampleStore:
    def __init__(self, db):
        self.db = db

    # ------------------------------------------------------------ create
    def create(self, *, rec: dict, setup_id: str, version: int, view, asof: datetime, source: str, quality: str, feed_id: str,
               cost: dict, synthetic: bool) -> bool:
        """Idempotent: a (setup_id, version) is stored once. Returns True when a new sample was created."""
        sid = f"{setup_id}:{version}"
        if {"COMMISSION_UNKNOWN", "SPREAD_UNKNOWN", "SLIPPAGE_POINT_UNKNOWN"} & set(cost.get("flags") or []):     # 1.46: unknown spread too
            quality = "COST_UNKNOWN"                   # the net label cannot be computed honestly -> never trained on
        if self.db.one("SELECT 1 AS x FROM ml_samples WHERE sample_id=?", (sid,)):
            return False
        if rec.get("stop_loss") is None or not rec.get("targets"):
            status, feats = "NO_ENTRY", {}
            # 1.46: make_spec -> execution.policy.from_plan(float(stop_loss)) raised TypeError for a setup without SL: the documented
            # NO_ENTRY / NO_VALID_LEVELS row was never written (collector error; a backfill aborted). No levels -> no label policy.
            entry = {"spec": None, "state": None, "reason": "NO_VALID_LEVELS"}
        else:
            feats = fe.to_json_safe(fe.compute(view, rec, asof))
            status = "PENDING"
            spec = lb.make_spec(rec, iso(asof), spread=cost["spread"], slippage=cost["slippage"], commission=cost["commission"], cost_flags=cost["flags"])
            entry = {"spec": spec, "state": lb.new_state(spec)}
        now = iso(utcnow())
        self.db.execute("""INSERT OR IGNORE INTO ml_samples(sample_id, setup_id, setup_version, group_id, event_id, symbol, feed_id, strategy_id, strategy_version,
                           direction, timeframe, asof_utc, feature_schema_version, features_json, entry_json, cost_model_version, label_policy_version, source,
                           quality, status, exit_reason, synthetic, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (sid, setup_id, version, setup_id, rec.get("event_id"), rec.get("symbol") or "XAUUSD-", feed_id, rec["strategy_id"], rec["strategy_version"],
                         rec["direction"], rec["timeframe"], iso(asof), fe.FEATURE_SCHEMA_VERSION, json.dumps(feats), dumps(entry),
                         lb.COST_MODEL_VERSION, lb.LABEL_POLICY_VERSION, source, quality, status, None if status == "PENDING" else "NO_VALID_LEVELS",
                         int(synthetic), now, now))
        return True

    # ------------------------------------------------------------ labelling
    def pending(self, limit: int = 500) -> list[dict]:
        return self.db.query("SELECT sample_id, asof_utc, entry_json FROM ml_samples WHERE status='PENDING' ORDER BY asof_utc LIMIT ?", (limit,))

    def advance(self, sample_id: str, entry_json: str, bars: list[dict], ticks: list[tuple], now: datetime, outcome_source: str = "HYPOTHETICAL") -> str:
        ej = json.loads(entry_json)
        state, res = lb.step(ej["spec"], ej["state"], bars, ticks, now)
        ej["state"] = state
        if res is None:
            self.db.execute("UPDATE ml_samples SET entry_json=?, updated_at=? WHERE sample_id=? AND status='PENDING'", (dumps(ej), iso(now), sample_id))
            return "PENDING"
        self.db.execute("""UPDATE ml_samples SET entry_json=?, status=?, label=?, outcome_r=?, mfe_r=?, mae_r=?, exit_reason=?, label_end_utc=?,
                           label_known_utc=?, outcome_source=?, updated_at=? WHERE sample_id=? AND status='PENDING'""",
                        (dumps(ej), res["status"], res.get("label"), res.get("outcome_r"), res.get("mfe_r"), res.get("mae_r"), res.get("exit_reason"),
                         res.get("label_end_utc"), iso(now) if res["status"] == "LABELED" else None, outcome_source if res["status"] == "LABELED" else None,
                         iso(now), sample_id))
        return res["status"]

    def attach_realized(self) -> int:
        """Link settled (fully CLOSED) PAPER/DEMO/LIVE trades to their setup's sample (kept next to the hypothetical label)."""
        n = 0
        for t in self.db.query("""SELECT t.setup_id, t.mode, t.net_pnl, t.gross_pnl, t.volume, t.closed_at, t.position_ticket FROM trades t
                                  JOIN ml_samples s ON s.setup_id = t.setup_id WHERE s.realized_json IS NULL AND t.status='CLOSED'"""):
            cnt = self.db.one("SELECT COUNT(*) AS n FROM trades WHERE setup_id=? AND status='CLOSED'", (t["setup_id"],))["n"]
            info = {"mode": t["mode"], "net_pnl": t["net_pnl"], "gross_pnl": t["gross_pnl"], "volume": t["volume"], "closed_at": t["closed_at"],
                    "attribution": "UNIQUE" if cnt == 1 else "MULTIPLE_POSITIONS_FOR_SETUP"}
            n += self.db.execute("UPDATE ml_samples SET realized_json=? WHERE setup_id=? AND realized_json IS NULL", (dumps(info), t["setup_id"])) or 0
        return n

    # ------------------------------------------------------------ stats & snapshots
    @staticmethod
    def _scope_sql(feed_ids=None, since: str | None = None, until: str | None = None) -> tuple[str, list]:
        """1.46 w2 (I0061): optional scope of a selection - feed ids (e.g. the offline run's own BACKFILL:OFFLINE_<dataset_id>) and a
        window of the decision time asof_utc (ISO UTC strings, inclusive). None = no restriction (the bot's own job)."""
        q, args = "", []
        if feed_ids is not None:
            ids = [str(x) for x in feed_ids]
            q += f" AND feed_id IN ({','.join('?' * len(ids))})" if ids else " AND 0"
            args += ids
        if since:
            q += " AND asof_utc >= ?"
            args.append(since)
        if until:
            q += " AND asof_utc <= ?"
            args.append(until)
        return q, args

    # 1.46 w2 (I0048): labels of the old offline cost basis (labels.LEGACY_OFFLINE_COST_MODELS: slippage 0, commission / contract size)
    _LEGACY_PRED = (f"(substr(source, 1, {len(lb.LEGACY_OFFLINE_SOURCE_PREFIX)}) = '{lb.LEGACY_OFFLINE_SOURCE_PREFIX}'"
                    f" AND cost_model_version IN ({','.join(repr(v) for v in lb.LEGACY_OFFLINE_COST_MODELS)}))")
    _LEGACY_COST = " AND NOT " + _LEGACY_PRED

    def counts(self, include_approx: bool, synthetic: bool, *, feed_ids=None, since: str | None = None, until: str | None = None) -> dict:
        sq, sa = self._scope_sql(feed_ids, since, until)
        q = (" AND synthetic=1" if synthetic else " AND synthetic=0") + ("" if include_approx else " AND quality='HIGH'") + " AND quality!='COST_UNKNOWN'" \
            + self._LEGACY_COST + sq
        rows = self.db.query(f"SELECT status, label, COUNT(*) AS n FROM ml_samples WHERE 1=1{q} GROUP BY status, label", tuple(sa))
        out = {"by_status": {}, "labeled": 0, "pos": 0, "neg": 0}
        for r in rows:
            out["by_status"][r["status"]] = out["by_status"].get(r["status"], 0) + r["n"]
            if r["status"] == "LABELED":
                out["labeled"] += r["n"]
                out["pos" if r["label"] == 1 else "neg"] += r["n"]
        out["unique_setups"] = (self.db.one(f"SELECT COUNT(DISTINCT setup_id) AS n FROM ml_samples WHERE status='LABELED'{q}", tuple(sa)) or {}).get("n", 0)
        out["samples"] = sum(out["by_status"].values())
        world = " AND synthetic=1" if synthetic else " AND synthetic=0"      # 1.46: the excluded counts mixed the synthetic and the real world
        out["approx_excluded"] = 0 if include_approx else (self.db.one("SELECT COUNT(*) AS n FROM ml_samples WHERE quality NOT IN ('HIGH','COST_UNKNOWN') AND status='LABELED'"
                                                                       + world + sq, tuple(sa)) or {}).get("n", 0)
        out["cost_unknown_excluded"] = (self.db.one("SELECT COUNT(*) AS n FROM ml_samples WHERE quality='COST_UNKNOWN'" + world + sq, tuple(sa)) or {}).get("n", 0)
        legacy = " AND quality!='COST_UNKNOWN' AND status='LABELED'" + ("" if include_approx else " AND quality='HIGH'") + world + sq
        out["legacy_cost_basis_excluded"] = (self.db.one("SELECT COUNT(*) AS n FROM ml_samples WHERE " + self._LEGACY_PRED + legacy, tuple(sa))
                                             or {}).get("n", 0)
        return out

    def eligible(self, include_approx: bool, cutoff: datetime, synthetic: bool, *, feed_ids=None, since: str | None = None,
                 until: str | None = None, report: dict | None = None) -> list[dict]:
        """Synthetic and real samples are never mixed: `synthetic` selects exactly one of the two worlds. 1.46 w2: samples of the old
        offline cost basis are never selected (I0048); feed_ids / since / until restrict the selection (I0061); one market event replayed
        by several backfill feeds (overlapping exports: setup_id BF-<feed>-<tracker setup id>, the same tracker id and decision time) is
        kept once - the first in time order (I0061). `report` (a dict) receives duplicates_dropped."""
        sq, sa = self._scope_sql(feed_ids, since, until)
        q = "status='LABELED' AND label_known_utc <= ? AND quality!='COST_UNKNOWN' AND synthetic=" + ("1" if synthetic else "0")
        if not include_approx:
            q += " AND quality='HIGH'"
        rows = self.db.query(f"""SELECT sample_id, setup_id, group_id, event_id, strategy_id, direction, timeframe, asof_utc, label_end_utc, label_known_utc,
                                 features_json, label, outcome_r, quality, source, feature_schema_version, feed_id FROM ml_samples
                                 WHERE {q}{self._LEGACY_COST}{sq} ORDER BY asof_utc""", (iso(cutoff), *sa))
        rows, dropped = _drop_cross_feed_duplicates(rows)
        if report is not None:
            report["duplicates_dropped"] = dropped
        return rows

    def snapshot(self, out_dir: Path, *, include_approx: bool, synthetic: bool, feed_ids=None, since: str | None = None,
                 until: str | None = None) -> dict:
        cutoff = utcnow()
        rep: dict = {}
        rows = self.eligible(include_approx, cutoff, synthetic, feed_ids=feed_ids, since=since, until=until, report=rep)
        sid = "SNAP-" + cutoff.strftime("%Y%m%dT%H%M%SZ") + "-" + hashlib.sha256(str(len(rows)).encode() + cutoff.isoformat().encode()).hexdigest()[:6]
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{sid}.jsonl.gz"
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        comp: dict = {"by_feed": {}, "by_source": {}, "by_quality": {}, "duplicates_dropped": rep.get("duplicates_dropped", 0)}
        for r in rows:                                   # 1.46 w2 (I0061): what the model is trained on, stated in the manifest
            for k, col in (("by_feed", "feed_id"), ("by_source", "source"), ("by_quality", "quality")):
                comp[k][r.get(col)] = comp[k].get(r.get(col), 0) + 1
        manifest = {"snapshot_id": sid, "cutoff_utc": iso(cutoff), "rows": len(rows), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "include_approx": include_approx, "synthetic": synthetic, "feature_schema_version": fe.FEATURE_SCHEMA_VERSION,
                    "label_policy_version": lb.LABEL_POLICY_VERSION, "cost_model_version": lb.COST_MODEL_VERSION, "path": str(path),
                    "scope": {"feed_ids": None if feed_ids is None else list(feed_ids), "since": since, "until": until}, "composition": comp}
        (out_dir / f"{sid}.manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
        return manifest


def _drop_cross_feed_duplicates(rows: list[dict]) -> tuple[list[dict], int]:
    """Backfill samples (source BACKFILL_<feed>, setup_id BF-<feed>-<tracker setup id>) of different feeds that are the same market event:
    the tracker setup id (hash of symbol / strategy / direction / TF / structure, account 'backfill') and the decision time are equal.
    The first in the given order is kept; live samples are never touched."""
    seen, out, dropped = set(), [], 0
    for r in rows:
        src = r.get("source") or ""
        if src.startswith("BACKFILL_"):
            pre = "BF-" + src.removeprefix("BACKFILL_") + "-"
            key = ((r.get("setup_id") or "").removeprefix(pre), r.get("asof_utc"))
            if key in seen:
                dropped += 1
                continue
            seen.add(key)
        out.append(r)
    return out, dropped


def load_snapshot(path: str) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]
