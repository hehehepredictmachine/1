"""Synthetic contract tests; not a market backtest or MT5 integration test."""
import copy
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
from M09_REFERENCE_ROUTER import run, utc, mode_allowed, CATALOG, POLICY, CORE

T = "2026-10-08T10:00:00Z"
SNAP = "MT5-SYNTH-0001"
SYM = "XAUUSD.DEMO"

def ev(i, source="MT5_PRIMARY", status="VERIFIED"):
    return {"evidence_id": i, "available_at": T, "snapshot_id": SNAP, "instrument_id": SYM,
            "evidence_status": status, "source": source, "category":"STRUCTURE"}

def setup(strategy_id="XAU-S02", setup_id="S1", direction="LONG", stage="EARLY_SETUP", h="M5:10"):
    return {"setup_id":setup_id,"strategy_id":strategy_id,"version":"0.1.0",
            "instrument_id":SYM,"snapshot_id":SNAP,"available_at":T,"direction":direction,
            "stage":stage,"horizon_id":h,"evidence_status":"VERIFIED",
            "underlying_event_id":setup_id,"poi_id":"p1", "spec_hash":"f"*64,
            "core_evidence": {k:ev(setup_id+":"+k) for k in CORE},
            "next_expected_event":{"criterion":"M5 closed close above level", "timeframe":"M5"},
            "invalidation":{"rule":"M5 close below structural level", "timeframe":"M5","rule_id":"invalid-1"},
            "trap_risk":"LOW"}

def payload(*setups, mode="AUTO"):
    return {"schema_version":"2.0.0", "analysis_id":"SYNTHETIC_NOT_LIVE", "as_of":T,"config_version":"TEST",
            "mode":mode, "execution_environment":"ANALYSIS_ONLY", "account":{"account_type":"ZERO_SPREAD",
            "costs_verified_from_mt5":False},
            "data_snapshot":{"snapshot_id":SNAP,"as_of":T,"instrument_id":SYM,
                "data_source_policy":POLICY,"visual_capture_enabled":False,"source_health":"PRIMARY_OK",
                "analysis_gate":{"status":"PASS"},"execution_gate":{"status":"PENDING"}},
            "market_state":{"snapshot_id":SNAP,"as_of":T,"instrument_id":SYM,"status":"PASS",
                            "structure_regime":"TREND_UP"},
            "runtime":{"status":"HEALTHY"}, "mode_profiles":{},"registry_snapshots":[],
            "config":{"registry_max_age_seconds":30,"execution_policy_version":"test-only"},
            "setups":list(setups)}

def reg(s, status="LIVE_ACTIVE"):
    return {"module_id":"M08", "schema_version":"2.0.0", "source_policy":POLICY, "run_status":"COMPLETED", "as_of":T,"strategy_id":s["strategy_id"],
            "version":s["version"], "spec_hash":s["spec_hash"],"spec_status":"FROZEN",
            "registry_revision":2,"registry_integrity":"PASS","strategy_status":status,
            "edge_health":"HEALTHY", "portfolio_group":"CORE", "m09_live_pool_candidate":True,
            "evidence_gate":{"status":"PASS", "reason_codes":[], "missing_phases":[]},
            "execution_permission":"BLOCKED","live_execution_allowed":False}

def add_live_requirements(p, s):
    p["execution_environment"]="LIVE"
    p["runtime"]["status"]="HEALTHY"
    p["data_snapshot"]["execution_gate"]["status"]="PASS"
    p["data_snapshot"]["quote"]={"source":"MT5_PRIMARY","verified":True,"bid":2600.0,"ask":2600.0}
    p["account"]["costs_verified_from_mt5"]=True
    p["registry_snapshots"]=[reg(s)]
    p["strategy_specs"]={s["strategy_id"]:{"strategy_id":s["strategy_id"],"version":s["version"],
         "spec_hash":s["spec_hash"],"spec_status":"FROZEN",
         "required_regimes":[],"forbidden_regimes":[],"allowed_sessions":[]}}
    p["portfolio_snapshot"]={"source":"MT5_PRIMARY","verified":True,"as_of":T,
          "positions":[],"pending_orders":[]}
    p["config"]["portfolio_max_age_seconds"]=30
    return p

