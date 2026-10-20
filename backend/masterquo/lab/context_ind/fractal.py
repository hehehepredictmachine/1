"""PWM_KATZ_BOUNDED_v1 (VS05): window of N prices (n = N-1 segments), L = sum |p_j - p_{j-1}|, d = max |p_j - p_0| (not the endpoint),
den = log(n) + log(d/L); raw = log(n)/den when den > eps. Bounded policy: flat (L or d ~ 0) -> null + NO_MOTION; den <= eps or non-finite
raw -> fd_raw null, fd_bounded 2 (CONSERVATIVE_CHOP_SATURATION, flagged); otherwise clip(raw, 1, 2) with a clipped flag. EMA(S) over bounded
values, seed = mean of first S valid, warm-up N+S-1; a flat/invalid sample resets the smoothing segment. Zones on the unrounded smoothed
value: <= 1.40 TREND (no direction), >= 1.65 CHOP, else NEUTRAL."""
from __future__ import annotations

import math
from collections import deque

PROFILE = "PWM_KATZ_BOUNDED_v1"
DEFAULT = {"N": 30, "S": 5, "trend": 1.40, "chop": 1.65, "price": "CLOSE", "tol_ticks": 0.5}
PRICES = {"CLOSE": lambda b: b["c"], "OPEN": lambda b: b["o"], "HIGH": lambda b: b["h"], "LOW": lambda b: b["l"],
          "MEDIAN": lambda b: (b["h"] + b["l"]) / 2, "TYPICAL": lambda b: (b["h"] + b["l"] + b["c"]) / 3,
          "WEIGHTED": lambda b: (b["h"] + b["l"] + 2 * b["c"]) / 4}


def validate(cfg: dict | None) -> dict:
    c = dict(DEFAULT, **(cfg or {}))
    if not (int(c["N"]) >= 3 and int(c["S"]) >= 1 and 1 <= c["trend"] < c["chop"] <= 2 and c["price"] in PRICES):
        raise ValueError("FD_CONFIG_INVALID")
    return dict(c, N=int(c["N"]), S=int(c["S"]))


def katz(prices: list[float], tol: float = 1e-12, eps: float = 1e-12) -> dict:
    n = len(prices) - 1
    if n < 2:
        return {"status": "WARMING_UP", "fd_raw": None, "fd_bounded": None}
    L = sum(abs(prices[j] - prices[j - 1]) for j in range(1, len(prices)))
    d = max(abs(p - prices[0]) for p in prices)
    base = {"L": L, "d": d, "n": n}
    if L <= tol or d <= tol:
        return dict(base, status="FLAT_NO_MOTION", fd_raw=None, fd_bounded=None, den=None, zone="NO_MOTION")
    den = math.log(n) + math.log(d / L)
    if den <= eps:
        return dict(base, status="READY", den=den, fd_raw=None, fd_bounded=2.0, bound_policy="CONSERVATIVE_CHOP_SATURATION", saturated=True)
    raw = math.log(n) / den
    if not math.isfinite(raw):
        return dict(base, status="READY", den=den, fd_raw=None, fd_bounded=2.0, bound_policy="CONSERVATIVE_CHOP_SATURATION", saturated=True)
    b = min(2.0, max(1.0, raw))
    return dict(base, status="READY", den=den, fd_raw=raw, fd_bounded=b, clipped=b != raw, saturated=False)


class FractalRegime:
    def __init__(self, cfg: dict | None = None, tick: float = 0.01):
        self.cfg = validate(cfg)
        self.tol = self.cfg["tol_ticks"] * tick                            # flat = total path below half a tick (tick-scaled)
        self.win: deque = deque(maxlen=self.cfg["N"])
        self.seed: list = []
        self.ema = None

    def zone(self, v):
        if v is None:
            return None
        return "TREND" if v <= self.cfg["trend"] else ("CHOP" if v >= self.cfg["chop"] else "NEUTRAL")

    def update(self, bar: dict) -> dict:
        try:
            p = float(PRICES[self.cfg["price"]](bar))
        except (KeyError, TypeError, ValueError):
            return {"status": "INVALID_INPUT"}
        if not math.isfinite(p):
            return {"status": "INVALID_INPUT"}
        self.win.append(p)
        if len(self.win) < self.cfg["N"]:
            return {"status": "WARMING_UP", "fd_smooth": None, "zone": None}
        k = katz(list(self.win), self.tol)
        if k["fd_bounded"] is None:                                  # flat: reset the smoothing segment (never a 0 in the EMA)
            self.seed, self.ema = [], None
            return dict(k, fd_smooth=None, zone="NO_MOTION", quality="FLAT_NO_MOTION")
        S = self.cfg["S"]
        if self.ema is None:
            self.seed.append(k["fd_bounded"])
            if len(self.seed) == S:
                self.ema = sum(self.seed) / S
        else:
            self.ema = self.ema + (2.0 / (S + 1)) * (k["fd_bounded"] - self.ema)
        q = "SATURATED" if k.get("saturated") else ("CLIPPED" if k.get("clipped") else "OK")
        return dict(k, fd_smooth=self.ema, zone=self.zone(self.ema), quality=q if self.ema is not None else "WARMING_UP")


def series(bars: list[dict], cfg: dict | None = None) -> list[dict]:
    f = FractalRegime(cfg)
    return [dict(f.update(b), t=b["open_utc"]) for b in bars]
