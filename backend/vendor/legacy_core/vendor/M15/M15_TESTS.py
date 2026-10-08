"""Synthetic/offline M15 security and formatting tests. No network, no MT5 orders."""
from __future__ import annotations
import copy
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import M15_REFERENCE_COMMUNICATION_ENGINE as e

ROOT=Path(__file__).resolve().parent
M14_EXAMPLE=ROOT/'M14_REFERENCE_SYNTHETIC_OUTPUT.json'

def base():return json.loads(M14_EXAMPLE.read_text(encoding='utf-8'))
def ctxt():return {'instrument_id':'XAUUSD','analysis_id':'SYNTHETIC_DEMO_NO_REAL_TRADES','snapshot_as_of':'2026-10-08T10:00:00+00:00','account_type':'ZERO_SPREAD',
  'quote':{'source':'MT5_PRIMARY','as_of':'2026-10-08T10:00:00+00:00','instrument_id':'XAUUSD','bid':2650.0,'ask':2650.0},
  'plan':{'price_source':'MT5_PRIMARY','as_of':'2026-10-08T10:00:00+00:00','instrument_id':'XAUUSD','entry':2650.0,'sl':2645.0,'tp1':2660.0,'tp2':2670.0,'tp3':None,'plan_status':'ILLUSTRATIVE'}}

