"""Super Candles Intelligence Engine (SCI-1.0.0) - our own, explicitly defined candle engine on CLOSED OHLC bars.

It is NOT an imitation of any external product with a similar name. Two strictly separated layers:
  1. deterministic READING (geometry + named families), built on MQ-CANDLE-1.0.0 (analysis/candles.py) plus the
     families of the scalp specification below;
  2. STATISTICS of a pattern's outcome (`PatternStats`) - causal: a sample at time t only uses earlier cases whose
     outcome was already known before t, with a minimum sample, a Wilson interval and shrinkage to the baseline.
No pattern carries a fixed "success %"; the reading never is a probability of a winning trade.

Geometry per bar: R=H-L, B=|C-O|, upper, lower, CLV=(C-L)/R, body_ratio=B/R, R/ATR, gap=O-C_prev, position in the
frozen range (0=L, 1=H) and tick-volume activity tv / median(tv of the previous 20 closed bars, current excluded).
R=0 -> ZERO_RANGE (no division, no signal).

Spec families (hypotheses, LONG form, SHORT mirrored):
  REJECTION_BULL   lower/R >= 0.50, lower >= 2B, CLV >= 0.70, B/R <= 0.45 (pin / hammer / rejection family).
  ENGULFING_BULL   previous body bearish, current bullish, body engulfs previous body (O<=C_prev+tol, C>=O_prev),
                   strong close (CLV >= 0.6); IMPULSE quality separately: B/R >= 0.50 and R/ATR >= 0.8.
  DISPLACEMENT     B/R >= 0.70 and R/ATR >= 1.0, close in the outer 25% (marubozu-like); not "institutional liquidity".
  HARAMI           current body inside the previous body, previous body >= 0.6 ATR, opposite colour -> WAIT family.
  DOJI / INSIDE    neutral -> WAIT, never a direction.
Rejection (small body) and displacement (large body) are different families and never required together.
Several names of one family on the same bar are ONE evidence (strongest score); families are reported separately.
"""
from __future__ import annotations

import math

from ..analysis import candles as mq
from .indicators import median

VERSION = "SCI-1.0.0"

FAMILY = {"REJECTION": "REJECTION", "PIN_BAR": "REJECTION", "HAMMER": "REJECTION", "SHOOTING_STAR": "REJECTION",
          "ENGULFING": "ENGULFING", "MARUBOZU": "DISPLACEMENT", "DISPLACEMENT": "DISPLACEMENT", "OUTSIDE_BAR": "OUTSIDE",
          "INSIDE_BAR": "COMPRESSION", "HARAMI": "COMPRESSION", "DOJI": "NEUTRAL", "LONG_LEGGED_DOJI": "NEUTRAL",
          "TWEEZER": "TWEEZER", "MORNING_STAR": "STAR", "EVENING_STAR": "STAR", "THREE_WHITE_SOLDIERS": "THREE", "THREE_BLACK_CROWS": "THREE",
          "INSIDE_BAR_BREAK": "BREAK"}
CONFIRMATION_FAMILIES = ("REJECTION", "ENGULFING", "DISPLACEMENT")


def family_of(name: str) -> str:
    for k in sorted(FAMILY, key=len, reverse=True):
        if name.startswith(k):
            return FAMILY[k]
    return "OTHER"


def geometry(o, h, lo, c, i: int, atr: float | None, tv=None, rng: tuple | None = None) -> dict:
    R = h[i] - lo[i]
    if R <= 0:
        return {"zero_range": True, "reason": "ZERO_RANGE", "R": 0.0}
    B = abs(c[i] - o[i])
    g = {"zero_range": False, "R": R, "B": B, "upper": h[i] - max(o[i], c[i]), "lower": min(o[i], c[i]) - lo[i],
         "clv": (c[i] - lo[i]) / R, "body_ratio": B / R, "r_atr": (R / atr) if atr else None,
         "gap": (o[i] - c[i - 1]) if i > 0 else None, "bull": c[i] > o[i], "bear": c[i] < o[i]}
    if rng:
        L, H = rng
        g["range_pos"] = (c[i] - L) / (H - L) if H > L else None
    g["tv_ratio"] = tv_ratio(tv, i) if tv is not None else None
    return g


def tv_ratio(tv, i: int, n: int = 20) -> float | None:
    """tv_i / median(tv of the previous n CLOSED bars); current bar excluded. Missing / zero denominator -> None (UNKNOWN)."""
    if tv is None or i < n or tv[i] is None:
        return None
    m = median([x for x in tv[i - n:i] if x is not None])
    return None if not m else tv[i] / m


