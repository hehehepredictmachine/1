"""XAUUSD x DXY relation on H1 RETURNS (PMW-IND-DXY-1). DXY is a context instrument, never traded.

Alignment: closed H1 bars of both symbols, keyed by bar open (UTC), used only when available (close known) at as_of. A return
r_t = ln(C_t / C_{t-1h}) exists only when BOTH bars t and t-1h are present in that series - no forward fill, so a missing DXY hour
never becomes an artificial zero return. Joint observations = hours where both returns exist.
Per window W (default 24 / 72 / 240 joint observations; min_obs configurable):
  corr_W   Pearson correlation of the last W joint returns;
  beta_W   OLS slope of r_xau on r_dxy (alpha_W intercept);  r_xau = alpha + beta * r_dxy + e;
  resid_W  residual of the NEWEST observation with alpha / beta fitted on the W observations BEFORE it (the current point is never in
           its own fit); resid_z_W = resid / std(fit residuals) (ddof = 2).
Zero DXY variance -> beta / resid None (DXY_ZERO_VARIANCE). Unstable fit: beta of the two halves of the window with opposite signs ->
flag UNSTABLE. Data age: as_of - available_at of the last DXY bar; > max_age_s -> STALE (explicit degraded mode).
Presentation series (normalised cumulative returns) are for the chart only and never feed training features.
"""
from __future__ import annotations

import math

from . import contract as C

VERSION = "PMW-IND-DXY-1"
UNITS = {"corr": "correlation", "beta": "ratio", "alpha": "log_return", "resid": "log_return", "resid_z": "z_score", "age_s": "seconds"}


def _closed_map(bars: list[dict], as_of: float) -> dict[float, float]:
    out = {}
    for b in bars or []:
        if b.get("closed") is False or not b.get("open_utc"):
            continue
        t = C.ts(b["open_utc"])
        av = C.ts(b.get("available_at")) if b.get("available_at") else t + 3600
        if av > as_of + 1e-6 or t + 3600 > as_of + 1e-6:
            continue
        c = float(b["c"])
        if c > 0:
            out[t] = c
    return out


def _rets(m: dict[float, float]) -> dict[float, float]:
    return {t: math.log(c / m[t - 3600]) for t, c in m.items() if (t - 3600) in m}


def joint(xau: list[dict], dxy: list[dict], as_of: float) -> list[tuple[float, float, float]]:
    rx, rd = _rets(_closed_map(xau, as_of)), _rets(_closed_map(dxy, as_of))
    return [(t, rx[t], rd[t]) for t in sorted(set(rx) & set(rd))]


def _ols(xs: list[float], ys: list[float]) -> tuple[float | None, float | None, float | None]:
    n = len(xs)
    if n < 3:
        return None, None, None
    mx, my = sum(xs) / n, sum(ys) / n
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    cxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    corr = cxy / math.sqrt(vx * vy) if vx > 0 and vy > 0 else None
    if vx <= 1e-30:
        return None, None, corr
    beta = cxy / vx
    return my - beta * mx, beta, corr


def window_stats(obs: list[tuple[float, float, float]], w: int, min_obs: int) -> dict:
    out = {"n": 0, "corr": None, "beta": None, "alpha": None, "resid": None, "resid_z": None, "unstable": None, "reason": None,
           "from": None, "to": None, "coverage_hours": None}
    cur = obs[-w:]
    out["n"] = len(cur)
    if len(cur) < min_obs:
        out["reason"] = f"OBS_{len(cur)}<{min_obs}"
        return out
    xs, ys = [o[2] for o in cur], [o[1] for o in cur]
    a, b, corr = _ols(xs, ys)
    out.update(corr=corr, beta=b, alpha=a, **{"from": C.iso(cur[0][0]), "to": C.iso(cur[-1][0])},
               coverage_hours=(cur[-1][0] - cur[0][0]) / 3600 + 1)
    if b is None:
        out["reason"] = "DXY_ZERO_VARIANCE"
    else:
        h = len(cur) // 2
        _, b1, _ = _ols(xs[:h], ys[:h])
        _, b2, _ = _ols(xs[h:], ys[h:])
        out["unstable"] = bool(b1 is not None and b2 is not None and b1 * b2 < 0)
    fit = obs[-w - 1:-1]                                        # the W observations BEFORE the newest one
    if len(fit) >= min_obs:
        fx, fy = [o[2] for o in fit], [o[1] for o in fit]
        fa, fb, _ = _ols(fx, fy)
        if fb is not None:
            res = [y - (fa + fb * x) for x, y in zip(fx, fy)]
            sd = math.sqrt(sum(r * r for r in res) / (len(res) - 2)) if len(res) > 2 else None
            t, ry, rx = obs[-1]
            e = ry - (fa + fb * rx)
            out.update(resid=e, resid_z=(e / sd) if sd and sd > 0 else None, fit_alpha=fa, fit_beta=fb,
                       fit_from=C.iso(fit[0][0]), fit_to=C.iso(fit[-1][0]))
    return out


