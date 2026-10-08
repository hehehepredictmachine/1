import csv,copy,json,tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import MagicMock
import M06H_RESEARCH_ENGINE as m
import M06H_ARCHIVE_M04N as arc
import M06H_EXPORT_MT5_READONLY as mt
UTC=timezone.utc

D='2025-01-02T13:30:00Z'; F='2025-01-04T13:30:00Z'

def config():
    return {'schema_version':'2.0.0','symbol':'XAUUSD','frozen':True,'research_only':True,'bar_period_seconds':60,
            'horizons_minutes':[5,15], 'guard_windows_minutes':{'HIGH':{'pre':30,'post':15},'EXTREME':{'pre':60,'post':30}},
            'control_blackout_minutes':120,'bootstrap_iterations':100,'bootstrap_seed':4,
            'min_final_oos_events':2,'min_final_oos_trades':1,
            'folds':[{'id':'dev','role':'DEVELOPMENT','start':'2025-01-01T00:00:00Z','end':'2025-01-03T00:00:00Z'},
                     {'id':'oos','role':'FINAL_OOS','start':'2025-01-03T00:00:00Z','end':'2025-01-07T00:00:00Z'}]}

def event(time=D,eid='cal1',known='2025-01-01T13:00:00Z',impact='HIGH',synthetic=False):
    return {'event_id':eid,'name':'Consumer Price Index','scheduled_at':m.instant(time),'known_at':m.instant(known),
            'impact_known_at':m.instant(known),'source_id':'BLS_CALENDAR','source_family':'OFFICIAL_OR_OTHER',
            'impact':impact,'type':'CALENDAR','synthetic':synthetic,'time_quality':'SCHEDULED_FROM_OFFICIAL_CALENDAR','provider_sources':['BLS_CALENDAR']}

def bars_for(days=6):
    out=[]
    for day in range(days):
        start=m.instant('2025-01-01T12:00:00Z')+timedelta(days=day)
        for idx in range(210):
            t=start+timedelta(minutes=idx)
            c=2000+day*.3+idx*.001 + (5 if day in (1,3) and idx>=90 else 0)
            out.append({'open_at':t,'close_at':t+timedelta(minutes=1),'open':c,'high':c+1,'low':c-1,'close':c})
    return out

def signal(time=F,ident='s1'):
    t=m.instant(time)
    return {'signal_id':ident,'strategy_version':'XAU-S01@0.0.1','spec_hash':'abc', 'source':'MT5_DERIVED','symbol':'XAUUSD',
            'bar_state':'CLOSED','signal_at':m.utc(t),'available_at':m.utc(t), 'feature_available_at':[m.utc(t-timedelta(minutes=1))],
            'side':'LONG','entry_type':'MARKET_NEXT_AVAILABLE_TICK','stop':1990.,'target':2010.,'lots':0.1,'max_hold_seconds':600}

def packet():
    t=m.instant(F)
    return {'schema_version':'2.0.0','run_id':'synthetic-only','data_snapshot':{'snapshot_id':'test1','dataset_id':'synthetic-1',
             'as_of':'2025-01-07T23:59:00Z','data_source_policy':m.__dict__.get('POLICY','MT5_PRIMARY_TV_SUPPLEMENTAL_NO_SCREENSHOTS'),
             'visual_capture_enabled':False,'analysis_gate':{'status':'PASS'}},
            'market_state':{'snapshot_id':'test1','as_of':'2025-01-07T23:59:00Z','analysis_gate':{'status':'PASS'}},
            'account':{'account_type':'ZERO_SPREAD','symbol':'XAUUSD','broker':'SYNTHETIC', 'account_id_hash':'synthetic',
                        'currency':'USD','commission_source':'SCENARIO_ONLY','commission_per_lot_side':3.,
                        'conversion_source':'SCENARIO_ONLY','money_per_price_unit_per_lot':100.,'slippage_price':0.01},
            'validation_profile':{'folds':config()['folds'],'acceptance_criteria_frozen':True,'forward_demo_required':True,
                                  'max_entry_wait_seconds':60,'bootstrap_iterations':100,'bootstrap_seed':5,'min_completed_oos_trades':1},
            'trial_ledger':[{'id':'trial1','spec_hash':'abc'}],
            'signals':[signal()],
            'ticks':[{'symbol':'XAUUSD','source_id':'MT5_SYNTHETIC','time':m.utc(t+timedelta(seconds=1)),'available_at':m.utc(t+timedelta(seconds=1)),
                      'bid':2000,'ask':2000.2},
                     {'symbol':'XAUUSD','source_id':'MT5_SYNTHETIC','time':m.utc(t+timedelta(minutes=1)),'available_at':m.utc(t+timedelta(minutes=1)),
                      'bid':2012,'ask':2012.2}]}

