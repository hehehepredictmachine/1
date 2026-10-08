# M07/M03E operational integration contract

**Exports:** `discover(audited_m01_snapshot, market_state_m02, market_evidence_m03, mode, config) -> dict` and `ResearchPlanLock.choose(...) -> (plan|None, diagnostics)`; downstream `M03E_M10_PIPELINE.analyze_snapshot(...strategy_plan=plan...)` and original `M10_AUTO_TRIGGER_CONFIRM.advance`; `M14` alone produces analytical direction; original `M15` serializes and optionally notifies.

Required shared keys: `schema_version=2.0.0`, same `snapshot_id`, same UTC `as_of` (ISO formats may differ), `instrument_id=XAUUSD`, broker-specific `exact_symbol`, `visual_capture_enabled=false`, `data_source_policy=MT5_PRIMARY_TV_SUPPLEMENTAL_NO_SCREENSHOTS`, `analysis_gate.status PASS/PASS_WITH_LIMITATIONS` and time-confirmed M03 evidence. All source input evidence must satisfy point-in-time availability.

`selected_plan` is generated programmatically only for a present FVG, its direction and location, an existing liquidity level/sweep and the appropriate structure/momentum validation. It includes `strategy_id`, `version=1.0.0-RESEARCH`, `research_profile_hash`, `frozen_plan_hash`, `setup_tf`, `horizon_id`, `created_event_id`, three real market evidence IDs, `next_expected_event`, `invalidation` and four different `lifecycle_rules` with numeric levels and source evidence anchors. `spec_hash` is a **hash of the research rule generator/template**, not an M08 authorization or independently signed M07 production spec.

`MVP` is an explicit, provisional trend-pullback strategy, not an unknown historical definition. SMC supports a subset of the broad XAU-S14 family; it is not a full universal SMC engine. Scalping supports a subset of XAU-S06. All other XAU-S01–S20 strategies remain unchanged and unvalidated.

Selection identity is locked separately per `(broker_symbol, mode)` in `OP_RESEARCH_LOCK.sqlite` with integrity hash. The old plan is reusable only while source/phase/POI references and structural advantage still pass; a mitigated or invalidated FVG cannot create a fresh stop rule from the same event. M10A independently checks frozen policy hash and the new closed-bar key to prevent duplicate confirmation.

Adapter contract preserves `ANALYSIS_ONLY`; creates no orders, `execution_permission=BLOCKED`, `live_execution_allowed=false`, `broker_order_sent=false`, `submitted_order_id=null`, account_type ZERO_SPREAD_DECLARED_UNVERIFIED. Reconnecting after a gap does not replay unknown bars as historical confirmations.

**Known scope limitation:** only one chosen research plan is passed through M10/M15 per evaluation. The `AUTO_priority` is deterministic and **does not** evaluate a full live portfolio. Other candidate patterns may be included as supporting diagnostics, not concurrent orders.

**No automatic SL/TP fill model or broker account verification:** levels are provisional observation thresholds, not execution prices. M06 validation and forward MT5 DEMO remain required prior to even considering registry promotion.
