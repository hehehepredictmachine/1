"""M39 Repaint Inspector, M40 Edge Drift Detector, M41 Edge-or-Luck block bootstrap, M42 Trade Pad (plan / simulation; real
orders only through the manual pad of the execution path) - MQ-LAB-EDGE-1.0.0."""
from __future__ import annotations

import json
import math

import numpy as np

VERSION = "MQ-LAB-EDGE-1.0.0"


# ----------------------------------------------------------------------------- M39
class RepaintInspector:
    """Remembers module outputs per CLOSED bar (keyed by bar open time) and logs changed / appeared / vanished values when
    the same closed bar is evaluated again. Reports the observation span and gaps; it can never prove 'no repaint'."""

    def __init__(self, db=None, keep: int = 400):
        self.db = db
        self.keep = keep
        self.mem: dict[tuple, dict] = {}
        self.first_seen: dict[tuple, str] = {}
        self.counts: dict[tuple, dict] = {}

    def observe(self, asset: str, module: str, tf: str, values_by_bar: dict[str, object], observed_at: str) -> list[dict]:
        key = (asset, module, tf)
        prev = self.mem.get(key, {})
        cnt = self.counts.setdefault(key, {"observations": 0, "changed": 0, "appeared": 0, "vanished": 0})
        cnt["observations"] += 1
        self.first_seen.setdefault(key, observed_at)
        changes = []
        common_from = min(values_by_bar) if values_by_bar else None
        for t, v in values_by_bar.items():
            if t in prev:
                if json.dumps(prev[t], sort_keys=True, default=str) != json.dumps(v, sort_keys=True, default=str):
                    changes.append({"bar_open": t, "change": "CHANGED", "before": prev[t], "after": v})
            elif prev and t <= max(prev) and v is not None:
                changes.append({"bar_open": t, "change": "APPEARED", "before": None, "after": v})
        for t, v in prev.items():
            if common_from and t >= common_from and t not in values_by_bar and v is not None:
                changes.append({"bar_open": t, "change": "VANISHED", "before": v, "after": None})
        for ch in changes:
            cnt[ch["change"].lower()] += 1
            if self.db is not None:
                self.db.execute("INSERT INTO lab_repaint(asset, module, tf, bar_open, observed_at, change, before, after) VALUES (?,?,?,?,?,?,?,?)",
                                (asset, module, tf, ch["bar_open"], observed_at, ch["change"], json.dumps(ch["before"], default=str),
                                 json.dumps(ch["after"], default=str)))
        merged = {**prev, **values_by_bar}
        self.mem[key] = dict(sorted(merged.items())[-self.keep:])
        return changes

    def report(self) -> list[dict]:
        return [{"asset": k[0], "module": k[1], "tf": k[2], "observing_since": self.first_seen.get(k), **v,
                 "note": "obserwacja od uruchomienia programu; restart = nowa obserwacja; brak zmian ≠ dowód braku repaintingu"}
                for k, v in self.counts.items()]


# ----------------------------------------------------------------------------- M41
def block_bootstrap_mean(x: list[float], block: int | None = None, n_boot: int = 2000, seed: int = 7) -> dict:
    """Circular block bootstrap of the mean (dependent trades/returns). Block length default ~ n^(1/3)."""
    a = np.asarray(x, float)
    n = len(a)
    if n < 10:
        return {"status": "INSUFFICIENT_EVIDENCE", "n": n}
    b = int(block or max(2, round(n ** (1 / 3))))
    rng = np.random.default_rng(seed)
    k = math.ceil(n / b)
    means = np.empty(n_boot)
    for r in range(n_boot):
        starts = rng.integers(0, n, k)
        idx = (starts[:, None] + np.arange(b)[None, :]).ravel()[:n] % n
        means[r] = a[idx].mean()
    lo, hi = np.quantile(means, [0.025, 0.975])
    p_le0 = float((means <= 0).mean())
    verdict = "EDGE_CI_ABOVE_ZERO" if lo > 0 else "EDGE_CI_BELOW_ZERO" if hi < 0 else "NO_VALIDATED_EDGE"
    return {"status": "ready", "n": n, "block": b, "mean": float(a.mean()), "ci95": [float(lo), float(hi)], "p_mean_le_0": p_le0,
            "verdict": verdict, "seed": seed, "n_boot": n_boot, "note": "bootstrap blokowy – transakcje zależne nie są liczone jako niezależne"}


