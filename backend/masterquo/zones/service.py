"""ZoneService - live zone map of the active instrument (PMW-ZONES-SERVICE-1). Analytical only: no order path, no terminal trading calls.

* Recomputed once per new CLOSED M5 bar (own thread, poll 5 s) - never on every tick. Inputs: deep closed M5 / M15 history read
  through the bridge (symbol_bars, low priority), H1 / D1 from the bridge buffers. The map is a pure function of those bars and
  `as_of`, so a restart or a reconnect reproduces the same zone ids; completed session profiles are reproducible by construction.
* Persistence (data/zones/zones.sqlite): the latest maps (bounded) and a zone event log - one row per (zone_id, status), so a
  restart or a repeated computation never duplicates an event.
* Historical view: `at(as_of)` recomputes with bars cut at as_of (a pivot confirmed later is not shown as known earlier).
* Missing / stale data: the map carries data.state (OK / DEGRADED / STALE / INSUFFICIENT_HISTORY); downstream consumers must not
  treat a non-OK map as confirmed.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from . import engine as ZE
from . import features as ZF
from .series import iso

VERSION = "PMW-ZONES-SERVICE-1"
CHART_KEYS = ("zone_id", "zone_type", "polarity", "role", "timeframes", "lower_price", "upper_price", "width_atr", "created_at", "confirmed_at",
              "status", "provisional", "confluence_score", "flags", "reaction_metrics", "distance_atr")   # what the chart draws / shows
SCHEMA = """
CREATE TABLE IF NOT EXISTS zone_maps (map_id TEXT PRIMARY KEY, instrument TEXT, as_of TEXT, created_at REAL, payload TEXT);
CREATE TABLE IF NOT EXISTS zone_events (id INTEGER PRIMARY KEY AUTOINCREMENT, instrument TEXT, zone_id TEXT, status TEXT, at TEXT,
  map_id TEXT, detail TEXT, UNIQUE(instrument, zone_id, status));
