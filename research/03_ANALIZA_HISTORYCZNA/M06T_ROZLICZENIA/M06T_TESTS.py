"""Offline tests: synthetic fixtures only, NO broker and NO inferred alpha."""
from __future__ import annotations
import copy,csv,json,tempfile,unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
from M06T_ENGINE import (SettlementError,validate_protocol,load_ticks,verify_signal_ledger,
    macro_block,run,cli,metrics,report_md,dt,build_packet,settle_with_preserved_m06,verify_m06r_report)

START='2025-01-02T12:00:00Z';OOS='2025-01-04T12:00:00Z'
def t(value):return datetime.fromisoformat(value.replace('Z','+00:00'))
def tt(base,seconds):return (t(base)+timedelta(seconds=seconds)).isoformat().replace('+00:00','Z')
def protocol():
    return {'schema_version':'2.0.0','research_only':True,'frozen':True,'symbol':'XAUUSD',
        'account':{'account_type':'ZERO_SPREAD','symbol':'XAUUSD','account_id_hash':'DEMO_SYNTHETIC_NO_REAL_ACCOUNT','currency':'USD',
          'commission_source':'SCENARIO_ONLY','commission_per_lot_side':2.5,
          'conversion_source':'SCENARIO_ONLY','money_per_price_unit_per_lot':100.,
          'slippage_price':.02,'swap_per_lot_per_overnight':0},
        'settings':{'max_entry_wait_seconds':10.,'max_reference_age_seconds':30.,'max_tick_gap_seconds':120.,
                    'min_oos_trades':10,'bootstrap_iterations':30,'bootstrap_seed':7},
        'folds':[{'id':'DEV','role':'DEVELOPMENT','start':'2025-01-01T00:00:00Z','end':'2025-01-03T00:00:00Z'},
                 {'id':'OOS','role':'FINAL_OOS','start':'2025-01-03T00:00:00Z','end':'2025-01-06T00:00:00Z'}],
        'profiles':{name:{'strategy_id':strategy,'strategy_version':version,'spec_hash':'frozen-hash-'+name,
              'frozen_at':'2025-01-01T00:00:00Z','entry_type':'MARKET_NEXT_AVAILABLE_TICK',
              'reference':'LAST_KNOWN_MT5_MID_QUOTE','stop_distance':1.0,'target_distance':1.5,
              'lots':.1,'max_hold_seconds':60.}
            for name,strategy,version in [('MVP','XAU-S01','MVP-EXPERIMENT-v1'),('SMC','XAU-S14','SMC-EXPERIMENT-v1'),('SCALPING','XAU-S06','SCALP-EXPERIMENT-v1')]},
        'macro_windows':{'HIGH':{'pre':30,'post':15},'EXTREME':{'pre':60,'post':30}}}

def fixtures():
    p=protocol()
    data=[];stages=[];ticks=[]
    for i,(mode,base,side) in enumerate([('MVP',START,'LONG'),('SMC',OOS,'SHORT')]):
        pr=p['profiles'][mode];sid='SETUP-'+str(i);birth=tt(base,-300)
        stages.append({'setup_id':sid,'event_type':'DISCOVER','state':'EARLY_SETUP','available_at':birth,
           'strategy_id':pr['strategy_id'],'strategy_version':pr['strategy_version'],'mode':mode,'direction':side,
           'execution_permission':'BLOCKED','analysis_only':True})
        for state,event,offset in [('SETUP_FORMING','DEVELOPMENT',-240),('QUALIFIED','QUALIFY',-180),
                                  ('ARMED','ARM',-120),('TRIGGERED','TRIGGER',-60),('CONFIRMED','CONFIRM',0)]:
            stages.append({'setup_id':sid,'event_type':event,'state':state,'available_at':tt(base,offset),
               'strategy_id':pr['strategy_id'],'strategy_version':pr['strategy_version'],'mode':mode,'direction':side,
               'bar_evidence_id':sid+':'+state,'execution_permission':'BLOCKED','analysis_only':True})
        data.append({'signal_id':'M06R:SIGNAL-'+str(i),'setup_id':sid,'signal_at':base,'available_at':base,
          'strategy_id':pr['strategy_id'],'strategy_version':pr['strategy_version'],
          'direction':side,'mode':mode,'setup_tf':'M5',
          'entry':None,'stop_loss':None,'take_profit':None,'fill_status':'NOT_RUN','execution_permission':'BLOCKED'})
        tickprices=([ (0,100,100.10),(1,100.1,100.2),(2,101.8,101.9)] if side=='LONG' else
                     [(0,100,100.10),(1,99.9,100),(2,101.5,101.6)])
        ticks.append({'symbol':'XAUUSD','time':tt(base,-1),'available_at':tt(base,-1),'bid':100,'ask':100.1,'source_id':'MT5_TEST_FIXTURE'})
        for j,bid,ask in tickprices:
            at=tt(base,j+1)
            ticks.append({'symbol':'XAUUSD','time':at,'available_at':at,'bid':bid,'ask':ask,'source_id':'MT5_TEST_FIXTURE'})
    ticks.append({'symbol':'XAUUSD','time':'2025-01-06T00:01:00Z','available_at':'2025-01-06T00:01:00Z',
                  'bid':101.,'ask':101.1,'source_id':'MT5_TEST_FIXTURE'})
    return p,data,stages,ticks

