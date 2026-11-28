"""Pydantic request bodies of the bot API /api/v1 (Etap 4 krok B: moved unchanged from api/app.py, which re-exports every name -
alias zgodności; the route modules api/routes/*.py import them from here)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class AssetConfirmReq(BaseModel):
    asset: str
    broker_symbol: str


class AssetActiveReq(BaseModel):
    asset: str


class DesktopPrefsReq(BaseModel):
    close_action: str
    autostart: bool = False
    start_minimized: bool = False


class ModeReq(BaseModel):
    mode: str
    confirm: str = ""


class PrimaryPathReq(BaseModel):
    instrument: str
    path: str


class MarketZonesReq(BaseModel):
    instrument: str = Field(max_length=16)
    timeframes: list[str] | None = Field(default=None, max_length=4)


class MarketZonesLiveReq(MarketZonesReq):
    enabled: bool


class TrainJobReq(BaseModel):
    kind: str = Field(max_length=16)
    instrument: str = Field(max_length=16)
    params: dict = Field(default_factory=dict)


class TrainVersionReq(BaseModel):
    instrument: str = Field(max_length=16)
    model_key: str = Field(max_length=64)
    version: str | None = Field(default=None, max_length=64)


class OnReq(BaseModel):
    on: bool
    reason: str = "user"


class ExecReq(BaseModel):
    decision_id: str


class CloseReq(BaseModel):
    scope: str = "BOT"
    ticket: int | None = None
    confirm: str


class AskReq(BaseModel):
    question: str = Field(min_length=2, max_length=2000)


class KeyReq(BaseModel):
    api_key: str = Field(min_length=10, max_length=300)


class SecretReq(BaseModel):
    name: str
    value: str | None = None


class MLModeReq(BaseModel):
    mode: str = Field(pattern="^(OFF|SHADOW|ASSIST)$")


class MLTrainReq(BaseModel):
    include_approx: bool | None = None          # per job only (training installer); config ml.use_backfill_approx stays untouched


class MLBackfillReq(BaseModel):
    days: int = Field(30, ge=5, le=180)


class MLFlagReq(BaseModel):
    on: bool


class StrategyModeReq(BaseModel):
    strategy_mode: str = Field(pattern="^(AUTO|MANUAL)$")
    manual_strategy_id: str | None = Field(default=None, max_length=4)


class TelegramTemplateReq(BaseModel):
    template: str | None = Field(default=None, max_length=1500)


class PresetReq(BaseModel):
    name: str = Field(min_length=1, max_length=40)


class StrategyToggleReq(BaseModel):
    strategy_id: str = Field(pattern="^S[0-9]{2}$")          # checked against the registry in the endpoint (S11, S12 included)
    scan: bool | None = None
    trade: bool | None = None


class ProfileReq(BaseModel):
    profile: str = Field(pattern="^(ACTIVE|ORIGINAL)$")


class SetupViewReq(BaseModel):
    mode: str = Field(pattern="^(AUTO|SELECTED|ALL)$")
    strategy_id: str | None = Field(default=None, max_length=4)
    focus_setup_id: str | None = Field(default=None, max_length=120)


class LeverageReq(BaseModel):
    mode: str = Field(pattern="^(AUTO|MANUAL)$")
    limit: int | None = Field(default=None, ge=1, le=1000)


class MemoryReq(BaseModel):
    status: str
