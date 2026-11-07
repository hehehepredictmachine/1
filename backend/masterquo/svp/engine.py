"""Interactive Session Volume Profile (PMW-SVP-1) - the SAME histogram / value area / node functions as DSVIE (zones/dsvie.py), so a
profile drawn by the user, the algorithmic zones, the training features and the AI read one engine.

Modes: SESSION (named session of a session profile or a custom window with an IANA zone; windows crossing midnight are supported),
RANGE (two times picked on the chart / edited exactly), VISIBLE (the visible chart range, recomputed with a rate limit), LIVE (the
developing current session), FROZEN (a stored snapshot - never recomputed).

Sources / method (always reported): EXCHANGE_VOLUME (real_volume), TICK_VOLUME (quote updates = activity proxy) - both allocated from
OHLC bars with UNIFORM_RANGE allocation (each bar's weight spread uniformly over the bins its [low, high] covers): an ESTIMATE of where
activity happened, NOT a trade footprint. DOM sizes are never mixed into a profile.
Grid: bin_size = bin_ticks x tick (always a whole number of ticks); bins are anchored at absolute multiples of bin_size (price 0), so a
developing profile keeps stable bin boundaries as it grows. A grid change = new grid_version; stored snapshots never change.
Value Area (deterministic, documented tie rules): start at the POC (max bin; tie -> LOWER price), extend one bin at a time to the side
with the larger neighbour (tie -> LOWER side) until >= value_area_pct of the total weight. HVN = local maxima of the smoothed histogram
>= hvn_min_share_of_poc x max (POC excluded); LVN = local minima <= lvn_max_share_of_peaks x the smaller of the side peaks.
Weight conservation: sum(histogram) = sum(bar weights) up to floating tolerance (checked and reported).
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone

from ..zones import dsvie as DS
from ..zones.series import Series

VERSION = "PMW-SVP-1"
MODES = ("SESSION", "RANGE", "VISIBLE", "LIVE", "FROZEN")


def _ts(x) -> float:
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return float(x)
    return datetime.fromisoformat(str(x).replace("Z", "+00:00")).timestamp()


def _iso(t: float | None) -> str | None:
    return None if t is None else datetime.fromtimestamp(float(t), timezone.utc).isoformat().replace("+00:00", "Z")


def custom_window(tz: str, start_hm: str, end_hm: str, local_day: str | date) -> tuple[float, float]:
    """UTC [start, end) of a user session (IANA zone, DST via zoneinfo); end <= start = crosses midnight."""
    from ..analytics import session_engine as SE
    d = date.fromisoformat(local_day) if isinstance(local_day, str) else local_day
    a, b = SE.local_window(("CUSTOM", tz, start_hm, end_hm), d)
    return a.timestamp(), b.timestamp()


def session_window(profile_id: str, session: str, local_day: str | date) -> tuple[float, float]:
    from ..analytics import session_engine as SE
    d = date.fromisoformat(local_day) if isinstance(local_day, str) else local_day
    s = next(x for x in SE.PROFILES[profile_id]["sessions"] if x[0] == session)
    a, b = SE.local_window(s, d)
    return a.timestamp(), b.timestamp()


def current_session(profile_id: str, as_of: float) -> dict | None:
    from ..analytics import session_engine as SE
    ws = [w for w in SE.windows(profile_id, as_of, 1, 0) if w["start"].timestamp() <= as_of < w["end"].timestamp()]
    if not ws:
        return None
    w = max(ws, key=lambda x: x["start"])
    return {"session": w["session"], "local_date": w["local_date"], "start": w["start"].timestamp(), "end": w["end"].timestamp(), "tz": w["tz"]}


class _Cfg:
    def __init__(self, smoothing=3, hvn=0.6, lvn=0.35):
        self.node_smoothing_bins, self.hvn_min_share_of_poc, self.lvn_max_share_of_peaks = smoothing, hvn, lvn


def compute(bars: list[dict], tf: str, t0, t1, *, as_of: float, tick: float, bin_ticks: int, value_area_pct: float = 0.70,
            instrument: str, symbol: str | None = None, mode: str = "RANGE", grid_version: int = 1, smoothing: int = 3,
            hvn_share: float = 0.6, lvn_share: float = 0.35, label: str | None = None) -> dict:
    """Profile of closed bars with open >= t0 and close <= min(t1, as_of). Nothing after as_of is used."""
    if mode not in MODES:
        raise ValueError("SVP_MODE_INVALID")
    if not (tick > 0) or int(bin_ticks) < 1:
        raise ValueError("SVP_GRID_INVALID")
    a, b = _ts(t0), _ts(t1)
    if b <= a:
        raise ValueError("SVP_RANGE_EMPTY")
    bin_size = round(int(bin_ticks) * tick, 10)
    s = Series.from_bars(bars, tf, as_of)
    upto = min(b, as_of)
    idx = [i for i in range(len(s)) if s.t[i] >= a - 1e-6 and s.close_time(i) <= upto + 1e-6]
    vs = DS.volume_source(s) if len(s) else {"source": "NONE"}
    src = vs["source"]
    expected = max(0, int((upto - a) // s.tf_s)) if len(s) or True else 0
    pid_src = f"{instrument}|{symbol}|{tf}|{_iso(a)}|{_iso(b)}|{bin_size}|{value_area_pct}|{grid_version}"
    out = {"contract": VERSION, "mode": mode, "label": label, "instrument": instrument, "symbol": symbol, "tf": tf, "start": _iso(a), "end": _iso(b),
           "as_of": _iso(as_of), "state": "DEVELOPING" if as_of < b else "COMPLETED", "tick": tick, "bin_ticks": int(bin_ticks), "bin_size": bin_size,
           "grid_version": grid_version, "value_area_pct": value_area_pct, "volume_source": src, "method": DS.METHOD,
           "method_note": "rozkład wagi świecy równomiernie w jej zakresie [low, high] – estymata aktywności, nie footprint transakcji",
           "bars": len(idx), "expected_bars": expected, "coverage": round(len(idx) / expected, 4) if expected else 0.0,
           "geometry_id": "SVP-" + hashlib.sha256(pid_src.encode()).hexdigest()[:12]}
    if not idx:
        out.update(status="NO_DATA", reason="brak zamkniętych świec w zakresie (lub historia niedostępna)")
        return out
    if src == "NONE":
        out.update(status="NO_DATA", reason="brak użytecznego wolumenu")
        return out
    hist = DS.histogram(s, idx, bin_size, src)
    total_in = sum(DS._vol(s, i, src) for i in idx)
    total = sum(hist.values())
    if not hist or total <= 0:
        out.update(status="NO_DATA", reason="zerowe wagi w zakresie")
        return out
    poc, val_b, vah_b = DS.value_area(hist, value_area_pct)
    hvn, lvn = DS.nodes(hist, poc, _Cfg(smoothing, hvn_share, lvn_share))
    va_w = sum(v for k, v in hist.items() if val_b <= k <= vah_b)
    hi, lo = max(s.h[i] for i in idx), min(s.l[i] for i in idx)
    out.update(status="READY" if out["coverage"] >= 0.9 or out["state"] == "DEVELOPING" else "PARTIAL",
               reason=None if out["coverage"] >= 0.9 else f"pokrycie {out['coverage']:.0%} – historia częściowa",
               total_weight=round(total, 6), input_weight=round(total_in, 6), weight_conserved=abs(total - total_in) <= 1e-6 * max(1.0, total_in),
               poc=round((poc + 0.5) * bin_size, 10), vah=round((vah_b + 1) * bin_size, 10), val=round(val_b * bin_size, 10),
               va_share=round(va_w / total, 4), hvn=[round((k + 0.5) * bin_size, 10) for k in hvn], lvn=[round((k + 0.5) * bin_size, 10) for k in lvn],
               high=hi, low=lo, known_at=_iso(s.close_time(idx[-1])),
               histogram=[{"price": round((k + 0.5) * bin_size, 10), "lo": round(k * bin_size, 10), "hi": round((k + 1) * bin_size, 10),
                           "weight": round(v, 6)} for k, v in sorted(hist.items())])
    out["snapshot_id"] = "SVS-" + hashlib.sha256(json.dumps([out["geometry_id"], out["known_at"], out["total_weight"], out["poc"]],
                                                           default=str).encode()).hexdigest()[:14]
    return out


def visible_range_ok(last_call: float | None, now: float, min_interval_s: float = 1.0) -> bool:
    """Rate limit for the VISIBLE mode (pan / zoom fires many requests)."""
    return last_call is None or now - last_call >= min_interval_s
