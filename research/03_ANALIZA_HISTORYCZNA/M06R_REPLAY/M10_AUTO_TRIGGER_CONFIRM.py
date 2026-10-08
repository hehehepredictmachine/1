"""M10 Automatic Trigger/Confirmation adapter v1.1.0 CANDIDATE.

Consumes the verified M01/M03E candidate in the prior read-only pipeline and
strict point-in-time frozen rules. It does NOT send orders or approve trades.
Uses original M10 reducer unchanged; transactional audit + per-bar evaluation
ledger prevents duplicate or skipped lifecycle transitions after restart.
"""
from __future__ import annotations
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/'vendor'/'M10'))
from M10_REFERENCE_ENGINE import process as m10_process, digest as m10_digest
from M01_AUDIT import audit, when, GOOD, POLICY
from M03E_M10_PIPELINE import construct_early

STAGES = {'EARLY_SETUP': ('DEVELOPMENT', 'SETUP_FORMING', 'development'),
          'SETUP_FORMING': ('QUALIFY', 'QUALIFIED', 'qualification'),
          'QUALIFIED': ('ARM', 'ARMED', 'arming'),
          'ARMED': ('TRIGGER', 'TRIGGERED', 'trigger'),
          'TRIGGERED': ('CONFIRM', 'CONFIRMED', 'confirmation')}
TF_MIN = {'M1': 1,'M5': 5,'M15': 15,'H1':60,'H4':240,'D1':1440}
TERMINAL = {'EXPIRED','INVALIDATED','CANCELLED','MISSED_ENTRY','REVIEWED','ENTERED','MANAGED','EXITED'}


def canonical_hash(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(',',':'), ensure_ascii=False).encode()).hexdigest()


def is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def check_rule(rule, tf, ids, *, close_only=False):
    if not isinstance(rule, dict): return False
    if rule.get('timeframe') != tf or rule.get('requires_closed_bar') is not True: return False
    if rule.get('field') not in ({'close'} if close_only else {'close','high','low'}): return False
    if rule.get('operator') not in {'<','<=','>','>='}: return False
    if not (is_num(rule.get('level')) and rule['level'] > 0): return False
    return isinstance(rule.get('reference_evidence_id'), str) and rule['reference_evidence_id'] in ids


def matched(rule, bar):
    x = bar[rule['field']]
    if not is_num(x): raise ValueError('BAR_PRICE_NOT_FINITE')
    level=rule['level']
    return {'>': lambda: x>level, '>=': lambda: x>=level,
            '<': lambda: x<level, '<=': lambda: x<=level}[rule['operator']]()


def rules_valid(plan, candidate, market, evidence):
    tf = candidate['setup_tf']
    ids = set(market.get('evidence_ids') or []) | set(evidence.get('evidence_ids') or [])
    rs = (plan or {}).get('lifecycle_rules')
    if not isinstance(rs,dict): return None, 'FROZEN_LIFECYCLE_RULES_REQUIRED'
    for name in ('qualification','arming','trigger','confirmation'):
        if not check_rule(rs.get(name), tf, ids, close_only=name=='confirmation'):
            return None, 'INVALID_OR_UNANCHORED_RULE_'+name.upper()
    # Four distinct rules are required; one permanently true comparison may
    # not masquerade as four independent phases. New bars still required.
    stage_names=('qualification','arming','trigger','confirmation')
    signatures=[canonical_hash(rs[k]) for k in stage_names]
    if len(set(signatures))!=len(signatures):
        return None,'REUSED_STAGE_CONDITION_NOT_INDEPENDENT'
    trend_ops={'>','>='} if candidate['direction']=='LONG' else {'<','<='}
    reverse_ops={'<','<='} if candidate['direction']=='LONG' else {'>','>='}
    if any(rs[k]['operator'] not in trend_ops for k in stage_names):
        return None,'STAGE_DIRECTION_CONTRADICTS_STRATEGY'
    if 'development' in rs and not check_rule(rs['development'], tf, ids):
        return None, 'INVALID_OR_UNANCHORED_RULE_DEVELOPMENT'
    invalid = (plan or {}).get('invalidation') or {}
    invcond=invalid.get('condition') or {}
    invrule={**invcond, 'timeframe': invalid.get('timeframe')}
    if invalid.get('rule') != 'CLOSED_BAR' or not check_rule(invrule, tf, ids):
        return None,'INVALIDATION_RULE_UNVERIFIABLE'
    if invrule['operator'] not in reverse_ops:
        return None,'INVALIDATION_DIRECTION_CONTRADICTS_STRATEGY'
    frozen={'strategy_id':plan.get('strategy_id'), 'version':plan.get('version'),
            'spec_hash':plan.get('spec_hash'), 'setup_tf':tf, 'lifecycle_rules':rs,
            'invalidation':invalid,'next_expected_event':plan.get('next_expected_event')}
    # This hashes what is actually executed. It does NOT certify that an external
    # M07 frozen spec matches the user's claimed spec_hash.
    return (rs, invrule, canonical_hash(frozen)),None


