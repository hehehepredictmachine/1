# M10A → M15 Integration Contract — 1.0.0-CANDIDATE

## Producer / consumer

- Producer: `RUN_MT5_AUTOMATIC_TRIGGER_READONLY.publish` (M01/M02/M02I/M03E/M09/M10A/M14, read-only).
- Local in-process identity binding: `IntegratedReadOnlyMonitor.snapshot` supplies `analysis_id`, `snapshot_id`, `as_of`; matches the output of the same invocation. This corrects a missing field in the *outer M10A report only*, not upstream engine source.
- Consumer: `M10A_M15_ADAPTER.convert` calls unmodified `M15_REFERENCE_COMMUNICATION_ENGINE.validate_m14` and `compose`.
- Renderer: `M10A_M15_ADAPTER.render` writes files in the `runtime/M15` directory and optionally queues Telegram notifications.

## Required invariants

1. `schema_version=2.0.0`, valid RFC3339 as_of with timezone, matching M14 `analysis_id/as_of/decision/direction`, zero screenshot count, no OCR, `ZERO_SPREAD_DECLARED_UNVERIFIED`, `research_only=true`.
2. `monitor_connection_status=CONNECTED`, `monitor_quote_status=RECEIVED`, M01 analysis gate `PASS`/`PASS_WITH_LIMITATIONS`. Otherwise M15 exports **NO_TRADE / BLOCKED**, with no new actionable notification.
3. Source of prices is MT5 broker Bid/Ask; quote is displayed only if its timestamp is not later than bound analytical `as_of` and is valid. `TradingView` can only provide supplementary nonexecution context. Zero spread ≠ zero total costs.
4. All M14 execution fields must be BLOCKED/FALSE/NULL, regardless of any caller-supplied `AUTHORIZED` or order IDs. M15 and this adapter never grant execution rights.
5. The source of lifecycle stage/revision/event ID is the M10 persisted `validated_record.change_log`. Ordinary updates to Bid/Ask are **not material events**. Confirmation stage requires separate real M10 stages and M14 verification.
6. `M10A` source is the caller's own in-process result, NOT an externally submitted webhook or raw JSON file. The local adapter is not a production authentication boundary.
7. No valid `next_expected_event` or `invalidation` from an early setup → **NO_TRADE** fallback, no invented rule or price.
8. `Outbox` uses SQLite, extended with stable `(channel,event_id)` unique index. At-most-once **attempt** is preferred over automatic retry; API timeouts yield `UNKNOWN`.
9. `--telegram-send` explicit and `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` present are necessary for real delivery. No CLI option can send an MT5 order.
10. Monitor JSON is committed last. `m15_published_at` is a *local publication/heartbeat* timestamp, separate from the M01/M14 market `as_of`. The GUI rejects a heartbeat older than 15 seconds.
11. Never map `CONFIRMED` to a realized fill, ROI or true win probability. Entries/SL/TP remain null unless a real matching upstream plan with MT5 provenance exists.

## Outputs

- `M15_MONITOR_SNAPSHOT.json` full current snapshot, with `indicator_timeframes` for D1/H4/H1/M15/M5/M1, state, decision and `BLOCKED`.
- `M15_EXPORT_FULL.json` full M15 v2 export plus local adapter diagnostics.
- `M15_COMPACT_PL.txt` and `M15_FULL_PL.txt` (18 canonical sections).
- `M15_LAST_DELIVERY_STATUS.json`: `NOT_SENT`, `TELEGRAM_DISABLED`, `DELIVERED`, `QUEUED_MISSING_ENV`, `DUPLICATE_SUPPRESSED`, `UNKNOWN`, `REJECTED`, `NO_MATERIAL_EVENT` or `SUPPRESSED_UNSAFE_OR_NON_SIGNAL`.
- `M15_DELIVERY_OUTBOX.sqlite3` (only when Telegram enabled with a genuine material event).
- `M10_STATE.sqlite`: upstream lifecycle state; unchanged owner M10.

## Explicitly out of scope

Broker execution, full production M01 certification, data-driven strategy generation, OOS/WFA research, genuine zero-cost certification, Telegram 24/7 hosting, production identity attestation and forward DEMO are NOT covered.
