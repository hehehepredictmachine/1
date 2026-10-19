"""M18 Supply/Demand zones with versioned persistence (MQ-LAB-ZONES-2.0.0, PMW-UPD-07 R09 "Part V+").

Detection (own rule): a base candle followed within 2 bars by a displacement candle (body >= disp_atr x ATR14) away from it;
demand = base below an up-move, supply = base above a down-move. Life cycle: FRESH -> TESTED (price re-enters; touch_count)
-> BROKEN (close beyond the far edge). Origin = base bar open; confirmed_at = close of the displacement bar.

Persistence (own extension of the Part V idea - the article covers restore after a normal restart and does NOT claim crash
safety; the stronger durability below is ours): SQLite (WAL) is the source of truth. The detector only DISCOVERS zones (insert
if new - it never overwrites the stored lifecycle); the lifecycle is advanced incrementally from each zone's checkpoint
(`last_processed_bar`) by `process()`: one transaction writes the zone change, its interaction events (idempotent key
asset|zone|revision|bar|type) and the per-TF checkpoint. Entering the zone is ONE episode (several bars inside = one test; the next
test needs an exit first); touch and break in one bar without ticks -> flag ORDER_UNKNOWN_SAME_BAR (policy: touch then break).
A zone whose origin left the detector window stays in the store and in `list_asof()` (panel / SCI / training use the store).
Life: FRESH -> TESTED -> BROKEN -> ARCHIVED (EXPIRED optional), broken zones get a right edge (broken_at). Missing bars after the
checkpoint -> HISTORY_GAP flag (no pretended continuity). Score = explicit rule components (exit strength in ATR, base length,
age, tests) - a RATING, not a probability; manual zones stay UNRATED / MANUAL_BASELINE. Manual edits need the current revision
(optimistic check) and create a new revision; delete = tombstone (never resurrected by a restore).
JSON snapshot = export / recovery checkpoint (schema_version, asset, checkpoint_sequence, sha256; tmp -> fsync -> atomic replace,
last valid .bak) - NOT an independent source overriding the DB and NOT one atomic transaction with it; a failed write gives
DEGRADED_SNAPSHOT and is retried on the next save.
"""
from __future__ import annotations

import hashlib
import os
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .common import arrays, atr, close_time

SCHEMA_VERSION = 2
RULES = "SDZ-1.0.0"
STORE_VERSION = "MQ-LAB-ZONES-2.0.0"


def detect(bars: list[dict], tf: str, asset: str, disp_atr: float = 1.5) -> list[dict]:
    a = arrays(bars)
    at = atr(a["h"], a["l"], a["c"])
    out = []
    for i in range(15, len(bars) - 1):
        for j in (i + 1, i + 2):
            if j >= len(bars) or np.isnan(at[j]):
                continue
            body = a["c"][j] - a["o"][j]
            if abs(body) < disp_atr * at[j]:
                continue
            kind = "DEMAND" if body > 0 else "SUPPLY"
            body_hi, body_lo = max(a["o"][i], a["c"][i]), min(a["o"][i], a["c"][i])
            # demand: base low .. base body top; supply: base body bottom .. base high
            top, bot = (float(body_hi), float(a["l"][i])) if kind == "DEMAND" else (float(a["h"][i]), float(body_lo))
            if top - bot <= 0:
                continue
            zid = f"SDZ-{asset}-{tf}-{kind[0]}-{bars[i]['open_utc']}"
            z = {"zone_id": zid, "asset": asset, "tf": tf, "kind": kind, "top": round(top, 5), "bottom": round(bot, 5),
                 "origin_time": bars[i]["open_utc"], "confirmed_at": close_time(bars[j], tf), "source": "AUTO", "quality": "AUTO_RULE",
                 "state": "FRESH", "touch_count": 0, "history": [], "exit_strength_atr": round(float(abs(body) / at[j]), 3),
                 "base_len": j - i}
            _lifecycle(z, bars, a, j + 1)
            out.append(z)
            break
    seen, uniq = set(), []
    for z in out:
        if z["zone_id"] not in seen:
            seen.add(z["zone_id"])
            uniq.append(z)
    return uniq[-30:]


