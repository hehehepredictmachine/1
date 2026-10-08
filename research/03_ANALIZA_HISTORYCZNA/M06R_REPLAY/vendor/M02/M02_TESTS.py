"""Offline synthetic tests only. No broker or Internet connectivity."""
import copy
import json
import math
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from M02_REFERENCE_ENGINE import (analyze,atr_series,efficiency,iso,numeric,valid_ohlc,
                                  prepare_candles,pivots,RegimeMemory,slope_atr)

CFG=json.loads(Path(__file__).with_name('M02_PROFILE.example.json').read_text(encoding='utf-8'))
START=datetime(2026, 5, 1, tzinfo=timezone.utc)

def stamp(d): return d.isoformat().replace('+00:00','Z')

def bars(tf='M1',n=80,mode='up',start=START):
    minutes={'M1':1,'M5':5,'M15':15,'H1':60,'H4':240,'D1':1440}[tf]
    out=[]
    for i in range(n):
        wave=math.sin(i*0.92)*(0.85 if mode=='down' else 1.7)
        mid=100+(i*.30 if mode=='up' else -i*.30 if mode=='down' else 0)+wave
        o=mid-0.1; c=mid
        t=start+timedelta(minutes=i*minutes)
        out.append({'instrument_id':'XAUUSD','source_id':'MT5-FIXTURE','timeframe':tf,'bar_open_utc':stamp(t),
                    'open':o,'high':max(o,c)+.6,'low':min(o,c)-.6,'close':c,
                    'available_at':stamp(t+timedelta(minutes=minutes)),
                    'close_confirmed_at':stamp(t+timedelta(minutes=minutes)),
                    'bar_state':'CLOSED','evidence_id':f'{tf}-{i}',
                    'price_basis':'BID','revision':0,'tick_volume':22+i})
    return out

def snapshot(modes=None,n=100,at=None):
    modes=modes or {}
    tf={x:bars(x,n,modes.get(x,'up')) for x in CFG['timeframes']}
    max_at=max(iso(x[-1]['close_confirmed_at']) for x in tf.values())
    return {'snapshot_id':'SYNTH-M02-1','analysis_id':'SYNTH-M02-1','as_of':stamp(at or max_at),
            '_fixture_only':True,'candles_by_tf':tf,'data_gates':[{'status':'PASS','required_for':['ANALYSIS','DIRECTION','EXECUTION']}],
            'quote':None,'auxiliary_context':{},'data_source_policy':'MT5_PRIMARY_TV_SUPPLEMENTAL_NO_SCREENSHOTS',
            'instrument_profiles':[{'instrument_id':'XAUUSD','source_id':'MT5-FIXTURE','tick_size':0.01}]}

class TestTimes(unittest.TestCase):
    def test_utc(self): self.assertEqual(iso('2026-10-08T12:00:00+02:00').hour,10)
    def test_naive_rejected(self):
        with self.assertRaises(ValueError): iso('2026-10-08T12:00:00')
    def test_null_rejected(self):
        with self.assertRaises(ValueError): iso(None)
    def test_bad_rejected(self):
        with self.assertRaises(ValueError): iso('later')
    def test_numeric_nan(self): self.assertFalse(numeric(float('nan')))
    def test_numeric_bool(self): self.assertFalse(numeric(True))
    def test_numeric_finite(self): self.assertTrue(numeric(42.4))

