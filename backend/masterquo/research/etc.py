"""Exponential Trend Channel (ETC_LOG_CHANNEL, FEATURE_TRANSFORM) - port of ExponentialTrendChannelIndicator.mq5 v1.06 (Bruno Myrrha,
https://www.mql5.com/en/code/79188, sha256 17d6b674...). Implementation id PMW_ETC_SRC_PORT_V1 (the source WAS read; this is a line-by-
line port of FitWindow / ScanWindows / Position / SignedFit, not a re-invention):

  * x = bar index growing with time (oldest -> newest), y = ln(price) of CLOSED bars; anchored + centred sums (source's numerics);
  * slope b = cov(t, y) / var(t); level = fitted ln price at the newest bar; spread = sqrt(RSS / (n - 1))  <- the source's divisor (n-1);
  * fit = |cov| / sqrt(var_t * var_y) (|Pearson r|, 0 for a flat window); windows 20..200 step 10 (SHORT) or 300..1200 step 50 (LONG);
    the best window = highest fit, the FIRST (shorter) one on a tie; a window longer than the history or with a price <= 0 is skipped;
  * position = (ln price - fitted ln price) / spread (deviations).
NOT a neural network, no weights, no probability: fit quality / position are geometry of past prices. The indicator repaints its
whole window with the newest fit - therefore historical features are rebuilt AS OF every decision bar (build_asof / series_asof): bar i
only ever sees bars <= i, and the change features compare with the snapshot that was known at i-1.
"""
from __future__ import annotations

import hashlib
import json
import math

VERSION = "PMW_ETC_SRC_PORT_V1"
SCHEMA = "PMW_ETC_FEATURES_V1"
FEATURES = ("etc_log_slope_per_bar", "etc_fit_signed_corr", "etc_fit_abs_corr", "etc_residual_log_std", "etc_position_z_closed",
            "etc_channel_width_relative", "etc_selected_window", "etc_window_change_flag", "etc_fit_change", "etc_trend_direction",
            "etc_distance_upper_relative", "etc_distance_lower_relative")
SHORT = tuple(20 + 10 * k for k in range(19))
LONG = tuple(300 + 50 * k for k in range(19))
PRICES = ("CLOSE", "OPEN", "HIGH", "LOW", "MEDIAN", "TYPICAL", "WEIGHTED")
DEFAULT = {"price": "CLOSE", "window_set": "SHORT", "width": 2.0}


def params_hash(p: dict) -> str:
    return hashlib.sha256(json.dumps({**DEFAULT, **p}, sort_keys=True).encode()).hexdigest()[:12]


def schema_hash(p: dict) -> str:
    return f"{SCHEMA}:{VERSION}:{params_hash(p)}"


def bar_price(b: dict, how: str) -> float:
    o, h, l_, c = (float(b[k]) for k in ("o", "h", "l", "c"))
    return {"OPEN": o, "HIGH": h, "LOW": l_, "MEDIAN": (h + l_) / 2, "TYPICAL": (h + l_ + c) / 3, "WEIGHTED": (h + l_ + 2 * c) / 4}.get(how, c)


def fit_window(logs: list, newest: int, n: int) -> dict | None:
    """Port of FitWindow: logs oldest-first, None entries = price <= 0 (EMPTY_VALUE in the source)."""
    first = newest - n + 1
    if n < 3 or first < 0 or newest >= len(logs):
        return None
    anchor = logs[first]
    if anchor is None:
        return None
    mean_y = 0.0
    for j in range(first, newest + 1):
        if logs[j] is None:
            return None
        mean_y += logs[j] - anchor
    mean_y /= n
    mean_t = (n - 1) * 0.5
    ctt = cty = cyy = 0.0
    for t in range(n):
        dt = t - mean_t
        dy = (logs[first + t] - anchor) - mean_y
        ctt += dt * dt
        cty += dt * dy
        cyy += dy * dy
    b = cty / ctt
    rss = 0.0
    for t in range(n):
        e = (logs[first + t] - anchor) - (mean_y + b * (t - mean_t))
        rss += e * e
    return {"bars": n, "slope": b, "level": anchor + mean_y + b * (n - 1 - mean_t), "spread": math.sqrt(rss / (n - 1)),
            "fit": (abs(cty) / math.sqrt(ctt * cyy)) if (cty != 0 and cyy > 0) else 0.0}