class TimeValidation(unittest.TestCase):
    def test_utc(self):self.assertEqual(m.utc(m.instant(D)),D)
    def test_timezone_shift(self):self.assertEqual(m.utc(m.instant('2025-01-02T14:30:00+01:00')),D)
    def test_no_naive(self):
        with self.assertRaises(m.ResearchError):m.instant('2025-01-02T13:30:00')
    def test_no_bad_date(self):
        with self.assertRaises(m.ResearchError):m.instant('abc')
    def test_float_nan(self):
        with self.assertRaises(m.ResearchError):m.number('nan','price')
    def test_float_inf(self):
        with self.assertRaises(m.ResearchError):m.number('inf','price')
    def test_config_ok(self):self.assertEqual(len(m.check_config(config())),2)
    def test_config_not_frozen(self):
        c=config();c['frozen']=False
        with self.assertRaises(m.ResearchError):m.check_config(c)
    def test_config_no_oos(self):
        c=config();c['folds'][1]['role']='DEVELOPMENT'
        with self.assertRaises(m.ResearchError):m.check_config(c)
    def test_config_overlap(self):
        c=config();c['folds'][1]['start']='2025-01-02T00:00:00Z'
        with self.assertRaises(m.ResearchError):m.check_config(c)
    def test_config_duplicate_id(self):
        c=config();c['folds'][1]['id']='dev'
        with self.assertRaises(m.ResearchError):m.check_config(c)
    def test_config_wrong_period(self):
        c=config();c['bar_period_seconds']=300
        with self.assertRaises(m.ResearchError):m.check_config(c)
    def test_config_duplicate_horizon(self):
        c=config();c['horizons_minutes']=[5,5]
        with self.assertRaises(m.ResearchError):m.check_config(c)
    def test_config_small_blackout(self):
        c=config();c['control_blackout_minutes']=1
        with self.assertRaises(m.ResearchError):m.check_config(c)

