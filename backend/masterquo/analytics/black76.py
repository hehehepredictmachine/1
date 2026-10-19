"""Black-76 forward framework (PMW-UPD-07 R05) - pure, versioned maths; engine/volzones.black76 stays the legacy adapter.

For F>0, K>0, sigma>=0, T>=0, D>0 (discount factor):
  v = sigma*sqrt(T); d1 = (ln(F/K) + v^2/2)/v; d2 = d1 - v
  Call = D[F N(d1) - K N(d2)], Put = D[K N(-d2) - F N(-d1)], Call - Put = D (F - K)
  delta_fwd call = D N(d1), put = D (N(d1) - 1); gamma_fwd = D phi(d1)/(F v); vega = D F phi(d1) sqrt(T) (per 1.00 sigma)
Degenerate v = 0: discounted intrinsic value; delta 0/D (and the documented ATM convention 0.5D / -0.5D), gamma null with reason
NONDIFFERENTIABLE at the money, vega 0 at T = 0 and the right limit D F phi(0) sqrt(T) at the money for sigma = 0, T > 0.
Point mass at F when v = 0: p_above_strict = 1{F>K}, p_below_strict = 1{F<K}, p_at_strike = 1{F=K}.
N(d2) is the risk-neutral probability of finishing above K IN THE MODEL - not a trade probability; p_touch is NOT estimated (null).
Time convention: ACT/365F (seconds / (365 * 86400)); LEGACY_DAILY_PROXY (1/trading_days) only via the legacy adapter.
"""
from __future__ import annotations

import math

VERSION = "PMW-BLACK76-2.0.0"
YEAR_S = 365.0 * 86400.0


class Black76Error(ValueError):
    pass


def ncdf(x: float) -> float:
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def npdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def ninv(p: float) -> float:
    if not 0.0 < p < 1.0:
        raise Black76Error("QUANTILE_OUT_OF_RANGE")
    lo, hi = -40.0, 40.0
    for _ in range(200):                                   # bisection: monotone, exact enough (1e-12) without SciPy
        mid = 0.5 * (lo + hi)
        if ncdf(mid) < p:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def year_fraction(seconds: float) -> float:
    return max(0.0, seconds) / YEAR_S


def discount(rate: float | None = None, t: float = 0.0, d: float | None = None) -> float:
    """Discount factor given directly (d) or from a continuously compounded rate as a FRACTION (0.05 = 5 %); negative allowed."""
    if d is not None:
        if not (math.isfinite(d) and d > 0):
            raise Black76Error("DISCOUNT_INVALID")
        return float(d)
    r = 0.0 if rate is None else float(rate)
    if not math.isfinite(r) or abs(r) > 1.0:
        raise Black76Error("RATE_INVALID (podaj ułamek, np. 0.05)")
    return math.exp(-r * t)


def _check(f, k, sigma, t, d):
    for name, x in (("F", f), ("K", k), ("sigma", sigma), ("T", t), ("D", d)):
        if not isinstance(x, (int, float)) or not math.isfinite(x):
            raise Black76Error(f"{name}_NOT_FINITE")
    if f <= 0 or k <= 0:
        raise Black76Error("NONPOSITIVE_FORWARD_OR_STRIKE (profil lognormalny wymaga F>0, K>0)")
    if sigma < 0 or t < 0:
        raise Black76Error("NEGATIVE_SIGMA_OR_T")
    if d <= 0:
        raise Black76Error("DISCOUNT_INVALID")


def price(f: float, k: float, sigma: float, t: float, d: float = 1.0) -> dict:
    _check(f, k, sigma, t, d)
    v = sigma * math.sqrt(t)
    if v == 0.0:
        call, put = d * max(f - k, 0.0), d * max(k - f, 0.0)
        atm = f == k
        dc = 0.5 * d if atm else (d if f > k else 0.0)
        vega = d * f * npdf(0.0) * math.sqrt(t) if (atm and t > 0) else 0.0
        return {"version": VERSION, "call": call, "put": put, "parity_residual": (call - put) - d * (f - k), "d1": None, "d2": None,
                "delta_call": dc, "delta_put": dc - d, "gamma": None if atm else 0.0, "gamma_reason": "NONDIFFERENTIABLE" if atm else None,
                "vega": vega, "vega_per_vol_point": 0.01 * vega,
                "p_above_strict": 1.0 if f > k else 0.0, "p_below_strict": 1.0 if f < k else 0.0, "p_at_strike": 1.0 if atm else 0.0,
                "p_touch": None, "p_touch_reason": "NOT_ESTIMATED", "degenerate": True}
    d1 = (math.log(f / k) + 0.5 * v * v) / v
    d2 = d1 - v
    call = d * (f * ncdf(d1) - k * ncdf(d2))
    put = d * (k * ncdf(-d2) - f * ncdf(-d1))
    vega = d * f * npdf(d1) * math.sqrt(t)
    return {"version": VERSION, "call": call, "put": put, "parity_residual": (call - put) - d * (f - k), "d1": d1, "d2": d2,
            "delta_call": d * ncdf(d1), "delta_put": d * (ncdf(d1) - 1.0), "gamma": d * npdf(d1) / (f * v), "gamma_reason": None,
            "vega": vega, "vega_per_vol_point": 0.01 * vega, "p_above_strict": ncdf(d2), "p_below_strict": ncdf(-d2), "p_at_strike": 0.0,
            "p_touch": None, "p_touch_reason": "NOT_ESTIMATED", "degenerate": False,
            "note": "N(d2) = prawdopodobieństwo neutralne względem ryzyka w modelu, nie prawdopodobieństwo transakcji"}


