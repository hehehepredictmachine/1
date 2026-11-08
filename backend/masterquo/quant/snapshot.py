"""Point-in-time data snapshot + quality control (PMW-QUANT-SNAP-1).

Source: the EXISTING MarketBridge buffers (MT5Worker underneath). Only CLOSED bars are taken (`include_forming=False`); every bar keeps
the bridge's own `available_at` (observed close / next open - the bridge already converts server time to UTC with the measured offset;
no second shift is applied here), `source` native|resampled and, for resampled bars (M3 from M1, H8 from H1), the `complete` flag.

Times kept apart: bar open (t), bar close (t + TF), first availability (available_at), snapshot as_of (newest availability), computation
time (computed_at). `asof(snap, t)` returns per TF only the bars whose availability is <= t - a forming M15/H1 bar never leaks into an
earlier decision, and an H1 bar is never used before it closed.

QC per TF: order, duplicates, revisions, missing bars (gaps longer than one TF are reported, never filled), OHLC conditions, finite
values, incomplete resampled bars (excluded), spread present. Quote: age and symbol. Tick volume is labelled TICK_VOLUME (feed activity),
never traded volume. DXY / news / order book: own source and state; missing source = state, never 0. data_kind REAL|SYNTHETIC comes
from the bridge (the SYNTHETIC simulator can never be labelled REAL).
"""
from __future__ import annotations

import hashlib
import math
import time
from datetime import datetime, timezone

from ..timeutil import TF_SECONDS

VERSION = "PMW-QUANT-SNAP-1"
DEFAULT_TFS = ("M1", "M3", "M5", "M15", "M30", "H1", "H4", "D1")
SESSION_CALENDAR = "MT5_SYMBOL_SESSIONS (luki = przerwy sesji, bez wypełniania)"


