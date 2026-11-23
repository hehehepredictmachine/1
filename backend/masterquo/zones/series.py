"""Closed-bar series as known at `as_of` (the only input of the zone engines). A bar is used only when it is closed AND its close
time (open + TF) is <= as_of; a forming bar or a bar from the future never enters a calculation (no look-ahead)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..timeutil import TF_SECONDS


def ts(x) -> float:
    if isinstance(x, (int, float)):
        return float(x)
    d = datetime.fromisoformat(str(x).replace("Z", "+00:00"))
    if d.tzinfo is None:
        # 1.46: a naive ISO string was read in the LOCAL time zone of the machine (Windows Europe/Warsaw: as_of shifted by 1-2 h);
        # every caller passes UTC (bar open_utc, API as_of) - naive = UTC explicitly, independent of the machine
        d = d.replace(tzinfo=timezone.utc)
    return d.timestamp()


def iso(t: float | None) -> str | None:
    if t is None:
        return None
    from datetime import timezone
    return datetime.fromtimestamp(float(t), timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class Series:
    tf: str
    tf_s: int
    t: list[float] = field(default_factory=list)          # open time (UTC epoch)
    o: list[float] = field(default_factory=list)
    h: list[float] = field(default_factory=list)
    l: list[float] = field(default_factory=list)
    c: list[float] = field(default_factory=list)
    v: list[float] = field(default_factory=list)          # tick volume (MT5 tick_volume) - activity proxy, not traded quantity
    rv: list[float] = field(default_factory=list)         # real (exchange) volume - 0 on OTC CFDs

    def __len__(self) -> int:
        return len(self.c)

    def close_time(self, i: int) -> float:
        return self.t[i] + self.tf_s

    @classmethod
    def from_bars(cls, bars: list[dict], tf: str, as_of: float | None = None) -> "Series":
        tf_s = TF_SECONDS[tf]
        rows = {}
        for b in bars or []:
            if not b.get("open_utc") or b.get("closed") is False:
                continue
            o = ts(b["open_utc"])
            if as_of is not None and o + tf_s > as_of + 1e-6:
                continue
            rows[o] = b                                                       # duplicate slot: the latest revision wins
        s = cls(tf, tf_s)
        for o in sorted(rows):
            b = rows[o]
            s.t.append(o)
            s.o.append(float(b["o"]))
            s.h.append(float(b["h"]))
            s.l.append(float(b["l"]))
            s.c.append(float(b["c"]))
            s.v.append(float(b.get("tv") or 0.0))
            s.rv.append(float(b.get("rv") or 0.0))
        return s
    # 1.46: unused from_tfview() / tail() removed (no caller in backend/, tools/, tests/)
