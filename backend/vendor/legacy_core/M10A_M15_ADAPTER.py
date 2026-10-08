"""M10A to M15: read-only snapshot and material lifecycle event delivery.

No MT5 login, no trading orders, no screenshots; upstream M10A is owner of
setup state and M14 is owner of analysis decision. Output is *never* a grant.
Telegram is explicit opt-in and at-most-once attempted using M15 outbox; any
unknown send remains UNKNOWN, never automatically retried.
"""
from __future__ import annotations
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sys
from urllib import error

BASE=Path(__file__).resolve().parent
sys.path.insert(0,str(BASE/'vendor'/'M15'))
from M15_REFERENCE_COMMUNICATION_ENGINE import (
    compose, validate_m14, short_report, full_report, atomic_json,
    Outbox, ContractError, send_telegram, utc_iso,
)

MATERIAL={'CORE_READY','DEVELOPMENT','QUALIFY','ARM','TRIGGER','CONFIRM',
          'INVALIDATE','EXPIRE','CANCEL','MISS_ENTRY','MISSED_ENTRY'}
LIVE_STATES={'EARLY_SETUP','SETUP_FORMING','QUALIFIED','ARMED','TRIGGERED','CONFIRMED'}
TERMINAL_STATES={'INVALIDATED','EXPIRED','CANCELLED','MISSED_ENTRY'}
SOURCE_POLICY='MT5_PRIMARY_TV_SUPPLEMENTAL_NO_SCREENSHOTS'


def digest(v):
    return hashlib.sha256(json.dumps(v,sort_keys=True,ensure_ascii=False,
        separators=(',',':'),allow_nan=False).encode('utf-8')).hexdigest()


def safe_stamp(report):
    for key in ('as_of','published_at'):
        v=report.get(key)
        try:
            return utc_iso(v)
        except (TypeError,ValueError):
            pass
    # Genuine local publication timestamp, not an invented market observation.
    return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')


def connected_data(report):
    return (report.get('monitor_connection_status')=='CONNECTED'
            and report.get('monitor_quote_status')=='RECEIVED'
            and report.get('data_gate') in {'PASS','PASS_WITH_LIMITATIONS'}
            and report.get('schema_version')=='2.0.0'
            and report.get('screen_capture_count')==0
            and report.get('visual_capture_enabled') is False
            and report.get('research_only') is True
            and report.get('account_profile')=='ZERO_SPREAD_DECLARED_UNVERIFIED')


def _canonical_fallback(report, reason):
    """Fail-closed display when M14 output/MT5 data are unavailable."""
    ts=safe_stamp(report)
    aid=report.get('analysis_id')
    if not isinstance(aid,str) or not aid.strip() or len(aid)>160:
        aid='LOCAL_HEALTH_'+digest([ts,reason,report.get('snapshot_id')])[:20]
    return {'module_id':'M14','module_version':'1.0.0-FAIL_CLOSED_DISPLAY',
        'schema_version':'2.0.0','analysis_id':aid,'as_of':ts,
        'decision_scope':'ANALYSIS','decision':'NO_TRADE','signal_tier':'NONE',
        'signal_validity':'INSUFFICIENT_EVIDENCE','intended_direction':'UNKNOWN',
        'entry_status':'NOT_READY','entry_trigger':'NOT_CONFIRMED',
        'top_setup_id':None,'horizon_id':None,'execution_environment':'ANALYSIS_ONLY',
        'execution_permission':'BLOCKED','execution_eligible':False,
        'live_execution_allowed':False,'submitted_order_id':None,'order_actions':[],
        'broker_order_sent':False,'data_source_policy':SOURCE_POLICY,
        'screenshot_capture_enabled':False,'visual_capture_enabled':False,
        'ocr_enabled':False,'probabilities':None,'execution_blockers':[reason],
        'reason_codes':[reason],'gates':[]}


def _record(report):
    auto=report.get('auto_trigger') or {}
    if (isinstance(auto,dict) and auto.get('status')=='PASS_WITH_LIMITATIONS'
        and isinstance(auto.get('validated_record'),dict)):
        return auto['validated_record']
    m10=report.get('m10_result') or {}
    if isinstance(m10,dict) and isinstance(m10.get('setup'),dict):
        return m10['setup']
    return None


