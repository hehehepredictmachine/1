"""Volatility walls for strategies (MQ-WALLS-1.0.0) - a versioned data contract with an explicit SOURCE.

Source types (never mixed up, never renamed):
  IV_SOURCED   real implied volatility from a configured external adapter (instrument + tenor). No adapter is configured in
               this package (no licensed feed) -> status NOT_CONFIGURED. Nothing is invented in its place.
  IV_IMPORT    implied volatility imported from CSV/JSON (iv_import.py) - usable only from its `available_at` on.
  IV_MANUAL    implied volatility typed by the user with timestamp, source, unit, tenor and validity (config walls.manual).
  HV_PROXY     historical volatility of CLOSED broker D1 bars (close-to-close, `hv_window` days). It is a PROXY: not implied
               volatility, never labelled as IV.
  UNAVAILABLE / STALE  no current source.
IV of another instrument (GVZ = 30-day IV of GLD options; CME gold options = one futures contract) is flagged
IV_FROM_OTHER_INSTRUMENT_PROXY: its strikes are never copied as CFD prices - only the volatility NUMBER is used, around the
broker's own anchor price.  IV does not describe dealer positioning; no "gamma / dealer walls" are derived here.

Model (one explicit variant, chosen before any study):
  anchor  = OPEN of the current broker session (forming D1 bar), horizon = 1 session.
  T       = 1/252 for a volatility annualised on TRADING days (HV_PROXY, or IV declared TRADING_252),
            1/365 for IV on CALENDAR days (ACT_365 - typical for option IV / volatility indices). Never mixed silently.
  upper_k = anchor x exp(+k x sigma_annual x sqrt(T)),  lower_k = anchor x exp(-k x sigma_annual x sqrt(T)),  k in `ks`;
  zone    = level x exp(+-band x sigma x sqrt(T)).
This is a log-return band CONVENTION, not a forecast of the day's high/low, not a probability of a trade.
Snapshots are FROZEN per session: the first snapshot of a session is version 1; a new IV observation creates version 2
for FUTURE setups - setups keep the snapshot id they were created with (historical triggers/SL never move).
The intraday variant (time remaining x current anchor) is a separate hypothesis and is not implemented as trading input.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import timedelta

from ..timeutil import iso, parse_iso

VERSION = "MQ-WALLS-1.0.0"
SOURCE_PRIORITY = ("IV_SOURCED", "IV_IMPORT", "IV_MANUAL", "HV_PROXY")


def hv_annual(d1_closed: list[dict], window: int) -> float | None:
    closes = [float(b["c"]) for b in d1_closed[-(window + 1):]]
    if len(closes) < window + 1:
        return None
    rets = [math.log(b / a) for a, b in zip(closes, closes[1:]) if a > 0 and b > 0]
    if len(rets) < 2:
        return None
    mu = sum(rets) / len(rets)
    sd = math.sqrt(sum((r - mu) ** 2 for r in rets) / (len(rets) - 1))
    return sd * math.sqrt(252.0)


def _sid(*parts) -> str:
    return "WS-" + hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:14]


def choose_source(*, cfg, symbol: str, d1_closed: list[dict], iv_obs: dict | None, manual: dict | None, now) -> dict:
    """Pick the volatility input by the configured mode. Returns {source_type, sigma_annual, basis, ...} or a status."""
    mode = getattr(cfg, "source", "AUTO")
    notes = []
    cand = []
    if mode in ("AUTO", "IV_SOURCED"):
        notes.append("IV_SOURCED_NOT_CONFIGURED")
    if mode in ("AUTO", "IV_IMPORT") and iv_obs:
        cand.append(dict(iv_obs, source_type="IV_IMPORT"))
    if mode in ("AUTO", "IV_MANUAL") and manual:
        cand.append(dict(manual, source_type="IV_MANUAL"))
    for c in cand:
        avail = parse_iso(c["available_at"]) if c.get("available_at") else None
        until = parse_iso(c["valid_until"]) if c.get("valid_until") else None
        if avail is None or avail > now:
            notes.append(f"{c['source_type']}_NOT_YET_AVAILABLE")
            continue
        if until is not None and until < now:
            notes.append(f"{c['source_type']}_STALE")
            continue
        flags = []
        if c.get("underlier") and c["underlier"] != symbol:
            flags.append("IV_FROM_OTHER_INSTRUMENT_PROXY")
        return {"source_type": c["source_type"], "sigma_annual": float(c["sigma_annual"]), "basis": c.get("day_count_basis") or "ACT_365",
                "source": c.get("source"), "underlier": c.get("underlier"), "observed_at": c.get("observed_at"), "available_at": c.get("available_at"),
                "valid_until": c.get("valid_until"), "tenor_days": c.get("tenor_days"), "obs_id": c.get("obs_id"), "flags": flags, "notes": notes}
    if mode in ("AUTO", "HV_PROXY"):
        hv = hv_annual(d1_closed, int(getattr(cfg, "hv_window", 20)))
        if hv is None:
            return {"source_type": "UNAVAILABLE", "reason": "HV_INSUFFICIENT_D1_HISTORY", "notes": notes}
        return {"source_type": "HV_PROXY", "sigma_annual": hv, "basis": "TRADING_252", "source": f"MT5 D1 close-to-close {getattr(cfg, 'hv_window', 20)}d",
                "underlier": symbol, "available_at": d1_closed[-1].get("available_at") if d1_closed else None, "flags": ["PROXY_NOT_IMPLIED_VOLATILITY"],
                "notes": notes}
    return {"source_type": "UNAVAILABLE" if not any("STALE" in n for n in notes) else "STALE", "reason": "NO_VALID_SOURCE_FOR_MODE_" + mode, "notes": notes}


def build(*, symbol: str, d1_bars: list[dict], cfg, iv_obs: dict | None, manual: dict | None, now, digits: int = 2) -> dict:
    """Snapshot (not yet versioned/frozen - see WallsStore) for the current session."""
    bars = [b for b in d1_bars if b.get("open_utc")]
    closed = [b for b in bars if b.get("closed")]
    forming = bars[-1] if bars and not bars[-1].get("closed") else None
    if not closed:
        return {"version": VERSION, "status": "BRAK_DANYCH", "reason": "NO_D1_HISTORY", "walls": []}
    if forming is None:
        return {"version": VERSION, "status": "MARKET_CLOSED", "reason": "NO_OPEN_SESSION", "walls": []}
    src = choose_source(cfg=cfg, symbol=symbol, d1_closed=closed, iv_obs=iv_obs, manual=manual, now=now)
    if src["source_type"] in ("UNAVAILABLE", "STALE"):
        return {"version": VERSION, "status": src["source_type"], "reason": src.get("reason"), "notes": src.get("notes"), "walls": []}
    anchor, anchor_t = float(forming["o"]), forming["open_utc"]
    T = 1 / 252.0 if src["basis"] == "TRADING_252" else 1 / 365.0
    move = src["sigma_annual"] * math.sqrt(T)
    band = float(getattr(cfg, "band_sigma", 0.15)) * move
    valid_until = iso(parse_iso(anchor_t) + timedelta(days=1))
    avail = max([x for x in (anchor_t, src.get("available_at")) if x])
    r = (lambda x: round(x, digits))
    walls = []
    for k in sorted(set(float(x) for x in getattr(cfg, "ks", (1.0, 2.0)))):
        for side, sgn in (("UPPER", 1), ("LOWER", -1)):
            lvl = anchor * math.exp(sgn * k * move)
            walls.append({"wall_id": _sid(symbol, anchor_t, src["source_type"], round(src["sigma_annual"], 6), k, side), "side": side, "k": k,
                          "level": r(lvl), "low": r(lvl * math.exp(-band)), "high": r(lvl * math.exp(band))})
    return {"version": VERSION, "model_version": VERSION, "status": "OK", "symbol": symbol, "source_type": src["source_type"],
            "source": src.get("source"), "underlier": src.get("underlier"), "flags": src.get("flags", []), "notes": src.get("notes", []),
            "sigma_annual": round(src["sigma_annual"], 6), "day_count_basis": src["basis"], "T_years": T, "horizon": "SESSION_1D",
            "anchor_time": anchor_t, "anchor_price": r(anchor), "available_at": avail, "valid_until": valid_until,
            "observed_at": src.get("observed_at"), "obs_id": src.get("obs_id"), "band_sigma": float(getattr(cfg, "band_sigma", 0.15)),
            "walls": walls, "interpretation": "pasma log-zwrotu (konwencja), nie prognoza high/low dnia i nie prawdopodobieństwo transakcji"}


class WallsStore:
    """Freezes snapshots per (symbol, session anchor): same input -> same snapshot id; a different source / sigma ->
    next version (future setups only). Persisted in table walls_snapshots when a DB is given (replay may run without)."""

    def __init__(self, db=None):
        self.db = db
        self._mem: dict[tuple, list[dict]] = {}

    def freeze(self, snap: dict) -> dict:
        if snap.get("status") != "OK":
            return snap
        key = (snap["symbol"], snap["anchor_time"])
        fp = (snap["source_type"], snap["sigma_annual"], snap.get("obs_id"), tuple(sorted({w["k"] for w in snap["walls"]})), snap["band_sigma"])
        hist = self._mem.get(key)
        if hist is None and self.db is not None:
            rows = self.db.query("SELECT json FROM walls_snapshots WHERE symbol=? AND anchor_time=? ORDER BY snapshot_version", key)
            hist = [json.loads(x["json"]) for x in rows]
            self._mem[key] = hist
        hist = self._mem.setdefault(key, hist or [])
        for h in hist:
            if h.get("_fp") == list(fp):
                return h
        ver = len(hist) + 1
        out = dict(snap, snapshot_version=ver, _fp=list(fp))
        out["snapshot_id"] = _sid(snap["symbol"], snap["anchor_time"], ver, *fp)
        for w in out["walls"]:
            w["snapshot_id"] = out["snapshot_id"]
        hist.append(out)
        if self.db is not None:
            self.db.execute("INSERT OR IGNORE INTO walls_snapshots(snapshot_id, symbol, anchor_time, snapshot_version, source_type, created_at, json) VALUES (?,?,?,?,?,?,?)",
                            (out["snapshot_id"], snap["symbol"], snap["anchor_time"], ver, snap["source_type"], iso(parse_iso(snap["available_at"])),
                             json.dumps(out)))
        return out

    def latest(self, symbol: str, anchor_time: str) -> dict | None:
        h = self._mem.get((symbol, anchor_time)) or []
        return h[-1] if h else None


def mirror(snap: dict | None, k2: float) -> dict | None:
    """Walls in price-mirrored coordinates (p' = k2 - p): UPPER <-> LOWER (for the LONG-rules-on-mirror SHORT scan)."""
    if not snap or snap.get("status") != "OK":
        return snap
    out = dict(snap, anchor_price=round(k2 - snap["anchor_price"], 8), mirrored=True)
    out["walls"] = [dict(w, side="LOWER" if w["side"] == "UPPER" else "UPPER", level=k2 - w["level"], low=k2 - w["high"], high=k2 - w["low"])
                    for w in snap["walls"]]
    return out
