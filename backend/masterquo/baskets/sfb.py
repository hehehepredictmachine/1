"""Strategy Filter Bucket (Apollo23 TASK 018) - evidence-governed eligibility layer over the ACTIVE 60 / 6 / 2 catalogue.

Two independent gates per exact scope (profile | venue | environment | product | instrument):
  1. market compatibility (hard): profile, product, settlement, required capabilities / inputs, retired scope (TASK 020) -> INCOMPATIBLE / DATA_UNAVAILABLE
  2. performance evidence from TASK 014 canonical outcomes with exact lineage (strategy_id + version + config_hash), never SIGNAL_SIMULATION:
     independent events, active days, chronological outer folds with positive net-R, observed regimes, cost coverage, block-bootstrap LCB of
     mean net R -> ELIGIBLE / VALIDATION_PENDING / COMPATIBLE_UNVALIDATED / STALE_ARTIFACT.
Modes: OFF (default, zero effect) | OBSERVE | SHADOW (record what would be filtered) | ASSIST (only ELIGIBLE strategies run; none -> NO_TRADE_BUCKET).
apply_to_execution is a constant False (not configurable). No cross-profile pooling. Never adds a strategy, signal, side or plan.
"""
from __future__ import annotations

import hashlib
import json
import random
import time

from . import catalog as CAT

MODES = ("OFF", "OBSERVE", "SHADOW", "ASSIST", "MANUAL_RESEARCH")
APPLY_TO_EXECUTION = False
STATUSES = ("INCOMPATIBLE", "DATA_UNAVAILABLE", "COMPATIBLE_UNVALIDATED", "VALIDATION_PENDING", "ELIGIBLE", "DEGRADED", "QUARANTINED_OVERFIT",
            "STALE_ARTIFACT", "NO_TRADE_BUCKET", "RETIRED_SCOPE")
DEFAULT_CONFIG = {"mode": "OFF", "allow_cross_profile_pooling": False, "min_independent_events": 100, "min_local_instrument_events": 50,
                  "min_active_days": 30, "min_outer_folds": 5, "min_positive_oos_folds": 3, "min_observed_regimes": 2, "min_cost_coverage": 0.98,
                  "bootstrap_confidence": 0.90, "min_net_r_lcb": 0.0, "stale_after_hours": 168, "bootstrap_block": 10, "bootstrap_reps": 400}
PROFILE_SUPPORT = {"FOREX_MT5": {"products": {"CFD", "FX_SPOT_CFD", "METAL_CFD"}}, "CRYPTO_FOMO_PERPS": {"products": {"PERPETUAL"}}}


class ConfigError(ValueError):
    pass


def validate_config(cfg: dict) -> dict:
    if "apply_to_execution" in cfg:
        raise ConfigError("apply_to_execution nie jest konfigurowalne (stała false)")
    bad = [k for k in cfg if k not in DEFAULT_CONFIG]
    if bad:
        raise ConfigError(f"UNKNOWN_KEYS: {bad}")
    out = {**DEFAULT_CONFIG, **cfg}
    if out["mode"] not in MODES:
        raise ConfigError(f"mode: {MODES}")
    if out["allow_cross_profile_pooling"]:
        raise ConfigError("allow_cross_profile_pooling: false (TASK 018 v1)")
    return out


def compatibility(strategy: dict, scope: dict) -> tuple[str, list[str]]:
    sid = strategy["strategy_id"]
    if CAT.retired_reason(sid) or CAT.retired_reason(profile_id=scope.get("profile")):
        return "RETIRED_SCOPE", ["RETIRED_STRATEGY_ID"]
    if sid not in CAT.BY_ID:
        return "INCOMPATIBLE", ["UNKNOWN_STRATEGY"]
    prof = scope.get("profile")
    if prof not in PROFILE_SUPPORT:
        return "INCOMPATIBLE", ["UNSUPPORTED_PROFILE"]
    if strategy["profile_id"] != prof:
        return "INCOMPATIBLE", ["PROFILE_MISMATCH"]
    prod = scope.get("product")
    if prod and prod not in strategy["supported_product_types"]:
        return "INCOMPATIBLE", ["PRODUCT_MISMATCH"]
    have = set(scope.get("capabilities") or [])
    if scope.get("capabilities") is not None:
        missing = [c for c in strategy["required_capabilities"] if c not in have]
        if missing:
            return "DATA_UNAVAILABLE", [f"MISSING_CAPABILITY:{m}" for m in missing]
    return "COMPATIBLE", []