def _material_event(report):
    """Event id only from an M10 state log + matching final revision/state.

    May be called again after restart. M15 Outbox handles duplicate event
    fingerprints; do not generate an event from a new quote alone.
    """
    r=_record(report)
    if not r or not isinstance(r.get('change_log'),list) or not r['change_log']:
        return None
    last=r['change_log'][-1]
    if not isinstance(last,dict) or last.get('reason') not in MATERIAL:
        return None
    if not r.get('setup_id') or not isinstance(r.get('revision'),int):return None
    if r.get('state') not in LIVE_STATES|TERMINAL_STATES:return None
    # Last transition must describe current state and exact M10 revision.
    if last.get('to_state',last.get('new_state')) != r.get('state'):
        return None
    if last.get('revision') not in (None,r['revision']):return None
    return (f"{r['setup_id']}|{r['revision']}|{r['state']}|"
            f"{last.get('event_id','')}|{last['reason']}")


def _rule_text(rule):
    if not isinstance(rule,dict):return None
    tf=rule.get('timeframe')
    expr=rule.get('criterion') if 'criterion' in rule else rule.get('condition')
    if not isinstance(tf,str) or not isinstance(expr,dict):return None
    typ=expr.get('field') or expr.get('quote_field')
    op=expr.get('operator') or expr.get('op')
    value=expr.get('level',expr.get('value'))
    if not isinstance(typ,str) or not isinstance(op,str):return None
    if isinstance(value,(int,float)) and not isinstance(value,bool):
        val=str(value)
    elif isinstance(expr.get('reference_evidence_id'),str):
        val='ref '+expr['reference_evidence_id'][:60]
    else:
        return None
    return f'{tf}: {typ} {op} {val} (warunek strategii)'


def _quote_context(report, m14):
    b=report.get('broker_quote')
    if not isinstance(b,dict) or b.get('source')!='MT5_BROKER':return None
    if b.get('symbol') not in (report.get('exact_symbol'),report.get('symbol'),'XAUUSD','XAUUSDm'):
        # Some broker symbols have nonstandard suffixes. Do not guess.
        return None
    try:
        qt=utc_iso(b.get('source_timestamp'))
        if qt>utc_iso(m14['as_of']):return None
        bid,ask=b.get('bid'),b.get('ask')
        if isinstance(bid,bool) or isinstance(ask,bool) or not isinstance(bid,(int,float)) or not isinstance(ask,(int,float)):
            return None
        if not (0<bid<=ask):return None
        return {'source':'MT5_PRIMARY','instrument_id':'XAUUSD','as_of':qt,'bid':bid,'ask':ask}
    except (ValueError,TypeError):
        return None


