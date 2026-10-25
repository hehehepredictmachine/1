"""Data snapshots + quality checks + event sources (PMW-MM-DATA-1).

A training run never reads "the latest export": it reads an explicit dataset directory written by `training export`
(source_metadata.json + <PREFIX>_<TF>.csv + files_sha256). The snapshot id pins dataset_id + the hashes of the files actually read,
so a run is reproducible and two runs on different data can never share an id. Bars are closed broker-chart OHLC in UTC; a bar's
values are available at open + tf seconds.

Event sources for the event-driven / STE models (never fabricated):
* REAL_TICKS        - quote ticks from the tick archive (lab/tick_store, exported from the user's MT5 through the bridge);
* BAR_CLOSE_EVENTS  - explicitly named bar-derived adapter: ONE event per closed M1 bar at its close time (close as mid, spread from
                      the bar, tick_volume as an activity count). It does not contain intrabar micro-events and is labelled as such.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

TF_S = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400}
QUALITY_VERSION = "PMW-MM-DQ-1"


def _ts(s: str) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=timezone.utc).timestamp()


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class Bars:
    tf: str
    t: np.ndarray          # bar open, UTC seconds
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray          # noqa: E741
    c: np.ndarray
    tv: np.ndarray         # tick volume (activity count, NOT traded volume)
    spread: np.ndarray     # points (NaN when absent)

    def __len__(self) -> int:
        return len(self.t)

    @property
    def available_at(self) -> np.ndarray:
        return self.t + TF_S[self.tf]

    def slice(self, a: int, b: int) -> "Bars":
        return Bars(self.tf, *(x[a:b] for x in (self.t, self.o, self.h, self.l, self.c, self.tv, self.spread)))

    def rows(self) -> list[dict]:
        """Row dicts in the convention of the existing lab/analysis code (open_utc ISO, o/h/l/c, tv, closed=True)."""
        return [{"open_utc": datetime.fromtimestamp(float(t), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "o": float(o), "h": float(h),
                 "l": float(lo), "c": float(c), "tv": int(v), "closed": True}
                for t, o, h, lo, c, v in zip(self.t, self.o, self.h, self.l, self.c, self.tv)]


@dataclass
class Snapshot:
    snapshot_id: str
    dataset_dir: str
    instrument: str
    symbol: str
    data_kind: str                       # REAL_USER_DATA | SYNTHETIC_TEST
    point: float
    tick_size: float
    meta: dict
    bars: dict = field(default_factory=dict)
    quality: dict = field(default_factory=dict)
    files: dict = field(default_factory=dict)

    def lineage(self) -> dict:
        return {"snapshot_id": self.snapshot_id, "dataset_dir": self.dataset_dir, "dataset_id": self.meta.get("dataset_id"),
                "instrument": self.instrument, "symbol": self.symbol, "data_kind": self.data_kind, "source": self.meta.get("source"),
                "account_server": self.meta.get("account_server"), "requested_months": self.meta.get("requested_months"),
                "actual_range_utc": self.meta.get("range_utc"), "time_basis": self.meta.get("time_basis"),
                "price_basis": self.meta.get("price_basis"), "files_sha256": self.files,
                "rows": {tf: len(b) for tf, b in self.bars.items()}, "quality": self.quality, "quality_version": QUALITY_VERSION}


def quality(b: Bars) -> dict:
    """Integrity of one bar series. INVALID rows are reported, never repaired silently (the export already dropped broken geometry)."""
    n = len(b)
    if n == 0:
        return {"rows": 0, "status": "MISSING"}
    fin = np.isfinite(b.o) & np.isfinite(b.h) & np.isfinite(b.l) & np.isfinite(b.c)
    pos = (b.o > 0) & (b.h > 0) & (b.l > 0) & (b.c > 0)
    geo = (b.h >= np.maximum(b.o, b.c) - 1e-12) & (b.l <= np.minimum(b.o, b.c) + 1e-12)
    dt = np.diff(b.t)
    step = TF_S[b.tf]
    bad = int((~(fin & pos & geo)).sum())
    out = {"rows": n, "first_utc": float(b.t[0]), "last_utc": float(b.t[-1]), "non_finite": int((~fin).sum()), "non_positive": int((~pos).sum()),
           "bad_geometry": int((~geo).sum()), "duplicates": int((dt == 0).sum()), "out_of_order": int((dt < 0).sum()),
           "gaps_over_1bar": int((dt > step).sum()), "max_gap_bars": float(dt.max() / step) if len(dt) else 0.0,
           "spread_missing_share": float(np.isnan(b.spread).mean())}
    out["status"] = "INVALID" if (bad or out["duplicates"] or out["out_of_order"]) else "OK"
    return out


def load_bars(path: Path, tf: str) -> Bars:
    t, o, h, lo, c, tv, sp = [], [], [], [], [], [], []
    with open(path, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            t.append(_ts(r["time_open_utc"]))
            o.append(float(r["open"]))
            h.append(float(r["high"]))
            lo.append(float(r["low"]))
            c.append(float(r["close"]))
            tv.append(float(r.get("tick_volume") or 0))
            s = r.get("spread_points")
            sp.append(float(s) if s not in (None, "") else math.nan)
    return Bars(tf, *(np.asarray(x, dtype=float) for x in (t, o, h, lo, c, tv, sp)))


def open_snapshot(dataset_dir: str | Path, tfs: tuple[str, ...] = ("M1", "M5"), verify_hashes: bool = True) -> Snapshot:
    ds = Path(dataset_dir)
    meta = json.loads((ds / "source_metadata.json").read_text(encoding="utf-8"))
    prefix = meta.get("file_prefix") or meta.get("instrument") or "XAUUSD"
    declared = meta.get("files_sha256") or {}
    bars, files, q = {}, {}, {}
    for tf in tfs:
        p = ds / f"{prefix}_{tf}.csv"
        if not p.exists():
            q[tf] = {"rows": 0, "status": "MISSING"}
            continue
        hx = sha256_file(p)
        if verify_hashes and declared.get(p.name) and declared[p.name] != hx:
            raise ValueError(f"SNAPSHOT_HASH_MISMATCH:{p.name}")
        files[p.name] = hx
        bars[tf] = load_bars(p, tf)
        q[tf] = quality(bars[tf])
    spec = meta.get("spec") or {}
    if isinstance(spec, str):
        spec = {}
    tick = float(meta.get("tick_size") or spec.get("trade_tick_size") or 0.01)
    sid = "SNAP-" + hashlib.sha256(json.dumps({"dataset": meta.get("dataset_id"), "files": files}, sort_keys=True).encode()).hexdigest()[:16]
    return Snapshot(sid, str(ds), meta.get("instrument") or prefix, meta.get("symbol") or prefix, meta.get("data_kind") or "UNKNOWN",
                    float(spec.get("point") or tick), tick, meta, bars, q, files)


# ----------------------------------------------------------------------------------------------------- events
EVENT_SCHEMA = "PMW-MM-EVENT-1"


def events_from_bars(b: Bars, point: float) -> dict:
    """BAR_CLOSE_EVENTS: one event per closed bar at its close time. mid = close; bid/ask reconstructed around it only when the bar
    carries a spread (spread_points x point), otherwise spread is unavailable (NaN) - never a fabricated constant."""
    t = b.available_at.astype(float)
    sp = b.spread * point
    return {"source": "BAR_CLOSE_EVENTS", "schema": EVENT_SCHEMA, "t": t, "mid": b.c.astype(float), "bid": b.c - sp / 2, "ask": b.c + sp / 2,
            "spread": sp, "activity": b.tv.astype(float), "range": (b.h - b.l).astype(float), "received_at": t.copy(),
            "limits": "bar-derived adapter: no intrabar micro-events, no traded volume, no aggressor side"}


def events_from_ticks(ticks: list[dict]) -> dict:
    t = np.array([x["t"] for x in ticks], dtype=float)
    bid = np.array([x["bid"] for x in ticks], dtype=float)
    ask = np.array([x["ask"] for x in ticks], dtype=float)
    return {"source": "REAL_TICKS", "schema": EVENT_SCHEMA, "t": t, "mid": (bid + ask) / 2, "bid": bid, "ask": ask, "spread": ask - bid,
            "activity": np.ones_like(t), "range": np.full_like(t, np.nan), "received_at": t.copy(),
            "limits": "quote ticks (bid/ask changes); MT5 quote ticks carry no traded volume or aggressor side"}
