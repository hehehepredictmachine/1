"""Canonical Trade Event Engine (Apollo23 TASK 004 / M5) - ONE immutable executed-trade ledger shared by Volume Profile (TASK 001),
Bookmap trade bubbles (TASK 002), Footprint (TASK 004) and verified delta / CVD features.

Provider side semantics are explicit per provider. A raw side is turned into an AGGRESSOR side only where the provider's documented field
semantics is VERIFIED; otherwise the trade's aggressor is UNKNOWN and every directional consumer (delta, CVD, imbalance, strategies needing
`trades_aggressor`) is disabled - never estimated from candles, ticks, quotes or DOM.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

ENGINE_VERSION = "PMW-TRADE-LEDGER-1"

# provider -> how its raw trade side maps to the aggressor. Status values: VERIFIED (official field documentation), NOT_VERIFIED.
SIDE_SEMANTICS = {
    "BINANCE": {"field": "isBuyerMaker", "status": "VERIFIED", "rule": "isBuyerMaker=true -> seller is the aggressor (SELL); false -> BUY",
                "source": "OFFICIAL_PROVIDER_DOC (Binance aggTrade / trade: m = is the buyer the market maker)"},
    "BYBIT": {"field": "S", "status": "VERIFIED", "rule": "S = taker side (Buy / Sell)", "source": "OFFICIAL_PROVIDER_DOC (Bybit V5 publicTrade: S = side of taker)"},
    "OKX": {"field": "side", "status": "VERIFIED", "rule": "side = taker side (buy / sell)", "source": "OFFICIAL_PROVIDER_DOC (OKX V5 trades: side = taker side)"},
    "HYPERLIQUID": {"field": "side", "status": "NOT_VERIFIED", "rule": "raw 'B' / 'A' - aggressor meaning not proven in the official schema",
                    "source": "NOT_VERIFIED (WsTrade.side documented as a side enum only; owner must confirm before enabling)"},
    "MT5": {"field": "MqlTick.flags", "status": "NOT_VERIFIED", "rule": "TICK_FLAG_BUY/SELL describe last-deal ticks of the broker feed, not a venue tape",
            "source": "NOT_VERIFIED"},
}


def aggressor_from_raw(provider: str, raw) -> str:
    sem = SIDE_SEMANTICS.get(provider.upper())
    if not sem or sem["status"] != "VERIFIED":
        return "UNKNOWN"
    p = provider.upper()
    if p == "BINANCE":
        return "SELL" if raw in (True, "true", "True", 1) else ("BUY" if raw in (False, "false", "False", 0) else "UNKNOWN")
    v = str(raw or "").strip().upper()
    return "BUY" if v in ("BUY", "B") else ("SELL" if v in ("SELL", "S") else "UNKNOWN")


def capability(provider: str) -> str:
    """Capability `trades_aggressor` for a provider: SUPPORTED only when the side semantics is VERIFIED."""
    s = SIDE_SEMANTICS.get(provider.upper(), {}).get("status")
    return "SUPPORTED" if s == "VERIFIED" else "NOT_VERIFIED"


@dataclass(frozen=True)
class TradeEvent:
    provider: str
    instrument_id: str
    trade_id: str
    ts: float                 # event time (venue), seconds UTC
    price: float
    size: float               # base units (instrument metadata unit)
    aggressor: str            # BUY | SELL | UNKNOWN
    raw_side: str = ""
    revision: int = 0

    def __post_init__(self):
        for k in ("ts", "price", "size"):
            v = getattr(self, k)
            if not isinstance(v, (int, float)) or math.isnan(v) or math.isinf(v):
                raise ValueError(f"NON_FINITE_{k.upper()}")
        if self.price <= 0 or self.size <= 0:
            raise ValueError("NON_POSITIVE_PRICE_OR_SIZE")
        if self.aggressor not in ("BUY", "SELL", "UNKNOWN"):
            raise ValueError("BAD_AGGRESSOR")


class TradeLedger:
    """Dedupe by (provider, instrument, trade_id); a correction (same id, higher revision) replaces the event; output ordered by (ts, id)."""

    def __init__(self, max_per_instrument: int | None = None):
        self._ev: dict[tuple, TradeEvent] = {}
        self.duplicates = 0
        self.corrections = 0
        self.max_per_instrument = max_per_instrument      # 1.46: bound for a process running for weeks (None = unbounded)
        self._n: dict[str, int] = {}
        self.dropped = 0

    def _prune(self, instrument_id: str) -> None:
        keep = self.max_per_instrument
        mine = sorted((e.ts, e.trade_id, k) for k, e in self._ev.items() if e.instrument_id == instrument_id)
        for _, _, k in mine[:max(0, len(mine) - keep)]:
            del self._ev[k]
            self.dropped += 1
        self._n[instrument_id] = min(len(mine), keep)

    def add(self, e: TradeEvent) -> str:
        k = (e.provider, e.instrument_id, e.trade_id)
        cur = self._ev.get(k)
        if cur is None:
            self._ev[k] = e
            n = self._n[e.instrument_id] = self._n.get(e.instrument_id, 0) + 1
            if self.max_per_instrument and n > self.max_per_instrument * 1.1:     # prune in batches: the OLDEST events go first
                self._prune(e.instrument_id)
            return "ADDED"
        if e.revision > cur.revision:
            self._ev[k] = e
            self.corrections += 1
            return "CORRECTED"
        self.duplicates += 1
        return "DUPLICATE"

    def extend(self, evs) -> dict:
        out = {"ADDED": 0, "CORRECTED": 0, "DUPLICATE": 0}
        for e in evs:
            out[self.add(e)] += 1
        return out

    def events(self, instrument_id: str | None = None, t0: float | None = None, t1: float | None = None) -> list[TradeEvent]:
        ev = [e for e in self._ev.values() if (instrument_id is None or e.instrument_id == instrument_id)
              and (t0 is None or e.ts >= t0) and (t1 is None or e.ts < t1)]
        return sorted(ev, key=lambda e: (e.ts, e.trade_id))

    def total_volume(self, instrument_id: str | None = None) -> float:
        return sum(e.size for e in self.events(instrument_id))


def from_hyperliquid(instrument_id: str, rows: list[dict]) -> list[TradeEvent]:
    out = []
    for r in rows or []:
        try:
            out.append(TradeEvent("HYPERLIQUID", instrument_id, str(r.get("tid") or r.get("hash") or f"{r['time']}:{r['px']}:{r['sz']}"),
                                  float(r["time"]) / 1000.0, float(r["px"]), float(r["sz"]), aggressor_from_raw("HYPERLIQUID", r.get("side")),
                                  str(r.get("side") or "")))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def with_aggressor(e: TradeEvent, provider: str | None = None) -> TradeEvent:
    return replace(e, aggressor=aggressor_from_raw(provider or e.provider, e.raw_side))