def _block_bootstrap_lcb(xs: list[float], block: int, reps: int, conf: float, seed: int = 0) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    rnd = random.Random(seed)
    nb = max(1, n // block)
    means = []
    for _ in range(reps):
        s = []
        while len(s) < n:
            i = rnd.randrange(0, max(1, n - block + 1))
            s.extend(xs[i:i + block])
        means.append(sum(s[:n]) / n)
    means.sort()
    return means[int((1 - conf) * reps)]


def evidence(strategy: dict, outcomes: list[dict], cfg: dict, now: float | None = None) -> dict:
    """outcomes: TASK 014 canonical rows for this exact scope {strategy_id, version, config_hash, net_R, closed_ts, event_group_id, regime,
    cost_complete, source}. Rows with wrong lineage or SIGNAL_SIMULATION are excluded (never evidence)."""
    now = time.time() if now is None else now
    rows = [o for o in outcomes if o.get("strategy_id") == strategy["strategy_id"] and o.get("config_hash") == strategy["config_hash"]
            and o.get("version") == strategy["version"] and o.get("source") != "SIGNAL_SIMULATION" and o.get("net_R") is not None]
    excluded = len(outcomes) - len(rows)
    if not rows:
        return {"status": "COMPATIBLE_UNVALIDATED", "reason_codes": ["NO_LINEAGE_EVIDENCE"], "n_events": 0, "excluded_rows": excluded}
    rows.sort(key=lambda o: o["closed_ts"])
    groups: dict[str, list[float]] = {}
    for o in rows:
        groups.setdefault(o.get("event_group_id") or str(o["closed_ts"]), []).append(o["net_R"])
    ev = [sum(v) / len(v) for v in groups.values()]
    n = len(ev)
    days = len({int(o["closed_ts"] // 86400) for o in rows})
    regimes = len({o.get("regime") for o in rows if o.get("regime")})
    cov = sum(1 for o in rows if o.get("cost_complete", False)) / len(rows)
    k = cfg["min_outer_folds"]
    folds = [ev[i * n // k:(i + 1) * n // k] for i in range(k)] if n >= k else []
    pos = sum(1 for f in folds if f and sum(f) / len(f) > 0)
    lcb = _block_bootstrap_lcb(ev, cfg["bootstrap_block"], cfg["bootstrap_reps"], cfg["bootstrap_confidence"])
    last = rows[-1]["closed_ts"]
    reasons = []
    if n < cfg["min_independent_events"]:
        reasons.append(f"EVENTS {n}<{cfg['min_independent_events']}")
    if days < cfg["min_active_days"]:
        reasons.append(f"ACTIVE_DAYS {days}<{cfg['min_active_days']}")
    if pos < cfg["min_positive_oos_folds"]:
        reasons.append(f"POSITIVE_FOLDS {pos}<{cfg['min_positive_oos_folds']}")
    if regimes < cfg["min_observed_regimes"]:
        reasons.append(f"REGIMES {regimes}<{cfg['min_observed_regimes']}")
    if cov < cfg["min_cost_coverage"]:
        reasons.append(f"COST_COVERAGE {cov:.2f}<{cfg['min_cost_coverage']}")
    if lcb is None or lcb <= cfg["min_net_r_lcb"]:
        reasons.append("NET_R_LCB_NOT_ABOVE_HURDLE")
    stale = (now - last) / 3600 > cfg["stale_after_hours"]
    if stale:
        reasons.append("STALE_EVIDENCE")
    status = "ELIGIBLE" if not reasons else ("STALE_ARTIFACT" if stale and len(reasons) == 1 else
                                             "COMPATIBLE_UNVALIDATED" if n < cfg["min_independent_events"] // 2 else "VALIDATION_PENDING")
    return {"status": status, "reason_codes": reasons, "n_events": n, "active_days": days, "positive_folds": pos, "folds": len(folds),
            "regimes": regimes, "cost_coverage": round(cov, 4), "net_r_lcb": lcb, "mean_net_r": sum(ev) / n, "excluded_rows": excluded}


class StrategyFilterBucket:
    def __init__(self, cfg: dict | None = None, outcomes_fn=None):
        self.cfg = validate_config(cfg or {})
        self.outcomes_fn = outcomes_fn or (lambda scope: [])
        self.snapshots: list[dict] = []

    def evaluate(self, strategies: list[dict], scope: dict) -> dict:
        items = {}
        outs = self.outcomes_fn(scope)
        for s in strategies:
            comp, rc = compatibility(s, scope)
            if comp != "COMPATIBLE":
                items[s["strategy_id"]] = {"compatibility_status": comp, "eligibility_status": comp, "reason_codes": rc}
                continue
            e = evidence(s, outs, self.cfg)
            items[s["strategy_id"]] = {"compatibility_status": comp, "eligibility_status": e["status"], "reason_codes": e["reason_codes"], "evidence": e}
        body = {"scope": scope, "mode": self.cfg["mode"], "items": items, "config": self.cfg, "apply_to_execution": APPLY_TO_EXECUTION}
        sid = hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()[:16]
        snap = {**body, "snapshot_id": sid, "at": time.time(), "bucket_key": "|".join(str(scope.get(k, "")) for k in ("profile", "venue", "environment",
                                                                                                                          "product", "instrument"))}
        self.snapshots = (self.snapshots + [snap])[-200:]
        return snap

    def filter(self, strategies: list[dict], scope: dict) -> tuple[list[dict], dict | None]:
        """OFF: unchanged list, no snapshot. OBSERVE / SHADOW: unchanged list + snapshot. ASSIST: only ELIGIBLE (may be empty = NO_TRADE_BUCKET)."""
        mode = self.cfg["mode"]
        if mode == "OFF":
            return strategies, None
        snap = self.evaluate(strategies, scope)
        if mode == "ASSIST":
            kept = [s for s in strategies if snap["items"][s["strategy_id"]]["eligibility_status"] == "ELIGIBLE" or s["kind"] == "HEDGING"]
            snap["would_keep"] = [s["strategy_id"] for s in kept]
            snap["bucket_status"] = "NO_TRADE_BUCKET" if not [s for s in kept if s["kind"] != "HEDGING"] else "ACTIVE"
            return kept, snap
        snap["would_keep"] = [s["strategy_id"] for s in strategies if snap["items"][s["strategy_id"]]["eligibility_status"] == "ELIGIBLE"]
        return strategies, snap

    def status(self) -> dict:
        return {"mode": self.cfg["mode"], "apply_to_execution": APPLY_TO_EXECUTION, "config": self.cfg, "active_catalog": CAT.validate(),
                "last_snapshot": self.snapshots[-1] if self.snapshots else None}
