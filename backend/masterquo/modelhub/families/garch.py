"""VOL_GARCH (arch) - conditional volatility of log returns, compared with EWMA and historical baselines.

Scale is explicit everywhere: arch is fitted on PERCENT returns (100 x log return, numerically stable); every output is converted back
to DECIMAL and labelled: sigma_bar (per bar), sigma_h (over H bars = sqrt of the summed forecast variances), variance_h and the price
move sigma_h x price. Distribution (normal vs Student-t) is chosen on development data by QLIKE against the squared-return proxy -
never by the holdout. A fit is accepted only when the optimiser converged, alpha + beta < 1 (stationary), omega > 0 and all
parameters are finite; otherwise VALIDATION_FAILED and the risk receiver keeps its own volatility.
The output is a volatility forecast, not a BUY/SELL vote. The risk receiver may use it inside the existing limits only (it never
raises the allowed risk and never moves an existing stop to hide a loss).
"""
from __future__ import annotations

import json
import math
import warnings

import numpy as np

from . import base as B


def _qlike(var_f: np.ndarray, r2: np.ndarray) -> float:
    v = np.maximum(var_f, 1e-18)
    return float(np.mean(r2 / v - np.log(r2 / v + 1e-300) - 1))


def ewma_var(r: np.ndarray, lam: float = 0.94) -> np.ndarray:
    """One-step-ahead EWMA variance: v[t] forecasts r[t]^2 from r[:t]."""
    v = np.empty(len(r))
    v[0] = np.var(r[: min(50, len(r))]) if len(r) > 1 else r[0] ** 2
    for i in range(1, len(r)):
        v[i] = lam * v[i - 1] + (1 - lam) * r[i - 1] ** 2
    return v


def garch_filter(r_pct: np.ndarray, omega, alpha, beta) -> np.ndarray:
    """One-step-ahead conditional variance (percent^2) with fixed params."""
    v = np.empty(len(r_pct))
    v[0] = omega / max(1e-12, 1 - alpha - beta) if alpha + beta < 1 else np.var(r_pct)
    for i in range(1, len(r_pct)):
        v[i] = omega + alpha * r_pct[i - 1] ** 2 + beta * v[i - 1]
    return v


