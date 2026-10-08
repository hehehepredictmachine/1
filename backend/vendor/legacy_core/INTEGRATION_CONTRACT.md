# MasterQUO M01 audit → M03E → M10 · contract 1.0.0-CANDIDATE

## Scope
- Read-only, local Windows Python/MetaTrader5; MT5 primary; TradingView **not** used for broker quotes or fills; no screenshots/OCR.
- `schema_version=2.0.0`, `prompt_version=4.1.0`, declared `ZERO_SPREAD` profile, **real costs not verified**. No `order_send`, position management, alerts or autotrading.
- Existing M01/M02/M02I/M03/M09/M10/M14 source files are vendored **without changes**. This adapter adds M01 local integrity checks, M03E evidence mapping, M10 persistence and monitor JSON.

## M01 local audit
- Only after *direct collection through an active local MT5 read-only monitor* may `collected_directly=True` be passed by the runner. This is a code-level assertion, **not cryptographic broker attestation**. External JSON cannot certify itself through the provided CLI.
- Require MT5 BID closed candles, exact broker symbol, six timeframes D1/H4/H1/M15/M5/M1, timestamps with offset, `close_confirmed_at <= available_at <= as_of`, positive OHLC geometry, nonnegative tick volume, sufficient bars and monotonic unique opens.
- Runtime freshness: quote (default audit ≤5 s), snapshot (≤15 s), latest closed candle per TF, conservative unresolved gap detection for last 14 intraday bars. Session calendar is **not** fully reconciled; broker closures or DST gaps become PENDING, never synthetic bars.
- `PASS_WITH_LIMITATIONS` enables descriptive research analysis only. Critical corruption => FAIL; missing history/freshness/session coverage => PENDING. Execution gate ALWAYS PENDING.
- The prior preview observer writes `MT5_READONLY_PREVIEW_UNVERIFIED`; this local auditor is supplementary, not an independent feed provenance certification. No claim of production-grade M01 until broker calendar, revision and history coverage are validated.

## M03E
- M03E is owned by M03 `early_assessment`; `EARLY_SETUP` requires all five CORE: STRUCTURAL_ADVANTAGE, MEANINGFUL_LOCATION, LIQUIDITY_CONTEXT, DEVELOPMENT_PATH, KNOWN_INVALIDATION.
- Strategy research plan MUST come from M07 frozen rules and explicitly reference *actual* M02/M03 structure evidence and M03 FVG/OB and LEVEL/SWEEP evidence IDs in the current validated snapshot.
- Every core has a unique ID, source, snapshot, available_at, verified local basis. `development_path` and `known_invalidation` are rules anchored to a real bar, not future triggers.
- `STRATEGY_PLAN.example.json` is NOT an approved strategy; all placeholders intentionally result in CANDIDATE / WAIT. M07/M06/M08 approvals are NOT bypassed.
- Indicators M02I are context only; RSI/EMA/MACD alone never satisfy core.

## M09 / M14
- Same immutable `snapshot_id` and `as_of`; M09 controls research eligibility, M14 one analytical decision. The entire execution path is always `BLOCKED`, even if a descriptive EARLY_SETUP exists.

## M10
- Only an M09-selected, M03E qualified candidate enters SQLite via *unmodified* `M10_REFERENCE_ENGINE.SQLiteSetupStore`.
- Stable setup ID: SHA-256 of broker symbol, strategy identity/version/spec_hash/horizon, location/liquidity and independent created-event ID.
- Automatic transition only `CANDIDATE → EARLY_SETUP` from `CORE_READY`; verified new `CLOSED_BAR` events update TTL/aging. No automatic QUALIFY/ARM/TRIGGER/CONFIRM; future event-specific detectors and M06 validation remain missing.
- `HEALTHY` passed to M10 refers to *local read-only transport health* confirmed by live collection and M01 local audit, NOT deployed M16 execution/runtime authorization. M10's execution hard gates remain permanently blocked.
- SQLite restart retains known events and states; same event replays are deduplicated. Terminal/rejected records are not resurrected.
- On disconnection/quote stale/critical audit failure, monitor changes to `NO_TRADE/BLOCKED`; archived SQLite state remains for postmortem only.

## API and outputs
- `M01_AUDIT.audit(snapshot, quote, collected_directly=..., connected=..., now=...) -> audited_snapshot`
- `M03E_M10_PIPELINE.analyze_snapshot(snapshot, quote, *, direct_mt5, connected, strategy_plan, db_path, runtime_clock, read_only_runtime_healthy) -> report`
- `RUN_MT5_READONLY_SIGNAL_LIFECYCLE.py --symbol ... [--dxy-symbol ...] [--strategy-plan ...]`
- Output JSON `runtime/MASTERQUO_M03E_M10_MONITOR.json`, raw diagnostic `runtime/MT5_RAW_DIAGNOSTIC.json`, SQLite `runtime/M10_STATE.sqlite`.
- Output fields: `data_audit`, `market_state`, `indicator_intelligence`, `market_evidence`, `router_result`, `decision_result`, `m10_result`, `strategy_setup_id`, `setup_state`, `analysis_decision`, `reason_codes`, and fixed `execution_permission=BLOCKED`, `live_execution_allowed=false`, `submitted_order_id=null`.

## Acceptance criteria before any future live order execution
1. Verified exact MT5 broker symbol/account + authenticated feed provenance and market calendar gap reconciliation.
2. Independent M06 OOS, walk-forward, realistic zero-spread-account commission/slippage and MT5 DEMO forward testing.
3. Real M08 approved strategy version, M10 confirmed executable trigger and lifecycle, M11 risk approval.
4. Deployed, authenticated M14 authorization and trusted broker reconciliation adapter; **not implemented here**.

### Testable rule grammar (M03E adapter)
`next_expected_event.condition` and `invalidation.condition` MUST each be a JSON object with `field` (`close`, `high`, `low`), `operator` (`<`, `>`, `<=`, `>=`), positive finite `level`, `requires_closed_bar=true`, and `reference_evidence_id` contained in actual M02/M03 evidence IDs. Their `timeframe` MUST match the setup TF. `invalidation.rule=CLOSED_BAR`. No automatic trigger is generated from those conditions in this version; a dedicated validated closed-bar event detector is still required for M10 TRIGGER/CONFIRM. Reference ID alone does not independently certify the appropriateness of the numeric level.
