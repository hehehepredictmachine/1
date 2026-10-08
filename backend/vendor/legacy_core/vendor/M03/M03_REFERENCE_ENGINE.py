"""MasterQUO M03 deterministic, read-only reference analyzer.
Input: validated M01 data_snapshot + M02 market_state in JSON envelope.
Outputs descriptive MARKET_EVIDENCE; no trading signals, orders, screenshots or network.
Research reference ONLY. Rules are provisional and must be validated by M06.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = '1.0.0-CANDIDATE'
SOURCE_POLICY = 'MT5_PRIMARY_TV_SUPPLEMENTAL_NO_SCREENSHOTS'
GOOD = {'PASS', 'PASS_WITH_LIMITATIONS'}
TIMEFRAMES = {'M1', 'M5', 'M15', 'H1', 'H4', 'D1'}


def utc(value: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError('TIME_UNKNOWN')
    x = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if x.tzinfo is None:
        raise ValueError('TIMEZONE_MISSING')
    return x.astimezone(timezone.utc)


def num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def valid_ohlc(c: dict) -> bool:
    vals = [c.get(z) for z in ('open', 'high', 'low', 'close')]
    return all(num(z) and z > 0 for z in vals) and c['low'] <= min(c['open'], c['close']) <= max(c['open'], c['close']) <= c['high']


def selected_bars(snapshot: dict, tf: str) -> tuple[list[dict], list[str]]:
    """Fail-closed on bad same-scope data, but exclude FORMING and future bars."""
    now = utc(snapshot['as_of'])
    issues = []
    buckets: dict[str, dict] = {}
    disputed = set()
    for raw in snapshot.get('candles_by_tf', {}).get(tf, []):
        if not isinstance(raw, dict):
            issues.append('INVALID_BAR_OBJECT'); continue
        if raw.get('bar_state') == 'FORMING':
            continue
        if raw.get('bar_state') != 'CLOSED':
            issues.append('BAR_NOT_CONFIRMED'); continue
        if raw.get('instrument_id') != 'XAUUSD' or raw.get('timeframe') != tf:
            issues.append('INSTRUMENT_OR_TF_MISMATCH'); continue
        if not str(raw.get('source_id', '')).upper().startswith('MT5'):
            issues.append('NON_MT5_BROKER_BAR'); continue
        if raw.get('price_basis') not in ('BID', 'ASK', 'LAST') or not raw.get('evidence_id'):
            issues.append('INVALID_PROVENANCE'); continue
        try:
            opened, conf, avail = (utc(raw[z]) for z in ('bar_open_utc', 'close_confirmed_at', 'available_at'))
        except (TypeError, ValueError, KeyError):
            issues.append('INVALID_TIME'); continue
        if conf < opened or avail < conf:
            issues.append('INVALID_TIME'); continue
        if conf > now or avail > now:
            issues.append('FUTURE_BAR_EXCLUDED'); continue
        if not valid_ohlc(raw):
            issues.append('INVALID_OHLC'); continue
        try:
            revision = int(raw.get('revision', 0))
        except (TypeError, ValueError):
            issues.append('INVALID_REVISION'); continue
        if revision < 0:
            issues.append('INVALID_REVISION'); continue
        key = opened.isoformat()
        if key in disputed:
            continue
        previous = buckets.get(key)
        if previous is not None:
            prev_revision = int(previous.get('revision', 0))
            if revision == prev_revision:
                identity = ('open', 'high', 'low', 'close', 'price_basis', 'tick_volume')
                if any(raw.get(a) != previous.get(a) for a in identity):
                    issues.append('CONFLICTING_REVISION'); disputed.add(key)
                    buckets.pop(key, None)
                continue
            if revision < prev_revision:
                continue
            issues.append('HIGHER_REVISION_OBSERVED')
        buckets[key] = raw
    bars = sorted(buckets.values(), key=lambda c: utc(c['bar_open_utc']))
    if len({x['price_basis'] for x in bars}) > 1:
        issues.append('MIXED_PRICE_BASIS')
    if len({x['source_id'] for x in bars}) > 1:
        issues.append('MIXED_BROKER_SOURCES')
    # Intraday gaps not guessed: M01 owns session calendar and gap integrity.
    if any(i in issues for i in ('CONFLICTING_REVISION','MIXED_PRICE_BASIS','MIXED_BROKER_SOURCES','INSTRUMENT_OR_TF_MISMATCH','INVALID_OHLC','INVALID_TIME','INVALID_REVISION','INVALID_PROVENANCE','NON_MT5_BROKER_BAR')):
        return [], sorted(set(issues))
    return bars, sorted(set(issues))


def metric(c: dict) -> dict:
    r = c['high'] - c['low']
    body = abs(c['close'] - c['open'])
    return {'body': body, 'range': r,
            'body_ratio': body/r if r > 0 else None,
            'upper_wick': c['high'] - max(c['open'], c['close']),
            'lower_wick': min(c['open'], c['close']) - c['low'],
            'close_location': (c['close']-c['low'])/r if r > 0 else None}


def available_pivots(m02_tf: dict, bars: list[dict], side: str, at: dict, tolerance: float) -> list[dict]:
    """Only M02 pivots confirmed before the observed bar; verify pivot against M01 history."""
    by_time = {utc(x['bar_open_utc']): x for x in bars}
    out = []
    event_open = utc(at['bar_open_utc'])
    event_avail = utc(at['available_at'])
    field = 'high' if side == 'highs' else 'low'
    for p in m02_tf.get('swings', {}).get(side, []):
        try:
            pivot = utc(p['pivot_time']); available = utc(p['available_at'])
            bar = by_time.get(pivot)
            if (bar is None or not num(p['price']) or not num(bar[field]) or
                abs(float(p['price']) - float(bar[field])) > tolerance or
                available < utc(bar['close_confirmed_at']) or available >= event_avail or
                pivot >= event_open):
                continue
        except (ValueError, KeyError, TypeError):
            continue
        out.append(p)
    return sorted(out, key=lambda p: utc(p['pivot_time']))


def eid(kind: str, tf: str, bar: dict, tag: str = '') -> str:
    return ':'.join(filter(None, ('M03', kind, tf, bar['bar_open_utc'], tag)))


def atr_at(bars: list[dict], index: int, period: int) -> float | None:
    # Wilder ATR as-of the event. Never use the FINAL-snapshot ATR for an earlier bar.
    if not isinstance(period,int) or period<1 or index < period:
        return None
    tr=[]
    for i in range(1,index+1):
        b,p=bars[i],bars[i-1]
        tr.append(max(b['high']-b['low'],abs(b['high']-p['close']),abs(b['low']-p['close'])))
    value=sum(tr[:period])/period
    for x in tr[period:]:value=((period-1)*value+x)/period
    return value if value>0 else None


def find_breaks(bars: list[dict], m02_tf: dict, cfg: dict, tf: str) -> list[dict]:
    events = []
    seen = set()
    eps = float(cfg['break_buffer_abs'])
    # detect only break of a confirmed reference pivot available to that bar
    for i in range(1, len(bars)):
        b, prev = bars[i], bars[i-1]
        cmetrics = metric(b)
        for side, direction in (('highs', 'BULLISH'), ('lows', 'BEARISH')):
            pivs = available_pivots(m02_tf, bars, side, b, eps)
            if not pivs: continue
            last = pivs[-1]
            level = float(last['price'])
            crossed = ((prev['close'] <= level + eps and b['close'] > level + eps) if direction == 'BULLISH' else
                       (prev['close'] >= level - eps and b['close'] < level - eps))
            key = (direction, last['pivot_time'])
            if not crossed or key in seen: continue
            seen.add(key)
            atr = atr_at(bars,i,int(cfg['atr_period']))
            disp = (num(atr) and atr > 0 and cmetrics['body_ratio'] is not None and
                    cmetrics['body_ratio'] >= cfg['displacement_body_ratio_min'] and
                    cmetrics['range']/atr >= cfg['displacement_range_atr_min'])
            # PRIOR regime only. The CURRENT M02 regime may already incorporate this
            # breaking candle (or many later candles) and must not label past breaks.
            trend = 'UNKNOWN'
            prior = m02_tf.get('prior_structure_regime_by_bar',{}).get(b['bar_open_utc'])
            if isinstance(prior, dict):
                try:
                    if (prior.get('regime') in ('TREND_UP','TREND_DOWN') and
                        prior.get('evidence_id') and utc(prior['available_at']) < utc(b['available_at'])):
                        trend=prior['regime']
                except (ValueError, KeyError, TypeError):
                    pass
            if trend == 'UNKNOWN':
                h=available_pivots(m02_tf,bars,'highs',b,eps)
                l=available_pivots(m02_tf,bars,'lows',b,eps)
                if len(h)>=2 and len(l)>=2:
                    if h[-1]['price']>h[-2]['price']+eps and l[-1]['price']>l[-2]['price']+eps:
                        trend='TREND_UP'
                    elif h[-1]['price']<h[-2]['price']-eps and l[-1]['price']<l[-2]['price']-eps:
                        trend='TREND_DOWN'
            if trend in ('TREND_UP','TREND_DOWN'):
                opposing = (trend == 'TREND_UP' and direction == 'BEARISH') or (trend == 'TREND_DOWN' and direction == 'BULLISH')
                kind = ('MSS' if disp else 'CHOCH') if opposing else 'BOS'
            else:
                kind = 'STRUCTURE_BREAK_UNCLASSIFIED'
            events.append({'event_id': eid(kind, tf, b, str(last['pivot_time'])), 'kind': kind,
                           'direction':direction,'break_level':level,'reference_pivot_time':last['pivot_time'],
                           'reference_available_at':last['available_at'],
                           'observed_at':b['available_at'], 'bar_open_utc':b['bar_open_utc'],
                           'displacement_confirmed':bool(disp), 'displacement_assessable':bool(num(atr) and atr > 0),
                           'pre_break_regime':trend, 'atr_asof_event':atr,
                           'evidence_ids':[b['evidence_id']], 'underlying_event_id':eid('PRICE_EVENT',tf,b)})
    return events


def find_sweeps(bars: list[dict], m02_tf: dict, cfg: dict, tf: str) -> list[dict]:
    out=[]; eps=float(cfg['sweep_min_penetration_abs'])
    for i in range(1,len(bars)):
        b, prev=bars[i],bars[i-1]
        for side, d, kind in (('highs','BEARISH','BSL'),('lows','BULLISH','SSL')):
            pivs=available_pivots(m02_tf,bars,side,b,eps)
            if not pivs: continue
            pivot=pivs[-1]; level=float(pivot['price'])
            valid = ((prev['close'] <= level and b['high'] > level+eps and b['close'] <= level) if kind=='BSL' else
                     (prev['close'] >= level and b['low'] < level-eps and b['close'] >= level))
            if valid:
                out.append({'event_id':eid('SWEEP',tf,b,kind+':'+pivot['pivot_time']),
                            'kind':'POTENTIAL_LIQUIDITY_SWEEP','liquidity_side':kind,'directional_reaction':d,
                            'reference_level':level,'reference_pivot_time':pivot['pivot_time'],
                            'observed_at':b['available_at'], 'evidence_ids':[b['evidence_id']],
                            'underlying_event_id':eid('PRICE_EVENT',tf,b),
                            'limitations':['LIQUIDITY_NOT_OBSERVED_DIRECTLY','NOT_AN_ENTRY_TRIGGER']})
    return out


def find_fvgs(bars: list[dict], cfg: dict, tf: str) -> list[dict]:
    gaps=[]; min_gap=float(cfg['fvg_min_size_abs'])
    for i in range(2,len(bars)):
        a,b,c=bars[i-2:i+1]
        direction=None; lo=hi=0.0
        if c['low'] > a['high'] + min_gap:
            direction='BULLISH'; lo=float(a['high']); hi=float(c['low'])
        elif c['high'] < a['low'] - min_gap:
            direction='BEARISH'; lo=float(c['high']); hi=float(a['low'])
        else: continue
        later=bars[i+1:]
        if direction=='BULLISH':
            deepest=min((z['low'] for z in later),default=hi)
            mitigation=min(1.0,max(0.0,(hi-deepest)/(hi-lo)))
        else:
            highest=max((z['high'] for z in later),default=lo)
            mitigation=min(1.0,max(0.0,(highest-lo)/(hi-lo)))
        gaps.append({'event_id':eid('FVG',tf,c,direction), 'direction':direction,
                     'zone_low':lo,'zone_high':hi,'formed_at':c['available_at'],
                     'mitigated_fraction':mitigation,'age_closed_bars':len(later),
                     'status':'FILLED' if mitigation>=1.0 else 'PARTIAL' if mitigation>0 else 'UNTOUCHED',
                     'evidence_ids':[a['evidence_id'],b['evidence_id'],c['evidence_id']],
                     'limitations':['GEOMETRIC_FVG_NOT_ORDER_FLOW_PROOF']})
    return gaps


def find_order_blocks(bars: list[dict], breaks: list[dict], cfg: dict, tf: str) -> list[dict]:
    out=[]
    baridx={x['bar_open_utc']:i for i,x in enumerate(bars)}
    for e in breaks:
        if not e['displacement_confirmed'] or e['kind']=='STRUCTURE_BREAK_UNCLASSIFIED': continue
        i=baridx.get(e['bar_open_utc'])
        if i is None: continue
        direction=e['direction']
        search=range(i-1,max(-1,i-1-int(cfg['ob_lookback_bars'])),-1)
        chosen=None
        for j in search:
            z=bars[j]
            if ((direction=='BULLISH' and z['close'] < z['open']) or
                (direction=='BEARISH' and z['close'] > z['open'])):
                chosen=z;break
        if chosen is None: continue
        lo = float(chosen['low'] if direction=='BULLISH' else chosen['open'])
        hi = float(chosen['open'] if direction=='BULLISH' else chosen['high'])
        if lo>=hi:continue
        out.append({'event_id':eid('OB_CANDIDATE',tf,chosen,direction),
                    'kind':'CANDIDATE_ORDER_BLOCK','direction':direction,
                    'zone_low':lo,'zone_high':hi,'origin_bar':chosen['bar_open_utc'],
                    'confirmed_at':e['observed_at'],'supporting_break_id':e['event_id'],
                    'rating':'UNRATED','evidence_ids':[chosen['evidence_id']]+e['evidence_ids'],
                    'limitations':['HEURISTIC_ZONE_NOT_INSTITUTIONAL_ORDER_PROOF']})
    return out


def liquidity_levels(bars: list[dict], m02_tf: dict, tf: str, cfg: dict) -> list[dict]:
    if not bars:return []
    eps=float(cfg['break_buffer_abs'])
    result=[]
    for side, label in (('highs','BSL'),('lows','SSL')):
        for pivot in available_pivots(m02_tf,bars,side,bars[-1],eps):
            result.append({'event_id':'M03:LEVEL:'+tf+':'+label+':'+pivot['pivot_time'],
                           'liquidity_side':label,'reference_level':pivot['price'],
                           'pivot_time':pivot['pivot_time'],'available_at':pivot['available_at'],
                           'underlying_event_id':'M02:PIVOT:'+tf+':'+pivot['pivot_time'],
                           'limitations':['POTENTIAL_LIQUIDITY_NOT_OBSERVED_STOPS']})
    return result


def premium_discount(bars: list[dict], m02_tf: dict, tf: str, cfg: dict) -> dict:
    if not bars: return {'status':'UNAVAILABLE','reason':'NO_CLOSED_BARS'}
    top=available_pivots(m02_tf,bars,'highs',bars[-1],float(cfg['break_buffer_abs']))
    bot=available_pivots(m02_tf,bars,'lows',bars[-1],float(cfg['break_buffer_abs']))
    if not top or not bot: return {'status':'UNAVAILABLE','reason':'CONFIRMED_DEALING_RANGE_NOT_AVAILABLE'}
    hi,lo=float(top[-1]['price']),float(bot[-1]['price'])
    if lo>=hi: return {'status':'UNAVAILABLE','reason':'INVALID_DEALING_RANGE'}
    pos=(float(bars[-1]['close'])-lo)/(hi-lo)
    label='DISCOUNT' if pos<0.5 else 'PREMIUM' if pos>0.5 else 'EQUILIBRIUM'
    return {'status':'AVAILABLE','dealing_range_high':hi,'dealing_range_low':lo,
            'equilibrium':(hi+lo)/2,'relative_position':pos,'zone':label,
            'limitations':['PIVOT_DERIVED_RANGE_PROVISIONAL']}


def early_assessment(market_evidence: dict, m02: dict, plan: dict | None = None) -> dict:
    """No auto early without five verified CORE and strategy-owned next event/invalidation."""
    plan=plan or {}
    direction=plan.get('intended_direction')
    if direction not in ('LONG','SHORT'):
        return {'status':'CANDIDATE','intended_direction':'UNKNOWN', 'core_status':'INCOMPLETE',
                'missing_core':['STRATEGY_DEFINED_DIRECTION','MEANINGFUL_LOCATION','LIQUIDITY_CONTEXT',
                                'DEVELOPMENT_PATH','KNOWN_INVALIDATION'], 'signal_validity':'INSUFFICIENT_EVIDENCE'}
    structural=(m02.get('structural_direction') or 'UNKNOWN')
    align={'LONG':'BULLISH','SHORT':'BEARISH'}[direction]
    # A strategy explicitly allowing countertrend must separately establish structural advantage.
    countertrend_id=plan.get('countertrend_structure_evidence_id')
    countertrend_supported=False
    if isinstance(countertrend_id,str):
        for x in market_evidence.get('timeframes',{}).values():
            if any(e.get('event_id')==countertrend_id and e.get('kind') in ('CHOCH','MSS')
                   and e.get('direction')==align for e in x.get('breaks',[])):
                countertrend_supported=True
                break
    structure_ok=(structural==align or countertrend_supported)
    chosen=plan.get('location_evidence_id'); liq=plan.get('liquidity_evidence_id')
    # A break alone is not a location; confirmed liquidity reference isn't automatically a POI.
    location_ok=bool(chosen in market_evidence['evidence_ids'] and
                     (chosen.startswith('M03:FVG:') or chosen.startswith('M03:OB_CANDIDATE:')))
    liq_ok=bool(liq in market_evidence['evidence_ids'] and
                (liq.startswith('M03:SWEEP:') or liq.startswith('M03:LEVEL:')) and liq != chosen)
    next_event=plan.get('next_expected_event') or {}
    inval=plan.get('invalidation') or {}
    path_ok=bool(next_event.get('timeframe') and next_event.get('condition') and next_event.get('failure_condition'))
    inval_ok=bool(inval.get('timeframe') and inval.get('condition') and inval.get('rule'))
    checks={'STRUCTURAL_ADVANTAGE':structure_ok,'MEANINGFUL_LOCATION':location_ok,
            'LIQUIDITY_CONTEXT':liq_ok,'DEVELOPMENT_PATH':path_ok,'KNOWN_INVALIDATION':inval_ok}
    missing=[k for k,v in checks.items() if not v]
    return {'status':'EARLY_SETUP' if not missing else 'CANDIDATE', 'intended_direction':direction,
            'core_status':'COMPLETE' if not missing else 'INCOMPLETE', 'missing_core':missing,
            'core_checks':checks, 'signal_validity':'VALID_EARLY_SETUP' if not missing else 'INSUFFICIENT_EVIDENCE',
            'execution_permission':'BLOCKED', 'notes':'Early is analysis only; M09/M10/M14 own final decision.'}


def analyze(snapshot: dict, m02: dict, cfg: dict, strategy_plan: dict | None = None) -> dict:
    now=utc(snapshot['as_of'])
    if not snapshot.get('snapshot_id') or snapshot.get('snapshot_id') != m02.get('snapshot_id'):
        raise ValueError('SNAPSHOT_ID_MISMATCH')
    if utc(m02['as_of'])!=now or m02.get('instrument_id') != 'XAUUSD':
        raise ValueError('MARKET_STATE_MISMATCH')
    cfg_tfs=cfg.get('timeframes',[])
    if not cfg_tfs or len(cfg_tfs)!=len(set(cfg_tfs)) or not set(cfg_tfs)<=TIMEFRAMES:
        raise ValueError('INVALID_TIMEFRAME_CONFIG')
    if not snapshot.get('data_source_policy')==SOURCE_POLICY or snapshot.get('visual_capture_enabled') is not False:
        raise ValueError('SOURCE_POLICY_VIOLATION')
    if not cfg.get('research_only'):
        raise ValueError('RESEARCH_ONLY_PROFILE_REQUIRED')
    ag=m02.get('analysis_gate',{}).get('status')
    m02state=m02.get('status')
    m02exec=m02.get('execution_context_gate',{}).get('status')
    enabled=ag in GOOD and m02state in GOOD
    per={}; reasons=[]
    all_ev=[]
    for tf in cfg_tfs:
        tfstate=m02.get('timeframes',{}).get(tf,{})
        if not enabled or tfstate.get('status') not in GOOD:
            per[tf]={'status':'PENDING','reason_codes':['M02_TF_OR_ANALYSIS_UNVERIFIED'],
                     'breaks':[], 'sweeps':[], 'fvgs':[], 'order_blocks':[], 'evidence_ids':[]}
            continue
        bars,issues=selected_bars(snapshot,tf)
        if not bars or len(bars)<cfg['min_closed_bars']:
            per[tf]={'status':'FAIL' if any(x in issues for x in ('INVALID_OHLC','CONFLICTING_REVISION','MIXED_PRICE_BASIS','INSTRUMENT_OR_TF_MISMATCH','INVALID_PROVENANCE','MIXED_BROKER_SOURCES','INVALID_TIME')) else 'PENDING',
                     'reason_codes':issues+['INSUFFICIENT_VALID_CLOSED_BARS'],
                     'breaks':[], 'sweeps':[], 'fvgs':[], 'order_blocks':[], 'evidence_ids':[]}
            continue
        # Restrict calculation to same M02 evaluated window: never use newer candles than M02 last closed.
        try:
            m02end=utc(tfstate['last_closed_at'])
        except (KeyError,ValueError,TypeError):
            per[tf]={'status':'PENDING','reason_codes':['M02_LAST_CLOSED_UNKNOWN'],
                     'breaks':[], 'sweeps':[], 'fvgs':[], 'order_blocks':[], 'evidence_ids':[]};continue
        latest_known=max((utc(b['close_confirmed_at']) for b in bars),default=None)
        if latest_known is not None and latest_known > m02end:
            per[tf]={'status':'PENDING','reason_codes':['M01_M02_CLOSE_BOUNDARY_MISMATCH'],
                     'breaks':[], 'sweeps':[], 'fvgs':[], 'order_blocks':[], 'evidence_ids':[]};continue
        bars=[b for b in bars if utc(b['close_confirmed_at'])<=m02end]
        if len(bars)<cfg['min_closed_bars'] or utc(bars[-1]['close_confirmed_at'])!=m02end:
            per[tf]={'status':'PENDING','reason_codes':['M01_M02_CLOSE_BOUNDARY_MISMATCH'],
                     'breaks':[], 'sweeps':[], 'fvgs':[], 'order_blocks':[], 'evidence_ids':[]};continue
        breaks=find_breaks(bars,tfstate,cfg,tf)
        sweeps=find_sweeps(bars,tfstate,cfg,tf)
        gaps=find_fvgs(bars,cfg,tf)
        blocks=find_order_blocks(bars,breaks,cfg,tf)
        levels=liquidity_levels(bars,tfstate,tf,cfg)
        pd=premium_discount(bars,tfstate,tf,cfg)
        ev=[]
        for group in (breaks,sweeps,gaps,blocks,levels):
            for x in group:
                ev.append(x['event_id'])
        # simple descriptive PA, no independent votes
        pa=metric(bars[-1]); pa.update({'bar_evidence_id':bars[-1]['evidence_id'],
                                      'observed_at':bars[-1]['available_at']})
        latest={'status':'PASS_WITH_LIMITATIONS' if issues else 'PASS',
                'reason_codes':issues,'last_closed_at':m02end.isoformat(),
                'breaks':breaks,'sweeps':sweeps,'fvgs':gaps,'order_blocks':blocks,'liquidity_levels':levels,
                'premium_discount':pd,'price_action':pa,
                'evidence_ids':list(dict.fromkeys(ev))}
        per[tf]=latest
        all_ev.extend(latest['evidence_ids'])
    req=cfg.get('required_timeframes',[])
    if not set(req)<=set(cfg_tfs): raise ValueError('REQUIRED_TFS_NOT_IN_CONFIG')
    if m02state=='FAIL' or ag=='FAIL':
        status='FAIL';reasons.append('M02_ANALYSIS_FAILED')
    elif not enabled:
        status='PENDING';reasons.append('M02_ANALYSIS_UNVERIFIED')
    elif any(per[t]['status']=='FAIL' for t in req):
        status='FAIL';reasons.append('REQUIRED_TF_CORRUPTED')
    elif any(per[t]['status'] not in GOOD for t in req):
        status='PENDING';reasons.append('REQUIRED_TF_UNAVAILABLE')
    else:
        status='PASS' if all(x['status']=='PASS' for x in per.values()) else 'PASS_WITH_LIMITATIONS'
    gate='FAIL' if m02exec=='FAIL' or status=='FAIL' else 'PENDING'
    if m02exec=='PASS' and status=='PASS' and not snapshot.get('_fixture_only'):
        gate='PASS'  # contextual data gate only; M14 remains sole execution authorizer
    # pending data must never be execution PASS
    if status not in GOOD: gate='FAIL' if status=='FAIL' else 'PENDING'
    evidence=list(dict.fromkeys(all_ev))
    result={'module_id':'M03','module_version':VERSION,'analysis_id':snapshot.get('analysis_id'),
            'snapshot_id':snapshot['snapshot_id'],'as_of':now.isoformat(),
            'instrument_id':'XAUUSD','config_version':cfg.get('profile_id'),
            'status':status,'run_status':'COMPLETED','reason_codes':reasons,
            'missing_inputs':[t for t in req if per[t]['status'] not in GOOD],
            'evidence_ids':evidence, 'timeframes':per,
            'm02_regime_conflict':m02.get('regime_conflict','UNRESOLVED'),
            'analysis_gate':{'required_for':['ANALYSIS','DIRECTION'],'status':status},
            'execution_context_gate':{'required_for':['EXECUTION'],'status':gate},
            'execution_permission':'BLOCKED','visual_capture_enabled':False,
            'market_data_source_policy':SOURCE_POLICY,
            'limitations':['RESEARCH_ONLY','PROVISIONAL_DETECTORS','NO_LIVE_OR_OOS_VALIDATION']}
    result['early_evidence']=early_assessment(result,m02,strategy_plan) if status in GOOD else {
        'status':'CANDIDATE','signal_validity':'INSUFFICIENT_EVIDENCE',
        'missing_core':['M03_VALID_MARKET_EVIDENCE']}
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description='M03 JSONL research analyzer - no orders and no screenshots')
    p.add_argument('--input',default='-',help='JSONL envelopes: data_snapshot, market_state, optional strategy_plan')
    p.add_argument('--profile',default=str(Path(__file__).with_name('M03_PROFILE.example.json')))
    a=p.parse_args(argv)
    cfg=json.loads(Path(a.profile).read_text(encoding='utf-8'))
    stream=sys.stdin if a.input=='-' else open(a.input,encoding='utf-8')
    try:
        for line in stream:
            if not line.strip():continue
            try:
                obj=json.loads(line)
                d=analyze(obj['data_snapshot'],obj['market_state'],cfg,obj.get('strategy_plan'))
            except (KeyError,ValueError,TypeError,IndexError) as exc:
                d={'module_id':'M03','status':'FAIL','run_status':'FAILED',
                   'reason_codes':[str(exc)],'execution_context_gate':{'status':'FAIL'},
                   'execution_permission':'BLOCKED'}
            print(json.dumps(d,ensure_ascii=False,allow_nan=False))
    finally:
        if stream is not sys.stdin:stream.close()

if __name__=='__main__':
    main()
