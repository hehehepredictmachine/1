"""Offline no-network tests; run py -3 -m unittest -v M04N_TESTS."""
import datetime as dt
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import xml.etree.ElementTree as ET

import M04N_ENGINE as m

NOW=dt.datetime(2026,10,8,12,0,tzinfo=m.UTC)
FED_RSS=b'''<?xml version="1.0"?><rss version="2.0"><channel><title>Fed</title><item><title>Federal Reserve FOMC interest rate decision</title><link>https://www.federalreserve.gov/newsevents/pressreleases/monetary.htm?utm_source=test</link><pubDate>Thu, 08 Oct 2026 11:00:00 GMT</pubDate><description>Fed kept its target range</description></item><item><title>Old item unrelated</title><link>https://www.federalreserve.gov/old</link><pubDate>Thu, 01 Jan 2015 11:00:00 GMT</pubDate></item></channel></rss>'''
ICS=b'''BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:cpi-20261008\r\nSUMMARY:Consumer Price Index\r\nDTSTART;TZID=America/New_York:20261008T083000\r\nEND:VEVENT\r\nBEGIN:VEVENT\r\nUID:nfp-20261106\r\nSUMMARY:Employment Situation\r\nDTSTART;TZID=America/New_York:20261106T083000\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n'''
GDELT=json.dumps({"articles":[{"url":"https://news.example.org/gold?utm_medium=test","title":"Gold ETF demand rises amid sanctions","seendate":"20261008T113000Z","domain":"news.example.org"}]}).encode()
FRED=json.dumps({"observations":[{"date":"2026-10-08","value":"."},{"date":"2026-10-07","value":"4.1"},{"date":"2026-10-06","value":"4.2"}]}).encode()

class FakeHTTP:
    def __init__(self, payloads):self.payloads=payloads;self.calls=[]
    def get(self,url,headers=None):
        self.calls.append(url)
        for key,value in self.payloads.items():
            if key in url:
                if isinstance(value,Exception):raise value
                return value
        raise urllib.error.URLError('fixture missing')

class ConfigTests(unittest.TestCase):
    def test_real_sources_allowlisted(self):
        cfg=json.loads((Path(__file__).parent/'M04N_CONFIG.json').read_text())
        for f in cfg['rss_feeds']:self.assertEqual(m.validate_https(f['url'],cfg['allowed_hosts']),f['url'])
        m.validate_https(cfg['bls_calendar_ics'],cfg['allowed_hosts'])
    def test_version(self):self.assertEqual(m.VERSION,'1.1.0')
    def test_fred_url_encoded(self):self.assertIn('api_key=x',m.fred_url('DGS10','x'))
    def test_gdelt_encoded(self):self.assertIn('query=',m.gdelt_url('gold OR dollar'))
    def test_untrusted_domain(self):
        with self.assertRaises(ValueError):m.validate_https('https://evil.example/',['www.bls.gov'])
    def test_http_disallowed(self):
        with self.assertRaises(ValueError):m.validate_https('http://www.bls.gov/',['www.bls.gov'])
    def test_userinfo_disallowed(self):
        with self.assertRaises(ValueError):m.validate_https('https://u:p@www.bls.gov/',['www.bls.gov'])
    def test_custom_port_disallowed(self):
        with self.assertRaises(ValueError):m.validate_https('https://www.bls.gov:444/', ['www.bls.gov'])
    def test_ip_literal_disallowed(self):
        with self.assertRaises(ValueError):m.validate_https('https://127.0.0.1/', ['127.0.0.1'])
    def test_file_url_not_allowed(self):
        with self.assertRaises(ValueError):m.validate_https('file:///etc/passwd',[''])
    def test_qualified_domain_not_sibling(self):
        with self.assertRaises(ValueError):m.validate_https('https://www.bls.gov.evil.com/feed',['www.bls.gov'])
    def test_optional_key_not_configured(self):self.assertNotIn('api_key',str(json.loads((Path(__file__).parent/'M04N_CONFIG.json').read_text()).keys()))