def compute(xau_h1: list[dict], dxy_h1: list[dict], *, as_of: float, instrument: str, broker_symbol: str | None, dxy_symbol: str | None,
            dxy_status: str | None = None, windows=(24, 72, 240), min_obs: int = 20, max_age_s: float = 3 * 3600, cfg: dict | None = None,
            presentation_points: int = 72) -> dict:
    cfgd = dict(cfg or {}, windows=list(windows), min_obs=min_obs, max_age_s=max_age_s, dxy_symbol=dxy_symbol)
    base = dict(instrument=instrument, broker_symbol=broker_symbol, source=f"MT5_H1:{dxy_symbol}" if dxy_symbol else "MT5_H1", timeframe="H1",
                cfg=cfgd, units=UNITS)
    if not dxy_symbol:
        return C.result("XAU_DXY", VERSION, status="DISABLED", reason="DXY_SYMBOL_NOT_CONFIGURED",
                        extra={"dxy": {"status": "NOT_CONFIGURED", "last_available_at": None}}, **base)
    dm = _closed_map(dxy_h1, as_of)
    last_t = max(dm) if dm else None
    last_av = None
    if last_t is not None:
        b = next((x for x in dxy_h1 if x.get("open_utc") and C.ts(x["open_utc"]) == last_t), None)
        last_av = C.ts(b.get("available_at")) if b and b.get("available_at") else last_t + 3600
    age = (as_of - last_av) if last_av is not None else None
    dstate = {"symbol": dxy_symbol, "bridge_status": dxy_status, "last_bar": C.iso(last_t), "last_available_at": C.iso(last_av),
              "age_s": age, "bars": len(dm)}
    if not dm:
        dstate["status"] = "NO_DATA"
        return C.result("XAU_DXY", VERSION, status="NO_DATA", reason=f"DXY_NO_BARS({dxy_status or 'UNKNOWN'})", extra={"dxy": dstate}, **base)
    obs = joint(xau_h1, dxy_h1, as_of)
    vals = {"joint_obs": len(obs), "age_s": age}
    per = {}
    for w in windows:
        st = window_stats(obs, w, min_obs)
        per[str(w)] = st
        for k in ("corr", "beta", "alpha", "resid", "resid_z"):
            vals[f"{k}_{w}"] = st[k]
        vals[f"n_{w}"] = st["n"]
        vals[f"unstable_{w}"] = st["unstable"]
    ws = sorted(windows)
    if vals.get(f"corr_{ws[0]}") is not None and vals.get(f"corr_{ws[-1]}") is not None:
        vals["corr_change"] = vals[f"corr_{ws[0]}"] - vals[f"corr_{ws[-1]}"]
    vals["sign"] = (None if vals.get(f"corr_{ws[1] if len(ws) > 1 else ws[0]}") is None else
                    "NEGATIVE" if vals[f"corr_{ws[1] if len(ws) > 1 else ws[0]}"] < 0 else "POSITIVE")
    pres = obs[-presentation_points:]
    cx = cd = 0.0
    series = []
    for t, rx, rd in pres:
        cx += rx
        cd += rd
        series.append({"t": C.iso(t), "xau_cum": C.num(cx), "dxy_cum": C.num(cd)})
    extra = {"dxy": dstate, "windows": per, "presentation": {"note": "tylko do wykresu – nie jest cechą treningową", "series": series},
             "equation": "r_xau = alpha + beta * r_dxy + e (OLS, H1 log-zwroty, bez forward-fill)"}
    dt = C.iso(obs[-1][0]) if obs else None
    if age is not None and age > max_age_s:
        dstate["status"] = "STALE"
        return C.result("XAU_DXY", VERSION, values=vals, status="STALE", reason=f"DXY_AGE_{int(age)}S>{int(max_age_s)}S", sample_count=len(obs),
                        data_time=dt, available_at=last_av, extra=extra, **base)
    if vals.get(f"corr_{ws[0]}") is None and vals.get(f"beta_{ws[0]}") is None:
        dstate["status"] = "READY"
        return C.result("XAU_DXY", VERSION, values=vals, status="WARMUP", reason=per[str(ws[0])]["reason"] or "WARMUP", sample_count=len(obs),
                        data_time=dt, available_at=last_av, extra=extra, **base)
    dstate["status"] = "READY"
    return C.result("XAU_DXY", VERSION, values=vals, sample_count=len(obs), data_time=dt, available_at=last_av, extra=extra, **base)


def feature_context(r: dict | None) -> dict:
    """What MarketView.context['dxy'] carries (ml.features.dxy_missing reads status + last_available_at)."""
    if not r:
        return {"status": "NO_DATA", "last_available_at": None}
    d = dict(r.get("dxy") or {})
    return {"status": "READY" if r["status"] in ("READY", "WARMUP") and d.get("status") == "READY" else r["status"],
            "last_available_at": d.get("last_available_at"), "relation_status": r["status"], "reason": r.get("reason"),
            "corr_72": C.value(r, "corr_72"), "beta_72": C.value(r, "beta_72"), "resid_z_72": C.value(r, "resid_z_72"),
            "corr_24": C.value(r, "corr_24"), "corr_240": C.value(r, "corr_240"), "symbol": d.get("symbol"), "age_s": d.get("age_s"),
            "horizon": "H1"}
