"""M18 Supply/Demand zones with versioned persistence (MQ-LAB-ZONES-1.0.0).

Detection (own rule): a base candle followed within 2 bars by a displacement candle (body >= disp_atr x ATR14) away from it;
demand = base below an up-move, supply = base above a down-move. Life cycle: FRESH -> TESTED (price re-enters; touch_count)
-> BROKEN (close beyond the far edge). Origin = base bar open; confirmed_at = close of the displacement bar.

Persistence: every save is ONE SQLite transaction (upsert by zone_id = no duplicates) plus an atomic JSON snapshot file
(tmp + replace) whose previous valid version is kept as .bak; a corrupt snapshot is detected by its sha256 and the .bak is
used, with a recovery event - never a silent loss or duplication. Manual zones are stored with quality UNRATED and never get an
automatic quality confirmation.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .common import arrays, atr, close_time

SCHEMA_VERSION = 1
RULES = "SDZ-1.0.0"


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
                 "state": "FRESH", "touch_count": 0, "history": []}
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


class ZoneStore:
    def __init__(self, db, snapshot_dir: Path):
        self.db = db
        self.dir = Path(snapshot_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.events: list[dict] = []

    def _file(self, asset: str) -> Path:
        return self.dir / f"zones_{asset}.json"

    def save(self, asset: str, zones: list[dict], broker_symbol: str | None = None) -> dict:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self.db.tx() as con:
            for z in zones:
                if z["asset"] != asset:
                    raise ValueError("ZONE_ASSET_MISMATCH")
                prev = con.execute("SELECT source, quality FROM lab_zones WHERE zone_id=?", (z["zone_id"],)).fetchone()
                quality = z["quality"]
                if prev and prev[0] == "MANUAL":
                    quality = prev[1]                       # manual zone never auto-upgraded
                con.execute("INSERT INTO lab_zones(zone_id, schema_version, asset, broker_symbol, source, tf, kind, top, bottom, origin_time, "
                            "confirmed_at, state, touch_count, quality, rules_version, history, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                            "ON CONFLICT(zone_id) DO UPDATE SET state=excluded.state, touch_count=excluded.touch_count, "
                            "history=excluded.history, quality=?, updated_at=excluded.updated_at",
                            (z["zone_id"], SCHEMA_VERSION, asset, broker_symbol, z["source"], z["tf"], z["kind"], z["top"], z["bottom"],
                             z["origin_time"], z.get("confirmed_at"), z["state"], z["touch_count"], quality, RULES,
                             json.dumps(z["history"]), now, quality))
        rows = self.load_db(asset)
        body = json.dumps({"schema_version": SCHEMA_VERSION, "asset": asset, "saved_at": now, "zones": rows}, sort_keys=True)
        doc = json.dumps({"sha256": hashlib.sha256(body.encode()).hexdigest(), "body": json.loads(body)})
        f = self._file(asset)
        if f.exists() and self._valid(f):
            f.replace(f.with_suffix(".json.bak"))           # keep the previous VALID snapshot
        tmp = f.with_suffix(".json.tmp")
        tmp.write_text(doc, encoding="utf-8")
        tmp.replace(f)
        return {"saved": len(zones), "stored": len(rows)}

    def add_manual(self, asset: str, tf: str, kind: str, top: float, bottom: float, origin_time: str) -> dict:
        if kind not in ("DEMAND", "SUPPLY") or not top > bottom:
            raise ValueError("INVALID_ZONE")
        z = {"zone_id": f"SDZ-{asset}-{tf}-M-{origin_time}", "asset": asset, "tf": tf, "kind": kind, "top": top, "bottom": bottom,
             "origin_time": origin_time, "confirmed_at": None, "source": "MANUAL", "quality": "UNRATED", "state": "FRESH",
             "touch_count": 0, "history": [{"t": origin_time, "event": "MANUAL_CREATED"}]}
        self.save(asset, [z])
        return z

    @staticmethod
    def _valid(f: Path) -> bool:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            return hashlib.sha256(json.dumps(d["body"], sort_keys=True).encode()).hexdigest() == d["sha256"]
        except Exception:
            return False

    def load_db(self, asset: str) -> list[dict]:
        rows = self.db.query("SELECT * FROM lab_zones WHERE asset=? ORDER BY origin_time", (asset,))
        for r in rows:
            r["history"] = json.loads(r["history"])
        return rows

    def restore(self, asset: str) -> dict:
        """Startup reconciliation: DB rows are the source of truth; a missing/corrupt snapshot falls back to .bak and any
        snapshot zone missing in the DB is re-inserted (by id - no duplicates)."""
        f = self._file(asset)
        used = None
        for cand in (f, f.with_suffix(".json.bak")):
            if cand.exists() and self._valid(cand):
                used = cand
                break
            if cand.exists():
                self.events.append({"asset": asset, "event": "SNAPSHOT_CORRUPT", "file": cand.name})
        db_rows = {r["zone_id"]: r for r in self.load_db(asset)}
        restored = 0
        if used is not None:
            snap = json.loads(used.read_text(encoding="utf-8"))["body"]["zones"]
            missing = [z for z in snap if z["zone_id"] not in db_rows]
            if missing:
                with self.db.tx() as con:
                    for z in missing:
                        con.execute("INSERT OR IGNORE INTO lab_zones(zone_id, schema_version, asset, broker_symbol, source, tf, kind, top, bottom, "
                                    "origin_time, confirmed_at, state, touch_count, quality, rules_version, history, updated_at) "
                                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                    (z["zone_id"], z["schema_version"], z["asset"], z.get("broker_symbol"), z["source"], z["tf"], z["kind"],
                                     z["top"], z["bottom"], z["origin_time"], z.get("confirmed_at"), z["state"], z["touch_count"],
                                     z["quality"], z["rules_version"], json.dumps(z["history"]), z["updated_at"]))
                restored = len(missing)
                self.events.append({"asset": asset, "event": "RESTORED_FROM_SNAPSHOT", "zones": restored, "file": used.name})
        return {"asset": asset, "snapshot_used": used.name if used else None, "restored": restored,
                "zones": len(self.load_db(asset)), "events": self.events[-5:]}
