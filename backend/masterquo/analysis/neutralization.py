"""SIGNAL_NEUTRALIZATION_ROLLING_V1 (PMW-UPD-08 R17) - rolling OLS regression of a RAW signal on chosen factors.

Distinct from FEATURE_RESIDUALIZATION_COMPAT_V1 (the old M08 LOGREG_NEUTRALIZED column transform in lab/protocol.py, kept unchanged).
Order per step (live, training, replay, panel, export alike): take s_t, f_t -> score with beta fitted ONLY on earlier rows (window W_t of
the last N qualifying observations, current t excluded) -> record -> only then append t and refit for the next step.
  D = [1, standardised factors] on W_t;  beta_t = lstsq(D, s(W_t)) (SVD, rcond 1e-10, max condition 1e8 on the standardised D)
  exposure_t = beta0 + standardised(f_t; scaler of W_t) @ beta[1:];  residual_t = s_t - exposure_t;  partial_t = s_t - alpha*exposure_t
With full OLS + intercept, D.T @ e_fit ~ 0 and mean(e_fit) ~ 0 hold for the FITTED window only - never asserted for later observations.
Residual = part not described by the chosen LINEAR factors in the fit: it can contain noise, omitted factors or a useful trend; it is
not automatically alpha. z-scores use the earlier raw / prequential residual stream (the current value never scales itself);
near-zero variance -> DEGENERATE_RESIDUAL and z = null. Failed / degenerate fits are named states (WARMUP, CONSTANT_FACTOR, SINGULAR,
STALE_BETA, NAN_INPUT) with eligible = false; the last good beta may be shown for preview with its age, never as a fresh fit.
Reference signal ROC20 = C_t / C_(t-20) - 1; factors: volatility = ATR14 / C_t, trend_slope = (EMA50_t - EMA50_(t-5)) / C_t.
Model score adapter: log((p_up + 1e-6) / (p_down + 1e-6)) - NOT a probability.
"""
from __future__ import annotations

import hashlib
import json
import math

import numpy as np

PROFILE = "SIGNAL_NEUTRALIZATION_ROLLING_V1"
LEGACY = "FEATURE_RESIDUALIZATION_COMPAT_V1"
DEFAULT = {"window": 240, "min_obs": 60, "rcond": 1e-10, "max_cond": 1e8, "const_rel_tol": 1e-9, "alphas": [0.0, 0.5, 1.0], "z_window": 240,
           "max_gap_s": 3600.0, "grace_steps": 0, "factors": ["volatility", "trend_slope"]}


def roc20(c: list[float]) -> list:
    return [None if i < 20 or not c[i - 20] else c[i] / c[i - 20] - 1.0 for i in range(len(c))]


def _ema(x: list[float], n: int) -> list:
    out, k, e = [], 2.0 / (n + 1), None
    for i, v in enumerate(x):
        e = v if e is None else e + k * (v - e)
        out.append(e if i >= n - 1 else None)
    return out


def factors(h: list[float], lo: list[float], c: list[float]) -> dict[str, list]:
    from .structure_v2 import atr_series
    a = atr_series(h, lo, c)
    e = _ema(c, 50)
    vol = [None if a[i] is None else a[i] / c[i] for i in range(len(c))]
    slope = [None if i < 5 or e[i] is None or e[i - 5] is None else (e[i] - e[i - 5]) / c[i] for i in range(len(c))]
    return {"volatility": vol, "trend_slope": slope}


def model_score(p_up: float, p_down: float, eps: float = 1e-6) -> float:
    return math.log((p_up + eps) / (p_down + eps))


def _corr(a: np.ndarray, b: np.ndarray):
    if len(a) < 3 or np.std(a) <= 1e-15 or np.std(b) <= 1e-15:
        return None
    return float(np.corrcoef(a, b)[0, 1])


