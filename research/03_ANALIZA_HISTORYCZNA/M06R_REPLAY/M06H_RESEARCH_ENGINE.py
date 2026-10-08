"""MasterQUO M06H v1.0.0-CANDIDATE: historical XAUUSD macro-event study and M06 quote-ledger overlay.

Offline-only. CSV MT5 M1 bar close price is a RESEARCH PROXY, not executable quote.
This program does not download historical events or invent broker results.
"""
from __future__ import annotations
import argparse
import csv
from datetime import datetime, timezone, timedelta
from collections import defaultdict, Counter
from pathlib import Path
import hashlib
import importlib.util
import json
import math
import random
import re
import statistics

UTC = timezone.utc
VERSION = "1.0.0-CANDIDATE"
M06_PATH = Path(__file__).resolve().parent / 'vendor' / 'M06_REFERENCE_ENGINE.py'

class ResearchError(ValueError): pass

def must(cond, code):
    if not cond: raise ResearchError(code)

def instant(s):
    must(isinstance(s,str),'TIME_NOT_STRING')
    try:
        d=datetime.fromisoformat(s.replace('Z','+00:00'))
        must(d.tzinfo is not None,'NAIVE_DATETIME_FORBIDDEN')
        return d.astimezone(UTC)
    except (ValueError,OverflowError) as e: raise ResearchError('INVALID_TIME') from e

def utc(d):return d.astimezone(UTC).isoformat().replace('+00:00','Z')

def number(s,label):
    try: v=float(s)
    except (ValueError,TypeError) as e: raise ResearchError('INVALID_'+label) from e
    must(math.isfinite(v),'INVALID_'+label)
    return v

def canon(obj):return json.dumps(obj,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)

def sha(obj):return hashlib.sha256(canon(obj).encode()).hexdigest()

def read_json(path):
    with open(path,'r',encoding='utf-8') as f:return json.load(f)

def save_json(path,obj):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    with open(path,'w',encoding='utf-8') as f:json.dump(obj,f,ensure_ascii=False,indent=2,allow_nan=False)

def check_config(cfg):
    must(cfg.get('schema_version')=='2.0.0','SCHEMA_MISMATCH')
    must(cfg.get('frozen') is True,'PROTOCOL_NOT_FROZEN')
    must(cfg.get('research_only') is True,'RESEARCH_ONLY_REQUIRED')
    must(cfg.get('symbol') and isinstance(cfg['symbol'],str),'SYMBOL_REQUIRED')
    must(cfg.get('bar_period_seconds')==60,'ONLY_MT5_M1_BARS_SUPPORTED')
    hs=cfg.get('horizons_minutes')
    must(isinstance(hs,list) and hs and all(type(h)==int and 1<=h<=240 for h in hs),'INVALID_HORIZONS')
    must(len(set(hs))==len(hs),'DUPLICATE_HORIZON')
    must(type(cfg.get('control_blackout_minutes'))==int and cfg['control_blackout_minutes']>=max(hs),'BAD_CONTROL_BLACKOUT')
    windows=cfg.get('guard_windows_minutes',{})
    for key in ('HIGH','EXTREME'):
        w=windows.get(key)
        must(isinstance(w,dict) and type(w.get('pre'))==int and type(w.get('post'))==int and 0<=w['pre']<=240 and 0<=w['post']<=240,'BAD_MACRO_WINDOWS')
    folds=cfg.get('folds',[])
    must(isinstance(folds,list) and len(folds)>=2,'REQUIRES_DEVELOPMENT_AND_OOS_FOLDS')
    starts=[];roles=set();seen=set()
    for f in folds:
        must(f.get('id') and f['id'] not in seen,'DUPLICATE_FOLD_ID');seen.add(f['id'])
        must(f.get('role') in ('DEVELOPMENT','VALIDATION','FINAL_OOS'),'BAD_FOLD_ROLE')
        a,b=instant(f['start']),instant(f['end'])
        must(a<b,'BAD_FOLD_INTERVAL')
        starts.append((a,b,f));roles.add(f['role'])
    starts.sort(key=lambda x:x[0]);must(all(starts[i][1]<=starts[i+1][0] for i in range(len(starts)-1)),'OVERLAPPING_FOLDS')
    must('DEVELOPMENT' in roles and 'FINAL_OOS' in roles,'OOS_FOLD_REQUIRED')
    must(type(cfg.get('bootstrap_iterations'))==int and 100<=cfg['bootstrap_iterations']<=5000,'INVALID_BOOTSTRAP')
    must(type(cfg.get('bootstrap_seed'))==int,'INVALID_BOOTSTRAP_SEED')
    must(type(cfg.get('min_final_oos_events'))==int and cfg['min_final_oos_events']>=1,'INVALID_MIN_EVENT_COUNT')
    must(type(cfg.get('min_final_oos_trades'))==int and cfg['min_final_oos_trades']>=1,'INVALID_MIN_TRADE_COUNT')
    return starts

