"""MasterQUO M06R historical signal replay v1.0.0 CANDIDATE.

Research-only; accepts independently exported MT5 D1/H4/H1/M15/M5/M1 CLOSED BID
candles. Runs unchanged M02, M02I, M03, M07 detector and M10A rule checks.
Never interprets a simulated signal as a broker trade/fill/profit. User-supplied
CSV cannot be authenticated as broker data. Absolutely NO order or network API.
"""
from __future__ import annotations
import argparse
import copy
from bisect import bisect_right
from collections import Counter
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent
for sub in ('M02','M02I','M03'):
    sys.path.insert(0,str(ROOT/'vendor'/sub))
from M02_REFERENCE_ENGINE import analyze as market_analyze
from M02I_INDICATOR_ENGINE import analyze as indicator_analyze
from M03_REFERENCE_ENGINE import analyze as structure_analyze
from M07_M03E_PROFILE_DETECTOR import discover, read_config, hashed
from M03E_M10_PIPELINE import construct_early
from M10_AUTO_TRIGGER_CONFIRM import matched, rules_valid
from vendor.M03.M03_REFERENCE_ENGINE import early_assessment

TF={'M1':60,'M5':300,'M15':900,'H1':3600,'H4':14400,'D1':86400}
ORDER=('D1','H4','H1','M15','M5','M1')
MODE=('MVP','SMC','SCALPING','AUTO')
VERSION='1.0.0-CANDIDATE'
POLICY='MT5_PRIMARY_TV_SUPPLEMENTAL_NO_SCREENSHOTS'
UTC=timezone.utc

class ReplayError(ValueError):pass

def check(v,msg):
    if not v:raise ReplayError(msg)

def stamp(d):return d.astimezone(UTC).isoformat().replace('+00:00','Z')

def parse_time(v):
    try:d=datetime.fromisoformat(str(v).replace('Z','+00:00'))
    except (ValueError,TypeError) as e:raise ReplayError('INVALID_TIMESTAMP') from e
    check(d.tzinfo is not None and d.utcoffset() is not None,'NAIVE_TIMESTAMP')
    return d.astimezone(UTC)

def fnum(value):
    try:n=float(value)
    except (TypeError,ValueError) as e:raise ReplayError('INVALID_OHLC_NUMBER') from e
    check(math.isfinite(n),'NONFINITE_OHLC')
    return n

def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()

def load_csv(path,tf,symbol):
    """Strict read. No sorting/revision resolution: bad source order aborts research."""
    check(tf in TF,'UNKNOWN_TF')
    path=Path(path)
    check(path.is_file(),'MISSING_CSV_'+tf)
    out=[];prior=None
    with path.open('r',encoding='utf-8-sig',newline='') as fh:
        reader=csv.DictReader(fh)
        check(reader.fieldnames is not None,'EMPTY_CSV_'+tf)
        req={'symbol','time_utc','open','high','low','close','bar_state'}
        check(req.issubset(reader.fieldnames),'CSV_COLUMNS_MISSING_'+tf)
        for line,r in enumerate(reader,2):
            check(r['symbol']==symbol,'SYMBOL_MISMATCH_'+tf)
            check(r['bar_state']=='CLOSED','NONCLOSED_BAR_'+tf)
            start=parse_time(r['time_utc'])
            check(prior is None or start>prior,'NONMONOTONIC_OR_DUPLICATE_'+tf)
            prior=start
            close=start+timedelta(seconds=TF[tf])
            # Historical export may contain an explicit known-at timestamp; only later one wins.
            available=parse_time(r['available_at_utc']) if r.get('available_at_utc') else close
            check(available>=close,'PREMATURE_AVAILABLE_'+tf)
            o,h,l,c=(fnum(r[z]) for z in ('open','high','low','close'))
            check(all(v>0 for v in (o,h,l,c)) and l<=min(o,c)<=max(o,c)<=h,'BAD_OHLC_'+tf)
            volume=None
            if r.get('tick_volume') not in ('',None):
                volume=fnum(r['tick_volume']);check(volume>=0,'BAD_VOLUME_'+tf)
            out.append({'start':start,'available':available,
                        'instrument_id':'XAUUSD','exact_symbol':symbol,
                        'timeframe':tf,'bar_state':'CLOSED','price_basis':'BID',
                        'source_id':'MT5:CSV_REPLAY_UNVERIFIED',
                        'evidence_id':'MT5:REPLAY:'+tf+':'+stamp(start),
                        'bar_open_utc':stamp(start),'close_confirmed_at':stamp(close),
                        'available_at':stamp(available),'open':o,'high':h,'low':l,'close':c,
                        'tick_volume':volume,'revision':0})
    check(out,'NO_BARS_'+tf)
    # Distinct bars may have delayed availability, but must be ordered for binary search.
    check(all(out[i]['available']>out[i-1]['available'] for i in range(1,len(out))),'NONMONOTONIC_AVAILABILITY_'+tf)
    return out

