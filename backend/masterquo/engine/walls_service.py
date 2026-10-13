"""Walls provider for the live engine: builds the session snapshot from the broker's D1 bars and the configured source
(imported IV -> manual IV -> HV proxy, analysis/walls.py), freezes it per session (WallsStore, table walls_snapshots) and
hands it to strategies through MarketView.context. Read-only: never touches orders."""
from __future__ import annotations

from ..analysis import iv_import, walls
from ..timeutil import iso, utcnow


class WallsService:
    def __init__(self, cfg_store, db, bridge):
        self.cfg_store = cfg_store
        self.db = db
        self.bridge = bridge
        self.store = walls.WallsStore(db)
        self.last: dict | None = None
        self.last_error: str | None = None

    def _manual(self, cfg) -> dict | None:
        m = cfg.walls.manual
        if m is None:
            return None
        return {"sigma_annual": m.sigma_annual_pct / 100.0, "day_count_basis": m.day_count_basis, "underlier": m.underlier, "source": m.source,
                "observed_at": m.observed_at, "available_at": m.available_at, "valid_until": m.valid_until, "tenor_days": m.tenor_days,
                "obs_id": f"MANUAL:{m.observed_at}:{m.sigma_annual_pct}"}

    def snapshot(self, d1_bars: list[dict], now=None) -> dict:
        cfg = self.cfg_store.get()
        now = now or utcnow()
        try:
            obs = iv_import.latest_usable(self.db, iso(now), cfg.walls.import_underliers) if cfg.walls.source in ("AUTO", "IV_IMPORT") else None
            digits = int((self.bridge.symbol_info or {}).get("digits") or 2)
            snap = walls.build(symbol=cfg.mt5.symbol, d1_bars=d1_bars, cfg=cfg.walls, iv_obs=obs, manual=self._manual(cfg), now=now, digits=digits)
            snap = self.store.freeze(snap)
            if cfg.walls.source == "IV_SOURCED" or cfg.walls.external_adapter:
                snap = dict(snap, notes=list(snap.get("notes") or []) + ["IV_SOURCED_ADAPTER_NOT_CONFIGURED"])
            self.last = snap
            self.last_error = None
            return snap
        except Exception as exc:                      # walls never stop the engine: strategies see WALL_STALE / NO_WALLS
            self.last_error = f"{type(exc).__name__}: {exc}"[:200]
            self.last = {"version": walls.VERSION, "status": "UNAVAILABLE", "reason": "ERROR", "walls": []}
            return self.last

    def context(self, view, bars: dict) -> dict:
        return {"walls": self.snapshot(bars.get("D1") or [])}

    def status(self) -> dict:
        cfg = self.cfg_store.get()
        s = self.last or {}
        return {"source_mode": cfg.walls.source, "status": s.get("status"), "source_type": s.get("source_type"), "snapshot_id": s.get("snapshot_id"),
                "snapshot_version": s.get("snapshot_version"), "notes": s.get("notes"), "flags": s.get("flags"), "error": self.last_error,
                "iv_observations": (self.db.one("SELECT COUNT(*) AS n FROM iv_observations") or {}).get("n", 0),
                "external_adapter": "NOT_CONFIGURED" if not cfg.walls.external_adapter else cfg.walls.external_adapter}
