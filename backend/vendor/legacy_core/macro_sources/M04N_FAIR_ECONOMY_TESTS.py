"""Independent, no-network contract & regression tests for two public calendar exports."""
import copy
import datetime as dt
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import M04N_ENGINE as m
from M04N_TESTS import NOW, ICS, FED_RSS, GDELT, FakeHTTP

ROOT=Path(__file__).resolve().parent
FF_DATA=[
 {"title":"Core CPI m/m","country":"USD","date":"2026-10-08T08:30:00-04:00","impact":"High","forecast":"0.3%","previous":"0.2%","actual":""},
 {"title":"Fed Chair Powell Speaks","country":"USD","date":"2026-10-08T10:00:00-04:00","impact":"High","forecast":"","previous":""},
 {"title":"CNY Trade Balance","country":"CNY","date":"2026-10-09T21:00:00+08:00","impact":"Medium","forecast":"50B","previous":"45B"},
 {"title":"EUR German Import Prices","country":"EUR","date":"2026-10-10T10:00:00+02:00","impact":"Low"},
 {"title":"Tentative release","country":"USD","date":"Tentative","impact":"High"},
]
MM_DATA=[
 {"title":"Core CPI m/m","country":"US","date":"2026-10-08T08:30:00-04:00","impact":"High","forecast":"0.2%","previous":"0.2%","actual":"0.4%"},
 {"title":"US Gold Bullion Reserves","country":"US","date":"2026-10-09T09:00:00-04:00","impact":"Medium","previous":""},
 {"title":"LME Copper Inventories","country":"UK","date":"2026-10-09T09:00:00+01:00","impact":"Low","previous":"1500"},
 {"title":"CH Inflation Data","country":"CH","date":"2026-10-09T21:00:00+08:00","impact":"High"}
]

class ParseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cfg=json.loads((ROOT/'M04N_CONFIG.json').read_text(encoding='utf8'))
        cls.ff=cfg['fair_economy_calendars'][0];cls.mm=cfg['fair_economy_calendars'][1]
    def run_ff(self, rows=FF_DATA,source=None,now=NOW):
        return m.fair_economy_events(json.dumps(rows).encode(),source or self.ff,now)
    def test_both_sources_configured(self):
        self.assertTrue(self.ff['enabled'] and self.mm['enabled'])
    def test_domains_are_exactly_allowlisted(self):
        cfg=json.loads((ROOT/'M04N_CONFIG.json').read_text())
        for src in cfg['fair_economy_calendars']:
            self.assertEqual(m.validate_https(src['url'],cfg['allowed_hosts']),src['url'])
    def test_only_public_weekly_exports(self):
        for src in (self.ff,self.mm):
            self.assertTrue(src['url'].startswith('https://nfs.faireconomy.media/'))
            self.assertTrue(src['url'].endswith('_calendar_thisweek.json'))
    def test_parses_filtered_ff(self):
        records,invalid=self.run_ff()
        self.assertEqual(len(records),3)
        self.assertEqual(invalid,1)
    def test_us_timezone_dst(self):
        self.assertEqual(self.run_ff()[0][0]['scheduled_at'],'2026-10-08T12:30:00Z')
    def test_china_timezone(self):
        self.assertEqual(self.run_ff()[0][2]['scheduled_at'],'2026-10-09T13:00:00Z')
    def test_mm_us_alias(self):
        rows,invalid=m.fair_economy_events(json.dumps(MM_DATA).encode(),self.mm,NOW)
        self.assertEqual(rows[0]['currency'],'USD')
    def test_mm_china_alias(self):
        rows,_=m.fair_economy_events(json.dumps(MM_DATA).encode(),self.mm,NOW)
        self.assertEqual(rows[-1]['currency'],'CNY')
    def test_mm_gold_specific(self):
        rows,_=m.fair_economy_events(json.dumps(MM_DATA).encode(),self.mm,NOW)
        self.assertTrue(any('Gold Bullion' in r['name'] for r in rows))
    def test_mm_copper_optional(self):
        rows,_=m.fair_economy_events(json.dumps(MM_DATA).encode(),self.mm,NOW)
        self.assertTrue(any('Copper' in r['name'] for r in rows))
    def test_ff_excludes_useless_countries(self):
        self.assertFalse(any(e['name'].startswith('EUR') for e in self.run_ff()[0]))
    def test_no_naive_datetime_assumption(self):
        x=[{'title':'CPI','country':'USD','impact':'High','date':'2026-10-08T08:30:00'}]
        self.assertEqual(self.run_ff(x)[0],[])
    def test_skips_far_future_and_old(self):
        x=[{'title':'CPI','country':'USD','impact':'High','date':'2027-10-08T08:30:00+00:00'}, {'title':'CPI','country':'USD','impact':'High','date':'2025-10-08T08:30:00+00:00'}]
        self.assertEqual(self.run_ff(x)[0],[])
    def test_rejects_wrong_root(self):
        with self.assertRaises(ValueError):m.fair_economy_events(b'{"events":[]}',self.ff,NOW)
    def test_rejects_oversized(self):
        with self.assertRaises(ValueError):m.fair_economy_events(b' ' * 1_500_001,self.ff,NOW)
    def test_rejects_excessive_rows(self):
        with self.assertRaises(ValueError):m.fair_economy_events(json.dumps([{}]*2001).encode(),self.ff,NOW)
    def test_bad_json_rejected(self):
        with self.assertRaises(ValueError):m.fair_economy_events(b'not json',self.ff,NOW)
    def test_values_remain_strings_not_synthetic_surprise(self):
        r=self.run_ff()[0][0]
        self.assertEqual(r['forecast'],'0.3%')
        self.assertIsNone(r['actual'])
        self.assertTrue(r['no_release_surprise_inferred'])
    def test_cannot_authorize_order(self):
        self.assertTrue(all(x['risk_context_only'] for x in self.run_ff()[0]))
    def test_missing_impact_conservatively_classified(self):
        obj={'title':'Consumer Price Index','country':'USD','date':'2026-10-08T08:30:00-04:00','impact':'?' }
        self.assertEqual(self.run_ff([obj])[0][0]['impact'],'HIGH')
    def test_refuses_invalid_tz(self):
        obj={'title':'CPI','country':'USD','date':'2026-10-08T08:30:00+55:00','impact':'High'}
        self.assertEqual(self.run_ff([obj])[0],[])
    def test_event_key_stable_across_poll(self):
        first=self.run_ff()[0][0]
        later=self.run_ff(now=NOW+dt.timedelta(minutes=10))[0][0]
        self.assertEqual(first['event_id'],later['event_id'])
    def test_event_revision_does_not_change_id(self):
        rows=copy.deepcopy(FF_DATA);rows[0]['actual']='0.5%'
        self.assertEqual(self.run_ff(rows)[0][0]['event_id'],self.run_ff()[0][0]['event_id'])

