"""Liquidity heatmap of the MT5 book archive (Apollo23 CHARTS · HEATMAPA, read-only).

Source: the bot's own archive of broker market-depth snapshots (IndicatorService.book_snapshots: MT5 market_book_get polled every
indicators.book_period_s, top 20 levels per side, kept indicators.book_keep_days). For XAUUSD this is the BROKER'S quote book - not an
exchange L2 / MBO feed - and there is no executed-trade tape, so trade bubbles are NOT available (never estimated from ticks or candles).

Time grid: buckets of `seconds / cols` aligned to the epoch (bucket i = [i*step, (i+1)*step)), so a finished bucket never changes between
two requests and can be cached; only the last bucket is still filling. A bucket cell = MEAN resting size of that price row over the
snapshots inside the bucket (a level missing from a snapshot counts as 0 for that snapshot). A bucket without snapshots is omitted - the
chart shows a gap, never zeros. Best bid / ask of a bucket = its LAST snapshot.
"""
from __future__ import annotations

import math
import threading
from collections import defaultdict

from .analytics import row_of

VERSION = "PMW-DEPTH-HIST-1"
TRADES = {"status": "NOT_AVAILABLE", "reason": "arkusz kwotowań brokera (OTC) – brak taśmy transakcji; strona agresora MT5 niezweryfikowana"}


def auto_row(bids, asks, tick: float | None = None) -> float:
    """Price row = the smallest positive gap between neighbouring levels of one side (the broker's level spacing), never below the tick."""
    gaps = []
    for side in (bids or [], asks or []):
        ps = sorted({float(p) for p, _ in side})
        gaps += [round(b - a, 10) for a, b in zip(ps, ps[1:]) if b - a > 0]
    tick = float(tick or 0) or None
    row = min(gaps) if gaps else (tick or 0.01)
    if tick:
        row = max(row, tick)
    return float(f"{row:.6g}")


def grid(now: float, seconds: float, cols: int) -> tuple[float, float, float]:
    """Epoch-aligned window that ends with the bucket containing `now`: (t0, t1, step)."""
    step = seconds / cols
    t1 = (math.floor(now / step) + 1) * step
    return t1 - cols * step, t1, step


def columns(snaps, t0: float, t1: float, cols: int, row: float) -> list[dict]:
    """snaps: [(t, bids [[p, q]], asks [[p, q]])] -> [{t, t1, n, bid, ask, cells: [[row_price, mean_size]]}] for non-empty buckets."""
    if row <= 0 or cols <= 0 or t1 <= t0:
        raise ValueError("ROW_OR_WINDOW")
    w = (t1 - t0) / cols
    acc: dict[int, dict] = {}
    for t, bids, asks in sorted(snaps, key=lambda s: s[0]):
        if t < t0 or t >= t1:
            continue
        i = min(cols - 1, int((t - t0) // w))
        b = acc.setdefault(i, {"n": 0, "sum": defaultdict(float), "bid": None, "ask": None})
        b["n"] += 1
        for p, q in list(bids or []) + list(asks or []):
            if float(q) > 0:
                b["sum"][row_of(float(p), row)] += float(q)
        if bids:
            b["bid"] = max(float(p) for p, _ in bids)
        if asks:
            b["ask"] = min(float(p) for p, _ in asks)
    out = []
    for i in sorted(acc):
        b = acc[i]
        out.append({"t": round(t0 + i * w, 3), "t1": round(t0 + (i + 1) * w, 3), "n": b["n"], "bid": b["bid"], "ask": b["ask"],
                    "cells": [[p, round(s / b["n"], 6)] for p, s in sorted(b["sum"].items())]})
    return out


class ColumnCache:
    """Finished buckets per (symbol, step, row) - a poll reads only the snapshots of buckets it has not seen finished."""

    def __init__(self, max_keys: int = 8):
        self._d: dict[tuple, dict[int, dict | None]] = {}
        self._lock = threading.Lock()
        self.max_keys = max_keys
        self.reads = 0

    def build(self, key: tuple, t0: float, step: float, cols: int, row: float, fetch, finished_before: float) -> list[dict]:
        """fetch(a, b) -> snapshots in [a, b]; buckets ending at or before `finished_before` are cached (empty ones too, as gaps)."""
        i0 = round(t0 / step)
        with self._lock:
            if key not in self._d and len(self._d) >= self.max_keys:
                self._d.pop(next(iter(self._d)))
            have = self._d.setdefault(key, {})
            for i in [i for i in have if i < i0]:
                del have[i]
            missing = [i for i in range(i0, i0 + cols) if i not in have]
        live: dict[int, dict] = {}
        if missing:
            a = missing[0]
            snaps = fetch(a * step, (i0 + cols) * step)
            self.reads += 1
            got = {round(c["t"] / step): c for c in columns(snaps, a * step, (i0 + cols) * step, i0 + cols - a, row)}
            with self._lock:
                for i in range(a, i0 + cols):
                    if (i + 1) * step <= finished_before:
                        have[i] = got.get(i)
                    elif i in got:
                        live[i] = got[i]
        with self._lock:
            return [c for i in range(i0, i0 + cols) for c in [have.get(i) or live.get(i)] if c]


def heatmap(cols_out: list[dict], *, t0: float, t1: float, cols: int, row: float, ref: dict | None = None, book: dict | None = None,
            period_s: float = 1.0, levels: int = 20, now: float | None = None, max_age_s: float = 5.0, bars: list[dict] | None = None,
            symbol: str | None = None) -> dict:
    """Response of GET /api/v1/orderflow/mt5/heatmap (pure: the route collects the inputs). ref = the latest book {t, bids, asks}."""
    now = now if now is not None else t1
    dom_out = None
    if ref:
        age = round(now - float(ref["t"]), 3)
        dom_out = {"t": ref["t"], "age_s": age, "bids": [[float(p), float(q)] for p, q in ref["bids"]][:levels],
                   "asks": [[float(p), float(q)] for p, q in ref["asks"]][:levels], "fresh": age <= max_age_s}
    book = book or {}
    if cols_out:
        status = "READY" if dom_out and dom_out["fresh"] else "STALE"
        reason = None if status == "READY" else f"BOOK_AGE_{dom_out['age_s']:.0f}S" if dom_out else "BRAK_BIEŻĄCEGO_ARKUSZA"
    else:
        status = "NO_DATA"
        reason = book.get("reason") or ("Brak zapisanych snapshotów arkusza w tym oknie (indicators.book_record)" if book.get("status") == "READY"
                                        else "Brak danych arkusza – symbol bez DOM u brokera albo arkusz wyłączony")
    return {"version": VERSION, "status": status, "reason": reason, "symbol": symbol, "t0": t0, "t1": t1, "now": now, "cols": cols,
            "step_s": round((t1 - t0) / cols, 6), "row_size": row, "columns": cols_out, "snapshots": sum(c["n"] for c in cols_out), "dom": dom_out,
            "book": {"status": book.get("status"), "reason": book.get("reason")}, "bars": bars or [], "trades": dict(TRADES),
            "source": "MT5_MARKET_BOOK(broker) · archiwum book_snapshots",
            "quality": f"SAMPLED({period_s:g}s) · top-{levels} poziomów · arkusz kwotowań brokera, nie giełdowy L2 / MBO",
            "aggregation": "komórka = średnia płynność oczekująca wiersza ceny w kubełku czasu; kubełek bez snapshotów = przerwa (nie zero)",
            "mode": "READ_ONLY"}
