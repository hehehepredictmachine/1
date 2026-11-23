"""SMMA-CCI Trend Pullback Confirmation Engine (Apollo23 TASK 023) - clean-room variant of the public description of the MQL5 product
"Buy Sell Signal Low TF" (SMMA 13/21/35, CCI(8) zero cross, closed candles, M5/M15). No code copied / decompiled; undisclosed product rules
(trend definition, noise filter, CCI applied price) are PMW DESIGN_INFERENCE_UNVALIDATED. Reuses the Modular Indicator Engine SMMA
(MQL5_STANDARD_V1 SMA-seeded) and the existing CCI (typical price) - global CCI(20) and every legacy MA stay unchanged.
Mode OFF by default; signals only on the LAST CLOSED bar; SIGNAL_QUALITY_SCORE 0-100 is not a probability; no order side effects.
"""
from __future__ import annotations

from ..indicators import smoothing as SM

VERSION = "APOLLO23-SMMA-CCI-1.0"
DEFAULT = {"mode": "OFF", "periods": (13, 21, 35), "cci_period": 8, "slope_lookback": 3, "noise_min_spread_atr": 0.1}


def evaluate(bars: list[dict], cfg: dict | None = None) -> dict:
    c = {**DEFAULT, **(cfg or {})}
    closed = [b for b in bars if not b.get("forming")]
    need = max(c["periods"]) + c["slope_lookback"] + 2
    if len(closed) < need:
        return {"status": "WARMUP", "bars": len(closed), "need": need, "version": VERSION}
    import numpy as np
    from ..mm.multi_indicator import cci as _cci
    closes = [float(b["c"]) for b in closed]
    sm = {p: SM.full(SM.IndicatorSpec.make("SMMA", p, policy="MQL5_STANDARD_V1"), closes) for p in c["periods"]}
    cc = _cci([b["h"] for b in closed], [b["l"] for b in closed], closes, c["cci_period"])
    i = len(closed) - 1
    a, b2, d = (sm[p][i] for p in c["periods"])
    up = a > b2 > d
    dn = a < b2 < d
    k = c["slope_lookback"]
    slope = sm[c["periods"][0]][i] - sm[c["periods"][0]][i - k]
    prev, cur = float(cc[i - 1]), float(cc[i])
    cross_up = prev <= 0 < cur
    cross_dn = prev >= 0 > cur
    tr = [max(x["h"] - x["l"], abs(x["h"] - closed[j - 1]["c"]), abs(x["l"] - closed[j - 1]["c"])) for j, x in enumerate(closed) if j > 0]
    atr = float(np.mean(tr[-14:]))
    spread_atr = abs(a - d) / atr if atr > 0 else 0.0
    noise = spread_atr < c["noise_min_spread_atr"]
    side = "LONG" if (up and cross_up) else ("SHORT" if (dn and cross_dn) else None)
    reasons = []
    if side is None:
        reasons.append("NO_ALIGNED_CROSS")
    if noise:
        reasons.append("NOISE_FILTER")
    close_reclaim = side == "LONG" and closes[i] > a or side == "SHORT" and closes[i] < a
    score = None
    if side and not noise:
        score = round(min(100.0, 40 + 30 * min(1.0, spread_atr) + 15 * (1 if (slope > 0) == (side == "LONG") else 0) + 15 * (1 if close_reclaim else 0)), 1)
    return {"status": "SIGNAL" if side and not noise else "NO_SIGNAL", "side": side if not noise else None, "signal_quality_score": score,
            "bar_index": i, "bar_t": closed[i].get("t") or closed[i].get("t_raw"), "smma": {p: sm[p][i] for p in c["periods"]}, "cci": cur,
            "cci_prev": prev, "spread_atr": spread_atr, "reason_codes": reasons, "mode": c["mode"], "version": VERSION,
            "rule_status": "DESIGN_INFERENCE_UNVALIDATED", "execution": "NONE (OFF/SHADOW – sygnał tylko do porównania z FX_SCALP_01 / CP_SCALP_01)"}
