"""Deterministic synthetic tests. Not an MT5 demo or backtest."""
import copy
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from M10_REFERENCE_ENGINE import process, core_ok, validated_plan, SQLiteSetupStore, POLICY, ts, digest, init_record

T0 = datetime(2026, 10, 8, 10, 0, tzinfo=timezone.utc)
def dt(minutes=0): return (T0 + timedelta(minutes=minutes)).isoformat()

def fixture():
    core={k: {"evidence_id": k, "available_at": dt(), "snapshot_id": "snapshot-A", "instrument_id": "XAUUSD", "evidence_status": "VERIFIED", "source": "MT5_PRIMARY", "category": "STRUCTURAL"} for k in ("structural_advantage", "meaningful_location", "liquidity_context", "development_path", "known_invalidation")}
    return {"schema_version": "2.0.0", "data_source_policy": POLICY, "screenshot_capture_enabled": False, "analysis_id":"SYNTHETIC_ONLY", "as_of": dt(), "data_snapshot": {"snapshot_id":"snapshot-A", "as_of": dt(), "instrument_id":"XAUUSD", "analysis_gate":"PASS", "execution_gate":"PENDING", "data_source_policy":POLICY, "screenshot_capture_enabled":False}, "runtime":{"status":"HEALTHY"}, "router_result":{"module_id":"M09", "analysis_pool":[{"setup_id":"SYN-001","analytical_eligible":True}], "execution_pool":[], "execution_permission":"BLOCKED"}, "setup": {"setup_id":"SYN-001", "strategy_id":"XAU-S02", "version":"0.1.0", "spec_hash":"f"*64, "direction":"LONG", "instrument_id":"XAUUSD", "horizon_id":"M5:10", "setup_tf":"M5", "core_evidence":core, "created_at":dt(), "next_expected_event":"WAIT_FOR_RECLAIM", "invalidation":{"price":2990.0,"rule":"M5_CLOSE_BELOW"}}, "config":{"ttl_closed_bars":12,"aging_closed_bars":6,"max_quote_age_seconds":5}, "events":[], "plan":{"price_source":"MT5_PRIMARY", "entry":3000.0,"stop_loss":2990.0,"targets":[3020.0,3030.0],"partial_weights":[0.5,0.5],"entry_trigger":"M5_RECLAIM_CLOSE","invalidation":{"price":2990.0},"management_rules":{"stop":"NO_WIDENING"}}}

def event(name, num=0, **extra):
    x={"event_id":f"e-{num}-{name}","evidence_id":f"evidence-{num}-{name}","type":name,"source":"MT5_PRIMARY", "instrument_id":"XAUUSD", "snapshot_id":"snapshot-A", "evidence_status":"VERIFIED", "available_at":dt()}
    x.update(extra); return x

def life_events():
    return [event("CORE_READY",1), event("DEVELOPMENT",2), event("QUALIFY",3,conditions_met=True), event("ARM",4,conditions_met=True), event("TRIGGER",5,trigger_confirmed=True,bar_state="CLOSED",requires_closed_bar=True), event("CONFIRM",6,confirmation_gates={"data":"PASS","trigger":"PASS","invalidation":"PASS","expiry":"PASS","conflict":"PASS"},distinct_confirmation=True,ref_trigger_event_id="e-5-TRIGGER",bar_state="CLOSED",requires_closed_bar=True)]

