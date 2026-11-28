"""Association Rules & Probability Filter (Apollo23 TASK 010, MQL5 article #23324) - a FILTER of existing candidates, never a signal generator.

Closed-bar features -> versioned event bits -> rules A => UP / DOWN over an exact scope (market | venue | instrument | TF | horizon | schema).
Separate fields: antecedent_count, antecedent_support, joint_support_up/down, raw / Laplace-smoothed probabilities, base rates, edge, lift, score.
Mode OFF / OBSERVE by default; ASSIST may only HOLD a candidate when a fresh, supported, OPPOSITE edge exists; never creates or flips a side.

Validation (1.46, VALIDATION): the descriptive rule statistics above are in-sample (all labelled bars). Up to 92 rules were mined from the
same bars on overlapping labels (one label per bar, `horizon` bars ahead), so in-sample edges >= the threshold appeared on pure noise
(random walk: 'SUPPORTED' in 3 of 5 seeds). A rule now claims a direction on the chronologically EARLIER part (fit) and is `validated`
only when the LATER part (holdout, last `holdout_frac` of the labelled bars, fit purged by `horizon` bars at the boundary) shows the same
edge >= threshold with a one-sided test p (effective count n / horizon - overlapping labels are not independent) Bonferroni-adjusted for
every tested hypothesis (2 x rules) below `p_max`. assess() reports SUPPORTED / CONTRARY_EDGE only from validated rules; an in-sample
edge without validation is reported as IN_SAMPLE_ONLY. Models without the `validation` field (hand-built dicts) keep the old rule.
"""
from __future__ import annotations

import itertools
import math

SCHEMA = "PMW-AR-EVENTS-1"                      # event bits / catalog - unchanged
VALIDATION = "PMW-AR-VALIDATION-1:HOLDOUT_PURGED_BONFERRONI"
CATALOG = ("RSI_LOW", "RSI_HIGH", "PRICE_ABOVE_EMA", "PRICE_BELOW_EMA", "ATR_HIGH", "MOM_UP", "MOM_DOWN", "SESSION_EU")
DEFAULTS = {"horizon": 24, "min_move": 0.0, "min_rule_count": 50, "edge_threshold": 0.08, "alpha": 1.0, "max_rule_len": 3,
            "holdout_frac": 0.3, "p_max": 0.05}


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


def _p_one_sided(k: int, n: int, p0: float, n_eff: float) -> float:
    """One-sided normal test of the share k/n against p0 with the effective count n_eff (overlapping labels: n / horizon)."""
    if n <= 0 or n_eff < 1 or not 0.0 < p0 < 1.0:
        return 1.0
    z = (k / n - p0) / math.sqrt(p0 * (1 - p0) / n_eff)
    return 0.5 * math.erfc(z / math.sqrt(2))