def convert(report):
    """Return (M15 canonical export, lifecycle event or None, readiness reason).

    Doesn't authenticate external JSON. Intended to be called only with the
    in-process output of M10A publish, never an arbitrary incoming webhook.
    """
    if not isinstance(report,dict):raise ContractError('M10A_REPORT_OBJECT_REQUIRED')
    healthy=connected_data(report)
    raw=report.get('decision_result')
    reason='MT5_DATA_UNAVAILABLE_OR_UNVERIFIED'
    if healthy and isinstance(raw,dict):
        try:
            validate_m14(raw)
            if (raw['analysis_id']!=report.get('analysis_id')
                or utc_iso(raw['as_of'])!=utc_iso(report.get('as_of'))
                or raw['decision']!=report.get('analysis_decision')
                or raw.get('intended_direction')!=report.get('intended_direction')
                or report.get('execution_permission')!='BLOCKED'
                or report.get('live_execution_allowed') is not False
                or report.get('broker_order_sent') is not False
                or report.get('submitted_order_id') is not None):
                raise ContractError('M14_M10A_BINDING_MISMATCH')
            m14=raw
            reason='M14_VALID_ANALYTICAL_ONLY'
        except (ValueError,TypeError):
            m14=_canonical_fallback(report,'M14_INVALID_OR_UNBOUND')
            reason='M14_INVALID_OR_UNBOUND'
    else:
        m14=_canonical_fallback(report, reason if not healthy else 'M14_RESULT_NOT_AVAILABLE')
        if healthy:reason='M14_RESULT_NOT_AVAILABLE'
    rec=_record(report) if healthy else None
    context={'analysis_id':m14['analysis_id'],'snapshot_as_of':m14['as_of'],
        'instrument_id':'XAUUSD', 'account_type':'ZERO_SPREAD',
        'mode':'MT5_READONLY', 'probability_policy':'EVIDENCE_ONLY',
        'data_snapshot':report.get('data_audit') if healthy else None,
        'market_state':report.get('market_state') if healthy else None,
        'router':report.get('router_result') if healthy else None,
        'evidence':report.get('market_evidence') if healthy else None,
        'limitations':['CANDIDATE_NOT_BROKER_CERTIFIED','NO_LIVE_TRADING','MT5_ZERO_COSTS_NOT_YET_VERIFIED',reason],
        'data_limitations':list(report.get('reason_codes') or [])[:12],
        'capabilities':{'mt5_primary':True,'tradingview_supplemental':True,
              'screenshots':False,'execution':False},
        'next_expected_event':_rule_text(rec.get('next_expected_event')) if rec else None,
        'invalidation':_rule_text(rec.get('invalidation')) if rec else None,
        'active_setups':([{'setup_id':rec['setup_id'],'state':rec['state'],
                           'direction':rec.get('direction'),'horizon_id':rec.get('horizon_id')}]
                         if rec and rec.get('state') in LIVE_STATES else []),
        'early_setups':([rec['setup_id']] if rec and rec.get('state') in ('EARLY_SETUP','SETUP_FORMING') else []),
        'conditional_setups':([rec['setup_id']] if rec and rec.get('state') in ('QUALIFIED','ARMED','TRIGGERED') else []),
        'confirmed_setups':([rec['setup_id']] if rec and rec.get('state')=='CONFIRMED' else []),
        'invalidated_setups':([rec['setup_id']] if rec and rec.get('state') in TERMINAL_STATES else []),
        'signal_change_log':list(rec.get('change_log') or [])[-20:] if rec else [],
        'signal_frequency_control':{'dedupe':'SETUP_REVISION_AND_EVENT','source':'M10A_SQLITE'},
        'signal_tier':m14.get('signal_tier')}
    # M15 will fail if an early report has no actual next-event/invalidation.
    # Do not fill them from imagined prices: downgrade rather than invent.
    if m14['decision'] in ('EARLY_SETUP','CONDITIONAL_SETUP') and not (context['next_expected_event'] and context['invalidation']):
        m14=_canonical_fallback(report,'MISSING_TESTABLE_EARLY_EVENT_OR_INVALIDATION')
        context['analysis_id']=m14['analysis_id'];context['snapshot_as_of']=m14['as_of']
        context['active_setups']=[];context['early_setups']=[];context['conditional_setups']=[]
        reason='MISSING_TESTABLE_EARLY_EVENT_OR_INVALIDATION'
    if healthy:
        context['quote']=_quote_context(report,m14)
    try:
        payload=compose(m14,context)
    except (ValueError,TypeError) as exc:
        # A broken provenance contract must cause a safe NO_TRADE, never a live alert.
        reason='M15_CONTRACT_BLOCKED_'+type(exc).__name__
        m14=_canonical_fallback(report,reason)
        payload=compose(m14,{'analysis_id':m14['analysis_id'],'instrument_id':'XAUUSD',
            'account_type':'ZERO_SPREAD','mode':'MT5_READONLY',
            'limitations':['INCONSISTENT_UPSTREAM_M14_OR_CONTEXT',reason]})
    payload['m15_published_at']=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
    indicator=report.get('indicator_intelligence') if healthy else None
    summary={}
    if isinstance(indicator,dict) and indicator.get('snapshot_id')==report.get('snapshot_id'):
        for tf in ('D1','H4','H1','M15','M5','M1'):
            item=(indicator.get('timeframes') or {}).get(tf)
            if not isinstance(item,dict):continue
            measurements={}
            for name,val in (item.get('indicators') or {}).items():
                if name in {'ema_9','ema_20','ema_21','ema_50','ema_200','rsi_9','rsi_14','atr_14','adx_14'} and isinstance(val,dict):
                    measurements[name]=val.get('value')
            interp=item.get('interpretation') or {}
            summary[tf]={'status':item.get('status'),
                         'market_direction':interp.get('market_direction','UNKNOWN'),
                         'indicators':measurements}
    payload['indicator_timeframes']=summary
    payload['m10a_connection_status']=report.get('monitor_connection_status','UNKNOWN')
    payload['m10a_quote_status']=report.get('monitor_quote_status','UNKNOWN')
    payload['m10a_setup_state']=rec.get('state') if rec else None
    payload['m10a_source_snapshot_id']=report.get('snapshot_id') if healthy else None
    payload['m10a_verified_market_feed']=False
    payload['read_only']=True
    payload['delivery_status']='NOT_SENT'
    payload['m10a_integration_status']='PASS_WITH_LIMITATIONS' if healthy and reason=='M14_VALID_ANALYTICAL_ONLY' else 'PENDING'
    evt=_material_event(report) if healthy and reason=='M14_VALID_ANALYTICAL_ONLY' else None
    if payload['decision'] in ('WAIT','NO_TRADE') and not (rec and rec.get('state') in TERMINAL_STATES):
        evt=None
    return payload,evt,reason


