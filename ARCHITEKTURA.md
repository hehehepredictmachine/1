# Architektura MasterQUO AI 1.0.0

## 1. Jeden proces, jeden przepływ

```
 Windows: terminal64.exe (zalogowany)          przeglądarka  http://127.0.0.1:8765
            ▲  IPC (MetaTrader5 Python)                 ▲  HTTP /api/v1 + WebSocket /api/v1/ws (sesja, CSRF, Origin)
            │                                           │
 ┌──────────┴───────────────────────────────────────────┴───────────────────────────────────────┐
 │ python -m masterquo serve   (uvicorn, 127.0.0.1 only, single instance lock)                  │
 │                                                                                              │
 │  MT5Worker ── jedyny wątek wywołujący MetaTrader5; kolejka priorytetów: trade > quote > hist │
 │     ▲                                                                                        │
 │  MarketBridge (wątek) ── connect/backoff, heartbeat, symbol XAUUSD-, quote 0,5 s,            │
 │     │   6 TF (M1…D1) zrzut + ogon + gap-fill, rachunek/pozycje 2 s, deals 30 s,              │
 │     │   ServerClock: offset serwera z ticków, session_epoch (zmiana rachunku/terminala)      │
 │     ▼  zdarzenia: bars_closed / connected / account_changed                                  │
 │  EngineService (wątek) ─ pełny cykl na zamkniętej świecy, lekki co 1 s:                     │
 │     quality.assess → build_snapshot → M02 → M02I → M03 → M07+PlanLock (bez zmian)            │
 │     → LifecycleStore (M10A) → MQAI-LEVELS → risk.evaluate (M11) → agent.gate_for             │
 │     → modes.gate → decision.build → SQLite → EventBus → (AUTO) gateway.execute               │
 │  ClaudeAgent (asyncio) ─ żądania zdarzeniowe → manual tool loop (AsyncAnthropic)            │
 │     narzędzia read-only nad zamrożonym kontekstem snapshotu; JSON schema; budżet             │
 │  ExecutionGateway ─ walidacja → order_check → order_send (PAPER: PaperBroker)               │
 │  PositionManager (wątek 1 s) ─ UNKNOWN→rekonsyliacja, TP1 partial, SL→BE, rozliczenia,       │
 │     PAPER exits, equity snapshots                                                            │
 │  NewsService (wątek) ─ M04N collect() co 300 s (sieć: Fed/BLS/FF/MM/GDELT, opc. FRED)       │
 │  EventBus (seq, ring 5000) ─ WebSocket: resync | replay od last_seq                         │
 │  SQLite WAL (data/masterquo.sqlite) ─ migracje + kopie w data/backups                        │
 └──────────────────────────────────────────────────────────────────────────────────────────────┘
```

Analiza Claude i newsy działają w osobnych wątkach/pętli – nigdy nie blokują odbioru danych z MT5 ani wykresów.

## 2. Moduły (backend/masterquo)

| Pakiet | Odpowiedzialność |
|---|---|
| `mt5/worker.py` | jeden wątek terminala, priorytety, timeout, wykrycie zawieszenia |
| `mt5/bridge.py` | połączenie, symbol, quote, świece 6 TF, rachunek, pozycje, deals, kalkulatory brokera |
| `mt5/clock.py` | kontrakt czasu: pomiar offsetu serwera, zmiany DST |
| `mt5/fake.py` | symulator terminala (testy + tryb DANE SYNTETYCZNE) |
| `data/quality.py` | rola M01: walidacja, luki (weekend/przerwa/niewyjaśniona), świeżość, stan rynku, bramki |
| `data/pcclock.py` | opcjonalna kontrola zegara PC (nagłówek Date HTTPS) |
| `engine/legacy.py` | adapter do niezmienionych M02/M02I/M03/M07 (`backend/vendor/legacy_core`) |
| `engine/lifecycle.py` | reduktor M10A + tabela `setups` |
| `engine/targets.py` | MQAI-LEVELS-1.0.0 (SL/TP z poziomów płynności M03) |
| `engine/decision.py` | drzewo decyzji, pola rozdzielone |
| `engine/chartdata.py` | serie wskaźników (funkcje M02I) i nakładki struktury |
| `engine/service.py` | orkiestracja, konteksty dla agenta, zapis decyzji |
| `risk/engine.py`, `risk/costs.py` | port M11: koszty, RR netto, sizing, limity |
| `execution/modes.py` | tryby i bramka uprawnień |
| `execution/gateway.py` | jedyna ścieżka do `order_send`, idempotencja |
| `execution/paper.py` | symulacja PAPER |
| `execution/manager.py` | zarządzanie pozycjami, rekonsyliacja, rozliczenia, equity |
| `agent/*` | ClaudeAgent, narzędzia, schemat JSON, prompt |
| `news/service.py` | M04N |
| `api/*` | FastAPI, bezpieczeństwo, WebSocket |
| `stats.py` | statystyki z rozliczonych zdarzeń |
| `diagnostics.py`, `__main__.py` | CLI: serve/stop/doctor/clock/set-key/export |