def read_bars(path,symbol,period=60):
    rows=[];prev=None
    with open(path,newline='',encoding='utf-8-sig') as f:
        csvr=csv.DictReader(f)
        must({'time_utc','open','high','low','close','symbol'}.issubset(csvr.fieldnames or []),'BAD_BARS_HEADER')
        for r in csvr:
            must(r['symbol']==symbol,'BAR_SYMBOL_MISMATCH')
            t=instant(r['time_utc']);must(t.second==0 and t.microsecond==0,'BAD_M1_BAR_ALIGNMENT')
            must(prev is None or t>prev,'BARS_NOT_STRICTLY_SORTED');prev=t
            o,h,l,c=[number(r[k],k) for k in ('open','high','low','close')]
            must(l>0 and l<=min(o,c)<=max(o,c)<=h,'INVALID_OHLC')
            if r.get('bar_state'):must(r['bar_state']=='CLOSED','FORMING_BAR_FORBIDDEN')
            rows.append({'open_at':t,'close_at':t+timedelta(seconds=period),'open':o,'high':h,'low':l,'close':c})
    must(rows,'NO_BARS')
    return rows

def check_archive_line(row,previous):
    must(isinstance(row,dict) and row.get('prev_hash')==previous,'ARCHIVE_CHAIN_BROKEN')
    expected=sha({'prev_hash':previous,'captured_at':row.get('captured_at'),'payload':row.get('payload')})
    must(row.get('record_hash')==expected,'ARCHIVE_RECORD_HASH_INVALID')
    instant(row['captured_at'])
    return row['record_hash']

def parse_event(raw,known_at,synthetic,record_type):
    must(isinstance(raw,dict),'BAD_EVENT')
    event_at=raw.get('scheduled_at') if record_type=='CALENDAR' else raw.get('published_at')
    if not event_at:return None
    at=instant(event_at)
    if record_type=='NEWS' and raw.get('time_quality')!='PUBLISHED':return None
    source=raw.get('source_id') or 'UNKNOWN'
    must(bool(raw.get('event_id')),'EVENT_ID_REQUIRED')
    published=raw.get('available_at') if record_type=='CALENDAR' else raw.get('first_seen_at')
    first=instant(published) if published else known_at
    known=max(first,known_at)
    impact=str(raw.get('impact') or 'UNKNOWN').upper()
    if impact not in ('LOW','MEDIUM','HIGH','EXTREME'):impact='UNKNOWN'
    return {'event_id':str(raw['event_id']),'name':str(raw.get('name') or raw.get('headline') or 'UNKNOWN')[:200],
            'scheduled_at':at,'known_at':known,'source_id':source,'source_family':'FAIR_ECONOMY' if source in ('FF_CALENDAR','MM_CALENDAR') or raw.get('source_family')=='FAIR_ECONOMY' else 'OFFICIAL_OR_OTHER',
            'impact':impact,'impact_known_at':known,'type':record_type,'synthetic':bool(synthetic),'time_quality':raw.get('event_time_quality') or raw.get('time_quality') or 'UNVERIFIED',
            'provider_sources':raw.get('provider_sources') or [source]}