def macro(base=OOS,known='2025-01-04T11:00:00Z'):
    return [{'event_id':'EV-CPI','type':'CALENDAR','scheduled_at':t(tt(base,300)),
             'known_at':t(known),'impact_known_at':t(known),'impact':'HIGH','synthetic':False}]

class ProtocolTests(unittest.TestCase):
    def setUp(self):self.p,self.s,self.e,self.t=fixtures()
    def test_valid(self):validate_protocol(self.p)
    def test_research_lock(self):
        self.p['research_only']=False
        with self.assertRaises(SettlementError):validate_protocol(self.p)
    def test_frozen_required(self):
        self.p['frozen']=False
        with self.assertRaises(SettlementError):validate_protocol(self.p)
    def test_bad_account(self):
        self.p['account']['account_type']='STANDARD'
        with self.assertRaises(SettlementError):validate_protocol(self.p)
    def test_overlap(self):
        self.p['folds'][1]['start']='2025-01-02T00:00:00Z'
        with self.assertRaises(SettlementError):validate_protocol(self.p)
    def test_no_oos(self):
        self.p['folds'][1]['role']='DEVELOPMENT'
        with self.assertRaises(SettlementError):validate_protocol(self.p)
    def test_missing_cost(self):
        del self.p['account']['commission_per_lot_side']
        with self.assertRaises(SettlementError):validate_protocol(self.p)
    def test_negative_slip(self):
        self.p['account']['slippage_price']=-1
        with self.assertRaises(SettlementError):validate_protocol(self.p)
    def test_nan_money(self):
        self.p['account']['money_per_price_unit_per_lot']=float('nan')
        with self.assertRaises(SettlementError):validate_protocol(self.p)
    def test_nonfrozen_profile(self):
        self.p['profiles']['MVP']['frozen_at']='2025-01-02T12:00:00Z'
        with self.assertRaises(SettlementError):verify_signal_ledger(self.s,self.e,self.p)
    def test_bad_entry_policy(self):
        self.p['profiles']['MVP']['entry_type']='BEST_PRICE'
        with self.assertRaises(SettlementError):validate_protocol(self.p)
    def test_unknown_mode(self):
        self.p['profiles']['ALPHA']=self.p['profiles'].pop('MVP')
        with self.assertRaises(SettlementError):validate_protocol(self.p)
    def test_zero_stop_distance(self):
        self.p['profiles']['MVP']['stop_distance']=0
        with self.assertRaises(SettlementError):validate_protocol(self.p)
    def test_dates_require_timezone(self):
        with self.assertRaises(SettlementError):dt('2025-01-01T12:00:00')

