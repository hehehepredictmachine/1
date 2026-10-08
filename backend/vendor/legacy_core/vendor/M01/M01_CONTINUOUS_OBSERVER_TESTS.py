"""Isolated synthetic tests of read-only, no-screenshot continuous observer.
No MT5 account, TV access or real data required.
"""
import copy
import json
import pathlib
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from M01_CONTINUOUS_MT5_OBSERVER_REFERENCE import Observer

BASE=pathlib.Path(__file__).parent
SPEC=(BASE/'M01_DATA_INTELLIGENCE_v4.2.1_CANDIDATE.txt').read_text(encoding='utf8')
SCHEMA=json.loads((BASE/'M01_DATA_SNAPSHOT_SCHEMA_v2_0_EXTENSION.json').read_text(encoding='utf8'))
SNAPSHOT=json.loads((BASE/'M01_SYNTHETIC_EXAMPLE.json').read_text(encoding='utf8'))

class Bar(dict):
    @property
    def dtype(self):return SimpleNamespace(names=tuple(self.keys()))

def rate(t, price=3000):
    return Bar(time=t,open=price,high=price+1,low=price-1,close=price+0.4,
               tick_volume=30,real_volume=0)

class FakeMT5:
    TIMEFRAME_D1=1440;TIMEFRAME_H4=240;TIMEFRAME_H1=60
    TIMEFRAME_M15=15;TIMEFRAME_M5=5;TIMEFRAME_M1=1
    def __init__(self):
        self.ticks=SimpleNamespace(time=1791448080,time_msc=1791448080000,bid=3000.0,ask=3000.5,flags=1)
        self.rows=[rate(1791447960, 2998),rate(1791448020,2999),rate(1791448080,3000)]
        self.online=True
        self.closed=False
    def initialize(self,*args):return self.online
    def terminal_info(self):return SimpleNamespace(connected=self.online)
    def last_error(self):return (1,'bad')
    def symbol_info(self,s):return object() if s in {'XAUUSD','DXY'} else None
    def symbol_select(self,*args):return True
    def symbol_info_tick(self,*args):return self.ticks
    def copy_rates_from_pos(self,*args):return self.rows
    def shutdown(self):self.closed=True

