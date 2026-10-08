"""Offline reproducible tests, no network, no broker and no Telegram."""
from __future__ import annotations
import copy
import json
import sys
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from M04N_MACRO_GUARD import (utc,stamp,build,step,MacroAlertStore,load_optional,atomic,
                              _m14_state,_validate_sources,_calendar_cross_check,alert_text)
from M10A_M15_ADAPTER import _canonical_fallback
from M04N_MACRO_GUARD import validate_m14
sys.path.insert(0,str(ROOT/'vendor'/'M15'))
from M15_REFERENCE_COMMUNICATION_ENGINE import compose

NOW=datetime(2026,10,8,16,0,tzinfo=timezone.utc)
def make_event(name='CPI',impact='HIGH',minutes=5,avail=-3600,ident='C1'):
    return dict(event_id=ident,name=name,impact=impact,source_id='BLS_CALENDAR',
        scheduled_at=stamp(NOW+timedelta(minutes=minutes)),
        available_at=stamp(NOW+timedelta(seconds=avail)),actual=None,forecast=None)
def data(now=NOW,events=None,status='HEALTHY'):
    events=copy.deepcopy(events if events is not None else [])
    feed={'module_id':'M04N','module_version':'1.1.0','schema_version':'2.0.0',
        'as_of':stamp(now),'execution_permission':'BLOCKED','visual_capture_enabled':False,
        'research_only':True,'status':status,'calendar':{'events':events,'status':'PARTIAL'},
        'news':{'new_events':[]},'integrity':{'source_health':{'BLS_CALENDAR':{'state':'HEALTHY'}}},
        'interpretation':{'detected_topics':['INFLATION']}}
    bridge={'module_id':'M04N','as_of':stamp(now),'source_status':status,
        'context_inputs':{'macro_events':copy.deepcopy(events),'calendar_coverage':{'status':'PARTIAL',
                 'data_complete':False,'source_id':'BLS_CALENDAR'}},
        'advisory':{'execution_permission':'BLOCKED','does_not_override_m04_m11_m14':True}}
    return feed,bridge

def monitor(now=NOW,decision='NO_TRADE'):
    m14=_canonical_fallback({'analysis_id':'SIM_TEST_A1','as_of':stamp(now)},'TEST_ONLY')
    if decision in ('LONG','SHORT'):
        m14.update(decision=decision,intended_direction=decision,top_setup_id='S1',
            horizon_id='M5',signal_validity='VALID_CONFIRMED_SETUP',signal_tier='CONFIRMED',
            entry_trigger='CONFIRMED',entry_status='READY')
    validate_m14(m14)
    c={'analysis_id':m14['analysis_id'],'snapshot_as_of':m14['as_of'],
       'instrument_id':'XAUUSD','mode':'MT5_READONLY','account_type':'ZERO_SPREAD'}
    p=compose(m14,c)
    p.update(m15_published_at=stamp(now),m10a_connection_status='CONNECTED',m10a_quote_status='RECEIVED')
    return p