class LedgerTests(unittest.TestCase):
    def setUp(self):self.p,self.s,self.e,self.t=fixtures()
    def test_link(self):self.assertEqual(len(verify_signal_ledger(self.s,self.e,self.p)),2)
    def test_no_confirm(self):
        with self.assertRaises(SettlementError):verify_signal_ledger(self.s,self.e[:-1],self.p)
    def test_no_discover(self):
        with self.assertRaises(SettlementError):verify_signal_ledger(self.s,self.e[1:],self.p)
    def test_duplicate_confirm(self):
        with self.assertRaises(SettlementError):verify_signal_ledger(self.s,self.e+[self.e[-1]],self.p)
    def test_duplicate_signal(self):
        with self.assertRaises(SettlementError):verify_signal_ledger(self.s+self.s,self.e,self.p)
    def test_missing_qualify_stage(self):
        with self.assertRaises(SettlementError):verify_signal_ledger(self.s,[x for x in self.e if x['state']!='QUALIFIED'],self.p)
    def test_reused_bar_evidence(self):
        self.e[3]['bar_evidence_id']=self.e[2]['bar_evidence_id']
        with self.assertRaises(SettlementError):verify_signal_ledger(self.s,self.e,self.p)
    def test_repeated_same_timestamp(self):
        self.e[3]['available_at']=self.e[2]['available_at']
        with self.assertRaises(SettlementError):verify_signal_ledger(self.s,self.e,self.p)
    def test_wrong_direction(self):
        self.s[0]['direction']='SHORT'
        with self.assertRaises(SettlementError):verify_signal_ledger(self.s,self.e,self.p)
    def test_wrong_mode(self):
        self.s[0]['mode']='SMC'
        with self.assertRaises(SettlementError):verify_signal_ledger(self.s,self.e,self.p)
    def test_changed_time(self):
        self.s[0]['signal_at']=tt(START,-1)
        with self.assertRaises(SettlementError):verify_signal_ledger(self.s,self.e,self.p)
    def test_claimed_fill(self):
        self.s[0]['fill_status']='COMPLETED'
        with self.assertRaises(SettlementError):verify_signal_ledger(self.s,self.e,self.p)
    def test_unauthorized_stage(self):
        self.e[0]['execution_permission']='ALLOW'
        with self.assertRaises(SettlementError):verify_signal_ledger(self.s,self.e,self.p)
    def test_early_after_confirm(self):
        self.e[0]['available_at']=tt(START,1)
        with self.assertRaises(SettlementError):verify_signal_ledger(self.s,self.e,self.p)
    def test_hindsight_stop_level(self):
        self.s[0]['stop_loss']=99
        with self.assertRaises(SettlementError):verify_signal_ledger(self.s,self.e,self.p)

