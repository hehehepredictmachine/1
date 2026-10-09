# Kontrakt API v1 (backend ↔ monitor)

Bazowy adres: `http://127.0.0.1:8765` (port: `server.port`). Wszystkie czasy: ISO 8601 UTC (`Z`). Wersja: `version.API_CONTRACT_VERSION = 1.0.0`.

## Sesja
* `GET /` – strona monitora; ustawia cookie `mq_sid` (HttpOnly, SameSite=Strict).
* `GET /api/v1/session` → `{csrf, contract, boot_id, port}` (wymaga cookie).
* Każde żądanie zmieniające stan: nagłówki `Origin: http://127.0.0.1:<port>` i `X-MQ-CSRF: <csrf>`.
* `GET /api/v1/health` (bez sesji) → `{ok, app, version, contract, boot_id, synthetic, mt5_state, time}`.

## Odczyt
| Endpoint | Treść |
|---|---|
| `GET /api/v1/state` | connection, account, symbol, quote, tf_meta, analysis, decision, engine, agent, agent_last, mode, risk/costs/strategy config, news, positions, managed, attempts, paper, logs, pc_clock, manager, first_run_completed, seq, boot_id |
| `GET /api/v1/candles?tf=M1..D1` | bars (forming + closed, `open_utc`, `close_confirmed_utc`, `available_at`, `basis`), indicators (lines, panels.rsi, panels.macd z `visual_only`), overlays (breaks, fvgs, order_blocks, sweeps, liquidity_levels, pivots, premium_discount), quality, clock |
| `GET /api/v1/decision` | bieżący rekord decyzji (`mq-decision-1.0.0`) |
| `GET /api/v1/signals` | setups, decisions (istotne), attempts, trades |
| `GET /api/v1/stats?mode=PAPER\|DEMO_EXECUTION\|LIVE_EXECUTION` | bot (all/day/week/month), equity (snapshoty), account (operacje rachunku) |
| `GET /api/v1/news` | status M04N, macro, calendar, news, sentiment (NOT_AVAILABLE) |
| `GET /api/v1/logs?limit=` | log bota |
| `GET /api/v1/config` | konfiguracja bez sekretów + źródła/maski sekretów |
| `GET /api/v1/agent`, `/agent/models`, `/agent/memory` | status, ostatnia analiza, przebiegi; lista modeli z API; propozycje |
| `GET /api/v1/diagnostics` | platforma, połączenie, surowe otwarcia świec, worker, schema DB |

## Zmiana stanu
`PUT /api/v1/config` (częściowy patch), `POST /api/v1/secrets/anthropic {api_key}`, `POST /api/v1/secrets {name,value}`,
`POST /api/v1/mode {mode, confirm}`, `POST /api/v1/auto {on}`, `POST /api/v1/kill {on, reason}`, `POST /api/v1/execute {decision_id}`,
`POST /api/v1/positions/close {scope, ticket?, confirm:"ZAMKNIJ"}`, `POST /api/v1/positions/{ticket}/adopt {confirm:"PRZEJMIJ"}`,
`POST /api/v1/agent/test|analyze`, `POST /api/v1/agent/ask {question}`, `POST /api/v1/agent/memory/{id} {status}`,
`POST /api/v1/mt5/reconnect`, `POST /api/v1/news/refresh`, `POST /api/v1/admin/shutdown`.

## WebSocket `/api/v1/ws`
1. Klient: `{"csrf": "...", "last_seq": <int|null>, "boot_id": "<z poprzedniej sesji>"}`.
2. Serwer: `{"type":"resync","seq":N,"boot_id":..,"state":{...}}` albo zdarzenia od `last_seq+1` (jeśli są w buforze).
3. Zdarzenia: `{"seq","boot_id","type","ts","data"}`; typy: `quote, bar, bar_closed, bars_reloaded, connection, account, positions, symbol,
   clock, analysis, decision, dq, agent, agent_result, mode, news, orders, log, trade_settled, engine_error`.
4. Luka w `seq` → klient zamyka i łączy ponownie z `last_seq` (replay lub pełny resync). Kod 4403 = sesja nieważna (restart serwera).

## Rekord decyzji `mq-decision-1.0.0`
`decision_id, content_hash, snapshot_id, symbol, account_key, session_epoch, as_of_utc, expires_at_utc, analysis_direction (LONG|SHORT|NEUTRAL),
direction_basis (SETUP|STRUCTURE_OBSERVATION|NONE), signal_stage (WATCH|EARLY|CONFIRMED|EXPIRED|INVALIDATED), decision (BUY|SELL|WAIT|NO_TRADE),
execution_permission (ALLOWED|BLOCKED), system_state, data_quality, market_state, setup, levels, risk, agent_gate, mode_gate, decision_tree[7], reason_codes, structure, synthetic`.

## Rekord oceny AI `mq-agent-1.0.0`
`schema_version, decision_id, snapshot_id, setup_id, as_of_utc, expires_at_utc, analysis_direction, signal_stage, proposed_action, strategy_id,
strategy_version, entry_zone, invalidation_level, proposed_targets, scenarios{bullish,bearish,wait}, evidence_refs, contradictions, missing_data,
reason_codes, explanation_pl, answer_pl, lessons, playbook_proposals, model_id, prompt_version`.
