"""Closed-bar series as known at `as_of` (the only input of the zone engines). A bar is used only when it is closed AND its close
time (open + TF) is <= as_of; a forming bar or a bar from the future never enters a calculation (no look-ahead)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ..timeutil import TF_SECONDS


def ts(x) -> float:
    if isinstance(x, (int, float)):
        return float(x)
    return datetime.fromisoformat(str(x).replace("Z", "+00:00")).timestamp()


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

    @classmethod
    def from_tfview(cls, v, tf: str, as_of: float | None = None) -> "Series":
        """strategies.base.TFView (closed bars only) -> Series, cut at as_of."""
        bars = [{"open_utc": t, "o": o, "h": h, "l": lo, "c": c, "tv": tv} for t, o, h, lo, c, tv in zip(v.t, v.o, v.h, v.l, v.c, v.tv)]
        return cls.from_bars(bars, tf, as_of)

    def tail(self, n: int) -> "Series":
        if n >= len(self):
            return self
        s = Series(self.tf, self.tf_s)
        for k in ("t", "o", "h", "l", "c", "v", "rv"):
            setattr(s, k, getattr(self, k)[-n:])
        return s
