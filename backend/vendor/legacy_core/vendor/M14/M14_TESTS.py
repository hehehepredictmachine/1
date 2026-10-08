"""Offline synthetic unit and safety tests for M14. No brokerage data or orders."""
import copy
import json
import unittest
from M14_REFERENCE_DECISION_ENGINE import evaluate, score_sq41, SCORE_WEIGHTS, POLICY

T = '2026-10-08T10:00:00+00:00'
F = '2026-10-08T10:00:05+00:00'
P = '2026-10-08T09:59:59+00:00'


def base(state='EARLY_SETUP', environment='ANALYSIS_ONLY'):
    core = {}
    for key in ('structural_advantage', 'meaningful_location', 'liquidity_context', 'development_path', 'known_invalidation'):
        core[key] = {'evidence_id':f'ev_{key}', 'available_at':T, 'snapshot_id':'s1',
                     'instrument_id':'XAUUSD', 'evidence_status':'VERIFIED', 'source':'MT5_PRIMARY'}
    return {'schema_version':'2.0.0','analysis_id':'SYNTHETIC_ONLY','as_of':T,
        'data_source_policy':POLICY,'screenshot_capture_enabled':False,
        'visual_capture_enabled':False,'ocr_enabled':False,'execution_environment':environment,
        'kill_switch':False,'account':{'source':'MT5_PRIMARY','verified':True,'account_type':'ZERO_SPREAD'},'config':{'max_quote_age_seconds':5},
        'data_snapshot':{'snapshot_id':'s1','as_of':T,'instrument_id':'XAUUSD','analysis_gate':'PASS',
            'execution_gate':'PASS','event_gate':'PASS','trap_gate':'PASS',
            'quote':{'source':'MT5_PRIMARY','evidence_status':'VERIFIED','bid':3999.9,'ask':4000,
                     'available_at':P}},
        'runtime':{'status':'HEALTHY','snapshot_id':'s1'},
        'router_result':{'module_id':'M09','analysis_pool':[{'setup_id':'a','analytical_eligible':True}],
                         'horizon_conflicts':[],'top_early_setup_id':'a','top_conditional_setup_id':'a',
                         'top_confirmed_setup_id':'a'},
        'setup':{'setup_id':'a','strategy_id':'XAU-S01','strategy_version':'1.0.0',
            'spec_hash':'0123456789abcdef'*4,'snapshot_id':'s1','instrument_id':'XAUUSD',
            'last_as_of':T,'horizon_id':'M5:10','direction':'LONG','state':state,
            'core_evidence':core,'invalidation':{'price':3995},
            'next_expected_event':'retest', 'plan':{'plan_status':'COMPLETE','rr_net':2.3,
            'management_rules':{'trailing':False},'entry':4000,'stop_loss':3995,
            'targets':[4010],'cost_verified':True,'entry_tolerance_verified':True}},
        'risk_result':{'module_id':'M11','setup_id':'a','risk_gate':'PASS',
            'preliminary_risk_eligible':True,'risk_policy_frozen':True,
            'account_verified':True,'portfolio_reconciled':True,'costs_verified':True},
        'registry_snapshot':{'source':'TRUSTED_M08_ADAPTER','attested':True,
            'strategy_id':'XAU-S01','strategy_version':'1.0.0',
            'spec_hash':'0123456789abcdef'*4,'status':'LIVE_ACTIVE','validated_at':P,
            'expires_at':'2026-10-09T10:00:00+00:00'},
        'portfolio_snapshot':{'source':'MT5_PRIMARY','verified':True,'reconciled':True,
            'instrument_id':'XAUUSD','snapshot_id':'s1'}}


def confirmed(p):
    p['setup'].update({'state':'CONFIRMED','trigger_event_id':'t1','trigger_confirmed':True,
        'trigger_source':'MT5_PRIMARY','trigger_available_at':P,'confirmation_source':'MT5_PRIMARY',
        'distinct_confirmation':True,'confirmation_gates':{x:'PASS' for x in
                    ('data','trigger','invalidation','expiry','conflict')}})
    return p


