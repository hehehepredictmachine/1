"""Synthetic logic tests only. No broker data, strategy profitability or MT5 connection."""
from __future__ import annotations
import copy
import json
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from M03_REFERENCE_ENGINE import (analyze, selected_bars, metric, available_pivots,
                                   find_breaks, find_sweeps, find_fvgs, find_order_blocks, atr_at,
                                   premium_discount, early_assessment, SOURCE_POLICY)

ROOT=Path(__file__).parent
CFG=json.loads((ROOT/'M03_PROFILE.example.json').read_text())
BASE=datetime(2026,8,3,0,0,tzinfo=timezone.utc)

def dt(m): return (BASE+timedelta(minutes=m)).isoformat()

def mkbar(i, o=100.0,h=101.0,l=99.0,c=100.0, tf='M1', source='MT5-DEMO', state='CLOSED'):
    return {'instrument_id':'XAUUSD','source_id':source,'timeframe':tf,'bar_open_utc':dt(i),
            'close_confirmed_at':dt(i+1),'available_at':dt(i+1),'evidence_id':f'bar-{tf}-{i}',
            'price_basis':'BID','bar_state':state,'open':o,'high':h,'low':l,'close':c,
            'revision':0,'tick_volume':100}

def bars12(tf='M1'):
    data=[(100,101,99,100),(100,102,99.2,101),(101,104,100,103),
          (103,103.4,99.1,100),(100,102,99.6,101),(101,103,100,102),
          (102,103,99.5,100),(100,104,99.9,103),(103,104,101,103),
          (103,106,102,105),(105,106,98,101),(101,103,99.2,102)]
    return [mkbar(i,*z,tf=tf) for i,z in enumerate(data)]

def m02tf(bars,trend='TREND_UP',status='PASS'):
    return {'status':status,'structure_regime':trend,'direction':'BULLISH' if trend=='TREND_UP' else 'BEARISH',
            'last_closed_at':bars[-1]['close_confirmed_at'],'atr':1.5,
            'prior_structure_regime_by_bar':{bars[9]['bar_open_utc']:{'regime':trend,'available_at':bars[8]['close_confirmed_at'],'evidence_id':'prior-regime-9'}},
            'swings':{'highs':[{'price':104,'pivot_time':bars[2]['bar_open_utc'],'available_at':bars[4]['close_confirmed_at']}],
                      'lows':[{'price':99.1,'pivot_time':bars[3]['bar_open_utc'],'available_at':bars[5]['close_confirmed_at']}]}}

def envelope(tfs=('M1',),bars=None):
    bars=bars or bars12()
    cb={}; mt={}
    for tf in tfs:
        bb=[{**z,'timeframe':tf,'evidence_id':f'{tf}-{z["evidence_id"]}'} for z in bars]
        cb[tf]=bb;mt[tf]=m02tf(bb)
    sn={'analysis_id':'SYNT-M03','snapshot_id':'snap-A','as_of':dt(20),
        'data_source_policy':SOURCE_POLICY,'visual_capture_enabled':False,
        'candles_by_tf':cb,'data_gates':[{'required_for':['ANALYSIS'],'status':'PASS'}],
        '_fixture_only':True}
    state={'snapshot_id':'snap-A','as_of':dt(20),'instrument_id':'XAUUSD',
           'status':'PASS','analysis_gate':{'status':'PASS'},
           'execution_context_gate':{'status':'PENDING'}, 'structural_direction':'BULLISH',
           'regime_conflict':'ALIGNED','timeframes':mt}
    cfg={**CFG,'timeframes':list(tfs),'required_timeframes':list(tfs)}
    return sn,state,cfg

