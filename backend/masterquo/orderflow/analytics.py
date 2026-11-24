"""Trade-based Volume Profile (TASK 001), Footprint (TASK 004) and Depth engine / Bookmap workspace data (TASK 002).

All consume the canonical TradeLedger (executed price x size). Never inferred from candle ranges, tick counts, quotes, DOM sizes or pixels.
Directional values (buy / sell / delta / CVD / imbalance) exist only for classified aggressor volume; with unverified side semantics they are
None and the profile / footprint shows neutral total volume only. Pattern names (absorption, exhaustion, ...) are labelled HEURISTIC.
Depth (resting liquidity) is a separate domain and is never counted as traded volume.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, ROUND_FLOOR

VP_VERSION = "PMW-VP-TRADES-1"
FP_VERSION = "PMW-FOOTPRINT-1"
IMBALANCE_VERSION = "PMW-IMB-DIAG-1"     # ask[p] vs bid[p - row] (buy), bid[p] vs ask[p + row] (sell); ratio, min volume, zero-denominator rule


def row_of(price: float, row: float) -> float:
    """Deterministic price row (floor to the row grid) using Decimal to avoid float drift."""
    r = Decimal(str(row))
    return float((Decimal(str(price)) / r).to_integral_value(rounding=ROUND_FLOOR) * r)


def auto_row(px: float | None) -> float:
    """Default price-row height of the order-flow workspace (and its export): 0.05 % of the price, 2 significant digits; 0.01 when the
    price is unknown or the rounding gives 0."""
    if not px or px <= 0:
        return 0.01
    return float(f"{px * 0.0005:.2g}") or 0.01


def _directional(events) -> bool:
    return any(e.aggressor != "UNKNOWN" for e in events)


def volume_profile(events, row: float, value_area: float = 0.70) -> dict:
    if row <= 0:
        raise ValueError("ROW_SIZE")
    rows: dict[float, dict] = defaultdict(lambda: {"total": 0.0, "buy": 0.0, "sell": 0.0, "unknown": 0.0, "trades": 0})
    for e in events:
        r = rows[row_of(e.price, row)]
        r["total"] += e.size
        r["trades"] += 1
        r[{"BUY": "buy", "SELL": "sell"}.get(e.aggressor, "unknown")] += e.size
    if not rows:
        return {"status": "NO_DATA", "rows": [], "version": VP_VERSION}
    prices = sorted(rows)
    total = sum(rows[p]["total"] for p in prices)
    poc = max(prices, key=lambda p: (rows[p]["total"], -p))          # tie -> lower price (deterministic)
    i = prices.index(poc)
    lo = hi = i
    acc = rows[poc]["total"]
    while acc < value_area * total - 1e-12 and (lo > 0 or hi < len(prices) - 1):
        up = rows[prices[hi + 1]]["total"] if hi < len(prices) - 1 else -1.0
        dn = rows[prices[lo - 1]]["total"] if lo > 0 else -1.0
        if up >= dn:                                                  # tie -> upper row first
            hi += 1
            acc += up
        else:
            lo -= 1
            acc += dn
    directional = _directional(events)
    out_rows = [{"price": p, **{k: round(v, 12) if isinstance(v, float) else v for k, v in rows[p].items()},
                 "delta": round(rows[p]["buy"] - rows[p]["sell"], 12) if directional else None} for p in prices]
    return {"status": "READY", "version": VP_VERSION, "row_size": row, "total_volume": round(total, 12), "poc": poc,
            "vah": prices[hi] + row, "val": prices[lo], "value_area_pct": value_area, "value_area_volume": round(acc, 12),
            "directional": directional, "delta": round(sum(r["buy"] - r["sell"] for r in rows.values()), 12) if directional else None,
            "unknown_volume": round(sum(r["unknown"] for r in rows.values()), 12), "rows": out_rows,
            "convention": "VA: start POC, dodawaj większy sąsiedni wiersz (remis = wyżej) do 70%; POC remis = niższa cena; VAH = górna krawędź wiersza",
            "source": "EXECUTED_TRADES"}


def cvd(events) -> list[dict]:
    if not _directional(events):
        return []
    s, out = 0.0, []
    for e in events:
        if e.aggressor != "UNKNOWN":
            s += e.size if e.aggressor == "BUY" else -e.size
        out.append({"ts": e.ts, "cvd": round(s, 12)})
    return out


def footprint(events, tf_seconds: int, row: float, *, ratio: float = 3.0, min_volume: float = 0.0, stacked: int = 3) -> dict:
    """Per bar x price row: A (buyer aggressor), B (seller aggressor), U (unknown), V = A + B + U, delta = A - B (classified only), trades."""
    bars: dict[int, dict[float, dict]] = defaultdict(lambda: defaultdict(lambda: {"A": 0.0, "B": 0.0, "U": 0.0, "V": 0.0, "trades": 0}))
    for e in events:
        t0 = int(e.ts // tf_seconds * tf_seconds)
        c = bars[t0][row_of(e.price, row)]
        c[{"BUY": "A", "SELL": "B"}.get(e.aggressor, "U")] += e.size
        c["V"] += e.size
        c["trades"] += 1
    directional = _directional(events)
    out = []
    for t0 in sorted(bars):
        cells = bars[t0]
        ps = sorted(cells)
        poc = max(ps, key=lambda p: (cells[p]["V"], -p))
        rows = []
        for p in ps:
            c = cells[p]
            rows.append({"price": p, "A": round(c["A"], 12) if directional else None, "B": round(c["B"], 12) if directional else None,
                         "U": round(c["U"], 12), "V": round(c["V"], 12), "delta": round(c["A"] - c["B"], 12) if directional else None,
                         "trades": c["trades"], "imbalance": None})
        if directional:
            idx = {r["price"]: r for r in rows}
            for r in rows:
                below = idx.get(round(r["price"] - row, 12)) or idx.get(row_of(r["price"] - row / 2, row))
                above = idx.get(round(r["price"] + row, 12)) or idx.get(row_of(r["price"] + row * 1.5, row))
                bid_below = below["B"] if below else 0.0
                ask_above = above["A"] if above else 0.0
                if r["A"] >= max(min_volume, 1e-15) and (bid_below == 0 or r["A"] / bid_below >= ratio):
                    r["imbalance"] = "BUY"
                elif r["B"] >= max(min_volume, 1e-15) and (ask_above == 0 or r["B"] / ask_above >= ratio):
                    r["imbalance"] = "SELL"
            stacks = []
            for side in ("BUY", "SELL"):
                run = []
                for r in rows:
                    adjacent = bool(run) and abs(r["price"] - run[-1] - row) <= row * 1e-6
                    if r["imbalance"] == side and (not run or adjacent):
                        run.append(r["price"])
                    elif r["imbalance"] == side:                         # same side but a price gap -> a new run
                        if len(run) >= stacked:
                            stacks.append({"side": side, "from": run[0], "to": run[-1], "rows": len(run)})
                        run = [r["price"]]
                    else:
                        if len(run) >= stacked:
                            stacks.append({"side": side, "from": run[0], "to": run[-1], "rows": len(run)})
                        run = []
                if len(run) >= stacked:
                    stacks.append({"side": side, "from": run[0], "to": run[-1], "rows": len(run)})
        else:
            stacks = []
        tot = sum(c["V"] for c in cells.values())
        out.append({"t": t0, "rows": rows, "poc": poc, "volume": round(tot, 12),
                    "delta": round(sum(c["A"] - c["B"] for c in cells.values()), 12) if directional else None,
                    "stacked_imbalances": stacks, "labels": "HEURISTIC" if stacks else None})
    return {"version": FP_VERSION, "imbalance_version": IMBALANCE_VERSION, "tf_seconds": tf_seconds, "row_size": row, "directional": directional,
            "imbalance_rule": {"ratio": ratio, "min_volume": min_volume, "stacked": stacked,
                               "zero_denominator": "licznik ≥ min_volume i mianownik 0 => imbalance", "tie": "BUY sprawdzany przed SELL"},
            "bars": out, "status": "READY" if out else "NO_DATA",
            "mode": None if directional else "NEUTRAL_TOTAL_ONLY (strona agresora niezweryfikowana)"}


# ---------------------------------------------------------------- depth (resting liquidity) - TASK 002
class OrderBook:
    """Snapshot + sequenced deltas. A sequence gap marks the book RESYNC_REQUIRED (no silent continuation)."""

    def __init__(self):
        self.bids: dict[float, float] = {}
        self.asks: dict[float, float] = {}
        self.seq: int | None = None
        self.state = "EMPTY"

    def snapshot(self, bids, asks, seq: int | None = None):
        self.bids = {float(p): float(s) for p, s in bids if float(s) > 0}
        self.asks = {float(p): float(s) for p, s in asks if float(s) > 0}
        self.seq = seq
        self.state = "SYNCED"

    def delta(self, side: str, price: float, size: float, seq: int | None = None) -> str:
        if self.state != "SYNCED":
            return "IGNORED_NOT_SYNCED"
        if seq is not None and self.seq is not None and seq != self.seq + 1:
            self.state = "RESYNC_REQUIRED"
            return "GAP"
        book = self.bids if side == "BID" else self.asks
        if size <= 0:
            book.pop(float(price), None)
        else:
            book[float(price)] = float(size)
        if seq is not None:
            self.seq = seq
        return "APPLIED"

    def dom(self, depth: int = 20) -> dict:
        b = sorted(self.bids.items(), reverse=True)[:depth]
        a = sorted(self.asks.items())[:depth]
        crossed = bool(b and a and b[0][0] >= a[0][0])
        return {"state": "CROSSED" if crossed else self.state, "bids": b, "asks": a, "seq": self.seq,
                "note": "płynność oczekująca (resting) – nie jest wolumenem transakcji"}


def heatmap(snapshots: list[dict], row: float) -> dict:
    """snapshots: [{t, bids:[[p,s]], asks:[[p,s]]}] -> {t -> {row: resting size}}; flagged DEGRADED when the feed is polled top-N."""
    cols = []
    for s in sorted(snapshots, key=lambda x: x["t"]):
        cells: dict[float, float] = defaultdict(float)
        for p, sz in list(s.get("bids") or []) + list(s.get("asks") or []):
            cells[row_of(float(p), row)] += float(sz)
        cols.append({"t": s["t"], "cells": dict(sorted(cells.items()))})
    return {"columns": cols, "row_size": row, "quality": "DEGRADED (snapshoty odpytywane, top-N; brak pełnej historii L2/MBO)"}


# 1.46: the unused is_finite_profile() (and the math import) was removed - dead code, no caller
def bubbles(events, min_size: float = 0.0) -> list[dict]:
    return [{"ts": e.ts, "price": e.price, "size": e.size, "aggressor": e.aggressor} for e in events if e.size >= min_size]

