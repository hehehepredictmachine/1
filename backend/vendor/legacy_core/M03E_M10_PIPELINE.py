"""Read-only local M01 audit -> unmodified M02/M02I/M03/M09/M14 -> M10.

Research-grade pipeline, no order, no screenshot, no AI/MT5 login data storage.
M03E may form EARLY only for externally defined, explicit strategy_plan
that references actual point-in-time M03 location and liquidity evidence.
M10 only moves to EARLY_SETUP automatically. No autonomous TRIGGER/CONFIRM.
"""
from __future__ import annotations
import copy
from datetime import datetime,timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import sys
BASE=Path(__file__).resolve().parent
for sub in ('M02','M02I','M03'):
    sys.path.insert(0,str(BASE/'vendor'/sub))
sys.path.insert(0,str(BASE/'vendor'))
from M02_REFERENCE_ENGINE import analyze as m02_analyze
from M02I_INDICATOR_ENGINE import analyze as m02i_analyze
from M01_AUDIT import audit, when, digest, POLICY, GOOD
from M02I_M03_M09_M14_ADAPTER import process as route_process
from M10_REFERENCE_ENGINE import SQLiteSetupStore

PROFILE_M02=BASE/'vendor/M02/M02_PROFILE.example.json'
PROFILE_M02I=BASE/'vendor/M02I/M02I_PROFILE_MT5_TIMEFRAMES_v1.1.json'
PROFILE_M03=BASE/'M03_PROFILE.example.json'
CORE=('structural_advantage','meaningful_location','liquidity_context','development_path','known_invalidation')

def testable_condition(cond, ids):
    return (isinstance(cond,dict) and cond.get('field') in ('close','high','low')
            and cond.get('operator') in ('<','>','<=','>=')
            and isinstance(cond.get('level'),(int,float)) and not isinstance(cond.get('level'),bool)
            and math.isfinite(cond['level']) and cond['level']>0
            and cond.get('requires_closed_bar') is True
            and cond.get('reference_evidence_id') in ids)

def load(p):return json.loads(Path(p).read_text(encoding='utf-8'))

def proof(name, evidence_id, snap, source='MT5_PRIMARY'):
    return {'evidence_id':evidence_id,'evidence_status':'VERIFIED',
            'source':source,'instrument_id':'XAUUSD','snapshot_id':snap['snapshot_id'],
            'available_at':snap['as_of'],'requires_closed_bar':False,'category':name.upper()}

def construct_early(m03, m02, snap, strategy):
    """Evidence-driven research candidate; never invents POI or liquidity."""
    if not isinstance(strategy,dict):return None,['STRATEGY_PLAN_REQUIRED']
    early=m03.get('early_evidence',{})
    if early.get('status')!='EARLY_SETUP':
        return None, ['M03E_FIVE_CORE_INCOMPLETE']+list(early.get('missing_core') or [])
    for k in ('strategy_id','version','spec_hash','horizon_id','setup_tf','created_event_id'):
        if not isinstance(strategy.get(k),str) or not strategy[k]:return None,[f'STRATEGY_{k.upper()}_REQUIRED']
    if strategy['strategy_id'] not in {f'XAU-S{i:02d}' for i in range(1,21)}:
        return None,['STRATEGY_NOT_IN_XAU_LIBRARY']
    if strategy['setup_tf'] not in ('M1','M5','M15','H1','H4','D1'):
        return None,['SETUP_TF_INVALID']
    loc=strategy.get('location_evidence_id');liq=strategy.get('liquidity_evidence_id')
    struct_id=strategy.get('structural_evidence_id')
    if not isinstance(struct_id,str) or struct_id not in (set(m02.get('evidence_ids',[]))|set(m03.get('evidence_ids',[]))):
        return None,['STRUCTURAL_EVIDENCE_REFERENCE_REQUIRED']
    if loc not in m03.get('evidence_ids',[]) or liq not in m03.get('evidence_ids',[]):
        return None,['LOCATION_LIQUIDITY_M03_REFERENCE_REQUIRED']
    direction=strategy['intended_direction']; event=strategy.get('next_expected_event') or {}; invalid=strategy.get('invalidation') or {}
    anchor_ids=set(m03.get('evidence_ids',[]))|set(m02.get('evidence_ids',[]))
    if not(event.get('timeframe')==strategy['setup_tf'] and
           testable_condition(event.get('condition'),anchor_ids) and event.get('failure_condition') and
           invalid.get('timeframe')==strategy['setup_tf'] and
           testable_condition(invalid.get('condition'),anchor_ids) and invalid.get('rule')=='CLOSED_BAR'):
        return None,['TESTABLE_DEVELOPMENT_AND_INVALIDATION_RULES_REQUIRED']
    # Development/invalidation are observable *rules*, not future events or proven wins.
    # Their anchor is a frozen strategy and an identified existing bar evidence.
    tfbars=snap.get('candles_by_tf',{}).get(strategy['setup_tf'],[])
    if not tfbars:return None,['NO_SETUP_TF_BAR']
    anchor=tfbars[-1].get('evidence_id')
    if not anchor:return None,['UNVERIFIED_SETUP_TF_BAR']
    edid='M03E:DEVELOPMENT:'+digest([strategy['spec_hash'],anchor,event])[:20]
    inid='M03E:INVALIDATION:'+digest([strategy['spec_hash'],anchor,invalid])[:20]
    core={'structural_advantage':proof('STRUCTURE',struct_id,snap),
          'meaningful_location':proof('LOCATION',loc,snap),
          'liquidity_context':proof('LIQUIDITY',liq,snap),
          'development_path':proof('RULE',edid,snap),
          'known_invalidation':proof('RULE',inid,snap)}
    # A single underlying event cannot serve two independent CORE references.
    if len({x['evidence_id'] for x in core.values()})!=5:
        return None,['DUPLICATE_CORE_EVIDENCE']
    stable_identity=[snap.get('exact_symbol'),strategy['strategy_id'],strategy['version'],
                     strategy['spec_hash'],strategy['horizon_id'],strategy['created_event_id'],loc,liq]
    sid='M10:'+digest(stable_identity)[:24]
    result={'setup_id':sid,'strategy_id':strategy['strategy_id'],'version':strategy['version'],
            'spec_hash':strategy['spec_hash'],'instrument_id':'XAUUSD','snapshot_id':snap['snapshot_id'],
            'direction':direction,'stage':'EARLY_SETUP','horizon_id':strategy['horizon_id'],
            'setup_tf':strategy['setup_tf'],'available_at':snap['as_of'],
            'core_evidence':core,'next_expected_event':{'criterion':event['condition'],'timeframe':event['timeframe'],
                   'failure_condition':event['failure_condition']},
            'invalidation':{'condition':invalid['condition'],'rule':invalid['rule'],'timeframe':invalid['timeframe']},
            'score':None,'confidence':'UNKNOWN','plan':None,'research_only':True}
    return result,[]

