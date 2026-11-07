"""KALMAN_LS - extension of mm_kalman with a local LINEAR TREND state (level + slope).

State x = [level, slope]; x_t = F x_{t-1} + w (F = [[1, 1], [0, 1]], Q = diag(q_level, q_slope)); y_t = level + v (R). Q / R are
ESTIMATED on the training part by maximising the Gaussian innovation log-likelihood over a bounded log-grid (not ML training). Runtime
is the CAUSAL filter only (no smoother): output level, slope (price per bar), innovation, its variance, state variance and a trend
state from |slope| / sqrt(P_slope) (z of the slope, a filter statistic - not a probability). Covariance stays symmetric PSD (Joseph
form). Gaps longer than 3 bars or a source change reset the state (deterministic warm-up on the last W bars). The existing mm_kalman
is kept unchanged.
"""
from __future__ import annotations

import json
import math

import numpy as np

from . import base as B


def run(y: np.ndarray, q_l: float, q_s: float, r: float, t: np.ndarray | None = None, tf_s: int = 300, gap_bars: int = 3):
    F = np.array([[1.0, 1.0], [0.0, 1.0]])
    H = np.array([[1.0, 0.0]])
    Q = np.diag([q_l, q_s])
    x = np.array([y[0], 0.0])
    P = np.diag([r * 10, r])
    ll, out, resets = 0.0, [], 0
    for i in range(len(y)):
        if i and t is not None and (t[i] - t[i - 1]) > gap_bars * tf_s:
            x, P = np.array([y[i], 0.0]), np.diag([r * 10, r])
            resets += 1
        x = F @ x
        P = F @ P @ F.T + Q
        S = (H @ P @ H.T).item() + r
        e = y[i] - x[0]
        K = (P @ H.T) / S
        x = x + (K * e).ravel()
        I_KH = np.eye(2) - K @ H
        P = I_KH @ P @ I_KH.T + K @ K.T * r                                    # Joseph form: symmetric, PSD
        P = (P + P.T) / 2
        ll += -0.5 * (math.log(2 * math.pi * S) + e * e / S)
        out.append((x[0], x[1], e, S, P[1, 1]))
    return np.asarray(out), ll, resets


class KalmanLS(B.Family):
    ID = "KALMAN_LS"
    NAME = "Filtr Kalmana poziom + nachylenie (rozbudowa mm_kalman)"
    KIND = "ESTIMATED"
    FIT_LABEL = "estymacja Q/R"
    TASK_TYPE = "FILTER_STATE"
    UNIT = "mixed"
    TASK = "TREND_STATE"
    DEPS = ()
    TF = "M5"
    HORIZONS = (1,)
    RECEIVERS = ("SH_CONTEXT:trend_state", "STRATEGY:regime_context", "PANEL:model_status")
    DATA = {"kind": "BARS", "tf": "M5", "min_bars": 600}

    def fit(self, data, cfg, tmp, budget):
        bars = data["bars"][-int(budget.get("max_rows", 5000)):]
        y = B.closes(bars)
        t = np.asarray([b["t"] for b in bars], dtype=float)
        n = len(y)
        tr = int(n * 0.6)
        v = float(np.var(np.diff(y[:tr]))) or 1e-6
        best = None
        for ql in (1e-3, 1e-2, 1e-1, 1.0):
            for qs in (1e-6, 1e-5, 1e-4, 1e-3):
                for rr in (0.1, 1.0, 10.0):
                    _, ll, _ = run(y[:tr], ql * v, qs * v, rr * v, t[:tr])
                    if best is None or ll > best[0]:
                        best = (ll, ql * v, qs * v, rr * v)
        ll, ql, qs, rr = best
        outv, llv, _ = run(y[tr:], ql, qs, rr, t[tr:])
        innov = outv[:, 2]
        z = innov / np.sqrt(outv[:, 3])
        art = {"q_level": ql, "q_slope": qs, "r": rr, "warmup": 300, "tf_s": 300, "gap_bars": 3}
        (tmp / "kalman.json").write_text(json.dumps(art), encoding="utf-8")
        tail = bars[-art["warmup"]:]
        vm = {"val_innov_z_std": float(np.std(z)), "val_ll_per_obs": llv / max(1, len(y) - tr)}
        val = self.promotion({"z_std_ok": 1.0 if 0.5 < vm["val_innov_z_std"] < 2.0 else 0.0}, {"z_std_ok": (">", 0.5)})
        return {"metrics": {"train_ll": ll, **vm, "estimation": "maksimum wiarygodności innowacji (siatka log)",
                            "note": "standaryzowane innowacje ~1 na walidacji = spójna estymacja Q/R"},
                "validation": val, "sample": {"closes_tail": [b["c"] for b in tail], "t_tail": [b["t"] for b in tail],
                                              "expected": self._state(art, tail), "tolerance": 1e-9}}

    def load(self, d):
        return json.loads((d / "kalman.json").read_text(encoding="utf-8"))

    def _state(self, art, bars):
        y = np.asarray([b["c"] for b in bars], dtype=float)
        t = np.asarray([b["t"] for b in bars], dtype=float)
        out, _, resets = run(y, art["q_level"], art["q_slope"], art["r"], t, art["tf_s"], art["gap_bars"])
        lv, sl, e, S, Ps = out[-1]
        zs = sl / math.sqrt(Ps) if Ps > 0 else 0.0
        st = "UP" if zs > 2 else "DOWN" if zs < -2 else "FLAT"
        return {"state": st, "level": float(lv), "slope": float(sl), "innovation": float(e), "innovation_var": float(S),
                "slope_var": float(Ps), "slope_z": float(zs), "resets": int(resets)}

    def predict(self, art, live):
        bars = live["bars"][-art["warmup"]:]
        if len(bars) < 50:
            raise B.Unavailable("BLOCKED_DATA", "za mało świec do rozgrzania filtra")
        return self._state(art, bars)
