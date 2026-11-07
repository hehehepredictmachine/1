"""Spread percentile and execution-condition view (PMW-IND-SPREAD-1).

Sampling: the live quote is sampled on a FIXED clock (default every 10 s; method FIXED_INTERVAL) - not per tick, so a session with
more quote updates does not get more weight. Each sample stores the session (same calendar as profiles), the slot within the
session (minutes since session start // slot_minutes) and the session instance (session + local date).

Percentile of the current spread: reference = previous session instances of the SAME instrument + broker symbol, the SAME session
and the SAME slot. Each instance contributes ONE value (median of its samples in that slot), so a busy day does not dominate. Only
instances that started before the current one are used (a point never belongs to its own future reference). Percentile =
100 * (count(ref < x) + 0.5 * count(ref == x)) / n. Fewer than min_sessions instances -> WARMUP.

Costs: the spread is already inside bid/ask prices of every fill and every replay with bid/ask - it is reported next to TP1 / RR for
reading, never added a second time on top of bid/ask-based costs. Data latency (receive - quote time), quote interval (time between
distinct quotes) and real execution slippage (from fills) are three different numbers and are kept apart.
"""
from __future__ import annotations

import statistics
import time

from . import contract as C

VERSION = "PMW-IND-SPREAD-1"
UNITS = {"spread_price": "price", "spread_ticks": "ticks", "spread_atr": "atr", "percentile": "percent", "quote_age_s": "seconds",
         "receive_delay_s": "seconds", "quote_interval_s": "seconds", "updates_per_min": "count_per_minute", "spread_to_tp1": "ratio"}


def session_slot(profile_id: str, t: float, slot_minutes: int = 30) -> dict:
    from ..analytics import session_engine as SE
    ws = [w for w in SE.windows(profile_id, t, 1, 0) if w["start"].timestamp() <= t < w["end"].timestamp()]
    if not ws:
        return {"session": "OFF_SESSION", "slot": int((t % 86400) // (slot_minutes * 60)), "instance": time.strftime("%Y-%m-%d", time.gmtime(t)),
                "instance_start": t - (t % 86400)}
    w = max(ws, key=lambda x: x["start"])
    st = w["start"].timestamp()
    return {"session": w["session"], "slot": int((t - st) // (slot_minutes * 60)), "instance": f"{w['session']}:{w['local_date']}",
            "instance_start": st}


def percentile(x: float, ref: list[float]) -> float | None:
    if not ref:
        return None
    lt = sum(1 for r in ref if r < x)
    eq = sum(1 for r in ref if r == x)
    return 100.0 * (lt + 0.5 * eq) / len(ref)


def reference(samples: list[dict], *, session: str, slot: int, before_instance_start: float, max_sessions: int = 20) -> list[float]:
    """One median per earlier session instance (same session + slot). samples: {t, spread, session, slot, instance, instance_start}."""
    by: dict[str, list[float]] = {}
    starts: dict[str, float] = {}
    for s in samples:
        if s["session"] != session or s["slot"] != slot or s["instance_start"] >= before_instance_start - 1e-6:
            continue
        by.setdefault(s["instance"], []).append(float(s["spread"]))
        starts[s["instance"]] = s["instance_start"]
    keys = sorted(by, key=lambda k: starts[k])[-max_sessions:]
    return [statistics.median(by[k]) for k in keys]


def compute(quote: dict | None, samples: list[dict], *, now: float, instrument: str, broker_symbol: str | None, profile_id: str,
            tick: float, atr_v: float | None = None, tp1_distance: float | None = None, slot_minutes: int = 30, min_sessions: int = 5,
            max_sessions: int = 20, max_quote_age_s: float = 30.0, intensity: dict | None = None, cfg: dict | None = None,
            sample_every_s: float = 10.0) -> dict:
    cfgd = dict(cfg or {}, slot_minutes=slot_minutes, min_sessions=min_sessions, max_sessions=max_sessions, max_quote_age_s=max_quote_age_s,
                sampling=f"FIXED_INTERVAL_{int(sample_every_s)}S")
    base = dict(instrument=instrument, broker_symbol=broker_symbol, source="MT5_QUOTE", timeframe=None, cfg=cfgd,
                instrument_meta={"tick": tick}, units=UNITS)
    if not quote or quote.get("bid") is None or quote.get("ask") is None:
        return C.result("SPREAD", VERSION, status="NO_DATA", reason="NO_QUOTE", **base)
    sp = float(quote["ask"]) - float(quote["bid"])
    qt = C.ts(quote.get("time_utc")) if quote.get("time_utc") else None
    rec = C.ts(quote.get("received_at")) if quote.get("received_at") else None
    age = (now - qt) if qt is not None else None
    ss = session_slot(profile_id, now, slot_minutes)
    ref = reference(samples, session=ss["session"], slot=ss["slot"], before_instance_start=ss["instance_start"], max_sessions=max_sessions)
    pct = percentile(sp, ref) if len(ref) >= min_sessions else None
    vals = {"spread_price": sp, "spread_ticks": sp / tick if tick else None, "spread_atr": sp / atr_v if atr_v else None,
            "percentile": pct, "quote_age_s": age, "receive_delay_s": (rec - qt) if (rec is not None and qt is not None) else None,
            "quote_interval_s": (intensity or {}).get("mean_interval_s"), "updates_per_min": (intensity or {}).get("updates_per_min"),
            "spread_to_tp1": sp / tp1_distance if tp1_distance else None, "session": ss["session"], "slot": ss["slot"],
            "reference_sessions": len(ref), "reference_median": statistics.median(ref) if ref else None,
            "unusual": (pct is not None and pct >= 90.0), "spread_in_prices": True}
    extra = {"session_slot": ss, "note": "spread jest już w cenach bid/ask – nie jest doliczany drugi raz do kosztów"}
    if age is not None and age > max_quote_age_s:
        return C.result("SPREAD", VERSION, values=vals, status="STALE", reason=f"QUOTE_AGE_{int(age)}S", sample_count=len(ref), data_time=qt,
                        available_at=rec, extra=extra, **base)
    if pct is None:
        return C.result("SPREAD", VERSION, values=vals, status="WARMUP", reason=f"REFERENCE_SESSIONS_{len(ref)}<{min_sessions}",
                        sample_count=len(ref), data_time=qt, available_at=rec, extra=extra, **base)
    return C.result("SPREAD", VERSION, values=vals, sample_count=len(ref), data_time=qt, available_at=rec, extra=extra, **base)


class Intensity:
    """Distinct quotes per minute and mean interval between distinct quotes (from the quote time_msc sequence)."""

    def __init__(self, window_s: float = 60.0):
        self.window_s = window_s
        self.ts: list[float] = []
        self.last_msc = None

    def observe(self, quote: dict | None, now: float) -> None:
        if not quote or quote.get("time_msc") is None or quote.get("time_msc") == self.last_msc:
            return
        self.last_msc = quote["time_msc"]
        self.ts.append(now)
        cut = now - self.window_s
        while self.ts and self.ts[0] < cut:
            self.ts.pop(0)

    def view(self) -> dict:
        n = len(self.ts)
        iv = [b - a for a, b in zip(self.ts, self.ts[1:])]
        return {"updates_per_min": n * 60.0 / self.window_s, "mean_interval_s": (sum(iv) / len(iv)) if iv else None}
