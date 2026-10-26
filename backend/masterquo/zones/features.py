"""Zone features for one setup (PMW-ZONE-FEAT-1). Computed from a zone map (UZICE) for a given direction / entry / stop / cost.
Distances are in ATR (M5) or in R (R = |entry - stop|) and signed by the trade direction where stated. A feature whose data does not
exist is NaN - never a substituted value. Used by the evaluation ledger (every setup) and the legacy ML FeatureEngine (MQ-FEAT-1.1.0)."""
from __future__ import annotations

import math

from . import uzice as UZ

VERSION = "PMW-ZONE-FEAT-1"
NAN = float("nan")
SESSION_CODE = {"ASIA": 0.0, "LONDON": 1.0, "EUROPE": 1.0, "NEW_YORK": 2.0, "US": 2.0}
SRC_CODE = {"NONE": 0.0, "TICK_VOLUME": 1.0, "EXCHANGE_VOLUME": 2.0}
NAMES = ["zone_dist_m5_high_atr", "zone_dist_m5_low_atr", "zone_dist_m15_high_atr", "zone_dist_m15_low_atr", "zone_dist_poc_atr",
         "zone_dist_vah_atr", "zone_dist_val_atr", "zone_va_position", "zone_dist_demand_atr", "zone_dist_supply_atr", "zone_opp_dist_r",
         "zone_opp_room_after_costs_r", "zone_opp_score", "zone_opp_width_atr", "zone_opp_age_bars", "zone_opp_retests", "zone_own_dist_r",
         "zone_own_score", "zone_own_swept", "zone_session", "zone_relvol", "zone_poc_migration", "zone_hvn_near", "zone_lvn_near",
         "zone_data_ok", "zone_volume_source"]


def _nearest(zs: list[dict], price: float, above: bool) -> dict | None:
    if above:
        c = [z for z in zs if z["upper"] >= price]
        return min(c, key=lambda z: max(0.0, z["lower"] - price), default=None)
    c = [z for z in zs if z["lower"] <= price]
    return min(c, key=lambda z: max(0.0, price - z["upper"]), default=None)


