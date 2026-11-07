"""SVPService (PMW-SVP-1) - user profiles, frozen snapshots, zones MANUAL / ALGORITHM / AI, LIVE recomputation and AI LIVE.
Analytical only: no order path. Persistence: data/svp/svp.sqlite (profiles and zones are per instrument + broker symbol + account).

* A user profile row stores mode, range / session, grid (bin ticks), value-area %, colour, opacity, hidden, pinned; moving its time
  bounds creates a new version. FROZEN profiles serve their stored snapshot only.
* Zones are versioned (zone_id, version): an edit writes a new version, the old one stays in history (active = 0). MANUAL zones are
  never touched by ALGORITHM refresh or AI. Pinned zones of any source survive "clear automatic zones" and LIVE refresh.
* LIVE: on each new closed bar of the profile TF the LIVE profiles are recomputed; a generation counter per profile drops results of a
  slower, older job (no overwrite of a newer profile by an old one). Turning LIVE off releases it; closing a panel tab does not.
* AI: "Zaproponuj strefy AI" (on demand) and "AI LIVE - strefy analityczne" (opt-in): rate-limited, only after a significant profile
  change, one job in flight per profile, results applied only when their snapshot is still the latest. No agent -> AGENT_NOT_CONFIGURED,
  manual and algorithmic zones keep working.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from . import engine as EN
from . import zones as ZN

VERSION = "PMW-SVP-SERVICE-1"
SCHEMA = """
CREATE TABLE IF NOT EXISTS svp_profiles (profile_id TEXT PRIMARY KEY, name TEXT, instrument TEXT, symbol TEXT, account_key TEXT, mode TEXT,
  tf TEXT, t0 TEXT, t1 TEXT, session TEXT, profile_set TEXT, local_date TEXT, tz TEXT, start_hm TEXT, end_hm TEXT, bin_ticks INTEGER,
  va_pct REAL, color TEXT, opacity REAL, hidden INTEGER DEFAULT 0, pinned INTEGER DEFAULT 0, live INTEGER DEFAULT 0, ai_live INTEGER DEFAULT 0,
  frozen_snapshot TEXT, version INTEGER DEFAULT 1, created_at REAL, updated_at REAL, deleted INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS svp_snapshots (snapshot_id TEXT PRIMARY KEY, profile_id TEXT, created_at REAL, frozen INTEGER DEFAULT 0, payload TEXT);
CREATE INDEX IF NOT EXISTS ix_svp_snap_prof ON svp_snapshots(profile_id, created_at);
CREATE TABLE IF NOT EXISTS svp_zones (zone_id TEXT, version INTEGER, source TEXT, instrument TEXT, symbol TEXT, account_key TEXT, profile_id TEXT,
  snapshot_id TEXT, kind TEXT, lower REAL, upper REAL, name TEXT, color TEXT, description TEXT, pinned INTEGER DEFAULT 0, locked INTEGER DEFAULT 0,
  created_at REAL, available_at TEXT, valid_until TEXT, active INTEGER DEFAULT 1, payload TEXT, PRIMARY KEY(zone_id, version));
CREATE INDEX IF NOT EXISTS ix_svp_zones_sym ON svp_zones(symbol, active);
CREATE TABLE IF NOT EXISTS svp_ai_jobs (job_id TEXT PRIMARY KEY, profile_id TEXT, snapshot_id TEXT, status TEXT, requested_at REAL,
  finished_at REAL, reason TEXT, accepted INTEGER, rejected INTEGER, cost_usd REAL);
"""
EDITABLE = ("name", "mode", "tf", "t0", "t1", "session", "profile_set", "local_date", "tz", "start_hm", "end_hm", "bin_ticks", "va_pct",
            "color", "opacity", "hidden", "pinned")
GEOMETRY = ("mode", "tf", "t0", "t1", "session", "profile_set", "local_date", "tz", "start_hm", "end_hm", "bin_ticks", "va_pct")


def _default_dir() -> Path:
    from ..paths import data_dir
    return data_dir() / "svp"


class SVPService:
    def __init__(self, cfg_store, bridge, *, agent=None, bus=None, data_dir: Path | None = None, clock=time.time):
        self.cfg_store, self.bridge, self.agent, self.bus, self.clock = cfg_store, bridge, agent, bus, clock
        d = Path(data_dir or _default_dir())
        d.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(d / "svp.sqlite"), check_same_thread=False, isolation_level=None, timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self.gen: dict[str, int] = {}
        self.ai_inflight: set[str] = set()
        self.ai_last: dict[str, float] = {}
        self.last_bar: str | None = None
        self.state = {"version": VERSION, "live_runs": 0, "last_error": None, "ai": {"jobs": 0, "last": None}}
        self.ai_min_interval_s = 300.0
        self.visible_last: float | None = None

    # ------------------------------------------------------------------ context
    def _ctx(self) -> tuple[str, str, str | None, float]:
        app = self.cfg_store.get()
        info = getattr(self.bridge, "symbol_info", None) or {}
        tick = float(info.get("trade_tick_size") or info.get("point") or 0.01)
        return app.assets.active, app.mt5.symbol, getattr(self.bridge, "account_key", None), tick

    def _bars(self, tf: str, t0: float) -> list[dict]:
        from ..timeutil import TF_SECONDS
        _, sym, _, _ = self._ctx()
        n = int(min(20000, max(300, (self.clock() - t0) / TF_SECONDS[tf] + 50)))
        try:
            return self.bridge.symbol_bars(sym, tf, n)
        except Exception:  # noqa: BLE001 - deep read unavailable: bridge buffer (shorter history, reported as coverage)
            return self.bridge.bars(tf, include_forming=False)

    # ------------------------------------------------------------------ profiles
    def create_profile(self, spec: dict) -> dict:
        inst, sym, acct, _ = self._ctx()
        pid = "UP-" + uuid.uuid4().hex[:12]
        row = {k: spec.get(k) for k in EDITABLE}
        row.update(mode=(spec.get("mode") or "SESSION").upper(), tf=spec.get("tf") or "M5", bin_ticks=int(spec.get("bin_ticks") or 50),
                   va_pct=float(spec.get("va_pct") or 0.70), name=spec.get("name") or "Session Volume Profile", color=spec.get("color") or "#c8a24a",
                   opacity=float(spec.get("opacity") if spec.get("opacity") is not None else 0.6), hidden=int(bool(spec.get("hidden"))),
                   pinned=int(bool(spec.get("pinned"))))
        if row["mode"] not in EN.MODES or row["mode"] == "FROZEN":
            raise ValueError("SVP_MODE_INVALID")
        if not (0.3 < row["va_pct"] < 1.0):
            raise ValueError("SVP_VA_PCT_INVALID")
        now = self.clock()
        with self._lock:
            self.db.execute(f"INSERT INTO svp_profiles(profile_id, instrument, symbol, account_key, {', '.join(row)}, live, created_at, updated_at) "
                            f"VALUES (?,?,?,?,{','.join('?' * len(row))},?,?,?)",
                            (pid, inst, sym, acct, *row.values(), int(row["mode"] == "LIVE"), now, now))
        return self.profile(pid)

    def profile(self, pid: str) -> dict | None:
        r = self.db.execute("SELECT * FROM svp_profiles WHERE profile_id=? AND deleted=0", (pid,)).fetchone()
        return dict(r) if r else None

    def profiles(self) -> list[dict]:
        inst, sym, acct, _ = self._ctx()
        q = "SELECT * FROM svp_profiles WHERE deleted=0 AND instrument=? AND symbol=? AND (account_key IS ? OR account_key=?) ORDER BY created_at"
        return [dict(r) for r in self.db.execute(q, (inst, sym, acct, acct)).fetchall()]

    def update_profile(self, pid: str, patch: dict) -> dict:
        p = self.profile(pid)
        if p is None:
            raise KeyError("PROFILE_NOT_FOUND")
        if p["mode"] == "FROZEN" and any(k in patch for k in GEOMETRY):
            raise ValueError("FROZEN_PROFILE_GEOMETRY_LOCKED")
        upd = {k: patch[k] for k in EDITABLE if k in patch}
        if not upd:
            return p
        geo = any(k in upd and upd[k] != p[k] for k in GEOMETRY)
        upd["version"] = p["version"] + (1 if geo else 0)
        upd["updated_at"] = self.clock()
        if "mode" in upd:
            upd["live"] = int(str(upd["mode"]).upper() == "LIVE")
        with self._lock:
            self.db.execute(f"UPDATE svp_profiles SET {', '.join(k + '=?' for k in upd)} WHERE profile_id=?", (*upd.values(), pid))
        return self.profile(pid)

    def copy_settings(self, src: str, dst: str) -> dict:
        s = self.profile(src)
        if s is None:
            raise KeyError("PROFILE_NOT_FOUND")
        return self.update_profile(dst, {k: s[k] for k in ("bin_ticks", "va_pct", "color", "opacity")})

    def delete_profile(self, pid: str) -> bool:
        with self._lock:
            return self.db.execute("UPDATE svp_profiles SET deleted=1 WHERE profile_id=?", (pid,)).rowcount > 0

    def set_live(self, pid: str, on: bool) -> dict:
        with self._lock:
            self.db.execute("UPDATE svp_profiles SET live=? WHERE profile_id=?", (int(on), pid))
        return self.profile(pid)

    def set_ai_live(self, pid: str, on: bool) -> dict:
        with self._lock:
            self.db.execute("UPDATE svp_profiles SET ai_live=? WHERE profile_id=?", (int(on), pid))
        return self.profile(pid)

    # ------------------------------------------------------------------ compute
    def window(self, p: dict, as_of: float) -> tuple[float, float]:
        m = p["mode"]
        if m in ("RANGE", "VISIBLE"):
            return EN._ts(p["t0"]), EN._ts(p["t1"])
        app = self.cfg_store.get()
        pset = p.get("profile_set") or app.zones.session_profile.get(app.assets.active) or "LAB_XAU_REFERENCE_V1"
        if m == "LIVE" or (m == "SESSION" and not p.get("local_date") and not p.get("tz")):
            cur = EN.current_session(pset, as_of)
            if cur is None:
                raise ValueError("NO_ACTIVE_SESSION")
            return cur["start"], cur["end"]
        if p.get("tz") and p.get("start_hm") and p.get("end_hm"):
            return EN.custom_window(p["tz"], p["start_hm"], p["end_hm"], p["local_date"])
        return EN.session_window(pset, p["session"], p["local_date"])

    def compute(self, pid: str, *, as_of: float | None = None, store: bool = True) -> dict:
        p = self.profile(pid)
        if p is None:
            raise KeyError("PROFILE_NOT_FOUND")
        if p["mode"] == "FROZEN":
            snap = self.snapshot(p["frozen_snapshot"])
            return dict(snap or {"status": "NO_DATA", "reason": "brak zapisanego snapshotu"}, profile_id=pid, frozen=True)
        as_of = as_of if as_of is not None else self.clock()
        inst, sym, _, tick = self._ctx()
        self.gen[pid] = self.gen.get(pid, 0) + 1
        g = self.gen[pid]
        t0, t1 = self.window(p, as_of)
        prof = EN.compute(self._bars(p["tf"], t0), p["tf"], t0, t1, as_of=as_of, tick=tick, bin_ticks=p["bin_ticks"], value_area_pct=p["va_pct"],
                          instrument=inst, symbol=sym, mode=p["mode"], label=p["name"])
        prof.update(profile_id=pid, profile_version=p["version"], color=p["color"], opacity=p["opacity"])
        if g != self.gen.get(pid):                                    # a newer computation started meanwhile: drop this one
            prof["superseded"] = True
            return prof
        if store and prof.get("snapshot_id"):
            with self._lock:
                self.db.execute("INSERT OR IGNORE INTO svp_snapshots(snapshot_id, profile_id, created_at, frozen, payload) VALUES (?,?,?,0,?)",
                                (prof["snapshot_id"], pid, self.clock(), json.dumps(prof, default=float)))
        return prof

    def visible(self, tf: str, t0, t1, *, bin_ticks: int = 50, va_pct: float = 0.70) -> dict:
        now = self.clock()
        if not EN.visible_range_ok(self.visible_last, now):
            return {"status": "RATE_LIMITED", "reason": "zakres widoczny przeliczany najwyżej raz na sekundę"}
        self.visible_last = now
        inst, sym, _, tick = self._ctx()
        a = EN._ts(t0)
        return EN.compute(self._bars(tf, a), tf, a, t1, as_of=now, tick=tick, bin_ticks=bin_ticks, value_area_pct=va_pct, instrument=inst,
                          symbol=sym, mode="VISIBLE")

    def freeze(self, pid: str) -> dict:
        prof = self.compute(pid)
        if not prof.get("snapshot_id"):
            raise ValueError("NOTHING_TO_FREEZE: " + str(prof.get("reason")))
        with self._lock:
            self.db.execute("UPDATE svp_snapshots SET frozen=1 WHERE snapshot_id=?", (prof["snapshot_id"],))
            self.db.execute("UPDATE svp_profiles SET mode='FROZEN', live=0, frozen_snapshot=?, updated_at=? WHERE profile_id=?",
                            (prof["snapshot_id"], self.clock(), pid))
        return dict(prof, frozen=True)

    def snapshot(self, sid: str | None) -> dict | None:
        if not sid:
            return None
        r = self.db.execute("SELECT payload FROM svp_snapshots WHERE snapshot_id=?", (sid,)).fetchone()
        return json.loads(r["payload"]) if r else None

    def latest_snapshot(self, pid: str) -> dict | None:
        r = self.db.execute("SELECT payload FROM svp_snapshots WHERE profile_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1", (pid,)).fetchone()
        return json.loads(r["payload"]) if r else None

    # ------------------------------------------------------------------ zones
    def _insert_zone(self, z: dict, version: int = 1) -> None:
        inst, sym, acct, _ = self._ctx()
        self.db.execute("INSERT OR REPLACE INTO svp_zones(zone_id, version, source, instrument, symbol, account_key, profile_id, snapshot_id, kind, "
                        "lower, upper, name, color, description, pinned, locked, created_at, available_at, valid_until, active, payload) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)",
                        (z["zone_id"], version, z["source"], z.get("instrument") or inst, z.get("symbol") or sym, acct, z.get("profile_id"),
                         z.get("snapshot_id"), z.get("kind"), z["lower"], z["upper"], z.get("name"), z.get("color"), z.get("description"),
                         int(bool(z.get("pinned"))), int(bool(z.get("locked"))), z.get("created_at") or self.clock(), z.get("available_at"),
                         z.get("valid_until"), json.dumps(z, default=float)))

    def zones(self, *, source: str | None = None, profile_id: str | None = None, as_of: float | None = None) -> list[dict]:
        inst, sym, acct, _ = self._ctx()
        if as_of is None:
            q, args = "SELECT * FROM svp_zones WHERE active=1 AND symbol=? AND (account_key IS ? OR account_key=?)", [sym, acct, acct]
        else:                                                         # state as known at as_of: latest version created <= as_of
            q = ("SELECT z.* FROM svp_zones z JOIN (SELECT zone_id, MAX(version) v FROM svp_zones WHERE created_at <= ? AND symbol=? GROUP BY zone_id) m "
                 "ON z.zone_id=m.zone_id AND z.version=m.v WHERE (z.account_key IS ? OR z.account_key=?)")
            args = [as_of, sym, acct, acct]
        if source:
            q += " AND source=?"
            args.append(source)
        if profile_id:
            q += " AND profile_id=?"
            args.append(profile_id)
        out = []
        for r in self.db.execute(q, args).fetchall():
            d = dict(r)
            d.update({k: v for k, v in json.loads(d.pop("payload") or "{}").items() if k not in d})
            out.append(d)
        return out

    def create_manual(self, spec: dict) -> dict:
        _, sym, _, _ = self._ctx()
        lo, hi = float(spec["lower"]), float(spec["upper"])
        if not lo < hi:
            raise ValueError("ZONE_BOUNDS_INVALID")
        now = self.clock()
        z = {"zone_id": ZN.zone_id("MANUAL", sym, spec.get("snapshot_id"), spec.get("name") or "MANUAL", lo, hi) + "-" + uuid.uuid4().hex[:4],
             "source": "MANUAL", "kind": spec.get("kind") or "MANUAL", "lower": lo, "upper": hi, "name": spec.get("name") or "Strefa ręczna",
             "color": spec.get("color"), "description": spec.get("description"), "profile_id": spec.get("profile_id"),
             "snapshot_id": spec.get("snapshot_id"), "pinned": bool(spec.get("pinned", True)), "locked": bool(spec.get("locked")),
             "created_at": now, "available_at": EN._iso(now), "state": "CANDIDATE",
             "note": "czas utworzenia = rzeczywisty moment narysowania (bez wiedzy wstecznej)"}
        with self._lock:
            self._insert_zone(z)
        return z

    def edit_zone(self, zone_id: str, patch: dict) -> dict:
        with self._lock:
            r = self.db.execute("SELECT * FROM svp_zones WHERE zone_id=? AND active=1", (zone_id,)).fetchone()
            if r is None:
                raise KeyError("ZONE_NOT_FOUND")
            cur = dict(r)
            if cur["locked"] and not patch.get("unlock"):
                raise ValueError("ZONE_LOCKED")
            z = json.loads(cur["payload"] or "{}")
            z.update({k: patch[k] for k in ("lower", "upper", "name", "color", "description", "pinned", "locked") if k in patch})
            if patch.get("unlock"):
                z["locked"] = False
            if float(z["lower"]) >= float(z["upper"]):
                raise ValueError("ZONE_BOUNDS_INVALID")
            z["created_at"] = self.clock()
            self.db.execute("UPDATE svp_zones SET active=0 WHERE zone_id=? AND active=1", (zone_id,))
            self._insert_zone(z, version=cur["version"] + 1)
        return dict(z, version=cur["version"] + 1)

    def delete_zone(self, zone_id: str) -> bool:
        with self._lock:
            return self.db.execute("UPDATE svp_zones SET active=0 WHERE zone_id=? AND active=1", (zone_id,)).rowcount > 0

    def zone_history(self, zone_id: str) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT zone_id, version, source, lower, upper, name, pinned, locked, created_at, active "
                                                 "FROM svp_zones WHERE zone_id=? ORDER BY version", (zone_id,)).fetchall()]

    def _replace_auto(self, pid: str, source: str, new: list[dict], snapshot_id: str) -> None:
        with self._lock:
            keep = {r["zone_id"] for r in self.db.execute("SELECT zone_id FROM svp_zones WHERE profile_id=? AND source=? AND active=1 AND pinned=1",
                                                           (pid, source)).fetchall()}
            self.db.execute("UPDATE svp_zones SET active=0 WHERE profile_id=? AND source=? AND active=1 AND pinned=0", (pid, source))
            for z in new:
                if z["zone_id"] in keep:
                    continue
                z = dict(z, profile_id=pid, created_at=self.clock())
                self._insert_zone(z)

    def algo_now(self, pid: str) -> dict:
        prof = self.compute(pid)
        if prof.get("superseded"):
            return {"status": "SUPERSEDED"}
        zs = ZN.algorithmic(prof)
        from ..timeutil import TF_SECONDS
        bars = self._bars(prof["tf"], EN._ts(prof["start"]))
        zs = [ZN.evolve(z, bars, tf_s=TF_SECONDS[prof["tf"]], as_of=self.clock()) for z in zs]
        if prof.get("snapshot_id"):
            self._replace_auto(pid, "ALGORITHM", zs, prof["snapshot_id"])
        return {"profile": prof, "zones": zs, "events": ZN.profile_events(prof, bars, tf_s=TF_SECONDS[prof["tf"]])}

    def clear_auto(self, pid: str | None = None) -> int:
        q = "UPDATE svp_zones SET active=0 WHERE source IN ('ALGORITHM','AI') AND active=1 AND pinned=0"
        args: tuple = ()
        if pid:
            q += " AND profile_id=?"
            args = (pid,)
        with self._lock:
            return self.db.execute(q, args).rowcount

    # ------------------------------------------------------------------ AI
    def agent_status(self) -> dict:
        if self.agent is None:
            return {"state": "AGENT_NOT_CONFIGURED"}
        try:
            st = self.agent.status()
        except Exception as exc:  # noqa: BLE001
            return {"state": "ERROR", "detail": str(exc)[:120]}
        return {"state": st.get("state"), "model": st.get("model"), "spent_today_usd_estimate": st.get("spent_today_usd_estimate")}

    def ai_payload(self, snap: dict) -> dict:
        keep = ("snapshot_id", "geometry_id", "profile_id", "instrument", "symbol", "tf", "start", "end", "known_at", "state", "bin_size", "poc",
                "vah", "val", "hvn", "lvn", "high", "low", "volume_source", "method", "coverage", "value_area_pct")
        return {**{k: snap.get(k) for k in keep}, "histogram": snap.get("histogram", [])[:200],
                "rules": "propozycje tylko z poziomów profilu; backend odrzuci ceny bez podstawy"}

    async def ai_propose(self, pid: str) -> dict:
        snap = self.latest_snapshot(pid) or self.compute(pid)
        if not snap or not snap.get("snapshot_id"):
            return {"status": "NO_PROFILE", "accepted": [], "rejected": []}
        st = self.agent_status()
        if self.agent is None or st.get("state") in ("AGENT_NOT_CONFIGURED", "DISABLED", "AI_UNAVAILABLE_NO_KEY", "MODEL_NOT_CONFIGURED"):
            return {"status": "AGENT_NOT_CONFIGURED", "agent": st, "accepted": [], "rejected": [],
                    "note": "profile ręczne i strefy algorytmiczne działają bez agenta"}
        if pid in self.ai_inflight:
            return {"status": "IN_PROGRESS", "accepted": [], "rejected": []}
        self.ai_inflight.add(pid)
        job = "SVJ-" + uuid.uuid4().hex[:12]
        self.db.execute("INSERT INTO svp_ai_jobs(job_id, profile_id, snapshot_id, status, requested_at) VALUES (?,?,?,?,?)",
                        (job, pid, snap["snapshot_id"], "RUNNING", self.clock()))
        try:
            res = await self.agent.propose_zones(self.ai_payload(dict(snap, profile_id=pid)))
        finally:
            self.ai_inflight.discard(pid)
        return self.apply_ai(pid, snap, res, job)

    def apply_ai(self, pid: str, snap: dict, res: dict, job: str | None = None) -> dict:
        _, sym, _, _ = self._ctx()
        acc, rej = [], []
        if res.get("ok"):
            for prop in res.get("proposals") or []:
                ok, why, z = ZN.validate_ai(dict(prop, profile_id=prop.get("profile_id") or pid), dict(snap, profile_id=pid), symbol=sym, now=self.clock())
                (acc if ok else rej).append(z if ok else {"proposal": prop, "reason": why})
        latest = self.latest_snapshot(pid)
        stale = latest is not None and latest.get("snapshot_id") != snap.get("snapshot_id")
        if acc and not stale:
            self._replace_auto(pid, "AI", acc, snap["snapshot_id"])
        status = "ERROR" if not res.get("ok") else ("STALE_RESULT_DROPPED" if stale and acc else "OK")
        if job:
            self.db.execute("UPDATE svp_ai_jobs SET status=?, finished_at=?, reason=?, accepted=?, rejected=?, cost_usd=? WHERE job_id=?",
                            (status, self.clock(), res.get("error"), len(acc), len(rej), res.get("cost_usd_estimate"), job))
        self.ai_last[pid] = self.clock()
        self.state["ai"] = {"jobs": self.state["ai"]["jobs"] + 1, "last": {"profile_id": pid, "status": status, "accepted": len(acc), "rejected": len(rej)}}
        return {"status": status, "error": res.get("error"), "accepted": acc if not stale else [], "rejected": rej, "snapshot_id": snap.get("snapshot_id"),
                "cost_usd_estimate": res.get("cost_usd_estimate")}

    def ai_jobs(self, limit: int = 50) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM svp_ai_jobs ORDER BY requested_at DESC LIMIT ?", (limit,)).fetchall()]

    @staticmethod
    def significant_change(prev: dict | None, cur: dict, bins: int = 2) -> bool:
        if not prev or prev.get("poc") is None:
            return True
        bs = cur.get("bin_size") or 1.0
        return any(abs((cur.get(k) or 0) - (prev.get(k) or 0)) >= bins * bs - 1e-9 for k in ("poc", "vah", "val"))

    # ------------------------------------------------------------------ LIVE loop
    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="svp", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(5.0):
            try:
                self.live_tick()
            except Exception as exc:  # noqa: BLE001
                self.state["last_error"] = f"{type(exc).__name__}: {exc}"[:300]

    def live_tick(self) -> int:
        rows = self.bridge.bars("M1", include_forming=False)
        t = rows[-1].get("open_utc") if rows else None
        if not t or t == self.last_bar:
            return 0
        self.last_bar = t
        n = 0
        for p in self.profiles():
            if not p["live"] or p["mode"] == "FROZEN":
                continue
            prev = self.latest_snapshot(p["profile_id"])
            r = self.algo_now(p["profile_id"])
            n += 1
            cur = r.get("profile") or {}
            if p["ai_live"] and cur.get("snapshot_id") and self.significant_change(prev, cur) and \
                    self.clock() - self.ai_last.get(p["profile_id"], 0) >= self.ai_min_interval_s:
                loop = getattr(self.agent, "loop", None)
                if loop is not None and p["profile_id"] not in self.ai_inflight:
                    asyncio.run_coroutine_threadsafe(self.ai_propose(p["profile_id"]), loop)
        self.state["live_runs"] += n
        return n

    def status(self) -> dict:
        return {**self.state, "agent": self.agent_status(), "ai_inflight": sorted(self.ai_inflight),
                "note": "profil z OHLC = estymata aktywności; strefy to informacja analityczna, nie zlecenia"}