def load_events(path):
    path=Path(path);records=[];mode=''
    if path.suffix.lower()=='.jsonl':
        previous='GENESIS';last_time=None
        with path.open(encoding='utf-8') as f:
            for ln,line in enumerate(f,1):
                if not line.strip():continue
                row=json.loads(line)
                previous=check_archive_line(row,previous)
                at=instant(row['captured_at'])
                must(last_time is None or at>=last_time,'ARCHIVE_NONMONOTONIC_CAPTURE');last_time=at
                records.append((row['payload'],at))
        mode='APPEND_ONLY_CAPTURED_SNAPSHOTS'
    else:
        obj=read_json(path)
        if obj.get('module_id')=='M04N':
            records=[(obj,instant(obj['as_of']))];mode='SINGLE_SNAPSHOT_NO_HISTORICAL_CERTIFICATION'
        elif obj.get('kind')=='CURATED_HISTORICAL_EVENTS':
            # Explicitly declare this user-supplied dataset lacks cryptographic provider certification.
            must(obj.get('data_provenance') in ('USER_SUPPLIED','SYNTHETIC'),'EVENT_PROVENANCE_REQUIRED')
            base=[]
            for item in obj.get('events',[]):
                known=instant(item['known_at'])
                ev=parse_event(item,known,obj.get('data_provenance')=='SYNTHETIC','CALENDAR' if item.get('type','CALENDAR')=='CALENDAR' else 'NEWS')
                if ev:
                    ev['known_at']=max(known,instant(item['available_at'])) if item.get('available_at') else known
                    base.append(ev)
            return dedupe_events(base), 'CURATED_'+obj['data_provenance']+'_UNVERIFIED'
        else:raise ResearchError('UNSUPPORTED_EVENT_FILE')
    observations=[]
    for report,capture_at in records:
        must(report.get('module_id')=='M04N','NOT_M04N_REPORT')
        for item in report.get('calendar',{}).get('events',[]):
            ev=parse_event(item,capture_at,bool(report.get('synthetic',False) or report.get('status')=='SYNTHETIC_TEST_ONLY'),'CALENDAR')
            if ev:observations.append(ev)
        for item in report.get('news',{}).get('recent',[]):
            ev=parse_event(item,capture_at,bool(report.get('synthetic',False) or report.get('status')=='SYNTHETIC_TEST_ONLY'),'NEWS')
            if ev:observations.append(ev)
    return dedupe_events(observations),mode

def event_key(event):
    # Alternative provider ids for the same scheduled release should not become independent samples.
    name=event['name'].lower()
    name=re.sub(r'[^a-z0-9]+',' ',name).strip()
    if name in ('consumer price index','cpi'):name='us cpi'
    if name in ('employment situation','nonfarm payrolls','nfp','non farm payrolls'):name='us nfp'
    return (event['type'],name,event['scheduled_at'])

def dedupe_events(items):
    groups={}
    for ev in items:
        key=event_key(ev)
        if key not in groups:
            groups[key]=dict(ev)
        else:
            old=groups[key]
            # Earliest actual snapshot observed is prior knowledge; later snapshot must not rewrite it.
            if ev['known_at']<old['known_at']:
                old['known_at']=ev['known_at'];old['event_id']=ev['event_id'];old['source_id']=ev['source_id'];old['time_quality']=ev['time_quality']
            old['synthetic']=old['synthetic'] or ev['synthetic']
            old['provider_sources']=sorted(set(old['provider_sources'])|set(ev['provider_sources']))
            if ev['impact']=='EXTREME' or ev['impact']=='HIGH' and old['impact'] not in ('HIGH','EXTREME'):
                old['impact']=ev['impact']; old['impact_known_at']=ev['known_at']
            elif ev['impact']==old['impact'] and ev['known_at']<old['impact_known_at']:
                old['impact_known_at']=ev['known_at']
    # Revised scheduling of a single event_id cannot be treated as one stable known-at event.
    schedules=defaultdict(set)
    for e in items:schedules[e['event_id']].add(e['scheduled_at'])
    revised={eid for eid,times in schedules.items() if len(times)>1}
    # CPI/NFP-like releases are scheduled once per day; conflicting same-day times
    # (possibly different provider IDs) cannot be safely treated as two independent events.
    by_day=defaultdict(set)
    for ev in items:
        kind,name,at=event_key(ev)
        by_day[(kind,name,at.date())].add(at)
    conflicts={key for key,times in by_day.items() if len(times)>1}
    return sorted((x for x in groups.values()
                   if x['event_id'] not in revised and (x['type'],event_key(x)[1],x['scheduled_at'].date()) not in conflicts),
                  key=lambda x:(x['scheduled_at'],x['event_id']))