def compute(zmap: dict, *, direction: str, entry: float, stop: float | None, cost_price: float = 0.0) -> dict:
    f = {k: NAN for k in NAMES}
    if not zmap or not zmap.get("zones") and not zmap.get("m5"):
        return f
    sgn = 1.0 if direction == "LONG" else -1.0
    atr = zmap.get("atr_m5") or NAN
    price = entry
    R = abs(entry - stop) if stop is not None else NAN

    def d_atr(x):
        return (x - price) / atr if x is not None and atr == atr and atr > 0 else NAN
    for tf in ("m5", "m15"):
        zs = [z for z in zmap.get(tf) or [] if z["status"] != "PROVISIONAL"]
        hi = _nearest([z for z in zs if UZ.polarity(z["zone_type"]) == "HIGH"], price, True)
        lo = _nearest([z for z in zs if UZ.polarity(z["zone_type"]) == "LOW"], price, False)
        f[f"zone_dist_{tf}_high_atr"] = d_atr(hi["lower"]) if hi else NAN
        f[f"zone_dist_{tf}_low_atr"] = -d_atr(lo["upper"]) if lo else NAN
    prof = (zmap.get("profiles") or {}).get("completed") or []
    prev = next((p for p in reversed(prof) if p.get("state") == "COMPLETED" and "poc" in p), None)
    if prev:
        f["zone_dist_poc_atr"] = sgn * d_atr(prev["poc"])
        f["zone_dist_vah_atr"] = sgn * d_atr(prev["vah"])
        f["zone_dist_val_atr"] = sgn * d_atr(prev["val"])
        pos = 1.0 if price > prev["vah"] else -1.0 if price < prev["val"] else 0.0
        f["zone_va_position"] = sgn * pos
        half = 0.5 * atr if atr == atr else 0.0
        f["zone_hvn_near"] = 1.0 if any(abs(x - price) <= half for x in prev.get("hvn") or []) else 0.0
        f["zone_lvn_near"] = 1.0 if any(abs(x - price) <= half for x in prev.get("lvn") or []) else 0.0
    ds = zmap.get("demand_supply") or []
    dem = _nearest([z for z in ds if z["zone_type"] == "DEMAND"], price, False)
    sup = _nearest([z for z in ds if z["zone_type"] == "SUPPLY"], price, True)
    f["zone_dist_demand_atr"] = -d_atr(dem["upper"]) if dem else NAN
    f["zone_dist_supply_atr"] = d_atr(sup["lower"]) if sup else NAN
    opp = UZ.nearest(zmap, "ABOVE" if sgn > 0 else "BELOW", price)
    own = UZ.nearest(zmap, "BELOW" if sgn > 0 else "ABOVE", price)
    if opp is not None:
        dist = max(0.0, (opp["lower_price"] - price) if sgn > 0 else (price - opp["upper_price"]))
        f["zone_opp_dist_r"] = dist / R if R == R and R > 0 else NAN
        f["zone_opp_room_after_costs_r"] = (dist - (cost_price or 0.0)) / R if R == R and R > 0 else NAN
        f["zone_opp_score"] = opp["confluence_score"]
        f["zone_opp_width_atr"] = opp.get("width_atr") if opp.get("width_atr") is not None else NAN
        f["zone_opp_age_bars"] = float((opp.get("reaction_metrics") or {}).get("age_bars") or 0)
        f["zone_opp_retests"] = float((opp.get("reaction_metrics") or {}).get("retests") or 0)
    if own is not None:
        dist = max(0.0, (price - own["upper_price"]) if sgn > 0 else (own["lower_price"] - price))
        f["zone_own_dist_r"] = dist / R if R == R and R > 0 else NAN
        f["zone_own_score"] = own["confluence_score"]
        f["zone_own_swept"] = 1.0 if (own.get("reaction_metrics") or {}).get("swept") else 0.0
    ctx = zmap.get("context") or {}
    f["zone_session"] = SESSION_CODE.get(ctx.get("current_session"), -1.0)
    f["zone_relvol"] = ctx.get("relative_volume") if ctx.get("relative_volume") is not None else NAN
    pm = ctx.get("poc_migration_bins")
    f["zone_poc_migration"] = sgn * pm if pm is not None else NAN
    f["zone_data_ok"] = 1.0 if (zmap.get("data") or {}).get("state") == "OK" else 0.0
    f["zone_volume_source"] = SRC_CODE.get((zmap.get("volume_source") or {}).get("source"), 0.0)
    return {k: (float(v) if v is not None and not (isinstance(v, float) and math.isinf(v)) else NAN) for k, v in f.items()}


def context_for(zmap: dict, *, direction: str, entry: float, stop: float | None, cost_price: float, cfg) -> dict:
    """Human-readable zone context for one setup (evaluation layer / panel). The final decision stays with the strategy logic,
    R:R, probability and execution - an opposing zone is evidence, not an unconditional rule."""
    sgn = 1.0 if direction == "LONG" else -1.0
    opp = UZ.nearest(zmap, "ABOVE" if sgn > 0 else "BELOW", entry)
    own = UZ.nearest(zmap, "BELOW" if sgn > 0 else "ABOVE", entry)
    f = compute(zmap, direction=direction, entry=entry, stop=stop, cost_price=cost_price)
    room = f["zone_opp_room_after_costs_r"]
    strong = opp is not None and opp["confluence_score"] >= cfg.strong_zone_score
    flags = []
    if strong and room == room and room < cfg.min_room_r:
        flags.append("ZONE_ROOM_INSUFFICIENT")
    if opp is not None and "CONFLICT" in opp.get("flags", []):
        flags.append("ZONE_CONFLICT_AHEAD")
    return {"version": VERSION, "map_id": zmap.get("map_id"), "map_as_of": zmap.get("as_of"), "data_state": (zmap.get("data") or {}).get("state"),
            "opposing_zone": opp and {k: opp[k] for k in ("zone_id", "zone_type", "lower_price", "upper_price", "confluence_score", "status", "flags")},
            "supporting_zone": own and {k: own[k] for k in ("zone_id", "zone_type", "lower_price", "upper_price", "confluence_score", "status")},
            "room_after_costs_r": None if room != room else round(room, 3), "flags": flags,
            "session_context": zmap.get("context"), "features": f}
