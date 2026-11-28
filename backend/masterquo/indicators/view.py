"""TFView - closed bars of one timeframe as parallel lists with a per-view indicator cache (1.46 arch, Etap 4).

Moved here byte for byte from strategies/base.py: the class uses only the causal indicator functions (indicators.series), so an
analysis-layer user of a bar view (zones.hlze -> analysis.range_m5) no longer imports the trading core. strategies.base keeps the name as
a compatibility alias of the SAME class object (strategies.base.TFView is indicators.view.TFView) - every strategy, the regime engine,
the ML features and the tests keep working unchanged.
"""
from __future__ import annotations

from . import series as ind


class TFView:
    """Closed bars of one timeframe as parallel lists + the forming bar (closed=False) if any."""

    def __init__(self, tf: str, bars: list[dict]):
        self.tf = tf
        closed = [b for b in bars if b.get("closed") and b.get("open_utc")]
        self.t = [b["open_utc"] for b in closed]
        self.o = [float(b["o"]) for b in closed]
        self.h = [float(b["h"]) for b in closed]
        self.l = [float(b["l"]) for b in closed]
        self.c = [float(b["c"]) for b in closed]
        self.tv = [float(b.get("tv") or 0.0) for b in closed]     # broker tick count (CFD activity proxy, not exchange volume)
        fb = next((b for b in reversed(bars) if not b.get("closed")), None)
        self.forming = {"open_utc": fb["open_utc"], "o": float(fb["o"]), "h": float(fb["h"]), "l": float(fb["l"]), "c": float(fb["c"])} if fb else None
        self._cache: dict = {}

    def __len__(self) -> int:
        return len(self.c)

    @property
    def last(self) -> int:
        return len(self.c) - 1

    def get(self, key: str, fn):
        if key not in self._cache:
            self._cache[key] = fn()
        return self._cache[key]

    def atr(self, n: int = 14):
        return self.get(f"atr{n}", lambda: ind.atr(self.h, self.l, self.c, n))

    def ema(self, n: int):
        return self.get(f"ema{n}", lambda: ind.ema(self.c, n))

    def rsi(self, n: int = 14):
        return self.get(f"rsi{n}", lambda: ind.rsi(self.c, n))

    def macd_hist(self):
        return self.get("macdh", lambda: ind.macd_hist(self.c))

    def pivots(self, left: int = 3, right: int = 3):
        return self.get(f"piv{left}_{right}", lambda: ind.pivots(self.h, self.l, left, right))