def _ts(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()
    except ValueError:
        return None


def normalise(rows: list[dict], tf: str) -> list[dict]:
    """Bridge bar JSON -> compact bar {t, close_t, available_at, o, h, l, c, tick_volume, spread_points, source, complete, revision}."""
    sec = TF_SECONDS.get(tf, 60)
    out = []
    for r in rows or []:
        if not r.get("closed", True):
            continue
        t = _ts(r.get("open_utc") if r.get("open_utc") is not None else r.get("t"))
        if t is None:
            continue
        av = _ts(r.get("available_at"))
        out.append({"t": t, "close_t": t + sec, "available_at": av if av is not None else t + sec, "o": r.get("o"), "h": r.get("h"), "l": r.get("l"),
                    "c": r.get("c"), "tick_volume": r.get("tv"), "spread_points": r.get("spread"), "source": str(r.get("source") or "native").upper(),
                    "complete": r.get("complete"), "revision": r.get("revision"), "available_basis": "BRIDGE" if av is not None else "CLOSE_TIME"})
    return out


def qc(bars: list[dict], tf: str, *, max_gap_report: int = 20) -> dict:
    sec = TF_SECONDS.get(tf, 60)
    issues, gaps, bad = [], [], 0
    dup = sum(1 for a, b in zip(bars, bars[1:]) if b["t"] == a["t"])
    unordered = sum(1 for a, b in zip(bars, bars[1:]) if b["t"] < a["t"])
    for a, b in zip(bars, bars[1:]):
        d = b["t"] - a["t"]
        if d > sec * 1.5:
            gaps.append({"after": a["t"], "missing_bars": int(round(d / sec)) - 1})
    for b in bars:
        vals = [b[k] for k in ("o", "h", "l", "c")]
        if any(v is None or isinstance(v, bool) or not math.isfinite(float(v)) for v in vals):
            bad += 1
            continue
        o, h, l_, c = (float(v) for v in vals)
        if not (h >= max(o, c) - 1e-9 and l_ <= min(o, c) + 1e-9 and h >= l_):
            bad += 1
    incomplete = sum(1 for b in bars if b["source"] == "RESAMPLED" and b["complete"] is False)
    revised = sum(1 for b in bars if (b.get("revision") or 0) > 0)
    no_spread = sum(1 for b in bars if b.get("spread_points") is None)
    if dup:
        issues.append(f"DUPLICATES:{dup}")
    if unordered:
        issues.append(f"UNORDERED:{unordered}")
    if bad:
        issues.append(f"OHLC_INVALID:{bad}")
    if incomplete:
        issues.append(f"RESAMPLED_INCOMPLETE:{incomplete}")
    status = "BLOCK" if (dup or unordered or bad) else ("DEGRADED" if incomplete or (gaps and len(gaps) > 50) else "OK")
    return {"tf": tf, "n": len(bars), "status": status, "issues": issues, "gaps": gaps[-max_gap_report:], "gap_count": len(gaps),
            "revised_bars": revised, "bars_without_spread": no_spread,
            "source": sorted({b["source"] for b in bars}) or None, "volume_kind": "TICK_VOLUME (aktywność feedu, nie wolumen obrotu)",
            "last_close_t": bars[-1]["close_t"] if bars else None, "last_available_at": bars[-1]["available_at"] if bars else None}


def revision_id(bars_by_tf: dict) -> str:
    h = hashlib.sha256()
    for tf in sorted(bars_by_tf):
        for b in bars_by_tf[tf][-50:]:
            h.update(f"{tf}|{b['t']}|{b['o']}|{b['h']}|{b['l']}|{b['c']}|{b.get('revision')}".encode())
    return h.hexdigest()[:16]


def build(bridge, *, instrument: str, tfs=DEFAULT_TFS, limit: int = 600, now: float | None = None, quote_max_age_s: float = 10.0) -> dict:
    """Snapshot of the bridge buffers at `now`. Never raises for missing data - each part carries its state."""
    now = time.time() if now is None else now
    bars, quality = {}, {}
    avail_tfs = set(getattr(bridge, "tfs", {}) or {})
    for tf in tfs:
        if avail_tfs and tf not in avail_tfs:
            quality[tf] = {"tf": tf, "n": 0, "status": "NOT_LOADED", "issues": ["TF_NOT_IN_BRIDGE"]}
            continue
        try:
            rows = normalise(bridge.bars(tf, limit, include_forming=False), tf)
        except Exception as exc:  # noqa: BLE001
            quality[tf] = {"tf": tf, "n": 0, "status": "ERROR", "issues": [f"{type(exc).__name__}"]}
            continue
        rows = [b for b in rows if b["available_at"] <= now + 1e-6]                    # nothing that was not available at `now`
        q = qc(rows, tf)
        quality[tf] = q
        bars[tf] = [b for b in rows if not (b["source"] == "RESAMPLED" and b["complete"] is False)]
    try:
        quote = bridge.quote_status()
    except Exception:  # noqa: BLE001
        quote = None
    qstate = "MISSING"
    if quote:
        age = quote.get("age_seconds")
        qstate = "OK" if age is not None and age <= quote_max_age_s else "STALE"
    info = getattr(bridge, "symbol_info", None) or {}
    cfg = getattr(bridge, "cfg", None)
    symbol = getattr(cfg, "symbol", None)
    synthetic = bool(getattr(bridge, "synthetic", getattr(bridge, "_synthetic", False)))
    as_of = max((b[-1]["available_at"] for b in bars.values() if b), default=None)
    rev = revision_id(bars)
    status = "BLOCK" if any(q.get("status") == "BLOCK" for q in quality.values()) else (
        "DEGRADED" if any(q.get("status") in ("DEGRADED", "ERROR") for q in quality.values()) or qstate != "OK" else "OK")
    snap = {"version": VERSION, "instrument": instrument, "symbol": symbol, "server": (getattr(bridge, "account_key", None) or "").split(":")[0] or None,
            "spec": {k: info.get(k) for k in ("point", "trade_tick_size", "trade_tick_value", "trade_contract_size", "volume_min", "volume_step",
                                              "volume_max", "digits")},
            "as_of_utc": as_of, "computed_at": now, "source": "MT5_BRIDGE" if not synthetic else "SYNTHETIC_SIMULATOR",
            "data_kind": "SYNTHETIC" if synthetic else "REAL", "bars": bars, "quality": quality, "quote": quote, "quote_state": qstate,
            "extra_sources": _extra_sources(bridge), "revision_id": rev, "session_calendar": SESSION_CALENDAR,
            "aggregation": {"M3": "natywna seria MT5, inaczej pełne trójki M1 (niepełne wykluczone)", "H8": "natywna albo 8×H1"},
            "status": status}
    snap["snapshot_id"] = hashlib.sha256(f"{instrument}|{symbol}|{as_of}|{rev}".encode()).hexdigest()[:16]
    return snap


def _extra_sources(bridge) -> dict:
    out = {}
    try:
        d = bridge.bars("DXY_H1", 5, include_forming=False)
        out["DXY"] = {"state": "OK" if d else "MISSING", "last_available_at": _ts(d[-1].get("available_at")) if d else None}
    except Exception:  # noqa: BLE001
        out["DXY"] = {"state": "MISSING", "reason": "brak serii DXY w bridge"}
    out["ORDER_BOOK"] = {"state": "SEE_INDICATORS", "reason": "głębokość rynku tylko z PMW-IND-1 (market depth); brak = stan, nie zero"}
    out["NEWS"] = {"state": "SEE_NEWS_SERVICE", "reason": "czas pierwszego odbioru z usługi news"}
    return out


def asof(snap: dict, t: float) -> dict:
    """Bars available at time t per TF (availability <= t). Used for replay / training rows (no look-ahead)."""
    return {tf: [b for b in bars if b["available_at"] <= t + 1e-9] for tf, bars in (snap.get("bars") or {}).items()}


def last_closed(snap: dict, tf: str, t: float | None = None) -> dict | None:
    bs = (snap.get("bars") or {}).get(tf) or []
    if t is not None:
        bs = [b for b in bs if b["available_at"] <= t + 1e-9]
    return bs[-1] if bs else None


def summary(snap: dict) -> dict:
    return {k: snap.get(k) for k in ("snapshot_id", "instrument", "symbol", "as_of_utc", "computed_at", "data_kind", "source", "status", "quote_state",
                                     "revision_id")} | {"quality": {tf: {k: q.get(k) for k in ("n", "status", "issues", "gap_count", "last_close_t", "source")}
                                                                    for tf, q in (snap.get("quality") or {}).items()},
                                                        "extra_sources": snap.get("extra_sources")}