def check_bar(bar, audited, tf):
    if not isinstance(bar,dict): return 'BAR_MISSING'
    try:
        closed=when(bar.get('close_confirmed_at')); available=when(bar.get('available_at'))
        opened=when(bar.get('bar_open_utc')); asof=when(audited['as_of'])
    except (ValueError,TypeError,KeyError): return 'BAR_TIMESTAMP_INVALID'
    if bar.get('bar_state') != 'CLOSED' or bar.get('timeframe')!=tf or bar.get('instrument_id')!='XAUUSD':
        return 'BAR_NOT_CLOSED_OR_CONTEXT_MISMATCH'
    if bar.get('exact_symbol')!=audited.get('exact_symbol') or bar.get('price_basis')!='BID':
        return 'BAR_NOT_BROKER_BID_BASIS'
    if (not str(bar.get('source_id','')).startswith('MT5') or not bar.get('evidence_id')
        or available < closed or closed > asof or available > asof or opened >= closed):
        return 'BAR_UNAVAILABLE_POINT_IN_TIME'
    if tf!='D1' and closed < opened + __import__('datetime').timedelta(minutes=TF_MIN[tf]):
        return 'BAR_NOT_MATURED'
    if not all(is_num(bar.get(x)) and bar[x]>0 for x in ('open','high','low','close')):
        return 'INVALID_OHLC'
    if not bar['low'] <= min(bar['open'],bar['close']) <= max(bar['open'],bar['close']) <= bar['high']:
        return 'INVALID_OHLC'
    return None


def _event(name, bar, cand, snap_id, asof, **extra):
    eid='M10AUTO:'+canonical_hash([cand['setup_id'],name,bar['bar_open_utc']])[:30]
    return {'event_id':eid,'type':name,'source':'MT5_PRIMARY',
            'instrument_id':'XAUUSD','snapshot_id':snap_id,
            'evidence_id':bar['evidence_id'],'evidence_status':'VERIFIED',
            'available_at':asof,'bar_state':'CLOSED','requires_closed_bar':True,
            'timeframe':cand['setup_tf'],'bar_open_utc':bar['bar_open_utc'], **extra}


def _critical_conflict(router, cand):
    return any(isinstance(x,dict) and
               (x.get('horizon_id') == cand.get('horizon_id') or
                cand['setup_id'] in (x.get('setup_ids') or []))
               for x in (router.get('horizon_conflicts') or []))


def _safe_report(reason, report, record=None):
    return {'module_id':'M10_AUTO_TRIGGER','module_version':'1.1.0-CANDIDATE',
            'schema_version':'2.0.0','as_of':report.get('as_of'),
            'status':'PENDING','reason_codes':[reason],
            'setup_state':record.get('state') if record else report.get('setup_state'),
            'evaluation':'NOT_RUN','evaluated_bar':None,'trigger_verified':False,
            'confirmation_verified':False,'execution_permission':'BLOCKED',
            'live_execution_allowed':False,'submitted_order_id':None,'order_actions':[]}


