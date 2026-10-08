"""MasterQUO M04N: read-only public-information collector (stdlib, no trading)."""
from __future__ import annotations
import argparse
import datetime as dt
import email.utils
import hashlib
import html
import ipaddress
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import urllib.parse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

UTC = dt.timezone.utc
VERSION = "1.1.0"
RELEVANT = {
    "FED": ("fed", "fomc", "federal reserve", "interest rate", "monetary policy", "powell", "hawkish", "dovish", "balance sheet", "qt", "qe"),
    "INFLATION": ("inflation", "cpi", "ppi", "pce", "consumer price", "producer price", "core price", "prices"),
    "LABOR": ("nonfarm", "payroll", "employment", "unemployment", "jobs", "labor", "wage", "jolts"),
    "YIELDS": ("treasury", "bond yield", "real yield", "10-year", "10 year", "yield curve", "tips"),
    "GOLD": ("gold", "xauusd", "bullion", "precious metal", "comex", "gold futures", "gold price"),
    "USD": ("dollar", "dxy", "usd", "currency", "exchange rate", "foreign exchange"),
    "GEOPOLITICS": ("war", "sanction", "missile", "ceasefire", "geopolit", "conflict", "invasion", "military", "tariff", "trade war"),
    "PHYSICAL": ("gold etf", "gold reserve", "gold purchas", "central bank gold", "gold import", "jewelry demand", "gold mine", "gold supply", "gold output"),
    "RISK": ("liquidity", "volatility", "bank crisis", "debt ceiling", "shutdown", "recession", "market stress"),
}
HIGH_WORDS = ("fomc", "interest rate decision", "rate decision", "nonfarm", "payroll", "consumer price index", " cpi ", "core pce", "inflation data", "emergency", "war", "attack", "missile", "sanctions", "default", "bank crisis", "powell", "jobs report")
EXTREME_WORDS = ("emergency rate cut", "emergency rate hike", "nuclear", "military invasion", "sovereign default")
CALENDAR_HIGH = ("consumer price index", "cpi", "employment situation", "nonfarm", "producer price index", "ppi", "job openings", "employment cost index")
CALENDAR_MED = ("real earnings", "productivity", "import", "export", "wages")


def utc_now():
    return dt.datetime.now(UTC)


def parse_time(value):
    if isinstance(value, dt.datetime):
        return value.astimezone(UTC) if value.tzinfo else None
    if not value or not isinstance(value, str):
        return None
    value=value.strip()
    try:
        parsed=dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo:
            return parsed.astimezone(UTC)
    except ValueError:
        pass
    try:
        parsed=email.utils.parsedate_to_datetime(value)
        return parsed.astimezone(UTC) if parsed.tzinfo else None
    except (ValueError,TypeError,OverflowError):
        return None


def iso(value):
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z") if value else None


def clean_text(value):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]*>", " ", str(value or "")))).strip()[:600]


def validate_https(url, allow_hosts):
    parsed=urllib.parse.urlsplit(url)
    if parsed.scheme!="https" or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None,443):
        raise ValueError("ONLY_HTTPS_APPROVED_HOSTS")
    hostname=parsed.hostname.lower().rstrip(".")
    if hostname not in {h.lower() for h in allow_hosts}:
        raise ValueError("HOST_NOT_ALLOWLISTED")
    try:
        ipaddress.ip_address(hostname)
        raise ValueError("IP_LITERAL_NOT_ALLOWED")
    except ValueError as exc:
        if str(exc)=="IP_LITERAL_NOT_ALLOWED":
            raise
    return url


class _RestrictedRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, allow_hosts):
        self.allow_hosts=allow_hosts
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_https(newurl, self.allow_hosts)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class HTTPClient:
    def __init__(self, hosts, timeout=8, max_bytes=1_500_000):
        self.hosts=hosts; self.timeout=timeout; self.max_bytes=max_bytes
        self.opener=urllib.request.build_opener(_RestrictedRedirect(hosts))
    def get(self, url, headers=None):
        validate_https(url,self.hosts)
        req=urllib.request.Request(url,headers={"User-Agent":"MasterQUO-M04N/1.0 (+offline research; read-only)","Accept":"application/rss+xml, application/xml, application/json, text/calendar, */*",**(headers or {})})
        with self.opener.open(req,timeout=self.timeout) as response:
            if response.status != 200:
                raise ValueError("HTTP_STATUS_"+str(response.status))
            data=response.read(self.max_bytes+1)
            if len(data)>self.max_bytes:
                raise ValueError("RESPONSE_TOO_LARGE")
            return data