def _lifecycle(z: dict, bars: list[dict], a: dict, start: int) -> None:
    inside_prev = False
    for k in range(start, len(bars)):
        inside = a["l"][k] <= z["top"] and a["h"][k] >= z["bottom"]
        if inside and not inside_prev:
            z["touch_count"] += 1
            z["history"].append({"t": bars[k]["open_utc"], "event": "TOUCH"})
            if z["state"] == "FRESH":
                z["state"] = "TESTED"
        broken = a["c"][k] < z["bottom"] if z["kind"] == "DEMAND" else a["c"][k] > z["top"]
        if broken:
            z["state"] = "BROKEN"
            z["history"].append({"t": bars[k]["open_utc"], "event": "BROKEN"})
            break
        inside_prev = inside


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def score(z: dict, age_bars: int | None = None) -> dict:
    """Explicit rule rating (not a probability). Manual zones: MANUAL_BASELINE without detector quality."""
    if z.get("source") == "MANUAL":
        return {"rating": "MANUAL_BASELINE", "components": None, "source": "MANUAL"}
    comp = {"exit_strength_atr": z.get("exit_strength_atr"), "base_len": z.get("base_len"), "age_bars": age_bars, "tests": z.get("touch_count", 0)}
    pts = (2 if (comp["exit_strength_atr"] or 0) >= 2.5 else 1 if (comp["exit_strength_atr"] or 0) >= 1.5 else 0) + (1 if (comp["base_len"] or 9) <= 1 else 0) \
        - min(2, comp["tests"])
    return {"rating": "A" if pts >= 3 else "B" if pts >= 1 else "C", "components": comp, "points": pts, "rules": RULES}