class SettlementTests(unittest.TestCase):
    def setUp(self):self.p,self.s,self.e,self.t=fixtures()
    def test_long_short(self):
        r=run(self.s,self.e,self.t,self.p)
        self.assertEqual(r['status'],'RESEARCH_ONLY');self.assertEqual(r['metrics']['all']['trades'],2)
        self.assertEqual(r['metrics']['by_strategy']['MVP']['development']['trades'],1)
        self.assertEqual(r['metrics']['by_strategy']['SMC']['final_oos']['trades'],1)
        self.assertTrue(r['trades'][0]['net_pnl']>0);self.assertTrue(r['trades'][1]['net_pnl']<0)
        self.assertFalse(r['oos_approved']);self.assertEqual(r['execution_permission'],'BLOCKED')
    def test_unmodified_m06_parity_for_trade_settlement(self):
        from M06T_ENGINE import m06
        s=self.s[0];ref=self.t[0];mid=(ref['bid']+ref['ask'])/2
        sig={'signal_id':s['signal_id'],'side':'LONG','symbol':'XAUUSD','source':'MT5_DERIVED','bar_state':'CLOSED',
             'strategy_version':s['strategy_version'],'spec_hash':'frozen-hash-MVP',
             'signal_at':s['signal_at'],'available_at':s['available_at'],
             'feature_available_at':[self.e[0]['available_at'],s['available_at']],
             'stop':mid-1,'target':mid+1.5,'lots':.1,'max_hold_seconds':60.,
             'entry_type':'MARKET_NEXT_AVAILABLE_TICK'}
        packet=build_packet(self.p,self.t,[sig],dt(self.t[-1]['available_at']),'PARITY')
        original=m06.main(packet)['trades'][0]
        optimized=settle_with_preserved_m06(packet)[0]
        self.assertEqual(original,optimized)
    def test_costs_are_deducted(self):
        r=run(self.s,self.e,self.t,self.p)
        self.assertLess(r['trades'][0]['net_pnl'],r['trades'][0]['gross_pnl'])
    def test_no_reference_quote(self):
        # remove old quote for first signal
        self.t=self.t[1:];r=run(self.s,self.e,self.t,self.p)
        self.assertTrue(any(x['reason']=='NO_REFERENCE_QUOTE' for x in r['excluded']))
    def test_stale_quote(self):
        self.t[0]['time']=self.t[0]['available_at']=tt(START,-40)
        r=run(self.s,self.e,self.t,self.p)
        self.assertTrue(any(x['reason']=='REFERENCE_QUOTE_STALE' for x in r['excluded']))
    def test_tick_gap_not_profitable(self):
        self.t[3]['time']=self.t[3]['available_at']=tt(START,200)
        self.p['profiles']['MVP']['max_hold_seconds']=240
        r=run(self.s,self.e,self.t,self.p)
        self.assertEqual(r['trades'][0]['status'],'UNVERIFIED_TICK_GAP')
        self.assertIsNone(r['trades'][0]['net_pnl'])
        self.assertEqual(r['metrics']['by_strategy']['MVP']['all']['trades'],0)
    def test_macro_blocks_known(self):
        r=run(self.s,self.e,self.t,self.p,events=macro(),macro_mode='CURATED_USER_SUPPLIED_UNVERIFIED')
        self.assertEqual(r['macro_comparison']['blocked_signals'],1)
        self.assertEqual(r['macro_comparison']['before']['trades'],2)
        self.assertEqual(r['macro_comparison']['after']['trades'],1)
        self.assertEqual(r['macro_comparison']['status'],'EXPLORATORY_PARTIAL_COVERAGE')
    def test_macro_future_knowledge_not_used(self):
        r=run(self.s,self.e,self.t,self.p,events=macro(known=tt(OOS,1)),macro_mode='CURATED_USER_SUPPLIED_UNVERIFIED')
        self.assertEqual(r['macro_comparison']['blocked_signals'],0)
    def test_macro_disabled_unknown(self):
        r=run(self.s,self.e,self.t,self.p)
        self.assertEqual(r['macro_comparison']['status'],'NOT_RUN')
    def test_macro_synthetic_not_empirical(self):
        es=macro();es[0]['synthetic']=True
        self.assertEqual(macro_block(self.s[1],es,self.p['macro_windows']),[])
    def test_no_signals(self):
        r=run([],[],self.t,self.p)
        self.assertEqual(r['status'],'NOT_RUN');self.assertIsNone(r['metrics'].get('all'))
    def test_first_next_quote_prevents_pre_signal_fill(self):
        r=run(self.s,self.e,self.t,self.p)
        self.assertGreater(dt(r['trades'][0]['entry_at']),dt(START))
    def test_report(self):
        r=run(self.s,self.e,self.t,self.p)
        self.assertIn('MVP',report_md(r))
    def test_bad_quote_bracket(self):
        self.p['profiles']['MVP']['stop_distance']=.01
        self.p['profiles']['MVP']['target_distance']=.01
        r=run(self.s,self.e,self.t,self.p)
        self.assertTrue(any(x['reason']=='ENTRY_BRACKET_INVALID_AT_FIRST_TICK' for x in r['excluded']))

