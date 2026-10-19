"""Causal indicators for the scalp profile (value at bar i uses bars <= i only). Pure Python - the bot venv has no pandas.

ATR14   Wilder: seed = mean of the first 14 true ranges, then (prev*13 + TR)/14.
ER(n)   |C_t - C_(t-n)| / sum(|C_i - C_(i-1)|); zero denominator -> 0.0 with flat=True (caller checks minimal movement).
BB      basis = SMA(20) of close, dev = POPULATION standard deviation (divide by N - the MT5 iBands formula), upper/lower =
        basis +/- 2*dev, %B = (C-lower)/(upper-lower), BandWidth = (upper-lower)/basis, its percentile over the previous 100
        bars (strictly earlier values), slope = (basis_t - basis_(t-3)) / (3 * ATR_t)  [ATR per bar].
SAR     Parabolic SAR profile MQ_SAR_WILDER_PROFILE_V1 (step 0.02, maximum 0.2): validated inputs, 2-bar seed, typed points
        (EP/AF/bars_since_flip), incremental SarState with checkpoint. MT5 iSAR parity: MT5_PARITY_NOT_RUN until compared.
"""
from __future__ import annotations

import math


def atr(h, lo, c, n: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(c)
    trs = []
    for i in range(len(c)):
        tr = h[i] - lo[i] if i == 0 else max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1]))
        trs.append(tr)
        if i == n - 1:
            out[i] = sum(trs) / n
        elif i >= n:
            out[i] = (out[i - 1] * (n - 1) + tr) / n
    return out


def er(c, n: int = 10) -> list[float | None]:
    out: list[float | None] = [None] * len(c)
    for i in range(n, len(c)):
        den = sum(abs(c[k] - c[k - 1]) for k in range(i - n + 1, i + 1))
        out[i] = 0.0 if den == 0 else abs(c[i] - c[i - n]) / den
    return out


def bollinger(c, a: list, n: int = 20, k: float = 2.0, pct_window: int = 100) -> list[dict | None]:
    out: list[dict | None] = [None] * len(c)
    widths: list[float] = []
    for i in range(n - 1, len(c)):
        win = c[i - n + 1: i + 1]
        m = sum(win) / n
        sd = math.sqrt(sum((x - m) ** 2 for x in win) / n)
        up, dn = m + k * sd, m - k * sd
        bw = (up - dn) / m if m else None
        prev = widths[-pct_window:]
        pct = None if len(prev) < pct_window or bw is None else 100.0 * sum(1 for x in prev if x < bw) / len(prev)
        slope = None
        if i >= n - 1 + 3 and out[i - 3] is not None and a[i]:
            slope = (m - out[i - 3]["basis"]) / (3 * a[i])
        out[i] = {"basis": m, "upper": up, "lower": dn, "pct_b": None if up == dn else (c[i] - dn) / (up - dn), "bandwidth": bw,
                  "bandwidth_pct100": pct, "slope_atr_per_bar": slope}
        if bw is not None:
            widths.append(bw)
    return out


SAR_PROFILE = "MQ_SAR_WILDER_PROFILE_V1"
SAR_PROFILE_DOC = ("seed after 2 bars: UP if high[1] >= high[0]; UP: SAR=low[0], EP=high[1] / DOWN: SAR=high[0], EP=low[1]; AF=step. "
                   "candidate = SAR + AF*(EP-SAR), clamped by the two previous lows (UP) / highs (DOWN); flip only on a STRICT cross "
                   "(low < candidate / high > candidate) -> SAR=previous EP, EP=current extreme, AF=step; otherwise EP/AF update on a new "
                   "extreme (AF += step, capped at maximum). Equality is not a cross. Values depend on the first bar of the history.")


class SarInputError(ValueError):
    pass


def validate_sar(h, lo, step: float, maximum: float) -> None:
    """Parameters finite and 0 < step <= maximum; equal lengths; finite prices with high >= low. Nothing is rounded."""
    if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in (step, maximum)) or not 0 < step <= maximum:
        raise SarInputError(f"SAR_INVALID_PARAMS:step={step},max={maximum}")
    if len(h) != len(lo):
        raise SarInputError("SAR_LENGTH_MISMATCH")
    for i, (a, b) in enumerate(zip(h, lo)):
        if not (math.isfinite(a) and math.isfinite(b)):
            raise SarInputError(f"SAR_NON_FINITE_PRICE@{i}")
        if a < b:
            raise SarInputError(f"SAR_HIGH_BELOW_LOW@{i}")


