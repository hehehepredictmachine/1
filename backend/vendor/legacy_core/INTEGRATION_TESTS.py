"""Offline mocked-MT5 unit and integration tests; no live, network, or orders."""
from __future__ import annotations
import copy
from datetime import datetime,timezone,timedelta
from pathlib import Path
import tempfile
import unittest
from BRIDGE_TESTS import FakeMT5,CFG,M02,M02I
from M02I_M01_M02_LIVE_BRIDGE import IntegratedReadOnlyMonitor
from M01_AUDIT import audit,GOOD
from M03E_M10_PIPELINE import analyze_snapshot,construct_early
from M10_REFERENCE_ENGINE import process as m10_process,SQLiteSetupStore
from RUN_MT5_READONLY_SIGNAL_LIFECYCLE import empty,publish

class TestAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t=datetime(2026,10,8,14,30,tzinfo=timezone.utc)
        cls.mt=FakeMT5(cls.t)
        cls.temp=tempfile.TemporaryDirectory()
        cls.bridge=IntegratedReadOnlyMonitor(cls.mt,'XAUUSD',CFG,M02,M02I,Path(cls.temp.name)/'legacy.json',clock=lambda:cls.mt.now,session_id='AUDIT')
        assert cls.bridge.start()
    @classmethod
    def tearDownClass(cls): cls.bridge.disconnect();cls.temp.cleanup()
    def aud(self,s=None,q=None,**kw):
        return audit(s if s is not None else self.bridge.snapshot,
                     q if q is not None else self.bridge.quote,
                     now=self.t,collected_directly=True,connected=True,**kw)
    def test_local_limited_pass(self):self.assertEqual(self.aud()['analysis_gate']['status'],'PASS_WITH_LIMITATIONS')
    def test_execution_always_pending(self):self.assertEqual(self.aud()['execution_gate']['status'],'PENDING')
    def test_zero_spread_is_not_zero_commission(self):self.assertNotIn('costs_verified_from_mt5',self.aud())
    def test_no_direct_mt5_pending(self):
        self.assertEqual(audit(self.bridge.snapshot,self.bridge.quote,now=self.t)['analysis_gate']['status'],'PENDING')
    def test_disconnected_pending(self):
        self.assertEqual(audit(self.bridge.snapshot,self.bridge.quote,now=self.t,collected_directly=True)['analysis_gate']['status'],'PENDING')
    def test_missing_quote_pending(self):self.assertEqual(self.aud(q={})['analysis_gate']['status'],'FAIL')
    def test_missing_quote_none_pending(self):
        self.assertEqual(audit(self.bridge.snapshot,None,now=self.t,collected_directly=True,connected=True)['analysis_gate']['status'],'PENDING')
    def test_negative_spread_fail(self):
        q=dict(self.bridge.quote,ask=self.bridge.quote['bid']-.1)
        self.assertEqual(self.aud(q=q)['analysis_gate']['status'],'FAIL')
    def test_stale_quote_pending(self):
        q=dict(self.bridge.quote,source_timestamp=(self.t-timedelta(seconds=40)).isoformat())
        self.assertEqual(self.aud(q=q)['analysis_gate']['status'],'PENDING')
    def test_future_quote_pending(self):
        q=dict(self.bridge.quote,source_timestamp=(self.t+timedelta(seconds=40)).isoformat())
        self.assertEqual(self.aud(q=q)['analysis_gate']['status'],'PENDING')
    def test_corrupt_ohlc_fail(self):
        s=copy.deepcopy(self.bridge.snapshot);s['candles_by_tf']['M5'][-1]['low']=s['candles_by_tf']['M5'][-1]['high']+10
        self.assertEqual(self.aud(s=s)['analysis_gate']['status'],'FAIL')
    def test_duplicate_bar_fail(self):
        s=copy.deepcopy(self.bridge.snapshot);s['candles_by_tf']['H1'].append(copy.deepcopy(s['candles_by_tf']['H1'][-1]))
        self.assertEqual(self.aud(s=s)['analysis_gate']['status'],'FAIL')
    def test_non_mt5_fail(self):
        s=copy.deepcopy(self.bridge.snapshot);s['candles_by_tf']['H1'][-1]['source_id']='TRADINGVIEW'
        self.assertEqual(self.aud(s=s)['analysis_gate']['status'],'FAIL')
    def test_broker_symbol_mismatch_fail(self):
        s=copy.deepcopy(self.bridge.snapshot);s['candles_by_tf']['H1'][-1]['exact_symbol']='GOLD'
        self.assertEqual(self.aud(s=s)['analysis_gate']['status'],'FAIL')
    def test_forming_candle_fail(self):
        s=copy.deepcopy(self.bridge.snapshot);s['candles_by_tf']['M1'][-1]['bar_state']='FORMING'
        self.assertEqual(self.aud(s=s)['analysis_gate']['status'],'FAIL')
    def test_future_bar_fail(self):
        s=copy.deepcopy(self.bridge.snapshot);s['candles_by_tf']['M1'][-1]['available_at']=(self.t+timedelta(minutes=5)).isoformat()
        self.assertEqual(self.aud(s=s)['analysis_gate']['status'],'FAIL')
    def test_short_history_pending(self):
        s=copy.deepcopy(self.bridge.snapshot);s['candles_by_tf']['M15']=s['candles_by_tf']['M15'][-15:]
        self.assertEqual(self.aud(s=s)['analysis_gate']['status'],'PENDING')
    def test_screenshot_ban(self):
        s=copy.deepcopy(self.bridge.snapshot);s['visual_capture_enabled']=True
        self.assertEqual(self.aud(s=s)['analysis_gate']['status'],'FAIL')
    def test_last_bar_too_old_pending(self):
        self.assertEqual(self.aud(max_last_bar_age_minutes={'D1':0.01})['analysis_gate']['status'],'PENDING')
    def test_readonly_packet_no_plan_wait(self):
        r=analyze_snapshot(self.bridge.snapshot,self.bridge.quote,direct_mt5=True,connected=True,runtime_clock=self.t)
        self.assertEqual(r['analysis_decision'],'WAIT');self.assertEqual(r['data_gate'],'PASS_WITH_LIMITATIONS')
        self.assertEqual(r['execution_permission'],'BLOCKED');self.assertIsNone(r['strategy_setup_id'])
    def test_readonly_untrusted_packet_no_live(self):
        r=analyze_snapshot(self.bridge.snapshot,self.bridge.quote,runtime_clock=self.t)
        self.assertEqual(r['analysis_decision'],'NO_TRADE');self.assertFalse(r['live_execution_allowed'])
    def test_data_broken_prevents_indicators(self):
        s=copy.deepcopy(self.bridge.snapshot);s['candles_by_tf']['M5'][-1]['high']=0
        r=analyze_snapshot(s,self.bridge.quote,direct_mt5=True,connected=True,runtime_clock=self.t)
        self.assertNotIn('indicator_intelligence',r)
    def test_same_snapshot_id(self):
        r=analyze_snapshot(self.bridge.snapshot,self.bridge.quote,direct_mt5=True,connected=True,runtime_clock=self.t)
        self.assertEqual(r['market_state']['snapshot_id'],r['indicator_intelligence']['snapshot_id'])
    def test_no_spurious_direction(self):
        r=analyze_snapshot(self.bridge.snapshot,self.bridge.quote,direct_mt5=True,connected=True,runtime_clock=self.t)
        self.assertNotIn(r['analysis_decision'],('LONG','SHORT','EARLY_SETUP'))
    def test_invalidation_requires_real_m03_evidence(self):
        d={'early_evidence':{'status':'EARLY_SETUP'},'evidence_ids':['M03:FVG:x','M03:LEVEL:y']}
        m={'evidence_ids':['M02:S:x'],'structural_direction':'BULLISH'}
        s=dict(self.bridge.snapshot)
        p={'strategy_id':'XAU-S01','version':'1.0.0','spec_hash':'SHA','horizon_id':'M5',
           'setup_tf':'M5','created_event_id':'EVENT','intended_direction':'LONG',
           'structural_evidence_id':'M02:S:x','location_evidence_id':'M03:FVG:x','liquidity_evidence_id':'M03:LEVEL:y',
           'next_expected_event':{'timeframe':'M5','condition':{'field':'close','operator':'>','level':2750.1,'requires_closed_bar':True,'reference_evidence_id':'M03:FVG:x'},'failure_condition':'below POI'},
           'invalidation':{'timeframe':'M5','condition':{'field':'close','operator':'<','level':2740.0,'requires_closed_bar':True,'reference_evidence_id':'M03:FVG:x'},'rule':'CLOSED_BAR'}}
        candidate,reasons=construct_early(d,m,s,p)
        self.assertIsNotNone(candidate);self.assertFalse(reasons)
        self.assertEqual(len(candidate['core_evidence']),5)
        invalid_rule=copy.deepcopy(p)
        invalid_rule['invalidation']['condition']='CENA SPADA'
        self.assertIsNone(construct_early(d,m,s,invalid_rule)[0])
        p['location_evidence_id']='INVALID'
        self.assertIsNone(construct_early(d,m,s,p)[0])
    def test_empty_when_disconnected(self):
        with tempfile.TemporaryDirectory() as td:
            self.bridge.connected=False
            try:
                r=publish(self.bridge,Path(td)/'out.json',str(Path(td)/'state.sqlite'))
                self.assertEqual(r['analysis_decision'],'NO_TRADE')
                self.assertIsNone(r['broker_quote'])
            finally:self.bridge.connected=True
    def test_m10_is_persisted_and_no_auto_fill(self):
        # Deliberately standalone synthetic M10 data; not asserted broker-valid.
        now=self.t.isoformat(); sid='SIM-1'
        core={key:{'evidence_id':f'ev{i}','evidence_status':'VERIFIED','instrument_id':'XAUUSD',
                   'snapshot_id':'SS1','source':'MT5_PRIMARY','available_at':now} for i,key in enumerate(('structural_advantage','meaningful_location','liquidity_context','development_path','known_invalidation'))}
        setup={'setup_id':sid,'strategy_id':'XAU-S01','version':'1.0.0','spec_hash':'A',
               'direction':'LONG','instrument_id':'XAUUSD','horizon_id':'M5','created_at':now,'core_evidence':core}
        event={'event_id':'E1','type':'CORE_READY','source':'MT5_PRIMARY','instrument_id':'XAUUSD',
               'snapshot_id':'SS1','evidence_status':'VERIFIED','available_at':now}
        pkt={'schema_version':'2.0.0','data_source_policy':'MT5_PRIMARY_TV_SUPPLEMENTAL_NO_SCREENSHOTS',
             'screenshot_capture_enabled':False,'as_of':now,'setup':setup,
             'data_snapshot':{'snapshot_id':'SS1','instrument_id':'XAUUSD','as_of':now,'analysis_gate':'PASS'},
             'router_result':{'module_id':'M09','analysis_pool':[{'setup_id':sid,'analytical_eligible':True}]},
             'events':[event],'runtime':{'status':'HEALTHY'}}
        with tempfile.TemporaryDirectory() as td:
            db=Path(td)/'m10.sqlite';store=SQLiteSetupStore(str(db))
            try:
                result=store.apply(pkt)
                self.assertEqual(result['setup']['state'],'EARLY_SETUP')
                self.assertEqual(result['execution_permission'],'BLOCKED')
                self.assertEqual(result['setup']['order_state'],'NONE')
                self.assertEqual(store.apply(pkt)['setup']['revision'],result['setup']['revision'])
            finally:store.close()

if __name__=='__main__':unittest.main()
