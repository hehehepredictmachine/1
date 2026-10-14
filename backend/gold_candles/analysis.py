from __future__ import annotations

from .data import Config, DataError, clean_json, closed_snapshot_id, utc
from .patterns import latest_patterns
from .model import forecast


def analyze(m5,m30=None,config=Config(),model=None,as_of=None,mode="REPLAY",quote=None):
    now=utc(as_of)
    for frame in (m5,m30):
        if frame is not None and (frame.time_close_utc>now).any():
            raise DataError("SNAPSHOT_CONTAINS_BARS_NOT_CLOSED_AT_AS_OF")
    if mode not in ("REPLAY","LIVE","SYNTHETIC_DEMO"):
        raise ValueError("UNKNOWN_ANALYSIS_MODE")
    age=float((now-m5.time_close_utc.iloc[-1]).total_seconds())
    reasons=["STRATEGY_PNL_VALIDATION_NOT_IMPLEMENTED_IN_CANDLE_MODULE",
             "BROKER_RISK_ORDER_AND_CALENDAR_GATES_NOT_CONNECTED"]
    if mode=="LIVE" and (age<0 or age>=330):
        predicted=dict(status="STALE_M5_DATA",probabilities=None,execution_permission=False)
        reasons.append("STALE_M5_DATA")
    else:
        predicted=forecast(m5,m30,config,model)
    if model is None:
        reasons.append("NO_TRAINED_FORECAST_MODEL")
    if mode!="LIVE":
        reasons.append("NOT_A_LIVE_EXECUTION_SNAPSHOT")
    if quote is None or not quote.get("valid",False):
        reasons.append("EXECUTABLE_QUOTE_UNKNOWN_OR_STALE")
    result=dict(module_version="2.0.0",symbol=config.symbol,mode=mode,
                snapshot_id=closed_snapshot_id(m5,m30,config),
                observed_at_utc=now.isoformat(),last_m5_close_utc=m5.time_close_utc.iloc[-1].isoformat(),
                data_age_seconds=age,chart_close=float(m5.close.iloc[-1]),quote=quote,
                candle_analysis=dict(M5=latest_patterns(m5,config),
                    M30=latest_patterns(m30,config) if m30 is not None else None),
                forecast=predicted,
                execution_lock=dict(state="BLOCKED",can_submit_order=False,reasons=reasons),
                limits="This module does not implement the full strategy, send orders or prove profitability.")
    return clean_json(result)

