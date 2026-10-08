"""M01 additional local read-only integrity review; not a broker certification.

Only local runtime caller (after direct authenticated MT5 read) may pass
collected_directly=True. JSON/CLI input cannot grant itself that flag.
No order operations or screenshot imports. ALL real costs remain unverified.
"""
from __future__ import annotations
import copy
from datetime import datetime, timezone, timedelta
import hashlib
import json
import math

POLICY = 'MT5_PRIMARY_TV_SUPPLEMENTAL_NO_SCREENSHOTS'
TF_MIN = {'M1':1,'M5':5,'M15':15,'H1':60,'H4':240,'D1':1440}
GOOD = ('PASS','PASS_WITH_LIMITATIONS')

def when(s):
    if not isinstance(s,str): raise ValueError('TIME_INVALID')
    t=datetime.fromisoformat(s.replace('Z','+00:00'))
    if not t.utcoffset() and t.tzinfo is None: raise ValueError('TIMEZONE_REQUIRED')
    return t.astimezone(timezone.utc)

def number(x):return isinstance(x,(float,int)) and not isinstance(x,bool) and math.isfinite(x)

def digest(obj):return hashlib.sha256(json.dumps(obj,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()

def audit(snapshot, quote, *, collected_directly=False, connected=False, now=None,
          max_quote_age_seconds=5.0, min_bars=230, max_last_bar_age_minutes=None):
    if not isinstance(snapshot,dict): raise ValueError('SNAPSHOT_REQUIRED')
    s=copy.deepcopy(snapshot)
    reasons=[]; pending=[]; metrics={}; now=now or datetime.now(timezone.utc)
    if now.tzinfo is None: raise ValueError('CLOCK_TIMEZONE_REQUIRED')
    now=now.astimezone(timezone.utc)
    try: asof=when(s.get('as_of'))
    except (ValueError,TypeError):
        asof=None;reasons.append('AS_OF_INVALID')
    if asof and (asof>now+timedelta(seconds=1) or (now-asof).total_seconds()>max_quote_age_seconds*3):
        pending.append('SNAPSHOT_STALE_OR_FUTURE')
    if s.get('data_source_policy')!=POLICY or s.get('visual_capture_enabled') is not False:
        reasons.append('SOURCE_POLICY_INVALID')
    if s.get('instrument_id')!='XAUUSD' or not s.get('exact_symbol'):
        reasons.append('INSTRUMENT_OR_BROKER_SYMBOL_INVALID')
    if not collected_directly or not connected:
        pending.append('DIRECT_MT5_COLLECTION_NOT_VERIFIED')
    if not isinstance(quote,dict):
        pending.append('QUOTE_UNAVAILABLE')
    else:
        try:
            bid,ask=quote.get('bid'),quote.get('ask')
            qt=when(quote.get('source_timestamp'))
            if quote.get('source') not in ('MT5_BROKER','MT5_PRIMARY') or quote.get('symbol') != s.get('exact_symbol'):
                reasons.append('QUOTE_SOURCE_MISMATCH')
            if not all(number(v) and v>0 for v in (bid,ask)) or ask<bid:
                reasons.append('BID_ASK_INVALID')
            if (now-qt).total_seconds()< -1 or (now-qt).total_seconds() > max_quote_age_seconds:
                pending.append('QUOTE_STALE_OR_FUTURE')
        except (ValueError,TypeError):reasons.append('QUOTE_TIME_INVALID')
    groups=s.get('candles_by_tf') or {}
    if not isinstance(groups,dict):reasons.append('CANDLES_NOT_OBJECT');groups={}
    for tf in TF_MIN:
        bars=groups.get(tf)
        r=[];p=[];last=None
        if not isinstance(bars,list) or len(bars)<min_bars:
            p.append('INSUFFICIENT_CLOSED_HISTORY')
            bars=bars if isinstance(bars,list) else []
        opens=set();prev=None
        for b in bars:
            if not isinstance(b,dict):r.append('INVALID_BAR');continue
            try:
                t=when(b['bar_open_utc']); c=when(b['close_confirmed_at']); a=when(b['available_at'])
            except (ValueError,TypeError,KeyError): r.append('BAR_TIME_INVALID');continue
            if t in opens: r.append('DUPLICATE_OPEN_TIME')
            opens.add(t)
            if prev and t<=prev:r.append('NON_MONOTONIC_BAR_TIME')
            prev=t
            if a<c or c<=t or (asof and (a>asof or c>asof)):
                r.append('FUTURE_OR_UNCONFIRMED_BAR')
            if (b.get('bar_state')!='CLOSED' or b.get('instrument_id')!='XAUUSD' or b.get('timeframe')!=tf
                or b.get('exact_symbol')!=s.get('exact_symbol') or b.get('price_basis')!='BID'
                or not str(b.get('source_id','')).startswith('MT5') or not b.get('evidence_id')):
                r.append('PROVENANCE_OR_BAR_STATE_INVALID')
            o,h,l,cl=(b.get(x) for x in ('open','high','low','close'))
            if not all(number(v) and v>0 for v in (o,h,l,cl)) or not (l<=min(o,cl)<=max(o,cl)<=h):
                r.append('OHLC_INVALID')
            if b.get('tick_volume') is not None and (not number(b['tick_volume']) or b['tick_volume']<0):
                r.append('TICK_VOLUME_INVALID')
            last=c
        # Conservative recent intraday gap detection (session exceptions are
        # not guessed): missing bars trigger PENDING for investigation.
        if len(bars)>2 and tf!='D1':
            recent=[]
            for b in bars[-14:]:
                try: recent.append(when(b['bar_open_utc']))
                except (ValueError,KeyError,TypeError): break
            if len(recent)==min(14,len(bars)):
                span=timedelta(minutes=TF_MIN[tf])
                for left,right in zip(recent,recent[1:]):
                    if right-left>span*1.1:
                        p.append('RECENT_BAR_GAP_CALENDAR_RECONCILIATION_REQUIRED')
                        break
        if bars and asof and last:
            # Last bar may be old on legitimate closures (weekend/news halt): mark as PENDING,
            # not corrupted. Policy is explicit, not universal.
            limit=(max_last_bar_age_minutes or {}).get(tf)
            if limit is not None and (asof-last).total_seconds()>limit*60:
                p.append('CLOSED_BAR_TOO_OLD')
            if last>asof:r.append('LAST_BAR_FUTURE')
        metrics[tf]={'status':'FAIL' if r else 'PENDING' if p else 'PASS',
                     'closed_bars':len(bars),'latest_close':last.isoformat() if last else None,
                     'error_codes':sorted(set(r)),'pending_codes':sorted(set(p)),
                     'last_evidence_id':bars[-1].get('evidence_id') if bars and isinstance(bars[-1],dict) else None}
        reasons.extend(f'{tf}:{x}' for x in sorted(set(r)))
        pending.extend(f'{tf}:{x}' for x in sorted(set(p)))
    status='FAIL' if reasons else 'PENDING' if pending else 'PASS_WITH_LIMITATIONS'
    # Read-only local audit is limited, never a certified fill/risk/portfolio gate.
    s['_preview_only']=status not in GOOD
    s['_local_integrity_audit']=True
    s['data_gates']=[{'gate_id':'M01_ANALYSIS_INTEGRITY','required_for':['ANALYSIS','DIRECTION'],'status':status,
                      'reason_codes':sorted(set(reasons+pending))},
                     {'gate_id':'M01_EXECUTION_BROKER','required_for':['EXECUTION'],'status':'PENDING',
                      'reason_codes':['FULL_BROKER_RISK_COST_AUTHORITY_NOT_VERIFIED']}]
    s['analysis_gate']={'status':status,'required_for':['ANALYSIS','DIRECTION']}
    s['execution_gate']={'status':'PENDING','required_for':['EXECUTION']}
    s['bridge_data_status']='LOCAL_AUDIT_LIMITED' if status in GOOD else 'LOCAL_AUDIT_'+status
    s['local_audit']={'module_id':'M01_LOCAL_AUDIT','status':status,'as_of':s.get('as_of'),
                      'closed_bar_checks':metrics,'reason_codes':sorted(set(reasons+pending)),
                      'live_execution_eligible':False,'source_hash':digest({'bars':groups,'symbol':s.get('exact_symbol')}),
                      'limitations':['BROKER_SESSION_CALENDAR_NOT_FULLY_VERIFIED',
                                     'NO_BROKER_COST_RECONCILIATION','NOT_PRODUCTION_CERTIFICATION']}
    return s