class TestContract(unittest.TestCase):
    def test_reference_passes(self):
        p=e.compose(base(),ctxt());self.assertEqual(p['decision'],'LONG');self.assertFalse(p['live_execution_allowed'])
    def test_m14_untrusted_object(self):
        with self.assertRaises(e.ContractError):e.compose('bad')
    def test_missing_required(self):
        for k in e.M14_REQUIRED:
            with self.subTest(k=k):
                x=base();x.pop(k)
                with self.assertRaises(e.ContractError):e.compose(x)
    def test_bad_decisions(self):
        for dec in ('BUY','SELL','WATCH_CONDITIONAL','',None,1):
            with self.subTest(dec=dec):
                x=base();x['decision']=dec
                with self.assertRaises(e.ContractError):e.compose(x)
    def test_external_authorization_fails(self):
        mutations=[('execution_permission','AUTHORIZED'),('execution_permission','READY'),
                   ('execution_eligible',True),('live_execution_allowed',True),
                   ('submitted_order_id','123'),('order_actions',[{'action':'BUY'}]),('broker_order_sent',True)]
        for k,v in mutations:
            with self.subTest(k=k,v=v):
                x=base();x[k]=v
                with self.assertRaises(e.ContractError):e.compose(x)
    def test_flags_sources(self):
        mutations=[('data_source_policy','TV_PRIMARY'),('screenshot_capture_enabled',True),
                  ('visual_capture_enabled',True),('ocr_enabled',True)]
        for k,v in mutations:
            with self.subTest(k=k):
                x=base();x[k]=v
                with self.assertRaises(e.ContractError):e.compose(x)
    def test_no_market_feed_and_no_orders(self):
        src=(ROOT/'M15_REFERENCE_COMMUNICATION_ENGINE.py').read_text()
        self.assertNotIn('order_send(',src);self.assertNotIn('ImageGrab',src)
        self.assertNotIn('pyautogui',src)
    def test_decision_scope(self):
        x=base();x['decision_scope']='EXECUTION'
        with self.assertRaises(e.ContractError):e.compose(x)
    def test_schema_version(self):
        x=base();x['schema_version']='1.0.0'
        with self.assertRaises(e.ContractError):e.compose(x)
    def test_no_early_hallucinations(self):
        x=base();x.update(decision='EARLY_SETUP',signal_tier='EARLY',signal_validity='VALID_EARLY_SETUP',entry_trigger='NOT_CONFIRMED')
        with self.assertRaises(e.ContractError):e.compose(x,ctxt())
        c=ctxt();c['next_expected_event']='M5 BOS close';c['invalidation']='M5 close below low'
        y=e.compose(x,c);self.assertEqual(y['decision'],'EARLY_SETUP')
    def test_no_fake_confirms(self):
        for key,val in [('signal_tier','EARLY'),('entry_trigger','NOT_CONFIRMED'),('signal_validity','VALID_EARLY_SETUP'),('intended_direction','SHORT')]:
            with self.subTest(key=key):
                x=base();x[key]=val
                with self.assertRaises(e.ContractError):e.compose(x)
    def test_bad_tiers(self):
        x=base();x['signal_tier']='GOLD'
        with self.assertRaises(e.ContractError):e.compose(x)
    def test_bad_input_times(self):
        for stamp in (None,'2026-10-08T10:00:00','garbage',''):
            with self.subTest(stamp=stamp):
                x=base();x['as_of']=stamp
                with self.assertRaises(e.ContractError):e.compose(x)
    def test_utc_as_of(self):self.assertEqual(e.compose(base())['as_of'],'2026-10-08T10:00:00Z')
    def test_quote_not_from_tradingview(self):
        c=ctxt();c['quote']['source']='TRADINGVIEW'
        with self.assertRaises(e.ContractError):e.compose(base(),c)
    def test_quote_invalid(self):
        for bid,ask in [(2,1),(None,2),(0,1),('2',2),(2,float('nan'))]:
            with self.subTest(bid=bid,ask=ask):
                c=ctxt();c['quote'].update(bid=bid,ask=ask)
                with self.assertRaises(e.ContractError):e.compose(base(),c)
    def test_quote_future(self):
        c=ctxt();c['quote']['as_of']='2026-10-08T10:00:01+00:00'
        with self.assertRaises(e.ContractError):e.compose(base(),c)
    def test_quote_instrument(self):
        c=ctxt();c['quote']['instrument_id']='USDJPY'
        with self.assertRaises(e.ContractError):e.compose(base(),c)
    def test_zero_spread_not_zero_commission(self):
        p=e.compose(base(),ctxt());self.assertEqual(p['quote']['spread'],0.0)
        self.assertNotIn('commission',p['quote']);self.assertEqual(p['account_type'],'ZERO_SPREAD')
    def test_plan_invalid_price_source(self):
        c=ctxt();c['plan']['price_source']='TRADINGVIEW'
        with self.assertRaises(e.ContractError):e.compose(base(),c)
    def test_plan_future(self):
        c=ctxt();c['plan']['as_of']='2026-10-08T10:00:01Z'
        with self.assertRaises(e.ContractError):e.compose(base(),c)
    def test_plan_geometry(self):
        for k,v in [('sl',2652),('tp1',2640)]:
            with self.subTest(k=k):
                c=ctxt();c['plan'][k]=v
                with self.assertRaises(e.ContractError):e.compose(base(),c)
    def test_short_geometry(self):
        x=base();x['decision']='SHORT';x['intended_direction']='SHORT'
        c=ctxt();c['plan'].update(sl=2655,tp1=2640,tp2=2630)
        self.assertEqual(e.compose(x,c)['decision'],'SHORT')
        c['plan']['sl']=2645
        with self.assertRaises(e.ContractError):e.compose(x,c)
    def test_null_prices(self):
        c=ctxt();c['plan']['entry']=None;c['plan']['sl']=None;c['plan']['tp1']=None
        p=e.compose(base(),c);self.assertIsNone(p['plan']['entry'])
        self.assertIn('N/D',e.short_report(p))
    def test_probability_provenance(self):
        x=base();x['probabilities']={'p_long':{'value':.7}}
        with self.assertRaises(e.ContractError):e.compose(x)
        x['probabilities']['p_long'].update(method_id='p-v1',run_status='COMPLETED',evidence_ids=['provenance_ref'])
        self.assertAlmostEqual(e.compose(x)['probabilities']['p_long']['value'],.7)
    def test_no_fake_stats_from_null(self):
        self.assertIsNone(e.compose(base())['probabilities'])
        self.assertIn('N/D',e.full_report(e.compose(base())))
    def test_analysis_id(self):
        c=ctxt();c['analysis_id']='bad'
        with self.assertRaises(e.ContractError):e.compose(base(),c)
    def test_context_future(self):
        c=ctxt();c['snapshot_as_of']='2026-10-08T11:00:00Z'
        with self.assertRaises(e.ContractError):e.compose(base(),c)
    def test_instrument_empty(self):
        c=ctxt();c['instrument_id']=''
        with self.assertRaises(e.ContractError):e.compose(base(),c)
    def test_other_account_conflict(self):
        c=ctxt();c['account_type']='ECN'
        with self.assertRaises(e.ContractError):e.compose(base(),c)
    def test_setup_top_mismatch(self):
        c=ctxt();c['active_setups']=[{'setup_id':'other'}]
        with self.assertRaises(e.ContractError):e.compose(base(),c)
    def test_setup_collection_not_list(self):
        c=ctxt();c['active_setups']='bad'
        with self.assertRaises(e.ContractError):e.compose(base(),c)
    def test_safe_text_controls(self):
        self.assertEqual(e.clean_text('Hello\x00\x01  world\n\u202e'), 'Hello world')
    def test_report_no_execution(self):
        s=e.short_report(e.compose(base(),ctxt()));self.assertIn('BLOCKED',s)
        self.assertIn('NIE potwierdzenie',s);self.assertIn('MT5',s)
        self.assertNotIn('Wyślij BUY',s)
    def test_wait_report(self):
        x=base();x['decision']='WAIT';x['signal_tier']='NONE';x['entry_trigger']='UNKNOWN';x['signal_validity']='INSUFFICIENT_EVIDENCE';x['intended_direction']='NEUTRAL';x['top_setup_id']=None
        p=e.compose(x);self.assertIn('OCZEKIWANIE',e.short_report(p))
    def test_json_no_nan(self):
        c=ctxt();c['plan']['entry']=float('nan')
        p=e.compose(base(),c)
        self.assertIsNone(p['plan']['entry'])
        json.dumps(p,allow_nan=False)
    def test_prohibited_elevated_authorization_even_paper(self):
        for env in ('PAPER','DEMO','LIVE'):
            x=base();x['execution_environment']=env;x['execution_permission']='AUTHORIZED'
            with self.subTest(env=env), self.assertRaises(e.ContractError):e.compose(x)