class TickTests(unittest.TestCase):
    def setUp(self):self.p,self.s,self.e,self.t=fixtures()
    def make_csv(self,temp,items):
        f=Path(temp)/'ticks.csv'
        with f.open('w',newline='',encoding='utf-8') as o:
            w=csv.DictWriter(o,fieldnames=['symbol','time_utc','bid','ask','source_id','available_at']);w.writeheader()
            for x in items:w.writerow({'symbol':x['symbol'],'time_utc':x['time'],'bid':x['bid'],'ask':x['ask'],
             'source_id':x['source_id'],'available_at':x['available_at']})
        return f
    def test_normal(self):
        with tempfile.TemporaryDirectory() as tmp:self.assertEqual(len(load_ticks([self.make_csv(tmp,self.t)],'XAUUSD')),len(self.t))
    def test_duplicate_dedup(self):
        with tempfile.TemporaryDirectory() as tmp:self.assertEqual(len(load_ticks([self.make_csv(tmp,self.t[:1]+self.t[:1])],'XAUUSD')),1)
    def test_wrong_symbol(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SettlementError):load_ticks([self.make_csv(tmp,self.t)],'XAUUSDm')
    def test_negative_spread(self):
        self.t[0]['ask']=99
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SettlementError):load_ticks([self.make_csv(tmp,self.t)],'XAUUSD')
    def test_out_of_order(self):
        self.t[0],self.t[1]=self.t[1],self.t[0]
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SettlementError):load_ticks([self.make_csv(tmp,self.t)],'XAUUSD')
    def test_nonmt5(self):
        self.t[0]['source_id']='TV_CHART'
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SettlementError):load_ticks([self.make_csv(tmp,self.t)],'XAUUSD')
    def test_future_available_at(self):
        self.t[0]['available_at']=tt(START,-2)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SettlementError):load_ticks([self.make_csv(tmp,self.t)],'XAUUSD')
    def test_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SettlementError):load_ticks([self.make_csv(tmp,self.t)],'XAUUSD',max_rows=2)
    def test_bad_time(self):
        self.t[0]['time']='not a timestamp'
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SettlementError):load_ticks([self.make_csv(tmp,self.t)],'XAUUSD')
    def test_gap_validation_no_hallucinated_pnl(self):
        self.t[3]['time']=self.t[3]['available_at']=tt(START,200);self.p['profiles']['MVP']['max_hold_seconds']=240
        r=run(self.s,self.e,self.t,self.p)
        self.assertIn('QUOTE_GAP_EXCLUSIONS',r['warnings'])


