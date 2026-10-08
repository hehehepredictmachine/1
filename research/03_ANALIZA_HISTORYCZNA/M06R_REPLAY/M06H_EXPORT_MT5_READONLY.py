"""Read-only MetaTrader 5 UTC historical M1 bars exporter. Uses no order API. Windows/MT5 required."""
from __future__ import annotations
import argparse,csv,sys
from datetime import datetime,timedelta,timezone
from pathlib import Path
from M06H_RESEARCH_ENGINE import instant,utc,canon,ResearchError

def export_m1(mt5,symbol,start,end,out,now=None):
    now=now or datetime.now(timezone.utc)
    if start>=end or end>now:raise ResearchError('INVALID_OR_FUTURE_RANGE')
    if end-start>timedelta(days=45):raise ResearchError('EXPORT_MAX_45_DAYS_PER_JOB')
    if not mt5.symbol_select(symbol,True):raise ResearchError('MT5_SYMBOL_NOT_FOUND')
    path=Path(out);path.parent.mkdir(parents=True,exist_ok=True)
    count=0;last_t=None
    with path.open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=['symbol','time_utc','open','high','low','close','tick_volume','real_volume','spread_points','bar_state'])
        writer.writeheader()
        cursor=start
        while cursor<end:
            limit=min(end,cursor+timedelta(days=5))
            bars=mt5.copy_rates_range(symbol,mt5.TIMEFRAME_M1,cursor,limit)
            if bars is None:raise ResearchError('MT5_COPY_RATES_FAILED_'+str(mt5.last_error()))
            for b in bars:
                bar_at=datetime.fromtimestamp(int(b['time']),timezone.utc)
                if bar_at<start or bar_at>=end or bar_at+timedelta(minutes=1)>now:continue
                if last_t is not None and bar_at<=last_t:continue
                if int(b['time'])%60!=0:raise ResearchError('MT5_TIME_NOT_ALIGNED_M1')
                row={'symbol':symbol,'time_utc':utc(bar_at),'open':float(b['open']),'high':float(b['high']),
                     'low':float(b['low']),'close':float(b['close']),'tick_volume':int(b['tick_volume']),
                     'real_volume':int(b['real_volume']),'spread_points':int(b['spread']),'bar_state':'CLOSED'}
                writer.writerow(row);count+=1;last_t=bar_at
            cursor=limit
    if not count:raise ResearchError('NO_MT5_BARS_RETURNED')
    return {'status':'EXPORTED_READ_ONLY','bars':count,'symbol':symbol,'start_utc':utc(start),'end_utc':utc(end),
            'source':'MT5_PYTHON_COPY_RATES_RANGE','execution_permission':'BLOCKED',
            'limitations':['M1 candle closes may be broker Bid prices; NOT fill prices','MT5 chart max bars may limit archive history']}

def main():
    p=argparse.ArgumentParser();p.add_argument('--symbol',default='XAUUSD');p.add_argument('--from-utc',required=True);p.add_argument('--to-utc',required=True)
    p.add_argument('--output',default='data/XAUUSD_MT5_M1.csv');a=p.parse_args()
    try:
        start,end=instant(a.from_utc),instant(a.to_utc)
        try:import MetaTrader5 as mt5
        except ImportError as e:raise ResearchError('INSTALL_META_TRADER5_ON_WINDOWS') from e
        if not mt5.initialize():raise ResearchError('MT5_INITIALIZATION_FAILED_'+str(mt5.last_error()))
        try:result=export_m1(mt5,a.symbol,start,end,a.output)
        finally:mt5.shutdown()
        print(canon(result))
    except (ResearchError,ValueError,OSError) as e:
        print(canon({'status':'FAIL','reason':str(e),'execution_permission':'BLOCKED'}));sys.exit(2)
if __name__=='__main__':main()
