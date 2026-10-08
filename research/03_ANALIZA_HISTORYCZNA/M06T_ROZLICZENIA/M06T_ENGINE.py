"""MasterQUO M06T v1.0.0-CANDIDATE: read-only, conservative M06R -> M06/M06H research adapter.

No order APIs, no network, no fills claimed. Any entry/exit is a QUOTE SIMULATION.
"""
from __future__ import annotations
import argparse
from bisect import bisect_left,bisect_right
from collections import Counter,defaultdict
import csv
from datetime import datetime,timezone,timedelta
import hashlib
import json
import math
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'vendor'))
import M06_REFERENCE_ENGINE as m06
import M06H_RESEARCH_ENGINE as m06h

VERSION='1.0.0-CANDIDATE'
POLICY=m06.POLICY
class SettlementError(ValueError):pass

def must(v,reason):
    if not v:raise SettlementError(reason)
def dt(s):
    try:r=m06.instant(s)
    except (ValueError,TypeError) as e:raise SettlementError('BAD_OR_NAIVE_TIME') from e
    return r
def iso(x):return x.astimezone(timezone.utc).isoformat().replace('+00:00','Z')
def number(x,reason,positive=False):
    try:v=float(x)
    except (TypeError,ValueError) as e:raise SettlementError(reason) from e
    must(not isinstance(x,bool) and math.isfinite(v) and (v>0 if positive else v>=0),reason)
    return v
