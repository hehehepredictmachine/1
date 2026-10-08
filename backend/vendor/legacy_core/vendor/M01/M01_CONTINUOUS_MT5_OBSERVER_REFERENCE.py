"""MasterQUO M01 read-only reference observer for MetaTrader 5.

Runs on Windows with MetaTrader 5 terminal and `pip install MetaTrader5`.
No screenshot/OCR, no TradingView scraping, no orders, no trading signals.
Emits normalized quote/bar/health events to STDOUT JSONL; optional file mirror.
This is a reference acquisition layer, NOT a production MT5 feed/complete M01.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import math
import pathlib
import sys
import time
from typing import Any

UTC = dt.timezone.utc
TF_NAMES = ("D1", "H4", "H1", "M15", "M5", "M1")

def timestamp() -> str:
    return dt.datetime.now(tz=UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")

def unix_time(value: Any) -> str:
    return dt.datetime.fromtimestamp(float(value), tz=UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")

def as_python(value: Any) -> Any:
    if hasattr(value, 'item'): return value.item()
    return value

class Observer:
    """Polls one live MT5 terminal; each source is broker-identified.

    `mt5` is dependency-injected to permit isolated tests without installed MT5.
    """
    def __init__(self, mt5: Any, symbol: str, bar_symbols: dict[str,list[str]],
                 quote_interval_s: float, bar_interval_s: float, emit,
                 heartbeat_s: float=10.0):
        if quote_interval_s <= 0 or bar_interval_s <= 0 or heartbeat_s <= 0:
            raise ValueError('interval must be > 0')
        self.mt5 = mt5
        self.symbol = symbol
        self.bar_symbols = bar_symbols
        self.quote_interval_s = quote_interval_s
        self.bar_interval_s = bar_interval_s
        self.heartbeat_s = heartbeat_s
        self.emit = emit
        self.last_quote_key = None
        self.last_bar_data = {}  # (symbol,tf,bar_time) -> fingerprint
        self.last_open = {}      # (symbol,tf) -> latest forming bar open
        self.status = 'CONNECTING'
        self.connected = False
        self.terminal_path = None
        self.last_health_reason = None

    def event(self, kind: str, **data):
        self.emit({'module_id':'M01', 'event_type':kind,
                   'received_at':timestamp(), 'source':'MT5_TERMINAL', **data})

    def connect(self, terminal_path: str | None):
        self.terminal_path = terminal_path
        if terminal_path and not pathlib.Path(terminal_path).is_file():
            raise FileNotFoundError(f'Nie ma pliku terminala: {terminal_path}')
        # MT5 Python API accepts the path as first positional parameter.
        ok = self.mt5.initialize(terminal_path) if terminal_path else self.mt5.initialize()
        if not ok:
            self.status = 'DISCONNECTED'
            self.connected = False
            self.event('data_degraded', status=self.status, reason='MT5_INITIALIZE_FAILED',
                       api_error=str(self.mt5.last_error()))
            return False
        info = self.mt5.terminal_info()
        if info is None or not bool(getattr(info, 'connected', False)):
            self.mt5.shutdown()
            self.connected = False
            self.status = 'DISCONNECTED'
            self.event('data_degraded', status=self.status, reason='TERMINAL_NOT_CONNECTED')
            return False
        for sym in self.bar_symbols:
            if self.mt5.symbol_info(sym) is None or not self.mt5.symbol_select(sym, True):
                if sym == self.symbol:
                    self.status = 'DISCONNECTED'
                    self.event('data_degraded', status=self.status, reason='XAU_SYMBOL_UNAVAILABLE', symbol=sym)
                    self.mt5.shutdown()
                    return False
                self.event('auxiliary_unavailable', symbol=sym, reason='SYMBOL_NOT_AVAILABLE_IN_TERMINAL')
        self.status = 'HEALTHY'
        self.connected = True
        self.last_quote_key = None
        self.event('source_recovered', status=self.status, symbol=self.symbol)
        return True

    def close(self):
        if self.connected:
            self.mt5.shutdown()
        self.connected = False
        self.status='DISCONNECTED'

    def check_quote(self):
        tick = self.mt5.symbol_info_tick(self.symbol)
        if tick is None:
            self.status = 'DEGRADED'
            if self.last_health_reason != 'QUOTE_UNAVAILABLE':
                self.event('data_degraded', reason='QUOTE_UNAVAILABLE', status=self.status)
                self.last_health_reason = 'QUOTE_UNAVAILABLE'
            return
        bid, ask = float(tick.bid), float(tick.ask)
        if not all(map(math.isfinite,(bid,ask))) or bid <= 0 or ask < bid:
            self.status='DEGRADED'
            self.event('data_degraded', reason='INVALID_BID_ASK', status=self.status)
            return
        epoch_msc = int(getattr(tick, 'time_msc', 0) or int(tick.time * 1000))
        key=(epoch_msc, bid, ask, int(getattr(tick,'flags',0)))
        self.last_health_reason = None
        if key != self.last_quote_key:
            self.last_quote_key = key
            self.event('quote_updated', instrument_id='XAUUSD', symbol=self.symbol,
                       bid=bid, ask=ask, spread_abs=round(ask-bid,10),
                       source_timestamp=unix_time(epoch_msc/1000.0),
                       evidence_status='VERIFIED', source_quality='MT5_BROKER')

    def check_bars(self):
        for sym, names in self.bar_symbols.items():
            if self.mt5.symbol_info(sym) is None:
                self.event('auxiliary_unavailable', symbol=sym, reason='SYMBOL_NOT_AVAILABLE_IN_TERMINAL')
                continue
            for tf in names:
                mt5_tf = getattr(self.mt5,'TIMEFRAME_'+tf,None)
                if mt5_tf is None:
                    self.event('data_degraded', symbol=sym, timeframe=tf, reason='TIMEFRAME_UNSUPPORTED')
                    continue
                rates=self.mt5.copy_rates_from_pos(sym, mt5_tf, 0, 3)
                if rates is None or len(rates) == 0:
                    self.event('data_degraded',symbol=sym,timeframe=tf,reason='BARS_UNAVAILABLE')
                    continue
                # MT5 returns oldest->newest in typical Python results; sort regardless.
                rows=sorted(rates,key=lambda b:int(b['time']))
                current=rows[-1]
                current_open=int(current['time'])
                sf=(sym,tf)
                previous_open=self.last_open.get(sf)
                if previous_open is not None and current_open != previous_open:
                    # Close only on confirmed appearance of a newer source bar.
                    match=next((b for b in rows if int(b['time'])==previous_open),None)
                    if match is not None:
                        self.emit_bar('candle_closed',sym,tf,match,'CLOSED',close_confirmed_at=timestamp())
                    else:
                        self.event('data_gap',symbol=sym,timeframe=tf,reason='PREVIOUS_BAR_MISSING_FROM_WINDOW')
                # First poll never emits a fake real-time candle_closed event.
                self.last_open[sf]=current_open
                self.emit_bar('candle_updated',sym,tf,current,'FORMING')
                # Bound the in-memory dedupe cache during long-running monitoring.
                keys_for_tf=sorted({k[3] for k in self.last_bar_data if k[1]==sym and k[2]==tf})
                for obsolete_open in keys_for_tf[:-4]:
                    for k in list(self.last_bar_data):
                        if k[1]==sym and k[2]==tf and k[3]==obsolete_open:
                            del self.last_bar_data[k]

    def emit_bar(self,kind,symbol,tf,row,state,**extra):
        fields=('open','high','low','close')
        p={f:float(as_python(row[f])) for f in fields}
        if not all(math.isfinite(v) and v>0 for v in p.values()) or not(p['low']<=min(p['open'],p['close'])<=max(p['open'],p['close'])<=p['high']):
            self.event('data_degraded',symbol=symbol,timeframe=tf,reason='INVALID_OHLC')
            return
        bar_time=int(as_python(row['time']))
        fingerprint=(state,bar_time,*[p[f] for f in fields],int(as_python(row['tick_volume'])))
        k=(kind,symbol,tf,bar_time)
        if self.last_bar_data.get(k)==fingerprint: return
        self.last_bar_data[k]=fingerprint
        self.event(kind,instrument_id='XAUUSD' if symbol==self.symbol else symbol,
                   symbol=symbol,timeframe=tf,bar_state=state,
                   bar_open_utc=unix_time(bar_time),**p,
                   tick_volume=int(as_python(row['tick_volume'])),
                   real_volume=float(as_python(row['real_volume'])) if 'real_volume' in row.dtype.names else None,
                   source_timestamp=unix_time(bar_time), **extra)

    def cycle(self,now:float,last_quote:float,last_bars:float,last_heartbeat:float):
        if now-last_quote>=self.quote_interval_s:
            self.check_quote(); last_quote=now
        if now-last_bars>=self.bar_interval_s:
            self.check_bars(); last_bars=now
        if now-last_heartbeat>=self.heartbeat_s:
            self.event('heartbeat',process_alive=True,adapter_status=self.status,
                       note='HEARTBEAT_DOES_NOT_PROVE_MARKET_FRESHNESS')
            last_heartbeat=now
        return last_quote,last_bars,last_heartbeat

    def run(self,seconds:float|None=None):
        last_quote=last_bars=last_heartbeat=float('-inf')
        start=time.monotonic()
        while seconds is None or time.monotonic()-start<seconds:
            now=time.monotonic()
            try:
                last_quote,last_bars,last_heartbeat=self.cycle(now,last_quote,last_bars,last_heartbeat)
            except Exception as exc:
                self.status='DEGRADED'
                self.event('data_degraded',status=self.status,reason='MT5_READ_ERROR',detail=str(exc))
                # No screenshot fallback. A supervisor handles reconnection.
            time.sleep(min(self.quote_interval_s,self.bar_interval_s,0.1))

def main(argv=None):
    a=argparse.ArgumentParser(description='Read-only MT5 continuous XAUUSD candle/tick observer; no screenshots')
    a.add_argument('--terminal-path', default=None,help='Complete path to terminal64.exe / terminal.exe on Windows')
    a.add_argument('--symbol',required=True,help='Exact validated broker XAUUSD symbol')
    a.add_argument('--dxy-symbol',default=None,help='Optional exact MT5 symbol with DXY H1 (if provided by broker)')
    a.add_argument('--quote-poll-ms',type=int,default=500)
    a.add_argument('--bar-poll-ms',type=int,default=1000)
    a.add_argument('--output-jsonl',default=None)
    a.add_argument('--duration-seconds',type=float,default=None,help='Demo only, default run until Ctrl+C')
    args=a.parse_args(argv)
    if args.quote_poll_ms<100 or args.bar_poll_ms<100:
        a.error('minimum 100ms; this is a reference, not low-latency production feed')
    try:
        import MetaTrader5 as mt5
    except ImportError:
        a.error('MetaTrader5 Python package not installed; run on Windows with MT5 terminal')
    stream=open(args.output_jsonl,'a',encoding='utf8',buffering=1) if args.output_jsonl else None
    def emit(evt):
        line=json.dumps(evt,ensure_ascii=False,allow_nan=False)
        print(line,flush=True)
        if stream: stream.write(line+'\n')
    symbols={args.symbol:list(TF_NAMES)}
    if args.dxy_symbol and args.dxy_symbol != args.symbol: symbols[args.dxy_symbol]=['H1']
    ob=Observer(mt5,args.symbol,symbols,args.quote_poll_ms/1000,args.bar_poll_ms/1000,emit)
    try:
        if not ob.connect(args.terminal_path): return 2
        ob.run(args.duration_seconds)
        return 0
    except KeyboardInterrupt:
        return 130
    finally:
        ob.close()
        if stream: stream.close()

if __name__=='__main__': sys.exit(main())