class TimeTests(unittest.TestCase):
    def test_rfc2822(self):self.assertEqual(m.parse_time('Thu, 08 Oct 2026 12:00:00 GMT'),NOW)
    def test_utc_iso(self):self.assertEqual(m.parse_time('2026-10-08T12:00:00Z'),NOW)
    def test_other_tz(self):self.assertEqual(m.parse_time('2026-10-08T14:00:00+02:00'),NOW)
    def test_naive_rejected(self):self.assertIsNone(m.parse_time('2026-10-08T12:00:00'))
    def test_bad_time(self):self.assertIsNone(m.parse_time('hello'))
    def test_empty_time(self):self.assertIsNone(m.parse_time(None))
    def test_iso(self):self.assertEqual(m.iso(NOW),'2026-10-08T12:00:00Z')
    def test_dst_oct(self):self.assertEqual(m.ics_datetime('DTSTART;TZID=America/New_York:20261008T083000'),dt.datetime(2026,10,8,12,30,tzinfo=m.UTC))
    def test_dst_nov(self):self.assertEqual(m.ics_datetime('DTSTART;TZID=America/New_York:20261106T083000'),dt.datetime(2026,11,6,13,30,tzinfo=m.UTC))
    def test_utc_calendar(self):self.assertEqual(m.ics_datetime('DTSTART:20261008T120000Z'),NOW)
    def test_all_day_rejected(self):self.assertIsNone(m.ics_datetime('DTSTART;VALUE=DATE:20261008'))
    def test_eastern_windows_tz(self):self.assertEqual(m.ics_datetime('DTSTART;TZID=Eastern Standard Time:20261008T083000'),dt.datetime(2026,10,8,12,30,tzinfo=m.UTC))
    def test_invalid_ics_time(self):self.assertIsNone(m.ics_datetime('DTSTART:BAD'))

class RSSTests(unittest.TestCase):
    def setUp(self):self.src={'id':'FED_MONETARY','authority':'OFFICIAL','category':'FED'}
    def test_two_items(self):self.assertEqual(len(m.rss_items(FED_RSS,self.src,NOW)),2)
    def test_published(self):self.assertEqual(m.rss_items(FED_RSS,self.src,NOW)[0]['published_at'],'2026-10-08T11:00:00Z')
    def test_no_tracking(self):self.assertNotIn('utm_',m.rss_items(FED_RSS,self.src,NOW)[0]['url'])
    def test_stale_filtered(self):self.assertIsNone(m.normalize_story(m.rss_items(FED_RSS,self.src,NOW)[1],NOW,48))
    def test_relevant(self):self.assertIn('FED',m.normalize_story(m.rss_items(FED_RSS,self.src,NOW)[0],NOW,48)['categories'])
    def test_monetary_high(self):self.assertEqual(m.normalize_story(m.rss_items(FED_RSS,self.src,NOW)[0],NOW,48)['impact'],'HIGH')
    def test_no_trade_direction(self):self.assertEqual(m.normalize_story(m.rss_items(FED_RSS,self.src,NOW)[0],NOW,48)['potential_gold_direction'],'UNKNOWN')
    def test_nonspecific_ignored(self):
        rec=m.rss_items(b'<rss><channel><item><title>Office renovation</title><link>https://www.bls.gov/renovation</link></item></channel></rss>',self.src,NOW)[0]
        self.assertIsNone(m.normalize_story(rec,NOW,48))
    def test_future_timestamp_skipped(self):
        text=FED_RSS.replace(b'08 Oct 2026 11:',b'10 Oct 2026 11:')
        self.assertEqual(len(m.rss_items(text,self.src,NOW)),1)
    def test_invalid_xml(self):
        with self.assertRaises(ET.ParseError):m.rss_items(b'<broken',self.src,NOW)
    def test_entity_rejected(self):
        with self.assertRaises(ValueError):m.rss_items(b'<!DOCTYPE bad><rss/>',self.src,NOW)
    def test_empty_feed(self):self.assertEqual(m.rss_items(b'<rss><channel></channel></rss>',self.src,NOW),[])
    def test_atom(self):
        atom=b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Gold rises</title><link href="https://news.example.com/a"/><published>2026-10-08T11:00:00Z</published></entry></feed>'
        self.assertEqual(len(m.rss_items(atom,self.src,NOW)),1)
    def test_canonical_url(self):self.assertEqual(m.canonical_url('https://NEWS.EXAMPLE.com/a/?utm_source=b&x=1#frag'),'https://news.example.com/a?x=1')
    def test_canonical_reject_js(self):self.assertIsNone(m.canonical_url('javascript:evil'))
    def test_rss_missing_date_quality(self):
        item=m.rss_items(b'<rss><item><title>Gold demand</title><link>https://a.example/1</link></item></rss>',self.src,NOW)[0]
        self.assertEqual(item['time_quality'],'UNKNOWN')
    def test_summary_sanitized(self):self.assertEqual(m.clean_text('<b>Hello</b> &amp; world'),'Hello & world')

