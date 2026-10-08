#!/usr/bin/env python3
"""MasterQUO M15 candidate: read-only presentation and opt-in alert delivery.
No order execution, no screenshots, no market feeds. Python standard library only.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from urllib import request, error

VERSION = '1.0.0-CANDIDATE'
POLICY = 'MT5_PRIMARY_TV_SUPPLEMENTAL_NO_SCREENSHOTS'
DECISIONS = {'LONG','SHORT','EARLY_SETUP','CONDITIONAL_SETUP','WAIT','NO_TRADE'}
TIERS = {'NONE','EARLY','CONDITIONAL','CONFIRMED','A_PLUS'}
STATES = {'EARLY_SETUP','SETUP_FORMING','QUALIFIED','ARMED','TRIGGERED','CONFIRMED'}
M14_REQUIRED = {'module_id','schema_version','analysis_id','as_of','decision','decision_scope',
                'execution_permission','execution_eligible','live_execution_allowed',
                'submitted_order_id','order_actions','broker_order_sent',
                'data_source_policy','screenshot_capture_enabled'}

class ContractError(ValueError):
    pass


def utc_iso(s):
    if not isinstance(s,str) or not s.strip():
        raise ContractError('AS_OF_REQUIRED')
    try:
        dt = datetime.fromisoformat(s.replace('Z','+00:00'))
        if dt.utcoffset() is None:
            raise ValueError('missing offset')
        return dt.astimezone(timezone.utc).isoformat().replace('+00:00','Z')
    except (ValueError, OverflowError) as exc:
        raise ContractError('AS_OF_MUST_HAVE_OFFSET') from exc


def validate_m14(x):
    if not isinstance(x,dict): raise ContractError('M14_OBJECT_REQUIRED')
    missing=M14_REQUIRED-set(x)
    if missing: raise ContractError('M14_MISSING_FIELDS:'+','.join(sorted(missing)))
    if x['module_id']!='M14' or x['schema_version']!='2.0.0':
        raise ContractError('M14_SCHEMA_MISMATCH')
    if x['data_source_policy']!=POLICY or x['screenshot_capture_enabled'] is not False:
        raise ContractError('SOURCE_POLICY_VIOLATION')
    if x.get('visual_capture_enabled') is True or x.get('ocr_enabled') is True:
        raise ContractError('CAPTURE_PROHIBITED')
    if x['decision_scope']!='ANALYSIS' or x['decision'] not in DECISIONS:
        raise ContractError('ANALYSIS_DECISION_INVALID')
    if not isinstance(x['analysis_id'],str) or not x['analysis_id'] or len(x['analysis_id'])>160:
        raise ContractError('ANALYSIS_ID_INVALID')
    utc_iso(x['as_of'])
    if x['execution_permission']!='BLOCKED' or x['execution_eligible'] is not False \
       or x['live_execution_allowed'] is not False or x['submitted_order_id'] is not None \
       or x['order_actions']!=[] or x['broker_order_sent'] is not False:
        raise ContractError('UNTRUSTED_EXECUTION_PERMISSION')
    if x.get('signal_tier','NONE') not in TIERS:
        raise ContractError('INVALID_SIGNAL_TIER')
    direction=x.get('intended_direction','UNKNOWN')
    if direction not in {'LONG','SHORT','NEUTRAL','UNKNOWN'}:
        raise ContractError('INVALID_DIRECTION')
    if x['decision'] in {'EARLY_SETUP','CONDITIONAL_SETUP'}:
        if direction not in {'LONG','SHORT'} or not x.get('top_setup_id') or not x.get('horizon_id'):
            raise ContractError('EARLY_REQUIRES_DIRECTION_SETUP_HORIZON')
        if x.get('signal_tier') != ('EARLY' if x['decision']=='EARLY_SETUP' else 'CONDITIONAL'):
            raise ContractError('EARLY_TIER_MISMATCH')
    if x['decision'] in {'WAIT','NO_TRADE'} and x.get('signal_tier') in {'CONFIRMED','A_PLUS'}:
        raise ContractError('NON_SIGNAL_CANNOT_HAVE_CONFIRMED_TIER')
    if x['decision'] in {'LONG','SHORT'}:
        if x['decision']!=direction or x.get('signal_validity')!='VALID_CONFIRMED_SETUP' \
        or x.get('signal_tier') not in {'CONFIRMED','A_PLUS'} \
        or x.get('entry_trigger')!='CONFIRMED' or not x.get('top_setup_id'):
            raise ContractError('DIRECTION_CONFIRMATION_INVALID')
    if x.get('probabilities') is not None:
        ps=x['probabilities']
        if not isinstance(ps,dict): raise ContractError('PROBABILITIES_WRAPPERS_REQUIRED')
        # Fail closed on unverified numerics. M15 cannot authenticate M05P provenance.
        def walk(y):
            if isinstance(y,dict):
                if 'value' in y and isinstance(y['value'],(int,float)) and not isinstance(y['value'],bool):
                    if not math.isfinite(y['value']) or not 0<=y['value']<=1:
                        raise ContractError('PROBABILITY_RANGE_INVALID')
                    if not (y.get('run_status')=='COMPLETED' and y.get('method_id') and y.get('evidence_ids')):
                        raise ContractError('PROBABILITY_PROVENANCE_MISSING')
                for z in y.values():walk(z)
            elif isinstance(y,list):
                for z in y:walk(z)
        walk(ps)
        directions=[ps.get(k) for k in ('p_long','p_short','p_neutral')]
        if all(isinstance(d,dict) and isinstance(d.get('value'),(int,float)) and not isinstance(d.get('value'),bool) for d in directions):
            if abs(sum(d['value'] for d in directions)-1)>1e-9:
                raise ContractError('DIRECTION_PROBABILITY_SUM_INVALID')
            if len({(d.get('horizon_id'),d.get('label_spec_id')) for d in directions})!=1:
                raise ContractError('DIRECTION_PROBABILITY_TARGET_MISMATCH')
    return x


def clean_text(x, maxlen=200):
    if x is None: return None
    s=str(x)
    s=re.sub(r'[\x00-\x1f\x7f\u202a-\u202e\u2066-\u2069]',' ',s)
    return ' '.join(s.split())[:maxlen]


def number_or_none(v):
    if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v):return None
    return v


def normalized_plan(c, x):
    plan=c.get('plan')
    if plan is None: return None
    if not isinstance(plan,dict): raise ContractError('PLAN_MUST_BE_OBJECT')
    if plan.get('price_source')!='MT5_PRIMARY' or plan.get('instrument_id')!=c.get('instrument_id'):
        raise ContractError('PLAN_PRICE_MUST_MATCH_MT5_INSTRUMENT')
    out={k:number_or_none(plan.get(k)) for k in ('entry','sl','tp1','tp2','tp3','rr_net')}
    if out['entry'] is not None and out['sl'] is not None:
        if x['intended_direction']=='LONG' and not out['sl']<out['entry']: raise ContractError('INVALID_LONG_SL')
        if x['intended_direction']=='SHORT' and not out['sl']>out['entry']: raise ContractError('INVALID_SHORT_SL')
    for k in ('tp1','tp2','tp3'):
        if out[k] is not None and out['entry'] is not None:
            if x['intended_direction']=='LONG' and not out[k]>out['entry']:raise ContractError('INVALID_LONG_TP')
            if x['intended_direction']=='SHORT' and not out[k]<out['entry']:raise ContractError('INVALID_SHORT_TP')
    out['price_source']='MT5_PRIMARY'
    out['quote_side']=plan.get('quote_side') if plan.get('quote_side') in {'BID','ASK'} else None
    out['plan_status']=plan.get('plan_status') if plan.get('plan_status') in {'ILLUSTRATIVE','CONDITIONAL','COMPLETE'} else 'ILLUSTRATIVE'
    out['as_of']=utc_iso(plan.get('as_of',x['as_of']))
    if out['as_of']>utc_iso(x['as_of']):raise ContractError('FUTURE_PLAN_DATA')
    return out


def compose(m14, context=None):
    x=validate_m14(m14)
    c=context or {}
    if not isinstance(c,dict):raise ContractError('CONTEXT_OBJECT_REQUIRED')
    if c.get('analysis_id',x['analysis_id'])!=x['analysis_id']:
        raise ContractError('ANALYSIS_ID_MISMATCH')
    if c.get('snapshot_as_of') and utc_iso(c['snapshot_as_of'])!=utc_iso(x['as_of']):
        raise ContractError('SNAPSHOT_AS_OF_MISMATCH')
    inst=c.get('instrument_id')
    if inst is not None and (not isinstance(inst,str) or not inst.strip()):raise ContractError('INVALID_INSTRUMENT')
    if c.get('account_type') not in (None,'ZERO_SPREAD'):raise ContractError('ACCOUNT_TYPE_CONFLICT')
    quote=c.get('quote')
    if quote is not None:
        if not isinstance(quote,dict) or quote.get('source')!='MT5_PRIMARY':
            raise ContractError('BROKER_QUOTE_ONLY')
        if quote.get('instrument_id')!=inst or utc_iso(quote.get('as_of'))>utc_iso(x['as_of']):
            raise ContractError('QUOTE_MISMATCH_OR_FUTURE')
        bid,ask=number_or_none(quote.get('bid')),number_or_none(quote.get('ask'))
        if bid is None or ask is None or bid<=0 or ask<bid:raise ContractError('INVALID_BID_ASK')
        quote={'source':'MT5_PRIMARY','as_of':utc_iso(quote['as_of']),'bid':bid,'ask':ask,
               'spread':ask-bid, 'instrument_id':inst}
    plan=normalized_plan(c,x)
    probs=x.get('probabilities')
    if isinstance(probs,dict):
        # Do not turn statistical/probability wrappers into bare percentages.
        probs=json.loads(json.dumps(probs,allow_nan=False))
    payload={
      'module_id':'M15','module_version':VERSION,'schema_version':'2.0.0',
      'synthetic_example':x['analysis_id'].upper().startswith(('SYNTHETIC','EXAMPLE_','TEST_')), 
      'prompt_version':c.get('prompt_version','4.1.0'),
      'analysis_id':x['analysis_id'],'as_of':utc_iso(x['as_of']),
      'mode':c.get('mode'), 'run_status':'COMPLETED', 'status':'PASS_WITH_LIMITATIONS',
      'evidence_ids':c.get('evidence_ids', []),
      'data_source_policy':POLICY,'screenshot_capture_enabled':False,
      'decision_scope':'ANALYSIS','decision':x['decision'],
      'intended_direction':x.get('intended_direction','UNKNOWN'),
      'directional_bias':x.get('directional_bias','UNKNOWN'),
      'signal_validity':x.get('signal_validity','UNKNOWN'),
      'signal_tier':x.get('signal_tier','NONE'),
      'entry_status':x.get('entry_status','NOT_READY'),
      'entry_trigger':x.get('entry_trigger','UNKNOWN'),
      'top_setup_id':x.get('top_setup_id'), 'horizon_id':x.get('horizon_id'),
      'top_early_setup_id':c.get('top_early_setup_id'),
      'top_conditional_setup_id':c.get('top_conditional_setup_id'),
      'top_confirmed_setup_id':c.get('top_confirmed_setup_id'),
      'execution_environment':x.get('execution_environment','ANALYSIS_ONLY'),
      'execution_permission':'BLOCKED','execution_eligible':False,
      'live_execution_allowed':False,'submitted_order_id':None,
      'broker_order_sent':False,'order_actions':[],
      'preliminary_execution_readiness':x.get('preliminary_execution_readiness'),
      'execution_blockers':x.get('execution_blockers') or ['TRUSTED_AUTHORIZATION_AND_EXECUTOR_ABSENT'],
      'reason_codes':x.get('reason_codes',[]),
      'gates':x.get('gates',[]),'setup_score':x.get('setup_score'),
      'probabilities':probs,'probability_policy':c.get('probability_policy','EVIDENCE_ONLY'),
      'direction_score':c.get('direction_score'),
      'direction_confidence':c.get('direction_confidence', 'UNKNOWN'),
      'market_map':c.get('market_map'),
      'early_entry_map':c.get('early_entry_map'),
      'data_snapshot':c.get('data_snapshot'),
      'instrument_id':inst,'account_type':c.get('account_type'),
      'quote':quote,'plan':plan,
      'next_expected_event':clean_text(c.get('next_expected_event'),240),
      'invalidation':clean_text(c.get('invalidation'),240),
      'opposite_scenario':clean_text(c.get('opposite_scenario'),240),
      'data_limitations':[clean_text(t,150) for t in c.get('data_limitations',[])][:20],
      'active_setups':c.get('active_setups',[]),
      'early_setups':c.get('early_setups',[]),
      'conditional_setups':c.get('conditional_setups',[]),
      'confirmed_setups':c.get('confirmed_setups',[]),
      'invalidated_setups':c.get('invalidated_setups',[]),
      'signal_change_log':c.get('signal_change_log',[]),
      'signal_frequency_control':c.get('signal_frequency_control',{}),
      'capabilities':c.get('capabilities',{}),
      'config_version':c.get('config_version'),
      'market_state':c.get('market_state'), 'evidence':c.get('evidence',[]),
      'historical':c.get('historical'), 'validation':c.get('validation'),
      'registry':c.get('registry'), 'router':c.get('router'), 'setup':c.get('setup'),
      'risk':c.get('risk'), 'monitoring':c.get('monitoring'),
      'persistence_status':'LOCAL_FILE_AND_SQLITE_ON_RUN',
      'delivery_status':'NOT_SENT','limitations':c.get('limitations',[]),
      'migration_warnings':[],
      'original_m14':x
    }
    if payload['decision'] in {'EARLY_SETUP','CONDITIONAL_SETUP'}:
        if not payload['next_expected_event'] or not payload['invalidation']:
            # M14 alone does not contain these narrative fields. Fail rather than invent.
            raise ContractError('EARLY_CONTEXT_REQUIRES_NEXT_EVENT_AND_INVALIDATION')
    for name in ('active_setups','early_setups','conditional_setups','confirmed_setups','invalidated_setups'):
        if not isinstance(payload[name],list):raise ContractError('SETUP_COLLECTION_MUST_BE_LIST:'+name)
    if payload['top_setup_id'] and payload['active_setups']:
        ids={s.get('setup_id') for s in payload['active_setups'] if isinstance(s,dict)}
        if payload['top_setup_id'] not in ids:raise ContractError('TOP_NOT_IN_ACTIVE_SETUPS')
    # Context passed by an upstream integration layer is informational only:
    # M15 does not authenticate it and never elevates the execution scope.
    json.dumps(payload,allow_nan=False)
    return payload


def short_report(p):
    dec=p['decision'];direction=p['intended_direction']
    status={'LONG':'POTWIERDZONY LONG','SHORT':'POTWIERDZONY SHORT','EARLY_SETUP':'WCZESNY SETUP',
            'CONDITIONAL_SETUP':'SETUP WARUNKOWY','WAIT':'OCZEKIWANIE','NO_TRADE':'BRAK TRANSAKCJI'}[dec]
    a=[f"MASTERQUO | {status}",f"Instrument: {clean_text(p.get('instrument_id') or 'N/D',60)}",
       f"Kierunek: {direction} | Horyzont: {clean_text(p.get('horizon_id') or 'N/D',60)}",
       f"Faza: {p['signal_tier']} | As-of: {p['as_of']}",
       f"Setup: {clean_text(p.get('top_setup_id') or 'N/D',80)}"]
    if p.get('synthetic_example'):
        a.insert(0,'[PRZYKŁAD SYNTETYCZNY — NIE JEST SYGNAŁEM RYNKOWYM]')
    pl=p.get('plan')
    if pl:
        def fmt(k):
            v=pl.get(k)
            return f'{v:.5f}'.rstrip('0').rstrip('.') if isinstance(v,(int,float)) else 'N/D'
        a.append(f"Entry: {fmt('entry')} | SL: {fmt('sl')}")
        a.append(f"TP1: {fmt('tp1')} | TP2: {fmt('tp2')} | TP3: {fmt('tp3')}")
        a.append(f"Plan: {pl['plan_status']} | Cena: MT5")
    if p['next_expected_event']:a.append('Następny warunek: '+p['next_expected_event'])
    if p['invalidation']:a.append('Unieważnienie: '+p['invalidation'])
    a.extend([f"Wykonanie: {p['execution_permission']} (brak autoryzacji zlecenia)",
              'To alert analityczny, NIE potwierdzenie otwarcia pozycji.'])
    if p['execution_blockers']:
        a.append('Blokady: '+', '.join(clean_text(t,55) for t in p['execution_blockers'][:3]))
    msg='\n'.join(a)
    if len(msg)>3400:msg=msg[:3390]+'…'
    return msg


def full_report(p):
    """All 18 canonical report sections. Unknown upstream sections are labeled N/D."""
    sections=[
      ('ACTIVE MARKET MAP + ACTIVE SETUPS', ['market_map','active_setups']),
      ('DATA AUDIT', ['data_snapshot','quote','account_type','data_limitations']),
      ('MARKET SNAPSHOT', ['market_state']),
      ('MTF STRUCTURE', ['market_map']),
      ('STRUCTURE & LIQUIDITY', ['evidence']),
      ('SMC/POI', ['evidence']),
      ('PRICE ACTION + FLOW', ['evidence']),
      ('TRAPS + MACRO', ['market_state']),
      ('HISTORICAL INTELLIGENCE', ['historical']),
      ('VALIDATION', ['validation']),
      ('STRATEGY INTELLIGENCE', ['registry','router']),
      ('DECISION TREE / EVIDENCE AGREEMENT', ['gates']),
      ('SCORE / CONFIDENCE', ['setup_score','direction_score','direction_confidence','probabilities']),
      ('TRADE PLAN', ['plan','next_expected_event','invalidation']),
      ('RISK', ['risk','execution_blockers']),
      ('WHY THIS TRADE COULD FAIL', ['limitations','data_limitations']),
      ('ALTERNATIVE SCENARIO', ['opposite_scenario']),
      ('FINAL DECISION', ['decision','intended_direction','signal_validity','execution_permission'])
    ]
    out=[short_report(p),'','--- PEŁNY RAPORT M15 / TYKO PRZEKAZANE DANE ---']
    for i,(title,keys) in enumerate(sections,1):
        out.extend(['',f'{i}. {title}'])
        seen=False
        for key in keys:
            v=p.get(key)
            if v is None or v==[] or v=={} or v=='UNKNOWN':continue
            seen=True
            if key=='probabilities':
                out.append('  probabilities: metoda i horyzont w JSON; M15 nie przelicza procentów')
            else:
                if isinstance(v,(dict,list)):
                    compact=json.dumps(v,ensure_ascii=False,default=str)
                    out.append(f'  {key}: {compact[:1500]}' + (' [skrócono — pełny JSON]' if len(compact)>1500 else ''))
                else:out.append(f'  {key}: {clean_text(v,500)}')
        if not seen:out.append('  N/D — brak źródłowych danych dla tej sekcji')
    out.append('')
    out.append('UWAGA: brak autoryzacji transakcji; kompletne dane i uwierzytelnienie wymagają integracji.')
    return '\n'.join(out)


def atomic_json(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=path.parent,delete=False, suffix='.tmp') as f:
        tmp=Path(f.name);json.dump(obj,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
    try:os.replace(tmp,path)
    finally:
        if tmp.exists():tmp.unlink()


def event_fingerprint(p,event_id=None):
    # as_of not included; repeated same content does not generate a second event.
    material={'setup':p.get('top_setup_id'),'decision':p['decision'],
              'direction':p['intended_direction'],'tier':p['signal_tier'],
              'trigger':p['entry_trigger'],'validity':p['signal_validity'],
              'invalidation':p.get('invalidation'),'next':p.get('next_expected_event'),
              'plan':p.get('plan'),'blockers':p.get('execution_blockers'),
              'event_id':event_id}
    b=json.dumps(material,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')
    return hashlib.sha256(b).hexdigest()


class Outbox:
    def __init__(self,path):
        self.con=sqlite3.connect(path)
        self.con.execute('PRAGMA journal_mode=WAL')
        self.con.execute('''CREATE TABLE IF NOT EXISTS alerts(
          channel TEXT NOT NULL, fingerprint TEXT NOT NULL, analysis_id TEXT NOT NULL,
          setup_id TEXT, payload TEXT NOT NULL, status TEXT NOT NULL,
          created_at TEXT NOT NULL, attempted_at TEXT, remote_message_id TEXT,
          PRIMARY KEY(channel,fingerprint))''')
        self.con.commit()
    def queue(self,p,event_id=None,channel='TELEGRAM'):
        if p['decision'] in ('WAIT','NO_TRADE') and not event_id:
            # Event-only news and NO_TRADE suppress high-frequency ordinary snapshots.
            return ('SUPPRESSED_NON_SIGNAL',None)
        fp=event_fingerprint(p,event_id)
        try:
            with self.con:
                self.con.execute('INSERT INTO alerts(channel,fingerprint,analysis_id,setup_id,payload,status,created_at) VALUES(?,?,?,?,?,?,?)',
                    (channel,fp,p['analysis_id'],p['top_setup_id'],short_report(p),'PENDING',datetime.now(timezone.utc).isoformat()))
        except sqlite3.IntegrityError:
            return ('DUPLICATE_SUPPRESSED',fp)
        return ('QUEUED',fp)
    def get(self,fp,channel='TELEGRAM'):
        return self.con.execute('SELECT status,payload FROM alerts WHERE channel=? AND fingerprint=?',(channel,fp)).fetchone()
    def begin_send(self,fp,channel='TELEGRAM'):
        with self.con:
            cur=self.con.execute("UPDATE alerts SET status='SENDING', attempted_at=? WHERE channel=? AND fingerprint=? AND status='PENDING'",
                (datetime.now(timezone.utc).isoformat(),channel,fp))
        return cur.rowcount==1
    def result(self,fp,status,remote_message_id=None,channel='TELEGRAM'):
        if status not in {'DELIVERED','UNKNOWN','REJECTED'}:raise ValueError('bad status')
        with self.con:
            self.con.execute("UPDATE alerts SET status=?,remote_message_id=? WHERE channel=? AND fingerprint=? AND status='SENDING'",
                (status,str(remote_message_id) if remote_message_id is not None else None,channel,fp))
    def close(self):self.con.close()


def send_telegram(text, token,chat_id):
    if not token or not chat_id:raise ContractError('TELEGRAM_ENV_NOT_CONFIGURED')
    if len(text)>4096:raise ContractError('TELEGRAM_TEXT_TOO_LONG')
    data=json.dumps({'chat_id':chat_id,'text':text,'disable_web_page_preview':True}).encode('utf-8')
    req=request.Request('https://api.telegram.org/bot'+token+'/sendMessage',data=data,
                        headers={'Content-Type':'application/json'},method='POST')
    # Calling send_telegram is only permitted from explicit CLI --telegram-send.
    with request.urlopen(req,timeout=8) as res:
        obj=json.loads(res.read(20000).decode('utf-8'))
    if obj.get('ok') is not True:raise RuntimeError('TELEGRAM_API_REJECTED')
    return obj.get('result',{}).get('message_id')


def run_cli(argv=None):
    ap=argparse.ArgumentParser(description='M15 output processor; no MT5 execution')
    ap.add_argument('--m14',required=True,help='M14 result JSON')
    ap.add_argument('--context',help='optional integration context JSON')
    ap.add_argument('--output-dir',default='./m15_output')
    ap.add_argument('--telegram-send',action='store_true',help='explicit opt-in network send of analysis alert')
    ap.add_argument('--event-id',help='distinct trusted lifecycle revision/id for alert changes')
    args=ap.parse_args(argv)
    try:
        m14=json.loads(Path(args.m14).read_text(encoding='utf-8'))
        context=json.loads(Path(args.context).read_text(encoding='utf-8')) if args.context else None
        payload=compose(m14,context)
        out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=True)
        atomic_json(out/'M15_EXPORT_FULL.json',payload)
        atomic_json(out/'M15_MONITOR_SNAPSHOT.json',{k:v for k,v in payload.items() if k!='original_m14'})
        (out/'M15_COMPACT_PL.txt').write_text(short_report(payload)+'\n',encoding='utf-8')
        (out/'M15_FULL_PL.txt').write_text(full_report(payload)+'\n',encoding='utf-8')
        db=Outbox(out/'M15_DELIVERY_OUTBOX.sqlite3')
        try:
            state,fp=db.queue(payload,args.event_id)
            if args.telegram_send and state=='QUEUED' and payload['synthetic_example']:
                state='SUPPRESSED_SYNTHETIC'
            elif args.telegram_send and state=='QUEUED':
                if not os.getenv('TELEGRAM_BOT_TOKEN') or not os.getenv('TELEGRAM_CHAT_ID'):
                    state='QUEUED_MISSING_ENV'
                elif db.begin_send(fp):
                    try:
                        message_id=send_telegram(short_report(payload),os.environ['TELEGRAM_BOT_TOKEN'],os.environ['TELEGRAM_CHAT_ID'])
                        db.result(fp,'DELIVERED',message_id);state='DELIVERED'
                    except error.HTTPError as exc:
                        # HTTP 4xx is deterministic reject; 5xx may have been delivered.
                        db.result(fp,'REJECTED' if 400<=exc.code<500 else 'UNKNOWN')
                        state='REJECTED' if 400<=exc.code<500 else 'UNKNOWN'
                    except Exception:
                        db.result(fp,'UNKNOWN');state='UNKNOWN'
            atomic_json(out/'M15_LAST_DELIVERY_STATUS.json',{'delivery_status':state,
                       'channel':'TELEGRAM','message_fingerprint':fp,'auto_retry':False,
                       'execution_permission':'BLOCKED'})
        finally:db.close()
        print('M15_OK',state,'(no broker orders)',str(out))
        return 0
    except (OSError,ValueError,TypeError,json.JSONDecodeError) as exc:
        print('M15_BLOCKED:',str(exc),file=sys.stderr);return 2

if __name__=='__main__':raise SystemExit(run_cli())
