"""Order-book microstructure from the broker's market depth (PMW-IND-OFI-1).

Source: MT5 market_book_add / market_book_get / market_book_release through the bridge's call queue (BookAdapter). For XAUUSD this is
the BROKER'S quote book (not an exchange order book); a symbol without DOM -> status NO_DATA "Brak danych arkusza" and the metrics do
not vote. Nothing here is derived from OHLC or tick volume - no synthetic order flow, no CVD, no historical DOM.

Metrics (each separately):
  best_imbalance  = (Qb - Qa) / (Qb + Qa) at the best levels (None when both sizes are 0);
  depth_imbalance = same over the first `levels` levels of each side (when the book has them);
  OFI (Cont, Kukanov, Stoikov 2014) per update n:
      e_n = 1[Pb_n >= Pb_{n-1}] Qb_n - 1[Pb_n <= Pb_{n-1}] Qb_{n-1} - 1[Pa_n <= Pa_{n-1}] Qa_n + 1[Pa_n >= Pa_{n-1}] Qa_{n-1}
      (price moves handled by the indicator terms; a removed best level appears as a price change);
  microprice      = (Pa Qb + Pb Qa) / (Qb + Qa) and its deviation from the mid - a quote-based measure, NOT a calibrated forecast.
Mode: EVENT_STREAM when every book change is seen, SAMPLED(<period>) when the book is polled - then OFI is an ESTIMATE from samples.
After a gap (> max_gap_s), a symbol change or a reconnect the accumulator RESETS (unknown changes are never summed).
"""
from __future__ import annotations

import threading
import time

from . import contract as C

VERSION = "PMW-IND-OFI-1"
UNITS = {"best_imbalance": "ratio", "depth_imbalance": "ratio", "ofi": "lots", "ofi_window": "lots", "microprice": "price",
         "microprice_dev": "price", "mid": "price"}
BOOK_TYPE_SELL, BOOK_TYPE_BUY, BOOK_TYPE_SELL_MARKET, BOOK_TYPE_BUY_MARKET = 1, 2, 3, 4


def normalize(entries, t: float) -> dict | None:
    """MT5 BookInfo rows (type, price, volume, volume_dbl) -> {bids: [(p, q)] best first, asks: [(p, q)] best first}."""
    bids, asks = [], []
    for e in entries or ():
        typ = int(getattr(e, "type", e[0] if isinstance(e, (tuple, list)) else 0))
        px = float(getattr(e, "price", e[1] if isinstance(e, (tuple, list)) else 0))
        q = getattr(e, "volume_dbl", None)
        if q is None:
            q = getattr(e, "volume", e[2] if isinstance(e, (tuple, list)) else 0)
        q = float(q or 0)
        if typ in (BOOK_TYPE_BUY, BOOK_TYPE_BUY_MARKET):
            bids.append((px, q))
        elif typ in (BOOK_TYPE_SELL, BOOK_TYPE_SELL_MARKET):
            asks.append((px, q))
    if not bids or not asks:
        return None
    bids.sort(key=lambda x: -x[0])
    asks.sort(key=lambda x: x[0])
    return {"t": t, "bids": bids, "asks": asks}


def best_imbalance(book: dict) -> float | None:
    qb, qa = book["bids"][0][1], book["asks"][0][1]
    return (qb - qa) / (qb + qa) if (qb + qa) > 0 else None


def depth_imbalance(book: dict, levels: int = 5) -> float | None:
    if len(book["bids"]) < 2 or len(book["asks"]) < 2:
        return None
    qb = sum(q for _, q in book["bids"][:levels])
    qa = sum(q for _, q in book["asks"][:levels])
    return (qb - qa) / (qb + qa) if (qb + qa) > 0 else None


def microprice(book: dict) -> tuple[float | None, float]:
    (pb, qb), (pa, qa) = book["bids"][0], book["asks"][0]
    mid = (pa + pb) / 2.0
    return ((pa * qb + pb * qa) / (qb + qa) if (qb + qa) > 0 else None), mid


def ofi_step(prev: dict, cur: dict) -> float:
    (pb0, qb0), (pa0, qa0) = prev["bids"][0], prev["asks"][0]
    (pb1, qb1), (pa1, qa1) = cur["bids"][0], cur["asks"][0]
    e = 0.0
    if pb1 >= pb0:
        e += qb1
    if pb1 <= pb0:
        e -= qb0
    if pa1 <= pa0:
        e -= qa1
    if pa1 >= pa0:
        e += qa0
    return e


class OFIAccumulator:
    def __init__(self, *, mode: str = "SAMPLED", period_s: float = 1.0, max_gap_s: float = 5.0, window_s: float = 60.0):
        self.mode, self.period_s, self.max_gap_s, self.window_s = mode, period_s, max_gap_s, window_s
        self.reset("INIT")

    def reset(self, why: str) -> None:
        self.prev: dict | None = None
        self.cum = 0.0
        self.steps: list[tuple[float, float]] = []
        self.resets = getattr(self, "resets", 0) + (0 if why == "INIT" else 1)
        self.last_reset = why
        self.key = None

    def add(self, book: dict | None, *, key=None) -> None:
        if book is None:
            return
        if key is not None and self.key is not None and key != self.key:
            self.reset("SYMBOL_OR_SESSION_CHANGE")
        self.key = key
        if self.prev is not None and book["t"] - self.prev["t"] > self.max_gap_s:
            self.reset(f"GAP_{book['t'] - self.prev['t']:.1f}S")
            self.key = key
        if self.prev is not None:
            e = ofi_step(self.prev, book)
            self.cum += e
            self.steps.append((book["t"], e))
            cut = book["t"] - self.window_s
            while self.steps and self.steps[0][0] < cut:
                self.steps.pop(0)
        self.prev = book

    def view(self) -> dict:
        return {"ofi": self.cum if self.prev is not None else None, "ofi_window": sum(e for _, e in self.steps) if self.steps else None,
                "updates": len(self.steps), "resets": self.resets, "last_reset": self.last_reset,
                "mode": "EVENT_STREAM" if self.mode == "EVENT_STREAM" else f"SAMPLED({self.period_s:g}s)",
                "estimate": self.mode != "EVENT_STREAM"}


