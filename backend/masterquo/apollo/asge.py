"""AutoStrategyGeneratorEngine (Apollo23 TASK 024) - discovery -> declarative spec -> validation -> frozen holdout -> SHADOW challenger ->
human review. The generator emits a typed, declarative Strategy IR built ONLY from an allowlist of conditions (no Python / MQL / JS is
generated or executed). Every trial, including rejected ones, goes to the append-only Trial Ledger with parent / child lineage, data hash,
config hash and full OOS result. execution_allowed = False is a constant; the canonical catalogue (60 / 6 / 2) never changes automatically;
SFB and the Market Trap Detector stay hard gates. Statuses: PROPOSED, REJECTED, VALIDATED_OOS, SHADOW_CHALLENGER, HUMAN_REVIEW.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import time

VERSION = "APOLLO23-ASGE-IR-1"
EXECUTION_ALLOWED = False
TAMPERED_FLAG = "EXECUTION_ALLOWED_TAMPERED"     # 1.46: ledger row read from the file with execution_allowed != False (restored / edited file)
DATA_HASH_BASIS = "t,o,h,l,c"                    # 1.46: data_hash covers the whole bar (before: closes only - no "data_hash_basis" in the row)
CONDITIONS = {   # allowlist: name -> (params with bounds)
    "close_above_sma": {"n": (5, 200)}, "close_below_sma": {"n": (5, 200)}, "sma_cross_up": {"fast": (3, 50), "slow": (10, 200)},
    "sma_cross_down": {"fast": (3, 50), "slow": (10, 200)}, "breakout_high": {"n": (5, 100)}, "breakdown_low": {"n": (5, 100)},
    "rsi_below": {"n": (2, 30), "level": (5, 50)}, "rsi_above": {"n": (2, 30), "level": (50, 95)},
}
EXITS = {"tp_r": (0.5, 5.0), "sl_atr": (0.5, 5.0), "max_bars": (2, 200)}


class IRError(ValueError):
    pass


def validate_ir(ir: dict) -> dict:
    if not isinstance(ir, dict):
        raise IRError("IR: obiekt")
    if not isinstance(ir.get("conditions"), list) or not all(isinstance(c, dict) for c in ir["conditions"]) or \
            not isinstance(ir.get("exit") or {}, dict):
        raise IRError("conditions: lista obiektów, exit: obiekt")          # 1.46: wrong types were a TypeError / AttributeError (500)
    if set(ir) - {"side", "conditions", "exit", "parent", "family"}:
        raise IRError(f"UNKNOWN_KEYS: {sorted(set(ir) - {'side', 'conditions', 'exit', 'parent', 'family'})}")
    if ir.get("side") not in ("LONG", "SHORT"):
        raise IRError("side: LONG | SHORT")
    conds = ir.get("conditions") or []
    if not 1 <= len(conds) <= 3:
        raise IRError("1-3 conditions")
    for c in conds:
        spec = CONDITIONS.get(c.get("type"))
        if spec is None:
            raise IRError(f"CONDITION_NOT_ALLOWED: {c.get('type')}")
        for k, (lo, hi) in spec.items():
            v = c.get(k)
            if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:      # 1.46: window lengths are integers (float sliced -> 500)
                raise IRError(f"PARAM_OUT_OF_BOUNDS: {c['type']}.{k}")
        if set(c) - set(spec) - {"type"}:
            raise IRError("UNKNOWN_PARAM")
    ex = ir.get("exit") or {}
    for k, (lo, hi) in EXITS.items():
        if not isinstance(ex.get(k), (int, float)) or not lo <= ex[k] <= hi:
            raise IRError(f"EXIT_OUT_OF_BOUNDS: {k}")
    return ir


def ir_hash(ir: dict) -> str:
    return hashlib.sha256(json.dumps(ir, sort_keys=True).encode()).hexdigest()[:16]


def _sma(c, n, i):
    return sum(c[i - n + 1:i + 1]) / n if i >= n - 1 else None


def _rsi(c, n, i):
    if i < n:
        return None
    g = sum(max(0, c[j] - c[j - 1]) for j in range(i - n + 1, i + 1))
    lo = sum(max(0, c[j - 1] - c[j]) for j in range(i - n + 1, i + 1))
    return 100.0 if lo == 0 else 100 - 100 / (1 + g / lo)


def _cond(c, h, lo, cond, i):
    t = cond["type"]
    if t == "close_above_sma":
        s = _sma(c, cond["n"], i)
        return s is not None and c[i] > s
    if t == "close_below_sma":
        s = _sma(c, cond["n"], i)
        return s is not None and c[i] < s
    if t in ("sma_cross_up", "sma_cross_down"):
        f0, s0, f1, s1 = _sma(c, cond["fast"], i - 1), _sma(c, cond["slow"], i - 1), _sma(c, cond["fast"], i), _sma(c, cond["slow"], i)
        if None in (f0, s0, f1, s1):
            return False
        return (f0 <= s0 and f1 > s1) if t == "sma_cross_up" else (f0 >= s0 and f1 < s1)
    if t == "breakout_high":
        n = cond["n"]
        return i > n and c[i] > max(h[i - n:i])
    if t == "breakdown_low":
        n = cond["n"]
        return i > n and c[i] < min(lo[i - n:i])
    if t == "rsi_below":
        r = _rsi(c, cond["n"], i)
        return r is not None and r < cond["level"]
    if t == "rsi_above":
        r = _rsi(c, cond["n"], i)
        return r is not None and r > cond["level"]
    return False


def backtest(ir: dict, bars: list[dict], cost_r: float = 0.05) -> list[float]:
    """Closed-bar evaluation: signal on close of bar i, entry at open of bar i+1, SL = sl_atr x ATR14, TP = tp_r x risk, time stop; SL first
    when both inside one bar; a bar that OPENS beyond the SL (gap) exits at its open. Returns net R per trade after cost."""
    c = [b["c"] for b in bars]
    h = [b["h"] for b in bars]
    lo = [b["l"] for b in bars]
    o = [b["o"] for b in bars]
    s = 1 if ir["side"] == "LONG" else -1
    ex = ir["exit"]
    out, i = [], 15
    while i < len(bars) - 1:
        if all(_cond(c, h, lo, cd, i) for cd in ir["conditions"]):
            atr = sum(max(h[j] - lo[j], abs(h[j] - c[j - 1]), abs(lo[j] - c[j - 1])) for j in range(i - 13, i + 1)) / 14
            entry = o[i + 1]
            risk = ex["sl_atr"] * atr
            if risk <= 0:
                i += 1
                continue
            sl, tp = entry - s * risk, entry + s * ex["tp_r"] * risk
            r = None
            for j in range(i + 1, min(len(bars), i + 1 + int(ex["max_bars"]))):
                if (s > 0 and lo[j] <= sl) or (s < 0 and h[j] >= sl):
                    # 1.46: a gap through the SL (weekend / news) fills at the open, not at the SL - it was booked as -1R (optimistic expectancy)
                    r = s * (o[j] - entry) / risk if (s > 0 and o[j] <= sl) or (s < 0 and o[j] >= sl) else -1.0
                    break
                if (s > 0 and h[j] >= tp) or (s < 0 and lo[j] <= tp):
                    r = ex["tp_r"]
                    break
            if r is None:
                j = min(len(bars) - 1, i + int(ex["max_bars"]))
                r = s * (c[j] - entry) / risk
            out.append(r - cost_r)
            i = j + 1
        else:
            i += 1
    return out


def mutate(parent: dict, rnd: random.Random) -> dict:
    """Immutable child variant: one bounded parameter step inside the allowlist (never a new condition type)."""
    child = json.loads(json.dumps(parent))
    c = rnd.choice(child["conditions"])
    k = rnd.choice(list(CONDITIONS[c["type"]]))
    lo, hi = CONDITIONS[c["type"]][k]
    c[k] = int(max(lo, min(hi, c[k] + rnd.choice([-1, 1]) * max(1, round(0.15 * c[k])))))
    child["parent"] = ir_hash(parent)
    return validate_ir(child)


def _sealed(row: dict) -> dict:
    """1.46: execution_allowed was read from the file verbatim - a row with `true` (file restored from a backup, another version, edited) was
    published by /asge/ledger and the export as allowed. It is a constant: the row carries EXECUTION_ALLOWED, a different value in the file
    is flagged (TAMPERED_FLAG), and the append-only file itself is never rewritten."""
    if "execution_allowed" in row and row["execution_allowed"] is not EXECUTION_ALLOWED:
        row = {**row, "integrity": TAMPERED_FLAG}
    return {**row, "execution_allowed": EXECUTION_ALLOWED}


def _holdout_judged(row: dict) -> bool:
    """The candidate of this ledger row was evaluated on the frozen holdout (passed or failed); tampered rows are never trusted."""
    return not row.get("integrity") and (row.get("status") == "SHADOW_CHALLENGER" or "HOLDOUT_FAILED" in (row.get("reasons") or []))


class TrialLedger:
    """Append-only. 1.46: with `path` every trial is appended to a JSONL file (lineage survives a restart - before it lived only in memory)
    and ids are assigned under a lock (parallel /asge/run calls could reuse a trial_id)."""

    def __init__(self, path=None):
        import threading
        from pathlib import Path as _P
        self.rows: list[dict] = []
        self.path = _P(path) if path else None
        self._lock = threading.Lock()
        if self.path and self.path.exists():
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue                              # a torn last line (crash while writing) is skipped, never repaired by guessing
                    if isinstance(row, dict):
                        self.rows.append(_sealed(row))

    def add(self, row: dict) -> dict:
        with self._lock:
            row = {**row, "trial_id": f"T{len(self.rows) + 1:05d}", "created_at": row.get("created_at") or time.time(),   # 1.46: UTC epoch
                   "execution_allowed": EXECUTION_ALLOWED}    # 1.46: the constant, whatever the caller passed
            if self.path:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            self.rows.append(row)
            return row


def run(bars: list[dict], seeds: list[dict], n_children: int = 10, *, holdout_frac: float = 0.25, folds: int = 3, min_trades: int = 20,
        seed: int = 7, ledger: TrialLedger | None = None) -> dict:
    """Walk-forward on the development part, frozen holdout evaluated ONCE per surviving candidate. Multiple-testing aware: the number of
    trials is reported and the hurdle rises with log(trials).
    1.46: both were counted only inside one call (every POST /asge/run started from a low hurdle and re-used the same holdout). Now the
    hurdle uses every DISTINCT candidate (ir_hash) tried on the same data (data_hash) in the ledger, earlier calls included, and a candidate
    already judged on this holdout is not evaluated again - the recorded result is returned (`holdout_reused_from`)."""
    led = ledger or TrialLedger()
    rnd = random.Random(seed)
    cut = int(len(bars) * (1 - holdout_frac))
    dev, hold = bars[:cut], bars[cut:]
    # 1.46: the hash covered only the closes - bars with other open / high / low (or times) got the same lineage although the backtest differs
    data_hash = hashlib.sha256(json.dumps([[b.get("t"), b["o"], b["h"], b["l"], b["c"]] for b in bars], default=str).encode()).hexdigest()[:16]
    cands = []
    for sd in seeds:
        validate_ir(sd)
        cands.append(sd)
        for _ in range(n_children):
            cands.append(mutate(sd, rnd))
    n_trials = len(cands)
    prior = [r for r in list(led.rows) if r.get("data_hash") == data_hash]
    hold_done: dict = {}                                  # ir_hash -> first ledger row judged on this holdout
    for r in prior:
        if r.get("ir_hash") and _holdout_judged(r):
            hold_done.setdefault(r["ir_hash"], r)
    n_cum = len({r["ir_hash"] for r in prior if r.get("ir_hash")} | {ir_hash(c) for c in cands})    # distinct candidates on these data
    hurdle = 0.05 * math.log(max(2, n_trials, n_cum))     # never below the per-call count used before (the gate only gets stricter)
    results = []
    for ir in cands:
        fold_len = len(dev) // folds
        frs = [backtest(ir, dev[k * fold_len:(k + 1) * fold_len]) for k in range(folds)]
        allr = [x for f in frs for x in f]
        pos = sum(1 for f in frs if f and sum(f) / len(f) > 0)
        mean = sum(allr) / len(allr) if allr else None
        status, reasons = "REJECTED", []
        if len(allr) < min_trades:
            reasons.append("INSUFFICIENT_TRADES")
        if mean is None or mean <= hurdle:
            reasons.append("DEV_EXPECTANCY_BELOW_HURDLE")
        if pos < folds - 1:
            reasons.append("UNSTABLE_FOLDS")
        hold_mean, reused = None, None
        if not reasons:
            done = hold_done.get(ir_hash(ir))
            if done is not None:                          # 1.46: frozen holdout - judged once per (data, candidate)
                reused, hold_mean, passed = done.get("trial_id"), done.get("holdout_mean_net_r"), done.get("status") == "SHADOW_CHALLENGER"
            else:
                hr = backtest(ir, hold)
                hold_mean = sum(hr) / len(hr) if hr else None
                passed = not (hold_mean is None or hold_mean <= 0 or len(hr) < max(5, min_trades // 4))
            if not passed:
                reasons.append("HOLDOUT_FAILED")
            else:
                status = "SHADOW_CHALLENGER"
        row = led.add({"ir": ir, "ir_hash": ir_hash(ir), "parent": ir.get("parent"), "data_hash": data_hash, "dev_trades": len(allr),
                       "dev_mean_net_r": mean, "positive_folds": pos, "holdout_mean_net_r": hold_mean, "status": status, "reasons": reasons,
                       "execution_allowed": EXECUTION_ALLOWED, "version": VERSION, "hurdle_net_r": hurdle, "holdout_reused_from": reused,
                       "data_hash_basis": DATA_HASH_BASIS})
        if _holdout_judged(row):
            hold_done.setdefault(row["ir_hash"], row)
        results.append(row)
    return {"trials": n_trials, "trials_cumulative": n_cum, "holdout_evaluations": len(hold_done), "hurdle_net_r": hurdle,
            "challengers": [r for r in results if r["status"] == "SHADOW_CHALLENGER"],
            "rejected": sum(1 for r in results if r["status"] == "REJECTED"), "ledger_size": len(led.rows),
            "next_step": "HUMAN_REVIEW (brak automatycznej promocji, brak Deploy Live)", "execution_allowed": EXECUTION_ALLOWED}