CREATE INDEX IF NOT EXISTS ix_zone_maps_inst ON zone_maps(instrument, as_of);
"""


def _default_dir() -> Path:
    from ..paths import data_dir
    return data_dir() / "zones"


class ZoneService:
    def __init__(self, cfg_store, bridge, *, bus=None, log=None, data_dir: Path | None = None, clock=time.time):
        self.cfg_store, self.bridge, self.bus, self.log, self.clock = cfg_store, bridge, bus, log, clock
        d = Path(data_dir or _default_dir())
        d.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(d / "zones.sqlite"), check_same_thread=False, isolation_level=None, timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.map: dict | None = None
        self.last_bar: str | None = None
        self.state = {"version": VERSION, "runs": 0, "last_error": None, "last_ms": None, "mode": "ANALYTICAL_ONLY"}
        self.poll_s = 5.0

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="zones", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self.poll_s):
            try:
                if not self.cfg_store.get().zones.enabled:
                    continue
                rows = self.bridge.bars("M5", include_forming=False)
                t = rows[-1].get("open_utc") if rows else None
                if t and t != self.last_bar:
                    self.last_bar = t
                    self.refresh()
            except Exception as exc:  # noqa: BLE001 - analytical loop never stops the bot
                self.state["last_error"] = f"{type(exc).__name__}: {exc}"[:300]

    # ------------------------------------------------------------------ inputs
    def _instrument(self) -> tuple[str, str, float]:
        cfg = self.cfg_store.get()
        info = getattr(self.bridge, "symbol_info", None) or {}
        tick = float(info.get("trade_tick_size") or info.get("point") or 0.01)
        return cfg.assets.active, cfg.mt5.symbol, tick

    def _bars(self, symbol: str) -> dict:
        cfg = self.cfg_store.get().zones
        out = {}
        for tf, n in (("M5", cfg.profile_history_bars), ("M15", max(400, cfg.profile_history_bars // 3))):
            try:
                out[tf] = self.bridge.symbol_bars(symbol, tf, n)
            except Exception:  # noqa: BLE001 - deep read unavailable -> the bridge buffer (shorter history, reported in data.bars)
                out[tf] = self.bridge.bars(tf, include_forming=False)
        for tf in ("H1", "D1"):
            out[tf] = self.bridge.bars(tf, include_forming=False)
        return out

    # ------------------------------------------------------------------ compute
    def refresh(self, as_of: float | None = None) -> dict:
        t0 = time.perf_counter()
        inst, symbol, tick = self._instrument()
        as_of = as_of if as_of is not None else self.clock()
        bars = self._bars(symbol)
        t1 = time.perf_counter()
        zm = ZE.compute_map(instrument=inst, symbol=symbol, tick=tick, bars=bars, cfg=self.cfg_store.get().zones, as_of=as_of)
        t2 = time.perf_counter()
        with self._lock:
            self.map = zm
        self._persist(zm)
        self.state.update(runs=self.state["runs"] + 1, last_ms=round((time.perf_counter() - t0) * 1000, 1), last_error=None,
                          last_read_ms=round((t1 - t0) * 1000, 1), last_compute_ms=round((t2 - t1) * 1000, 1),
                          last_map_id=zm["map_id"], as_of=zm["as_of"], data_state=zm["data"]["state"])
        if self.bus is not None:
            try:
                self.bus.publish("zones", {"map_id": zm["map_id"], "as_of": zm["as_of"], "summary": zm["summary"], "data": zm["data"]})
            except Exception:  # noqa: BLE001
                pass
        return zm

    def at(self, as_of: float) -> dict:
        """Historical map: bars cut at as_of (no information from after as_of)."""
        inst, symbol, tick = self._instrument()
        return ZE.compute_map(instrument=inst, symbol=symbol, tick=tick, bars=self._bars(symbol), cfg=self.cfg_store.get().zones, as_of=as_of)

    def _persist(self, zm: dict) -> None:
        with self._lock, self.db:                                        # one transaction (autocommit would commit every event row)
            self.db.execute("BEGIN")
            self.db.execute("INSERT OR IGNORE INTO zone_maps(map_id, instrument, as_of, created_at, payload) VALUES (?,?,?,?,?)",
                            (zm["map_id"], zm["instrument"], zm["as_of"], time.time(), json.dumps(zm, default=float)))
            self.db.execute("DELETE FROM zone_maps WHERE instrument=? AND map_id NOT IN (SELECT map_id FROM zone_maps WHERE instrument=? "
                            "ORDER BY as_of DESC LIMIT 300)", (zm["instrument"], zm["instrument"]))
            for z in zm["zones"] + zm["expired"]:
                zid = z["zone_id"]
                self.db.execute("INSERT OR IGNORE INTO zone_events(instrument, zone_id, status, at, map_id, detail) VALUES (?,?,?,?,?,?)",
                                (zm["instrument"], zid, z["status"], zm["as_of"], zm["map_id"],
                                 json.dumps({k: z.get(k) for k in ("zone_type", "lower_price", "upper_price", "lower", "upper", "confluence_score")},
                                            default=float)))

    # ------------------------------------------------------------------ outputs
    def current(self) -> dict | None:
        with self._lock:
            return self.map

    def current_or_refresh(self) -> dict | None:
        """The live map, computed on demand when none exists yet; None (reason in status.last_error) when the inputs are unavailable."""
        zm = self.current()
        if zm is not None:
            return zm
        try:
            return self.refresh()
        except Exception as exc:  # noqa: BLE001 - e.g. terminal not connected: the API answers NO_MAP, never a 500
            self.state["last_error"] = f"{type(exc).__name__}: {exc}"[:300]
            return None

    def status(self) -> dict:
        zm = self.current()
        return {**self.state, "instrument": zm and zm["instrument"], "summary": zm and zm["summary"], "data": zm and zm["data"],
                "volume_source": zm and zm.get("volume_source"), "versions": ZE.VERSIONS,
                "note": "strefy są informacją analityczną; wynik 0-100 nie jest prawdopodobieństwem"}

    def events(self, limit: int = 100) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self.db.execute("SELECT * FROM zone_events ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()]

    def context_for(self, *, direction: str, entry: float, stop: float | None, cost_price: float = 0.0) -> dict | None:
        zm = self.current()
        if zm is None:
            return None
        return ZF.context_for(zm, direction=direction, entry=entry, stop=stop, cost_price=cost_price, cfg=self.cfg_store.get().zones)

    @staticmethod
    def chart_view(zm: dict | None, tf: str | None = None) -> dict:
        """Backend values for the chart (the panel draws, it never recomputes zones). Zones carry only the fields the chart draws;
        evidence and scoring details stay in the full map (`/api/v1/zones/map?full=true`)."""
        if not zm:
            return {"status": "NO_MAP"}
        zones = zm["zones"] if tf in (None, "ALL") else [z for z in zm["zones"] if tf in z["timeframes"] or "D1" in z["timeframes"]]
        zones = [{k: z.get(k) for k in CHART_KEYS} for z in zones]
        dev = (zm.get("profiles") or {}).get("developing")
        last = next((p for p in reversed((zm.get("profiles") or {}).get("completed") or []) if p.get("state") == "COMPLETED"), None)

        def lv(p):
            return p and {k: p.get(k) for k in ("profile_id", "session", "local_date", "state", "poc", "vah", "val", "hvn", "lvn", "start", "end",
                                                 "volume_source", "method", "relative_volume", "coverage")}
        return {"status": "OK", "map_id": zm["map_id"], "as_of": zm["as_of"], "data": zm["data"], "volume_source": zm.get("volume_source"),
                "zones": zones, "profile_developing": lv(dev), "profile_last_completed": lv(last),
                "summary": zm.get("summary"), "generated_at": iso(time.time())}