def canonical_url(url):
    try:
        p=urllib.parse.urlsplit(url.strip())
        if p.scheme not in ("http","https") or not p.hostname:
            return None
        if p.hostname.lower() in ("localhost",) or p.username or p.password:
            return None
        qs=[(k,v) for k,v in urllib.parse.parse_qsl(p.query) if not k.lower().startswith("utm_") and k.lower() not in ("fbclid","gclid","mc_cid","mc_eid")]
        return urllib.parse.urlunsplit((p.scheme.lower(),p.netloc.lower(),p.path.rstrip("/") or "/",urllib.parse.urlencode(sorted(qs)),""))
    except ValueError:
        return None


def new_id(prefix, value):
    return prefix+":"+hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


def text_at(element, name):
    for child in element:
        if child.tag.rsplit('}',1)[-1] == name:
            return (child.text or "").strip()
    return ""


def rss_items(payload, source, now):
    if len(payload)>1_500_000 or b"<!DOCTYPE" in payload.upper() or b"<!ENTITY" in payload.upper():
        raise ValueError("XML_UNTRUSTED")
    root=ET.fromstring(payload)
    entries=[e for e in root.iter() if e.tag.rsplit('}',1)[-1] in ("item","entry")]
    if not entries and root.tag.rsplit('}',1)[-1] not in ("rss","feed","RDF"):
        raise ValueError("NOT_A_FEED")
    result=[]
    for e in entries[:200]:
        title=clean_text(text_at(e,"title"))
        summary=clean_text(text_at(e,"description") or text_at(e,"summary"))
        url=text_at(e,"link")
        if not url:
            for child in e:
                if child.tag.rsplit('}',1)[-1]=="link" and child.attrib.get("href"):
                    url=child.attrib["href"]; break
        url=canonical_url(url)
        date=parse_time(text_at(e,"pubDate") or text_at(e,"published") or text_at(e,"updated") or text_at(e,"date"))
        if not title or not url or (date and date>now+dt.timedelta(minutes=5)):
            continue
        result.append({"headline":title,"summary":summary,"url":url,"source_id":source["id"],"source_authority":source.get("authority","UNKNOWN"),"published_at":iso(date),"time_quality":"PUBLISHED" if date else "UNKNOWN","first_seen_at":iso(now),"origin_category":source.get("category")})
    return result


