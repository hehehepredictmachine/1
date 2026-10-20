"""Shared MA kernels (FF03/FF05). Two explicit seed profiles - the global lab/common.ema (FULL_SEED, NaN until P) is NOT changed:
  PARTIAL_PREFIX_V1: m = min(P, i+1); SMA = mean of the last m; LWMA weights 1..m oldest->newest, denominator m(m+1)/2;
                     EMA/SMMA for i < P are the mean of the available prefix, at i = P-1 the state equals SMA_P, then
                     alpha = 2/(P+1) (EMA) or 1/P (SMMA). P = 1 is the identity.
  FULL_SEED:         value undefined (None) until P full values; EMA/SMMA seeded with SMA of the first P values.
Incremental `RollingMA`: O(1) per closed bar (sliding S and weighted W for SMA/LWMA, recursive EMA/SMMA), commit once per bar identity,
transient `preview` for the forming bar never mutates the committed state; periodic exact rebase limits roundoff."""
from __future__ import annotations

import math
from collections import deque

METHODS = ("EMA", "SMA", "SMMA", "LWMA")
SEEDS = ("PARTIAL_PREFIX_V1", "FULL_SEED")
MAX_PERIOD = 10000
REBASE_EVERY = 4096


def normalize_period(requested) -> tuple[int, str | None]:
    """Integer requested <= 0 -> 1, > 10000 -> 10000 (CONFIG_CLAMPED); non-integer / NaN rejected."""
    if isinstance(requested, bool) or not isinstance(requested, (int, float)) or (isinstance(requested, float) and (math.isnan(requested) or not requested.is_integer())):
        raise ValueError("PERIOD_INVALID: wymagana liczba całkowita")
    p = int(requested)
    if p <= 0:
        return 1, "CONFIG_CLAMPED"
    if p > MAX_PERIOD:
        return MAX_PERIOD, "CONFIG_CLAMPED"
    return p, None


def check_method(m: str) -> str:
    if m not in METHODS:
        raise ValueError(f"MA_METHOD_INVALID: {m}")
    return m


class RollingMA:
    def __init__(self, method: str, period: int, seed: str = "PARTIAL_PREFIX_V1"):
        self.method = check_method(method)
        self.P, self.clamp = normalize_period(period)
        if seed not in SEEDS:
            raise ValueError("SEED_PROFILE_INVALID")
        self.seed = seed
        self.reset()

    def reset(self):
        self.n = 0
        self.win: deque = deque()
        self.S = 0.0
        self.W = 0.0
        self.state = None
        self.since_rebase = 0

    # pure transition from a committed state (no mutation) -> (value, new_state_tuple)
    def _next(self, x: float):
        P, m_old = self.P, len(self.win)
        n1 = self.n + 1
        if self.method in ("SMA", "LWMA"):
            full = m_old == P
            old = self.win[0] if full else None
            S = self.S - (old if full else 0.0) + x
            if full:
                W = self.W - self.S + P * x
                m = P
            else:
                W = self.W + (m_old + 1) * x
                m = m_old + 1
            if self.seed == "FULL_SEED" and m < P:
                val = None
            elif self.method == "SMA":
                val = S / m
            else:
                val = W / (m * (m + 1) / 2)
            return val, (S, W, None)
        # EMA / SMMA
        a = 2.0 / (P + 1) if self.method == "EMA" else 1.0 / P
        if n1 <= P:                                   # prefix (both profiles keep the running mean; FULL_SEED hides it)
            S = self.S + x
            st = S / n1
            val = st if (self.seed == "PARTIAL_PREFIX_V1" or n1 == P) else None
            return val, (S, 0.0, st)
        st = self.state + a * (x - self.state)
        return st, (self.S, 0.0, st)

    def commit(self, x: float):
        if not math.isfinite(x):
            raise ValueError("NON_FINITE_INPUT")
        val, (S, W, st) = self._next(x)
        if self.method in ("SMA", "LWMA"):
            if len(self.win) == self.P:
                self.win.popleft()
            self.win.append(x)
            self.S, self.W = S, W
            self.since_rebase += 1
            if self.since_rebase >= REBASE_EVERY:                     # exact rebase (compensates accumulated roundoff)
                w = list(self.win)
                self.S = math.fsum(w)
                self.W = math.fsum((k + 1) * v for k, v in enumerate(w))
                self.since_rebase = 0
        else:
            self.S, self.state = S, st
        self.n += 1
        return val

    def preview(self, x: float):
        """Value for a forming bar WITHOUT changing the committed state (repeated ticks never double-update)."""
        return self._next(x)[0]

    @property
    def warm(self) -> bool:
        return self.n >= self.P


def ma_series(xs, method: str, period: int, seed: str = "PARTIAL_PREFIX_V1") -> list:
    r = RollingMA(method, period, seed)
    return [r.commit(float(x)) for x in xs]


def naive_ma(xs, method: str, P: int, seed: str = "PARTIAL_PREFIX_V1") -> list:
    """Independent naive window reference (tests only): recomputes every point from its definition."""
    out, st = [], None
    for i in range(len(xs)):
        m = min(P, i + 1)
        w = xs[i - m + 1:i + 1]
        if method == "SMA":
            v = sum(w) / m
        elif method == "LWMA":
            v = sum((k + 1) * w[k] for k in range(m)) / (m * (m + 1) / 2)
        else:
            a = 2.0 / (P + 1) if method == "EMA" else 1.0 / P
            if i + 1 <= P:
                st = sum(xs[:i + 1]) / (i + 1)
            else:
                st = st + a * (xs[i] - st)
            v = st
        out.append(None if (seed == "FULL_SEED" and i + 1 < P) else v)
    return out
