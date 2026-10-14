from __future__ import annotations

import numpy as np
import pandas as pd
from .data import Config


PATTERN_DEFINITIONS = {
    "lower_wick_rejection": ("REJECTION", "BULLISH"),
    "upper_wick_rejection": ("REJECTION", "BEARISH"),
    "bullish_engulfing": ("BODY_REVERSAL", "BULLISH"),
    "bearish_engulfing": ("BODY_REVERSAL", "BEARISH"),
    "bullish_outside_close": ("RANGE_EXPANSION", "BULLISH"),
    "bearish_outside_close": ("RANGE_EXPANSION", "BEARISH"),
    "inside_bar": ("COMPRESSION", "NEUTRAL"),
    "nr4": ("COMPRESSION", "NEUTRAL"),
    "doji": ("INDECISION", "NEUTRAL"),
    "bullish_marubozu": ("MOMENTUM", "BULLISH"),
    "bearish_marubozu": ("MOMENTUM", "BEARISH"),
    "three_bar_reversal_bull_no_gap": ("MULTIBAR_REVERSAL", "BULLISH"),
    "three_bar_reversal_bear_no_gap": ("MULTIBAR_REVERSAL", "BEARISH"),
    "three_bar_continuation_bull": ("MULTIBAR_MOMENTUM", "BULLISH"),
    "three_bar_continuation_bear": ("MULTIBAR_MOMENTUM", "BEARISH"),
    "tweezer_bottom": ("REJECTION", "BULLISH"),
    "tweezer_top": ("REJECTION", "BEARISH"),
    "failed_breakdown": ("LIQUIDITY_REJECTION", "BULLISH"),
    "failed_breakout": ("LIQUIDITY_REJECTION", "BEARISH"),
    "bullish_displacement": ("MOMENTUM", "BULLISH"),
    "bearish_displacement": ("MOMENTUM", "BEARISH"),
    "inside_break_bull": ("CONFIRMED_COMPRESSION_BREAK", "BULLISH"),
    "inside_break_bear": ("CONFIRMED_COMPRESSION_BREAK", "BEARISH"),
}


def atr14(frame):
    previous = frame.close.shift(1)
    tr = pd.concat([frame.high-frame.low, (frame.high-previous).abs(),
                    (frame.low-previous).abs()], axis=1).max(axis=1)
    # Wilder seed: simple mean of first 14 TRs, then recursive alpha=1/14.
    result = np.full(len(tr), np.nan)
    if len(tr) >= 14:
        result[13] = tr.iloc[:14].mean()
        for i in range(14, len(tr)):
            result[i] = (result[i-1]*13+tr.iloc[i])/14
    return pd.Series(result, index=frame.index)


def measurements(frame):
    o, h, l, c = (frame[x] for x in ("open", "high", "low", "close"))
    r = h-l
    safe = r.replace(0, np.nan)
    body = (c-o).abs()
    upper = h-pd.concat([o,c], axis=1).max(axis=1)
    lower = pd.concat([o,c], axis=1).min(axis=1)-l
    return pd.DataFrame(dict(range=r, body=body, upper_wick=upper,
                             lower_wick=lower, body_fraction=body/safe,
                             upper_fraction=upper/safe, lower_fraction=lower/safe,
                             close_position=(c-l)/safe, atr=atr14(frame)), index=frame.index)


