"""MasterQUO MT5 Zero local read-only observer + M01/M03E/M10 research lifecycle.
No order API, no screenshots, no password capture, no external services.
"""
from __future__ import annotations
import argparse
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from M02I_M01_M02_LIVE_BRIDGE import IntegratedReadOnlyMonitor, atomic_json
from M03E_M10_PIPELINE import analyze_snapshot, load

BASE=Path(__file__).resolve().parent

def empty(reason):
    return {'schema_version':'2.0.0','module_id':'M01_M03E_M10_READONLY_INTEGRATION',
      'status':'PENDING','analysis_decision':'NO_TRADE','intended_direction':'UNKNOWN',
      'execution_permission':'BLOCKED','execution_eligible':False,'live_execution_allowed':False,
      'broker_order_sent':False,'submitted_order_id':None,'reason_codes':[reason],
      'research_only':True,'account_profile':'ZERO_SPREAD_DECLARED_UNVERIFIED'}

def publish(monitor,output,db_path,strategy_plan=None):
    health,warnings,age=monitor.quote_health()
    if not monitor.connected or health!='RECEIVED' or not monitor.snapshot:
        result=empty('MT5_DATA_UNAVAILABLE_OR_QUOTE_'+health)
    else:
        try:
            if (getattr(monitor,'_research_cache_id',None)==monitor.snapshot.get('snapshot_id')
                and getattr(monitor,'_research_cache_result',None) is not None):
                result=copy.deepcopy(monitor._research_cache_result)
                result['quote_only_update_no_new_bar_evidence']=True
                result['signal_valid_as_of_closed_bar_only']=True
            else:
                result=analyze_snapshot(monitor.snapshot,monitor.quote,
                      direct_mt5=True,connected=monitor.connected,
                      runtime_clock=monitor.now(),strategy_plan=strategy_plan,
                      db_path=db_path,read_only_runtime_healthy=True)
                monitor._research_cache_id=monitor.snapshot.get('snapshot_id')
                monitor._research_cache_result=copy.deepcopy(result)
                result['quote_only_update_no_new_bar_evidence']=False
        except (ValueError,TypeError,KeyError,RuntimeError) as exc:
            result=empty('PIPELINE_ERROR_'+type(exc).__name__)
    if not monitor.connected or health!='RECEIVED':
        monitor._research_cache_id=None
        monitor._research_cache_result=None
    result['monitor_connection_status']='CONNECTED' if monitor.connected else 'DISCONNECTED'
    result['monitor_quote_status']=health
    result['monitor_quote_age_seconds']=age
    result['published_at']=monitor.now().isoformat()
    result['broker_quote']=monitor.quote if health=='RECEIVED' else None
    # Local integrity PASS_WITH_LIMITATIONS is not proof of live execution eligibility.
    result['execution_permission']='BLOCKED'
    result['live_execution_allowed']=False
    result['broker_order_sent']=False
    atomic_json(output,result)
    return result

def run(args,mt5):
    settings=load(args.settings)
    settings['full_refresh_seconds']=min(settings['full_refresh_seconds'],10.0)
    if args.bars:settings['history_closed_bars']=args.bars
    mon=IntegratedReadOnlyMonitor(mt5,args.symbol,settings,
          load(args.m02_profile),load(args.m02i_profile),args.raw_monitor_file,
          dxy_symbol=args.dxy_symbol)
    plan=load(args.strategy_plan) if args.strategy_plan else None
    started=time.monotonic();next_try=0.0;next_quote=next_bar=next_full=0.0;attempt=0
    try:
        while args.duration_seconds is None or time.monotonic()-started < args.duration_seconds:
            t=time.monotonic()
            if not mon.connected:
                if t>=next_try:
                    if mon.start(args.terminal_path):
                        attempt=0;next_quote=next_bar=t;next_full=t+settings['full_refresh_seconds']
                    else:
                        attempt+=1;next_try=t+min(30,2**min(attempt,5))
                publish(mon,args.monitor_file,args.state_db,plan)
            elif t>=next_quote or t>=next_bar or t>=next_full:
                if t>=next_full:
                    try:mon.refresh()
                    except (ValueError,TypeError,KeyError,RuntimeError) as exc:
                        mon.disconnect('REFRESH_FAILED_'+type(exc).__name__)
                    next_full=t+settings['full_refresh_seconds']
                if mon.connected:
                    mon.poll(check_bars=t>=next_bar)
                if t>=next_quote:next_quote=t+settings['quote_poll_seconds']
                if t>=next_bar:next_bar=t+settings['bar_poll_seconds']
                r=publish(mon,args.monitor_file,args.state_db,plan)
                if r.get('setup_state'):
                    print(r['published_at'],r['analysis_decision'],r['setup_state'],r['execution_permission'],flush=True)
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        mon.disconnect('STOPPED_BY_USER')
        publish(mon,args.monitor_file,args.state_db,plan)
    return 0

def main():
    ap=argparse.ArgumentParser(description='MasterQUO live MT5 read-only research bridge; no trade execution')
    ap.add_argument('--symbol',default='XAUUSD')
    ap.add_argument('--dxy-symbol',default=None)
    ap.add_argument('--terminal-path',default=None)
    ap.add_argument('--duration-seconds',type=float,default=None)
    ap.add_argument('--bars',type=int,default=None)
    ap.add_argument('--settings',default=str(BASE/'BRIDGE_SETTINGS.example.json'))
    ap.add_argument('--m02-profile',default=str(BASE/'vendor/M02/M02_PROFILE.example.json'))
    ap.add_argument('--m02i-profile',default=str(BASE/'vendor/M02I/M02I_PROFILE_MT5_TIMEFRAMES_v1.1.json'))
    ap.add_argument('--strategy-plan',default=None,help='Optional explicit research-only plan with matching M03 evidence IDs')
    ap.add_argument('--monitor-file',default=str(BASE/'runtime/MASTERQUO_M03E_M10_MONITOR.json'))
    ap.add_argument('--raw-monitor-file',default=str(BASE/'runtime/MT5_RAW_DIAGNOSTIC.json'))
    ap.add_argument('--state-db',default=str(BASE/'runtime/M10_STATE.sqlite'))
    a=ap.parse_args()
    try:import MetaTrader5 as mt5
    except ImportError:
        print('Windows: py -m pip install MetaTrader5 numpy',file=sys.stderr);return 2
    return run(a,mt5)

if __name__=='__main__':raise SystemExit(main())
