"""Deterministic offline integration tests. Mocked MT5, no broker/network, no orders."""
import copy
from datetime import datetime, timezone, timedelta
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
import numpy as np

from M02I_M01_M02_LIVE_BRIDGE import (IntegratedReadOnlyMonitor, atomic_json,
    validate_configuration, DEFAULT_M02, DEFAULT_M02I, TF_NAMES)

BASE = Path(__file__).resolve().parent
CFG = json.loads((BASE / 'BRIDGE_SETTINGS.example.json').read_text())
M02 = json.loads(DEFAULT_M02.read_text())
M02I = json.loads(DEFAULT_M02I.read_text())
N = {'M1': 60, 'M5': 300, 'M15': 900, 'H1': 3600, 'H4': 14400, 'D1': 86400}
DTYPE = [('time','i8'),('open','f8'),('high','f8'),('low','f8'),('close','f8'),
         ('tick_volume','i8'),('real_volume','f8')]

class FakeMT5:
    TIMEFRAME_M1, TIMEFRAME_M5, TIMEFRAME_M15, TIMEFRAME_H1, TIMEFRAME_H4, TIMEFRAME_D1 = range(6)
    _tf = dict(zip(('M1','M5','M15','H1','H4','D1'),range(6)))
    def __init__(self, now):
        self.now = now
        self.connected = True
        self.init_ok = True
        self.available = {'XAUUSD', 'USDX'}
        self.selected = []
        self.errors = []
        self.shutdowns = 0
        self.reads = 0
        self.malformed = False
        self.short_history = False
        self.quote_ok = True
        self.current_offset = 0
        self.rows = {}
        self._build()

    def _build(self):
        current = int(self.now.timestamp())
        for sym in ('XAUUSD', 'USDX'):
            for tf, frame in self._tf.items():
                sec = N[tf]
                last_open = current // sec * sec
                out = []
                for i in range(281):
                    op = last_open - (280-i)*sec
                    val = (2750.0 if sym=='XAUUSD' else 105.0) + (i-280)*0.04 + ((i%11)-5)*0.002
                    lo,hi = val-0.16,val+0.20
                    out.append((op,val,hi,lo,val+0.05,60+i%5,0.0))
                self.rows[(sym,tf)] = np.array(out,dtype=DTYPE)

    def initialize(self,*args):
        return self.init_ok
    def shutdown(self):
        self.shutdowns += 1
    def last_error(self):
        return (-1,'mock unavailable')
    def terminal_info(self):
        return SimpleNamespace(connected=self.connected)
    def symbol_info(self,sym):
        return SimpleNamespace(visible=True) if sym in self.available else None
    def symbol_select(self,sym,visible):
        self.selected.append(sym)
        return sym in self.available
    def symbol_info_tick(self,sym):
        if not self.quote_ok:
            return None
        t=int(self.now.timestamp()*1000)
        return SimpleNamespace(bid=2750.10,ask=2750.10,time_msc=t,time=int(t/1000),flags=0)
    def copy_rates_from_pos(self,sym,tf,start,count):
        self.reads += 1
        name=next((k for k,v in self._tf.items() if v==tf),None)
        if not name or sym not in self.available:
            return None
        arr=self.rows[(sym,name)]
        if self.malformed and name=='M5' and sym=='XAUUSD':
            arr=arr.copy();arr[-2]['high']=arr[-2]['low']-1
        if self.short_history:
            arr=arr[-16:]
        return arr[-count:]
    def roll(self,tf,sym='XAUUSD'):
        arr=self.rows[(sym,tf)]
        nxt=arr[-1].copy()
        nxt['time']=int(arr[-1]['time'])+N[tf]
        nxt['open']=float(arr[-1]['close'])
        nxt['close']=float(nxt['open'])+0.05
        nxt['high']=float(nxt['close'])+0.1
        nxt['low']=float(nxt['open'])-0.1
        self.rows[(sym,tf)] = np.concatenate([arr,np.array([tuple(nxt)],dtype=DTYPE)])
        self.now=datetime.fromtimestamp(int(nxt['time'])+5, timezone.utc)


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now=datetime(2026,10,8,14,30,tzinfo=timezone.utc)
        self.mt5=FakeMT5(self.now)
        self.file=Path(self.tmp.name)/'monitor.json'
        self.bridge=IntegratedReadOnlyMonitor(self.mt5,'XAUUSD',copy.deepcopy(CFG),
                       copy.deepcopy(M02),copy.deepcopy(M02I),self.file,
                       clock=lambda:self.mt5.now,session_id='OFFLINE-TEST')

    def test_01_start_and_write(self):
        self.assertTrue(self.bridge.start())
        self.assertTrue(self.file.exists())
        self.assertEqual(json.loads(self.file.read_text())['connection_status'],'CONNECTED')

    def test_02_m01_m02_m02i_same_snapshot(self):
        self.bridge.start()
        self.assertEqual(self.bridge.market['snapshot_id'],self.bridge.indicators['snapshot_id'])
        self.assertEqual(self.bridge.snapshot['as_of'],self.bridge.market['as_of'])
        self.assertEqual(self.bridge.market['analysis_id'],self.bridge.indicators['analysis_id'])

    def test_03_all_timeframes(self):
        self.bridge.start()
        self.assertEqual(set(self.bridge.indicators['timeframes']),set(TF_NAMES))
        self.assertEqual(set(self.bridge.market['timeframes']),set(TF_NAMES))

    def test_04_history_warmup_ema200(self):
        self.bridge.start()
        d=self.bridge.indicators['timeframes']['D1']
        self.assertGreaterEqual(d['closed_bars'],230)
        self.assertIsNotNone(d['indicators']['ema_200']['value'])

    def test_05_profile_specific_m1(self):
        self.bridge.start()
        d=self.bridge.indicators['timeframes']['M1']['indicators']
        self.assertIn('ema_9',d)
        self.assertNotIn('ema_200',d)
        self.assertNotIn('macd',d)

    def test_06_end_to_end_pending_not_fake_pass(self):
        self.bridge.start()
        self.assertEqual(self.bridge.market['status'],'PENDING')
        self.assertEqual(self.bridge.indicators['status'],'PENDING')
        self.assertEqual(self.bridge.snapshot['data_gates'][0]['status'],'PENDING')
        self.assertEqual(self.bridge.indicators['execution_permission'],'BLOCKED')

    def test_07_zero_spread_not_zero_cost(self):
        self.bridge.start(); r=self.bridge.last_published
        self.assertEqual(r['quote']['spread_abs'],0)
        self.assertFalse(r['real_broker_costs_verified'])
        self.assertIn('UNVERIFIED',r['account_profile'])

    def test_08_quote_change_does_not_recompute(self):
        self.bridge.start(); seq=self.bridge.sequence
        self.mt5.now += timedelta(seconds=1)
        self.bridge.poll()
        self.assertEqual(self.bridge.sequence,seq)
        self.assertIsNotNone(self.bridge.last_published['quote'])

    def test_09_new_closed_bar_recomputes(self):
        self.bridge.start(); old=self.bridge.snapshot['snapshot_id']
        self.mt5.roll('M1');self.bridge.poll()
        self.assertNotEqual(old,self.bridge.snapshot['snapshot_id'])

    def test_10_same_bar_deduplicates(self):
        self.bridge.start();self.bridge.poll();self.bridge.poll()
        self.assertEqual(self.bridge.sequence,1)

    def test_11_disconnect_fail_closed(self):
        self.bridge.start();self.mt5.connected=False
        self.bridge.poll()
        self.assertEqual(self.bridge.last_published['connection_status'],'DISCONNECTED')
        self.assertFalse(self.bridge.last_published['execution_eligible'])
        self.assertIsNone(self.bridge.last_published['quote'])

    def test_12_stale_quote(self):
        self.bridge.start();self.mt5.now+=timedelta(minutes=1)
        status,_,_=self.bridge.quote_health()
        self.assertEqual(status,'STALE')

    def test_13_missing_quote(self):
        self.mt5.quote_ok=False
        self.bridge.start()
        self.assertIsNone(self.bridge.last_published['quote'])
        self.assertEqual(self.bridge.last_published['quote_status'],'PENDING')

    def test_14_no_dxy_still_works(self):
        self.bridge.start();d=self.bridge.indicators['auxiliary_instruments']['DXY']
        self.assertIn(d['status'],('UNAVAILABLE','PENDING','PASS','PASS_WITH_LIMITATIONS'))

    def test_15_optional_dxy(self):
        b=IntegratedReadOnlyMonitor(self.mt5,'XAUUSD',CFG,M02,M02I,self.file,
                    clock=lambda:self.mt5.now,session_id='DXY',dxy_symbol='USDX')
        self.assertTrue(b.start())
        self.assertIn(b.indicators['auxiliary_instruments']['DXY']['status'],('PENDING','PASS','PASS_WITH_LIMITATIONS'))

    def test_16_missing_dxy_is_nonblocking(self):
        b=IntegratedReadOnlyMonitor(self.mt5,'XAUUSD',CFG,M02,M02I,self.file,
                    clock=lambda:self.mt5.now,session_id='DXY2',dxy_symbol='DOES_NOT_EXIST')
        self.assertTrue(b.start())
        self.assertEqual(b.market['status'],'PENDING')
        self.assertIn('MT5_DXY_NOT_ENOUGH_BARS_OR_UNAVAILABLE',b.snapshot['preview_reasons'])

    def test_17_short_history_pending(self):
        self.mt5.short_history=True
        self.assertTrue(self.bridge.start())
        self.assertIn(self.bridge.indicators['status'],('PENDING','FAIL'))
        self.assertFalse(self.bridge.last_published['live_signal_available'])

    def test_18_invalid_ohlc_blocks_interpretation(self):
        self.mt5.malformed=True
        self.assertTrue(self.bridge.start())
        self.assertNotIn(self.bridge.market['status'],('PASS','PASS_WITH_LIMITATIONS'))
        self.assertFalse(self.bridge.last_published['live_execution_allowed'])

    def test_19_init_failed(self):
        self.mt5.init_ok=False
        self.assertFalse(self.bridge.start())
        self.assertEqual(self.bridge.last_published['connection_status'],'DISCONNECTED')

    def test_20_invalid_settings_orders(self):
        a=copy.deepcopy(CFG);a['enable_orders']=True
        with self.assertRaises(ValueError):validate_configuration(a)

    def test_21_invalid_settings_capture(self):
        a=copy.deepcopy(CFG);a['screenshots_enabled']=True
        with self.assertRaises(ValueError):validate_configuration(a)

    def test_22_invalid_history(self):
        a=copy.deepcopy(CFG);a['history_closed_bars']=30
        with self.assertRaises(ValueError):validate_configuration(a)

    def test_23_invalid_source(self):
        a=copy.deepcopy(CFG);a['data_source_policy']='TRADINGVIEW_PRIMARY'
        with self.assertRaises(ValueError):validate_configuration(a)

    def test_24_invalid_symbol(self):
        with self.assertRaises(ValueError):IntegratedReadOnlyMonitor(self.mt5,'BAD\n',CFG,M02,M02I,self.file)

    def test_25_no_order_methods(self):
        self.assertFalse(any(hasattr(self.mt5,k) for k in ('order_send','order_check')))
        self.assertTrue(self.bridge.start())

    def test_26_atomic_json(self):
        atomic_json(self.file,{'x':1})
        atomic_json(self.file,{'x':2})
        self.assertEqual(json.loads(self.file.read_text()),{'x':2})
        self.assertEqual(list(self.file.parent.glob('.masterquo_*.tmp')),[])

    def test_27_restarter_does_not_claim_same_id(self):
        self.bridge.start();old=self.bridge.snapshot['snapshot_id']
        n=IntegratedReadOnlyMonitor(self.mt5,'XAUUSD',CFG,M02,M02I,self.file,
                        clock=lambda:self.mt5.now,session_id='OTHER')
        n.start();self.assertNotEqual(old,n.snapshot['snapshot_id'])

    def test_28_quote_from_broker_only(self):
        self.bridge.start()
        self.assertEqual(self.bridge.last_published['quote']['source'],'MT5_BROKER')
        self.assertFalse(self.bridge.last_published['visual_capture_enabled'])

    def test_29_monitor_has_indicator_values_even_when_pending(self):
        self.bridge.start()
        self.assertIsNotNone(self.bridge.last_published['indicator_intelligence']['timeframes']['H4']['indicators']['rsi_14']['value'])
        self.assertTrue(self.bridge.last_published['research_observation_only'])

    def test_30_last_events_bounded(self):
        for _ in range(100): self.bridge.on_event({'event_type':'heartbeat','received_at':'x'})
        self.assertLessEqual(len(self.bridge.events),40)

    def test_31_backward_timestamp_quote_rejected(self):
        self.bridge.start()
        self.bridge.quote['source_timestamp']='2000-01-01T00:00:00+00:00'
        self.assertEqual(self.bridge.quote_health()[0],'STALE')

    def test_32_future_quote_fails(self):
        self.bridge.start()
        self.bridge.quote['source_timestamp']='2099-01-01T00:00:00+00:00'
        self.assertEqual(self.bridge.quote_health()[0],'FAIL')

    def test_33_invalid_bidask_fails(self):
        self.bridge.start()
        self.bridge.quote['bid']=3001;self.bridge.quote['ask']=3000
        self.assertEqual(self.bridge.quote_health()[0],'FAIL')

    def test_34_shutdown_invalidates_live_quote(self):
        self.bridge.start();self.bridge.disconnect()
        self.assertFalse(self.bridge.last_published['live_execution_allowed'])
        self.assertEqual(self.bridge.last_published['quote_status'],'DISCONNECTED')

    def test_35_no_reuse_of_old_status_on_refresh(self):
        self.bridge.start()
        self.mt5.short_history=True
        self.bridge.refresh()
        self.assertFalse(self.bridge.last_published['live_signal_available'])

    def test_36_no_runtime_trade_leak(self):
        self.bridge.start()
        d=self.bridge.last_published
        for f,v in [('execution_permission','BLOCKED'),('live_execution_allowed',False),('submitted_order_id',None)]:
            self.assertEqual(d[f],v)


    def test_37_data_degraded_quote_clears_old(self):
        self.bridge.start()
        self.mt5.quote_ok=False
        self.bridge.poll(check_bars=False)
        self.assertIsNone(self.bridge.last_published['quote'])
        self.assertEqual(self.bridge.last_published['quote_status'],'PENDING')

    def test_38_reconnect_resets_old_regime_memory(self):
        self.bridge.start()
        self.bridge.observer.last_open[('XAUUSD','M1')] = 123
        self.bridge.disconnect()
        self.mt5.connected=True
        self.assertTrue(self.bridge.start())
        self.assertNotEqual(self.bridge.observer.last_open[('XAUUSD','M1')],123)
        self.assertEqual(self.bridge.sequence,2)

    def test_39_no_forming_candles_in_indicators(self):
        self.bridge.start()
        self.assertEqual(self.bridge.indicators['timeframes']['M1']['closed_bars'],260)
        self.assertTrue(all(c['bar_state']=='CLOSED' for c in self.bridge.snapshot['candles_by_tf']['M1']))

    def test_40_viewer_has_six_correct_roles(self):
        self.bridge.start()
        from M02I_MONITOR_VIEWER import row_view
        r=row_view(self.bridge.last_published,'D1')
        self.assertEqual(r[0],'D1')
        self.assertIn('50:',r[4])
        self.assertIn('200:',r[4])

    def test_41_quotes_do_not_fetch_261_history_again(self):
        self.bridge.start()
        before=self.mt5.reads
        self.bridge.poll(check_bars=False)
        self.assertEqual(before,self.mt5.reads)

    def test_42_correct_schema_version(self):
        self.bridge.start()
        self.assertEqual(self.bridge.last_published['schema_version'],'2.0.0')
        self.assertEqual(self.bridge.last_published['prompt_version'],'4.1.0')

    def test_43_expected_timeframe_profile(self):
        self.bridge.start()
        h=self.bridge.indicators['timeframes']['H1']['indicators']
        self.assertIn('macd_histogram',h)
        self.assertNotIn('rsi_14',h)

    def test_44_research_mode_never_claims_live_signal(self):
        self.bridge.start();report=self.bridge.last_published
        self.assertFalse(report['live_signal_available'])
        self.assertFalse(report['execution_eligible'])
        self.assertFalse(report['live_execution_allowed'])

    def test_45_risk_gate_missing_is_not_fabricated_pass(self):
        self.bridge.start()
        self.assertFalse(any(g['status']=='PASS' for g in self.bridge.snapshot['data_gates']))

    def test_46_closed_bar_updates_with_actual_broker_open(self):
        self.bridge.start();old=self.bridge.indicators['timeframes']['M1']['last_closed_at']
        self.mt5.roll('M1');self.bridge.poll()
        self.assertNotEqual(old,self.bridge.indicators['timeframes']['M1']['last_closed_at'])

    def test_47_optional_dxy_never_changes_broker_quote(self):
        b=IntegratedReadOnlyMonitor(self.mt5,'XAUUSD',CFG,M02,M02I,self.file,
                    clock=lambda:self.mt5.now,dxy_symbol='USDX')
        b.start()
        self.assertEqual(b.last_published['quote']['symbol'],'XAUUSD')
        self.assertNotEqual(b.last_published['quote']['bid'],105.0)

    def test_48_negative_confirms_no_screenshot_api(self):
        from inspect import getsource
        from M02I_M01_M02_LIVE_BRIDGE import IntegratedReadOnlyMonitor
        source=getsource(IntegratedReadOnlyMonitor)
        for bad in ('pyautogui','ImageGrab','order_send(', 'screenshot(', 'cv2.'):
            self.assertNotIn(bad,source)


if __name__ == '__main__':
    unittest.main(verbosity=2)
