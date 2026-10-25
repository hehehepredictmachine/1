"""Gaussian process regression for short-horizon log returns (PMW-MM-GPR-1). TRAINABLE (fit-based, hyper-parameters by LML).

Problem (one feature, one target, chronological arrays of CLOSED bars):  x_k = ln(C[k]/C[k-1]),  y_k = ln(C[k+h]/C[k]).
A sample k is usable at fit time T only if k-1 >= 0 and k+h <= T (its target bar has closed). The live query is x* = ln(C[T]/C[T-1]).
Standardisation (population std, floor -> scale 1.0 + DEGENERATE flag) from the fit window only; reused for the query.
Kernel Matérn 3/2: s = sqrt(3)|xi-xj|/ell, k = signal_var (1+s) exp(-s). K = k(X,X) + noise_var I (lower triangle mirrored).
Cholesky with an adaptive jitter ladder [0,1e-10,...,1e-2] applied to a fresh copy each time (jitter recorded separately from noise).
alpha = K^-1 y via two triangular solves (no inverse). Predictive mean = k*.alpha; latent var = k(x*,x*) - v.v (v = L^-1 k*), small negative
round-off clamped to 0 (raw kept, large negative -> NUMERICAL_FAULT); observed var = latent + noise_var. Back-transform: mean*y_std+y_mean,
var*y_std^2. Bands in price: base*exp(mean +- z sqrt(observed_var)). Edge in price = base*(exp(mean)-1).
LML = -0.5 y.alpha - sum(log diag L) - n/2 log(2 pi). Hyper-parameter search on a log-spaced grid with a PURE scorer (local state only);
the winning candidate is fitted into a temporary state, validated, and only then committed (all-or-nothing); a failure leaves the
previous committed fit untouched and returns FIT_FAILED (no stale forecast is served unless the caller asks for STALE_MODEL explicitly).
"""
from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass, field

import numpy as np
from scipy.linalg import solve_triangular

VERSION = "PMW-MM-GPR-1"
JITTER = (0.0, 1e-10, 1e-8, 1e-6, 1e-4, 1e-2)
ARTICLE_NOISE_GRID = (1e-6, 1e-5, 1e-4, 1e-3, 1e-2, 1e-1)
GRID_NOTE = ("y is standardised (variance 1). The article's noise grid stops at 0.1, i.e. it forces the GP to explain >= 90% of the target "
             "variance with the lag-1 feature; on short-horizon returns this produced over-confident bands (measured 1-sigma coverage 0.27 on "
             "the technical dataset). The default grid therefore extends noise_var to 0.3/1/3; the literal grid stays available as "
             "GPRConfig(grid_noise=ARTICLE_NOISE_GRID).")


@dataclass
class GPRConfig:
    window: int = 120
    horizon: int = 3
    auto_tune: bool = True
    grid_ell: tuple = (1, 2, 4, 8, 16, 32, 64)
    grid_signal: tuple = (1e-4, 1e-3, 1e-2, 1e-1, 1)
    grid_noise: tuple = (1e-6, 1e-5, 1e-4, 1e-3, 1e-2, 1e-1, 0.3, 1.0, 3.0)   # see GRID_NOTE
    ell: float = 4.0
    signal_var: float = 0.1
    noise_var: float = 1e-2
    std_floor: float = 1e-12
    jitter_degraded: float = 1e-4
    neg_var_tol: float = 1e-9
    retune_every: int = 24

    def validate(self):
        if self.window < 10 or self.horizon < 1 or self.retune_every < 1:
            raise ValueError("GPR_WINDOW_HORIZON_INVALID")
        for g in (self.grid_ell, self.grid_signal, self.grid_noise, (self.ell, self.signal_var, self.noise_var)):
            if not g or any(not (math.isfinite(v) and v > 0) for v in g):
                raise ValueError("GPR_HYPERPARAMETER_INVALID")


