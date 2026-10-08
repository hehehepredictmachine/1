"""Synthetic/offline M10A->M15 integration tests. No network or orders."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from M10A_M15_ADAPTER import (convert,render,_material_event,_rule_text,connected_data,
                               safe_stamp,_quote_context,digest)
from M15_REFERENCE_COMMUNICATION_ENGINE import validate_m14

ROOT=Path(__file__).resolve().parent
SOURCE=ROOT/'vendor/M15/M14_REFERENCE_SYNTHETIC_OUTPUT.json'


def record():
    return {'setup_id':'M10:synthetic','revision':5,'state':'CONFIRMED',
            'direction':'LONG','horizon_id':'M5',
            'next_expected_event':{'timeframe':'M5','criterion':{'field':'close','operator':'>','level':2700.,'reference_evidence_id':'E'}},
            'invalidation':{'timeframe':'M5','condition':{'field':'close','operator':'<','level':2600.}},
            'change_log':[{'reason':'CONFIRM','new_state':'CONFIRMED','event_id':'BAR:42','available_at':'2026-10-08T10:00:00Z'}]}


def base(*,synthetic=True):
    x=json.loads(SOURCE.read_text(encoding='utf-8'))
    if not synthetic:x['analysis_id']='BRIDGE-TEST_SESSION_X'
    x['top_setup_id']='M10:synthetic'
    x['horizon_id']='M5'
    report={'schema_version':'2.0.0','analysis_id':x['analysis_id'],
       'as_of':x['as_of'],'snapshot_id':'SNAP:42',
       'analysis_decision':'LONG','intended_direction':'LONG',
       'decision_result':x,'data_gate':'PASS_WITH_LIMITATIONS',
       'monitor_connection_status':'CONNECTED','monitor_quote_status':'RECEIVED',
       'screen_capture_count':0,'visual_capture_enabled':False,
       'research_only':True,'account_profile':'ZERO_SPREAD_DECLARED_UNVERIFIED',
       'execution_permission':'BLOCKED','live_execution_allowed':False,
       'broker_order_sent':False,'submitted_order_id':None,'reason_codes':[],
       'auto_trigger':{'status':'PASS_WITH_LIMITATIONS','validated_record':record()},
       'broker_quote':{'source':'MT5_BROKER','symbol':'XAUUSD','source_timestamp':x['as_of'],
                       'bid':2650.,'ask':2650.}}
    return report

class ConverterTests(unittest.TestCase):
    def test_01_valid_m14(self):
        r=base();validate_m14(r['decision_result'])
    def test_02_valid_convert(self):
        p,e,why=convert(base());self.assertEqual(p['decision'],'LONG');self.assertEqual(p['execution_permission'],'BLOCKED')
        self.assertEqual(why,'M14_VALID_ANALYTICAL_ONLY');self.assertTrue(e)
    def test_03_data_lost(self):
        r=base();r['monitor_connection_status']='DISCONNECTED'
        p,e,_=convert(r);self.assertEqual(p['decision'],'NO_TRADE');self.assertIsNone(e)
    def test_04_stale_quote(self):
        r=base();r['monitor_quote_status']='STALE'
        self.assertEqual(convert(r)[0]['decision'],'NO_TRADE')
    def test_05_approval_forbidden(self):
        r=base();r['decision_result']['execution_permission']='AUTHORIZED'
        p,e,_=convert(r);self.assertEqual(p['decision'],'NO_TRADE');self.assertIsNone(e)
    def test_06_order_id_forbidden(self):
        r=base();r['decision_result']['submitted_order_id']='123'
        self.assertEqual(convert(r)[0]['decision'],'NO_TRADE')
    def test_07_orders_flag_forbidden(self):
        r=base();r['broker_order_sent']=True
        self.assertEqual(convert(r)[0]['decision'],'NO_TRADE')
    def test_08_snapshot_binding_required(self):
        r=base();r['decision_result']['analysis_id']='OTHER'
        self.assertEqual(convert(r)[0]['decision'],'NO_TRADE')
    def test_09_asof_binding_required(self):
        r=base();r['as_of']='2026-10-08T10:01:00Z'
        self.assertEqual(convert(r)[0]['decision'],'NO_TRADE')
    def test_10_decision_binding_required(self):
        r=base();r['analysis_decision']='SHORT'
        self.assertEqual(convert(r)[0]['decision'],'NO_TRADE')
    def test_11_required_m01_gate(self):
        r=base();r['data_gate']='PENDING'
        self.assertEqual(convert(r)[0]['decision'],'NO_TRADE')
    def test_12_provenance_visual(self):
        r=base();r['screen_capture_count']=1
        self.assertEqual(convert(r)[0]['decision'],'NO_TRADE')
    def test_13_unsupported_account(self):
        r=base();r['account_profile']='OTHER'
        self.assertEqual(convert(r)[0]['decision'],'NO_TRADE')
    def test_14_zero_quote_cost_assumption(self):
        p,_,_=convert(base());self.assertEqual(p['quote']['spread'],0)
        self.assertNotIn('commission',p['quote'])
        self.assertIn('MT5_ZERO_COSTS_NOT_YET_VERIFIED',p['limitations'])
    def test_15_future_quote_not_reused(self):
        r=base();r['broker_quote']['source_timestamp']='2026-10-08T10:00:01Z'
        self.assertIsNone(convert(r)[0]['quote'])
    def test_16_tradingview_quote_rejected(self):
        r=base();r['broker_quote']['source']='TRADINGVIEW'
        self.assertIsNone(convert(r)[0]['quote'])
    def test_17_invalid_spread_not_reused(self):
        r=base();r['broker_quote']['ask']=2640.
        self.assertIsNone(convert(r)[0]['quote'])
    def test_18_empty_data_safely_displays(self):
        p,e,_=convert({'monitor_quote_status':'UNAVAILABLE'})
        self.assertEqual(p['decision'],'NO_TRADE');self.assertIsNone(e)
    def test_19_bad_type_rejected(self):
        with self.assertRaises(ValueError):convert('bad')
    def test_20_no_fake_probability(self):
        self.assertIsNone(convert(base())[0]['probabilities'])
    def test_21_no_fake_plan(self):
        self.assertIsNone(convert(base())[0]['plan'])
    def test_22_rule_text(self):
        self.assertIn('close > 2700',_rule_text(record()['next_expected_event']))
    def test_23_rule_text_does_not_invent(self):
        self.assertIsNone(_rule_text({'timeframe':'M5','criterion':{'field':'close'}}))
    def test_24_missing_early_rule_blocks(self):
        r=base();x=r['decision_result']
        x.update(decision='EARLY_SETUP',signal_tier='EARLY',signal_validity='VALID_EARLY_SETUP',entry_trigger='NOT_CONFIRMED')
        r['analysis_decision']='EARLY_SETUP';r['auto_trigger']['validated_record']['next_expected_event']={}
        self.assertEqual(convert(r)[0]['decision'],'NO_TRADE')
    def test_25_canonical_enums_no_buy_sell(self):
        self.assertIn(convert(base())[0]['decision'],{'LONG','SHORT','EARLY_SETUP','CONDITIONAL_SETUP','WAIT','NO_TRADE'})
    def test_26_invalidation_stage_event(self):
        r=base();rec=r['auto_trigger']['validated_record'];rec['revision']=6;rec['state']='INVALIDATED'
        rec['change_log'].append({'reason':'INVALIDATE','new_state':'INVALIDATED','event_id':'EV:invalidate'})
        self.assertIn('INVALIDATED',_material_event(r))
    def test_27_stage_nonmaterial_suppressed(self):
        r=base();r['auto_trigger']['validated_record']['change_log'][-1]['reason']='QUOTE_UPDATED'
        self.assertIsNone(_material_event(r))
    def test_28_stage_mismatch_suppressed(self):
        r=base();r['auto_trigger']['validated_record']['change_log'][-1]['new_state']='TRIGGERED'
        self.assertIsNone(_material_event(r))
    def test_29_revision_not_int_rejected(self):
        r=base();r['auto_trigger']['validated_record']['revision']='5'
        self.assertIsNone(_material_event(r))
    def test_30_event_stable_for_quote_updates(self):
        a=base();b=base();b['broker_quote']['bid']=2651.;b['broker_quote']['ask']=2651.
        self.assertEqual(_material_event(a),_material_event(b))
    def test_31_safe_stamp(self):
        self.assertEqual(safe_stamp(base()),'2026-10-08T10:00:00Z')
    def test_32_digest_stable(self):self.assertEqual(digest({'a':1,'b':2}),digest({'b':2,'a':1}))

class RenderingTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup)
        self.out=Path(self.t.name)
    def test_33_files_generated(self):
        render(base(),self.out)
        for f in ('M15_MONITOR_SNAPSHOT.json','M15_EXPORT_FULL.json','M15_COMPACT_PL.txt','M15_FULL_PL.txt','M15_LAST_DELIVERY_STATUS.json'):
            self.assertTrue((self.out/f).is_file())
    def test_34_default_no_telegram(self):
        r=render(base(synthetic=False),self.out)
        self.assertEqual(r['delivery']['delivery_status'],'TELEGRAM_DISABLED')
        self.assertFalse((self.out/'M15_DELIVERY_OUTBOX.sqlite3').exists())
    def test_35_synthetic_never_sent(self):
        fn=lambda *a:self.fail('sender must not be called')
        with patch.dict('os.environ',{'TELEGRAM_BOT_TOKEN':'fake','TELEGRAM_CHAT_ID':'fake'}):
            r=render(base(),self.out,telegram_enabled=True,telegram_sender=fn)
        self.assertIn(r['delivery']['delivery_status'],{'SUPPRESSED_UNSAFE_OR_NON_SIGNAL','NO_MATERIAL_EVENT'})
    def test_36_live_no_env_not_sent(self):
        with patch.dict('os.environ',{'TELEGRAM_BOT_TOKEN':'','TELEGRAM_CHAT_ID':''}):
            r=render(base(synthetic=False),self.out,telegram_enabled=True)
        self.assertEqual(r['delivery']['delivery_status'],'QUEUED_MISSING_ENV')
    def test_37_mocked_send(self):
        sent=[]
        def mock(text,token,chat):sent.append(text);return 41
        with patch.dict('os.environ',{'TELEGRAM_BOT_TOKEN':'test','TELEGRAM_CHAT_ID':'test'}):
            r=render(base(synthetic=False),self.out,telegram_enabled=True,telegram_sender=mock)
        self.assertEqual(r['delivery']['delivery_status'],'DELIVERED');self.assertEqual(len(sent),1)
        self.assertIn('NIE potwierdzenie',sent[0]);self.assertIn('BLOCKED',sent[0])
    def test_38_repeat_once(self):
        calls=[]
        with patch.dict('os.environ',{'TELEGRAM_BOT_TOKEN':'test','TELEGRAM_CHAT_ID':'test'}):
            for i in range(3):
                r=base(synthetic=False);r['broker_quote']['bid']+=i
                render(r,self.out,telegram_enabled=True,telegram_sender=lambda *a:calls.append(1))
        self.assertEqual(len(calls),1)
    def test_39_new_revision_new_event(self):
        calls=[]
        with patch.dict('os.environ',{'TELEGRAM_BOT_TOKEN':'test','TELEGRAM_CHAT_ID':'test'}):
            a=base(synthetic=False);render(a,self.out,telegram_enabled=True,telegram_sender=lambda *k:calls.append(1))
            b=base(synthetic=False);rec=b['auto_trigger']['validated_record'];rec['revision']=6
            rec['change_log'][-1]['event_id']='BAR:43'
            render(b,self.out,telegram_enabled=True,telegram_sender=lambda *k:calls.append(1))
        self.assertEqual(len(calls),2)
    def test_40_unknown_network_not_retried(self):
        attempts=[]
        def failing(*args):attempts.append(1);raise TimeoutError()
        with patch.dict('os.environ',{'TELEGRAM_BOT_TOKEN':'test','TELEGRAM_CHAT_ID':'test'}):
            a=render(base(synthetic=False),self.out,telegram_enabled=True,telegram_sender=failing)
            b=render(base(synthetic=False),self.out,telegram_enabled=True,telegram_sender=failing)
        self.assertEqual(a['delivery']['delivery_status'],'UNKNOWN')
        self.assertEqual(b['delivery']['delivery_status'],'DUPLICATE_SUPPRESSED')
        self.assertEqual(len(attempts),1)
    def test_41_m01_fail_no_alert(self):
        r=base(synthetic=False);r['monitor_quote_status']='UNAVAILABLE'
        with patch.dict('os.environ',{'TELEGRAM_BOT_TOKEN':'test','TELEGRAM_CHAT_ID':'test'}):
            out=render(r,self.out,telegram_enabled=True,telegram_sender=lambda *x:self.fail())
        self.assertEqual(out['payload']['decision'],'NO_TRADE')
    def test_42_after_outage_clears_old_signal(self):
        render(base(),self.out)
        r=base();r['monitor_connection_status']='DISCONNECTED'
        render(r,self.out)
        p=json.loads((self.out/'M15_MONITOR_SNAPSHOT.json').read_text())
        self.assertEqual(p['decision'],'NO_TRADE');self.assertIsNone(p['quote'])
        self.assertFalse(p['live_execution_allowed'])
    def test_43_not_a_bot_executor(self):
        for name in ('M10A_M15_ADAPTER.py','RUN_MT5_M10A_M15_READONLY.py','M15_SIGNAL_VIEWER.py'):
            s=(ROOT/name).read_text()
            self.assertNotIn('order_send(',s)
            self.assertNotIn('ImageGrab',s)
            self.assertNotIn('pyautogui',s)
    def test_44_full_report_18_sections(self):
        r=render(base(),self.out)
        self.assertIn('18. FINAL DECISION',(self.out/'M15_FULL_PL.txt').read_text())
    def test_45_alert_not_flagged_broker_fill(self):
        r=render(base(),self.out)
        p=r['payload'];self.assertFalse(p['broker_order_sent']);self.assertIsNone(p['submitted_order_id'])
    def test_46_cross_restart_outbox(self):
        hits=[]
        with patch.dict('os.environ',{'TELEGRAM_BOT_TOKEN':'test','TELEGRAM_CHAT_ID':'test'}):
            render(base(synthetic=False),self.out,telegram_enabled=True,telegram_sender=lambda *a:hits.append(1))
            # New function call simulates separate runner process, persistent DB retained.
            render(base(synthetic=False),self.out,telegram_enabled=True,telegram_sender=lambda *a:hits.append(1))
        self.assertEqual(hits,[1])


class ActualM10AtoM15Tests(unittest.TestCase):
    def test_47_real_reducer_to_m14_to_m15(self):
        import sys
        sys.path.insert(0,str(ROOT/'vendor'))
        from M10_AUTO_TRIGGER_TESTS import Fixture
        from RUN_MT5_AUTOMATIC_TRIGGER_READONLY import decision_from_auto
        f=Fixture();self.addCleanup(f.close)
        for i in range(4):
            if i:f.make(i)
            result=f.step()
        f.report.update({'analysis_id':'SYNTHETIC_BRIDGE_E2E','schema_version':'2.0.0',
          'research_only':True,'screen_capture_count':0,'visual_capture_enabled':False,
          'account_profile':'ZERO_SPREAD_DECLARED_UNVERIFIED',
          'monitor_connection_status':'CONNECTED','monitor_quote_status':'RECEIVED',
          'analysis_decision':'WAIT','intended_direction':'UNKNOWN',
          'execution_permission':'BLOCKED','live_execution_allowed':False,
          'broker_order_sent':False,'submitted_order_id':None,
          'broker_quote':{'source':'MT5_BROKER','symbol':'XAUUSD',
                         'source_timestamp':f.snap['as_of'],'bid':2750.,'ask':2750.},
          'auto_trigger':result})
        decision=decision_from_auto(f.report,result)
        self.assertEqual(decision['decision'],'LONG')
        f.report.update({'decision_result':decision,'analysis_decision':decision['decision'],
                         'intended_direction':decision['intended_direction']})
        payload,event,reason=convert(f.report)
        self.assertEqual(payload['decision'],'LONG')
        self.assertIn('CONFIRMED',event)
        self.assertFalse(payload['live_execution_allowed'])
    def test_48_indicator_context_six_timeframes(self):
        r=base()
        r['indicator_intelligence']={'snapshot_id':'SNAP:42','timeframes':{
           tf:{'status':'PASS','interpretation':{'market_direction':'UNKNOWN'},
                'indicators':{'ema_20':{'value':2700.},'rsi_14':{'value':52.}}}
           for tf in ('D1','H4','H1','M15','M5','M1')}}
        p,_,_=convert(r)
        self.assertEqual(len(p['indicator_timeframes']),6)
        self.assertEqual(p['indicator_timeframes']['H4']['indicators']['ema_20'],2700.)
    def test_49_indicator_data_mismatch_not_shown(self):
        r=base();r['indicator_intelligence']={'snapshot_id':'OTHER','timeframes':{
            'M1':{'status':'PASS','indicators':{'rsi_9':{'value':100}}}}}
        self.assertEqual(convert(r)[0]['indicator_timeframes'],{})
    def test_50_heartbeat_written(self):
        import datetime
        p,_,_=convert(base())
        t=datetime.datetime.fromisoformat(p['m15_published_at'].replace('Z','+00:00'))
        self.assertLess(abs((datetime.datetime.now(datetime.timezone.utc)-t).total_seconds()),3)

if __name__=='__main__':unittest.main()