# ----------------------------------------------------------------------------- M40
def edge_drift(values: list[float], baseline_mean: float | None, label_delay: int = 0, warn_k: float = 2.5, drift_k: float = 5.0,
               slack: float = 0.25) -> dict:
    """One-sided CUSUM on standardized net results (after costs) relative to a baseline mean fixed BEFORE monitoring.
    Labels arrive with a delay: only the first len - label_delay values are matured. States: OK / WARNING / DEGRADED."""
    v = np.asarray(values[: max(0, len(values) - label_delay)], float)
    if baseline_mean is None or len(v) < 20:
        return {"state": "INSUFFICIENT_EVIDENCE", "matured": int(len(v))}
    sd = float(v.std()) or 1.0
    z = (v - baseline_mean) / sd
    s, peak = 0.0, 0.0
    for x in z:
        s = min(0.0, s + x + slack)
        peak = min(peak, s)
    state = "DEGRADED" if -s >= drift_k else "WARNING" if -s >= warn_k else "OK"
    return {"state": state, "cusum": round(s, 3), "worst": round(peak, 3), "matured": int(len(v)), "baseline_mean": baseline_mean,
            "rules": {"warning_at": warn_k, "degraded_at": drift_k, "slack": slack, "label_delay": label_delay}}


# ----------------------------------------------------------------------------- M42
def trade_pad_plan(*, side: str, entry: float, sl: float, tp: float, lots: float, meta: dict, quote: dict | None,
                   commission_per_lot_side: float, account_ccy_per_profit_ccy: float = 1.0) -> dict:
    """Plan + simulation only. P&L from the terminal contract (contract size, tick size/value), bid/ask side and commission.
    Never sends anything; a real order goes through the Manual Pad (plan -> intent -> execute) and its gateway checks."""
    if side not in ("BUY", "SELL") or lots <= 0:
        raise ValueError("INVALID_PLAN")
    cs = float(meta.get("trade_contract_size") or 0)
    if cs <= 0:
        raise ValueError("CONTRACT_SIZE_UNKNOWN")
    sgn = 1 if side == "BUY" else -1
    if sgn * (tp - entry) <= 0 or sgn * (entry - sl) <= 0:
        raise ValueError("SL_TP_WRONG_SIDE")
    spread = (quote["ask"] - quote["bid"]) if quote else None
    comm = 2 * commission_per_lot_side * lots
    win = sgn * (tp - entry) * cs * lots * account_ccy_per_profit_ccy - comm
    loss = sgn * (sl - entry) * cs * lots * account_ccy_per_profit_ccy - comm
    vmin, vstep = float(meta.get("volume_min") or 0.01), float(meta.get("volume_step") or 0.01)
    ok_lot = lots >= vmin and abs(round(lots / vstep) * vstep - lots) < 1e-9
    return {"mode": "SIMULATION_ONLY", "execution": "VIA_MANUAL_PAD", "side": side, "entry": entry, "sl": sl, "tp": tp,
            "lots": lots, "lot_valid": ok_lot, "rr": round(abs(tp - entry) / abs(entry - sl), 3), "spread_now": spread,
            "pnl_at_tp": round(win, 2), "pnl_at_sl": round(loss, 2), "commission_round_turn": round(comm, 2),
            "contract_size": cs, "note": "symulacja z parametrów kontraktu; rzeczywiste warunki brokera są nadrzędne"}