class M10Tests(unittest.TestCase):
    def test_initial(self):
        x=process(fixture()); self.assertEqual(x["setup"]["state"],"CANDIDATE"); self.assertEqual(x["execution_permission"],"BLOCKED"); self.assertFalse(x["live_execution_allowed"]); self.assertIsNone(x["submitted_order_id"])
    def test_full_analytical_path(self):
        p=fixture(); p["events"]=life_events(); r=process(p); self.assertEqual(r["setup"]["state"],"CONFIRMED"); self.assertEqual(r["setup"]["revision"],6); self.assertEqual(r["setup"]["entry_status"],"CONDITIONAL"); self.assertEqual(len(r["setup"]["change_log"]),6); self.assertEqual(r["setup"]["order_state"],"NONE")
    def test_no_skipping(self):
        for name in ("DEVELOPMENT", "QUALIFY", "ARM", "TRIGGER", "CONFIRM", "FILL", "MANAGE", "FULL_EXIT", "REVIEW"):
            with self.subTest(name=name):
                p=fixture(); p["events"]=[event(name,1,conditions_met=True,trigger_confirmed=True,confirmation_gates={"x":"PASS"},distinct_confirmation=True)]; x=process(p); self.assertEqual(x["setup"]["state"],"CANDIDATE")
    def test_stepwise_states(self):
        steps=["EARLY_SETUP","SETUP_FORMING","QUALIFIED","ARMED","TRIGGERED","CONFIRMED"]
        for n,state in enumerate(steps,1):
            with self.subTest(stage=state):
                p=fixture(); p["events"]=life_events()[:n]; self.assertEqual(process(p)["setup"]["state"],state)
    def test_replay_idempotent(self):
        p=fixture(); p["events"]=life_events(); a=process(p); b=process(p,a["setup"]); self.assertEqual(a["setup"]["revision"],b["setup"]["revision"]); self.assertEqual(len(a["setup"]["change_log"]),len(b["setup"]["change_log"]))
    def test_collision(self):
        p=fixture(); p["events"]=[event("CORE_READY",1), {**event("CORE_READY",1),"evidence_id":"different"}]
        with self.assertRaisesRegex(ValueError,"EVENT_ID_COLLISION_IN_BATCH"): process(p)
    def test_collision_history(self):
        p=fixture(); p["events"]=[event("CORE_READY",1)]; a=process(p); p["events"]=[{**event("CORE_READY",1),"evidence_id":"different"}]
        with self.assertRaisesRegex(ValueError,"EVENT_ID_COLLISION_WITH_HISTORY"): process(p,a["setup"])
    def test_after_asof(self):
        p=fixture(); p["events"]=[event("CORE_READY",1,available_at=dt(1))]; x=process(p); self.assertEqual(x["setup"]["state"],"CANDIDATE"); self.assertIn("FUTURE_EVIDENCE",str(x["rejected_events"]))
    def test_core_missing_each(self):
        for k in fixture()["setup"]["core_evidence"]:
            with self.subTest(k=k):
                p=fixture(); del p["setup"]["core_evidence"][k]; p["events"]=[event("CORE_READY")]; x=process(p); self.assertEqual(x["setup"]["state"],"CANDIDATE"); self.assertIn("CORE_MISSING_"+k.upper(),x["reason_codes"])
    def test_future_core(self):
        p=fixture(); p["setup"]["core_evidence"]["liquidity_context"]["available_at"]=dt(1); p["events"]=[event("CORE_READY")]; x=process(p); self.assertEqual(x["setup"]["state"],"CANDIDATE")
    def test_core_wrong_snapshot(self):
        p=fixture(); p["setup"]["core_evidence"]["meaningful_location"]["snapshot_id"]="OTHER"; self.assertIn("CORE_CONTEXT_MISMATCH_MEANINGFUL_LOCATION",process(p)["reason_codes"])
    def test_core_wrong_instrument(self):
        p=fixture(); p["setup"]["core_evidence"]["meaningful_location"]["instrument_id"]="EURUSD"; self.assertIn("CORE_CONTEXT_MISMATCH_MEANINGFUL_LOCATION",process(p)["reason_codes"])
    def test_core_open_bar(self):
        p=fixture(); p["setup"]["core_evidence"]["structural_advantage"].update({"requires_closed_bar":True,"bar_state":"FORMING"}); self.assertIn("CORE_BAR_NOT_CLOSED_STRUCTURAL_ADVANTAGE",process(p)["reason_codes"])
    def test_core_incorrect_broker_source(self):
        p=fixture(); p["setup"]["core_evidence"]["structural_advantage"].update({"source":"TRADINGVIEW_SUPPLEMENTAL","category":"EXECUTION_TRIGGER"}); self.assertIn("BROKER_SOURCE_REQUIRED_STRUCTURAL_ADVANTAGE",process(p)["reason_codes"])
    def test_m01_bad_gate(self):
        p=fixture(); p["data_snapshot"]["analysis_gate"]="FAIL"; p["events"]=[event("CORE_READY")]; self.assertEqual(process(p)["setup"]["state"],"CANDIDATE")
    def test_m16_unhealthy(self):
        for status in ("DEGRADED","OFFLINE","RECOVERING"):
            with self.subTest(status=status):
                p=fixture(); p["runtime"]["status"]=status; p["events"]=[event("CORE_READY")]; self.assertEqual(process(p)["setup"]["state"],"CANDIDATE")
    def test_m09_missing(self):
        p=fixture(); p["router_result"]={}; p["events"]=[event("CORE_READY")]; self.assertEqual(process(p)["setup"]["state"],"CANDIDATE")
    def test_m09_not_eligible(self):
        p=fixture(); p["router_result"]["analysis_pool"][0]["analytical_eligible"]=False; p["events"]=[event("CORE_READY")]; self.assertEqual(process(p)["setup"]["state"],"CANDIDATE")
    def test_tv_trigger_blocked(self):
        p=fixture(); p["events"]=life_events()[:4]+[event("TRIGGER",5,trigger_confirmed=True,source="TRADINGVIEW_SUPPLEMENTAL")]; r=process(p); self.assertEqual(r["setup"]["state"],"ARMED"); self.assertIn("MT5_PRICE_EVIDENCE_REQUIRED", str(r["rejected_events"]))
    def test_tv_confirm_blocked(self):
        p=fixture(); p["events"]=life_events()[:5]+[event("CONFIRM",6,source="TRADINGVIEW_SUPPLEMENTAL",confirmation_gates={"x":"PASS"},distinct_confirmation=True,ref_trigger_event_id="e-5-TRIGGER")]; self.assertEqual(process(p)["setup"]["state"],"TRIGGERED")
    def test_trigger_requires_close(self):
        p=fixture(); p["events"]=life_events()[:4]+[event("TRIGGER",5,requires_closed_bar=True,bar_state="FORMING",trigger_confirmed=True)]; self.assertEqual(process(p)["setup"]["state"],"ARMED")
    def test_trigger_unconfirmed(self):
        p=fixture(); p["events"]=life_events()[:4]+[event("TRIGGER",5,trigger_confirmed=False)]; self.assertEqual(process(p)["setup"]["state"],"ARMED")
    def test_confirm_gates(self):
        for extra in ({"confirmation_gates":{"data":"FAIL"},"distinct_confirmation":True},{"confirmation_gates":{"data":"PASS"},"distinct_confirmation":False},{"confirmation_gates":{},"distinct_confirmation":True}):
            with self.subTest(extra=extra):
                p=fixture(); p["events"]=life_events()[:5]+[event("CONFIRM",6,ref_trigger_event_id="e-5-TRIGGER",**extra)]; self.assertEqual(process(p)["setup"]["state"],"TRIGGERED")
    def test_invalidate(self):
        p=fixture(); p["events"]=life_events()[:2]+[event("INVALIDATE",20)]+life_events()[2:]; r=process(p); self.assertEqual(r["setup"]["state"],"INVALIDATED"); self.assertEqual(r["setup"]["revision"],3)
    def test_terminal_variants(self):
        for name,state in (("EXPIRE","EXPIRED"),("CANCEL","CANCELLED"),("MISSED_ENTRY","MISSED_ENTRY"),("TARGET_REACHED","EXPIRED")):
            with self.subTest(name=name):
                p=fixture(); p["events"]=[event(name,1)]; self.assertEqual(process(p)["setup"]["state"],state)
    def test_ttl(self):
        p=fixture(); bars=[event("CLOSED_BAR",i,bar_state="CLOSED",timeframe="M5",bar_open_utc=dt(i*5),close_confirmed_at=dt((i+1)*5),available_at=dt((i+1)*5)) for i in range(12)]
        # Inputs are deliberately as_of advanced beyond last bar, snapshots and core evidence stay point-in-time.
        p["as_of"]=dt(60); p["data_snapshot"]["as_of"]=dt(60); p["events"]=bars
        self.assertEqual(process(p)["setup"]["state"],"EXPIRED")
    def test_aging(self):
        p=fixture(); p["as_of"]=dt(35); p["data_snapshot"]["as_of"]=dt(35)
        p["events"]=[event("CLOSED_BAR",i,bar_state="CLOSED",timeframe="M5",bar_open_utc=dt(i*5),close_confirmed_at=dt((i+1)*5),available_at=dt((i+1)*5)) for i in range(6)]; x=process(p)
        self.assertTrue(x["setup"]["aging"]); self.assertEqual(x["setup"]["closed_bars_elapsed"],6)
    def test_no_duplicate_bars(self):
        p=fixture(); p["as_of"]=dt(6); p["data_snapshot"]["as_of"]=dt(6)
        p["events"]=[event("CLOSED_BAR",i,bar_state="CLOSED",timeframe="M5",bar_open_utc=dt(),close_confirmed_at=dt(5),available_at=dt(5)) for i in range(3)]
        self.assertEqual(process(p)["setup"]["closed_bars_elapsed"],1)
    def test_bar_tf_wrong(self):
        p=fixture(); p["events"]=[event("CLOSED_BAR",1,bar_state="CLOSED",timeframe="H1",bar_open_utc=dt())]; self.assertEqual(process(p)["setup"]["closed_bars_elapsed"],0)
    def test_bar_without_time(self):
        p=fixture(); p["events"]=[event("CLOSED_BAR",1,bar_state="CLOSED",timeframe="M5")]; self.assertEqual(process(p)["setup"]["closed_bars_elapsed"],0)
    def test_malformed_date(self):
        for field,val in (("as_of","not_time"),("as_of","2026-10-08T10:00:00")):
            with self.subTest(field=field,val=val):
                p=fixture(); p[field]=val
                with self.assertRaises(ValueError): process(p)
    def test_snapshot_mismatch(self):
        p=fixture(); p["data_snapshot"]["as_of"]=dt(1)
        with self.assertRaisesRegex(ValueError,"AS_OF_SNAPSHOT_MISMATCH"): process(p)
    def test_data_instrument(self):
        p=fixture(); p["data_snapshot"]["instrument_id"]="DXY"
        with self.assertRaisesRegex(ValueError,"DATA_INSTRUMENT_MISMATCH"): process(p)
    def test_schema(self):
        p=fixture(); p["schema_version"]="3.0.0"
        with self.assertRaisesRegex(ValueError,"SCHEMA_VERSION_MISMATCH"): process(p)
    def test_no_screenshot(self):
        for val in (True,"TRUE",None):
            with self.subTest(val=val):
                p=fixture(); p["screenshot_capture_enabled"]=val
                with self.assertRaisesRegex(ValueError,"SCREENSHOTS_FORBIDDEN"): process(p)
    def test_no_foreign_policy(self):
        p=fixture(); p["data_source_policy"]="SCREENSHOT"
        with self.assertRaisesRegex(ValueError,"DATA_SOURCE_POLICY_MISMATCH"): process(p)
    def test_unknown_event_source(self):
        for source in ("SCREENSHOT","OCR","WEB_SCRAPE","TV_PIXELS",None):
            with self.subTest(source=source):
                p=fixture(); p["events"]=[event("CORE_READY",1,source=source)]; self.assertEqual(process(p)["setup"]["state"],"CANDIDATE")
    def test_unknown_event_name(self):
        p=fixture(); p["events"]=[event("BUY_NOW",1)]; self.assertIn("UNKNOWN_EVENT_TYPE",str(process(p)["rejected_events"]))
    def test_no_real_fill(self):
        p=fixture(); p["events"]=life_events()+[event("FILL",7,source="MT5_BROKER_EVENT",broker_deal_id="synthetic")]; r=process(p); self.assertEqual(r["setup"]["state"],"CONFIRMED"); self.assertIn("TRUSTED_BROKER_RECONCILIATION_NOT_IMPLEMENTED",str(r["rejected_events"]))
    def test_simulated_fill(self):
        p=fixture(); p["reference_mode"]="SIMULATION"; p["events"]=life_events()+[event("FILL",7,source="MT5_BROKER_EVENT",broker_deal_id="SYNTH-1")]; r=process(p); self.assertEqual(r["setup"]["state"],"ENTERED"); self.assertFalse(r["live_execution_allowed"]); self.assertIsNone(r["actual_fills"])
    def test_simulated_exit(self):
        p=fixture(); p["reference_mode"]="SIMULATION"; p["events"]=life_events()+[event("FILL",7,source="MT5_BROKER_EVENT",broker_deal_id="SYNTH-1"),event("MANAGE",8),event("FULL_EXIT",9,source="MT5_BROKER_EVENT",broker_deal_id="SYNTH-2",position_fully_closed=True),event("REVIEW",10)]
        r=process(p); self.assertEqual(r["setup"]["state"],"REVIEWED")
    def test_partial_not_entered(self):
        p=fixture(); p["reference_mode"]="SIMULATION"; p["events"]=life_events()+[event("PARTIAL_FILL",7,source="MT5_BROKER_EVENT",broker_deal_id="SYNTH-1")]; r=process(p); self.assertEqual(r["setup"]["state"],"ENTERED"); self.assertEqual(r["setup"]["order_state"],"PARTIALLY_FILLED")
    def test_exit_requires_full_close(self):
        p=fixture(); p["reference_mode"]="SIMULATION"; p["events"]=life_events()+[event("FILL",7,source="MT5_BROKER_EVENT",broker_deal_id="SYNTH-1"),event("FULL_EXIT",8,source="MT5_BROKER_EVENT",broker_deal_id="SYNTH-2",position_fully_closed=False)]
        self.assertEqual(process(p)["setup"]["state"],"ENTERED")
    def test_invalidation_after_entered_no_archive(self):
        p=fixture(); p["reference_mode"]="SIMULATION"; p["events"]=life_events()+[event("FILL",7,source="MT5_BROKER_EVENT",broker_deal_id="SYNTH-1"),event("INVALIDATE",8)]
        self.assertEqual(process(p)["setup"]["state"],"ENTERED")
    def test_identity_immutable(self):
        p=fixture(); a=process(p)
        for fld,value in (("direction","SHORT"),("spec_hash","x"*64),("strategy_id","XAU-S01"),("version","1.0.0"),("horizon_id","H1"),("setup_id","new"),("instrument_id","EURUSD")):
            with self.subTest(fld=fld):
                q=fixture(); q["setup"][fld]=value
                with self.assertRaises(ValueError): process(q,a["setup"])
    def test_time_rollback(self):
        p=fixture(); p["as_of"]=dt(20); p["data_snapshot"]["as_of"]=dt(20); a=process(p)
        with self.assertRaisesRegex(ValueError,"AS_OF_ROLLBACK"): process(fixture(),a["setup"])
    def test_entry_plan_geometry(self):
        for direction,entry,stop,targets in (("LONG",3000,3010,[3030]),("SHORT",3000,2990,[2980]),("LONG",3000,2990,[2999]),("SHORT",3000,3010,[3001])):
            with self.subTest(d=direction):
                r=validated_plan({"price_source":"MT5_PRIMARY","entry":entry,"stop_loss":stop,"targets":targets,"entry_trigger":"x","invalidation":"y","management_rules":"z"},direction)
                self.assertIsNone(r["rr_gross"]); self.assertTrue(r["reason_codes"])
    def test_entry_plan_valid_gross(self):
        r=process(fixture())["setup"]["plan"]; self.assertEqual(r["rr_gross"],2.0); self.assertIsNone(r["rr_net"])
    def test_plan_partial_weights(self):
        p=fixture(); p["plan"]["partial_weights"]=[0.8,0.5]; r=process(p); self.assertIn("PARTIAL_WEIGHTS_NOT_SUM_ONE",r["setup"]["plan"]["reason_codes"])
    def test_plan_no_mt5_price(self):
        p=fixture(); p["plan"]["price_source"]="TRADINGVIEW_SUPPLEMENTAL"; self.assertIn("ENTRY_PRICE_MUST_BE_MT5",process(p)["setup"]["plan"]["reason_codes"])
    def test_zero_account_not_free(self):
        p=fixture(); p["account"]={"account_type":"ZERO_SPREAD","commission":None}; r=process(p); self.assertIsNone(r["setup"]["plan"]["rr_net"])
    def test_ttl_config_invalid(self):
        for ttl,aging in ((0,1),(10,11),(-1,1),(12,0),(1.2,1),(True,1)):
            with self.subTest(ttl=ttl,aging=aging):
                p=fixture(); p["config"]={"ttl_closed_bars":ttl,"aging_closed_bars":aging}
                with self.assertRaises(ValueError): process(p)
    def test_store_persistence(self):
        with tempfile.TemporaryDirectory() as d:
            path=os.path.join(d,"local.sqlite")
            db=SQLiteSetupStore(path); p=fixture(); p["events"]=[event("CORE_READY",1)]; a=db.apply(p); db.close()
            db=SQLiteSetupStore(path); b=db.apply(p); self.assertEqual(a["setup"]["revision"],b["setup"]["revision"]); self.assertEqual(db.db.execute("SELECT count(*) FROM audit").fetchone()[0],1); db.close()
    def test_store_two_updates(self):
        with tempfile.TemporaryDirectory() as d:
            db=SQLiteSetupStore(Path(d)/"state.sqlite"); p=fixture(); p["events"]=[event("CORE_READY",1)]; db.apply(p)
            p["events"]=[event("CORE_READY",1),event("DEVELOPMENT",2)]; x=db.apply(p); self.assertEqual(x["setup"]["state"],"SETUP_FORMING"); db.close()
    def test_store_reject_transaction(self):
        with tempfile.TemporaryDirectory() as d:
            db=SQLiteSetupStore(Path(d)/"state.sqlite"); p=fixture(); p["events"]=[event("CORE_READY",1)]; db.apply(p)
            p["events"]=[{**event("CORE_READY",1),"evidence_id":"changed"}]
            with self.assertRaises(ValueError): db.apply(p)
            self.assertEqual(db.db.execute("SELECT count(*) FROM audit").fetchone()[0],1); db.close()
    def test_timestamps_timezone_aware(self):
        self.assertEqual(ts("2026-10-08T12:00:00+02:00"),ts("2026-10-08T10:00:00Z"))
    def test_no_order_actions_for_all_states(self):
        for n in range(7):
            with self.subTest(n=n):
                p=fixture(); p["events"]=life_events()[:n]; r=process(p); self.assertEqual(r["order_actions"],[]); self.assertFalse(r["execution_eligible"])

    def test_simulated_partial_then_fill(self):
        p=fixture(); p["reference_mode"]="SIMULATION"
        p["events"]=life_events()+[event("PARTIAL_FILL",7,source="MT5_BROKER_EVENT",broker_deal_id="SYN-1"),event("FILL",8,source="MT5_BROKER_EVENT",broker_deal_id="SYN-2")]
        out=process(p); self.assertEqual(out["setup"]["state"],"ENTERED"); self.assertEqual(out["setup"]["order_state"],"FILLED"); self.assertEqual(len(out["setup"]["broker_fills"]),2)
    def test_duplicate_broker_deal(self):
        p=fixture(); p["reference_mode"]="SIMULATION"
        p["events"]=life_events()+[event("PARTIAL_FILL",7,source="MT5_BROKER_EVENT",broker_deal_id="SYN-1"),event("PARTIAL_FILL",8,source="MT5_BROKER_EVENT",broker_deal_id="SYN-1")]
        out=process(p); self.assertIn("BROKER_DEAL_ID_DUPLICATE",str(out["rejected_events"]))
    def test_unconfirmed_never_ready_to_trade(self):
        p=fixture(); p["events"]=life_events(); r=process(p); self.assertEqual(r["setup"]["entry_status"],"CONDITIONAL"); self.assertEqual(r["execution_permission"],"BLOCKED")
    def test_missing_costs_zero_profile(self):
        p=fixture(); p["account"]={"account_type":"ZERO_SPREAD","costs_verified_from_mt5":False}
        self.assertIn("ZERO_ACCOUNT_COSTS_NOT_VERIFIED",process(p)["execution_blockers"])
    def test_quote_bid_ask_side(self):
        for direction,bid,ask,entry,expected in (("LONG",2990,3002,3000,True),("SHORT",2999.5,3010,3000,False)):
            with self.subTest(direction=direction):
                p=fixture(); p["setup"]["direction"]=direction
                p["plan"]["stop_loss"]=2990 if direction=="LONG" else 3010
                p["plan"]["targets"]=[3020] if direction=="LONG" else [2980]
                p["plan"]["partial_weights"]=[1]
                p["data_snapshot"]["quote"]={"source":"MT5_PRIMARY","evidence_status":"VERIFIED","bid":bid,"ask":ask,"available_at":dt()}
                p["config"]["max_entry_distance_abs"]=1
                r=process(p)
                self.assertEqual("ANTI_FOMO_WAIT_FOR_RETEST" in r["execution_blockers"],expected)
    def test_tv_execution_quote_refused(self):
        p=fixture(); p["data_snapshot"]["quote"]={"source":"TRADINGVIEW_SUPPLEMENTAL","evidence_status":"VERIFIED","bid":3000,"ask":3000,"available_at":dt()}
        self.assertIn("MT5_QUOTE_UNVERIFIED_OR_UNAVAILABLE",process(p)["execution_blockers"])
    def test_zero_spread_quote_is_valid(self):
        p=fixture(); p["data_snapshot"]["quote"]={"source":"MT5_PRIMARY","evidence_status":"VERIFIED","bid":3000,"ask":3000,"available_at":dt()}
        self.assertNotIn("MT5_QUOTE_UNVERIFIED_OR_UNAVAILABLE",process(p)["execution_blockers"])
    def test_invalid_negative_spread(self):
        p=fixture(); p["data_snapshot"]["quote"]={"source":"MT5_PRIMARY","evidence_status":"VERIFIED","bid":3001,"ask":3000,"available_at":dt()}
        self.assertIn("MT5_QUOTE_UNVERIFIED_OR_UNAVAILABLE",process(p)["execution_blockers"])
    def test_future_quote_unavailable(self):
        p=fixture(); p["data_snapshot"]["quote"]={"source":"MT5_PRIMARY","evidence_status":"VERIFIED","bid":3000,"ask":3000,"available_at":dt(1)}
        self.assertIn("MT5_QUOTE_UNVERIFIED_OR_UNAVAILABLE",process(p)["execution_blockers"])
    def test_router_spec_mismatch(self):
        for fld,val in (("version","9.9.9"),("strategy_id","XAU-S20"),("spec_hash","bad"),("horizon_id","H1:10")):
            with self.subTest(fld=fld):
                p=fixture(); p["router_result"]["analysis_pool"][0][fld]=val; p["events"]=[event("CORE_READY")]
                self.assertEqual(process(p)["setup"]["state"],"CANDIDATE")
    def test_closed_bar_not_before_period_end(self):
        p=fixture(); p["as_of"]=dt(7); p["data_snapshot"]["as_of"]=dt(7)
        p["events"]=[event("CLOSED_BAR",1,bar_state="CLOSED",timeframe="M5",bar_open_utc=dt(),close_confirmed_at=dt(3),available_at=dt(6))]
        self.assertIn("CANDLE_LIFECYCLE_INCONSISTENT",str(process(p)["rejected_events"]))
    def test_closed_bar_confirmation_late_availability(self):
        p=fixture(); p["as_of"]=dt(7); p["data_snapshot"]["as_of"]=dt(7)
        p["events"]=[event("CLOSED_BAR",1,bar_state="CLOSED",timeframe="M5",bar_open_utc=dt(),close_confirmed_at=dt(6),available_at=dt(5))]
        self.assertEqual(process(p)["setup"]["closed_bars_elapsed"],0)
    def test_confirmation_cross_reference_required(self):
        p=fixture(); p["events"]=life_events()[:5]+[event("CONFIRM",6,confirmation_gates={"x":"PASS"},distinct_confirmation=True,ref_trigger_event_id="WRONG")]
        self.assertEqual(process(p)["setup"]["state"],"TRIGGERED")
    def test_alert_not_sent(self):
        p=fixture(); p["events"]=life_events(); r=process(p); self.assertEqual(r["alert_emission"],"NOT_SENT"); self.assertTrue(r["signal_dedupe_key"])

    def test_quote_age_stale(self):
        p=fixture(); p["as_of"]=dt(1); p["data_snapshot"]["as_of"]=dt(1)
        p["data_snapshot"]["quote"]={"source":"MT5_PRIMARY","evidence_status":"VERIFIED","bid":3000,"ask":3000,"available_at":dt()}
        self.assertIn("MT5_QUOTE_UNVERIFIED_OR_UNAVAILABLE",process(p)["execution_blockers"])
    def test_quote_age_policy_missing(self):
        p=fixture(); p["config"].pop("max_quote_age_seconds")
        p["data_snapshot"]["quote"]={"source":"MT5_PRIMARY","evidence_status":"VERIFIED","bid":3000,"ask":3000,"available_at":dt()}
        r=process(p); self.assertIn("QUOTE_FRESHNESS_POLICY_MISSING",r["execution_blockers"])
    def test_quote_too_future(self):
        p=fixture(); p["data_snapshot"]["quote"]={"source":"MT5_PRIMARY","evidence_status":"VERIFIED","bid":3000,"ask":3000,"available_at":dt(1)}
        self.assertIn("MT5_QUOTE_UNVERIFIED_OR_UNAVAILABLE",process(p)["execution_blockers"])
    def test_required_confirmation_gates_all(self):
        required={"data":"PASS","trigger":"PASS","invalidation":"PASS","expiry":"PASS","conflict":"PASS"}
        for missing in required:
            with self.subTest(missing=missing):
                p=fixture(); e=event("CONFIRM",6,confirmation_gates={k:v for k,v in required.items() if k != missing},distinct_confirmation=True,ref_trigger_event_id="e-5-TRIGGER")
                p["events"]=life_events()[:5]+[e]
                self.assertEqual(process(p)["setup"]["state"],"TRIGGERED")
    def test_daily_bar_requires_broker_calendar(self):
        p=fixture(); p["setup"]["setup_tf"]="D1"; p["as_of"]=dt(61*24); p["data_snapshot"]["as_of"]=p["as_of"]
        p["events"]=[event("CLOSED_BAR",1,timeframe="D1",bar_state="CLOSED",bar_open_utc=dt(),close_confirmed_at=dt(60*24),available_at=dt(60*24))]
        self.assertIn("DAILY_BAR_CALENDAR_REQUIRED",str(process(p)["rejected_events"]))
    def test_daily_bar_23h_broker_day(self):
        p=fixture(); p["setup"]["setup_tf"]="D1"; p["as_of"]=dt(23*60+1); p["data_snapshot"]["as_of"]=p["as_of"]
        p["events"]=[event("CLOSED_BAR",1,timeframe="D1",bar_state="CLOSED",bar_open_utc=dt(),bar_expected_close_utc=dt(23*60),close_confirmed_at=dt(23*60),available_at=dt(23*60))]
        self.assertEqual(process(p)["setup"]["closed_bars_elapsed"],1)

if __name__ == '__main__': unittest.main()
