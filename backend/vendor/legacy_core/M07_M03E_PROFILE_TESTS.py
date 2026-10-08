"""Offline synthetic tests for research-only operational strategy selector."""
import copy
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from M07_M03E_PROFILE_DETECTOR import (discover,read_config,hashed,atr14,_bars,utc)
from M03E_M10_PIPELINE import construct_early
from vendor.M03.M03_REFERENCE_ENGINE import early_assessment
from M10_AUTO_TRIGGER_CONFIRM import rules_valid

BASE=datetime(2026,10,8,12,0,tzinfo=timezone.utc)

def make_fixture(*,direction='LONG',with_sweep=True,with_break=True,tf='M15'):
    duration={'M15':15,'M5':5}[tf]
    asof=BASE+timedelta(minutes=duration*66)
    bars=[]
    for i in range(66):
        opened=BASE+timedelta(minutes=duration*i)
        close=101.30+(i%4)*0.06
        bars.append({'timeframe':tf,'bar_state':'CLOSED','instrument_id':'XAUUSD',
            'exact_symbol':'XAUUSD','price_basis':'BID','source_id':'MT5:MOCK',
            'bar_open_utc':opened.isoformat(),
            'close_confirmed_at':(opened+timedelta(minutes=duration)).isoformat(),
            'available_at':(opened+timedelta(minutes=duration)).isoformat(),
            'open':close-.12,'high':close+.5,'low':close-.55,'close':close,
            'evidence_id':f'MT5:{tf}:{i}'})
    # For exact point-in-time FVG, prior closed bars and evidence are synthetic;
    # the FVG object mimics the standard M03 geometric detector output.
    if direction=='SHORT':
        fvg_lo,fvg_hi=101.2,101.6;target='BEARISH';liqtype='BSL'
        high,low=102.1,101.3
        for b in bars:
            b.update({'open':101.42,'high':high,'low':low,'close':101.40})
    else:
        fvg_lo,fvg_hi=101.0,101.5;target='BULLISH';liqtype='SSL'
    bars[-1]['open']=101.30;bars[-1]['close']=101.40
    bars[-1]['low']=min(bars[-1]['low'],101.25)
    bars[-1]['high']=max(bars[-1]['high'],101.70)
    snap={'analysis_gate':{'status':'PASS_WITH_LIMITATIONS'},'data_source_policy':'MT5_PRIMARY_TV_SUPPLEMENTAL_NO_SCREENSHOTS',
          'visual_capture_enabled':False,'instrument_id':'XAUUSD','exact_symbol':'XAUUSD',
          'snapshot_id':'MOCK_SNAP_1','as_of':asof.isoformat(),'candles_by_tf':{tf:bars}}
    htime=bars[-8]['available_at'];ftime=bars[-4]['available_at']
    fvg={'event_id':'M03:FVG:'+tf+':'+bars[-4]['bar_open_utc']+':'+target,
         'direction':target,'zone_low':fvg_lo,'zone_high':fvg_hi,
         'formed_at':ftime,'mitigated_fraction':0.2}
    sweep={'event_id':'M03:SWEEP:'+tf+':'+bars[-8]['bar_open_utc']+':'+liqtype,
           'directional_reaction':target,'observed_at':htime}
    br={'event_id':'M03:BOS:'+tf+':'+bars[-6]['bar_open_utc'],
        'direction':target,'kind':'BOS','displacement_confirmed':True,
        'observed_at':bars[-6]['available_at']}
    lvl={'event_id':'M03:LEVEL:'+tf+':'+liqtype+':PIVOT1','liquidity_side':liqtype,
         'available_at':bars[-15]['available_at'],'reference_level':100.8 if direction=='LONG' else 102.0}
    tfrec={'status':'PASS','fvgs':[fvg],'sweeps':[sweep] if with_sweep else [],
           'breaks':[br] if with_break else [],'liquidity_levels':[lvl]}
    ids=[fvg['event_id'],lvl['event_id']]
    if with_sweep:ids.append(sweep['event_id'])
    if with_break:ids.append(br['event_id'])
    m03={'status':'PASS','snapshot_id':snap['snapshot_id'],'as_of':snap['as_of'],
         'evidence_ids':ids,'timeframes':{tf:tfrec}}
    m02={'analysis_gate':{'status':'PASS'},'status':'PASS',
         'snapshot_id':snap['snapshot_id'],'as_of':snap['as_of'],
         'structural_direction':target,'evidence_ids':['M02:H1:struct'],
         'timeframes':{'H1':{'evidence_ids':['M02:H1:struct']}}}
    return snap,m02,m03