class TestInputs(unittest.TestCase):
    def setUp(self): self.s=snapshot()
    def test_ohlc_valid(self): self.assertTrue(valid_ohlc(self.s['candles_by_tf']['M1'][0]))
    def test_ohlc_bad(self):
        b=copy.deepcopy(self.s['candles_by_tf']['M1'][0]); b['low']=b['high']+1
        self.assertFalse(valid_ohlc(b))
    def test_forming_excluded(self):
        b=copy.deepcopy(self.s['candles_by_tf']['M1'][-1]); b['bar_state']='FORMING'
        b['bar_open_utc']=stamp(iso(b['bar_open_utc'])+timedelta(minutes=1))
        self.s['candles_by_tf']['M1'].append(b)
        arr,errs,forming,_=prepare_candles(self.s,'M1')
        self.assertEqual(len(arr),100); self.assertTrue(forming)
    def test_future_close_excluded(self):
        self.s['candles_by_tf']['M1'][-1]['close_confirmed_at']=stamp(iso(self.s['as_of'])+timedelta(seconds=1))
        arr,errs,_,_=prepare_candles(self.s,'M1')
        self.assertEqual(len(arr),99);self.assertIn('FUTURE_EVIDENCE_EXCLUDED',errs)
    def test_future_available_excluded(self):
        self.s['candles_by_tf']['M1'][-1]['available_at']=stamp(iso(self.s['as_of'])+timedelta(seconds=1))
        arr,errs,_,_=prepare_candles(self.s,'M1')
        self.assertEqual(len(arr),99);self.assertIn('FUTURE_EVIDENCE_EXCLUDED',errs)
    def test_cross_instrument_candle_quarantined(self):
        self.s['candles_by_tf']['M1'][-1]['instrument_id']='EURUSD'
        self.assertEqual(analyze(self.s,CFG)['status'],'FAIL')
    def test_wrong_tf_candle_quarantined(self):
        self.s['candles_by_tf']['M1'][-1]['timeframe']='H1'
        self.assertEqual(analyze(self.s,CFG)['status'],'FAIL')
    def test_runtime_offline_blocks_execution(self):
        self.s['_fixture_only']=False
        r=analyze(self.s,CFG,{'status':'OFFLINE','execution_data_gate':'FAIL'})
        self.assertEqual(r['execution_context_gate']['status'],'FAIL')
    def test_runtime_healthy_requires_data_gate(self):
        self.s['_fixture_only']=False
        r=analyze(self.s,CFG,{'status':'HEALTHY','execution_data_gate':'PASS'})
        self.assertEqual(r['execution_context_gate']['status'],'PASS')
    def test_runtime_healthy_without_gate_stays_pending(self):
        self.s['_fixture_only']=False
        r=analyze(self.s,CFG,{'status':'HEALTHY'})
        self.assertEqual(r['execution_context_gate']['status'],'PENDING')
    def test_tradingview_candle_excluded(self):
        self.s['candles_by_tf']['M1'][-1]['source_id']='TRADINGVIEW'
        arr,errs,_,_=prepare_candles(self.s,'M1')
        self.assertEqual(len(arr),99);self.assertIn('NON_MT5_CANDLE_EXCLUDED',errs)
    def test_screenshot_excluded(self):
        self.s['screenshot_url']='fake.png'
        self.assertNotIn('screenshot_url',json.dumps(analyze(self.s,CFG)).lower())
        self.assertFalse(analyze(self.s,CFG)['visual_capture_enabled'])
    def test_duplicates_idempotent(self):
        self.s['candles_by_tf']['M1'].append(copy.deepcopy(self.s['candles_by_tf']['M1'][-1]))
        arr,errs,_,_=prepare_candles(self.s,'M1')
        self.assertEqual(len(arr),100); self.assertFalse(errs)
    def test_conflicting_duplicates_fail(self):
        b=copy.deepcopy(self.s['candles_by_tf']['M1'][-1]);b['close']-=.1
        self.s['candles_by_tf']['M1'].append(b)
        self.assertIn('CONFLICTING_CLOSED_BAR_REVISIONS',prepare_candles(self.s,'M1')[1])
        self.assertEqual(analyze(self.s,CFG)['status'],'FAIL')
    def test_revised_bar_detected(self):
        b=copy.deepcopy(self.s['candles_by_tf']['M1'][-1]);b['revision']=1; b['close']-=.1
        self.s['candles_by_tf']['M1'].append(b)
        arr,_,_,revised=prepare_candles(self.s,'M1')
        self.assertEqual(len(arr),100);self.assertEqual(len(revised),1);self.assertEqual(arr[-1]['revision'],1)
    def test_price_basis_mixed_fail(self):
        self.s['candles_by_tf']['M1'][2]['price_basis']='LAST'
        self.assertEqual(analyze(self.s,CFG)['status'],'FAIL')
    def test_missing_evidence(self):
        self.s['candles_by_tf']['M1'][-1].pop('evidence_id')
        self.assertIn('MISSING_PROVENANCE',prepare_candles(self.s,'M1')[1])
    def test_missing_confirmation_timestamp(self):
        self.s['candles_by_tf']['M1'][-1].pop('close_confirmed_at')
        self.assertIn('CANDLE_TIME_INVALID',prepare_candles(self.s,'M1')[1])
    def test_garbage_bar(self):
        self.s['candles_by_tf']['M1'].append('not a bar')
        self.assertIn('INVALID_BAR_OBJECT',prepare_candles(self.s,'M1')[1])
    def test_older_asof_no_lookahead(self):
        self.s['as_of']=stamp(iso(self.s['candles_by_tf']['H4'][29]['close_confirmed_at']))
        result=analyze(self.s,CFG)
        self.assertLessEqual(result['timeframes']['H4']['closed_bars'],30)
        self.assertEqual(result['status'],'PENDING')
    def test_no_fabricated_tf(self):
        self.s['candles_by_tf'].pop('H1')
        r=analyze(self.s,CFG);self.assertEqual(r['status'],'PENDING');self.assertIn('H1',r['missing_inputs'])
    def test_optional_d1_missing_not_hard_fail(self):
        self.s['candles_by_tf'].pop('D1')
        r=analyze(self.s,CFG)
        self.assertEqual(r['status'],'PASS_WITH_LIMITATIONS')
        self.assertNotIn('D1',r['missing_inputs'])
    def test_m01_critical_gate(self):
        self.s['data_gates']=[{'status':'FAIL','required_for':['ANALYSIS']}]
        self.assertEqual(analyze(self.s,CFG)['status'],'FAIL')
    def test_missing_m01_gates_pending(self):
        self.s['data_gates']=[]
        self.assertEqual(analyze(self.s,CFG)['status'],'PENDING')
    def test_m01_execution_only_gate_block(self):
        self.s['data_gates']=[{'status':'PASS','required_for':['ANALYSIS','DIRECTION']},
                              {'status':'FAIL','required_for':['EXECUTION']}]
        self.s['_fixture_only']=False
        r=analyze(self.s,CFG,{'status':'HEALTHY'})
        self.assertEqual(r['status'],'PASS')
        self.assertEqual(r['execution_context_gate']['status'],'PENDING')
    def test_wrong_source_policy_pending(self):
        self.s['data_source_policy']='SCREENSHOT_PRIMARY'
        self.assertEqual(analyze(self.s,CFG)['status'],'PENDING')
    def test_down_trend_detected(self):
        s=snapshot({tf:'down' for tf in CFG['timeframes']})
        r=analyze(s,CFG)
        self.assertEqual(r['timeframes']['H4']['structure_regime'],'TREND_DOWN')
    def test_mtf_correction_without_false_reversal(self):
        s=snapshot({'H4':'up','H1':'up','M5':'down','M1':'down'})
        r=analyze(s,CFG)
        self.assertEqual(r['regime_conflict'],'CORRECTION_POSSIBLE')
        self.assertEqual(r['structural_direction'],'BULLISH')
        self.assertEqual(r['tactical_direction'],'BEARISH')
    def test_trader_quote_not_obtained(self):
        self.s['quote']={'source_id':'TRADINGVIEW','bid':123456}
        self.assertNotIn('bid',analyze(self.s,CFG))
    def test_bad_profile_tf(self):
        c={**CFG,'timeframes':['M1','M1']}
        with self.assertRaises(ValueError): analyze(self.s,c)
    def test_bad_profile_required(self):
        c={**CFG,'required_timeframes':['H2']}
        with self.assertRaises(ValueError): analyze(self.s,c)
    def test_missing_snapshot_id(self):
        self.s.pop('snapshot_id')
        with self.assertRaises(ValueError): analyze(self.s,CFG)