def flags(frame, config=Config()):
    m = measurements(frame)
    o,h,l,c = (frame[x] for x in ("open","high","low","close"))
    b,u,d,p,a = (m[x] for x in ("body_fraction","upper_fraction",
                              "lower_fraction","close_position","atr"))
    up, down = c>o, c<o
    valid = m.range.gt(0) & a.gt(0)
    joint2 = ~frame.gap_before
    joint3 = joint2 & joint2.shift(1, fill_value=False)
    prior_top = pd.concat([o.shift(1),c.shift(1)],axis=1).max(axis=1)
    prior_bottom = pd.concat([o.shift(1),c.shift(1)],axis=1).min(axis=1)
    tolerance = pd.concat([a*0.10, pd.Series(2*config.tick_size,index=frame.index)],axis=1).max(axis=1)
    f = pd.DataFrame(index=frame.index)
    f["lower_wick_rejection"] = b.between(.10,.45) & (d>=.50) & (m.lower_wick>=2*m.body) & (u<=.20) & (p>=.70) & (m.range>=.60*a)
    f["upper_wick_rejection"] = b.between(.10,.45) & (u>=.50) & (m.upper_wick>=2*m.body) & (d<=.20) & (p<=.30) & (m.range>=.60*a)
    f["bullish_engulfing"] = joint2 & up & down.shift(1,fill_value=False) & (o<=c.shift(1)) & (c>=o.shift(1)) & (m.body>m.body.shift(1)) & (b>=.35)
    f["bearish_engulfing"] = joint2 & down & up.shift(1,fill_value=False) & (o>=c.shift(1)) & (c<=o.shift(1)) & (m.body>m.body.shift(1)) & (b>=.35)
    outside = joint2 & (h>h.shift(1)) & (l<l.shift(1))
    f["bullish_outside_close"] = outside & up & (p>=.75) & (c>c.shift(1))
    f["bearish_outside_close"] = outside & down & (p<=.25) & (c<c.shift(1))
    f["inside_bar"] = joint2 & (h<h.shift(1)) & (l>l.shift(1))
    f["nr4"] = joint3 & joint2.shift(2,fill_value=False) & (m.range<m.range.shift(1).rolling(3,min_periods=3).min())
    f["doji"] = (b<=.08) & (m.range>=.40*a)
    f["bullish_marubozu"] = up & (b>=.80) & (u<=.10) & (d<=.10) & (m.range>=.80*a)
    f["bearish_marubozu"] = down & (b>=.80) & (u<=.10) & (d<=.10) & (m.range>=.80*a)
    mid2 = (o.shift(2)+c.shift(2))/2
    small_mid = b.shift(1)<=.30
    f["three_bar_reversal_bull_no_gap"] = joint3 & down.shift(2,fill_value=False) & (b.shift(2)>=.50) & small_mid & up & (b>=.50) & (c>mid2)
    f["three_bar_reversal_bear_no_gap"] = joint3 & up.shift(2,fill_value=False) & (b.shift(2)>=.50) & small_mid & down & (b>=.50) & (c<mid2)
    o_in_prior_body = (o>=prior_bottom-2*config.tick_size) & (o<=prior_top+2*config.tick_size)
    all_up = up & up.shift(1,fill_value=False) & up.shift(2,fill_value=False)
    all_down = down & down.shift(1,fill_value=False) & down.shift(2,fill_value=False)
    bodies = (b>=.50) & (b.shift(1)>=.50) & (b.shift(2)>=.50)
    f["three_bar_continuation_bull"] = joint3 & all_up & bodies & (c>c.shift(1)) & (c.shift(1)>c.shift(2)) & o_in_prior_body & o_in_prior_body.shift(1,fill_value=False)
    f["three_bar_continuation_bear"] = joint3 & all_down & bodies & (c<c.shift(1)) & (c.shift(1)<c.shift(2)) & o_in_prior_body & o_in_prior_body.shift(1,fill_value=False)
    f["tweezer_bottom"] = joint2 & down.shift(1,fill_value=False) & up & ((l-l.shift(1)).abs()<=tolerance) & (c>c.shift(1)) & (b>=.30)
    f["tweezer_top"] = joint2 & up.shift(1,fill_value=False) & down & ((h-h.shift(1)).abs()<=tolerance) & (c<c.shift(1)) & (b>=.30)
    contiguous5 = frame.time_open_utc.diff(5).eq(pd.Timedelta(minutes=5*frame.attrs.get("timeframe_minutes",5)))
    low5, high5 = l.shift(1).rolling(5,min_periods=5).min(), h.shift(1).rolling(5,min_periods=5).max()
    f["failed_breakdown"] = contiguous5 & (l<low5) & (c>low5) & (p>=.75) & ((low5-l)>=.10*a)
    f["failed_breakout"] = contiguous5 & (h>high5) & (c<high5) & (p<=.25) & ((h-high5)>=.10*a)
    displacement = (m.body>=.80*a) & (m.range>=1.20*a) & (b>=.65)
    f["bullish_displacement"] = displacement & up & (p>=.80)
    f["bearish_displacement"] = displacement & down & (p<=.20)
    f["inside_break_bull"] = joint3 & f.inside_bar.shift(1,fill_value=False) & (c>h.shift(1)) & up & (p>=.70)
    f["inside_break_bear"] = joint3 & f.inside_bar.shift(1,fill_value=False) & (c<l.shift(1)) & down & (p<=.30)
    return f.fillna(False).astype(bool).mul(valid,axis=0).astype(bool)


def latest_patterns(frame, config=Config()):
    f = flags(frame,config).iloc[-1]
    m = measurements(frame).iloc[-1]
    active = []
    for name in f.index[f]:
        family,direction = PATTERN_DEFINITIONS[name]
        active.append(dict(name=name,family=family,directional_evidence=direction,
                           confirmed_at=frame.time_close_utc.iloc[-1].isoformat(),
                           status="CLOSED_BAR_MORPHOLOGY_NOT_A_TRADE_SIGNAL"))
    sides = {p["directional_evidence"] for p in active}-{"NEUTRAL"}
    hypothesis = next(iter(sides)) if len(sides)==1 else ("MIXED" if sides else "NEUTRAL")
    return dict(patterns=active,morphology_hypothesis=hypothesis,
                probability=None,measurements=m.to_dict(),
                confirmation_families=sorted({p["family"] for p in active}))

