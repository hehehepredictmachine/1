"""Model1 heatmap contract (CoinGlass API v4 'liquidation/heatmap/model1' and 'liquidation/aggregated-heatmap/model1').

Documented shape (data): y_axis = price levels, liquidation_leverage_data = sparse triplets [time_index, price_index, intensity],
price_candlesticks = [[time, open, high, low, close, volume], ...]. The time axis is the candlestick list (index -> its time);
without it the time index is NOT mapped to an assumed equal step (TIME_AXIS_UNVERIFIED). Validation rejects: non-finite / non
increasing prices, bad indices, duplicate cells, negative / NaN / Inf intensity, unknown time unit, too many cells.
A missing sparse cell is UNKNOWN (the provider's zero semantics is not confirmed) - never 0. Intensity unit: provider_intensity
(no "$" assumed). data_kind is explicit: ESTIMATED_LIQUIDATION_LEVELS for model1.
"""
from __future__ import annotations

import hashlib
import json
import math

SCHEMA = "PMW-LIQ-HEATMAP-1"
PARSER_VERSION = "PMW-LIQ-PARSER-1.0.0"
MAX_CELLS = 400_000
MAX_BYTES = 10 * 1024 * 1024
ZONE_QUANTILE = 0.85
MAX_ZONES = 15


class HeatmapError(ValueError):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _time_s(v) -> float:
    if not _finite(v):
        raise HeatmapError("UNSUPPORTED_SCHEMA", "czas świecy nie jest liczbą")
    if v > 1e14:
        raise HeatmapError("TIME_AXIS_UNVERIFIED", f"nieznana jednostka czasu {v}")
    return float(v) / 1000.0 if v > 1e11 else float(v)            # milliseconds -> seconds; seconds kept


def parse_model1(body: dict, *, max_cells: int = MAX_CELLS) -> dict:
    """body: the provider 'data' object. Returns the validated grid (prices, times, cells) or raises HeatmapError."""
    if not isinstance(body, dict):
        raise HeatmapError("UNSUPPORTED_SCHEMA", "data nie jest obiektem")
    ya, cells, cs = body.get("y_axis"), body.get("liquidation_leverage_data"), body.get("price_candlesticks")
    if not isinstance(ya, list) or not ya:
        raise HeatmapError("EMPTY" if ya == [] else "UNSUPPORTED_SCHEMA", "brak y_axis")
    if not all(_finite(p) for p in ya):
        raise HeatmapError("UNSUPPORTED_SCHEMA", "y_axis zawiera wartości nieliczbowe / NaN / Inf")
    prices = [float(p) for p in ya]
    if any(b <= a for a, b in zip(prices, prices[1:])):
        raise HeatmapError("UNSUPPORTED_SCHEMA", "y_axis nie jest ściśle rosnąca")
    if not isinstance(cells, list):
        raise HeatmapError("UNSUPPORTED_SCHEMA", "brak liquidation_leverage_data")
    if len(cells) > max_cells:
        raise HeatmapError("TOO_LARGE", f"{len(cells)} komórek > limit {max_cells}")
    times, time_status = None, "TIME_AXIS_UNVERIFIED"
    if isinstance(cs, list) and cs:
        if not all(isinstance(r, list) and r for r in cs):
            raise HeatmapError("UNSUPPORTED_SCHEMA", "price_candlesticks: zły wiersz")
        times = [_time_s(r[0]) for r in cs]
        if any(b <= a for a, b in zip(times, times[1:])):
            raise HeatmapError("TIME_AXIS_UNVERIFIED", "czasy świec nie są ściśle rosnące")
        time_status = "OK"
    seen, out = set(), []
    max_ti = -1
    for c in cells:
        if not isinstance(c, list) or len(c) != 3:
            raise HeatmapError("UNSUPPORTED_SCHEMA", "komórka nie jest trójką [t, p, v]")
        ti, pi, v = c
        if not (isinstance(ti, int) and isinstance(pi, int)) or isinstance(ti, bool) or isinstance(pi, bool):
            raise HeatmapError("UNSUPPORTED_SCHEMA", "indeks nie jest liczbą całkowitą")
        if not _finite(v) or v < 0:
            raise HeatmapError("INVALID_INTENSITY", f"intensywność {v}")
        if pi < 0 or pi >= len(prices) or ti < 0:
            raise HeatmapError("INDEX_OUT_OF_RANGE", f"[{ti}, {pi}]")
        if times is not None and ti >= len(times):
            raise HeatmapError("INDEX_OUT_OF_RANGE", f"indeks czasu {ti} >= {len(times)} świec")
        if (ti, pi) in seen:
            raise HeatmapError("DUPLICATE_CELL", f"[{ti}, {pi}]")
        seen.add((ti, pi))
        max_ti = max(max_ti, ti)
        out.append((ti, pi, float(v)))
    return {"schema": SCHEMA, "parser_version": PARSER_VERSION, "data_kind": "ESTIMATED_LIQUIDATION_LEVELS", "prices": prices, "times": times,
            "time_axis_status": time_status, "cells": out, "n_time": (len(times) if times is not None else max_ti + 1), "intensity_unit": "provider_intensity",
            "missing_cell_semantics": "UNKNOWN (zero niepotwierdzone przez dostawcę)", "price_edges": price_edges(prices)}