def matern32(a: np.ndarray, b: np.ndarray, ell: float, sv: float) -> np.ndarray:
    if not (ell > 0 and sv > 0):
        raise ValueError("GPR_KERNEL_PARAM_INVALID")
    r = np.abs(a[:, None] - b[None, :])
    s = math.sqrt(3.0) * r / ell
    return sv * (1.0 + s) * np.exp(-s)


def cholesky_ref(A: np.ndarray) -> np.ndarray | None:
    """Plain Cholesky-Banachiewicz (reference, mirrors the MQL5 core); None when not positive definite."""
    n = len(A)
    L = np.zeros_like(A)
    for i in range(n):
        for j in range(i + 1):
            s = A[i, j] - float(np.dot(L[i, :j], L[j, :j]))
            if i == j:
                if not (s > 0 and math.isfinite(s)):
                    return None
                L[i, i] = math.sqrt(s)
            else:
                L[i, j] = s / L[j, j]
    return L


def chol_jitter(K: np.ndarray, ladder=JITTER) -> tuple[np.ndarray | None, float | None, int, list]:
    tried = []
    for k, j in enumerate(ladder):
        A = K.copy()                                       # fresh copy every rung (no cumulative jitter)
        if j:
            A[np.diag_indices_from(A)] += j
        try:
            L = np.linalg.cholesky(A)
            d = np.diag(L)
            if np.all(np.isfinite(L)) and np.all(d > 0):
                tried.append(j)
                return L, j, k, tried
        except np.linalg.LinAlgError:
            pass
        tried.append(j)
    return None, None, -1, tried


def samples(c: np.ndarray, T: int, window: int, h: int) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """Training samples available at fit time T (index of the last CLOSED bar): k in [T-h-window+1, T-h], k >= 1."""
    hi = T - h
    lo = max(1, hi - window + 1)
    if hi < lo or hi - lo + 1 < window:
        return None
    k = np.arange(lo, hi + 1)
    if np.any(c[np.r_[k - 1, k, k + h]] <= 0) or not np.all(np.isfinite(c[np.r_[k - 1, k, k + h]])):
        return None
    return np.log(c[k] / c[k - 1]), np.log(c[k + h] / c[k]), k


@dataclass
class Fit:
    x: np.ndarray
    y_norm: np.ndarray
    x_mean: float
    x_std: float
    y_mean: float
    y_std: float
    ell: float
    signal_var: float
    noise_var: float
    jitter: float
    jitter_rung: int
    L: np.ndarray
    alpha: np.ndarray
    lml: float
    n: int
    fit_ts: float
    window_id: str
    health: str
    flags: list = field(default_factory=list)


def _std(v: np.ndarray, floor: float) -> tuple[float, float, bool]:
    m, s = float(v.mean()), float(v.std())
    return (m, s, False) if s > floor else (m, 1.0, True)


def score(x: np.ndarray, y: np.ndarray, ell: float, sv: float, nv: float, floor: float) -> dict:
    """PURE candidate scorer (no model state): standardise on this window, factor, LML."""
    xm, xs, dx = _std(x, floor)
    ym, ys, dy = _std(y, floor)
    xn, yn = (x - xm) / xs, (y - ym) / ys
    K = matern32(xn, xn, ell, sv)
    K = np.tril(K) + np.tril(K, -1).T
    K[np.diag_indices_from(K)] += nv
    L, j, rung, tried = chol_jitter(K)
    if L is None:
        return {"ok": False, "reason": "CHOLESKY_FAILED_ALL_RUNGS", "tried": tried}
    a = solve_triangular(L.T, solve_triangular(L, yn, lower=True), lower=False)
    lml = float(-0.5 * yn @ a - np.log(np.diag(L)).sum() - 0.5 * len(yn) * math.log(2 * math.pi))
    if not math.isfinite(lml):
        return {"ok": False, "reason": "LML_NOT_FINITE"}
    return {"ok": True, "lml": lml, "L": L, "alpha": a, "xn": xn, "yn": yn, "xm": xm, "xs": xs, "ym": ym, "ys": ys, "jitter": j, "rung": rung,
            "degenerate": dx or dy}


