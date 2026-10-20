"""MQ_HEIKIN_FLOW_V1 (FF03) - own implementation; source name QCL Heikin Flow, ORIGINAL parity UNVERIFIED_ORIGINAL.
Stage 1: smooth raw O/H/L/C separately with MA1/P1. Raw HA from the stage-1 series (HA_open recursion on RAW HA open/close).
Stage 2: smooth the four HA series with MA2/P2 -> canonical final OHLC (synthetic price: never a fill price, never a training target).
Colour: body > deadband*point BULL, < -deadband*point BEAR, else NEUTRAL. Quality PARTIAL_STARTUP until 3*(P1+P2)+10 bars.
Incremental engine commits once per closed bar identity; forming preview does not touch the committed state."""
from __future__ import annotations

import hashlib
import json

from .ma import RollingMA, check_method, normalize_period

ALGO = "MQ_HEIKIN_FLOW_V1"
DEFAULT = {"ma1": "EMA", "p1": 10, "ma2": "EMA", "p2": 5, "deadband_points": 1.0, "seed": "PARTIAL_PREFIX_V1"}
PROFILES = {"BASELINE_1_1": ("EMA", 1, "EMA", 1), "EMA10_EMA5": ("EMA", 10, "EMA", 5), "SMA10_SMA5": ("SMA", 10, "SMA", 5),
            "SMMA10_SMMA5": ("SMMA", 10, "SMMA", 5), "LWMA10_LWMA5": ("LWMA", 10, "LWMA", 5), "EMA5_EMA3": ("EMA", 5, "EMA", 3),
            "EMA20_EMA10": ("EMA", 20, "EMA", 10)}
ABI = {"buffers": 24, "plots": 7, "bull": [0, 1, 2, 3], "bear": [4, 5, 6, 7], "neutral": [8, 9, 10, 11], "canonical": [12, 13, 14, 15],
       "stage1_calc": [16, 17, 18, 19], "raw_ha_calc": [20, 21, 22, 23], "units": "synthetic price"}


def effective(cfg: dict | None) -> dict:
    c = dict(DEFAULT, **(cfg or {}))
    check_method(c["ma1"])
    check_method(c["ma2"])
    p1, f1 = normalize_period(c["p1"])
    p2, f2 = normalize_period(c["p2"])
    db = float(c["deadband_points"])
    if not db >= 0:
        raise ValueError("DEADBAND_INVALID")
    eff = {"ma1": c["ma1"], "p1": p1, "ma2": c["ma2"], "p2": p2, "deadband_points": db, "seed": c["seed"]}
    eff["requested"] = {"p1": c["p1"], "p2": c["p2"]}
    eff["flags"] = [x for x in (f1, f2) if x]
    eff["config_hash"] = hashlib.sha256(json.dumps({k: eff[k] for k in ("ma1", "p1", "ma2", "p2", "deadband_points", "seed")}, sort_keys=True)
                                        .encode()).hexdigest()[:16]
    eff["warmup_required"] = 3 * (p1 + p2) + 10
    return eff


class HeikinFlow:
    def __init__(self, cfg: dict | None = None, point: float = 0.01):
        self.cfg = effective(cfg)
        self.point = point
        self.reset()

    def reset(self):
        c = self.cfg
        self.s1 = [RollingMA(c["ma1"], c["p1"], c["seed"]) for _ in range(4)]
        self.s2 = [RollingMA(c["ma2"], c["p2"], c["seed"]) for _ in range(4)]
        self.ha_prev = None                  # (raw HA open, raw HA close) of the last committed bar
        self.n = 0
        self.last_id = None

    def _row(self, o, h, l_, c, commit: bool, bar_id=None) -> dict:
        if not all(map(lambda v: v == v and abs(v) != float("inf"), (o, h, l_, c))) or h < max(o, c) or l_ > min(o, c) or h < l_:
            raise ValueError("INVALID_OHLC")
        f = (lambda m, x: m.commit(x)) if commit else (lambda m, x: m.preview(x))
        O1, H1, L1, C1 = (f(m, x) for m, x in zip(self.s1, (o, h, l_, c)))
        hc = (O1 + H1 + L1 + C1) / 4
        ho = (O1 + C1) / 2 if self.ha_prev is None else (self.ha_prev[0] + self.ha_prev[1]) / 2
        hh, hl = max(H1, ho, hc), min(L1, ho, hc)
        FO, FH, FL, FC = (f(m, x) for m, x in zip(self.s2, (ho, hh, hl, hc)))
        if commit:
            self.ha_prev = (ho, hc)
            self.n += 1
            self.last_id = bar_id
        tol = 1e-9 * max(1.0, abs(FH))
        if not (FH >= max(FO, FC) - tol and FL <= min(FO, FC) + tol):
            raise ValueError("NUMERIC_ERROR: final OHLC invariant")
        body = FC - FO
        db = self.cfg["deadband_points"] * self.point
        color = "BULL" if body > db else ("BEAR" if body < -db else "NEUTRAL")
        n = self.n if commit else self.n + 1
        return {"o": FO, "h": FH, "l": FL, "c": FC, "color": color, "stage1": [O1, H1, L1, C1], "raw_ha": [ho, hh, hl, hc],
                "quality": "OK" if n >= self.cfg["warmup_required"] else "PARTIAL_STARTUP", "closed": commit}

    def update(self, bar: dict) -> dict | None:
        """Commit one CLOSED bar once per identity (repeated poll returns None)."""
        bid = bar["open_utc"]
        if bid == self.last_id:
            return None
        return dict(self._row(bar["o"], bar["h"], bar["l"], bar["c"], True, bid), t=bid)

    def preview(self, bar: dict) -> dict:
        return dict(self._row(bar["o"], bar["h"], bar["l"], bar["c"], False), t=bar["open_utc"])


def heikin_series(bars: list[dict], cfg: dict | None = None, point: float = 0.01) -> dict:
    hf = HeikinFlow(cfg, point)
    rows = [hf.update(b) for b in bars]
    hist = hashlib.sha256(json.dumps([[b["open_utc"], b["o"], b["h"], b["l"], b["c"]] for b in bars], default=str).encode()).hexdigest()[:16]
    return {"algorithm_id": ALGO, "source_parity": "UNVERIFIED_ORIGINAL", "config": hf.cfg, "history_hash": hist,
            "seed_origin": bars[0]["open_utc"] if bars else None, "rows": rows, "units": "synthetic price (nie cena wykonania)"}


def color_lag(bars: list[dict], rows: list[dict]) -> dict:
    """Diagnostic: bars from a raw close-to-close direction change to the next HA colour change in the same direction."""
    lags = []
    c = [b["c"] for b in bars]
    for i in range(2, len(c)):
        d0, d1 = c[i - 1] - c[i - 2], c[i] - c[i - 1]
        if d0 * d1 < 0:
            want = "BULL" if d1 > 0 else "BEAR"
            for j in range(i, min(len(rows), i + 50)):
                if rows[j]["color"] == want:
                    lags.append(j - i)
                    break
    lags.sort()
    return {"n": len(lags), "median_bars": lags[len(lags) // 2] if lags else None}
