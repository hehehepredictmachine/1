import copy,json,tempfile,unittest
from pathlib import Path
from datetime import datetime,timedelta,timezone
from M06R_HISTORICAL_REPLAY import (ReplayError,ORDER,TF,parse_time,stamp,load_bundle,run_replay,HistoricalLifecycle,apply_macro_archive)
from M06R_MAKE_SYNTHETIC_DEMO import make
from M06R_EXPORT_MT5_ALL_TIMEFRAMES import export
from M07_M03E_PROFILE_TESTS import make_fixture
from M07_M03E_PROFILE_DETECTOR import discover

class MockMT5:
    TIMEFRAME_D1=1;TIMEFRAME_H4=2;TIMEFRAME_H1=3;TIMEFRAME_M15=4;TIMEFRAME_M5=5;TIMEFRAME_M1=6
    def symbol_select(self,*a):return True
    def copy_rates_range(self,s,tf,start,end):
        t=datetime(2025,1,1,tzinfo=timezone.utc)
        return [{'time':int(t.timestamp()),'open':100.,'high':102.,'low':99.,'close':101.,'tick_volume':22,'real_volume':0,'spread':10}]
    def last_error(self):return None

class IntegrityTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
    def export(self):
        return export(MockMT5(),'XAUUSD',datetime(2025,1,1,tzinfo=timezone.utc),
            datetime(2025,1,2,tzinfo=timezone.utc),Path(self.tmp.name)/'t',
            now=datetime(2025,1,10,tzinfo=timezone.utc))
    def test_manifest_pass(self):
        self.export();self.assertEqual(len(load_bundle(Path(self.tmp.name)/'t')),6)
    def test_integrity_tamper(self):
        self.export();file=Path(self.tmp.name)/'t'/'M1.csv';file.write_text(file.read_text()+'\n')
        with self.assertRaisesRegex(ReplayError,'SHA256'):
            load_bundle(Path(self.tmp.name)/'t')
    def test_manifest_symbol(self):
        self.export()
        with self.assertRaisesRegex(ReplayError,'SYMBOL'):load_bundle(Path(self.tmp.name)/'t','XAUUSDm')
    def test_manifest_count(self):
        self.export();f=Path(self.tmp.name)/'t'/'MT5_EXPORT_MANIFEST.json'
        x=json.loads(f.read_text());x['files']['D1']['bars']=5;f.write_text(json.dumps(x))
        with self.assertRaisesRegex(ReplayError,'COUNT'):load_bundle(Path(self.tmp.name)/'t')
    def test_manifest_missing_file(self):
        self.export();(Path(self.tmp.name)/'t'/'M1.csv').unlink()
        with self.assertRaisesRegex(ReplayError,'MISSING'):load_bundle(Path(self.tmp.name)/'t')
    def test_prevent_future_replay(self):
        d=make(Path(self.tmp.name)/'fake',60)
        b=load_bundle(d)
        r=run_replay(b,min_closed=45,max_steps=1,from_utc='2028-01-01T00:00:00Z')
        self.assertEqual(r['status'],'INSUFFICIENT_HISTORY')
    def test_bad_interval(self):
        b=load_bundle(make(Path(self.tmp.name)/'fake',60))
        with self.assertRaisesRegex(ReplayError,'INTERVAL'):
            run_replay(b,min_closed=45,max_steps=1,from_utc='2027-01-01T00:00:00Z',to_utc='2026-01-01T00:00:00Z')
    def test_real_window_replay(self):
        b=load_bundle(make(Path(self.tmp.name)/'fake',60))
        r=run_replay(b,min_closed=45,max_steps=1,
             from_utc='2026-09-01T11:00:00Z',to_utc='2026-09-01T12:00:00Z')
        self.assertGreaterEqual(r['steps_attempted'],1)
    def test_truncated(self):
        b=load_bundle(make(Path(self.tmp.name)/'fake',60))
        r=run_replay(b,min_closed=45,max_steps=1)
        self.assertTrue(r['truncated_by_step_limit'])
    def test_unverified_even_manifest(self):
        self.export();b=load_bundle(Path(self.tmp.name)/'t')
        r=run_replay(b,min_closed=40,max_steps=1)
        self.assertFalse(r['historical_data_certified'])

class MacroTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
    def base(self,at='2025-01-02T13:30:00Z'):
        return {'confirmed_signals':[{'signal_id':'id1','available_at':at,'signal_at':at,'direction':'LONG','execution_permission':'BLOCKED'}]}
    def events(self,known='2025-01-01T13:00:00Z',synthetic=False):
        event={'event_id':'cpi1','name':'CPI','type':'CALENDAR','scheduled_at':'2025-01-02T13:30:00Z',
                'known_at':known,'source_id':'BLS_CALENDAR','impact':'HIGH'}
        obj={'kind':'CURATED_HISTORICAL_EVENTS','data_provenance':'SYNTHETIC' if synthetic else 'USER_SUPPLIED',
             'events':[event]}
        p=Path(self.tmp.name)/'events.json';p.write_text(json.dumps(obj));return p
    def test_macro_unknown_without_archive(self):
        r=apply_macro_archive(self.base())
        self.assertEqual(r['confirmed_signals'][0]['macro_risk_status'],'UNKNOWN_PARTIAL_CALENDAR')
    def test_high_cpi_blocks(self):
        r=apply_macro_archive(self.base(),self.events())
        self.assertEqual(r['confirmed_signals'][0]['macro_risk_status'],'BLOCKED_BY_KNOWN_EVENT')
        self.assertEqual(r['macro_overlay']['blocked_confirmations'],1)
    def test_late_news_does_not_block(self):
        r=apply_macro_archive(self.base(),self.events(known='2025-01-03T00:00:00Z'))
        self.assertEqual(r['macro_overlay']['blocked_confirmations'],0)
        self.assertFalse(r['confirmed_signals'][0]['macro_execution_clearance'])
    def test_synthetic_news_does_not_certify(self):
        r=apply_macro_archive(self.base(),self.events(synthetic=True))
        self.assertEqual(r['macro_overlay']['blocked_confirmations'],0)
    def test_before_window_no_block(self):
        r=apply_macro_archive(self.base(at='2025-01-02T12:00:00Z'),self.events())
        self.assertEqual(r['macro_overlay']['blocked_confirmations'],0)
    def test_invalid_policy_rejected(self):
        f=Path(self.tmp.name)/'config.json';f.write_text(json.dumps({'frozen':False}))
        with self.assertRaisesRegex(ReplayError,'NOT_FROZEN'):
            apply_macro_archive(self.base(),self.events(),f)
    def test_events_missing_rejected(self):
        with self.assertRaises(FileNotFoundError):
            apply_macro_archive(self.base(),Path(self.tmp.name)/'missing.json')

class ShortLifecycle(unittest.TestCase):
    def setUp(self):
        self.snap,self.market,self.m03=make_fixture(direction='SHORT')
        self.plan=discover(self.snap,self.market,self.m03,mode='MVP')['selected_plan']
        self.assertIsNotNone(self.plan)
        self.life=HistoricalLifecycle(ttl=12)
        self.assertTrue(self.life.accept(self.plan,self.snap,self.market,self.m03))
    def newbar(self,level=None):
        prev=self.snap['candles_by_tf']['M15'][-1]
        time=parse_time(prev['bar_open_utc'])+timedelta(minutes=15)
        if level is None:level=min(x['level'] for x in self.plan['lifecycle_rules'].values())-5
        candle={**prev,'bar_open_utc':stamp(time),'close_confirmed_at':stamp(time+timedelta(minutes=15)),
                'available_at':stamp(time+timedelta(minutes=15)),'open':level,
                'high':level+1,'low':level-1,'close':level,'evidence_id':'MT5:SHORT:'+stamp(time)}
        self.snap['candles_by_tf']['M15'].append(candle);self.snap['as_of']=candle['available_at']
    def test_short_direction(self):self.assertEqual(self.life.active['MVP']['direction'],'SHORT')
    def test_short_confirmed(self):
        for _ in range(5):self.newbar();self.life.advance(self.snap)
        self.assertEqual(len(self.life.confirmed),1)
        self.assertEqual(self.life.confirmed[0]['direction'],'SHORT')
        self.assertIsNone(self.life.confirmed[0]['entry'])
    def test_short_invalidation(self):
        inv=self.plan['invalidation']['condition']['level'];self.newbar(level=inv+2)
        self.life.advance(self.snap)
        self.assertEqual(self.life.transitions[-1]['state'],'INVALIDATED')

if __name__=='__main__':unittest.main()