class GPModel:
    def __init__(self, cfg: GPRConfig | None = None):
        self.cfg = cfg or GPRConfig()
        self.cfg.validate()
        self.fit: Fit | None = None
        self.last_search: dict | None = None

    def search(self, x, y) -> dict:
        t0 = time.perf_counter()
        res, bad = [], 0
        for ell in self.cfg.grid_ell:
            for sv in self.cfg.grid_signal:
                for nv in self.cfg.grid_noise:
                    s = score(x, y, ell, sv, nv, self.cfg.std_floor)
                    if s["ok"]:
                        res.append((s["lml"], ell, sv, nv))
                    else:
                        bad += 1
        if not res:
            return {"ok": False, "reason": "NO_VALID_CANDIDATE", "failed": bad}
        res.sort(key=lambda r: (-r[0], r[1], r[2], r[3]))                 # deterministic tie order
        l = np.array([r[0] for r in res])
        return {"ok": True, "best": {"ell": res[0][1], "signal_var": res[0][2], "noise_var": res[0][3], "lml": res[0][0]}, "candidates": len(res) + bad,
                "failed": bad, "lml_spread": float(l.max() - np.median(l)), "lml_top5_spread": float(l[0] - l[min(4, len(l) - 1)]),
                "flat_surface": bool(l[0] - l[min(4, len(l) - 1)] < 0.5), "search_s": time.perf_counter() - t0}

    def refit(self, c: np.ndarray, T: int, tune: bool, window_id: str = "") -> dict:
        """Transactional: build a complete temporary fit; commit only when everything validates."""
        smp = samples(np.asarray(c, float), T, self.cfg.window, self.cfg.horizon)
        if smp is None:
            return {"ok": False, "status": "INSUFFICIENT_OR_INVALID_HISTORY"}
        x, y, _ = smp
        hp = {"ell": self.cfg.ell, "signal_var": self.cfg.signal_var, "noise_var": self.cfg.noise_var}
        if tune and self.cfg.auto_tune:
            srch = self.search(x, y)
            self.last_search = srch
            if not srch["ok"]:
                return {"ok": False, "status": "SEARCH_FAILED", "reason": srch["reason"]}
            hp = {k: srch["best"][k] for k in ("ell", "signal_var", "noise_var")}
        elif self.fit is not None and self.cfg.auto_tune:
            hp = {"ell": self.fit.ell, "signal_var": self.fit.signal_var, "noise_var": self.fit.noise_var}
        s = score(x, y, hp["ell"], hp["signal_var"], hp["noise_var"], self.cfg.std_floor)
        if not s["ok"]:
            return {"ok": False, "status": "FIT_FAILED", "reason": s["reason"]}
        flags = (["DEGENERATE_WINDOW"] if s["degenerate"] else []) + (["NUMERICALLY_DEGRADED_JITTER"] if s["jitter"] >= self.cfg.jitter_degraded else [])
        tmp = Fit(s["xn"], s["yn"], s["xm"], s["xs"], s["ym"], s["ys"], hp["ell"], hp["signal_var"], hp["noise_var"], s["jitter"], s["rung"], s["L"],
                  s["alpha"], s["lml"], len(x), time.time(), window_id, "DEGRADED" if flags else "OK", flags)
        if not (np.all(np.isfinite(tmp.L)) and np.all(np.isfinite(tmp.alpha)) and tmp.n == self.cfg.window):
            return {"ok": False, "status": "FIT_VALIDATION_FAILED"}
        self.fit = tmp                                                     # commit (single assignment = atomic)
        return {"ok": True, "status": "FITTED", "hp": hp, "lml": tmp.lml, "jitter": tmp.jitter, "health": tmp.health}

    def predict(self, x_star_raw: float, base_close: float) -> dict:
        f = self.fit
        if f is None:
            return {"status": "NOT_FITTED"}
        if not (math.isfinite(x_star_raw) and base_close > 0):
            return {"status": "INVALID_QUERY"}
        xs = (x_star_raw - f.x_mean) / f.x_std
        ks = matern32(np.array([xs]), f.x, f.ell, f.signal_var)[0]
        mn = float(ks @ f.alpha)
        v = solve_triangular(f.L, ks, lower=True)
        raw_lat = float(f.signal_var - v @ v)
        if raw_lat < -self.cfg.neg_var_tol:
            return {"status": "NUMERICAL_FAULT", "raw_latent_var_norm": raw_lat}
        lat = max(raw_lat, 0.0)
        obs = lat + f.noise_var
        m = mn * f.y_std + f.y_mean
        lv, ov = lat * f.y_std ** 2, obs * f.y_std ** 2
        sd = math.sqrt(ov)
        z = abs(m) / sd if sd > 0 else None
        return {"status": "OK" if f.health == "OK" else "DEGRADED", "mean_logret": m, "latent_var": lv, "observed_var": ov, "sd": sd,
                "band1": [m - sd, m + sd], "band2": [m - 2 * sd, m + 2 * sd],
                "price": {"base": base_close, "forecast": base_close * math.exp(m), "upper1": base_close * math.exp(m + sd), "lower1": base_close * math.exp(m - sd),
                          "upper2": base_close * math.exp(m + 2 * sd), "lower2": base_close * math.exp(m - 2 * sd)},
                "edge_price": base_close * (math.exp(m) - 1.0), "z": z, "raw_latent_var_norm": raw_lat,
                "hp": {"ell": f.ell, "signal_var": f.signal_var, "noise_var": f.noise_var}, "jitter": f.jitter, "n": f.n, "lml": f.lml,
                "std": {"x_mean": f.x_mean, "x_std": f.x_std, "y_mean": f.y_mean, "y_std": f.y_std}, "flags": f.flags}

    def state(self) -> dict:
        f = self.fit
        return {"x": f.x, "y_norm": f.y_norm, "L": f.L, "alpha": f.alpha,
                "scalars": np.array([f.x_mean, f.x_std, f.y_mean, f.y_std, f.ell, f.signal_var, f.noise_var, f.jitter, f.lml, f.n, f.fit_ts])}

    @classmethod
    def from_state(cls, cfg: GPRConfig, st: dict) -> "GPModel":
        m = cls(cfg)
        s = st["scalars"]
        m.fit = Fit(st["x"], st["y_norm"], *map(float, s[:4]), float(s[4]), float(s[5]), float(s[6]), float(s[7]), -1, st["L"], st["alpha"],
                    float(s[8]), int(s[9]), float(s[10]), "loaded", "OK")
        return m