class M14Tests(unittest.TestCase):
    def check_safe(self,p):
        r=evaluate(p)
        self.assertEqual(r['execution_permission'],'BLOCKED')
        self.assertFalse(r['live_execution_allowed'])
        self.assertFalse(r['execution_eligible'])
        self.assertEqual(r['order_actions'],[])
        self.assertIsNone(r['submitted_order_id'])
        self.assertFalse(r['broker_order_sent'])
        return r
    def test_early_no_broker(self):
        p=base();r=self.check_safe(p);self.assertEqual(r['decision'],'EARLY_SETUP')
    def test_early_risk_block_retains(self):
        p=base();p['risk_result']={};r=self.check_safe(p);self.assertEqual(r['decision'],'EARLY_SETUP')
    def test_early_analysis_only_retains(self):
        p=base();r=self.check_safe(p);self.assertIn('ANALYSIS_ONLY',r['execution_blockers'])
    def test_conditional_qualified(self):
        r=self.check_safe(base('QUALIFIED'));self.assertEqual(r['decision'],'CONDITIONAL_SETUP')
    def test_conditional_armed(self):
        r=self.check_safe(base('ARMED'));self.assertEqual(r['decision'],'CONDITIONAL_SETUP')
    def test_conditional_triggered(self):
        r=self.check_safe(base('TRIGGERED'));self.assertEqual(r['decision'],'CONDITIONAL_SETUP')
    def test_forming_early(self):
        r=self.check_safe(base('SETUP_FORMING'));self.assertEqual(r['decision'],'EARLY_SETUP')
    def test_observe_wait(self):
        r=self.check_safe(base('OBSERVE'));self.assertEqual(r['decision'],'WAIT')
    def test_candidate_wait(self):
        r=self.check_safe(base('CANDIDATE'));self.assertEqual(r['decision'],'WAIT')
    def test_confirmed_long(self):
        r=self.check_safe(confirmed(base('CONFIRMED')));self.assertEqual(r['decision'],'LONG')
    def test_confirmed_short(self):
        p=confirmed(base('CONFIRMED'));p['setup']['direction']='SHORT'
        r=self.check_safe(p);self.assertEqual(r['decision'],'SHORT')
    def test_confirmed_without_gates_no_long(self):
        p=base('CONFIRMED');r=self.check_safe(p);self.assertEqual(r['decision'],'CONDITIONAL_SETUP')
    def test_confirmed_tv_trigger_denied(self):
        p=confirmed(base('CONFIRMED'));p['setup']['trigger_source']='TRADINGVIEW'
        r=self.check_safe(p);self.assertEqual(r['decision'],'CONDITIONAL_SETUP')
    def test_confirmed_tv_confirmation_denied(self):
        p=confirmed(base('CONFIRMED'));p['setup']['confirmation_source']='TRADINGVIEW'
        r=self.check_safe(p);self.assertEqual(r['decision'],'CONDITIONAL_SETUP')
    def test_confirmed_trigger_future_denied(self):
        p=confirmed(base('CONFIRMED'));p['setup']['trigger_available_at']=F
        r=self.check_safe(p);self.assertEqual(r['decision'],'CONDITIONAL_SETUP')
    def test_confirmation_not_distinct(self):
        p=confirmed(base('CONFIRMED'));p['setup']['distinct_confirmation']=False
        r=self.check_safe(p);self.assertEqual(r['decision'],'CONDITIONAL_SETUP')
    def test_horizon_conflict_wait(self):
        p=confirmed(base('CONFIRMED'));p['router_result']['horizon_conflicts']=[{'horizon_id':'M5:10'}]
        r=self.check_safe(p);self.assertEqual(r['decision'],'WAIT')
    def test_missing_core_wait(self):
        p=base();p['setup']['core_evidence'].pop('known_invalidation')
        r=self.check_safe(p);self.assertEqual(r['decision'],'WAIT')
    def test_future_core_wait(self):
        p=base();p['setup']['core_evidence']['development_path']['available_at']=F
        r=self.check_safe(p);self.assertEqual(r['decision'],'WAIT')
    def test_tv_core_not_price_proof(self):
        p=base();p['setup']['core_evidence']['structural_advantage']['source']='TRADINGVIEW'
        r=self.check_safe(p);self.assertEqual(r['decision'],'WAIT')
    def test_unclosed_required_candle(self):
        p=base();p['setup']['core_evidence']['structural_advantage'].update({'requires_closed_bar':True,'bar_state':'FORMING'})
        r=self.check_safe(p);self.assertEqual(r['decision'],'WAIT')
    def test_closed_required_candle(self):
        p=base();p['setup']['core_evidence']['structural_advantage'].update({'requires_closed_bar':True,'bar_state':'CLOSED'})
        r=self.check_safe(p);self.assertEqual(r['decision'],'EARLY_SETUP')
    def test_stale_data_no_trade(self):
        p=base();p['data_snapshot']['analysis_gate']='FAIL'
        r=self.check_safe(p);self.assertEqual(r['decision'],'NO_TRADE')
    def test_mismatched_snapshot_no_trade(self):
        p=base();p['setup']['snapshot_id']='s2'
        r=self.check_safe(p);self.assertEqual(r['decision'],'NO_TRADE')
    def test_mismatched_instrument_no_trade(self):
        p=base();p['setup']['instrument_id']='SILVER'
        r=self.check_safe(p);self.assertEqual(r['decision'],'NO_TRADE')
    def test_mismatched_time_no_trade(self):
        p=base();p['data_snapshot']['as_of']=P
        r=self.check_safe(p);self.assertEqual(r['decision'],'NO_TRADE')
    def test_naive_time_no_trade(self):
        p=base();p['as_of']='2026-10-08T10:00:00'
        r=self.check_safe(p);self.assertEqual(r['decision'],'NO_TRADE')
    def test_screenshot_forbidden(self):
        p=base();p['screenshot_capture_enabled']=True
        r=self.check_safe(p);self.assertEqual(r['decision'],'NO_TRADE')
    def test_ocr_forbidden(self):
        p=base();p['ocr_enabled']=True
        r=self.check_safe(p);self.assertEqual(r['decision'],'NO_TRADE')
    def test_policy_mismatch_no_trade(self):
        p=base();p['data_source_policy']='SCREENSHOT'
        r=self.check_safe(p);self.assertEqual(r['decision'],'NO_TRADE')
    def test_expired_terminal(self):
        r=self.check_safe(base('EXPIRED'));self.assertEqual(r['signal_validity'],'EXPIRED')
    def test_invalidated_terminal(self):
        r=self.check_safe(base('INVALIDATED'));self.assertEqual(r['signal_validity'],'INVALID')
    def test_managed_no_new_entry(self):
        r=self.check_safe(base('MANAGED'));self.assertEqual(r['decision'],'WAIT')
    def test_wrong_router_top_wait(self):
        p=base();p['router_result']['top_early_setup_id']='b'
        r=self.check_safe(p);self.assertEqual(r['decision'],'WAIT')
    def test_no_next_event_wait(self):
        p=base();p['setup'].pop('next_expected_event')
        r=self.check_safe(p);self.assertEqual(r['decision'],'WAIT')
    def test_zero_profile_unknown_exec_blocked(self):
        p=confirmed(base('CONFIRMED','LIVE'));p['account']['account_type']='UNKNOWN'
        r=self.check_safe(p);self.assertEqual(r['decision'],'LONG');self.assertEqual(r['preliminary_execution_readiness'],'BLOCKED')
    def test_no_route_wait(self):
        p=base();p['router_result']['analysis_pool']=[]
        r=self.check_safe(p);self.assertEqual(r['decision'],'WAIT')
    def test_incomplete_score_null(self):
        r=score_sq41({'structure':{'q':1}})
        self.assertIsNone(r['value']);self.assertAlmostEqual(r['coverage'],0.15)
    def test_full_score_100(self):
        c={x:{'q':1} for x in SCORE_WEIGHTS};r=score_sq41(c)
        self.assertEqual(r['value'],100);self.assertEqual(r['quality_band'],'A_PLUS_QUALITY')
    def test_score_not_probability(self):
        p=confirmed(base('CONFIRMED'));p['score_components']={x:{'q':1} for x in SCORE_WEIGHTS}
        r=self.check_safe(p);self.assertIsNone(r['probabilities']);self.assertEqual(r['decision'],'LONG')
    def test_duplicate_evidence_not_double_count(self):
        c={x:{'q':1} for x in SCORE_WEIGHTS};c['structure']['underlying_event_id']='one';c['liquidity']['underlying_event_id']='one'
        r=score_sq41(c);self.assertIsNone(r['value']);self.assertEqual(r['coverage'],0.85)
    def test_untrusted_json_authorized_cannot_open(self):
        p=confirmed(base('CONFIRMED','LIVE'));p['authorization']={'permission':'AUTHORIZED','signed':True}
        p['executor_available']=True
        r=self.check_safe(p);self.assertEqual(r['preliminary_execution_readiness'],'READY')
    def test_zero_account_does_not_waive_cost_gate(self):
        p=confirmed(base('CONFIRMED','LIVE'));p['account_type']='ZERO_SPREAD';p['risk_result']['costs_verified']=False
        r=self.check_safe(p);self.assertEqual(r['preliminary_execution_readiness'],'BLOCKED')
    def test_stale_quote_blocks_only_exec(self):
        p=confirmed(base('CONFIRMED','LIVE'));p['data_snapshot']['quote']['available_at']='2026-10-08T09:50:00Z'
        r=self.check_safe(p);self.assertEqual(r['decision'],'LONG');self.assertEqual(r['preliminary_execution_readiness'],'BLOCKED')
    def test_broker_bid_gt_ask_blocks_exec(self):
        p=confirmed(base('CONFIRMED','LIVE'));p['data_snapshot']['quote']['bid']=4001
        r=self.check_safe(p);self.assertEqual(r['decision'],'LONG');self.assertEqual(r['preliminary_execution_readiness'],'BLOCKED')
    def test_tv_quote_blocks_exec(self):
        p=confirmed(base('CONFIRMED','LIVE'));p['data_snapshot']['quote']['source']='TRADINGVIEW'
        r=self.check_safe(p);self.assertEqual(r['decision'],'LONG');self.assertEqual(r['preliminary_execution_readiness'],'BLOCKED')
    def test_no_quote_freshness_policy_blocks(self):
        p=confirmed(base('CONFIRMED','LIVE'));p['config']={}
        r=self.check_safe(p);self.assertEqual(r['preliminary_execution_readiness'],'BLOCKED')
    def test_m16_stale_blocks_exec(self):
        p=confirmed(base('CONFIRMED','LIVE'));p['runtime']['status']='DEGRADED'
        r=self.check_safe(p);self.assertEqual(r['decision'],'LONG');self.assertEqual(r['preliminary_execution_readiness'],'BLOCKED')
    def test_risk_conditional_blocks_exec(self):
        p=confirmed(base('CONFIRMED','LIVE'));p['risk_result']['risk_gate']='CONDITIONAL'
        r=self.check_safe(p);self.assertEqual(r['decision'],'LONG');self.assertEqual(r['preliminary_execution_readiness'],'BLOCKED')
    def test_expired_registry_blocks_exec(self):
        p=confirmed(base('CONFIRMED','LIVE'));p['registry_snapshot']['expires_at']=P
        r=self.check_safe(p);self.assertEqual(r['preliminary_execution_readiness'],'BLOCKED')
    def test_wrong_registry_hash_blocks_exec(self):
        p=confirmed(base('CONFIRMED','LIVE'));p['registry_snapshot']['spec_hash']='bad'
        r=self.check_safe(p);self.assertEqual(r['preliminary_execution_readiness'],'BLOCKED')
    def test_unknown_strategy_status_blocks_exec(self):
        p=confirmed(base('CONFIRMED','LIVE'));p['registry_snapshot']['status']='RESEARCH'
        r=self.check_safe(p);self.assertEqual(r['preliminary_execution_readiness'],'BLOCKED')
    def test_no_portfolio_blocks_exec(self):
        p=confirmed(base('CONFIRMED','LIVE'));p['portfolio_snapshot']={}
        r=self.check_safe(p);self.assertEqual(r['preliminary_execution_readiness'],'BLOCKED')
    def test_kill_switch_blocks_exec(self):
        p=confirmed(base('CONFIRMED','LIVE'));p['kill_switch']=True
        r=self.check_safe(p);self.assertEqual(r['preliminary_execution_readiness'],'BLOCKED')
    def test_macro_risk_blocks_exec(self):
        p=confirmed(base('CONFIRMED','LIVE'));p['data_snapshot']['event_gate']='PENDING'
        r=self.check_safe(p);self.assertEqual(r['preliminary_execution_readiness'],'BLOCKED')
    def test_without_verified_plan_blocks(self):
        p=confirmed(base('CONFIRMED','LIVE'));p['setup']['plan']['cost_verified']=False
        r=self.check_safe(p);self.assertEqual(r['preliminary_execution_readiness'],'BLOCKED')
    def test_demo_never_live(self):
        p=confirmed(base('CONFIRMED','DEMO'));r=self.check_safe(p)
        self.assertEqual(r['decision'],'LONG');self.assertEqual(r['preliminary_execution_readiness'],'READY')
    def test_paper_never_live(self):
        p=confirmed(base('CONFIRMED','PAPER'));r=self.check_safe(p)
        self.assertEqual(r['decision'],'LONG');self.assertEqual(r['preliminary_execution_readiness'],'READY')
    def test_result_deterministic(self):
        p=confirmed(base('CONFIRMED','LIVE'));self.assertEqual(evaluate(p),evaluate(p))
    def test_does_not_mutate_input(self):
        p=base();q=copy.deepcopy(p);evaluate(p);self.assertEqual(q,p)
    def test_json_export(self):
        self.assertTrue(json.dumps(evaluate(base()),allow_nan=False))

if __name__=='__main__': unittest.main(verbosity=2)
