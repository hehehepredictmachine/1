"""Kronos settings - data/kronos/settings.json, validated (unknown keys rejected), defaults = observation only.

Kept in its own file (not in the strict AppConfig): an older release that does not know Kronos still opens config.json unchanged.
The decision role per strategy (strategy_use) is OBSERVE by default; REQUIRED can only be set through KronosService.set_strategy_use,
which demands a positive walk-forward report on real (non-synthetic) data and an explicit confirmation.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .. import paths

TF = Literal["M1", "M3", "M5", "M15", "M30", "H1"]
TF_ALL = ("M1", "M3", "M5", "M15", "M30", "H1")
STRATEGIES = ("SCALPING", "HEDGING")


class StrategyUse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    use: Literal["OBSERVE", "REQUIRED"] = "OBSERVE"
    timeframe: TF = "M5"
    validation_report: str | None = None          # report id that justified REQUIRED
    confirmed_at: str | None = None


def _default_use() -> dict:
    return {"SCALPING": StrategyUse(timeframe="M5"), "HEDGING": StrategyUse(timeframe="M15")}


class KronosSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    enabled: bool = True                                   # no effect until the model is installed (status NOT_INSTALLED)
    instruments: list[Literal["XAUUSD", "BTC"]] = Field(default_factory=lambda: ["XAUUSD", "BTC"])
    timeframes: list[TF] = Field(default_factory=lambda: ["M5", "M15"])
    horizon_bars: dict[str, int] = Field(default_factory=lambda: {"M1": 15, "M3": 10, "M5": 12, "M15": 8, "M30": 8, "H1": 6})
    lookback: int = Field(400, ge=64, le=512)
    max_context: int = Field(512, ge=64, le=512)
    min_context: int = Field(128, ge=32, le=512)
    temperature: float = Field(1.0, gt=0.0, le=2.0)
    top_k: int = Field(0, ge=0, le=1024)
    top_p: float = Field(0.9, gt=0.0, le=1.0)
    paths: int = Field(0, ge=0, le=32)                     # 0 = no uncertainty band; >=2 = N independent paths (cost x N)
    direction_band_atr: float = Field(0.25, ge=0.0, le=5.0)
    direction_band_min_points: float = Field(0.0, ge=0.0, le=100000.0)
    volume_source: Literal["AUTO", "TICK_VOLUME", "NONE"] = "AUTO"
    timestamp_basis: Literal["SERVER", "UTC"] = "SERVER"
    device: Literal["AUTO", "CPU", "CUDA"] = "AUTO"
    cpu_threads: int | None = Field(None, ge=1, le=64)
    request_timeout_s: float = Field(120.0, ge=5.0, le=900.0)
    load_timeout_s: float = Field(300.0, ge=10.0, le=1800.0)
    queue_max: int = Field(8, ge=1, le=64)
    max_staleness_bars: float = Field(2.0, ge=1.0, le=20.0)
    weights_dir: str | None = None
    python_path: str | None = None
    strategy_use: dict[str, StrategyUse] = Field(default_factory=_default_use)

    @field_validator("horizon_bars")
    @classmethod
    def _hz(cls, v: dict) -> dict:
        bad = [k for k in v if k not in TF_ALL]
        if bad:
            raise ValueError("HORIZON_UNKNOWN_TF:" + ",".join(bad))
        for k, n in v.items():
            if not 1 <= int(n) <= 64:
                raise ValueError(f"HORIZON_OUT_OF_RANGE:{k}={n} (1..64)")
        for k in TF_ALL:
            v.setdefault(k, {"M1": 15, "M3": 10, "M5": 12, "M15": 8, "M30": 8, "H1": 6}[k])
        return {k: int(n) for k, n in v.items()}

    @field_validator("strategy_use")
    @classmethod
    def _su(cls, v: dict) -> dict:
        bad = [k for k in v if k not in STRATEGIES]
        if bad:
            raise ValueError("STRATEGY_UNKNOWN:" + ",".join(bad))
        d = _default_use()
        for k in STRATEGIES:
            v.setdefault(k, d[k])
        return v

    @field_validator("paths")
    @classmethod
    def _paths(cls, v: int) -> int:
        if v == 1:
            raise ValueError("PATHS_1: użyj 0 (bez pasma) albo >= 2 niezależnych ścieżek")
        return v

    @field_validator("timeframes", "instruments")
    @classmethod
    def _uniq(cls, v: list) -> list:
        return list(dict.fromkeys(v))


def kronos_dir() -> Path:
    p = paths.data_dir() / "kronos"
    p.mkdir(parents=True, exist_ok=True)
    return p


def default_weights_dir() -> Path:
    return kronos_dir() / "models"


def python_candidates(s: KronosSettings) -> list[str]:
    root = paths.ROOT_DIR
    return [c for c in (os.environ.get("MQ_KRONOS_PYTHON"), s.python_path, str(root / ".venv_kronos" / "Scripts" / "python.exe"),
                        str(root / ".venv_kronos" / "bin" / "python")) if c]


def find_python(s: KronosSettings) -> str | None:
    return next((c for c in python_candidates(s) if Path(c).is_file()), None)


class SettingsStore:
    def __init__(self, path: Path | None = None):
        self.path = path or (kronos_dir() / "settings.json")
        self._lock = threading.Lock()
        self.load_error: str | None = None
        self._s = self._load()

    def _load(self) -> KronosSettings:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return KronosSettings()
        except (OSError, ValueError) as exc:
            self.load_error = f"settings.json nieczytelny ({type(exc).__name__}) – użyto ustawień domyślnych"
            return KronosSettings()
        try:
            return KronosSettings.model_validate(raw)
        except Exception as exc:  # noqa: BLE001 - a broken file never enables anything: defaults = observation only
            self.load_error = f"settings.json niepoprawny ({str(exc)[:200]}) – użyto ustawień domyślnych"
            return KronosSettings()

    def get(self) -> KronosSettings:
        with self._lock:
            return self._s.model_copy(deep=True)

    def update(self, patch: dict) -> KronosSettings:
        with self._lock:
            merged = self._s.model_dump(mode="json")
            for k, v in patch.items():
                if isinstance(v, dict) and isinstance(merged.get(k), dict):
                    merged[k] = {**merged[k], **v}
                else:
                    merged[k] = v
            s = KronosSettings.model_validate(merged)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(s.model_dump(mode="json"), indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
            self._s = s
            self.load_error = None
            return s.model_copy(deep=True)
