"""Read-only file watcher: capture new local M04N report snapshots into append-only history."""
from __future__ import annotations
import argparse,time,sys
from pathlib import Path
from M06H_ARCHIVE_M04N import archive_snapshot
from M06H_RESEARCH_ENGINE import canon

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--input',required=True,help='Local live M04N_INTELLIGENCE.json path')
    p.add_argument('--archive',default='runtime_m06h/M04N_HISTORY.jsonl')
    p.add_argument('--interval',type=int,default=60,help='seconds, >=30')
    args=p.parse_args()
    if args.interval<30 or args.interval>3600:
        print('INVALID_INTERVAL');sys.exit(2)
    print('M06H archive watch running; read-only. Ctrl+C to stop.',flush=True)
    try:
        while True:
            try:
                if Path(args.input).is_file():
                    r=archive_snapshot(args.input,args.archive)
                    if r['status']=='APPENDED':print(canon(r),flush=True)
                else:print('M04N_REPORT_MISSING; archiving paused.',flush=True)
            except (ValueError,OSError,KeyError) as e:print(canon({'status':'PENDING','reason':str(e)}),flush=True)
            time.sleep(args.interval)
    except KeyboardInterrupt: print('Archive watch stopped.')
if __name__=='__main__':main()
