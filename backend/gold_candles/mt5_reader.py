from __future__ import annotations

from .data import Config, DataError, utc, validate_bars
import pandas as pd


def require_utc_server(tick_time_msc,now,grid_s=900,tolerance_s=90.0):
    """1.46: MT5 bar / tick epochs are the broker SERVER wall clock (masterquo/mt5/clock.py), not UTC. This reference reader converts
    nothing, so it reads only when the newest tick puts the server on UTC: the tick-minus-UTC difference rounded to the 15-minute time
    zone grid (as the bot's ServerClock) must be 0 h within `tolerance_s`. Otherwise DataError with the reason - never shifted bars."""
    delta=float(tick_time_msc)/1000.0-pd.Timestamp(now).timestamp()
    grid=round(delta/grid_s)*grid_s
    if abs(delta-grid)>tolerance_s:
        raise DataError(f"MT5_SERVER_TIME_OFFSET_UNVERIFIED: ostatni tick odbiega od siatki stref czasu o {delta-grid:+.0f} s (stary tick / "
                        "rynek zamknięty / zegar PC) – czasu serwera nie da się potwierdzić; użyj eksportu bota (11_EKSPORT_HISTORII_XAUUSD.bat)")
    if grid!=0:
        raise DataError(f"MT5_SERVER_TIME_NOT_UTC: czas ticka różni się od UTC o {grid/3600:+g} h (serwer brokera poza UTC albo rynek "
                        "zamknięty) – referencyjny czytnik nie przelicza czasu serwera; użyj eksportu bota (11_EKSPORT_HISTORII_XAUUSD.bat)")


def read_mt5(symbol="XAUUSD-",count=3000):
    """Uses the user's already-open Windows terminal, without credentials/orders."""
    Config(symbol=symbol)
    try:
        import MetaTrader5 as mt5
    except ImportError as error:
        raise DataError("MT5_SDK_NOT_INSTALLED_WINDOWS_REQUIRED_FOR_MT5") from error
    if not mt5.initialize():
        raise DataError(f"MT5_INITIALIZE_FAILED:{mt5.last_error()}")
    try:
        info=mt5.symbol_info(symbol)
        if info is None:
            raise DataError("EXACT_BROKER_SYMBOL_NOT_FOUND")
        if not info.visible and not mt5.symbol_select(symbol,True):
            raise DataError("SYMBOL_SELECT_FAILED")
        name=str(getattr(info,"name","") or symbol).upper()
        cfd_gold=info.currency_base==info.currency_profit=="USD" and ("XAUUSD" in name or "GOLD" in name) and "XAUT" not in name  # CFD brokers report base=USD
        if not (info.currency_base=="XAU" and info.currency_profit=="USD") and not cfd_gold:
            raise DataError("BROKER_SYMBOL_NOT_CONFIRMED_AS_XAU_USD")
        tick_size=float(info.trade_tick_size)
        if tick_size<=0 or info.trade_contract_size<=0:
            raise DataError("BROKER_CONTRACT_SPECIFICATION_INVALID")
        # Position 0 is the current bar. Epochs are used unshifted only from a server verified to run on UTC (require_utc_server).
        r5=mt5.copy_rates_from_pos(symbol,mt5.TIMEFRAME_M5,1,count)
        r30=mt5.copy_rates_from_pos(symbol,mt5.TIMEFRAME_M30,1,max(350,count//6))
        tick=mt5.symbol_info_tick(symbol)
        now=utc()
        if r5 is None or r30 is None or tick is None:
            raise DataError(f"MT5_READ_FAILED:{mt5.last_error()}")
        # 1.46: a UTC+2/+3 server gave FUTURE_BAR_OPEN_TIMESTAMP and a negative tick age, a server behind UTC silently shifted every
        # bar into the past (the epochs were taken for UTC) - now the server time is checked first and any other offset is BLOCKED
        require_utc_server(tick.time_msc,now)
        m5=validate_bars(pd.DataFrame(r5),5,now,symbol)
        m30=validate_bars(pd.DataFrame(r30),30,now,symbol)
        tick_time=pd.Timestamp(tick.time_msc,unit="ms",tz="UTC")
        age=float((now-tick_time).total_seconds())
        quote=dict(bid=float(tick.bid),ask=float(tick.ask),
                   time_utc=tick_time.isoformat(),age_seconds=age,
                   valid=bool(0<=age<=2 and 0<tick.bid<=tick.ask))
        config=Config(symbol=symbol,tick_size=tick_size)
        return m5,m30,config,quote,now
    finally:
        mt5.shutdown()