def sha(o):return hashlib.sha256(json.dumps(o,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def jsonread(p):return json.loads(Path(p).read_text('utf-8'))
def jsonl(p):
    with Path(p).open(encoding='utf-8') as f:
        for n,line in enumerate(f,1):
            if line.strip():
                try:yield json.loads(line)
                except (TypeError,ValueError) as e:raise SettlementError('INVALID_JSONL_LINE_'+str(n)) from e

def validate_protocol(p):
    must(p.get('schema_version')=='2.0.0','SCHEMA_VERSION')
    must(p.get('research_only') is True and p.get('frozen') is True,'PROTOCOL_MUST_BE_FROZEN_RESEARCH_ONLY')
    must(bool(p.get('symbol')),'EXACT_SYMBOL_REQUIRED')
    a=p.get('account',{})
    must(a.get('account_type')=='ZERO_SPREAD' and a.get('symbol')==p['symbol'],'ZERO_ACCOUNT_SYMBOL_REQUIRED')
    must(a.get('commission_source') in ('BROKER_DEALS','BROKER_TARIFF','SCENARIO_ONLY'),'COMMISSION_PROVENANCE')
    must(a.get('conversion_source') in ('BROKER_ORDER_CALC_PROFIT','BROKER_CONTRACT_VERIFIED','SCENARIO_ONLY'),'CONVERSION_PROVENANCE')
    for k in ('commission_per_lot_side','slippage_price'):number(a.get(k),'BAD_'+k)
    number(a.get('money_per_price_unit_per_lot'),'BAD_CONVERSION',True)
    must(a.get('account_id_hash') and a.get('currency'),'BROKER_ID_REQUIRED')
    f=p.get('folds',[]);must(len(f)>=2,'DEVELOPMENT_AND_OOS_FOLDS_REQUIRED')
    roles=set();prev=None
    for fold in sorted(f,key=lambda z:dt(z['start'])):
        start,end=dt(fold['start']),dt(fold['end']);must(start<end,'INVALID_FOLD')
        must(prev is None or prev<=start,'OVERLAPPING_FOLDS');prev=end
        must(fold.get('id') and fold.get('role') in ('DEVELOPMENT','VALIDATION','FINAL_OOS'),'BAD_FOLD_ROLE')
        roles.add(fold['role'])
    must('DEVELOPMENT' in roles and 'FINAL_OOS' in roles,'OOS_REQUIRED')
    cfg=p.get('settings',{})
    for k in ('max_entry_wait_seconds','max_reference_age_seconds','max_tick_gap_seconds'):
        number(cfg.get(k),'BAD_'+k,True)
    must(type(cfg.get('min_oos_trades'))==int and cfg['min_oos_trades']>=1,'MIN_OOS_TRADES')
    must(type(cfg.get('bootstrap_iterations'))==int and cfg['bootstrap_iterations']>=20,'BOOTSTRAP_ITERATIONS')
    must(type(cfg.get('bootstrap_seed'))==int,'BOOTSTRAP_SEED')
    must(isinstance(p.get('profiles'),dict) and p['profiles'],'PROFILES_REQUIRED')
    for mode,prof in p['profiles'].items():
        must(mode in ('MVP','SMC','SCALPING'),'UNKNOWN_STRATEGY_MODE')
        must(prof.get('strategy_id') and prof.get('strategy_version') and prof.get('spec_hash'),'FROZEN_SPEC_REQUIRED')
        must(prof.get('entry_type')=='MARKET_NEXT_AVAILABLE_TICK','UNSUPPORTED_ENTRY')
        must(prof.get('reference')=='LAST_KNOWN_MT5_MID_QUOTE','BAD_REFERENCE_POLICY')
        must(dt(prof['frozen_at']).tzinfo is not None,'BAD_FREEZE_TIME')
        for k in ('stop_distance','target_distance','lots','max_hold_seconds'):
            number(prof.get(k),'BAD_'+k,True)
    for impact in ('HIGH','EXTREME'):
        w=p.get('macro_windows',{}).get(impact)
        must(isinstance(w,dict),'MISSING_MACRO_WINDOW')
        for k in ('pre','post'):number(w.get(k),'BAD_MACRO_WINDOW')
    return p

def load_ticks(paths,symbol,max_rows=2_000_000):
    """Strict supplied MT5 CSV tick export; no sorting to hide disorder."""
    must(paths,'TICK_FILES_REQUIRED')
    rows=[];seen=set();prev=None;count=0
    for file in paths:
        with open(file,encoding='utf-8-sig',newline='') as f:
            r=csv.DictReader(f);must({'symbol','time_utc','bid','ask','available_at','source_id'}.issubset(r.fieldnames or []),'TICK_FIELDS_MISSING')
            for x in r:
                count+=1;must(count<=max_rows,'TICK_LIMIT_EXCEEDED')
                must(x['symbol']==symbol,'TICK_SYMBOL_MISMATCH')
                must(x['source_id'].startswith('MT5'),'TICK_SOURCE_NOT_MT5')
                t=dt(x['time_utc']);av=dt(x['available_at']);must(t<=av,'TICK_LOOKAHEAD')
                must(prev is None or (t,av)>=prev,'UNSORTED_TICKS');prev=t,av
                bid=number(x['bid'],'BAD_BID',True);ask=number(x['ask'],'BAD_ASK',True);must(bid<=ask,'CROSSED_QUOTES')
                key=(t,av,bid,ask)
                if key in seen:continue
                seen.add(key)
                rows.append({'time':iso(t),'available_at':iso(av),'source_id':x['source_id'],'symbol':symbol,'bid':bid,'ask':ask})
    must(rows,'TICKS_EMPTY')
    must(all(dt(rows[i]['available_at'])>=dt(rows[i-1]['available_at']) for i in range(1,len(rows))),'NONMONOTONIC_TICK_AVAILABILITY')
    return rows

def verify_signal_ledger(signals,events,protocol):
    """Reconcile M06R CONFIRMED signals against historical stage evidence."""
    confirms={};births={};seen=set();selected=[];history=defaultdict(list)
    for e in events:
        must(e.get('execution_permission')=='BLOCKED' and e.get('analysis_only') is True,'UNSAFE_STAGE_LEDGER')
        must(e.get('setup_id') and e.get('available_at'),'MALFORMED_STAGE')
        history[e['setup_id']].append(e)
        if e.get('state')=='EARLY_SETUP' and e.get('event_type')=='DISCOVER':
            births.setdefault(e.get('setup_id'),e)
        if e.get('state')=='CONFIRMED' and e.get('event_type')=='CONFIRM':
            must(e.get('setup_id') not in confirms,'DUPLICATE_CONFIRMED_STAGE')
            confirms[e.get('setup_id')]=e
    for s in signals:
        must(s.get('signal_id') and s['signal_id'] not in seen,'DUPLICATE_SIGNAL_ID');seen.add(s['signal_id'])
        must(s.get('execution_permission')=='BLOCKED' and s.get('fill_status')=='NOT_RUN','SIGNAL_ALREADY_EXECUTED_OR_UNSAFE')
        must(s.get('entry') is None and s.get('stop_loss') is None and s.get('take_profit') is None,'HINDSIGHT_PRICE_FIELDS')
        must(s.get('direction') in ('LONG','SHORT'),'SIGNAL_DIRECTION_REQUIRED')
        must(s.get('mode') in protocol['profiles'],'PROFILE_NOT_CONFIGURED')
        e=confirms.get(s.get('setup_id'));b=births.get(s.get('setup_id'))
        must(e is not None and b is not None,'CONFIRM_AND_DISCOVER_PROOF_REQUIRED')
        must(e.get('available_at')==s.get('available_at')==s.get('signal_at'),'SIGNAL_CONFIRM_TIME_MISMATCH')
        must(e.get('strategy_id')==s.get('strategy_id')==b.get('strategy_id'),'STRATEGY_ID_MISMATCH')
        must(e.get('strategy_version')==s.get('strategy_version')==b.get('strategy_version'),'STRATEGY_VERSION_MISMATCH')
        must(e.get('direction')==s.get('direction')==b.get('direction'),'SIGNAL_SIDE_MISMATCH')
        must(e.get('mode')==s.get('mode')==b.get('mode'),'SIGNAL_MODE_MISMATCH')
        must(dt(b['available_at'])<dt(s['signal_at']),'DISCOVERY_AFTER_CONFIRM')
        chain=history[s['setup_id']]
        expected=('EARLY_SETUP','SETUP_FORMING','QUALIFIED','ARMED','TRIGGERED','CONFIRMED')
        must(tuple(x.get('state') for x in chain)==expected,'MISSING_OR_MISORDERED_LIFECYCLE_STAGES')
        times=[dt(x['available_at']) for x in chain]
        must(all(times[i]<times[i+1] for i in range(len(times)-1)),'LIFECYCLE_TIME_NOT_STRICT')
        must(all(x.get('strategy_id')==s['strategy_id'] and x.get('strategy_version')==s['strategy_version']
                 and x.get('direction')==s['direction'] and x.get('mode')==s['mode'] for x in chain),'LIFECYCLE_IDENTITY_CHANGED')
        bars=[x.get('bar_evidence_id') for x in chain if x.get('bar_evidence_id')]
        must(len(bars)==len(set(bars)),'REUSED_CLOSED_BAR_EVIDENCE')
        prof=protocol['profiles'][s['mode']]
        must(prof['strategy_version']==s['strategy_version'] and prof['strategy_id']==s['strategy_id'],'FROZEN_PROFILE_VERSION_MISMATCH')
        must(dt(prof['frozen_at'])<=dt(b['available_at']),'PLAN_NOT_FROZEN_BEFORE_DISCOVERY')
        selected.append((s,e,b,prof))
    must(len(signals)==len(confirms),'ORPHANED_CONFIRM_OR_SIGNAL')
    return selected

def verify_m06r_report(report,signals,stages,symbol):
    must(report.get('module_id')=='M06R_HISTORICAL_STRATEGY_REPLAY','NOT_M06R_REPORT')
    must(report.get('schema_version')=='2.0.0' and report.get('symbol')==symbol,'REPLAY_REPORT_SYMBOL_SCHEMA_MISMATCH')
    must(report.get('status')=='REPLAY_RESEARCH_COMPLETE' and report.get('execution_permission')=='BLOCKED',
         'REPLAY_REPORT_NOT_COMPLETED_OR_SAFE')
    must(report.get('signal_count')==len(signals),'REPLAY_SIGNAL_COUNT_MISMATCH')
    must(report.get('confirmed_signals')==signals,'REPLAY_SIGNALS_DIFFER_FROM_REPORT')
    must(report.get('stage_transitions')==stages,'REPLAY_STAGES_DIFFER_FROM_REPORT')
    return True

def macro_block(s,events,windows):
    now=dt(s['available_at']);hits=[]
    for ev in events:
        if ev.get('type')!='CALENDAR' or ev.get('impact') not in ('HIGH','EXTREME'):continue
        if ev.get('synthetic') is True:continue  # demonstration macro cannot establish historical empirical filter
        if ev['known_at']>now or ev.get('impact_known_at',ev['known_at'])>now:continue
        when=ev['scheduled_at'];window=windows[ev['impact']]
        if when-timedelta(minutes=window['pre'])<=now<=when+timedelta(minutes=window['post']):
            hits.append(ev['event_id'])
    return sorted(set(hits))

def metrics(rows):
    done=[r for r in rows if r.get('status')=='COMPLETED']
    if not done:return {'trades':0,'mean_net_pnl':None,'mean_net_r':None,'win_rate':None,'profit_factor':None,'max_drawdown_money':None}
    return m06.metric(done)

def build_packet(p,ticks,signals,asof,label):
    cfg=p['settings'];ds={'data_source_policy':POLICY,'visual_capture_enabled':False,'analysis_gate':{'status':'PASS_WITH_LIMITATIONS'},
        'dataset_id':'M06T:SUPPLIED_MT5_CSV_UNCERTIFIED','snapshot_id':'M06T:'+sha([label,iso(asof)])[:20],'as_of':iso(asof)}
    return {'schema_version':'2.0.0','run_id':'M06T-'+label,'data_snapshot':ds,
        'market_state':{'snapshot_id':ds['snapshot_id'],'as_of':ds['as_of'],'analysis_gate':{'status':'PASS_WITH_LIMITATIONS'}},
        'account':p['account'],'ticks':ticks,'signals':signals,'trial_ledger':[{'protocol_hash':sha(p),'profile':k,'frozen_at':v['frozen_at']} for k,v in p['profiles'].items()],
        'validation_profile':{'folds':p['folds'],'acceptance_criteria_frozen':True,'forward_demo_required':True,
          'max_entry_wait_seconds':cfg['max_entry_wait_seconds'],'min_completed_oos_trades':cfg['min_oos_trades'],
          'bootstrap_iterations':cfg['bootstrap_iterations'],'bootstrap_seed':cfg['bootstrap_seed'],'confidence_level':.95}}

def settle_with_preserved_m06(packet):
    """Call the *unchanged* M06 validator & trade_one, with bounded tick slices.

    Avoids O(all_ticks * signals), without changing fill/stop/target accounting rules.
    """
    as_of,acct,profile,folds,money,commission,slip,max_age=m06.validate_config(packet)
    all_ticks=m06.prepare_ticks(packet,as_of,acct)
    availability=[x['available_at'] for x in all_ticks]
    output=[]
    for s in packet['signals']:
        at=dt(s['available_at']);expiry=at+timedelta(seconds=max_age+s['max_hold_seconds'])
        lo=bisect_left(availability,at)
        hi=min(len(all_ticks),bisect_right(availability,expiry)+1)
        # +1 is needed for M06's conservative handling of a quote after expiry.
        output.append(m06.trade_one(s,all_ticks[lo:hi],acct,profile,folds,money,commission,slip,max_age,as_of))
    return output

def run(signals,stages,ticks,protocol,events=None,macro_mode='NOT_PROVIDED'):
    p=validate_protocol(protocol)
    assert_ticks=all(x['symbol']==p['symbol'] for x in ticks);must(assert_ticks,'TICK_SYMBOL_MISMATCH')
    verified=verify_signal_ledger(signals,stages,p)
    must(len(ticks)>0,'TICKS_REQUIRED')
    asof=dt(ticks[-1]['available_at'])
    must(asof>=max(dt(f['end']) for f in p['folds']),'FOLDS_AFTER_TICK_EXPORT')
    tick_times=[dt(t['available_at']) for t in ticks]
    eligible=[];excluded=[];mflags=[]
    for s,e,b,prof in verified:
        sat=dt(s['available_at'])
        # Configured frozen quote-based bracket, not historical optimal path or hindsight swing levels.
        idx=bisect_right(tick_times,sat)-1
        if idx<0:
            excluded.append({'signal_id':s['signal_id'],'reason':'NO_REFERENCE_QUOTE'});continue
        ref=ticks[idx];age=(sat-tick_times[idx]).total_seconds()
        if age>p['settings']['max_reference_age_seconds']:
            excluded.append({'signal_id':s['signal_id'],'reason':'REFERENCE_QUOTE_STALE'});continue
        centre=(ref['bid']+ref['ask'])/2
        stop=centre-prof['stop_distance'] if s['direction']=='LONG' else centre+prof['stop_distance']
        target=centre+prof['target_distance'] if s['direction']=='LONG' else centre-prof['target_distance']
        if min(stop,target)<=0:
            excluded.append({'signal_id':s['signal_id'],'reason':'NONPOSITIVE_PRICE_BRACKET'});continue
        # M06 requires a real next tick > signal time for the simulated market entry.
        if idx+1<len(ticks) and (tick_times[idx+1]-sat).total_seconds()<=p['settings']['max_entry_wait_seconds']:
            fill=ticks[idx+1]['ask']+p['account']['slippage_price'] if s['direction']=='LONG' else ticks[idx+1]['bid']-p['account']['slippage_price']
            if not ((stop<fill<target) if s['direction']=='LONG' else (target<fill<stop)):
                excluded.append({'signal_id':s['signal_id'],'reason':'ENTRY_BRACKET_INVALID_AT_FIRST_TICK'});continue
        row={'signal_id':s['signal_id'],'side':s['direction'],'symbol':p['symbol'],'source':'MT5_DERIVED',
           'bar_state':'CLOSED','strategy_version':s['strategy_version'],'spec_hash':prof['spec_hash'],
           'signal_at':s['signal_at'],'available_at':s['available_at'],
           'feature_available_at':[b['available_at'],e['available_at']],
           'stop':stop,'target':target,'lots':prof['lots'],'max_hold_seconds':prof['max_hold_seconds'],
           'entry_type':'MARKET_NEXT_AVAILABLE_TICK'}
        eligible.append(row)
        flag={'signal_id':s['signal_id'],'mode':s['mode'],'strategy_version':s['strategy_version'],'fold':'UNKNOWN',
              'bracket_basis':'FROZEN_DISTANCE_FROM_LAST_KNOWN_BROKER_MID_QUOTE','quote_reference_at':ref['available_at'],
              'macro':'UNKNOWN' if events is None else 'PASS','macro_event_ids':[]}
        if events is not None:
            hits=macro_block(s,events,p['macro_windows']);flag['macro']='BLOCK' if hits else 'NO_KNOWN_WINDOW_PARTIAL_COVERAGE';flag['macro_event_ids']=hits
        mflags.append(flag)
    if not eligible:
        return {'module_id':'M06T','module_version':VERSION,'schema_version':'2.0.0','status':'NOT_RUN',
            'reason_codes':['NO_ELIGIBLE_SIGNALS_FOR_SETTLEMENT'],'input_signals':len(signals),'excluded':excluded,
            'macro_coverage':macro_mode,'execution_permission':'BLOCKED','live_eligible':False,'metrics':{},'trades':[]}
    packet=build_packet(p,ticks,eligible,asof,'BASELINE')
    # Genuine preserved M06 core, not independently invented PnL math.
    trades=settle_with_preserved_m06(packet);byid={x['signal_id']:x for x in trades}
    for f in mflags:
        tr=byid[f['signal_id']]
        f['fold']=tr.get('fold_role','UNKNOWN')
        if tr.get('status')=='COMPLETED':
            begin,end=dt(tr['entry_at']),dt(tr['exit_at'])
            left=bisect_right(tick_times,begin)-1;right=bisect_right(tick_times,end)-1
            spans=[(tick_times[i+1]-tick_times[i]).total_seconds() for i in range(left,right) ]
            if spans and max(spans)>p['settings']['max_tick_gap_seconds']:
                tr['status']='UNVERIFIED_TICK_GAP';tr['reason_codes']=['TICK_GAP_ON_EXECUTION_PATH']
                # NEVER keep a gap-derived PnL as validated result.
                for k in ('net_pnl','gross_pnl','net_r','initial_risk'):tr[k]=None
        tr['macro_status']=f['macro'];tr['macro_event_ids']=f['macro_event_ids'];tr['profile_name']=f['mode']
        tr['execution_permission']='BLOCKED';tr['simulation_only']=True
    total=metrics(trades)
    bymode={}
    for mode in ('MVP','SMC','SCALPING'):
        relevant=[x for x in trades if x['profile_name']==mode]
        bymode[mode]={'all':metrics(relevant),'development':metrics([x for x in relevant if x.get('fold_role')=='DEVELOPMENT']),
                      'final_oos':metrics([x for x in relevant if x.get('fold_role')=='FINAL_OOS']),
                      'statuses':dict(Counter(x['status'] for x in relevant))}
    comparison={'status':'NOT_RUN','reason':'HISTORICAL_MACRO_ARCHIVE_NOT_PROVIDED'}
    if events is not None and any(not e.get('synthetic') for e in events):
        allowed={x['signal_id'] for x in mflags if x['macro']!='BLOCK'}
        with_news=[t for t in trades if t['signal_id'] in allowed]
        breakdown={}
        for name in ('MVP','SMC','SCALPING'):
            before=[t for t in trades if t['profile_name']==name]
            after=[t for t in with_news if t['profile_name']==name]
            breakdown[name]={'before':metrics(before),'after':metrics(after),
                             'oos_before':metrics([t for t in before if t.get('fold_role')=='FINAL_OOS']),
                             'oos_after':metrics([t for t in after if t.get('fold_role')=='FINAL_OOS'])}
        comparison={'status':'EXPLORATORY_PARTIAL_COVERAGE','macro_archive_type':macro_mode,
          'before':metrics(trades),'after':metrics(with_news),'by_strategy':breakdown,
          'oos_before':metrics([t for t in trades if t.get('fold_role')=='FINAL_OOS']),
          'oos_after':metrics([t for t in with_news if t.get('fold_role')=='FINAL_OOS']),
          'blocked_signals':len(trades)-len(with_news),
          'selection_note':'Macro windows use ONLY information known by signal time; missing events do not prove calendar completeness.'}
    elif events is not None:
        comparison={'status':'NOT_RUN','reason':'ONLY_SYNTHETIC_OR_EMPTY_MACRO_EVENTS','macro_archive_type':macro_mode}
    complete=[x for x in trades if x['status']=='COMPLETED']
    sensitivity=[]
    for multiplier in (1.,1.25,1.5,2.):
        pnl=[]
        for t in complete:
            lot=p['profiles'][t['profile_name']]['lots']
            extra=(multiplier-1)*(t['commission']+2*t['slip_price_each_side']*p['account']['money_per_price_unit_per_lot']*lot)
            pnl.append(t['net_pnl']-extra)
        sensitivity.append({'commission_slippage_multiplier':multiplier,
            'average_projected_net_pnl':round(sum(pnl)/len(pnl),8) if pnl else None,
            'spread_stress':'NOT_MODELED','method':'SENSITIVITY_NOT_NEW_BROKER_QUOTES'})
    byfold={f['id']:metrics([x for x in complete if x.get('fold_id')==f['id']]) for f in p['folds']}
    warnings=['SIMULATED_QUOTES_NOT_BROKER_FILLS','TICK_EXPORT_UNCERTIFIED_SOURCE','BROKER_QUOTE_TIMESTAMP_DOES_NOT_PROVE_LOCAL_RECEIPT',
      'NO_LIVE_EXECUTION','NO_FORWARD_DEMO','INDEPENDENT_TRADES_NOT_PORTFOLIO_EQUITY','EX_ANTE_PROTOCOL_TIMESTAMP_USER_DECLARED_NOT_CRYPTOGRAPHICALLY_PROVEN']
    if p['account']['commission_source']=='SCENARIO_ONLY' or p['account']['conversion_source']=='SCENARIO_ONLY':warnings.append('COSTS_ARE_SCENARIOS_NOT_VERIFIED')
    if comparison['status']=='NOT_RUN':warnings.append('MACRO_STUDY_NOT_RUN')
    if any(t['status']=='UNVERIFIED_TICK_GAP' for t in trades):warnings.append('QUOTE_GAP_EXCLUSIONS')
    oos_count=sum(t.get('status')=='COMPLETED' and t.get('fold_role')=='FINAL_OOS' for t in trades)
    if oos_count<p['settings']['min_oos_trades']:warnings.append('INSUFFICIENT_FINAL_OOS_SAMPLE')
    if any(t['status'] not in ('COMPLETED',) for t in trades):warnings.append('INCOMPLETE_QUOTE_SETTLEMENTS_EXCLUDED_FROM_METRICS')
    return {'module_id':'M06T','module_version':VERSION,'schema_version':'2.0.0','status':'RESEARCH_ONLY',
       'protocol_hash':sha(p),'tick_count':len(ticks),'input_signals':len(signals),'eligible_signals':len(eligible),
       'excluded':excluded,'metrics':{'all':total,'by_strategy':bymode,'by_fold':byfold},
       'macro_coverage':macro_mode,'macro_comparison':comparison,'cost_sensitivity':sensitivity,
       'trades':trades,'warnings':warnings,
       'oos_approved':False,'execution_permission':'BLOCKED','live_eligible':False}

def report_md(r):
    lines=['# MasterQUO M06T — raport walidacji','',f"Status: **{r['status']}**",'',
      f"Sygnały wejściowe: {r.get('input_signals',0)}; rozliczalne kandydaty: {r.get('eligible_signals',0)}.",
      '', '| Tryb | Wszystkie zakończone | OOS zakończone | Średnia R OOS |', '|---|---:|---:|---:|']
    for mode,metric in r.get('metrics',{}).get('by_strategy',{}).items():
        os=metric['final_oos'];lines.append(f"| {mode} | {metric['all']['trades']} | {os['trades']} | {os['mean_net_r'] if os['mean_net_r'] is not None else 'N/D'} |")
    lines+=['','## Ograniczenia','','Wynik jest badawczą symulacją kwotowań, a nie historią faktycznych zleceń MT5.',
     'Nie ma autoryzacji LIVE ani udowodnionej przewagi OOS. Braki ticków, niezarejestrowane koszty i niekompletny kalendarz ograniczają wnioski.',
     '', '## Weryfikacja','','- Wymagany eksport ticków Bid/Ask od brokera, historia sygnałów i dziennik M06R.',
     '- Zamrożone parametry wejścia, wolumen, koszty, zakresy DEV/OOS.',
     '- Wynik netto w M06 nie jest faktycznym wykonaniem zleceń.', '']
    return '\n'.join(lines)

def cli(argv=None):
    a=argparse.ArgumentParser(description='M06T offline settled point-in-time research only')
    a.add_argument('--signals',required=True);a.add_argument('--ledger',required=True)
    a.add_argument('--ticks',required=True,nargs='+');a.add_argument('--max-ticks',type=int,default=2_000_000)
    a.add_argument('--protocol',required=True)
    a.add_argument('--events');a.add_argument('--replay-report',help='Recommended original M06R_REPLAY_REPORT.json cross-check')
    a.add_argument('--out-dir',default='results_m06t')
    args=a.parse_args(argv)
    out=Path(args.out_dir);out.mkdir(parents=True,exist_ok=True)
    try:
        p=validate_protocol(jsonread(args.protocol))
        must(1<=args.max_ticks<=10_000_000,'INVALID_MAX_TICKS')
        ticks=load_ticks(args.ticks,p['symbol'],max_rows=args.max_ticks);signals=list(jsonl(args.signals));stages=list(jsonl(args.ledger))
        if args.replay_report:verify_m06r_report(jsonread(args.replay_report),signals,stages,p['symbol'])
        events=None;mode='NOT_PROVIDED'
        if args.events:events,mode=m06h.load_events(args.events)
        result=run(signals,stages,ticks,p,events,mode)
        if not args.replay_report:
            result.setdefault('warnings',[]).append('ORIGINAL_M06R_REPLAY_REPORT_NOT_CROSS_CHECKED')
        result['input_sha256']=[{'filename':str(Path(q).name),'sha256':hashlib.sha256(Path(q).read_bytes()).hexdigest()}
            for q in [args.signals,args.ledger,args.protocol,*args.ticks]+([args.events] if args.events else [])+([args.replay_report] if args.replay_report else [])]
        result['data_sources_unverified']=True
        (out/'M06T_REPORT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        (out/'M06T_REPORT_PL.md').write_text(report_md(result),encoding='utf-8')
        print(json.dumps({'status':result['status'],'signals':len(signals),'trades':result['metrics'].get('all',{}).get('trades',0),
          'report':str(out/'M06T_REPORT.json'),'execution_permission':'BLOCKED'}))
        return 0
    except (SettlementError,m06.ValidationError,m06h.ResearchError,ValueError,TypeError,KeyError,OSError) as e:
        report={'module_id':'M06T','status':'FAIL','reason_codes':[str(e)],'execution_permission':'BLOCKED','live_eligible':False}
        (out/'M06T_REPORT.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report));return 2
if __name__=='__main__':sys.exit(cli())