class ZoneStore:
    def __init__(self, db, snapshot_dir: Path):
        self.db = db
        self.dir = Path(snapshot_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.events: list[dict] = []
        self.snapshot_status: dict[str, str] = {}

    def _file(self, asset: str) -> Path:
        return self.dir / f"zones_{asset}.json"

    # ------------------------------------------------------------ discovery (never overwrites the stored lifecycle)
    def save(self, asset: str, zones: list[dict], broker_symbol: str | None = None) -> dict:
        now = _now()
        new = 0
        with self.db.tx() as con:
            for z in zones:
                if z["asset"] != asset:
                    raise ValueError("ZONE_ASSET_MISMATCH")
                if z["top"] - z["bottom"] <= 0:
                    raise ValueError("ZERO_HEIGHT_ZONE")
                ex = con.execute("SELECT 1 FROM lab_zones WHERE zone_id=?", (z["zone_id"],)).fetchone()
                if ex:
                    continue                                    # existing zone: lifecycle is advanced only by process()
                quality = "UNRATED" if z["source"] == "MANUAL" else z["quality"]
                con.execute("INSERT INTO lab_zones(zone_id, schema_version, asset, broker_symbol, source, tf, kind, top, bottom, origin_time, "
                            "confirmed_at, state, touch_count, quality, rules_version, history, updated_at, revision, last_processed_bar, score, created_at) "
                            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (z["zone_id"], SCHEMA_VERSION, asset, broker_symbol, z["source"], z["tf"], z["kind"], z["top"], z["bottom"], z["origin_time"],
                             z.get("confirmed_at"), "FRESH", 0, quality, RULES, json.dumps([{"t": z.get("confirmed_at") or z["origin_time"], "event": "CREATED"}]),
                             now, 1, None, json.dumps(score(z)), now))
                new += 1
        snap = self.write_snapshot(asset)
        return {"saved": new, "stored": len(self.load_db(asset)), "snapshot": snap}

    # ------------------------------------------------------------ incremental lifecycle from the checkpoint
    def process(self, asset: str, tf: str, bars: list[dict]) -> dict:
        """Advance every live zone of (asset, tf) over CLOSED bars after its checkpoint. Replaying the same bars is a no-op."""
        if not bars:
            return {"processed": 0}
        from .common import TF_SEC
        tsec = TF_SEC[tf]
        times = [b["open_utc"] for b in bars]
        changed, ev_n = 0, 0
        with self.db.tx() as con:
            cp = con.execute("SELECT sequence FROM lab_zone_checkpoints WHERE asset=? AND tf=?", (asset, tf)).fetchone()
            seq = cp[0] if cp else 0
            rows = con.execute("SELECT * FROM lab_zones WHERE asset=? AND tf=? AND tombstone=0 AND state IN ('FRESH','TESTED')", (asset, tf)).fetchall()
            cols = [d[0] for d in con.execute("SELECT * FROM lab_zones LIMIT 0").description]
            for r in rows:
                z = dict(zip(cols, r))
                start_after = z["last_processed_bar"] or (z["confirmed_at"] and _shift(z["confirmed_at"], -tsec)) or z["origin_time"]
                todo = [k for k, t in enumerate(times) if t > start_after]
                if not todo:
                    continue
                flags = set(json.loads(z["flags"]) if z["flags"] else [])
                if z["last_processed_bar"] and _shift(z["last_processed_bar"], tsec) < times[todo[0]] and z["last_processed_bar"] not in times:
                    flags.add("HISTORY_GAP")
                inside, state, touches, hist = bool(z["inside"]), z["state"], z["touch_count"], json.loads(z["history"])
                broken_at = None
                for k in todo:
                    b = bars[k]
                    now_in = b["l"] <= z["top"] and b["h"] >= z["bottom"]
                    brk = b["c"] < z["bottom"] if z["kind"] == "DEMAND" else b["c"] > z["top"]
                    evs = []
                    if now_in and not inside:
                        touches += 1
                        evs.append("TOUCH")
                        if state == "FRESH":
                            state = "TESTED"
                    if brk:
                        if evs:
                            flags.add("ORDER_UNKNOWN_SAME_BAR")
                        state, broken_at = "BROKEN", b["open_utc"]
                        evs.append("BROKEN")
                    inside = now_in
                    for typ in evs:
                        seq += 1
                        key = f"{asset}|{z['zone_id']}|{z['revision']}|{b['open_utc']}|{typ}"
                        cur = con.execute("INSERT OR IGNORE INTO lab_zone_events(event_key, asset, zone_id, revision, bar_t, type, seq, at, payload) "
                                          "VALUES (?,?,?,?,?,?,?,?,?)", (key, asset, z["zone_id"], z["revision"], b["open_utc"], typ, seq, _now(), None))
                        if cur.rowcount:
                            hist.append({"t": b["open_utc"], "event": typ})
                            ev_n += 1
                    if state == "BROKEN":
                        break
                last = bars[k]["open_utc"]
                con.execute("UPDATE lab_zones SET state=?, touch_count=?, inside=?, history=?, last_processed_bar=?, broken_at=COALESCE(broken_at, ?), "
                            "flags=?, updated_at=? WHERE zone_id=?", (state, touches, int(inside), json.dumps(hist), last, broken_at,
                                                                      json.dumps(sorted(flags)) if flags else None, _now(), z["zone_id"]))
                changed += 1
            con.execute("INSERT INTO lab_zone_checkpoints(asset, tf, last_bar, sequence, updated_at) VALUES (?,?,?,?,?) "
                        "ON CONFLICT(asset, tf) DO UPDATE SET last_bar=excluded.last_bar, sequence=excluded.sequence, updated_at=excluded.updated_at",
                        (asset, tf, times[-1], seq, _now()))
        return {"processed": changed, "events": ev_n}

    def list_asof(self, asset: str, include_archived: bool = False) -> list[dict]:
        """Panel / SCI / training list from the restored store (not only the last detect()). Broken zones have a right edge."""
        rows = self.db.query("SELECT * FROM lab_zones WHERE asset=? AND tombstone=0 ORDER BY origin_time", (asset,))
        out = []
        for r in rows:
            if r["state"] == "ARCHIVED" and not include_archived:
                continue
            r["history"] = json.loads(r["history"])
            r["flags"] = json.loads(r["flags"]) if r.get("flags") else []
            r["score"] = json.loads(r["score"]) if r.get("score") else None
            r["right_edge"] = r.get("broken_at")
            r["active"] = r["state"] in ("FRESH", "TESTED")
            out.append(r)
        return out

    # ------------------------------------------------------------ manual CRUD (optimistic revision)
    def add_manual(self, asset: str, tf: str, kind: str, top: float, bottom: float, origin_time: str) -> dict:
        if kind not in ("DEMAND", "SUPPLY") or not top > bottom:
            raise ValueError("INVALID_ZONE")
        z = {"zone_id": f"SDZ-{asset}-{tf}-M-{origin_time}", "asset": asset, "tf": tf, "kind": kind, "top": top, "bottom": bottom,
             "origin_time": origin_time, "confirmed_at": None, "source": "MANUAL", "quality": "UNRATED", "state": "FRESH",
             "touch_count": 0, "history": [{"t": origin_time, "event": "MANUAL_CREATED"}]}
        self.save(asset, [z])
        return z

    def patch(self, zone_id: str, expected_revision: int, *, top: float | None = None, bottom: float | None = None, state: str | None = None,
              blacklist: bool | None = None, reason: str = "") -> dict:
        r = self.db.one("SELECT * FROM lab_zones WHERE zone_id=? AND tombstone=0", (zone_id,))
        if not r:
            raise KeyError("ZONE_NOT_FOUND")
        if r["revision"] != expected_revision:
            raise ValueError(f"REVISION_CONFLICT: aktualna {r['revision']}")
        nt, nb = (top if top is not None else r["top"]), (bottom if bottom is not None else r["bottom"])
        if not nt > nb:
            raise ValueError("ZERO_HEIGHT_ZONE")
        if state is not None and state not in ("FRESH", "TESTED", "BROKEN", "ARCHIVED", "EXPIRED", "INACTIVE"):
            raise ValueError("STATE_INVALID")
        hist = json.loads(r["history"])
        geo = (nt, nb) != (r["top"], r["bottom"])
        hist.append({"t": _now(), "event": "REVISION" if geo else "EDIT", "from_revision": r["revision"], "old": [r["top"], r["bottom"]] if geo else None,
                     "reason": reason[:200]})
        with self.db.tx() as con:
            cur = con.execute("UPDATE lab_zones SET top=?, bottom=?, state=COALESCE(?, state), blacklist=COALESCE(?, blacklist), revision=revision+1, history=?, "
                              "updated_at=? WHERE zone_id=? AND revision=?", (nt, nb, state, None if blacklist is None else int(blacklist), json.dumps(hist),
                                                                              _now(), zone_id, expected_revision))
            if not cur.rowcount:
                raise ValueError("REVISION_CONFLICT")
        self.write_snapshot(r["asset"])
        return self.db.one("SELECT zone_id, revision, top, bottom, state, blacklist FROM lab_zones WHERE zone_id=?", (zone_id,))

    def delete(self, zone_id: str, expected_revision: int) -> dict:
        r = self.db.one("SELECT asset, revision FROM lab_zones WHERE zone_id=? AND tombstone=0", (zone_id,))
        if not r:
            raise KeyError("ZONE_NOT_FOUND")
        if r["revision"] != expected_revision:
            raise ValueError(f"REVISION_CONFLICT: aktualna {r['revision']}")
        with self.db.tx() as con:                       # tombstone row + durable TOMBSTONE event (survives a lost zones table / older .bak)
            con.execute("UPDATE lab_zones SET tombstone=1, revision=revision+1, updated_at=? WHERE zone_id=?", (_now(), zone_id))
            con.execute("INSERT OR IGNORE INTO lab_zone_events(event_key, asset, zone_id, revision, bar_t, type, seq, at, payload) VALUES (?,?,?,?,?,?,?,?,?)",
                        (f"{r['asset']}|{zone_id}|{r['revision']}|-|TOMBSTONE", r["asset"], zone_id, r["revision"], None, "TOMBSTONE", 0, _now(), None))
        self.write_snapshot(r["asset"])
        return {"ok": True, "zone_id": zone_id, "tombstone": True}

    # ------------------------------------------------------------ snapshot / restore
    def write_snapshot(self, asset: str) -> str:
        rows = self.load_db(asset, include_tombstones=True)
        cp = self.db.query("SELECT tf, sequence, last_bar FROM lab_zone_checkpoints WHERE asset=?", (asset,))
        body = {"schema_version": SCHEMA_VERSION, "asset": asset, "saved_at": _now(), "checkpoint_sequence": {r["tf"]: r["sequence"] for r in cp},
                "zones": rows}
        raw = json.dumps(body, sort_keys=True)
        doc = json.dumps({"sha256": hashlib.sha256(raw.encode()).hexdigest(), "body": json.loads(raw)})
        f = self._file(asset)
        try:
            tmp = f.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(doc)
                fh.flush()
                try:
                    os.fsync(fh.fileno())
                except OSError:
                    pass
            if f.exists() and self._valid(f):
                f.replace(f.with_suffix(".json.bak"))       # keep the previous VALID snapshot
            tmp.replace(f)
            self.snapshot_status[asset] = "OK"
        except OSError as exc:
            self.snapshot_status[asset] = f"DEGRADED_SNAPSHOT: {type(exc).__name__}"
            self.events.append({"asset": asset, "event": "DEGRADED_SNAPSHOT", "error": type(exc).__name__})
        return self.snapshot_status[asset]

    @staticmethod
    def _valid(f: Path) -> bool:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            return hashlib.sha256(json.dumps(d["body"], sort_keys=True).encode()).hexdigest() == d["sha256"]
        except Exception:
            return False

    def load_db(self, asset: str, include_tombstones: bool = False) -> list[dict]:
        rows = self.db.query("SELECT * FROM lab_zones WHERE asset=?" + ("" if include_tombstones else " AND tombstone=0") + " ORDER BY origin_time", (asset,))
        for r in rows:
            r["history"] = json.loads(r["history"])
        return rows

    def restore(self, asset: str) -> dict:
        """Startup reconciliation: DB rows are the source of truth; a missing/corrupt snapshot falls back to .bak; a zone present only
        in the snapshot is re-inserted (by id, no duplicates) unless the DB or the snapshot holds its tombstone."""
        f = self._file(asset)
        used = None
        for cand in (f, f.with_suffix(".json.bak")):
            if cand.exists() and self._valid(cand):
                used = cand
                break
            if cand.exists():
                self.events.append({"asset": asset, "event": "SNAPSHOT_CORRUPT", "file": cand.name})
        db_rows = {r["zone_id"]: r for r in self.load_db(asset, include_tombstones=True)}
        restored = 0
        if used is not None:
            snap = json.loads(used.read_text(encoding="utf-8"))["body"]["zones"]
            tomb = {r["zone_id"] for r in self.db.query("SELECT zone_id FROM lab_zone_events WHERE asset=? AND type='TOMBSTONE'", (asset,))}
            missing = [z for z in snap if z["zone_id"] not in db_rows and not z.get("tombstone") and z["zone_id"] not in tomb]
            if missing:
                with self.db.tx() as con:
                    for z in missing:
                        con.execute("INSERT OR IGNORE INTO lab_zones(zone_id, schema_version, asset, broker_symbol, source, tf, kind, top, bottom, "
                                    "origin_time, confirmed_at, state, touch_count, quality, rules_version, history, updated_at, revision, "
                                    "last_processed_bar, inside, blacklist, trigger_flags, score, broken_at, created_at, flags) "
                                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                    (z["zone_id"], z["schema_version"], z["asset"], z.get("broker_symbol"), z["source"], z["tf"], z["kind"],
                                     z["top"], z["bottom"], z["origin_time"], z.get("confirmed_at"), z["state"], z["touch_count"],
                                     z["quality"], z["rules_version"], json.dumps(z["history"]), z["updated_at"], z.get("revision") or 1,
                                     z.get("last_processed_bar"), z.get("inside") or 0, z.get("blacklist") or 0, z.get("trigger_flags"), z.get("score"),
                                     z.get("broken_at"), z.get("created_at"), z.get("flags")))
                restored = len(missing)
                self.events.append({"asset": asset, "event": "RESTORED_FROM_SNAPSHOT", "zones": restored, "file": used.name})
        return {"asset": asset, "snapshot_used": used.name if used else None, "restored": restored,
                "zones": len(self.load_db(asset)), "events": self.events[-5:], "store_version": STORE_VERSION}

    def diagnostics(self, asset: str) -> dict:
        cp = self.db.query("SELECT * FROM lab_zone_checkpoints WHERE asset=?", (asset,))
        return {"store_version": STORE_VERSION, "checkpoints": cp, "snapshot": self.snapshot_status.get(asset, "NOT_WRITTEN"), "events": self.events[-10:],
                "tombstones": self.db.one("SELECT COUNT(*) AS n FROM lab_zones WHERE asset=? AND tombstone=1", (asset,))["n"]}


def _shift(t: str, sec: int) -> str:
    from .common import iso, ts
    return iso(ts(t) + sec)