class ContinuousTests(unittest.TestCase):
    def setUp(self):
        self.ev=[]; self.mt5=FakeMT5()
        self.ob=Observer(self.mt5,'XAUUSD',{'XAUUSD':['M1','M5','M15','H1','H4','D1']},.5,1.,self.ev.append)
    def test_01_no_visual_capture_flag(self):self.assertIs(SNAPSHOT['visual_capture_enabled'],False)
    def test_02_frozen_root_schema(self):self.assertIn('2.0.0',SPEC)
    def test_03_no_screenshot_fallback_spec(self):self.assertIn('Nie wolno awaryjnie uruchomić screenshotu',SPEC)
    def test_04_tv_is_secondary(self):self.assertIn('TRADINGVIEW_ROLE=SUPPLEMENTAL_CONTEXT_ONLY',SPEC)
    def test_05_mt5_only_execution(self):self.assertIn('MT5_ONLY, TV_FORBIDDEN',SPEC)
    def test_06_continuous_state_contract(self):self.assertIn('CONTINUOUS_OBSERVATION:',SPEC)
    def test_07_observer_import_no_dependency_on_mt5(self):self.assertTrue(callable(Observer))
    def test_08_connect(self):self.assertTrue(self.ob.connect(None))
    def test_09_disconnect(self):self.ob.connect(None);self.ob.close();self.assertTrue(self.mt5.closed)
    def test_10_init_failure(self):self.mt5.online=False;self.assertFalse(self.ob.connect(None))
    def test_11_tick_changes_emitted(self):
        self.ob.check_quote();self.assertEqual(1,sum(e['event_type']=='quote_updated' for e in self.ev))
        self.mt5.ticks=SimpleNamespace(time=1791448080,time_msc=1791448080500,bid=3001.,ask=3001.5,flags=1)
        self.ob.check_quote();self.assertEqual(2,sum(e['event_type']=='quote_updated' for e in self.ev))
    def test_12_same_tick_deduped(self):
        self.ob.check_quote();self.ob.check_quote();self.assertEqual(1,sum(e['event_type']=='quote_updated' for e in self.ev))
    def test_13_inverted_quote_degraded(self):
        self.mt5.ticks=SimpleNamespace(time=1791448080,time_msc=1791448080000,bid=3000.,ask=2999.,flags=1)
        self.ob.check_quote();self.assertEqual('data_degraded',self.ev[-1]['event_type'])
    def test_14_six_tf_on_first_poll(self):
        self.ob.check_bars(); self.assertEqual(6,sum(e['event_type']=='candle_updated' for e in self.ev))
    def test_15_first_poll_no_close(self):
        self.ob.check_bars();self.assertFalse(any(e['event_type']=='candle_closed' for e in self.ev))
    def test_16_same_bar_no_repeat(self):
        self.ob.check_bars();self.ob.check_bars();self.assertEqual(6,sum(e['event_type']=='candle_updated' for e in self.ev))
    def test_17_close_on_real_next_bar(self):
        self.ob.check_bars();self.mt5.rows=[rate(1791448020,2999),rate(1791448080,3000),rate(1791448140,3001)]
        self.ob.check_bars();self.assertEqual(6,sum(e['event_type']=='candle_closed' for e in self.ev))
    def test_18_missing_former_bar_creates_gap(self):
        self.ob.check_bars();self.mt5.rows=[rate(1791448140,3001)];self.ob.check_bars()
        self.assertEqual(6,sum(e['event_type']=='data_gap' for e in self.ev))
    def test_19_intrabar_update_no_close(self):
        self.ob.check_bars();self.mt5.rows[-1]['close']=3000.7;self.ob.check_bars()
        self.assertEqual(12,sum(e['event_type']=='candle_updated' for e in self.ev))
        self.assertEqual(0,sum(e['event_type']=='candle_closed' for e in self.ev))
    def test_20_heartbeat_not_quote(self):
        self.ob.cycle(100,0,0,0)
        heartbeats=[e for e in self.ev if e['event_type']=='heartbeat']
        self.assertEqual(1,len(heartbeats));self.assertIn('DOES_NOT_PROVE',heartbeats[0]['note'])
    def test_21_readonly_code(self):
        code=(BASE/'M01_CONTINUOUS_MT5_OBSERVER_REFERENCE.py').read_text(encoding='utf8')
        for v in ('order_send(', 'pyautogui', 'ImageGrab', 'mss.mss(', 'pytesseract'):
            self.assertNotIn(v,code)
    def test_22_output_policy_only_metadata_not_secret(self):
        self.ob.check_quote();self.assertNotIn('password',json.dumps(self.ev))
    def test_23_tv_webhook_separate(self):
        code=(BASE/'M01_CONTINUOUS_MT5_OBSERVER_REFERENCE.py').read_text(encoding='utf8')
        self.assertNotIn('requests.post(',code);self.assertNotIn('webhook_receiver(',code)
    def test_24_schema_reject_visual_true(self):
        from jsonschema import Draft202012Validator
        bad=copy.deepcopy(SNAPSHOT);bad['visual_capture_enabled']=True
        self.assertTrue(list(Draft202012Validator(SCHEMA).iter_errors(bad)))
    def test_25_schema_accepts_example(self):
        from jsonschema import Draft202012Validator,FormatChecker
        self.assertFalse(list(Draft202012Validator(SCHEMA,format_checker=FormatChecker()).iter_errors(SNAPSHOT)))
    def test_26_dxy_optional_context(self):
        ob=Observer(self.mt5,'XAUUSD',{'XAUUSD':['M1'],'DXY':['H1']},.5,1.,self.ev.append)
        ob.check_bars();self.assertEqual(2,sum(e['event_type']=='candle_updated' for e in self.ev))
    def test_27_submitted_orders_not_supported(self):
        code=(BASE/'M01_CONTINUOUS_MT5_OBSERVER_REFERENCE.py').read_text(encoding='utf8')
        self.assertNotIn('order_check(',code);self.assertNotIn('positions_get(',code)

if __name__=='__main__':unittest.main(verbosity=2)