def advance(report, snapshot, quote, strategy_plan, db_path, *, now=None,
            direct_mt5=False, connected=False):
    """Evaluate at most one frozen transition per *new closed* setup-TF bar.
    `direct_mt5` must only be passed by trusted local MT5 runner, never external JSON.
    """
    if not report or report.get('data_gate') not in GOOD or report.get('m10_result') is None:
        return _safe_report('M01_OR_M03E_M10_NOT_ELIGIBLE',report or {})
    if not isinstance(strategy_plan,dict) or not db_path:
        return _safe_report('STRATEGY_AND_SQLITE_REQUIRED', report)
    if strategy_plan.get('example_only') is True:
        return _safe_report('EXAMPLE_STRATEGY_CANNOT_PRODUCE_LIVE_SIGNAL',report)
    now=now or datetime.now(timezone.utc)
    audited=audit(snapshot,quote,collected_directly=direct_mt5,connected=connected,now=now,
                  max_quote_age_seconds=5.0,min_bars=230,
                  max_last_bar_age_minutes={'M1':15,'M5':25,'M15':65,'H1':180,'H4':720,'D1':4320})
    if (audited['analysis_gate']['status'] not in GOOD or
        report.get('snapshot_id') != audited.get('snapshot_id') or
        report.get('data_audit',{}).get('source_hash') != audited['local_audit']['source_hash']):
        return _safe_report('M01_SNAPSHOT_OR_AUDIT_NOT_MATCHED',report)
    candidate, why=construct_early(report.get('market_evidence') or {},
                 report.get('market_state') or {},audited,strategy_plan)
    if candidate is None:
        return _safe_report('FIVE_CORE_OR_STRATEGY_NOT_VERIFIED:'+','.join(why),report)
    if candidate['setup_id'] != report['m10_result']['setup'].get('setup_id'):
        return _safe_report('SETUP_ID_MISMATCH',report)
    ruleset, error=rules_valid(strategy_plan,candidate,report['market_state'],report['market_evidence'])
    if error:return _safe_report(error,report)
    rules, invalidrule, policy_hash=ruleset
    tf=candidate['setup_tf']
    bars=audited.get('candles_by_tf',{}).get(tf) or []
    if not bars: return _safe_report('SETUP_TF_BAR_MISSING',report)
    bar=bars[-1]
    error=check_bar(bar,audited,tf)
    if error:return _safe_report(error,report)
    if _critical_conflict(report.get('router_result') or {},candidate):
        return _safe_report('M09_CRITICAL_HORIZON_CONFLICT',report)
    if ((report.get('router_result') or {}).get('module_id') != 'M09' or
        not any(x.get('setup_id')==candidate['setup_id'] and x.get('analytical_eligible')
                for x in (report['router_result'].get('analysis_pool') or []))):
        return _safe_report('M09_ANALYSIS_ELIGIBILITY_NOT_PASS',report)
    Path(db_path).parent.mkdir(parents=True,exist_ok=True)
    cx=sqlite3.connect(str(db_path),timeout=10,isolation_level=None)
    try:
        cx.execute('PRAGMA busy_timeout=10000')
        cx.execute('CREATE TABLE IF NOT EXISTS m10auto_policy(setup_id TEXT PRIMARY KEY,policy_hash TEXT NOT NULL)')
        cx.execute('CREATE TABLE IF NOT EXISTS m10auto_ledger(setup_id TEXT NOT NULL,bar_key TEXT NOT NULL,bar_hash TEXT NOT NULL,stage_event TEXT, evaluated_at TEXT NOT NULL,PRIMARY KEY(setup_id,bar_key))')
        cx.execute('BEGIN IMMEDIATE')
        try:
            row=cx.execute('SELECT record_json FROM setup_state WHERE setup_id=?',(candidate['setup_id'],)).fetchone()
            if row is None:
                cx.execute('ROLLBACK');return _safe_report('M10_SETUP_NOT_IN_STATE_DB',report)
            rec=json.loads(row[0]);state=rec['state']
            # Protect against a stale candidate, concurrent M10 changes, or rule mutation.
            if (rec.get('spec_hash')!=candidate['spec_hash'] or rec.get('strategy_version')!=candidate['version']
                or rec.get('setup_tf')!=tf or rec.get('direction')!=candidate['direction']):
                cx.execute('ROLLBACK');return _safe_report('M10_IMMUTABLE_SETUP_MISMATCH',report,rec)
            old=cx.execute('SELECT policy_hash FROM m10auto_policy WHERE setup_id=?',(candidate['setup_id'],)).fetchone()
            if old and old[0]!=policy_hash:
                cx.execute('ROLLBACK');return _safe_report('FROZEN_LIFECYCLE_RULES_CHANGED_NEW_VERSION_REQUIRED',report,rec)
            if not old:
                cx.execute('INSERT INTO m10auto_policy(setup_id,policy_hash) VALUES(?,?)',(candidate['setup_id'],policy_hash))
            key=tf+':'+bar['bar_open_utc'];bar_hash=canonical_hash(bar)
            prev_led=cx.execute('SELECT bar_key FROM m10auto_ledger WHERE setup_id=? ORDER BY bar_key DESC LIMIT 1',
                                (candidate['setup_id'],)).fetchone()
            if prev_led and prev_led[0]!=key:
                prior_open=when(prev_led[0].split(':',1)[1])
                this_open=when(bar['bar_open_utc'])
                if this_open<prior_open:
                    cx.execute('ROLLBACK');return _safe_report('BAR_TIME_ROLLBACK',report,rec)
                if tf!='D1' and (this_open-prior_open).total_seconds()>TF_MIN[tf]*60*1.5:
                    # Do not skip arbitrary middle candles and then declare a trigger.
                    # Gaps around sessions need explicit broker-calendar reconciliation.
                    cx.execute('ROLLBACK');return _safe_report('UNREPLAYED_CLOSED_BAR_GAP',report,rec)
            led=cx.execute('SELECT bar_hash,stage_event FROM m10auto_ledger WHERE setup_id=? AND bar_key=?',(candidate['setup_id'],key)).fetchone()
            if led:
                if led[0]!=bar_hash:
                    cx.execute('ROLLBACK');return _safe_report('HISTORICAL_BAR_REVISION_REQUIRES_REVIEW',report,rec)
                cx.execute('COMMIT')
                return {'module_id':'M10_AUTO_TRIGGER','module_version':'1.1.0-CANDIDATE','schema_version':'2.0.0',
                        'as_of':audited['as_of'],'status':'PASS_WITH_LIMITATIONS','reason_codes':['NO_MATERIAL_CHANGE'],
                        'setup_state':state,'evaluation':'DUPLICATE_SKIPPED','evaluated_bar':key,
                        'event_type':led[1],'validated_record':rec,'core_evidence':candidate['core_evidence'],
                        'trigger_verified':state in ('TRIGGERED','CONFIRMED'),
                        'confirmation_verified':state=='CONFIRMED','execution_permission':'BLOCKED',
                        'live_execution_allowed':False,'submitted_order_id':None,'order_actions':[]}
            stage_event=None; reason=None
            if state in TERMINAL:
                reason='TERMINAL_NO_REACTIVATION'
            elif when(bar['close_confirmed_at']) <= when(rec['created_at']):
                reason='BAR_NOT_AFTER_SETUP_CREATION'
            elif any(x.get('reason')=='CORE_READY' and when(x['available_at'])>=when(bar['close_confirmed_at'])
                     for x in rec.get('change_log', [])):
                reason='BAR_NOT_AFTER_CORE_READY'
            elif state not in STAGES:
                reason='STAGE_NOT_SUPPORTED'
            elif matched(invalidrule,bar):
                stage_event='INVALIDATE'
            else:
                desired, _, name=STAGES[state]
                if state=='EARLY_SETUP' and 'development' not in rules:
                    desired,name='QUALIFY','qualification'
                if matched(rules[name],bar):
                    # Distinct bar after previous transition. One transition per bar,
                    # never confirmation on the bar of the original trigger.
                    previous_stages=[x for x in rec.get('change_log',[]) if x.get('reason') in ('DEVELOPMENT','QUALIFY','ARM','TRIGGER','CONFIRM')]
                    if any(x.get('bar_open_utc')==bar['bar_open_utc'] for x in previous_stages):
                        reason='SAME_BAR_CANNOT_ADVANCE_TWICE'
                    else:
                        stage_event=desired
                else: reason='WAIT_FOR_'+name.upper()
            ev=[]
            if stage_event:
                ext={'conditions_met':True} if stage_event in ('QUALIFY','ARM') else {}
                if stage_event=='TRIGGER':ext['trigger_confirmed']=True
                if stage_event=='CONFIRM':
                    ext.update({'distinct_confirmation':True,'ref_trigger_event_id':rec.get('trigger_event_id'),
                      'confirmation_gates':{x:'PASS' for x in ('data','trigger','invalidation','expiry','conflict')}})
                ev=[_event(stage_event,bar,candidate,audited['snapshot_id'],audited['as_of'],**ext)]
            # M10 remains sole reducer: no manual assignment of state or broker actions.
            p={'schema_version':'2.0.0','data_source_policy':POLICY,'screenshot_capture_enabled':False,
                'as_of':audited['as_of'],'analysis_id':audited.get('analysis_id'),
                'data_snapshot':{'snapshot_id':audited['snapshot_id'],'instrument_id':'XAUUSD',
                     'as_of':audited['as_of'],'analysis_gate':audited['analysis_gate']['status'],
                     'execution_gate':'PENDING','data_source_policy':POLICY,'screenshot_capture_enabled':False},
                'router_result':report['router_result'],'setup':{**candidate,'created_at':rec['created_at']},
                'events':ev,'config':{},'runtime':{'status':'HEALTHY'},
                'account':{'account_type':'ZERO_SPREAD','costs_verified_from_mt5':False},
                'state_store_enabled':True}
            res=m10_process(p,rec)
            new=res['setup']
            if res.get('rejected_events') and ev:
                cx.execute('ROLLBACK');return _safe_report('M10_REJECTED_AUTO_EVENT:'+res['rejected_events'][0]['reason'],report,rec)
            # Add evidence for M14 stage handoff only from M10-validated events.
            if stage_event and new['state']==state:
                cx.execute('ROLLBACK');return _safe_report('M10_TRANSITION_NOT_COMPLETED',report,rec)
            newjs=json.dumps(new,ensure_ascii=False,sort_keys=True)
            if new != rec:
                cx.execute('UPDATE setup_state SET record_json=?,revision=? WHERE setup_id=?',
                           (newjs,new['revision'],candidate['setup_id']))
                cx.execute('INSERT INTO audit(setup_id,revision,state_hash,recorded_at) VALUES(?,?,?,?)',
                           (candidate['setup_id'],new['revision'],m10_digest(new),audited['as_of']))
            cx.execute('INSERT INTO m10auto_ledger(setup_id,bar_key,bar_hash,stage_event,evaluated_at) VALUES(?,?,?,?,?)',
                       (candidate['setup_id'],key,bar_hash,stage_event,audited['as_of']))
            cx.execute('COMMIT')
            return {'module_id':'M10_AUTO_TRIGGER','module_version':'1.1.0-CANDIDATE',
                    'schema_version':'2.0.0','as_of':audited['as_of'],
                    'status':'PASS_WITH_LIMITATIONS','reason_codes':[reason] if reason else [],
                    'setup_state':new['state'],'evaluation':'EVENT_APPLIED' if stage_event else 'RULE_NOT_MET',
                    'event_type':stage_event,'evaluated_bar':key,
                    'm10_result':res,'validated_record':new,'core_evidence':candidate['core_evidence'],
                    'trigger_verified':new['state'] in ('TRIGGERED','CONFIRMED'),
                    'confirmation_verified':new['state']=='CONFIRMED',
                    'execution_permission':'BLOCKED','live_execution_allowed':False,
                    'submitted_order_id':None,'order_actions':[]}
        except Exception:
            cx.execute('ROLLBACK');raise
    finally:cx.close()