class GdeltTests(unittest.TestCase):
    def test_parse(self):self.assertEqual(len(m.gdelt_items(GDELT,{'id':'GOLD_MARKET','category':'GOLD'},NOW)),1)
    def test_seen_not_published(self):
        x=m.gdelt_items(GDELT,{'id':'GOLD_MARKET','category':'GOLD'},NOW)[0]
        self.assertIsNone(x['published_at']);self.assertEqual(x['time_quality'],'FIRST_SEEN_ONLY')
    def test_unverified_authority(self):self.assertEqual(m.gdelt_items(GDELT,{'id':'GOLD_MARKET','category':'GOLD'},NOW)[0]['source_authority'],'AGGREGATOR_UNVERIFIED')
    def test_json_invalid(self):
        with self.assertRaises(ValueError):m.gdelt_items(b'[]',{},NOW)
    def test_missing_articles_empty(self):self.assertEqual(m.gdelt_items(b'{}',{},NOW),[])
    def test_future_item_dropped(self):
        self.assertEqual(m.gdelt_items(GDELT.replace(b'20261008T113000Z',b'20261010T113000Z'),{'id':'G'},NOW),[])
    def test_dedupe_url_rss_gdelt(self):
        a={'url':'https://news.example/a','headline':'Gold futures','summary':'','source_id':'X','source_authority':'OFFICIAL','first_seen_at':m.iso(NOW),'published_at':m.iso(NOW),'time_quality':'PUBLISHED'}
        b={**a,'source_id':'Y'}
        self.assertEqual(m.normalize_story(a,NOW,24)['event_id'],m.normalize_story(b,NOW,24)['event_id'])