def walk_forward(t, c, cfg: GPRConfig, start: int, stop: int, step: int = 1, ledger=None, symbol="XAUUSD", tf="M5", tf_s=300,
                 model_id="gpr_logret", artifact_id=None, cancel=None) -> dict:
    """Rolling out-of-sample forecasts for T in [start, stop) (fit on data available at T only). Every forecast is recorded (no gate
    sampling); the realised target is attached only when bar T+h exists in the data. Baselines on the same samples: zero, trailing
    mean of the fit window's targets, OLS of y on x on the fit window."""
    c = np.asarray(c, float)
    m = GPModel(cfg)
    rows, fails, since = [], {}, cfg.retune_every
    for T in range(start, stop, step):
        if cancel and cancel():
            break
        tune = since >= cfg.retune_every or m.fit is None
        r = m.refit(c, T, tune, f"{symbol}:{tf}:{T}")
        since = 0 if (tune and r["ok"]) else since + step
        if not r["ok"]:
            fails[r["status"]] = fails.get(r["status"], 0) + 1
            continue
        xq = math.log(c[T] / c[T - 1])
        p = m.predict(xq, c[T])
        if p["status"] not in ("OK", "DEGRADED"):
            fails[p["status"]] = fails.get(p["status"], 0) + 1
            continue
        smp = samples(c, T, cfg.window, cfg.horizon)
        xx, yy, _ = smp
        A = np.column_stack([np.ones_like(xx), xx])
        beta = np.linalg.lstsq(A, yy, rcond=None)[0]
        row = {"T": T, "ts": float(t[T]), "pred": p["mean_logret"], "sd": p["sd"], "lat_var": p["latent_var"], "obs_var": p["observed_var"],
               "hist_mean": float(yy.mean()), "ols": float(beta[0] + beta[1] * xq), "hp": p["hp"], "jitter": p["jitter"], "z": p["z"],
               "lml": p["lml"], "health": p["status"]}
        if T + cfg.horizon < len(c):
            row["real"] = math.log(c[T + cfg.horizon] / c[T])
        rows.append(row)
        if ledger is not None:
            ledger.log(pred_id=f"{model_id}:{symbol}:{tf}:{int(t[T])}:h{cfg.horizon}", model_id=model_id, artifact_id=artifact_id, feature_schema="GPR_LAG1_LOGRET",
                       symbol=symbol, timeframe=tf, source_ts=float(t[T]), available_at=float(t[T]) + tf_s,
                       matures_at=float(t[T]) + tf_s * (cfg.horizon + 1), horizon=f"{cfg.horizon}bars", kind="GAUSSIAN_PREDICTIVE",
                       payload={k: row[k] for k in ("pred", "sd", "lat_var", "obs_var", "z")}, quality=p["status"])
    return {"rows": rows, "failures": fails, "last_search": m.last_search, "model": m}


