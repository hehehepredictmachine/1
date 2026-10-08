#!/usr/bin/env python3
"""M04N->M04/M11/M14/M15 fail-closed, read-only macro overlay.

Collector M04N and MT5/M15 producer remain separate processes. This tool
never writes into their source output or issues orders. No prediction/BUY/SELL.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/'vendor'/'M04'))
sys.path.insert(0, str(ROOT/'vendor'/'M11'))
sys.path.insert(0, str(ROOT/'vendor'/'M15'))
from M04_REFERENCE_ENGINE import calendar_context  # existing M04 engine, unmodified
from M11_REFERENCE_ENGINE import evaluate as m11_evaluate, result_base as m11_result_base
from M15_REFERENCE_COMMUNICATION_ENGINE import validate_m14, send_telegram, clean_text

VERSION='1.0.0-CANDIDATE'
WINDOWS={'LOW':{'pre':0,'post':0},'MEDIUM':{'pre':10,'post':5},
         'HIGH':{'pre':45,'post':30},'EXTREME':{'pre':60,'post':45}}
SOURCE_POLICY='MT5_PRIMARY_TV_SUPPLEMENTAL_NO_SCREENSHOTS'


def utc(v):
    if not isinstance(v,str):raise ValueError('TIME_INVALID')
    d=datetime.fromisoformat(v.replace('Z','+00:00'))
    if d.tzinfo is None or d.utcoffset() is None:raise ValueError('TIMEZONE_MISSING')
    return d.astimezone(timezone.utc)

def stamp(d):return d.isoformat().replace('+00:00','Z')
def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()

def load_optional(path):
    try:
        if path is None:return None
        obj=json.loads(Path(path).read_text(encoding='utf-8'))
        return obj if isinstance(obj,dict) else None
    except (ValueError,OSError,UnicodeError):return None

def atomic(path,obj):
    path=Path(path);path.parent.mkdir(exist_ok=True,parents=True)
    temp=path.with_name(path.name+'.tmp')
    temp.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    os.replace(temp,path)

def _validate_sources(feed,bridge,now,max_age):
    if not isinstance(feed,dict) or not isinstance(bridge,dict):return ['M04N_REPORTS_MISSING']
    errors=[]
    if (feed.get('module_id')!='M04N' or bridge.get('module_id')!='M04N'
            or feed.get('schema_version')!='2.0.0'):
        errors.append('M04N_ID_SCHEMA_INVALID')
    if (feed.get('execution_permission')!='BLOCKED' or feed.get('research_only') is not True
            or feed.get('visual_capture_enabled') is not False
            or (bridge.get('advisory') or {}).get('execution_permission')!='BLOCKED'
            or (bridge.get('advisory') or {}).get('does_not_override_m04_m11_m14') is not True):
        errors.append('M04N_AUTHORITY_VIOLATION')
    if feed.get('status') not in ('HEALTHY','PARTIAL','UNAVAILABLE'):
        errors.append('M04N_STATE_INVALID')
    try:
        ft=utc(feed['as_of']);bt=utc(bridge['as_of'])
        if ft != bt:errors.append('M04N_REPORT_TIME_MISMATCH')
        if not 0<=(now-ft).total_seconds()<=max_age:errors.append('M04N_FEED_STALE_OR_FUTURE')
    except (ValueError,TypeError,KeyError,OverflowError):errors.append('M04N_TIME_INVALID')
    ctx=bridge.get('context_inputs')
    if not isinstance(ctx,dict):errors.append('M04N_CONTEXT_MISSING');return errors
    cov=ctx.get('calendar_coverage')
    if not isinstance(cov,dict) or cov.get('status') not in ('PARTIAL','UNAVAILABLE') or cov.get('data_complete') is not False:
        errors.append('M04N_FALSE_FULL_CALENDAR_COVERAGE')
    if not isinstance(ctx.get('macro_events'),list):errors.append('M04N_MACRO_EVENTS_INVALID')
    if (not isinstance(feed.get('calendar'),dict) or
        not isinstance(feed.get('integrity'),dict)):
        errors.append('M04N_INTEGRITY_MISSING')
    return errors

def _calendar_cross_check(feed,bridge):
    """Reject invented or altered bridge events. Match only facts in contemporaneous feed."""
    events=(bridge.get('context_inputs') or {}).get('macro_events',[])
    feed_ev=(feed.get('calendar') or {}).get('events',[])
    if not isinstance(events,list) or not isinstance(feed_ev,list):return False
    canon={x.get('event_id'):x for x in feed_ev if isinstance(x,dict) and x.get('event_id')}
    if len(events)>150 or len(events)!=len({x.get('event_id') for x in events if isinstance(x,dict)}):return False
    for e in events:
        if not isinstance(e,dict) or not isinstance(e.get('event_id'),str):return False
        f=canon.get(e['event_id'])
        if f is None:return False
        for key in ('scheduled_at','available_at','impact','name','source_id'):
            if e.get(key)!=f.get(key):return False
    return True

def _m14_state(technical,now, max_age=15.0):
    """Read actual M15 output and validate original canonical M14; never forge it."""
    if not isinstance(technical,dict):return None,'M15_REPORT_MISSING'
    try:
        p=utc(technical['m15_published_at'])
        if not 0<=(now-p).total_seconds()<=max_age:return None,'M15_HEARTBEAT_STALE'
        if (technical.get('execution_permission')!='BLOCKED' or
           technical.get('live_execution_allowed') is not False or
           technical.get('broker_order_sent') is not False or
           technical.get('execution_eligible') is not False):return None,'M15_EXECUTION_POLICY_INVALID'
        m14=technical.get('original_m14')
        validate_m14(m14)
        if (technical.get('analysis_id')!=m14.get('analysis_id') or
            technical.get('decision')!=m14.get('decision') or
            utc(technical.get('as_of'))!=utc(m14.get('as_of'))):
            return None,'M14_M15_BINDING_MISMATCH'
        if (technical.get('m10a_connection_status')!='CONNECTED' or
            technical.get('m10a_quote_status')!='RECEIVED'):
            return None,'MT5_DISCONNECTED_OR_QUOTE_STALE'
        return m14,None
    except (ValueError,KeyError,TypeError,OverflowError):return None,'M14_M15_INVALID'

def _advisory_from_m11(now, risk_payload,technical):
    """Run unchanged M11 with supplied actual risk snapshot only. No fake capital/broker inputs."""
    if risk_payload is None:
        out=m11_result_base({'analysis_id':technical.get('analysis_id') if isinstance(technical,dict) else None,
                             'as_of':stamp(now)})
        out['risk_gate_reason']='RISK_PAYLOAD_NOT_PROVIDED'
        return out
    if not isinstance(risk_payload,dict):return {'risk_gate':'BLOCKED','risk_gate_reason':'RISK_PAYLOAD_INVALID','execution_permission':'BLOCKED'}
    if not isinstance(technical,dict) or risk_payload.get('analysis_id')!=technical.get('analysis_id'):
        return {'risk_gate':'BLOCKED','risk_gate_reason':'RISK_ANALYSIS_ID_MISMATCH','execution_permission':'BLOCKED'}
    try:
        if utc(risk_payload['as_of'])!=utc(technical['as_of']):
            return {'risk_gate':'BLOCKED','risk_gate_reason':'RISK_AS_OF_MISMATCH','execution_permission':'BLOCKED'}
        out=m11_evaluate(risk_payload)
        if out.get('execution_permission')!='BLOCKED':raise ValueError('M11_MUST_BLOCK')
        return out
    except (TypeError,ValueError,KeyError,OverflowError):
        return {'risk_gate':'BLOCKED','risk_gate_reason':'M11_INPUT_FAILED','execution_permission':'BLOCKED'}

def build(now,feed,bridge,technical=None,risk_payload=None,*,max_feed_age=900,max_monitor_age=15):
    """Pure deterministic join. Macro may veto, NEVER promote an M14 signal."""
    now=now.astimezone(timezone.utc)
    errs=_validate_sources(feed,bridge,now,max_feed_age)
    if not errs and not _calendar_cross_check(feed,bridge):errs.append('M04N_CONTEXT_PROVENANCE_MISMATCH')
    native=None; active=[]
    if not errs:
        try:
            inputs=bridge['context_inputs']
            native=calendar_context(inputs['macro_events'],now,
                         {'event_windows_minutes':WINDOWS},inputs['calendar_coverage'])
            active=native.get('upcoming',[])
        except (ValueError,TypeError,KeyError,OverflowError,AttributeError):
            errs.append('M04_CALENDAR_CONTEXT_FAILED');native=None;active=[]
    m14,m14_err=_m14_state(technical,now,max_monitor_age)
    risk=_advisory_from_m11(now,risk_payload,technical)
    news=[]
    if not errs:
        for e in (feed.get('news') or {}).get('new_events',[]):
            if not isinstance(e,dict) or e.get('time_quality')!='PUBLISHED' or e.get('impact') not in ('HIGH','EXTREME'):continue
            try:
                elapsed=(now-utc(e.get('published_at'))).total_seconds()
                if not 0<=elapsed<=1800:continue
            except (TypeError,ValueError,OverflowError):continue
            news.append({'event_id':e.get('event_id'),'title':clean_text(e.get('headline') or e.get('title'),170),
                         'impact':e['impact'],'published_at':e['published_at'],'source_id':e.get('source_id')})
    block=bool(errs or native is None or native.get('event_gate')=='BLOCKED' or
               (isinstance(feed,dict) and feed.get('status')=='UNAVAILABLE'))
    gate=('BLOCKED' if block else 'PENDING') # Partial coverage can NEVER generate PASS.
    why=list(errs)
    if native and native.get('event_gate')=='BLOCKED':why.append('HIGH_IMPACT_ECONOMIC_EVENT_WINDOW')
    if isinstance(feed,dict) and feed.get('status')=='UNAVAILABLE':why.append('M04N_ALL_SOURCES_UNAVAILABLE')
    if not why:why.append('PARTIAL_CALENDAR_COVERAGE_NO_GLOBAL_ALL_CLEAR')
    if m14_err:why.append(m14_err)
    if risk.get('risk_gate')!='PASS':why.append('M11_'+str(risk.get('risk_gate_reason')))
    context_ok=(not block and m14_err is None)
    technical_decision=m14.get('decision') if m14 is not None else None
    displayed=('NO_TRADE' if (block or m14_err) else 'WAIT' if technical_decision not in ('WAIT','NO_TRADE') else technical_decision)
    # Guarded status deliberately stays WAIT on partial coverage. Original
    # M14 technical decision is available separately, not overwritten.
    report={
      'module_id':'M04N_MACRO_GUARD','module_version':VERSION,'schema_version':'2.0.0',
      'as_of':stamp(now),'integrity_status':'VALID_PARTIAL' if not errs else 'FAIL_CLOSED',
      'monitor_status':'ACTIVE_DIAGNOSTIC' if m14_err is None else 'MT5_UNVERIFIED',
      'macro_gate':gate,'macro_reason_codes':sorted(set(why)),
      'm04_calendar_context':native if native else {'event_gate':'PENDING','status':'UNAVAILABLE','event_risk':'UNKNOWN'},
      'm11_risk_gate':risk.get('risk_gate','BLOCKED'),
      'm11_risk_reason':risk.get('risk_gate_reason'),
      'm14_original_decision':technical_decision,
      'm14_analysis_id':m14.get('analysis_id') if m14 else None,
      'guarded_display_decision':displayed,
      'macro_context_usable':context_ok,'market_setup_validated':False,
      'macro_calendar_coverage':'PARTIAL_NEVER_ALL_CLEAR',
      'source_health':(feed.get('integrity') or {}).get('source_health',{}) if not errs else {},
      'feed_status':feed.get('status') if not errs else 'UNAVAILABLE',
      'macro_active_events':active[:30] if not errs else [],
      'macro_new_high_impact_news':news[:15] if not errs else [],
      'macro_topics':(feed.get('interpretation') or {}).get('detected_topics',[])[:25] if not errs else [],
      'technical_indicator_timeframes':(technical.get('indicator_timeframes') or {}) if m14_err is None else {},
      'quote_source':'MT5_PRIMARY_ONLY','news_is_not_directional_signal':True,
      'telegram_send_default':False,'telegram_scope':'MACRO_RISK_WARNING_ONLY',
      'execution_permission':'BLOCKED','execution_eligible':False,
      'live_execution_allowed':False,'broker_order_sent':False,
      'submitted_order_id':None,'order_actions':[],
      'limitations':['NO_MARKET_EDGE_VALIDATION','NO_TRADE_AUTHORITY',
        'FOREX_FACTORY_METALS_MINE_CORRELATED_CALENDARS','PARTIAL_MACRO_CALENDAR',
        'REAL_MT5_DEMO_AND_NEWS_ENDPOINT_TESTS_NOT_PERFORMED'],
    }
    return report


class MacroAlertStore:
    """At-most-once STARTED attempt per alert, with baseline suppression."""
    def __init__(self,path):
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(str(path),timeout=20,isolation_level=None)
        self.db.execute('CREATE TABLE IF NOT EXISTS lifecycle(key TEXT PRIMARY KEY, first_seen TEXT NOT NULL, last_active INTEGER NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS sent(key TEXT PRIMARY KEY, state TEXT NOT NULL, attempted_at TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT)')
    def observe(self,report):
        """Returns new alert ids only upon transition from inactive to active.
        First successful active observation is baseline; no retrospective spam.
        """
        if report.get('integrity_status')!='VALID_PARTIAL':return []
        now=report['as_of']
        observed={}
        for e in report.get('macro_active_events',[]):
            if e.get('impact') not in ('HIGH','EXTREME'):continue
            key='CAL:'+str(e.get('event_id'))+':'+str(e.get('scheduled_at'))
            observed[key]={'kind':'CALENDAR','event':e}
        for e in report.get('macro_new_high_impact_news',[]):
            if not e.get('event_id'):continue
            key='NEWS:'+str(e['event_id'])
            observed[key]={'kind':'NEWS','event':e}
        self.db.execute('BEGIN IMMEDIATE')
        try:
            baseline=self.db.execute("SELECT value FROM meta WHERE key='BASELINED'").fetchone()
            if baseline is None:
                for key in observed:
                    self.db.execute('INSERT OR IGNORE INTO lifecycle VALUES(?,?,1)',(key,now))
                self.db.execute("INSERT INTO meta VALUES('BASELINED',?)",(now,))
                self.db.execute('COMMIT');return []
            self.db.execute('UPDATE lifecycle SET last_active=0')
            new=[]
            for key,data in observed.items():
                row=self.db.execute('SELECT last_active FROM lifecycle WHERE key=?',(key,)).fetchone()
                if row is None:
                    self.db.execute('INSERT INTO lifecycle VALUES(?,?,1)',(key,now));new.append((key,data))
                else:
                    self.db.execute('UPDATE lifecycle SET last_active=1 WHERE key=?',(key,))
                    # A previously seen, expired risk does not regenerate a notification.
            self.db.execute('COMMIT')
            return new
        except BaseException:
            self.db.execute('ROLLBACK');raise
    def claim(self,key,now):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            if self.db.execute('SELECT key FROM sent WHERE key=?',(key,)).fetchone():
                self.db.execute('COMMIT');return False
            self.db.execute('INSERT INTO sent VALUES(?,?,?)',(key,'UNKNOWN_STARTED',now))
            self.db.execute('COMMIT');return True
        except BaseException:self.db.execute('ROLLBACK');raise
    def result(self,key,state):
        self.db.execute('UPDATE sent SET state=? WHERE key=?',(state,key))
    def close(self):self.db.close()


def alert_text(detail):
    kind=detail['kind'];e=detail['event']
    if kind=='CALENDAR':
        label=clean_text(e.get('name') or 'Wydarzenie makro',180)
        when=clean_text(e.get('scheduled_at'),45)
        text=f'MASTERQUO | RYZYKO MAKRO {e.get("impact")}\n{label}\nTermin UTC: {when}'
    else:
        text=f'MASTERQUO | NOWA WIADOMOŚĆ MAKRO {e.get("impact")}\n{clean_text(e.get("title"),180)}'
    return text+'\nUwaga: nie jest to sygnał LONG/SHORT. Handel pozostaje zablokowany.'


def step(now,feed,bridge,technical,output,risk_payload=None,alert_store=None,telegram=False,sender=None):
    report=build(now,feed,bridge,technical,risk_payload)
    delivery={'status':'DISABLED','events_found':0,'attempted':0}
    if alert_store is not None:
        fresh=alert_store.observe(report)
        delivery={'status':'DRY_RUN' if not telegram else 'ENABLED','events_found':len(fresh),'attempted':0}
        if telegram and fresh:
            token=os.getenv('TELEGRAM_BOT_TOKEN');chat=os.getenv('TELEGRAM_CHAT_ID')
            if not token or not chat:
                delivery['status']='MISSING_CREDENTIALS'
            else:
                for key,detail in fresh:
                    if not alert_store.claim(key,report['as_of']):continue
                    delivery['attempted']+=1
                    try:
                        (sender or send_telegram)(alert_text(detail),token,chat)
                        alert_store.result(key,'DELIVERED')
                    except Exception:
                        alert_store.result(key,'UNKNOWN_NO_AUTOMATIC_RETRY')
                        delivery['status']='UNKNOWN_DELIVERY'
    report['delivery']=delivery
    atomic(output,report)
    return report


def main(argv=None):
    ap=argparse.ArgumentParser(description='MasterQUO M04N/M04/M11/M14/M15 macro guard (READ ONLY)')
    runtime=ROOT/'runtime'; mr=runtime/'M04N'
    ap.add_argument('--intelligence',default=str(mr/'M04N_INTELLIGENCE.json'))
    ap.add_argument('--context',default=str(mr/'M04N_M04_CONTEXT_BRIDGE.json'))
    ap.add_argument('--technical',default=str(runtime/'M15'/'M15_MONITOR_SNAPSHOT.json'))
    ap.add_argument('--risk-input',default=None,help='optional real aligned M11 risk payload')
    ap.add_argument('--output',default=str(runtime/'M04N_GUARDED_MONITOR.json'))
    ap.add_argument('--state-db',default=str(runtime/'M04N_GUARD_ALERTS.sqlite'))
    ap.add_argument('--poll',type=float,default=3.0)
    ap.add_argument('--once',action='store_true')
    ap.add_argument('--telegram-send',action='store_true',help='explicit opt-in macro warnings only')
    args=ap.parse_args(argv)
    if not 1<=args.poll<=3600:ap.error('poll must be from 1 to 3600 seconds')
    db=MacroAlertStore(args.state_db)
    try:
        while True:
            now=datetime.now(timezone.utc)
            report=step(now,load_optional(args.intelligence),load_optional(args.context),
                 load_optional(args.technical),args.output,load_optional(args.risk_input),db,args.telegram_send)
            print(report['as_of'],'MACRO',report['macro_gate'],'M14',report['m14_original_decision'],
                  'DISPLAY',report['guarded_display_decision'],'ALERT',report['delivery']['status'],flush=True)
            if args.once:break
            time.sleep(args.poll)
    except KeyboardInterrupt:pass
    finally:db.close()
    return 0

if __name__=='__main__':raise SystemExit(main())