def analyze_snapshot(snapshot, quote, *, direct_mt5=False, connected=False,
                     m02_profile=None, m02i_profile=None, m03_profile=None,
                     strategy_plan=None, db_path=None, runtime_clock=None, read_only_runtime_healthy=False):
    now=runtime_clock or datetime.now(timezone.utc)
    audited=audit(snapshot,quote,collected_directly=direct_mt5,connected=connected,now=now,
                  max_quote_age_seconds=5.0,min_bars=230,
                  max_last_bar_age_minutes={'M1':15,'M5':25,'M15':65,'H1':180,'H4':720,'D1':4320})
    reasons=list(audited['local_audit']['reason_codes'])
    report={'schema_version':'2.0.0','prompt_version':'4.1.0',
            'module_id':'M01_M03E_M10_READONLY_INTEGRATION',
            'module_version':'1.0.0-CANDIDATE','snapshot_id':audited.get('snapshot_id'),
            'as_of':audited.get('as_of'), 'account_profile':'ZERO_SPREAD_DECLARED_UNVERIFIED',
            'data_audit':audited['local_audit'],'data_gate':audited['analysis_gate']['status'],
            'strategy_setup_id':None,'setup_state':None,'m10_result':None,
            'analysis_decision':'NO_TRADE','intended_direction':'UNKNOWN',
            'execution_permission':'BLOCKED','execution_eligible':False,
            'live_execution_allowed':False,'broker_order_sent':False,
            'submitted_order_id':None,'screen_capture_count':0,'visual_capture_enabled':False,
            'persistence_status':'SESSION_ONLY' if not db_path else 'LOCAL_SQLITE',
            'reason_codes':reasons,'research_only':True,
            'limitations':['LOCAL_AUDIT_NOT_BROKER_CERTIFICATION','M06_OOS_FORWARD_NOT_RUN',
                           'M11_RISK_AND_M14_AUTHORIZATION_ABSENT','NO_ORDER_EXECUTOR']}
    if audited['analysis_gate']['status'] not in GOOD:
        report['reason_codes']=list(dict.fromkeys(reasons+['M01_ANALYSIS_AUDIT_NOT_PASS']))
        return report
    mp=m02_profile or load(PROFILE_M02);ip=m02i_profile or load(PROFILE_M02I);p3=m03_profile or load(PROFILE_M03)
    try:
        market=m02_analyze(audited,mp,runtime_health={'status':'UNKNOWN','execution_data_gate':'PENDING'})
        indicators=m02i_analyze({'data_snapshot':audited,'market_state':market},ip)
    except (ValueError,KeyError,TypeError,ZeroDivisionError) as exc:
        report['reason_codes'].append('M02_M02I_ERROR:'+type(exc).__name__);return report
    report['market_state']=market
    report['indicator_intelligence']=indicators
    # M03E source independent of supplied future/price data.
    from M03_REFERENCE_ENGINE import analyze as m03_analyze
    m03=m03_analyze(audited,market,p3,strategy_plan=strategy_plan)
    report['market_evidence']=m03
    candidate,why=construct_early(m03,market,audited,strategy_plan)
    report['reason_codes']+=why
    packet={'schema_version':'2.0.0','execution_environment':'ANALYSIS_ONLY',
            'data_snapshot':audited,'market_state':market,'indicator_intelligence':indicators,
            'strategy_plan':strategy_plan,'candidate_setups':[candidate] if candidate else [],
            'mode':'AUTO','screenshot_capture_enabled':False,
            'account':{'account_type':'ZERO_SPREAD'},'enable_orders':False}
    downstream=route_process(packet,p3)
    report['router_result']=downstream['router_result']
    report['decision_result']=downstream['decision_result']
    # Lifecycle owned by M10 and stored only if M09 agrees with the candidate.
    if candidate and downstream.get('selected_setup_id')==candidate['setup_id'] and db_path:
        # CORE_READY derived from observed M03 evidence and exact M09 selected ID.
        from M10_REFERENCE_ENGINE import SQLiteSetupStore
        s=strategy_plan
        bar=audited['candles_by_tf'][candidate['setup_tf']][-1]
        old_row=None
        cx=sqlite3.connect(str(db_path))
        try:
            old_table=cx.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='setup_state'").fetchone()
            if old_table:
                old_row=cx.execute('SELECT record_json FROM setup_state WHERE setup_id=?',(candidate['setup_id'],)).fetchone()
        finally: cx.close()
        event={'event_id':'M03E:CORE_READY:'+candidate['setup_id'], 'type':'CORE_READY',
               'source':'MT5_PRIMARY','instrument_id':'XAUUSD','snapshot_id':audited['snapshot_id'],
               'evidence_status':'VERIFIED','available_at':audited['as_of']}
        m10p={'schema_version':'2.0.0','data_source_policy':POLICY,'screenshot_capture_enabled':False,
              'as_of':audited['as_of'],'analysis_id':audited.get('analysis_id'),
              'data_snapshot':{'snapshot_id':audited['snapshot_id'],'instrument_id':'XAUUSD',
                               'as_of':audited['as_of'],'analysis_gate':audited['analysis_gate']['status'],
                               'execution_gate':'PENDING','data_source_policy':POLICY,
                               'screenshot_capture_enabled':False},
              'router_result':downstream['router_result'],
              'setup':{**candidate,'created_at':s.get('created_at',audited['as_of'])},
              'events':([] if old_row else [event]), 'config':{},
              'runtime':{'status':'HEALTHY' if read_only_runtime_healthy and direct_mt5 and connected else 'UNVERIFIED'},
              'account':{'account_type':'ZERO_SPREAD','costs_verified_from_mt5':False}}
        # HEALTHY refers only to the local read-only transport after actual check.
        # This DOES NOT certify the M16 execution runtime; execution is BLOCKED.
        if old_row:
            existing=json.loads(old_row[0])
            if existing.get('state') not in ('REVIEWED','INVALIDATED','CANCELLED','EXPIRED','MISSED_ENTRY'):
                if (bar.get('bar_open_utc') and bar.get('close_confirmed_at')
                    and candidate['setup_tf']+':'+bar['bar_open_utc'] not in set(existing.get('closed_bar_keys',[]))):
                    bar_event={'event_id':'M10:CLOSED:'+candidate['setup_id']+':'+bar['bar_open_utc'],
                        'type':'CLOSED_BAR','source':'MT5_PRIMARY','instrument_id':'XAUUSD',
                        'snapshot_id':audited['snapshot_id'],'evidence_status':'VERIFIED',
                        'available_at':audited['as_of'],'bar_state':'CLOSED',
                        'timeframe':candidate['setup_tf'],'bar_open_utc':bar['bar_open_utc'],
                        'close_confirmed_at':bar['close_confirmed_at'],
                        'bar_expected_close_utc':bar['close_confirmed_at'],
                        'requires_closed_bar':True}
                    m10p['events'].append(bar_event)
        store=SQLiteSetupStore(db_path)
        try:
            result=store.apply(m10p)
        finally:store.close()
        report['m10_result']=result
        report['strategy_setup_id']=candidate['setup_id']
        report['setup_state']=result['setup']['state']
        report['reason_codes']+=result['reason_codes']
        if result['setup']['state'] not in ('EARLY_SETUP','SETUP_FORMING','QUALIFIED','ARMED','TRIGGERED','CONFIRMED'):
            report['analysis_decision']='WAIT'
            report['intended_direction']='UNKNOWN'
    elif candidate and not db_path:
        report['reason_codes'].append('M10_STATE_DB_REQUIRED_FOR_PERSISTENT_LIFECYCLE')
    elif candidate:
        report['reason_codes'].append('M09_DID_NOT_SELECT_EARLY_CANDIDATE')
    if not candidate or (db_path and report['setup_state'] not in ('EARLY_SETUP','SETUP_FORMING','QUALIFIED','ARMED','TRIGGERED','CONFIRMED')):
        report['analysis_decision']='WAIT'
        report['intended_direction']='UNKNOWN'
    else:
        report['analysis_decision']=downstream.get('analysis_decision','WAIT')
        report['intended_direction']=downstream.get('intended_direction','UNKNOWN')
    report['reason_codes']=sorted(set(report['reason_codes']+downstream.get('reason_codes',[])))
    return report
