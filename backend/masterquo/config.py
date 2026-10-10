"""Application configuration (no secrets).

`config/masterquo.defaults.json` ships with the package; the user's editable copy lives in
`data/config.json`. Secrets (Anthropic key, Telegram token) are stored separately (secrets.py).

Rules enforced here:
* the exact broker symbol is kept verbatim (e.g. ``XAUUSD-``); it is never normalised;
* risk limits default to ``None`` = "not configured" -> execution is blocked until set;
* the 40% spread setting has no established denominator in the sources -> it is
  exposed as ``REQUIRES_DEFINITION`` and never used as an execution filter;
* there is no READ_ONLY/research-only switch: the execution mode chosen by the user (SIGNALS/PAPER/AUTO_DEMO/
  AUTO_LIVE) is stored here and restored; default PAPER. Account type is always re-checked against the terminal.
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import paths

SYMBOL_RE = re.compile(r"^[A-Za-z0-9_.#\-+]{2,32}$")

OperatingMode = Literal["SIGNALS", "PAPER", "AUTO_DEMO", "AUTO_LIVE"]
StrategyMode = Literal["AUTO", "MVP", "SMC", "SCALPING"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class MT5Config(_Strict):
    symbol: str = "XAUUSD-"
    # Analytical alias used by the unchanged legacy engines (instrument_id). Not a broker symbol.
    analytical_alias: str = "XAUUSD"
    dxy_symbol: str | None = None
    terminal_path: str | None = None
    quote_poll_seconds: float = Field(0.5, ge=0.2, le=10)
    bars_poll_seconds: float = Field(2.0, ge=0.5, le=30)
    account_poll_seconds: float = Field(2.0, ge=0.5, le=60)
    history_poll_seconds: float = Field(30.0, ge=5, le=3600)
    heartbeat_seconds: float = Field(5.0, ge=1, le=60)
    reconnect_max_backoff_seconds: float = Field(60.0, ge=5, le=600)
    call_timeout_seconds: float = Field(15.0, ge=2, le=120)
    max_quote_age_seconds: float = Field(10.0, ge=1, le=120)
    # Bars shown on the charts; analysis buffers are derived from indicator requirements.
    chart_bars: int = Field(500, ge=100, le=2000)
    deals_history_days: int = Field(30, ge=1, le=365)
    magic_number: int = Field(4108_2026, ge=1, le=2_000_000_000)

    @field_validator("symbol")
    @classmethod
    def _symbol(cls, v: str) -> str:
        if not SYMBOL_RE.fullmatch(v):
            raise ValueError("INVALID_BROKER_SYMBOL")
        return v

    @field_validator("dxy_symbol")
    @classmethod
    def _dxy(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        if not SYMBOL_RE.fullmatch(v):
            raise ValueError("INVALID_DXY_SYMBOL")
        return v


class ClockConfig(_Strict):
    # Offsets of broker server time are measured from fresh ticks and must be a multiple of
    # this granularity (time zones are 15-minute aligned). Tolerance absorbs latency.
    offset_granularity_seconds: int = 900
    offset_tolerance_seconds: float = 90.0
    min_samples: int = 5
    # Optional independent reference for the PC clock (HTTP Date header). Empty disables.
    reference_url: str | None = "https://api.anthropic.com"
    max_pc_clock_skew_seconds: float = 30.0


class StrategyConfig(_Strict):
    mode: StrategyMode = "AUTO"
    # Provisional lifecycle TTL in setup-timeframe closed bars (EARLY..TRIGGERED).
    setup_ttl_bars: int = Field(24, ge=3, le=500)
    # D1 is context only; when True a D1 trend opposing the H4/H1 structure blocks entries.
    d1_conflict_blocks_entry: bool = False
    # How the H4/H1 structural direction is resolved before M07 looks for setups.
    #   STRICT_H4_H1        original M02 rule: H4 and H1 must agree (fewest setups)
    #   H1_H4_NOT_OPPOSING  H1 decides when H4 is neutral/unknown; opposite H4 -> no direction
    #   H1_LEAD             H1 decides; an opposite H4 is reported as STRUCTURE_COUNTER_H4 (most setups)
    structure_policy: Literal["STRICT_H4_H1", "H1_H4_NOT_OPPOSING", "H1_LEAD"] = "H1_LEAD"
    # Closed setup-TF bars a CONFIRMED setup stays executable before MISSED_ENTRY.
    confirmed_window_bars: int = Field(3, ge=1, le=20)
    # DXY is optional. No built-in strategy requires it; listed strategies would block without it.
    strategies_requiring_dxy: list[str] = Field(default_factory=list)
    # Target rule (MasterQUO AI extension, provisional - see docs).
    tp1_weight: float = Field(0.5, gt=0, lt=1)
    min_target_distance_atr: float = Field(0.5, ge=0, le=20)
    move_sl_to_breakeven_after_tp1: bool = True


class RiskLimits(_Strict):
    """All None = not configured. Execution modes require them (see risk/limits.py)."""
    risk_per_trade_pct: float | None = Field(None, gt=0, le=10)
    max_total_open_risk_pct: float | None = Field(None, gt=0, le=50)
    daily_loss_limit_pct: float | None = Field(None, gt=0, le=50)
    max_drawdown_pct: float | None = Field(None, gt=0, le=90)
    max_open_positions: int | None = Field(None, ge=1, le=50)
    cooldown_minutes_after_loss: int | None = Field(None, ge=0, le=1440)
    min_free_margin_buffer_pct: float | None = Field(None, ge=0, le=95)
    # RR policy inherited from M11 v4.1 (<1.5 BLOCKED, 1.5..2.0 CONDITIONAL, >=2 PASS).
    rr_block_below: float = Field(1.0, ge=0.3, le=10)
    rr_pass_from: float = Field(1.5, ge=0.3, le=20)
    # RR between the two thresholds: execute with risk scaled by conditional_risk_factor
    # (False = original M11 behaviour: CONDITIONAL never executes).
    conditional_rr_executes: bool = True
    conditional_risk_factor: float = Field(0.5, gt=0, le=1)
    # Day boundary for the daily loss limit: broker server midnight (documented in docs).
    daily_reset: Literal["BROKER_SERVER_MIDNIGHT", "UTC_MIDNIGHT"] = "BROKER_SERVER_MIDNIGHT"
    max_spread_points: float | None = Field(None, gt=0)
    macro_block_high_impact: bool = True  # blocks only inside a known high-impact event window
    macro_calendar_required: bool = False  # True: a missing/unavailable calendar blocks entries


class CostConfig(_Strict):
    # "Zero" is the declared account profile, not a proof of zero costs.
    account_profile: str = "ZERO_DECLARED_COSTS_UNVERIFIED"
    commission_mode: Literal["UNKNOWN", "CONFIGURED", "FROM_DEAL_HISTORY"] = "FROM_DEAL_HISTORY"
    commission_per_lot_per_side: float | None = Field(None, ge=0)
    slippage_stress_points: float | None = Field(20.0, ge=0)
    # Found in sources (M01 v4.2.1 §12): "spread do 40%" with no denominator. Not used.
    spread_40pct_rule: Literal["REQUIRES_DEFINITION"] = "REQUIRES_DEFINITION"


class AgentConfig(_Strict):
    enabled: bool = True
    model: str | None = None  # resolved from ANTHROPIC_MODEL or the first-run wizard
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    max_tokens: int = Field(8000, ge=1024, le=64000)
    max_tool_calls: int = Field(8, ge=1, le=30)
    request_timeout_seconds: float = Field(90.0, ge=10, le=600)
    min_interval_seconds: float = Field(120.0, ge=10, le=86400)
    daily_budget_usd: float = Field(3.0, ge=0.05, le=500)
    required_for_entry: bool = True  # False = ADVISORY regardless of gate_policy
    # REQUIRED: only a fresh agreeing assessment passes (no key/error/timeout blocks).
    # VETO:     Claude blocks only by explicitly disagreeing; no key, errors or no answer within
    #           ai_wait_seconds do not block.
    # ADVISORY: Claude never blocks; assessments are informational.
    gate_policy: Literal["REQUIRED", "VETO", "ADVISORY"] = "VETO"
    ai_wait_seconds: float = Field(60.0, ge=0, le=900)
    decision_ttl_seconds: int = Field(900, ge=60, le=86400)
    use_refusal_fallback: bool = True
    # Price table for *estimates* only (USD per 1M tokens), cached 2026-10-06.
    price_per_mtok: dict[str, tuple[float, float]] = Field(default_factory=lambda: {
        "claude-fable-5-1": (10.0, 50.0), "claude-opus-5-5": (4.0, 20.0), "claude-opus-5": (5.0, 25.0),
        "claude-sonnet-5-5": (2.0, 10.0), "claude-sonnet-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50),
    })


class NewsConfig(_Strict):
    enabled: bool = True
    poll_seconds: int = Field(300, ge=60, le=86400)


class TelegramConfig(_Strict):
    enabled: bool = False
    chat_id: str | None = None
    send_signals: bool = False


class ServerConfig(_Strict):
    host: Literal["127.0.0.1"] = "127.0.0.1"  # loopback only, by design
    port: int = Field(8765, ge=1024, le=65535)
    open_browser: bool = True


class ExecutionConfig(_Strict):
    # SIGNALS = "Analiza warunków" (no orders), PAPER = automatic simulation, AUTO_DEMO / AUTO_LIVE = automatic orders.
    mode: OperatingMode = "PAPER"
    bound_account: str | None = None      # account key confirmed for AUTO_DEMO / AUTO_LIVE (server:login)
    allow_live_execution: bool = False    # legacy 1.x field, no longer required (kept for config compatibility)
    deviation_points: int = Field(20, ge=0, le=1000)
    order_timeout_seconds: float = Field(10.0, ge=2, le=60)
    paper_starting_balance: float = Field(10000.0, gt=0)


class MLPromotion(_Strict):
    """Champion/challenger rules, fixed BEFORE an evaluation (stored with every evaluation)."""
    min_test_samples: int = Field(150, ge=20)
    min_test_per_class: int = Field(30, ge=5)
    max_brier_vs_baseline: float = Field(0.0, description="challenger Brier minus base-rate Brier must be <= this (negative = better)")
    min_net_r_vs_no_ml: float = Field(0.0, description="net R per trade of the ML policy minus all-trades policy on the test block")
    max_drawdown_increase_r: float = Field(2.0, ge=0)
    max_calibration_error: float = Field(0.10, ge=0, le=1)
    must_beat_champion_brier: bool = True


class MLConfig(_Strict):
    """Decision Tree + XGBoost pipeline (MQ-ML-1.0.0). Start values are working parameters, not guarantees."""
    mode: Literal["OFF", "SHADOW", "ASSIST"] = "SHADOW"
    collect: bool = True                          # build samples/labels from live setups
    training_paused: bool = False
    check_interval_seconds: int = Field(60, ge=10, le=3600)
    min_labeled_setups: int = Field(1000, ge=50)
    min_per_class: int = Field(100, ge=10)
    retrain_after_new_labels: int = Field(250, ge=10)
    min_hours_between_trainings: float = Field(6.0, ge=0)
    min_block_samples: int = Field(60, ge=10)     # per validation block (fit / tune / calibrate / test)
    min_block_per_class: int = Field(10, ge=2)
    embargo_minutes: int = Field(120, ge=0)
    use_backfill_approx: bool = False             # include OHLC-approximate backfill labels in training (off by default)
    dt_tuning_budget: int = Field(24, ge=4, le=200)
    xgb_tuning_budget: int = Field(8, ge=1, le=50)
    xgb_max_trees: int = Field(400, ge=20, le=5000)
    xgb_threads: int = Field(2, ge=1, le=32)
    xgb_device: Literal["cpu", "cuda"] = "cpu"
    train_timeout_minutes: int = Field(30, ge=1, le=600)
    random_state: int = 42
    assist_rank_weight: float = Field(10.0, ge=0, le=50)   # ASSIST: rank += weight x (calibrated p - base rate) x 10
    drift_psi_warn: float = Field(0.2, gt=0)
    drift_psi_degraded: float = Field(0.35, gt=0)
    degrade_brier_increase: float = Field(0.05, ge=0)      # mature-label Brier above validation Brier by more -> DEGRADED
    promotion: MLPromotion = Field(default_factory=MLPromotion)


class StrategyToggle(_Strict):
    scan: bool = True    # detect and show setups of this strategy
    trade: bool = True   # may the selected setup of this strategy be executed (all other gates still apply)


class ActiveThresholds(_Strict):
    # ACTIVE score 0-100 (heuristic, not a probability). CONFIRMED additionally needs the strategy's real trigger.
    watch: float = Field(40, ge=0, le=100)
    early: float = Field(55, ge=0, le=100)
    confirmed: float = Field(70, ge=0, le=100)


def _default_toggles() -> dict[str, StrategyToggle]:
    return {f"S{i:02d}": StrategyToggle() for i in range(1, 11)}


class ActiveConfig(_Strict):
    """Profile ACTIVE (S01-S10 scanner + AUTO strategy selection). ORIGINAL = legacy M07 path only."""
    profile: Literal["ACTIVE", "ORIGINAL"] = "ACTIVE"
    strategy_mode: Literal["AUTO", "MANUAL"] = "AUTO"       # AUTO = strategy selection only, never order execution
    manual_strategy_id: str | None = None
    thresholds: ActiveThresholds = Field(default_factory=ActiveThresholds)
    scan_min_interval_seconds: float = Field(2.0, ge=0.5, le=60)
    min_switch_margin: float = Field(8.0, ge=0, le=50)
    switch_confirm_updates: int = Field(2, ge=1, le=20)
    min_selection_hold_seconds: float = Field(60.0, ge=0, le=3600)
    conflict_margin: float = Field(5.0, ge=0, le=50)
    downgrade_confirm_updates: int = Field(2, ge=1, le=20)
    cancel_after_misses: int = Field(3, ge=1, le=50)
    confirmed_window_bars: int = Field(3, ge=1, le=20)
    strategies: dict[str, StrategyToggle] = Field(default_factory=_default_toggles)
    params: dict[str, dict] = Field(default_factory=dict)      # per-strategy parameter overrides (validated keys only)
    regime: dict = Field(default_factory=dict)                 # MarketRegimeEngine overrides

    @field_validator("manual_strategy_id")
    @classmethod
    def _manual(cls, v: str | None) -> str | None:
        if v in (None, ""):
            return None
        if not re.fullmatch(r"S(0[1-9]|10)", v):
            raise ValueError("UNKNOWN_STRATEGY_ID")
        return v


class VolatilityConfig(_Strict):
    """Daily volatility levels: HV, 1-day contract pricing and IV walls (engine/volzones.py)."""
    enabled: bool = True
    estimator: Literal["close_to_close", "parkinson"] = "close_to_close"
    window: int = Field(20, ge=5, le=250)                       # closed D1 bars used for HV
    trading_days_per_year: int = Field(252, ge=200, le=366)
    iv_source: Literal["HV", "MANUAL"] = "HV"                    # MT5 has no option chain -> HV is the IV proxy
    manual_iv_pct: float | None = Field(None, gt=0, le=300)       # annualised %, used when iv_source=MANUAL
    walls_sigma: list[float] = Field(default_factory=lambda: [1.0, 2.0])
    wall_band_sigma: float = Field(0.1, ge=0.0, le=0.5)

    @field_validator("walls_sigma")
    @classmethod
    def _walls(cls, v: list[float]) -> list[float]:
        if not 1 <= len(v) <= 4 or any(not 0.25 <= x <= 4.0 for x in v):
            raise ValueError("WALLS_SIGMA_1_TO_4_VALUES_0.25_TO_4")
        return sorted(set(round(x, 3) for x in v))


class MarketsConfig(_Strict):
    """Multi-market scanner (markets/scanner.py): analysis of other symbols of the connected terminal (read-only)."""
    enabled: bool = True
    source: Literal["MARKET_WATCH", "LIST", "ALL"] = "MARKET_WATCH"   # ALL adds symbols to Market Watch (symbol_select)
    symbols: list[str] = Field(default_factory=list)                 # used by LIST (exact broker names)
    exclude: list[str] = Field(default_factory=list)
    include_main: bool = True
    max_symbols: int = Field(30, ge=1, le=200)
    scan_interval_seconds: int = Field(300, ge=60, le=3600)

    @field_validator("symbols", "exclude")
    @classmethod
    def _names(cls, v: list[str]) -> list[str]:
        out = []
        for x in v:
            x = str(x).strip()
            if not x or len(x) > 40 or any(ch in x for ch in "*?,!"):
                raise ValueError("SYMBOL_NAMES_MUST_BE_EXACT_BROKER_NAMES")
            if x not in out:
                out.append(x)
        return out[:200]


class AISignalsConfig(_Strict):
    """AI signals (agent/signals.py): Claude proposes BUY/SELL/NO_TRADE with levels; validated and tracked, never executed."""
    enabled: bool = True
    auto_top_n: int = Field(0, ge=0, le=10)                 # 0 = only on request; >0 = best-ranked scanner symbols
    auto_interval_minutes: int = Field(120, ge=15, le=1440)
    default_valid_minutes: int = Field(240, ge=15, le=2880)
    min_rr: float = Field(1.0, ge=0.3, le=10.0)
    min_sl_atr_h1: float = Field(0.3, ge=0.05, le=5.0)
    max_sl_atr_d1: float = Field(3.0, ge=0.2, le=20.0)
    max_entry_distance_atr_h1: float = Field(4.0, ge=0.1, le=50.0)
    max_hold_hours: int = Field(72, ge=1, le=720)


class AppConfig(_Strict):
    config_version: int = 5
    mt5: MT5Config = Field(default_factory=MT5Config)
    clock: ClockConfig = Field(default_factory=ClockConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    risk: RiskLimits = Field(default_factory=RiskLimits)
    costs: CostConfig = Field(default_factory=CostConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    news: NewsConfig = Field(default_factory=NewsConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    active: ActiveConfig = Field(default_factory=ActiveConfig)
    ml: MLConfig = Field(default_factory=MLConfig)
    volatility: VolatilityConfig = Field(default_factory=VolatilityConfig)
    markets: MarketsConfig = Field(default_factory=MarketsConfig)
    ai_signals: AISignalsConfig = Field(default_factory=AISignalsConfig)
    first_run_completed: bool = False
    synthetic_demo: bool = False  # set only by the --demo launcher; never by the UI


class ConfigStore:
    """Thread-safe holder with atomic persistence to data/config.json."""

    def __init__(self, path: Path | None = None):
        self.path = path or (paths.data_dir() / "config.json")
        self._lock = threading.RLock()
        self._cfg = self._load()

    def _load(self) -> AppConfig:
        if self.path.exists():
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            migrated = migrate(raw)
            cfg = AppConfig.model_validate(raw)
            if migrated:
                self._write(cfg)
            return cfg
        if paths.DEFAULTS_FILE.exists():
            cfg = AppConfig.model_validate(json.loads(paths.DEFAULTS_FILE.read_text(encoding="utf-8")))
        else:
            cfg = AppConfig()
        self._write(cfg)
        return cfg

    def _write(self, cfg: AppConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cfg.model_dump(mode="json"), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def get(self) -> AppConfig:
        with self._lock:
            return self._cfg.model_copy(deep=True)

    def update(self, patch: dict) -> AppConfig:
        """Deep-merge a partial dict, validate the whole result, persist atomically."""
        with self._lock:
            merged = _deep_merge(self._cfg.model_dump(mode="json"), patch)
            merged.pop("synthetic_demo", None)
            merged["synthetic_demo"] = self._cfg.synthetic_demo
            cfg = AppConfig.model_validate(merged)
            self._write(cfg)
            self._cfg = cfg
            return cfg.model_copy(deep=True)

    def set_runtime_flag(self, **flags) -> None:
        with self._lock:
            self._cfg = self._cfg.model_copy(update=flags)


# v1 -> v2: less restrictive defaults. A value is replaced only when it still equals the old
# default, so settings the user chose deliberately are kept.
_V2_CHANGES = [
    (("risk", "rr_block_below"), 1.5, 1.0),
    (("risk", "rr_pass_from"), 2.0, 1.5),
    (("costs", "slippage_stress_points"), None, 20.0),
]


def migrate(raw: dict) -> bool:
    """In-place upgrade of a stored config dict. Returns True when something changed."""
    v = int(raw.get("config_version", 1))
    if v >= 5:
        return False
    if v >= 3:
        _to_v5(raw)
        return True
    if v == 2:
        _to_v3(raw)
        _to_v5(raw)
        return True
    for (sec, key), old, new in _V2_CHANGES:
        part = raw.get(sec)
        if isinstance(part, dict) and part.get(key, old) == old:
            part[key] = new
    agent = raw.get("agent")
    if isinstance(agent, dict) and "gate_policy" not in agent:
        agent["gate_policy"] = "ADVISORY" if agent.get("required_for_entry") is False else "VETO"
    _to_v3(raw)
    _to_v5(raw)
    return True


def _to_v5(raw: dict) -> None:
    """v3/v4 -> v5 (1.3.1): volatility section (defaults). Sections written by the withdrawn 1.4 licensing build
    (config_version 4: central, connector) are dropped so its config files keep loading."""
    raw.pop("central", None)
    raw.pop("connector", None)
    raw["config_version"] = 5


def _to_v3(raw: dict) -> None:
    """v2 -> v3 (1.3): READ_ONLY removed. The mode was never stored before, so the default PAPER applies;
    a stored legacy mode name (if any) is translated."""
    ex = raw.setdefault("execution", {})
    legacy = {"READ_ONLY": "SIGNALS", "DEMO_EXECUTION": "AUTO_DEMO", "LIVE_EXECUTION": "AUTO_LIVE"}
    if ex.get("mode") in legacy:
        ex["mode"] = legacy[ex["mode"]]
    raw["config_version"] = 3


def _deep_merge(base: dict, patch: dict) -> dict:
    out = dict(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict) and k != "price_per_mtok":
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out
