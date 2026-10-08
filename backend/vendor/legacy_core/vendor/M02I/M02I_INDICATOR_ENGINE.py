"""MasterQUO M02I v1.1.0-CANDIDATE: deterministic, read-only indicator intelligence.

Consumes point-in-time M01 DATA_SNAPSHOT and optional matching M02 MARKET_STATE.
No MT5 login, orders, screenshots, OCR, network, self-training, win probabilities.
Indicators use CLOSED confirmed broker OHLC only. Requires audited M01 gates for trust.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "1.1.0-CANDIDATE"
POLICY = "MT5_PRIMARY_TV_SUPPLEMENTAL_NO_SCREENSHOTS"
TIMEFRAMES = {"D1", "H4", "H1", "M15", "M5", "M1"}
SEVERE = {"MIXED_PRICE_BASIS", "CONFLICTING_BAR_REVISIONS", "INVALID_OHLC", "INVALID_BAR_TIME",
          "INSTRUMENT_MISMATCH", "TIMEFRAME_MISMATCH", "NON_MT5_SOURCE", "MISSING_PROVENANCE",
          "DUPLICATED_EVIDENCE_ID", "INVALID_VOLUME"}


def utc(t: str) -> datetime:
    if not isinstance(t, str) or not t:
        raise ValueError("TIME_UNKNOWN")
    x = datetime.fromisoformat(t.replace("Z", "+00:00"))
    if x.tzinfo is None:
        raise ValueError("TIMEZONE_REQUIRED")
    return x.astimezone(timezone.utc)


def num(v: Any) -> bool:
    return isinstance(v, (float, int)) and not isinstance(v, bool) and math.isfinite(float(v))


def value(v: float | None, unit: str = "", reason: str | None = None, kind: str = "OHLC_DERIVED") -> dict:
    ok = v is not None and num(v)
    return {"value": float(v) if ok else None, "unit": unit, "status": "AVAILABLE" if ok else "UNAVAILABLE",
            "evidence_type": kind, "reason": None if ok else (reason or "INSUFFICIENT_DATA")}


def profile_check(cfg: dict) -> None:
    ps = ("ema_fast", "ema_mid", "ema_slow", "rsi_period", "atr_period", "adx_period", "macd_fast",
          "macd_slow", "macd_signal", "bb_period", "pivot_left", "pivot_right")
    for k in ps:
        if type(cfg.get(k)) is not int or not 1 <= cfg[k] <= 400:
            raise ValueError("INVALID_PROFILE_" + k)
    if not (cfg["ema_fast"] < cfg["ema_mid"] < cfg["ema_slow"] and cfg["macd_fast"] < cfg["macd_slow"]):
        raise ValueError("INVALID_PROFILE_PERIOD_ORDER")
    if not num(cfg.get("bb_std_mult")) or not 0 < cfg["bb_std_mult"] < 10:
        raise ValueError("INVALID_PROFILE_BB")
    for k in ("rsi_overbought", "rsi_oversold", "adx_trend_min"):
        if not num(cfg.get(k)) or not 0 <= cfg[k] <= 100:
            raise ValueError("INVALID_PROFILE_" + k)
    if cfg["rsi_oversold"] >= cfg["rsi_overbought"]:
        raise ValueError("INVALID_RSI_THRESHOLDS")
    if cfg.get("price_basis_allowed") not in ("BID", "ASK", "MID", "LAST"):
        raise ValueError("INVALID_PRICE_BASIS_PROFILE")
    if type(cfg.get("allow_tick_vwap_proxy")) is not bool:
        raise ValueError("INVALID_VWAP_PROFILE")
    tfs=cfg.get("timeframes")
    if "timeframe_profiles" in cfg:
        validate_timeframe_profiles(cfg)
    if not isinstance(tfs,list) or not tfs or len(tfs)!=len(set(tfs)) or not set(tfs)<=TIMEFRAMES:
        raise ValueError("INVALID_PROFILE_TIMEFRAMES")
    if type(cfg.get("min_closed_bars")) is not int or cfg["min_closed_bars"]<1:
        raise ValueError("INVALID_MIN_CLOSED_BARS")
    if type(cfg.get("atr_baseline_bars")) is not int or not 5<=cfg["atr_baseline_bars"]<=200:
        raise ValueError("INVALID_ATR_BASELINE")
    for k in ("atr_low_ratio", "atr_high_ratio", "ema_extension_atr_threshold"):
        if not num(cfg.get(k)) or cfg[k]<=0:
            raise ValueError("INVALID_PROFILE_"+k)
    if cfg["atr_low_ratio"]>=cfg["atr_high_ratio"]:
        raise ValueError("INVALID_ATR_VOL_BOUNDS")


def ema(data: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(data)
    if len(data) < n:
        return out
    current = sum(data[:n]) / n  # explicit SMA seed
    out[n-1] = current
    k = 2.0 / (n + 1.0)
    for i in range(n, len(data)):
        current += k * (data[i] - current)
        out[i] = current
    return out


def rsi(data: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(data)
    if len(data) < n+1:
        return out
    deltas = [data[i] - data[i-1] for i in range(1, len(data))]
    up = sum(max(0.0, x) for x in deltas[:n]) / n
    down = sum(max(0.0, -x) for x in deltas[:n]) / n
    def calc(u: float, d: float) -> float:
        if u == 0 and d == 0:
            return 50.0
        if d == 0:
            return 100.0
        if u == 0:
            return 0.0
        return 100.0 - 100.0 / (1.0 + u / d)
    out[n] = calc(up, down)
    for i in range(n+1, len(data)):
        ch = deltas[i-1]
        up = (up * (n-1) + max(0.0, ch)) / n
        down = (down * (n-1) + max(0.0, -ch)) / n
        out[i] = calc(up, down)
    return out


def true_ranges(bars: list[dict]) -> list[float]:
    res = [float(bars[0]["high"]) - float(bars[0]["low"])]
    for i in range(1, len(bars)):
        b, pc = bars[i], float(bars[i-1]["close"])
        res.append(max(float(b["high"]) - float(b["low"]), abs(float(b["high"]) - pc),
                       abs(float(b["low"]) - pc)))
    return res


def atr(bars: list[dict], n: int) -> list[float | None]:
    res: list[float | None] = [None] * len(bars)
    if len(bars) <= n:
        return res
    t = true_ranges(bars)
    current = sum(t[1:n+1]) / n  # Wilder seed from n real transitions
    res[n] = current
    for i in range(n+1, len(bars)):
        current = (current*(n-1) + t[i]) / n
        res[i] = current
    return res


def adx(bars: list[dict], n: int) -> dict[str, list[float | None]]:
    total = len(bars)
    av: list[float | None] = [None]*total
    plus: list[float | None] = [None]*total
    minus: list[float | None] = [None]*total
    dx: list[float | None] = [None]*total
    if total <= n:
        return {"adx": av, "+di": plus, "-di": minus}
    trs = true_ranges(bars)
    pdm = [0.0]*total
    mdm = [0.0]*total
    for i in range(1, total):
        up = float(bars[i]["high"]) - float(bars[i-1]["high"])
        down = float(bars[i-1]["low"]) - float(bars[i]["low"])
        pdm[i] = up if up > down and up > 0 else 0.0
        mdm[i] = down if down > up and down > 0 else 0.0
    trsum = sum(trs[1:n+1]); psum = sum(pdm[1:n+1]); msum = sum(mdm[1:n+1])
    for i in range(n, total):
        if i > n:
            trsum = trsum - trsum/n + trs[i]
            psum = psum - psum/n + pdm[i]
            msum = msum - msum/n + mdm[i]
        p = 100 * psum/trsum if trsum > 0 else 0.0
        m = 100 * msum/trsum if trsum > 0 else 0.0
        plus[i], minus[i] = p, m
        dx[i] = 100 * abs(p-m)/(p+m) if p+m > 0 else 0.0
    first = 2*n-1
    if total > first:
        current = sum(float(x) for x in dx[n:first+1])/n
        av[first] = current
        for i in range(first+1,total):
            current = (current*(n-1) + float(dx[i]))/n
            av[i] = current
    return {"adx": av, "+di": plus, "-di": minus}


def macd(data: list[float], fast: int, slow: int, signal: int, signal_ma: str="EMA") -> dict[str,list[float|None]]:
    a, b = ema(data,fast), ema(data,slow)
    line = [x-y if x is not None and y is not None else None for x,y in zip(a,b)]
    valid = [x for x in line if x is not None]
    if signal_ma == "EMA":
        sig_part = ema(valid, signal)
    elif signal_ma == "SMA":
        sig_part = [sum(valid[i-signal+1:i+1])/signal if i>=signal-1 else None
                    for i in range(len(valid))]
    else:
        raise ValueError("INVALID_MACD_SIGNAL_MA")
    sig = [None] * (len(line)-len(valid)) + sig_part
    hist = [x-y if x is not None and y is not None else None for x,y in zip(line,sig)]
    return {"line":line, "signal":sig, "histogram":hist}


def bb(data: list[float], n: int, k: float) -> dict[str, float | None]:
    if len(data) < n:
        return {"mid":None,"upper":None,"lower":None,"percent_b":None,"bandwidth":None}
    seq = data[-n:]
    avg = statistics.mean(seq); sd = statistics.pstdev(seq)
    hi = avg + k*sd; lo = avg-k*sd
    return {"mid":avg,"upper":hi,"lower":lo,
            "percent_b":(seq[-1]-lo)/(hi-lo) if hi>lo else None,
            "bandwidth":(hi-lo)/avg if avg>0 else None}


def obv(bars:list[dict]) -> float | None:
    if not bars or any(not num(b.get("tick_volume")) or b["tick_volume"] < 0 for b in bars):
        return None
    if not any(b["tick_volume"] > 0 for b in bars):
        return None
    level = 0.0
    for prev,b in zip(bars,bars[1:]):
        delta = (float(b["close"]) > float(prev["close"])) - (float(b["close"]) < float(prev["close"]))
        level += delta*float(b["tick_volume"])
    return level


def prepare(snapshot:dict, tf:str, cfg:dict, *, instrument_id:str="XAUUSD",
            source_bars:list|None=None) -> tuple[list[dict],list[str]]:
    now = utc(snapshot["as_of"])
    barlist = snapshot.get("candles_by_tf",{}).get(tf,[]) if source_bars is None else source_bars
    if not isinstance(barlist,list):
        return [],["INVALID_BAR_LIST"]
    issues=[]; buckets={}; evidence_ids=set()
    for b in barlist:
        if not isinstance(b,dict):
            issues.append("INVALID_BAR_OBJECT"); continue
        if b.get("bar_state")=="FORMING":
            continue
        if b.get("bar_state")!="CLOSED":
            issues.append("BAR_NOT_CONFIRMED"); continue
        if b.get("instrument_id")!=instrument_id:
            issues.append("INSTRUMENT_MISMATCH");continue
        if b.get("timeframe")!=tf:
            issues.append("TIMEFRAME_MISMATCH");continue
        if not str(b.get("source_id", "")).upper().startswith("MT5"):
            issues.append("NON_MT5_SOURCE");continue
        if b.get("price_basis")!=cfg["price_basis_allowed"]:
            issues.append("MIXED_PRICE_BASIS");continue
        if not b.get("evidence_id"):
            issues.append("MISSING_PROVENANCE");continue
        try:
            opened=utc(b["bar_open_utc"]); available=utc(b["available_at"]); closed=utc(b["close_confirmed_at"])
        except (ValueError,KeyError,TypeError):
            issues.append("INVALID_BAR_TIME");continue
        if not (opened < closed <= now and opened <= available <= now):
            # future bars must not contribute; not all future timestamps imply corrupt packet
            if available>now or closed>now:
                issues.append("FUTURE_BAR_EXCLUDED")
            else:
                issues.append("INVALID_BAR_TIME")
            continue
        if not all(num(b.get(k)) for k in ("open","high","low","close")):
            issues.append("INVALID_OHLC");continue
        op, hi, lo, cl = [float(b[k]) for k in ("open","high","low","close")]
        if not (0 < lo <= min(op,cl) <= max(op,cl) <= hi):
            issues.append("INVALID_OHLC"); continue
        if any(b.get(k) is not None and (not num(b[k]) or b[k]<0) for k in ("tick_volume","real_volume")):
            issues.append("INVALID_VOLUME");continue
        key=opened.isoformat()
        if key in buckets:
            existing=buckets[key]
            def signature(x:dict)->tuple:
                return tuple(x.get(k) for k in ("open","high","low","close","tick_volume","real_volume","price_basis"))
            try: nr=int(b.get("revision",0)); old=int(existing.get("revision",0))
            except (TypeError,ValueError):
                issues.append("INVALID_REVISION");continue
            if nr == old and signature(b)!=signature(existing):
                issues.append("CONFLICTING_BAR_REVISIONS");continue
            if nr > old:
                buckets[key]=b
        else:
            buckets[key]=b
    out=sorted(buckets.values(),key=lambda x:utc(x["bar_open_utc"]))
    # Need uniqueness of event IDs among distinct bars, not duplicated revisions.
    for b in out:
        eid=b["evidence_id"]
        if eid in evidence_ids:
            issues.append("DUPLICATED_EVIDENCE_ID")
        evidence_ids.add(eid)
    if not out:
        issues.append("NO_CLOSED_MT5_BARS")
    if any(x in SEVERE or x in ("INVALID_BAR_LIST","INVALID_BAR_OBJECT","INVALID_REVISION") for x in issues):
        return [], sorted(set(issues))
    return out,sorted(set(issues))


def pivots_divergence(bars:list[dict], rsis:list[float|None], left:int,right:int) -> dict:
    highs=[]; lows=[]
    for i in range(left,len(bars)-right):
        if rsis[i] is None:
            continue
        before=bars[i-left:i]; after=bars[i+1:i+right+1]
        if all(float(bars[i]["high"])>float(x["high"]) for x in before+after):
            highs.append(i)
        if all(float(bars[i]["low"])<float(x["low"]) for x in before+after):
            lows.append(i)
    result={"type":"NONE","pivot_times":[],"confirmed_by":None,"limitations":["PIVOTS_CONFIRMED_ONLY_WITH_RIGHT_BARS"]}
    if len(highs)>=2:
        a,b=highs[-2:]
        if float(bars[b]["high"])>float(bars[a]["high"]) and float(rsis[b])<float(rsis[a]):
            result.update({"type":"BEARISH_RSI_DIVERGENCE","pivot_times":[bars[a]["bar_open_utc"],bars[b]["bar_open_utc"]],"confirmed_by":bars[b+right]["close_confirmed_at"]})
    if result["type"]=="NONE" and len(lows)>=2:
        a,b=lows[-2:]
        if float(bars[b]["low"])<float(bars[a]["low"]) and float(rsis[b])>float(rsis[a]):
            result.update({"type":"BULLISH_RSI_DIVERGENCE","pivot_times":[bars[a]["bar_open_utc"],bars[b]["bar_open_utc"]],"confirmed_by":bars[b+right]["close_confirmed_at"]})
    return result


def session_vwap(bars:list[dict], context:dict|None, cfg:dict, now:datetime) -> dict:
    unavailable=lambda reason:{"value":None,"unit":"price","status":"UNAVAILABLE","evidence_type":None,"reason":reason}
    if not isinstance(context,dict) or context.get("session_data_complete") is not True or context.get("source_module")!="M04" or context.get("status")!="PASS":
        return unavailable("NO_VERIFIED_SESSION_COVERAGE")
    try:
        anchor=utc(context["session_anchor_utc"])
    except (KeyError,ValueError,TypeError):
        return unavailable("NO_SESSION_ANCHOR")
    if anchor>now:
        return unavailable("FUTURE_SESSION_ANCHOR")
    within=[b for b in bars if utc(b["bar_open_utc"])>=anchor]
    if not within:
        return unavailable("NO_SESSION_BARS")
    if all(num(b.get("real_volume")) and b["real_volume"]>0 for b in within):
        field="real_volume";typ="BROKER_REAL_VOLUME"
    elif cfg["allow_tick_vwap_proxy"] and all(num(b.get("tick_volume")) and b["tick_volume"]>0 for b in within):
        field="tick_volume";typ="TICK_VOLUME_PROXY_NOT_EXCHANGE_VWAP"
    else:
        return unavailable("REAL_VOLUME_UNAVAILABLE_AND_PROXY_NOT_ALLOWED")
    total=sum(float(b[field]) for b in within)
    if total<=0:return unavailable("ZERO_VOLUME")
    raw=sum((float(b["high"])+float(b["low"])+float(b["close"]))/3*float(b[field]) for b in within)/total
    return {"value":raw,"unit":"price","status":"AVAILABLE","evidence_type":typ,"reason":None,
            "anchor_utc":anchor.isoformat(),"bars_used":len(within)}


def classify(bars:list[dict], cfg:dict, market_tf:dict|None, context:dict|None, now:datetime)->dict:
    closes=[float(b["close"]) for b in bars]
    ema_fast=ema(closes,cfg["ema_fast"]);ema_mid=ema(closes,cfg["ema_mid"]);ema_slow=ema(closes,cfg["ema_slow"])
    rsis=rsi(closes,cfg["rsi_period"])
    atrs=atr(bars,cfg["atr_period"])
    dax=adx(bars,cfg["adx_period"])
    md=macd(closes,cfg["macd_fast"],cfg["macd_slow"],cfg["macd_signal"])
    band=bb(closes,cfg["bb_period"],cfg["bb_std_mult"])
    prev_atr=[x for x in atrs[-(cfg["atr_baseline_bars"]+1):-1] if x is not None and x>0]
    atr_ratio=(atrs[-1]/statistics.median(prev_atr) if atrs[-1] is not None
               and len(prev_atr)==cfg["atr_baseline_bars"] else None)
    ema_distance=(closes[-1]-ema_fast[-1])/atrs[-1] if (ema_fast[-1] is not None
                  and atrs[-1] is not None and atrs[-1]>0) else None
    fields={"ema_fast":value(ema_fast[-1],"price"),"ema_mid":value(ema_mid[-1],"price"),
            "ema_slow":value(ema_slow[-1],"price"),"rsi":value(rsis[-1],"index"),
            "atr":value(atrs[-1],"price"),"adx":value(dax["adx"][-1],"index"),
            "plus_di":value(dax["+di"][-1],"index"),"minus_di":value(dax["-di"][-1],"index"),
            "macd":value(md["line"][-1],"price"),"macd_signal":value(md["signal"][-1],"price"),
            "macd_histogram":value(md["histogram"][-1],"price"),
            "bb_mid":value(band["mid"],"price"),"bb_upper":value(band["upper"],"price"),
            "bb_lower":value(band["lower"],"price"),"bb_percent_b":value(band["percent_b"],"ratio", "ZERO_BANDWIDTH"),
            "bb_bandwidth":value(band["bandwidth"],"ratio"),
            "atr_ratio_to_previous_median":value(atr_ratio,"ratio"),
            "ema_fast_distance_atr":value(ema_distance,"ATR_units"),
            "obv_tick":value(obv(bars),"broker_tick_volume_units", "TICK_VOLUME_MISSING", "BROKER_TICK_VOLUME_PROXY")}
    fields["session_vwap"]=session_vwap(bars,context,cfg,now)
    fields["cvd"]={"value":None,"unit":None,"status":"UNAVAILABLE","evidence_type":None,
                   "reason":"AGGRESSOR_SIGNED_TRADES_UNAVAILABLE"}
    e1,e2,e3=ema_fast[-1],ema_mid[-1],ema_slow[-1]
    current=closes[-1]; r=rsis[-1]; ad=dax["adx"][-1]; h=md["histogram"][-1]
    reg=(market_tf or {}).get("structure_regime","UNKNOWN")
    if (market_tf or {}).get("status") not in ("PASS","PASS_WITH_LIMITATIONS"):
        reg="UNKNOWN"
    stack="UNKNOWN"
    if all(x is not None for x in (e1,e2,e3)):
        if current>e1>e2>e3: stack="UP_STACK"
        elif current<e1<e2<e3:stack="DOWN_STACK"
        else:stack="MIXED"
    strength=("STRONG" if ad is not None and ad>=cfg["adx_trend_min"] else
              "WEAK_OR_RANGE" if ad is not None else "UNKNOWN")
    di_direction=("UP" if dax["+di"][-1] is not None and dax["-di"][-1] is not None
                   and dax["+di"][-1]>dax["-di"][-1] else
                  "DOWN" if dax["+di"][-1] is not None and dax["-di"][-1] is not None
                   and dax["-di"][-1]>dax["+di"][-1] else "UNKNOWN")
    if atr_ratio is None:vol_context="UNKNOWN"
    elif atr_ratio>=cfg["atr_high_ratio"]:vol_context="ATR_EXPANSION"
    elif atr_ratio<=cfg["atr_low_ratio"]:vol_context="ATR_CONTRACTION"
    else:vol_context="ATR_STABLE"
    if band["upper"] is None:bb_context="UNKNOWN"
    elif current>band["upper"]:bb_context="ABOVE_UPPER_BAND_NOT_AUTOMATIC_BUY"
    elif current<band["lower"]:bb_context="BELOW_LOWER_BAND_NOT_AUTOMATIC_SELL"
    else:bb_context="INSIDE_BANDS"
    prior_h=md["histogram"][-2] if len(md["histogram"])>1 else None
    if h is None or prior_h is None:momentum_cross="UNKNOWN"
    elif prior_h<=0<h:momentum_cross="MACD_POSITIVE_CROSS_CLOSED_BAR"
    elif prior_h>=0>h:momentum_cross="MACD_NEGATIVE_CROSS_CLOSED_BAR"
    else:momentum_cross="NO_NEW_CROSS"
    reading="RSI_UNAVAILABLE"
    if r is not None:
        if r>=cfg["rsi_overbought"]:
            reading=("OVERBOUGHT_IN_UPTREND_NOT_AUTOMATIC_SHORT" if reg=="TREND_UP" and strength=="STRONG" else
                     "OVERBOUGHT_CONTEXT_ONLY")
        elif r<=cfg["rsi_oversold"]:
            reading=("OVERSOLD_IN_DOWNTREND_NOT_AUTOMATIC_LONG" if reg=="TREND_DOWN" and strength=="STRONG" else
                     "OVERSOLD_CONTEXT_ONLY")
        else:reading="RSI_MID_RANGE"
    conflict=[]
    if reg=="TREND_UP" and stack=="DOWN_STACK": conflict.append("EMA_STACK_OPPOSES_M02_UPTREND")
    if reg=="TREND_DOWN" and stack=="UP_STACK": conflict.append("EMA_STACK_OPPOSES_M02_DOWNTREND")
    if reg=="TREND_UP" and h is not None and h<0: conflict.append("MACD_MOMENTUM_COUNTER_TREND_UP")
    if reg=="TREND_DOWN" and h is not None and h>0: conflict.append("MACD_MOMENTUM_COUNTER_TREND_DOWN")
    if strength=="STRONG" and stack in ("UP_STACK","DOWN_STACK") and reg in ("TREND_UP","TREND_DOWN"):
        narrative="TREND_STRENGTH_MOMENTUM_ARE_CORRELATED_NOT_INDEPENDENT_VOTES"
    else:narrative="INDICATORS_REQUIRE_PRICE_STRUCTURE_AND_LIQUIDITY_CONTEXT"
    divergence=pivots_divergence(bars,rsis,cfg["pivot_left"],cfg["pivot_right"])
    return {"indicators":fields,"interpretation":{"ema_stack":stack,"adx_strength":strength,
            "di_direction":di_direction,"volatility_context":vol_context,
            "bollinger_context":bb_context,"macd_histogram_cross":momentum_cross,
            "ema_extension_context":"EXTENDED_FROM_EMA_NOT_REVERSAL_SIGNAL" if ema_distance is not None
               and abs(ema_distance)>=cfg["ema_extension_atr_threshold"] else
               "NOT_EXTENDED" if ema_distance is not None else "UNKNOWN",
            "m02_structure_regime":reg,"rsi_context":reading,
            "macd_momentum":"POSITIVE" if h is not None and h>0 else "NEGATIVE" if h is not None and h<0 else "UNKNOWN",
            "conflicts":conflict,"rsi_divergence":divergence,
            "evidence_groups":["TREND_CONTEXT","MOMENTUM","VOLATILITY","PARTICIPATION_PROXY"],
            "correlation_warning":narrative,"trade_signal":"NONE","win_probability":None,
            "market_direction":"UNKNOWN" if reg=="UNKNOWN" else "BULLISH" if reg=="TREND_UP" else "BEARISH" if reg=="TREND_DOWN" else "NEUTRAL" if reg=="RANGE" else "UNKNOWN"}}


# Versioned, timeframe-specific MT5 chart profiles. Legacy global profile remains
# functional for compatibility; selecting a new profile is an explicit opt-in.
ALLOWED_KEYS = {"ema", "rsi", "macd", "adx_wilder", "atr", "bollinger", "tick_volumes",
                "obv", "session_vwap", "fractals"}


def validate_timeframe_profiles(cfg:dict)->None:
    profiles=cfg.get("timeframe_profiles")
    if not isinstance(profiles,dict) or set(profiles)!=set(cfg["timeframes"]):
        raise ValueError("TIMEFRAME_PROFILE_MISSING_OR_EXTRA")
    for tf,pc in profiles.items():
        if not isinstance(pc,dict) or not isinstance(pc.get("role"),str):
            raise ValueError("INVALID_TF_PROFILE:"+tf)
        enabled=pc.get("enabled")
        if not isinstance(enabled,dict) or not enabled or not set(enabled)<=ALLOWED_KEYS:
            raise ValueError("INVALID_TF_INDICATORS:"+tf)
        for k,v in enabled.items():
            if k=="ema":
                if (not isinstance(v,list) or not 1<=len(v)<=3 or any(type(n)!=int or not 2<=n<=400 for n in v)
                        or len(set(v))!=len(v) or v!=sorted(v)):
                    raise ValueError("INVALID_EMA_PERIODS:"+tf)
            elif k in ("rsi","atr","adx_wilder"):
                if type(v)!=int or not 2<=v<=100:
                    raise ValueError("INVALID_INDICATOR_PERIOD:"+tf+":"+k)
            elif k=="macd":
                if not isinstance(v,dict) or v.get("signal_ma")!="SMA" or any(type(v.get(x))!=int or not 2<=v[x]<=100 for x in ("fast","slow","signal")) or not v["fast"]<v["slow"]:
                    raise ValueError("INVALID_MACD_PROFILE:"+tf)
            elif k=="bollinger":
                if not isinstance(v,dict) or type(v.get("period"))!=int or not 2<=v["period"]<=200 or not num(v.get("std_mult")) or v["std_mult"]<=0:
                    raise ValueError("INVALID_BOLLINGER_PROFILE:"+tf)
            elif type(v)!=bool:
                raise ValueError("INVALID_BOOLEAN_INDICATOR:"+tf+":"+k)
        if type(pc.get("min_closed_bars"))!=int or not 10<=pc["min_closed_bars"]<=2000:
            raise ValueError("INVALID_TF_MIN_BARS:"+tf)
        required=max([20]+[n+20 for n in enabled.get("ema",[])]+
                     [enabled.get("rsi",0)+1,2*enabled.get("adx_wilder",0),
                      enabled.get("atr",0)+cfg["atr_baseline_bars"]+1,
                      (enabled.get("macd") or {}).get("slow",0)+(enabled.get("macd") or {}).get("signal",0)-1,
                      (enabled.get("bollinger") or {}).get("period",0)])
        if pc["min_closed_bars"]<required:
            raise ValueError("TF_WARMUP_TOO_SHORT:"+tf)
    auxiliary=cfg.get("auxiliary_instruments",{})
    if not isinstance(auxiliary,dict) or not set(auxiliary)<={"DXY"}:
        raise ValueError("INVALID_AUXILIARY_INSTRUMENTS")
    if "DXY" in auxiliary:
        ax=auxiliary["DXY"]
        if not isinstance(ax,dict) or ax.get("required_for_xau_direction") is not False or ax.get("timeframe")!="H1":
            raise ValueError("INVALID_DXY_POLICY")
        if ax.get("enabled") is not True:
            raise ValueError("INVALID_DXY_ENABLED")
        sub=ax.get("indicators",{})
        if sub!={"ema":[50,200],"rsi":14}:
            raise ValueError("INVALID_DXY_INDICATORS")


def fractals_confirmed(bars:list[dict],left:int=2,right:int=2)->dict:
    """Last confirmed five-bar high/low; recorded at right-bar close, not pivot time."""
    result={"last_high":None,"last_low":None,"confirmation_lag_bars":right}
    for i in range(left,len(bars)-right):
        v=float(bars[i]["high"])
        if all(v>float(x["high"]) for x in bars[i-left:i]+bars[i+1:i+right+1]):
            result["last_high"]={"price":v,"pivot_at":bars[i]["bar_open_utc"],
                                 "confirmed_at":bars[i+right]["close_confirmed_at"]}
        v=float(bars[i]["low"])
        if all(v<float(x["low"]) for x in bars[i-left:i]+bars[i+1:i+right+1]):
            result["last_low"]={"price":v,"pivot_at":bars[i]["bar_open_utc"],
                                "confirmed_at":bars[i+right]["close_confirmed_at"]}
    return result


def classify_timeframe(bars:list[dict],cfg:dict,pc:dict,market_tf:dict|None,
                       context:dict|None,now:datetime,instrument:str="XAUUSD")->dict:
    """Compute ONLY indicators enabled in the TF profile. No synthetic trade signals."""
    enabled=pc["enabled"];closes=[float(b["close"]) for b in bars];cur=closes[-1]
    metrics={}; readings={"role":pc["role"],"market_direction":"UNKNOWN",
                         "trade_signal":"NONE","win_probability":None,"conflicts":[],
                         "evidence_groups":[],"no_double_counting":True}
    reg=(market_tf or {}).get("structure_regime","UNKNOWN") if instrument=="XAUUSD" else "UNKNOWN"
    if instrument=="XAUUSD" and (market_tf or {}).get("status") not in ("PASS","PASS_WITH_LIMITATIONS"):
        reg="UNKNOWN"
    readings["m02_structure_regime"]=reg
    readings["market_direction"]={"TREND_UP":"BULLISH","TREND_DOWN":"BEARISH","RANGE":"NEUTRAL"}.get(reg,"UNKNOWN")
    atrv=None
    if "atr" in enabled:
        av=atr(bars,enabled["atr"]);atrv=av[-1]
        metrics["atr_"+str(enabled["atr"])]=value(atrv,"price")
        median_data=[x for x in av[-(cfg["atr_baseline_bars"]+1):-1] if x is not None and x>0]
        ratio=atrv/statistics.median(median_data) if atrv is not None and len(median_data)==cfg["atr_baseline_bars"] else None
        metrics["atr_ratio_to_previous_median"]=value(ratio,"ratio")
        readings["volatility_context"]=("ATR_EXPANSION" if ratio is not None and ratio>=cfg["atr_high_ratio"] else
                                         "ATR_CONTRACTION" if ratio is not None and ratio<=cfg["atr_low_ratio"] else
                                         "ATR_STABLE" if ratio is not None else "UNKNOWN")
        readings["evidence_groups"].append("VOLATILITY")
    if "ema" in enabled:
        levels={n:ema(closes,n)[-1] for n in enabled["ema"]}
        for n,x in levels.items():metrics[f"ema_{n}"]=value(x,"price")
        known=all(x is not None for x in levels.values())
        seq=[levels[n] for n in enabled["ema"]]
        readings["ema_stack"]=("UP_STACK" if known and all(a>b for a,b in zip(seq,seq[1:])) and cur>seq[0]
                                else "DOWN_STACK" if known and all(a<b for a,b in zip(seq,seq[1:])) and cur<seq[0]
                                else "MIXED" if known else "UNKNOWN")
        closest=levels[enabled["ema"][0]]
        ext=(cur-closest)/atrv if closest is not None and atrv is not None and atrv>0 else None
        metrics["ema_fast_distance_atr"]=value(ext,"ATR_units")
        readings["ema_extension_context"]=("EXTENDED_FROM_EMA_NOT_REVERSAL_SIGNAL" if ext is not None and abs(ext)>=cfg["ema_extension_atr_threshold"] else
                                             "NOT_EXTENDED" if ext is not None else "UNKNOWN")
        readings["evidence_groups"].append("TREND_CONTEXT")
        if reg=="TREND_UP" and readings["ema_stack"]=="DOWN_STACK":readings["conflicts"].append("EMA_STACK_OPPOSES_M02_UPTREND")
        if reg=="TREND_DOWN" and readings["ema_stack"]=="UP_STACK":readings["conflicts"].append("EMA_STACK_OPPOSES_M02_DOWNTREND")
    if "adx_wilder" in enabled:
        n=enabled["adx_wilder"];a=adx(bars,n)
        for source,key in (("adx",f"adx_wilder_{n}"),("+di","plus_di"),("-di","minus_di")):
            metrics[key]=value(a[source][-1],"index")
        d=a["adx"][-1];pos=a["+di"][-1];neg=a["-di"][-1]
        readings["adx_strength"]="STRONG" if d is not None and d>=cfg["adx_trend_min"] else "WEAK_OR_RANGE" if d is not None else "UNKNOWN"
        readings["di_direction"]="UP" if pos is not None and neg is not None and pos>neg else "DOWN" if pos is not None and neg is not None and neg>pos else "UNKNOWN"
        if "TREND_CONTEXT" not in readings["evidence_groups"]:readings["evidence_groups"].append("TREND_CONTEXT")
    if "rsi" in enabled:
        n=enabled["rsi"];r=rsi(closes,n)[-1]
        metrics[f"rsi_{n}"]=value(r,"index")
        readings["rsi_context"]=("OVERBOUGHT_IN_UPTREND_NOT_AUTOMATIC_SHORT" if r is not None and r>=cfg["rsi_overbought"] and reg=="TREND_UP" else
                                  "OVERBOUGHT_CONTEXT_ONLY" if r is not None and r>=cfg["rsi_overbought"] else
                                  "OVERSOLD_IN_DOWNTREND_NOT_AUTOMATIC_LONG" if r is not None and r<=cfg["rsi_oversold"] and reg=="TREND_DOWN" else
                                  "OVERSOLD_CONTEXT_ONLY" if r is not None and r<=cfg["rsi_oversold"] else "RSI_MID_RANGE" if r is not None else "UNKNOWN")
        readings["evidence_groups"].append("MOMENTUM")
    if "macd" in enabled:
        m=enabled["macd"];a=macd(closes,m["fast"],m["slow"],m["signal"],m["signal_ma"])
        for k in ("line","signal","histogram"):
            metrics["macd_"+k]=value(a[k][-1],"price")
        h=a["histogram"][-1];prev=a["histogram"][-2] if len(bars)>1 else None
        readings["macd_histogram_cross"]=("MACD_POSITIVE_CROSS_CLOSED_BAR" if h is not None and prev is not None and prev<=0<h else
                                             "MACD_NEGATIVE_CROSS_CLOSED_BAR" if h is not None and prev is not None and prev>=0>h else
                                             "NO_NEW_CROSS" if h is not None and prev is not None else "UNKNOWN")
        if reg=="TREND_UP" and h is not None and h<0:readings["conflicts"].append("MACD_MOMENTUM_COUNTER_TREND_UP")
        if reg=="TREND_DOWN" and h is not None and h>0:readings["conflicts"].append("MACD_MOMENTUM_COUNTER_TREND_DOWN")
        if "MOMENTUM" not in readings["evidence_groups"]:readings["evidence_groups"].append("MOMENTUM")
        readings["macd_signal_ma"]="SMA"
    if "bollinger" in enabled:
        bb_cfg=enabled["bollinger"];b=bb(closes,bb_cfg["period"],bb_cfg["std_mult"])
        for key in ("mid","upper","lower","percent_b","bandwidth"):
            metrics["bb_"+key]=value(b[key],"ratio" if key in ("percent_b","bandwidth") else "price")
        readings["bollinger_context"]=("ABOVE_UPPER_BAND_NOT_AUTOMATIC_BUY" if b["upper"] is not None and cur>b["upper"] else
                                         "BELOW_LOWER_BAND_NOT_AUTOMATIC_SELL" if b["lower"] is not None and cur<b["lower"] else
                                         "INSIDE_BANDS" if b["mid"] is not None else "UNKNOWN")
        if "VOLATILITY" not in readings["evidence_groups"]:readings["evidence_groups"].append("VOLATILITY")
    if enabled.get("tick_volumes"):
        latest=bars[-1].get("tick_volume")
        recent=[b.get("tick_volume") for b in bars[-21:-1]]
        ratio=(float(latest)/statistics.median(recent) if num(latest) and len(recent)==20 and all(num(x) and x>0 for x in recent) else None)
        metrics["tick_volume_current"]=value(float(latest) if num(latest) else None,"broker_tick_count",kind="BROKER_TICK_VOLUME_PROXY")
        metrics["tick_volume_ratio_20_median"]=value(ratio,"ratio",kind="BROKER_TICK_VOLUME_PROXY")
        readings["evidence_groups"].append("PARTICIPATION_PROXY")
    if enabled.get("obv"):
        metrics["obv_tick"]=value(obv(bars),"broker_tick_volume_units",kind="BROKER_TICK_VOLUME_PROXY")
    if enabled.get("session_vwap"):
        metrics["session_vwap"]=session_vwap(bars,context,cfg,now)
    if enabled.get("fractals"):
        readings["confirmed_fractals"]=fractals_confirmed(bars)
    # Every instrument needs signed trade data for actual CVD: never synthesize it.
    readings["cvd_status"]="UNAVAILABLE_WITHOUT_SIGNED_TRADES"
    readings["correlation_warning"]="RELATED_INDICATORS_ARE_NOT_INDEPENDENT_VOTES"
    readings["indicator_parameters"]={"enabled":enabled,"adx_variant":"WILDER","closed_bars_only":True}
    return {"indicators":metrics,"interpretation":readings,
            "profile_role":pc["role"],"enabled_indicators":list(enabled)}


def analyze_dxy(snapshot:dict,cfg:dict,now:datetime)->dict:
    """Optional, never permitted to override XAU broker quote or execution gate."""
    a=cfg["auxiliary_instruments"]["DXY"]
    source=snapshot.get("auxiliary_candles_by_instrument",{}).get("DXY",{})
    barlist=source.get("H1",[]) if isinstance(source,dict) else []
    if not barlist:
        return {"status":"UNAVAILABLE","required_for_xau_direction":False,
                "reason_codes":["DXY_NOT_AVAILABLE_IN_MT5"],"timeframe":"H1","indicators":{},"interpretation":None}
    bars,issues=prepare(snapshot,"H1",cfg,instrument_id="DXY",source_bars=barlist)
    if any(k in SEVERE for k in issues):
        return {"status":"FAIL","required_for_xau_direction":False,"timeframe":"H1",
                "reason_codes":issues,"indicators":{},"interpretation":None}
    if not bars:
        return {"status":"PENDING","required_for_xau_direction":False,"timeframe":"H1",
                "reason_codes":issues,"indicators":{},"interpretation":None}
    pc={"role":"USD_CONTEXT_FILTER_ONLY","enabled":a["indicators"],"min_closed_bars":230}
    result=classify_timeframe(bars,cfg,pc,None,None,now,"DXY")
    result.update({"status":"PENDING","timeframe":"H1","closed_bars":len(bars),
                   "reason_codes":sorted(set(issues+["AUXILIARY_M01_M04_CONTEXT_NOT_AUDITED"])),
                   "required_for_xau_direction":False,"execution_quote_allowed":False,
                   "last_closed_at":bars[-1]["close_confirmed_at"]})
    return result


def analyze(packet:dict,cfg:dict)->dict:
    profile_check(cfg)
    snapshot=packet.get("data_snapshot",packet)
    if not isinstance(snapshot,dict):raise ValueError("INVALID_SNAPSHOT")
    now=utc(snapshot["as_of"])
    market=packet.get("market_state")
    context=packet.get("session_context")
    reasons=[];missing=[]
    if snapshot.get("data_source_policy")!=POLICY or snapshot.get("visual_capture_enabled",False) is not False:
        reasons.append("SOURCE_POLICY_MISMATCH")
    if not snapshot.get("snapshot_id") or not snapshot.get("analysis_id"):
        reasons.append("SNAPSHOT_ID_MISSING")
    gates=snapshot.get("data_gates")
    if not isinstance(gates,list) or not gates:
        reasons.append("M01_DATA_GATES_MISSING")
    else:
        for g in gates:
            if not isinstance(g,dict):reasons.append("INVALID_M01_GATE");continue
            if set(g.get("required_for",[]))&{"ANALYSIS","DIRECTION"}:
                if g.get("status")=="FAIL":reasons.append("M01_ANALYSIS_OR_DIRECTION_GATE_FAIL")
                elif g.get("status") not in ("PASS","PASS_WITH_LIMITATIONS"):
                    reasons.append("M01_ANALYSIS_OR_DIRECTION_GATE_PENDING")
    matching=True
    if isinstance(market,dict):
        if (market.get("snapshot_id")!=snapshot.get("snapshot_id") or utc(market["as_of"])!=now or
            market.get("analysis_id")!=snapshot.get("analysis_id")):
            reasons.append("M02_SNAPSHOT_MISMATCH"); matching=False
        upstream_status=market.get("analysis_gate",{}).get("status")
        if upstream_status not in ("PASS","PASS_WITH_LIMITATIONS"):
            reasons.append("M02_ANALYSIS_GATE_FAIL" if upstream_status=="FAIL" else "M02_ANALYSIS_GATE_PENDING");matching=False
    else:
        reasons.append("M02_CONTEXT_NOT_AVAILABLE");matching=False
    timeframes={};critical=False;statuses=[]
    for tf in cfg["timeframes"]:
        if tf not in TIMEFRAMES:raise ValueError("UNSUPPORTED_TF")
        bars,issues=prepare(snapshot,tf,cfg)
        tf_state=(market.get("timeframes",{}).get(tf) if matching else None)
        tf_context=(context if isinstance(context,dict) and context.get("timeframe")==tf
                    and context.get("snapshot_id")==snapshot.get("snapshot_id")
                    and context.get("as_of")==snapshot.get("as_of") else None)
        if not bars:
            per={"status":"FAIL" if any(k in SEVERE for k in issues) else "PENDING",
                 "closed_bars":0,"last_closed_at":None,"indicators":{},"interpretation":None}
        else:
            per=(classify_timeframe(bars,cfg,cfg["timeframe_profiles"][tf],tf_state,tf_context,now)
                 if "timeframe_profiles" in cfg else classify(bars,cfg,tf_state,tf_context,now))
            per.update({"status":"PASS_WITH_LIMITATIONS" if issues and len(bars)>=cfg.get("timeframe_profiles",{}).get(tf,{}).get("min_closed_bars",cfg["min_closed_bars"]) else
                        "PASS" if len(bars)>=cfg.get("timeframe_profiles",{}).get(tf,{}).get("min_closed_bars",cfg["min_closed_bars"]) else "PENDING",
                        "closed_bars":len(bars),"last_closed_at":bars[-1]["close_confirmed_at"]})
            if len(bars)<cfg.get("timeframe_profiles",{}).get(tf,{}).get("min_closed_bars",cfg["min_closed_bars"]):issues.append("INSUFFICIENT_CLOSED_BARS")
            if matching and (not isinstance(tf_state,dict) or
                             tf_state.get("last_closed_at")!=bars[-1]["close_confirmed_at"] or
                             tf_state.get("status") not in ("PASS","PASS_WITH_LIMITATIONS")):
                issues.append("M02_TF_SNAPSHOT_OUT_OF_SYNC")
                per["status"]="PENDING"
                per["interpretation"]["m02_structure_regime"]="UNKNOWN"
                per["interpretation"]["market_direction"]="UNKNOWN"
        if any(k in SEVERE for k in issues):critical=True
        per.update({"timeframe":tf,"reason_codes":sorted(set(issues)),
                    "price_basis":cfg["price_basis_allowed"],
                    "evidence_ids":[b["evidence_id"] for b in bars[-5:]],
                    "source_series_hash":hashlib.sha256(json.dumps([(b["bar_open_utc"],b["open"],b["high"],b["low"],b["close"],b.get("tick_volume")) for b in bars],separators=(",", ":")).encode()).hexdigest() if bars else None})
        timeframes[tf]=per;statuses.append(per["status"])
        if per["status"]!="PASS":missing.append(tf)
    blocking={"M01_ANALYSIS_OR_DIRECTION_GATE_FAIL","SOURCE_POLICY_MISMATCH","M02_SNAPSHOT_MISMATCH",
              "M02_ANALYSIS_GATE_FAIL","SNAPSHOT_ID_MISSING","INVALID_M01_GATE"}
    status="FAIL" if critical or any(x in blocking for x in reasons) else (
        "PENDING" if any(x not in ("PASS","PASS_WITH_LIMITATIONS") for x in statuses)
           or "M01_DATA_GATES_MISSING" in reasons or "M01_ANALYSIS_OR_DIRECTION_GATE_PENDING" in reasons or not matching else
        "PASS_WITH_LIMITATIONS" if any(x=="PASS_WITH_LIMITATIONS" for x in statuses) else "PASS")
    return {"module_id":"M02I","module_version":VERSION,"schema_version":"2.0.0",
            "prompt_version":"4.1.0","analysis_id":snapshot.get("analysis_id"),
            "snapshot_id":snapshot.get("snapshot_id"),"as_of":now.isoformat(),"instrument_id":"XAUUSD",
            "profile_id":cfg["profile_id"],"config_version":cfg["config_version"],
            "feature_spec_id":cfg["feature_spec_id"],"status":status,"run_status":"COMPLETED",
            "reason_codes":sorted(set(reasons)),"missing_inputs":sorted(set(missing)),
            "timeframes":timeframes,"auxiliary_instruments":({"DXY":analyze_dxy(snapshot,cfg,now)} if "DXY" in cfg.get("auxiliary_instruments",{}) else {}),
            "analysis_gate":{"status":status,"required_for":["ANALYSIS","DIRECTION"]},
            "execution_context_gate":{"status":"BLOCKED","required_for":["EXECUTION"],
                "reason_codes":["M02I_HAS_NO_EXECUTION_AUTHORITY"]},
            "execution_permission":"BLOCKED","live_execution_allowed":False,
            "submitted_order_id":None,"probability_status":"NOT_AVAILABLE",
            "indicator_quality_rubric":"PROVISIONAL_RESEARCH_NO_EMPIRICAL_WEIGHTING",
            "market_data_source_policy":POLICY,"visual_capture_enabled":False,
            "account_profile":"ZERO_SPREAD_DECLARED_BROKER_COSTS_MUST_BE_VERIFIED",
            "limitations":["NO_TRADING_EDGE_VALIDATION","NO_AUTONOMOUS_ORDER_EXECUTION",
                           "M01_M02_INTEGRATION_NOT_YET_TESTED_LIVE","NO_TRUE_CVD_WITHOUT_SIGNED_TRADES",
                           "NOT_A_STRATEGY_OR_ENTRY_TRIGGER"]}


def main(argv:list[str]|None=None)->int:
    ap=argparse.ArgumentParser(description="M02I read-only MT5 indicator interpretation on M01 JSONL snapshots")
    ap.add_argument("--input",default="-",help="JSONL packet(s); '-' stdin")
    ap.add_argument("--profile",default=str(Path(__file__).with_name("M02I_PROFILE_MT5_TIMEFRAMES_v1.1.json")))
    ns=ap.parse_args(argv)
    cfg=json.loads(Path(ns.profile).read_text(encoding="utf-8"))
    inp=sys.stdin if ns.input=="-" else open(ns.input,encoding="utf-8")
    try:
        for line in inp:
            if not line.strip():continue
            try:
                result=analyze(json.loads(line),cfg)
                print(json.dumps(result,ensure_ascii=False,allow_nan=False))
            except Exception as exc:
                print(json.dumps({"module_id":"M02I","status":"FAIL","run_status":"FAILED",
                                  "reason_codes":[str(exc)],"execution_permission":"BLOCKED",
                                  "live_execution_allowed":False,"submitted_order_id":None}),flush=True)
    finally:
        if inp is not sys.stdin:inp.close()
    return 0

if __name__=="__main__":raise SystemExit(main())
