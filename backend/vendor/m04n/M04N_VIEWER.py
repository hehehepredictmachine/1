"""Console news/macro viewer. Does not fetch data or place trades."""
import argparse
import datetime as dt
import json
from pathlib import Path
import time
from M04N_ENGINE import parse_time,utc_now

def show(obj,now=None):
    now=now or utc_now()
    stamp=parse_time(obj.get('as_of'))
    age=(now-stamp).total_seconds()/60 if stamp else float('inf')
    status=obj.get('status','UNKNOWN')
    print('='*75)
    print('MASTERQUO M04N  | XAUUSD / USD NEWS & MACRO | READ ONLY')
    print('Status:',status,' | Report UTC:',obj.get('as_of'),' | Age min:',round(age,1))
    if age>15:print('!! REPORT STALE (>15 MINUTES). DO NOT USE AS LIVE CONTEXT !!')
    print('Risk:',obj.get('interpretation',{}).get('risk_advisory','UNKNOWN'), '| Orders: BLOCKED')
    print('Source problems:',', '.join(obj.get('integrity',{}).get('failed_or_stale_sources',[])) or 'None among configured sources')
    print('Fair Economy calendar imports: FF + Metals Mine (configured); their news pages are reference links, NOT automatic headline feeds.')
    print('Recent headlines:')
    for a in obj.get('news',{}).get('recent',[])[:12]:
        print(' ',a['impact'],a['headline'][:110], '['+a['source_id']+']')
    events=obj.get('calendar',{}).get('events',[])
    print('Scheduled releases, next 48 hours (BLS + Forex Factory + Metals Mine; partial):')
    count=0
    for e in events:
        when=parse_time(e.get('scheduled_at'))
        if when and now <= when <= now+dt.timedelta(hours=48):
            print(' ',e['scheduled_at'],e['impact'],e['name'][:70], '['+', '.join(e.get('provider_sources',[e.get('source_id','?')]))+']');count+=1
    if not count:print('  No fresh events detected in configured calendars; this does NOT mean no market risk')
    print('='*75,flush=True)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--file',default=str(Path(__file__).parent/'runtime'/'M04N_INTELLIGENCE.json'))
    ap.add_argument('--watch',type=int,default=0,help='seconds between screen updates; 0 once')
    a=ap.parse_args()
    while True:
        try:show(json.loads(Path(a.file).read_text(encoding='utf-8')))
        except (FileNotFoundError,json.JSONDecodeError) as exc:print('Report unavailable:',exc)
        if not a.watch:break
        time.sleep(max(2,a.watch))
if __name__=='__main__':main()
