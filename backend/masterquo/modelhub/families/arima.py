"""TS_ARIMA and TS_SARIMAX (statsmodels) - forecasts of the log return over 1 / 3 / 5 bars with intervals.

TS_ARIMA compares two explicit transformations on development data: LOGPRICE (ARIMA(p,1,q) on log close; forecast = predicted log price
- current log price) and RETURNS (ARIMA(p,0,q) with a constant on log returns). (p, q) in a bounded grid chosen by AIC on train; the
transformation by 1-step validation MAE. Diagnostics: optimiser convergence, Ljung-Box on residuals, AR/MA roots outside the unit
circle - a non-converged / non-stationary fit is not reported as a forecast (VALIDATION_FAILED).
TS_SARIMAX (H1): SARIMAX on log returns with CALENDAR exog known in advance (session flags of the instrument's own session profile and
hour-of-day sin / cos) - future exog of a multi-step forecast is computed from the calendar, never from future data. Seasonality
(period 24 on H1) is enabled only when the seasonal autocorrelation on train exceeds 2/sqrt(n).
Artifacts are JSON (orders, transformation, parameters); at prediction the model is rebuilt on the last W observations and FILTERED
with the stored parameters (state update without refitting). Baselines: zero return and random walk (identical for log returns).
Intervals are model intervals of the return, not P(TP before SL).
"""
from __future__ import annotations

import json
import math
import time
import warnings

import numpy as np

from . import base as B

GRID = [(p, q) for p in range(3) for q in range(3)]
SMOKE_GRID = [(0, 0), (1, 0), (0, 1), (1, 1)]
WINDOW = 600


def _arima(endog, order, trend, exog=None, seasonal=(0, 0, 0, 0)):
    from statsmodels.tsa.statespace.sarimax import SARIMAX
    return SARIMAX(endog, exog=exog, order=order, seasonal_order=seasonal, trend=trend, enforce_stationarity=True, enforce_invertibility=True)


def _fit(endog, order, trend, exog=None, seasonal=(0, 0, 0, 0)):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = _arima(endog, order, trend, exog, seasonal).fit(disp=False, maxiter=200)
    conv = bool((getattr(res, "mle_retvals", None) or {}).get("converged", True))
    return res, conv


def _scale(x: np.ndarray) -> float:
    """Fit on returns scaled to unit variance: raw M5/H1 log returns (~1e-3) make the MLE optimiser fail to converge (1.33 audit:
    SARIMAX on H1 data with volatility clustering did not converge in most fits; scaled - all converged). Stored in the artifact;
    forecasts and error metrics are converted back to log-return units. Old artifacts without 'scale' = 1.0 (unchanged)."""
    sd = float(np.std(x)) if len(x) else 0.0
    return 1.0 / sd if sd > 0 and math.isfinite(sd) else 1.0


def _unscale(ev: dict, k: float) -> dict:
    return {**ev, **{m: ev[m] / k for m in ("mae", "rmse", "baseline_zero_mae", "mean_width_90") if ev.get(m) is not None}}


def _diag(res) -> dict:
    out = {"aic": float(res.aic), "converged": bool((getattr(res, "mle_retvals", None) or {}).get("converged", True))}
    try:
        from statsmodels.stats.diagnostic import acorr_ljungbox
        lb = acorr_ljungbox(np.asarray(res.resid)[1:], lags=[10], return_df=True)
        out["ljung_box_p10"] = float(lb["lb_pvalue"].iloc[0])
    except Exception:  # noqa: BLE001
        out["ljung_box_p10"] = None
    try:
        ar = np.abs(res.arroots) if len(getattr(res, "arroots", [])) else np.array([])
        ma = np.abs(res.maroots) if len(getattr(res, "maroots", [])) else np.array([])
        out["min_ar_root"] = float(ar.min()) if len(ar) else None
        out["min_ma_root"] = float(ma.min()) if len(ma) else None
        out["stable"] = int(bool((not len(ar) or ar.min() > 1.0) and (not len(ma) or ma.min() > 1.0)))
    except Exception:  # noqa: BLE001
        out["stable"] = 1
    return out