def fold_for(t,folds):
    return next((f for a,b,f in folds if a<=t<b),None)

def lookup_close(bars_by_close,t):
    return bars_by_close.get(t)

def bar_move(anchor,h,bars_by_close,folds):
    """Prior completed M1 close strictly BEFORE timestamp; exact +h close. No gaps."""
    base=anchor-timedelta(minutes=1)
    f=fold_for(anchor,folds)
    if not f:return None,'OUTSIDE_FOLDS'
    if base<instant(f['start']) or anchor+timedelta(minutes=h)>=instant(f['end']):return None,'PURGED_FOLD_BOUNDARY'
    p=bars_by_close.get(base)
    if not p:return None,'MISSING_PRE_EVENT_CLOSE'
    t=base+timedelta(minutes=1)
    future=None
    while t<=anchor+timedelta(minutes=h):
        item=bars_by_close.get(t)
        if item is None:return None,'MISSING_OR_GAPPED_M1_BARS'
        future=item
        t+=timedelta(minutes=1)
    return round((future['close']-p['close'])/p['close']*10000,8),None

def nearest_control(event,anchor,h,by_close,folds,events,blackout,used):
    f=fold_for(anchor,folds)
    if f is None:return None
    start,end=instant(f['start']),instant(f['end'])
    # Sample exact UTC hour/minute across different UTC dates, same fold.
    times=[t for t in by_close if start<=t<end and (t.hour,t.minute)==(anchor.hour,anchor.minute)
           and t.date()!=anchor.date() and t not in used]
    times.sort(key=lambda t:(abs((t-anchor).total_seconds()),t))
    for t in times:
        if any(abs((t-e['scheduled_at']).total_seconds())<=blackout*60 for e in events):continue
        response,why=bar_move(t,h,by_close,folds)
        if why is None:return t,response
    return None

def percentile(vals,frac):
    if not vals:return None
    arr=sorted(vals);k=(len(arr)-1)*frac;low=int(k);upper=min(len(arr)-1,low+1)
    return arr[low]+(arr[upper]-arr[low])*(k-low)

def bootstrap_day_blocks(pairs,iterations,seed):
    groups=defaultdict(list)
    for p in pairs:groups[p['event_day']].append(p['excess_abs_bp'])
    if len(groups)<3:return {'status':'NOT_RUN','reason':'FEWER_THAN_THREE_INDEPENDENT_EVENT_DAYS'}
    rng=random.Random(seed);days=sorted(groups);means=[]
    for _ in range(iterations):
        values=[r for _ in days for r in groups[rng.choice(days)]]
        means.append(statistics.mean(values))
    return {'status':'COMPLETED','method':'UTC_EVENT_DAY_BLOCK_BOOTSTRAP','days':len(days),
            'mean_excess_abs_bp_ci95':[round(percentile(means,.025),6),round(percentile(means,.975),6)]}