class TestOperationalProfiles(unittest.TestCase):
    def setUp(self):
        self.cfg=read_config();self.snap,self.m02,self.m03=make_fixture()
    def select(self,mode='MVP'):
        return discover(self.snap,self.m02,self.m03,mode=mode,config=self.cfg)
    def test_01_config(self):self.assertEqual(set(self.cfg['profiles']),{'MVP','SMC','SCALPING'})
    def test_02_research_only(self):self.assertFalse(self.cfg['execution_enabled'])
    def test_03_mvp_detects(self):self.assertIsNotNone(self.select()['selected_plan'])
    def test_04_mvp_family(self):self.assertEqual(self.select()['selected_plan']['strategy_id'],'XAU-S01')
    def test_05_smc_detects(self):self.assertEqual(self.select('SMC')['selected_plan']['strategy_id'],'XAU-S14')
    def test_06_auto_prioritizes_smc(self):self.assertEqual(self.select('AUTO')['selected_plan']['profile_name'],'SMC')
    def test_07_scalp_requires_m5(self):self.assertIsNone(self.select('SCALPING')['selected_plan'])
    def test_08_direction(self):self.assertEqual(self.select()['selected_plan']['intended_direction'],'LONG')
    def test_09_permitted_strategy(self):self.assertEqual(self.select()['selected_plan']['setup_tf'],'M15')
    def test_10_verifiable_early(self):
        p=self.select()['selected_plan'];x,why=construct_early({**self.m03,"early_evidence":early_assessment(self.m03,self.m02,p)},self.m02,self.snap,p)
        self.assertIsNotNone(x);self.assertEqual(why,[])
    def test_11_m10a_rules(self):
        p=self.select()['selected_plan'];e,_=construct_early({**self.m03,"early_evidence":early_assessment(self.m03,self.m02,p)},self.m02,self.snap,p)
        self.assertIsNone(rules_valid(p,e,self.m02,self.m03)[1])
    def test_12_four_unique_rules(self):
        p=self.select()['selected_plan'];self.assertEqual(len({hashed(x) for x in p['lifecycle_rules'].values()}),4)
    def test_13_future_fvg_refused(self):
        self.m03['timeframes']['M15']['fvgs'][0]['formed_at']='2028-01-01T00:00:00+00:00'
        self.assertIsNone(self.select()['selected_plan'])
    def test_14_fvg_filled(self):
        self.m03['timeframes']['M15']['fvgs'][0]['mitigated_fraction']=1.
        self.assertIsNone(self.select()['selected_plan'])
    def test_15_fvg_wrong_side(self):
        self.m03['timeframes']['M15']['fvgs'][0]['direction']='BEARISH'
        self.assertIsNone(self.select()['selected_plan'])
    def test_16_fvg_missing_id(self):
        self.m03['evidence_ids'].remove(self.m03['timeframes']['M15']['fvgs'][0]['event_id'])
        self.assertIsNone(self.select()['selected_plan'])
    def test_17_no_liquidity(self):
        self.m03['timeframes']['M15']['liquidity_levels']=[]
        self.assertIsNone(self.select('MVP')['selected_plan'])
    def test_18_no_sweep_for_smc(self):
        self.m03['timeframes']['M15']['sweeps']=[]
        self.assertIsNone(self.select('SMC')['selected_plan'])
    def test_19_smc_falls_back_auto(self):
        self.m03['timeframes']['M15']['sweeps']=[]
        self.assertEqual(self.select('AUTO')['selected_plan']['profile_name'],'MVP')
    def test_20_time_of_sweep_future(self):
        self.m03['timeframes']['M15']['sweeps'][0]['observed_at']='2028-01-01T00:00:00+00:00'
        self.assertIsNone(self.select('SMC')['selected_plan'])
    def test_21_m02_regime_unknown(self):
        self.m02['structural_direction']='UNKNOWN'
        self.assertIsNone(self.select()['selected_plan'])
    def test_22_m03_pending(self):
        self.m03['status']='PENDING'
        self.assertIsNone(self.select()['selected_plan'])
    def test_23_m01_pending(self):
        self.snap['analysis_gate']['status']='PENDING'
        self.assertIsNone(self.select()['selected_plan'])
    def test_24_m02_pending(self):
        self.m02['analysis_gate']['status']='FAIL'
        self.assertIsNone(self.select()['selected_plan'])
    def test_25_m03_future(self):
        self.m03['as_of']='2028-01-01T00:00:00+00:00'
        self.assertIsNone(self.select()['selected_plan'])
    def test_26_snapshot_id_mismatch(self):
        self.m03['snapshot_id']='other'
        self.assertIsNone(self.select()['selected_plan'])
    def test_27_no_screenshots(self):
        self.snap['visual_capture_enabled']=True
        self.assertIsNone(self.select()['selected_plan'])
    def test_28_non_mt5_source(self):
        self.snap['candles_by_tf']['M15'][5]['source_id']='TV'
        self.assertIsNone(self.select()['selected_plan'])
    def test_29_forming_bar_ignored(self):
        b=copy.deepcopy(self.snap['candles_by_tf']['M15'][-1]);b.update({'bar_state':'FORMING','evidence_id':'NOT_USED'})
        self.snap['candles_by_tf']['M15'].append(b)
        self.assertIsNotNone(self.select()['selected_plan'])
    def test_30_future_closed_bar_rejected(self):
        self.snap['candles_by_tf']['M15'][-1]['available_at']='2028-01-01T00:00:00+00:00'
        self.assertIsNone(self.select()['selected_plan'])
    def test_31_wrong_quote_basis(self):
        self.snap['candles_by_tf']['M15'][2]['price_basis']='MID'
        self.assertIsNone(self.select()['selected_plan'])
    def test_32_invalid_ohlc(self):
        self.snap['candles_by_tf']['M15'][2]['low']=200
        self.assertIsNone(self.select()['selected_plan'])
    def test_33_short_geometry(self):
        self.snap,self.m02,self.m03=make_fixture(direction='SHORT')
        p=self.select()['selected_plan'];self.assertIsNotNone(p)
        self.assertEqual(p['intended_direction'],'SHORT')
        self.assertTrue(all(r['operator']=='<' for r in p['lifecycle_rules'].values()))
        self.assertEqual(p['invalidation']['condition']['operator'],'>')
    def test_34_short_stage_order(self):
        self.snap,self.m02,self.m03=make_fixture(direction='SHORT')
        p=self.select()['selected_plan'];levels=[p['lifecycle_rules'][k]['level'] for k in ('qualification','arming','trigger','confirmation')]
        self.assertEqual(levels,sorted(levels,reverse=True))
    def test_35_long_stage_order(self):
        p=self.select()['selected_plan'];levels=[p['lifecycle_rules'][k]['level'] for k in ('qualification','arming','trigger','confirmation')]
        self.assertEqual(levels,sorted(levels))
    def test_36_evidence_distinct(self):
        p=self.select()['selected_plan'];self.assertNotEqual(p['location_evidence_id'],p['liquidity_evidence_id'])
    def test_37_snapshot_not_asof(self):
        self.snap['as_of']='2026-10-07T12:00:00+00:00'
        self.assertIsNone(self.select()['selected_plan'])
    def test_38_immutable_repeat(self):
        self.assertEqual(self.select()['selected_plan']['frozen_plan_hash'],self.select()['selected_plan']['frozen_plan_hash'])
    def test_39_does_not_fake_probability(self):
        self.assertNotIn('win_probability',self.select()['selected_plan'])
    def test_40_no_order(self):
        self.assertFalse(self.select()['selected_plan']['execution_enabled'])
    def test_41_no_m08_claim(self):
        self.assertFalse(self.select()['selected_plan']['m08_registry_approved'])
    def test_42_bad_mode(self):
        with self.assertRaises(ValueError):self.select('LIVE')
    def test_43_invalid_config(self):
        with tempfile.TemporaryDirectory() as d:
            c=copy.deepcopy(self.cfg);c['execution_enabled']=True
            fn=Path(d)/'c.json';fn.write_text(json.dumps(c),encoding='utf-8')
            with self.assertRaises(ValueError):read_config(fn)
    def test_44_broken_stage_order_config(self):
        with tempfile.TemporaryDirectory() as d:
            c=copy.deepcopy(self.cfg);c['profiles']['MVP']['entry_stage_atr']=[.4,.3,.2,.1]
            fn=Path(d)/'c.json';fn.write_text(json.dumps(c),encoding='utf-8')
            with self.assertRaises(ValueError):read_config(fn)
    def test_45_bad_symbol(self):
        self.snap['candles_by_tf']['M15'][5]['exact_symbol']='DIFFERENT'
        self.assertIsNone(self.select()['selected_plan'])
    def test_46_no_m02_structure(self):
        self.m02['evidence_ids']=[]
        self.assertIsNone(self.select()['selected_plan'])
    def test_47_atr_needs_history(self):
        self.assertIsNone(atr14(self.snap['candles_by_tf']['M15'][:10]))
    def test_48_no_real_fill(self):
        self.assertIsNone(self.select()['selected_plan'].get('submitted_order_id'))
    def test_49_no_filled_tag(self):
        self.assertNotIn('FILLED',self.select()['candidate_status'])
    def test_50_no_automated_loss_cap(self):
        self.assertIsNone(self.select()['selected_plan']['risk_profile'])
    def test_51_scalping_detects_with_confirmed_break(self):
        self.snap,self.m02,self.m03=make_fixture(tf='M5')
        p=self.select('SCALPING')['selected_plan']
        self.assertIsNotNone(p)
        self.assertEqual(p['strategy_id'],'XAU-S06')
        self.assertEqual(p['setup_tf'],'M5')
    def test_52_scalping_requires_displacement(self):
        self.snap,self.m02,self.m03=make_fixture(tf='M5')
        self.m03['timeframes']['M5']['breaks'][0]['displacement_confirmed']=False
        self.assertIsNone(self.select('SCALPING')['selected_plan'])
    def test_53_scalping_rejects_wrong_break_direction(self):
        self.snap,self.m02,self.m03=make_fixture(tf='M5')
        self.m03['timeframes']['M5']['breaks'][0]['direction']='BEARISH'
        self.assertIsNone(self.select('SCALPING')['selected_plan'])
    def test_54_scalping_rejects_late_break(self):
        self.snap,self.m02,self.m03=make_fixture(tf='M5')
        self.m03['timeframes']['M5']['breaks'][0]['observed_at']='2028-01-01T00:00:00+00:00'
        self.assertIsNone(self.select('SCALPING')['selected_plan'])
    def test_55_scalping_valid_m10_rules(self):
        self.snap,self.m02,self.m03=make_fixture(tf='M5')
        p=self.select('SCALPING')['selected_plan']
        e,_=construct_early({**self.m03,'early_evidence':early_assessment(self.m03,self.m02,p)},self.m02,self.snap,p)
        self.assertIsNotNone(e)
        self.assertIsNone(rules_valid(p,e,self.m02,self.m03)[1])
    def test_56_scalping_short(self):
        self.snap,self.m02,self.m03=make_fixture(tf='M5',direction='SHORT')
        p=self.select('SCALPING')['selected_plan']
        self.assertIsNotNone(p)
        self.assertEqual(p['intended_direction'],'SHORT')
    def test_57_m1_only_not_valid_m5_source(self):
        self.snap,self.m02,self.m03=make_fixture(tf='M5')
        self.snap['candles_by_tf']['M5'][5]['timeframe']='M1'
        self.assertIsNone(self.select('SCALPING')['selected_plan'])
    def test_58_broker_quote_is_not_order(self):
        self.snap,self.m02,self.m03=make_fixture(tf='M5')
        self.assertFalse(self.select('SCALPING')['live_execution_allowed'])
    def test_59_optional_dxy_not_needed(self):
        self.snap,self.m02,self.m03=make_fixture(tf='M5')
        self.assertIsNotNone(self.select('SCALPING')['selected_plan'])
    def test_60_auto_selects_scalping_if_only_m5(self):
        self.snap,self.m02,self.m03=make_fixture(tf='M5')
        self.assertEqual(self.select('AUTO')['selected_plan']['profile_name'],'SCALPING')
    def test_61_real_m03_geometric_fvg_derivation(self):
        from vendor.M03.M03_REFERENCE_ENGINE import find_fvgs
        b=self.snap['candles_by_tf']['M15']
        a=b[-6];c=b[-4]
        a.update({'open':100.40,'close':100.55,'low':100.20,'high':100.90})
        c.update({'open':101.35,'close':101.50,'low':101.22,'high':101.85})
        for after in b[-3:]:
            after.update({'open':101.35,'close':101.40,'low':101.25,'high':101.80})
        f=[v for v in find_fvgs(b,{'fvg_min_size_abs':.01},'M15')
           if v['event_id']=='M03:FVG:M15:'+c['bar_open_utc']+':BULLISH']
        self.assertEqual(len(f),1)
        self.assertNotEqual(f[0]['status'],'FILLED')
        self.m03['timeframes']['M15']['fvgs']=[f[0]]
        self.m03['evidence_ids']=[x for x in self.m03['evidence_ids'] if not x.startswith('M03:FVG:')]+[f[0]['event_id']]
        # Genuine M03 geometric output can be bound without manually naming the POI id.
        self.assertIsNotNone(self.select('MVP')['selected_plan'])

if __name__=='__main__':unittest.main(verbosity=1)