class SarState:
    """Incremental Parabolic SAR (O(1) per closed bar after the 2-bar seed). checkpoint()/restore() make a restart or a
    chunked run give exactly the same values as one pass over the same history (the profile depends on the first bar)."""

    def __init__(self, step: float = 0.02, maximum: float = 0.2):
        validate_sar([], [], step, maximum)
        self.step, self.maximum = float(step), float(maximum)
        self.n = 0
        self.h2: list[float] = []            # last two highs / lows (clamp)
        self.l2: list[float] = []
        self.up = None
        self.s = self.ep = self.af = None
        self.since_flip = 0
        self.flips: list[int] = []            # bar indices of flips (bounded)

    def update(self, high: float, low: float) -> dict | None:
        validate_sar([high], [low], self.step, self.maximum)
        i = self.n
        self.n += 1
        if i == 0:
            self.h2, self.l2 = [high], [low]
            return None
        if i == 1:
            h0, l0 = self.h2[0], self.l2[0]
            self.up = high >= h0
            self.ep = high if self.up else low
            self.s = l0 if self.up else h0
            self.af = self.step
            self.h2, self.l2 = [h0, high], [l0, low]
            self.since_flip = 0
            return self._point(i, False, flat=(high == h0 and low == l0))
        s = self.s + self.af * (self.ep - self.s)
        flip = False
        if self.up:
            s = min(s, self.l2[-1], self.l2[-2])
            if low < s:
                self.up, flip, s, self.ep, self.af = False, True, self.ep, low, self.step
            elif high > self.ep:
                self.ep, self.af = high, min(self.maximum, self.af + self.step)
        else:
            s = max(s, self.h2[-1], self.h2[-2])
            if high > s:
                self.up, flip, s, self.ep, self.af = True, True, self.ep, high, self.step
            elif low < self.ep:
                self.ep, self.af = low, min(self.maximum, self.af + self.step)
        self.s = s
        self.h2, self.l2 = [self.h2[-1], high], [self.l2[-1], low]
        self.since_flip = 0 if flip else self.since_flip + 1
        if flip:
            self.flips = (self.flips + [i])[-500:]
        return self._point(i, flip, flat=(high == low == self.h2[0] == self.l2[0]))

    def _point(self, i: int, flip: bool, flat: bool) -> dict:
        return {"sar": self.s, "trend": "UP" if self.up else "DOWN", "flip": flip, "ep": self.ep, "af": self.af,
                "bars_since_flip": self.since_flip, "index": i, "degenerate": bool(flat)}

    def checkpoint(self) -> dict:
        return {"profile": SAR_PROFILE, "step": self.step, "max": self.maximum, "n": self.n, "h2": list(self.h2), "l2": list(self.l2),
                "up": self.up, "s": self.s, "ep": self.ep, "af": self.af, "since_flip": self.since_flip, "flips": list(self.flips)}

    @classmethod
    def restore(cls, ck: dict) -> "SarState":
        if ck.get("profile") != SAR_PROFILE:
            raise SarInputError(f"SAR_PROFILE_MISMATCH:{ck.get('profile')}")
        st = cls(ck["step"], ck["max"])
        for k in ("n", "h2", "l2", "up", "s", "ep", "af", "since_flip", "flips"):
            setattr(st, k, ck[k])
        return st


def sar(h, lo, step: float = 0.02, maximum: float = 0.2) -> list[dict | None]:
    """Legacy adapter (same values as before 1.16): [{sar, trend, flip}] per bar, None for bar 0. Now validated."""
    return [None if p is None else {"sar": p["sar"], "trend": p["trend"], "flip": p["flip"]} for p in sar_points(h, lo, step, maximum)]


def sar_points(h, lo, step: float = 0.02, maximum: float = 0.2) -> list[dict | None]:
    """Full typed points (SAR, trend, flip, EP, AF, bars_since_flip, degenerate) of profile MQ_SAR_WILDER_PROFILE_V1."""
    validate_sar(h, lo, step, maximum)
    st = SarState(step, maximum)
    return [st.update(a, b) for a, b in zip(h, lo)]


def sar_diagnostics(h, lo, c, atr_last: float | None, step: float = 0.02, maximum: float = 0.2, flip_window: int = 50) -> dict:
    """Last closed point + interpretation fields. Raw seed direction on flat / degenerate input is kept but marked
    NO_DIRECTIONAL_EVIDENCE (a flat series is not an up-trend)."""
    if len(h) < 2:
        return {"status": "WARMING_UP", "profile": SAR_PROFILE, "params": {"step": step, "max": maximum}, "reason": "mniej niż 2 zamknięte świece"}
    pts = sar_points(h, lo, step, maximum)
    last = pts[-1]
    n = len(h)
    flips = sum(1 for p in pts[max(1, n - flip_window):] if p and p["flip"])
    rng = max(h[-flip_window:]) - min(lo[-flip_window:])
    dist = c[-1] - last["sar"]
    interp = "NO_DIRECTIONAL_EVIDENCE" if rng == 0 or last["degenerate"] else ("PRESSURE_UP" if last["trend"] == "UP" else "PRESSURE_DOWN")
    return {"status": "OK" if n >= 5 else "WARMING_UP", "profile": SAR_PROFILE, "params": {"step": step, "max": maximum},
            "sar": last["sar"], "raw_trend": last["trend"], "interpretation": interp, "flip": last["flip"], "ep": last["ep"], "af": last["af"],
            "bars_since_flip": last["bars_since_flip"], "flips_in_window": flips, "flip_window": flip_window,
            "distance_price": dist, "distance_atr": (dist / atr_last) if atr_last else None,
            "whipsaw_risk": "HIGH" if flips >= max(4, flip_window // 8) else "NORMAL", "bars": n,
            "note": "flip potwierdza dopiero zamknięta świeca; kierunek seeda zależy od początku historii"}


def median(xs: list[float]) -> float | None:
    v = sorted(x for x in xs if x is not None)
    if not v:
        return None
    m = len(v) // 2
    return v[m] if len(v) % 2 else (v[m - 1] + v[m]) / 2
