"""Offline deterministic tests for M02I; all broker records below are synthetic."""
from __future__ import annotations
import copy
import json
import math
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

import M02I_INDICATOR_ENGINE as e

HERE=Path(__file__).resolve().parent
CFG=json.loads((HERE/'M02I_PROFILE.example.json').read_text(encoding='utf-8'))
END=datetime(2026,10,8,12,0,tzinfo=timezone.utc)
STEPS={'M1':1,'M5':5,'M15':15,'H1':60,'H4':240,'D1':1440}

def iso(d):return d.isoformat().replace('+00:00','Z')

def fixture(n=240,trend='UP',tf_list=None):
    tf_list=tf_list or CFG['timeframes']
    candles={}
    for tf in tf_list:
        dt=timedelta(minutes=STEPS[tf]);bars=[]
        for i in range(n):
            op=END-(n-i)*dt;cl=op+dt
            base=(2900+0.55*i if trend=='UP' else 3200-0.55*i if trend=='DOWN' else 3000+2*math.sin(i/3))
            # valid stable candle w small wicks, synthetic fixed ticks
            bars.append({'instrument_id':'XAUUSD','source_id':'MT5-SYNTHETIC',
                         'timeframe':tf,'bar_state':'CLOSED','bar_open_utc':iso(op),
                         'close_confirmed_at':iso(cl),'available_at':iso(cl),
                         'price_basis':'BID','open':round(base-0.2,5),
                         'high':round(base+0.8,5),'low':round(base-0.8,5),'close':round(base,5),
                         'tick_volume':100+i%8,'real_volume':0,
                         'evidence_id':tf+'-'+str(i),'revision':0})
        candles[tf]=bars
    snap={'_fixture_only':True,'analysis_id':'OFFLINE-XAU-1','snapshot_id':'SNAP-001',
          'as_of':iso(END),'data_source_policy':e.POLICY,
          'visual_capture_enabled':False,'candles_by_tf':candles,
          'data_gates':[{'gate_id':'BROKER_BAR_INTEGRITY','required_for':['ANALYSIS','DIRECTION'],
                         'status':'PASS','evidence_ids':['SYNTH-DATA']}],
          'account_profile':'ZERO_SPREAD_DECLARED'}
    ms={'analysis_id':snap['analysis_id'],'snapshot_id':snap['snapshot_id'],'as_of':snap['as_of'],
        'analysis_gate':{'status':'PASS'},'timeframes':{
            tf:{'status':'PASS','structure_regime':'TREND_UP' if trend=='UP' else 'TREND_DOWN' if trend=='DOWN' else 'RANGE',
                'last_closed_at':candles[tf][-1]['close_confirmed_at']}
            for tf in tf_list}}
    return {'data_snapshot':snap,'market_state':ms}

