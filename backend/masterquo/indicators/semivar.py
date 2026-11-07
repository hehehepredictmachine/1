"""Realised semivariance of closed-bar log returns (PMW-IND-SEMIVAR-1).

r_i = ln(C_i / C_{i-1}) for consecutive CLOSED bars;  RS_down = sum(r^2, r < 0);  RS_up = sum(r^2, r > 0);  RV = RS_up + RS_down;
downside_share = RS_down / RV (None when RV == 0: no movement - not 0.5, not 0).
A return across a gap (open_i - open_{i-1} > gap_factor x TF: session break, missing bars) is SKIPPED (default) or kept and FLAGGED
(gap_mode FLAG). Windows count valid returns (default 20 and 60 closed M1 bars - starting variants, not optimised parameters); the
window is also reported in seconds. downside_share is a share of realised variation, NOT a probability of a fall.
"""
from __future__ import annotations

import math

from . import contract as C

VERSION = "PMW-IND-SEMIVAR-1"
UNITS = {"rs_up": "log_return_sq", "rs_down": "log_return_sq", "rv": "log_return_sq", "downside_share": "ratio", "window_s": "seconds"}


def returns(bars: list[dict], tf_s: int, *, gap_factor: float = 1.5, gap_mode: str = "SKIP") -> list[dict]:
    out = []
    for a, b in zip(bars, bars[1:]):
        ca, cb = float(a["c"]), float(b["c"])
        if ca <= 0 or cb <= 0:
            continue
        dt = C.ts(b["open_utc"]) - C.ts(a["open_utc"])
        gap = dt > gap_factor * tf_s
        if gap and gap_mode == "SKIP":
            continue
        out.append({"t": b["open_utc"], "r": math.log(cb / ca), "gap": gap})
    return out


def window(rets: list[dict], n: int) -> dict:
    seq = rets[-n:]
    up = sum(x["r"] ** 2 for x in seq if x["r"] > 0)
    dn = sum(x["r"] ** 2 for x in seq if x["r"] < 0)
    rv = up + dn
    return {"rs_up": up, "rs_down": dn, "rv": rv, "downside_share": (dn / rv) if rv > 0 else None, "returns": len(seq),
            "gap_returns": sum(1 for x in seq if x["gap"])}


def compute(bars: list[dict], tf: str = "M1", *, as_of: float, instrument: str, broker_symbol: str | None = None, windows=(20, 60),
            gap_factor: float = 1.5, gap_mode: str = "SKIP", cfg: dict | None = None) -> dict:
    from ..timeutil import TF_SECONDS
    from .avwap import _closed
    tf_s = TF_SECONDS[tf]
    seq = _closed(bars, tf_s, as_of)
    rets = returns(seq, tf_s, gap_factor=gap_factor, gap_mode=gap_mode)
    cfgd = dict(cfg or {}, windows=list(windows), gap_factor=gap_factor, gap_mode=gap_mode, tf=tf)
    base = dict(instrument=instrument, broker_symbol=broker_symbol, source="MT5_BARS", timeframe=tf, cfg=cfgd, units=UNITS)
    vals, ready_all = {}, True
    for n in windows:
        w = window(rets, n)
        ok = w["returns"] >= n
        ready_all &= ok
        for k in ("rs_up", "rs_down", "rv", "downside_share"):
            vals[f"{k}_{n}"] = w[k] if ok else None
        vals[f"returns_{n}"] = w["returns"]
        vals[f"gap_returns_{n}"] = w["gap_returns"]
        vals[f"window_s_{n}"] = n * tf_s
    if not seq:
        return C.result("SEMIVAR", VERSION, status="NO_DATA", reason="NO_BARS", **base)
    dt, avail = seq[-1]["open_utc"], C.ts(seq[-1]["open_utc"]) + tf_s
    if not ready_all:
        return C.result("SEMIVAR", VERSION, values=vals, status="WARMUP", reason=f"RETURNS_{len(rets)}<{max(windows)}", sample_count=len(rets),
                        data_time=dt, available_at=avail, **base)
    zero = [n for n in windows if vals[f"downside_share_{n}"] is None]
    return C.result("SEMIVAR", VERSION, values=vals, sample_count=len(rets), data_time=dt, available_at=avail,
                    extra={"zero_movement_windows": zero} if zero else None, **base)