class TestFeatures(unittest.TestCase):
    def test_atr_initialization(self):
        a=atr_series(bars(n=20),14)
        self.assertIsNone(a[13]);self.assertGreater(a[14],0)
    def test_efficiency_constant(self):
        b=bars(n=40)
        for x in b: x.update(open=100,close=100,high=100.5,low=99.5)
        self.assertIsNone(efficiency(b,12))
    def test_efficiency_bounds(self):
        e=efficiency(bars(n=40),12)
        self.assertTrue(0<=e<=1)
    def test_sloping_up_positive(self):
        b=bars(n=60,mode='up')
        self.assertGreater(slope_atr(b,12,atr_series(b,14)[-1]),0)
    def test_slope_no_atr(self):self.assertIsNone(slope_atr(bars(n=40),12,None))
    def test_pivots_delayed_two_closed(self):
        b=bars(n=100)
        piv=pivots(b,2,2)
        self.assertGreater(len(piv['highs']),0)
        # availability of pivot always later than pivot creation
        for x in piv['highs']+piv['lows']:
            self.assertGreater(iso(x['available_at']),iso(x['pivot_time']))
    def test_pivot_not_created_on_last_bar(self):
        b=bars(n=100)
        b[-1]['high']=99999;b[-1]['close']=b[-1]['high']-0.1
        self.assertNotEqual(pivots(b,2,2)['highs'][-1]['pivot_time'],b[-1]['bar_open_utc'])
    def test_point_in_time_pivot_no_future(self):
        b=bars(n=40)
        b[-2]['high']=9999;b[-2]['close']=9998
        self.assertNotIn(b[-2]['bar_open_utc'],[z['pivot_time'] for z in pivots(b,2,2)['highs']])

