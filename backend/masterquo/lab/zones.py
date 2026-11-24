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
import math
import os
import json
import threading
from datetime import UTC, datetime, timezone
from pathlib import Path

import numpy as np

from .common import arrays, atr, close_time

SCHEMA_VERSION = 2
RULES = "SDZ-1.0.0"
STORE_VERSION = "MQ-LAB-ZONES-2.0.0"
# 1.46: LabService.tick() detects / processes zones on these TFs only - a manual zone on another TF (M5, a typo) was stored and never
# processed, i.e. FRESH forever whatever the price did
TRACKED_TFS = ("M15", "H1")
EVENTS_MAX = 200                    # 1.46: ZoneStore.events was unbounded (a permanent snapshot failure appended ~576 entries / day)


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


def _level(v, name: str) -> float:
    """1.46: a zone edge is a finite number - text was compared lexicographically / stored as TEXT (process() then raised TypeError),
    +-inf broke every JSON list of zones (allow_nan=False -> 500)."""
    try:
        f = math.nan if isinstance(v, bool) else float(v)          # True / False are not prices
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"INVALID_{name}") from None
    if not math.isfinite(f):
        raise ValueError(f"INVALID_{name}")
    return f


def _norm_time(s) -> str:
    """1.46: origin_time parsed and normalised to YYYY-MM-DDTHH:MM:SSZ (process() compares it with bar times as text); naive = UTC."""
    try:
        d = datetime.fromisoformat(str(s).strip())                    # 3.11+: accepts the Z suffix
        d = (d.replace(tzinfo=UTC) if d.tzinfo is None else d).astimezone(UTC)
    except (ValueError, OverflowError):
        raise ValueError("INVALID_ORIGIN_TIME") from None
    if not 1970 <= d.year <= 2999:                                    # year 1 / 9999 is a typo, not a bar (and breaks ts() / _shift())
        raise ValueError("INVALID_ORIGIN_TIME")
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


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
        # 1.46: the lab thread and the API threads wrote the same zones_X.json.tmp without a lock (FileNotFoundError ->
        # DEGRADED_SNAPSHOT, mixed content); restore() runs under the same lock
        self._snap_lock = threading.RLock()
        self._restored: set[str] = set()           # 1.46: restore() before the first snapshot write of this process (see write_snapshot)
        self._dirty: set[str] = set()              # 1.46: lifecycle changed since the last snapshot (save() rewrites only then)

    def _event(self, ev: dict) -> None:
        self.events.append(ev)
        del self.events[:-EVENTS_MAX]              # 1.46: bounded (API / state read only the tail)

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
        # 1.46: every save() (2x per new M5 bar) rewrote the full snapshot with fsync even when nothing changed; now only on a new zone, a
        # lifecycle change since the last snapshot, a failed / missing snapshot (retry) or a missing .bak (keeps the main/.bak pair)
        f = self._file(asset)
        if new or asset in self._dirty or self.snapshot_status.get(asset) != "OK" or not f.exists() or not f.with_suffix(".json.bak").exists():
            snap = self.write_snapshot(asset)
        else:
            snap = self.snapshot_status[asset]
        stored = self.db.one("SELECT COUNT(*) AS n FROM lab_zones WHERE asset=? AND tombstone=0", (asset,))["n"]
        return {"saved": new, "stored": stored, "snapshot": snap}

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
                flags = set(json.loads(z["flags"]) if z["flags"] else [])
                try:
                    z["top"], z["bottom"] = _level(z["top"], "TOP"), _level(z["bottom"], "BOTTOM")
                    ok = z["top"] > z["bottom"]
                except ValueError:
                    ok = False
                if not ok:
                    # 1.46: a row with TEXT / inverted edges (left by a 1.45 PATCH) raised TypeError here, rolled back the whole transaction
                    # and stopped the lab tick; it is skipped with a flag until a manual edit repairs it
                    if "INVALID_LEVELS" not in flags:
                        con.execute("UPDATE lab_zones SET flags=?, updated_at=? WHERE zone_id=?",
                                    (json.dumps(sorted(flags | {"INVALID_LEVELS"})), _now(), z["zone_id"]))
                        changed += 1
                    continue
                lp = z["last_processed_bar"]
                start_after = lp or (z["confirmed_at"] and _shift(z["confirmed_at"], -tsec)) or z["origin_time"]
                todo = [k for k, t in enumerate(times) if t > start_after]
                if not todo:
                    continue
                # 1.46: also without a checkpoint (manual zone / AUTO zone never processed) a start before the window is a HISTORY_GAP -
                # it was flagged only after a checkpoint, so an origin older than the 600-bar window pretended continuity
                nxt = _try_shift(start_after, tsec)
                if nxt is not None and nxt < times[todo[0]] and start_after not in times:
                    flags.add("HISTORY_GAP")
                inside, state, touches, hist = bool(z["inside"]), z["state"], z["touch_count"], json.loads(z["history"])
                if lp is None and not z["confirmed_at"]:
                    # 1.46: manual zone (no displacement bar): the lifecycle starts at the base bar - when the base overlaps the zone, the
                    # bar leaving it (it opens at the base close, inside the zone) was counted as TOUCH/TESTED although price never returned
                    ob = None
                    for b in bars:
                        if b["open_utc"] > z["origin_time"]:
                            break
                        ob = b
                    if ob is not None and (_try_shift(ob["open_utc"], tsec) or "") <= z["origin_time"]:
                        ob = None                                       # origin not inside a bar of this window
                    inside = bool(ob is not None and ob["l"] <= z["top"] and ob["h"] >= z["bottom"])
                broken_at = None
                n_done = 0
                for k in todo:
                    n_done += 1
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
                # 1.46: the rating was computed once at INSERT (tests=0, age_bars=None) and never refreshed; AUTO zones now carry the
                # current tests and the closed bars since confirmed_at (None when not verifiable: HISTORY_GAP / confirmation before the
                # window without a counted age); manual zones keep MANUAL_BASELINE, a missing score is not invented
                sc = z["score"]
                comp = (json.loads(sc) if sc else {}).get("components")
                if comp is not None:
                    ca = z["confirmed_at"]
                    if ca and ca >= times[0]:
                        age = sum(1 for x in times if ca <= x <= last)
                    elif comp.get("age_bars") is not None and "HISTORY_GAP" not in flags:
                        age = comp["age_bars"] + n_done
                    else:
                        age = None
                    sc = json.dumps(score({"exit_strength_atr": comp.get("exit_strength_atr"), "base_len": comp.get("base_len"),
                                           "touch_count": touches}, age_bars=age))
                con.execute("UPDATE lab_zones SET state=?, touch_count=?, inside=?, history=?, last_processed_bar=?, broken_at=COALESCE(broken_at, ?), "
                            "flags=?, score=?, updated_at=? WHERE zone_id=?", (state, touches, int(inside), json.dumps(hist), last, broken_at,
                                                                               json.dumps(sorted(flags)) if flags else None, sc, _now(), z["zone_id"]))
                changed += 1
            con.execute("INSERT INTO lab_zone_checkpoints(asset, tf, last_bar, sequence, updated_at) VALUES (?,?,?,?,?) "
                        "ON CONFLICT(asset, tf) DO UPDATE SET last_bar=excluded.last_bar, sequence=excluded.sequence, updated_at=excluded.updated_at",
                        (asset, tf, times[-1], seq, _now()))
        if changed:
            self._dirty.add(asset)                      # 1.46: written by the next save() (no full rewrite when nothing changed)
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
        # 1.46: finite numeric edges, a TF that LabService processes and a parsed / normalised origin_time
        top, bottom = _level(top, "TOP"), _level(bottom, "BOTTOM")
        if kind not in ("DEMAND", "SUPPLY") or not top > bottom:
            raise ValueError("INVALID_ZONE")
        if tf not in TRACKED_TFS:
            raise ValueError(f"TF_NOT_TRACKED: {tf} ({'/'.join(TRACKED_TFS)})")
        origin_time = _norm_time(origin_time)
        # 1.46: the id had neither kind nor levels and save() silently skips an existing id (also a tombstone) while the new zone was
        # still returned -> a second zone on the same base bar was lost and a deleted zone could not be added again. The first zone keeps
        # the id format, further ones on the same base get a numbered id, an identical live zone is refused and save() is checked.
        base = f"SDZ-{asset}-{tf}-M-{origin_time}"
        dup = self.db.one("SELECT zone_id FROM lab_zones WHERE asset=? AND tf=? AND source='MANUAL' AND origin_time=? AND kind=? AND top=? "
                          "AND bottom=? AND tombstone=0", (asset, tf, origin_time, kind, top, bottom))
        if dup:
            raise ValueError(f"ZONE_EXISTS: {dup['zone_id']}")
        taken = {r["zone_id"] for r in self.db.query("SELECT zone_id FROM lab_zones WHERE zone_id=? OR substr(zone_id, 1, ?)=?",
                                                     (base, len(base) + 1, base + "-"))}
        zid = next(x for x in (base if n == 1 else f"{base}-{n}" for n in range(1, len(taken) + 2)) if x not in taken)
        z = {"zone_id": zid, "asset": asset, "tf": tf, "kind": kind, "top": top, "bottom": bottom,
             "origin_time": origin_time, "confirmed_at": None, "source": "MANUAL", "quality": "UNRATED", "state": "FRESH",
             "touch_count": 0, "history": [{"t": origin_time, "event": "MANUAL_CREATED"}]}
        if not self.save(asset, [z])["saved"]:
            raise ValueError(f"ZONE_EXISTS: {zid}")    # concurrent add of the same id
        return z

    def patch(self, zone_id: str, expected_revision: int, *, top: float | None = None, bottom: float | None = None, state: str | None = None,
              blacklist: bool | None = None, reason: str = "") -> dict:
        # 1.46: read, checks and write in ONE transaction - history appended by process() between a read outside it and the write was
        # overwritten (process() does not bump the revision)
        with self.db.tx() as con:
            row = con.execute("SELECT * FROM lab_zones WHERE zone_id=? AND tombstone=0", (zone_id,)).fetchone()
            if not row:
                raise KeyError("ZONE_NOT_FOUND")
            r = dict(row)
            if r["revision"] != expected_revision:
                raise ValueError(f"REVISION_CONFLICT: aktualna {r['revision']}")
            # 1.46: edges coerced to finite floats - text was compared lexicographically ('99.5' > '100'), raised TypeError against a
            # stored float or was stored as TEXT (process() then failed on every bar)
            nt = _level(top if top is not None else r["top"], "TOP")
            nb = _level(bottom if bottom is not None else r["bottom"], "BOTTOM")
            if not nt > nb:
                raise ValueError("ZERO_HEIGHT_ZONE")
            if state is not None and state not in ("FRESH", "TESTED", "BROKEN", "ARCHIVED", "EXPIRED", "INACTIVE"):
                raise ValueError("STATE_INVALID")
            now = _now()
            hist = json.loads(r["history"])
            geo = (nt, nb) != (r["top"], r["bottom"])
            entry = {"t": now, "event": "REVISION" if geo else "EDIT", "from_revision": r["revision"], "old": [r["top"], r["bottom"]] if geo else None,
                     "reason": reason[:200]}
            new_state, broken_at = state or r["state"], r.get("broken_at")
            if new_state != r["state"]:
                entry["state"] = [r["state"], new_state]
            hist.append(entry)
            # 1.46: a manual state change kept broken_at (a revived zone was active WITH a right edge) and a manual BROKEN had none
            # (drawn to infinity, history only 'EDIT')
            if new_state in ("FRESH", "TESTED"):
                broken_at = None
            elif new_state == "BROKEN" and r["state"] != "BROKEN":
                broken_at = r.get("last_processed_bar") or now
                hist.append({"t": now, "event": "BROKEN", "source": "MANUAL", "bar_t": r.get("last_processed_bar")})
            flags = set(json.loads(r["flags"]) if r.get("flags") else [])
            flags.discard("INVALID_LEVELS")                             # edges validated above
            cur = con.execute("UPDATE lab_zones SET top=?, bottom=?, state=?, blacklist=COALESCE(?, blacklist), revision=revision+1, history=?, "
                              "broken_at=?, flags=?, updated_at=? WHERE zone_id=? AND revision=?",
                              (nt, nb, new_state, None if blacklist is None else int(blacklist), json.dumps(hist), broken_at,
                               json.dumps(sorted(flags)) if flags else None, now, zone_id, expected_revision))
            if not cur.rowcount:
                raise ValueError("REVISION_CONFLICT")
        self.write_snapshot(r["asset"])
        return self.db.one("SELECT zone_id, revision, top, bottom, state, blacklist FROM lab_zones WHERE zone_id=?", (zone_id,))

    def delete(self, zone_id: str, expected_revision: int) -> dict:
        with self.db.tx() as con:                       # tombstone row + durable TOMBSTONE event (survives a lost zones table / older .bak)
            # 1.46: revision read and tombstone write in one transaction, the UPDATE guarded by the revision (a concurrent PATCH did not
            # block the delete of a revision the client never saw)
            row = con.execute("SELECT asset, revision FROM lab_zones WHERE zone_id=? AND tombstone=0", (zone_id,)).fetchone()
            if not row:
                raise KeyError("ZONE_NOT_FOUND")
            r = dict(row)
            if r["revision"] != expected_revision:
                raise ValueError(f"REVISION_CONFLICT: aktualna {r['revision']}")
            cur = con.execute("UPDATE lab_zones SET tombstone=1, revision=revision+1, updated_at=? WHERE zone_id=? AND revision=? AND tombstone=0",
                              (_now(), zone_id, expected_revision))
            if not cur.rowcount:
                raise ValueError("REVISION_CONFLICT")
            con.execute("INSERT OR IGNORE INTO lab_zone_events(event_key, asset, zone_id, revision, bar_t, type, seq, at, payload) VALUES (?,?,?,?,?,?,?,?,?)",
                        (f"{r['asset']}|{zone_id}|{r['revision']}|-|TOMBSTONE", r["asset"], zone_id, r["revision"], None, "TOMBSTONE", 0, _now(), None))
        self.write_snapshot(r["asset"])
        return {"ok": True, "zone_id": zone_id, "tombstone": True}

    # ------------------------------------------------------------ snapshot / restore
    def write_snapshot(self, asset: str) -> str:
        with self._snap_lock:                           # 1.46: one writer at a time (lab thread + API threads shared the .tmp path)
            if asset not in self._restored:
                # 1.46: restore() BEFORE the first write of this process - a write (API add / patch / delete, it works without MT5 and for
                # the inactive asset) after a DB loss rotated the only recovery point to .bak and restore() then used the new main file
                try:
                    self.restore(asset)
                except Exception as exc:                # noqa: BLE001 - never overwrite the recovery point after a failed restore
                    self.snapshot_status[asset] = f"DEGRADED_SNAPSHOT: RESTORE_{type(exc).__name__}"
                    self._event({"asset": asset, "event": "DEGRADED_SNAPSHOT", "error": f"RESTORE_{type(exc).__name__}"})
                    return self.snapshot_status[asset]
            self._dirty.discard(asset)                  # before the read: a process() change after it marks the asset dirty again
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
                self._event({"asset": asset, "event": "DEGRADED_SNAPSHOT", "error": type(exc).__name__})
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
        with self._snap_lock:                           # 1.46: serialised with write_snapshot()
            f = self._file(asset)
            used, corrupt = None, False
            for cand in (f, f.with_suffix(".json.bak")):
                if cand.exists() and self._valid(cand):
                    used = cand
                    break
                if cand.exists():
                    self._event({"asset": asset, "event": "SNAPSHOT_CORRUPT", "file": cand.name})
                    corrupt = True
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
                    self._event({"asset": asset, "event": "RESTORED_FROM_SNAPSHOT", "zones": restored, "file": used.name})
            self._restored.add(asset)
            if restored or corrupt:
                self._dirty.add(asset)                  # 1.46: the next save() rewrites a valid main snapshot
            return {"asset": asset, "snapshot_used": used.name if used else None, "restored": restored,
                    "zones": len(self.load_db(asset)), "events": self.events[-5:], "store_version": STORE_VERSION}

    def diagnostics(self, asset: str) -> dict:
        cp = self.db.query("SELECT * FROM lab_zone_checkpoints WHERE asset=?", (asset,))
        return {"store_version": STORE_VERSION, "checkpoints": cp, "snapshot": self.snapshot_status.get(asset, "NOT_WRITTEN"), "events": self.events[-10:],
                "tombstones": self.db.one("SELECT COUNT(*) AS n FROM lab_zones WHERE asset=? AND tombstone=1", (asset,))["n"]}


def _shift(t: str, sec: int) -> str:
    from .common import iso, ts
    return iso(ts(t) + sec)


def _try_shift(t, sec: int) -> str | None:
    """1.46: _shift() for stored times that may not parse (legacy manual origin_time) - None instead of failing the whole process()."""
    try:
        return _shift(t, sec)
    except (TypeError, ValueError, OverflowError):
        return None
