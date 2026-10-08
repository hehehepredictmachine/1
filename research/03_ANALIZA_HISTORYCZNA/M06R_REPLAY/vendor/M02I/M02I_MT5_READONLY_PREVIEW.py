"""Optional Windows MT5 preview for M02I.

READ ONLY: fetches CLOSED MT5 candles, calls NO trade/order APIs, never sets M01 gates PASS.
No M02 market_state -> diagnostic indicator values but global status PENDING (expected).
Production must use validated M01 DATA_SNAPSHOT and actual M02 MARKET_STATE.
"""
from __future__ import annotations
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from M02I_INDICATOR_ENGINE import analyze, POLICY

TF_NAMES=("D1","H4","H1","M15","M5","M1")
MINUTES={"M1":1,"M5":5,"M15":15,"H1":60,"H4":240,"D1":1440}


def row_dict(r):
    if hasattr(r,'_asdict'):return r._asdict()
    if hasattr(r,'dtype') and getattr(r.dtype,'names',None):return {k:r[k].item() if hasattr(r[k],'item') else r[k] for k in r.dtype.names}
    if isinstance(r,dict):return dict(r)
    raise ValueError('INVALID_MT5_BAR_ROW')


def iso_sec(s):return datetime.fromtimestamp(int(s),timezone.utc).isoformat()


def preview_snapshot(mt5, symbol:str='XAUUSD', count:int=260, now:datetime|None=None,
                     dxy_symbol:str|None=None)->dict:
    if not isinstance(symbol,str) or not symbol or any(ord(x)<32 for x in symbol):
        raise ValueError('INVALID_SYMBOL')
    if not isinstance(count,int) or count<205 or count>2000:
        raise ValueError('BAR_COUNT_MUST_BE_205_TO_2000')
    if dxy_symbol is not None and (not isinstance(dxy_symbol,str) or not dxy_symbol.strip() or any(ord(x)<32 for x in dxy_symbol)):
        raise ValueError('INVALID_DXY_SYMBOL')
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:raise ValueError('NOW_TIMEZONE_REQUIRED')
    as_of=now.astimezone(timezone.utc).isoformat()
    tfmap={'M1':mt5.TIMEFRAME_M1,'M5':mt5.TIMEFRAME_M5,'M15':mt5.TIMEFRAME_M15,
           'H1':mt5.TIMEFRAME_H1,'H4':mt5.TIMEFRAME_H4,'D1':mt5.TIMEFRAME_D1}
    by_tf={};reasons=[]
    for tf in TF_NAMES:
        rates=mt5.copy_rates_from_pos(symbol,tfmap[tf],0,count+1)
        if rates is None or len(rates)<2:
            by_tf[tf]=[]; reasons.append('MT5_NOT_ENOUGH_BARS:'+tf);continue
        # Ascending time, last record is bar0 (forming); require its existence.
        records=sorted((row_dict(x) for x in rates),key=lambda x:int(x['time']))
        bars=[]
        for i in range(len(records)-1):
            b=records[i];nextbar=records[i+1]
            if int(nextbar['time'])<=int(b['time']):
                reasons.append('NON_MONOTONIC_MT5_BARS:'+tf);bars=[];break
            if datetime.fromtimestamp(int(nextbar['time']),timezone.utc)>now:
                reasons.append('FUTURE_CLOSED_BAR_EXCLUDED:'+tf);continue
            bars.append({'instrument_id':'XAUUSD','exact_symbol':symbol,
                'source_id':'MT5_READONLY_PREVIEW_UNVERIFIED','timeframe':tf,'bar_state':'CLOSED',
                'bar_open_utc':iso_sec(b['time']),'close_confirmed_at':iso_sec(nextbar['time']),
                'available_at':as_of,'price_basis':'BID',
                'open':float(b['open']),'high':float(b['high']),'low':float(b['low']),'close':float(b['close']),
                'tick_volume':int(b['tick_volume']) if b.get('tick_volume') is not None else None,
                'real_volume':float(b.get('real_volume',0)),
                'evidence_id':f'MT5_PREVIEW:{symbol}:{tf}:{int(b["time"])}','revision':0})
        by_tf[tf]=bars
    auxiliary={}
    if dxy_symbol:
        # Explicit broker symbol only; NEVER infer DXY from an unrelated USD pair.
        dxy_rates=mt5.copy_rates_from_pos(dxy_symbol,tfmap['H1'],0,count+1)
        dxy_bars=[]
        if dxy_rates is None or len(dxy_rates)<2:
            reasons.append('MT5_DXY_NOT_ENOUGH_BARS_OR_UNAVAILABLE')
        else:
            dxy_rows=sorted((row_dict(x) for x in dxy_rates),key=lambda x:int(x['time']))
            for i in range(len(dxy_rows)-1):
                b,nxt=dxy_rows[i],dxy_rows[i+1]
                if int(nxt['time'])<=int(b['time']):
                    dxy_bars=[];reasons.append('MT5_DXY_NON_MONOTONIC');break
                if datetime.fromtimestamp(int(nxt['time']),timezone.utc)>now:continue
                dxy_bars.append({'instrument_id':'DXY','exact_symbol':dxy_symbol,
                    'source_id':'MT5_READONLY_PREVIEW_UNVERIFIED','timeframe':'H1','bar_state':'CLOSED',
                    'bar_open_utc':iso_sec(b['time']),'close_confirmed_at':iso_sec(nxt['time']),
                    'available_at':as_of,'price_basis':'BID',
                    'open':float(b['open']),'high':float(b['high']),'low':float(b['low']),
                    'close':float(b['close']), 'tick_volume':int(b['tick_volume']) if b.get('tick_volume') is not None else None,
                    'real_volume':float(b.get('real_volume',0)),
                    'evidence_id':f'MT5_PREVIEW:{dxy_symbol}:H1:{int(b["time"])}','revision':0})
        auxiliary={'DXY':{'H1':dxy_bars}}
    return {'_preview_only':True,'analysis_id' :'READONLY-MT5-PREVIEW','snapshot_id':'READONLY-MT5-PREVIEW:'+as_of,
       'as_of':as_of,'instrument_id':'XAUUSD','exact_symbol':symbol,
       'data_source_policy':POLICY,'visual_capture_enabled':False,
       'data_gates':[{'gate_id':'M01_NOT_RUN_PREVIEW_ONLY','required_for':['ANALYSIS','DIRECTION'],
                      'status':'PENDING','reason_codes':['M01_VALIDATION_NOT_EXECUTED']}],
       'candles_by_tf':by_tf,'auxiliary_candles_by_instrument':auxiliary,
       'preview_reasons':reasons,'account_profile':'ZERO_SPREAD_DECLARED_UNVERIFIED'}


