"""Association Rules & Probability Filter (Apollo23 TASK 010, MQL5 article #23324) - a FILTER of existing candidates, never a signal generator.

Closed-bar features -> versioned event bits -> rules A => UP / DOWN over an exact scope (market | venue | instrument | TF | horizon | schema).
Separate fields: antecedent_count, antecedent_support, joint_support_up/down, raw / Laplace-smoothed probabilities, base rates, edge, lift, score.
Mode OFF / OBSERVE by default; ASSIST may only HOLD a candidate when a fresh, supported, OPPOSITE edge exists; never creates or flips a side.
"""
from __future__ import annotations

import itertools
import math

SCHEMA = "PMW-AR-EVENTS-1"
CATALOG = ("RSI_LOW", "RSI_HIGH", "PRICE_ABOVE_EMA", "PRICE_BELOW_EMA", "ATR_HIGH", "MOM_UP", "MOM_DOWN", "SESSION_EU")
DEFAULTS = {"horizon": 24, "min_move": 0.0, "min_rule_count": 50, "edge_threshold": 0.08, "alpha": 1.0, "max_rule_len": 3}


def _rsi(c, n=14):
    out = [None] * len(c)
    if len(c) <= n:
        return out
    g = [max(0.0, c[i] - c[i - 1]) for i in range(1, len(c))]
    lo = [max(0.0, c[i - 1] - c[i]) for i in range(1, len(c))]
    ag, al = sum(g[:n]) / n, sum(lo[:n]) / n
    for i in range(n, len(c)):
        if i > n:
            ag = (ag * (n - 1) + g[i - 1]) / n
            al = (al * (n - 1) + lo[i - 1]) / n
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def event_bits(bars: list[dict], atr_ratio: float = 0.0012, session_hours=(8, 17)) -> list[int | None]:
    """Per closed bar: bitmask over CATALOG using only data up to that bar. Warm-up bars -> None (never 0)."""
    from ..analytics.ta import atr14, ema
    c = [float(b["c"]) for b in bars]
    r = _rsi(c)
    e = ema(c, 50)
    a = atr14([float(b["h"]) for b in bars], [float(b["l"]) for b in bars], c)
    out = []
    for i, b in enumerate(bars):
        if r[i] is None or e[i] is None or a[i] is None or i < 6:
            out.append(None)
            continue
        hour = int(b.get("hour", -1))
        ev = {"RSI_LOW": r[i] < 35, "RSI_HIGH": r[i] > 65, "PRICE_ABOVE_EMA": c[i] > e[i], "PRICE_BELOW_EMA": c[i] < e[i],
              "ATR_HIGH": a[i] / c[i] > atr_ratio, "MOM_UP": c[i] > c[i - 6], "MOM_DOWN": c[i] < c[i - 6],
              "SESSION_EU": session_hours[0] <= hour < session_hours[1]}
        out.append(sum(1 << k for k, name in enumerate(CATALOG) if ev[name]))
    return out


def labels(closes: list[float], horizon: int, min_move: float) -> list[str | None]:
    out = []
    for i, c in enumerate(closes):
        if i + horizon >= len(closes):
            out.append(None)                     # not matured
            continue
        d = closes[i + horizon] - c
        out.append("UP" if d > min_move else ("DOWN" if d < -min_move else "NEUTRAL"))
    return out


def train(masks: list[int | None], labs: list[str | None], *, alpha=1.0, min_rule_count=50, max_rule_len=3, scope: dict | None = None) -> dict:
    rows = [(m, y) for m, y in zip(masks, labs) if m is not None and y in ("UP", "DOWN")]
    N = len(rows)
    up = sum(1 for _, y in rows if y == "UP")
    if N == 0:
        return {"status": "NO_DATA", "rules": [], "n_labeled": 0, "scope": scope or {}}
    base_up_raw, base_down_raw = up / N, (N - up) / N
    base_up = (up + alpha) / (N + 2 * alpha)
    base_down = (N - up + alpha) / (N + 2 * alpha)
    bits = range(len(CATALOG))
    rules = []
    for L in range(1, max_rule_len + 1):
        for combo in itertools.combinations(bits, L):
            mask = sum(1 << b for b in combo)
            sel = [y for m, y in rows if m & mask == mask]
            n = len(sel)
            if n < min_rule_count:
                continue
            u = sum(1 for y in sel if y == "UP")
            d = n - u
            pu, pd = (u + alpha) / (n + 2 * alpha), (d + alpha) / (n + 2 * alpha)
            rules.append({"mask": mask, "events": [CATALOG[b] for b in combo], "length": L, "antecedent_count": n, "up_count": u, "down_count": d,
                          "antecedent_support": n / N, "joint_support_up": u / N, "joint_support_down": d / N,
                          "p_up_raw": u / n, "p_down_raw": d / n, "p_up": pu, "p_down": pd, "edge_up": pu - base_up, "edge_down": pd - base_down,
                          "lift_up": (u / n) / base_up_raw if base_up_raw > 0 else None, "lift_down": (d / n) / base_down_raw if base_down_raw > 0 else None,
                          "score_up": (pu - base_up) * math.log(1 + n), "score_down": (pd - base_down) * math.log(1 + n)})
    return {"status": "READY", "schema": SCHEMA, "rules": rules, "n_labeled": N, "base_up": base_up, "base_down": base_down,
            "base_up_raw": base_up_raw, "alpha": alpha, "min_rule_count": min_rule_count, "scope": scope or {}}


def assess(model: dict, mask: int | None, direction: str, edge_threshold: float = 0.08, mode: str = "OBSERVE") -> dict:
    """Candidate direction LONG / SHORT vs the best matching rule. Output role: OBSERVE (diagnostic) or ASSIST (HOLD only)."""
    if mode not in ("OFF", "OBSERVE", "ASSIST"):
        raise ValueError("mode")
    if mode == "OFF" or model.get("status") != "READY" or mask is None:
        return {"mode": mode, "action": "PASS", "reason": "OFF" if mode == "OFF" else "NO_MODEL_OR_WARMUP", "candidate_direction_supported": None}
    matched = [r for r in model["rules"] if mask & r["mask"] == r["mask"]]
    if not matched:
        return {"mode": mode, "action": "PASS", "reason": "NO_MATCH", "candidate_direction_supported": None, "matched_rules": []}
    key = "edge_up" if direction == "LONG" else "edge_down"
    opp = "edge_down" if direction == "LONG" else "edge_up"
    best_for = max(matched, key=lambda r: r[key])
    best_against = max(matched, key=lambda r: r[opp])
    supported = best_for[key] >= edge_threshold
    contrary = best_against[opp] >= edge_threshold and best_against[opp] > best_for[key]
    action = "HOLD" if (mode == "ASSIST" and contrary) else "PASS"
    # 1.46: a contrary edge wins - "supported" and CONTRARY_EDGE / HOLD were reported together
    return {"mode": mode, "action": action, "candidate_direction_supported": False if contrary else (True if supported else None),
            "best_rule_for": best_for, "best_rule_against": best_against, "reason": "CONTRARY_EDGE" if contrary else ("SUPPORTED" if supported else "WEAK_EDGE"),
            "matched_rules": len(matched), "note": "estymata kierunkowa – nie gwarancja; ASSIST może tylko wstrzymać, nigdy dodać stronę"}
