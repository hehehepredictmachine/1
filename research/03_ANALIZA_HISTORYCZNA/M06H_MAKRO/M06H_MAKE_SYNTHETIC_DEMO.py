"""Generate strictly synthetic fixture and protocol; NEVER use for investment outcomes."""
from __future__ import annotations
import csv,copy
from pathlib import Path
from M06H_RESEARCH_ENGINE import save_json,utc
from M06H_TESTS import config,bars_for,packet

def main():
    out=Path(__file__).resolve().parent/'examples'
    out.mkdir(exist_ok=True)
    cfg=config();cfg['horizons_minutes']=[5,15,60];cfg['min_final_oos_events']=8
    save_json(out/'DEMO_CONFIG_SYNTHETIC.json',cfg)
    candles=bars_for()
    with (out/'DEMO_BARS_SYNTHETIC_M1.csv').open('w',newline='',encoding='utf-8') as f:
        cols=['symbol','time_utc','open','high','low','close','bar_state','tick_volume']
        w=csv.DictWriter(f,fieldnames=cols);w.writeheader()
        for b in candles:
            w.writerow({'symbol':'XAUUSD','time_utc':utc(b['open_at']),'open':b['open'],'high':b['high'],
                        'low':b['low'],'close':b['close'],'bar_state':'CLOSED','tick_volume':10})
    save_json(out/'DEMO_EVENTS_SYNTHETIC.json',{'kind':'CURATED_HISTORICAL_EVENTS','data_provenance':'SYNTHETIC',
        'description':'Invented timestamps and prices for functional tests only; not historical CPI release times',
        'events':[{'event_id':'SYN_CPI_1','name':'Consumer Price Index (SYNTHETIC)', 'type':'CALENDAR',
                    'scheduled_at':'2025-01-02T13:30:00Z','known_at':'2025-01-01T13:00:00Z',
                    'source_id':'SYNTHETIC_FIXTURE','impact':'HIGH'},
                  {'event_id':'SYN_CPI_2','name':'Consumer Price Index (SYNTHETIC)', 'type':'CALENDAR',
                    'scheduled_at':'2025-01-04T13:30:00Z','known_at':'2025-01-03T13:00:00Z',
                    'source_id':'SYNTHETIC_FIXTURE','impact':'HIGH'}]})
    save_json(out/'DEMO_M06_TICKS_SIGNALS_SYNTHETIC.json',packet())
    print('Generated synthetic example data:',out)
if __name__=='__main__':main()