class MathTests(unittest.TestCase):
    def test_ema_constant(self):self.assertAlmostEqual(e.ema([2.0]*300,20)[-1],2)
    def test_ema_seed(self):self.assertAlmostEqual(e.ema([1.,2.,3.],3)[-1],2)
    def test_ema_warmup(self):self.assertEqual(e.ema([1.,2.],3),[None,None])
    def test_rsi_up(self):self.assertAlmostEqual(e.rsi(list(range(30)),14)[-1],100)
    def test_rsi_down(self):self.assertAlmostEqual(e.rsi(list(range(30,0,-1)),14)[-1],0)
    def test_rsi_flat(self):self.assertAlmostEqual(e.rsi([10.]*30,14)[-1],50)
    def test_rsi_no_lookahead(self):
        x=[float(i) for i in range(20)]
        self.assertEqual(e.rsi(x,14),e.rsi(x+[10000.],14)[:-1])
    def test_atr_constant(self):
        b=[{'high':11,'low':9,'close':10} for i in range(30)]
        self.assertAlmostEqual(e.atr(b,14)[-1],2)
    def test_atr_insufficient(self):
        b=[{'high':11,'low':9,'close':10} for i in range(14)]
        self.assertIsNone(e.atr(b,14)[-1])
    def test_adx_up_strong(self):
        b=[{'high':11+i,'low':9+i,'close':10+i} for i in range(70)]
        self.assertAlmostEqual(e.adx(b,14)['adx'][-1],100)
    def test_adx_warmup(self):
        b=[{'high':11+i,'low':9+i,'close':10+i} for i in range(22)]
        self.assertIsNone(e.adx(b,14)['adx'][-1])
    def test_macd_flat(self):
        m=e.macd([5.]*100,12,26,9)
        self.assertAlmostEqual(m['histogram'][-1],0)
    def test_macd_line_no_future(self):
        x=[float(i) for i in range(40)]
        self.assertEqual(e.macd(x,12,26,9)['line'],e.macd(x+[900.],12,26,9)['line'][:-1])
    def test_bb_flat(self):self.assertIsNone(e.bb([1.]*50,20,2)['percent_b'])
    def test_bb_values(self):
        x=e.bb([float(i) for i in range(1,21)],20,2)
        self.assertAlmostEqual(x['mid'],10.5)
        self.assertGreater(x['upper'],x['mid'])
    def test_obv_up(self):
        b=[{'close':float(i),'tick_volume':10} for i in range(1,11)]
        self.assertEqual(e.obv(b),90)
    def test_obv_no_volume(self):self.assertIsNone(e.obv([{'close':1}]))
    def test_obv_all_zero_unavailable(self):self.assertIsNone(e.obv([{'close':1,'tick_volume':0}]))
    def test_value_null_not_zero(self):self.assertIsNone(e.value(None)['value'])
    def test_value_nan_rejected(self):self.assertIsNone(e.value(float('nan'))['value'])
    def test_utc_naive_rejected(self):
        with self.assertRaises(ValueError):e.utc('2026-10-08T10:00:00')
    def test_utc_offset_conversion(self):self.assertEqual(e.utc('2026-10-08T14:00:00+02:00'),END)
    def test_profile_invalid_period(self):
        c=copy.deepcopy(CFG);c['ema_fast']=-2
        with self.assertRaises(ValueError):e.profile_check(c)
    def test_profile_invalid_order(self):
        c=copy.deepcopy(CFG);c['ema_mid']=5
        with self.assertRaises(ValueError):e.profile_check(c)
    def test_profile_invalid_tf(self):
        c=copy.deepcopy(CFG);c['timeframes'].append('M8')
        with self.assertRaises(ValueError):e.profile_check(c)