def gdelt_items(payload, source, now):
    obj=json.loads(payload)
    if not isinstance(obj,dict) or not isinstance(obj.get("articles",[]),list):
        raise ValueError("BAD_GDELT_RESPONSE")
    out=[]
    for row in obj.get("articles",[])[:100]:
        if not isinstance(row,dict):continue
        url=canonical_url(str(row.get("url") or "")); title=clean_text(row.get("title"))
        if not url or not title: continue
        date=None
        stamp=str(row.get("seendate") or "")
        if re.fullmatch(r"\d{8}T\d{6}Z",stamp):
            date=dt.datetime.strptime(stamp,"%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        if date and date>now+dt.timedelta(minutes=5):continue
        out.append({"headline":title,"summary":"","url":url,"source_id":source["id"],"source_authority":"AGGREGATOR_UNVERIFIED","published_at":None,"time_quality":"FIRST_SEEN_ONLY","first_seen_at":iso(date or now),"origin_category":source.get("category"),"origin_domain":row.get("domain")})
    return out


def tags_for(headline, summary, hint=None):
    text=(" "+headline.lower()+" "+summary.lower()+" ")[:1100]
    hits={k for k,words in RELEVANT.items() if any(word in text for word in words)}
    if hint == "FED" and ("fed" in text or "reserve" in text or "rate" in text or "powell" in text):hits.add("FED")
    if hint=="GOLD":hits.add("GOLD")
    if hint=="GEOPOLITICS" and any(w in text for w in RELEVANT["GEOPOLITICS"]):hits.add("GEOPOLITICS")
    if hint=="PHYSICAL_GOLD" and any(w in text for w in RELEVANT["PHYSICAL"]): hits.add("PHYSICAL")
    return sorted(hits)


def impact_for(headline, tags):
    text=" "+headline.lower()+" "
    if any(w in text for w in EXTREME_WORDS):return "EXTREME"
    if any(w in text for w in HIGH_WORDS):return "HIGH"
    if {"FED","INFLATION","LABOR","GEOPOLITICS"}&set(tags):return "MEDIUM"
    return "LOW"


def normalize_story(item, now, max_age_hours):
    headline=item["headline"]
    tags=tags_for(headline,item.get("summary", ""),item.get("origin_category"))
    if not tags:return None
    published=parse_time(item.get("published_at"))
    seen=parse_time(item.get("first_seen_at"))
    event_time=published or seen
    if event_time is None or event_time>now+dt.timedelta(minutes=5):return None
    age_hours=(now-event_time).total_seconds()/3600
    if age_hours>max_age_hours:return None
    url=item["url"]
    out={"event_id":new_id("NEWS",url),"headline":headline,"summary":item.get("summary", ""),"url":url,"source_id":item["source_id"],"origin_domain":item.get("origin_domain") or urllib.parse.urlsplit(url).hostname,"authority":item["source_authority"],"published_at":item.get("published_at"),"first_seen_at":item.get("first_seen_at"),"time_quality":item.get("time_quality"),"categories":tags,"impact":impact_for(headline,tags),"potential_gold_direction":"UNKNOWN","potential_usd_direction":"UNKNOWN","impact_not_prediction":True,"risk_context_only":True}
    return out


def ics_unfold(data):
    lines=re.split(r"\r\n|\n|\r",data)
    folded=[]
    for line in lines:
        if line.startswith((' ', '\t')) and folded:
            folded[-1]+=line[1:]
        else: folded.append(line)
    return folded


def unescape_ics(value):
    return value.replace(r'\n',' ').replace(r'\N',' ').replace(r'\,',',').replace(r'\;',';').replace(r'\\','\\')


def ics_datetime(line):
    field,value=line.split(':',1)
    if "VALUE=DATE" in field.upper() or re.fullmatch(r"\d{8}",value):return None
    zone="America/New_York"
    found=re.search(r"TZID=([^;:]+)",field)
    if found:zone=found.group(1)
    if zone in ("Eastern Standard Time","US/Eastern"):
        zone="America/New_York"
    try:
        if re.fullmatch(r"\d{8}T\d{6}Z",value):
            return dt.datetime.strptime(value,"%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        if re.fullmatch(r"\d{8}T\d{6}",value):
            return dt.datetime.strptime(value,"%Y%m%dT%H%M%S").replace(tzinfo=ZoneInfo(zone)).astimezone(UTC)
        if re.fullmatch(r"\d{8}T\d{4}",value):
            return dt.datetime.strptime(value,"%Y%m%dT%H%M").replace(tzinfo=ZoneInfo(zone)).astimezone(UTC)
    except (ValueError,KeyError):return None
    return None


def calendar_events(payload, source_id, now):
    if len(payload)>1_500_000:raise ValueError("ICS_TOO_LARGE")
    data=payload.decode('utf-8-sig',errors='replace')
    if "BEGIN:VCALENDAR" not in data or "END:VCALENDAR" not in data:
        raise ValueError("NOT_CALENDAR")
    entries=[]; cur=None
    for line in ics_unfold(data):
        if line=="BEGIN:VEVENT":cur={}
        elif line=="END:VEVENT":
            if cur is not None:entries.append(cur)
            cur=None
        elif cur is not None and ':' in line:
            field,value=line.split(':',1)
            base=field.split(';')[0].upper()
            if base in ("UID","SUMMARY","DTSTART","DTSTAMP","STATUS","LAST-MODIFIED"):
                cur[base]=(field,value)
    result=[]; unknown=0
    for e in entries[:1500]:
        title=clean_text(unescape_ics(e.get('SUMMARY',('', ''))[1]))
        line=e.get("DTSTART")
        at=ics_datetime(line[0]+":"+line[1]) if line else None
        if not title or not at:
            unknown+=1;continue
        if e.get("STATUS",('', ''))[1].upper()=="CANCELLED":continue
        if not now-dt.timedelta(days=2)<=at<=now+dt.timedelta(days=90):continue
        label=title.lower()
        impact="HIGH" if any(w in label for w in CALENDAR_HIGH) else "MEDIUM" if any(w in label for w in CALENDAR_MED) else "LOW"
        uid=e.get('UID',('', title+iso(at)))[1]
        result.append({"event_id":new_id("CAL",source_id+":"+uid),"name":title,"impact":impact,"scheduled_at":iso(at),"source_id":source_id,"available_at":iso(now),"event_time_quality":"SCHEDULED_FROM_OFFICIAL_CALENDAR","actual":None,"forecast":None,"risk_context_only":True})
    return result,unknown



def fair_economy_events(payload, source, now):
    """Read the sites' *weekly JSON calendar export*, never HTML or private APIs.

    The timestamp must include an explicit offset. Missing/unparseable times are
    rejected rather than assumed to be ET/UTC. Values are display strings only.
    """
    if len(payload) > 1_500_000:
        raise ValueError("FAIR_ECONOMY_TOO_LARGE")
    rows=json.loads(payload)
    if not isinstance(rows,list):
        raise ValueError("FAIR_ECONOMY_NOT_JSON_ARRAY")
    if len(rows)>2000:
        raise ValueError("FAIR_ECONOMY_EXCESSIVE_EVENTS")
    allowed=set(source.get("country_filter",["USD","CNY","XAU"]))
    alias={"US":"USD","USD":"USD","CH":"CNY","CN":"CNY","CNY":"CNY","XAU":"XAU","GOLD":"XAU"}
    output=[]
    unknown_time=0
    for item in rows:
        if not isinstance(item,dict):
            continue
        title=clean_text(item.get("title", ""))
        raw_country=str(item.get("country") or "").upper().strip()
        currency=alias.get(raw_country,raw_country)
        # For example, Metals Mine reports US while Forex Factory reports USD.
        metals_event=bool(re.search(r"\b(gold|silver|bullion|precious metals|lme|copper inventory)\b",title,re.I))
        if currency not in allowed and not (source.get('include_metals_events',False) and metals_event):
            continue
        scheduled=parse_time(item.get("date"))
        if not scheduled:
            unknown_time+=1
            continue
        if not now-dt.timedelta(days=2) <= scheduled <= now+dt.timedelta(days=16):
            continue
        if not title:
            continue
        impact_text=str(item.get("impact") or "").strip().lower()
        mapping={"high":"HIGH","medium":"MEDIUM","med":"MEDIUM","low":"LOW","holiday":"LOW","non-economic":"LOW"}
        impact=mapping.get(impact_text,"UNKNOWN")
        if impact=="UNKNOWN":
            # Failure-open is unsafe for a blocking economic event calendar.
            impact="HIGH" if any(word in title.lower() for word in CALENDAR_HIGH) else "MEDIUM"
        key="|".join((iso(scheduled),currency,re.sub(r"[^a-z0-9]+"," ",title.casefold()).strip()))
        def value(field):
            raw=item.get(field)
            return clean_text(raw)[:100] if raw is not None and str(raw).strip() else None
        output.append({"event_id":new_id("CAL",source["id"]+":"+key),
             "name":title,"impact":impact,"scheduled_at":iso(scheduled),"source_id":source["id"],
             "source_family":"FAIR_ECONOMY", "calendar_provider":source.get("provider"),
             "calendar_url":source.get("public_calendar_url"),
             "currency":currency,"raw_country":raw_country,
             "available_at":iso(now),"event_time_quality":"THIRD_PARTY_WEEKLY_EXPORT",
             "actual":value("actual"),"forecast":value("forecast"),"previous":value("previous"),
             "not_official_release":True,"no_release_surprise_inferred":True,"risk_context_only":True})
    return output,unknown_time


def merge_calendar_events(events, freshness):
    """One *known* event is not two independent risk votes.

    BLS events have precedence for verified timing; third-party actual/forecast
    remain provider-specific and are never placed into official BLS records.
    Stale provider records are excluded from actionable calendar risk.
    """
    rows=[e for e in events if freshness.get(e.get('source_id'),{}).get('state')=='HEALTHY']
    priority=lambda e: (0 if e['source_id']=='BLS_CALENDAR' else 1 if e['source_id']=='FF_CALENDAR' else 2)
    grouped={}
    for e in sorted(rows,key=priority):
        stamp=parse_time(e.get('scheduled_at'))
        if not stamp:continue
        currency=e.get('currency') or 'USD'  # BLS exclusively reports US releases.
        normalized=re.sub(r'[^a-z0-9]+',' ',str(e.get('name') or '').casefold()).strip()
        # Exact time/title/currency only; similar but different CPI series must not merge.
        key=(stamp.replace(second=0,microsecond=0),currency,normalized)
        if key not in grouped:
            base=dict(e)
            base['event_id']=new_id('CAL_MERGED',iso(key[0])+':'+currency+':'+normalized)
            base['provider_sources']=[e['source_id']]
            base['provider_occurrences']=[{"source_id":e['source_id'],"event_id":e['event_id'],"actual":e.get('actual'),"forecast":e.get('forecast'),"previous":e.get('previous'),"event_time_quality":e.get('event_time_quality')}]
            grouped[key]=base
        else:
            base=grouped[key]
            base['provider_sources'].append(e['source_id'])
            base['provider_occurrences'].append({"source_id":e['source_id'],"event_id":e['event_id'],"actual":e.get('actual'),"forecast":e.get('forecast'),"previous":e.get('previous'),"event_time_quality":e.get('event_time_quality')})
            rank={'LOW':1,'MEDIUM':2,'HIGH':3,'EXTREME':4}
            if rank.get(e['impact'],0)>rank.get(base['impact'],0):base['impact']=e['impact']
            a=parse_time(e.get('available_at')); b=parse_time(base.get('available_at'))
            if a and b and a<b:base['available_at']=iso(a)
    return sorted(grouped.values(),key=lambda e:(e['scheduled_at'],e['name']))

def macro_risk(events, now, before, after):
    active=[]
    for ev in events:
        at=parse_time(ev.get("scheduled_at"))
        if not at:continue
        delta=(at-now).total_seconds()/60
        if -after<=delta<=before and ev.get("impact") in ("HIGH","EXTREME"):
            active.append(ev)
    return {"level":"HIGH" if active else "NONE_DETECTED_IN_PARTIAL_CALENDAR", "events":active,"status":"PARTIAL_COVERAGE","action":"REVIEW_RISK_GATES" if active else "DO_NOT_ASSUME_CALENDAR_COMPLETE"}


def parse_fred(payload, series_id, now):
    doc=json.loads(payload)
    items=doc.get('observations')
    if not isinstance(items,list):raise ValueError("FRED_OBSERVATIONS_INVALID")
    valid=[]
    for item in items:
        if not isinstance(item,dict):continue
        try:
            value=float(item['value'])
            if not (-1_000_000_000<value<1_000_000_000):continue
            date=dt.date.fromisoformat(item['date'])
            if date>now.date():continue
        except (ValueError,KeyError,TypeError):continue
        valid.append((date,value))
    valid.sort(reverse=True)
    if not valid:return None
    date,value=valid[0]
    prev=valid[1][1] if len(valid)>1 else None
    return {"series_id":series_id,"observation_date":date.isoformat(),"value":value,"previous_observation_value":prev,"difference_from_previous_observation":round(value-prev,7) if prev is not None else None,"retrieved_at":iso(now),"first_available_to_this_collector_at":iso(now),"status":"LAGGED_OBSERVATION","not_intraday_price":True,"not_release_surprise":True}


class Store:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(str(self.path));self.db.row_factory=sqlite3.Row
        self.db.execute("CREATE TABLE IF NOT EXISTS articles (event_id TEXT PRIMARY KEY, data TEXT NOT NULL, first_saved_at TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS feed_status (source_id TEXT PRIMARY KEY, last_success TEXT, last_error TEXT, last_checked TEXT, error_count INTEGER NOT NULL DEFAULT 0)")
        self.db.execute("CREATE TABLE IF NOT EXISTS calendar (event_id TEXT PRIMARY KEY, data TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS observations (series_id TEXT PRIMARY KEY, data TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS poll_meta (source_id TEXT PRIMARY KEY,last_poll TEXT NOT NULL)")
        self.db.commit()
    def mark(self,source_id,now,error=None):
        prev=self.db.execute("SELECT error_count,last_success FROM feed_status WHERE source_id=?",(source_id,)).fetchone()
        count=(prev['error_count'] if prev else 0)+1 if error else 0
        self.db.execute("INSERT INTO feed_status VALUES (?,?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET last_success=excluded.last_success,last_error=excluded.last_error,last_checked=excluded.last_checked,error_count=excluded.error_count",(source_id,prev['last_success'] if prev and error else iso(now),str(error)[:180] if error else None,iso(now),count))
        self.db.execute("INSERT OR REPLACE INTO poll_meta(source_id,last_poll) VALUES(?,?)",(source_id,iso(now)))
        self.db.commit()
    def due(self,source_id,now,seconds):
        rec=self.db.execute("SELECT last_poll FROM poll_meta WHERE source_id=?",(source_id,)).fetchone()
        last=parse_time(rec[0]) if rec else None
        state=self.db.execute("SELECT error_count FROM feed_status WHERE source_id=?",(source_id,)).fetchone()
        errors=state[0] if state else 0
        cooldown=seconds*min(8,2**min(errors,3)) if errors else seconds
        return last is None or (now-last).total_seconds()>=cooldown
    def article(self,record,now):
        existed=self.db.execute("SELECT 1 FROM articles WHERE event_id=?",(record['event_id'],)).fetchone()
        if existed:return False
        self.db.execute("INSERT INTO articles VALUES(?,?,?)",(record['event_id'],json.dumps(record,ensure_ascii=False),iso(now)))
        self.db.commit();return True
    def save_calendar(self,events,now,source_id):
        # Replace this source, preserving the earliest first-known time.
        previous={r["event_id"]:json.loads(r["data"]) for r in self.db.execute("SELECT event_id,data FROM calendar")}
        self.db.execute("DELETE FROM calendar WHERE json_extract(data,'$.source_id')=?",(source_id,))
        for ev in events:
            old=previous.get(ev["event_id"])
            if old and old.get("available_at"):
                ev["available_at"]=old["available_at"]
            self.db.execute("INSERT OR REPLACE INTO calendar VALUES(?,?)",(ev["event_id"],json.dumps(ev,ensure_ascii=False)))
        self.db.commit()
    def save_observation(self,record):
        self.db.execute("INSERT OR REPLACE INTO observations VALUES (?,?)",(record['series_id'],json.dumps(record)))
        self.db.commit()
    def recent(self,now,hours,limit):
        rows=self.db.execute("SELECT data FROM articles ORDER BY first_saved_at DESC LIMIT 1000").fetchall()
        out=[]
        for row in rows:
            record=json.loads(row[0]);stamp=parse_time(record.get('published_at')) or parse_time(record.get('first_seen_at'))
            if stamp and dt.timedelta(0)<=now-stamp<=dt.timedelta(hours=hours):out.append(record)
        out.sort(key=lambda x:x['published_at'] or x['first_seen_at'],reverse=True)
        return out[:limit]
    def events(self):return [json.loads(r[0]) for r in self.db.execute("SELECT data FROM calendar")]
    def observations(self):return [json.loads(r[0]) for r in self.db.execute("SELECT data FROM observations")]
    def status(self):return [dict(r) for r in self.db.execute("SELECT * FROM feed_status ORDER BY source_id")]
    def close(self):self.db.close()


def gdelt_url(query):
    return "https://api.gdeltproject.org/api/v2/doc/doc?"+urllib.parse.urlencode({"query":query,"mode":"artlist","format":"json","maxrecords":30,"timespan":"1d"})


def fred_url(series_id,api_key):
    return "https://api.stlouisfed.org/fred/series/observations?"+urllib.parse.urlencode({"series_id":series_id,"api_key":api_key,"file_type":"json","sort_order":"desc","limit":8})


def write_json_atomic(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+".tmp")
    with tmp.open('w',encoding='utf-8') as fp:
        json.dump(obj,fp,indent=2,ensure_ascii=False,allow_nan=False)
        fp.flush();os.fsync(fp.fileno())
    os.replace(tmp,path)


def configured_sources(cfg):
    return [str(f['id']) for f in cfg['rss_feeds']]+(['BLS_CALENDAR'] if cfg.get('bls_calendar_ics') else [])+[f["id"] for f in cfg.get("fair_economy_calendars",[]) if f.get("enabled")]+([f["id"] for f in cfg['gdelt_queries']] if cfg.get('gdelt_enabled') else [])+(["FRED_"+s for s in cfg['fred_series']] if cfg.get('fred_enabled') and os.environ.get('FRED_API_KEY') else [])


def collect(cfg,store,client=None,now=None,force=False):
    now=now or utc_now(); client=client or HTTPClient(cfg['allowed_hosts']); maxage=cfg['item_max_age_hours']
    touched=[]; new=[]; problems=[]; skipped=[]
    initial_backfill=store.db.execute("SELECT 1 FROM poll_meta WHERE source_id='__NEWS_BOOTSTRAPPED__'").fetchone() is None
    def fetch(source_id,url,interval,handler):
        if not force and not store.due(source_id,now,interval):return
        try:
            payload=client.get(url)
            handler(payload)
            store.mark(source_id,now)
            touched.append(source_id)
        except (ValueError,TypeError,KeyError,ET.ParseError,UnicodeError,urllib.error.URLError,TimeoutError, OSError) as exc:
            store.mark(source_id,now,type(exc).__name__+':'+str(exc))
            problems.append({"source_id":source_id,"error":type(exc).__name__+':'+str(exc)[:135]})
    def persist(items):
        for item in items:
            rec=normalize_story(item,now,maxage)
            if rec and store.article(rec,now):new.append(rec)
    for source in cfg['rss_feeds']:
        fetch(source['id'],source['url'],cfg.get('rss_interval_seconds',300),lambda data,s=source:persist(rss_items(data,s,now)))
    if cfg.get('bls_calendar_ics'):
        def handle_calendar(payload):
            items,unknown=calendar_events(payload,'BLS_CALENDAR',now)
            store.save_calendar(items,now,'BLS_CALENDAR')
            if unknown>0:
                # Unknown time events are intentionally not converted to a guessed hour.
                pass
        fetch('BLS_CALENDAR',cfg['bls_calendar_ics'],cfg.get('calendar_interval_seconds',900),handle_calendar)
    for source in cfg.get("fair_economy_calendars",[]):
        if not source.get("enabled"):
            continue
        def handle_fair(payload,s=source):
            items,unknown=fair_economy_events(payload,s,now)
            store.save_calendar(items,now,s["id"])
        fetch(source["id"],source["url"],max(900,int(cfg.get("fair_economy_interval_seconds",1800))),handle_fair)
    if cfg.get('gdelt_enabled'):
        for q in cfg['gdelt_queries']:
            fetch(q['id'],gdelt_url(q['query']),cfg.get('gdelt_interval_seconds',600),lambda data,s=q:persist(gdelt_items(data,s,now)))
    if cfg.get('fred_enabled'):
        key=os.environ.get('FRED_API_KEY')
        if key:
            for series_id in cfg['fred_series']:
                def parse_fred_and_save(payload,s=series_id):
                    rec=parse_fred(payload,s,now)
                    if rec is None:raise ValueError("FRED_NO_OBSERVATIONS")
                    store.save_observation(rec)
                fetch('FRED_'+series_id,fred_url(series_id,key),cfg.get('fred_interval_seconds',3600),parse_fred_and_save)
        else:skipped.append({"source_id":"FRED","reason":"OPTIONAL_FRED_API_KEY_NOT_SET"})
    # An initial successful news-source poll is the baseline, even if it has zero articles.
    news_ids={f["id"] for f in cfg["rss_feeds"]} | ({q["id"] for q in cfg["gdelt_queries"]} if cfg.get("gdelt_enabled") else set())
    if any(name in news_ids for name in touched):
        store.db.execute("INSERT OR REPLACE INTO poll_meta(source_id,last_poll) VALUES (?,?)",("__NEWS_BOOTSTRAPPED__",iso(now)))
        store.db.commit()
    full_list=configured_sources(cfg)
    states={row['source_id']:row for row in store.status()}
    freshness={}
    for name in full_list:
        row=states.get(name)
        interval=(cfg.get("fred_interval_seconds",3600) if name.startswith("FRED_") else
                  max(900,int(cfg.get("fair_economy_interval_seconds",1800))) if name in {f["id"] for f in cfg.get("fair_economy_calendars",[]) if f.get("enabled")} else
                  cfg.get("calendar_interval_seconds",900) if name=="BLS_CALENDAR" else
                  cfg.get("gdelt_interval_seconds",600) if any(name==q["id"] for q in cfg.get("gdelt_queries",[])) else
                  cfg.get("rss_interval_seconds",300))
        fresh=bool(row and row['last_success'] and (now-parse_time(row['last_success'])).total_seconds() <= max(2*interval,600) and row['last_error'] is None)
        freshness[name]={"state":"HEALTHY" if fresh else "UNAVAILABLE_OR_STALE","last_success":row['last_success'] if row else None,"last_error":row['last_error'] if row else None}
    calendar_status=freshness.get('BLS_CALENDAR',{}).get('state','UNAVAILABLE_OR_STALE')
    raw_events=store.events();events=merge_calendar_events(raw_events,freshness);recent=store.recent(now,maxage,cfg['max_recent_items'])
    macro_series=[]
    for rec in store.observations():
        st=freshness.get("FRED_"+rec["series_id"],{}).get("state")
        macro_series.append({**rec,"collection_status":"FETCH_FRESH" if st=="HEALTHY" else "FETCH_STALE_OR_UNKNOWN"})
    risk=macro_risk(events,now,cfg['calendar_pre_minutes'],cfg['calendar_post_minutes'])
    alert_new=[] if initial_backfill else new
    # Only a VERIFIED publication timestamp near this collector cycle may be urgent.
    # Rediscovered older articles are news, not breaking news.
    urgent=[x for x in alert_new if x['impact'] in ('HIGH','EXTREME') and x["time_quality"]=="PUBLISHED"
            and x.get("published_at") and 0 <= (now-parse_time(x["published_at"])).total_seconds() <= 1800]
    urgent_unverified=[x for x in alert_new if x['impact'] in ('HIGH','EXTREME') and x["time_quality"]!="PUBLISHED"]
    sources_bad=[name for name,val in freshness.items() if val['state']!='HEALTHY']
    out={
        "module_id":"M04N","module_version":VERSION,"schema_version":cfg.get('schema_version','2.0.0'),"prompt_version":cfg.get('prompt_version','4.1.0'),
        "as_of":iso(now),"feed_scope":"PUBLIC_INFORMATION_ONLY","market_data_source_policy":"MT5_PRIMARY_INFORMATION_SUPPLEMENTAL","visual_capture_enabled":False,
        "status":"HEALTHY" if not sources_bad else "PARTIAL" if len(sources_bad)<len(full_list) else "UNAVAILABLE",
        "integrity":{"expected_sources":full_list,"source_health":freshness,"failed_or_stale_sources":sources_bad,"errors_this_poll":problems,"sources_updated_this_poll":touched,"optional_skipped":skipped,"complete_global_news_coverage":False,"calendar_completeness":"MULTISOURCE_PARTIAL_NEVER_GLOBAL_COMPLETE","fair_economy_is_single_source_family":True, "report_is_live_feed_check":True},
        "source_directory":{"forexfactory":{"calendar":"https://www.forexfactory.com/calendar","news":"https://www.forexfactory.com/news","calendar_auto_import":True,"news_page_auto_import":False},"metalsmine":{"calendar":"https://www.metalsmine.com/calendar","news":"https://www.metalsmine.com/news","calendar_auto_import":True,"news_page_auto_import":False}},
        "news":{"new_count_this_poll":len(alert_new),"initial_backfill_count":len(new) if initial_backfill else 0,"initial_backfill_suppresses_new_alerts":initial_backfill,"new_high_impact_count":len(urgent),"new_unverified_high_impact_count":len(urgent_unverified),"new_events":alert_new[:40],"recent":recent},
        "calendar":{"source":"MULTISOURCE_PARTIAL","status":"PARTIAL" if events else "PARTIAL_NO_EVENTS" if any(freshness.get(k,{}).get("state")=="HEALTHY" for k in ("BLS_CALENDAR","FF_CALENDAR","MM_CALENDAR")) else "UNAVAILABLE","events":events[:150],"risk":risk,"coverage":"BLS_PLUS_FF_MM_WEEKLY_SUBSET_NEVER_COMPLETE", "individual_source_counts":{name:sum(1 for e in raw_events if e.get('source_id')==name) for name in ['BLS_CALENDAR','FF_CALENDAR','MM_CALENDAR']},"source_urls":{"FF_CALENDAR":"https://www.forexfactory.com/calendar","MM_CALENDAR":"https://www.metalsmine.com/calendar"}},
        "macro_observations":{"source":"FRED_OPTIONAL","series":macro_series,"no_intraday_release_timing":True},
        "interpretation":{"detected_topics":sorted({c for n in recent for c in n['categories']}),"gold_direction":"UNKNOWN","usd_direction":"UNKNOWN","no_inferred_trade_signal":True,
                          "risk_advisory":"ELEVATED" if urgent or risk['level']=='HIGH' else "CHECK_UNVERIFIED_HEADLINES" if urgent_unverified else "SOURCE_COVERAGE_INCOMPLETE" if sources_bad or calendar_status!='HEALTHY' else "PARTIAL_ECONOMIC_CALENDAR_COVERAGE", "no_trade_permission_granted":True},
        "execution_permission":"BLOCKED","research_only":True,
        "limitations":["News is not guaranteed exhaustive or instantaneous; aggregation may lag publication.","Headlines and calendars are context, not entry confirmations.","FRED values are low frequency historical observations; no forecast or actual release-surprise data are inferred.","BLS/Forex Factory/Metals Mine calendar coverage is insufficient to assert an absence of FOMC/BEA/geopolitical risk.","Forex Factory and Metals Mine are correlated Fair Economy sources; not independent corroboration; exports can be unavailable or revised.","Third-party actual/forecast strings are unverified; no numerical surprise or trading signal inferred.","Weekly calendars exclude dates outside this-week export; historical backfills are not contemporaneous observations."]
    }
    # Do NOT mark entire M04 calendar VERIFIED from BLS calendar (partial by design).
    bridge={"module_id":"M04N","module_version":VERSION,"as_of":iso(now),"source_status":out['status'],"context_inputs":{
        "macro_events":[{k:v for k,v in ev.items() if k in ('event_id','name','impact','scheduled_at','source_id','available_at','actual','forecast','previous','provider_sources','provider_occurrences','event_time_quality')} for ev in events],
        "calendar_coverage":{"status":"PARTIAL" if calendar_status=='HEALTHY' else "UNAVAILABLE","source_id":"BLS_CALENDAR" if calendar_status=='HEALTHY' else None,"verified_at":states.get('BLS_CALENDAR',{}).get('last_success') if calendar_status=='HEALTHY' else None,"data_complete":False,"window_from":None,"window_to":None,"scope":"BLS_OFFICIAL_AND_FAIR_ECONOMY_WEEKLY_PARTIAL"},
        "macro_news_context":{"as_of":iso(now),"fresh_items":recent[:30],"source_health":freshness,"news_coverage_complete":False},
        "fred_observations":macro_series},
        "advisory":{"risk":out['interpretation']['risk_advisory'],"execution_permission":"BLOCKED","does_not_override_m04_m11_m14":True}}
    return out,bridge


def main(argv=None):
    base=Path(__file__).resolve().parent
    parser=argparse.ArgumentParser(description='MasterQUO M04N — read-only macro/news intelligence')
    parser.add_argument('--config',default=str(base/'M04N_CONFIG.json'))
    parser.add_argument('--runtime',default=str(base/'runtime'))
    parser.add_argument('--once',action='store_true')
    parser.add_argument('--interval',type=int,default=None)
    parser.add_argument('--force',action='store_true',help='ignore per-source polling intervals (one-shot diagnosis)')
    opts=parser.parse_args(argv)
    cfg=json.loads(Path(opts.config).read_text(encoding='utf-8'))
    for source in cfg['rss_feeds']:validate_https(source['url'],cfg['allowed_hosts'])
    if cfg.get('bls_calendar_ics'):validate_https(cfg['bls_calendar_ics'],cfg['allowed_hosts'])
    for source in cfg.get('fair_economy_calendars',[]):
        if source.get('enabled'):validate_https(source['url'],cfg['allowed_hosts'])
    if opts.interval is not None and opts.interval<60:parser.error('--interval minimum 60 seconds')
    runtime=Path(opts.runtime);runtime.mkdir(parents=True,exist_ok=True)
    store=Store(runtime/'M04N_STATE.sqlite')
    try:
        while True:
            report,bridge=collect(cfg,store,force=opts.force)
            write_json_atomic(runtime/'M04N_INTELLIGENCE.json',report)
            write_json_atomic(runtime/'M04N_M04_CONTEXT_BRIDGE.json',bridge)
            print(f"{report['as_of']} M04N {report['status']} new={report['news']['new_count_this_poll']} risk={report['interpretation']['risk_advisory']} sources_unavailable={len(report['integrity']['failed_or_stale_sources'])}",flush=True)
            if opts.once:break
            time.sleep(opts.interval or cfg.get('poll_seconds',300))
    except KeyboardInterrupt:print('M04N stopped by user.')
    finally:store.close()
    return 0

if __name__=='__main__':raise SystemExit(main())
