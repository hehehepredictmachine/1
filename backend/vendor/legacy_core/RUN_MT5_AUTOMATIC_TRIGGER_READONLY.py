"""MT5-only read-only trigger confirmation monitor. No order API."""
from __future__ import annotations
import argparse
import copy
import json
from pathlib import Path
import sys
import time
from M02I_M01_M02_LIVE_BRIDGE import IntegratedReadOnlyMonitor, atomic_json
from RUN_MT5_READONLY_SIGNAL_LIFECYCLE import publish as previous_publish, load, BASE
from M10_AUTO_TRIGGER_CONFIRM import advance
from M14_REFERENCE_DECISION_ENGINE import evaluate as m14_evaluate
from M01_AUDIT import POLICY


def _confirmation_from_record(rec):
    if rec.get('state')!='CONFIRMED' or not rec.get('trigger_event_id'):
        return None
    changes=rec.get('change_log') or []
    triggers=[x for x in changes if x.get('reason')=='TRIGGER' and x.get('event_id')==rec['trigger_event_id']]
    confirms=[x for x in changes if x.get('reason')=='CONFIRM']
    if not triggers or not confirms or triggers[-1]['event_id']==confirms[-1]['event_id']:
        return None
    if not all(x['event_id'] in (rec.get('event_hashes') or {}) for x in (triggers[-1],confirms[-1])):
        return None
    return triggers[-1]['available_at']


def decision_from_auto(base, auto):
    rec=auto.get('validated_record')
    core=auto.get('core_evidence')
    if rec is None or core is None:return None
    # The M14 analytical gate remains authoritative, rather than formatting
    # an arbitrary CONFIRMED string as a BUY or SELL signal.
    report=base.get('router_result') or {}
    snap=base.get('market_state') or {}
    trigger_at=_confirmation_from_record(rec)
    m14_setup={**rec, 'core_evidence':core, 'trigger_confirmed':trigger_at is not None,
               'trigger_source':'MT5_PRIMARY' if trigger_at else None,
               'trigger_available_at':trigger_at,
               'confirmation_source':'MT5_PRIMARY' if trigger_at else None,
               'distinct_confirmation':trigger_at is not None,
               'confirmation_gates':{k:'PASS' for k in ('data','trigger','invalidation','expiry','conflict')}
                     if trigger_at else {}}
    m14_snap={'snapshot_id':base.get('snapshot_id'),'as_of':base.get('as_of'),
             'instrument_id':'XAUUSD','analysis_gate':base.get('data_gate'),
             'execution_gate':'PENDING','event_gate':'PENDING','trap_gate':'PENDING'}
    return m14_evaluate({
        'schema_version':'2.0.0','data_source_policy':POLICY,
        'screenshot_capture_enabled':False,'visual_capture_enabled':False,'ocr_enabled':False,
        'execution_environment':'ANALYSIS_ONLY','analysis_id':base.get('analysis_id'),
        'as_of':base.get('as_of'),'data_snapshot':m14_snap,'router_result':report,
        'setup':m14_setup,'runtime':{'status':'UNKNOWN'},'risk_result':{},
        'registry_snapshot':{},'account':{'source':'MT5_PRIMARY','verified':False,'account_type':'ZERO_SPREAD'},
        'config':{},'portfolio_snapshot':{},'kill_switch':True,'score_components':None})