def scan(logs: list, newest: int, window_set: str = "SHORT") -> tuple[dict | None, list]:
    fits, best = [], None
    for n in (LONG if window_set == "LONG" else SHORT):
        f = fit_window(logs, newest, n)
        fits.append(f)
        if f is not None and (best is None or f["fit"] > best["fit"]):     # strictly greater: the first (shorter) window wins a tie
            best = f
    return best, fits


def _logs(bars: list[dict], how: str) -> list:
    out = []
    for b in bars:
        p = bar_price(b, how)
        out.append(math.log(p) if p > 0 and math.isfinite(p) else None)
    return out


def snapshot(bars: list[dict], i: int, p: dict | None = None, prev: dict | None = None, logs: list | None = None) -> dict:
    """Features of the channel fitted on CLOSED bars 0..i (bars oldest-first). prev = the snapshot known at i-1 (for the change
    features). Returns {features, masks, channel, state} - a missing value is None with mask 1 (never 0 pretending to be data)."""
    p = {**DEFAULT, **(p or {})}
    logs = logs if logs is not None else _logs(bars[: i + 1], p["price"])
    best, _ = scan(logs, i, p["window_set"])
    feats = {k: None for k in FEATURES}
    if best is None:
        return {"features": feats, "masks": {k: 1 for k in FEATURES}, "channel": None, "state": "WARMING_UP",
                "reason": f"za mało prawidłowych zamkniętych świec (min. {min(SHORT if p['window_set'] != 'LONG' else LONG)}, bez cen ≤ 0)"}
    w = float(p["width"])
    lp = logs[i]
    mid = best["level"]
    sd = best["spread"]
    up, lo = mid + w * sd, mid - w * sd
    feats.update(etc_log_slope_per_bar=best["slope"], etc_fit_abs_corr=best["fit"], etc_fit_signed_corr=(-best["fit"] if best["slope"] < 0 else best["fit"]),
                 etc_residual_log_std=sd, etc_selected_window=float(best["bars"]), etc_trend_direction=(1.0 if best["slope"] > 0 else -1.0 if best["slope"] < 0 else 0.0),
                 etc_channel_width_relative=(math.exp(up) - math.exp(lo)) / math.exp(mid))
    if sd > 0 and lp is not None:
        feats["etc_position_z_closed"] = (lp - mid) / sd
        px = math.exp(lp)
        feats["etc_distance_upper_relative"] = (math.exp(up) - px) / px
        feats["etc_distance_lower_relative"] = (px - math.exp(lo)) / px
    if prev and prev.get("channel"):
        feats["etc_window_change_flag"] = 1.0 if prev["channel"]["bars"] != best["bars"] else 0.0
        feats["etc_fit_change"] = best["fit"] - prev["channel"]["fit"]
    masks = {k: 0 if feats[k] is not None else 1 for k in FEATURES}
    return {"features": feats, "masks": masks, "state": "READY",
            "channel": {"bars": best["bars"], "slope": best["slope"], "level": mid, "spread": sd, "fit": best["fit"],
                        "upper": math.exp(up), "mid": math.exp(mid), "lower": math.exp(lo), "bar_index": i}}


def series_asof(bars: list[dict], p: dict | None = None, start: int = 0) -> list[dict]:
    """Causal series: element k = snapshot as known at the close of bar k (only bars <= k). Appending future bars never changes an
    earlier element (tested)."""
    p = {**DEFAULT, **(p or {})}
    logs = _logs(bars, p["price"])
    out, prev = [], None
    for i in range(start, len(bars)):
        s = snapshot(bars, i, p, prev, logs=logs[: i + 1])
        out.append(s)
        prev = s
    return out


def live_position(snap: dict, live_price: float | None) -> float | None:
    """etc_position_z_live: the tick price against the channel fitted on the last CLOSED bar - a separate field, never a training
    feature (the fit does not move within a bar; only the price does)."""
    ch = (snap or {}).get("channel")
    if not ch or not live_price or live_price <= 0 or ch["spread"] <= 0:
        return None
    return (math.log(live_price) - ch["level"] - ch["slope"]) / ch["spread"]          # one bar ahead of the newest closed bar
