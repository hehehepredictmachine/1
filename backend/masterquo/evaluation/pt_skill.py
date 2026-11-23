"""Pesaran-Timmermann directional skill (Apollo23 TASK 011, MQL5 article #25105) - read-only OBSERVE / SHADOW diagnostic.

Measures whether the SIGN of a forecast is associated with the sign of the NEXT matured outcome beyond the base rates. It does not measure
profitability and its p-value is not a probability of profit. A forecast for t is scored only after the final close of t+1; flat outcomes
and zero forecasts are not scored pairs.

Profiles (never switched automatically):
  ARTICLE_25105_V1        Var(P*) with the extra 4*Py*Px*(1-Py)*(1-Px)/n^2 term (as in the article's PTFromCounts()).
  STATSMODELS_REFERENCE_V1 Var(P*) with the two /n terms only - for methodological comparison.
"""
from __future__ import annotations

import math
from statistics import NormalDist

ENGINE_VERSION = "PMW-PT-1"
PROFILES = ("ARTICLE_25105_V1", "STATSMODELS_REFERENCE_V1")
MIN_N = 30
_N = NormalDist()


def counts(forecasts, outcomes) -> dict:
    """forecasts / outcomes: signed numbers (or +1 / -1 / 0). Zero forecast and flat outcome are excluded and counted separately."""
    uu = ud = du = dd = zf = fo = 0
    for f, y in zip(forecasts, outcomes):
        if f is None or y is None:
            continue
        if f == 0:
            zf += 1
            continue
        if y == 0:
            fo += 1
            continue
        if f > 0 and y > 0:
            uu += 1
        elif f > 0:
            ud += 1
        elif y > 0:
            du += 1
        else:
            dd += 1
    return {"uu": uu, "ud": ud, "du": du, "dd": dd, "zero_forecast_excluded": zf, "flat_outcome_excluded": fo}


def pt_from_counts(uu: int, ud: int, du: int, dd: int, profile: str = "ARTICLE_25105_V1", min_n: int = MIN_N) -> dict:
    if profile not in PROFILES:
        raise ValueError(f"UNKNOWN_PROFILE: {profile}")
    n = uu + ud + du + dd
    base = {"profile": profile, "n": n, "uu": uu, "ud": ud, "du": du, "dd": dd, "pt": None, "p_right": None, "p_left": None, "p_two": None,
            "gate_open": False, "engine": ENGINE_VERSION}
    if n < min_n:
        return {**base, "status": "INSUFFICIENT_N"}
    P = (uu + dd) / n
    Py = (uu + du) / n
    Px = (uu + ud) / n
    base.update(hit_rate=P, p_y=Py, p_x=Px)
    if Px <= 0 or Px >= 1:
        return {**base, "status": "NO_FORECAST_VARIATION"}
    if Py <= 0 or Py >= 1:
        return {**base, "status": "NO_OUTCOME_VARIATION"}
    Ps = Py * Px + (1 - Py) * (1 - Px)
    var_p = Ps * (1 - Ps) / n
    var_ps = ((2 * Py - 1) ** 2 * Px * (1 - Px)) / n + ((2 * Px - 1) ** 2 * Py * (1 - Py)) / n
    if profile == "ARTICLE_25105_V1":
        var_ps += 4 * Py * Px * (1 - Py) * (1 - Px) / n ** 2
    base.update(p_star=Ps, var_p=var_p, var_p_star=var_ps)
    if var_p - var_ps <= 0:
        return {**base, "status": "NON_POSITIVE_VARIANCE"}
    pt = (P - Ps) / math.sqrt(var_p - var_ps)
    pr, pl = 1 - _N.cdf(pt), _N.cdf(pt)
    return {**base, "status": "OK", "pt": pt, "p_right": pr, "p_left": pl, "p_two": min(1.0, 2 * min(pr, pl)), "gate_open": True,
            "chi2": chi2(uu, ud, du, dd)}


def chi2(uu, ud, du, dd) -> dict:
    n = uu + ud + du + dd
    den = (uu + ud) * (du + dd) * (uu + du) * (ud + dd)
    if den == 0:
        return {"chi2": None, "p": None, "status": "UNDEFINED"}
    c = n * (uu * dd - ud * du) ** 2 / den
    return {"chi2": c, "p": math.erfc(math.sqrt(c / 2)), "status": "OK", "note": "dwustronny test niezależności (1 df) – nie zastępuje p_right PT"}


def evaluate(forecasts, outcomes, profile: str = "ARTICLE_25105_V1") -> dict:
    c = counts(forecasts, outcomes)
    r = pt_from_counts(c["uu"], c["ud"], c["du"], c["dd"], profile)
    return {**r, "excluded": {"zero_forecast": c["zero_forecast_excluded"], "flat_outcome": c["flat_outcome_excluded"]},
            "mode": "OBSERVE (diagnostyka – nie bramka zleceń)"}


def matured_pairs(forecasts: list[dict], closes: list[dict]) -> list[tuple[float, float]]:
    """forecasts: [{t, f}] for bar t; closes: [{t, c, final}] - outcome = sign(c[t+1] - c[t]) only when bar t+1 is FINAL."""
    idx = {b["t"]: i for i, b in enumerate(closes)}
    out = []
    for fc in forecasts:
        i = idx.get(fc["t"])
        if i is None or i + 1 >= len(closes) or not closes[i + 1].get("final", True):
            continue                                        # UNSETTLED_TARGET
        out.append((fc["f"], closes[i + 1]["c"] - closes[i]["c"]))
    return out


# 1.46: circular_shift_pvalue() removed - never called (no endpoint, job or test used it); evaluate() is the only PT entry point
