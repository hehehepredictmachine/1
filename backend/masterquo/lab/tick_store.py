"""Tick archive + Newtonian replay (PMW-UPD-08 R19). Real quote ticks only: exported through the existing MT5 worker/bridge in bounded
chunks (NPZ + JSON manifest with hashes, ranges and the time transformation) - never reconstructed from OHLC. A chunk that returned the
maximum count is marked TRUNCATED (the range is not complete). Historical ticks have availability_basis HISTORICAL_SOURCE_TIME_ESTIMATE
(not OBSERVED_LIVE). Replay builds an immutable kinematic feature archive at every M1 close (point-in-time, with masks / ages) and the
forecast scoreboard split by time; it is NOT supervised training by itself."""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import quotes as Q

FEATURES = ["bid16_zv", "bid16_za", "ask16_zv", "ask16_za", "bid256_zv", "bid256_za", "ask256_zv", "ask256_za", "bid256_neff_ratio",
            "ask256_neff_ratio", "bid_age_s", "ask_age_s", "spread_level_ticks", "spread_slope_ticks_s", "spread_efficiency",
            "phase_expansion", "phase_retracement", "phase_consolidation", "phase_stressed", "quote_mask"]
PHASES = ("EXPANSION", "RETRACEMENT", "CONSOLIDATION", "STRESSED")


def root(inst: str) -> Path:
    import mq_instruments
    d = mq_instruments.data_dir() / "ticks" / inst
    d.mkdir(parents=True, exist_ok=True)
    return d


def _index(inst: str) -> list[dict]:
    p = root(inst) / "index.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def save_chunk(inst: str, ticks: list[dict], source: str, clock_transform: str, truncated: bool) -> dict | None:
    if not ticks:
        return None
    arr = {"t_ms": np.array([int(k["t_ms"]) for k in ticks], np.int64), "time_msc": np.array([int(k.get("time_msc", k["t_ms"])) for k in ticks], np.int64),
           "bid": np.array([k["bid"] for k in ticks], float), "ask": np.array([k["ask"] for k in ticks], float),
           "flags": np.array([int(k.get("flags", 0)) for k in ticks], np.int32), "ord": np.arange(len(ticks), dtype=np.int64)}
    a, b = int(arr["t_ms"][0]), int(arr["t_ms"][-1])
    f = root(inst) / f"ticks_{a}_{b}.npz"
    np.savez_compressed(f, **arr)
    ent = {"file": f.name, "from_ms": a, "to_ms": b, "count": len(ticks), "sha256": hashlib.sha256(f.read_bytes()).hexdigest(), "source": source,
           "clock_transform": clock_transform, "truncated": truncated, "availability_basis": "HISTORICAL_SOURCE_TIME_ESTIMATE",
           "saved_at": datetime.now(timezone.utc).isoformat()}
    idx = [e for e in _index(inst) if e["file"] != f.name] + [ent]
    (root(inst) / "index.json").write_text(json.dumps(sorted(idx, key=lambda e: e["from_ms"]), indent=1), encoding="utf-8")
    return ent


def export_via_bridge(bridge, symbol: str, inst: str, days: float, chunk_hours: float = 6.0, max_count: int = 500_000, progress=None, cancel=None) -> dict:
    """Bounded chunks through the existing bridge (worker queue). Progress per chunk; no direct terminal connection."""
    now = time.time()
    start = now - days * 86400
    out, t = [], start
    while t < now:
        if cancel and cancel():
            break
        t1 = min(now, t + chunk_hours * 3600)
        r = bridge.ticks_range(symbol, t, t1, max_count)
        if r.get("status") not in ("ok", "missing_data"):
            out.append({"from": t, "to": t1, "status": r.get("status"), "reason": r.get("reason")})
            if r.get("reason") == "SERVER_OFFSET_UNKNOWN":
                break
        else:
            ent = save_chunk(inst, r["ticks"], r.get("source", "MT5"), r.get("clock_transform", ""), len(r["ticks"]) >= max_count)
            out.append({"from": t, "to": t1, "status": "TRUNCATED" if ent and ent["truncated"] else ("OK" if ent else "EMPTY"), "count": len(r["ticks"])})
        if progress:
            progress((t1 - start) / max(1.0, now - start))
        t = t1
    return {"chunks": out, "complete": all(c["status"] in ("OK", "EMPTY") for c in out)}