class RollingNeutralizer:
    def __init__(self, signal_id: str, model_version: str, context: str, cfg: dict | None = None):
        self.cfg = dict(DEFAULT, **(cfg or {}))
        self.signal_id, self.model_version, self.context = signal_id, model_version, context
        self.config_hash = hashlib.sha256(json.dumps({**self.cfg, "s": signal_id, "m": model_version}, sort_keys=True).encode()).hexdigest()[:16]
        self.reset("INIT")

    def reset(self, reason: str) -> None:
        self.S, self.F, self.T = [], [], []                  # ring buffer of qualifying earlier observations
        self.raw_hist, self.res_hist = [], []                # earlier raw / prequential residual streams (z-scores)
        self.fit = None
        self.fail_streak, self.last_t, self.seq = 0, None, 0
        self.last_reset = reason
        self.last_good = None

    # ------------------------------------------------------------ fit on the CURRENT buffer (= rows before the next t)
    def _refit(self) -> dict:
        c = self.cfg
        n = len(self.S)
        if n < c["min_obs"]:
            return {"status": "WARMUP", "n": n}
        F = np.array(self.F, float)
        s = np.array(self.S, float)
        mu, sd = F.mean(axis=0), F.std(axis=0)
        scale = np.maximum(np.abs(mu), 1.0)
        if np.any(sd <= c["const_rel_tol"] * scale):
            return {"status": "CONSTANT_FACTOR", "n": n, "factor_sd": sd.tolist()}
        D = np.hstack([np.ones((n, 1)), (F - mu) / sd])
        beta, _, rank, sv = np.linalg.lstsq(D, s, rcond=c["rcond"])
        cond = float(sv[0] / sv[-1]) if sv[-1] > 0 else float("inf")
        if rank < D.shape[1] or cond > c["max_cond"]:
            return {"status": "SINGULAR", "n": n, "rank": int(rank), "condition": cond}
        e = s - D @ beta
        ss_tot = float(np.sum((s - s.mean()) ** 2))
        return {"status": "OK", "n": n, "beta": beta.tolist(), "mu": mu.tolist(), "sd": sd.tolist(), "rank": int(rank), "condition": cond,
                "singular_values": sv.tolist(), "r2_in_sample": None if ss_tot <= 0 else 1.0 - float(np.sum(e ** 2)) / ss_tot,
                "orthogonality_max_abs": float(np.max(np.abs(D.T @ e))) / max(1.0, float(np.sqrt(np.sum(s ** 2)))),
                "mean_residual_fit": float(e.mean()), "fit_end": self.T[-1], "fit_id": hashlib.sha256(f"{self.config_hash}|{self.T[0]}|{self.T[-1]}|{n}".encode()).hexdigest()[:12]}

    def _z(self, hist: list, x: float):
        w = np.array(hist[-self.cfg["z_window"]:], float)
        if len(w) < self.cfg["min_obs"]:
            return None, "WARMUP"
        sd = float(w.std())
        if sd <= 1e-12 * max(1.0, abs(float(w.mean()))):
            return None, "DEGENERATE_RESIDUAL"
        return (x - float(w.mean())) / sd, None

    # ------------------------------------------------------------ one step: score BEFORE update
    def step(self, t: float, s: float | None, f: dict, available_at: str | None = None) -> dict:
        c = self.cfg
        if self.last_t is not None and t <= self.last_t:
            return {"status": "DUPLICATE_OR_OLD", "t": t, "eligible": False}                 # idempotent replay
        if self.last_t is not None and t - self.last_t > c["max_gap_s"]:
            self.reset("GAP")
        vals = [f.get(k) for k in c["factors"]]
        bad = s is None or any(v is None for v in vals) or not all(math.isfinite(float(v)) for v in vals + [s])
        out = {"profile": PROFILE, "signal_id": self.signal_id, "model_version": self.model_version, "context": self.context, "t": t,
               "available_at": available_at, "raw": s, "factors": dict(zip(c["factors"], vals)), "config_hash": self.config_hash}
        fit = self.fit
        if bad:
            out.update(status="NAN_INPUT", eligible=False, exposure=None, residual=None)
        elif fit is None or fit["status"] != "OK":
            st = (fit or {"status": "WARMUP"})["status"]
            if self.last_good is not None and st != "WARMUP":
                st = "STALE_BETA"
            out.update(status=st, eligible=False, exposure=None, residual=None, fit=fit, last_good_fit_end=(self.last_good or {}).get("fit_end"))
        else:
            z = (np.array(vals, float) - np.array(fit["mu"])) / np.array(fit["sd"])
            expo = float(fit["beta"][0] + z @ np.array(fit["beta"][1:]))
            res = float(s - expo)
            zr, zr_st = self._z(self.res_hist, res)
            zw, zw_st = self._z(self.raw_hist, float(s))
            out.update(status="OK" if zr_st is None else zr_st, eligible=zr_st is None, exposure=expo, residual=res,
                       partial={str(a): float(s - a * expo) for a in c["alphas"]}, z_residual=zr, z_raw=zw, fit_id=fit["fit_id"], fit_end=fit["fit_end"],
                       beta=fit["beta"], rank=fit["rank"], condition=fit["condition"], r2_in_sample=fit["r2_in_sample"],
                       orthogonality_fit=fit["orthogonality_max_abs"], fit_age_s=t - fit["fit_end"])
            self.res_hist.append(res)
        # ---- update AFTER scoring
        if not bad:
            self.S.append(float(s))
            self.F.append([float(v) for v in vals])
            self.T.append(t)
            self.raw_hist.append(float(s))
            if len(self.S) > c["window"]:
                self.S.pop(0), self.F.pop(0), self.T.pop(0)
            self.raw_hist = self.raw_hist[-c["z_window"]:]
            self.res_hist = self.res_hist[-c["z_window"]:]
            self.fit = self._refit()
            if self.fit["status"] == "OK":
                self.fail_streak, self.last_good = 0, self.fit
            elif self.fit["status"] != "WARMUP":
                self.fail_streak += 1
        self.last_t = t
        self.seq += 1
        out["seq"], out["fail_streak"] = self.seq, self.fail_streak
        return out

    # ------------------------------------------------------------ persistence (checkpoint) and diagnostics
    def state(self) -> dict:
        return {"profile": PROFILE, "cfg": self.cfg, "signal_id": self.signal_id, "model_version": self.model_version, "context": self.context,
                "S": self.S, "F": self.F, "T": self.T, "raw_hist": self.raw_hist, "res_hist": self.res_hist, "fit": self.fit, "last_good": self.last_good,
                "fail_streak": self.fail_streak, "last_t": self.last_t, "seq": self.seq, "config_hash": self.config_hash}

    @classmethod
    def load(cls, st: dict, signal_id: str, model_version: str, context: str) -> "RollingNeutralizer":
        n = cls(signal_id, model_version, context, st.get("cfg"))
        if st.get("signal_id") != signal_id or st.get("model_version") != model_version or st.get("context") != context or st.get("config_hash") != n.config_hash:
            n.reset("VERSION_OR_CONTEXT_CHANGE")
            return n
        for k in ("S", "F", "T", "raw_hist", "res_hist", "fit", "last_good", "fail_streak", "last_t", "seq"):
            setattr(n, k, st[k])
        return n


