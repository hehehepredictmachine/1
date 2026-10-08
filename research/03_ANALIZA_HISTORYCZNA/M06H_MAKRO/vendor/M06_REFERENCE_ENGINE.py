"""MasterQUO M06 v1.0.0: deterministic research-only quote replay and validation.
No broker connection, no screenshot/OCR, no live order placement. Standard library only.
This is a *reference validator for supplied point-in-time signals*, not a complete
strategy generator, MT5 Strategy Tester replacement, or validated live trading system.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import random
from datetime import datetime, timezone
from statistics import mean
from typing import Any

VERSION = '1.0.0-CANDIDATE'
POLICY = 'MT5_PRIMARY_TV_SUPPLEMENTAL_NO_SCREENSHOTS'

class ValidationError(ValueError):
    pass

def instant(v):
    if not isinstance(v,str): raise ValidationError('BAD_TIME')
    try:
        d=datetime.fromisoformat(v.replace('Z','+00:00'))
        if d.tzinfo is None: raise ValueError()
        return d.astimezone(timezone.utc)
    except ValueError as e: raise ValidationError('BAD_TIME') from e

def finite(v, name):
    if isinstance(v,bool) or not isinstance(v,(float,int)) or not math.isfinite(float(v)):
        raise ValidationError('BAD_'+name.upper())
    return float(v)

def need(condition,reason):
    if not condition: raise ValidationError(reason)

def canon(obj): return json.dumps(obj,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)

def quantile(data,q):
    if not data: return None
    a=sorted(data); position=(len(a)-1)*q; i=int(position)
    return a[i]+(a[min(i+1,len(a)-1)]-a[i])*(position-i)

def validate_config(p):
    need(p.get('schema_version')=='2.0.0','BAD_SCHEMA_VERSION')
    ds=p.get('data_snapshot',{})
    need(ds.get('data_source_policy')==POLICY,'BAD_SOURCE_POLICY')
    need(ds.get('visual_capture_enabled') is False,'SCREENSHOT_FORBIDDEN')
    need(ds.get('analysis_gate',{}).get('status') in ('PASS','PASS_WITH_LIMITATIONS'),'DATA_GATE_NOT_PASS')
    need(bool(ds.get('dataset_id') and ds.get('snapshot_id')),'MISSING_DATASET_ID')
    mt=p.get('market_state',{})
    need(mt.get('snapshot_id')==ds['snapshot_id'],'SNAPSHOT_MISMATCH')
    need(mt.get('as_of')==ds.get('as_of'),'AS_OF_MISMATCH')
    as_of=instant(ds['as_of'])
    need(mt.get('analysis_gate',{}).get('status') in ('PASS','PASS_WITH_LIMITATIONS'),'M02_GATE_NOT_PASS')
    acct=p.get('account',{})
    need(acct.get('account_type')=='ZERO_SPREAD','ACCOUNT_PROFILE_MISMATCH')
    need(isinstance(acct.get('symbol'),str) and bool(acct.get('symbol')),'MISSING_SYMBOL')
    need(acct.get('currency') and acct.get('account_id_hash'),'MISSING_BROKER_IDENTITY')
    need(acct.get('commission_source') in ('BROKER_DEALS','BROKER_TARIFF','SCENARIO_ONLY'),'COMMISSION_SOURCE_REQUIRED')
    commission=finite(acct.get('commission_per_lot_side'),'commission')
    need(commission>=0,'NEGATIVE_COMMISSION')
    money=finite(acct.get('money_per_price_unit_per_lot'),'contract_conversion')
    need(money>0,'INVALID_CONTRACT_CONVERSION')
    slip=finite(acct.get('slippage_price'),'slippage')
    need(slip>=0,'NEGATIVE_SLIPPAGE')
    need(acct.get('conversion_source') in ('BROKER_ORDER_CALC_PROFIT','BROKER_CONTRACT_VERIFIED','SCENARIO_ONLY'),'CONVERSION_SOURCE_REQUIRED')
    profile=p.get('validation_profile',{})
    max_age=finite(profile.get('max_entry_wait_seconds'),'max_entry_wait_seconds')
    need(max_age>0,'INVALID_ENTRY_WAIT')
    confidence=finite(profile.get('confidence_level',.95),'confidence_level')
    need(0<confidence<1,'INVALID_CONFIDENCE')
    iterations=profile.get('bootstrap_iterations',200)
    need(type(iterations)==int and 20<=iterations<=20000,'INVALID_BOOTSTRAP_ITERATIONS')
    need(isinstance(p.get('trial_ledger'),list) and bool(p['trial_ledger']),'TRIAL_LEDGER_REQUIRED')
    need(profile.get('acceptance_criteria_frozen') is True,'ACCEPTANCE_NOT_FROZEN')
    need(profile.get('forward_demo_required') is True,'FORWARD_DEMO_REQUIRED')
    folds=profile.get('folds',[])
    need(isinstance(folds,list) and folds,'FOLDS_REQUIRED')
    names=set()
    for fold in folds:
        name=fold.get('id')
        need(name and name not in names,'FOLD_ID_DUPLICATE'); names.add(name)
        start,end=instant(fold['start']),instant(fold['end'])
        need(start<end and end<=as_of,'INVALID_FOLD_WINDOW')
        need(fold.get('role') in ('DEVELOPMENT','VALIDATION','FINAL_OOS','FORWARD_DEMO'),'INVALID_FOLD_ROLE')
    folds=sorted(folds,key=lambda f: instant(f['start']))
    need(all(instant(folds[i]['end'])<=instant(folds[i+1]['start']) for i in range(len(folds)-1)),'FOLD_OVERLAP')
    return as_of,acct,profile,folds,money,commission,slip,max_age

def prepare_ticks(p,as_of,acct):
    ticks=p.get('ticks',[])
    need(isinstance(ticks,list) and bool(ticks),'TICKS_MISSING')
    arr=[]; prev=None; prev_av=None; seen=set()
    for v in ticks:
        need(v.get('source_id','').startswith('MT5'),'NON_MT5_EXECUTION_TICK')
        need(v.get('symbol')==acct['symbol'],'TICK_SYMBOL_MISMATCH')
        t=instant(v['time']); av=instant(v['available_at'])
        need(t<=av<=as_of,'TICK_LOOKAHEAD')
        if prev is not None: need(t>=prev,'TICKS_NOT_SORTED')
        if prev_av is not None: need(av>=prev_av,'TICK_AVAILABILITY_NOT_SORTED')
        bid,ask=finite(v.get('bid'),'bid'),finite(v.get('ask'),'ask')
        need(0<bid<=ask,'INVALID_BID_ASK')
        need((t,bid,ask) not in seen,'DUPLICATE_TICK')
        seen.add((t,bid,ask));prev=t;prev_av=av
        arr.append({'t':t,'available_at':av,'bid':bid,'ask':ask})
    return arr

def trade_one(signal,ticks,account,profile,folds,money,commission,slip,max_age,as_of):
    sid=signal.get('signal_id')
    need(sid and isinstance(sid,str),'SIGNAL_ID_REQUIRED')
    side=signal.get('side'); need(side in ('LONG','SHORT'),'BAD_SIDE')
    need(signal.get('symbol')==account['symbol'],'SIGNAL_SYMBOL_MISMATCH')
    need(signal.get('source')=='MT5_DERIVED','SIGNAL_SOURCE_INVALID')
    need(signal.get('bar_state')=='CLOSED','SIGNAL_ON_FORMING_BAR')
    need(signal.get('strategy_version') and signal.get('spec_hash'),'FROZEN_STRATEGY_REQUIRED')
    st=instant(signal['signal_at']); av=instant(signal['available_at'])
    need(st<=av<=as_of,'SIGNAL_LOOKAHEAD')
    signal_features=signal.get('feature_available_at',[])
    need(isinstance(signal_features,list) and signal_features,'FEATURE_PROVENANCE_REQUIRED')
    for x in signal_features: need(instant(x)<=st,'FEATURE_LEAKAGE')
    sl=finite(signal.get('stop'),'stop');tp=finite(signal.get('target'),'target')
    size=finite(signal.get('lots'),'lots');need(size>0,'BAD_LOTS')
    timeout=finite(signal.get('max_hold_seconds'),'max_hold_seconds');need(timeout>0,'BAD_HOLD')
    if signal.get('entry_type')!='MARKET_NEXT_AVAILABLE_TICK':raise ValidationError('UNSUPPORTED_ENTRY_TYPE')
    results={'signal_id':sid,'side':side,'signal_at':signal['signal_at'],'status':'NO_FILL','reason_codes':[], 'execution_permission':'BLOCKED'}
    fold=next((f for f in folds if instant(f['start'])<=av<instant(f['end'])),None)
    if fold is None:
        results.update(status='OUTSIDE_FOLD',reason_codes=['NO_FOLD_FOR_SIGNAL']);return results
    results['fold_id']=fold['id'];results['fold_role']=fold['role']
    q=next((x for x in ticks if x['available_at']>=av and (x['available_at']-av).total_seconds()<=max_age and x['t']>av),None)
    if q is None:results['reason_codes']=['NO_ENTRY_TICK'];return results
    fill= (q['ask']+slip) if side=='LONG' else (q['bid']-slip)
    need((sl<fill<tp) if side=='LONG' else (tp<fill<sl),'INVALID_ENTRY_SL_TP')
    results['entry_at']=q['available_at'].isoformat();results['entry_price']=fill
    expiry=q['available_at'].timestamp()+timeout
    # Walk available ticks in chronological order, with conservative exit when quote first crosses target/stop.
    reason=None
    for x in ticks:
        if x['available_at']<=q['available_at']:continue
        if x['available_at'].timestamp()>expiry:
            reason='TIMEOUT';exit_tick=x;break
        mark=x['bid'] if side=='LONG' else x['ask']
        if side=='LONG' and mark<=sl or side=='SHORT' and mark>=sl:reason='SL';exit_tick=x;break
        if side=='LONG' and mark>=tp or side=='SHORT' and mark<=tp:reason='TP';exit_tick=x;break
    if reason is None:
        results.update(status='UNRESOLVED',reason_codes=['NO_EXIT_TICK_WITHIN_HORIZON']);return results
    if reason=='TIMEOUT' and exit_tick['available_at'].timestamp()>expiry:
        # No quote at the exact horizon. It is invalid to assume execution at a past price.
        results.update(status='UNRESOLVED',reason_codes=['TIMEOUT_QUOTE_UNAVAILABLE']);return results
    px=(exit_tick['bid']-slip) if side=='LONG' else (exit_tick['ask']+slip)
    if exit_tick['available_at']>=instant(fold['end']):
        results.update(status='PURGED_BOUNDARY',reason_codes=['LABEL_CROSSES_FOLD_END']);return results
    if fold['role']=='DEVELOPMENT' and signal.get('label_available_at'):
        need(instant(signal['label_available_at'])<=instant(fold['end']),'DEVELOPMENT_LABEL_LEAKAGE')
    overnight=(exit_tick['available_at'].date()-q['available_at'].date()).days>0
    if account.get('swap_per_lot_per_overnight') is not None:
        finite(account['swap_per_lot_per_overnight'],'swap')
    swap=account.get('swap_per_lot_per_overnight')
    if overnight and swap is None:
        results.update(status='COST_UNKNOWN',reason_codes=['SWAP_UNKNOWN']);return results
    swap_cost=(max(0,(exit_tick['available_at'].date()-q['available_at'].date()).days)*float(swap or 0)*size)
    gross= (px-fill)*money*size * (1 if side=='LONG' else -1)
    fees=2*commission*size
    net=gross-fees-swap_cost
    stoprisk=(abs(fill-sl)*money*size+fees)
    need(stoprisk>0,'BAD_STOP_RISK')
    results.update(status='COMPLETED',exit_at=exit_tick['available_at'].isoformat(),exit_price=px,exit_reason=reason,
        gross_pnl=round(gross,8),commission=round(fees,8),swap=round(swap_cost,8),
        net_pnl=round(net,8),initial_risk=round(stoprisk,8),net_r=round(net/stoprisk,8),
        spread_entry=round(q['ask']-q['bid'],8),spread_exit=round(exit_tick['ask']-exit_tick['bid'],8),
        quote_entry={'bid':q['bid'],'ask':q['ask']},quote_exit={'bid':exit_tick['bid'],'ask':exit_tick['ask']},
        slip_price_each_side=slip,reason_codes=[])
    return results

def max_drawdown(pnls):
    peak=0;equity=0;worst=0
    for v in pnls:
        equity+=v;peak=max(peak,equity);worst=max(worst,peak-equity)
    return worst

def metric(trades):
    if not trades:return {'trades':0,'mean_net_r':None,'mean_net_pnl':None,'profit_factor':None,'max_drawdown_money':None,'win_rate':None}
    vals=[x['net_pnl'] for x in trades]
    pos=sum(max(0,v) for v in vals);neg=-sum(min(0,v) for v in vals)
    return {'trades':len(vals),'mean_net_r':round(mean(x['net_r'] for x in trades),8),
        'mean_net_pnl':round(mean(vals),8),'profit_factor':round(pos/neg,8) if neg else None,
        'profit_factor_status':'DEFINED' if neg else 'UNDEFINED_NO_LOSSES',
        'max_drawdown_money':round(max_drawdown(vals),8),
        'win_rate':round(sum(x>0 for x in vals)/len(vals),8)}

def boot_day_blocks(trades,iterations,seed,confidence):
    if len(trades)<2 or len({x['entry_at'][:10] for x in trades})<2:return {'run_status':'NOT_RUN','reason':'INSUFFICIENT_DAY_BLOCKS'}
    blocks={}
    for x in trades: blocks.setdefault(x['entry_at'][:10],[]).append(x)
    days=list(blocks);rng=random.Random(seed);points=[]
    for _ in range(iterations):
        sample=[]
        for _ in days: sample+=blocks[rng.choice(days)]
        points.append(mean(v['net_r'] for v in sample))
    alpha=(1-confidence)/2
    return {'run_status':'COMPLETED','method':'UTC_DAY_BLOCK_BOOTSTRAP','day_blocks':len(days),'iterations':iterations,'seed':seed,
            'mean_net_r_interval':[round(quantile(points,alpha),8),round(quantile(points,1-alpha),8)]}

def main(packet):
    as_of,acct,profile,folds,money,commission,slip,max_age=validate_config(packet)
    ticks=prepare_ticks(packet,as_of,acct)
    signals=packet.get('signals',[])
    need(isinstance(signals,list),'SIGNALS_NOT_LIST')
    seen=set();trades=[]
    for s in signals:
        need(s.get('signal_id') not in seen,'DUPLICATE_SIGNAL')
        seen.add(s.get('signal_id'))
        trades.append(trade_one(s,ticks,acct,profile,folds,money,commission,slip,max_age,as_of))
    completed=[x for x in trades if x['status']=='COMPLETED']
    metrics_by_fold={f['id']:metric([x for x in completed if x['fold_id']==f['id']]) for f in folds}
    oos=[x for x in completed if x['fold_role']=='FINAL_OOS']
    seed=profile.get('bootstrap_seed',20261008)
    need(type(seed)==int,'BAD_BOOTSTRAP_SEED')
    boots=boot_day_blocks(oos,profile.get('bootstrap_iterations',200),seed,profile.get('confidence_level',.95))
    scenario=[]
    for k in [1.,1.25,1.5,2.]:
        if completed:
            projected=[x['net_pnl']-(k-1)*(x['commission']+2*x['slip_price_each_side']*money*next(s['lots'] for s in signals if s['signal_id']==x['signal_id'])) for x in completed]
            scenario.append({'cost_multiplier':k,'mean_projected_pnl':round(mean(projected),8),'scope':'COMMISSION_AND_SLIPPAGE_ONLY','spread_stress':'NOT_MODELED'})
    provisional=acct.get('commission_source')=='SCENARIO_ONLY' or acct.get('conversion_source')=='SCENARIO_ONLY'
    expected=profile.get('min_completed_oos_trades',10)
    need(type(expected)==int and expected>0,'INVALID_MIN_OOS')
    reason=[]
    if provisional: reason.append('COST_OR_CONVERSION_SCENARIO_ONLY')
    if len(oos)<expected: reason.append('INSUFFICIENT_FINAL_OOS_TRADES')
    if boots['run_status']!='COMPLETED':reason.append('NO_CONFIDENCE_INTERVAL')
    reason.append('FORWARD_DEMO_NOT_RUN')
    out={'schema_version':'2.0.0','module_id':'M06','module_version':VERSION,
        'run_id':packet.get('run_id'),'snapshot_id':packet['data_snapshot']['snapshot_id'],
        'dataset_id':packet['data_snapshot']['dataset_id'],'as_of':packet['data_snapshot']['as_of'],
        'status':'PASS_WITH_LIMITATIONS' if completed else 'PENDING','run_status':'COMPLETED',
        'account_profile':{'type':'ZERO_SPREAD','verified_spread_zero':False,'commission_source':acct['commission_source'],'conversion_source':acct['conversion_source']},
        'validation':{'evidence_source':'SYNTHETIC_OR_USER_PROVIDED','approval_status':'RESEARCH_ONLY','executive_live_eligible':False,'reason_codes':reason},
        'metrics_by_fold':metrics_by_fold,'net_metrics':metric(completed),'bootstrap':boots,'bootstrap_window':'FINAL_OOS_ONLY',
        'cost_scenarios':scenario,'trades':trades,
        'trial_count':len(packet['trial_ledger']),'trial_ledger':packet['trial_ledger'],
        'limitations':['Reference event replay only; strategy rules, lookahead feature production, broker adapter, fills/partial fills not tested','No performance guarantee','No live promotion; M08/M11/M14 unchanged'],
        'execution_permission':'BLOCKED','live_execution_allowed':False,'submitted_order_id':None}
    return out

if __name__=='__main__':
    arg=argparse.ArgumentParser();arg.add_argument('--input',required=True);arg.add_argument('--output',required=True)
    a=arg.parse_args()
    try:
        with open(a.input,encoding='utf-8') as f: packet=json.load(f)
        result=main(packet)
    except (ValidationError,KeyError,TypeError,ValueError) as e:
        result={'module_id':'M06','module_version':VERSION,'status':'FAIL','run_status':'FAILED','reason_codes':[str(e)],'execution_permission':'BLOCKED','live_execution_allowed':False}
    with open(a.output,'w',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2,allow_nan=False)
    print(canon({'status':result.get('status'),'run_status':result['run_status'],'reason_codes':result.get('reason_codes',[])}))
