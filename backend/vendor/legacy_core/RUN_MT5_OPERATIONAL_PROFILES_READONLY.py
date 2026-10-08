"""Continuous, READ-ONLY MT5 strategy research scanner and M10A/M14/M15 handoff.

Selects one of three preset research playbooks from actual M03 evidence.
No screenshot, OCR, brokerage orders, live eligibility, or automatic Telegram.
"""
from __future__ import annotations
import argparse
import sqlite3
from pathlib import Path
import sys
import time
from M02I_M01_M02_LIVE_BRIDGE import IntegratedReadOnlyMonitor,atomic_json
from M03E_M10_PIPELINE import analyze_snapshot,load
from M01_AUDIT import audit
from RUN_MT5_AUTOMATIC_TRIGGER_READONLY import publish as publish_m10,decision_from_auto
from M10A_M15_ADAPTER import render
from M07_M03E_PROFILE_RUNTIME import ResearchPlanLock
from M07_M03E_PROFILE_DETECTOR import read_config,GOOD

ROOT=Path(__file__).resolve().parent


def research_selection(monitor,mode,lock):
    if not (monitor.connected and isinstance(monitor.snapshot,dict) and isinstance(monitor.quote,dict)):
        return None,{'candidate_status':'NONE','reason_codes':['MT5_DISCONNECTED']}
    try:
        clock=monitor.now()
        preview=analyze_snapshot(monitor.snapshot,monitor.quote, direct_mt5=True,connected=True,
                                 db_path=None, strategy_plan=None,runtime_clock=clock)
        if preview.get('data_gate') not in GOOD:
            return None,{'candidate_status':'NONE','reason_codes':preview.get('reason_codes',['M01_DATA_NOT_VERIFIED'])}
        if not isinstance(preview.get('market_state'),dict) or not isinstance(preview.get('market_evidence'),dict):
            return None,{'candidate_status':'NONE','reason_codes':['M02_M03_NOT_AVAILABLE']}
        source=audit(monitor.snapshot,monitor.quote,collected_directly=True,connected=True,now=clock,
                     max_quote_age_seconds=5.0,min_bars=230,
                     max_last_bar_age_minutes={'M1':15,'M5':25,'M15':65,'H1':180,'H4':720,'D1':4320})
        return lock.choose(source,preview['market_state'],preview['market_evidence'],mode)
    except (ValueError,TypeError,KeyError,RuntimeError,OverflowError,sqlite3.Error) as exc:
        return None,{'candidate_status':'NONE','reason_codes':['PROFILE_SELECTION_FAILED:'+type(exc).__name__]}