def run_series(t: list[float], s: list, fac: dict[str, list], signal_id: str = "ROC20", model_version: str = "DETERMINISTIC",
               context: str = "", cfg: dict | None = None) -> list[dict]:
    nz = RollingNeutralizer(signal_id, model_version, context, cfg)
    return [nz.step(t[i], s[i], {k: v[i] for k, v in fac.items()}) for i in range(len(t))]


def diagnostics(rows: list[dict], fac_names: list[str]) -> dict:
    """Prequential (out-of-fit) correlations of raw and residual with the factors over the scored rows - may be non-zero (drift)."""
    ok = [r for r in rows if r.get("residual") is not None]
    out = {"scored": len(ok), "rows": len(rows), "states": {}}
    for r in rows:
        out["states"][r["status"]] = out["states"].get(r["status"], 0) + 1
    if len(ok) >= 3:
        raw = np.array([r["raw"] for r in ok])
        res = np.array([r["residual"] for r in ok])
        for k in fac_names:
            f = np.array([r["factors"][k] for r in ok])
            out[f"prequential_corr_raw_{k}"] = _corr(raw, f)
            out[f"prequential_corr_residual_{k}"] = _corr(res, f)
        b = np.array([r["beta"] for r in ok])
        out["beta_drift_std"] = b.std(axis=0).tolist()
    out["note"] = "korelacje poza dopasowaniem mogą być niezerowe (drift relacji); ortogonalność gwarantowana tylko w oknie fit"
    return out
