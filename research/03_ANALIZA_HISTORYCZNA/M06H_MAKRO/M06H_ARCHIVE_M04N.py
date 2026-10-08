"""Append-only local historical M04N snapshot recorder with tamper-evident hash chain.
Run at each M04N poll, not retrospectively. Chains are unkeyed, not trusted third-party timestamps.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
from pathlib import Path
import json,os,sys
from M06H_RESEARCH_ENGINE import sha,canon,instant,check_archive_line,ResearchError,utc

def archive_snapshot(src,destination,now=None):
    obj=json.loads(Path(src).read_text(encoding='utf-8'))
    if obj.get('module_id')!='M04N' or 'calendar' not in obj or 'news' not in obj:raise ResearchError('INVALID_M04N_REPORT')
    now=now or datetime.now(timezone.utc)
    if isinstance(now,str):now=instant(now)
    report_at=instant(obj['as_of'])
    if report_at>now:raise ResearchError('FUTURE_SOURCE_REPORT')
    out=Path(destination);out.parent.mkdir(parents=True,exist_ok=True)
    prev='GENESIS';last_at=None;last_payload=None
    if out.exists():
        for line in out.read_text(encoding='utf-8').splitlines():
            if not line.strip():continue
            row=json.loads(line);prev=check_archive_line(row,prev)
            last_at=instant(row['captured_at']);last_payload=sha(row['payload'])
    if last_at and now<last_at:raise ResearchError('CAPTURE_CLOCK_MOVED_BACKWARD')
    if last_payload==sha(obj):return {'status':'UNCHANGED_NOT_APPENDED','records_appended':0}
    record={'prev_hash':prev,'captured_at':utc(now),'payload':obj}
    record['record_hash']=sha(record)
    with out.open('a',encoding='utf-8',newline='\n') as f:
        f.write(canon(record)+'\n');f.flush();os.fsync(f.fileno())
    return {'status':'APPENDED','records_appended':1,'record_hash':record['record_hash'],'captured_at':utc(now)}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--input',required=True);parser.add_argument('--archive',default='runtime_m06h/M04N_HISTORY.jsonl')
    a=parser.parse_args()
    try: print(canon(archive_snapshot(a.input,a.archive)))
    except (ResearchError,ValueError,KeyError,OSError) as e:
        print(canon({'status':'FAIL','reason':str(e)}));sys.exit(2)