class TestMarketState(unittest.TestCase):
    def setUp(self):self.s=snapshot()
    def test_no_execution_authorization(self):
        r=analyze(self.s,CFG)
        self.assertNotIn('execution_permission',r)
        self.assertNotIn('decision',r)
        self.assertNotIn('entry',r)
    def test_never_live_on_fixture(self):
        r=analyze(self.s,CFG,{'status':'HEALTHY'})
        self.assertEqual(r['execution_context_gate']['status'],'PENDING')
    def test_unverified_health_pending(self):
        r=analyze(self.s,CFG)
        self.assertEqual(r['execution_context_gate']['status'],'PENDING')
    def test_no_macro_inference(self):
        r=analyze(self.s,CFG)
        self.assertTrue(all(z['event_regime']=='UNKNOWN' for z in r['timeframes'].values()))
    def test_no_fake_probabilities(self):
        r=analyze(self.s,CFG)
        self.assertNotIn('p_long',json.dumps(r).lower())
    def test_directional_axes(self):
        r=analyze(self.s,CFG)
        self.assertIn(r['structural_direction'],('BULLISH','BEARISH','UNKNOWN','NEUTRAL'))
        self.assertIn('tactical_direction',r)
        self.assertIn('execution_observation_direction',r)
    def test_no_fabricated_reversal(self):
        self.s=snapshot({'H4':'up','H1':'up','M5':'down','M1':'down'})
        r=analyze(self.s,CFG)
        self.assertNotEqual(r['regime_conflict'],'CONFIRMED_REVERSAL')
    def test_unrequired_health_not_edge(self):
        r=analyze(self.s,CFG,{'status':'HEALTHY'})
        self.assertNotIn('win_rate',r)
    def test_reproducible(self):
        self.assertEqual(analyze(self.s,CFG),analyze(self.s,CFG))
    def test_input_not_modified(self):
        cp=copy.deepcopy(self.s)
        analyze(self.s,CFG)
        self.assertEqual(cp,self.s)
    def test_market_state_fields(self):
        r=analyze(self.s,CFG)
        for k in ('module_id','status','as_of','timeframes','snapshot_id','feature_spec_id','analysis_gate'):
            self.assertIn(k,r)
    def test_last_closed_timestamp(self):
        r=analyze(self.s,CFG)
        self.assertEqual(r['timeframes']['M1']['last_closed_at'],self.s['candles_by_tf']['M1'][-1]['close_confirmed_at'])

class TestHysteresis(unittest.TestCase):
    def test_initial_unknown(self):
        s=RegimeMemory(2)
        self.assertEqual(s.update('M5','TREND_UP','2026-10-08T08:00:00Z')['stable_regime'],'UNKNOWN')
    def test_two_distinct_bars(self):
        s=RegimeMemory(2)
        s.update('M5','TREND_UP','2026-10-08T08:00:00Z')
        self.assertEqual(s.update('M5','TREND_UP','2026-10-08T08:05:00Z')['stable_regime'],'TREND_UP')
    def test_duplicate_bar_not_vote(self):
        s=RegimeMemory(2)
        s.update('M5','TREND_UP','2026-10-08T08:00:00Z')
        self.assertEqual(s.update('M5','TREND_UP','2026-10-08T08:00:00Z')['stable_regime'],'UNKNOWN')
    def test_opposite_requires_confirmation(self):
        s=RegimeMemory(2)
        s.update('M1','TREND_UP','2026-10-08T08:00:00Z')
        s.update('M1','TREND_UP','2026-10-08T08:01:00Z')
        self.assertEqual(s.update('M1','TREND_DOWN','2026-10-08T08:02:00Z')['stable_regime'],'TREND_UP')
        self.assertEqual(s.update('M1','TREND_DOWN','2026-10-08T08:03:00Z')['stable_regime'],'TREND_DOWN')
    def test_corruption_immediate_unknown(self):
        s=RegimeMemory(2)
        s.update('M1','TREND_UP','2026-10-08T08:00:00Z')
        s.update('M1','TREND_UP','2026-10-08T08:01:00Z')
        self.assertEqual(s.update('M1','TREND_UP','2026-10-08T08:02:00Z',False)['stable_regime'],'UNKNOWN')
    def test_out_of_order_not_forward(self):
        s=RegimeMemory(2)
        s.update('M1','TREND_UP','2026-10-08T08:01:00Z')
        self.assertEqual(s.update('M1','TREND_UP','2026-10-08T08:00:00Z')['stable_regime'],'UNKNOWN')
    def test_unknown_resets(self):
        s=RegimeMemory(2)
        s.update('M1','TREND_UP','2026-10-08T08:00:00Z')
        self.assertEqual(s.update('M1','UNKNOWN','2026-10-08T08:01:00Z')['stable_regime'],'UNKNOWN')
    def test_invalid_confirmations(self):
        with self.assertRaises(ValueError):RegimeMemory(0)

if __name__=='__main__':unittest.main(verbosity=2)
