"""Read-only UTC tick quote exporter for M06: records genuine broker Bid/Ask, no orders.

Does NOT authenticate source or measure network arrival latency. Windows + MetaTrader5 required.
"""
from __future__ import annotations
import argparse,csv,sys
from datetime import datetime,timedelta,timezone
from pathlib import Path
from M06H_RESEARCH_ENGINE import instant,utc,canon,ResearchError

def export_ticks(mt5,symbol,start,end,destination,now=None,max_ticks=2_000_000):
    now=now or datetime.now(timezone.utc)
    if not start<end<=now:raise ResearchError('TICKS_INVALID_OR_FUTURE_RANGE')
    if end-start>timedelta(days=7):raise ResearchError('TICKS_EXPORT_MAX_7_DAYS_PER_JOB')
    if type(max_ticks)!=int or not 1<=max_ticks<=5_000_000:raise ResearchError('TICKS_BAD_LIMIT')
    if not mt5.symbol_select(symbol,True):raise ResearchError('TICKS_SYMBOL_NOT_AVAILABLE')
    output=Path(destination);output.parent.mkdir(parents=True,exist_ok=True)
    partial=output.with_suffix(output.suffix+'.partial')
    seen=set();n=skipped=0;last_at=None
    try:
        with partial.open('w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=['symbol','time_utc','bid','ask','source_id','available_at'])
            w.writeheader();cur=start
            while cur<end:
                until=min(cur+timedelta(hours=1),end)
                ticks=mt5.copy_ticks_range(symbol,cur,until,mt5.COPY_TICKS_ALL)
                if ticks is None:raise ResearchError('MT5_COPY_TICKS_FAILED_'+str(mt5.last_error()))
                for x in ticks:
                    names=(getattr(getattr(x,'dtype',None),'names',None) or (x.keys() if hasattr(x,'keys') else ()))
                    stamp=(int(x['time_msc'])/1000) if 'time_msc' in names else float(x['time'])
                    time_at=datetime.fromtimestamp(stamp,timezone.utc)
                    if not start<=time_at<end:continue
                    bid,ask=float(x['bid']),float(x['ask'])
                    if not (0<bid<=ask):skipped+=1;continue
                    if last_at and time_at<last_at:raise ResearchError('MT5_TICK_TIMES_UNSORTED')
                    key=(time_at,bid,ask)
                    if key in seen:continue
                    seen.add(key);last_at=time_at
                    w.writerow({'symbol':symbol,'time_utc':utc(time_at),'bid':bid,'ask':ask,
                                'source_id':'MT5_BROKER_EXPORT_UNCERTIFIED','available_at':utc(time_at)})
                    n+=1
                    if n>max_ticks:raise ResearchError('TICK_LIMIT_EXCEEDED_REDUCE_EXPORT_PERIOD')
                cur=until
        if n==0:raise ResearchError('NO_VALID_MT5_TICKS')
        partial.replace(output)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    return {'status':'EXPORTED_READONLY','tick_rows':n,'skipped_nonquotes':skipped,'symbol':symbol,
            'filename':str(output),'execution_permission':'BLOCKED',
            'notes':['Tick quote timestamps are broker timestamps; local arrival delay unknown',
                     'Zero account can still charge spread, commissions and slippage',
                     'A signal point-in-time ledger and validated M06 packet are still required for trading performance']}

def cli():
    p=argparse.ArgumentParser();p.add_argument('--symbol',default='XAUUSD');p.add_argument('--from-utc',required=True)
    p.add_argument('--to-utc',required=True);p.add_argument('--output',default='data/XAUUSD_MT5_TICKS.csv')
    p.add_argument('--max-ticks',type=int,default=2000000);a=p.parse_args()
    try:
        s,e=instant(a.from_utc),instant(a.to_utc)
        try:import MetaTrader5 as mt5
        except ImportError as x:raise ResearchError('INSTALL_META_TRADER5_ON_WINDOWS') from x
        if not mt5.initialize():raise ResearchError('MT5_INITIALIZATION_FAILED_'+str(mt5.last_error()))
        try:result=export_ticks(mt5,a.symbol,s,e,a.output,max_ticks=a.max_ticks)
        finally:mt5.shutdown()
        print(canon(result))
    except (ResearchError,ValueError,TypeError,OSError) as ex:
        print(canon({'status':'FAIL','reason':str(ex),'execution_permission':'BLOCKED'}));sys.exit(2)
if __name__=='__main__':cli()