class PipelineTests(unittest.TestCase):
    def setUp(self):self.p=fixture()
    def test_full_pipeline(self):
        o=e.analyze(self.p,CFG)
        self.assertEqual(o['status'],'PASS');self.assertEqual(len(o['timeframes']),6)
    def test_schema_version_preserved(self):self.assertEqual(e.analyze(self.p,CFG)['schema_version'],'2.0.0')
    def test_prompt_version_preserved(self):self.assertEqual(e.analyze(self.p,CFG)['prompt_version'],'4.1.0')
    def test_no_orders(self):
        o=e.analyze(self.p,CFG)
        self.assertEqual(o['execution_permission'],'BLOCKED');self.assertFalse(o['live_execution_allowed'])
        self.assertIsNone(o['submitted_order_id'])
    def test_no_trade_signal(self):self.assertEqual(e.analyze(self.p,CFG)['timeframes']['M5']['interpretation']['trade_signal'],'NONE')
    def test_no_probability(self):self.assertIsNone(e.analyze(self.p,CFG)['timeframes']['M5']['interpretation']['win_probability'])
    def test_wilder_rsi_available(self):self.assertGreater(e.analyze(self.p,CFG)['timeframes']['M5']['indicators']['rsi']['value'],70)
    def test_ema200_available(self):self.assertIsNotNone(e.analyze(self.p,CFG)['timeframes']['M5']['indicators']['ema_slow']['value'])
    def test_adx_available(self):self.assertIsNotNone(e.analyze(self.p,CFG)['timeframes']['H1']['indicators']['adx']['value'])
    def test_adx_directional_context(self):self.assertEqual(e.analyze(self.p,CFG)['timeframes']['H1']['interpretation']['di_direction'],'UP')
    def test_atr_volatility_ratio_available(self):self.assertIsNotNone(e.analyze(self.p,CFG)['timeframes']['M5']['indicators']['atr_ratio_to_previous_median']['value'])
    def test_price_distance_atr_units(self):self.assertGreater(e.analyze(self.p,CFG)['timeframes']['M5']['indicators']['ema_fast_distance_atr']['value'],0)
    def test_bollinger_context_is_non_signal(self):self.assertIn(e.analyze(self.p,CFG)['timeframes']['M5']['interpretation']['bollinger_context'],('INSIDE_BANDS','ABOVE_UPPER_BAND_NOT_AUTOMATIC_BUY','BELOW_LOWER_BAND_NOT_AUTOMATIC_SELL'))
    def test_macd_cross_context_present(self):self.assertIn(e.analyze(self.p,CFG)['timeframes']['M5']['interpretation']['macd_histogram_cross'],('NO_NEW_CROSS','MACD_POSITIVE_CROSS_CLOSED_BAR','MACD_NEGATIVE_CROSS_CLOSED_BAR'))
    def test_regime_bias_not_entry(self):self.assertEqual(e.analyze(self.p,CFG)['timeframes']['H4']['interpretation']['market_direction'],'BULLISH')
    def test_overbought_not_short(self):self.assertEqual(e.analyze(self.p,CFG)['timeframes']['M5']['interpretation']['rsi_context'],'OVERBOUGHT_IN_UPTREND_NOT_AUTOMATIC_SHORT')
    def test_bearish_over_sold_not_long(self):
        o=e.analyze(fixture(trend='DOWN'),CFG)
        self.assertEqual(o['timeframes']['M5']['interpretation']['rsi_context'],'OVERSOLD_IN_DOWNTREND_NOT_AUTOMATIC_LONG')
    def test_no_cvd_without_signed_trades(self):self.assertIsNone(e.analyze(self.p,CFG)['timeframes']['M5']['indicators']['cvd']['value'])
    def test_obv_is_tick_proxy(self):self.assertEqual(e.analyze(self.p,CFG)['timeframes']['M5']['indicators']['obv_tick']['evidence_type'],'BROKER_TICK_VOLUME_PROXY')
    def test_no_vwap_without_session(self):self.assertIsNone(e.analyze(self.p,CFG)['timeframes']['M5']['indicators']['session_vwap']['value'])
    def test_realvolume_zero_no_vwap(self):
        q=copy.deepcopy(self.p)
        q['session_context']={'source_module':'M04','status':'PASS','snapshot_id':'SNAP-001','as_of':iso(END),
                              'session_data_complete':True,'timeframe':'M5','session_anchor_utc':iso(END-timedelta(minutes=10))}
        self.assertIsNone(e.analyze(q,CFG)['timeframes']['M5']['indicators']['session_vwap']['value'])
    def test_tick_proxy_vwap_explicit(self):
        q=copy.deepcopy(self.p);c=copy.deepcopy(CFG);c['allow_tick_vwap_proxy']=True
        q['session_context']={'source_module':'M04','status':'PASS','snapshot_id':'SNAP-001','as_of':iso(END),
                              'session_data_complete':True,'timeframe':'M5','session_anchor_utc':iso(END-timedelta(minutes=10))}
        v=e.analyze(q,c)['timeframes']['M5']['indicators']['session_vwap']
        self.assertEqual(v['evidence_type'],'TICK_VOLUME_PROXY_NOT_EXCHANGE_VWAP');self.assertIsNotNone(v['value'])
    def test_verified_volume_vwap(self):
        q=copy.deepcopy(self.p)
        for b in q['data_snapshot']['candles_by_tf']['M5'][-2:]:b['real_volume']=50
        q['session_context']={'source_module':'M04','status':'PASS','snapshot_id':'SNAP-001','as_of':iso(END),
                              'session_data_complete':True,'timeframe':'M5','session_anchor_utc':iso(END-timedelta(minutes=10))}
        v=e.analyze(q,CFG)['timeframes']['M5']['indicators']['session_vwap']
        self.assertEqual(v['evidence_type'],'BROKER_REAL_VOLUME')
    def test_unverified_session_block(self):
        q=copy.deepcopy(self.p);c=copy.deepcopy(CFG);c['allow_tick_vwap_proxy']=True
        q['session_context']={'source_module':'OTHER','status':'PASS','snapshot_id':'SNAP-001','as_of':iso(END),
                              'session_data_complete':True,'timeframe':'M5','session_anchor_utc':iso(END-timedelta(minutes=10))}
        self.assertIsNone(e.analyze(q,c)['timeframes']['M5']['indicators']['session_vwap']['value'])
    def test_session_snapshot_mismatch(self):
        q=copy.deepcopy(self.p);c=copy.deepcopy(CFG);c['allow_tick_vwap_proxy']=True
        q['session_context']={'source_module':'M04','status':'PASS','snapshot_id':'OTHER','as_of':iso(END),
                              'session_data_complete':True,'timeframe':'M5','session_anchor_utc':iso(END-timedelta(minutes=10))}
        self.assertIsNone(e.analyze(q,c)['timeframes']['M5']['indicators']['session_vwap']['value'])
    def test_future_bar_excluded(self):
        q=copy.deepcopy(self.p)
        b=copy.deepcopy(q['data_snapshot']['candles_by_tf']['M5'][-1]);b['bar_open_utc']=iso(END+timedelta(minutes=1))
        b['close_confirmed_at']=iso(END+timedelta(minutes=6));b['available_at']=iso(END+timedelta(minutes=6))
        b['evidence_id']='FUTURE';b['close']=10000;b['high']=10001;b['low']=9999;b['open']=10000
        q['data_snapshot']['candles_by_tf']['M5'].append(b)
        o=e.analyze(q,CFG)
        self.assertEqual(o['status'],'PASS_WITH_LIMITATIONS')
        self.assertEqual(o['timeframes']['M5']['indicators']['ema_fast']['value'],e.analyze(self.p,CFG)['timeframes']['M5']['indicators']['ema_fast']['value'])
    def test_forming_bar_ignored(self):
        q=copy.deepcopy(self.p);b=copy.deepcopy(q['data_snapshot']['candles_by_tf']['M5'][-1]);b['bar_state']='FORMING'
        b['close']=10000;b['high']=10001;b['low']=9999;b['open']=10000
        q['data_snapshot']['candles_by_tf']['M5'].append(b)
        self.assertEqual(e.analyze(self.p,CFG)['timeframes']['M5']['indicators'],e.analyze(q,CFG)['timeframes']['M5']['indicators'])
    def test_revision_higher_replaces(self):
        q=copy.deepcopy(self.p);b=copy.deepcopy(q['data_snapshot']['candles_by_tf']['M5'][-1]);b['revision']=1;b['close']+=0.1
        q['data_snapshot']['candles_by_tf']['M5'].append(b)
        self.assertEqual(e.analyze(q,CFG)['status'],'PASS')
    def test_same_rev_conflict(self):
        q=copy.deepcopy(self.p);b=copy.deepcopy(q['data_snapshot']['candles_by_tf']['M5'][-1]);b['close']+=0.1
        q['data_snapshot']['candles_by_tf']['M5'].append(b)
        self.assertEqual(e.analyze(q,CFG)['status'],'FAIL')
    def test_invalid_high_low(self):
        q=copy.deepcopy(self.p);q['data_snapshot']['candles_by_tf']['M5'][-1]['high']=1
        self.assertEqual(e.analyze(q,CFG)['status'],'FAIL')
    def test_wrong_price_basis(self):
        q=copy.deepcopy(self.p);q['data_snapshot']['candles_by_tf']['M5'][-1]['price_basis']='ASK'
        self.assertEqual(e.analyze(q,CFG)['status'],'FAIL')
    def test_negative_tick_volume_fail(self):
        q=copy.deepcopy(self.p);q['data_snapshot']['candles_by_tf']['M5'][-1]['tick_volume']=-1
        self.assertEqual(e.analyze(q,CFG)['status'],'FAIL')
    def test_tv_bars_fail(self):
        q=copy.deepcopy(self.p);q['data_snapshot']['candles_by_tf']['M5'][-1]['source_id']='TRADINGVIEW'
        self.assertEqual(e.analyze(q,CFG)['status'],'FAIL')
    def test_missing_evidence_fail(self):
        q=copy.deepcopy(self.p);q['data_snapshot']['candles_by_tf']['M5'][-1].pop('evidence_id')
        self.assertEqual(e.analyze(q,CFG)['status'],'FAIL')
    def test_duplicate_ids_fail(self):
        q=copy.deepcopy(self.p);q['data_snapshot']['candles_by_tf']['M5'][-1]['evidence_id']='M5-2'
        self.assertEqual(e.analyze(q,CFG)['status'],'FAIL')
    def test_m02_wrong_snapshot(self):
        q=copy.deepcopy(self.p);q['market_state']['snapshot_id']='wrong'
        self.assertEqual(e.analyze(q,CFG)['status'],'FAIL')
    def test_m02_bad_gate(self):
        q=copy.deepcopy(self.p);q['market_state']['analysis_gate']['status']='FAIL'
        self.assertEqual(e.analyze(q,CFG)['status'],'FAIL')
    def test_m02_tf_lag_blocks(self):
        q=copy.deepcopy(self.p);q['market_state']['timeframes']['M5']['last_closed_at']='2026-10-07T10:00:00Z'
        o=e.analyze(q,CFG)
        self.assertEqual(o['status'],'PENDING');self.assertIn('M02_TF_SNAPSHOT_OUT_OF_SYNC',o['timeframes']['M5']['reason_codes'])
    def test_m01_bad_gate(self):
        q=copy.deepcopy(self.p);q['data_snapshot']['data_gates'][0]['status']='FAIL'
        self.assertEqual(e.analyze(q,CFG)['status'],'FAIL')
    def test_m01_pending_gate_not_corruption(self):
        q=copy.deepcopy(self.p);q['data_snapshot']['data_gates'][0]['status']='PENDING'
        self.assertEqual(e.analyze(q,CFG)['status'],'PENDING')
    def test_missing_m01_gates(self):
        q=copy.deepcopy(self.p);q['data_snapshot'].pop('data_gates')
        self.assertEqual(e.analyze(q,CFG)['status'],'PENDING')
    def test_missing_m02_context(self):
        q=copy.deepcopy(self.p);q.pop('market_state')
        self.assertEqual(e.analyze(q,CFG)['status'],'PENDING')
        self.assertEqual(e.analyze(q,CFG)['timeframes']['H1']['interpretation']['market_direction'],'UNKNOWN')
    def test_source_policy_invalid(self):
        q=copy.deepcopy(self.p);q['data_snapshot']['data_source_policy']='TV_ONLY'
        self.assertEqual(e.analyze(q,CFG)['status'],'FAIL')
    def test_screenshots_prohibited(self):
        q=copy.deepcopy(self.p);q['data_snapshot']['visual_capture_enabled']=True
        self.assertEqual(e.analyze(q,CFG)['status'],'FAIL')
    def test_insufficient_bars_null200(self):
        q=fixture(n=60);o=e.analyze(q,CFG)
        self.assertEqual(o['status'],'PENDING')
        self.assertIsNone(o['timeframes']['M5']['indicators']['ema_slow']['value'])
    def test_same_snapshot_repeated_deterministic(self):
        self.assertEqual(e.analyze(self.p,CFG),e.analyze(self.p,CFG))
    def test_unavailable_probability(self):self.assertEqual(e.analyze(self.p,CFG)['probability_status'],'NOT_AVAILABLE')
    def test_no_account_trade_cost_claim(self):
        self.assertIn('ZERO_SPREAD_DECLARED',e.analyze(self.p,CFG)['account_profile'])
    def test_missing_candles_all_tf(self):
        q=copy.deepcopy(self.p);q['data_snapshot']['candles_by_tf']={}
        self.assertEqual(e.analyze(q,CFG)['status'],'PENDING')
    def test_valid_complete_output_json(self):json.dumps(e.analyze(self.p,CFG),allow_nan=False)
    def test_duplicate_tf_profile_rejected(self):
        c=copy.deepcopy(CFG);c['timeframes'].append('M5')
        with self.assertRaises(ValueError):e.analyze(self.p,c)

