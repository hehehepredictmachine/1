# M10A → M15 — audit and tests — 1.0.0-CANDIDATE

## Changes

- Linked automatic M10A lifecycle events with unmodified M15 communication engine.
- Added canonical M14 source binding to actual in-process MT5 snapshot, rather than trusting an outer report missing `analysis_id`.
- Added fail-closed NO_TRADE/BLOCKED for missing/stale data, bad decision binding, missing early rules and untrusted authorization.
- Added single process runner, 15 s viewer heartbeat, compact six-TF indicator summary, outbox event dedup and explicit opt-in Telegram.
- MT5 Zero account is a declared profile; commissions, real spread, swap/slippage and fills are not certified.
- Preserved M01–M14 and vendor M15 source unmodified; no order executor and no screenshots.

## Offline verification

- Original M01–M14 integration regression: 679 / 679 PASS.
- Original standalone M15: 65 / 65 PASS.
- New M10A/M15 adapter: 50 / 50 PASS.
- **Total: 794 / 794 PASS**.
- An additional simulated integrated Windows-runner smoke test created local M15 output with `NO_TRADE/BLOCKED` and no Telegram/network activity.
- A real M10A state progression through QUALIFIED/ARMED/TRIGGERED/CONFIRMED was passed to M14 then M15: synthetic `LONG`, execution BLOCKED, correct event ID.

## Important limitations

These tests use fake MT5 and mocked Telegram, so they do not demonstrate real delivery, live data integrity, backtest profitability, complete broker costs, or account safety. Production M01 broker certification, full strategy specs, M06 OOS/forward DEMO, risk M11 and live authorization M14 remain outstanding. Current monitor/export are research-only. At-most-once Telegram attempt may drop notifications following network errors; UNKNOWN messages are not automatically retried. The system does not run in ChatGPT background or control Windows terminal remotely.

## Acceptance

Candidate only. Does not modify any existing MasterQUO project files or grant production execution rights.