def bounds(f: float, k: float, d: float, kind: str) -> tuple[float, float]:
    return (d * max(f - k, 0.0), d * f) if kind == "call" else (d * max(k - f, 0.0), d * k)


def implied_vol(premium: float, f: float, k: float, t: float, d: float = 1.0, kind: str = "call", tol: float = 1e-10, max_iter: int = 200) -> dict:
    """Bracketed (bisection) solver on sigma with explicit no-arbitrage bounds. Statuses: CONVERGED, BOUNDARY (sigma = 0),
    NO_SOLUTION (outside bounds / at the upper bound), T_ZERO_UNIDENTIFIED."""
    _check(f, k, 0.0, t, d)
    if kind not in ("call", "put"):
        raise Black76Error("KIND_INVALID")
    if not (math.isfinite(premium) and premium >= 0):
        raise Black76Error("PREMIUM_INVALID")
    if t == 0:
        return {"status": "T_ZERO_UNIDENTIFIED", "sigma": None}
    lo_p, hi_p = bounds(f, k, d, kind)
    scale = max(1e-12, hi_p)
    if premium < lo_p - tol * scale or premium >= hi_p - tol * scale:
        return {"status": "NO_SOLUTION", "sigma": None, "bounds": [lo_p, hi_p]}
    if abs(premium - lo_p) <= tol * scale:
        return {"status": "BOUNDARY", "sigma": 0.0, "bounds": [lo_p, hi_p], "repricing_error": 0.0}
    lo, hi = 0.0, 1.0
    while price(f, k, hi, t, d)[kind] < premium and hi < 1e3:
        hi *= 2.0
    it = 0
    for it in range(max_iter):
        mid = 0.5 * (lo + hi)
        if price(f, k, mid, t, d)[kind] < premium:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-12:
            break
    s = 0.5 * (lo + hi)
    err = price(f, k, s, t, d)[kind] - premium
    return {"status": "CONVERGED" if abs(err) <= max(1e-8, tol * scale * 1e3) else "NO_SOLUTION", "sigma": s, "repricing_error": err,
            "iterations": it + 1, "bounds": [lo_p, hi_p]}


def forward_from_parity(pairs: list[dict], d: float, *, max_age_s: float = 120.0, min_pairs: int = 3, exercise_style: str = "EUROPEAN") -> dict:
    """pairs: [{strike, call_bid, call_ask, put_bid, put_ask, age_s}] of ONE expiry. F_i = K + (C - P)/D from mids of liquid,
    uncrossed pairs; returns the median F, spread and the admissible interval from bid/ask. American / unknown style -> blocked."""
    if exercise_style != "EUROPEAN":
        return {"status": "BLOCKED_EXERCISE_STYLE", "reason": f"{exercise_style}: parytet put-call Black-76 nie obowiązuje dokładnie"}
    good, rejected = [], []
    for p in pairs:
        q = [p.get(x) for x in ("call_bid", "call_ask", "put_bid", "put_ask")]
        if any(v is None or not math.isfinite(v) or v < 0 for v in q):
            rejected.append((p.get("strike"), "MISSING_OR_NEGATIVE"))
        elif q[0] > q[1] or q[2] > q[3]:
            rejected.append((p.get("strike"), "CROSSED"))
        elif (p.get("age_s") or 0) > max_age_s:
            rejected.append((p.get("strike"), "STALE"))
        else:
            k = p["strike"]
            good.append({"strike": k, "F": k + ((q[0] + q[1]) / 2 - (q[2] + q[3]) / 2) / d,
                         "F_lo": k + (q[0] - q[3]) / d, "F_hi": k + (q[1] - q[2]) / d})
    if len(good) < min_pairs:
        return {"status": "INSUFFICIENT_PAIRS", "pairs_ok": len(good), "rejected": rejected, "min_pairs": min_pairs}
    fs = sorted(g["F"] for g in good)
    med = fs[len(fs) // 2] if len(fs) % 2 else 0.5 * (fs[len(fs) // 2 - 1] + fs[len(fs) // 2])
    return {"status": "OK", "forward": med, "dispersion": fs[-1] - fs[0], "pairs_ok": len(good), "admissible": [max(g["F_lo"] for g in good), min(g["F_hi"] for g in good)],
            "rejected": rejected, "qa": {"max_age_s": max_age_s, "min_pairs": min_pairs}}


def quantile(f: float, sigma: float, t: float, q: float) -> float:
    """Model quantile of the terminal forward (lognormal, constant sigma) - NOT a forecast of the CFD price nor day high/low."""
    _check(f, f, sigma, t, 1.0)
    return f * math.exp(-0.5 * sigma * sigma * t + sigma * math.sqrt(t) * ninv(q))
