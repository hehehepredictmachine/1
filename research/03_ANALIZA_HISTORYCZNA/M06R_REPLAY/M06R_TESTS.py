"""Offline tests for historical replay; no real MT5, trading or broker profit claims."""
import copy,csv,json,math,tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
from M06R_HISTORICAL_REPLAY import (TF,ORDER,MODE,ReplayError,parse_time,stamp,fnum,
    load_csv,load_bundle,checkpoint,HistoricalLifecycle,run_replay,export_result,digest)
from M06R_EXPORT_MT5_ALL_TIMEFRAMES import export
from M06R_MAKE_SYNTHETIC_DEMO import make
from M07_M03E_PROFILE_TESTS import make_fixture
from M07_M03E_PROFILE_DETECTOR import discover

START=datetime(2025,1,1,tzinfo=timezone.utc)

def csv_make(d,tf='M5',n=50,symbol='XAUUSD'):
    p=Path(d)/(tf+'.csv')
    with p.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=['symbol','time_utc','open','high','low','close','bar_state','tick_volume','available_at_utc'])
        w.writeheader()
        for i in range(n):
            now=START+timedelta(seconds=TF[tf]*i)
            w.writerow({'symbol':symbol,'time_utc':stamp(now),'open':100+i/10,'high':101+i/10,
                        'low':99+i/10,'close':100+i/10,'bar_state':'CLOSED','tick_volume':90,
                        'available_at_utc':stamp(now+timedelta(seconds=TF[tf]))})
    return p

def rewrite(p,mutate):
    with p.open(encoding='utf-8') as f:r=list(csv.DictReader(f))
    mutate(r)
    with p.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=r[0].keys());w.writeheader();w.writerows(r)

