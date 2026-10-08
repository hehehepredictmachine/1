"""New profile tests: fully synthetic, no MT5 account or execution connectivity."""
import copy
import json
import math
import unittest
from pathlib import Path
from datetime import timedelta

import M02I_INDICATOR_ENGINE as e
from M02I_TESTS import fixture, END, iso, MT5PreviewTests
from M02I_MT5_READONLY_PREVIEW import preview_snapshot

P = Path(__file__).resolve().parent
C = json.loads((P / 'M02I_PROFILE_MT5_TIMEFRAMES_v1.1.json').read_text(encoding='utf-8'))


def with_dxy(q):
    q=copy.deepcopy(q)
    bars=copy.deepcopy(q['data_snapshot']['candles_by_tf']['H1'])
    for b in bars:
        b['instrument_id']='DXY'
        b['source_id']='MT5-SYNTHETIC-DXY'
        b['exact_symbol']='DXY'
        b['evidence_id']='DXY:'+b['evidence_id']
        for k in ('open','high','low','close'):
            b[k]=round(b[k]/30,6)
    q['data_snapshot']['auxiliary_candles_by_instrument']={'DXY':{'H1':bars}}
    return q

class PresetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packet=fixture(260)
        cls.result=e.analyze(cls.packet,C)
    def test_profile_ok(self):e.profile_check(C)
    def test_primary_xau_status(self):self.assertEqual(self.result['status'],'PASS')
    def test_profile_version(self):self.assertEqual(self.result['module_version'],'1.1.0-CANDIDATE')
    def test_schema_unchanged(self):self.assertEqual(self.result['schema_version'],'2.0.0')
    def test_prompt_version_unchanged(self):self.assertEqual(self.result['prompt_version'],'4.1.0')
    def test_six_timeframes(self):self.assertEqual(set(self.result['timeframes']),set(C['timeframes']))
    def test_d1_only_requested(self):
        i=self.result['timeframes']['D1']['indicators']
        self.assertIn('ema_50',i);self.assertIn('ema_200',i)
        self.assertIn('adx_wilder_14',i);self.assertIn('atr_14',i)
        self.assertNotIn('rsi_14',i);self.assertNotIn('macd_line',i)
    def test_h4(self):
        i=self.result['timeframes']['H4']['indicators']
        for v in ('ema_20','ema_50','adx_wilder_14','rsi_14','atr_14'):self.assertIn(v,i)
        self.assertNotIn('ema_200',i)
    def test_h1(self):
        i=self.result['timeframes']['H1']['indicators']
        for v in ('ema_20','ema_50','macd_line','macd_signal','adx_wilder_14','atr_14'):self.assertIn(v,i)
        self.assertNotIn('rsi_14',i)
        self.assertEqual(self.result['timeframes']['H1']['interpretation']['macd_signal_ma'],'SMA')
    def test_m15(self):
        i=self.result['timeframes']['M15']['indicators']
        for v in ('ema_20','bb_upper','bb_lower','rsi_14','atr_14','tick_volume_current'):self.assertIn(v,i)
        self.assertNotIn('macd_signal',i)
    def test_m5(self):
        i=self.result['timeframes']['M5']['indicators']
        for v in ('ema_9','ema_21','rsi_9','atr_14','tick_volume_current'):self.assertIn(v,i)
        for v in ('ema_200','rsi_14','macd_line','adx_wilder_14'):self.assertNotIn(v,i)
    def test_m1(self):
        i=self.result['timeframes']['M1']['indicators']
        self.assertIn('ema_9',i);self.assertIn('ema_20',i)
        self.assertIn('atr_14',i);self.assertIn('tick_volume_current',i)
        for v in ('rsi_9','rsi_14','macd_line','bb_upper','ema_200'):self.assertNotIn(v,i)
    def test_no_obv_unrequested(self):
        for t in ('M15','M5','M1'):self.assertNotIn('obv_tick',self.result['timeframes'][t]['indicators'])
    def test_read_only(self):
        self.assertEqual(self.result['execution_permission'],'BLOCKED')
        self.assertFalse(self.result['live_execution_allowed'])
        self.assertIsNone(self.result['submitted_order_id'])
    def test_no_trade_signals(self):
        for v in self.result['timeframes'].values():
            self.assertEqual(v['interpretation']['trade_signal'],'NONE')
            self.assertIsNone(v['interpretation']['win_probability'])
    def test_no_vwap_without_optin(self):self.assertNotIn('session_vwap',self.result['timeframes']['M5']['indicators'])
    def test_no_fractals_without_optin(self):self.assertNotIn('confirmed_fractals',self.result['timeframes']['M15']['interpretation'])
    def test_tick_volume_is_proxy(self):
        self.assertEqual(self.result['timeframes']['M1']['indicators']['tick_volume_current']['evidence_type'],'BROKER_TICK_VOLUME_PROXY')
    def test_rsi_overbought_not_short(self):
        self.assertEqual(self.result['timeframes']['M5']['interpretation']['rsi_context'],'OVERBOUGHT_IN_UPTREND_NOT_AUTOMATIC_SHORT')
    def test_groups_no_double_counting(self):
        self.assertTrue(self.result['timeframes']['H1']['interpretation']['no_double_counting'])
        self.assertEqual(self.result['timeframes']['H1']['interpretation']['evidence_groups'].count('TREND_CONTEXT'),1)
        self.assertEqual(self.result['timeframes']['H1']['interpretation']['evidence_groups'].count('MOMENTUM'),1)
    def test_same_snapshot_deterministic(self):self.assertEqual(self.result,e.analyze(self.packet,C))
    def test_macd_sma_correct(self):
        x=[math.sin(i/8)+0.04*i for i in range(100)]
        a=e.macd(x,12,26,9,'SMA')
        self.assertAlmostEqual(a['signal'][-1],sum(a['line'][-9:])/9)
        b=e.macd(x,12,26,9,'EMA')
        self.assertNotAlmostEqual(a['signal'][-1],b['signal'][-1])
    def test_wrong_macd_signal_method(self):
        with self.assertRaises(ValueError):e.macd(list(range(100)),12,26,9,'WMA')
    def test_exact_required_bars_d1(self):
        a=e.analyze(fixture(220),C)
        self.assertEqual(a['timeframes']['D1']['status'],'PENDING')
        self.assertEqual(a['timeframes']['M1']['status'],'PASS')
    def test_too_short_h1_pends_not_fails(self):
        a=e.analyze(fixture(75),C)
        self.assertEqual(a['status'],'PENDING')
        self.assertEqual(a['timeframes']['H1']['status'],'PENDING')
    def test_forming_bar_no_change(self):
        q=copy.deepcopy(self.packet)
        b=copy.deepcopy(q['data_snapshot']['candles_by_tf']['M1'][-1])
        b['bar_state']='FORMING';b['close']=99999;b['high']=100000;b['low']=99998
        q['data_snapshot']['candles_by_tf']['M1'].append(b)
        self.assertEqual(self.result['timeframes']['M1']['indicators'],e.analyze(q,C)['timeframes']['M1']['indicators'])
    def test_missing_market_state_pending(self):
        q=copy.deepcopy(self.packet);q.pop('market_state')
        a=e.analyze(q,C)
        self.assertEqual(a['status'],'PENDING')
        self.assertEqual(a['timeframes']['H1']['interpretation']['market_direction'],'UNKNOWN')
    def test_optional_dxy_absent_does_not_block(self):
        self.assertEqual(self.result['auxiliary_instruments']['DXY']['status'],'UNAVAILABLE')
        self.assertEqual(self.result['status'],'PASS')
    def test_dxy_present_not_execution_source(self):
        a=e.analyze(with_dxy(self.packet),C)
        d=a['auxiliary_instruments']['DXY']
        self.assertEqual(d['status'],'PENDING')
        self.assertFalse(d['execution_quote_allowed'])
        self.assertEqual(a['status'],'PASS')
        self.assertIn('ema_50',d['indicators']);self.assertIn('ema_200',d['indicators'])
        self.assertIn('rsi_14',d['indicators']);self.assertNotIn('atr_14',d['indicators'])
        self.assertEqual(d['interpretation']['market_direction'],'UNKNOWN')
    def test_dxy_tampered_fails_its_scope_only(self):
        q=with_dxy(self.packet)
        q['data_snapshot']['auxiliary_candles_by_instrument']['DXY']['H1'][-1]['source_id']='TV-NOT-MT5'
        a=e.analyze(q,C)
        self.assertEqual(a['auxiliary_instruments']['DXY']['status'],'FAIL')
        self.assertEqual(a['status'],'PASS')
    def test_dxy_future_excluded(self):
        q=with_dxy(self.packet)
        b=copy.deepcopy(q['data_snapshot']['auxiliary_candles_by_instrument']['DXY']['H1'][-1])
        b['bar_open_utc']=iso(END+timedelta(hours=1));b['close_confirmed_at']=iso(END+timedelta(hours=2))
        b['available_at']=iso(END+timedelta(hours=2));b['evidence_id']='DXY-FUTURE'
        q['data_snapshot']['auxiliary_candles_by_instrument']['DXY']['H1'].append(b)
        d=e.analyze(q,C)['auxiliary_instruments']['DXY']
        self.assertEqual(d['status'],'PENDING');self.assertIn('FUTURE_BAR_EXCLUDED',d['reason_codes'])
    def test_profile_bad_tf_missing(self):
        c=copy.deepcopy(C);c['timeframe_profiles'].pop('M1')
        with self.assertRaisesRegex(ValueError,'TIMEFRAME_PROFILE_MISSING'):e.profile_check(c)
    def test_profile_bad_ema(self):
        c=copy.deepcopy(C);c['timeframe_profiles']['M5']['enabled']['ema']=[21,9]
        with self.assertRaisesRegex(ValueError,'INVALID_EMA_PERIODS'):e.profile_check(c)
    def test_profile_bad_macd(self):
        c=copy.deepcopy(C);c['timeframe_profiles']['H1']['enabled']['macd']['signal_ma']='EMA'
        with self.assertRaisesRegex(ValueError,'INVALID_MACD_PROFILE'):e.profile_check(c)
    def test_profile_low_warmup(self):
        c=copy.deepcopy(C);c['timeframe_profiles']['D1']['min_closed_bars']=200
        with self.assertRaisesRegex(ValueError,'TF_WARMUP_TOO_SHORT'):e.profile_check(c)
    def test_profile_reject_unlisted_indicator(self):
        c=copy.deepcopy(C);c['timeframe_profiles']['M1']['enabled']['supertrend']=10
        with self.assertRaisesRegex(ValueError,'INVALID_TF_INDICATORS'):e.profile_check(c)
    def test_profile_reject_dxy_required(self):
        c=copy.deepcopy(C);c['auxiliary_instruments']['DXY']['required_for_xau_direction']=True
        with self.assertRaisesRegex(ValueError,'INVALID_DXY_POLICY'):e.profile_check(c)
    def test_optional_fractals(self):
        c=copy.deepcopy(C);c['timeframe_profiles']['M15']['enabled']['fractals']=True
        a=e.analyze(self.packet,c)
        self.assertIn('confirmed_fractals',a['timeframes']['M15']['interpretation'])
    def test_optional_vwap_without_session_unavailable(self):
        c=copy.deepcopy(C);c['timeframe_profiles']['M5']['enabled']['session_vwap']=True
        a=e.analyze(self.packet,c)
        self.assertIsNone(a['timeframes']['M5']['indicators']['session_vwap']['value'])
    def test_json_serializable(self):json.dumps(self.result,allow_nan=False)
    def test_preview_default_no_dxy(self):
        mt5=MT5PreviewTests().fake_mt5()
        p=preview_snapshot(mt5,count=230,now=END)
        self.assertEqual(p['auxiliary_candles_by_instrument'],{})
        self.assertEqual(e.analyze({'data_snapshot':p},C)['status'],'PENDING')
    def test_preview_optional_dxy(self):
        mt5=MT5PreviewTests().fake_mt5()
        p=preview_snapshot(mt5,count=230,now=END,dxy_symbol='DXY')
        self.assertEqual(len(p['auxiliary_candles_by_instrument']['DXY']['H1']),230)
        self.assertEqual(e.analyze({'data_snapshot':p},C)['auxiliary_instruments']['DXY']['status'],'PENDING')
    def test_preview_bad_dxy_name(self):
        with self.assertRaises(ValueError):preview_snapshot(MT5PreviewTests().fake_mt5(),count=230,now=END,dxy_symbol='\n')

if __name__=='__main__':unittest.main(verbosity=2)
