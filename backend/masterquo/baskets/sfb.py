"""Strategy Filter Bucket (Apollo23 TASK 018) - evidence-governed eligibility layer over the ACTIVE 60 / 6 / 2 catalogue.

Two independent gates per exact scope (profile | venue | environment | product | instrument):
  1. market compatibility (hard): profile, product, required capabilities, retired scope (TASK 020) -> INCOMPATIBLE / DATA_UNAVAILABLE
     (1.46 docstring: settlement follows from the profile - one per profile; the extra required_inputs are mirrored in required_capabilities.
     A scope without its own capability list is checked against the profile's declared data-path registry - anything else NOT_VERIFIED)
  2. performance evidence from TASK 014 canonical outcomes with exact lineage (strategy_id + version + config_hash), never SIGNAL_SIMULATION:
     independent events, active days, chronological outer folds with positive net-R, observed regimes, cost coverage, block-bootstrap LCB of
     mean net R -> ELIGIBLE / VALIDATION_PENDING / COMPATIBLE_UNVALIDATED / STALE_ARTIFACT.
Modes: OFF (default, zero effect) | OBSERVE | SHADOW (record what would be filtered) | ASSIST (only ELIGIBLE strategies run; none -> NO_TRADE_BUCKET).
1.46: ASSIST can no longer be saved (BasketService.set_sfb refuses it - workflow v3.2 modules stay read-only); an ASSIST stored by 1.45
still runs as ASSIST (rule 1: the filter decides which basket strategies reach execution).
apply_to_execution is a constant False (not configurable). No cross-profile pooling. Never adds a strategy, signal, side or plan.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import time

from . import catalog as CAT
from .hyperliquid import CAPABILITIES as _HL_CAPS

MODES = ("OFF", "OBSERVE", "SHADOW", "ASSIST", "MANUAL_RESEARCH")
APPLY_TO_EXECUTION = False
STATUSES = ("INCOMPATIBLE", "DATA_UNAVAILABLE", "COMPATIBLE_UNVALIDATED", "VALIDATION_PENDING", "ELIGIBLE", "DEGRADED", "QUARANTINED_OVERFIT",
            "STALE_ARTIFACT", "NO_TRADE_BUCKET", "RETIRED_SCOPE")
DEFAULT_CONFIG = {"mode": "OFF", "allow_cross_profile_pooling": False, "min_independent_events": 100, "min_local_instrument_events": 50,
                  "min_active_days": 30, "min_outer_folds": 5, "min_positive_oos_folds": 3, "min_observed_regimes": 2, "min_cost_coverage": 0.98,
                  "bootstrap_confidence": 0.90, "min_net_r_lcb": 0.0, "stale_after_hours": 168, "bootstrap_block": 10, "bootstrap_reps": 400}
# 1.46: "capabilities" = what the profile's data path itself always provides (MT5 closed bars with tick volume + UTC session clock; the
# public Hyperliquid API as declared in hyperliquid.CAPABILITIES). Account / configuration / user-declared inputs (hedging account mode,
# calendar, partner symbols, declared exposure) and NOT_VERIFIED semantics (Hyperliquid trade side, TASK 004) are not in it.
_HL_CAP_NAMES = {"closed_bars": "closed_bar", "benchmark_btc": "history", "real_volume": "real_volume", "l2_orderbook": "l2_orderbook",
                 "open_interest": "open_interest", "funding": "funding", "trades_aggressor": "trades_aggressor"}     # strategy name -> adapter name
PROFILE_SUPPORT = {"FOREX_MT5": {"products": {"CFD", "FX_SPOT_CFD", "METAL_CFD"},
                                 "capabilities": frozenset({"closed_bars", "session_calendar", "tick_activity_proxy"})},
                   "CRYPTO_FOMO_PERPS": {"products": {"PERPETUAL"},
                                         "capabilities": frozenset(k for k, a in _HL_CAP_NAMES.items() if _HL_CAPS.get(a) is True)}}


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
    # 1.46: types / ranges (reps=0 -> IndexError, block<=0 -> endless loop, strings -> TypeError)
    ints = {"min_independent_events": (1, 10**6), "min_local_instrument_events": (0, 10**6), "min_active_days": (0, 3650), "min_outer_folds": (1, 100),
            "min_positive_oos_folds": (0, 100), "min_observed_regimes": (0, 100), "stale_after_hours": (1, 10**5), "bootstrap_block": (1, 10**4),
            "bootstrap_reps": (10, 10**5)}
    for k, (lo, hi) in ints.items():
        v = out[k]
        if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
            raise ConfigError(f"{k}: liczba całkowita {lo}..{hi}")
    for k, lo, hi in (("min_cost_coverage", 0.0, 1.0), ("bootstrap_confidence", 0.5, 0.999), ("min_net_r_lcb", -100.0, 100.0)):
        v = out[k]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= float(v) <= hi:
            raise ConfigError(f"{k}: liczba {lo}..{hi}")
    if out["allow_cross_profile_pooling"]:
        raise ConfigError("allow_cross_profile_pooling: false (TASK 018 v1)")
    return out


def compatibility(strategy: dict, scope: dict) -> tuple[str, list[str]]:
    sid = strategy["strategy_id"]
    retired = CAT.retired_reason(sid) or CAT.retired_reason(profile_id=scope.get("profile"))
    if retired:                                         # 1.46: the real code (RETIRED_PROFILE was reported as RETIRED_STRATEGY_ID)
        return "RETIRED_SCOPE", [retired]
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
    if scope.get("capabilities") is not None:
        have, code = set(scope["capabilities"]), "MISSING_CAPABILITY"
    else:
        # 1.46: a scope without a capability list (BasketService) skipped the hard gate - unknown capabilities counted as available (rule 6)
        have, code = PROFILE_SUPPORT[prof]["capabilities"], "CAPABILITY_NOT_VERIFIED"
    missing = [c for c in strategy["required_capabilities"] if c not in have]
    if missing:
        return "DATA_UNAVAILABLE", [f"{code}:{m}" for m in missing]
    return "COMPATIBLE", []


def _block_bootstrap_lcb(xs: list[float], block: int, reps: int, conf: float, seed: int = 0) -> float | None:
    n = len(xs)
    if n < 2 or block < 1:                    # 1.46: block < 1 never ended the loop below (only validate_config guarded it)
        return None
    block = min(block, max(1, n // 2))        # 1.46: n <= block -> every resample was the whole series (LCB = sample mean, no uncertainty)
    rnd = random.Random(seed)
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
    # 1.46: only finite net_R (NaN passed and skipped the LCB gate) and only rows CLOSED by `now` (no look-ahead when evaluated as of a past time)
    rows = [o for o in outcomes if o.get("strategy_id") == strategy["strategy_id"] and o.get("config_hash") == strategy["config_hash"]
            and o.get("version") == strategy["version"] and o.get("source") != "SIGNAL_SIMULATION"
            and isinstance(o.get("net_R"), (int, float)) and not isinstance(o.get("net_R"), bool) and math.isfinite(o["net_R"])
            and isinstance(o.get("closed_ts"), (int, float)) and o["closed_ts"] <= now]
    # 1.46: only this strategy's rows count as excluded (valid rows of the other strategies of the scope were counted too)
    excluded = sum(1 for o in outcomes if o.get("strategy_id") == strategy["strategy_id"]) - len(rows)
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


def _no_outcomes(scope: dict) -> list[dict]:
    """Default evidence source: none (TASK 014 outcomes with the basket strategies' lineage are not connected) - reported NOT_CONNECTED."""
    return []


def _selection(strategies: list[dict], items: dict) -> dict:
    """1.46: ONE selection for every mode except OFF (SHADOW / OBSERVE recorded only ELIGIBLE and no bucket_status, so the shadow did not
    predict ASSIST). would_keep = ELIGIBLE; hedging_passthrough = HEDGING strategies ASSIST keeps without evidence (they only protect
    existing exposure); bucket_status = NO_TRADE_BUCKET when no non-hedging strategy is ELIGIBLE."""
    keep = [s["strategy_id"] for s in strategies if items[s["strategy_id"]]["eligibility_status"] == "ELIGIBLE"]
    hedging = [s["strategy_id"] for s in strategies if s["kind"] == "HEDGING" and s["strategy_id"] not in keep]
    trading = [s for s in strategies if s["strategy_id"] in keep and s["kind"] != "HEDGING"]
    return {"would_keep": keep, "hedging_passthrough": hedging, "bucket_status": "ACTIVE" if trading else "NO_TRADE_BUCKET"}


class StrategyFilterBucket:
    def __init__(self, cfg: dict | None = None, outcomes_fn=None):
        self.cfg = validate_config(cfg or {})
        self.outcomes_fn = outcomes_fn or _no_outcomes
        self.snapshots: list[dict] = []

    @property
    def evidence_source(self) -> str:
        """1.46: NOT_CONNECTED while no outcome source was handed over (BasketService passes none) - ELIGIBLE is then unreachable and the
        snapshots must not read as an evaluation."""
        return "NOT_CONNECTED" if self.outcomes_fn is _no_outcomes else "CONNECTED"

    def evaluate(self, strategies: list[dict], scope: dict) -> dict:
        items = {}
        outs = self.outcomes_fn(scope)
        src = self.evidence_source
        for s in strategies:
            comp, rc = compatibility(s, scope)
            if comp != "COMPATIBLE":
                items[s["strategy_id"]] = {"compatibility_status": comp, "eligibility_status": comp, "reason_codes": rc}
                continue
            e = evidence(s, outs, self.cfg)
            rc = e["reason_codes"] + (["EVIDENCE_SOURCE_NOT_CONNECTED"] if src == "NOT_CONNECTED" else [])
            items[s["strategy_id"]] = {"compatibility_status": comp, "eligibility_status": e["status"], "reason_codes": rc, "evidence": e}
        body = {"scope": scope, "mode": self.cfg["mode"], "items": items, "config": self.cfg, "apply_to_execution": APPLY_TO_EXECUTION}
        sid = hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()[:16]
        snap = {**body, "snapshot_id": sid, "at": time.time(), "bucket_key": "|".join(str(scope.get(k, "")) for k in ("profile", "venue", "environment",
                                                                                                                          "product", "instrument")),
                "evidence_source": src, **_selection(strategies, items)}
        # 1.46: published only when complete (filter() added would_keep / bucket_status to the already visible dict - the status endpoint
        # could serialise it mid-change)
        self.snapshots = (self.snapshots + [snap])[-200:]
        return snap

    def filter(self, strategies: list[dict], scope: dict) -> tuple[list[dict], dict | None]:
        """OFF: unchanged list, no snapshot. OBSERVE / SHADOW: unchanged list + snapshot. ASSIST: ELIGIBLE + HEDGING (no non-hedging
        ELIGIBLE = NO_TRADE_BUCKET). The snapshot carries the same selection in every mode."""
        mode = self.cfg["mode"]
        if mode == "OFF":
            return strategies, None
        snap = self.evaluate(strategies, scope)
        if mode == "ASSIST":
            keep = set(snap["would_keep"]) | set(snap["hedging_passthrough"])
            return [s for s in strategies if s["strategy_id"] in keep], snap
        return strategies, snap

    def status(self) -> dict:
        src = self.evidence_source
        return {"mode": self.cfg["mode"], "mode_requested": getattr(self, "mode_requested", None), "apply_to_execution": APPLY_TO_EXECUTION,
                "config": self.cfg, "active_catalog": CAT.validate(),
                # 1.46: the evidence source and the configurable gate that is not evaluated are stated, not implied
                "evidence_source": {"state": src, "reason": ("brak podłączonego źródła wyników TASK 014 z linią strategii koszyków – każda zgodna "
                                                             "strategia = COMPATIBLE_UNVALIDATED (NO_LINEAGE_EVIDENCE), ELIGIBLE nieosiągalne")
                                    if src == "NOT_CONNECTED" else None},
                "not_implemented": {"min_local_instrument_events": "NOT_IMPLEMENTED: klucz konfiguracji zapisywany, bramka nie jest oceniana"},
                "last_snapshot": self.snapshots[-1] if self.snapshots else None}
