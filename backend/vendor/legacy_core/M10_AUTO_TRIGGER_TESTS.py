"""Offline M10 auto confirmation tests: synthetic examples, no MT5 broker, no orders."""
import copy
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from M10_AUTO_TRIGGER_CONFIRM import (advance, check_bar, check_rule, matched, rules_valid,
                                        _safe_report,canonical_hash)
from M10_REFERENCE_ENGINE import SQLiteSetupStore
from M03E_M10_PIPELINE import construct_early
from RUN_MT5_AUTOMATIC_TRIGGER_READONLY import decision_from_auto, publish as auto_publish
from BRIDGE_TESTS import FakeMT5, CFG, M02, M02I
from M02I_M01_M02_LIVE_BRIDGE import IntegratedReadOnlyMonitor

BASE=datetime(2026,10,8,12,0,tzinfo=timezone.utc)
iso=lambda x: x.isoformat()

class Fixture:
    def __init__(self, direction='LONG'):
        self.tmp=tempfile.TemporaryDirectory();self.db=str(Path(self.tmp.name)/'m10.sqlite')
        self.index=0;self.make(0)
        self.plan={
            'intended_direction':'LONG','strategy_id':'XAU-S14','version':'1.0.0-RESEARCH',
            'spec_hash':'synthetic-spec-1','horizon_id':'M5','setup_tf':'M5',
            'created_event_id':'synthetic-origin','structural_evidence_id':'M02:S:1',
            'location_evidence_id':'M03:POI:1','liquidity_evidence_id':'M03:LIQ:1',
            'next_expected_event':{'timeframe':'M5','condition':self.rule(),
                                   'failure_condition':'CLOSE_BELOW_INVALIDATION'},
            'invalidation':{'timeframe':'M5','condition':self.rule(op='<',level=2700.0),'rule':'CLOSED_BAR'},
            'lifecycle_rules':{
                'qualification':self.rule(level=2740.0),
                'arming':{**self.rule(level=2745.0),'field':'high'},
                'trigger':{**self.rule(level=2750.0),'field':'high'},
                'confirmation':self.rule(level=2750.5)}}
        if direction=='SHORT':
            self.plan['intended_direction']='SHORT'
            for j,k in enumerate(('qualification','arming','trigger','confirmation')):
                self.plan['lifecycle_rules'][k]['operator']='<'
                self.plan['lifecycle_rules'][k]['level']=2760.+j
            self.plan['invalidation']['condition']['operator']='>'
            self.plan['invalidation']['condition']['level']=2800.
            self.plan['next_expected_event']['condition']['operator']='<'
            self.plan['next_expected_event']['condition']['level']=2760.
        self.market={'evidence_ids':['M02:S:1'],'status':'PASS'}
        self.m03={'evidence_ids':['M03:POI:1','M03:LIQ:1'],
                  'early_evidence':{'status':'EARLY_SETUP'}, 'status':'PASS'}
        self.candidate,_=construct_early(self.m03,self.market,self.snap,self.plan)
        assert self.candidate
        self.router={'module_id':'M09','analysis_pool':[
            {'setup_id':self.candidate['setup_id'],'analytical_eligible':True,'strategy_id':'XAU-S14',
             'version':'1.0.0-RESEARCH','spec_hash':self.plan['spec_hash'],'horizon_id':'M5'}],
             'horizon_conflicts':[],'execution_permission':'BLOCKED'}
        self.init_store()

    def rule(self,op='>',level=2700.0):
        return {'timeframe':'M5','field':'close','operator':op,'level':level,
                'reference_evidence_id':'M03:POI:1','requires_closed_bar':True}

    def make(self,i,close=2751.0):
        self.index=i;asof=BASE+timedelta(minutes=5*i)
        opened=asof-timedelta(minutes=5)
        self.bar={'bar_open_utc':iso(opened),'close_confirmed_at':iso(asof),
                  'available_at':iso(asof),'open':close-0.1,'high':close+0.1,
                  'low':close-0.2,'close':close, 'source_id':'MT5:TEST',
                  'evidence_id':'MT5:M5:'+str(i),'timeframe':'M5','bar_state':'CLOSED',
                  'instrument_id':'XAUUSD','exact_symbol':'XAUUSD','price_basis':'BID'}
        self.snap={'schema_version':'2.0.0','snapshot_id':'SNAP:'+str(i),'as_of':iso(asof),
                   'exact_symbol':'XAUUSD','instrument_id':'XAUUSD','candles_by_tf':{'M5':[self.bar]},
                   'analysis_gate':{'status':'PASS_WITH_LIMITATIONS'},
                   'local_audit':{'source_hash':'HASH:'+str(i)}}
        self.quote={'bid':2750.,'ask':2750.,'source':'MT5_PRIMARY',
                    'symbol':'XAUUSD','source_timestamp':iso(asof)}
        self.clock=asof
        if hasattr(self,'report'):
            self.report.update({'as_of':self.snap['as_of'],'snapshot_id':self.snap['snapshot_id'],
                         'data_audit':self.snap['local_audit']})
    def init_store(self):
        core={key:{'evidence_id':f'ev:{j}','source':'MT5_PRIMARY','evidence_status':'VERIFIED',
             'available_at':self.snap['as_of'],'snapshot_id':self.snap['snapshot_id'],
             'instrument_id':'XAUUSD'} for j,key in enumerate((
              'structural_advantage','meaningful_location','liquidity_context','development_path','known_invalidation'))}
        pkt={'schema_version':'2.0.0','data_source_policy':'MT5_PRIMARY_TV_SUPPLEMENTAL_NO_SCREENSHOTS',
             'screenshot_capture_enabled':False,'as_of':self.snap['as_of'],
             'data_snapshot':{'snapshot_id':self.snap['snapshot_id'],'instrument_id':'XAUUSD',
                              'as_of':self.snap['as_of'],'analysis_gate':'PASS_WITH_LIMITATIONS'},
             'setup':{**self.candidate,'core_evidence':core,'created_at':iso(BASE-timedelta(minutes=15))},
             'router_result':self.router,
             'events':[{'event_id':'EARLY:1','type':'CORE_READY','source':'MT5_PRIMARY',
                        'instrument_id':'XAUUSD','snapshot_id':self.snap['snapshot_id'],
                        'evidence_status':'VERIFIED','available_at':iso(BASE-timedelta(minutes=10))}],
             'runtime':{'status':'HEALTHY'}}
        st=SQLiteSetupStore(self.db)
        try:r=st.apply(pkt)
        finally:st.close()
        assert r['setup']['state']=='EARLY_SETUP'
        self.report={'snapshot_id':self.snap['snapshot_id'],'as_of':self.snap['as_of'],
             'data_gate':'PASS_WITH_LIMITATIONS','data_audit':self.snap['local_audit'],
             'market_evidence':self.m03,'market_state':self.market,
             'router_result':self.router,'m10_result':r,'setup_state':'EARLY_SETUP'}

    def step(self):
        with patch('M10_AUTO_TRIGGER_CONFIRM.audit',return_value=self.snap):
            return advance(self.report,self.snap,self.quote,self.plan,self.db,
                           now=self.clock,direct_mt5=True,connected=True)
    def close(self): self.tmp.cleanup()