class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=m.Store(Path(self.tmp.name)/'s.sqlite')
        self.cfg=json.loads((ROOT/'M04N_CONFIG.json').read_text(encoding='utf8'))
        self.cfg['rss_feeds']=[self.cfg['rss_feeds'][0]]
        self.cfg['gdelt_enabled']=False
        self.cfg['fred_enabled']=False
        self.http=FakeHTTP({'press_monetary.xml':FED_RSS,'bls.ics':ICS,
            'ff_calendar_thisweek':json.dumps(FF_DATA).encode(),
            'mm_calendar_thisweek':json.dumps(MM_DATA).encode()})
    def tearDown(self):
        self.store.close();self.tmp.cleanup()
    def cycle(self,at=NOW, force=False):
        return m.collect(self.cfg,self.store,self.http,at,force)
    def test_official_bls_preferred_on_exact_match(self):
        extra={'title':'Consumer Price Index','country':'USD','date':'2026-10-08T08:30:00-04:00','impact':'Low','actual':'0.5%'}
        self.http.payloads['ff_calendar_thisweek']=json.dumps([extra]).encode()
        report,_=self.cycle()
        cpi=[e for e in report['calendar']['events'] if e['name']=='Consumer Price Index']
        self.assertEqual(len(cpi),1)
        self.assertEqual(cpi[0]['source_id'],'BLS_CALENDAR')
        self.assertIsNone(cpi[0]['actual'])
        self.assertCountEqual(cpi[0]['provider_sources'],['BLS_CALENDAR','FF_CALENDAR'])
    def test_distinct_cpi_series_do_not_merge(self):
        report,_=self.cycle()
        self.assertTrue(any(e['name']=='Core CPI m/m' for e in report['calendar']['events']))
        self.assertTrue(any(e['name']=='Consumer Price Index' for e in report['calendar']['events']))
    def test_source_directory_links_not_headline_claims(self):
        report,_=self.cycle()
        for key in ('forexfactory','metalsmine'):
            info=report['source_directory'][key]
            self.assertTrue(info['calendar_auto_import'])
            self.assertFalse(info['news_page_auto_import'])
            self.assertTrue(info['news'].startswith('https://'))
    def test_date_too_far_in_past_not_active(self):
        x=[{'title':'Core CPI m/m','country':'USD','date':'2026-10-01T08:30:00-04:00','impact':'High'}]
        self.http.payloads['ff_calendar_thisweek']=json.dumps(x).encode()
        self.http.payloads['mm_calendar_thisweek']=b'[]'
        self.cfg['bls_calendar_ics']=None
        report,_=self.cycle()
        self.assertEqual(report['calendar']['events'],[])
        self.assertEqual(report['calendar']['status'],'PARTIAL_NO_EVENTS')
    def test_fetches_both(self):
        report,_=self.cycle()
        self.assertIn('FF_CALENDAR',report['integrity']['sources_updated_this_poll'])
        self.assertIn('MM_CALENDAR',report['integrity']['sources_updated_this_poll'])
    def test_empty_ff_is_healthy_not_unavailable(self):
        self.http.payloads['ff_calendar_thisweek']=b'[]'
        report,_=self.cycle()
        self.assertEqual(report['integrity']['source_health']['FF_CALENDAR']['state'],'HEALTHY')
    def test_preserves_official_bls(self):
        report,_=self.cycle()
        self.assertEqual(report['integrity']['source_health']['BLS_CALENDAR']['state'],'HEALTHY')
    def test_dedup_ff_mm(self):
        report,_=self.cycle()
        cpi=[e for e in report['calendar']['events'] if e['name']=='Core CPI m/m']
        self.assertEqual(len(cpi),1)
        self.assertCountEqual(cpi[0]['provider_sources'],['FF_CALENDAR','MM_CALENDAR'])
    def test_provider_forecasts_not_equated(self):
        report,_=self.cycle()
        cpi=[e for e in report['calendar']['events'] if e['name']=='Core CPI m/m'][0]
        self.assertEqual(sorted(p['forecast'] for p in cpi['provider_occurrences']),['0.2%','0.3%'])
    def test_nonindependent_family(self):
        report,_=self.cycle()
        self.assertTrue(report['integrity']['fair_economy_is_single_source_family'])
    def test_overlapping_events_one_macro_context(self):
        _,bridge=self.cycle()
        self.assertEqual(len([e for e in bridge['context_inputs']['macro_events'] if e['name']=='Core CPI m/m']),1)
    def test_partial_never_full(self):
        _,bridge=self.cycle()
        self.assertFalse(bridge['context_inputs']['calendar_coverage']['data_complete'])
        self.assertNotEqual(bridge['context_inputs']['calendar_coverage']['status'],'VERIFIED')
    def test_high_risk_from_ff_blocks(self):
        self.cfg['bls_calendar_ics']=None
        self.http.payloads['mm_calendar_thisweek']=b'[]'
        report,_=self.cycle()
        self.assertEqual(report['calendar']['risk']['level'],'HIGH')
    def test_stale_fe_not_actionable(self):
        self.cfg['bls_calendar_ics']=None
        self.cycle()
        # Simulate no recent success, retry fails and all its old events remain in SQLite.
        self.http.payloads['ff_calendar_thisweek']=urllib.error.URLError('offline')
        self.http.payloads['mm_calendar_thisweek']=urllib.error.URLError('offline')
        out,_=self.cycle(NOW+dt.timedelta(hours=3),True)
        self.assertEqual(out['calendar']['risk']['level'],'NONE_DETECTED_IN_PARTIAL_CALENDAR')
        self.assertEqual(out['calendar']['events'],[])
        self.assertIn('FF_CALENDAR',out['integrity']['failed_or_stale_sources'])
    def test_single_down_still_keeps_other(self):
        self.http.payloads['mm_calendar_thisweek']=urllib.error.URLError('blocked')
        out,_=self.cycle()
        self.assertEqual(out['status'],'PARTIAL')
        self.assertTrue(any(e['source_id']=='FF_CALENDAR' for e in out['calendar']['events']))
    def test_no_fake_new_news(self):
        a,_=self.cycle()
        self.assertEqual(a['news']['new_count_this_poll'],0)
        self.assertEqual(a['news']['initial_backfill_count'],1)
    def test_throttle_30_min(self):
        self.cycle();count=len(self.http.calls)
        self.cycle(NOW+dt.timedelta(minutes=5))
        self.assertEqual(len([u for u in self.http.calls if 'calendar_thisweek' in u]),2)
    def test_weekly_source_updates_at_interval(self):
        self.cycle()
        self.cycle(NOW+dt.timedelta(minutes=31))
        self.assertEqual(len([u for u in self.http.calls if 'calendar_thisweek' in u]),4)
    def test_calendar_observation_first_seen_preserved(self):
        self.cycle()
        a=[e for e in self.store.events() if e['source_id']=='FF_CALENDAR'][0]
        later=NOW+dt.timedelta(minutes=31)
        self.cycle(later)
        b=[e for e in self.store.events() if e['event_id']==a['event_id']][0]
        self.assertEqual(a['available_at'],b['available_at'])
    def test_events_revised(self):
        self.cycle()
        next_rows=copy.deepcopy(FF_DATA);next_rows[0]['actual']='0.4%'
        self.http.payloads['ff_calendar_thisweek']=json.dumps(next_rows).encode()
        report,_=self.cycle(NOW+dt.timedelta(minutes=31))
        self.assertEqual([e for e in report['calendar']['events'] if e['name']=='Core CPI m/m'][0]['provider_occurrences'][0]['actual'],'0.4%')
    def test_rate_limited_429_marks_unavailable(self):
        self.http.payloads['ff_calendar_thisweek']=urllib.error.HTTPError('https://nfs.faireconomy.media',429,'Too Many Requests',{},None)
        report,_=self.cycle()
        self.assertEqual(report['integrity']['source_health']['FF_CALENDAR']['state'],'UNAVAILABLE_OR_STALE')
    def test_config_optional_disable(self):
        self.cfg['fair_economy_calendars'][0]['enabled']=False
        report,_=self.cycle()
        self.assertNotIn('FF_CALENDAR',report['integrity']['expected_sources'])
        self.assertNotIn('FF_CALENDAR',report['integrity']['sources_updated_this_poll'])
    def test_window_coverage_excludes_next_week(self):
        d=copy.deepcopy(FF_DATA);d.append({'title':'CPI','country':'USD','date':'2026-11-22T08:30:00+00:00','impact':'High'})
        self.http.payloads['ff_calendar_thisweek']=json.dumps(d).encode()
        report,_=self.cycle()
        self.assertFalse(any(e['scheduled_at'].startswith('2026-11-22') for e in report['calendar']['events']))
    def test_invalid_body_degrades_without_crashing(self):
        self.http.payloads['mm_calendar_thisweek']=b'<html>unexpected</html>'
        report,_=self.cycle()
        self.assertEqual(report['status'],'PARTIAL')
        self.assertTrue(any(e['source_id']=='FF_CALENDAR' for e in report['calendar']['events']))
    def test_m04_official_gate_partial(self):
        # Checks no new source silently grants execution.
        _,b=self.cycle()
        self.assertEqual(b['advisory']['execution_permission'],'BLOCKED')
        self.assertTrue(b['advisory']['does_not_override_m04_m11_m14'])
    def test_rejects_phantom_direction(self):
        report,_=self.cycle()
        self.assertEqual(report['interpretation']['gold_direction'],'UNKNOWN')
        self.assertEqual(report['interpretation']['usd_direction'],'UNKNOWN')
    def test_if_both_fe_offline_bls_retained(self):
        self.http.payloads['ff_calendar_thisweek']=urllib.error.URLError('offline')
        self.http.payloads['mm_calendar_thisweek']=urllib.error.URLError('offline')
        report,_=self.cycle()
        self.assertTrue(any(e['source_id']=='BLS_CALENDAR' for e in report['calendar']['events']))
        self.assertEqual(report['status'],'PARTIAL')
    def test_age_limit_does_not_reinterpret_news_date(self):
        report,_=self.cycle(NOW+dt.timedelta(hours=15))
        self.assertTrue(all(r['time_quality'] in ('PUBLISHED','UNKNOWN','FIRST_SEEN_ONLY') for r in report['news']['recent']))

if __name__=='__main__':unittest.main(verbosity=2)