class DivergenceTests(unittest.TestCase):
    def test_missing_pivots_no_divergence(self):
        p=fixture(n=60);bars=p['data_snapshot']['candles_by_tf']['M5']
        self.assertEqual(e.pivots_divergence(bars,e.rsi([b['close'] for b in bars],14),2,2)['type'],'NONE')
    def test_confirmed_by_future_right_bars(self):
        p=fixture(n=20,trend='RANGE');bars=p['data_snapshot']['candles_by_tf']['M5']
        rs=[50.]*20
        # Assert if detected, confirmation is not before second pivot observation time.
        r=e.pivots_divergence(bars,rs,2,2)
        if r['confirmed_by'] is not None:
            self.assertGreaterEqual(e.utc(r['confirmed_by']),e.utc(r['pivot_times'][-1]))

class ActualM02CompatibilityTests(unittest.TestCase):
    def test_existing_m02_processes_snapshot_and_m02i_accepts_result(self):
        import sys
        sys.path.insert(0,str(HERE/'compatibility'))
        import M02_REFERENCE_ENGINE as m02
        p=fixture(n=240)
        cfg=json.loads((HERE/'compatibility'/'M02_PROFILE.example.json').read_text(encoding='utf-8'))
        p['market_state']=m02.analyze(p['data_snapshot'],cfg)
        self.assertEqual(p['market_state']['status'],'PASS')
        self.assertEqual(e.analyze(p,CFG)['status'],'PASS')
    def test_original_m01_fixture_lacks_history_and_is_not_promoted(self):
        import sys
        sys.path.insert(0,str(HERE/'compatibility'))
        import M02_REFERENCE_ENGINE as m02
        s=json.loads((HERE/'compatibility'/'M01_SYNTHETIC_EXAMPLE.json').read_text(encoding='utf-8'))
        snap=s.get('data_snapshot',s)
        cfg=json.loads((HERE/'compatibility'/'M02_PROFILE.example.json').read_text(encoding='utf-8'))
        state=m02.analyze(snap,cfg)
        o=e.analyze({'data_snapshot':snap,'market_state':state},CFG)
        self.assertEqual(o['status'],'PENDING')
        self.assertIsNone(o['timeframes']['M1']['indicators']['ema_slow']['value'])