class TestInput(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
    def test_timezone_required(self):
        with self.assertRaises(ReplayError):parse_time('2025-01-01T00:00:00')
    def test_timezone_utc(self):self.assertEqual(stamp(parse_time('2025-01-01T01:00:00+01:00')),'2025-01-01T00:00:00Z')
    def test_nonfinite(self):
        with self.assertRaises(ReplayError):fnum('nan')
    def test_infinite(self):
        with self.assertRaises(ReplayError):fnum('inf')
    def test_missing_file(self):
        with self.assertRaises(ReplayError):load_csv(Path(self.temp.name)/'missing.csv','M1','XAUUSD')
    def test_valid_m5(self):self.assertEqual(len(load_csv(csv_make(self.temp.name),'M5','XAUUSD')),50)
    def test_provenance_not_live(self):
        b=load_csv(csv_make(self.temp.name),'M5','XAUUSD')[0]
        self.assertIn('UNVERIFIED',b['source_id'])
    def test_wrong_symbol(self):
        p=csv_make(self.temp.name)
        with self.assertRaises(ReplayError):load_csv(p,'M5','XAUUSDm')
    def test_wrong_tf(self):
        with self.assertRaises(ReplayError):load_csv(csv_make(self.temp.name),'W1','XAUUSD')
    def test_forming_bar(self):
        p=csv_make(self.temp.name)
        rewrite(p,lambda r:r[0].update({'bar_state':'FORMING'}))
        with self.assertRaises(ReplayError):load_csv(p,'M5','XAUUSD')
    def test_duplicate_bar(self):
        p=csv_make(self.temp.name)
        rewrite(p,lambda r:r[1].update({'time_utc':r[0]['time_utc']}))
        with self.assertRaises(ReplayError):load_csv(p,'M5','XAUUSD')
    def test_rollback(self):
        p=csv_make(self.temp.name)
        rewrite(p,lambda r:r[1].update({'time_utc':'2020-01-01T00:00:00Z'}))
        with self.assertRaises(ReplayError):load_csv(p,'M5','XAUUSD')
    def test_negative_volume(self):
        p=csv_make(self.temp.name)
        rewrite(p,lambda r:r[0].update({'tick_volume':'-1'}))
        with self.assertRaises(ReplayError):load_csv(p,'M5','XAUUSD')
    def test_zero_price(self):
        p=csv_make(self.temp.name)
        rewrite(p,lambda r:r[0].update({'open':'0'}))
        with self.assertRaises(ReplayError):load_csv(p,'M5','XAUUSD')
    def test_high_below_close(self):
        p=csv_make(self.temp.name)
        rewrite(p,lambda r:r[0].update({'high':'1'}))
        with self.assertRaises(ReplayError):load_csv(p,'M5','XAUUSD')
    def test_delayed_availability(self):
        p=csv_make(self.temp.name,n=2)
        rewrite(p,lambda r:r[0].update({'available_at_utc':stamp(START+timedelta(minutes=6))}))
        rows=load_csv(p,'M5','XAUUSD');self.assertEqual(stamp(rows[0]['available']),stamp(START+timedelta(minutes=6)))
    def test_premature_availability(self):
        p=csv_make(self.temp.name)
        rewrite(p,lambda r:r[0].update({'available_at_utc':stamp(START+timedelta(minutes=1))}))
        with self.assertRaises(ReplayError):load_csv(p,'M5','XAUUSD')
    def test_missing_columns(self):
        p=Path(self.temp.name)/'M5.csv';p.write_text('time_utc,close\n2025-01-01,10\n')
        with self.assertRaises(ReplayError):load_csv(p,'M5','XAUUSD')
    def test_full_bundle(self):
        for tf in ORDER:csv_make(self.temp.name,tf,n=45)
        self.assertEqual(len(load_bundle(self.temp.name)),6)
    def test_bundle_missing_one(self):
        for tf in ORDER[:-1]:csv_make(self.temp.name,tf,n=45)
        with self.assertRaises(ReplayError):load_bundle(self.temp.name)

class TestPointInTime(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        for tf in ORDER:csv_make(self.temp.name,tf,n=50)
        self.bundle=load_bundle(self.temp.name)
    def test_does_not_include_forming(self):
        at=START+timedelta(minutes=100)
        snap=checkpoint(at,self.bundle,'XAUUSD',40,50)
        self.assertEqual(len(snap['candles_by_tf']['M5']),20)
    def test_new_closed_bar_available(self):
        t=START+timedelta(minutes=105)
        self.assertEqual(len(checkpoint(t,self.bundle,'XAUUSD',40,50)['candles_by_tf']['M5']),21)
    def test_m1_later_not_visible(self):
        t=START+timedelta(minutes=10)
        seq=checkpoint(t,self.bundle,'XAUUSD',40,50)['candles_by_tf']['M1']
        self.assertLessEqual(max(parse_time(b['available_at']) for b in seq),t)
    def test_warmup_pending(self):
        at=START+timedelta(minutes=250)
        self.assertEqual(checkpoint(at,self.bundle,'XAUUSD',40,50)['analysis_gate']['status'],'PENDING')
    def test_not_broker_certified(self):
        s=checkpoint(START+timedelta(days=52),self.bundle,'XAUUSD',40,50)
        self.assertFalse(s['data_gates'][1]['status']=='PASS')
        self.assertTrue(s['replay_only'])
    def test_no_execution(self):
        s=checkpoint(START+timedelta(days=52),self.bundle,'XAUUSD',40,50)
        self.assertEqual(s['execution_permission'],'BLOCKED')
    def test_no_fake_d1(self):
        b={k:v for k,v in self.bundle.items() if k!='D1'}
        with self.assertRaises(ReplayError):run_replay(b,min_closed=40)
    def test_window_constraints(self):
        with self.assertRaises(ReplayError):checkpoint(START,self.bundle,'XAUUSD',40,39)
    def test_exact_time_id_deterministic(self):
        t=START+timedelta(days=51)
        self.assertEqual(checkpoint(t,self.bundle,'XAUUSD',40,50)['snapshot_id'],checkpoint(t,self.bundle,'XAUUSD',40,50)['snapshot_id'])

class TestLifecycle(unittest.TestCase):
    def setUp(self):
        self.snap,self.market,self.m03=make_fixture()
        self.plan=discover(self.snap,self.market,self.m03,mode='MVP')['selected_plan']
        self.assertIsNotNone(self.plan)
        self.life=HistoricalLifecycle(ttl=12)
        self.assertTrue(self.life.accept(self.plan,self.snap,self.market,self.m03))
    def bar(self,level=None,jump=1):
        prev=self.snap['candles_by_tf']['M15'][-1]
        new=copy.deepcopy(prev)
        when=parse_time(prev['bar_open_utc'])+timedelta(minutes=15*jump)
        close=max(x['level'] for x in self.plan['lifecycle_rules'].values())+20 if level is None else level
        new.update({'bar_open_utc':stamp(when),'close_confirmed_at':stamp(when+timedelta(minutes=15)),
                    'available_at':stamp(when+timedelta(minutes=15)), 'open':close,
                    'high':close+2,'low':close-2,'close':close,'evidence_id':'MT5:TEST:'+stamp(when)})
        self.snap['candles_by_tf']['M15'].append(new)
        self.snap['as_of']=new['available_at']
        return new
    def test_creation(self):self.assertEqual(self.life.active['MVP']['state'],'EARLY_SETUP')
    def test_creation_logged(self):self.assertEqual(self.life.transitions[0]['event_type'],'DISCOVER')
    def test_no_duplicate_early(self):self.assertFalse(self.life.accept(self.plan,self.snap,self.market,self.m03))
    def test_no_transition_same_bar(self):
        self.life.advance(self.snap);self.assertEqual(self.life.active['MVP']['state'],'EARLY_SETUP')
    def test_next_bar_develops(self):
        self.bar();self.life.advance(self.snap);self.assertEqual(self.life.active['MVP']['state'],'SETUP_FORMING')
    def test_lifecycle_all(self):
        for _ in range(5):self.bar();self.life.advance(self.snap)
        self.assertEqual(len(self.life.confirmed),1)
        self.assertEqual(self.life.transitions[-1]['state'],'CONFIRMED')
    def test_unique_bars_per_transition(self):
        for _ in range(5):self.bar();self.life.advance(self.snap)
        keys=[r['bar_open_utc'] for r in self.life.transitions]
        self.assertEqual(len(keys),len(set(keys)))
    def test_confirmation_no_fills(self):
        for _ in range(5):self.bar();self.life.advance(self.snap)
        x=self.life.confirmed[0]
        self.assertIsNone(x['entry']);self.assertEqual(x['fill_status'],'NOT_RUN')
    def test_invalidated_priority(self):
        inv=self.plan['invalidation']['condition']['level']
        self.bar(level=inv-1);self.life.advance(self.snap)
        self.assertEqual(self.life.transitions[-1]['state'],'INVALIDATED')
        self.assertEqual(len(self.life.confirmed),0)
    def test_time_gap_failclosed(self):
        self.bar(jump=2);self.life.advance(self.snap)
        self.assertEqual(self.life.transitions[-1]['state'],'GAP_REVIEW')
    def test_age_expire(self):
        l=HistoricalLifecycle(ttl=5);self.assertTrue(l.accept(self.plan,self.snap,self.market,self.m03))
        # Force level below qualify but above invalidation (setup remains forming)
        inv=self.plan['invalidation']['condition']['level']
        qual=self.plan['lifecycle_rules']['qualification']['level']
        between=(inv+qual)/2
        for _ in range(5):self.bar(level=between);l.advance(self.snap)
        self.assertEqual(l.transitions[-1]['state'],'EXPIRED')
    def test_different_profile_not_substituted(self):
        self.assertEqual(self.life.active['MVP']['strategy_id'],'XAU-S01')
    def test_execution_blocked(self):
        self.assertTrue(all(x['execution_permission']=='BLOCKED' for x in self.life.transitions))
    def test_restart_same_id(self):
        other=HistoricalLifecycle();self.assertTrue(other.accept(self.plan,self.snap,self.market,self.m03))
        self.assertEqual(other.transitions[0]['setup_id'],self.life.transitions[0]['setup_id'])
    def test_ttl_invalid(self):
        with self.assertRaises(ReplayError):HistoricalLifecycle(2)
    def test_long_confirmed_direction(self):
        for _ in range(5):self.bar();self.life.advance(self.snap)
        self.assertEqual(self.life.confirmed[0]['direction'],'LONG')

class TestReplay(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
    def test_research_incomplete_history(self):
        p=make(Path(self.tmp.name)/'demo',bars=60)
        b=load_bundle(p)
        r=run_replay(b,min_closed=45,max_steps=2)
        self.assertEqual(r['status'],'REPLAY_RESEARCH_COMPLETE')
    def test_invalid_mode(self):
        b={tf:[] for tf in ORDER}
        with self.assertRaises(ReplayError):run_replay(b,mode='INVALID')
    def test_invalid_steps(self):
        with self.assertRaises(ReplayError):run_replay({tf:[] for tf in ORDER},max_steps=0)
    def test_export_json_report(self):
        result={'mode':'AUTO','symbol':'XAUUSD','steps_analyzed':0,'steps_attempted':0,
                'research_setups_seen':0,'signal_count':0,'stage_transitions':[],'confirmed_signals':[]}
        export_result(result,Path(self.tmp.name)/'out')
        self.assertTrue((Path(self.tmp.name)/'out/M06R_REPLAY_REPORT.json').is_file())
    def test_consistent_empty_ledger(self):
        result={'mode':'AUTO','symbol':'XAUUSD','steps_analyzed':0,'steps_attempted':0,
                'research_setups_seen':0,'signal_count':0,'stage_transitions':[],'confirmed_signals':[]}
        out=Path(self.tmp.name)/'out';export_result(result,out)
        self.assertEqual((out/'M06R_CONFIRMED_SIGNALS.jsonl').read_text(),'')
    def test_no_profit_pretence(self):
        p=make(Path(self.tmp.name)/'demo2',bars=60)
        r=run_replay(load_bundle(p),min_closed=45,max_steps=1)
        self.assertEqual(r['strategy_net_performance']['status'],'NOT_RUN')
        self.assertFalse(r['live_execution_allowed'])
    def test_explicit_audit_limitation(self):
        p=make(Path(self.tmp.name)/'demo3',bars=60)
        r=run_replay(load_bundle(p),min_closed=45,max_steps=1)
        self.assertFalse(r['historical_data_certified'])
    def test_deterministic_replay(self):
        p=make(Path(self.tmp.name)/'demo4',bars=60)
        b=load_bundle(p)
        a=run_replay(b,min_closed=45,max_steps=1)
        c=run_replay(b,min_closed=45,max_steps=1)
        self.assertEqual(digest(a),digest(c))

class MockMT5:
    TIMEFRAME_D1=1;TIMEFRAME_H4=2;TIMEFRAME_H1=3;TIMEFRAME_M15=4;TIMEFRAME_M5=5;TIMEFRAME_M1=6
    def __init__(self):self.calls=[]
    def symbol_select(self,s,v):return s=='XAUUSD'
    def copy_rates_range(self,s,tf,start,end):
        self.calls.append(tf)
        t=datetime(2025,1,1,0,0,tzinfo=timezone.utc)
        return [{'time':int(t.timestamp()),'open':100.,'high':101.,'low':99.,'close':100.,
                 'tick_volume':100,'real_volume':0,'spread':10}]
    def last_error(self):return None

class TestExporter(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
    def test_no_order_api(self):
        mt=MockMT5()
        man=export(mt,'XAUUSD',datetime(2025,1,1,tzinfo=timezone.utc),
                   datetime(2025,1,2,tzinfo=timezone.utc),Path(self.tmp.name)/'out',
                   now=datetime(2025,1,5,tzinfo=timezone.utc))
        self.assertEqual(len(man['files']),6)
        self.assertEqual(set(mt.calls),{1,2,3,4,5,6})
        self.assertEqual(man['execution_permission'],'BLOCKED')
    def test_future_export_forbidden(self):
        with self.assertRaises(ReplayError):
            export(MockMT5(),'XAUUSD',START,START+timedelta(days=2),self.tmp.name,now=START+timedelta(days=1))
    def test_symbol_fail(self):
        with self.assertRaises(ReplayError):
            export(MockMT5(),'XAGUSD',START,START+timedelta(days=1),self.tmp.name,now=START+timedelta(days=3))
    def test_huge_time_forbidden(self):
        with self.assertRaises(ReplayError):
            export(MockMT5(),'XAUUSD',START,START+timedelta(days=501),self.tmp.name,now=START+timedelta(days=600))

if __name__=='__main__':unittest.main(verbosity=2)