def train(masks: list[int | None], labs: list[str | None], *, alpha=1.0, min_rule_count=50, max_rule_len=3, scope: dict | None = None,
          horizon: int = 1, holdout_frac: float = DEFAULTS["holdout_frac"], edge_threshold: float = DEFAULTS["edge_threshold"],
          p_max: float = DEFAULTS["p_max"]) -> dict:
    """masks / labs aligned per bar (labs[i] = direction of close[i + horizon] - close[i]). Descriptive statistics on all labelled bars
    (as before) + chronological holdout validation of every rule (module docstring)."""
    idx = [(i, m, y) for i, (m, y) in enumerate(zip(masks, labs)) if m is not None and y in ("UP", "DOWN")]
    rows = [(m, y) for _, m, y in idx]
    N = len(rows)
    up = sum(1 for _, y in rows if y == "UP")
    if N == 0:
        return {"status": "NO_DATA", "rules": [], "n_labeled": 0, "scope": scope or {}, "validation": VALIDATION, "validated_rules": 0}
    base_up_raw, base_down_raw = up / N, (N - up) / N
    base_up = (up + alpha) / (N + 2 * alpha)
    base_down = (N - up + alpha) / (N + 2 * alpha)
    h = max(1, int(horizon))
    n_hold = round(N * float(holdout_frac))
    t_cut = idx[N - n_hold][0] if 0 < n_hold < N else None
    fit = [(m, y) for i, m, y in idx if t_cut is not None and i + h <= t_cut]      # purge: no label window reaches into the holdout
    hold = [(m, y) for i, m, y in idx if t_cut is not None and i >= t_cut]
    nf, nh = len(fit), len(hold)
    uf, uh = sum(1 for _, y in fit if y == "UP"), sum(1 for _, y in hold if y == "UP")
    bf_up, bh_up = (uf + alpha) / (nf + 2 * alpha), (uh + alpha) / (nh + 2 * alpha)
    p0_up = uh / nh if nh else 0.5
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
            r = {"mask": mask, "events": [CATALOG[b] for b in combo], "length": L, "antecedent_count": n, "up_count": u, "down_count": d,
                 "antecedent_support": n / N, "joint_support_up": u / N, "joint_support_down": d / N,
                 "p_up_raw": u / n, "p_down_raw": d / n, "p_up": pu, "p_down": pd, "edge_up": pu - base_up, "edge_down": pd - base_down,
                 "lift_up": (u / n) / base_up_raw if base_up_raw > 0 else None, "lift_down": (d / n) / base_down_raw if base_down_raw > 0 else None,
                 "score_up": (pu - base_up) * math.log(1 + n), "score_down": (pd - base_down) * math.log(1 + n)}
            fs = [y for m, y in fit if m & mask == mask]
            hs = [y for m, y in hold if m & mask == mask]
            fu, hu = sum(1 for y in fs if y == "UP"), sum(1 for y in hs if y == "UP")
            fe_up = (fu + alpha) / (len(fs) + 2 * alpha) - bf_up
            he_up = (hu + alpha) / (len(hs) + 2 * alpha) - bh_up
            claim = "UP" if fe_up >= edge_threshold else ("DOWN" if -fe_up >= edge_threshold else None)
            r.update(fit_count=len(fs), fit_edge_up=fe_up, fit_edge_down=-fe_up, holdout_count=len(hs), holdout_up_count=hu,
                     holdout_edge_up=he_up, holdout_edge_down=-he_up, n_eff_holdout=len(hs) / h, claimed_direction=claim)
            rules.append(r)
    tests = 2 * len(rules)                             # every (rule, direction) hypothesis looked at
    for r in rules:
        claim, k, n = r["claimed_direction"], r["holdout_up_count"], r["holdout_count"]
        if claim is None or n == 0:
            p = 1.0
        elif claim == "UP":
            p = _p_one_sided(k, n, p0_up, n / h)
        else:
            p = _p_one_sided(n - k, n, 1.0 - p0_up, n / h)
        p_adj = min(1.0, p * tests)
        he = r["holdout_edge_up"] if claim == "UP" else (r["holdout_edge_down"] if claim == "DOWN" else None)
        ok = claim is not None and he is not None and he >= edge_threshold and p_adj < p_max
        r.update(p_value=p, p_adj=p_adj, validated=ok, validated_direction=claim if ok else None)
    return {"status": "READY", "schema": SCHEMA, "rules": rules, "n_labeled": N, "base_up": base_up, "base_down": base_down,
            "base_up_raw": base_up_raw, "alpha": alpha, "min_rule_count": min_rule_count, "scope": scope or {},
            "validation": VALIDATION, "validated_rules": sum(1 for r in rules if r["validated"]),
            "validation_params": {"holdout_frac": float(holdout_frac), "purge_bars": h, "n_fit": nf, "n_holdout": nh, "n_eff_holdout": nh / h,
                                  "tests_bonferroni": tests, "p_max": p_max, "edge_threshold": edge_threshold,
                                  "holdout_start_index": t_cut, "holdout_base_up_raw": p0_up if nh else None}}


def assess(model: dict, mask: int | None, direction: str, edge_threshold: float = 0.08, mode: str = "OBSERVE") -> dict:
    """Candidate direction LONG / SHORT vs the best matching rule. Output role: OBSERVE (diagnostic) or ASSIST (HOLD only).
    A model from train() (field `validation`): SUPPORTED / CONTRARY_EDGE (and an ASSIST HOLD) only from rules validated on the holdout."""
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
    extra = {}
    if model.get("validation"):
        d_for, d_against = ("UP", "DOWN") if direction == "LONG" else ("DOWN", "UP")
        vf = [r for r in matched if r.get("validated_direction") == d_for and r[f"holdout_{key}"] >= edge_threshold]
        va = [r for r in matched if r.get("validated_direction") == d_against and r[f"holdout_{opp}"] >= edge_threshold]
        supported = bool(vf)
        best_vf = max((r[f"holdout_{key}"] for r in vf), default=-math.inf)
        contrary = bool(va) and max(r[f"holdout_{opp}"] for r in va) > best_vf
        in_sample = best_for[key] >= edge_threshold or best_against[opp] >= edge_threshold
        weak = "IN_SAMPLE_ONLY" if in_sample else "WEAK_EDGE"
        extra = {"validation": model["validation"], "validated_rules_for": len(vf), "validated_rules_against": len(va)}
    else:                                               # hand-built model without validation fields: the 1.46 rule
        supported = best_for[key] >= edge_threshold
        contrary = best_against[opp] >= edge_threshold and best_against[opp] > best_for[key]
        weak = "WEAK_EDGE"
    action = "HOLD" if (mode == "ASSIST" and contrary) else "PASS"
    # 1.46: a contrary edge wins - "supported" and CONTRARY_EDGE / HOLD were reported together
    return {"mode": mode, "action": action, "candidate_direction_supported": False if contrary else (True if supported else None),
            "best_rule_for": best_for, "best_rule_against": best_against, "reason": "CONTRARY_EDGE" if contrary else ("SUPPORTED" if supported else weak),
            "matched_rules": len(matched), **extra,
            "note": "estymata kierunkowa – nie gwarancja; ASSIST może tylko wstrzymać, nigdy dodać stronę"}
