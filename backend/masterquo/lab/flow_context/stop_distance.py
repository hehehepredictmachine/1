"""MQ_STOP_DISTANCE_V1 (FF05): range_points = (High-Low)/SYMBOL_POINT (excludes the gap to the previous close - not ATR),
average over Period (SMA or EMA, FULL_SEED: undefined until P values; EMA seed = SMA of first P), suggested = average*factor, all in
POINTS. Price distance = points*point; SL price for an entry rounded OUTWARD to trade_tick_size. ADVISORY only: never moves the
strategy SL / TP1 = M5 MID, never a probability of stop safety. Calibration task NEXT_BAR_RANGE_COVERAGE (train-only quantile)."""
from __future__ import annotations

import math

from .ma import RollingMA, normalize_period

ALGO = "MQ_STOP_DISTANCE_V1"
DEFAULT = {"period": 20, "method": "SMA", "factor": 1.5}


def validate(cfg: dict | None, point) -> dict:
    c = dict(DEFAULT, **(cfg or {}))
    if c["method"] not in ("SMA", "EMA"):
        raise ValueError("METHOD_INVALID (SMA|EMA)")
    p, flag = normalize_period(c["period"])
    f = float(c["factor"])
    if not (math.isfinite(f) and f > 0):
        raise ValueError("FACTOR_INVALID")
    if point is None or not (math.isfinite(point) and point > 0):
        raise ValueError("POINT_UNKNOWN")
    return {"period": p, "method": c["method"], "factor": f, "flags": [flag] if flag else [], "seed": "FULL_SEED"}


class StopDistance:
    def __init__(self, cfg: dict | None, point: float, tick_size: float | None = None):
        self.cfg = validate(cfg, point)
        self.point, self.tick = point, tick_size or point
        self.ma = RollingMA(self.cfg["method"], self.cfg["period"], "FULL_SEED")
        self.last_id = None

    def _row(self, h, l_, commit, bar_id=None):
        if not (math.isfinite(h) and math.isfinite(l_)) or h < l_:
            raise ValueError("INVALID_HL")
        r = (h - l_) / self.point
        avg = self.ma.commit(r) if commit else self.ma.preview(r)
        if commit:
            self.last_id = bar_id
        sug = None if avg is None else avg * self.cfg["factor"]
        return {"range_points": r, "average_points": avg, "suggested_points": sug, "point": self.point, "trade_tick_size": self.tick,
                "suggested_price_distance": None if sug is None else sug * self.point, "status": "WARMUP" if avg is None else
                ("FLAT_WINDOW" if avg == 0 else "OK"), "closed": commit, "units": "points"}

    def update(self, bar: dict) -> dict | None:
        if bar["open_utc"] == self.last_id:
            return None
        return dict(self._row(float(bar["h"]), float(bar["l"]), True, bar["open_utc"]), t=bar["open_utc"])

    def preview(self, bar: dict) -> dict:
        return dict(self._row(float(bar["h"]), float(bar["l"]), False), t=bar["open_utc"])


def series(bars, cfg=None, point=0.01, tick=None) -> list:
    sd = StopDistance(cfg, point, tick)
    return [sd.update(b) for b in bars]


def sl_price(entry: float, side: str, distance_price: float, tick_size: float) -> float:
    """BUY SL = entry - distance, SELL SL = entry + distance; rounded OUTWARD (away from entry) to the legal tick grid."""
    if side not in ("BUY", "SELL") or not (tick_size > 0) or not (distance_price >= 0):
        raise ValueError("SL_INPUT_INVALID")
    raw = entry - distance_price if side == "BUY" else entry + distance_price
    k = raw / tick_size
    k = math.floor(k + 1e-9) if side == "BUY" else math.ceil(k - 1e-9)
    return round(k * tick_size, 10)


def risk_diagnostics(row: dict, strategy_sl_points: float | None, broker_stops_level_points: float | None = None) -> dict:
    """Advisory comparison for the checklist: never modifies the plan."""
    if row.get("average_points") is None:
        return {"status": "WARMUP", "advisory": True}
    out = {"advisory": True, "strategy_sl_points": strategy_sl_points, "average_points": row["average_points"], "suggested_points": row["suggested_points"],
           "broker_min_points": broker_stops_level_points, "flags": [], "note": "relacja odległości do pomiaru; nie p(stop hit), nie zmienia SL/TP1"}
    if strategy_sl_points is not None:
        if strategy_sl_points < row["average_points"]:
            out["flags"].append("BELOW_AVERAGE_RANGE")
        if strategy_sl_points < row["suggested_points"]:
            out["flags"].append("BELOW_SUGGESTED")
        if broker_stops_level_points is not None and strategy_sl_points < broker_stops_level_points:
            out["flags"].append("BELOW_BROKER_STOPS_LEVEL")
    return out


def calibrate_factor(bars: list[dict], point: float, cfg=None, coverage: float = 0.8, max_gap_s: float = 300.0) -> dict:
    """NEXT_BAR_RANGE_COVERAGE on TRAIN bars: ratio = range_next / average_current (positive average, contiguous). Quantile = factor.
    Coverage of the NEXT bar range only - not position MAE, not stop safety."""
    from datetime import datetime
    ts = lambda x: x if isinstance(x, (int, float)) else datetime.fromisoformat(str(x).replace("Z", "+00:00")).timestamp()  # noqa: E731
    rows = series(bars, cfg, point)
    ratios = []
    for i in range(len(bars) - 1):
        a = rows[i]["average_points"]
        if not a or a <= 0 or ts(bars[i + 1]["open_utc"]) - ts(bars[i]["open_utc"]) > max_gap_s:
            continue
        ratios.append(rows[i + 1]["range_points"] / a)
    if len(ratios) < 200:
        return {"status": "INSUFFICIENT_EVIDENCE", "n": len(ratios)}
    ratios.sort()
    q = ratios[min(len(ratios) - 1, int(coverage * (len(ratios) - 1)))]
    return {"status": "OK", "task": "NEXT_BAR_RANGE_COVERAGE", "n": len(ratios), "coverage_target": coverage, "factor": q,
            "note": "pokrycie zakresu NASTĘPNEJ świecy na train; nie bezpieczeństwo SL"}