def event_study(bars,events,cfg,folds):
    by={r['close_at']:r for r in bars}
    valid=[e for e in events if e['type']=='CALENDAR' and e['impact'] in ('HIGH','EXTREME')]
    rows=[];missing=Counter();reserved=set()
    for e in valid:
        t=e['scheduled_at']
        if t.second or t.microsecond:
            missing['EVENT_NOT_M1_ALIGNED']+=1;continue
        fold=fold_for(t,folds)
        if fold is None:missing['OUTSIDE_FOLDS']+=1;continue
        for h in cfg['horizons_minutes']:
            move,why=bar_move(t,h,by,folds)
            if why:
                missing[why]+=1;continue
            control=nearest_control(e,t,h,by,folds,valid,cfg['control_blackout_minutes'],reserved)
            record={'event_id':e['event_id'],'event_name':e['name'],'scheduled_at':utc(t),'known_at':utc(e['known_at']),
                    'fold_id':fold['id'],'fold_role':fold['role'],'impact':e['impact'],'source_id':e['source_id'],'horizon_minutes':h,
                    'directional_bp':move,'absolute_bp':round(abs(move),8),'research_price_type':'MT5_M1_CLOSE_BID_PROXY_NOT_EXECUTABLE',
                    'point_in_time_calendar_known_before_event':e['known_at']<=t,'matched_control':False,'synthetic':e['synthetic']}
            if control:
                ct,cval=control;reserved.add(ct)
                record.update(matched_control=True,control_at=utc(ct),control_abs_bp=round(abs(cval),8),excess_abs_bp=round(abs(move)-abs(cval),8))
            rows.append(record)
    aggregates=[]
    for f in [x[2] for x in folds]:
        for h in cfg['horizons_minutes']:
            subset=[x for x in rows if x['fold_id']==f['id'] and x['horizon_minutes']==h]
            matched=[x for x in subset if x['matched_control']]
            values=[x['absolute_bp'] for x in subset]
            if subset:
                boot=bootstrap_day_blocks([{'event_day':x['scheduled_at'][:10],'excess_abs_bp':x['excess_abs_bp']} for x in matched],cfg['bootstrap_iterations'],cfg['bootstrap_seed'])
                aggregates.append({'fold_id':f['id'],'role':f['role'],'horizon_minutes':h,'events':len(subset),
                    'median_absolute_move_bp':round(statistics.median(values),6), 'mean_directional_move_bp':round(statistics.mean(x['directional_bp'] for x in subset),6),
                    'matched_pairs':len(matched),'median_control_abs_bp':round(statistics.median(x['control_abs_bp'] for x in matched),6) if matched else None,
                    'mean_excess_abs_bp':round(statistics.mean(x['excess_abs_bp'] for x in matched),6) if matched else None,
                    'bootstrap':boot,'causal_inference_supported':False})
    return {'status':'COMPLETED' if rows else 'INSUFFICIENT_DATA','event_rows':rows,'aggregates':aggregates,
            'excluded_reasons':dict(missing),'studied_high_impact_events':len(valid),
            'limitations':['Retrospective M1 bar-close moves are descriptive not executable bid/ask PnL',
                           'Matched controls do not establish causality or cancel macro confounders','Historical FX/CFD bid-close feed may contain broker-specific gaps and sessions']}

def macro_guard_decision(signal,events,windows):
    decision=instant(signal['available_at'])
    must(instant(signal['signal_at'])<=decision,'BAD_SIGNAL_TIME')
    for e in events:
        if e['type']!='CALENDAR' or e['impact'] not in ('HIGH','EXTREME') or e['synthetic']:continue
        if e['known_at']>decision or e.get('impact_known_at',e['known_at'])>decision:continue
        w=windows[e['impact']]
        delta=(decision-e['scheduled_at']).total_seconds()/60
        if -w['pre']<=delta<=w['post']:
            return {'blocked':True,'reason':'PIT_KNOWN_MACRO_EVENT','event_id':e['event_id'],'known_at':utc(e['known_at'])}
    return {'blocked':False,'reason':'NO_MATCHING_KNOWN_EVENT_PARTIAL_CALENDAR_NOT_CLEARANCE','event_id':None}

