"""Scalar local-level Kalman filter + closed-bar fast/slow crossover (PMW-MM-KALMAN-1). RECURSIVE_FILTER - no training.

Model (y_t = closed-bar close):  predict  x_{t|t-1} = x_{t-1|t-1},  P_{t|t-1} = P_{t-1|t-1} + Q
                                 update   K_t = P_{t|t-1} / (P_{t|t-1} + R),  x_{t|t} = x_{t|t-1} + K_t (y_t - x_{t|t-1}),  P_{t|t} = (1-K_t) P_{t|t-1}
Q, R are variances in price units squared (not smoothing coefficients). Initialisation: the first valid close sets x = y and P = P0;
that observation is NOT also used as a measurement update. Steady-state gain: P_pred solves P^2 - Q P - Q R = 0, i.e.
P_pred = (Q + sqrt(Q^2 + 4QR)) / 2 and K = P_pred / (P_pred + R)  (Q=1,R=0.2 -> 0.854; Q=0.005,R=0.2 -> 0.146).

Crossover: direction per closed bar FAST>SLOW (+1) / FAST<SLOW (-1) / |diff|<=tol (0). A direction is ACCEPTED after `confirm_bars`
consecutive closed bars with that direction and an accepted state that was not already that direction. The first accepted state after
start-up is a silent baseline (no event) unless `emit_startup_signal`: the history window starting with fast>slow is not a crossover.
Each bar time is processed exactly once (repeated calls for the same / an older bar are ignored); invalid input resets the candidate.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

VERSION = "PMW-MM-KALMAN-1"
STATES = ("INITIALIZING", "INSUFFICIENT_HISTORY", "NEUTRAL", "BULLISH_CANDIDATE", "BEARISH_CANDIDATE", "BULLISH_CONFIRMED",
          "BEARISH_CONFIRMED", "INVALID_INPUT")


def steady_state_gain(Q: float, R: float) -> float:
    pp = (Q + math.sqrt(Q * Q + 4 * Q * R)) / 2.0
    return pp / (pp + R)


class LocalLevel:
    def __init__(self, Q: float, R: float, P0: float = 1.0):
        for n, v in (("Q", Q), ("R", R), ("P0", P0)):
            if not (isinstance(v, (int, float)) and math.isfinite(v) and v >= 0):
                raise ValueError(f"KALMAN_PARAM_INVALID:{n}={v}")
        if R <= 0:
            raise ValueError("KALMAN_PARAM_INVALID:R must be > 0")
        self.Q, self.R, self.P0 = float(Q), float(R), float(P0)
        self.reset()

    def reset(self):
        self.x = None
        self.P = None
        self.K = None
        self.P_pred = None
        self.n = 0
        self.error = None

    def step(self, y: float) -> dict:
        if not (isinstance(y, (int, float)) and math.isfinite(y) and y > 0):
            return {"ok": False, "status": "INVALID_INPUT", "x": self.x, "P": self.P, "K": None}   # state untouched (not poisoned)
        if self.x is None:
            self.x, self.P, self.n = float(y), self.P0, 1
            return {"ok": True, "status": "INITIALIZED", "x": self.x, "P": self.P, "K": None, "P_pred": None}
        x_pred, P_pred = self.x, self.P + self.Q
        den = P_pred + self.R
        K = P_pred / den
        x = x_pred + K * (y - x_pred)
        P = (1.0 - K) * P_pred
        if not (math.isfinite(x) and math.isfinite(P) and math.isfinite(K)) or P < -1e-15 or not (0.0 <= K <= 1.0):
            self.error = f"NUMERICAL_FAULT x={x} P={P} K={K}"
            return {"ok": False, "status": "NUMERICAL_FAULT", "x": self.x, "P": self.P, "K": None}
        self.x, self.P, self.K, self.P_pred, self.n = x, max(P, 0.0), K, P_pred, self.n + 1
        return {"ok": True, "status": "UPDATED", "x": x, "P": self.P, "K": K, "P_pred": P_pred}


@dataclass
class CrossConfig:
    Q_fast: float = 1.0
    Q_slow: float = 0.005
    R_fast: float = 0.2
    R_slow: float = 0.2
    P0: float = 1.0
    confirm_bars: int = 2
    tolerance: float = 0.0
    warmup_bars: int = 20
    emit_startup_signal: bool = False

    def validate(self):
        if not (isinstance(self.confirm_bars, int) and 1 <= self.confirm_bars <= 50):
            raise ValueError("KALMAN_CONFIRM_BARS_INVALID")
        if self.tolerance < 0 or self.warmup_bars < 1:
            raise ValueError("KALMAN_TOLERANCE_OR_WARMUP_INVALID")
        LocalLevel(self.Q_fast, self.R_fast, self.P0), LocalLevel(self.Q_slow, self.R_slow, self.P0)


@dataclass
class KalmanCross:
    cfg: CrossConfig = field(default_factory=CrossConfig)

    def __post_init__(self):
        self.cfg.validate()
        self.fast = LocalLevel(self.cfg.Q_fast, self.cfg.R_fast, self.cfg.P0)
        self.slow = LocalLevel(self.cfg.Q_slow, self.cfg.R_slow, self.cfg.P0)
        self.last_bar_time = None
        self.state = "INITIALIZING"
        self.cand_dir, self.cand_n = 0, 0
        self.accepted = 0
        self.baseline_set = False
        self.events: list[dict] = []
        self.bars = 0

    def update(self, bar_time: float, close: float) -> dict:
        if self.last_bar_time is not None and bar_time <= self.last_bar_time:
            return {"processed": False, "reason": "BAR_ALREADY_PROCESSED", "state": self.state}
        self.last_bar_time = bar_time
        a, b = self.fast.step(close), self.slow.step(close)
        row = {"processed": True, "bar_time": bar_time, "close": close, "fast": self.fast.x, "slow": self.slow.x, "K_fast": a.get("K"),
               "K_slow": b.get("K"), "P_fast": self.fast.P, "P_slow": self.slow.P, "event": None}
        if not (a["ok"] and b["ok"]):
            self.state = "INVALID_INPUT"
            self.cand_dir, self.cand_n = 0, 0                    # a candidate never survives an invalid bar
            row.update(state=self.state, cand_n=0, quality="INVALID")
            return row
        self.bars += 1
        if self.bars < self.cfg.warmup_bars:
            self.state = "INSUFFICIENT_HISTORY"
            row.update(state=self.state, cand_n=0, quality="WARMUP")
            return row
        diff = self.fast.x - self.slow.x
        d = 0 if abs(diff) <= self.cfg.tolerance else (1 if diff > 0 else -1)
        if d == 0:
            self.cand_dir, self.cand_n = 0, 0
            self.state = "NEUTRAL" if self.accepted == 0 else ("BULLISH_CONFIRMED" if self.accepted > 0 else "BEARISH_CONFIRMED")
        elif d == self.accepted:
            self.cand_dir, self.cand_n = 0, 0
        else:
            self.cand_n = self.cand_n + 1 if d == self.cand_dir else 1
            self.cand_dir = d
            self.state = "BULLISH_CANDIDATE" if d > 0 else "BEARISH_CANDIDATE"
            if self.cand_n >= self.cfg.confirm_bars:
                silent = not self.baseline_set and not self.cfg.emit_startup_signal
                self.accepted, self.baseline_set = d, True
                self.state = "BULLISH_CONFIRMED" if d > 0 else "BEARISH_CONFIRMED"
                self.cand_dir, self.cand_n = 0, 0
                if not silent:
                    ev = {"event_id": f"KX-{int(bar_time)}-{'BULL' if d > 0 else 'BEAR'}", "bar_time": bar_time,
                          "direction": "BULLISH" if d > 0 else "BEARISH", "fast": self.fast.x, "slow": self.slow.x, "version": VERSION}
                    self.events.append(ev)
                    row["event"] = ev
                else:
                    row["event"] = None
                    row["baseline"] = "STARTUP_BASELINE"
        if self.accepted and d == self.accepted:
            self.state = "BULLISH_CONFIRMED" if d > 0 else "BEARISH_CONFIRMED"
        row.update(state=self.state, cand_n=self.cand_n, direction_raw=d, accepted=self.accepted, quality="OK")
        return row


def run(t, c, cfg: CrossConfig | None = None) -> tuple[KalmanCross, list[dict]]:
    k = KalmanCross(cfg or CrossConfig())
    return k, [k.update(float(a), float(b)) for a, b in zip(t, c)]


def evaluate(t, c, cfg: CrossConfig, horizon: int = 12, whipsaw_bars: int = 6, cost: float = 0.0) -> dict:
    """Crossover statistics on closed bars: frequency, whipsaw (opposite event within N bars), time in each accepted direction and the
    forward h-bar log return after each event (signed by direction, minus a fixed cost in log units). Analytical, not a backtest of orders."""
    import numpy as np
    k, rows = run(t, c, cfg)
    c = np.asarray(c, float)
    idx = {r["bar_time"]: i for i, r in enumerate(rows) if r.get("processed")}
    ev = k.events
    fwd = []
    for e in ev:
        i = idx[e["bar_time"]]
        if i + horizon < len(c):
            s = 1 if e["direction"] == "BULLISH" else -1
            fwd.append(s * math.log(c[i + horizon] / c[i]) - cost)
    whip = sum(1 for a, b in zip(ev, ev[1:]) if idx[b["bar_time"]] - idx[a["bar_time"]] <= whipsaw_bars)
    acc = [r.get("accepted", 0) for r in rows if r.get("processed")]
    return {"bars": len(rows), "events": len(ev), "events_per_1000_bars": 1000.0 * len(ev) / max(1, len(rows)), "whipsaw_events": whip,
            "share_bull": float(np.mean([a == 1 for a in acc])) if acc else None, "share_bear": float(np.mean([a == -1 for a in acc])) if acc else None,
            "fwd_n": len(fwd), "fwd_mean_logret": float(np.mean(fwd)) if fwd else None,
            "fwd_hit_rate": float(np.mean([x > 0 for x in fwd])) if fwd else None, "horizon_bars": horizon, "cost_log": cost}
