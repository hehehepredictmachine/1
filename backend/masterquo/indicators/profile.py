"""Session profile features (PMW-IND-PROFILE-1) read from the DSVIE profiles of the zone map (zones/dsvie.py computes POC / VAH /
VAL / HVN / LVN / POC migration / relative volume; nothing is recomputed here). The map is built from bars known at its as_of, so the
features of a historical point use the profile known at that point (ZoneService.at(as_of) in replay).

  dist_poc_atr / dist_vah_atr / dist_val_atr  (price - level) / ATR for the developing and the last completed profile;
  va_position   (price - VAL) / (VAH - VAL): 0 = VAL, 1 = VAH, <0 below, >1 above;
  poc_migration_bins, relative_volume (cumulative, same elapsed time), interval_relative_volume (single bar, same slot);
  shape  P (POC in the upper third of the range) / b (lower third) / D (middle) - a descriptive label;
  state  DEVELOPING / COMPLETED / STALE / INVALID.
"""
from __future__ import annotations

from . import contract as C

VERSION = "PMW-IND-PROFILE-1"
UNITS = {"dist_poc_atr": "atr", "dist_vah_atr": "atr", "dist_val_atr": "atr", "va_position": "ratio", "relative_volume": "ratio",
         "interval_relative_volume": "ratio", "poc_migration_bins": "bins"}


def shape(p: dict) -> str | None:
    hi, lo, poc = p.get("high"), p.get("low"), p.get("poc")
    if hi is None or lo is None or poc is None or hi <= lo:
        return None
    x = (poc - lo) / (hi - lo)
    return "P" if x >= 2 / 3 else "b" if x <= 1 / 3 else "D"


def features(p: dict | None, price: float | None, atr_v: float | None, prefix: str) -> dict:
    out = {}
    ok = p is not None and price is not None and "poc" in (p or {})
    for k in ("poc", "vah", "val"):
        out[f"{prefix}dist_{k}_atr"] = (price - p[k]) / atr_v if ok and atr_v else None
    width = (p["vah"] - p["val"]) if ok else None
    out[f"{prefix}va_position"] = (price - p["val"]) / width if ok and width and width > 0 else None
    out[f"{prefix}state"] = p.get("state") if p else None
    out[f"{prefix}shape"] = shape(p) if ok else None
    return out


def compute(zmap: dict | None, price: float | None, atr_v: float | None, *, instrument: str, broker_symbol: str | None = None,
            cfg: dict | None = None) -> dict:
    base = dict(instrument=instrument, broker_symbol=broker_symbol, source="DSVIE", timeframe=(zmap or {}).get("profile_tf") or "M5", cfg=cfg,
                units=UNITS)
    if not zmap or not zmap.get("profiles"):
        return C.result("SESSION_PROFILE", VERSION, status="NO_DATA", reason="NO_ZONE_MAP", **base)
    pr = zmap["profiles"]
    dev = pr.get("developing")
    last = next((p for p in reversed(pr.get("completed") or []) if p.get("state") == "COMPLETED"), None)
    vals = {**features(dev, price, atr_v, "dev_"), **features(last, price, atr_v, "prev_"),
            "relative_volume": (dev or {}).get("relative_volume"), "interval_relative_volume": (dev or {}).get("interval_relative_volume"),
            "relative_volume_sessions": (dev or {}).get("relative_volume_baseline_sessions"),
            "poc_migration_bins": (dev or {}).get("poc_migration_bins"), "session": (dev or {}).get("session")}
    vs = (zmap.get("volume_source") or {}).get("source")
    extra = {"developing_profile_id": (dev or {}).get("profile_id"), "previous_profile_id": (last or {}).get("profile_id"),
             "map_id": zmap.get("map_id"), "map_as_of": zmap.get("as_of"), "session_calendar": (dev or last or {}).get("tz")}
    state = (zmap.get("data") or {}).get("state")
    if zmap.get("restored") or state == "STALE":
        return C.result("SESSION_PROFILE", VERSION, values=vals, status="STALE", reason="ZONE_MAP_STALE_OR_RESTORED", volume_source=vs,
                        data_time=zmap.get("as_of"), extra=extra, **base)
    if dev is None and last is None:
        return C.result("SESSION_PROFILE", VERSION, values=vals, status="WARMUP", reason="NO_PROFILE", volume_source=vs, extra=extra, **base)
    return C.result("SESSION_PROFILE", VERSION, values=vals, volume_source=vs, sample_count=(dev or last or {}).get("bars") or 0,
                    data_time=zmap.get("as_of"), available_at=zmap.get("as_of"), extra=extra, **base)