class CoreTests(unittest.TestCase):
    def setUp(self):self.feed,self.bridge=data();self.mon=monitor()
    def execute(self):return build(NOW,self.feed,self.bridge,self.mon)
    def test_valid_partial_remains_pending(self):
        r=self.execute();self.assertEqual(r['macro_gate'],'PENDING');self.assertEqual(r['m04_calendar_context']['event_gate'],'PENDING')
    def test_high_event_blocks(self):
        self.feed,self.bridge=data(events=[make_event()]);r=self.execute()
        self.assertEqual(r['macro_gate'],'BLOCKED');self.assertEqual(len(r['macro_active_events']),1)
    def test_extreme_blocks(self):
        self.feed,self.bridge=data(events=[make_event(impact='EXTREME',minutes=55)]);self.assertEqual(self.execute()['macro_gate'],'BLOCKED')
    def test_medium_pending(self):
        self.feed,self.bridge=data(events=[make_event(impact='MEDIUM')]);self.assertEqual(self.execute()['macro_gate'],'PENDING')
    def test_distant_high_pending(self):
        self.feed,self.bridge=data(events=[make_event(minutes=120)]);self.assertEqual(self.execute()['macro_gate'],'PENDING')
    def test_released_high_window_blocks(self):
        self.feed,self.bridge=data(events=[make_event(minutes=-20)]);self.assertEqual(self.execute()['macro_gate'],'BLOCKED')
    def test_after_postwindow(self):
        self.feed,self.bridge=data(events=[make_event(minutes=-35)]);self.assertEqual(self.execute()['macro_gate'],'PENDING')
    def test_future_available_at_ignored(self):
        self.feed,self.bridge=data(events=[make_event(avail=3600)]);self.assertEqual(self.execute()['macro_gate'],'PENDING')
    def test_technical_long_suppressed_pending(self):
        self.mon=monitor(decision='LONG');r=self.execute()
        self.assertEqual(r['m14_original_decision'],'LONG');self.assertEqual(r['guarded_display_decision'],'WAIT')
    def test_technical_short_suppressed_blocked(self):
        self.feed,self.bridge=data(events=[make_event()]);self.mon=monitor(decision='SHORT')
        r=self.execute();self.assertEqual(r['m14_original_decision'],'SHORT');self.assertEqual(r['guarded_display_decision'],'NO_TRADE')
    def test_no_trade_remains_no_trade(self):self.assertEqual(self.execute()['guarded_display_decision'],'NO_TRADE')
    def test_no_execution_any_stage(self):
        for events in ([],[make_event()]):
            with self.subTest(events=len(events)):
                self.feed,self.bridge=data(events=events);r=self.execute()
                self.assertEqual(r['execution_permission'],'BLOCKED');self.assertFalse(r['live_execution_allowed']);self.assertEqual(r['order_actions'],[])
    def test_missing_feed(self):self.assertEqual(build(NOW,None,self.bridge,self.mon)['macro_gate'],'BLOCKED')
    def test_missing_bridge(self):self.assertEqual(build(NOW,self.feed,None,self.mon)['macro_gate'],'BLOCKED')
    def test_missing_technical(self):self.assertEqual(build(NOW,self.feed,self.bridge,None)['guarded_display_decision'],'NO_TRADE')
    def test_technical_stale(self):
        self.mon['m15_published_at']=stamp(NOW-timedelta(seconds=16));self.assertEqual(self.execute()['guarded_display_decision'],'NO_TRADE')
    def test_feed_stale(self):
        self.feed,self.bridge=data(now=NOW-timedelta(minutes=16));self.assertEqual(self.execute()['macro_gate'],'BLOCKED')
    def test_feed_future(self):
        self.feed,self.bridge=data(now=NOW+timedelta(seconds=1));self.assertEqual(self.execute()['macro_gate'],'BLOCKED')
    def test_report_time_mismatch(self):
        self.bridge['as_of']=stamp(NOW-timedelta(seconds=2));self.assertEqual(self.execute()['macro_gate'],'BLOCKED')
    def test_report_unsigned_time(self):
        self.feed['as_of']='2026-10-08T16:00:00';self.assertEqual(self.execute()['macro_gate'],'BLOCKED')
    def test_guard_rejects_fake_calendar_verified(self):
        self.bridge['context_inputs']['calendar_coverage']['status']='VERIFIED';self.assertEqual(self.execute()['macro_gate'],'BLOCKED')
    def test_guard_rejects_complete_calendar(self):
        self.bridge['context_inputs']['calendar_coverage']['data_complete']=True;self.assertEqual(self.execute()['macro_gate'],'BLOCKED')
    def test_guard_rejects_injected_event(self):
        self.bridge['context_inputs']['macro_events'].append(make_event())
        self.assertEqual(self.execute()['macro_gate'],'BLOCKED')
    def test_guard_rejects_edited_event(self):
        self.feed,self.bridge=data(events=[make_event()]);self.bridge['context_inputs']['macro_events'][0]['impact']='LOW'
        self.assertEqual(self.execute()['macro_gate'],'BLOCKED')
    def test_guard_rejects_duplicate_events(self):
        e=make_event();self.feed,self.bridge=data(events=[e,e]);self.assertEqual(self.execute()['macro_gate'],'BLOCKED')
    def test_guard_no_spurious_surprise(self):
        e=make_event();e.update(actual='2.9%',forecast='2.8%')
        self.feed,self.bridge=data(events=[e]);self.assertEqual(self.execute()['m04_calendar_context']['released'],[])
    def test_reject_broker_permission_elevation(self):
        self.feed['execution_permission']='ALLOWED';self.assertEqual(self.execute()['macro_gate'],'BLOCKED')
    def test_reject_unavailable_all_sources(self):
        self.feed,self.bridge=data(status='UNAVAILABLE');self.assertEqual(self.execute()['macro_gate'],'BLOCKED')
    def test_reject_invalid_m14_binding(self):
        self.mon['analysis_id']='MISMATCH';self.assertEqual(self.execute()['guarded_display_decision'],'NO_TRADE')
    def test_reject_invalid_m14_authority(self):
        self.mon['original_m14']['execution_permission']='PASS'
        self.assertEqual(self.execute()['guarded_display_decision'],'NO_TRADE')
    def test_reject_disconnected_mt5(self):
        self.mon['m10a_connection_status']='OFFLINE';self.assertEqual(self.execute()['guarded_display_decision'],'NO_TRADE')
    def test_missing_risk_payload_stays_blocked(self):self.assertEqual(self.execute()['m11_risk_gate'],'BLOCKED')
    def test_wrong_risk_payload_analysis(self):
        r=build(NOW,self.feed,self.bridge,self.mon,{'analysis_id':'WRONG'})
        self.assertEqual(r['m11_risk_reason'],'RISK_ANALYSIS_ID_MISMATCH')
    def test_guards_no_dxy_price_direction(self):self.assertTrue(self.execute()['news_is_not_directional_signal'])
    def test_news_verified_age(self):
        self.feed['news']['new_events']=[{'event_id':'N1','time_quality':'PUBLISHED','impact':'HIGH',
            'title':'Fed release','published_at':stamp(NOW-timedelta(minutes=2)),'source_id':'FED_MONETARY'}]
        self.assertEqual(len(self.execute()['macro_new_high_impact_news']),1)
    def test_old_news_not_urgent(self):
        self.feed['news']['new_events']=[{'event_id':'N1','time_quality':'PUBLISHED','impact':'HIGH',
            'published_at':stamp(NOW-timedelta(hours=2))}]
        self.assertEqual(self.execute()['macro_new_high_impact_news'],[])
    def test_unverified_news_not_urgent(self):
        self.feed['news']['new_events']=[{'event_id':'N1','time_quality':'FIRST_SEEN','impact':'HIGH',
            'published_at':stamp(NOW)}];self.assertEqual(self.execute()['macro_new_high_impact_news'],[])
    def test_future_published_news_not_urgent(self):
        self.feed['news']['new_events']=[{'event_id':'N1','time_quality':'PUBLISHED','impact':'HIGH',
            'published_at':stamp(NOW+timedelta(seconds=10))}]
        self.assertEqual(self.execute()['macro_new_high_impact_news'],[])
    def test_atomic_read(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'report.json';atomic(p,{'x':1});self.assertEqual(load_optional(p),{'x':1})
            p.write_text('{bad',encoding='utf8');self.assertIsNone(load_optional(p))
    def test_utc_requires_offset(self):
        with self.assertRaises(ValueError):utc('2026-10-08T16:00:00')

class AlertTests(unittest.TestCase):
    def test_baseline_suppresses_preexisting_macro(self):
        with tempfile.TemporaryDirectory() as t:
            s=MacroAlertStore(Path(t)/'db.sqlite');r={'integrity_status':'VALID_PARTIAL','as_of':stamp(NOW),
              'macro_active_events':[make_event()],'macro_new_high_impact_news':[]}
            self.assertEqual(s.observe(r),[]);self.assertEqual(s.observe(r),[]);s.close()
    def test_new_active_event_one_alert_across_restart(self):
        with tempfile.TemporaryDirectory() as t:
            db=Path(t)/'db.sqlite';r={'integrity_status':'VALID_PARTIAL','as_of':stamp(NOW),
              'macro_active_events':[],'macro_new_high_impact_news':[]}
            s=MacroAlertStore(db);s.observe(r);r['macro_active_events']=[make_event()]
            self.assertEqual(len(s.observe(r)),1);s.close();s=MacroAlertStore(db)
            self.assertEqual(len(s.observe(r)),0);s.close()
    def test_partial_outage_does_not_emplace_baseline(self):
        with tempfile.TemporaryDirectory() as t:
            s=MacroAlertStore(Path(t)/'db.sqlite')
            x={'integrity_status':'FAIL_CLOSED','as_of':stamp(NOW),'macro_active_events':[make_event()]}
            self.assertEqual(s.observe(x),[])
            x['integrity_status']='VALID_PARTIAL';self.assertEqual(s.observe(x),[]);s.close()
    def test_claim_before_sending(self):
        with tempfile.TemporaryDirectory() as t:
            s=MacroAlertStore(Path(t)/'db.sqlite');self.assertTrue(s.claim('EV1',stamp(NOW)))
            self.assertFalse(s.claim('EV1',stamp(NOW)));s.close()
    def test_news_baseline(self):
        with tempfile.TemporaryDirectory() as t:
            s=MacroAlertStore(Path(t)/'db.sqlite');r={'integrity_status':'VALID_PARTIAL','as_of':stamp(NOW),
              'macro_active_events':[],'macro_new_high_impact_news':[{'event_id':'NX','impact':'HIGH'}]}
            self.assertEqual(s.observe(r),[]);self.assertEqual(s.observe(r),[]);s.close()
    def test_no_real_send_without_optin(self):
        with tempfile.TemporaryDirectory() as t:
            s=MacroAlertStore(Path(t)/'db.sqlite');self.assertEqual(
              step(NOW,None,None,None,Path(t)/'out.json',alert_store=s,telegram=False)['delivery']['attempted'],0);s.close()
    def test_alert_message_no_trade_recommendation(self):
        msg=alert_text({'kind':'CALENDAR','event':make_event()})
        self.assertIn('nie jest to sygnał LONG/SHORT',msg)
    def test_same_event_reappearance_no_duplicate(self):
        with tempfile.TemporaryDirectory() as t:
            s=MacroAlertStore(Path(t)/'db.sqlite');r={'integrity_status':'VALID_PARTIAL','as_of':stamp(NOW),
              'macro_active_events':[],'macro_new_high_impact_news':[]}
            s.observe(r);r['macro_active_events']=[make_event()]
            self.assertEqual(len(s.observe(r)),1);r['macro_active_events']=[];s.observe(r)
            r['macro_active_events']=[make_event()];self.assertEqual(s.observe(r),[]);s.close()
    def test_unknown_delivery_never_retry(self):
        with tempfile.TemporaryDirectory() as t:
            s=MacroAlertStore(Path(t)/'db.sqlite');s.claim('EV1',stamp(NOW));s.result('EV1','UNKNOWN_NO_AUTOMATIC_RETRY')
            self.assertFalse(s.claim('EV1',stamp(NOW)));s.close()

if __name__=='__main__':unittest.main()
