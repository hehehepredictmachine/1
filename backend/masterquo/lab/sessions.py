"""M15 Session Sweep Boxes + M20 Memory Sequence + multi-TF availability join (MQ-LAB-TIME-1.0.0).

Sessions are defined in the exchange's LOCAL time zone (zoneinfo -> DST handled), separately per asset; all stored times are
UTC. A session box's high/low is final (available) only after the session end; before that it is `developing`.
"""
from __future__ import annotations

from datetime import datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np

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


def session_windows(asset: str, day_utc: datetime) -> list[dict]:
    """UTC windows of each session whose LOCAL date equals the given calendar day (DST-correct)."""
    out = []
    for name, tz, a, b in SESSIONS[asset]:
        z = ZoneInfo(tz)
        local_day = day_utc.astimezone(z).date() if day_utc.tzinfo else day_utc.date()
        start = datetime.combine(local_day, _hm(a), z).astimezone(timezone.utc)
        end = datetime.combine(local_day, _hm(b), z).astimezone(timezone.utc)
        out.append({"session": name, "tz": tz, "start": start, "end": end})
    return out


def session_boxes(bars: list[dict], tf: str, asset: str, days: int = 3) -> dict:
    """Boxes for the last `days` UTC days: high/low from bars fully inside the window, breakout (first close beyond after
    the end), return inside, sweep (wick beyond + close inside)."""
    if not bars:
        return {"boxes": []}
    t = np.array([ts(b["open_utc"]) for b in bars])
    h = np.array([b["h"] for b in bars], float)
    lo = np.array([b["l"] for b in bars], float)
    c = np.array([b["c"] for b in bars], float)
    sec = TF_SEC[tf]
    as_of = t[-1] + sec
    last_day = datetime.fromtimestamp(t[-1], timezone.utc)
    boxes = []
    for k in range(days, -1, -1):
        day = last_day - timedelta(days=k)
        for w in session_windows(asset, day):
            s0, s1 = w["start"].timestamp(), w["end"].timestamp()
            m = (t >= s0) & (t + sec <= s1)
            if not m.any() or s0 > as_of:
                continue
            final = s1 <= as_of
            hi, low = float(h[m].max()), float(lo[m].min())
            box = {"id": f"SB-{asset}-{w['session']}-{w['start'].date()}", "session": w["session"], "tz": w["tz"],
                   "start_utc": iso(s0), "end_utc": iso(s1), "high": hi, "low": low, "bars": int(m.sum()),
                   "state": "FINAL" if final else "DEVELOPING", "available_at": iso(s1) if final else None,
                   "high_at": bars[int(np.where(m)[0][np.argmax(h[m])])]["open_utc"],
                   "low_at": bars[int(np.where(m)[0][np.argmin(lo[m])])]["open_utc"], "events": []}
            if final:
                after = np.where(t >= s1)[0]
                state = "INSIDE"
                for i in after:
                    if state in ("INSIDE", "RETURNED"):
                        if c[i] > hi:
                            box["events"].append({"t": bars[i]["open_utc"], "event": "BREAKOUT_UP"})
                            state = "OUT_UP"
                        elif c[i] < low:
                            box["events"].append({"t": bars[i]["open_utc"], "event": "BREAKOUT_DOWN"})
                            state = "OUT_DOWN"
                        elif h[i] > hi or lo[i] < low:
                            box["events"].append({"t": bars[i]["open_utc"], "event": "SWEEP_HIGH" if h[i] > hi else "SWEEP_LOW"})
                    elif (state == "OUT_UP" and c[i] < hi) or (state == "OUT_DOWN" and c[i] > low):
                        box["events"].append({"t": bars[i]["open_utc"], "event": "RETURN_INSIDE"})
                        state = "RETURNED"
                    if len(box["events"]) >= 6:
                        break
            boxes.append(box)
    return {"boxes": boxes[-9:], "definitions": SESSIONS[asset], "note": "czas lokalny giełdy z zoneinfo (DST); wartości w UTC"}


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