def main():
    ap=argparse.ArgumentParser(description='READ-ONLY local MT5 indicator preview: no orders, M01/M02 gates PENDING')
    ap.add_argument('--symbol',default='XAUUSD',help='Broker exact symbol, e.g. XAUUSD or XAUUSDm')
    ap.add_argument('--bars',type=int,default=260)
    ap.add_argument('--dxy-symbol',default=None,help='Optional EXACT DXY symbol provided by MT5 broker; omission is allowed')
    ap.add_argument('--terminal-path',default=None,help='Optional path to installed terminal64.exe')
    ap.add_argument('--profile',default=str(Path(__file__).with_name('M02I_PROFILE_MT5_TIMEFRAMES_v1.1.json')))
    a=ap.parse_args()
    try:import MetaTrader5 as mt5
    except ImportError:raise SystemExit('Requires MetaTrader5 on Windows: py -m pip install MetaTrader5')
    ok=mt5.initialize(path=a.terminal_path) if a.terminal_path else mt5.initialize()
    if not ok:raise SystemExit('MT5_INIT_FAILED:'+str(mt5.last_error()))
    try:
        info=mt5.symbol_info(a.symbol)
        if info is None:raise SystemExit('SYMBOL_NOT_FOUND_ON_BROKER:'+a.symbol)
        if not info.visible and not mt5.symbol_select(a.symbol,True):
            raise SystemExit('SYMBOL_NOT_VISIBLE:'+a.symbol)
        dxy=a.dxy_symbol
        if dxy:
            info_dxy=mt5.symbol_info(dxy)
            if info_dxy is None or (not info_dxy.visible and not mt5.symbol_select(dxy,True)):
                dxy=None   # Optional absence must not block XAU; report diagnostic reason.
        snap=preview_snapshot(mt5,a.symbol,a.bars,dxy_symbol=dxy)
        if a.dxy_symbol and not dxy:snap['preview_reasons'].append('DXY_SYMBOL_NOT_FOUND_ON_BROKER')
        cfg=json.loads(Path(a.profile).read_text(encoding='utf-8'))
        print(json.dumps({'preview_only':True,'data_snapshot':snap,'indicator_intelligence':analyze({'data_snapshot':snap},cfg)},
                         ensure_ascii=False,allow_nan=False))
    finally:mt5.shutdown()

if __name__=='__main__':main()
