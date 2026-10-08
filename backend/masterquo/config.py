"""Application configuration (no secrets).

`config/masterquo.defaults.json` ships with the package; the user's editable copy lives in
`data/config.json`. Secrets (Anthropic key, Telegram token) are stored separately (secrets.py).

Rules enforced here:
* the exact broker symbol is kept verbatim (e.g. ``XAUUSD-``); it is never normalised;
* risk limits default to ``None`` = "not configured" -> execution is blocked until set;
* the 40% spread setting has no established denominator in the sources -> it is
  exposed as ``REQUIRES_DEFINITION`` and never used as an execution filter;
* the operating mode is *never* restored from disk: every start is READ_ONLY, AUTO OFF.
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

OperatingMode = Literal["READ_ONLY", "PAPER", "DEMO_EXECUTION", "LIVE_EXECUTION"]
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
    rr_block_below: float = Field(1.5, ge=0.5, le=10)
    rr_pass_from: float = Field(2.0, ge=0.5, le=20)
    # Day boundary for the daily loss limit: broker server midnight (documented in docs).
    daily_reset: Literal["BROKER_SERVER_MIDNIGHT", "UTC_MIDNIGHT"] = "BROKER_SERVER_MIDNIGHT"
    max_spread_points: float | None = Field(None, gt=0)
    macro_block_high_impact: bool = True


class CostConfig(_Strict):
    # "Zero" is the declared account profile, not a proof of zero costs.
    account_profile: str = "ZERO_DECLARED_COSTS_UNVERIFIED"
    commission_mode: Literal["UNKNOWN", "CONFIGURED", "FROM_DEAL_HISTORY"] = "FROM_DEAL_HISTORY"
    commission_per_lot_per_side: float | None = Field(None, ge=0)
    slippage_stress_points: float | None = Field(None, ge=0)
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
    required_for_entry: bool = True
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
    # LIVE execution additionally requires this explicit local opt-in (see execution/modes.py).
    allow_live_execution: bool = False
    deviation_points: int = Field(20, ge=0, le=1000)
    order_timeout_seconds: float = Field(10.0, ge=2, le=60)
    paper_starting_balance: float = Field(10000.0, gt=0)


class AppConfig(_Strict):
    config_version: int = 1
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
            return AppConfig.model_validate(raw)
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


def _deep_merge(base: dict, patch: dict) -> dict:
    out = dict(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict) and k != "price_per_mtok":
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out