def load_bundle(folder,symbol='XAUUSD'):
    folder=Path(folder)
    manifest_path=folder/'MT5_EXPORT_MANIFEST.json'
    if manifest_path.is_file():
        manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
        check(manifest.get('symbol')==symbol,'MANIFEST_SYMBOL_MISMATCH')
        check(set((manifest.get('files') or {}).keys())==set(ORDER),'MANIFEST_TIMEFRAMES_INVALID')
        for tf in ORDER:
            disk=folder/(tf+'.csv')
            check(disk.is_file(),'MANIFEST_CSV_MISSING_'+tf)
            sig=hashlib.sha256(disk.read_bytes()).hexdigest()
            check(sig==manifest['files'][tf].get('sha256'),'MANIFEST_SHA256_MISMATCH_'+tf)
    bank={tf:load_csv(folder/(tf+'.csv'),tf,symbol) for tf in ORDER}
    if manifest_path.is_file():
        for tf in ORDER:
            check(len(bank[tf])==manifest['files'][tf].get('bars'),'MANIFEST_BAR_COUNT_MISMATCH_'+tf)
    return bank

def checkpoint(snapshot_time,bundle,symbol,min_closed=230,history_cap=300,available_index=None):
    """Build an as-of immutable snapshot. Excludes bars unless available_at <= as_of."""
    check(min_closed>=40 and history_cap>=min_closed,'INVALID_HISTORY_SETTINGS')
    candles={};pending=[]
    for tf in ORDER:
        rows=bundle[tf]
        n=bisect_right(available_index[tf] if available_index is not None else [z['available'] for z in rows],snapshot_time)
        seq=rows[max(0,n-history_cap):n]
        if len(seq)<min_closed:pending.append('WARMUP_'+tf)
        elif snapshot_time-seq[-1]['available']>timedelta(seconds={
            'M1':300,'M5':900,'M15':2700,'H1':10800,'H4':57600,'D1':259200}[tf]):
            pending.append('HISTORICAL_TIMEFRAME_STALE_'+tf)
        # NEVER fabricate bars across market closure or terminal history gaps.
        candles[tf]=[{k:v for k,v in bar.items() if k not in ('start','available')} for bar in seq]
    identity=digest([symbol,stamp(snapshot_time),[(tf,candles[tf][-1]['evidence_id'] if candles[tf] else None) for tf in ORDER]])[:24]
    # PASS_WITH_LIMITATIONS is an **offline simulation-only analytical gate**.
    # It does NOT claim M01 broker certification or LIVE permissions.
    ag='PENDING' if pending else 'PASS_WITH_LIMITATIONS'
    return {'schema_version':'2.0.0','analysis_id':'M06R-OFFLINE-'+identity,
            'snapshot_id':'M06R:'+identity,'as_of':stamp(snapshot_time),
            'instrument_id':'XAUUSD','exact_symbol':symbol,'strategy_version':'REPLAY_PROVISIONAL',
            'candles_by_tf':candles,'data_source_policy':POLICY,
            'visual_capture_enabled':False,'screenshot_capture_enabled':False,
            'analysis_gate':{'status':ag,'reason_codes':pending},
            'data_gates':[{'gate_id':'M06R_POINT_IN_TIME_ANALYSIS_REPLAY_ONLY',
                 'status':ag,'required_for':['ANALYSIS','DIRECTION'],'reason_codes':pending},
                 {'gate_id':'M01_BROKER_EXECUTION','status':'PENDING','required_for':['EXECUTION'],
                  'reason_codes':['HISTORICAL_CSV_NOT_AUTHENTICATED']}],
            '_fixture_only':True,'_preview_only':True,'replay_only':True,
            'execution_gate':{'status':'PENDING'},'execution_permission':'BLOCKED',
            'input_trust':'UNVERIFIED_USER_SUPPLIED_CSV'}