class GARCH(B.Family):
    ID = "VOL_GARCH"
    NAME = "GARCH(1,1) (arch) – zmienność warunkowa"
    KIND = "TRAINED"
    TASK_TYPE = "VOLATILITY"
    UNIT = "sigma_return"
    TASK = "SIGMA_LOG_RETURN_H"
    DEPS = ("arch", "scipy")
    TF = "M5"
    HORIZONS = (1, 6, 12)
    RECEIVERS = ("RISK:volatility_scenario", "SH_CONTEXT:volatility", "PANEL:model_status")
    DATA = {"kind": "BARS", "tf": "M5", "min_bars": 1000}

    def fit(self, data, cfg, tmp, budget):
        from arch import arch_model
        c = B.closes(data["bars"])[-int(budget.get("max_rows", 6000)):]
        r = np.diff(np.log(c))
        rp = 100.0 * r
        n = len(rp)
        sp = B.chrono_split(n, holdout_frac=0.2, val_frac=0.25)
        tr_end, va0, va1, h0 = sp["train"][1], sp["val"][0], sp["val"][1], sp["holdout"][0]
        cands = []
        for dist in ("normal", "t"):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                res = arch_model(rp[:tr_end], mean="Zero", vol="GARCH", p=1, q=1, dist=dist, rescale=False).fit(disp="off")
            pr = res.params
            om, al, be = float(pr["omega"]), float(pr["alpha[1]"]), float(pr["beta[1]"])
            ok = res.convergence_flag == 0 and all(map(math.isfinite, (om, al, be))) and om > 0 and al >= 0 and be >= 0 and al + be < 1
            v = garch_filter(rp[:va1], om, al, be)[va0:va1] / 1e4
            q = _qlike(v, r[va0:va1] ** 2) if ok else float("inf")
            cands.append({"dist": dist, "omega": om, "alpha": al, "beta": be, "nu": float(pr["nu"]) if "nu" in pr else None, "converged": ok,
                          "val_qlike": q, "persistence": al + be})
        ew = ewma_var(r[:va1])[va0:va1]
        hist = np.full(va1 - va0, np.var(r[:tr_end]))
        base = {"val_qlike_ewma": _qlike(ew, r[va0:va1] ** 2), "val_qlike_hist": _qlike(hist, r[va0:va1] ** 2)}
        good = [c for c in cands if c["converged"]]
        if not good:
            raise B.Unavailable("VALIDATION_FAILED", "GARCH nie zbiegł lub niestacjonarny (alpha+beta >= 1)")
        pick = min(good, key=lambda c: c["val_qlike"])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            res = arch_model(rp[:h0], mean="Zero", vol="GARCH", p=1, q=1, dist=pick["dist"], rescale=False).fit(disp="off")
        pr = res.params
        om, al, be = float(pr["omega"]), float(pr["alpha[1]"]), float(pr["beta[1]"])
        conv = res.convergence_flag == 0 and om > 0 and al + be < 1
        hv = garch_filter(rp, om, al, be)[h0:] / 1e4
        hold = {"qlike": _qlike(hv, r[h0:] ** 2), "mse_var": float(np.mean((hv - r[h0:] ** 2) ** 2)),
                "qlike_ewma": _qlike(ewma_var(r)[h0:], r[h0:] ** 2), "proxy": "kwadrat log-zwrotu (zaszumione proxy wariancji zrealizowanej)"}
        art = {"dist": pick["dist"], "omega": om, "alpha": al, "beta": be, "scale": "percent_internal", "window": 2000}
        (tmp / "garch.json").write_text(json.dumps(art), encoding="utf-8")
        tail = c[-(art["window"] + 1):]
        vm = {"converged": 1.0 if conv else 0.0, "val_qlike_gain_vs_ewma": base["val_qlike_ewma"] - pick["val_qlike"]}
        return {"metrics": {"candidates": cands, "baselines": base, "holdout": hold, "chosen_dist": pick["dist"]},
                "validation": self.promotion(vm, {"converged": (">", 0.5), "val_qlike_gain_vs_ewma": (">", 0.0)}),
                "sample": {"closes_tail": tail.tolist(), "expected": self._forecast(art, tail), "tolerance": 1e-9}}

    def load(self, d):
        return json.loads((d / "garch.json").read_text(encoding="utf-8"))

    def _forecast(self, art, c):
        r = np.diff(np.log(np.asarray(c, dtype=float)[-(art["window"] + 1):])) * 100.0
        om, al, be = art["omega"], art["alpha"], art["beta"]
        v = garch_filter(r, om, al, be)
        nxt = om + al * r[-1] ** 2 + be * v[-1]
        ub = om / (1 - al - be)
        out = {}
        for h in self.HORIZONS:
            vs = [ub + (al + be) ** k * (nxt - ub) for k in range(h)]          # E[sigma^2_{t+k}] of GARCH(1,1)
            var_h = float(sum(vs)) / 1e4                                       # percent^2 -> decimal^2
            out[str(h)] = {"variance": var_h, "sigma": math.sqrt(var_h)}
        return {"sigma_bar": math.sqrt(nxt / 1e4), "horizons": out}

    def predict(self, art, live):
        c = B.closes(live["bars"])
        if len(c) < 200:
            raise B.Unavailable("BLOCKED_DATA", "za mało świec do filtra GARCH")
        f = self._forecast(art, c)
        H = str(self.HORIZONS[1])
        s = f["horizons"][H]["sigma"]
        return {"sigma": s, "variance": f["horizons"][H]["variance"], "scale": "decimal", "sigma_bar": f["sigma_bar"], "horizon_bars": int(H),
                "price_move_1sigma": float(c[-1] * s), "horizons": f["horizons"],
                "note": "sigma log-zwrotu (ułamek dziesiętny) na horyzont; ruch ceny = sigma × cena"}
