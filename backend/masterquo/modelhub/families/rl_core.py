"""RL replay core (pure numpy; the Gymnasium wrapper lives in deep_runtime.rl).

Action space (one consistent variant): target exposure in {SHORT = -1, FLAT = 0, LONG = +1} x `unit` lots, |exposure| <= max_units.
Timing: the action chosen after the CLOSE of bar t is executed at the OPEN of bar t+1 (never at a price already known): fill = open
+/- half spread +/- slippage against the trader. Costs (half spread + slippage on the traded quantity, commission per lot side) are
charged exactly ONCE, at the fill. Reward = change of net equity from the close of t to the close of t+1 (mark-to-market incl. the
fill costs) divided by `reward_scale`; optional turnover penalty is separate and reported. Episode end: terminated when the data ends,
truncated at max_steps; any open position is force-liquidated at the next open with costs (no hidden unrealised loss).
Observation = last k log returns, range / close, current exposure, unrealised P/L (in reward units), bars in position - nothing after t.
"""
from __future__ import annotations

import numpy as np

ACTIONS = {0: -1, 1: 0, 2: 1}
ACTION_NAMES = {0: "SHORT", 1: "FLAT", 2: "LONG"}


class ReplayCore:
    def __init__(self, bars: list[dict], *, k: int = 16, spread: float = 0.2, slippage: float = 0.05, commission: float = 0.0,
                 unit: float = 1.0, max_units: int = 1, reward_scale: float = 1.0, max_steps: int = 2000, turnover_penalty: float = 0.0):
        self.o = np.asarray([b["o"] for b in bars], dtype=float)
        self.c = np.asarray([b["c"] for b in bars], dtype=float)
        self.h = np.asarray([b["h"] for b in bars], dtype=float)
        self.l = np.asarray([b["l"] for b in bars], dtype=float)
        self.r = np.concatenate([[0.0], np.diff(np.log(self.c))])
        self.k, self.spread, self.slip, self.comm = k, spread, slippage, commission
        self.unit, self.max_units, self.scale, self.max_steps, self.turn_pen = unit, max_units, reward_scale, max_steps, turnover_penalty
        self.obs_dim = k + 4

    def reset(self, start: int | None = None):
        self.t = max(self.k, start if start is not None else self.k)
        self.t0 = self.t
        self.pos = 0.0
        self.entry = 0.0
        self.cash = 0.0
        self.costs = 0.0
        self.trades = 0
        self.in_pos = 0
        self.equity_prev = 0.0
        self.log = []
        return self.obs()

    def mtm(self, px: float) -> float:
        return self.cash + self.pos * px

    def obs(self) -> np.ndarray:
        t = self.t
        rr = self.r[t - self.k + 1:t + 1]
        unreal = (self.pos * (self.c[t] - self.entry)) / self.scale if self.pos else 0.0
        return np.concatenate([rr * 100.0, [(self.h[t] - self.l[t]) / self.c[t] * 100.0, self.pos / max(1.0, self.max_units * self.unit),
                                            unreal, min(self.in_pos, 100) / 100.0]]).astype(np.float32)

    def _fill(self, target: float, px_open: float) -> float:
        dq = target - self.pos
        if dq == 0:
            return 0.0
        side = 1.0 if dq > 0 else -1.0
        px = px_open + side * (self.spread / 2 + self.slip)
        cost = abs(dq) * (self.spread / 2 + self.slip) + abs(dq) / self.unit * self.comm
        self.cash -= dq * px                       # cash flow at the (worse) fill price - the cost is inside the price ...
        self.cash -= abs(dq) / self.unit * self.comm   # ... plus commission, charged once here
        self.costs += cost
        self.trades += 1
        if self.pos == 0 or np.sign(target) != np.sign(self.pos):
            self.entry = px if target != 0 else 0.0
            self.in_pos = 0
        self.pos = target
        return cost

    def step(self, action: int):
        target = float(np.clip(ACTIONS[int(action)], -self.max_units, self.max_units)) * self.unit
        t = self.t
        nxt = t + 1
        if nxt >= len(self.c):
            return self.obs(), 0.0, True, False, {"reason": "END"}
        eq0 = self.mtm(self.c[t])
        cost = self._fill(target, self.o[nxt])                                  # executed at the NEXT open
        self.t = nxt
        self.in_pos = self.in_pos + 1 if self.pos else 0
        done = self.t >= len(self.c) - 2
        trunc = (self.t - self.t0) >= self.max_steps
        if done or trunc:
            self._fill(0.0, self.o[self.t + 1] if self.t + 1 < len(self.o) else self.c[self.t])   # forced liquidation, costs once
        eq1 = self.mtm(self.c[self.t]) if self.pos else self.cash
        rew = (eq1 - eq0) / self.scale - (self.turn_pen if cost > 0 else 0.0)
        self.log.append({"t": int(self.t), "pos": self.pos, "equity": eq1, "cost": cost})
        return self.obs(), float(rew), bool(done), bool(trunc and not done), {"equity": eq1, "cost": cost}


def run_policy(core: ReplayCore, policy, start: int, steps: int) -> dict:
    o = core.reset(start)
    eq, rets = [], []
    for _ in range(steps):
        a = policy(o, core)
        o, r, d, tr, info = core.step(a)
        rets.append(r)
        eq.append(info.get("equity", 0.0))
        if d or tr:
            break
    eq = np.asarray(eq) if eq else np.zeros(1)
    peak = np.maximum.accumulate(eq)
    return {"net_pnl": float(eq[-1]), "max_drawdown": float(np.max(peak - eq)), "trades": core.trades, "costs": core.costs, "steps": len(rets)}


def flat_policy(o, core):
    return 1


def momentum_policy(o, core):
    return 2 if o[core.k - 1] > 0 else 0
