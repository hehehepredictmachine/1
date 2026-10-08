"""Deliberately synthetic fixtures; NEVER market evidence."""
import argparse,csv,math
from datetime import datetime,timedelta,timezone
from pathlib import Path
from M06R_HISTORICAL_REPLAY import TF,ORDER,stamp

def make(directory, bars=260, end=None):
    dest=Path(directory);dest.mkdir(parents=True,exist_ok=True)
    end=end or datetime(2026,9,1,12,0,tzinfo=timezone.utc)
    for tf in ORDER:
        period=timedelta(seconds=TF[tf]);start=end-bars*period
        with (dest/(tf+'.csv')).open('w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=['symbol','time_utc','open','high','low','close','tick_volume','bar_state'])
            w.writeheader()
            for i in range(bars):
                t=start+i*period
                base=2400+0.07*i+1.4*math.sin(i/8.0)+0.7*math.sin(i/19)
                close=base+0.30*math.sin(i*0.73)
                w.writerow({'symbol':'XAUUSD','time_utc':stamp(t),'open':round(base,6),
                  'high':round(max(base,close)+1.0,6),'low':round(min(base,close)-1.0,6),
                  'close':round(close,6),'tick_volume':100+i%13,'bar_state':'CLOSED'})
    (dest/'READ_THIS_IS_SYNTHETIC.txt').write_text('These CSV files are ARTIFICIAL educational data, not MT5 quotes; no market performance inference.\n',encoding='utf-8')
    return dest
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output-dir',default='examples/SYNTHETIC_SIX_TF')
    p.add_argument('--bars',type=int,default=260);a=p.parse_args()
    print('SYNTHETIC ONLY',make(a.output_dir,a.bars))
