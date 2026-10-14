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

## Dodane w 1.2 (kontrakt AUTO `mq-auto-1.0.0`, zgodny wstecz)
| Endpoint | Treść |
|---|---|
| `GET /api/v1/strategy/auto` | strategy_mode, system_state, regime, selected_strategy_id/version, selected, selection_reason_codes, candidate_ranking, alternative, selected_at, last_evaluated_at, snapshot_id, data_status, last_change, per_strategy, setups, funnel, strategies, why_no_setup |
| `POST /api/v1/strategy/mode` | `{strategy_mode: AUTO|MANUAL, manual_strategy_id?}` – nie zmienia trybu ani wykonywania zleceń |
| `POST /api/v1/strategy/toggle` | `{strategy_id, scan?, trade?}` |
| `POST /api/v1/strategy/profile` | `{profile: ACTIVE|ORIGINAL}` |
| `GET /api/v1/strategy/selection-log` | historia zmian wyboru (przyczyna, poprzednia/nowa strategia, snapshot) |
| `GET /api/v1/playbook` | karty setupów ACTIVE (także odwołanych) z historią i wynikiem lub „brak danych” |
| `GET /api/v1/appearance/assets`, `POST /api/v1/appearance/upload?slot=background|frog` (body: GIF), `GET /media/masterquo/{slot}` | grafiki monitora; upload walidowany (struktura GIF, ≤ 15 MB) |
`GET /api/v1/state` zawiera dodatkowo `auto` (skrót) i `active_config`. Rekord decyzji ma pole `profile` (ACTIVE/ORIGINAL),
`direction_basis` może mieć wartość `REGIME_OBSERVATION`. WebSocket: nowe zdarzenie `auto`.

## 1.10 – rozszerzenia prezentacyjne (zgodne wstecz)
| Endpoint | Zawartość |
|---|---|
| `GET /api/v1/timeframes` | rejestr TF (`tf`, `seconds`, `role`, `core`), stan danych per TF (`data`, `closed_bars`, `required`), `used_by` (strategie), `strategies` (setup_tfs, required_tfs, context_tf) – źródło strony „Wykresy bota” |
| `GET /api/v1/setups` | jak w 1.8 + `terminal_reason_pl` |
| `GET /api/v1/setups/{id}/details` | schemat **MQ-SETUP-DETAILS-1.1.0**: każdy wiersz `checklist` ma `group` (1–10), `state` (MET/MISSING/PENDING/NO_DATA/NA), `required`, `tf`, `at`; nowe `summary` (`required_total`, `required_met`, `missing`, `pending`, `no_data`, `first_blocker`, `next_confirmation`, `groups`) i `selector_mode`. Setup innego rachunku → 404 |
| `GET /api/v1/walls`, `POST /api/v1/walls/iv-import`, `GET /api/v1/structure?tf=` | snapshot walls ze źródłem; import IV; struktura TF (S/R, zakres M5, strefy M1, formacje, pivoty z `known_at`, dowody świecowe) |
Monitor: odczyt szczegółów setupu nigdy nie wywołuje `POST /api/v1/prefs/setup-view` – ten endpoint zmienia wybór strategii silnika i jest używany tylko przez jawne ustawienie „Działanie bota”.

## 1.11 – prognozy świec (SHADOW)
| Endpoint | Zawartość |
|---|---|
| `GET /api/v1/forecast` | `status` (SHADOW / NO_MODEL / NO_CANDLE_ENV / WARMUP / STALE_DATA / CONTRACT_MISMATCH / FORECAST_UNAVAILABLE / DISABLED / NO_DATA), `report` (gold_candles: formacje M5/M30, `forecast`, `execution_lock` = BLOCKED), `model`, `setup_v2` (Double Retest v2, EXECUTION_STATE=BLOCKED), `registry`, `training`, `shadow_summary`, `latency_ms`; zawsze `execution_permission=false` |
| `GET /api/v1/forecast/shadow?limit=` | prognozy zapisane przed wynikiem i ich ocena (`outcome_status` PENDING / SCORED / NO_CONTINUOUS_DATA / OUT_OF_BUFFER) |
| `POST /api/v1/forecast/reload` | proces analityki odczyta rejestr ponownie; nowy model od następnej zamkniętej M5 |
WebSocket: zdarzenie `forecast` po każdej nowej zamkniętej M5.