def strategy_overlay(packet,events,cfg):
    if packet is None:return {'status':'NOT_RUN','reason_codes':['NO_HISTORICAL_SIGNALS_OR_BID_ASK_TICKS_PROVIDED'], 'validation_approved':False}
    spec=importlib.util.spec_from_file_location('masterquo_m06_reference',M06_PATH)
    must(spec is not None and spec.loader is not None,'M06_REFERENCE_NOT_INSTALLED')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    must(packet.get('account',{}).get('symbol')==cfg['symbol'],'M06_PACKET_SYMBOL_MISMATCH')
    a={(f['id'],f['role'],f['start'],f['end']) for f in packet['validation_profile']['folds']}
    b={(f['id'],f['role'],f['start'],f['end']) for f in cfg['folds']}
    must(a==b,'M06_FOLDS_MUST_MATCH_STUDY_FOLDS')
    original=mod.main(packet)
    must(original['run_status']=='COMPLETED','M06_REFERENCE_FAILED')
    trades_by_id={x['signal_id']:x for x in original['trades']}
    must(len(trades_by_id)==len(packet['signals']),'SIGNAL_LEDGER_DUPLICATES')
    decisions=[]
    for s in packet['signals']:
        check=macro_guard_decision(s,events,cfg['guard_windows_minutes'])
        tr=trades_by_id[s['signal_id']]
        decisions.append({'signal_id':s['signal_id'],'strategy_version':s['strategy_version'],
                          'fold_id':tr.get('fold_id'),'fold_role':tr.get('fold_role'),'replay_status':tr['status'],**check})
    fold_stats=[]
    for f in packet['validation_profile']['folds']:
        ids={x['signal_id'] for x in decisions if x['fold_id']==f['id']}
        done=[t for t in original['trades'] if t['signal_id'] in ids and t['status']=='COMPLETED']
        allowed={x['signal_id'] for x in decisions if x['signal_id'] in ids and not x['blocked']}
        after=[t for t in done if t['signal_id'] in allowed]
        fold_stats.append({'fold_id':f['id'],'role':f['role'],'completed_baseline':len(done),'completed_after_filter':len(after),
                           'removed_completed_trades':len(done)-len(after), 'baseline':mod.metric(done),'filtered':mod.metric(after),
                           'window_policy_frozen':cfg['frozen']})
    per_strategy=[]
    for spec in sorted({s['strategy_version'] for s in packet['signals']}):
        for f in packet['validation_profile']['folds']:
            selected={s['signal_id'] for s in packet['signals'] if s['strategy_version']==spec}
            original_trades=[t for t in original['trades'] if t['signal_id'] in selected and t.get('fold_id')==f['id'] and t['status']=='COMPLETED']
            accepted={x['signal_id'] for x in decisions if x['signal_id'] in selected and not x['blocked']}
            guarded=[t for t in original_trades if t['signal_id'] in accepted]
            per_strategy.append({'strategy_version':spec,'fold_id':f['id'],'role':f['role'],
                                 'baseline':mod.metric(original_trades),'guarded':mod.metric(guarded),
                                 'oos_minimum_met':f['role']=='FINAL_OOS' and len(original_trades)>=cfg['min_final_oos_trades'] and len(guarded)>=cfg['min_final_oos_trades']})
    oos=next((x for x in fold_stats if x['role']=='FINAL_OOS'),None)
    sufficient=bool(oos and oos['completed_baseline']>=cfg['min_final_oos_trades'] and oos['completed_after_filter']>=cfg['min_final_oos_trades'])
    synthetic_quotes=any('SYNTHETIC' in t.get('source_id','').upper() for t in packet['ticks']) or 'synthetic' in str(packet.get('run_id','')).lower()
    reasons=['NO_FORWARD_DEMO','PARTIAL_EVENT_CALENDAR_COVERAGE','NO_LIVE_AUTHORIZATION']
    if synthetic_quotes:reasons.append('SYNTHETIC_QUOTES_NOT_MARKET_EVIDENCE')
    if not sufficient:reasons.append('INSUFFICIENT_OOS_TRADES')
    if packet.get('account',{}).get('commission_source')=='SCENARIO_ONLY' or packet.get('account',{}).get('conversion_source')=='SCENARIO_ONLY':reasons.append('COSTS_SCENARIO_ONLY')
    return {'status':'SYNTHETIC_DEMONSTRATION_ONLY' if synthetic_quotes else 'RESEARCH_COMPLETE_WITH_LIMITATIONS' if sufficient else 'PENDING',
            'original_m06_validation':original['validation'],'account_profile':original['account_profile'],
            'm06_cost_stress_scenarios':original['cost_scenarios'],
            'fold_comparison':fold_stats,'by_strategy_by_fold':per_strategy,'signal_decisions':decisions,'reason_codes':reasons,'validation_approved':False,
            'limitations':['Quote replay delegated to original unchanged M06 reference engine',
                           'No fills can be inferred from M1 candle closes','Removed trades are excluded; no reallocation of capital or signal timing modeled',
                           'Averaging returns after filtering is subject to selection bias']}

