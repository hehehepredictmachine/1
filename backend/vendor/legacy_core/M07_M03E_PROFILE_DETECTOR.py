"""M07/M03E operational strategy research candidates from unchanged M01/M02/M03.

No MT5 connection, broker order, web, OCR, screenshot, or trade execution here.
Every price rule is derived from *already available* closed MT5 bars and M03
confirmed potential levels/FVG/breaks/sweeps. No ML probability or claimed edge.

The output is deliberately shaped for the existing M03E -> M10A contract.
It is NOT an M08-approved strategy and does not authorize execution.
"""
from __future__ import annotations
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GOOD = {'PASS', 'PASS_WITH_LIMITATIONS'}
TF = {'M1': 1, 'M5': 5, 'M15': 15, 'H1': 60, 'H4': 240, 'D1': 1440}
KEYS = ('qualification', 'arming', 'trigger', 'confirmation')


def hashed(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def utc(s):
    if not isinstance(s, str):
        raise ValueError('TIME_MISSING')
    x = datetime.fromisoformat(s.replace('Z', '+00:00'))
    if x.tzinfo is None:
        raise ValueError('TIMEZONE_REQUIRED')
    return x.astimezone(timezone.utc)


def is_positive(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x > 0


def read_config(path=None):
    cfg = json.loads(Path(path or ROOT/'OPERATIONAL_PROFILES_v1.json').read_text(encoding='utf-8'))
    if cfg.get('research_only') is not True or cfg.get('execution_enabled') is not False:
        raise ValueError('UNSAFE_PROFILE_CONFIG')
    profiles = cfg.get('profiles') or {}
    if set(profiles) != {'MVP', 'SMC', 'SCALPING'} or cfg.get('AUTO_priority') != ['SMC','MVP','SCALPING']:
        raise ValueError('UNEXPECTED_PROFILE_LIST')
    for name, p in profiles.items():
        if p['setup_tf'] not in TF or p.get('strategy_id') not in {'XAU-S01','XAU-S14','XAU-S06'}:
            raise ValueError('STRATEGY_OR_TF_INVALID')
        if not isinstance(p.get('max_fvg_age_bars'), int) or p['max_fvg_age_bars'] < 1:
            raise ValueError('AGE_INVALID')
        a = p.get('entry_stage_atr')
        if not isinstance(a,list) or len(a)!=4 or not all(is_positive(z) for z in a) or not all(x < y for x,y in zip(a,a[1:])):
            raise ValueError('STAGE_PARAMETERS_INVALID')
        for key in ('max_mitigation_fraction','max_distance_atr','min_atr','invalidation_buffer_atr'):
            v=p.get(key)
            if key=='max_mitigation_fraction':
                if not isinstance(v,(int,float)) or isinstance(v,bool) or not 0<=v<1:
                    raise ValueError('MITIGATION_INVALID')
            elif not is_positive(v):
                raise ValueError('PARAMETER_INVALID:'+key)
        if name=='SMC' and (not p.get('requires_sweep') or p.get('requires_displacement_break')):
            raise ValueError('SMC_SPEC_INVALID')
        if name=='SCALPING' and not p.get('requires_displacement_break'):
            raise ValueError('SCALPING_SPEC_INVALID')
    return cfg


def _candidate_mode_names(cfg, mode):
    if mode=='AUTO': return list(cfg['AUTO_priority'])
    if mode in cfg['profiles']: return [mode]
    raise ValueError('INVALID_MODE')


def atr14(bars):
    """Wilder ATR using only closed bars up to as_of (not future from M03 output)."""
    if len(bars)<15: return None
    trs=[]
    for a,b in zip(bars,bars[1:]):
        if not all(is_positive(b.get(k)) for k in ('open','high','low','close')) or not is_positive(a.get('close')):
            return None
        tr=max(b['high']-b['low'],abs(b['high']-a['close']),abs(b['low']-a['close']))
        trs.append(tr)
    val=sum(trs[:14])/14
    for tr in trs[14:]:val=(13*val+tr)/14
    return val if is_positive(val) else None


def _bars(snapshot, tf):
    if not isinstance(snapshot,dict):return None
    raw=(snapshot.get('candles_by_tf') or {}).get(tf)
    if not isinstance(raw,list) or len(raw)<30:return None
    asof=utc(snapshot['as_of']); sym=snapshot.get('exact_symbol')
    seen=set(); out=[]
    # Only proven closed broker BID bars; any malformed candle refuses discovery.
    for b in raw:
        if not isinstance(b,dict):return None
        if b.get('bar_state')=='FORMING':continue
        if (b.get('bar_state')!='CLOSED' or b.get('instrument_id')!='XAUUSD' or
            b.get('timeframe')!=tf or b.get('exact_symbol')!=sym or b.get('price_basis')!='BID' or
            not str(b.get('source_id','')).startswith('MT5') or not b.get('evidence_id')):
            return None
        try:
            op=utc(b['bar_open_utc']);cl=utc(b['close_confirmed_at']);av=utc(b['available_at'])
            if av>asof or cl>av or op>=cl or op in seen: return None
            seen.add(op)
        except (ValueError,TypeError,KeyError):return None
        if not all(is_positive(b.get(k)) for k in ('open','high','low','close')):return None
        if not b['low']<=min(b['open'],b['close'])<=max(b['open'],b['close'])<=b['high']:return None
        out.append(b)
    if any(utc(a['bar_open_utc'])>=utc(b['bar_open_utc']) for a,b in zip(out,out[1:])):return None
    return out if len(out)>=30 else None


def _stage_rule(tf, field, operator, level, event_id):
    return {'timeframe':tf,'field':field,'operator':operator,'level':round(level,6),
            'requires_closed_bar':True,'reference_evidence_id':event_id}


def _available(e, asof, name):
    try:return utc(e[name])<=asof
    except (ValueError,TypeError,KeyError):return False


def _index_at_or_before(bars, t):
    try:dt=utc(t)
    except (TypeError,ValueError):return -1
    return next((i for i in range(len(bars)-1,-1,-1)
                 if utc(bars[i]['available_at'])<=dt), -1)


def _age_closed_bars(bars, t):
    i=_index_at_or_before(bars,t)
    return (len(bars)-1-i) if i>=0 else None


def discover(snapshot, market, m03, *, mode='AUTO', config=None):
    """Return 1 research plan max, with non-selected candidates and reason codes.

    Missing verified source -> no strategy. Never invent levels or M03 ids.
    """
    cfg=copy.deepcopy(config) if config is not None else read_config()
    names=_candidate_mode_names(cfg,mode)
    summary={'module_id':'M07_M03E_OPERATIONAL_PROFILES','module_version':'1.0.0-CANDIDATE',
             'mode':mode,'research_only':True,'candidate_status':'NONE',
             'selected_plan':None,'proposals':[],'reason_codes':[],
             'execution_permission':'BLOCKED','live_execution_allowed':False,
             'account_profile':'MT5_ZERO_DECLARED_COSTS_UNVERIFIED',
             'limitations':['PROVISIONAL_RULES','NO_OOS_FORWARD','NO_M08_APPROVAL','NO_M11_EXECUTION_PLAN']}
    if not isinstance(snapshot,dict) or not isinstance(market,dict) or not isinstance(m03,dict):
        summary['reason_codes'].append('MARKET_PACKETS_MISSING');return summary
    if ((snapshot.get('analysis_gate') or {}).get('status') not in GOOD or
        market.get('analysis_gate',{}).get('status') not in GOOD or market.get('status') not in GOOD or
        m03.get('status') not in GOOD or not snapshot.get('snapshot_id') or
        snapshot.get('snapshot_id')!=market.get('snapshot_id') or
        market.get('snapshot_id')!=m03.get('snapshot_id') or
        snapshot.get('data_source_policy')!='MT5_PRIMARY_TV_SUPPLEMENTAL_NO_SCREENSHOTS' or
        snapshot.get('visual_capture_enabled') is not False or
        utc(snapshot['as_of'])!=utc(market.get('as_of')) or
        utc(snapshot['as_of'])!=utc(m03.get('as_of'))):
        summary['reason_codes'].append('M01_M02_M03_GATE_OR_SNAPSHOT_INVALID');return summary
    direction=market.get('structural_direction')
    if direction not in ('BULLISH','BEARISH'):
        summary['reason_codes'].append('STRUCTURAL_DIRECTION_UNRESOLVED');return summary
    dside='LONG' if direction=='BULLISH' else 'SHORT'
    known_market=set(market.get('evidence_ids') or [])
    known_m03=set(m03.get('evidence_ids') or [])
    evidence_times=m03.get('timeframes') or {}
    asof=utc(snapshot['as_of'])
    for name in names:
        p=cfg['profiles'][name];tf=p['setup_tf']
        tfe=evidence_times.get(tf) or {}
        bars=_bars(snapshot,tf)
        if tfe.get('status') not in GOOD or bars is None:
            summary['reason_codes'].append(name+':TF_DATA_NOT_VALID');continue
        vol=atr14(bars)
        if vol is None or vol < p['min_atr']:
            summary['reason_codes'].append(name+':ATR_NOT_AVAILABLE');continue
        close=bars[-1]['close']
        last_ev=bars[-1]['evidence_id']
        candidates=[]
        fs=list(tfe.get('fvgs') or [])
        for f in reversed(fs):
            if (not isinstance(f,dict) or f.get('direction')!=direction or f.get('event_id') not in known_m03 or
                not is_positive(f.get('zone_low')) or not is_positive(f.get('zone_high')) or
                f['zone_low']>=f['zone_high'] or
                not isinstance(f.get('mitigated_fraction'),(int,float)) or
                isinstance(f['mitigated_fraction'],bool) or
                not 0<=f['mitigated_fraction']<=p['max_mitigation_fraction'] or
                not _available(f,asof,'formed_at')):
                continue
            age=_age_closed_bars(bars,f['formed_at'])
            if age is None or age>p['max_fvg_age_bars'] or age<0:continue
            # Can be inside the POI; must not be too far from the midpoint.
            center=(f['zone_low']+f['zone_high'])/2
            if abs(close-center)>p['max_distance_atr']*vol:continue
            # A close beyond the far side of the candidate POI cannot create a
            # freshly reset stop/trigger from the same invalidated location.
            if dside=='LONG' and close < f['zone_low']:continue
            if dside=='SHORT' and close > f['zone_high']:continue
            # The FVG must be to the beneficial side of the proposed setup.
            if dside=='LONG' and close<f['zone_low']-p['max_distance_atr']*vol:continue
            if dside=='SHORT' and close>f['zone_high']+p['max_distance_atr']*vol:continue
            sweep=None;breaker=None
            if p.get('requires_sweep'):
                for s in reversed(tfe.get('sweeps') or []):
                    if (s.get('event_id') in known_m03 and s.get('directional_reaction')==direction
                        and s.get('event_id')!=f['event_id'] and
                        _available(s,asof,'observed_at') and utc(s['observed_at'])<=utc(f['formed_at'])
                        and (_age_closed_bars(bars,s['observed_at']) or 100000)<=p['max_sweep_age_bars']):
                        sweep=s;break
                if not sweep:continue
            if p.get('requires_displacement_break'):
                for b in reversed(tfe.get('breaks') or []):
                    if (b.get('event_id') in known_m03 and b.get('direction')==direction
                        and b.get('displacement_confirmed') is True and
                        b.get('kind') in ('BOS','MSS') and
                        _available(b,asof,'observed_at') and utc(b['observed_at'])<=utc(f['formed_at'])
                        and (_age_closed_bars(bars,b['observed_at']) or 100000)<=p['max_break_age_bars']):
                        breaker=b;break
                if not breaker:continue
            # For any family choose a real M03 level representing directional liquidity.
            desired='SSL' if dside=='LONG' else 'BSL'
            levels=[x for x in tfe.get('liquidity_levels') or []
                    if (x.get('event_id') in known_m03 and x.get('liquidity_side')==desired
                        and is_positive(x.get('reference_level')) and _available(x,asof,'available_at')
                        and x.get('event_id')!=f['event_id'])]
            # Sweep can be a liquidity evidence for SMC even with no durable pivot level.
            liquidity=sweep if sweep else (min(levels,key=lambda x:abs(x['reference_level']-close)) if levels else None)
            if not liquidity:continue
            # A price-only trend bar reference is not enough: require M02 known evidence,
            # chosen from higher-timeframe market structure evidence.
            htfs=('H1','H4') if tf in ('M1','M5','M15') else (tf,)
            structures=[k for htf in htfs for k in ((market.get('timeframes') or {}).get(htf,{}).get('evidence_ids') or []) if k in known_market]
            if not structures:continue
            structural_id=structures[-1]
            # Distinct, evidence-backed dynamic levels, fixed once created by M10.
            ref=max(close,f['zone_high']) if dside=='LONG' else min(close,f['zone_low'])
            signed=1 if dside=='LONG' else -1
            entrylevels=[round(ref + signed*a*vol,6) for a in p['entry_stage_atr']]
            if len(set(entrylevels))!=4:continue
            invlevel=round(min(f['zone_low'],close)-p['invalidation_buffer_atr']*vol,6) if dside=='LONG' \
                    else round(max(f['zone_high'],close)+p['invalidation_buffer_atr']*vol,6)
            if invlevel<=0 or (dside=='LONG' and invlevel>=close) or (dside=='SHORT' and invlevel<=close):continue
            positive='>' if signed>0 else '<'; reverse='<' if signed>0 else '>'
            rules={k:_stage_rule(tf,'close' if k in ('qualification','confirmation') else 'high' if signed>0 else 'low',
                                 positive,entrylevels[i],f['event_id']) for i,k in enumerate(KEYS)}
            inv=_stage_rule(tf,'close',reverse,invlevel,f['event_id'])
            template={**p,'algorithm':'OP_DETECTOR_1.0.0','mode':name}
            template_hash=hashed(template)
            setup_id=f['event_id']
            plan={'strategy_id':p['strategy_id'],'version':'1.0.0-RESEARCH',
                  'spec_hash':template_hash, 'research_profile_hash':template_hash,
                  'horizon_id':tf,'setup_tf':tf,'created_event_id':setup_id,
                  'intended_direction':dside,'structural_evidence_id':structural_id,
                  'location_evidence_id':f['event_id'],'liquidity_evidence_id':liquidity['event_id'],
                  'next_expected_event':{'timeframe':tf,'condition':rules['qualification'],
                      'failure_condition':'CLOSED_'+tf+'_PRICE_INVALIDATES_AT_'+str(invlevel)},
                  'invalidation':{'timeframe':tf,'condition':inv,'rule':'CLOSED_BAR'},
                  'lifecycle_rules':rules,'research_only':True,'example_only':False,
                  'profile_name':name,'profile_origin':'AUTO_BIND_FROM_M01_M02_M03',
                  'frozen_plan_hash':None,'m08_registry_approved':False,
                  'execution_enabled':False,'risk_profile':None,
                  'created_at':f['formed_at'],
                  'source_fvg_geometry':{'zone_low':f['zone_low'],'zone_high':f['zone_high'],
                    'formed_at':f['formed_at']},
                  'limitations':['M07_RESEARCH_TEMPLATE_NOT_M08_FROZEN_PRODUCTION_SPEC',
                                 'LEVELS_PROVISIONAL_NOT_OPTIMIZED','NO_ORDER_EXECUTOR']}
            plan['frozen_plan_hash']=hashed({k:v for k,v in plan.items() if k!='frozen_plan_hash'})
            # Pre-verify the original M03 5-CORE rule without inventing evidence.
            from_sys=False
            try:
                from vendor.M03.M03_REFERENCE_ENGINE import early_assessment
                from M03E_M10_PIPELINE import construct_early
                assessed=early_assessment(m03,market,plan)
                if assessed.get('status')!='EARLY_SETUP':continue
                early,why=construct_early({**m03, "early_evidence": assessed},market,snapshot,plan)
                if early is None:continue
            except (ValueError,TypeError,KeyError,ImportError):continue
            candidates.append({'mode':name,'plan':plan,'source_fvg_id':f['event_id'],
                               'source_liquidity_id':liquidity['event_id'],
                               'break_id':breaker['event_id'] if breaker else None,
                               'fvg_age_bars':age,'distance_atr':round(abs(close-center)/vol,5),
                               'evidence_ids':[structural_id,f['event_id'],liquidity['event_id']],
                               'candidate_id':early['setup_id']})
        if not candidates:
            summary['reason_codes'].append(name+':NO_VERIFIED_EXECUTABLE_FVG_SETUP');continue
        candidates.sort(key=lambda x:(x['fvg_age_bars'],x['distance_atr'],x['candidate_id']))
        summary['proposals'].append(candidates[0])
    if summary['proposals']:
        # Profile selection order is explicit configuration, not a learned rank or win probability.
        chosen=summary['proposals'][0]
        summary['selected_plan']=chosen['plan']
        summary['candidate_status']='RESEARCH_HYPOTHESIS'
        summary['selection_reason']='FROZEN_MODE_PRIORITY_THEN_NEWEST_VALID_FVG'
        summary['reason_codes']=sorted(set(summary['reason_codes']))
    else:
        summary['reason_codes']=sorted(set(summary['reason_codes'] or ['NO_MATCHING_MARKET_EVIDENCE']))
    return summary