class TestM03(unittest.TestCase):
    def test_01_profile_research(self): self.assertTrue(CFG['research_only'])
    def test_02_policy(self): self.assertEqual(SOURCE_POLICY,'MT5_PRIMARY_TV_SUPPLEMENTAL_NO_SCREENSHOTS')
    def test_03_ohlc_metric(self): self.assertAlmostEqual(metric(mkbar(0,100,104,98,102))['body_ratio'],2/6)
    def test_04_zero_range(self): self.assertIsNone(metric(mkbar(0,100,100,100,100))['body_ratio'])
    def test_05_bar_closed_only(self):
        s,_,_=envelope();s['candles_by_tf']['M1'].append(mkbar(12,tf='M1',state='FORMING'))
        self.assertEqual(len(selected_bars(s,'M1')[0]),12)
    def test_06_no_tv_prices(self):
        s,_,_=envelope();s['candles_by_tf']['M1'].append(mkbar(12,tf='M1',source='TV-WEBHOOK'))
        self.assertIn('NON_MT5_BROKER_BAR',selected_bars(s,'M1')[1]);self.assertEqual(selected_bars(s,'M1')[0],[])
    def test_07_no_future_evidence(self):
        s,_,_=envelope();s['candles_by_tf']['M1'].append(mkbar(30))
        b,i=selected_bars(s,'M1');self.assertEqual(len(b),12);self.assertIn('FUTURE_BAR_EXCLUDED',i)
    def test_08_wrong_symbol(self):
        s,_,_=envelope();s['candles_by_tf']['M1'][0]['instrument_id']='XAGUSD'
        self.assertIn('INSTRUMENT_OR_TF_MISMATCH',selected_bars(s,'M1')[1])
    def test_09_wrong_tf(self):
        s,_,_=envelope();s['candles_by_tf']['M1'][0]['timeframe']='M5'
        self.assertEqual(selected_bars(s,'M1')[0],[])
    def test_10_bad_ohlc(self):
        s,_,_=envelope();s['candles_by_tf']['M1'][0]['low']=200
        self.assertIn('INVALID_OHLC',selected_bars(s,'M1')[1])
    def test_11_same_revision_duplicate(self):
        s,_,_=envelope();s['candles_by_tf']['M1'].append(copy.deepcopy(s['candles_by_tf']['M1'][0]))
        self.assertEqual(len(selected_bars(s,'M1')[0]),12)
    def test_12_same_revision_conflict(self):
        s,_,_=envelope();v=copy.deepcopy(s['candles_by_tf']['M1'][0]);v['high']=120;s['candles_by_tf']['M1'].append(v)
        self.assertIn('CONFLICTING_REVISION',selected_bars(s,'M1')[1]);self.assertEqual(selected_bars(s,'M1')[0],[])
    def test_13_higher_revision(self):
        s,_,_=envelope();v=copy.deepcopy(s['candles_by_tf']['M1'][0]);v['revision']=1;v['high']=120;s['candles_by_tf']['M1'].append(v)
        b,issues=selected_bars(s,'M1');self.assertEqual(b[0]['high'],120);self.assertIn('HIGHER_REVISION_OBSERVED',issues)
    def test_14_mixed_basis(self):
        s,_,_=envelope();s['candles_by_tf']['M1'][0]['price_basis']='ASK'
        self.assertIn('MIXED_PRICE_BASIS',selected_bars(s,'M1')[1])
    def test_15_mixed_sources(self):
        s,_,_=envelope();s['candles_by_tf']['M1'][0]['source_id']='MT5-OTHER'
        self.assertIn('MIXED_BROKER_SOURCES',selected_bars(s,'M1')[1])
    def test_16_no_provenance(self):
        s,_,_=envelope();s['candles_by_tf']['M1'][0].pop('evidence_id')
        self.assertEqual(selected_bars(s,'M1')[0],[])
    def test_17_invalid_time(self):
        s,_,_=envelope();s['candles_by_tf']['M1'][0]['available_at']=dt(-1)
        self.assertIn('INVALID_TIME',selected_bars(s,'M1')[1])
    def test_18_pivot_available_after_bar(self):
        s,m,_=envelope();b=s['candles_by_tf']['M1'];tf=m['timeframes']['M1'];tf['swings']['highs'][0]['available_at']=dt(30)
        self.assertFalse(available_pivots(tf,b,'highs',b[9],0.01))
    def test_19_pivot_at_same_bar_confirmation_disallowed(self):
        s,m,_=envelope();b=s['candles_by_tf']['M1'];tf=m['timeframes']['M1'];tf['swings']['highs'][0]['available_at']=b[9]['available_at']
        self.assertFalse(available_pivots(tf,b,'highs',b[9],0.01))
    def test_20_pivot_price_mismatch(self):
        s,m,_=envelope();b=s['candles_by_tf']['M1'];tf=m['timeframes']['M1'];tf['swings']['highs'][0]['price']=999
        self.assertFalse(available_pivots(tf,b,'highs',b[9],0.01))
    def test_21_bos_close_confirm(self):
        s,m,c=envelope();b=s['candles_by_tf']['M1'];x=find_breaks(b,m['timeframes']['M1'],c,'M1')
        self.assertTrue(any(z['kind']=='BOS' and z['direction']=='BULLISH' and z['bar_open_utc']==b[9]['bar_open_utc'] for z in x))
    def test_22_bos_no_wick(self):
        s,m,c=envelope();b=s['candles_by_tf']['M1'];b[9]['close']=103
        self.assertFalse(any(z['bar_open_utc']==b[9]['bar_open_utc'] for z in find_breaks(b,m['timeframes']['M1'],c,'M1')))
    def test_23_choch_countertrend(self):
        s,m,c=envelope();b=s['candles_by_tf']['M1'];m['timeframes']['M1']['structure_regime']='TREND_DOWN';
        m['timeframes']['M1']['prior_structure_regime_by_bar'][b[9]['bar_open_utc']]['regime']='TREND_DOWN'
        self.assertTrue(any(z['kind']=='CHOCH' and z['direction']=='BULLISH' for z in find_breaks(b,m['timeframes']['M1'],c,'M1')))
    def test_24_mss_requires_displacement(self):
        s,m,c=envelope();b=s['candles_by_tf']['M1'];tf=m['timeframes']['M1'];tf['structure_regime']='TREND_DOWN';tf['prior_structure_regime_by_bar'][b[9]['bar_open_utc']]['regime']='TREND_DOWN';tf['atr']=1.0;c['atr_period']=3;c['displacement_body_ratio_min']=0.45;c['displacement_range_atr_min']=0.5
        self.assertTrue(any(z['kind']=='MSS' and z['direction']=='BULLISH' for z in find_breaks(b,tf,c,'M1')))
    def test_25_range_break_unclassified(self):
        s,m,c=envelope();tf=m['timeframes']['M1'];tf['structure_regime']='RANGE';
        tf['prior_structure_regime_by_bar'][s['candles_by_tf']['M1'][9]['bar_open_utc']]['regime']='RANGE'
        self.assertTrue(any(z['kind']=='STRUCTURE_BREAK_UNCLASSIFIED' for z in find_breaks(s['candles_by_tf']['M1'],tf,c,'M1')))
    def test_26_sweep_reclaim(self):
        s,m,c=envelope();x=find_sweeps(s['candles_by_tf']['M1'],m['timeframes']['M1'],c,'M1')
        self.assertTrue(any(z['liquidity_side']=='SSL' and z['directional_reaction']=='BULLISH' for z in x))
    def test_27_sweep_no_reclaim(self):
        s,m,c=envelope();b=s['candles_by_tf']['M1'];b[10]['close']=98.8
        self.assertFalse(any(z['observed_at']==b[10]['available_at'] and z['liquidity_side']=='SSL' for z in find_sweeps(b,m['timeframes']['M1'],c,'M1')))
    def test_28_bull_fvg(self):
        x=[mkbar(0,100,101,99,100),mkbar(1,101,103,100.5,102.5),mkbar(2,103,104,102,103.5)]
        f=find_fvgs(x,CFG,'M1');self.assertEqual(f[0]['direction'],'BULLISH');self.assertEqual(f[0]['zone_low'],101)
    def test_29_bear_fvg(self):
        x=[mkbar(0,104,105,103,104),mkbar(1,102,103.5,101,102),mkbar(2,100,101,99,100)]
        f=find_fvgs(x,CFG,'M1');self.assertEqual(f[0]['direction'],'BEARISH')
    def test_30_fvg_not_formed_with_two_bars(self):
        self.assertEqual(find_fvgs(bars12()[:2],CFG,'M1'),[])
    def test_31_fvg_fill_future_only(self):
        x=[mkbar(0,100,101,99,100),mkbar(1,101,103,100.5,102.5),mkbar(2,103,104,102,103.5),mkbar(3,103,103,100,101)]
        f=find_fvgs(x,CFG,'M1');self.assertEqual(f[0]['status'],'FILLED')
    def test_32_no_ob_without_displacement(self):
        s,m,c=envelope();b=s['candles_by_tf']['M1'];x=find_breaks(b,m['timeframes']['M1'],c,'M1')
        self.assertFalse(find_order_blocks(b,x,c,'M1'))
    def test_33_ob_after_displacement(self):
        s,m,c=envelope();b=s['candles_by_tf']['M1'];tf=m['timeframes']['M1'];tf['atr']=1.0;c['atr_period']=3;c['displacement_body_ratio_min']=0.45;c['displacement_range_atr_min']=0.5
        x=find_breaks(b,tf,c,'M1');ob=find_order_blocks(b,x,c,'M1')
        self.assertTrue(any(z['direction']=='BULLISH' and z['rating']=='UNRATED' for z in ob))
    def test_34_pd_pivots(self):
        s,m,c=envelope();p=premium_discount(s['candles_by_tf']['M1'],m['timeframes']['M1'],'M1',c)
        self.assertEqual(p['status'],'AVAILABLE')
    def test_35_pd_without_pivots(self):
        s,m,c=envelope();m['timeframes']['M1']['swings']={'highs':[],'lows':[]}
        self.assertEqual(premium_discount(s['candles_by_tf']['M1'],m['timeframes']['M1'],'M1',c)['status'],'UNAVAILABLE')
    def test_36_analyze_basic(self):
        s,m,c=envelope();r=analyze(s,m,c)
        self.assertEqual(r['status'],'PASS');self.assertEqual(r['early_evidence']['status'],'CANDIDATE')
    def test_37_no_permission(self):
        s,m,c=envelope();self.assertEqual(analyze(s,m,c)['execution_permission'],'BLOCKED')
    def test_38_no_screenshots(self):
        s,m,c=envelope();self.assertFalse(analyze(s,m,c)['visual_capture_enabled'])
    def test_39_m02_fail(self):
        s,m,c=envelope();m['analysis_gate']['status']='FAIL'
        self.assertEqual(analyze(s,m,c)['status'],'FAIL')
    def test_40_m02_fail_global(self):
        s,m,c=envelope();m['status']='FAIL'
        self.assertEqual(analyze(s,m,c)['status'],'FAIL')
    def test_41_m02_exec_fail(self):
        s,m,c=envelope();m['execution_context_gate']['status']='FAIL'
        self.assertEqual(analyze(s,m,c)['execution_context_gate']['status'],'FAIL')
    def test_42_same_snapshot(self):
        s,m,c=envelope();m['snapshot_id']='other'
        with self.assertRaises(ValueError):analyze(s,m,c)
    def test_43_no_future_m02(self):
        s,m,c=envelope();m['as_of']=dt(19)
        with self.assertRaises(ValueError):analyze(s,m,c)
    def test_44_wrong_instrument_m02(self):
        s,m,c=envelope();m['instrument_id']='XAGUSD'
        with self.assertRaises(ValueError):analyze(s,m,c)
    def test_45_wrong_source_policy(self):
        s,m,c=envelope();s['data_source_policy']='TV_PRIMARY'
        with self.assertRaises(ValueError):analyze(s,m,c)
    def test_46_screenshot_enabled(self):
        s,m,c=envelope();s['visual_capture_enabled']=True
        with self.assertRaises(ValueError):analyze(s,m,c)
    def test_47_research_profile_only(self):
        s,m,c=envelope();c['research_only']=False
        with self.assertRaises(ValueError):analyze(s,m,c)
    def test_48_required_tf_missing(self):
        s,m,c=envelope();c['required_timeframes']=['H1']
        with self.assertRaises(ValueError):analyze(s,m,c)
    def test_49_m02_end_mismatch(self):
        s,m,c=envelope();m['timeframes']['M1']['last_closed_at']=dt(10)
        self.assertEqual(analyze(s,m,c)['status'],'PENDING')
    def test_50_early_not_without_core(self):
        s,m,c=envelope();r=analyze(s,m,c,{'intended_direction':'LONG','next_expected_event':{'timeframe':'M1','condition':'close > level'}})
        self.assertEqual(r['early_evidence']['signal_validity'],'INSUFFICIENT_EVIDENCE')
    def test_51_early_with_five_core(self):
        s,m,c=envelope();s['candles_by_tf']['M1'][7].update(open=100,close=101,high=102,low=99.9);s['candles_by_tf']['M1'][9]['low']=102.2
        baseline=analyze(s,m,c);ids=baseline['evidence_ids'];self.assertTrue(len(ids)>=2)
        loc=next((x for x in ids if x.startswith('M03:FVG:')),None)
        self.assertIsNotNone(loc)
        liq=next((x for x in ids if x.startswith('M03:LEVEL:')),None)
        self.assertIsNotNone(liq)
        plan={'intended_direction':'LONG','location_evidence_id':loc,
              'liquidity_evidence_id':liq,
              'next_expected_event':{'timeframe':'M1','condition':'close > level','failure_condition':'close <= level'},
              'invalidation':{'timeframe':'M1','condition':'low < 99','rule':'closed_close'}}
        self.assertEqual(analyze(s,m,c,plan)['early_evidence']['status'],'EARLY_SETUP')
    def test_52_early_short_block_without_structure(self):
        s,m,c=envelope();ids=analyze(s,m,c)['evidence_ids'];plan={'intended_direction':'SHORT','location_evidence_id':next((x for x in ids if x.startswith('M03:FVG:')),None),'liquidity_evidence_id':next((x for x in ids if x.startswith('M03:LEVEL:')),None),
         'next_expected_event':{'timeframe':'M1','condition':'x','failure_condition':'y'},'invalidation':{'timeframe':'M1','condition':'x','rule':'wick'}}
        self.assertIn('STRUCTURAL_ADVANTAGE',analyze(s,m,c,plan)['early_evidence']['missing_core'])
    def test_53_early_countertrend_evidence(self):
        s,m,c=envelope();s['candles_by_tf']['M1'][7].update(open=100,close=101,high=102,low=99.9);s['candles_by_tf']['M1'][9]['low']=102.2
        ids=analyze(s,m,c)['evidence_ids'];plan={'intended_direction':'SHORT','location_evidence_id':next((x for x in ids if x.startswith('M03:FVG:')),None),'liquidity_evidence_id':next((x for x in ids if x.startswith('M03:LEVEL:')),None),
         'countertrend_structure_evidence_id':ids[0], 'next_expected_event':{'timeframe':'M1','condition':'x','failure_condition':'y'},
         'invalidation':{'timeframe':'M1','condition':'x','rule':'wick'}}
        self.assertEqual(analyze(s,m,c,plan)['early_evidence']['status'],'CANDIDATE')
    def test_54_early_never_authorized(self):
        s,m,c=envelope();r=analyze(s,m,c)
        self.assertEqual(r['early_evidence']['signal_validity'],'INSUFFICIENT_EVIDENCE')
    def test_55_no_prices_from_tv_aux(self):
        s,m,c=envelope();s['auxiliary_context']={'tradingview':{'XAUUSD':999999}}
        r=analyze(s,m,c);self.assertEqual(r['status'],'PASS')
    def test_56_idempotent_static(self):
        s,m,c=envelope();a=analyze(s,m,c);b=analyze(s,m,c)
        self.assertEqual(a,b)
    def test_57_empty_bars(self):
        s,m,c=envelope();s['candles_by_tf']['M1']=[]
        self.assertEqual(analyze(s,m,c)['status'],'PENDING')
    def test_58_tf_required_fail(self):
        s,m,c=envelope();s['candles_by_tf']['M1'][2]['high']=0
        self.assertEqual(analyze(s,m,c)['status'],'FAIL')
    def test_59_no_retroactive_break_from_pivot_future(self):
        s,m,c=envelope();b=s['candles_by_tf']['M1'];tf=m['timeframes']['M1'];tf['swings']['highs'][0]['available_at']=dt(12)
        self.assertEqual(find_breaks(b,tf,c,'M1'),[])
    def test_60_unknown_regime_not_bos(self):
        s,m,c=envelope();tf=m['timeframes']['M1'];tf['structure_regime']='UNKNOWN';
        tf['prior_structure_regime_by_bar'][s['candles_by_tf']['M1'][9]['bar_open_utc']]['regime']='UNKNOWN'
        self.assertFalse(any(z['kind']=='BOS' for z in find_breaks(s['candles_by_tf']['M1'],tf,c,'M1')))

    def test_61_atr_only_past(self):
        b=bars12();a=atr_at(b,9,3)
        b[10]['high']=10000
        self.assertEqual(a,atr_at(b,9,3))
    def test_62_no_displacement_when_history_short(self):
        s,m,c=envelope();b=s['candles_by_tf']['M1'];c['atr_period']=40
        self.assertFalse(any(e['displacement_confirmed'] for e in find_breaks(b,m['timeframes']['M1'],c,'M1')))
    def test_63_invalid_prior_regime_time(self):
        s,m,c=envelope();b=s['candles_by_tf']['M1'];tf=m['timeframes']['M1']
        tf['prior_structure_regime_by_bar'][b[9]['bar_open_utc']]['available_at']=dt(20)
        self.assertTrue(any(e['kind']=='STRUCTURE_BREAK_UNCLASSIFIED' for e in find_breaks(b,tf,c,'M1')))
    def test_64_no_chase_unknown_countertrend_id(self):
        s,m,c=envelope();r=analyze(s,m,c)
        plan={'intended_direction':'SHORT','countertrend_structure_evidence_id':r['evidence_ids'][0],
              'location_evidence_id':'unknown','liquidity_evidence_id':'unknown'}
        self.assertIn('STRUCTURAL_ADVANTAGE',analyze(s,m,c,plan)['early_evidence']['missing_core'])

if __name__=='__main__':unittest.main(verbosity=2)