def spec_families(o, h, lo, c, i: int, atr: float | None) -> list[dict]:
    out: list[dict] = []
    g = geometry(o, h, lo, c, i, atr)
    if g["zero_range"]:
        return [{"name": "ZERO_RANGE", "family": "NEUTRAL", "direction": "NEUTRAL", "score": 0.0, "reason": "ZERO_RANGE"}]
    R, B = g["R"], g["B"]
    if g["lower"] / R >= 0.5 and g["lower"] >= 2 * B and g["clv"] >= 0.7 and B / R <= 0.45:
        out.append({"name": "REJECTION_BULL", "family": "REJECTION", "direction": "LONG", "score": min(1.0, g["lower"] / R)})
    if g["upper"] / R >= 0.5 and g["upper"] >= 2 * B and g["clv"] <= 0.3 and B / R <= 0.45:
        out.append({"name": "REJECTION_BEAR", "family": "REJECTION", "direction": "SHORT", "score": min(1.0, g["upper"] / R)})
    if i >= 1 and atr:
        po, pc = o[i - 1], c[i - 1]
        tol = 0.05 * atr
        impulse = B / R >= 0.5 and R / atr >= 0.8
        if pc < po and c[i] > o[i] and o[i] <= pc + tol and c[i] >= po and B >= abs(pc - po) and g["clv"] >= 0.6:
            out.append({"name": "ENGULFING_BULL", "family": "ENGULFING", "direction": "LONG", "score": 0.8 if impulse else 0.5, "impulse_quality": impulse})
        if pc > po and c[i] < o[i] and o[i] >= pc - tol and c[i] <= po and B >= abs(pc - po) and g["clv"] <= 0.4:
            out.append({"name": "ENGULFING_BEAR", "family": "ENGULFING", "direction": "SHORT", "score": 0.8 if impulse else 0.5, "impulse_quality": impulse})
        if abs(pc - po) >= 0.6 * atr and max(o[i], c[i]) <= max(po, pc) and min(o[i], c[i]) >= min(po, pc) and B < abs(pc - po) and \
           ((pc > po) != (c[i] > o[i])) and c[i] != o[i]:
            out.append({"name": "HARAMI", "family": "COMPRESSION", "direction": "NEUTRAL", "score": 0.4})
    if atr and B / R >= 0.7 and R / atr >= 1.0:
        if g["bull"] and g["clv"] >= 0.75:
            out.append({"name": "DISPLACEMENT_BULL", "family": "DISPLACEMENT", "direction": "LONG", "score": min(1.0, 0.5 + 0.25 * R / atr)})
        if g["bear"] and g["clv"] <= 0.25:
            out.append({"name": "DISPLACEMENT_BEAR", "family": "DISPLACEMENT", "direction": "SHORT", "score": min(1.0, 0.5 + 0.25 * R / atr)})
    return out


def read_bar(o, h, lo, c, t, i: int, atr: float | None, tf: str, avail: str | None, tv=None, rng: tuple | None = None) -> dict:
    """Full reading of the closed bar i: geometry, named patterns (MQ-CANDLE + spec), one evidence per (family, direction)."""
    g = geometry(o, h, lo, c, i, atr, tv, rng)
    names: list[dict] = []
    if not g["zero_range"]:
        for p in mq.detect_at(o, h, lo, c, t, i, atr, tf, avail):
            d = p["direction"] if p["direction"] in ("LONG", "SHORT") else "NEUTRAL"
            names.append({"name": p["type"], "family": family_of(p["type"]), "direction": d, "score": p["score"], "source": mq.VERSION})
    names += [dict(x, source=VERSION) for x in spec_families(o, h, lo, c, i, atr)]
    ev: dict[tuple, dict] = {}
    for n in names:
        k = (n["family"], n["direction"])
        e = ev.setdefault(k, {"family": n["family"], "direction": n["direction"], "members": [], "score": 0.0})
        e["members"].append(n["name"])
        e["score"] = max(e["score"], n["score"])
    evidence = list(ev.values())
    dirs = {e["direction"] for e in evidence if e["family"] in CONFIRMATION_FAMILIES}
    verdict = "WAIT" if not dirs or len(dirs) > 1 else ("CONFIRM_LONG" if "LONG" in dirs else "CONFIRM_SHORT")
    return {"version": VERSION, "tf": tf, "time": t[i] if t is not None else None, "available_at": avail, "geometry": _round(g),
            "patterns": names, "evidence": evidence, "verdict": verdict,
            "conflict": len(dirs) > 1, "note": "odczyt geometrii – nie jest prawdopodobieństwem wygranej transakcji"}


def confirmation(reading: dict, direction: str) -> dict | None:
    """Strongest confirmation evidence in `direction` from the rejection / engulfing / displacement families (one per family)."""
    best = None
    for e in reading.get("evidence", []):
        if e["direction"] == direction and e["family"] in CONFIRMATION_FAMILIES and (best is None or e["score"] > best["score"]):
            best = e
    return best


def _round(g: dict) -> dict:
    return {k: (round(v, 5) if isinstance(v, float) else v) for k, v in g.items()}


class PatternStats:
    """Causal outcome statistics per pattern family+direction.

    add(key, outcome_known_at, success) records a case; estimate(key, t) uses ONLY cases with outcome_known_at < t.
    Estimate = (k + m*p0) / (n + m) (shrinkage to the baseline p0 with prior weight m), Wilson 95% interval on raw k/n;
    n < min_n -> status INSUFFICIENT_SAMPLE (the estimate is still the baseline)."""

    def __init__(self, baseline: float = 0.5, prior_weight: float = 20.0, min_n: int = 30):
        self.p0, self.m, self.min_n = baseline, prior_weight, min_n
        self.cases: dict[str, list[tuple[str, bool]]] = {}

    def add(self, key: str, outcome_known_at: str, success: bool) -> None:
        self.cases.setdefault(key, []).append((outcome_known_at, bool(success)))

    def estimate(self, key: str, t: str) -> dict:
        past = [s for (ka, s) in self.cases.get(key, []) if ka < t]
        n, k = len(past), sum(past)
        est = (k + self.m * self.p0) / (n + self.m)
        lo = hi = None
        if n:
            z, p = 1.96, k / n
            den = 1 + z * z / n
            ctr = (p + z * z / (2 * n)) / den
            half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
            lo, hi = round(ctr - half, 4), round(ctr + half, 4)
        return {"n": n, "k": k, "shrunk": round(est, 4), "wilson95": [lo, hi], "baseline": self.p0,
                "status": "OK" if n >= self.min_n else "INSUFFICIENT_SAMPLE"}
