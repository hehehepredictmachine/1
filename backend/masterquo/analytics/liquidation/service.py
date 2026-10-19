"""LiquidityService (PMW-UPD-06): session boxes of the active instrument (shared engine) + liquidation heatmap ingest/archive.

One background poll per configured source (provider / variant / symbol / range) - not per chart TF; HTTP never runs in the MT5
worker or in a chart endpoint. Errors back off with jitter (Retry-After honoured). Every distinct payload becomes ONE immutable
snapshot with first_received_at set at ingest; an identical repeat only refreshes last_seen_at. File inbox (data/liquidity/inbox)
uses the same validator; imported_at is the receipt time, a declared original time is kept with trust DECLARED_UNVERIFIED.
as_of(D) returns only a snapshot whose first_received_at <= D (never "latest cut on the time axis").
"""
from __future__ import annotations

import json
import random
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ... import paths
from ...timeutil import iso, utcnow
from .. import session_engine as se
from . import contract, provider

STALE_FACTOR = 3


def _now_iso() -> str:
    return iso(utcnow())


class LiquidityService:
    def __init__(self, cfg_store, db, bus, log, secrets=None, bridge=None, fetcher=None):
        self.cfg_store, self.db, self.bus, self.log, self.secrets, self.bridge = cfg_store, db, bus, log, secrets, bridge
        self.fetcher = fetcher or provider.fetch
        self._stop = threading.Event()
        self._th = None
        self._next = {}                    # source_key -> earliest next poll (monotonic)
        self._fail = {}                    # source_key -> consecutive failures

    @property
    def cfg(self):
        return self.cfg_store.get().liquidity

    @staticmethod
    def inbox() -> Path:
        d = paths.data_dir() / "liquidity" / "inbox"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @staticmethod
    def source_key(asset: str, src) -> str:
        return f"COINGLASS:{src.variant}:{src.source_symbol}:{src.exchange or '-'}:{src.range}->{asset}"

    # -------------------------------------------------- lifecycle
    def start(self) -> None:
        self._th = threading.Thread(target=self._loop, name="liquidity", daemon=True)
        self._th.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
                self.scan_inbox()
            except Exception as exc:  # noqa: BLE001 - the base bot never depends on this module
                if self.log:
                    self.log.error("LIQ", "LOOP", f"{type(exc).__name__}: {exc}"[:300])
            self._stop.wait(5.0)

    def poll_once(self, now_mono: float | None = None) -> list[str]:
        """Poll every enabled source whose time has come. Returns the keys polled."""
        done = []
        t = time.monotonic() if now_mono is None else now_mono
        for asset, src in self.cfg.sources.items():
            if not src.enabled or not src.source_symbol:
                continue
            key = self.source_key(asset, src)
            if t < self._next.get(key, 0):
                continue
            done.append(key)
            key_val = self.secrets.get("COINGLASS_API_KEY") if self.secrets else None
            try:
                r = self.fetcher(src.variant, src.source_symbol, src.range, src.exchange, key_val)
                res = self.ingest(asset, src, r["data"], origin="API", request=r.get("request"))
                self._fail[key] = 0
                self._next[key] = t + self.cfg.poll_seconds
                self._status(key, res["status"], res.get("detail"))
            except provider.ProviderError as e:
                n = self._fail.get(key, 0) + 1
                self._fail[key] = n
                wait = e.retry_after or min(3600.0, self.cfg.poll_seconds * (2 ** min(n, 6)))
                self._next[key] = t + wait * (1 + 0.2 * random.random())
                self._status(key, e.code, e.detail, retry_in=wait)
        return done

    def _status(self, key: str, status: str, detail: str | None, retry_in: float | None = None) -> None:
        self.db.execute("INSERT INTO liq_source_status(source_key, at, status, detail, retry_at) VALUES (?,?,?,?,?) "
                        "ON CONFLICT(source_key) DO UPDATE SET at=excluded.at, status=excluded.status, detail=excluded.detail, retry_at=excluded.retry_at",
                        (key, _now_iso(), status, (detail or "")[:300], iso(datetime.fromtimestamp(time.time() + retry_in, timezone.utc)) if retry_in else None))
        if self.bus:
            self.bus.publish("liquidity", {"source_key": key, "status": status})

    # -------------------------------------------------- ingest (API and file share the validator)
    def ingest(self, asset: str, src, data: dict, *, origin: str, request: dict | None = None, received_at: str | None = None,
               declared_received_at: str | None = None) -> dict:
        key = self.source_key(asset, src)
        now = received_at or _now_iso()
        h = contract.payload_hash(data)
        prev = self.db.one("SELECT snapshot_id FROM liq_heatmap_snapshots WHERE source_key=? AND payload_hash=?", (key, h))
        if prev:                                                       # the same estimate again: a newer sighting, not a new amount
            self.db.execute("UPDATE liq_heatmap_snapshots SET last_seen_at=? WHERE snapshot_id=?", (now, prev["snapshot_id"]))
            return {"status": "UNCHANGED", "snapshot_id": prev["snapshot_id"]}
        try:
            grid = contract.parse_model1(data)
            zs = contract.zones(grid)
            status, detail = "OK", None
        except contract.HeatmapError as e:
            grid, zs, status, detail = None, None, e.code, str(e)
        sid = "LIQ-" + uuid.uuid4().hex[:16]
        trust = "BACKEND_RECEIPT" if origin == "API" else ("DECLARED_UNVERIFIED" if declared_received_at else "IMPORT_TIME_ONLY")
        self.db.execute("""INSERT INTO liq_heatmap_snapshots(snapshot_id, source_key, target_asset, provider, variant, source_symbol, exchange, range, data_kind,
                           payload_hash, parser_version, first_received_at, last_seen_at, source_generated_at, origin, declared_received_at, availability_trust,
                           status, grid, zones, request) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (sid, key, asset, "COINGLASS", src.variant, src.source_symbol, src.exchange, src.range, "ESTIMATED_LIQUIDATION_LEVELS", h,
                         contract.PARSER_VERSION, now, now, None, origin, declared_received_at, trust, status,
                         json.dumps(grid) if grid else None, json.dumps(zs) if zs else None, json.dumps(request or {})))
        if self.bus:
            self.bus.publish("liquidity", {"source_key": key, "status": status, "snapshot_id": sid})
        return {"status": status, "snapshot_id": sid, "detail": detail}

    def scan_inbox(self) -> list[dict]:
        """Files {schema 'pmw-liq-export-1', target_asset, variant, source_symbol, exchange, range, declared_received_at?, data}."""
        out = []
        for f in sorted(self.inbox().glob("*.json")):
            try:
                if f.stat().st_size > contract.MAX_BYTES:
                    raise contract.HeatmapError("TOO_LARGE")
                doc = json.loads(f.read_text(encoding="utf-8"))
                if doc.get("schema") != "pmw-liq-export-1":
                    raise contract.HeatmapError("UNSUPPORTED_SCHEMA", "schema != pmw-liq-export-1")
                from ...config import HeatmapSource
                src = HeatmapSource(enabled=False, variant=doc.get("variant", "AGGREGATED"), source_symbol=doc["source_symbol"], exchange=doc.get("exchange"),
                                    range=doc.get("range", "24h"))
                out.append(self.ingest(doc["target_asset"], src, doc["data"], origin="FILE", declared_received_at=doc.get("declared_received_at")))
                f.rename(f.with_suffix(".done"))
            except (ValueError, KeyError, OSError, contract.HeatmapError) as exc:
                out.append({"status": "REJECTED", "file": f.name, "detail": str(exc)[:200]})
                try:
                    f.rename(f.with_suffix(".rejected"))
                except OSError:
                    pass
        return out

    # -------------------------------------------------- read side
    def as_of(self, asset: str, D: str | None = None) -> dict | None:
        """Latest OK snapshot of the asset's configured source received at or before D (point in time)."""
        src = self.cfg.sources.get(asset)
        if src is None or not src.source_symbol:
            return None
        key = self.source_key(asset, src)
        q = "SELECT * FROM liq_heatmap_snapshots WHERE source_key=? AND status='OK'" + (" AND first_received_at<=?" if D else "") + \
            " ORDER BY first_received_at DESC LIMIT 1"
        row = self.db.one(q, (key, D) if D else (key,))
        if not row:
            return None
        r = dict(row)
        r["grid"], r["zones"] = json.loads(r["grid"]), json.loads(r["zones"])
        age = (utcnow() - datetime.fromisoformat(r["last_seen_at"].replace("Z", "+00:00"))).total_seconds()
        r["age_s"] = round(age)
        r["stale"] = age > STALE_FACTOR * self.cfg.poll_seconds
        return r

    def heatmap_public(self, asset: str, D: str | None = None, max_cells: int = 20000) -> dict:
        src = self.cfg.sources.get(asset)
        st = None
        if src is not None and src.source_symbol:
            st = self.db.one("SELECT * FROM liq_source_status WHERE source_key=?", (self.source_key(asset, src),))
        base = {"asset": asset, "data_kind": "ESTIMATED_LIQUIDATION_LEVELS", "provider": "COINGLASS",
                "source": None if src is None else {k: getattr(src, k) for k in ("enabled", "variant", "source_symbol", "exchange", "range", "contract_type", "mapping")},
                "key_status": (self.secrets.source("COINGLASS_API_KEY") if self.secrets else "MISSING"), "source_status": st}
        if src is None or not src.source_symbol:
            return dict(base, status="NO_SOURCE_FOR_INSTRUMENT", reason=f"Brak danych heatmapy dla {asset} (brak skonfigurowanego, zweryfikowanego źródła; XAUT ≠ XAUUSD-)")
        snap = self.as_of(asset, D)
        if snap is None:
            return dict(base, status=(st or {}).get("status") or ("DISABLED" if not src.enabled else "NO_SNAPSHOT"),
                        reason="brak zarchiwizowanej mapy" + (f" otrzymanej do {D}" if D else ""))
        g = snap["grid"]
        cells = g["cells"]
        lod = None
        if max_cells <= 0:
            cells, lod = [], "pominięte (kontekst bez siatki)"
        elif len(cells) > max_cells:                                     # visual LOD only - analytics use the full grid
            step = len(cells) // max_cells + 1
            cells, lod = cells[::step], f"co {step}. komórka (tylko wizualizacja)"
        return dict(base, status="STALE" if snap["stale"] else "OK", snapshot_id=snap["snapshot_id"], first_received_at=snap["first_received_at"],
                    last_seen_at=snap["last_seen_at"], age_s=snap["age_s"], availability_trust=snap["availability_trust"], origin=snap["origin"],
                    source_instrument={"symbol": snap["source_symbol"], "exchange": snap["exchange"], "variant": snap["variant"], "range": snap["range"]},
                    target_instrument=asset, mapping=src.mapping, mapping_status="MAPPING_UNVALIDATED" if src.mapping != "VALIDATED_BASIS" else "VALIDATED_BASIS",
                    axis="SOURCE_PRICE (osobny panel – brak zweryfikowanego mapowania na cenę brokera)" if src.mapping != "VALIDATED_BASIS" else "BROKER_PRICE",
                    grid={"prices": g["prices"], "price_edges": g["price_edges"], "times": g["times"], "time_axis_status": g["time_axis_status"], "cells": cells,
                          "lod": lod, "n_cells": len(g["cells"]), "intensity_unit": g["intensity_unit"], "missing_cell_semantics": g["missing_cell_semantics"]},
                    zones=snap["zones"])

    def sessions(self, bars: list[dict], tf_s: int, asset: str, as_of: str | float | None = None, profile: str | None = None, days: int = 2) -> dict:
        prof = profile or self.cfg.scalp_profile
        t = as_of if as_of is not None else time.time()
        return {"profile_id": prof, "profile_label": se.PROFILES[prof]["label"], "engine": se.VERSION, "boxes": se.build(bars, tf_s, prof, asset, t, days=days),
                "profiles": {k: v["label"] for k, v in se.PROFILES.items()}}