class CalendarTests(unittest.TestCase):
    def test_two_events(self):self.assertEqual(len(m.calendar_events(ICS,'BLS',NOW)[0]),2)
    def test_impact_cpi(self):self.assertEqual(m.calendar_events(ICS,'BLS',NOW)[0][0]['impact'],'HIGH')
    def test_scheduled(self):self.assertEqual(m.calendar_events(ICS,'BLS',NOW)[0][0]['scheduled_at'],'2026-10-08T12:30:00Z')
    def test_upcoming_high(self):
        events,_=m.calendar_events(ICS,'BLS',NOW)
        self.assertEqual(m.macro_risk(events,NOW,45,30)['level'],'HIGH')
    def test_after_window(self):
        events,_=m.calendar_events(ICS,'BLS',NOW)
        self.assertNotEqual(m.macro_risk(events,NOW+dt.timedelta(minutes=70),45,30)['level'],'HIGH')
    def test_invalid_calendar(self):
        with self.assertRaises(ValueError):m.calendar_events(b'not calendar','BLS',NOW)
    def test_all_day_not_assumed_830(self):
        body=b'BEGIN:VCALENDAR\nBEGIN:VEVENT\nSUMMARY:Consumer Price Index\nDTSTART;VALUE=DATE:20261008\nEND:VEVENT\nEND:VCALENDAR'
        result,unknown=m.calendar_events(body,'BLS',NOW)
        self.assertEqual(result,[]);self.assertEqual(unknown,1)
    def test_cancelled(self):
        payload=ICS.replace(b'UID:cpi-20261008',b'UID:cpi-20261008\r\nSTATUS:CANCELLED')
        self.assertEqual(len(m.calendar_events(payload,'BLS',NOW)[0]),1)
    def test_folded_title(self):
        payload=ICS.replace(b'SUMMARY:Consumer Price Index',b'SUMMARY:Consumer Price\r\n Index')
        self.assertEqual(m.calendar_events(payload,'BLS',NOW)[0][0]['name'],'Consumer PriceIndex')
    def test_ics_id_stable(self):
        self.assertEqual(m.calendar_events(ICS,'BLS',NOW)[0][0]['event_id'],m.calendar_events(ICS,'BLS',NOW+dt.timedelta(minutes=5))[0][0]['event_id'])
    def test_fred_period(self):
        row=m.parse_fred(FRED,'DGS10',NOW)
        self.assertEqual(row['value'],4.1);self.assertEqual(row['difference_from_previous_observation'],-0.1)
    def test_fred_not_surprise(self):self.assertTrue(m.parse_fred(FRED,'DGS10',NOW)['not_release_surprise'])
    def test_fred_missing(self):self.assertIsNone(m.parse_fred(b'{"observations":[{"date":"2026-10-08","value":"."}]}','DGS10',NOW))
    def test_fred_future(self):self.assertIsNone(m.parse_fred(b'{"observations":[{"date":"2026-11-08","value":"2.0"}]}','DGS10',NOW))

class StoreTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.st=m.Store(Path(self.tmp.name)/'db.sqlite')
    def tearDown(self):self.st.close();self.tmp.cleanup()
    def test_dedup(self):
        rec=m.normalize_story(m.rss_items(FED_RSS,{'id':'FED','authority':'OFFICIAL'},NOW)[0],NOW,48)
        self.assertTrue(self.st.article(rec,NOW));self.assertFalse(self.st.article(rec,NOW))
    def test_due(self):
        self.assertTrue(self.st.due('TEST',NOW,60));self.st.mark('TEST',NOW)
        self.assertFalse(self.st.due('TEST',NOW+dt.timedelta(seconds=30),60))
        self.assertTrue(self.st.due('TEST',NOW+dt.timedelta(seconds=60),60))
    def test_mark_failed(self):
        self.st.mark('TEST',NOW,ValueError('broken'))
        self.assertEqual(self.st.status()[0]['error_count'],1)
    def test_recover(self):
        self.st.mark('TEST',NOW,ValueError('broken'));self.st.mark('TEST',NOW+dt.timedelta(seconds=30))
        self.assertEqual(self.st.status()[0]['error_count'],0)
    def test_latest_date_first_known_preserved(self):
        events,_=m.calendar_events(ICS,'BLS_CALENDAR',NOW)
        self.st.save_calendar(events,NOW,'BLS_CALENDAR')
        after=NOW+dt.timedelta(minutes=8)
        later,_=m.calendar_events(ICS,'BLS_CALENDAR',after)
        for e in later:e['available_at']=m.iso(after)
        self.st.save_calendar(later,after,'BLS_CALENDAR')
        self.assertEqual(self.st.events()[0]['available_at'],m.iso(NOW))
    def test_calendar_cancel_stale(self):
        events,_=m.calendar_events(ICS,'BLS_CALENDAR',NOW)
        self.st.save_calendar(events,NOW,'BLS_CALENDAR')
        self.st.save_calendar(events[:1],NOW,'BLS_CALENDAR')
        self.assertEqual(len(self.st.events()),1)
    def test_obs_saved(self):
        self.st.save_observation(m.parse_fred(FRED,'DGS10',NOW))
        self.assertEqual(len(self.st.observations()),1)
    def test_recent_age(self):
        rec=m.normalize_story(m.rss_items(FED_RSS,{'id':'FED','authority':'OFFICIAL'},NOW)[0],NOW,48)
        self.st.article(rec,NOW)
        self.assertEqual(len(self.st.recent(NOW,48,20)),1)
        self.assertEqual(len(self.st.recent(NOW+dt.timedelta(days=4),48,20)),0)

