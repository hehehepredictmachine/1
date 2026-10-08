"""Offline tests for persisted profile selection and MT5-mocked runner."""
import copy
from datetime import datetime,timezone
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from BRIDGE_TESTS import FakeMT5
from M07_M03E_PROFILE_TESTS import make_fixture
from M07_M03E_PROFILE_DETECTOR import read_config,discover,hashed
from M07_M03E_PROFILE_RUNTIME import ResearchPlanLock
from RUN_MT5_OPERATIONAL_PROFILES_READONLY import research_selection,publish_one,run,ROOT
from M02I_M01_M02_LIVE_BRIDGE import IntegratedReadOnlyMonitor
from M03E_M10_PIPELINE import load

class TestPersistentProfiles(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db=Path(self.tmp.name)/'lock.sqlite'
        self.s,self.m,self.e=make_fixture();self.c=read_config()
        self.lock=ResearchPlanLock(self.db,self.c)
    def test_01_lock_keeps_plan(self):
        p,r=self.lock.choose(self.s,self.m,self.e,'MVP')
        self.assertEqual(p['profile_name'],'MVP')
        q,r2=self.lock.choose(self.s,self.m,self.e,'MVP')
        self.assertEqual(q,p);self.assertEqual(r2['candidate_status'],'RESEARCH_HYPOTHESIS_LOCKED')
    def test_02_restart_keeps_plan(self):
        p,_=self.lock.choose(self.s,self.m,self.e,'MVP')
        lk=ResearchPlanLock(self.db,self.c)
        q,_=lk.choose(self.s,self.m,self.e,'MVP')
        self.assertEqual(p['frozen_plan_hash'],q['frozen_plan_hash'])
    def test_03_pending_blocks_even_if_locked(self):
        self.lock.choose(self.s,self.m,self.e,'MVP')
        self.s['analysis_gate']['status']='PENDING'
        q,_=self.lock.choose(self.s,self.m,self.e,'MVP')
        self.assertIsNone(q)
    def test_04_changed_spec_blocks_lock(self):
        p,_=self.lock.choose(self.s,self.m,self.e,'MVP')
        c=copy.deepcopy(self.c);c['profiles']['MVP']['entry_stage_atr'][1]=0.31
        lk=ResearchPlanLock(self.db,c)
        q,d=lk.choose(self.s,self.m,self.e,'MVP')
        self.assertIsNone(q)
        self.assertIn('SAME_EVENT_NEW_RULES_REQUIRES_NEW_RESEARCH_EVENT',d['reason_codes'])
    def test_05_broken_hash_replaced(self):
        self.lock.choose(self.s,self.m,self.e,'MVP')
        with sqlite3.connect(self.db) as conn:
            conn.execute("UPDATE research_plan_lock SET plan_hash='CORRUPT'")
        q,_=self.lock.choose(self.s,self.m,self.e,'MVP')
        self.assertTrue(q and q['profile_name']=='MVP')
    def test_06_mitigated_fvg_no_reuse(self):
        self.lock.choose(self.s,self.m,self.e,'MVP')
        self.e['timeframes']['M15']['fvgs'][0]['mitigated_fraction']=1.
        q,_=self.lock.choose(self.s,self.m,self.e,'MVP')
        self.assertIsNone(q)
    def test_07_orderless_mode(self):
        q,_=self.lock.choose(self.s,self.m,self.e,'AUTO')
        self.assertFalse(q['execution_enabled'])
    def test_08_separate_modes(self):
        p,_=self.lock.choose(self.s,self.m,self.e,'MVP')
        q,_=self.lock.choose(self.s,self.m,self.e,'SMC')
        self.assertNotEqual(p['strategy_id'],q['strategy_id'])
    def test_09_invalid_reversed_on_new_bar(self):
        p,_=self.lock.choose(self.s,self.m,self.e,'MVP')
        self.s['candles_by_tf']['M15'][-1]['close']=p['invalidation']['condition']['level']-0.1
        self.s['candles_by_tf']['M15'][-1]['low']=min(self.s['candles_by_tf']['M15'][-1]['low'],
                                                    self.s['candles_by_tf']['M15'][-1]['close']-0.2)
        q,_=self.lock.choose(self.s,self.m,self.e,'MVP')
        self.assertIsNone(q)
    def test_10_restart_cannot_forge_m08_approval(self):
        p,_=self.lock.choose(self.s,self.m,self.e,'MVP')
        self.assertFalse(p.get('m08_registry_approved'))
    def test_11_unknown_market_without_plan(self):
        self.m['structural_direction']='UNKNOWN'
        q,_=self.lock.choose(self.s,self.m,self.e,'AUTO')
        self.assertIsNone(q)
    def test_12_malformed_old_json_replaced(self):
        self.lock.choose(self.s,self.m,self.e,'MVP')
        with sqlite3.connect(self.db) as conn:
            conn.execute("UPDATE research_plan_lock SET plan_json='invalid'")
        q,d=self.lock.choose(self.s,self.m,self.e,'MVP')
        self.assertIsNone(q)
        self.assertIn('LOCK_CORRUPT_REQUIRES_MANUAL_REVIEW',d['reason_codes'])
    def test_13_source_not_via_screenshot(self):
        p,_=self.lock.choose(self.s,self.m,self.e,'SMC')
        self.assertNotIn('image',p)
    def test_14_does_not_claim_oos(self):
        p,_=self.lock.choose(self.s,self.m,self.e,'SMC')
        self.assertIn('LEVELS_PROVISIONAL_NOT_OPTIMIZED',p['limitations'])
    def test_15_stable_event_id(self):
        p,_=self.lock.choose(self.s,self.m,self.e,'MVP')
        q,_=self.lock.choose(self.s,self.m,self.e,'MVP')
        self.assertEqual(p['created_event_id'],q['created_event_id'])
    def test_23_fvg_zone_revision_blocks_same_event(self):
        self.lock.choose(self.s,self.m,self.e,'MVP')
        self.e['timeframes']['M15']['fvgs'][0]['zone_high']=1.02*self.e['timeframes']['M15']['fvgs'][0]['zone_high']
        q,d=self.lock.choose(self.s,self.m,self.e,'MVP')
        self.assertIsNone(q)
        self.assertIn('SAME_EVENT_NEW_RULES_REQUIRES_NEW_RESEARCH_EVENT',d['reason_codes'])
    def test_24_profile_mode_does_not_advance_m10(self):
        p,_=self.lock.choose(self.s,self.m,self.e,'MVP')
        self.assertFalse(p.get('execution_enabled'))
        self.assertNotIn('broker_order_id',p)

class TestMockedTerminal(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.mt5=FakeMT5(datetime.now(timezone.utc))
        self.mon=IntegratedReadOnlyMonitor(self.mt5,'XAUUSD',load(ROOT/'BRIDGE_SETTINGS.example.json'),
            load(ROOT/'vendor/M02/M02_PROFILE.example.json'),load(ROOT/'vendor/M02I/M02I_PROFILE_MT5_TIMEFRAMES_v1.1.json'),
            self.root/'raw.json')
        self.assertTrue(self.mon.start(None));self.addCleanup(self.mon.disconnect,'UNIT_TEST')
    def args(self):
        return SimpleNamespace(symbol='XAUUSD',mode='AUTO',dxy_symbol=None,terminal_path=None,
           duration_seconds=0.001,bars=None,profiles=str(ROOT/'OPERATIONAL_PROFILES_v1.json'),
           settings=str(ROOT/'BRIDGE_SETTINGS.example.json'),
           m02_profile=str(ROOT/'vendor/M02/M02_PROFILE.example.json'),
           m02i_profile=str(ROOT/'vendor/M02I/M02I_PROFILE_MT5_TIMEFRAMES_v1.1.json'),
           upstream_file=str(self.root/'upstream.json'),discovery_file=str(self.root/'discovery.json'),
           raw_monitor_file=str(self.root/'raw2.json'),state_db=str(self.root/'m10.sqlite'),
           profile_db=str(self.root/'research.sqlite'),output_dir=str(self.root/'M15'),telegram_send=False)
    def test_16_no_false_candidate_from_normal_mock(self):
        plan,decision=research_selection(self.mon,'AUTO',ResearchPlanLock(self.root/'research.sqlite'))
        self.assertIsNone(plan)
    def test_17_publish_no_order(self):
        a=self.args();o=publish_one(self.mon,a,ResearchPlanLock(self.root/'research.sqlite'))
        upstream=json.loads(Path(a.upstream_file).read_text())
        self.assertEqual(o['execution_permission'],'BLOCKED')
        self.assertFalse(upstream['broker_order_sent'])
    def test_18_output_exists(self):
        a=self.args();publish_one(self.mon,a,ResearchPlanLock(self.root/'research.sqlite'))
        self.assertTrue(Path(a.discovery_file).exists())
    def test_19_disconnect_no_stale_signal(self):
        a=self.args();l=ResearchPlanLock(self.root/'research.sqlite')
        publish_one(self.mon,a,l)
        self.mon.disconnect('SIMULATED_DISCONNECT')
        o=publish_one(self.mon,a,l)
        self.assertEqual(o['execution_permission'],'BLOCKED')
        self.assertIn(o['analysis_decision'],('NO_TRADE','WAIT'))
    def test_20_run_lifecycle_without_telegram(self):
        a=self.args()
        self.mon.disconnect('BEFORE_RUN')
        self.assertEqual(run(a,self.mt5),0)
        result=json.loads(Path(a.discovery_file).read_text())
        self.assertEqual(result['execution_permission'],'BLOCKED')
    def test_21_missing_mt5_no_evidence(self):
        self.mon.disconnect('TEST')
        plan,discovery=research_selection(self.mon,'MVP',ResearchPlanLock(self.root/'research.sqlite'))
        self.assertIsNone(plan)
        self.assertIn('MT5_DISCONNECTED',discovery['reason_codes'])
    def test_22_all_core_optional_volume_not_required(self):
        a=self.args();o=publish_one(self.mon,a,ResearchPlanLock(self.root/'research.sqlite'))
        self.assertFalse(json.loads(Path(a.discovery_file).read_text())['selected_profile'])

if __name__=='__main__': unittest.main(verbosity=2)