def compute(book: dict | None, acc: OFIAccumulator, *, instrument: str, broker_symbol: str | None, status: str, reason: str | None = None,
            levels: int = 5, now: float | None = None, max_age_s: float = 5.0, cfg: dict | None = None) -> dict:
    cfgd = dict(cfg or {}, levels=levels, mode=acc.mode, period_s=acc.period_s, max_gap_s=acc.max_gap_s, window_s=acc.window_s)
    base = dict(instrument=instrument, broker_symbol=broker_symbol, source="MT5_MARKET_BOOK(broker)", timeframe=None, cfg=cfgd, units=UNITS)
    if status != "READY" or book is None:
        return C.result("MICROSTRUCTURE", VERSION, status="NO_DATA" if status in ("READY", "NO_DATA", "NOT_SUBSCRIBED") else status,
                        reason=reason or "Brak danych arkusza", extra={"label": "Brak danych arkusza"}, **base)
    now = now or time.time()
    mp, mid = microprice(book)
    v = acc.view()
    vals = {"best_imbalance": best_imbalance(book), "depth_imbalance": depth_imbalance(book, levels), "microprice": mp, "mid": mid,
            "microprice_dev": (mp - mid) if mp is not None else None, "ofi": v["ofi"], "ofi_window": v["ofi_window"],
            "bid_levels": len(book["bids"]), "ask_levels": len(book["asks"]), "best_bid_size": book["bids"][0][1],
            "best_ask_size": book["asks"][0][1]}
    extra = {"ofi_state": v, "note": "arkusz kwotowań brokera; OFI z próbek = estymata"}
    if now - book["t"] > max_age_s:
        return C.result("MICROSTRUCTURE", VERSION, values=vals, status="STALE", reason=f"BOOK_AGE_{now - book['t']:.0f}S", data_time=book["t"],
                        extra=extra, **base)
    return C.result("MICROSTRUCTURE", VERSION, values=vals, data_time=book["t"], available_at=book["t"], sample_count=v["updates"], extra=extra,
                    **base)


class BookAdapter:
    """MT5 market-depth subscription through the bridge call queue + recorder for replay. Lifecycle: ensure(symbol) subscribes (and
    releases the previous symbol), poll() reads one snapshot, close() releases. A failed subscribe = NO_DATA (no DOM for the symbol)."""

    def __init__(self, bridge, recorder=None, *, period_s: float = 1.0):
        self.bridge, self.recorder, self.period_s = bridge, recorder, period_s
        self.symbol: str | None = None
        self.status, self.reason = "NOT_SUBSCRIBED", None
        self.epoch = None
        self.last: dict | None = None
        self._lock = threading.Lock()

    def _call(self, fn):
        return self.bridge._call(fn)

    def ensure(self, symbol: str) -> None:
        with self._lock:
            ep = getattr(self.bridge, "session_epoch", None)
            if symbol == self.symbol and ep == self.epoch and self.status in ("READY", "NO_DATA"):
                return
            if self.symbol and self.symbol != symbol:
                self._release()
            self.symbol, self.epoch = symbol, ep
            try:
                ok = self._call(lambda m: m.market_book_add(symbol) if hasattr(m, "market_book_add") else False)
            except Exception as exc:  # noqa: BLE001 - terminal unavailable -> no DOM, the rest of the bot is unaffected
                ok, self.reason = False, f"{type(exc).__name__}: {exc}"[:160]
            self.status = "READY" if ok else "NO_DATA"
            if not ok:
                self.reason = self.reason or "market_book_add odrzucone – brak DOM dla symbolu"

    def _release(self) -> None:
        sym = self.symbol
        if not sym:
            return
        try:
            self._call(lambda m: m.market_book_release(sym) if hasattr(m, "market_book_release") else None)
        except Exception:  # noqa: BLE001
            pass
        self.status = "NOT_SUBSCRIBED"

    def close(self) -> None:
        with self._lock:
            self._release()
            self.symbol = None

    def poll(self) -> dict | None:
        if self.status != "READY" or not self.symbol:
            return None
        sym = self.symbol
        try:
            rows = self._call(lambda m: m.market_book_get(sym))
        except Exception as exc:  # noqa: BLE001
            self.reason = f"{type(exc).__name__}: {exc}"[:160]
            return None
        book = normalize(rows, time.time())
        if book is None:
            self.reason = "pusty arkusz (brak bid lub ask)"
            return None
        self.reason = None
        self.last = book
        if self.recorder is not None:
            self.recorder(sym, book)
        return book