def load(inst: str, from_ms: int | None = None, to_ms: int | None = None) -> list[dict]:
    out = []
    for e in _index(inst):
        if (from_ms is not None and e["to_ms"] < from_ms) or (to_ms is not None and e["from_ms"] > to_ms):
            continue
        f = root(inst) / e["file"]
        if hashlib.sha256(f.read_bytes()).hexdigest() != e["sha256"]:
            raise ValueError(f"TICK_CHUNK_HASH_MISMATCH: {e['file']}")
        with np.load(f, allow_pickle=False) as z:
            for i in range(len(z["t_ms"])):
                out.append({"t_ms": int(z["t_ms"][i]), "bid": float(z["bid"][i]), "ask": float(z["ask"][i]), "ord": int(z["ord"][i])})
    out.sort(key=lambda k: (k["t_ms"], k["ord"]))
    return out


def feature_row(snap: dict, tick: float) -> list:
    s = snap["sides"]

    def g(side, N, k):
        f = s[side][N]
        return f.get(k) if f.get("status") in ("OK", "PRELIMINARY") else None
    sp = snap["spread"]
    vals = [g("BID", 16, "z_v"), g("BID", 16, "z_a"), g("ASK", 16, "z_v"), g("ASK", 16, "z_a"), g("BID", 256, "z_v"), g("BID", 256, "z_a"),
            g("ASK", 256, "z_v"), g("ASK", 256, "z_a"),
            (s["BID"][256].get("n_eff") or 0) / 256.0, (s["ASK"][256].get("n_eff") or 0) / 256.0, s["BID"][256].get("side_age_s"), s["ASK"][256].get("side_age_s"),
            None if sp.get("level") is None else sp["level"] / tick, None if sp.get("slope_per_s") is None else sp["slope_per_s"] / tick, sp.get("efficiency")]
    vals += [float(snap["phase"] == p) for p in PHASES]
    ok = all(v is not None for v in vals)
    return [0.0 if v is None else float(v) for v in vals] + [1.0 if ok else 0.0]


def replay(inst: str, tick: float, point: float, cfg: dict | None = None, progress=None) -> dict:
    """Process the archive in time order; snapshot + emission + scoring at every M1 close of tick time."""
    ticks = load(inst)
    if not ticks:
        return {"status": "BLOCKED_NO_TICK_HISTORY"}
    eng = Q.QuoteEngine(inst, tick, point, cfg)
    rows_t, rows_f = [], []
    nxt = (ticks[0]["t_ms"] // 60000 + 1) * 60000
    buf = []
    t_start = time.time()
    for k in ticks:
        while k["t_ms"] >= nxt:
            eng.ingest(buf)
            buf = []
            snap = eng.snapshot(nxt)
            eng.emit(snap, nxt)
            eng.score(nxt)
            rows_t.append(nxt / 1000.0)
            rows_f.append(feature_row(snap, tick))
            nxt += 60000
        buf.append(k)
    eng.ingest(buf)
    F = np.array(rows_f, float).reshape(len(rows_f), len(FEATURES))
    t = np.array(rows_t, float)
    rid = f"QRP-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    d = root(inst) / "replays" / rid
    d.mkdir(parents=True)
    np.savez(d / "quote_features.npz", t=t, F=F)
    cut = t[0] + 0.8 * (t[-1] - t[0]) if len(t) else 0
    dev = [m for m in eng.matured if (m["issued_s"] + (eng.origin_ms or 0) / 1000.0) < cut]
    hold = [m for m in eng.matured if (m["issued_s"] + (eng.origin_ms or 0) / 1000.0) >= cut]

    def board(ms):
        e2 = Q.QuoteEngine(inst, tick, point, cfg)
        e2.matured = ms
        return e2.scoreboard()
    man = {"replay_id": rid, "profile": Q.VERSION, "instrument": inst, "features": FEATURES, "rows": int(len(t)), "ticks": len(ticks),
           "clock": eng.clock, "flags": sorted(eng.flags), "scoreboard_dev": board(dev), "scoreboard_holdout_reported_once": board(hold),
           "seconds": round(time.time() - t_start, 1), "sha256": hashlib.sha256((d / "quote_features.npz").read_bytes()).hexdigest(),
           "note": "deterministyczny fit kinematyczny + scoreboard; to nie jest trening nadzorowany"}
    (d / "manifest.json").write_text(json.dumps(man, indent=1, default=str), encoding="utf-8")
    return dict(man, status="OK", dir=str(d))


def latest_replay(inst: str) -> Path | None:
    d = root(inst) / "replays"
    if not d.exists():
        return None
    xs = sorted(p for p in d.iterdir() if (p / "manifest.json").exists())
    return xs[-1] if xs else None
