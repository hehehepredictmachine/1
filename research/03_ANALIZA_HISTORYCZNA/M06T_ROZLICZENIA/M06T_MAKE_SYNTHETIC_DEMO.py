"""Synthetic-only, explicitly not broker data or real XAUUSD results."""
import argparse,csv,json
from pathlib import Path
from M06T_TESTS import fixtures,OOS

def main(folder):
    p,signals,stages,ticks=fixtures()
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    (folder/'PROTOCOL_SYNTHETIC.json').write_text(json.dumps(p,indent=2,ensure_ascii=False),encoding='utf-8')
    for name,rows in [('SIGNALS_SYNTHETIC.jsonl',signals),('STAGES_SYNTHETIC.jsonl',stages)]:
        (folder/name).write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in rows),encoding='utf-8')
    with (folder/'TICKS_SYNTHETIC.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=('symbol','time_utc','bid','ask','source_id','available_at'));w.writeheader()
        for t in ticks:w.writerow({'symbol':t['symbol'],'time_utc':t['time'],'bid':t['bid'],'ask':t['ask'],
          'source_id':'MT5_SYNTHETIC_FIXTURE_NOT_BROKER','available_at':t['available_at']})
    (folder/'MACRO_SYNTHETIC.json').write_text(json.dumps({'kind':'CURATED_HISTORICAL_EVENTS',
      'data_provenance':'SYNTHETIC','events':[{'event_id':'CPI_SYNTHETIC','name':'CPI SYNTHETIC TEST',
      'scheduled_at':'2025-01-04T12:05:00Z','known_at':'2025-01-04T11:00:00Z','impact':'HIGH','type':'CALENDAR'}]},indent=2),encoding='utf-8')
    (folder/'M06R_REPORT_SYNTHETIC.json').write_text(json.dumps({
      'module_id':'M06R_HISTORICAL_STRATEGY_REPLAY','schema_version':'2.0.0',
      'status':'REPLAY_RESEARCH_COMPLETE','symbol':'XAUUSD','signal_count':len(signals),
      'confirmed_signals':signals,'stage_transitions':stages,'execution_permission':'BLOCKED',
      'research_only':True,'historical_data_certified':False,'synthetic_demo':True
    },indent=2),encoding='utf-8')
    (folder/'SYNTHETIC_ONLY.txt').write_text('DEMO SYNTETYCZNE. Brak rzeczywistych wyników XAUUSD, zleceń i potwierdzonego OOS.\n',encoding='utf-8')
    return folder
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out-dir',default='examples/SYNTHETIC_ONLY');a=p.parse_args()
    print(main(a.out_dir))
