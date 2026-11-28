"""Chronos-2 / Granite TTM settings - data/tsfm/settings.json, validated (unknown keys rejected), defaults = observation only.

1.40: FinCast is RETIRED (replaced by Granite TTM). A settings file of 1.37-1.39 with a "fincast" entry is migrated on load: the entry is
removed from the active models, the untouched original is kept as settings.v139.bak.json and the change is written to
settings_history.jsonl (every later change of the settings - model, checkpoint, role - is appended there too).

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
import threading
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .. import paths

TF = Literal["M1", "M3", "M5", "M15", "M30", "H1"]
TF_ALL = ("M1", "M3", "M5", "M15", "M30", "H1")
PATHS = ("ACTIVE", "SCALPING", "HEDGING")
MODEL_IDS = ("chronos2", "granite_ttm", "tirex2")                                 # 1.41 TiRex-2
DIRECT_POLICY_IDS = ("tirex2", "chronos2", "granite_ttm")                       # ASSIST without a validation report (DIRECT_USER_REQUEST: 1.41 TiRex-2, 1.42 all)
RETIRED_IDS = ("fincast",)                                                       # 1.40: history only, never scheduled
HORIZON_DEFAULT = {"M1": 15, "M3": 10, "M5": 12, "M15": 8, "M30": 8, "H1": 6}      # = Kronos defaults (starting values, not proven optimal)


class PathUse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    use: Literal["OBSERVE", "ASSIST", "REQUIRED"] = "OBSERVE"
    timeframe: TF = "M5"
    validation_report: str | None = None
    confirmed_at: str | None = None
    # 1.41: how ASSIST was granted - VALIDATION (walk-forward report, unchanged rule for Chronos-2 / Granite TTM) or DIRECT_USER_REQUEST
    # (TiRex-2 only: the user's explicit instruction of the 1.41 update; no report is invented, calibration stays UNCALIBRATED)
    activation_policy: Literal["VALIDATION", "DIRECT_USER_REQUEST"] = "VALIDATION"
    activated_at: str | None = None


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
    checkpoint: str = Field("BASE", pattern=r"^(BASE|GTR-[0-9A-Za-z_-]{6,64})$")   # Granite TTM: BASE = pinned pretrained, GTR-... = own fine-tune

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


def default_model(mid: str) -> "ModelCfg":
    """1.41 TiRex-2: enabled, CPU, M5 + M15 after every closed bar, context 512 (the bot's horizons). Its forecast is used ACTIVELY in
    the analysis (Quant features / TabICL input / decision trace) from the first result; the hold-roles of the entry paths stay OBSERVE
    so no existing gold strategy gets a new gate (the user can switch ASSIST on without a report - DIRECT_USER_REQUEST)."""
    if mid == "tirex2":
        return ModelCfg(device="CPU", cpu_threads=2, context_len=512)
    return ModelCfg()


def _models() -> dict:
    return {m: default_model(m) for m in MODEL_IDS}


class TsfmSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    models: dict[str, ModelCfg] = Field(default_factory=_models)
    retired: dict[str, dict] = Field(default_factory=dict)        # 1.40: last settings of retired models (FinCast) - information only
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
            v.setdefault(k, default_model(k))
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
        allowed = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)                 # Chronos-2 / TiRex-2 levels used by the bot (Granite TTM: point only)
        bad = [x for x in v if x not in allowed]
        if bad:
            raise ValueError(f"QUANTILE_UNSUPPORTED:{bad} (wspólne poziomy obu modeli: 0,1–0,9)")
        return v


def tsfm_dir() -> Path:
    p = paths.data_dir() / "tsfm"
    p.mkdir(parents=True, exist_ok=True)
    return p


def default_weights_root() -> Path:
    """THE weights folder of the bot (TabICL: quant/tabicl.weights_root and its installs from Bootstrap / upgrade / API; TSFM: fallback of
    TsfmService.weights_root): weights_root from <data>/tsfm/settings.json when set, else <data>/tsfm/models - the same rule as the
    installer (tools/tsfm_setup.default_weights_root, --weights-root auto). 1.46 arch (P004): it always returned <data>/tsfm/models, so with
    a user weights folder the .bat installer put TabICL where the bot never looked."""
    d = tsfm_dir()
    try:
        w = json.loads((d / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        w = None
    w = w.get("weights_root") if isinstance(w, dict) else None
    return Path(w) if isinstance(w, str) and w.strip() else d / "models"


def python_candidates(mid: str, c: ModelCfg) -> list[str]:
    # 1.46 arch (I0117): one lookup (MQ_<MID>_PYTHON, python_path, .venv_X) - same order as before
    from .. import runtimes
    return runtimes.python_candidates(mid, c.python_path)


def find_python(mid: str, c: ModelCfg) -> str | None:
    return next((x for x in python_candidates(mid, c) if Path(x).is_file()), None)


class SettingsStore:
    """tsfm/settings.json - policy OWNER_CACHED (masterquo/settings_store.py): read once, kept in memory by the running bot (rt.tsfm.settings);
    other code inside the bot uses that instance, other processes must not write the file while the bot runs."""

    policy = "OWNER_CACHED"          # = settings_store.OWNER_CACHED (1.46 arch I0097)

    def __init__(self, path: Path | None = None):
        self.path = path or (tsfm_dir() / "settings.json")
        self._lock = threading.Lock()
        self.load_error: str | None = None
        self._keep_original = False          # 1.46: the file on disk was not loaded (unreadable / invalid) - kept before the first write
        self._s = self._load()

    def _load(self) -> TsfmSettings:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return TsfmSettings()
        except (OSError, ValueError) as exc:
            self.load_error = f"settings.json nieczytelny ({type(exc).__name__}) – użyto ustawień domyślnych (obserwacja)"
            self._keep_original = True
            return TsfmSettings()
        if isinstance(raw, dict) and isinstance(raw.get("models"), dict) and any(k in raw["models"] for k in RETIRED_IDS):
            raw = self._migrate_retired(raw)
        try:
            return TsfmSettings.model_validate(raw)
        except Exception as exc:  # noqa: BLE001 - a broken file never enables anything: defaults = observation only
            self.load_error = f"settings.json niepoprawny ({str(exc)[:200]}) – użyto ustawień domyślnych (obserwacja)"
            self._keep_original = True
            return TsfmSettings()

    def _migrate_retired(self, raw: dict) -> dict:
        """1.40: FinCast removed from the active models; original kept, change recorded. Roles of a retired model are never carried over
        to its successor (Granite TTM starts in OBSERVE with its own validation)."""
        bak = self.path.with_name("settings.v139.bak.json")
        try:
            if not bak.exists():
                bak.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
        raw = json.loads(json.dumps(raw))
        retired = raw.setdefault("retired", {})
        for k in RETIRED_IDS:
            if k in raw["models"]:
                retired[k] = {"settings": raw["models"].pop(k), "status": "RETIRED", "retired_in": "1.40.0", "replaced_by": "granite_ttm"}
        try:
            s = TsfmSettings.model_validate(raw)
            self.path.write_text(json.dumps(s.model_dump(mode="json"), indent=2, ensure_ascii=False), encoding="utf-8")
            self._history("migration", {"retired": list(retired), "added": ["granite_ttm"], "backup": bak.name})
        except Exception:  # noqa: BLE001 - validated again by the caller
            pass
        return raw

    def _history(self, who: str, change: dict) -> None:
        try:
            with open(self.path.with_name("settings_history.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                    "who": who, "change": change}, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def history(self, limit: int = 50) -> list[dict]:
        try:
            lines = self.path.with_name("settings_history.jsonl").read_text(encoding="utf-8").splitlines()[-limit:]
        except OSError:
            return []
        out = []
        for ln in lines:
            try:
                out.append(json.loads(ln))
            except ValueError:
                pass
        return out

    def get(self) -> TsfmSettings:
        with self._lock:
            return self._s.model_copy(deep=True)

    def _backup_original(self) -> str | None:
        """1.46: the user's file that could not be loaded (one bad value, a key of another version, a hand edit) was replaced by the
        defaults + the patch on the first change, without a copy (instruments, TFs, context, horizons, roles lost). It is now copied
        byte for byte to settings.invalid-<UTC>.json first; when the copy fails nothing is overwritten (OSError)."""
        if not self._keep_original or not self.path.is_file():
            return None
        bak = self.path.with_name(f"settings.invalid-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}.json")
        bak.write_bytes(self.path.read_bytes())
        return bak.name

    def update(self, patch: dict, who: str = "panel") -> TsfmSettings:
        with self._lock:
            merged = _merge(self._s.model_dump(mode="json"), patch)
            s = TsfmSettings.model_validate(merged)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            backup = self._backup_original()
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(s.model_dump(mode="json"), indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
            self._s = s
            self.load_error = None
            self._keep_original = False
            if backup:
                self._history("invalid_file_kept", {"backup": backup})
            self._history(who, patch)
            return s.model_copy(deep=True)


def _merge(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in b.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out