def independent_market(snapshot,mode):
    """Use UNMODIFIED M02/M02I/M03 engines on the same historical snapshot."""
    cp=json.loads((ROOT/'vendor/M02/M02_PROFILE.example.json').read_text('utf-8'))
    ip=json.loads((ROOT/'vendor/M02I/M02I_PROFILE_MT5_TIMEFRAMES_v1.1.json').read_text('utf-8'))
    p3=json.loads((ROOT/'M03_PROFILE.example.json').read_text('utf-8'))
    # Original M02 expects H4/H1 for SCALP; preserve this stable definition across all profiles.
    m02=market_analyze(snapshot,cp,runtime_health={'status':'UNKNOWN','execution_data_gate':'PENDING'})
    m02i=indicator_analyze({'data_snapshot':snapshot,'market_state':m02},ip)
    m03=structure_analyze(snapshot,m02,p3)
    check(m02['snapshot_id']==m03['snapshot_id']==m02i['snapshot_id'],'SNAPSHOT_MISMATCH')
    return m02,m02i,m03

STAGE={'EARLY_SETUP':('DEVELOPMENT','SETUP_FORMING',None),
       'SETUP_FORMING':('QUALIFY','QUALIFIED','qualification'),
       'QUALIFIED':('ARM','ARMED','arming'),
       'ARMED':('TRIGGER','TRIGGERED','trigger'),
       'TRIGGERED':('CONFIRM','CONFIRMED','confirmation')}
TERMINAL={'CONFIRMED','INVALIDATED','EXPIRED','GAP_REVIEW'}

class HistoricalLifecycle:
    """Replay-only lifecycle ledger following M10 stages and M10A predicates.

    This is NOT a broker event, LIVE M10 state-store, or fabricated M09 authorization.
    """
    def __init__(self,ttl=20):
        check(isinstance(ttl,int) and ttl>=5,'INVALID_TTL')
        self.ttl=ttl;self.active={};self.seen={};self.transitions=[];self.confirmed=[]
    def accept(self,plan,snapshot,m02,m03):
        mode=plan['profile_name']
        if mode in self.active:return False
        proof=early_assessment(m03,m02,plan)
        candidate,reasons=construct_early({**m03,'early_evidence':proof},m02,snapshot,plan)
        if candidate is None:return False
        rule,error=rules_valid(plan,candidate,m02,m03)
        if error:return False
        sid=candidate['setup_id']
        if sid in self.seen:return False # never replay same evidence as a newly created signal
        last=snapshot['candles_by_tf'][plan['setup_tf']][-1]
        plan=copy.deepcopy(plan)
        self.active[mode]={'setup_id':sid,'mode':mode,'strategy_id':plan['strategy_id'],
                          'strategy_version':plan['version'],'spec_hash':plan['spec_hash'],
                          'direction':plan['intended_direction'],'state':'EARLY_SETUP',
                          'created_at':snapshot['as_of'],'plan':plan,'birth_bar':last['bar_open_utc'],
                          'last_bar':last['bar_open_utc'],'bars_age':0,
                          'event_id':plan['created_event_id']}
        self.seen[sid]=mode
        self._log(self.active[mode],snapshot['as_of'],'DISCOVER','EARLY_SETUP',last)
        return True
    def _log(self,a,now,event,new,bar):
        item={'event_id':'M06R:'+digest([a['setup_id'],event,bar['bar_open_utc']])[:24],
              'setup_id':a['setup_id'],'mode':a['mode'],'strategy_id':a['strategy_id'],
              'strategy_version':a['strategy_version'],'direction':a['direction'],
              'event_type':event,'state':new,'available_at':now,
              'bar_open_utc':bar['bar_open_utc'],'bar_evidence_id':bar['evidence_id'],
              'analysis_only':True,'execution_permission':'BLOCKED'}
        self.transitions.append(item)
        if new=='CONFIRMED':
            self.confirmed.append({'signal_id':'M06R:'+digest([a['setup_id'],'CONFIRMED'])[:24],
                    'setup_id':a['setup_id'],'signal_at':now,'available_at':now,
                    'direction':a['direction'],'mode':a['mode'],'strategy_id':a['strategy_id'],
                    'strategy_version':a['strategy_version'],'setup_tf':a['plan']['setup_tf'],
                    'entry':None,'stop_loss':None,'take_profit':None,'fill_status':'NOT_RUN',
                    'broker_cost_status':'NOT_RUN','M06_import_status':'REQUIRES_EXECUTION_PLAN_AND_TICKS',
                    'execution_permission':'BLOCKED'})
    def advance(self,snapshot):
        """At most one transition per newly-available setup-TF closed candle."""
        asof=snapshot['as_of']
        for mode,a in list(self.active.items()):
            tf=a['plan']['setup_tf'];bars=snapshot['candles_by_tf'][tf]
            if not bars:continue
            latest=bars[-1]
            key=latest['bar_open_utc']
            if key==a['last_bar']:continue
            prev=parse_time(a['last_bar']);curr=parse_time(key)
            # More than one missing bar or weekend unverified: fail closed; never stitch an event sequence.
            if curr-prev!=timedelta(seconds=TF[tf]):
                a['state']='GAP_REVIEW';self._log(a,asof,'DATA_GAP','GAP_REVIEW',latest)
                self.active.pop(mode,None);continue
            a['last_bar']=key;a['bars_age']+=1
            inv=a['plan']['invalidation']['condition']
            if matched(inv,latest):
                a['state']='INVALIDATED';self._log(a,asof,'INVALIDATE','INVALIDATED',latest)
                self.active.pop(mode,None);continue
            if a['bars_age']>=self.ttl:
                a['state']='EXPIRED';self._log(a,asof,'EXPIRE','EXPIRED',latest)
                self.active.pop(mode,None);continue
            if a['state'] not in STAGE:continue
            event,target,rule=STAGE[a['state']]
            # EARLY->SETUP_FORMING merely means a new valid closed bar has arrived.
            if rule is None or matched(a['plan']['lifecycle_rules'][rule],latest):
                a['state']=target;self._log(a,asof,event,target,latest)
                if target in TERMINAL:self.active.pop(mode,None)

