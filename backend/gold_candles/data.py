from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import re

import numpy as np
import pandas as pd


class DataError(ValueError):
    pass


# Exact broker symbols of non-gold instruments registered by the runtime (gold_candles_runtime.common.use_instrument) from
# config/instruments_v1.json. The feature/label code is price-scale free (ATR-relative) except grid_step, which comes from
# the instrument profile and is part of the contract hash.
REGISTERED_SYMBOLS: set[str] = set()


@dataclass(frozen=True)
class Config:
    symbol: str = "XAUUSD-"
    tick_size: float = 0.01
    neutral_atr: float = 0.20
    atr_period: int = 14
    grid_step: float = 5.0
    horizons: tuple[int, ...] = (1, 3, 6)

    def __post_init__(self):
        if self.symbol not in ("XAUUSD", "XAUUSD-") and self.symbol not in REGISTERED_SYMBOLS:
            raise DataError("ONLY_XAUUSD_SUPPORTED")
        for key in ("tick_size", "neutral_atr", "grid_step"):
            value = getattr(self, key)
            if not math.isfinite(value) or value <= 0:
                raise DataError(f"INVALID_CONFIG_{key}")
        if self.atr_period != 14 or self.horizons != (1, 3, 6):
            raise DataError("FEATURE_CONTRACT_REQUIRES_ATR14_AND_HORIZONS_1_3_6")

    def contract_hash(self):
        root=Path(__file__).parent
        sources={name:hashlib.sha256((root/name).read_bytes()).hexdigest()
                 for name in ("data.py","patterns.py","features.py","model.py")}
        payload = {"schema": "gold-candles-v2.0", "config": asdict(self),"source_hashes":sources}
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def utc(value=None) -> pd.Timestamp:
    if value is None:
        return pd.Timestamp(datetime.now(timezone.utc))
    parsed = pd.Timestamp(value)
    if parsed.tzinfo is None:
        raise DataError("TIMEZONE_REQUIRED_USE_ISO_UTC_WITH_Z")
    return parsed.tz_convert("UTC")


def clean_json(value):
    if isinstance(value, dict):
        return {str(k): clean_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(v) for v in value]
    if isinstance(value, (pd.Timestamp, datetime)):
        return utc(value).isoformat()
    if isinstance(value, np.generic):
        return clean_json(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def write_json(path: str | Path, payload):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(clean_json(payload), ensure_ascii=False,
                                 indent=2, allow_nan=False), encoding="utf-8")


def validate_bars(frame: pd.DataFrame, minutes: int, as_of=None,
                  symbol="XAUUSD-") -> pd.DataFrame:
    Config(symbol=symbol)
    if minutes not in (5, 30):
        raise DataError("ONLY_M5_AND_M30_SUPPORTED")
    if frame.empty:
        raise DataError("EMPTY_BARS")
    f = frame.copy()
    time_col = "time_open_utc" if "time_open_utc" in f else "time"
    required = {time_col, "open", "high", "low", "close"}
    if not required.issubset(f.columns):
        raise DataError(f"MISSING_COLUMNS:{sorted(required-set(f.columns))}")
    if "symbol" in f and not f["symbol"].eq(symbol).all():
        raise DataError("CSV_SYMBOL_MISMATCH")
    try:
        if pd.api.types.is_numeric_dtype(f[time_col]):
            times = pd.to_datetime(f[time_col], unit="s", utc=True, errors="raise")
        else:
            strings = f[time_col].astype(str)
            if not strings.str.contains(r"(?:Z|[+-]\d{2}:?\d{2})$", regex=True).all():
                raise DataError("NAIVE_CSV_TIMES_NOT_ALLOWED")
            times = pd.to_datetime(strings, utc=True, errors="raise", format="mixed")
        for col in ("open", "high", "low", "close"):
            f[col] = pd.to_numeric(f[col], errors="raise")
    except (TypeError, ValueError) as error:
        raise DataError(f"INVALID_BAR_VALUES:{error}") from error
    if times.isna().any():
        raise DataError("INVALID_TIMESTAMPS")
    f["time_open_utc"] = times
    if f["time_open_utc"].duplicated().any():
        raise DataError("DUPLICATE_BAR_TIMESTAMPS")
    if not f["time_open_utc"].is_monotonic_increasing:
        raise DataError("UNSORTED_BARS_NO_SILENT_REORDERING")
    numeric = f[["open", "high", "low", "close"]].to_numpy(dtype=float)
    if not np.isfinite(numeric).all() or (numeric <= 0).any():
        raise DataError("NONFINITE_OR_NONPOSITIVE_OHLC")
    if (f.high < f[["open", "close"]].max(axis=1)).any() or \
       (f.low > f[["open", "close"]].min(axis=1)).any() or (f.high < f.low).any():
        raise DataError("OHLC_GEOMETRY_INVALID")
    f["time_close_utc"] = f.time_open_utc + pd.Timedelta(minutes=minutes)
    now = utc(as_of)
    if (f.time_open_utc > now).any():
        raise DataError("FUTURE_BAR_OPEN_TIMESTAMP")
    # Scheduled close alone is insufficient for MT5: its adapter requests pos=1.
    # This filter additionally removes any forming row supplied by a CSV.
    f = f.loc[f.time_close_utc <= now].copy()
    if f.empty:
        raise DataError("NO_CLOSED_BARS")
    if "tick_volume" not in f:
        f["tick_volume"] = np.nan
    else:
        f["tick_volume"] = pd.to_numeric(f.tick_volume, errors="raise")
        if (f.tick_volume.dropna() < 0).any():
            raise DataError("NEGATIVE_TICK_VOLUME")
    f = f.reset_index(drop=True)
    f["gap_before"] = f.time_open_utc.diff().ne(pd.Timedelta(minutes=minutes))
    f.loc[0, "gap_before"] = False
    f.attrs.update(symbol=symbol, timeframe_minutes=minutes,
                   as_of=now.isoformat(), closed_only=True)
    return f


def read_csv(path, minutes=5, as_of=None, symbol="XAUUSD-"):
    return validate_bars(pd.read_csv(path), minutes, as_of, symbol)


def aggregate_m30(m5: pd.DataFrame):
    """Only complete six-bar UTC buckets. Never carry a partial future M30."""
    groups = m5.groupby(m5.time_open_utc.dt.floor("30min"), sort=True)
    rows = []
    for start, block in groups:
        expected = pd.date_range(start, periods=6, freq="5min")
        if len(block) != 6 or not block.time_open_utc.reset_index(drop=True).equals(pd.Series(expected)):
            continue
        rows.append(dict(time_open_utc=start, open=block.open.iloc[0],
                         high=block.high.max(), low=block.low.min(),
                         close=block.close.iloc[-1],
                         tick_volume=block.tick_volume.sum(min_count=1)))
    if not rows:
        raise DataError("NO_COMPLETE_M30_BUCKETS")
    result = pd.DataFrame(rows)
    result["time_close_utc"] = result.time_open_utc + pd.Timedelta(minutes=30)
    result["gap_before"] = result.time_open_utc.diff().ne(pd.Timedelta(minutes=30))
    result.loc[0, "gap_before"] = False
    result.attrs.update(m5.attrs)
    result.attrs["timeframe_minutes"] = 30
    return result


def closed_snapshot_id(m5, m30, config):
    records = []
    for frame in (m5, m30):
        if frame is not None:
            block = frame
            records.append(block[["time_open_utc", "open", "high", "low", "close"]]
                           .astype(str).to_dict("records"))
    return hashlib.sha256(json.dumps([config.contract_hash(), records], sort_keys=True).encode()).hexdigest()

