#!/usr/bin/env python3
"""MasterQUO M04 v1.0.0 reference analytical context processor, read-only.

All algorithmic thresholds in supplied profile are illustrative, NOT empirically optimized.
No terminal connector, no market data, no order management, no screenshot capability.
Run: python M04_REFERENCE_ENGINE.py --input M04_SYNTHETIC_INPUT.json --profile M04_PROFILE.example.json
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import math
import statistics
from collections import defaultdict
from zoneinfo import ZoneInfo

VERSION = "1.0.0-CANDIDATE"
POLICY = "MT5_PRIMARY_TV_SUPPLEMENTAL_NO_SCREENSHOTS"
TF_MINUTES = {"M1":1,"M5":5,"M15":15,"H1":60,"H4":240,"D1":1440}

class DataError(ValueError):
    pass

def clock(v):
    if not isinstance(v,str):
        raise DataError("TIMESTAMP_MISSING")
    try:
        x=dt.datetime.fromisoformat(v.replace("Z","+00:00"))
    except ValueError as exc:
        raise DataError("TIMESTAMP_INVALID") from exc
    if x.tzinfo is None or x.utcoffset() is None:
        raise DataError("TIMEZONE_MISSING")
    return x.astimezone(dt.timezone.utc)

def iso(x):
    return x.astimezone(dt.timezone.utc).isoformat().replace("+00:00","Z")

def validate_bar(b,asof,tf):
    if b.get("instrument_id") != "XAUUSD":
        return "INSTRUMENT_MISMATCH"
    if b.get("timeframe") != tf:
        return "TIMEFRAME_MISMATCH"
    if b.get("bar_state") != "CLOSED":
        return "BAR_NOT_CLOSED"
    if not str(b.get("source_id","")).upper().startswith("MT5"):
        return "NON_MT5_EXECUTION_BAR"
    if not b.get("evidence_id"):
        return "EVIDENCE_ID_MISSING"
    if not b.get("price_basis"):
        return "PRICE_BASIS_MISSING"
    try:
        opened=clock(b.get("bar_open_utc"))
        available=clock(b.get("available_at"))
        confirmed=clock(b.get("close_confirmed_at"))
    except DataError as exc:
        return str(exc)
    if opened > asof or available > asof or confirmed > asof:
        return "FUTURE_BAR_EVIDENCE"
    if confirmed < opened or available < opened:
        return "BAR_CHRONOLOGY_ERROR"
    try:
        o,h,l,c=(float(b[x]) for x in ("open","high","low","close"))
    except (ValueError,TypeError,KeyError):
        return "OHLC_MISSING"
    if not all(math.isfinite(x) and x>0 for x in (o,h,l,c)) or not l<=min(o,c)<=max(o,c)<=h:
        return "OHLC_INVALID"
    return None

def select_bars(snapshot,asof,tf):
    raw=snapshot.get("candles_by_tf",{}).get(tf,[])
    seen={}; failures=[]; rejected_counts=defaultdict(int)
    for b in raw:
        reason=validate_bar(b,asof,tf)
        if reason:
            rejected_counts[reason]+=1
            if reason not in ("BAR_NOT_CLOSED","FUTURE_BAR_EVIDENCE"):
                failures.append(reason)
            continue
        key=(b["bar_open_utc"], b["source_id"], b["price_basis"])
        prev=seen.get(key)
        # Conflicting duplicates cannot be silently resolved.
        if prev and any(prev[k]!=b[k] for k in ("open","high","low","close")):
            failures.append("DUPLICATE_CONFLICT")
            continue
        seen[key]=b
    rows=sorted(seen.values(),key=lambda b:clock(b["bar_open_utc"]))
    if len({(b["source_id"],b["price_basis"]) for b in rows})>1:
        failures.append("MIXED_BROKER_PRICE_BASIS")
    return rows,sorted(set(failures)),dict(rejected_counts)

def session_metrics(bars,asof,profiles):
    out={}
    for name,spec in profiles.items():
        try:
            tz=ZoneInfo(spec["timezone"])
            start_h,start_m=(int(v) for v in spec["start"].split(":"))
            end_h,end_m=(int(v) for v in spec["end"].split(":"))
            start_t=dt.time(start_h,start_m)
            end_t=dt.time(end_h,end_m)
        except (KeyError,ValueError) as exc:
            raise DataError("SESSION_CONFIG_INVALID") from exc
        local=asof.astimezone(tz)
        session_date=local.date()
        # Session label = date of local session opening, including midnight crossing.
        if start_t>=end_t and local.timetz().replace(tzinfo=None)<end_t:
            session_date-=dt.timedelta(days=1)
        start_dt=dt.datetime.combine(session_date,start_t,tzinfo=tz).astimezone(dt.timezone.utc)
        end_date=session_date+dt.timedelta(days=(1 if start_t>=end_t else 0))
        end_dt=dt.datetime.combine(end_date,end_t,tzinfo=tz).astimezone(dt.timezone.utc)
        if end_dt<=start_dt:
            raise DataError("SESSION_WINDOW_INVALID")
        # Never report a future full-session high; only data as-of are considered.
        chosen=[b for b in bars if start_dt<=clock(b["bar_open_utc"])<end_dt and clock(b["available_at"])<=asof]
        active=start_dt<=asof<end_dt
        done=asof>=end_dt
        observed_start = min(end_dt,asof)
        nominal_expected = max(0,int((observed_start-start_dt).total_seconds()//300)) if asof>=start_dt else 0
        completeness = "NONE" if not chosen else "CLOSED_BARS_ONLY_COMPLETE_NOMINAL" if len(chosen)==nominal_expected and nominal_expected>0 else "PARTIAL_NOMINAL"
        out[name]={"timezone":spec["timezone"],"local_open_date":session_date.isoformat(),
                   "start_utc":iso(start_dt),"end_utc":iso(end_dt),
                   "status":"ACTIVE_PARTIAL" if active else "ENDED" if done else "NOT_STARTED",
                   "bars_observed":len(chosen),"nominal_expected_m5_bars":nominal_expected,
                   "range_completeness":completeness,"high":max((b["high"] for b in chosen),default=None),
                   "low":min((b["low"] for b in chosen),default=None),
                   "high_low_basis":"CLOSED_MT5_BARS_ONLY","evidence_ids":[b["evidence_id"] for b in chosen]}
    return out

def tick_volume_context(bars,history_count):
    if len(bars)<history_count+1:
        return {"status":"PENDING","reason":"NOT_ENOUGH_COMPLETED_BARS","rvol":None,"volume_kind":"TICK_COUNT"}
    sample=bars[-history_count-1:-1]
    vols=[]
    for b in sample:
        v=b.get("tick_volume")
        if not isinstance(v,(int,float)) or v<0 or not math.isfinite(v):
            return {"status":"UNAVAILABLE","reason":"TICK_VOLUME_INCOMPLETE","rvol":None,"volume_kind":"TICK_COUNT"}
        vols.append(float(v))
    cur=bars[-1].get("tick_volume")
    if not isinstance(cur,(int,float)) or cur<0 or not math.isfinite(cur):
        return {"status":"UNAVAILABLE","reason":"CURRENT_TICK_VOLUME_UNAVAILABLE","rvol":None,"volume_kind":"TICK_COUNT"}
    avg=statistics.mean(vols)
    if avg<=0:
        return {"status":"PENDING","reason":"ZERO_BASELINE","rvol":None,"volume_kind":"TICK_COUNT"}
    return {"status":"PASS","rvol":float(cur)/avg,"lookback":history_count,"volume_kind":"TICK_COUNT",
            "actual_delta":None,"cvd":None,"true_order_flow_status":"UNAVAILABLE","reason":None}

def pearson(a,b):
    if len(a)<2 or len(a)!=len(b):
        return None
    ax=statistics.mean(a); bx=statistics.mean(b)
    denom=math.sqrt(sum((x-ax)**2 for x in a)*sum((y-bx)**2 for y in b))
    if denom==0:
        return None
    return sum((x-ax)*(y-bx) for x,y in zip(a,b))/denom

def context_usd(context,asof,profile):
    data=context.get("usd_pairs",{})
    gold=data.get("XAUUSD")
    usd=data.get("DXY")
    if not gold or not usd:
        return {"status":"UNAVAILABLE","correlation":None,"regime":"UNKNOWN","reason":"PAIR_DATA_UNAVAILABLE"}
    def read_series(series,expected):
        points={}
        for p in series:
            if p.get("instrument_id")!=expected or p.get("timeframe")!=profile["correlation_timeframe"]:
                raise DataError("CORRELATION_SERIES_MISMATCH")
            av=clock(p.get("available_at"));stamp=clock(p.get("bar_open_utc"))
            if av>asof or stamp>asof:
                continue
            if not p.get("source_id") or not p.get("evidence_id"):
                raise DataError("CORRELATION_PROVENANCE_MISSING")
            v=p.get("close")
            if not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0:
                raise DataError("CORRELATION_PRICE_INVALID")
            if stamp in points and points[stamp]!=v:
                raise DataError("CORRELATION_DUPLICATE_CONFLICT")
            points[stamp]=float(v)
        return points
    try:
        gp=read_series(gold,"XAUUSD"); dp=read_series(usd,"DXY")
    except DataError as exc:
        return {"status":"PENDING","correlation":None,"regime":"UNKNOWN","reason":str(exc)}
    # Aligned timestamp returns require consecutive observations for BOTH instruments.
    shared=sorted(set(gp)&set(dp))
    step=dt.timedelta(minutes=TF_MINUTES[profile["correlation_timeframe"]])
    x=[];y=[]
    for prev,curr in zip(shared,shared[1:]):
        if curr-prev!=step:
            continue
        x.append(math.log(gp[curr]/gp[prev]));y.append(math.log(dp[curr]/dp[prev]))
    required=profile["minimum_correlation_returns"]
    if len(x)<required:
        return {"status":"PENDING","correlation":None,"regime":"UNKNOWN","sample_returns":len(x),"reason":"INSUFFICIENT_ALIGNED_RETURNS"}
    r=pearson(x,y)
    if r is None:
        return {"status":"PENDING","correlation":None,"regime":"UNKNOWN","sample_returns":len(x),"reason":"ZERO_VARIANCE"}
    if r<=-0.70: reg="STRONG_INVERSE"
    elif r<=-0.40: reg="MODERATE_INVERSE"
    elif r<=-0.20: reg="WEAK_INVERSE"
    elif r>=0.60: reg="TEMPORARY_DECOUPLING"
    else: reg="NEUTRAL"
    return {"status":"PASS_WITH_LIMITATIONS","correlation":round(r,6),"regime":reg,
            "sample_returns":len(x),"timeframe":profile["correlation_timeframe"],
            "reason":"HEURISTIC_BANDS_NOT_OOS_CALIBRATED", "signal_direction":None}

def calendar_context(events,asof,profile,coverage=None):
    coverage = coverage or {}
    audited=False
    try:
        if coverage.get("status")=="VERIFIED" and coverage.get("source_id") and coverage.get("data_complete") is True:
            checked=clock(coverage.get("verified_at"))
            begin=clock(coverage.get("window_from"))
            end=clock(coverage.get("window_to"))
            audited=checked<=asof and begin<=asof<=end and checked>=begin
    except DataError:
        audited=False
    if events is None:
        return {"status":"UNAVAILABLE","event_risk":"UNKNOWN","event_gate":"PENDING","reason":"CALENDAR_UNAVAILABLE","upcoming":[],"released":[]}
    selected=[];released=[];invalid=[]
    for ev in events:
        if not ev.get("event_id") or not ev.get("source_id"):
            invalid.append("EVENT_PROVENANCE_MISSING");continue
        try:
            at=clock(ev.get("scheduled_at"))
            known=clock(ev.get("available_at"))
        except DataError:
            invalid.append("EVENT_TIMESTAMP_INVALID");continue
        if known>asof:
            continue
        impact=ev.get("impact")
        if impact not in {"LOW","MEDIUM","HIGH","EXTREME"}:
            invalid.append("EVENT_IMPACT_UNKNOWN");continue
        e={"event_id":ev["event_id"],"name":ev.get("name"),"impact":impact,"scheduled_at":iso(at),"source_id":ev["source_id"]}
        delta=(at-asof).total_seconds()/60
        window=profile["event_windows_minutes"].get(impact,{"pre":0,"post":0})
        if -window["post"]<=delta<=window["pre"]:
            selected.append(e)
        # Economic surprise never use actual before release+available_at.
        if ev.get("actual") is not None and ev.get("forecast") is not None:
            released_at=ev.get("released_at")
            try:
                release=clock(released_at)
            except DataError:
                release=None
            value_available=None
            try:
                value_available=clock(ev.get("actual_available_at"))
            except DataError:
                pass
            if release is not None and value_available is not None and release<=asof and value_available<=asof and at<=asof:
                try:
                    a=float(ev["actual"]); f=float(ev["forecast"])
                    if math.isfinite(a) and math.isfinite(f) and ev.get("unit"):
                        released.append({**e,"surprise":a-f,"unit":ev["unit"],"actual":a,"forecast":f})
                except (ValueError,TypeError):
                    pass
    risk="LOW"
    if any(e["impact"]=="EXTREME" for e in selected):risk="EXTREME"
    elif any(e["impact"]=="HIGH" for e in selected):risk="HIGH"
    elif any(e["impact"]=="MEDIUM" for e in selected):risk="MEDIUM"
    # An empty event list is meaningful ONLY for an explicitly complete, audited calendar window.
    if invalid and not selected:
        return {"status":"PENDING","event_risk":"UNKNOWN","event_gate":"PENDING","reason":"CALENDAR_ITEMS_INVALID","upcoming":[],"released":released}
    if not audited and not selected:
        return {"status":"PENDING","event_risk":"UNKNOWN","event_gate":"PENDING","reason":"CALENDAR_COVERAGE_UNVERIFIED","upcoming":[],"released":released}
    event_gate="BLOCKED" if risk in {"HIGH","EXTREME"} else "PENDING" if not audited or invalid else "PASS"
    return {"status":"PASS" if audited else "PASS_WITH_LIMITATIONS","event_risk":risk,"event_gate":event_gate,"reason":None,
            "upcoming":selected,"released":released,"calendar_coverage_verified":audited}

def trap_context(bars,evidence,asof,profile):
    breaks=[]
    for tf,tf_obj in (evidence.get("timeframes") or {}).items():
        if tf!="M5":continue
        breaks.extend(tf_obj.get("breaks") or [])
    confirmed=[];candidate=[]
    for e in breaks:
        try: t=clock(e.get("available_at"))
        except DataError:continue
        if t>asof:continue
        direction=e.get("direction")
        level=e.get("level")
        if direction not in {"BULLISH","BEARISH"} or not isinstance(level,(int,float)) or not e.get("evidence_id"):
            continue
        subsequent=[b for b in bars if clock(b["available_at"])>t]
        subsequent=subsequent[:profile["trap_reclaim_bars"]]
        if not subsequent:
            candidate.append({"source_break_id":e["evidence_id"],"status":"AWAITING_REACTION"});continue
        reclaimed=any((b["close"]<level if direction=="BULLISH" else b["close"]>level) for b in subsequent)
        if reclaimed:
            confirmed.append({"source_break_id":e["evidence_id"],"classification":"FAILED_BREAKOUT_RECLAIM",
                              "direction":direction,"observed_bars":len(subsequent),"level":level})
        elif len(subsequent)<profile["trap_reclaim_bars"]:
            candidate.append({"source_break_id":e["evidence_id"],"status":"PENDING_WINDOW"})
    risk="HIGH" if confirmed else "MEDIUM" if candidate else "LOW" if breaks else "UNKNOWN"
    return {"trap_risk":risk,"confirmed_traps":confirmed,"candidates":candidate,"trap_score":None,
            "reason":"CONFIRMED_RECLAIM" if confirmed else "NO_VALID_BREAK_EVIDENCE" if not breaks else None,
            "probability_adjustment":None,"trade_signal":None}

def analyze(root,profile):
    snap=root.get("data_snapshot",{})
    market=root.get("market_state",{})
    evidence=root.get("market_evidence",{})
    as_of=snap.get("as_of")
    if not as_of:
        raise DataError("AS_OF_MISSING")
    at=clock(as_of)
    reasons=[]
    if snap.get("data_source_policy")!=POLICY or snap.get("visual_capture_enabled") is not False:
        reasons.append("M01_SOURCE_POLICY_MISMATCH")
    if not snap.get("snapshot_id") or snap.get("snapshot_id")!=market.get("snapshot_id") or (evidence and evidence.get("snapshot_id")!=snap.get("snapshot_id")):
        reasons.append("SNAPSHOT_ID_CONFLICT")
    for upstream in (market,evidence):
        if upstream and upstream.get("as_of") and clock(upstream["as_of"])!=at:
            reasons.append("AS_OF_CONFLICT")
    ag=market.get("analysis_gate",{}).get("status")
    if ag not in {"PASS","PASS_WITH_LIMITATIONS"}:
        reasons.append("UPSTREAM_ANALYSIS_UNAVAILABLE")
    bars,errs,rejects=select_bars(snap,at,"M5")
    reasons.extend(errs)
    if not bars:
        reasons.append("NO_VALID_CLOSED_M5_BARS")
    sessions=session_metrics(bars,at,profile["sessions"])
    flow=tick_volume_context(bars,profile["rvol_lookback"])
    usd=context_usd(root.get("context_inputs",{}),at,profile)
    inputs=root.get("context_inputs",{})
    news=calendar_context(inputs.get("macro_events"),at,profile,inputs.get("calendar_coverage"))
    traps=trap_context(bars,evidence,at,profile)
    upstream_exec=market.get("execution_context_gate",{}).get("status")
    runtime=root.get("runtime_health",{}).get("status")
    can_analyze=not reasons
    # M04 never authorizes execution. If required calendar is unknown, context gate remains PENDING.
    execution_context="PENDING" if can_analyze else "BLOCKED"
    if can_analyze and upstream_exec=="PASS" and runtime=="HEALTHY" and news["event_gate"]=="PASS":
        execution_context="PASS"
    if news["event_gate"]=="BLOCKED":execution_context="BLOCKED"
    if runtime in {"OFFLINE","DEGRADED","STOPPED","ERROR"}:execution_context="BLOCKED"
    result={"module_id":"M04","module_version":VERSION,"run_status":"COMPLETED",
            "snapshot_id":snap.get("snapshot_id"),"analysis_id":snap.get("analysis_id"),"as_of":iso(at),
            "status":"PASS_WITH_LIMITATIONS" if can_analyze else "PENDING",
            "context":{"sessions":sessions,"volume":flow,"usd_gold":usd,"economic_calendar":news,"traps":traps},
            "analysis_gate":{"status":"PASS_WITH_LIMITATIONS" if can_analyze else "PENDING","reason_codes":sorted(set(reasons))},
            "execution_context_gate":{"status":execution_context,"note":"CONTEXT_ONLY_NOT_EXECUTION_PERMISSION"},
            "execution_permission":"BLOCKED", "market_data_source_policy":POLICY,
            "visual_capture_enabled":False,"rejected_bars":rejects,"reason_codes":sorted(set(reasons)),
            "missing_inputs":[k for k,v in (("USD_ALIGNED_SERIES",usd["status"]),("CALENDAR",news["status"]),("TICK_VOLUME",flow["status"])) if v in {"UNAVAILABLE","PENDING"}],
            "limitations":["NO_ORDER_FLOW_WITHOUT_TRADES_OR_ORDER_BOOK","NO_M04_TRADE_SIGNAL","SYNTHETIC_POLICY_THRESHOLDS_REQUIRE_M06_VALIDATION"]}
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input",required=True)
    p.add_argument("--profile",required=True)
    opt=p.parse_args()
    with open(opt.input,encoding="utf-8") as f: inp=json.load(f)
    with open(opt.profile,encoding="utf-8") as f: profile=json.load(f)
    print(json.dumps(analyze(inp,profile),ensure_ascii=False,indent=2))
if __name__=="__main__":
    main()