def render(report,output_dir,*,telegram_enabled=False,telegram_sender=None):
    """Publish synchronized files and optionally one alert per durable M10 event.

    Single caller only. Outbox keyed by M15 event fingerprint. An interrupted
    API call marks UNKNOWN, never automatically retries (avoids duplicate spam).
    """
    out=Path(output_dir);out.mkdir(parents=True,exist_ok=True)
    payload,event_id,reason=convert(report)
    # Crash-safe atomic writes per file; main snapshot last is the commit view.
    (out/'M15_COMPACT_PL.txt').write_text(short_report(payload)+'\n',encoding='utf-8')
    (out/'M15_FULL_PL.txt').write_text(full_report(payload)+'\n',encoding='utf-8')
    atomic_json(out/'M15_EXPORT_FULL.json',payload)
    delivery={'delivery_status':'NOT_SENT','channel':'TELEGRAM','event_id':event_id,
              'enabled':bool(telegram_enabled),'no_automatic_retry':True,
              'execution_permission':'BLOCKED','reason_codes':[reason]}
    # No queue for synthetic samples, absent event, or unbound diagnostic fallback.
    may_alert=(event_id is not None and payload['m10a_integration_status']=='PASS_WITH_LIMITATIONS'
        and not payload['synthetic_example'] and payload['top_setup_id'] is not None
        and payload['decision'] in {'EARLY_SETUP','CONDITIONAL_SETUP','LONG','SHORT'})
    # Terminal invalidation: canonical NO_TRADE has no top_setup_id, but event is
    # still a meaningful lifecycle update for an already observed setup.
    if (event_id and payload['decision']=='NO_TRADE' and
        payload['m10a_setup_state'] in TERMINAL_STATES and
        payload['m10a_integration_status']=='PASS_WITH_LIMITATIONS'):
        may_alert=True
    if may_alert and not telegram_enabled:
        delivery['delivery_status']='TELEGRAM_DISABLED'
    elif may_alert:
        db=Outbox(out/'M15_DELIVERY_OUTBOX.sqlite3')
        try:
            # Use a stable event-specific report: M15 fingerprints include fields
            # besides event_id. Freeze content once on first queue, thereafter
            # do not start new send for duplicate revision.
            import sqlite3
            db.con.execute('''CREATE TABLE IF NOT EXISTS event_index(
                 channel TEXT NOT NULL,event_id TEXT NOT NULL,
                 fingerprint TEXT NOT NULL,PRIMARY KEY(channel,event_id))''')
            db.con.commit()
            with db.con:
                old=db.con.execute('SELECT fingerprint FROM event_index WHERE channel=? AND event_id=?',
                    ('TELEGRAM',event_id)).fetchone()
                if old:state,fp='DUPLICATE_SUPPRESSED',old[0]
                else:
                    state,fp=db.queue(payload,event_id,channel='TELEGRAM')
                    if state=='QUEUED':
                        db.con.execute('INSERT INTO event_index(channel,event_id,fingerprint) VALUES(?,?,?)',
                            ('TELEGRAM',event_id,fp))
            delivery['delivery_status']=state;delivery['message_fingerprint']=fp
            if (telegram_enabled and state=='QUEUED'):
                token=os.getenv('TELEGRAM_BOT_TOKEN');chat=os.getenv('TELEGRAM_CHAT_ID')
                if not token or not chat:
                    delivery['delivery_status']='QUEUED_MISSING_ENV'
                elif db.begin_send(fp):
                    try:
                        if telegram_sender is None: mid=send_telegram(short_report(payload),token,chat)
                        else: mid=telegram_sender(short_report(payload),token,chat)
                        db.result(fp,'DELIVERED',mid)
                        delivery['delivery_status']='DELIVERED'
                    except error.HTTPError as exc:
                        status='REJECTED' if 400<=exc.code<500 else 'UNKNOWN'
                        db.result(fp,status);delivery['delivery_status']=status
                    except Exception:
                        db.result(fp,'UNKNOWN');delivery['delivery_status']='UNKNOWN'
        finally: db.close()
    elif event_id:
        delivery['delivery_status']='SUPPRESSED_UNSAFE_OR_NON_SIGNAL'
    else:
        delivery['delivery_status']='NO_MATERIAL_EVENT'
    payload['delivery_status']=delivery['delivery_status']
    atomic_json(out/'M15_LAST_DELIVERY_STATUS.json',delivery)
    atomic_json(out/'M15_MONITOR_SNAPSHOT.json',payload)
    return {'payload':payload,'delivery':delivery}