def run_replay(bundle,*,mode='AUTO',symbol='XAUUSD',step_tf='M5',min_closed=230,
               history_cap=300,max_steps=2000,ttl=20,from_utc=None,to_utc=None):
    check(mode in MODE,'INVALID_MODE')
    check(step_tf in ('M5','M15'),'INVALID_REPLAY_STEP')
    check(type(max_steps)==int and 1<=max_steps<=100000,'INVALID_STEP_COUNT')
    check(type(history_cap)==int and history_cap>=min_closed,'BAD_WINDOW')
    # The six independently exported timeframes, all required. No M1->D1/H4 resampling.
    check(set(bundle)==set(ORDER),'REQUIRED_SIX_TIMEFRAMES')
    available_index={tf:[r['available'] for r in bundle[tf]] for tf in ORDER}
    lower=parse_time(from_utc) if from_utc else None
    upper=parse_time(to_utc) if to_utc else None
    if lower and upper:check(lower<upper,'INVALID_REPLAY_INTERVAL')
    times=[r['available'] for r in bundle[step_tf] if (lower is None or r['available']>=lower)
           and (upper is None or r['available']<upper)]
    attempts=0;warmup=0;analyzed=0;diagnostics=Counter();life=HistoricalLifecycle(ttl)
    samples=[];first=None;last=None
    for when in times:
        if attempts>=max_steps:break
        snapshot=checkpoint(when,bundle,symbol,min_closed,history_cap,available_index)
        if snapshot['analysis_gate']['status']!='PASS_WITH_LIMITATIONS':
            warmup+=1;continue
        attempts+=1
        if first is None:first=when
        last=when
        try:
            m02,m02i,m03=independent_market(snapshot,mode)
        except (ValueError,KeyError,TypeError,ZeroDivisionError) as exc:
            diagnostics['ENGINE_ERROR_'+type(exc).__name__]+=1
            continue
        if (m02.get('status') not in ('PASS','PASS_WITH_LIMITATIONS') or
            m03.get('status') not in ('PASS','PASS_WITH_LIMITATIONS')):
            diagnostics['ENGINE_GATE_PENDING']+=1
            continue
        analyzed+=1
        life.advance(snapshot)
        try:
            research=discover(snapshot,m02,m03,mode=mode)
        except (ValueError,KeyError,TypeError,ZeroDivisionError) as exc:
            diagnostics['DETECTOR_ERROR_'+type(exc).__name__]+=1
            continue
        for why in research.get('reason_codes') or []:diagnostics[why]+=1
        plan=research.get('selected_plan')
        if plan is not None and not (mode=='AUTO' and life.active):
            if life.accept(plan,snapshot,m02,m03):diagnostics['EARLY_NEW']+=1
            else:diagnostics['EARLY_REJECTED_OR_ALREADY_ACTIVE']+=1
        if len(samples)<6:
            samples.append({'as_of':snapshot['as_of'],'snapshot_id':snapshot['snapshot_id'],
                'm02':m02['status'],'m03':m03['status'],'m02i':m02i.get('status'),
                'mode':mode,'chosen_profile':research.get('candidate_status')})
    return {'module_id':'M06R_HISTORICAL_STRATEGY_REPLAY','module_version':VERSION,
            'schema_version':'2.0.0','prompt_version':'4.1.0',
            'status':'REPLAY_RESEARCH_COMPLETE' if analyzed else 'ANALYSIS_PENDING' if attempts else 'INSUFFICIENT_HISTORY',
            'symbol':symbol,'mode':mode,'step_timeframe':step_tf,
            'input_trust':'UNVERIFIED_MT5_CSV_OR_SYNTHETIC','historical_data_certified':False,
            'bars_count':{tf:len(bundle[tf]) for tf in ORDER},
            'steps_analyzed':analyzed,'steps_attempted':attempts,'warmup_skipped':warmup,
            'replay_from_utc':stamp(first) if first else None,
            'replay_to_utc':stamp(last) if last else None,
            'window_filtered_from':from_utc,'window_filtered_to':to_utc,
            'truncated_by_step_limit':len(times)>attempts+warmup,
            'reason_counts':dict(sorted(diagnostics.items())),
            'research_setups_seen':len(life.seen),
            'stage_transitions':life.transitions,'confirmed_signals':life.confirmed,
            'signal_count':len(life.confirmed),'sample_snapshots':samples,
            'strategy_net_performance':{'status':'NOT_RUN','reason':'REQUIRES_REAL_BROKER_BID_ASK_TICKS_AND_M06_COST_MODEL'},
            'execution_permission':'BLOCKED','live_execution_allowed':False,
            'broker_order_sent':False,'screen_capture_count':0,'research_only':True,
            'limitations':['M07_PROVISIONAL_NOT_OOS_APPROVED','REPLAY_ONLY_NOT_M01_LIVE_AUDIT',
                'M10A_RULE_SEMANTICS_REPLAY_NOT_LIVE_M10_SQLITE_EXECUTION','USER_CSV_PROVENANCE_NOT_AUTHENTICATED',
                'NO_HISTORICAL_TICK_FILLS','NO_GUARANTEED_EDGE','NO_AUTO_ORDER_EXECUTION']}