class TestAutoTrigger(unittest.TestCase):
    def setUp(self):self.f=Fixture();self.addCleanup(self.f.close)
    def test_01_ready_fixture(self):self.assertTrue(self.f.candidate)
    def test_02_rule_valid(self):
        self.assertIsNotNone(rules_valid(self.f.plan,self.f.candidate,self.f.market,self.f.m03)[0])
    def test_03_early_to_qualified(self):
        r=self.f.step();self.assertEqual(r['setup_state'],'QUALIFIED');self.assertEqual(r['event_type'],'QUALIFY')
    def test_04_only_once_per_bar(self):
        a=self.f.step();b=self.f.step()
        self.assertEqual(b['evaluation'],'DUPLICATE_SKIPPED');self.assertEqual(b['setup_state'],a['setup_state'])
    def test_05_all_states_four_bars(self):
        states=[]
        for i in range(4):
            if i:self.f.make(i)
            states.append(self.f.step()['setup_state'])
        self.assertEqual(states,['QUALIFIED','ARMED','TRIGGERED','CONFIRMED'])
    def test_06_no_order_even_confirmed(self):
        r=None
        for i in range(4):
            if i:self.f.make(i)
            r=self.f.step()
        self.assertEqual(r['execution_permission'],'BLOCKED')
        self.assertFalse(r['live_execution_allowed']);self.assertEqual(r['order_actions'],[])
    def test_07_restart_idempotent(self):
        self.f.step();r=self.f.step();self.assertEqual(r['reason_codes'],['NO_MATERIAL_CHANGE'])
    def test_08_rule_hash_mutation_blocks(self):
        self.f.step();self.f.make(1)
        self.f.plan['lifecycle_rules']['trigger']['level']=2701.
        r=self.f.step();self.assertIn('FROZEN_LIFECYCLE_RULES_CHANGED',r['reason_codes'][0])
    def test_09_bar_revision_blocks(self):
        self.f.step();self.f.bar['close']+=0.02
        self.assertIn('HISTORICAL_BAR_REVISION',self.f.step()['reason_codes'][0])
    def test_10_invalidation_priority(self):
        self.f.make(0,close=2699.)
        r=self.f.step();self.assertEqual(r['setup_state'],'INVALIDATED');self.assertEqual(r['event_type'],'INVALIDATE')
    def test_11_terminal_irreversible(self):
        self.f.make(0,close=2699.);self.f.step();self.f.make(1,close=2751.)
        r=self.f.step();self.assertEqual(r['setup_state'],'INVALIDATED')
    def test_12_no_plan(self):
        self.assertEqual(advance(self.f.report,self.f.snap,self.f.quote,None,self.f.db)['status'],'PENDING')
    def test_13_no_db(self):
        self.assertEqual(advance(self.f.report,self.f.snap,self.f.quote,self.f.plan,None)['status'],'PENDING')
    def test_14_no_m10_candidate(self):
        p=copy.deepcopy(self.f.report);p['m10_result']=None
        self.assertEqual(advance(p,self.f.snap,self.f.quote,self.f.plan,self.f.db)['status'],'PENDING')
    def test_15_missing_rule(self):
        self.f.plan['lifecycle_rules'].pop('trigger')
        self.assertIn('INVALID_OR_UNANCHORED',self.f.step()['reason_codes'][0])
    def test_16_unauthorized_reference(self):
        self.f.plan['lifecycle_rules']['trigger']['reference_evidence_id']='FABRICATED'
        self.assertIn('INVALID_OR_UNANCHORED',self.f.step()['reason_codes'][0])
    def test_17_confirmation_close_only(self):
        self.f.plan['lifecycle_rules']['confirmation']['field']='high'
        self.assertIn('INVALID_OR_UNANCHORED',self.f.step()['reason_codes'][0])
    def test_18_conflicting_horizon(self):
        self.f.router['horizon_conflicts']=[{'horizon_id':'M5','setup_ids':[self.f.candidate['setup_id']]}]
        self.assertIn('M09_CRITICAL_HORIZON_CONFLICT',self.f.step()['reason_codes'][0])
    def test_19_unselected_m09(self):
        self.f.router['analysis_pool']=[]
        self.assertIn('M09_ANALYSIS_ELIGIBILITY',self.f.step()['reason_codes'][0])
    def test_20_invalid_price_basis(self):
        self.f.bar['price_basis']='MID'
        self.assertIn('BAR_NOT_BROKER_BID',self.f.step()['reason_codes'][0])
    def test_21_candle_forming_rejected(self):
        self.f.bar['bar_state']='FORMING'
        self.assertIn('BAR_NOT_CLOSED',self.f.step()['reason_codes'][0])
    def test_22_future_candle_rejected(self):
        self.f.bar['available_at']=iso(self.f.clock+timedelta(seconds=1))
        self.assertIn('BAR_UNAVAILABLE',self.f.step()['reason_codes'][0])
    def test_23_bad_ohlc_rejected(self):
        self.f.bar['low']=self.f.bar['high']+1
        self.assertIn('INVALID_OHLC',self.f.step()['reason_codes'][0])
    def test_24_false_bool_price(self):
        self.f.plan['lifecycle_rules']['trigger']['level']=True
        self.assertIn('INVALID_OR_UNANCHORED',self.f.step()['reason_codes'][0])
    def test_25_not_numeric_price(self):
        self.f.bar['close']='NAN'
        self.assertIn('INVALID_OHLC',self.f.step()['reason_codes'][0])
    def test_26_requires_core(self):
        self.f.m03['early_evidence']['status']='CANDIDATE'
        self.assertIn('FIVE_CORE',self.f.step()['reason_codes'][0])
    def test_27_neutral_state_not_invented(self):
        for j,x in enumerate(('qualification','arming','trigger','confirmation')):
            self.f.plan['lifecycle_rules'][x]['level']=2800.+j
        self.assertEqual(self.f.step()['evaluation'],'RULE_NOT_MET')
    def test_28_plan_change_after_no_event(self):
        self.f.step();self.f.make(1)
        self.f.plan['lifecycle_rules']['trigger']['operator']='>='
        self.assertIn('FROZEN_LIFECYCLE_RULES_CHANGED',self.f.step()['reason_codes'][0])
    def test_29_development_before_qualification(self):
        self.f.plan['lifecycle_rules']['development']=self.f.rule()
        r=self.f.step();self.assertEqual(r['setup_state'],'SETUP_FORMING')
        self.f.make(1);self.assertEqual(self.f.step()['setup_state'],'QUALIFIED')
    def test_30_trigger_order(self):
        for i in range(4):
            if i:self.f.make(i)
            r=self.f.step()
        changes=[x['reason'] for x in r['validated_record']['change_log']]
        self.assertEqual(changes[-4:],['QUALIFY','ARM','TRIGGER','CONFIRM'])
    def test_31_trigger_event_linkage(self):
        for i in range(4):
            if i:self.f.make(i)
            r=self.f.step()
        self.assertIn(r['validated_record']['trigger_event_id'],r['validated_record']['event_hashes'])
    def test_32_m14_only_confirms_after_m10(self):
        p=None
        for i in range(4):
            if i:self.f.make(i)
            p=self.f.step()
        self.f.report['snapshot_id']=self.f.snap['snapshot_id']
        self.f.report['as_of']=self.f.snap['as_of']
        self.f.report['data_gate']='PASS_WITH_LIMITATIONS'
        d=decision_from_auto(self.f.report,p)
        self.assertEqual(d['decision'],'LONG');self.assertEqual(d['execution_permission'],'BLOCKED')
    def test_33_m14_no_confirm_before_final(self):
        p=self.f.step();d=decision_from_auto(self.f.report,p)
        self.assertNotEqual(d['decision'],'LONG');self.assertFalse(d['live_execution_allowed'])
    def test_34_invalid_snap_hash(self):
        self.f.report['data_audit']=copy.deepcopy(self.f.report['data_audit'])
        self.f.report['data_audit']['source_hash']='DIFFERENT'
        self.assertIn('M01_SNAPSHOT_OR_AUDIT',self.f.step()['reason_codes'][0])
    def test_35_local_audit_pending(self):
        self.f.snap['analysis_gate']['status']='PENDING'
        self.assertIn('M01_SNAPSHOT_OR_AUDIT',self.f.step()['reason_codes'][0])
    def test_36_zero_spread_does_not_authorize(self):
        self.assertEqual(self.f.step()['execution_permission'],'BLOCKED')
    def test_37_unknown_timeframe_rule(self):
        self.f.plan['lifecycle_rules']['arming']['timeframe']='M1'
        self.assertIn('INVALID_OR_UNANCHORED',self.f.step()['reason_codes'][0])
    def test_38_duplicate_candidate_ref(self):
        self.f.plan['location_evidence_id']='BAD'
        self.assertIn('FIVE_CORE',self.f.step()['reason_codes'][0])
    def test_39_rule_comparators(self):
        for op,value,expect in [('<',2700.,False),('<=',2751.,True),('>=',2751.,True),('>',2800.,False)]:
            self.assertEqual(matched(self.f.rule(op,value),self.f.bar),expect)
    def test_40_same_bar_cannot_double_promote(self):
        first=self.f.step();second=self.f.step()
        self.assertEqual(first['setup_state'],'QUALIFIED');self.assertEqual(second['setup_state'],'QUALIFIED')
    def test_42_duplicate_rules_not_allowed(self):
        self.f.plan['lifecycle_rules']['confirmation']=copy.deepcopy(self.f.plan['lifecycle_rules']['qualification'])
        self.assertIn('REUSED_STAGE_CONDITION',self.f.step()['reason_codes'][0])
    def test_43_wrong_long_trigger_direction(self):
        self.f.plan['lifecycle_rules']['trigger']['operator']='<'
        self.assertIn('STAGE_DIRECTION_CONTRADICTS',self.f.step()['reason_codes'][0])
    def test_44_wrong_invalidation_direction(self):
        self.f.plan['invalidation']['condition']['operator']='>'
        self.assertIn('INVALIDATION_DIRECTION',self.f.step()['reason_codes'][0])
    def test_45_same_bar_core_ready_no_promotion(self):
        # Separate CORE_READY and QUALIFY observations even if created_at is older.
        con=sqlite3.connect(self.f.db)
        try:
            rec=json.loads(con.execute('SELECT record_json FROM setup_state').fetchone()[0])
            for ch in rec['change_log']:
                if ch.get('reason')=='CORE_READY':ch['available_at']=self.f.snap['as_of']
            con.execute('UPDATE setup_state SET record_json=?',(json.dumps(rec),))
            con.commit()
        finally:con.close()
        r=self.f.step()
        self.assertEqual(r['setup_state'],'EARLY_SETUP')
        self.assertIn('BAR_NOT_AFTER_CORE_READY',r['reason_codes'])
    def test_46_confirm_bar_requires_new_close(self):
        for i in range(3):
            if i:self.f.make(i)
            res=self.f.step()
        self.assertEqual(res['setup_state'],'TRIGGERED')
        self.assertNotEqual(self.f.step()['setup_state'],'CONFIRMED')
        self.f.make(3)
        self.assertEqual(self.f.step()['setup_state'],'CONFIRMED')
    def test_47_duplicate_rule_only_separate_refs(self):
        self.f.plan['lifecycle_rules']['qualification']=copy.deepcopy(self.f.plan['lifecycle_rules']['arming'])
        self.assertIn('REUSED_STAGE_CONDITION',self.f.step()['reason_codes'][0])
    def test_48_short_proceeds_only_after_independent_bars(self):
        f=Fixture('SHORT');self.addCleanup(f.close)
        stages=[]
        for i in range(4):
            if i:f.make(i,close=2751.)
            stages.append(f.step()['setup_state'])
        self.assertEqual(stages,['QUALIFIED','ARMED','TRIGGERED','CONFIRMED'])
    def test_49_short_m14_remains_blocked(self):
        f=Fixture('SHORT');self.addCleanup(f.close)
        for i in range(4):
            if i:f.make(i)
            r=f.step()
        d=decision_from_auto(f.report,r)
        self.assertEqual(d['decision'],'SHORT')
        self.assertFalse(d['live_execution_allowed'])
    def test_50_real_legacy_bridge_no_plan_has_no_trade(self):
        now=datetime(2026,10,8,12,30,tzinfo=timezone.utc)
        mt=FakeMT5(now)
        with tempfile.TemporaryDirectory() as td:
            m=IntegratedReadOnlyMonitor(mt,'XAUUSD',copy.deepcopy(CFG),copy.deepcopy(M02),
                  copy.deepcopy(M02I),Path(td)/'raw.json',clock=lambda:mt.now,session_id='AUTO-SMOKE')
            self.assertTrue(m.start())
            try:
                out=auto_publish(m,Path(td)/'output.json',str(Path(td)/'state.sqlite'))
                self.assertEqual(out['execution_permission'],'BLOCKED')
                self.assertEqual(out['auto_trigger']['reason_codes'],['NO_FROZEN_STRATEGY_PLAN'])
                self.assertNotIn(out['analysis_decision'],('LONG','SHORT'))
            finally:m.disconnect()
    def test_51_actual_m01_without_attested_source_cannot_confirm(self):
        from M01_AUDIT import audit
        t=datetime(2026,10,8,12,30,tzinfo=timezone.utc)
        mt=FakeMT5(t)
        with tempfile.TemporaryDirectory() as td:
            m=IntegratedReadOnlyMonitor(mt,'XAUUSD',copy.deepcopy(CFG),copy.deepcopy(M02),
                  copy.deepcopy(M02I),Path(td)/'raw.json',clock=lambda:mt.now,session_id='AUTO-AUDIT')
            self.assertTrue(m.start())
            try:
                packet=audit(m.snapshot,m.quote,collected_directly=False,connected=False,now=t)
                self.assertEqual(packet['analysis_gate']['status'],'PENDING')
            finally:m.disconnect()
    def test_52_bars_skipped_fail_closed(self):
        self.f.step();self.f.make(3)
        self.assertIn('UNREPLAYED_CLOSED_BAR_GAP',self.f.step()['reason_codes'][0])
    def test_53_example_plan_does_not_signal(self):
        self.f.plan['example_only']=True
        self.assertIn('EXAMPLE_STRATEGY',self.f.step()['reason_codes'][0])
    def test_41_no_data_gate(self):
        self.f.report['data_gate']='PENDING'
        self.assertIn('M01_OR_M03E',self.f.step()['reason_codes'][0])

if __name__=='__main__':unittest.main()
