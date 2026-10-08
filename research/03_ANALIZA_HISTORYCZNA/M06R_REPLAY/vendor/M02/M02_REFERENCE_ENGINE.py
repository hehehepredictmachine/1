"""M02 reference implementation, read-only, no MT5 connection, no screenshot, no orders.

Consumes validated-like M01 JSON DATA_SNAPSHOTs and optionally M16 health.
A spec/test reference, NOT a validated trading strategy or production feed bridge.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MODULE_VERSION = "1.0.0-CANDIDATE"
PROFILE_PATH = Path(__file__).with_name("M02_PROFILE.example.json")
DIRECTION = {"TREND_UP": "BULLISH", "TREND_DOWN": "BEARISH", "RANGE": "NEUTRAL"}
VALID_TF = {"M1", "M5", "M15", "H1", "H4", "D1"}


def iso(ts: str) -> datetime:
    if not isinstance(ts, str) or not ts:
        raise ValueError("TIME_UNKNOWN")
    obj = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if obj.tzinfo is None:
        raise ValueError("TIMEZONE_REQUIRED")
    return obj.astimezone(timezone.utc)


def numeric(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(float(x))


def valid_ohlc(b: dict) -> bool:
    vals = [b.get(k) for k in ("open", "high", "low", "close")]
    if not all(numeric(x) for x in vals):
        return False
    o, h, l, c = [float(x) for x in vals]
    return l > 0 and l <= min(o, c) <= max(o, c) <= h


def prepare_candles(snapshot: dict, tf: str) -> tuple[list[dict], list[str], bool, list[str]]:
    """Only MT5 closed, confirmed point-in-time candles. Last argument is changed revisions."""
    now = iso(snapshot["as_of"])
    issues: list[str] = []
    revised: list[str] = []
    forming = False
    buckets: dict[str, dict] = {}
    for b in snapshot.get("candles_by_tf", {}).get(tf, []):
        if not isinstance(b, dict):
            issues.append("INVALID_BAR_OBJECT"); continue
        if b.get("instrument_id") not in ("XAUUSD",):
            issues.append("CANDLE_INSTRUMENT_MISMATCH"); continue
        if b.get("timeframe") != tf:
            issues.append("CANDLE_TIMEFRAME_MISMATCH"); continue
        state = b.get("bar_state")
        if state == "FORMING":
            forming = True; continue
        if state != "CLOSED":
            issues.append("BAR_NOT_CONFIRMED"); continue
        src = b.get("source_id")
        if not isinstance(src, str) or not src.upper().startswith("MT5"):
            issues.append("NON_MT5_CANDLE_EXCLUDED"); continue
        try:
            bar_time = iso(b["bar_open_utc"])
            available = iso(b["available_at"])
            confirmed = iso(b["close_confirmed_at"])
        except (ValueError, TypeError, KeyError):
            issues.append("CANDLE_TIME_INVALID"); continue
        if confirmed < bar_time or available < bar_time:
            issues.append("CANDLE_TIME_INVALID"); continue
        if confirmed > now or available > now:
            issues.append("FUTURE_EVIDENCE_EXCLUDED"); continue
        if not valid_ohlc(b):
            issues.append("INVALID_OHLC"); continue
        if not b.get("evidence_id") or not b.get("price_basis"):
            issues.append("MISSING_PROVENANCE"); continue
        key = bar_time.isoformat()
        prev = buckets.get(key)
        if prev is None:
            buckets[key] = b
            continue
        def candle_tuple(o: dict):
            return tuple(o.get(k) for k in ("open", "high", "low", "close", "tick_volume", "price_basis"))
        if int(b.get("revision", 0)) == int(prev.get("revision", 0)):
            if candle_tuple(prev) != candle_tuple(b):
                issues.append("CONFLICTING_CLOSED_BAR_REVISIONS")
                buckets.pop(key, None)
            continue
        if int(b.get("revision", 0)) > int(prev.get("revision", 0)):
            buckets[key] = b
            revised.append(key)
    candles = sorted(buckets.values(), key=lambda x: iso(x["bar_open_utc"]))
    if len({c.get("price_basis") for c in candles}) > 1:
        issues.append("MIXED_PRICE_BASIS")
        candles = []
    if "CONFLICTING_CLOSED_BAR_REVISIONS" in issues:
        candles = [] # fail-closed, never silently resolve conflict by dropped bar
    return candles, sorted(set(issues)), forming, revised


def atr_series(bars: list[dict], n: int) -> list[float | None]:
    vals: list[float | None] = [None] * len(bars)
    if len(bars) < n + 1:
        return vals
    trs = []
    for i in range(1, len(bars)):
        b, prev = bars[i], bars[i-1]
        trs.append(max(float(b["high"])-float(b["low"]),
                       abs(float(b["high"])-float(prev["close"])),
                       abs(float(b["low"])-float(prev["close"]))))
    a = sum(trs[:n]) / n
    vals[n] = a
    for i in range(n+1, len(bars)):
        a = ((n-1)*a + trs[i-1]) / n
        vals[i] = a
    return vals


def pivots(bars: list[dict], k_left: int, k_right: int) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {"highs": [], "lows": []}
    for i in range(k_left, len(bars)-k_right):
        b = bars[i]
        window = bars[i-k_left:i] + bars[i+1:i+k_right+1]
        if all(float(b["high"]) > float(z["high"]) for z in window):
            out["highs"].append({"price": b["high"], "pivot_time": b["bar_open_utc"],
                                 "available_at": bars[i+k_right]["close_confirmed_at"]})
        if all(float(b["low"]) < float(z["low"]) for z in window):
            out["lows"].append({"price": b["low"], "pivot_time": b["bar_open_utc"],
                                "available_at": bars[i+k_right]["close_confirmed_at"]})
    return out


def efficiency(bars: list[dict], n: int) -> float | None:
    if len(bars) <= n:
        return None
    closes = [float(x["close"]) for x in bars[-(n+1):]]
    total = sum(abs(b-a) for a,b in zip(closes,closes[1:]))
    return abs(closes[-1]-closes[0])/total if total > 0 else None


def slope_atr(bars: list[dict], n: int, atr: float | None) -> float | None:
    if not atr or atr <= 0 or len(bars) < n:
        return None
    close = [float(z["close"]) for z in bars[-n:]]
    mid=(n-1)/2
    denom=sum((i-mid)**2 for i in range(n))
    return sum((i-mid)*(v-statistics.mean(close)) for i,v in enumerate(close))/denom/atr if denom else None


def classify_tf(snapshot: dict, tf: str, cfg: dict) -> dict:
    candles, issues, forming, revised = prepare_candles(snapshot, tf)
    n = len(candles)
    base = {"timeframe":tf,"closed_bars":n,"last_closed_at":candles[-1]["close_confirmed_at"] if n else None,
            "last_closed_bar_open":candles[-1]["bar_open_utc"] if n else None,
            "has_forming_preview":forming,"issues":issues,"revised_bars":revised,
            "structure_regime":"UNKNOWN","volatility_level":"UNKNOWN", "volatility_phase":"UNKNOWN",
            "trend_phase":"UNKNOWN", "behavior":"UNKNOWN", "event_regime":"UNKNOWN",
            "direction":"UNKNOWN","efficiency":None,"atr":None,"normalized_move":None,
            "slope_atr":None,"volatility_ratio":None,"swings":{"highs":[],"lows":[]},
            "protected_high":None,"protected_low":None,
            "evidence_ids":[],"status":"PENDING"}
    if any(x in issues for x in ["INVALID_OHLC","MIXED_PRICE_BASIS","CONFLICTING_CLOSED_BAR_REVISIONS","CANDLE_INSTRUMENT_MISMATCH","CANDLE_TIMEFRAME_MISMATCH"]):
        base["status"]="FAIL"; return base
    if n < cfg["min_closed_bars"]:
        base["issues"] += ["INSUFFICIENT_CLOSED_BARS"]; return base
    a = atr_series(candles,cfg["atr_period"])
    lastatr = a[-1]
    base["atr"] = lastatr
    if not lastatr or lastatr <= 0:
        base["issues"] += ["ATR_UNAVAILABLE"]; return base
    look = cfg["efficiency_lookback"]
    eff = efficiency(candles,look)
    norm = (float(candles[-1]["close"])-float(candles[-(look+1)]["close"]))/lastatr
    sl = slope_atr(candles,look,lastatr)
    pv = pivots(candles,cfg["pivot_left"],cfg["pivot_right"])
    highs,lows = pv["highs"],pv["lows"]
    eps = cfg["price_epsilon_abs"]
    structure_up = len(highs)>=2 and len(lows)>=2 and (highs[-1]["price"]-highs[-2]["price"])>eps and (lows[-1]["price"]-lows[-2]["price"])>eps
    structure_down = len(highs)>=2 and len(lows)>=2 and (highs[-2]["price"]-highs[-1]["price"])>eps and (lows[-2]["price"]-lows[-1]["price"])>eps
    recent_close = [float(z["close"]) for z in candles[-(look+1):]]
    width = (max(recent_close)-min(recent_close))/lastatr
    if eff is None:
        regime="UNKNOWN"
    elif (structure_up and eff>=cfg["efficiency_trend_min"] and norm>=cfg["normalized_move_min_atr"]
          and sl is not None and sl>=cfg["slope_min_atr_per_bar"]):
        regime="TREND_UP"
    elif (structure_down and eff>=cfg["efficiency_trend_min"] and norm<=-cfg["normalized_move_min_atr"]
          and sl is not None and sl<=-cfg["slope_min_atr_per_bar"]):
        regime="TREND_DOWN"
    elif eff<=cfg["range_efficiency_max"] and width<=cfg["range_width_max_atr"]:
        regime="RANGE"
    else:
        regime="TRANSITION"
    past=[x for x in a[-(cfg["volatility_baseline_period"]+1):-1] if x and x>0]
    v_ratio=lastatr/statistics.median(past) if len(past)>=cfg["volatility_baseline_period"] else None
    if v_ratio is not None:
        if v_ratio>=cfg["volatility_extreme_ratio"]: v_level="EXTREME"
        elif v_ratio>=cfg["volatility_high_ratio"]: v_level="HIGH"
        elif v_ratio<=cfg["volatility_low_ratio"]: v_level="LOW"
        else: v_level="NORMAL"
        v_phase=("COMPRESSION" if v_ratio<=cfg["volatility_compression_ratio"] else
                 "EXPANSION" if v_ratio>=cfg["volatility_expansion_ratio"] else "STABLE")
    else:
        v_level="UNKNOWN"; v_phase="UNKNOWN"
    base.update({"status":"PASS" if not issues else "PASS_WITH_LIMITATIONS",
                 "structure_regime":regime,"direction":DIRECTION.get(regime,"UNKNOWN"),
                 "volatility_level":v_level,"volatility_phase":v_phase,"volatility_ratio":v_ratio,
                 "efficiency":eff,"atr":lastatr,"normalized_move":norm,"slope_atr":sl,
                 "swings":{"highs":highs,"lows":lows},
                 "protected_high":highs[-1]["price"] if highs else None,
                 "protected_low":lows[-1]["price"] if lows else None,
                 "evidence_ids":[x.get("evidence_id") for x in candles if x.get("evidence_id")][-5:]})
    return base


class RegimeMemory:
    """Uninterrupted sequential CLOSED-bar confirmations. Pure live companion; no persistence assumption."""
    def __init__(self, confirmations: int=2):
        if confirmations < 1: raise ValueError("confirmation count >=1")
        self.confirmations=confirmations
        self.state:dict[str,dict] = {}

    def update(self, tf: str, candidate: str, last_bar: str | None, healthy: bool=True) -> dict:
        s=self.state.setdefault(tf,{"stable":"UNKNOWN","pending":None,"count":0,"last_bar":None})
        if not healthy or candidate=="UNKNOWN":
            s.update({"stable":"UNKNOWN","pending":None,"count":0,"last_bar":last_bar})
            return {"stable_regime":"UNKNOWN","candidate_regime":candidate,"confirmation_progress":0,"transition_pending":False}
        if not last_bar or (s["last_bar"] is not None and iso(last_bar)<iso(s["last_bar"])):
            return {"stable_regime":s["stable"],"candidate_regime":candidate,"confirmation_progress":s["count"],"transition_pending":True}
        if s["last_bar"]==last_bar:
            return {"stable_regime":s["stable"],"candidate_regime":candidate,"confirmation_progress":s["count"],"transition_pending":s["pending"] is not None}
        s["last_bar"]=last_bar
        if candidate==s["stable"]:
            s.update({"pending":None,"count":0})
        elif s["pending"]==candidate:
            s["count"]+=1
        else:
            s.update({"pending":candidate,"count":1})
        if s["count"]>=self.confirmations:
            s.update({"stable":candidate,"pending":None,"count":0})
        return {"stable_regime":s["stable"],"candidate_regime":candidate,"confirmation_progress":s["count"],"transition_pending":s["pending"] is not None}


def analyze(snapshot:dict, cfg:dict, runtime_health:dict|None=None, memory:RegimeMemory|None=None) -> dict:
    asof=iso(snapshot["as_of"])
    snapshot_id = snapshot.get("snapshot_id")
    if not snapshot_id:
        raise ValueError("SNAPSHOT_ID_REQUIRED")
    tf_list=cfg["timeframes"]
    if len(tf_list)!=len(set(tf_list)) or not set(tf_list)<=VALID_TF:
        raise ValueError("TF_CONFIGURATION_INVALID")
    req=set(cfg["required_timeframes"])
    if not req<=set(tf_list): raise ValueError("REQUIRED_TF_CONFIGURATION_INVALID")
    per={tf:classify_tf(snapshot,tf,cfg) for tf in tf_list}
    runtime_status=(runtime_health or {}).get("status","UNKNOWN")
    data_gates=snapshot.get("data_gates",[])
    m01_analytical_gates=[g for g in data_gates if set(g.get("required_for",[])) & {"ANALYSIS","DIRECTION"}]
    m01_exec_gates=[g for g in data_gates if "EXECUTION" in g.get("required_for",[])]
    m01_bad = any(g.get("status")=="FAIL" for g in m01_analytical_gates)
    m01_unverified=not m01_analytical_gates or any(g.get("status") not in ("PASS","PASS_WITH_LIMITATIONS") for g in m01_analytical_gates)
    m01_execution_unverified=not m01_exec_gates or any(g.get("status") != "PASS" for g in m01_exec_gates)
    source_policy_ok=snapshot.get("data_source_policy")=="MT5_PRIMARY_TV_SUPPLEMENTAL_NO_SCREENSHOTS"

    missing=[tf for tf in cfg["required_timeframes"] if per[tf]["status"] not in ("PASS","PASS_WITH_LIMITATIONS")]
    corrupted=any(per[tf]["status"]=="FAIL" for tf in req)
    if m01_bad or corrupted:
        status="FAIL"; reasons=["M01_REQUIRED_DATA_FAIL" if m01_bad else "INVALID_REQUIRED_TF"]
    elif not source_policy_ok or m01_unverified:
        status="PENDING"; reasons=["M01_DATA_GATE_UNVERIFIED" if m01_unverified else "SOURCE_POLICY_UNVERIFIED"]
    elif missing:
        status="PENDING"; reasons=["REQUIRED_TF_UNAVAILABLE:"+tf for tf in missing]
    else:
        status="PASS"; reasons=[]
        if any(per[tf]["status"]!="PASS" for tf in tf_list if tf not in req):
            status="PASS_WITH_LIMITATIONS"
    # No additional M16 proof is fabricated. Execution context stays PENDING absent a verified health source.
    runtime_gate=(runtime_health or {}).get("execution_data_gate", "UNKNOWN")
    execution_context="PASS" if status=="PASS" and runtime_status=="HEALTHY" and runtime_gate=="PASS" and not snapshot.get("_fixture_only") and not m01_execution_unverified else "PENDING"
    if runtime_status in ("DEGRADED","OFFLINE","QUARANTINED","STOPPED") or runtime_gate=="FAIL":
        execution_context="FAIL"
        reasons.append("M16_RUNTIME_NOT_HEALTHY")
    if m01_execution_unverified: reasons.append("M01_EXECUTION_DATA_UNVERIFIED")
    if status=="FAIL": execution_context="FAIL"
    if execution_context!="PASS": reasons.append("EXECUTION_CONTEXT_NOT_VERIFIED")
    if snapshot.get("_fixture_only"):
        reasons.append("SYNTHETIC_FIXTURE_NOT_LIVE")
    def direction(tf:str)->str:
        return per[tf]["direction"] if tf in per and per[tf]["status"] in ("PASS","PASS_WITH_LIMITATIONS") else "UNKNOWN"
    style=cfg.get("trading_style","SCALP")
    struct_tf=("H4","H1") if style=="SCALP" else ("D1","H4")
    tactical_tf="M5" if style=="SCALP" else "M15"
    structural=[direction(tf) for tf in struct_tf]
    structural_direction=structural[0] if structural[0]!="UNKNOWN" and len(set(structural))==1 else "UNKNOWN"
    tactical_direction=direction(tactical_tf)
    exec_direction=direction("M1" if style=="SCALP" else "M5")
    if structural_direction in ("BULLISH","BEARISH") and tactical_direction not in (structural_direction,"NEUTRAL","UNKNOWN"):
        conflict="CORRECTION_POSSIBLE" # M03 owns actual protected-swing invalidation
    elif structural_direction!="UNKNOWN" and tactical_direction==structural_direction:
        conflict="ALIGNED"
    elif len(set(structural))>1 and "UNKNOWN" not in structural:
        conflict="HTF_CONFLICT"
    else:
        conflict="UNRESOLVED"
    for tf, x in per.items():
        if memory:
            # a data-quality fail immediately invalidates stable regime
            x.update(memory.update(tf,x["structure_regime"],x["last_closed_at"],
                                   healthy=x["status"] in ("PASS","PASS_WITH_LIMITATIONS") and not m01_bad))
        else:
            x.update({"stable_regime":"UNKNOWN","candidate_regime":x["structure_regime"],
                      "confirmation_progress":0,"transition_pending":True})
    evidence=list(dict.fromkeys(e for v in per.values() for e in v["evidence_ids"]))
    return {"module_id":"M02","module_version":MODULE_VERSION,"analysis_id":snapshot.get("analysis_id"),
            "snapshot_id":snapshot_id,"as_of":asof.isoformat(),"instrument_id":"XAUUSD",
            "config_version":cfg.get("config_version"),"feature_spec_id":cfg.get("feature_spec_id"),
            "strategy_version":snapshot.get("strategy_version"),"trading_style":style,
            "status":status,"run_status":"COMPLETED","evidence_ids":evidence,
            "missing_inputs":missing,"reason_codes":reasons,"limitations":["PROVISIONAL_RESEARCH_THRESHOLDS","NO_PRODUCTION_INTEGRATION"],
            "timeframes":per,"structural_direction":structural_direction,"tactical_direction":tactical_direction,
            "execution_observation_direction":exec_direction,"regime_conflict":conflict,
            "required_timeframes":cfg["required_timeframes"],"optional_timeframes":cfg.get("optional_timeframes",[]),
            "analysis_gate":{"required_for":["ANALYSIS","DIRECTION"],"status":status,"reason_codes":reasons},
            "execution_context_gate":{"required_for":["EXECUTION"],"status":execution_context,"reason_codes":reasons},
            "runtime_health_status":runtime_status,"visual_capture_enabled":False,
            "market_data_source_policy":"MT5_PRIMARY_TV_SUPPLEMENTAL_NO_SCREENSHOTS"}


def main(argv:list[str]|None=None)->int:
    ap=argparse.ArgumentParser(description="M02 read-only JSONL snapshot analyzer; does not connect to MT5")
    ap.add_argument("--profile",default=str(PROFILE_PATH))
    ap.add_argument("--input",default="-",help="JSONL snapshots or envelopes with data_snapshot")
    ns=ap.parse_args(argv)
    cfg=json.loads(Path(ns.profile).read_text(encoding="utf-8"))
    mem=RegimeMemory(cfg["regime_confirmation_bars"])
    inp=sys.stdin if ns.input=="-" else open(ns.input,encoding="utf-8")
    try:
        for ln in inp:
            if not ln.strip(): continue
            try:
                data=json.loads(ln)
                result=analyze(data.get("data_snapshot",data),cfg,data.get("runtime_health"),mem)
                print(json.dumps(result,ensure_ascii=False,allow_nan=False))
            except Exception as exc:
                print(json.dumps({"module_id":"M02","status":"FAIL","run_status":"FAILED","reason_codes":[str(exc)],"execution_context_gate":{"status":"FAIL"}}),flush=True)
    finally:
        if inp is not sys.stdin: inp.close()
    return 0


if __name__=="__main__":
    raise SystemExit(main())