def price_edges(prices: list[float]) -> list[float]:
    """Bucket edges: midpoints between neighbouring levels; the outer edges mirror the first / last half-step (explicit rule)."""
    if len(prices) == 1:
        return [prices[0], prices[0]]
    mids = [(a + b) / 2 for a, b in zip(prices, prices[1:])]
    return [prices[0] - (mids[0] - prices[0])] + mids + [prices[-1] + (prices[-1] - mids[-1])]


def payload_hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def zones(grid: dict, q: float = ZONE_QUANTILE, max_zones: int = MAX_ZONES) -> dict:
    """Up to `max_zones` contiguous price ranges of the LATEST cross-section whose intensity >= the q-quantile of its positive values.
    No additivity assumed (max / median only). Constant or empty section -> no discriminating ranking (no artificial zone)."""
    if grid["time_axis_status"] != "OK":
        return {"status": "TIME_AXIS_UNVERIFIED", "zones": [], "reason": "bez osi czasu nie da się jednoznacznie wskazać bieżącego przekroju"}
    if not grid["cells"]:
        return {"status": "NO_CELLS", "zones": []}
    t_last = max(c[0] for c in grid["cells"])
    sec = {pi: v for ti, pi, v in grid["cells"] if ti == t_last}
    pos = sorted(v for v in sec.values() if v > 0)
    if not pos or pos[0] == pos[-1]:
        return {"status": "NO_DISCRIMINATING_RANK", "zones": [], "section_time": grid["times"][t_last] if grid["times"] else None}
    k = (len(pos) - 1) * q
    thr = pos[int(math.floor(k))] + (pos[int(math.ceil(k))] - pos[int(math.floor(k))]) * (k - math.floor(k))
    qual = sorted(pi for pi, v in sec.items() if v >= thr and v > 0)
    groups, cur = [], []
    for pi in qual:
        if cur and pi != cur[-1] + 1:
            groups.append(cur)
            cur = []
        cur.append(pi)
    if cur:
        groups.append(cur)
    e = grid["price_edges"]
    zs = []
    for g in groups:
        vals = sorted(sec[i] for i in g)
        zs.append({"low": e[g[0]], "high": e[g[-1] + 1], "price_index_from": g[0], "price_index_to": g[-1], "max_intensity": vals[-1],
                   "median_intensity": vals[len(vals) // 2] if len(vals) % 2 else (vals[len(vals) // 2 - 1] + vals[len(vals) // 2]) / 2})
    zs.sort(key=lambda z: -z["max_intensity"])
    zs = zs[:max_zones]
    top = zs[0]["max_intensity"] if zs else 1.0
    for i, z in enumerate(zs):
        z.update(rank=i + 1, relative=z["max_intensity"] / top)
    return {"status": "OK", "zones": zs, "threshold": thr, "quantile": q, "section_time": grid["times"][t_last], "section_index": t_last,
            "method": f"kwantyl {q} dodatnich intensywności ostatniego przekroju + łączenie sąsiednich koszyków (RESEARCH, nie prawdopodobieństwo)"}