def research(bars,events,cfg,mode,packet=None):
    folds=check_config(cfg)
    study=event_study(bars,events,cfg,folds)
    strategies=strategy_overlay(packet,events,cfg)
    final_events=sum(1 for x in study['event_rows'] if x['fold_role']=='FINAL_OOS' and x['horizon_minutes']==cfg['horizons_minutes'][0])
    flags=[]
    if final_events<cfg['min_final_oos_events']:flags.append('INSUFFICIENT_FINAL_OOS_EVENTS')
    if mode=='SINGLE_SNAPSHOT_NO_HISTORICAL_CERTIFICATION':flags.append('SINGLE_M04N_REPORT_NOT_HISTORICAL_ARCHIVE')
    if any(e['synthetic'] for e in events):flags.append('SYNTHETIC_EVENTS_EXCLUDED_FROM_IMPACT_STUDY')
    if strategies['status']=='NOT_RUN':flags.append('TRADE_PNL_NOT_MEASURED')
    flags.append('GLOBAL_CALENDAR_COVERAGE_PARTIAL')
    flags.append('BAR_PROVENANCE_EXTERNAL_NOT_CRYPTOGRAPHICALLY_CERTIFIED')
    return {'schema_version':'2.0.0','module_id':'M06H','module_version':VERSION,'status':'RESEARCH_ONLY',
            'data_origin':mode,'broker_symbol':cfg['symbol'],'as_of':utc(datetime.now(UTC)),
            'protocol_hash':sha(cfg),'observed_bar_count':len(bars),'unique_events':len(events),
            'strategy_profiles':['MVP','SMC','SCALPING'],'event_study':study,'strategy_validation':strategies,
            'reason_codes':flags,'contains_synthetic_events':any(e['synthetic'] for e in events),
            'approval_status':'PENDING_APPROVAL','execution_permission':'BLOCKED',
            'live_execution_allowed':False,'orders_sent':0,'visual_capture_enabled':False,
            'audit_note':'Research data must be retained with broker/source metadata; OOS and DEMO are mandatory before considering any promotion.'}

