"""Chronos-2 / FinCast settings - data/tsfm/settings.json, validated (unknown keys rejected), defaults = observation only.

Own file (like Kronos): an older release that does not know these models opens config.json unchanged. Per model:
  enabled, instruments, timeframes (start: M5 + M15), context_len, input profile, device, threads, timeouts;
  use per decision path: ACTIVE (S01-S12 engine), SCALPING, HEDGING -> OBSERVE (default) | ASSIST | REQUIRED, with the timeframe the
  role reads and the approval (validation report id). ASSIST / REQUIRED can only be set by TsfmService.set_use (positive walk-forward
  report on REAL data for the CURRENT binding + explicit confirmation).
Common: horizon per timeframe (the same defaults as Kronos so the three models answer the SAME task: same target bars and horizon),
quantile levels, neutral band rule, data freshness, queue size, weights folder.
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
PATHS = ("ACTIVE", "SCALPING", "HEDGING")
MODEL_IDS = ("chronos2", "fincast")
HORIZON_DEFAULT = {"M1": 15, "M3": 10, "M5": 12, "M15": 8, "M30": 8, "H1": 6}      # = Kronos defaults (starting values, not proven optimal)


class PathUse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    use: Literal["OBSERVE", "ASSIST", "REQUIRED"] = "OBSERVE"
    timeframe: TF = "M5"
    validation_report: str | None = None
    confirmed_at: str | None = None


def _uses() -> dict:
    return {"ACTIVE": PathUse(timeframe="M15"), "SCALPING": PathUse(timeframe="M5"), "HEDGING": PathUse(timeframe="M15")}


class ModelCfg(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    enabled: bool = True                                   # no effect until installed (status NOT_INSTALLED / NO_WEIGHTS)
    instruments: list[Literal["XAUUSD", "BTC"]] = Field(default_factory=lambda: ["XAUUSD"])
    timeframes: list[TF] = Field(default_factory=lambda: ["M5", "M15"])
    context_len: int = Field(512, ge=64, le=2048)
    profile: Literal["CLOSE_V1", "CLOSE_OHLCV_PAST_V1"] = "CLOSE_V1"
    device: Literal["AUTO", "CPU", "CUDA"] = "AUTO"
    cpu_threads: int | None = Field(None, ge=1, le=64)
    request_timeout_s: float = Field(120.0, ge=5.0, le=900.0)
    load_timeout_s: float = Field(900.0, ge=30.0, le=3600.0)
    use: dict[str, PathUse] = Field(default_factory=_uses)
    python_path: str | None = None

    @field_validator("use")
    @classmethod
    def _use(cls, v: dict) -> dict:
        bad = [k for k in v if k not in PATHS]
        if bad:
            raise ValueError("PATH_UNKNOWN:" + ",".join(bad))
        d = _uses()
        for k in PATHS:
            v.setdefault(k, d[k])
        return v

    @field_validator("timeframes", "instruments")
    @classmethod
    def _uniq(cls, v: list) -> list:
        return list(dict.fromkeys(v))


def _models() -> dict:
    return {"chronos2": ModelCfg(), "fincast": ModelCfg()}


class TsfmSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    models: dict[str, ModelCfg] = Field(default_factory=_models)
    horizon_bars: dict[str, int] = Field(default_factory=lambda: dict(HORIZON_DEFAULT))
    quantiles: list[float] = Field(default_factory=lambda: [0.1, 0.5, 0.9])
    lookback: int = Field(560, ge=96, le=2200)
    min_context: int = Field(128, ge=32, le=2048)
    direction_band_atr: float = Field(0.25, ge=0.0, le=5.0)
    direction_band_min_points: float = Field(0.0, ge=0.0, le=100000.0)
    max_staleness_bars: float = Field(2.0, ge=1.0, le=20.0)
    queue_max: int = Field(16, ge=1, le=64)
    weights_root: str | None = None

    @field_validator("models")
    @classmethod
    def _m(cls, v: dict) -> dict:
        bad = [k for k in v if k not in MODEL_IDS]
        if bad:
            raise ValueError("MODEL_UNKNOWN:" + ",".join(bad))
        for k in MODEL_IDS:
            v.setdefault(k, ModelCfg())
        return v

    @field_validator("horizon_bars")
    @classmethod
    def _hz(cls, v: dict) -> dict:
        bad = [k for k in v if k not in TF_ALL]
        if bad:
            raise ValueError("HORIZON_UNKNOWN_TF:" + ",".join(bad))
        for k, n in v.items():
            if not 1 <= int(n) <= 128:
                raise ValueError(f"HORIZON_OUT_OF_RANGE:{k}={n} (1..128)")
        for k in TF_ALL:
            v.setdefault(k, HORIZON_DEFAULT[k])
        return {k: int(n) for k, n in v.items()}

    @field_validator("quantiles")
    @classmethod
    def _q(cls, v: list) -> list:
        v = sorted({float(x) for x in v} | {0.5})
        allowed = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)                 # common to both models (FinCast: only these)
        bad = [x for x in v if x not in allowed]
        if bad:
            raise ValueError(f"QUANTILE_UNSUPPORTED:{bad} (wspólne poziomy obu modeli: 0,1–0,9)")
        return v


def tsfm_dir() -> Path:
    p = paths.data_dir() / "tsfm"
    p.mkdir(parents=True, exist_ok=True)
    return p


def default_weights_root() -> Path:
    return tsfm_dir() / "models"


def python_candidates(mid: str, c: ModelCfg) -> list[str]:
    root = paths.ROOT_DIR
    venv = {"chronos2": ".venv_chronos2", "fincast": ".venv_fincast"}[mid]
    return [x for x in (os.environ.get(f"MQ_{mid.upper()}_PYTHON"), c.python_path, str(root / venv / "Scripts" / "python.exe"),
                        str(root / venv / "bin" / "python")) if x]


def find_python(mid: str, c: ModelCfg) -> str | None:
    return next((x for x in python_candidates(mid, c) if Path(x).is_file()), None)


class SettingsStore:
    def __init__(self, path: Path | None = None):
        self.path = path or (tsfm_dir() / "settings.json")
        self._lock = threading.Lock()
        self.load_error: str | None = None
        self._s = self._load()

    def _load(self) -> TsfmSettings:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return TsfmSettings()
        except (OSError, ValueError) as exc:
            self.load_error = f"settings.json nieczytelny ({type(exc).__name__}) – użyto ustawień domyślnych (obserwacja)"
            return TsfmSettings()
        try:
            return TsfmSettings.model_validate(raw)
        except Exception as exc:  # noqa: BLE001 - a broken file never enables anything: defaults = observation only
            self.load_error = f"settings.json niepoprawny ({str(exc)[:200]}) – użyto ustawień domyślnych (obserwacja)"
            return TsfmSettings()

    def get(self) -> TsfmSettings:
        with self._lock:
            return self._s.model_copy(deep=True)

    def update(self, patch: dict) -> TsfmSettings:
        with self._lock:
            merged = _merge(self._s.model_dump(mode="json"), patch)
            s = TsfmSettings.model_validate(merged)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(s.model_dump(mode="json"), indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
            self._s = s
            self.load_error = None
            return s.model_copy(deep=True)


def _merge(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in b.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out