class EndToEndTests(unittest.TestCase):
    def setUp(self):self.p,self.s,self.e,self.t=fixtures()
    def test_macro_by_strategy(self):
        r=run(self.s,self.e,self.t,self.p,macro(),'CURATED_USER_SUPPLIED_UNVERIFIED')
        self.assertEqual(r['macro_comparison']['by_strategy']['SMC']['oos_before']['trades'],1)
        self.assertEqual(r['macro_comparison']['by_strategy']['SMC']['oos_after']['trades'],0)
        self.assertEqual(r['macro_comparison']['by_strategy']['MVP']['before']['trades'],1)
    def test_replay_report_integrity(self):
        report={'module_id':'M06R_HISTORICAL_STRATEGY_REPLAY','schema_version':'2.0.0',
          'status':'REPLAY_RESEARCH_COMPLETE','symbol':'XAUUSD','signal_count':len(self.s),
          'confirmed_signals':self.s,'stage_transitions':self.e,'execution_permission':'BLOCKED'}
        self.assertTrue(verify_m06r_report(report,self.s,self.e,'XAUUSD'))
        report['signal_count']=99
        with self.assertRaises(SettlementError):verify_m06r_report(report,self.s,self.e,'XAUUSD')
    def test_cost_sensitivity(self):
        r=run(self.s,self.e,self.t,self.p)
        entries=r['cost_sensitivity'];self.assertEqual([x['commission_slippage_multiplier'] for x in entries],[1.,1.25,1.5,2.])
        self.assertLess(entries[-1]['average_projected_net_pnl'],entries[0]['average_projected_net_pnl'])
    def test_macro_empty_data(self):
        r=run(self.s,self.e,self.t,self.p,events=[],macro_mode='EMPTY')
        self.assertEqual(r['macro_comparison']['status'],'NOT_RUN')
    def test_quote_path_scenarios_bounded(self):
        self.assertIn('SIMULATED_QUOTES_NOT_BROKER_FILLS',run(self.s,self.e,self.t,self.p)['warnings'])
    def test_partial_oos_blocks_approval(self):
        r=run(self.s,self.e,self.t,self.p)
        self.assertIn('INSUFFICIENT_FINAL_OOS_SAMPLE',r['warnings'])
        self.assertFalse(r['live_eligible'])
    def test_short_side_settlement_original(self):
        from M06T_ENGINE import m06,build_packet,settle_with_preserved_m06
        s=self.s[1];ref=self.t[4];mid=(ref['bid']+ref['ask'])/2
        # t[4] is 1s before second signal in our fixture sequence.
        sig={'signal_id':s['signal_id'],'side':'SHORT','symbol':'XAUUSD','source':'MT5_DERIVED',
             'bar_state':'CLOSED','strategy_version':s['strategy_version'],'spec_hash':'frozen-hash-SMC',
             'signal_at':s['signal_at'],'available_at':s['available_at'],
             'feature_available_at':[self.e[6]['available_at'],s['available_at']],
             'stop':mid+1,'target':mid-1.5,'lots':.1,'max_hold_seconds':60,
             'entry_type':'MARKET_NEXT_AVAILABLE_TICK'}
        packet=build_packet(self.p,self.t,[sig],dt(self.t[-1]['available_at']),'PARITY_SHORT')
        self.assertEqual(m06.main(packet)['trades'][0],settle_with_preserved_m06(packet)[0])
    def test_cli_synthetic_roundtrip(self):
        from M06T_MAKE_SYNTHETIC_DEMO import main as make_demo
        with tempfile.TemporaryDirectory() as tmp:
            folder=make_demo(Path(tmp)/'demo')
            code=cli(['--signals',str(folder/'SIGNALS_SYNTHETIC.jsonl'),
              '--ledger',str(folder/'STAGES_SYNTHETIC.jsonl'), '--ticks',str(folder/'TICKS_SYNTHETIC.csv'),
              '--protocol',str(folder/'PROTOCOL_SYNTHETIC.json'),
              '--events',str(folder/'MACRO_SYNTHETIC.json'),
              '--replay-report',str(folder/'M06R_REPORT_SYNTHETIC.json'),'--out-dir',str(folder/'output')])
            self.assertEqual(code,0)
            result=json.loads((folder/'output'/'M06T_REPORT.json').read_text())
            self.assertEqual(result['metrics']['all']['trades'],2)
            self.assertEqual(result['macro_comparison']['status'],'NOT_RUN')
            self.assertEqual(len(result['input_sha256']),6)
            self.assertEqual(result['execution_permission'],'BLOCKED')
    def test_cli_rejects_unfrozen_protocol(self):
        from M06T_MAKE_SYNTHETIC_DEMO import main as make_demo
        with tempfile.TemporaryDirectory() as tmp:
            folder=make_demo(Path(tmp)/'demo')
            path=folder/'PROTOCOL_SYNTHETIC.json';p=json.loads(path.read_text());p['frozen']=False
            path.write_text(json.dumps(p))
            code=cli(['--signals',str(folder/'SIGNALS_SYNTHETIC.jsonl'),
              '--ledger',str(folder/'STAGES_SYNTHETIC.jsonl'), '--ticks',str(folder/'TICKS_SYNTHETIC.csv'),
              '--protocol',str(path),'--out-dir',str(folder/'out')])
            self.assertEqual(code,2)
            r=json.loads((folder/'out'/'M06T_REPORT.json').read_text())
            self.assertEqual(r['execution_permission'],'BLOCKED')
    def test_no_fill_when_quote_delay(self):
        self.p['settings']['max_entry_wait_seconds']=.1
        r=run(self.s,self.e,self.t,self.p)
        self.assertTrue(all(q['status']=='NO_FILL' for q in r['trades']))
        self.assertEqual(r['metrics']['all']['trades'],0)
    def test_limit_without_quote_path(self):
        # second signal occurs after exported history, should be a no-entry candidate or excluded.
        r=run(self.s,self.e,self.t,self.p)
        self.assertEqual(len(r['trades'])+len(r['excluded']),len(self.s))

if __name__=='__main__':unittest.main(verbosity=2)
