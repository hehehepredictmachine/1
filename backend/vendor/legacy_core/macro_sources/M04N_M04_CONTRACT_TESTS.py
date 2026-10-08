"""Tests M04N payload against unmodified candidate M04 calendar contract."""
import importlib.util
import unittest
import datetime as dt
import os
from pathlib import Path
import tempfile
from unittest.mock import patch
import json
import M04N_ENGINE as n
from M04N_TESTS import NOW,ICS,FED_RSS,GDELT,FakeHTTP

root=Path(__file__).parent
spec=importlib.util.spec_from_file_location('M04_REFERENCE_ENGINE',root/'vendor'/'M04_REFERENCE_ENGINE.py')
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class M04ContractTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=n.Store(Path(self.temp.name)/'state.sqlite')
        self.cfg=json.loads((root/'M04N_CONFIG.json').read_text())
        self.cfg['rss_feeds']=self.cfg['rss_feeds'][:1]
        self.cfg['gdelt_queries']=self.cfg['gdelt_queries'][:1]
        self.cfg['fred_enabled']=False
        self.cfg['fair_economy_calendars']=[]
        self.http=FakeHTTP({'press_monetary.xml':FED_RSS,'bls.ics':ICS,'api.gdeltproject.org':GDELT})
        self.profile={'event_windows_minutes':{'HIGH':{'pre':45,'post':45},'MEDIUM':{'pre':15,'post':15},'LOW':{'pre':5,'post':5},'EXTREME':{'pre':120,'post':120}}}
    def tearDown(self):self.store.close();self.temp.cleanup()
    def test_m04_high_risk_blocks(self):
        _,bridge=n.collect(self.cfg,self.store,self.http,NOW)
        out=mod.calendar_context(bridge['context_inputs']['macro_events'],NOW,self.profile,bridge['context_inputs']['calendar_coverage'])
        self.assertEqual(out['event_risk'],'HIGH')
        self.assertEqual(out['event_gate'],'BLOCKED')
    def test_m04_no_certified_calendar(self):
        _,bridge=n.collect(self.cfg,self.store,self.http,NOW)
        out=mod.calendar_context(bridge['context_inputs']['macro_events'],NOW+dt.timedelta(minutes=100),self.profile,bridge['context_inputs']['calendar_coverage'])
        self.assertEqual(out['event_gate'],'PENDING')
        self.assertEqual(out['event_risk'],'UNKNOWN')
    def test_m04_never_verified(self):
        _,bridge=n.collect(self.cfg,self.store,self.http,NOW)
        self.assertFalse(bridge['context_inputs']['calendar_coverage']['data_complete'])
    def test_m04_no_actual_or_forecast(self):
        _,bridge=n.collect(self.cfg,self.store,self.http,NOW)
        self.assertTrue(all(e['actual'] is None and e['forecast'] is None for e in bridge['context_inputs']['macro_events']))
    def test_no_execution_enable(self):
        _,bridge=n.collect(self.cfg,self.store,self.http,NOW)
        self.assertEqual(bridge['advisory']['execution_permission'],'BLOCKED')
        self.assertTrue(bridge['advisory']['does_not_override_m04_m11_m14'])
    def test_bls_failure_keeps_unknown(self):
        self.http.payloads['bls.ics']=ValueError('blocked')
        _,bridge=n.collect(self.cfg,self.store,self.http,NOW)
        self.assertEqual(mod.calendar_context(bridge['context_inputs']['macro_events'],NOW,self.profile,bridge['context_inputs']['calendar_coverage'])['event_gate'],'PENDING')
if __name__=='__main__':unittest.main()