def report_markdown(r):
    lines=['# MasterQUO M06H — raport badawczy','',f"**Status:** {r['status']} · **Symbol:** {r['broker_symbol']} · **Moduł:** {r['module_version']}",
           '',f"Zaobserwowane zamknięte świece M1: **{r['observed_bar_count']}**. Zdarzenia: **{r['unique_events']}**.",
           '', '**DANE SYNTETYCZNE — WYŁĄCZNIE DEMONSTRACJA**' if r['contains_synthetic_events'] else '**Dane z plików zewnętrznych wymagają weryfikacji pochodzenia**',
           '', '## Wpływ publikacji — opisowy, nie PnL','',
           '| Fold | Rola | Horyzont | Liczba zdarzeń | Mediana bezwzględnego ruchu (bp) | Pary kontrolne | Śr. nadwyżka abs. ruchu (bp) |',
           '|---|---|---:|---:|---:|---:|---:|']
    for x in r['event_study']['aggregates']:
        lines.append(f"| {x['fold_id']} | {x['role']} | {x['horizon_minutes']}m | {x['events']} | {x['median_absolute_move_bp']:.2f} | {x['matched_pairs']} | {x['mean_excess_abs_bp'] if x['mean_excess_abs_bp'] is not None else 'N/A'} |")
    if not r['event_study']['aggregates']:lines.append('Brak wystarczających kompletnych szeregów dla event-study.')
    lines += ['', '## Walidacja strategii i kosztów','',f"**{r['strategy_validation']['status']}** — {', '.join(r['strategy_validation'].get('reason_codes') or [])}.",
              '']
    if 'fold_comparison' in r['strategy_validation']:
        lines+=['| Fold | Baseline trades | Filter trades | Średni net R baseline | Średni net R filter |','|---|---:|---:|---:|---:|']
        for x in r['strategy_validation']['fold_comparison']:
            lines.append(f"| {x['fold_id']} | {x['completed_baseline']} | {x['completed_after_filter']} | {x['baseline'].get('mean_net_r')} | {x['filtered'].get('mean_net_r')} |")
    if r['strategy_validation'].get('by_strategy_by_fold'):
        lines+=['','### Według zamrożonych profili strategii','',
                '| Strategia | Fold | N przed filtrem | N po filtrze | R netto przed | R netto po | OOS minimum |',
                '|---|---|---:|---:|---:|---:|---|']
        for x in r['strategy_validation']['by_strategy_by_fold']:
            lines.append(f"| {x['strategy_version']} | {x['fold_id']} | {x['baseline']['trades']} | {x['guarded']['trades']} | {x['baseline']['mean_net_r']} | {x['guarded']['mean_net_r']} | {x['oos_minimum_met']} |")
    lines+=['', '## Ograniczenia i blokady',
            '- Wyniki syntetyczne lub z plików użytkownika NIE są zweryfikowaną przewagą strategii.',
            '- Retrospektywne ruchy świec M1 NIE oznaczają możliwego wykonania transakcji ani kierunku przyszłego ruchu.',
            '- Dzisiejszy kalendarz portali nie odtwarza historycznej wiedzy sprzed daty jego pobrania.',
            '- Domyślne okna newsowe to wstępne założenia, a nie zoptymalizowane progi.',
            '- Bez pełnego historycznego sygnału oraz ticków Bid/Ask i prowizji wynik netto = NOT_RUN.',
            '- Brak pokrycia wydarzeń przez feed nie upoważnia do zniesienia blokady M04/M11/M14.',
            '- Status wykonania: BLOCKED; wymagana dalsza walidacja OOS i forward DEMO.',
            '', 'Powody ostrożności: '+', '.join(r['reason_codes'])+'.','']
    return '\n'.join(lines)

def cli():
    p=argparse.ArgumentParser(description='M06H macro event study and optional M06 tick-backed strategy filter research')
    p.add_argument('--bars',required=True,help='UTC 1-minute MT5 broker bars CSV')
    p.add_argument('--events',required=True,help='M04N snapshots archive JSONL or one report JSON or curated event JSON')
    p.add_argument('--config',default='M06H_RESEARCH_CONFIG.example.json')
    p.add_argument('--m06-packet',help='Optional original complete M06 quote replay packet JSON')
    p.add_argument('--output-dir',default='runtime_m06h')
    a=p.parse_args()
    try:
        cfg=read_json(a.config);bars=read_bars(a.bars,cfg['symbol']);events,mode=load_events(a.events)
        packet=read_json(a.m06_packet) if a.m06_packet else None
        res=research(bars,events,cfg,mode,packet)
        out=Path(a.output_dir);out.mkdir(parents=True,exist_ok=True)
        save_json(out/'M06H_VALIDATION_REPORT.json',res)
        (out/'M06H_REPORT_PL.md').write_text(report_markdown(res),encoding='utf-8')
        print(canon({'status':res['status'],'event_rows':len(res['event_study']['event_rows']),'strategy_validation':res['strategy_validation']['status'],'output_dir':str(out)}))
    except (ResearchError,ValueError,TypeError,KeyError,FileNotFoundError) as e:
        print(canon({'status':'FAIL','reason':str(e),'execution_permission':'BLOCKED'}));raise SystemExit(2)

if __name__=='__main__':cli()