## 3. Kontrakt czasu

* Surowe czasy MT5 (`time`, `time_msc`) = zegar serwera brokera zapisany jako epoch („UTC without the shift” wg dokumentacji MetaTrader5 –
  strona mql5.com była niedostępna z mojego środowiska, cytat z wiedzy, nie z bieżącej weryfikacji).
* `ServerClock`: delta = `time_msc/1000 − UTC_PC` dla **nowych** ticków; przyjęcie offsetu tylko gdy ≥ 5 próbek i najlepsza delta leży ±90 s od
  wielokrotności 15 min. Wynik: VERIFIED / STORED_UNVERIFIED (z poprzedniej sesji, np. weekend) / INCONSISTENT / UNKNOWN. Cofnięcie czasu > 30 min = ponowny pomiar.
* Świeca: `open_raw`, `open_utc = raw − offset`, `close_confirmed_utc` = zaobserwowane otwarcie następnej świecy, `available_at` =
  moment obserwacji (live, `basis=OBSERVED`) lub otwarcie następnej świecy (historia, `basis=HISTORICAL_ESTIMATE`).
* TTL świeżości per interwał: forming bar nie starszy niż TF + 180 s przy otwartym rynku; quote ≤ `max_quote_age_seconds` (10 s).
* Interfejs: czas lokalny / UTC / czas serwera – wyłącznie prezentacja.

## 4. API (wersja kontraktu 1.0.0)

Szczegóły: `docs/API_KONTRAKT_v1.md`. Najważniejsze: `GET /api/v1/state` (pełny snapshot), `GET /api/v1/candles?tf=`,
`GET /api/v1/signals|stats|news|logs|config|diagnostics|agent`, `POST /api/v1/mode|auto|kill|execute|positions/close|agent/ask|agent/analyze`,
`PUT /api/v1/config`, `POST /api/v1/secrets/anthropic`, `WS /api/v1/ws` (hello `{csrf,last_seq,boot_id}` → `resync` lub zdarzenia z `seq`).

## 5. Baza danych (migracja 0001)

`app_events` (log bota), `clock_offsets`, `accounts_seen`, `analysis_snapshots`, `setups`, `decisions`, `agent_runs`, `agent_memory`,
`order_attempts` (UNIQUE `entry_key` = tryb:rachunek:setup), `managed_positions`, `trades`, `paper_account`, `equity_snapshots`,
`settings_audit`, `notifications_sent`. Migracje numerowane, transakcyjne; kopia zapasowa przed każdą nową migracją istniejącej bazy.

## 6. Bezpieczeństwo lokalne

Nasłuch wyłącznie `127.0.0.1` (pole konfiguracji przyjmuje tylko tę wartość). Host-check (DNS rebinding), Origin-check dla zmian i WS,
cookie sesji HttpOnly/SameSite=Strict + token CSRF, CSP, brak CORS. Zatrzymanie przez lokalny token w `data/runtime/shutdown.token`.
Klucz Claude: Windows DPAPI (`data/secrets.dpapi.json`), nigdy w odpowiedziach API, logach, przeglądarce ani paczce.

## 7. Decyzje technologiczne

* **FastAPI + uvicorn + pydantic** – prosta walidacja i WebSocket w jednym procesie; bez Dockera.
* **SQLite (WAL)** – zero instalacji, transakcje dla idempotencji.
* **React 19 + TypeScript + Vite** – frontend zbudowany do `frontend/dist`, serwowany przez backend (Node.js niepotrzebny u użytkownika).
* **TradingView Lightweight Charts™ 5.2.1** – licencja Apache-2.0, własne dane OHLC, panele, prymitywy; wymagane uznanie autorstwa
  (logo TradingView na wykresie pozostawione włączone + nota w stopce). Biblioteka **nie** jest źródłem notowań.
* **Brak EA/MQL5** – wszystkie potrzebne dane (świece, ticki, rachunek, kalkulatory, zlecenia) są dostępne przez pakiet Python MetaTrader5;
  aplikacja nie odczytuje niestandardowych wskaźników ani obiektów z wykresów terminala (tego API świec nie umożliwia).
* **Silniki legacy bez zmian** – zachowana dokładnie metoda obliczeń i definicje; hash każdego pliku kontrolowany testem.
