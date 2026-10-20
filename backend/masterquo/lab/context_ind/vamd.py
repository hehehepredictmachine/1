"""PWM_VAMD_ATR_WILDER_SMA_v1 (VS02): m_t = (C_t - C_{t-P}) / ATR_t (Wilder ATR, seed = mean of first A TR), baseline = SMA of the last B
valid ATR INCLUDING the current one, r = ATR/baseline, alpha = min(amax, max(0, b*r)), y_t = y_{t-1} + alpha (m_t - y_{t-1}), first y = m.
Warm-up: A+B-1 = 63 valid bars for 14/50 (and t >= P). Zero ATR/baseline -> no value (never an epsilon). Convex update: y stays between the
previous y and the new m; y converges to 0 only when the target momentum fades (constant m=4, y=4 stays 4 for any alpha)."""
from __future__ import annotations

import math
from collections import deque

PROFILE = "PWM_VAMD_ATR_WILDER_SMA_v1"
DEFAULT = {"P": 10, "A": 14, "B": 50, "base_decay": 0.15, "max_decay": 0.90}


def validate(cfg: dict | None) -> dict:
    c = dict(DEFAULT, **(cfg or {}))
    if not (int(c["P"]) >= 1 and int(c["A"]) >= 1 and int(c["B"]) >= 1 and 0 < float(c["base_decay"]) <= float(c["max_decay"]) < 1):
        raise ValueError("VAMD_CONFIG_INVALID")
    return {k: (int(v) if k in ("P", "A", "B") else float(v)) for k, v in c.items()}


class VAMD:
    def __init__(self, cfg: dict | None = None, max_gap_s: float | None = None):
        self.cfg = validate(cfg)
        self.max_gap = max_gap_s
        self.reset()

    def reset(self):
        c = self.cfg
        self.closes: deque = deque(maxlen=c["P"] + 1)
        self.tr_seed: list = []
        self.atr = None
        self.atrs: deque = deque(maxlen=c["B"])
        self.y = None
        self.prev_close = None
        self.last_t = None
        self.last_sign = None
        self.n = 0

    def checkpoint(self) -> dict:
        return {"closes": list(self.closes), "tr_seed": list(self.tr_seed), "atr": self.atr, "atrs": list(self.atrs), "y": self.y,
                "prev_close": self.prev_close, "last_t": self.last_t, "last_sign": self.last_sign, "n": self.n, "cfg": self.cfg}

    def restore(self, ck: dict):
        if ck["cfg"] != self.cfg:
            raise ValueError("VAMD_CONFIG_CHANGED")
        c = self.cfg
        self.closes = deque(ck["closes"], maxlen=c["P"] + 1)
        self.tr_seed, self.atr, self.atrs = list(ck["tr_seed"]), ck["atr"], deque(ck["atrs"], maxlen=c["B"])
        self.y, self.prev_close, self.last_t, self.last_sign, self.n = ck["y"], ck["prev_close"], ck["last_t"], ck["last_sign"], ck["n"]

    def update(self, bar: dict, t: float | None = None) -> dict:
        h, lo, c_ = float(bar["h"]), float(bar["l"]), float(bar["c"])
        if not all(map(math.isfinite, (h, lo, c_))) or h < lo:
            return {"status": "INVALID_INPUT", "y": None}
        if self.max_gap is not None and t is not None and self.last_t is not None and t - self.last_t > self.max_gap:
            self.reset()                                          # unexpected gap: new segment, re-warm-up (flagged)
            gap = True
        else:
            gap = False
        self.last_t = t
        c = self.cfg
        tr = h - lo if self.prev_close is None else max(h - lo, abs(h - self.prev_close), abs(lo - self.prev_close))
        self.prev_close = c_
        self.closes.append(c_)
        self.n += 1
        if self.atr is None:
            self.tr_seed.append(tr)
            if len(self.tr_seed) == c["A"]:
                self.atr = sum(self.tr_seed) / c["A"]
        else:
            self.atr = (self.atr * (c["A"] - 1) + tr) / c["A"]
        out = {"status": "WARMING_UP", "y": None, "atr": self.atr, "segment_reset": gap}
        if self.atr is None:
            return out
        self.atrs.append(self.atr)
        if len(self.atrs) < c["B"] or len(self.closes) < c["P"] + 1:
            return out
        base = sum(self.atrs) / c["B"]
        if self.atr <= 0 or base <= 0:
            return dict(out, status="FLAT_NO_MOTION")
        raw = self.closes[-1] - self.closes[0]
        m = raw / self.atr
        r = self.atr / base
        a = min(c["max_decay"], max(0.0, c["base_decay"] * r))
        self.y = m if self.y is None else self.y + a * (m - self.y)
        sign = 1 if self.y > 0 else (-1 if self.y < 0 else 0)
        cross = None
        if self.last_sign is not None and sign != 0 and self.last_sign != 0 and sign != self.last_sign:
            cross = "ZERO_CROSS_UP" if sign > 0 else "ZERO_CROSS_DOWN"
        if sign != 0:
            self.last_sign = sign
        return {"status": "READY", "y": self.y, "m": m, "raw_momentum": raw, "atr": self.atr, "baseline": base, "ratio": r, "alpha": a,
                "sign": sign, "event": cross, "segment_reset": gap}

    def preview(self, bar: dict) -> dict:
        """Forming bar: computed on a copy; never a feature/alert and never changes the checkpoint."""
        import copy
        return dict(copy.deepcopy(self).update(bar), closed=False)


def series(bars: list[dict], cfg: dict | None = None) -> list[dict]:
    v = VAMD(cfg)
    return [dict(v.update(b), t=b["open_utc"]) for b in bars]
