"""Registry of the 10 implemented strategies and the scanner that runs them on one MarketView."""
from __future__ import annotations

import hashlib

from . import base
from .s01_trend_pullback import TrendPullback
from .s02_adaptive_trend import AdaptiveTrend
from .s03_channel_breakout import ChannelBreakout
from .s04_volatility_compression_breakout import VolatilityCompressionBreakout
from .s05_session_range_breakout import SessionRangeBreakout
from .s06_breakout_retest import BreakoutRetest
from .s07_failed_breakout_reclaim import FailedBreakoutReclaim
from .s08_range_edge_reversion import RangeEdgeReversion
from .s09_statistical_mean_reversion import StatisticalMeanReversion
from .s10_exhaustion_structure_reversal import ExhaustionStructureReversal

REGISTRY_VERSION = "MQ-REGISTRY-1.0.0"
STRATEGIES: dict[str, base.Strategy] = {s.id: s for s in (
    TrendPullback(), AdaptiveTrend(), ChannelBreakout(), VolatilityCompressionBreakout(), SessionRangeBreakout(),
    BreakoutRetest(), FailedBreakoutReclaim(), RangeEdgeReversion(), StatisticalMeanReversion(), ExhaustionStructureReversal())}


def params_for(sid: str, overrides: dict | None) -> dict:
    s = STRATEGIES[sid]
    p = dict(s.params)
    for k, v in (overrides or {}).items():
        if k in p:
            p[k] = v
    return p


def describe() -> list[dict]:
    return [{"strategy_id": s.id, "name": s.name, "version": s.version, "family": s.family, "setup_tfs": list(s.setup_tfs),
             "context_tf": s.context_tf, "required_tfs": list(s.required_tfs), "min_bars": s.min_bars, "regime_fit": s.regime_fit,
             "params": s.params, "implemented": True, "validation_status": s.validation_status, "contract": base.CONTRACT_VERSION}
            for s in STRATEGIES.values()]


def setup_id_for(symbol: str, account_key: str | None, d: base.Draft) -> str:
    raw = f"{symbol}|{account_key}|{d.strategy_id}|{d.direction}|{d.timeframe}|{d.structure_key}"
    return "MQA-" + hashlib.sha256(raw.encode()).hexdigest()[:16]


def event_id_for(symbol: str, d: base.Draft) -> str:
    return "EV-" + hashlib.sha256(f"{symbol}|{d.event_key}".encode()).hexdigest()[:12]


def scan(view: base.MarketView, *, enabled: dict[str, bool], overrides: dict[str, dict], thresholds: dict,
         account_key: str | None, extra_fn=None) -> dict:
    """Run every scan-enabled strategy; returns published candidates and a per-strategy funnel.

    Funnel counters per strategy: drafts (recognised structures), below_watch, published by stage.
    A strategy without its own required data reports DATA_MISSING/WARMING_UP - the rest still run.
    """
    regime_state = (view.regime or {}).get("state")
    candidates, per = [], {}
    for sid, s in STRATEGIES.items():
        if not enabled.get(sid, True):
            per[sid] = {"status": "DISABLED", "reasons": ["SCAN_DISABLED_BY_USER"], "drafts": 0, "published": {}}
            continue
        status, why = s.check_data(view)
        if status != "OK":
            per[sid] = {"status": status, "reasons": why, "drafts": 0, "published": {}}
            continue
        p = params_for(sid, overrides.get(sid))
        try:
            drafts = s.detect(view, p)
        except (ValueError, IndexError, ZeroDivisionError, KeyError, TypeError) as exc:
            per[sid] = {"status": "ERROR", "reasons": [f"{type(exc).__name__}: {exc}"[:160]], "drafts": 0, "published": {}}
            continue
        fit = float(s.regime_fit.get(regime_state, 0.3))
        pub: dict[str, int] = {}
        below = 0
        reasons: list[str] = []
        chash = s.config_hash(p)
        for d in drafts:
            extra = extra_fn(d) if extra_fn else None
            sc = base.score(d, view, extra)
            stage, more = base.finalize(d, sc, thresholds)
            if stage is None:
                below += 1
                reasons.append(f"{d.direction}:{d.timeframe}:SCORE_{sc['total']:.0f}<WATCH")
                continue
            pub[stage] = pub.get(stage, 0) + 1
            v = view.tfs[d.timeframe]
            counter = d.countertrend or sc["htf_countertrend"]
            missing = list(dict.fromkeys(d.missing + more + ([] if d.targets else ["NO_VALID_TARGET"])
                                         + ([] if sc["points"]["extra"] else ["EXTRA_CONFIRMATION_UNAVAILABLE"])))
            candidates.append({
                "schema_version": base.SCHEMA_VERSION, "strategy_id": sid, "strategy_name": s.name, "strategy_version": s.version,
                "config_hash": chash, "setup_id": setup_id_for(view.symbol, account_key, d), "event_id": event_id_for(view.symbol, d),
                "symbol": view.symbol, "direction": d.direction, "timeframe": d.timeframe, "horizon": d.horizon, "family": s.family,
                "regime": regime_state, "stage": stage, "phase": d.phase, "setup_score": sc["total"], "score": sc,
                "strategy_fit_score": round(fit * 100, 1), "structure_key": d.structure_key, "anchor_time": d.anchor_time,
                "source_time": v.t[-1] if v.t else None, "forming_bar_used": bool(v.forming), "entry_plan": d.entry_plan,
                "invalidation_level": d.invalidation_level, "invalidation_rule": d.invalidation_rule, "stop_loss": d.stop_loss,
                "targets": d.targets, "exit_rules": d.exit_rules, "expires_bars": d.expires_bars,
                "reason_codes": d.reason_codes + (["COUNTERTREND"] if counter else []), "missing_confirmations": missing,
                "countertrend": counter, "facts": d.facts, "validation_status": s.validation_status, "synthetic": view.synthetic})
        per[sid] = {"status": "OK", "reasons": reasons[:6] if not drafts or below else [], "drafts": len(drafts), "below_watch": below,
                    "published": pub, "regime_fit": fit, "config_hash": chash}
        if not drafts:
            per[sid]["reasons"] = ["NO_STRUCTURE_MATCHING_DEFINITION"]
    return {"candidates": candidates, "per_strategy": per, "regime": regime_state}