def publish_one(monitor,args,lock,cache=None):
    # Poll no more than once per 5 seconds for strategy discovery; M10A rechecks
    # live quote validity on each publication. No cache grants freshness.
    now=time.monotonic()
    snap_id=(monitor.snapshot or {}).get('snapshot_id') if monitor.connected else None
    key=(snap_id,args.mode,int(now//5),bool(monitor.connected))
    if cache is not None and cache.get('key')==key:
        plan=cache['plan'];discovery=cache['discovery']
    else:
        plan,discovery=research_selection(monitor,args.mode,lock)
        if cache is not None:cache.update(key=key,plan=plan,discovery=discovery)
    upstream=publish_m10(monitor,args.upstream_file,args.state_db,plan)
    if (monitor.connected and isinstance(monitor.snapshot,dict) and
        upstream.get('snapshot_id')==monitor.snapshot.get('snapshot_id') and
        upstream.get('as_of')==monitor.snapshot.get('as_of')):
        upstream['analysis_id']=monitor.snapshot.get('analysis_id')
        auto=upstream.get('auto_trigger') or {}
        if auto.get('status')=='PASS_WITH_LIMITATIONS' and auto.get('validated_record'):
            decision=decision_from_auto(upstream,auto)
            if decision is not None:
                upstream['decision_result']=decision
                upstream['analysis_decision']=decision['decision']
                upstream['intended_direction']=decision['intended_direction']
                upstream['signal_tier']=decision['signal_tier']
                upstream['signal_validity']=decision['signal_validity']
    upstream['operational_profiles']={'mode':args.mode,
         'selected_profile':plan.get('profile_name') if plan else None,
         'strategy_id':plan.get('strategy_id') if plan else None,
         'plan_hash':plan.get('frozen_plan_hash') if plan else None,
         'research_only':True,'execution_permission':'BLOCKED',
         'reason_codes':discovery.get('reason_codes',[])}
    upstream['execution_permission']='BLOCKED';upstream['execution_eligible']=False
    upstream['live_execution_allowed']=False;upstream['broker_order_sent']=False
    upstream['submitted_order_id']=None;upstream['screen_capture_count']=0
    atomic_json(args.upstream_file,upstream)
    atomic_json(args.discovery_file,{'as_of':upstream.get('as_of'),'snapshot_id':upstream.get('snapshot_id'),
        'connected':bool(monitor.connected),'decision':upstream.get('analysis_decision'),
        'mode':args.mode,'selected_profile':plan.get('profile_name') if plan else None,
        'strategy_id':plan.get('strategy_id') if plan else None,
        'candidate_status':discovery.get('candidate_status'),'reason_codes':discovery.get('reason_codes',[]),
        'proposals':[{k:v for k,v in x.items() if k!='plan'} for x in discovery.get('proposals',[])],
        'source':'MT5_PRIMARY','research_only':True,'execution_permission':'BLOCKED'})
    final=render(upstream,args.output_dir,telegram_enabled=args.telegram_send)
    return {'analysis_decision':upstream.get('analysis_decision'),'data_gate':upstream.get('data_gate'),
            'setup_state':upstream.get('setup_state'),'profile':plan.get('profile_name') if plan else None,
            'delivery_status':final['delivery']['delivery_status'],'execution_permission':'BLOCKED'}


def run(args, mt5):
    cfg=read_config(args.profiles)
    lock=ResearchPlanLock(args.profile_db,cfg)
    settings=load(args.settings)
    settings['full_refresh_seconds']=min(settings['full_refresh_seconds'],10.0)
    if args.bars:settings['history_closed_bars']=args.bars
    mon=IntegratedReadOnlyMonitor(mt5,args.symbol,settings,
        load(args.m02_profile),load(args.m02i_profile),args.raw_monitor_file,
        dxy_symbol=args.dxy_symbol)
    started=time.monotonic();next_try=0.;next_quote=next_bar=next_full=0.;attempt=0;cache={}
    def output():
        result=publish_one(mon,args,lock,cache)
        print('MODE',args.mode,'PROFILE',result['profile'],'DATA',result['data_gate'],
              'DECISION',result['analysis_decision'],'PHASE',result['setup_state'],
              'EXECUTION BLOCKED',flush=True)
    try:
        while args.duration_seconds is None or time.monotonic()-started<args.duration_seconds:
            t=time.monotonic()
            if not mon.connected:
                if t>=next_try:
                    if mon.start(args.terminal_path):
                        attempt=0;next_quote=next_bar=t;next_full=t+settings['full_refresh_seconds']
                    else:
                        attempt+=1;next_try=t+min(30,2**min(attempt,5))
                output()
            elif t>=next_quote or t>=next_bar or t>=next_full:
                if t>=next_full:
                    try:mon.refresh()
                    except (ValueError,TypeError,KeyError,RuntimeError) as exc:
                        mon.disconnect('REFRESH_FAILED_'+type(exc).__name__)
                    next_full=t+settings['full_refresh_seconds']
                if mon.connected:mon.poll(check_bars=t>=next_bar)
                if t>=next_quote:next_quote=t+settings['quote_poll_seconds']
                if t>=next_bar:next_bar=t+settings['bar_poll_seconds']
                output()
            time.sleep(.1)
    except KeyboardInterrupt:
        pass
    finally:
        mon.disconnect('STOPPED_BY_USER');output()
    return 0


def main(argv=None):
    ap=argparse.ArgumentParser(description='MasterQUO operational research profiles MT5 read-only')
    ap.add_argument('--symbol',default='XAUUSD');ap.add_argument('--mode',choices=['AUTO','MVP','SMC','SCALPING'],default='AUTO')
    ap.add_argument('--dxy-symbol',default=None);ap.add_argument('--terminal-path',default=None)
    ap.add_argument('--duration-seconds',type=float,default=None);ap.add_argument('--bars',type=int,default=None)
    ap.add_argument('--profiles',default=str(ROOT/'OPERATIONAL_PROFILES_v1.json'))
    ap.add_argument('--settings',default=str(ROOT/'BRIDGE_SETTINGS.example.json'))
    ap.add_argument('--m02-profile',default=str(ROOT/'vendor/M02/M02_PROFILE.example.json'))
    ap.add_argument('--m02i-profile',default=str(ROOT/'vendor/M02I/M02I_PROFILE_MT5_TIMEFRAMES_v1.1.json'))
    ap.add_argument('--upstream-file',default=str(ROOT/'runtime/M10A_UPSTREAM_MONITOR.json'))
    ap.add_argument('--discovery-file',default=str(ROOT/'runtime/OP_DISCOVERY.json'))
    ap.add_argument('--raw-monitor-file',default=str(ROOT/'runtime/MT5_RAW_DIAGNOSTIC.json'))
    ap.add_argument('--state-db',default=str(ROOT/'runtime/M10_STATE.sqlite'))
    ap.add_argument('--profile-db',default=str(ROOT/'runtime/OP_RESEARCH_LOCK.sqlite'))
    ap.add_argument('--output-dir',default=str(ROOT/'runtime/M15'))
    ap.add_argument('--telegram-send',action='store_true',help='EXPLICIT opt-in analytical notifications only, no orders')
    args=ap.parse_args(argv)
    try:import MetaTrader5 as mt5
    except ImportError:
        print('Windows: py -3 -m pip install MetaTrader5 numpy',file=sys.stderr);return 2
    return run(args,mt5)

if __name__=='__main__':raise SystemExit(main())
