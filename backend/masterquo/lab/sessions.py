"""M15 Session Sweep Boxes + M20 Memory Sequence + multi-TF availability join (MQ-LAB-TIME-1.0.0).

Sessions are defined in the exchange's LOCAL time zone (zoneinfo -> DST handled), separately per asset; all stored times are
UTC. A session box's high/low is final (available) only after the session end; before that it is `developing`.
"""
from __future__ import annotations

from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo


from ..analytics.ta import TF_SEC
from .common import iso, ts

VERSION = "MQ-LAB-TIME-1.0.0"

# Working definitions (editable in config later); BTC trades 24/7 on many venues but the broker CFD may not - availability is
# checked from the bars, never assumed.
SESSIONS = {
    "XAUUSD": [("ASIA", "Asia/Tokyo", "09:00", "15:00"), ("LONDON", "Europe/London", "08:00", "16:30"),
               ("NEW_YORK", "America/New_York", "08:20", "13:30")],
    "BTC": [("ASIA", "Asia/Singapore", "08:00", "16:00"), ("EUROPE", "Europe/London", "08:00", "16:30"),
            ("US", "America/New_York", "09:30", "16:00")],
}


def _hm(s: str) -> dtime:
    h, m = s.split(":")
    return dtime(int(h), int(m))


PROFILE = {"XAUUSD": "LAB_XAU_REFERENCE_V1", "BTC": "LAB_BTC_REFERENCE_V1"}


def session_windows(asset: str, day_utc: datetime) -> list[dict]:
    """UTC windows of each session whose LOCAL date equals the given calendar day (DST-correct) - shared engine (PMW-UPD-06)."""
    from ..analytics import session_engine as se
    out = []
    for s_ in se.PROFILES[PROFILE[asset]]["sessions"]:
        z = ZoneInfo(s_[1])
        local_day = day_utc.astimezone(z).date() if day_utc.tzinfo else day_utc.date()
        a, b = se.local_window(s_, local_day)
        out.append({"session": s_[0], "tz": s_[1], "start": a, "end": b})
    return out


def session_boxes(bars: list[dict], tf: str, asset: str, days: int = 3) -> dict:
    """Boxes of the asset's lab profile for the last `days` days from the shared engine; legacy fields kept (state FINAL /
    DEVELOPING / INCOMPLETE, available_at only for FINAL, events [{t, event}]), engine fields added."""
    from ..analytics import session_engine as se
    if not bars:
        return {"boxes": []}
    sec = TF_SEC[tf]
    as_of = ts(bars[-1]["open_utc"]) + sec
    prof = PROFILE[asset]
    out = []
    for b in se.build(bars, sec, prof, asset, as_of, days=days):
        if b["state"] in ("SCHEDULED", "NO_DATA"):
            continue
        hi = b.get("final_high") if b["state"] == "FINAL" else b.get("developing_high") if b["state"] == "DEVELOPING" else b.get("observed_high")
        lo = b.get("final_low") if b["state"] == "FINAL" else b.get("developing_low") if b["state"] == "DEVELOPING" else b.get("observed_low")
        out.append({"id": f"SB-{asset}-{b['session']}-{b['local_date']}", "box_id": b["box_id"], "profile_id": prof, "session": b["session"], "tz": b["tz"],
                    "start_utc": iso(ts(b["start_utc"])), "end_utc": iso(ts(b["end_utc"])), "high": hi, "low": lo, "bars": b["bars"], "state": b["state"],
                    "available_at": b.get("known_at") if b["state"] == "FINAL" else None, "high_at": b.get("high_at"), "low_at": b.get("low_at"),
                    "coverage": {k: b.get(k) for k in ("expected_slots", "observed_slots", "missing_slots", "coverage_ratio", "coverage_basis")},
                    "events": [{"t": e["bar_open_utc"], "event": e["kind"].replace("RETURN_INSIDE_AFTER_BREAK", "RETURN_INSIDE"), "available_at": e["available_at"],
                                "event_id": e["event_id"]} for e in b.get("events") or []], "edges": b.get("edges")})
    return {"boxes": out[-9:], "definitions": SESSIONS[asset], "profile_id": prof, "engine": se.VERSION,
            "note": "czas lokalny giełdy z zoneinfo (DST); wartości w UTC; wspólny silnik sesji (profil " + prof + ")"}


def memory_sequence(bars_by_tf: dict[str, list[dict]], host_tf: str, host_open_utc: str) -> dict:
    """M20: the host candle's interval [open, close) projected on the other TFs of the SAME asset. Lower TFs: bars fully
    inside; higher TFs: the containing bar, flagged `forming_at_host_close` when it was still open at the host's close
    (in replay its final OHLC was not yet known then)."""
    t0 = ts(host_open_utc)
    t1 = t0 + TF_SEC[host_tf]
    out = {}
    for tf, bars in bars_by_tf.items():
        if tf == host_tf:
            continue
        sec = TF_SEC[tf]
        if sec <= TF_SEC[host_tf]:
            sel = [b for b in bars if t0 <= ts(b["open_utc"]) and ts(b["open_utc"]) + sec <= t1]
            out[tf] = {"relation": "INSIDE", "bars": [{k: b[k] for k in ("open_utc", "o", "h", "l", "c")} for b in sel]}
        else:
            cont = [b for b in bars if ts(b["open_utc"]) <= t0 and ts(b["open_utc"]) + sec >= t1]
            if cont:
                b = cont[-1]
                out[tf] = {"relation": "CONTAINING", "bar": {k: b[k] for k in ("open_utc", "o", "h", "l", "c")},
                           "forming_at_host_close": ts(b["open_utc"]) + sec > t1}
            else:
                out[tf] = {"relation": "NONE"}
    return {"host_tf": host_tf, "host_open_utc": host_open_utc, "host_close_utc": iso(t1), "projections": out}


def as_of_join(lower_decision_t: float, higher: list[dict], tf_high: str) -> dict | None:
    """Latest higher-TF bar whose CLOSE is <= the decision time (no future H1 close inside an M5 decision)."""
    sec = TF_SEC[tf_high]
    ok = [b for b in higher if ts(b["open_utc"]) + sec <= lower_decision_t and b.get("closed", True)]
    return ok[-1] if ok else None
