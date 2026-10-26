"""Common setup contract for every strategy engine (PMW-EVAL-CONTRACT-1).

SetupCandidate = one trade idea, independent of the engine that produced it (S01-S12 ACTIVE profile, SCALPING/HEDGING, ...).
SetupAssessment = the shared evaluation of that idea (probability of the defined event, net EV, uncertainty, execution conditions,
portfolio state) and a SHADOW decision. Nothing here sends, sizes or blocks an order.

Times are UTC epoch seconds. `decision_ts` is the moment the idea is evaluated; every input must be known by then
(`features_as_of` <= decision_ts, `data_as_of` <= decision_ts) - a value from the future is a contract violation, not a warning.
Prices are instrument prices (Bid chart OHLC; the entry is priced on the executable side: Ask for LONG, Bid for SHORT).
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field

VERSION = "PMW-EVAL-CONTRACT-1"
ENGINES = ("ACTIVE_S01_S12", "SH_SCALPING", "SH_HEDGING")
DECISIONS = ("ACCEPT", "REDUCE", "DEFER", "REJECT")
TF_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "H8": 28800, "D1": 86400}


class ContractError(ValueError):
    pass


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(float(x))


@dataclass
class SetupCandidate:
    setup_id: str
    engine: str
    strategy_id: str
    symbol: str
    instrument: str
    timeframe: str
    decision_ts: float
    direction: str                                  # LONG / SHORT
    entry_type: str                                 # MARKET_ON_CONFIRMATION / MARKET / LIMIT
    entry_price: float
    stop_loss: float
    targets: list[dict]                             # [{"price", "weight"}] in execution order; weights sum to 1
    horizon_s: float                                # validity of the event definition (TP before SL within the horizon)
    stage: str = "CONFIRMED"                        # WATCH / EARLY / CONFIRMED (engine stage)
    version: int = 1
    market_regime: dict = field(default_factory=dict)       # {"state", "source"} - the engine's own regime, source named
    features: dict = field(default_factory=dict)
    features_as_of: float | None = None
    data_quality: dict = field(default_factory=dict)        # {"status", "data_as_of", "reasons"}
    execution_context: dict = field(default_factory=dict)   # spread, quote_age_s, commission_known, margin_mode, cost_price
    score: float | None = None                              # engine heuristic 0-100 - never a probability
    engine_probability: dict | None = None                  # probability already attached by the engine (event named)
    source_ref: dict = field(default_factory=dict)          # row id / signal id for traceability
    schema: str = VERSION

    def key(self) -> str:
        return hashlib.sha256(json.dumps([self.engine, self.setup_id, self.version, self.stage], sort_keys=True).encode()).hexdigest()[:20]

    def validate(self) -> "SetupCandidate":
        if self.engine not in ENGINES:
            raise ContractError(f"ENGINE_UNKNOWN:{self.engine}")
        if self.direction not in ("LONG", "SHORT"):
            raise ContractError(f"DIRECTION_INVALID:{self.direction}")
        if self.timeframe not in TF_SECONDS:
            raise ContractError(f"TIMEFRAME_INVALID:{self.timeframe}")
        for k in ("entry_price", "stop_loss", "decision_ts", "horizon_s"):
            if not _finite(getattr(self, k)):
                raise ContractError(f"NOT_FINITE:{k}")
        if self.horizon_s <= 0:
            raise ContractError("HORIZON_NOT_POSITIVE")
        if not self.targets:
            raise ContractError("NO_TARGETS")
        sgn = 1 if self.direction == "LONG" else -1
        if sgn * (self.entry_price - self.stop_loss) <= 0:
            raise ContractError("STOP_ON_WRONG_SIDE")
        wsum = 0.0
        for t in self.targets:
            if not _finite(t.get("price")) or not _finite(t.get("weight")) or t["weight"] < 0:
                raise ContractError("TARGET_INVALID")
            if sgn * (t["price"] - self.entry_price) <= 0:
                raise ContractError("TARGET_ON_WRONG_SIDE")
            wsum += t["weight"]
        if abs(wsum - 1.0) > 1e-3:
            raise ContractError(f"TARGET_WEIGHTS_SUM:{wsum:.4f}")
        for k in ("features_as_of",):
            v = getattr(self, k)
            if v is not None and v > self.decision_ts + 1e-6:
                raise ContractError(f"LOOKAHEAD:{k}")                       # an input from after the decision
        da = (self.data_quality or {}).get("data_as_of")
        if da is not None and da > self.decision_ts + 1e-6:
            raise ContractError("LOOKAHEAD:data_as_of")
        return self

    def risk_price(self) -> float:
        return abs(self.entry_price - self.stop_loss)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SetupAssessment:
    setup_id: str
    engine: str
    strategy_id: str
    candidate_key: str
    decision_ts: float
    event: str                                     # the exact event the probability refers to
    probability: float | None = None
    probability_source: str | None = None          # model id / NONE
    probability_calibrated: bool = False
    probability_status: str = "NO_MODEL"           # CALIBRATED / UNCALIBRATED / NO_MODEL / EVENT_MISMATCH
    probability_interval: list | None = None       # [lo, hi] when the calibration sample size is known
    gain_r: float | None = None                    # net of costs, in R (R = entry->SL price distance)
    loss_r: float | None = None                    # net of costs, positive number
    cost_r: float | None = None
    break_even_probability: float | None = None    # p* = L / (G + L): the EV is positive only above it
    expected_value_r: float | None = None
    expected_value_interval_r: list | None = None
    uncertainty: dict = field(default_factory=dict)
    model_agreement: dict = field(default_factory=dict)
    market_regime: dict = field(default_factory=dict)
    execution_quality: dict = field(default_factory=dict)
    portfolio_risk_status: dict = field(default_factory=dict)
    hedge_assessment: dict = field(default_factory=dict)
    decision: str = "REJECT"
    rejection_reasons: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    model_versions: dict = field(default_factory=dict)
    data_timestamp: float | None = None
    mode: str = "SHADOW"                           # the assessment never gates or sends anything
    schema: str = VERSION

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------------------------- adapters
def _ts(iso_or_epoch) -> float | None:
    if iso_or_epoch is None:
        return None
    if isinstance(iso_or_epoch, (int, float)):
        return float(iso_or_epoch)
    from datetime import datetime
    s = str(iso_or_epoch).replace("Z", "+00:00")
    return datetime.fromisoformat(s).timestamp()


def from_active_row(row: dict, *, symbol: str, instrument: str, quote: dict | None, regime: dict | None, now: float,
                    data_status: str | None = None, cost_price: float | None = None, commission_known: bool | None = None) -> SetupCandidate:
    """S01-S12 tracker row -> candidate. Entry on the executable side of the CURRENT quote (the plan is MARKET_ON_CONFIRMATION);
    the horizon is the setup expiry (expires_at) or, without one, 12 bars of the setup timeframe."""
    rec = row["record"]
    side = rec["direction"]
    q = quote or {}
    entry = q.get("ask") if side == "LONG" else q.get("bid")
    ep = rec.get("entry_plan") or {}
    if entry is None:
        entry = ep.get("trigger_level") or ep.get("reference_price")
    tf = rec.get("timeframe") or "M15"
    exp = _ts(row.get("expires_at"))
    horizon = max(TF_SECONDS.get(tf, 900), (exp - now)) if exp and exp > now else 12 * TF_SECONDS.get(tf, 900)
    tg = [{"price": float(t["price"]), "weight": float(t.get("weight") or 0.0), "basis": t.get("basis")} for t in rec.get("targets") or []]
    ws = sum(t["weight"] for t in tg)
    if tg and ws > 0:
        for t in tg:
            t["weight"] = t["weight"] / ws
    return SetupCandidate(
        setup_id=row["setup_id"], engine="ACTIVE_S01_S12", strategy_id=rec["strategy_id"], symbol=symbol, instrument=instrument,
        timeframe=tf, decision_ts=now, direction=side, entry_type=ep.get("order_type") or "MARKET_ON_CONFIRMATION",
        entry_price=float(entry) if entry is not None else float("nan"), stop_loss=float(rec.get("stop_loss") or float("nan")), targets=tg,
        horizon_s=float(horizon), stage=row.get("stage") or "WATCH", version=int(row.get("version") or 1),
        market_regime={"state": (regime or {}).get("state") or rec.get("regime"), "source": "strategies.regime (MarketRegimeEngine)"},
        features={"setup_score": rec.get("setup_score"), "strategy_fit_score": rec.get("strategy_fit_score"), "family": rec.get("family"),
                  "countertrend": rec.get("countertrend")},
        features_as_of=_ts(rec.get("source_time")) if rec.get("source_time") else None,
        data_quality={"status": data_status or ("STALE" if row.get("stale") else "OK"), "data_as_of": None, "reasons": []},
        execution_context={"spread": (q.get("ask") - q.get("bid")) if q.get("ask") is not None and q.get("bid") is not None else None,
                           "quote_age_s": q.get("age_seconds", q.get("age_s")), "cost_price": cost_price, "commission_known": commission_known},
        score=rec.get("setup_score"), source_ref={"tracker_setup_id": row["setup_id"], "event_id": rec.get("event_id")})


def from_sh_setup(su: dict, *, regime: dict | None = None) -> SetupCandidate:
    """SCALPING / HEDGING setup (status READY carries levels) -> candidate. Weights = the strategy's partial shares."""
    side = {"BUY": "LONG", "SELL": "SHORT"}.get(su.get("side"), su.get("side"))
    tps = su.get("tps") or []
    sh = [float(t.get("share") or 0.0) for t in tps]
    tot = sum(sh) or 1.0
    eng = "SH_" + su["strategy"]
    prob = su.get("probability") or {}
    return SetupCandidate(
        setup_id=su.get("signal_id") or "SH-UNKNOWN", engine=eng, strategy_id=su["strategy"], symbol=su.get("symbol") or "",
        instrument=su.get("instrument") or "", timeframe="M1", decision_ts=float(su.get("created_at") or 0.0), direction=side,
        entry_type="MARKET", entry_price=float(su.get("entry_ref") if su.get("entry_ref") is not None else float("nan")),
        stop_loss=float(su.get("sl") if su.get("sl") is not None else float("nan")),
        targets=[{"price": float(t["price"]), "weight": s / tot, "basis": t.get("name")} for t, s in zip(tps, sh)],
        horizon_s=60.0 * float(su.get("horizon_minutes") or 30), stage="CONFIRMED" if su.get("status") == "READY" else str(su.get("status")),
        market_regime={"state": (regime or {}).get("state"), "source": "sh.context (RegimeMachine v2)"},
        features={"net_rr": su.get("net_rr"), "mode": su.get("mode"), "model_mode": su.get("model_mode")},
        features_as_of=float(su.get("created_at") or 0.0),
        data_quality={"status": "OK" if su.get("status") == "READY" else str(su.get("status")), "data_as_of": None, "reasons": []},
        execution_context={"spread": (su.get("costs") or {}).get("spread"), "cost_price": (su.get("costs") or {}).get("round_trip_price"),
                           "commission_known": (su.get("costs") or {}).get("commission_known"), "quote_age_s": None},
        score=(su.get("score") or {}).get("value"),
        engine_probability={"value": prob.get("value"), "status": prob.get("status"), "event": prob.get("event"),
                            "model_version": prob.get("model_version")} if prob else None,
        source_ref={"sh_signal_id": su.get("signal_id")})