class BarInput(unittest.TestCase):
    def setUp(self):self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.path=Path(self.t.name)/'bars.csv'
    def create(self,rows):
        with self.path.open('w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=['symbol','time_utc','open','high','low','close','bar_state']);w.writeheader();w.writerows(rows)
    def row(self,**kw):return {'symbol':'XAUUSD','time_utc':'2025-01-02T13:29:00Z','open':'2000','high':'2001','low':'1999','close':'2000','bar_state':'CLOSED',**kw}
    def test_one_bar(self):self.create([self.row()]);self.assertEqual(len(m.read_bars(self.path,'XAUUSD')),1)
    def test_forming_forbidden(self):
        self.create([self.row(bar_state='FORMING')])
        with self.assertRaises(m.ResearchError):m.read_bars(self.path,'XAUUSD')
    def test_symbol_mismatch(self):
        self.create([self.row(symbol='EURUSD')])
        with self.assertRaises(m.ResearchError):m.read_bars(self.path,'XAUUSD')
    def test_unsorted(self):
        self.create([self.row(time_utc='2025-01-02T13:30:00Z'),self.row()])
        with self.assertRaises(m.ResearchError):m.read_bars(self.path,'XAUUSD')
    def test_duplicates(self):
        self.create([self.row(),self.row()])
        with self.assertRaises(m.ResearchError):m.read_bars(self.path,'XAUUSD')
    def test_invalid_ohlc(self):
        self.create([self.row(high='1995')])
        with self.assertRaises(m.ResearchError):m.read_bars(self.path,'XAUUSD')
    def test_zero_price(self):
        self.create([self.row(low='0')])
        with self.assertRaises(m.ResearchError):m.read_bars(self.path,'XAUUSD')
    def test_nonzero_second(self):
        self.create([self.row(time_utc='2025-01-02T13:29:30Z')])
        with self.assertRaises(m.ResearchError):m.read_bars(self.path,'XAUUSD')

class EventArchive(unittest.TestCase):
    def setUp(self):self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.root=Path(self.t.name)
    def fake(self):
        return {'module_id':'M04N','as_of':'2025-01-02T13:00:00Z','calendar':{'events':[{'event_id':'cpi-1','name':'CPI','scheduled_at':D,'available_at':'2025-01-01T11:00:00Z','impact':'HIGH','source_id':'FF_CALENDAR'}]},'news':{'recent':[]}}
    def test_single_snapshot_cannot_be_backdated(self):
        fn=self.root/'one.json';m.save_json(fn,self.fake())
        ev,mode=m.load_events(fn)
        self.assertEqual(mode,'SINGLE_SNAPSHOT_NO_HISTORICAL_CERTIFICATION')
        self.assertEqual(m.utc(ev[0]['known_at']),'2025-01-02T13:00:00Z')
    def test_archive_valid(self):
        fn=self.root/'one.json';m.save_json(fn,self.fake());ar=self.root/'archive.jsonl'
        result=arc.archive_snapshot(fn,ar,now='2025-01-02T13:05:00Z')
        self.assertEqual(result['status'],'APPENDED')
        ev,mode=m.load_events(ar)
        self.assertEqual(mode,'APPEND_ONLY_CAPTURED_SNAPSHOTS')
        self.assertEqual(m.utc(ev[0]['known_at']),'2025-01-02T13:05:00Z')
    def test_duplicate_archive_not_appended(self):
        fn=self.root/'one.json';m.save_json(fn,self.fake());ar=self.root/'a.jsonl'
        arc.archive_snapshot(fn,ar,'2025-01-02T13:05:00Z')
        self.assertEqual(arc.archive_snapshot(fn,ar,'2025-01-02T13:06:00Z')['records_appended'],0)
    def test_tampered_archive_rejected(self):
        fn=self.root/'one.json';m.save_json(fn,self.fake());ar=self.root/'a.jsonl'
        arc.archive_snapshot(fn,ar,'2025-01-02T13:05:00Z')
        contents=ar.read_text().replace('CPI','HACKED');ar.write_text(contents)
        with self.assertRaises(m.ResearchError):m.load_events(ar)
    def test_forged_previous_hash_rejected(self):
        fn=self.root/'one.json';m.save_json(fn,self.fake());ar=self.root/'a.jsonl'
        arc.archive_snapshot(fn,ar,'2025-01-02T13:05:00Z')
        row=json.loads(ar.read_text());row['prev_hash']='WRONG';ar.write_text(json.dumps(row)+'\n')
        with self.assertRaises(m.ResearchError):m.load_events(ar)
    def test_future_report_rejected(self):
        fn=self.root/'one.json';m.save_json(fn,self.fake())
        with self.assertRaises(m.ResearchError):arc.archive_snapshot(fn,self.root/'a.jsonl','2025-01-01T12:00:00Z')
    def test_capture_clock_rollback_rejected(self):
        fn=self.root/'one.json';m.save_json(fn,self.fake());ar=self.root/'a.jsonl'
        arc.archive_snapshot(fn,ar,'2025-01-02T13:05:00Z')
        obj=self.fake();obj['as_of']='2025-01-02T13:06:00Z';m.save_json(fn,obj)
        with self.assertRaises(m.ResearchError):arc.archive_snapshot(fn,ar,'2025-01-02T13:04:00Z')
    def test_news_without_confirmed_published_at_ignored(self):
        f=self.fake();f['news']['recent']=[{'event_id':'n1','time_quality':'UNKNOWN','first_seen_at':D,'impact':'HIGH'}]
        fn=self.root/'one.json';m.save_json(fn,f)
        ev,_=m.load_events(fn);self.assertEqual(len(ev),1)
    def test_curated_provenance_required(self):
        fn=self.root/'bad.json';m.save_json(fn,{'kind':'CURATED_HISTORICAL_EVENTS','events':[]})
        with self.assertRaises(m.ResearchError):m.load_events(fn)
    def test_duplicate_two_portals(self):
        obj=self.fake();ev=obj['calendar']['events'][0];obj['calendar']['events'].append({**ev,'event_id':'cpi-2','source_id':'MM_CALENDAR','name':'Consumer Price Index'})
        fn=self.root/'one.json';m.save_json(fn,obj)
        rows,_=m.load_events(fn)
        self.assertEqual(len(rows),1);self.assertEqual(sorted(rows[0]['provider_sources']),['FF_CALENDAR','MM_CALENDAR'])
    def test_revised_schedule_quarantined(self):
        base=event();changed=event(time='2025-01-02T13:35:00Z')
        self.assertEqual(m.dedupe_events([base,changed]),[])
    def test_late_impact_upgrade_cannot_retroactively_block(self):
        low=event(impact='LOW',known='2025-01-01T12:00:00Z')
        high=event(impact='HIGH',known='2025-01-02T13:32:00Z')
        merged=m.dedupe_events([low,high]);self.assertEqual(len(merged),1)
        self.assertFalse(m.macro_guard_decision(signal(time=D),merged,config()['guard_windows_minutes'])['blocked'])

class EventStudy(unittest.TestCase):
    def setUp(self):self.bars=bars_for();self.cfg=config();self.folds=m.check_config(self.cfg);self.events=[event(),event(time=F,eid='other',known='2025-01-03T14:00:00Z')]
    def test_moves_follow_synthetic_change(self):
        by={r['close_at']:r for r in self.bars}
        move,why=m.bar_move(m.instant(D),5,by,self.folds)
        self.assertIsNone(why);self.assertGreater(move,0)
    def test_oos_fold(self):self.assertEqual(m.fold_for(m.instant(F),self.folds)['id'],'oos')
    def test_gap_excluded(self):
        by={r['close_at']:r for r in self.bars};del by[m.instant(D)+timedelta(minutes=3)]
        move,reason=m.bar_move(m.instant(D),5,by,self.folds)
        self.assertIsNone(move);self.assertEqual(reason,'MISSING_OR_GAPPED_M1_BARS')
    def test_missing_prior_close(self):
        by={r['close_at']:r for r in self.bars};del by[m.instant(D)-timedelta(minutes=1)]
        move,reason=m.bar_move(m.instant(D),5,by,self.folds)
        self.assertEqual(reason,'MISSING_PRE_EVENT_CLOSE')
    def test_fold_boundary_purged(self):
        by={r['close_at']:r for r in self.bars}
        _,reason=m.bar_move(m.instant('2025-01-02T23:59:00Z'),5,by,self.folds)
        self.assertEqual(reason,'PURGED_FOLD_BOUNDARY')
    def test_event_study_has_both_folds(self):
        s=m.event_study(self.bars,self.events,self.cfg,self.folds)
        self.assertEqual({r['fold_role'] for r in s['event_rows']},{'DEVELOPMENT','FINAL_OOS'})
    def test_event_study_controls_matched(self):
        s=m.event_study(self.bars,self.events,self.cfg,self.folds)
        self.assertTrue(any(r['matched_control'] for r in s['event_rows']))
    def test_impact_only_high_extreme(self):
        s=m.event_study(self.bars,[event(impact='LOW')],self.cfg,self.folds)
        self.assertEqual(s['status'],'INSUFFICIENT_DATA')
    def test_news_not_calendar(self):
        e=event();e['type']='NEWS'
        self.assertEqual(len(m.event_study(self.bars,[e],self.cfg,self.folds)['event_rows']),0)
    def test_misaligned_event_not_rounded(self):
        e=event();e['scheduled_at']+=timedelta(seconds=3)
        s=m.event_study(self.bars,[e],self.cfg,self.folds)
        self.assertIn('EVENT_NOT_M1_ALIGNED',s['excluded_reasons'])
    def test_controls_not_near_event(self):
        s=m.event_study(self.bars,self.events,self.cfg,self.folds)
        for r in s['event_rows']:
            if r['matched_control']:
                ct=m.instant(r['control_at'])
                self.assertTrue(all(abs((ct-e['scheduled_at']).total_seconds())>self.cfg['control_blackout_minutes']*60 for e in self.events))
    def test_demo_report_blocks_execution(self):
        report=m.research(self.bars,self.events,self.cfg,'CURATED_USER_SUPPLIED_UNVERIFIED')
        self.assertEqual(report['execution_permission'],'BLOCKED')
        self.assertIsNone(report['strategy_validation'].get('fold_comparison'))
        self.assertIn('TRADE_PNL_NOT_MEASURED',report['reason_codes'])
    def test_markdown_contains_no_pnl(self):
        r=m.research(self.bars,self.events,self.cfg,'CURATED_USER_SUPPLIED_UNVERIFIED')
        self.assertIn('NOT_RUN',m.report_markdown(r))

class StrategyIntegration(unittest.TestCase):
    def test_known_event_blocks(self):
        ev=event(time=F,known='2025-01-03T10:00:00Z')
        self.assertTrue(m.macro_guard_decision(signal(),[ev],config()['guard_windows_minutes'])['blocked'])
    def test_future_known_does_not_block(self):
        ev=event(time=F,known='2025-01-04T13:31:00Z')
        self.assertFalse(m.macro_guard_decision(signal(),[ev],config()['guard_windows_minutes'])['blocked'])
    def test_synthetic_never_blocks(self):
        ev=event(time=F,known='2025-01-03T10:00:00Z',synthetic=True)
        self.assertFalse(m.macro_guard_decision(signal(),[ev],config()['guard_windows_minutes'])['blocked'])
    def test_low_impact_does_not_block(self):
        ev=event(time=F,known='2025-01-03T10:00:00Z',impact='LOW')
        self.assertFalse(m.macro_guard_decision(signal(),[ev],config()['guard_windows_minutes'])['blocked'])
    def test_after_window_no_block(self):
        ev=event(time='2025-01-04T12:00:00Z',known='2025-01-03T10:00:00Z')
        self.assertFalse(m.macro_guard_decision(signal(),[ev],config()['guard_windows_minutes'])['blocked'])
    def test_bad_signal_timestamp(self):
        s=signal();s['signal_at']='2025-01-04T13:31:00Z'
        with self.assertRaises(m.ResearchError):m.macro_guard_decision(s,[event()],config()['guard_windows_minutes'])
    def test_quote_replay_integration(self):
        cfg=config();p=packet()
        result=m.strategy_overlay(p,[event(time=F,known='2025-01-03T10:00:00Z')],cfg)
        self.assertEqual(result['fold_comparison'][1]['completed_baseline'],1)
        self.assertEqual(result['fold_comparison'][1]['completed_after_filter'],0)
        self.assertFalse(result['validation_approved'])
        self.assertEqual(result['signal_decisions'][0]['reason'],'PIT_KNOWN_MACRO_EVENT')
    def test_quote_cost_spread(self):
        result=m.strategy_overlay(packet(),[],config())
        self.assertEqual(result['fold_comparison'][1]['completed_after_filter'],1)
        self.assertLess(result['fold_comparison'][1]['baseline']['mean_net_pnl'],120.0)
    def test_fold_mismatch_rejected(self):
        p=packet();p['validation_profile']['folds'][0]['id']='different'
        with self.assertRaises(m.ResearchError):m.strategy_overlay(p,[],config())
    def test_symbol_mismatch_rejected(self):
        p=packet();p['account']['symbol']='GOLD'
        with self.assertRaises(m.ResearchError):m.strategy_overlay(p,[],config())
    def test_original_m06_still_blocked(self):
        result=m.strategy_overlay(packet(),[],config())
        self.assertEqual(result['original_m06_validation']['approval_status'],'RESEARCH_ONLY')
    def test_signal_price_lookahead_rejected(self):
        p=packet();p['signals'][0]['feature_available_at']=['2025-01-04T13:31:00Z']
        with self.assertRaises(ValueError):m.strategy_overlay(p,[],config())
    def test_optional_packet_not_run(self):
        self.assertEqual(m.strategy_overlay(None,[],config())['status'],'NOT_RUN')

class ExportTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
    def test_range_future(self):
        fake=MagicMock();a=m.instant('2025-01-01T00:00:00Z')
        with self.assertRaises(m.ResearchError):mt.export_m1(fake,'XAUUSD',a,a+timedelta(days=50),Path(self.tmp.name)/'b.csv',now=a+timedelta(days=60))
    def test_range_late(self):
        fake=MagicMock();a=m.instant('2025-01-01T00:00:00Z')
        with self.assertRaises(m.ResearchError):mt.export_m1(fake,'XAUUSD',a,a+timedelta(days=1),Path(self.tmp.name)/'b.csv',now=a)
    def test_empty_feed(self):
        fake=MagicMock();fake.symbol_select.return_value=True;fake.copy_rates_range.return_value=[]
        a=m.instant('2025-01-01T00:00:00Z')
        with self.assertRaises(m.ResearchError):mt.export_m1(fake,'XAUUSD',a,a+timedelta(minutes=15),Path(self.tmp.name)/'b.csv',now=a+timedelta(days=1))
    def test_export_closed_only(self):
        fake=MagicMock();fake.symbol_select.return_value=True
        a=m.instant('2025-01-01T00:00:00Z')
        fake.copy_rates_range.return_value=[{'time':int(a.timestamp()),'open':2000,'high':2001,'low':1999,'close':2000,
                                             'tick_volume':10,'real_volume':0,'spread':10},
                                            {'time':int((a+timedelta(minutes=1)).timestamp()),'open':2000,'high':2001,'low':1999,'close':2000,
                                             'tick_volume':10,'real_volume':0,'spread':10}]
        path=Path(self.tmp.name)/'b.csv'
        data=mt.export_m1(fake,'XAUUSD',a,a+timedelta(minutes=1),path,now=a+timedelta(minutes=1,seconds=30))
        self.assertEqual(data['bars'],1)
        with path.open(newline='') as f:self.assertEqual(len(list(csv.DictReader(f))),1)
    def test_no_order_call(self):
        fake=MagicMock();fake.symbol_select.return_value=True;fake.copy_rates_range.return_value=[]
        a=m.instant('2025-01-01T00:00:00Z')
        with self.assertRaises(m.ResearchError):mt.export_m1(fake,'XAUUSD',a,a+timedelta(minutes=5),Path(self.tmp.name)/'b.csv',now=a+timedelta(days=1))
        fake.order_send.assert_not_called()

if __name__=='__main__':unittest.main()

# Extended revision / source-provenance cases (appended before test discovery during unittest module import).
class RevisedCalendarSafety(unittest.TestCase):
    def test_same_day_different_provider_schedule_quarantined(self):
        a=event(time=D,eid='ff',known='2025-01-01T10:00:00Z')
        b=event(time='2025-01-02T14:30:00Z',eid='mm',known='2025-01-01T10:00:00Z')
        self.assertEqual(m.dedupe_events([a,b]),[])
    def test_same_day_different_event_names_preserved(self):
        a=event();b=event(time='2025-01-02T14:30:00Z',eid='ppipost')
        b['name']='Producer Price Index'
        self.assertEqual(len(m.dedupe_events([a,b])),2)
    def test_synthetic_status_without_synthetic_flag(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'r.json';m.save_json(p,{'module_id':'M04N','status':'SYNTHETIC_TEST_ONLY','as_of':'2025-01-02T13:00:00Z',
                            'calendar':{'events':[{'event_id':'demo','name':'CPI','impact':'HIGH', 'scheduled_at':D,'source_id':'FF_CALENDAR'}]},
                            'news':{'recent':[]}})
            rows,_=m.load_events(p);self.assertTrue(rows[0]['synthetic'])
    def test_strategy_group_separated(self):
        result=m.strategy_overlay(packet(),[],config())
        self.assertEqual(result['by_strategy_by_fold'][1]['strategy_version'],'XAU-S01@0.0.1')
        self.assertEqual(result['by_strategy_by_fold'][1]['role'],'FINAL_OOS')
    def test_synthetic_quotes_cannot_claim_research_complete(self):
        result=m.strategy_overlay(packet(),[],config())
        self.assertEqual(result['status'],'SYNTHETIC_DEMONSTRATION_ONLY')
        self.assertIn('SYNTHETIC_QUOTES_NOT_MARKET_EVIDENCE',result['reason_codes'])
    def test_m06_preserves_cost_stress(self):
        result=m.strategy_overlay(packet(),[],config())
        self.assertEqual(len(result['m06_cost_stress_scenarios']),4)

class TickExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.a=m.instant('2025-01-04T13:30:00Z')
    def test_actual_quote_export_no_order(self):
        import M06H_EXPORT_MT5_TICKS_READONLY as ex
        fake=MagicMock();fake.symbol_select.return_value=True
        fake.copy_ticks_range.return_value=[{'time_msc':int(self.a.timestamp()*1000)+1000,'time':int(self.a.timestamp())+1,'bid':2000.0,'ask':2000.2}]
        out=ex.export_ticks(fake,'XAUUSD',self.a,self.a+timedelta(minutes=2),self.root/'t.csv',now=self.a+timedelta(days=1))
        self.assertEqual(out['tick_rows'],1)
        with (self.root/'t.csv').open(newline='') as f:self.assertEqual(len(list(csv.DictReader(f))),1)
        fake.order_send.assert_not_called()
    def test_duplicate_ticks_skipped(self):
        import M06H_EXPORT_MT5_TICKS_READONLY as ex
        fake=MagicMock();fake.symbol_select.return_value=True
        row={'time_msc':int(self.a.timestamp()*1000)+1000,'time':int(self.a.timestamp())+1,'bid':2000.0,'ask':2000.2}
        fake.copy_ticks_range.return_value=[row,row]
        result=ex.export_ticks(fake,'XAUUSD',self.a,self.a+timedelta(minutes=2),self.root/'t.csv',now=self.a+timedelta(days=1))
        self.assertEqual(result['tick_rows'],1)
    def test_bad_quote_skipped_no_trades_fabricated(self):
        import M06H_EXPORT_MT5_TICKS_READONLY as ex
        fake=MagicMock();fake.symbol_select.return_value=True
        fake.copy_ticks_range.return_value=[{'time':int(self.a.timestamp())+1,'bid':0,'ask':2000}]
        with self.assertRaises(m.ResearchError):ex.export_ticks(fake,'XAUUSD',self.a,self.a+timedelta(minutes=2),self.root/'t.csv',now=self.a+timedelta(days=1))
        self.assertFalse((self.root/'t.csv').exists())
    def test_export_too_long(self):
        import M06H_EXPORT_MT5_TICKS_READONLY as ex
        fake=MagicMock()
        with self.assertRaises(m.ResearchError):ex.export_ticks(fake,'XAUUSD',self.a,self.a+timedelta(days=8),self.root/'t.csv',now=self.a+timedelta(days=9))
    def test_export_limit_never_partial(self):
        import M06H_EXPORT_MT5_TICKS_READONLY as ex
        fake=MagicMock();fake.symbol_select.return_value=True
        fake.copy_ticks_range.return_value=[{'time':int(self.a.timestamp())+j+1,'bid':2000+j,'ask':2000+j+.1} for j in range(3)]
        with self.assertRaises(m.ResearchError):ex.export_ticks(fake,'XAUUSD',self.a,self.a+timedelta(minutes=2),self.root/'t.csv',now=self.a+timedelta(days=1),max_ticks=1)
        self.assertFalse((self.root/'t.csv').exists())