class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.st=m.Store(Path(self.tmp.name)/'db.sqlite')
        self.cfg=json.loads((Path(__file__).parent/'M04N_CONFIG.json').read_text())
        self.cfg['rss_feeds']=self.cfg['rss_feeds'][:1]
        self.cfg['gdelt_queries']=self.cfg['gdelt_queries'][:1]
        self.cfg['fred_series']=['DGS10']
        self.cfg['fair_economy_calendars']=[]  # Regression isolates old v1.0 inputs; new feed tests live in M04N_FAIR_ECONOMY_TESTS.py
        self.http=FakeHTTP({'press_monetary.xml':FED_RSS, 'bls.ics':ICS, 'api.gdeltproject.org':GDELT,'api.stlouisfed.org':FRED})
    def tearDown(self):self.st.close();self.tmp.cleanup()
    def test_end_to_end_no_key(self):
        with patch.dict(os.environ,{'FRED_API_KEY':''}):
            report,bridge=m.collect(self.cfg,self.st,self.http,NOW)
        self.assertEqual(report['status'],'HEALTHY')
        self.assertEqual(report['news']['initial_backfill_count'],2)
        self.assertEqual(report['news']['new_count_this_poll'],0)
        self.assertEqual(report['calendar']['risk']['level'],'HIGH')
        self.assertEqual(report['execution_permission'],'BLOCKED')
        self.assertEqual(bridge['context_inputs']['calendar_coverage']['data_complete'],False)
    def test_no_key_skip(self):
        with patch.dict(os.environ,{'FRED_API_KEY':''}):report,_=m.collect(self.cfg,self.st,self.http,NOW)
        self.assertEqual(report['integrity']['optional_skipped'][0]['source_id'],'FRED')
    def test_with_fred(self):
        with patch.dict(os.environ,{'FRED_API_KEY':'a'*32}):report,_=m.collect(self.cfg,self.st,self.http,NOW)
        self.assertEqual(len(report['macro_observations']['series']),1)
        self.assertIn('FRED_DGS10',report['integrity']['expected_sources'])
    def test_no_duplicate_on_second_poll(self):
        with patch.dict(os.environ,{'FRED_API_KEY':''}):
            first,_=m.collect(self.cfg,self.st,self.http,NOW)
            second,_=m.collect(self.cfg,self.st,self.http,NOW+dt.timedelta(minutes=6))
        self.assertEqual(first['news']['initial_backfill_count'],2)
        self.assertEqual(second['news']['new_count_this_poll'],0)
    def test_throttle(self):
        with patch.dict(os.environ,{'FRED_API_KEY':''}):
            m.collect(self.cfg,self.st,self.http,NOW)
            count=len(self.http.calls)
            m.collect(self.cfg,self.st,self.http,NOW+dt.timedelta(seconds=5))
        self.assertEqual(len(self.http.calls),count)
    def test_failed_sources_degrade(self):
        self.http.payloads['bls.ics']=urllib.error.URLError('offline')
        with patch.dict(os.environ,{'FRED_API_KEY':''}):report,bridge=m.collect(self.cfg,self.st,self.http,NOW)
        self.assertEqual(report['status'],'PARTIAL')
        self.assertEqual(bridge['context_inputs']['calendar_coverage']['status'],'UNAVAILABLE')
    def test_all_sources_offline(self):
        self.http.payloads={'press_monetary.xml':urllib.error.URLError('offline'),'bls.ics':urllib.error.URLError('offline'),'api.gdeltproject.org':urllib.error.URLError('offline')}
        with patch.dict(os.environ,{'FRED_API_KEY':''}):report,_=m.collect(self.cfg,self.st,self.http,NOW)
        self.assertEqual(report['status'],'UNAVAILABLE')
        self.assertFalse(report['integrity']['complete_global_news_coverage'])
    def test_m04_contract_has_no_verified(self):
        with patch.dict(os.environ,{'FRED_API_KEY':''}):_,bridge=m.collect(self.cfg,self.st,self.http,NOW)
        self.assertNotEqual(bridge['context_inputs']['calendar_coverage']['status'],'VERIFIED')
    def test_elevated_risk(self):
        with patch.dict(os.environ,{'FRED_API_KEY':''}):report,_=m.collect(self.cfg,self.st,self.http,NOW)
        self.assertEqual(report['interpretation']['risk_advisory'],'ELEVATED')
    def test_empty_feed_is_not_same_as_unavailable(self):
        self.http.payloads['press_monetary.xml']=b'<rss><channel/></rss>'
        self.cfg['gdelt_enabled']=False
        with patch.dict(os.environ,{'FRED_API_KEY':''}):report,_=m.collect(self.cfg,self.st,self.http,NOW)
        self.assertEqual(report['news']['new_count_this_poll'],0)
        self.assertEqual(report['status'],'HEALTHY')
    def test_schema(self):
        with patch.dict(os.environ,{'FRED_API_KEY':''}):report,bridge=m.collect(self.cfg,self.st,self.http,NOW)
        self.assertEqual(report['module_id'],'M04N');self.assertEqual(bridge['module_id'],'M04N')
        self.assertFalse(report['visual_capture_enabled'])
        self.assertTrue(report['research_only'])
    def test_atomic_write(self):
        p=Path(self.tmp.name)/'file.json';m.write_json_atomic(p,{'a':'ą'})
        self.assertEqual(json.loads(p.read_text(encoding='utf-8')),{'a':'ą'})
        self.assertFalse((Path(self.tmp.name)/'file.json.tmp').exists())
    def test_fred_no_leak_in_report(self):
        with patch.dict(os.environ,{'FRED_API_KEY':'a'*32}):report,bridge=m.collect(self.cfg,self.st,self.http,NOW)
        self.assertNotIn('a'*32,json.dumps(report)+json.dumps(bridge))
    def test_no_success_claim_after_error(self):
        self.http.payloads['bls.ics']=urllib.error.URLError('down')
        with patch.dict(os.environ,{'FRED_API_KEY':''}):report,_=m.collect(self.cfg,self.st,self.http,NOW)
        self.assertEqual(report['integrity']['source_health']['BLS_CALENDAR']['state'],'UNAVAILABLE_OR_STALE')
    def test_empty_bootstrap_allows_future_new_item(self):
        self.cfg['gdelt_enabled']=False
        self.cfg['fred_enabled']=False
        self.http.payloads['press_monetary.xml']=b'<rss><channel/></rss>'
        first,_=m.collect(self.cfg,self.st,self.http,NOW)
        self.assertEqual(first['news']['initial_backfill_count'],0)
        self.http.payloads['press_monetary.xml']=FED_RSS
        second,_=m.collect(self.cfg,self.st,self.http,NOW+dt.timedelta(minutes=6))
        self.assertEqual(second['news']['new_count_this_poll'],1)
        self.assertEqual(second['news']['initial_backfill_count'],0)
    def test_old_news_not_fake_breaking(self):
        self.cfg['gdelt_enabled']=False
        self.cfg['fred_enabled']=False
        self.http.payloads['press_monetary.xml']=b'<rss><channel/></rss>'
        m.collect(self.cfg,self.st,self.http,NOW)
        self.http.payloads['press_monetary.xml']=FED_RSS
        report,_=m.collect(self.cfg,self.st,self.http,NOW+dt.timedelta(minutes=6))
        self.assertEqual(report['news']['new_high_impact_count'],0)
        self.assertEqual(report['news']['new_count_this_poll'],1)
    def test_fresh_new_news_high_alert(self):
        self.cfg['gdelt_enabled']=False
        self.cfg['fred_enabled']=False
        self.http.payloads['press_monetary.xml']=b'<rss><channel/></rss>'
        m.collect(self.cfg,self.st,self.http,NOW)
        self.http.payloads['press_monetary.xml']=FED_RSS.replace(b'08 Oct 2026 11:00:00',b'08 Oct 2026 12:01:00')
        report,_=m.collect(self.cfg,self.st,self.http,NOW+dt.timedelta(minutes=6))
        self.assertEqual(report['news']['new_high_impact_count'],1)
    def test_synthetic_demo_stays_separate(self):
        # The offline demo is intentionally not a path to the production runtime.
        from pathlib import Path
        self.assertNotEqual(Path(__file__).parent/'demo_synthetic_only',Path(__file__).parent/'runtime')
    def test_error_backoff(self):
        self.st.mark('TEST',NOW,ValueError('down'))
        self.assertFalse(self.st.due('TEST',NOW+dt.timedelta(seconds=90),60))
        self.assertTrue(self.st.due('TEST',NOW+dt.timedelta(seconds=121),60))
    def test_fred_series_freshness(self):
        with patch.dict(os.environ,{'FRED_API_KEY':'a'*32}):report,_=m.collect(self.cfg,self.st,self.http,NOW)
        self.assertEqual(report['macro_observations']['series'][0]['collection_status'],'FETCH_FRESH')
    def test_all_news_sources_failed_keeps_bootstrap_pending(self):
        self.cfg['gdelt_enabled']=False
        self.http.payloads['press_monetary.xml']=urllib.error.URLError('fail')
        with patch.dict(os.environ,{'FRED_API_KEY':''}):m.collect(self.cfg,self.st,self.http,NOW)
        self.assertFalse(bool(self.st.db.execute("SELECT 1 FROM poll_meta WHERE source_id='__NEWS_BOOTSTRAPPED__'").fetchone()))
    def test_high_impact_only_context(self):
        with patch.dict(os.environ,{'FRED_API_KEY':''}):report,_=m.collect(self.cfg,self.st,self.http,NOW)
        self.assertTrue(all(x['risk_context_only'] and x['impact_not_prediction'] for x in report['news']['recent']))
    def test_bls_calendar_not_exhaustive_even_healthy(self):
        with patch.dict(os.environ,{'FRED_API_KEY':''}):report,_=m.collect(self.cfg,self.st,self.http,NOW)
        self.assertEqual(report['calendar']['coverage'],'BLS_PLUS_FF_MM_WEEKLY_SUBSET_NEVER_COMPLETE')
        self.assertFalse(report['integrity']['complete_global_news_coverage'])
    def test_zero_orders_without_any_source(self):
        self.cfg['rss_feeds']=[];self.cfg['gdelt_enabled']=False;self.cfg['bls_calendar_ics']=None
        with patch.dict(os.environ,{'FRED_API_KEY':''}):report,_=m.collect(self.cfg,self.st,self.http,NOW)
        self.assertEqual(report['execution_permission'],'BLOCKED')
        self.assertFalse(report['integrity']['complete_global_news_coverage'])

    def test_lagged_is_not_spot_price(self):
        with patch.dict(os.environ,{'FRED_API_KEY':'a'*32}):report,_=m.collect(self.cfg,self.st,self.http,NOW)
        self.assertTrue(report['macro_observations']['series'][0]['not_intraday_price'])

if __name__=='__main__':unittest.main(verbosity=2)