def apply_macro_archive(result,events_path=None,config_path=None):
    """Optional archived point-in-time M06H macro annotations, never clearance.

    If no archive is provided, even a technically CONFIRMED setup has UNKNOWN macro
    exposure. A signal is a research row, NOT an approved trade.
    """
    if events_path is None:
        for s in result['confirmed_signals']:
            s['macro_risk_status']='UNKNOWN_PARTIAL_CALENDAR'
            s['macro_execution_clearance']=False
        result['macro_overlay']={'status':'NOT_RUN','reason':'NO_PIT_MACRO_EVENT_ARCHIVE',
                                 'execution_permission':'BLOCKED'}
        return result
    from M06H_RESEARCH_ENGINE import load_events,macro_guard_decision
    config_path=config_path or ROOT/'M06H_RESEARCH_CONFIG.example.json'
    cfg=json.loads(Path(config_path).read_text(encoding='utf-8'))
    check(cfg.get('frozen') is True,'MACRO_POLICY_NOT_FROZEN')
    evs,archive_mode=load_events(events_path)
    nblocked=0
    for s in result['confirmed_signals']:
        verdict=macro_guard_decision(s,evs,cfg['guard_windows_minutes'])
        if verdict['blocked']:
            s['macro_risk_status']='BLOCKED_BY_KNOWN_EVENT';nblocked+=1
        else:s['macro_risk_status']='NO_MATCHING_KNOWN_EVENT_PARTIAL_COVERAGE'
        s['macro_event_id']=verdict['event_id']
        s['macro_reason']=verdict['reason']
        s['macro_execution_clearance']=False
    result['macro_overlay']={'status':'RESEARCH_ANNOTATED','archive_mode':archive_mode,
        'events_loaded':len(evs),'blocked_confirmations':nblocked,
        'nonblocked_confirmations':len(result['confirmed_signals'])-nblocked,
        'coverage_certified':False,'execution_permission':'BLOCKED'}
    return result