def calibration(rows: list[dict]) -> dict:
    sc = [r for r in rows if "real" in r]
    n = len(sc)
    if not n:
        return {"n_issued": len(rows), "n_scored": 0, "status": "NO_MATURED_FORECASTS"}
    e = np.array([r["real"] - r["pred"] for r in sc])
    sd = np.array([r["sd"] for r in sc])
    z = e / sd
    c1, c2 = float(np.mean(np.abs(z) <= 1)), float(np.mean(np.abs(z) <= 2))
    se = lambda p: math.sqrt(p * (1 - p) / n)  # noqa: E731
    real = np.array([r["real"] for r in sc])
    mae = lambda p: float(np.mean(np.abs(real - p)))  # noqa: E731
    rmse = lambda p: float(np.sqrt(np.mean((real - p) ** 2)))  # noqa: E731
    gp = np.array([r["pred"] for r in sc])
    zero = np.zeros(n)
    hm = np.array([r["hist_mean"] for r in sc])
    ols = np.array([r["ols"] for r in sc])
    jit = {}
    for r in sc:
        jit[str(r["jitter"])] = jit.get(str(r["jitter"]), 0) + 1
    ells = {}
    for r in sc:
        ells[str(r["hp"]["ell"])] = ells.get(str(r["hp"]["ell"]), 0) + 1
    return {"n_issued": len(rows), "n_scored": n, "coverage_1sd": c1, "coverage_1sd_se": se(c1), "coverage_2sd": c2, "coverage_2sd_se": se(c2),
            "nominal_1sd": 0.6827, "nominal_2sd": 0.9545, "coverage_gap_1sd": c1 - 0.6827, "coverage_gap_2sd": c2 - 0.9545,
            "width_2sd_median": float(np.median(4 * sd)), "mae": {"gp": mae(gp), "zero": mae(zero), "hist_mean": mae(hm), "ols": mae(ols)},
            "rmse": {"gp": rmse(gp), "zero": rmse(zero), "hist_mean": rmse(hm), "ols": rmse(ols)}, "err_mean": float(e.mean()), "err_median": float(np.median(e)),
            "z_mean": float(z.mean()), "z_std": float(z.std()), "jitter_counts": jit, "ell_counts": ells,
            "inconclusive": n < 200}
