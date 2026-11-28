"""Pure helpers shared by the live forecast (tsfm/service.py) and the walk-forward validation (tsfm/validation.py) - leaf module.
1.46 arch I0085: validation imported them from service, and service imports validation (start_validation) - the service <-> validation
cycle. The functions are moved unchanged; tsfm.service re-exports them under the old names."""
from __future__ import annotations


def predict_request(c, s, bars: list[dict], tf: str, H: int, volume_source: str | None) -> tuple[dict, int]:
    """(request, context bars) of ONE forecast from `bars` = the closed bars of the quality window (<= settings.lookback).
    1.46: shared by the live forecast and the walk-forward validation - the validation used to send CLOSE_V1 without covariates and the
    full context_len although its report binds the configured profile / context (the live input is cut to the lookback window)."""
    ctx = min(c.context_len, len(bars))
    win = bars[-ctx:]
    req = {"cmd": "predict", "close": [float(b["c"]) for b in win], "pred_len": H, "context_len": ctx, "profile": c.profile,
           "quantiles": s.quantiles, "freq_tf": tf}
    if c.profile == "CLOSE_OHLCV_PAST_V1":
        vol = [float(b.get("rv") or 0) for b in win] if volume_source == "REAL_VOLUME" else \
            [float(b.get("tv") or 0) for b in win] if volume_source == "TICK_VOLUME" else None
        req["covariates"] = {"open": [b["o"] for b in win], "high": [b["h"] for b in win], "low": [b["l"] for b in win], "volume": vol}
    return req, ctx


def neutral_band(s, atr14: float | None, point: float | None) -> float:
    """The neutral band of the direction rule: max(k x ATR14, min_points x point) - 1.46: one definition for the live forecast and the
    walk-forward validation (the validation used k x ATR only). Unchanged rule (a missing ATR / point still counts as 0 here)."""
    return max(s.direction_band_atr * (atr14 or 0.0), s.direction_band_min_points * (point or 0.0))