class TestDelivery(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def test_outbox_queue_and_dedup(self):
        p=e.compose(base(),ctxt());db=e.Outbox(self.path/'o.db')
        a,fp=db.queue(p);b,_=db.queue(p)
        self.assertEqual((a,b),('QUEUED','DUPLICATE_SUPPRESSED'))
        self.assertEqual(db.get(fp)[0],'PENDING');db.close()
    def test_restart_dedup(self):
        p=e.compose(base(),ctxt());db=e.Outbox(self.path/'o.db');db.queue(p);db.close()
        db=e.Outbox(self.path/'o.db');self.assertEqual(db.queue(p)[0],'DUPLICATE_SUPPRESSED');db.close()
    def test_asof_new_no_alert(self):
        p=e.compose(base(),ctxt());q=copy.deepcopy(p);q['as_of']='2026-10-08T11:00:00Z'
        self.assertEqual(e.event_fingerprint(p),e.event_fingerprint(q))
    def test_changed_tier_new_alert(self):
        p=e.compose(base(),ctxt());q=copy.deepcopy(p);q['signal_tier']='A_PLUS'
        self.assertNotEqual(e.event_fingerprint(p),e.event_fingerprint(q))
    def test_unique_event_ids(self):
        p=e.compose(base(),ctxt());self.assertNotEqual(e.event_fingerprint(p,'001'),e.event_fingerprint(p,'002'))
    def test_no_order_submission_from_outbox(self):
        db=e.Outbox(self.path/'o.db');state,_=db.queue(e.compose(base()))
        self.assertEqual(state,'QUEUED');db.close()
    def test_atomic_monitor_json(self):
        out=self.path/'nested'/'snapshot.json';e.atomic_json(out,{'x':1});self.assertEqual(json.loads(out.read_text())['x'],1)
        e.atomic_json(out,{'x':2});self.assertEqual(json.loads(out.read_text())['x'],2)
    def test_db_only_first_claim(self):
        db=e.Outbox(self.path/'o.db');state,fp=db.queue(e.compose(base()))
        self.assertTrue(db.begin_send(fp));self.assertFalse(db.begin_send(fp));db.result(fp,'UNKNOWN')
        self.assertEqual(db.get(fp)[0],'UNKNOWN');db.close()
    def test_unknown_status_no_auto_retry(self):
        db=e.Outbox(self.path/'o.db');_,fp=db.queue(e.compose(base()))
        db.begin_send(fp);db.result(fp,'UNKNOWN');self.assertFalse(db.begin_send(fp));db.close()
    def test_delivered_has_message_id(self):
        db=e.Outbox(self.path/'o.db');_,fp=db.queue(e.compose(base()))
        db.begin_send(fp);db.result(fp,'DELIVERED',123)
        row=db.con.execute('select remote_message_id from alerts').fetchone();self.assertEqual(row[0],'123');db.close()
    def test_no_alert_wait_no_event_id(self):
        x=base();x['decision']='WAIT';x['signal_tier']='NONE';x['entry_trigger']='UNKNOWN';x['signal_validity']='INSUFFICIENT_EVIDENCE';x['top_setup_id']=None
        p=e.compose(x);db=e.Outbox(self.path/'o.db')
        self.assertEqual(db.queue(p)[0],'SUPPRESSED_NON_SIGNAL')
        self.assertEqual(db.queue(p,'event-01')[0],'QUEUED');db.close()
    def test_safe_no_secrets_logs(self):
        p=e.compose(base());self.assertNotIn('TELEGRAM_BOT_TOKEN',json.dumps(p))
    def test_missing_telegram_credentials(self):
        with self.assertRaises(e.ContractError):e.send_telegram('hello','','')
    def test_telegram_text_limit(self):
        with self.assertRaises(e.ContractError):e.send_telegram('X'*5000,'token','42')
    def test_cli_offline_default(self):
        out=self.path/'out'
        code=e.run_cli(['--m14',str(M14_EXAMPLE),'--output-dir',str(out)])
        self.assertEqual(code,0)
        self.assertTrue((out/'M15_EXPORT_FULL.json').exists())
        self.assertTrue((out/'M15_MONITOR_SNAPSHOT.json').exists())
        self.assertTrue((out/'M15_DELIVERY_OUTBOX.sqlite3').exists())
        self.assertEqual(json.loads((out/'M15_LAST_DELIVERY_STATUS.json').read_text())['delivery_status'],'QUEUED')
    def test_cli_repeated_no_new_alert(self):
        out=self.path/'out';a=['--m14',str(M14_EXAMPLE),'--output-dir',str(out)]
        self.assertEqual(e.run_cli(a),0);self.assertEqual(e.run_cli(a),0)
        self.assertEqual(json.loads((out/'M15_LAST_DELIVERY_STATUS.json').read_text())['delivery_status'],'DUPLICATE_SUPPRESSED')
    def test_cli_no_outdir_on_invalid(self):
        x=base();x['execution_permission']='AUTHORIZED'
        src=self.path/'bad.json';src.write_text(json.dumps(x))
        out=self.path/'out'
        self.assertEqual(e.run_cli(['--m14',str(src),'--output-dir',str(out)]),2)
        self.assertFalse(out.exists())
    def test_cli_network_not_called_without_optin(self):
        with patch.object(e,'send_telegram',side_effect=AssertionError('network!')):
            self.assertEqual(e.run_cli(['--m14',str(M14_EXAMPLE),'--output-dir',str(self.path/'o')]),0)
    def test_cli_optin_missing_env_stays_queued(self):
        with patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN':'','TELEGRAM_CHAT_ID':''}):
            out=self.path/'out'
            self.assertEqual(e.run_cli(['--m14',str(M14_EXAMPLE),'--output-dir',str(out),'--telegram-send']),0)
            self.assertEqual(json.loads((out/'M15_LAST_DELIVERY_STATUS.json').read_text())['delivery_status'],'SUPPRESSED_SYNTHETIC')
    def test_cli_optin_fake_sender(self):
        with patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN':'synthetic','TELEGRAM_CHAT_ID':'123'}):
            with patch.object(e,'send_telegram',return_value=77) as send:
                out=self.path/'out';src=self.path/'nonsynthetic.json';x=base();x['analysis_id']='LOCAL_TEST_NO_BROKER';src.write_text(json.dumps(x))
                self.assertEqual(e.run_cli(['--m14',str(src),'--output-dir',str(out),'--telegram-send']),0)
                self.assertEqual(send.call_count,1)
                self.assertEqual(json.loads((out/'M15_LAST_DELIVERY_STATUS.json').read_text())['delivery_status'],'DELIVERED')
    def test_cli_network_error_unknown(self):
        with patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN':'synthetic','TELEGRAM_CHAT_ID':'123'}):
            with patch.object(e,'send_telegram',side_effect=TimeoutError('possible sent')) as send:
                out=self.path/'out';src=self.path/'nonsynthetic.json';x=base();x['analysis_id']='LOCAL_TEST_NO_BROKER';src.write_text(json.dumps(x))
                a=['--m14',str(src),'--output-dir',str(out),'--telegram-send']
                self.assertEqual(e.run_cli(a),0);self.assertEqual(e.run_cli(a),0)
                self.assertEqual(send.call_count,1)
                self.assertEqual(json.loads((out/'M15_LAST_DELIVERY_STATUS.json').read_text())['delivery_status'],'DUPLICATE_SUPPRESSED')
    def test_cli_context_not_invented(self):
        out=self.path/'out';self.assertEqual(e.run_cli(['--m14',str(M14_EXAMPLE),'--output-dir',str(out)]),0)
        p=json.loads((out/'M15_EXPORT_FULL.json').read_text())
        self.assertIsNone(p['instrument_id']);self.assertIsNone(p['plan'])
        self.assertFalse(p['live_execution_allowed'])
    def test_source_m14_unchanged_hash(self):
        b=M14_EXAMPLE.read_bytes();e.compose(base(),ctxt());self.assertEqual(M14_EXAMPLE.read_bytes(),b)

if __name__=='__main__':unittest.main(verbosity=2)

# Additional standalone parameterised regression cases.
class TestProbabilityContract(unittest.TestCase):
    def test_probability_invalid_sum(self):
        x=base()
        x['probabilities']={k:{'value':v,'method_id':'x','run_status':'COMPLETED','evidence_ids':['ev'], 'horizon_id':'M5:10','label_spec_id':'L1'} for k,v in [('p_long',.7),('p_short',.6),('p_neutral',.1)]}
        with self.assertRaises(e.ContractError):e.compose(x)
    def test_probability_valid_sum(self):
        x=base()
        x['probabilities']={k:{'value':v,'method_id':'x','run_status':'COMPLETED','evidence_ids':['ev'], 'horizon_id':'M5:10','label_spec_id':'L1'} for k,v in [('p_long',.5),('p_short',.3),('p_neutral',.2)]}
        p=e.compose(x);self.assertAlmostEqual(p['probabilities']['p_long']['value'],.5)
    def test_probability_horizon_mismatch(self):
        x=base()
        x['probabilities']={k:{'value':v,'method_id':'x','run_status':'COMPLETED','evidence_ids':['ev'], 'horizon_id':k,'label_spec_id':'L1'} for k,v in [('p_long',.5),('p_short',.3),('p_neutral',.2)]}
        with self.assertRaises(e.ContractError):e.compose(x)
    def test_probability_bad_values(self):
        for v in (-.01,1.1,float('nan'),float('inf')):
            with self.subTest(v=v):
                x=base();x['probabilities']={'p_long':{'value':v,'method_id':'x','run_status':'COMPLETED','evidence_ids':['ev']}}
                with self.assertRaises(e.ContractError):e.compose(x)
    def test_no_trade_cannot_be_confirmed(self):
        x=base();x['decision']='NO_TRADE'
        with self.assertRaises(e.ContractError):e.compose(x)
