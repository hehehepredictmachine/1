from __future__ import annotations

import numpy as np
import pandas as pd
from .data import Config, aggregate_m30
from .patterns import flags, measurements


def efficiency(close,n=10):
    return (close-close.shift(n)).abs()/close.diff().abs().rolling(n,min_periods=n).sum().replace(0,np.nan)


def feature_frame(m5, m30=None, config=Config()):
    context_source = "BROKER_M30" if m30 is not None else "DERIVED_COMPLETE_UTC_M30"
    context = m30 if m30 is not None else aggregate_m30(m5)
    m = measurements(m5)
    a = m.atr.replace(0,np.nan)
    x = pd.DataFrame(index=m5.index)
    x["body_fraction"] = m.body_fraction
    x["upper_fraction"] = m.upper_fraction
    x["lower_fraction"] = m.lower_fraction
    x["close_position"] = m.close_position
    x["signed_body_atr"] = (m5.close-m5.open)/a
    x["range_atr"] = m.range/a
    for n in (1,3,6):
        contiguous = m5.time_open_utc.diff(n).eq(pd.Timedelta(minutes=5*n))
        x[f"return{n}_atr"] = ((m5.close-m5.close.shift(n))/a).where(contiguous)
    ema = m5.close.ewm(span=20,adjust=False,min_periods=20).mean()
    x["ema_distance_atr"] = (m5.close-ema)/a
    x["ema_slope3_atr"] = (ema-ema.shift(3))/a
    x["er10"] = efficiency(m5.close)
    x["range_compression"] = m.range/m.range.shift(1).rolling(10,min_periods=10).mean().replace(0,np.nan)
    x["grid_fraction"] = m5.close.mod(config.grid_step)/config.grid_step
    minutes = m5.time_close_utc.dt.hour*60+m5.time_close_utc.dt.minute
    x["time_sin"] = np.sin(2*np.pi*minutes/1440)
    x["time_cos"] = np.cos(2*np.pi*minutes/1440)
    pattern_flags = flags(m5,config).astype(float).add_prefix("pattern_")
    x = pd.concat([x,pattern_flags],axis=1)
    ctx_m = measurements(context)
    ctx_a = ctx_m.atr.replace(0,np.nan)
    ctx_ema = context.close.ewm(span=20,adjust=False,min_periods=20).mean()
    cf = pd.DataFrame({"context_closed_at":context.time_close_utc,
                       "m30_ema_distance_atr":(context.close-ctx_ema)/ctx_a,
                       "m30_ema_slope3_atr":(ctx_ema-ctx_ema.shift(3))/ctx_a,
                       "m30_er10":efficiency(context.close),
                       "m30_atr_ratio":ctx_a/config.grid_step})
    left = pd.DataFrame({"feature_time":m5.time_close_utc})
    joined = pd.merge_asof(left,cf,left_on="feature_time",right_on="context_closed_at",direction="backward")
    age = joined.feature_time-joined.context_closed_at
    usable = age.ge(pd.Timedelta(0)) & age.lt(pd.Timedelta(minutes=30))
    for name in cf.columns[1:]:
        x[name] = joined[name].where(usable).to_numpy()
    # All future observations, labels and after-entry fields remain outside X.
    x = x.replace([np.inf,-np.inf],np.nan)
    x.attrs.update(context_source=context_source,contract_hash=config.contract_hash())
    return x, joined.context_closed_at


def make_labels(m5,horizon,config=Config()):
    if horizon not in config.horizons:
        raise ValueError("UNSUPPORTED_HORIZON")
    a = measurements(m5).atr
    future_close = m5.close.shift(-horizon)
    label_end = m5.time_close_utc.shift(-horizon)
    continuous = (label_end-m5.time_close_utc).eq(pd.Timedelta(minutes=5*horizon))
    normalized = ((future_close-m5.close)/a).where(continuous & a.gt(0))
    y = pd.Series(np.nan,index=m5.index)
    valid = normalized.notna()
    y.loc[valid] = np.select([normalized.loc[valid]<-config.neutral_atr,
                              normalized.loc[valid]>config.neutral_atr], [0,2], default=1)
    return y, normalized, label_end.where(continuous)


def chronological_masks(times,label_end,train_fraction=.60,cal_fraction=.20,embargo_minutes=30):
    n=len(times)
    if n<10:
        raise ValueError("INSUFFICIENT_ROWS_FOR_SPLIT")
    cal_start = times.iloc[int(n*train_fraction)]
    test_start = times.iloc[int(n*(train_fraction+cal_fraction))]
    embargo = pd.Timedelta(minutes=embargo_minutes)
    fit = (times<cal_start) & (label_end<cal_start-embargo)
    calibration = (times>=cal_start) & (times<test_start) & (label_end<test_start-embargo)
    holdout = times>=test_start
    return fit, calibration, holdout, {"calibration_start_utc":cal_start.isoformat(),
                                      "holdout_start_utc":test_start.isoformat(),
                                      "embargo_minutes":embargo_minutes}

