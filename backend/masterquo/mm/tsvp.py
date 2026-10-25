"""Tick Session Volume Profile - testable core (PMW-MM-TSVP-1). DETERMINISTIC_INDICATOR / VISUALIZATION (the MT5 renderer is
mql5/MasterModels/Indicators/PMW_TickSessionVP.mq5; this module is its reference model and the bot-side profile).

Source modes (never switched silently):
  ACTUAL_TRADE_VOLUME  - only ticks with TICK_FLAG_LAST|TICK_FLAG_VOLUME (or COPY_TICKS_TRADE records) with last > 0 and a positive
                         volume_real (else volume); quote-only ticks are ignored. If the feed has none -> status ACTUAL_VOLUME_UNAVAILABLE.
  TICK_ACTIVITY_PROXY  - counts eligible quote events (bid change, by default) at the bid; labelled as a proxy, never as volume.
Bucket key = floor((price - origin) / size + 1e-9) on a grid aligned to the tick size (origin = 0, size = k * tick). The ATR mode
freezes the resolved size for the profile snapshot; a different size is a FULL_REBUILD. Session interval: start <= t <= end (closed).
Incremental reconciliation: ticks arrive in overlapping inclusive range reads; MT5 ticks have no unique id, so the reconciler keeps, for
the trailing (not yet closed) millisecond, the multiset of field signatures already counted and adds only the surplus occurrences of a
later read (`integrity = EXACT_UNDER_MULTISET_ASSUMPTION`: two genuinely identical ticks in the same ms read in separate polls are only
distinguishable by count, which is what the multiset preserves). Milliseconds older than the watermark are final.
Render state machine priority: FULL_REBUILD_REQUIRED > FULL_REDRAW_REQUIRED > PARTIAL_UPDATE_PENDING > CLEAN.
POC = bucket with the largest value; ties -> the lower price bucket (deterministic). POC is computed from bucket values, never pixels.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

VERSION = "PMW-MM-TSVP-1"
TICK_FLAG_BID, TICK_FLAG_ASK, TICK_FLAG_LAST, TICK_FLAG_VOLUME = 2, 4, 8, 16
STATE_PRI = {"CLEAN": 0, "PARTIAL_UPDATE_PENDING": 1, "FULL_REDRAW_REQUIRED": 2, "FULL_REBUILD_REQUIRED": 3}


class BucketMap:
    """Open-addressing hash map int64 key -> [value, count] with linear probing and load-factor growth (expected O(1))."""

    def __init__(self, cap: int = 64, max_load: float = 0.6):
        self.cap = max(8, 1 << (cap - 1).bit_length())
        self.max_load = max_load
        self.keys: list[int | None] = [None] * self.cap
        self.vals: list[list[float]] = [[0.0, 0] for _ in range(self.cap)]
        self.n = 0
        self.rehashes = 0

    def _slot(self, k: int) -> int:
        h = (k * 0x9E3779B97F4A7C15) & (self.cap - 1)
        while self.keys[h] is not None and self.keys[h] != k:
            h = (h + 1) & (self.cap - 1)
        return h

    def _grow(self):
        old = [(k, v) for k, v in zip(self.keys, self.vals) if k is not None]
        self.cap *= 2
        self.keys = [None] * self.cap
        self.vals = [[0.0, 0] for _ in range(self.cap)]
        self.n = 0
        self.rehashes += 1
        for k, v in old:
            s = self._slot(k)
            self.keys[s], self.vals[s] = k, v
            self.n += 1
        if self.n != len(old):
            raise RuntimeError("REHASH_LOST_BUCKET")

    def add(self, k: int, v: float) -> float:
        if (self.n + 1) / self.cap > self.max_load:
            self._grow()
        s = self._slot(k)
        if self.keys[s] is None:
            self.keys[s] = k
            self.n += 1
        self.vals[s][0] += v
        self.vals[s][1] += 1
        return self.vals[s][0]

    def get(self, k: int) -> float:
        s = self._slot(k)
        return self.vals[s][0] if self.keys[s] == k else 0.0

    def items(self):
        return sorted((k, v[0], v[1]) for k, v in zip(self.keys, self.vals) if k is not None)


@dataclass
class TSVPConfig:
    source: str = "TICK_ACTIVITY_PROXY"     # | ACTUAL_TRADE_VOLUME
    bucket_mode: str = "MANUAL"             # | ATR
    bucket_ticks: int = 50                  # manual size = bucket_ticks * tick
    atr_mult: float = 0.25
    tick: float = 0.01
    proxy_event: str = "BID_CHANGE"         # | ANY_QUOTE

    def validate(self):
        if self.source not in ("TICK_ACTIVITY_PROXY", "ACTUAL_TRADE_VOLUME") or self.bucket_mode not in ("MANUAL", "ATR"):
            raise ValueError("TSVP_MODE_INVALID")
        if self.bucket_ticks < 1 or self.tick <= 0 or self.atr_mult <= 0 or self.proxy_event not in ("BID_CHANGE", "ANY_QUOTE"):
            raise ValueError("TSVP_PARAM_INVALID")


class Profile:
    def __init__(self, cfg: TSVPConfig, start_ms: int, end_ms: int, atr: float | None = None):
        cfg.validate()
        if not start_ms < end_ms:
            raise ValueError("TSVP_SESSION_INVALID")
        self.cfg, self.start, self.end = cfg, int(start_ms), int(end_ms)
        if cfg.bucket_mode == "ATR":
            if not (atr and math.isfinite(atr) and atr > 0):
                raise ValueError("TSVP_ATR_UNAVAILABLE")
            self.size = max(cfg.tick, round(atr * cfg.atr_mult / cfg.tick) * cfg.tick)
        else:
            self.size = cfg.bucket_ticks * cfg.tick
        self.map = BucketMap()
        self.dirty: set[int] = set()
        self.state = "FULL_REBUILD_REQUIRED"
        self.total = 0.0
        self.max_val = 0.0
        self.poc: int | None = None
        self.watermark_ms = None            # last fully reconciled millisecond
        self.tail_ms = None
        self.tail_seen: Counter = Counter()
        self.last_bid = None
        self.counted = 0
        self.ignored = {"outside_session": 0, "not_eligible": 0, "invalid": 0, "duplicate": 0}
        self.status = "EMPTY"

    def key(self, price: float) -> int:
        return math.floor(price / self.size + 1e-9)

    def bounds(self, k: int) -> tuple[float, float, float]:
        lo = k * self.size
        return lo, lo + self.size, lo + self.size / 2

    def request(self, st: str):
        if STATE_PRI[st] > STATE_PRI[self.state]:
            self.state = st                                    # a lower-priority request never downgrades a pending one

    def _eligible(self, t: dict) -> tuple[float, float] | None:
        flags = int(t.get("flags", 0))
        if self.cfg.source == "ACTUAL_TRADE_VOLUME":
            if not (flags & TICK_FLAG_LAST) or not (flags & TICK_FLAG_VOLUME):
                return None
            vol = float(t.get("volume_real") or 0) or float(t.get("volume") or 0)
            px = float(t.get("last") or 0)
            return (px, vol) if px > 0 and vol > 0 else None
        bid = float(t.get("bid") or 0)
        if bid <= 0:
            return None
        if self.cfg.proxy_event == "BID_CHANGE" and not (flags & TICK_FLAG_BID) and self.last_bid is not None and bid == self.last_bid:
            return None
        return (bid, 1.0)

    @staticmethod
    def _sig(t: dict) -> tuple:
        return (int(t["time_msc"]), float(t.get("bid") or 0), float(t.get("ask") or 0), float(t.get("last") or 0), int(t.get("volume") or 0),
                float(t.get("volume_real") or 0), int(t.get("flags", 0)))

    def ingest(self, ticks: list[dict], read_until_ms: int | None = None) -> dict:
        """Feed one chronologically ordered (oldest first) inclusive range read. Overlap with previous reads is reconciled."""
        added = 0
        by_ms: dict[int, list[dict]] = {}
        for t in ticks:
            by_ms.setdefault(int(t["time_msc"]), []).append(t)
        for ms in sorted(by_ms):
            if self.watermark_ms is not None and ms <= self.watermark_ms:
                self.ignored["duplicate"] += len(by_ms[ms])                    # already final
                continue
            group = by_ms[ms]
            if ms == self.tail_ms:
                cnt = Counter(self._sig(t) for t in group)
                new = []
                for sig, c in cnt.items():
                    surplus = c - self.tail_seen.get(sig, 0)
                    self.ignored["duplicate"] += min(c, self.tail_seen.get(sig, 0))
                    new += [t for t in group if self._sig(t) == sig][:max(0, surplus)]
                    self.tail_seen[sig] = max(self.tail_seen.get(sig, 0), c)
                group = new
            else:
                if self.tail_ms is not None and ms > self.tail_ms:
                    self.watermark_ms = self.tail_ms                           # the previous trailing ms is now final
                self.tail_ms, self.tail_seen = ms, Counter(self._sig(t) for t in group)
            for t in group:
                added += self._count(t)
        if read_until_ms is not None and self.tail_ms is not None and read_until_ms > self.tail_ms:
            self.watermark_ms = self.tail_ms
        self.status = "COMPLETE" if self.counted else ("ACTUAL_VOLUME_UNAVAILABLE" if self.cfg.source == "ACTUAL_TRADE_VOLUME" else "EMPTY")
        return {"added": added, "state": self.state, "status": self.status}

    def _count(self, t: dict) -> int:
        ms = int(t["time_msc"])
        if not (self.start <= ms <= self.end):
            self.ignored["outside_session"] += 1
            return 0
        e = self._eligible(t)
        if t.get("bid"):
            self.last_bid = float(t["bid"])
        if e is None:
            self.ignored["not_eligible"] += 1
            return 0
        px, v = e
        if not (math.isfinite(px) and math.isfinite(v)):
            self.ignored["invalid"] += 1
            return 0
        k = self.key(px)
        val = self.map.add(k, v)
        self.total += v
        self.counted += 1
        self.dirty.add(k)
        if val > self.max_val or (val == self.max_val and self.poc is not None and k < self.poc):
            new_max = val > self.max_val
            self.max_val, self.poc = val, k
            if new_max:
                self.request("FULL_REDRAW_REQUIRED")                       # normalised widths of every bar change
        self.request("PARTIAL_UPDATE_PENDING")
        return 1

    def render_pass(self, rows_budget: int = 10_000) -> dict:
        """What the renderer must redraw now (the MT5 renderer does the same in OnTimer). Clears dirty keys only on success."""
        st = self.state
        if st == "CLEAN":
            return {"state": st, "draw": []}
        if st in ("FULL_REBUILD_REQUIRED", "FULL_REDRAW_REQUIRED"):
            self.dirty = {k for k, _, _ in self.map.items()}          # every bucket once, then budgeted partial passes
            self.state = "PARTIAL_UPDATE_PENDING"
        draw = sorted(self.dirty)[:rows_budget]
        self.dirty -= set(draw)
        if not self.dirty:
            self.state = "CLEAN"
        return {"state": st, "draw": draw, "poc": self.poc, "max": self.max_val, "remaining": len(self.dirty)}

    def summary(self) -> dict:
        it = self.map.items()
        return {"version": VERSION, "source": self.cfg.source, "label": "TICK ACTIVITY (proxy, nie wolumen)" if self.cfg.source == "TICK_ACTIVITY_PROXY"
                else "ACTUAL TRADE VOLUME", "bucket_size": self.size, "bucket_mode": self.cfg.bucket_mode, "buckets": len(it), "total": self.total,
                "poc_key": self.poc, "poc_price": self.bounds(self.poc)[2] if self.poc is not None else None, "status": self.status,
                "counted": self.counted, "ignored": self.ignored, "integrity": "EXACT_UNDER_MULTISET_ASSUMPTION", "rehashes": self.map.rehashes,
                "session_ms": [self.start, self.end]}


def rebuild(cfg: TSVPConfig, start_ms: int, end_ms: int, ticks: list[dict], atr: float | None = None) -> Profile:
    p = Profile(cfg, start_ms, end_ms, atr)
    p.ingest([t for t in ticks if start_ms <= int(t["time_msc"]) <= end_ms], read_until_ms=end_ms)
    p.request("FULL_REDRAW_REQUIRED")
    return p