class MT5PreviewTests(unittest.TestCase):
    def fake_mt5(self):
        # a deliberately bare object without ANY order methods: read-only contract
        class Fake:
            TIMEFRAME_M1='M1';TIMEFRAME_M5='M5';TIMEFRAME_M15='M15'
            TIMEFRAME_H1='H1';TIMEFRAME_H4='H4';TIMEFRAME_D1='D1'
            def copy_rates_from_pos(self,symbol,tf,start,count):
                step=timedelta(minutes=STEPS[tf])
                arr=[]
                for i in range(count):
                    start=END-(count-1-i)*step
                    arr.append({'time':int(start.timestamp()),'open':3000+i*.2,'high':3001+i*.2,
                                'low':2999+i*.2,'close':3000+i*.2,'tick_volume':20,'real_volume':0})
                return arr
        return Fake()
    def test_readonly_preview_excludes_forming_bar(self):
        from M02I_MT5_READONLY_PREVIEW import preview_snapshot
        p=preview_snapshot(self.fake_mt5(),now=END,count=220)
        self.assertEqual(len(p['candles_by_tf']['M5']),220)
        self.assertEqual(e.utc(p['candles_by_tf']['M5'][-1]['close_confirmed_at']),END)
        self.assertTrue(all(b['bar_state']=='CLOSED' for b in p['candles_by_tf']['M5']))
    def test_preview_gates_pending(self):
        from M02I_MT5_READONLY_PREVIEW import preview_snapshot
        p=preview_snapshot(self.fake_mt5(),now=END,count=220)
        self.assertEqual(p['data_gates'][0]['status'],'PENDING')
        self.assertEqual(e.analyze({'data_snapshot':p},CFG)['status'],'PENDING')
    def test_preview_cannot_claim_direction(self):
        from M02I_MT5_READONLY_PREVIEW import preview_snapshot
        p=preview_snapshot(self.fake_mt5(),now=END,count=220)
        r=e.analyze({'data_snapshot':p},CFG)
        self.assertEqual(r['timeframes']['M5']['interpretation']['market_direction'],'UNKNOWN')
    def test_preview_bad_symbol(self):
        from M02I_MT5_READONLY_PREVIEW import preview_snapshot
        with self.assertRaises(ValueError):preview_snapshot(self.fake_mt5(),symbol='',now=END,count=220)
    def test_preview_too_little_history(self):
        from M02I_MT5_READONLY_PREVIEW import preview_snapshot
        with self.assertRaises(ValueError):preview_snapshot(self.fake_mt5(),now=END,count=20)

if __name__=='__main__':unittest.main(verbosity=2)
