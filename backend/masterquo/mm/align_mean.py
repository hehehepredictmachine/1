"""Align Mean - one mean-reference definition shared by every chart (PMW-MM-ALIGNMEAN-1). DETERMINISTIC_INDICATOR.

Separate concerns: (1) mean calculation, (2) time alignment, (3) cross-market normalisation, (4) read-only P&L visibility (from the
bot's own account/deal data, never fabricated), (5) parameter evaluation (a separate experiment, never part of the display).

Modes:   ROLLING_MEAN        mean of the trailing window, recomputed at every closed bar;
         FIXED_ANCHORED_MEAN mean of the window ending at the anchor bar, then FROZEN until the reset rule fires (next session start);
         SESSION_MEAN        mean from the session start to the current closed bar, reset at the next session start.
Source:  CLOSE | TYPICAL (H+L+C)/3 | MEDIAN (H+L)/2 | WEIGHTED_CLOSE (H+L+2C)/4.
Lookback: BARS (n bars of this chart) | ELAPSED_TIME (seconds; bars whose CLOSE time lies in (t-W, t]) | SESSION.
Session: start = `session_start_min` minutes after midnight in UTC+`session_tz_offset_min`; holidays/weekend gaps simply produce no bars
(the mean of a session with no closed bar is NOT_READY). All values are closed-bar values with available_at = bar close.
Normalisation: distance in points, % of mean (mean>0), and / ATR(n) of the SAME chart (Wilder, closed bars). None of these is a
probability or an edge; ATR not ready -> NOT_READY, mean <= 0 -> INVALID_NORMALISATION.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np

VERSION = "PMW-MM-ALIGNMEAN-1"
MODES = ("ROLLING_MEAN", "FIXED_ANCHORED_MEAN", "SESSION_MEAN")
SOURCES = ("CLOSE", "TYPICAL", "MEDIAN", "WEIGHTED_CLOSE")
LOOKBACKS = ("BARS", "ELAPSED_TIME", "SESSION")


@dataclass
class AlignConfig:
    mode: str = "ROLLING_MEAN"
    source: str = "TYPICAL"
    lookback: str = "ELAPSED_TIME"
    bars: int = 48
    seconds: int = 4 * 3600
    session_start_min: int = 0
    session_tz_offset_min: int = 0
    atr_period: int = 14

    def validate(self):
        if self.mode not in MODES or self.source not in SOURCES or self.lookback not in LOOKBACKS:
            raise ValueError("ALIGN_CONFIG_INVALID")
        if self.mode == "SESSION_MEAN" and self.lookback != "SESSION":
            raise ValueError("ALIGN_SESSION_MODE_REQUIRES_SESSION_LOOKBACK")
        if self.lookback == "SESSION" and self.mode == "ROLLING_MEAN":
            raise ValueError("ALIGN_ROLLING_MODE_NEEDS_BARS_OR_TIME")
        if self.bars < 1 or self.seconds < 60 or not (0 <= self.session_start_min < 1440) or abs(self.session_tz_offset_min) > 840 or self.atr_period < 1:
            raise ValueError("ALIGN_RANGE_INVALID")

    def key(self) -> str:
        return f"{self.mode}/{self.source}/{self.lookback}/{self.bars if self.lookback == 'BARS' else self.seconds if self.lookback == 'ELAPSED_TIME' else 'SESSION'}"


def price(src: str, h, l, c):  # noqa: E741
    return {"CLOSE": c, "TYPICAL": (h + l + c) / 3.0, "MEDIAN": (h + l) / 2.0, "WEIGHTED_CLOSE": (h + l + 2 * c) / 4.0}[src]


def atr_wilder(h, l, c, n: int) -> np.ndarray:  # noqa: E741
    h, l, c = (np.asarray(x, float) for x in (h, l, c))  # noqa: E741
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.r_[np.nan, c[:-1]]), np.abs(l - np.r_[np.nan, c[:-1]])))
    tr[0] = h[0] - l[0]
    out = np.full(len(c), np.nan)
    if len(c) < n:
        return out
    out[n - 1] = tr[:n].mean()
    for i in range(n, len(c)):
        out[i] = (out[i - 1] * (n - 1) + tr[i]) / n
    return out


def session_id(t_close: np.ndarray, cfg: AlignConfig) -> np.ndarray:
    """Session index of each bar CLOSE time (sessions start at session_start_min local = UTC + offset)."""
    local = np.asarray(t_close, float) + cfg.session_tz_offset_min * 60.0 - cfg.session_start_min * 60.0
    return np.floor(local / 86400.0).astype(np.int64)


def compute(t_open, o, h, l, c, tf_s: int, cfg: AlignConfig, point: float) -> dict:  # noqa: E741
    """Arrays aligned with the input bars (chronological). mean[i] uses bars <= i only."""
    cfg.validate()
    t_open = np.asarray(t_open, float)
    tc = t_open + tf_s
    p = price(cfg.source, np.asarray(h, float), np.asarray(l, float), np.asarray(c, float))
    n = len(p)
    mean = np.full(n, np.nan)
    win_n = np.zeros(n, dtype=int)
    win_from = np.full(n, np.nan)
    cs = np.r_[0.0, np.cumsum(p)]
    sid = session_id(tc, cfg)
    if cfg.lookback == "BARS":
        for i in range(n):
            if i + 1 >= cfg.bars:
                a = i + 1 - cfg.bars
                mean[i], win_n[i], win_from[i] = (cs[i + 1] - cs[a]) / cfg.bars, cfg.bars, tc[a]
    elif cfg.lookback == "ELAPSED_TIME":
        a = 0
        for i in range(n):
            while tc[a] <= tc[i] - cfg.seconds:
                a += 1
            covered = tc[i] - (tc[a] - tf_s)                 # time actually spanned by the bars in the window
            if a > 0 or covered >= cfg.seconds * 0.999:       # window fully covered by history (else NOT_READY: missing history)
                mean[i], win_n[i], win_from[i] = (cs[i + 1] - cs[a]) / (i + 1 - a), i + 1 - a, tc[a]
    else:                                                     # SESSION lookback (session mean / anchored at session start)
        a = 0
        for i in range(n):
            if i and sid[i] != sid[i - 1]:
                a = i
            mean[i], win_n[i], win_from[i] = (cs[i + 1] - cs[a]) / (i + 1 - a), i + 1 - a, tc[a]
    if cfg.mode == "FIXED_ANCHORED_MEAN":
        # freeze the first READY value of each session until the next session start (reset rule); values never change afterwards
        frozen = np.full(n, np.nan)
        cur, cur_sid, anchor = math.nan, None, np.full(n, np.nan)
        for i in range(n):
            if sid[i] != cur_sid:
                cur_sid, cur = sid[i], math.nan
            if math.isnan(cur) and np.isfinite(mean[i]):
                cur = mean[i]
                anchor[i] = tc[i]
            frozen[i] = cur
        mean = frozen
    atr = atr_wilder(h, l, c, cfg.atr_period)
    close = np.asarray(c, float)
    dist = close - mean
    with np.errstate(invalid="ignore", divide="ignore"):
        pct = np.where(mean > 0, 100.0 * dist / mean, np.nan)
        z_atr = np.where(atr > 0, dist / atr, np.nan)
    return {"version": VERSION, "config": asdict(cfg), "t_close": tc, "mean": mean, "close": close, "dist_points": dist / point, "dist_pct": pct,
            "dist_atr": z_atr, "atr": atr, "window_bars": win_n, "window_from": win_from, "session": sid}


def latest(res: dict, symbol: str, tf: str) -> dict:
    i = len(res["mean"]) - 1
    if i < 0:
        return {"symbol": symbol, "tf": tf, "status": "NO_DATA"}
    m = res["mean"][i]
    st = "OK" if np.isfinite(m) else "NOT_READY"
    if st == "OK" and m <= 0:
        st = "INVALID_NORMALISATION"
    f = lambda x: (None if not np.isfinite(x) else float(x))  # noqa: E731
    return {"symbol": symbol, "tf": tf, "mode": res["config"]["mode"], "source": res["config"]["source"], "lookback": res["config"]["lookback"],
            "window": res["config"]["bars"] if res["config"]["lookback"] == "BARS" else res["config"]["seconds"] if res["config"]["lookback"] == "ELAPSED_TIME" else "SESSION",
            "mean": f(m), "mean_ts": float(res["t_close"][i]), "close": f(res["close"][i]), "dist_points": f(res["dist_points"][i]),
            "dist_pct": f(res["dist_pct"][i]), "dist_atr": f(res["dist_atr"][i]), "atr_period": res["config"]["atr_period"],
            "window_bars": int(res["window_bars"][i]), "value_kind": "CLOSED_BAR", "status": st, "version": VERSION,
            "note": "odległość od średniej to kontekst, nie sygnał ani prawdopodobieństwo"}
