"""Produce deliberately SYNTHETIC reports; never mistaken for market signals."""
from pathlib import Path
import datetime as dt
import json
import tempfile
import M04N_ENGINE as m

class FixtureHTTP:
    def __init__(self,now):self.now=now
    def get(self,url,headers=None):
        if 'bls.ics' in url:
            local=(self.now+dt.timedelta(minutes=30)).astimezone(m.ZoneInfo('America/New_York'))
            stamp=local.strftime('%Y%m%dT%H%M%S')
            return f'BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:DEMO-1\nSUMMARY:Consumer Price Index (synthetic)\nDTSTART;TZID=America/New_York:{stamp}\nEND:VEVENT\nEND:VCALENDAR'.encode()
        if 'fred/' in url:return b'{"observations":[{"date":"2026-10-07","value":"3.5"}]}'
        if 'gdeltproject' in url:return b'{"articles":[]}'
        title='Federal Reserve interest rate decision (synthetic test)'
        date=m.email.utils.format_datetime(self.now)
        return f'<rss><channel><item><title>{title}</title><link>https://www.federalreserve.gov/newsevents/synthetic-demonstration</link><pubDate>{date}</pubDate></item></channel></rss>'.encode()

def main():
    root=Path(__file__).parent;now=m.utc_now()
    cfg=json.loads((root/'M04N_CONFIG.json').read_text(encoding='utf-8'))
    cfg['fred_enabled']=False
    cfg['fair_economy_calendars']=[]  # baseline synthetic fixture; no simulated Fair Economy claims
    folder=root/'demo_synthetic_only';folder.mkdir(exist_ok=True)
    demo_db=folder/'DEMO_STATE.sqlite'
    if demo_db.exists():demo_db.unlink()  # Synthetic demo is always recreated deterministically.
    store=m.Store(demo_db)
    try:
        out,bridge=m.collect(cfg,store,FixtureHTTP(now),now,force=True)
        out['status']='SYNTHETIC_TEST_ONLY';out['synthetic']=True
        bridge['synthetic']=True;bridge['source_status']='SYNTHETIC_TEST_ONLY'
        m.write_json_atomic(folder/'M04N_SYNTHETIC.json',out)
        m.write_json_atomic(folder/'M04_CONTEXT_SYNTHETIC.json',bridge)
        print('SYNTHETIC examples created in demo_synthetic_only/ (not real market data)')
    finally:store.close()
if __name__=='__main__':main()
