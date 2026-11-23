"""Modular Indicator & Smoothing Engine (Apollo23 TASK 007, MQL5 article 23623 adapted - independent implementation of the published formulas).

Flow: closed canonical bars -> AppliedPrice -> SmoothingModule (factory by method) -> IndicatorResult (contract + config hash) -> consumers.

Compatibility profiles (part of algorithm_version / config_hash / cache key - never mixed):
  PMW_LEGACY_V1       exactly the existing analytics.ta outputs: EMA seeded with the SMA of the first P values, period >= 1, WMA == LWMA.
  MQL5_STANDARD_V1    article / MQL5 semantics: EMA seeded with the FIRST source value (barsRequired = source), period >= 2 (clamped + warning).
  LAB_PARTIAL_PREFIX_V1 / LAB_FULL_SEED   the existing lab.flow_context.ma.RollingMA profiles, reached through an adapter (no duplicate kernel).

Every method has a reference full calculation and an O(1)-per-bar incremental state (LWMA: two running sums, W updated with the OLD S first).
Warm-up is None (never 0). Descriptive only: no signal, no order path, no risk permission.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field

ENGINE_VERSION = "PMW-SMOOTH-1"
METHODS = ("SMA", "EMA", "SMMA", "LWMA")
ALIASES = {"WMA": "LWMA", "RMA": "SMMA", "WILDER": "SMMA"}
APPLIED = ("OPEN", "HIGH", "LOW", "CLOSE", "MEDIAN", "TYPICAL", "WEIGHTED")
POLICIES = {
    "PMW_LEGACY_V1": {"min_period": 1, "ema_seed": "PMW_EMA_SMA_SEED_V1"},
    "MQL5_STANDARD_V1": {"min_period": 2, "ema_seed": "MQL5_EMA_SOURCE_SEED_V1"},
    "LAB_PARTIAL_PREFIX_V1": {"min_period": 1, "ema_seed": "LAB_PARTIAL_PREFIX_V1"},
    "LAB_FULL_SEED": {"min_period": 1, "ema_seed": "LAB_FULL_SEED"},
}
MAX_PERIOD = 5000
STATUSES = ("READY", "WARMUP", "NO_DATA", "STALE", "ERROR", "DISABLED")


class SpecError(ValueError):
    pass


def normalize_method(m: str) -> str:
    m = str(m or "").upper().strip()
    m = ALIASES.get(m, m)
    if m not in METHODS:
        raise SpecError(f"UNKNOWN_METHOD: {m} (SMA | EMA | SMMA | LWMA; alias WMA)")
    return m


def applied_price(bar: dict, kind: str = "CLOSE") -> float:
    o, h, lo, c = (float(bar[k] if k in bar else bar[n]) for k, n in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close")))
    return {"OPEN": o, "HIGH": h, "LOW": lo, "CLOSE": c, "MEDIAN": (h + lo) / 2, "TYPICAL": (h + lo + c) / 3, "WEIGHTED": (h + lo + 2 * c) / 4}[kind]


@dataclass(frozen=True)
class IndicatorSpec:
    method: str
    period: int
    applied_price: str = "CLOSE"
    policy: str = "PMW_LEGACY_V1"
    instrument: str = ""
    timeframe: str = ""
    venue: str = ""
    closed_only: bool = True
    raw_method: str = field(default="", compare=False)          # the method as configured (e.g. WMA) - kept for audit, not in the hash
    warnings: tuple = field(default=(), compare=False)

    @classmethod
    def make(cls, method, period, applied="CLOSE", policy="PMW_LEGACY_V1", instrument="", timeframe="", venue="") -> "IndicatorSpec":
        raw = str(method or "").upper().strip()
        m = normalize_method(raw)
        if policy not in POLICIES:
            raise SpecError(f"UNKNOWN_POLICY: {policy}")
        ap = str(applied or "CLOSE").upper()
        if ap not in APPLIED:
            raise SpecError(f"UNKNOWN_APPLIED_PRICE: {ap}")
        try:
            p = int(period)
        except (TypeError, ValueError):
            raise SpecError("INVALID_PERIOD") from None
        if p < 1 or p > MAX_PERIOD:
            raise SpecError(f"INVALID_PERIOD: 1..{MAX_PERIOD}")
        warn = []
        mn = POLICIES[policy]["min_period"]
        if p < mn:
            warn.append(f"PERIOD_CLAMPED: {p} -> {mn} ({policy})")
            p = mn
        return cls(m, p, ap, policy, str(instrument or ""), str(timeframe or ""), str(venue or ""), True, raw, tuple(warn))

    @property
    def seed_policy(self) -> str:
        return POLICIES[self.policy]["ema_seed"] if self.method == "EMA" else ("SMA_WINDOW_SEED" if self.policy in ("PMW_LEGACY_V1", "MQL5_STANDARD_V1")
                                                                                 else POLICIES[self.policy]["ema_seed"])

    @property
    def algorithm_version(self) -> str:
        return f"{ENGINE_VERSION}/{self.policy}/{self.method}/{self.seed_policy}"

    @property
    def config_hash(self) -> str:
        d = {"method": self.method, "period": self.period, "applied_price": self.applied_price, "policy": self.policy, "seed": self.seed_policy,
             "instrument": self.instrument, "timeframe": self.timeframe, "venue": self.venue, "closed_only": self.closed_only, "v": ENGINE_VERSION}
        return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()[:16]

    def bars_required(self, source_bars_required: int = 1) -> int:
        if self.method == "EMA" and self.policy == "MQL5_STANDARD_V1":
            return source_bars_required
        if self.policy.startswith("LAB_PARTIAL"):
            return source_bars_required
        return source_bars_required + self.period - 1


# ---------------------------------------------------------------- reference full calculations (simple, independent of the state machine)
def full(spec: IndicatorSpec, x: list[float]) -> list[float | None]:
    P, n = spec.period, len(x)
    if spec.policy.startswith("LAB_"):
        from ..lab.flow_context.ma import ma_series
        return [None if v is None else float(v) for v in ma_series(x, spec.method, P, "PARTIAL_PREFIX_V1" if "PARTIAL" in spec.policy else "FULL_SEED")]
    out: list[float | None] = [None] * n
    if spec.method == "EMA" and spec.policy == "MQL5_STANDARD_V1":
        a = 2.0 / (P + 1)
        for i in range(n):
            out[i] = x[0] if i == 0 else a * x[i] + (1 - a) * out[i - 1]
        return out
    if n < P:
        return out
    if spec.method == "SMA":
        for i in range(P - 1, n):
            out[i] = sum(x[i - P + 1:i + 1]) / P
    elif spec.method == "EMA":                       # PMW_LEGACY_V1: SMA seed of the first P values (== analytics.ta.ema)
        a = 2.0 / (P + 1)
        out[P - 1] = sum(x[:P]) / P
        for i in range(P, n):
            out[i] = a * x[i] + (1 - a) * out[i - 1]
    elif spec.method == "SMMA":
        out[P - 1] = sum(x[:P]) / P
        for i in range(P, n):
            out[i] = (out[i - 1] * (P - 1) + x[i]) / P
    elif spec.method == "LWMA":
        den = P * (P + 1) / 2
        for i in range(P - 1, n):
            out[i] = sum(x[i - P + 1 + k] * (k + 1) for k in range(P)) / den
    return out


class SmoothingState:
    """O(1) incremental kernel. commit(x) appends one CLOSED value; preview(x) evaluates a forming value without mutating state."""

    def __init__(self, spec: IndicatorSpec):
        if spec.policy.startswith("LAB_"):
            raise SpecError("LAB profiles are incremental through lab.flow_context.ma.RollingMA")
        self.spec = spec
        self.reset()

    def reset(self):
        self.n = 0
        self.win: list[float] = []            # last P values (SMA/LWMA removal, seeds)
        self.prev: float | None = None
        self.S = 0.0                          # running window sum
        self.W = 0.0                          # running weighted sum (LWMA)
        self.committed: list[float | None] = []

    def _step(self, x: float, commit: bool):
        P, m, pol = self.spec.period, self.spec.method, self.spec.policy
        n = self.n + 1
        old = self.win[0] if len(self.win) == P else None
        S, W, prev = self.S, self.W, self.prev
        if m == "EMA" and pol == "MQL5_STANDARD_V1":
            a = 2.0 / (P + 1)
            val = x if prev is None else a * x + (1 - a) * prev
            prev = val
        elif m == "LWMA":
            if n <= P:                                            # priming: W = sum(k * x_k) for k = 1..n with window growing
                W = W + n * x
                S = S + x
                val = W / (P * (P + 1) / 2) if n == P else None
            else:
                W = W - S + P * x                                 # W first, with the OLD S (order matters)
                S = S - old + x
                val = W / (P * (P + 1) / 2)
        else:                                                     # SMA / EMA legacy / SMMA
            S = S + x - (old if old is not None and m == "SMA" else 0.0)
            if n < P:
                val = None
            elif n == P:
                val = (S if m != "SMA" else S) / P                 # seed = SMA of the first P values
            elif m == "SMA":
                val = S / P
            elif m == "EMA":
                a = 2.0 / (P + 1)
                val = a * x + (1 - a) * prev
            else:
                val = (prev * (P - 1) + x) / P
            if m != "SMA" and n > P:
                S = 0.0                                           # the window sum is only needed until the seed
            prev = val if val is not None else prev
        if commit:
            self.n = n
            self.win.append(x)
            if len(self.win) > P:
                self.win.pop(0)
            self.S, self.W, self.prev = S, W, prev
            self.committed.append(val)
        return val

    def commit(self, x: float):
        return self._step(float(x), True)

    def preview(self, x: float):
        return self._step(float(x), False)


def _clean(v):
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        raise SpecError("NON_FINITE_VALUE")
    return v


class IndicatorEngine:
    """Per-key state (venue|instrument|tf|config_hash): incremental update on appended closed bars; any revision / shrink / instrument or
    spec change -> deterministic full replay. Full == incremental is asserted by the tests."""

    def __init__(self):
        self._st: dict[str, dict] = {}

    @staticmethod
    def key(spec: IndicatorSpec) -> str:
        return f"{spec.venue}|{spec.instrument}|{spec.timeframe}|{spec.config_hash}|{spec.algorithm_version}"

    def calculate(self, spec: IndicatorSpec, bars: list[dict], *, revision: str | int | None = None, now: float | None = None) -> dict:
        closed = [b for b in bars if not b.get("forming")] if spec.closed_only else list(bars)
        if not closed:
            return self._result(spec, [], [], "NO_DATA", "brak zamkniętych świec", revision)
        for b in closed:
            for k in ("o", "h", "l", "c", "open", "high", "low", "close"):
                v = b.get(k)
                if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                    return self._result(spec, [], closed, "ERROR", "NON_FINITE_INPUT", revision)
        x = [applied_price(b, spec.applied_price) for b in closed]
        ident = [(b.get("t") or b.get("time") or b.get("t_raw")) for b in closed]
        k = self.key(spec)
        st = self._st.get(k)
        mode = "FULL"
        if spec.policy.startswith("LAB_"):
            vals = full(spec, x)
        else:
            ok = (st is not None and st["revision"] == revision and len(ident) >= len(st["ident"]) and ident[:len(st["ident"])] == st["ident"]
                  and st["x"] == x[:len(st["x"])])
            if not ok:
                state = SmoothingState(spec)
                for v in x:
                    state.commit(v)
            else:
                state = st["state"]
                for v in x[len(st["x"]):]:
                    state.commit(v)
                mode = "INCREMENTAL"
            vals = list(state.committed)
            self._st[k] = {"state": state, "ident": ident, "x": x, "revision": revision}
        need = spec.bars_required()
        status = "READY" if any(v is not None for v in vals) else "WARMUP"
        res = self._result(spec, vals, closed, status, None if status == "READY" else f"za mało świec: {len(closed)}/{need}", revision)
        res["calc_mode"] = mode
        return res

    def _result(self, spec, vals, closed, status, reason, revision):
        vf = next((i for i, v in enumerate(vals) if v is not None), None)
        return {"status": status, "reason": reason, "values": [_clean(v) for v in vals],
                "times": [(b.get("t") or b.get("time") or b.get("t_raw")) for b in closed], "valid_from": vf, "bars_required": spec.bars_required(),
                "spec": {k: v for k, v in asdict(spec).items() if k != "warnings"}, "label": f"{spec.method}({spec.period})",
                "seed_policy": spec.seed_policy, "applied_price": spec.applied_price, "algorithm_version": spec.algorithm_version,
                "config_hash": spec.config_hash, "source_revision": revision, "warnings": list(spec.warnings),
                "available_at": (closed[-1].get("available_at") or closed[-1].get("t") or closed[-1].get("time") or closed[-1].get("t_raw")) if closed else None, "engine": ENGINE_VERSION,
                "mode": "DESCRIPTIVE (bez sygnału, bez zleceń)"}


def catalog() -> dict:
    return {"engine": ENGINE_VERSION, "methods": list(METHODS), "aliases": ALIASES, "applied_prices": list(APPLIED),
            "policies": POLICIES, "default_policy": "PMW_LEGACY_V1",
            "note": "PMW_LEGACY_V1 = dotychczasowe wartości (EMA z seedem SMA); MQL5_STANDARD_V1 = semantyka MQL5 (EMA z seedem pierwszą ceną)",
            "rollout": "OFF -> REPLAY -> SHADOW -> CHART_ONLY -> CONSUMER_OPT_IN (żaden konsument nie zmienia polityki samoczynnie)"}