def calendar_exog(ts: np.ndarray, profile_id: str) -> np.ndarray:
    """Known-in-advance calendar features: session flags of the instrument's session profile + hour-of-day sin/cos (UTC)."""
    from ...analytics import session_engine as SE
    sess = [s[0] for s in SE.PROFILES[profile_id]["sessions"]]
    out = np.zeros((len(ts), len(sess) + 2))
    cache: dict[int, list] = {}
    for i, t in enumerate(ts):
        day = int(t // 86400)
        if day not in cache:
            cache[day] = [(w["session"], w["start"].timestamp(), w["end"].timestamp()) for w in SE.windows(profile_id, float(t), 1, 1)]
        for j, s in enumerate(sess):
            out[i, j] = 1.0 if any(n == s and a <= t < b for n, a, b in cache[day]) else 0.0
        h = (t % 86400) / 3600.0
        out[i, -2], out[i, -1] = math.sin(2 * math.pi * h / 24), math.cos(2 * math.pi * h / 24)
    return out


def _one_step_eval(endog_all, start, order, trend, params, exog_all=None, seasonal=(0, 0, 0, 0), transform="RETURNS", logp=None) -> dict:
    """Rolling 1-step forecasts over [start, n) with FIXED parameters (filter, no refit): MAE/RMSE of the log return + 90 % coverage."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        mod = _arima(endog_all, order, trend, exog_all, seasonal)
        res = mod.filter(params)
        pr = res.get_prediction(start=start)
        mean = np.asarray(pr.predicted_mean)
        ci = np.asarray(pr.conf_int(alpha=0.1))
    y = np.asarray(endog_all)[start:]
    if transform == "LOGPRICE":
        prev = np.asarray(endog_all)[start - 1:-1]
        err = (mean - prev) - (y - prev)
        lo, hi = ci[:, 0] - prev, ci[:, 1] - prev
        yy = y - prev
    else:
        err, lo, hi, yy = mean - y, ci[:, 0], ci[:, 1], y
    zero = np.abs(yy)
    return {"mae": float(np.mean(np.abs(err))), "rmse": float(np.sqrt(np.mean(err ** 2))), "baseline_zero_mae": float(np.mean(zero)),
            "skill_vs_zero": float(1 - np.mean(np.abs(err)) / np.mean(zero)) if np.mean(zero) > 0 else None,
            "coverage_90": float(np.mean((yy >= lo) & (yy <= hi))), "mean_width_90": float(np.mean(hi - lo)), "n": int(len(y))}


class ARIMA(B.Family):
    ID = "TS_ARIMA"
    NAME = "ARIMA (statsmodels) – prognoza log-zwrotu"
    KIND = "TRAINED"
    TASK_TYPE = "REGRESSION"
    UNIT = "log_return"
    TASK = "LOG_RETURN_H"
    DEPS = ("statsmodels", "pandas", "scipy")
    TF = "M5"
    HORIZONS = (1, 3, 5)
    RECEIVERS = ("SH_CONTEXT:expected_move", "PANEL:model_status", "AGENT:context")
    DATA = {"kind": "BARS", "tf": "M5", "min_bars": 800, "source": "eksport MT5 (marketdata Store) / bridge na żywo"}

    def fit(self, data, cfg, tmp, budget):
        c = B.closes(data["bars"])[-int(budget.get("max_rows", 4000)):]
        logp = np.log(c)
        ret = np.diff(logp)
        n = len(ret)
        sp = B.chrono_split(n, holdout_frac=0.2, val_frac=0.25, embargo=0)
        tr_end, va0, va1, h0 = sp["train"][1], sp["val"][0], sp["val"][1], sp["holdout"][0]
        grid = SMOKE_GRID if budget.get("profile") == "smoke" else GRID
        k = _scale(ret[:tr_end])
        cands = []
        for transform in ("RETURNS", "LOGPRICE"):
            endog = (ret[:tr_end] if transform == "RETURNS" else logp[1:tr_end + 1]) * k
            best = None
            for p, q in grid:
                order = (p, 0, q) if transform == "RETURNS" else (p, 1, q)
                trend = "c" if transform == "RETURNS" else "n"
                try:
                    res, conv = _fit(endog, order, trend)
                except Exception:  # noqa: BLE001
                    continue
                if not conv or not np.all(np.isfinite(res.params)):
                    continue
                if best is None or res.aic < best[0].aic:
                    best = (res, order, trend)
            if best is None:
                continue
            res, order, trend = best
            full = (ret[:va1] if transform == "RETURNS" else logp[1:va1 + 1]) * k
            ev = _unscale(_one_step_eval(full, va0, order, trend, res.params, transform=transform), k)
            cands.append({"transform": transform, "order": order, "trend": trend, "params": [float(x) for x in res.params],
                          "param_names": list(res.param_names), "diag": _diag(res), "val": ev})
        if not cands:
            raise B.Unavailable("VALIDATION_FAILED", "żadne dopasowanie ARIMA nie zbiegło")
        pick = min(cands, key=lambda c: c["val"]["mae"])
        # holdout: parameters re-estimated on train+val (development), evaluated ONCE on the untouched end
        endog_dev = (ret[:h0] if pick["transform"] == "RETURNS" else logp[1:h0 + 1]) * k
        res_dev, conv = _fit(endog_dev, tuple(pick["order"]), pick["trend"])
        full = (ret if pick["transform"] == "RETURNS" else logp[1:]) * k
        hold = _unscale(_one_step_eval(full, h0, tuple(pick["order"]), pick["trend"], res_dev.params, transform=pick["transform"]), k)
        diag = _diag(res_dev)
        art = {"transform": pick["transform"], "order": list(pick["order"]), "trend": pick["trend"], "params": [float(x) for x in res_dev.params],
               "param_names": list(res_dev.param_names), "window": WINDOW, "scale": k}
        (tmp / "arima.json").write_text(json.dumps(art), encoding="utf-8")
        sample_in = data["bars"][-(WINDOW + 1):]
        sample = self._forecast(art, B.closes(sample_in))
        val_metrics = {"val_mae": pick["val"]["mae"], "val_skill_vs_zero": pick["val"]["skill_vs_zero"], "converged": 1.0 if conv else 0.0,
                       "stable": float(diag.get("stable", 1))}
        valid = self.promotion(val_metrics, {"converged": (">", 0.5), "stable": (">", 0.5), "val_skill_vs_zero": (">", 0.0)})
        return {"metrics": {"candidates": cands, "chosen": {k: pick[k] for k in ("transform", "order", "trend")}, "holdout": hold, "diag_dev": diag,
                            "baseline": "zerowy zwrot / random walk"},
                "validation": valid, "sample": {"closes_tail": B.closes(sample_in).tolist(), "expected": sample, "tolerance": 1e-8}}

    def load(self, d):
        return json.loads((d / "arima.json").read_text(encoding="utf-8"))

    def _forecast(self, art, c: np.ndarray) -> dict:
        logp = np.log(c[-(art["window"] + 1):])
        k = float(art.get("scale") or 1.0)
        endog = (np.diff(logp) if art["transform"] == "RETURNS" else logp[1:]) * k
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            res = _arima(endog, tuple(art["order"]), art["trend"]).filter(np.asarray(art["params"]))
            fc = res.get_forecast(max(self.HORIZONS))
            m, ci = np.asarray(fc.predicted_mean) / k, np.asarray(fc.conf_int(alpha=0.1)) / k
        out = {}
        for h in self.HORIZONS:
            if art["transform"] == "RETURNS":
                mean = float(np.sum(m[:h]))
                var = float(np.sum(((ci[:h, 1] - ci[:h, 0]) / (2 * 1.6449)) ** 2))       # independent-step approximation, labelled
                lo, hi = mean - 1.6449 * math.sqrt(var), mean + 1.6449 * math.sqrt(var)
            else:
                mean, lo, hi = float(m[h - 1] - logp[-1]), float(ci[h - 1, 0] - logp[-1]), float(ci[h - 1, 1] - logp[-1])
            out[str(h)] = {"mean": mean, "lo": lo, "hi": hi}
        return out

    def predict(self, art, live):
        c = B.closes(live["bars"])
        if len(c) < art["window"] + 1:
            raise B.Unavailable("BLOCKED_DATA", f"za mało świec: {len(c)} < {art['window'] + 1}")
        f = self._forecast(art, c)
        h1 = f[str(self.HORIZONS[0])]
        return {"mean": h1["mean"], "lo": h1["lo"], "hi": h1["hi"], "price_now": float(c[-1]),
                "price_mean": float(c[-1] * math.exp(h1["mean"])), "horizons": f, "interval": "90% (model)", "transform": art["transform"]}


class SARIMAX(ARIMA):
    ID = "TS_SARIMAX"
    NAME = "SARIMAX (statsmodels) – zwroty H1 z kalendarzem sesji jako exog"
    TF = "H1"
    HORIZONS = (1, 3, 5)
    DATA = {"kind": "BARS", "tf": "H1", "min_bars": 600, "exog": "kalendarz sesji (znany z góry)"}
    RECEIVERS = ("SH_CONTEXT:expected_move_h1", "PANEL:model_status", "AGENT:context")

    def _profile(self, inst):
        return {"XAUUSD": "LAB_XAU_REFERENCE_V1", "BTC": "LAB_BTC_REFERENCE_V1"}.get(inst, "LAB_XAU_REFERENCE_V1")

    def fit(self, data, cfg, tmp, budget):
        bars = data["bars"][-int(budget.get("max_rows", 3000)):]
        c = B.closes(bars)
        t = np.asarray([b["t"] for b in bars], dtype=float)
        ret = np.diff(np.log(c))
        tr = t[1:]
        prof = self._profile(data["instrument"])
        X = calendar_exog(tr, prof)
        n = len(ret)
        sp = B.chrono_split(n, holdout_frac=0.2, val_frac=0.25)
        tr_end, va0, va1, h0 = sp["train"][1], sp["val"][0], sp["val"][1], sp["holdout"][0]
        acf24 = float(np.corrcoef(ret[24:tr_end], ret[:tr_end - 24])[0, 1]) if tr_end > 100 else 0.0
        seasonal = (1, 0, 0, 24) if abs(acf24) > 2 / math.sqrt(max(tr_end, 1)) else (0, 0, 0, 0)
        grid = [(1, 0), (0, 1)] if budget.get("profile") == "smoke" else [(0, 0), (1, 0), (0, 1), (1, 1)]
        k = _scale(ret[:tr_end])
        z = ret * k
        best = None
        for p, q in grid:
            try:
                res, conv = _fit(z[:tr_end], (p, 0, q), "c", X[:tr_end], seasonal)
            except Exception:  # noqa: BLE001
                continue
            if conv and np.all(np.isfinite(res.params)) and (best is None or res.aic < best[0].aic):
                best = (res, (p, 0, q))
        if best is None:
            raise B.Unavailable("VALIDATION_FAILED", "żadne dopasowanie SARIMAX nie zbiegło")
        res, order = best
        ev = _unscale(_one_step_eval(z[:va1], va0, order, "c", res.params, X[:va1], seasonal), k)
        res_dev, conv = _fit(z[:h0], order, "c", X[:h0], seasonal)
        hold = _unscale(_one_step_eval(z, h0, order, "c", res_dev.params, X, seasonal), k)
        art = {"transform": "RETURNS", "order": list(order), "trend": "c", "seasonal": list(seasonal), "params": [float(x) for x in res_dev.params],
               "param_names": list(res_dev.param_names), "window": WINDOW, "profile_id": prof, "tf_s": 3600, "scale": k,
               "exog": "kalendarz: flagi sesji + sin/cos godziny (UTC) – znane z góry"}
        (tmp / "arima.json").write_text(json.dumps(art), encoding="utf-8")
        tail = bars[-(WINDOW + 1):]
        sample = self._forecast_x(art, B.closes(tail), np.asarray([b["t"] for b in tail], dtype=float))
        vm = {"val_skill_vs_zero": ev["skill_vs_zero"], "converged": 1.0 if conv else 0.0}
        return {"metrics": {"val": ev, "holdout": hold, "seasonal": seasonal, "seasonal_acf24_train": acf24, "diag_dev": _diag(res_dev),
                            "exog_scenario": "CALENDAR_KNOWN"},
                "validation": self.promotion(vm, {"converged": (">", 0.5), "val_skill_vs_zero": (">", 0.0)}),
                "sample": {"closes_tail": B.closes(tail).tolist(), "t_tail": [b["t"] for b in tail], "expected": sample, "tolerance": 1e-8}}

    def _forecast_x(self, art, c, t):
        k = float(art.get("scale") or 1.0)
        ret = np.diff(np.log(c[-(art["window"] + 1):])) * k
        tt = t[-(art["window"]):]
        X = calendar_exog(tt, art["profile_id"])
        H = max(self.HORIZONS)
        fut = calendar_exog(tt[-1] + art["tf_s"] * np.arange(1, H + 1), art["profile_id"])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            res = _arima(ret, tuple(art["order"]), art["trend"], X, tuple(art["seasonal"])).filter(np.asarray(art["params"]))
            fc = res.get_forecast(H, exog=fut)
            m, ci = np.asarray(fc.predicted_mean) / k, np.asarray(fc.conf_int(alpha=0.1)) / k
        out = {}
        for h in self.HORIZONS:
            mean = float(np.sum(m[:h]))
            sd = math.sqrt(float(np.sum(((ci[:h, 1] - ci[:h, 0]) / (2 * 1.6449)) ** 2)))
            out[str(h)] = {"mean": mean, "lo": mean - 1.6449 * sd, "hi": mean + 1.6449 * sd}
        return out

    def predict(self, art, live):
        bars = live["bars"]
        c = B.closes(bars)
        if len(c) < art["window"] + 1:
            raise B.Unavailable("BLOCKED_DATA", f"za mało świec H1: {len(c)} < {art['window'] + 1}")
        f = self._forecast_x(art, c, np.asarray([b["t"] for b in bars], dtype=float))
        h1 = f["1"]
        return {"mean": h1["mean"], "lo": h1["lo"], "hi": h1["hi"], "price_now": float(c[-1]), "horizons": f, "interval": "90% (model)",
                "exog_scenario": "CALENDAR_KNOWN"}