def publish(monitor, output, db_path, strategy_plan=None):
    # Prior runner owns actual M01->M02->M02I->M03E->M09->M10 EARLY flow.
    base=previous_publish(monitor, output, db_path, strategy_plan)
    base['auto_trigger']={'status':'PENDING','reason_codes':['NO_FROZEN_STRATEGY_PLAN']}
    if (strategy_plan and monitor.connected and monitor.snapshot and
        base.get('monitor_quote_status')=='RECEIVED' and base.get('data_gate') in ('PASS','PASS_WITH_LIMITATIONS')
        and base.get('m10_result')):
        try:
            result=advance(base,monitor.snapshot,monitor.quote,strategy_plan,db_path,
                now=monitor.now(),direct_mt5=True,connected=True)
            base['auto_trigger']=result
            if result.get('validated_record') and result.get('status')=='PASS_WITH_LIMITATIONS':
                base['setup_state']=result['setup_state']
                decision=decision_from_auto(base,result)
                if decision is not None:
                    base['decision_result']=decision
                    base['analysis_decision']=decision['decision']
                    base['intended_direction']=decision['intended_direction']
                    base['signal_tier']=decision['signal_tier']
                    base['signal_validity']=decision['signal_validity']
                if result.get('m10_result'):
                    base['m10_result']=result['m10_result']
        except (ValueError,TypeError,KeyError,RuntimeError,TimeoutError) as exc:
            base['auto_trigger']={'status':'PENDING','reason_codes':['AUTO_TRIGGER_ERROR:'+type(exc).__name__]}
            base['analysis_decision']='NO_TRADE';base['intended_direction']='UNKNOWN'
    # This monitor is never an execution authorization or brokerage order.
    base['execution_permission']='BLOCKED'
    base['execution_eligible']=False
    base['live_execution_allowed']=False
    base['broker_order_sent']=False
    base['submitted_order_id']=None
    base['screen_capture_count']=0
    atomic_json(output,base)
    return base


def run(args, mt5):
    settings=load(args.settings)
    settings['full_refresh_seconds']=min(settings['full_refresh_seconds'],10.0)
    if args.bars:settings['history_closed_bars']=args.bars
    mon=IntegratedReadOnlyMonitor(mt5,args.symbol,settings,
      load(args.m02_profile),load(args.m02i_profile),args.raw_monitor_file,
      dxy_symbol=args.dxy_symbol)
    plan=load(args.strategy_plan) if args.strategy_plan else None
    started=time.monotonic();next_try=0.0;next_quote=next_bar=next_full=0.0;attempt=0
    try:
        while args.duration_seconds is None or time.monotonic()-started<args.duration_seconds:
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
                if mon.connected:mon.poll(check_bars=t>=next_bar)
                if t>=next_quote:next_quote=t+settings['quote_poll_seconds']
                if t>=next_bar:next_bar=t+settings['bar_poll_seconds']
                r=publish(mon,args.monitor_file,args.state_db,plan)
                if r.get('setup_state'):
                    print(r['published_at'],r['analysis_decision'],r['setup_state'],'EXECUTION=BLOCKED',flush=True)
            time.sleep(.1)
    except KeyboardInterrupt:
        pass
    finally:
        mon.disconnect('STOPPED_BY_USER')
        publish(mon,args.monitor_file,args.state_db,plan)
    return 0


def main():
    ap=argparse.ArgumentParser(description='MasterQUO MT5 automatic M10 trigger (READ ONLY; NO ORDERS)')
    ap.add_argument('--symbol',default='XAUUSD');ap.add_argument('--dxy-symbol',default=None)
    ap.add_argument('--terminal-path',default=None);ap.add_argument('--duration-seconds',type=float,default=None)
    ap.add_argument('--bars',type=int,default=None)
    ap.add_argument('--settings',default=str(BASE/'BRIDGE_SETTINGS.example.json'))
    ap.add_argument('--m02-profile',default=str(BASE/'vendor/M02/M02_PROFILE.example.json'))
    ap.add_argument('--m02i-profile',default=str(BASE/'vendor/M02I/M02I_PROFILE_MT5_TIMEFRAMES_v1.1.json'))
    ap.add_argument('--strategy-plan',default=None,help='Required for automatic stages; frozen rules and actual M03 IDs')
    ap.add_argument('--monitor-file',default=str(BASE/'runtime/MASTERQUO_M10_AUTO_TRIGGER_MONITOR.json'))
    ap.add_argument('--raw-monitor-file',default=str(BASE/'runtime/MT5_RAW_DIAGNOSTIC.json'))
    ap.add_argument('--state-db',default=str(BASE/'runtime/M10_STATE.sqlite'))
    args=ap.parse_args()
    try:import MetaTrader5 as mt5
    except ImportError:
        print('Windows: py -m pip install MetaTrader5 numpy',file=sys.stderr);return 2
    return run(args,mt5)

if __name__=='__main__':raise SystemExit(main())