def atomic_json(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    temp.replace(path)

def export_result(result,directory):
    d=Path(directory);d.mkdir(parents=True,exist_ok=True)
    atomic_json(d/'M06R_REPLAY_REPORT.json',result)
    with (d/'M06R_STAGE_LEDGER.jsonl').open('w',encoding='utf-8') as f:
        for row in result['stage_transitions']:
            f.write(json.dumps(row,ensure_ascii=False,allow_nan=False,sort_keys=True)+'\n')
    with (d/'M06R_CONFIRMED_SIGNALS.jsonl').open('w',encoding='utf-8') as f:
        for row in result['confirmed_signals']:
            f.write(json.dumps(row,ensure_ascii=False,allow_nan=False,sort_keys=True)+'\n')
    txt=f'''# MasterQUO M06R — raport historycznego replay\n\n- Wariant: {result['mode']}; instrument: {result['symbol']}\n- Przetworzone kroki: {result['steps_analyzed']} / {result['steps_attempted']}\n- Hipotezy EARLY: {result['research_setups_seen']}\n- Sygnały analitycznie CONFIRMED: {result['signal_count']}\n- Wynik netto: **NOT_RUN** — brak autentycznych ticków i kosztów rachunku\n- Pochodzenie danych CSV: niecertyfikowane, żadnych zleceń\n\nNie interpretuj danych syntetycznych jako historii XAUUSD. Brak sygnałów nie oznacza braku możliwości strategii.\n'''
    (d/'M06R_REPORT_PL.md').write_text(txt,encoding='utf-8')

def cli(argv=None):
    p=argparse.ArgumentParser(description='M06R: no-lookahead XAUUSD MT5 six-timeframe CSV replay (no orders).')
    p.add_argument('--bars-dir',required=True,help='Folder D1.csv H4.csv H1.csv M15.csv M5.csv M1.csv')
    p.add_argument('--symbol',default='XAUUSD');p.add_argument('--mode',choices=MODE,default='AUTO')
    p.add_argument('--step-tf',choices=['M5','M15'],default='M5')
    p.add_argument('--min-closed',type=int,default=230);p.add_argument('--history-cap',type=int,default=300)
    p.add_argument('--max-steps',type=int,default=2000)
    p.add_argument('--replay-from-utc',help='Start decision replay after warm-up, inclusive UTC')
    p.add_argument('--replay-to-utc',help='Stop decision replay, exclusive UTC')
    p.add_argument('--macro-events',help='Optional M06H M04N archived .jsonl or curated events .json')
    p.add_argument('--macro-config',default=str(ROOT/'M06H_RESEARCH_CONFIG.example.json'))
    p.add_argument('--output-dir',default='runtime_m06r');a=p.parse_args(argv)
    try:
        bank=load_bundle(a.bars_dir,a.symbol)
        report=run_replay(bank,mode=a.mode,symbol=a.symbol,step_tf=a.step_tf,
            min_closed=a.min_closed,history_cap=a.history_cap,max_steps=a.max_steps,
            from_utc=a.replay_from_utc,to_utc=a.replay_to_utc)
        apply_macro_archive(report,a.macro_events,a.macro_config)
        export_result(report,a.output_dir)
        print(json.dumps({'status':report['status'],'attempted':report['steps_attempted'],
                 'analyzed':report['steps_analyzed'],'setups':report['research_setups_seen'],
                 'confirmed':report['signal_count'],'profit':'NOT_RUN',
                 'execution_permission':'BLOCKED'},ensure_ascii=False))
        return 0 if report['steps_attempted'] else 3
    except (ReplayError,ValueError,OSError,KeyError) as e:
        print(json.dumps({'status':'FAIL','error':str(e),'execution_permission':'BLOCKED'},ensure_ascii=False),file=sys.stderr)
        return 2

if __name__=='__main__':raise SystemExit(cli())