class RouterTest(unittest.TestCase):
    def assertBlocked(self, out):
        self.assertEqual(out["execution_permission"],"BLOCKED")
        self.assertFalse(out["execution_eligible"])
        self.assertFalse(out["live_execution_allowed"])
        self.assertIsNone(out["submitted_order_id"])
        self.assertEqual(out["order_actions"], [])
        self.assertFalse(out["registry_write"])

    def test_01_clean_early(self):
        r=run(payload(setup()))
        self.assertEqual(r["top_early_setup_id"],"S1")
        self.assertEqual(r["analysis_router_state"],"EARLY_SETUP")
        self.assertBlocked(r)
    def test_02_no_setup(self):
        r=run(payload());self.assertEqual(r["analysis_router_state"],"NO_VALID_SETUP")
    def test_03_research_does_not_execute(self):
        r=run(payload(setup())); self.assertFalse(r["execution_pool"][0]["preliminary_eligible_for_downstream"])
    def test_04_mvp_unconfigured(self):
        r=run(payload(setup(),mode="MVP")); self.assertEqual(r["mode_status"],"NOT_CONFIGURED")
    def test_05_mvp_map(self):
        p=payload(setup(),mode="MVP");p["mode_profiles"]["MVP"]={"approved_mapping":True,"strategy_ids":["XAU-S02"]}
        self.assertEqual(run(p)["top_early_setup_id"],"S1")
    def test_06_mvp_wrong_mapping(self):
        p=payload(setup(),mode="MVP");p["mode_profiles"]["MVP"]={"approved_mapping":True,"strategy_ids":["XAU-S01"]}
        self.assertIsNone(run(p)["top_early_setup_id"])
    def test_07_smc_filters_non_smc(self):
        self.assertIsNone(run(payload(setup("XAU-S03"),mode="SMC"))["top_early_setup_id"])
    def test_08_scalp_allows_breakout(self):
        self.assertEqual(run(payload(setup("XAU-S03"),mode="SCALPING"))["top_early_setup_id"],"S1")
    def test_09_catalog_size(self):
        self.assertEqual(len(CATALOG),20)
    def test_10_catalog_no_registry_rights(self):
        self.assertBlocked(run(payload(setup())))
    def test_11_invalid_mode(self):
        with self.assertRaisesRegex(ValueError,"MODE_INVALID"):run(payload(setup(),mode="SUPER"))
    def test_12_invalid_asof(self):
        p=payload(setup());p["as_of"]="oops"
        with self.assertRaisesRegex(ValueError,"TIMESTAMP_INVALID"):run(p)
    def test_13_timezone_required(self):
        with self.assertRaisesRegex(ValueError,"TIMESTAMP_NAIVE"):utc("2026-10-08T10:00:00")
    def test_14_snapshot_id_mismatch(self):
        p=payload(setup());p["market_state"]["snapshot_id"]="OTHER"
        self.assertIsNone(run(p)["top_early_setup_id"])
    def test_15_snap_asof_mismatch(self):
        p=payload(setup());p["data_snapshot"]["as_of"]="2026-10-08T09:00:00Z"
        self.assertIsNone(run(p)["top_early_setup_id"])
    def test_16_market_not_pass(self):
        p=payload(setup());p["market_state"]["status"]="FAIL"
        self.assertIsNone(run(p)["top_early_setup_id"])
    def test_17_analysis_data_not_pass(self):
        p=payload(setup());p["data_snapshot"]["analysis_gate"]["status"]="FAIL"
        self.assertIsNone(run(p)["top_early_setup_id"])
    def test_18_future_setup(self):
        x=setup();x["available_at"]="2026-10-08T10:01:00Z"
        self.assertIsNone(run(payload(x))["top_early_setup_id"])
    def test_19_future_core(self):
        x=setup();x["core_evidence"]["liquidity_context"]["available_at"]="2026-10-08T10:01:00Z"
        self.assertIsNone(run(payload(x))["top_early_setup_id"])
    def test_20_missing_core(self):
        x=setup();del x["core_evidence"]["meaningful_location"]
        self.assertIsNone(run(payload(x))["top_early_setup_id"])
    def test_21_core_duplicate(self):
        x=setup();x["core_evidence"]["meaningful_location"]["evidence_id"]=x["core_evidence"]["liquidity_context"]["evidence_id"]
        self.assertIsNone(run(payload(x))["top_early_setup_id"])
    def test_22_open_bar_core(self):
        x=setup();x["core_evidence"]["structural_advantage"].update({"requires_closed_bar":True,"bar_state":"FORMING"})
        self.assertIsNone(run(payload(x))["top_early_setup_id"])
    def test_23_missing_next_event(self):
        x=setup();x["next_expected_event"]={}
        self.assertIsNone(run(payload(x))["top_early_setup_id"])
    def test_24_missing_invalidation(self):
        x=setup();x["invalidation"]={}
        self.assertIsNone(run(payload(x))["top_early_setup_id"])
    def test_25_already_invalidated(self):
        x=setup();x["invalidation_observed"]=True
        self.assertIsNone(run(payload(x))["top_early_setup_id"])
    def test_26_expired(self):
        x=setup();x["expires_at"]=T
        self.assertIsNone(run(payload(x))["top_early_setup_id"])
    def test_27_future_expiry_allowed(self):
        x=setup();x["expires_at"]="2026-10-08T10:05:00Z"
        self.assertEqual(run(payload(x))["top_early_setup_id"],"S1")
    def test_28_terminal_stage(self):
        x=setup();x["stage"]="ENTERED"
        self.assertIsNone(run(payload(x))["top_early_setup_id"])
    def test_29_intrabar_not_confirmed(self):
        x=setup(stage="CONFIRMED");x["trigger_confirmed"]=True
        self.assertIsNone(run(payload(x))["top_confirmed_setup_id"])
    def test_30_valid_confirmed(self):
        x=setup(stage="CONFIRMED");x["trigger_confirmed"]=True;x["confirmation_evidence"]=ev("con1")
        self.assertEqual(run(payload(x))["top_confirmed_setup_id"],"S1")
    def test_31_invalid_confirmation_future(self):
        x=setup(stage="CONFIRMED");x["trigger_confirmed"]=True;x["confirmation_evidence"]=ev("con1")
        x["confirmation_evidence"]["available_at"]="2026-10-08T10:01:00Z"
        self.assertIsNone(run(payload(x))["top_confirmed_setup_id"])
    def test_32_duplicate_group_tie(self):
        a,b=setup(setup_id="S1"),setup(setup_id="S2")
        a["underlying_event_id"]=b["underlying_event_id"]="E_SHARED"
        r=run(payload(a,b)); self.assertIsNone(r["top_early_setup_id"])
        self.assertTrue(r["duplicate_groups"][0]["tie"])
    def test_33_duplicate_group_maturity_primary(self):
        a,b=setup(setup_id="S1"),setup(setup_id="S2",stage="SETUP_FORMING")
        a["underlying_event_id"]=b["underlying_event_id"]="E_SHARED"
        r=run(payload(a,b)); self.assertEqual(r["top_early_setup_id"],"S2")
    def test_34_duplicate_id(self):
        a,b=setup(setup_id="S1"),setup(setup_id="S1")
        self.assertIsNone(run(payload(a,b))["top_early_setup_id"])
    def test_35_same_horizon_conflict(self):
        a,b=setup(setup_id="S1"),setup(setup_id="S2",direction="SHORT")
        r=run(payload(a,b));self.assertTrue(r["horizon_conflicts"])
        self.assertIsNone(r["top_early_setup_id"])
    def test_36_htf_ltf_correction_no_conflict(self):
        a,b=setup(setup_id="S1",h="H4:10"),setup(setup_id="S2",direction="SHORT",h="M5:10")
        r=run(payload(a,b));self.assertFalse(r["horizon_conflicts"])
    def test_37_unrelated_third_cannot_override_horizon_conflict(self):
        a,b,c=setup(setup_id="S1"),setup(setup_id="S2",direction="SHORT"),setup(setup_id="S3",stage="QUALIFIED")
        r=run(payload(a,b,c));self.assertIsNone(r["top_conditional_setup_id"])
    def test_38_top_tie_not_arbitrarily_winner(self):
        a,b=setup(setup_id="S1"),setup(setup_id="S2")
        r=run(payload(a,b));self.assertIsNone(r["top_early_setup_id"])
        self.assertEqual(r["top_reasons"]["early"],"TOP_RANK_TIE")
    def test_39_future_reg_rejected(self):
        x=setup(stage="CONFIRMED");x["trigger_confirmed"]=True;x["confirmation_evidence"]=ev("con")
        p=add_live_requirements(payload(x),x)
        p["registry_snapshots"][0]["as_of"]="2026-10-08T10:02:00Z"
        self.assertIn("REGISTRY_STALE_OR_FUTURE",run(p)["execution_pool"][0]["reason_codes"])
    def test_40_registry_hash_mismatch(self):
        x=setup(stage="CONFIRMED");x["trigger_confirmed"]=True;x["confirmation_evidence"]=ev("con")
        p=add_live_requirements(payload(x),x);p["registry_snapshots"][0]["spec_hash"]="0"*64
        self.assertIn("REGISTRY_SPEC_HASH_MISMATCH",run(p)["execution_pool"][0]["reason_codes"])
    def test_41_registry_not_live(self):
        x=setup(stage="CONFIRMED");x["trigger_confirmed"]=True;x["confirmation_evidence"]=ev("con")
        p=add_live_requirements(payload(x),x);p["registry_snapshots"][0]["strategy_status"]="RESEARCH"
        self.assertIn("STRATEGY_NOT_LIVE_APPROVED",run(p)["execution_pool"][0]["reason_codes"])
    def test_42_m16_down(self):
        x=setup(stage="CONFIRMED");x["trigger_confirmed"]=True;x["confirmation_evidence"]=ev("con")
        p=add_live_requirements(payload(x),x);p["runtime"]["status"]="OFFLINE"
        self.assertIn("M16_NOT_HEALTHY",run(p)["execution_pool"][0]["reason_codes"])
    def test_43_m01_execution_fail(self):
        x=setup(stage="CONFIRMED");x["trigger_confirmed"]=True;x["confirmation_evidence"]=ev("con")
        p=add_live_requirements(payload(x),x);p["data_snapshot"]["execution_gate"]["status"]="FAIL"
        self.assertIn("M01_EXECUTION_GATE_NOT_PASS",run(p)["execution_pool"][0]["reason_codes"])
    def test_44_spread_zero_no_assumed_costs(self):
        x=setup(stage="CONFIRMED");x["trigger_confirmed"]=True;x["confirmation_evidence"]=ev("con")
        p=add_live_requirements(payload(x),x);p["account"]["costs_verified_from_mt5"]=False
        self.assertIn("ZERO_ACCOUNT_COSTS_NOT_VERIFIED",run(p)["execution_pool"][0]["reason_codes"])
    def test_45_negative_spread_bidask(self):
        x=setup(stage="CONFIRMED");x["trigger_confirmed"]=True;x["confirmation_evidence"]=ev("con")
        p=add_live_requirements(payload(x),x);p["data_snapshot"]["quote"]["bid"]=2602
        self.assertIn("MT5_QUOTE_INVALID",run(p)["execution_pool"][0]["reason_codes"])
    def test_46_tv_cannot_supply_execution_quote(self):
        x=setup(stage="CONFIRMED");x["trigger_confirmed"]=True;x["confirmation_evidence"]=ev("con")
        p=add_live_requirements(payload(x),x);p["data_snapshot"]["quote"]["source"]="TRADINGVIEW_SUPPLEMENTAL"
        self.assertIn("MT5_EXECUTION_QUOTE_NOT_VERIFIED",run(p)["execution_pool"][0]["reason_codes"])
    def test_47_tv_extra_evidence_allowed_when_missing_primary(self):
        x=setup();x["core_evidence"]["liquidity_context"].update({"source":"TRADINGVIEW_SUPPLEMENTAL","primary_field_missing":True,"category":"SUPPLEMENTAL_LIQUIDITY_CONTEXT"})
        self.assertEqual(run(payload(x))["top_early_setup_id"],"S1")
    def test_48_tv_broker_price_forbidden(self):
        x=setup();x["core_evidence"]["liquidity_context"].update({"source":"TRADINGVIEW_SUPPLEMENTAL","primary_field_missing":True,"category":"BROKER_QUOTE"})
        self.assertIsNone(run(payload(x))["top_early_setup_id"])
    def test_49_tv_not_gap(self):
        x=setup();x["core_evidence"]["liquidity_context"].update({"source":"TRADINGVIEW_SUPPLEMENTAL","category":"SUPPLEMENTAL_LIQUIDITY_CONTEXT"})
        self.assertIsNone(run(payload(x))["top_early_setup_id"])
    def test_50_screenshot_forbidden(self):
        p=payload(setup());p["data_snapshot"]["visual_capture_enabled"]=True
        self.assertIsNone(run(p)["top_early_setup_id"])
    def test_51_hidden_order_send_field_forbidden(self):
        p=payload(setup());p["nested"]={"order_send":True}
        self.assertIsNone(run(p)["top_early_setup_id"])
    def test_52_bad_source_policy(self):
        p=payload(setup());p["data_snapshot"]["data_source_policy"]="IMAGE_CAPTURE"
        self.assertIsNone(run(p)["top_early_setup_id"])
    def test_53_reg_no_risk_authorization(self):
        x=setup(stage="CONFIRMED");x["trigger_confirmed"]=True;x["confirmation_evidence"]=ev("con")
        p=add_live_requirements(payload(x),x)
        o=run(p)
        self.assertTrue(o["execution_pool"][0]["preliminary_eligible_for_downstream"])
        self.assertBlocked(o)
    def test_54_high_trap_blocks_execution_not_early(self):
        x=setup(stage="CONFIRMED");x["trigger_confirmed"]=True;x["confirmation_evidence"]=ev("con")
        x["trap_risk"]="HIGH";p=add_live_requirements(payload(x),x)
        o=run(p);self.assertEqual(o["top_confirmed_setup_id"],"S1")
        self.assertIn("TRAP_RISK_EXECUTION_BLOCK",o["execution_pool"][0]["reason_codes"])
    def test_55_no_probability_fiction(self):
        o=run(payload(setup()));self.assertIsNone(o["probabilities"])
    def test_56_source_immutability(self):
        p=payload(setup());clone=copy.deepcopy(p);run(p);self.assertEqual(p,clone)
    def test_57_deterministic(self):
        p=payload(setup());self.assertEqual(run(p),run(p))
    def test_58_serializable(self):
        json.dumps(run(payload(setup())),allow_nan=False)
    def test_59_core_evidence_non_dict_fails_gracefully(self):
        x=setup();x["core_evidence"]=[]
        self.assertIsNone(run(payload(x))["top_early_setup_id"])
    def test_60_duplicate_registry_versions_block(self):
        x=setup(stage="CONFIRMED");x["trigger_confirmed"]=True;x["confirmation_evidence"]=ev("con")
        p=add_live_requirements(payload(x),x);p["registry_snapshots"].append(copy.deepcopy(p["registry_snapshots"][0]))
        self.assertIn("DUPLICATE_REGISTRY_VERSION",run(p)["execution_pool"][0]["reason_codes"])
    def test_61_wrong_symbol(self):
        x=setup();x["instrument_id"]="XAUUSD_OTHER"
        self.assertIsNone(run(payload(x))["top_early_setup_id"])
    def test_62_no_tested_trigger_before_confirmation(self):
        x=setup(stage="TRIGGERED");x["trigger_confirmed"]=True
        o=run(payload(x));self.assertIsNone(o["top_confirmed_setup_id"])
    def test_63_paper_scope_no_live_rights(self):
        x=setup(stage="CONFIRMED");x["trigger_confirmed"]=True;x["confirmation_evidence"]=ev("con")
        p=add_live_requirements(payload(x),x);p["execution_environment"]="PAPER";p["demo_research_enabled"]=True
        self.assertBlocked(run(p))
    def test_64_empty_setup_not_automatic_neutral(self):
        o=run(payload());self.assertNotIn("NEUTRAL",json.dumps(o))
    def test_65_partial_valid_evidence(self):
        x=setup();x["core_evidence"]["meaningful_location"]["evidence_status"]="PARTIAL"
        self.assertEqual(run(payload(x))["top_early_setup_id"],"S1")
    def test_66_unknown_evidence_denied(self):
        x=setup();x["core_evidence"]["meaningful_location"]["evidence_status"]="UNKNOWN"
        self.assertIsNone(run(payload(x))["top_early_setup_id"])
    def test_67_m05_not_prerequisite_for_early(self):
        x=setup();self.assertEqual(run(payload(x))["top_early_setup_id"],"S1")
    def test_68_demo_no_approval_status_not_execute(self):
        x=setup(stage="CONFIRMED");x["trigger_confirmed"]=True;x["confirmation_evidence"]=ev("con")
        p=add_live_requirements(payload(x),x);p["execution_environment"]="DEMO";p["demo_research_enabled"]=True
        p["registry_snapshots"][0]["strategy_status"]="RESEARCH"
        self.assertIn("DEMO_STRATEGY_STATUS_NOT_ALLOWED",run(p)["execution_pool"][0]["reason_codes"])
    def test_69_short_not_automatically_long(self):
        x=setup(direction="SHORT");o=run(payload(x))
        self.assertEqual(o["analysis_pool"][0]["direction"],"SHORT")
    def test_70_top_early_not_champion_live(self):
        o=run(payload(setup()));self.assertIsNone(o["deployed_champion_version"])

    def test_71_no_strategy_spec_prevents_downstream(self):
        x=setup(stage="CONFIRMED");x["trigger_confirmed"]=True;x["confirmation_evidence"]=ev("con")
        p=add_live_requirements(payload(x),x);p["strategy_specs"]={}
        self.assertIn("M07_STRATEGY_SPEC_UNAVAILABLE",run(p)["execution_pool"][0]["reason_codes"])
    def test_72_required_regime_fail(self):
        x=setup(stage="CONFIRMED");x["trigger_confirmed"]=True;x["confirmation_evidence"]=ev("con")
        p=add_live_requirements(payload(x),x)
        p["strategy_specs"][x["strategy_id"]]["required_regimes"]=["RANGE"]
        self.assertIn("REQUIRED_REGIME_NOT_MET",run(p)["execution_pool"][0]["reason_codes"])
    def test_73_forbidden_regime_fail(self):
        x=setup(stage="CONFIRMED");x["trigger_confirmed"]=True;x["confirmation_evidence"]=ev("con")
        p=add_live_requirements(payload(x),x)
        p["strategy_specs"][x["strategy_id"]]["forbidden_regimes"]=["TREND_UP"]
        self.assertIn("FORBIDDEN_REGIME",run(p)["execution_pool"][0]["reason_codes"])
    def test_74_required_regime_pass(self):
        x=setup(stage="CONFIRMED");x["trigger_confirmed"]=True;x["confirmation_evidence"]=ev("con")
        p=add_live_requirements(payload(x),x)
        p["strategy_specs"][x["strategy_id"]]["required_regimes"]=["TREND_UP"]
        self.assertTrue(run(p)["execution_pool"][0]["preliminary_eligible_for_downstream"])
    def test_75_session_filter_fail(self):
        x=setup(stage="CONFIRMED");x["trigger_confirmed"]=True;x["confirmation_evidence"]=ev("con")
        p=add_live_requirements(payload(x),x)
        p["strategy_specs"][x["strategy_id"]]["allowed_sessions"]=["LONDON"]
        p["context"]={"session":"ASIA"}
        self.assertIn("SESSION_NOT_ALLOWED_OR_UNKNOWN",run(p)["execution_pool"][0]["reason_codes"])
    def test_76_session_filter_pass(self):
        x=setup(stage="CONFIRMED");x["trigger_confirmed"]=True;x["confirmation_evidence"]=ev("con")
        p=add_live_requirements(payload(x),x)
        p["strategy_specs"][x["strategy_id"]]["allowed_sessions"]=["LONDON"]
        p["context"]={"session":"LONDON"}
        self.assertTrue(run(p)["execution_pool"][0]["preliminary_eligible_for_downstream"])
    def test_77_extreme_macro_risk_blocks_execution(self):
        x=setup(stage="CONFIRMED");x["trigger_confirmed"]=True;x["confirmation_evidence"]=ev("con")
        p=add_live_requirements(payload(x),x);p["context"]={"event_risk":"EXTREME"}
        self.assertIn("EXTREME_EVENT_RISK",run(p)["execution_pool"][0]["reason_codes"])
    def test_78_no_portfolio_snapshot(self):
        x=setup(stage="CONFIRMED");x["trigger_confirmed"]=True;x["confirmation_evidence"]=ev("con")
        p=add_live_requirements(payload(x),x);p.pop("portfolio_snapshot")
        self.assertIn("MT5_PORTFOLIO_SNAPSHOT_MISSING",run(p)["execution_pool"][0]["reason_codes"])
    def test_79_untrusted_portfolio_snapshot(self):
        x=setup(stage="CONFIRMED");x["trigger_confirmed"]=True;x["confirmation_evidence"]=ev("con")
        p=add_live_requirements(payload(x),x);p["portfolio_snapshot"]["source"]="TRADINGVIEW_SUPPLEMENTAL"
        self.assertIn("MT5_PORTFOLIO_NOT_VERIFIED",run(p)["execution_pool"][0]["reason_codes"])
    def test_80_broker_portfolio_stale(self):
        x=setup(stage="CONFIRMED");x["trigger_confirmed"]=True;x["confirmation_evidence"]=ev("con")
        p=add_live_requirements(payload(x),x);p["portfolio_snapshot"]["as_of"]="2026-10-08T09:00:00Z"
        self.assertIn("MT5_PORTFOLIO_SNAPSHOT_STALE",run(p)["execution_pool"][0]["reason_codes"])
    def test_81_paused_strategy_never_analytical_early(self):
        x=setup();p=payload(x);p["registry_snapshots"]=[reg(x,"PAUSED")]
        self.assertIsNone(run(p)["top_early_setup_id"])
    def test_82_without_registry_research_early_remains(self):
        self.assertEqual(run(payload(setup()))["top_early_setup_id"],"S1")
    def test_83_zero_spread_with_commission_still_blocked(self):
        x=setup(stage="CONFIRMED");x["trigger_confirmed"]=True;x["confirmation_evidence"]=ev("con")
        p=add_live_requirements(payload(x),x)
        out=run(p);self.assertBlocked(out)
    def test_84_volatility_forbidden(self):
        x=setup(stage="CONFIRMED");x["trigger_confirmed"]=True;x["confirmation_evidence"]=ev("con")
        p=add_live_requirements(payload(x),x)
        p["market_state"]["volatility_level"]="EXTREME"
        p["strategy_specs"][x["strategy_id"]]["forbidden_volatility_levels"]=["EXTREME"]
        self.assertIn("VOLATILITY_FORBIDDEN",run(p)["execution_pool"][0]["reason_codes"])
    def test_85_conflicted_market_scope_not_user_override(self):
        a,b=setup(setup_id="S1"),setup(setup_id="S2",direction="SHORT")
        a["market_scope"]="A";b["market_scope"]="B"
        self.assertTrue(run(payload(a,b))["horizon_conflicts"])

    def test_86_missing_m08_run_status_block(self):
        x=setup(stage="CONFIRMED");x["trigger_confirmed"]=True;x["confirmation_evidence"]=ev("con")
        p=add_live_requirements(payload(x),x);p["registry_snapshots"][0]["run_status"]="NOT_RUN"
        self.assertIn("M08_NOT_COMPLETED",run(p)["execution_pool"][0]["reason_codes"])
    def test_87_wrong_m08_source_policy_block(self):
        x=setup(stage="CONFIRMED");x["trigger_confirmed"]=True;x["confirmation_evidence"]=ev("con")
        p=add_live_requirements(payload(x),x);p["registry_snapshots"][0]["source_policy"]="OTHER"
        self.assertIn("M08_SOURCE_POLICY_MISMATCH",run(p)["execution_pool"][0]["reason_codes"])
    def test_88_mandatory_calendar_missing(self):
        x=setup(stage="CONFIRMED");x["trigger_confirmed"]=True;x["confirmation_evidence"]=ev("con")
        p=add_live_requirements(payload(x),x);p["config"]["event_policy_requires_calendar"]=True
        self.assertIn("EVENT_CALENDAR_NOT_VERIFIED",run(p)["execution_pool"][0]["reason_codes"])
    def test_89_spec_calendar_missing(self):
        x=setup(stage="CONFIRMED");x["trigger_confirmed"]=True;x["confirmation_evidence"]=ev("con")
        p=add_live_requirements(payload(x),x);p["strategy_specs"][x["strategy_id"]]["require_economic_calendar"]=True
        self.assertIn("REQUIRED_ECONOMIC_CALENDAR_NOT_VERIFIED",run(p)["execution_pool"][0]["reason_codes"])

if __name__ == "__main__":
    unittest.main(verbosity=2)
