"""Zone map compiler (PMW-ZONES-MAP-1): bars as known at `as_of` -> HLZE -> DSVIE -> UZICE -> one versioned zone map.
The same function serves the live ZoneService, the historical "as of" view of the chart and the ML feature pipeline, so no consumer
recreates zones with different rules."""
from __future__ import annotations

import hashlib

from ..analysis import levels as LV
from ..analytics import session_engine as SE
from . import dsvie as DV
from . import hlze as HZ
from . import uzice as UZ
from .series import Series, iso

VERSION = "PMW-ZONES-MAP-1"
VERSIONS = {"map": VERSION, "hlze": HZ.VERSION, "dsvie": DV.VERSION, "uzice": UZ.VERSION, "schema": UZ.SCHEMA}


def compute_map(*, instrument: str, symbol: str, tick: float, bars: dict[str, list[dict]], cfg, as_of: float,
                profile_id: str | None = None) -> dict:
    """bars: {"M5": [...], "M15": [...], "D1": [...], "H1": [...]} (bridge / symbol_bars dicts). Only closed bars with close <= as_of are used."""
    tick = tick or 0.01
    pid = profile_id or cfg.session_profile.get(instrument) or "LAB_XAU_REFERENCE_V1"
    cut = {tf: [b for b in (bars.get(tf) or []) if b.get("open_utc") and b.get("closed") is not False] for tf in bars}
    series = {tf: Series.from_bars(cut.get(tf) or [], tf, as_of) for tf in ("M5", "M15")}
    d1 = Series.from_bars(cut.get("D1") or [], "D1", as_of)
    m5 = series["M5"]
    m5_bars = [b for b in cut.get("M5") or [] if HZ_close(b, 300) <= as_of]
    data_state, reasons = "OK", []
    if len(m5) < 60:
        data_state, reasons = "INSUFFICIENT_HISTORY", [f"M5: {len(m5)} świec"]
    elif as_of - m5.close_time(len(m5) - 1) > 3 * m5.tf_s:
        data_state, reasons = "STALE", [f"ostatnia zamknięta M5 {iso(m5.close_time(len(m5) - 1))}"]
    out = {"map_id": None, "schema_version": UZ.SCHEMA, "instrument": instrument, "symbol": symbol, "as_of": iso(as_of), "versions": VERSIONS,
           "data": {"state": data_state, "reasons": reasons, "bars": {tf: len(s) for tf, s in series.items()} | {"D1": len(d1)}},
           "zones": [], "m5": [], "m15": [], "levels": [], "profiles": {"developing": None, "completed": []}, "demand_supply": [],
           "context": {}, "expired": [], "summary": {}, "mode": "ANALYTICAL_ONLY"}
    if data_state == "INSUFFICIENT_HISTORY":
        out["map_id"] = _map_id(out)
        return out
    boxes = []
    try:
        boxes = SE.build(m5_bars, 300, pid, instrument, as_of, days=2)
    except Exception as exc:  # noqa: BLE001 - session boxes missing = no session levels, other zones stay
        reasons.append(f"sesje: {type(exc).__name__}")
    hl = HZ.build(series, cfg, tick, m5_bars=m5_bars, d1=d1 if len(d1) else None, boxes=boxes, as_of=as_of)
    refs = [z for z in hl["zones"] if z["zone_type"].startswith(("PREVIOUS_", "INTRADAY_", "CONSOLIDATION_")) or z.get("range_state")]
    prof_series = series.get(cfg.profile_tf) if cfg.profile_tf in series else Series.from_bars(cut.get(cfg.profile_tf) or [], cfg.profile_tf, as_of)
    dv = DV.build(prof_series, profile_id=pid, instrument=instrument, cfg=cfg, as_of=as_of, tick=tick, piv_by_tf=hl["pivots"],
                  series_by_tf=series, refs=refs)
    a5 = HZ.atr_series(m5)
    atr = HZ._atr_at(a5, len(m5) - 1) or (tick * 100)
    price = m5.c[-1]
    htf = []
    h1 = [b for b in cut.get("H1") or [] if HZ_close(b, 3600) <= as_of]   # cut BEFORE the length check (no look-ahead in the gate)
    if len(h1) >= 40:
        try:
            htf = LV.zones_for_tf(LV._Bars(h1), "H1", point=tick).get("zones") or []
        except Exception:  # noqa: BLE001
            htf = []
    profiles = dv["profiles"]
    dev = next((p for p in reversed(profiles) if p["state"] in ("DEVELOPING", "STALE")), None)
    if dev and dev["state"] == "STALE" and data_state == "OK":
        data_state = "DEGRADED"
    unified, expired = UZ.unify(hl["zones"], dv["demand_supply"], profiles, cfg=cfg, atr=atr, tick=tick, price=price, htf_sr=htf,
                                vol_source=dv["volume_source"]["source"], data_state=data_state, as_of=as_of)
    completed = [p for p in profiles if p["state"] in ("COMPLETED", "INVALID")]
    for p in completed[:-3]:
        p.pop("histogram", None)                                         # keep histograms of the recent profiles only
        p.pop("poc_path", None)
    out.update(zones=unified, m5=[z for z in hl["zones"] if z.get("tf") == "M5" and z["status"] in UZ.LIVE],
               m15=[z for z in hl["zones"] if z.get("tf") == "M15" and z["status"] in UZ.LIVE],
               levels=[z for z in refs if z["status"] in UZ.LIVE], demand_supply=[z for z in dv["demand_supply"] if z["status"] in UZ.LIVE],
               profiles={"developing": dev, "completed": completed[-12:], "profile_set": pid}, context=dv["context"],
               volume_source=dv["volume_source"], expired=sorted(expired, key=lambda z: z.get("confirmed_at") or "")[-30:],
               htf_sr=htf, price=price, atr_m5=atr, session_boxes=[{k: b.get(k) for k in ("box_id", "session", "state", "final_high", "final_low",
                                                                                            "developing_high", "developing_low", "start_utc", "end_utc")}
                                                                    for b in boxes if b.get("state") != "SCHEDULED"])
    out["data"]["state"] = data_state
    sup = UZ.nearest(out, "BELOW", price)
    res = UZ.nearest(out, "ABOVE", price)
    out["summary"] = {"price": price, "nearest_support": sup and {k: sup[k] for k in ("zone_id", "zone_type", "lower_price", "upper_price", "confluence_score", "status")},
                      "nearest_resistance": res and {k: res[k] for k in ("zone_id", "zone_type", "lower_price", "upper_price", "confluence_score", "status")},
                      "zones": len(unified), "provisional": sum(1 for z in unified if z["provisional"])}
    out["map_id"] = _map_id(out)
    return out


def HZ_close(b: dict, tf_s: int) -> float:
    from .series import ts
    return ts(b["open_utc"]) + tf_s


def _map_id(m: dict) -> str:
    key = repr((m["instrument"], m["as_of"], VERSIONS, [(z["zone_id"], z["status"], z.get("confluence_score")) for z in m.get("zones") or []]))
    return "ZM-" + hashlib.sha256(key.encode()).hexdigest()[:16]
