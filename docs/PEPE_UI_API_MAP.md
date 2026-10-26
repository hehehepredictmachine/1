# PEPE_UI_API_MAP – mapa integracji nowych paneli z istniejącym API (Etap 0)

Źródło prawdy: kod `backend/masterquo/api/app.py` (252 trasy `/api/v1/*`) i WebSocket `/api/v1/ws`. Statusy jak w
[PEPE_UI_AUDIT.md](PEPE_UI_AUDIT.md). Wszystkie trasy wymagają sesji monitora (ciasteczko + CSRF dla zmian stanu); bez sesji
odpowiedź 401 `SESSION_REQUIRED_OPEN_MONITOR_PAGE` – UI pokazuje stan **permission denied / session expired**, nie zero.

Konwencje obsługi błędów w nowych panelach (dla każdego wiersza, o ile nie zapisano inaczej):
* **HTTP ≠ 2xx** → stan `error` z kodem z odpowiedzi; 401 → `permission denied`; 409 → konflikt stanu (np. zmiana trybu odrzucona);
* **brak pola / `null`** → `N/A` / `UNKNOWN`, nigdy `0`;
* **WS zamknięty** (`ws ≠ OPEN`) lub **MT5 ≠ CONNECTED** → nakładka `disconnected`, dane oznaczone `stale`, operacje zablokowane;
* **świeżość** – z pól czasu w danych (`quote.age_seconds`, czas ostatniej zamkniętej świecy, `as_of`, `generated_at`), a nie z czasu
  odebrania odpowiedzi.

---

## 1. Kontekst aplikacji (header, sidebar) – Etap 1

| Funkcja UI | Istniejący endpoint / event | Typ danych | Właściciel źródła | Status integracji | Obsługa błędu | Test integracyjny |
|---|---|---|---|---|---|---|
| Wersja, kontrakt API, `boot_id` | `GET /api/v1/state` (`app_version`, `contract`, `boot_id`), `GET /api/v1/health` | obiekt | API | `EXISTS_VERIFIED` | brak backendu → ekran fatal (istniejący) | `test_app_process` |
| Środowisko LIVE / DEMO / SYNTHETIC / UNKNOWN | `state.account.trade_mode` (DEMO / CONTEST / REAL), `state.synthetic`; zdarzenia WS `account` | enum | MarketBridge (`mt5/bridge.py`) | `EXISTS_VERIFIED` (mapowanie do uzgodnienia – D2) | brak rachunku → `UNKNOWN` | nowy: `test_ui_terminal_shell` (env badge) |
| Tryb wykonania | `state.mode` + WS `mode` (SIGNALS / PAPER / AUTO_DEMO / AUTO_LIVE, STOP, ścieżka główna) | obiekt | ModeManager (`execution/modes.py`) | `EXISTS_VERIFIED` | brak → `UNKNOWN` | `test_risk_execution`, nowy test UI |
| Status MT5 + szczegóły | `state.connection` + WS `connection`, `clock` (stan, przyczyna, `last_heartbeat`, `connected_since`, `session_epoch`, próby, błędy, offset zegara) | obiekt | MarketBridge | `EXISTS_VERIFIED`; opóźnienie zapytań: brak (tylko wiek kwotowania) | ≠ CONNECTED → `DISCONNECTED` + blokada operacji | `test_bridge_engine`, nowy test UI |
| Świeżość danych | WS `quote` (`time_utc`, `age_seconds`), `state.decision.data_quality`, `GET /api/v1/timeframes` (dane per TF) | obiekt | MarketBridge / data quality | `EXISTS_VERIFIED` | `age_seconds` > próg TF → `stale` | `test_time_and_data` |
| Instrument (wyświetlenie) | `state.symbol`, `GET /api/v1/assets` | obiekt | AssetRegistry | `EXISTS_VERIFIED` | – | `test_ui_pages` |
| Instrument (przełączenie) | `POST /api/v1/assets/active` (+ `/assets/confirm`) – **zmienia instrument bota, resetuje tryb** | zmiana stanu | AssetRegistry + Runtime | `EXISTS_VERIFIED`; użycie w nowym UI: decyzja D1 | 409 → komunikat; po zmianie: reconnect | istniejące testy aktywa |
| Powiadomienia / ostrzeżenia | WS `log` (poziom, kategoria, kod), `GET /api/v1/logs`, `state.last_error`, WS `engine_error` | lista | Logger (`app_events`) | `EXISTS_VERIFIED`; status alertu: `MISSING` | – | `test_ui_monitor` (logi) |
| Diagnostyka | `GET /api/v1/diagnostics`, `GET /api/v1/analytics/diagnostics` | obiekt | Runtime | `EXISTS_VERIFIED` | błąd → `error` | `test_ui_analytics` |
| Ustawienia | istniejący `SettingsModal` (`/api/v1/config`, `/prefs`) | – | Config | `EXISTS_VERIFIED` | – | `test_ui_monitor` |
| Status źródeł danych | `GET /api/v1/timeframes`, `/zones/status`, `/liquidity/source`, `/ml/status`, `/forecast` | obiekty | serwisy | `EXISTS_VERIFIED` per źródło; widok zbiorczy: `MISSING` | – | nowy test (etap 4) |

## 2. Trading Intelligence – Etap 2

### 2.1 Market Overview (2×2: M5, M15, H1, H4)

| Funkcja UI | Endpoint / event | Typ danych | Właściciel | Status | Obsługa błędu | Test |
|---|---|---|---|---|---|---|
| Świece OHLC aktywnego instrumentu | `GET /api/v1/candles?tf=` + WS `bar`, `bar_closed`, `bars_reloaded` | `{tf, symbol, bars[{open_utc,o,h,l,c,tv,closed}], overlays, clock, synthetic}` | EngineService / MarketBridge | `EXISTS_VERIFIED` | 400 `INVALID_TIMEFRAME`; brak świec → `WARMING_UP` z liczbą świec | `test_bridge_engine`, `test_ui_monitor` |
| Świece innego instrumentu (tryb podglądu, D1-a) | `GET /api/v1/markets/chart?symbol=&tf=&bars=` | `{bars, meta}` | MarketBridge (multi-symbol) | `EXISTS_VERIFIED`; bez nakładek silnika | `SYMBOL_NOT_FOUND` → `error` | `test_markets_signals` |
| Wolumen | `bars[].tv` = **tick volume** (aktywność) | liczba | MT5 | `EXISTS_VERIFIED` | etykieta „tick volume”, nie „volume” | – |
| High / low, strefy H/L, profil sesji | `GET /api/v1/zones/map?tf=` (+ WS `zones`) | mapa `PMW-ZONE-1.0` (wycinek wykresu) | ZoneService | `EXISTS_VERIFIED` | `NO_MAP` / `data.state ≠ OK` → `stale`/`degraded` | `test_zones` |
| Sesje (boksy, sweepy) | `GET /api/v1/liquidity/sessions?tf=` | boksy z `known_at` | LiquidityService / session_engine | `EXISTS_VERIFIED` | `INCOMPLETE` jako niepełny | `test_liquidity` |
| Strefy płynności | (a) **obliczone**: równe szczyty/dołki z mapy stref (`liquidity.inference = INFERRED`); (b) **zewnętrzne**: `GET /api/v1/liquidity/heatmap` (dostawca, wymaga klucza) | strefy | ZoneService / LiquidityService | (a) `EXISTS_VERIFIED`; (b) `BLOCKED` bez klucza | etykiety „obliczone / zewnętrzne / koncepcyjne” rozdzielone | `test_zones`, `test_liquidity` |
| Wsparcie / opór | mapa stref (`summary.nearest_support/resistance`, `htf_sr`), `GET /api/v1/structure?tf=` | strefy, zdarzenia | ZoneService, analiza struktury | `EXISTS_VERIFIED` | – | `test_zones`, `test_structure_v2` |
| Wejście / SL / TP | `state.decision` + WS `decision` (plan silnika), `GET /api/v1/sh` (plany SH) | ceny | EngineService, SHService | `EXISTS_VERIFIED` | brak planu → brak linii (nie 0) | `test_ui_monitor` |
| Znaczniki sygnałów | `GET /api/v1/signal-history`, `overlays` z `/candles` | lista | Engine | `EXISTS_VERIFIED` | – | `test_signal_view` |
| Metadane czasu i źródła | `clock` (dowód offsetu serwera), `synthetic`, `bars[].closed` | obiekt | MarketBridge | `EXISTS_VERIFIED` | – | `test_time_and_data` |

### 2.2 Signal Intelligence

| Funkcja UI | Endpoint / event | Typ danych | Właściciel | Status | Obsługa błędu | Test |
|---|---|---|---|---|---|---|
| Sygnały S01–S12 (bieżące) | `GET /api/v1/signals`, `GET /api/v1/setups`, `GET /api/v1/setups/{id}/details` (checklista, progi) | `MQ-SIGNAL-1.0.0` / scenariusze | Engine (tracker) | `EXISTS_VERIFIED` | `BRAK_DANYCH` → `UNKNOWN` | `test_signal_contract`, `test_setup_details` |
| Historia sygnałów | `GET /api/v1/signal-history?strategy=&status=&tf=` | lista | Engine | `EXISTS_VERIFIED` | – | `test_signal_view` |
| Sygnały SCALPING / HEDGING | `GET /api/v1/sh` (`last_eval`: checklista, poziomy, modele, ryzyko), `GET /api/v1/sh/signals` | obiekty | SHService | `EXISTS_VERIFIED` | – | `test_sh_api`, `test_sh_service` |
| Ocena setupu (ACCEPT / REDUCE / DEFER / REJECT + powody, P/EV, kontekst stref) | `GET /api/v1/eval/assessments?engine=`, `/eval/report`, `/eval/exposure` | lista | EvaluationService (SHADOW) | `EXISTS_VERIFIED`; **nieużywane w obecnym UI** | `SMALL_SAMPLE` jawnie | `test_evaluation` |
| Wynik modeli przy sygnale | ML: `GET /api/v1/ml/predict?setup_id=`, `GET /api/v1/ml/explain?setup_id=&version=` (ścieżka DT / TreeSHAP XGB); SH: `last_eval.models`; NSS: `GET /api/v1/lab/neural` | obiekty | MLService, SH, NSS | `EXISTS_VERIFIED` per model | model niegotowy → `N/A` z powodem | `test_ml`, `test_nss` |
| Konsensus / konflikty | `GET /api/v1/mm/live` (tablica dowodów: wyniki obok siebie, niezgodności, `independence`) | obiekt | MMService (`mm/fusion.py`) | `EXISTS_VERIFIED` – **bez jednej liczby konsensusu** (celowo) | `MISSING_INPUT` jawnie | `test_mm_core` |
| Ocena ryzyka | `decision.risk` (wielkość, ryzyko, marża), `/eval/exposure`, `state.risk_config` | obiekt | risk engine | `EXISTS_VERIFIED` | – | `test_risk_execution` |
| Lista zunifikowana z jednym statusem | brak – trzy źródła | – | – | `MISSING` – kontrakt N2 (§4) | – | nowy |

#### 2.3 Proponowane mapowanie statusów prezentacyjnych (do akceptacji przed etapem 2)

| Prezentacja | S01–S12 (`MQ-SIGNAL-1.0.0`) | SCALPING / HEDGING | Ocena SHADOW |
|---|---|---|---|
| `NEW` | nowy setup w trackerze (pierwsza wersja, przed potwierdzeniem) | – | – |
| `ANALYZING` | `OCZEKIWANIE` | `WAIT` z kandydatem | `DEFER` |
| `VALIDATED` | `POTWIERDZONY` | `READY` | `ACCEPT` |
| `WARNING` | `POTWIERDZONY` z ostrzeżeniem danych (`data_quality ≠ GOOD`) | `READY` z ostrzeżeniem | `REDUCE` |
| `REJECTED` | `ZABLOKOWANY` | `BLOCKED` | `REJECT` |
| `EXPIRED` | `WYGASŁY`, `UNIEWAŻNIONY` (z podtypem) | wygaśnięcie planu | – |
| `EXECUTED` | **tylko** `execution_state = WYKONANO` (potwierdzone przez gateway / terminal); `WYSŁANO` = osobna plakietka „wysłano, czeka na potwierdzenie” | plan z otwartą pozycją | – |
| `UNKNOWN` | `BRAK_DANYCH`, nieznany status | brak oceny | brak oceny |

Status ze źródła jest zawsze pokazywany obok statusu prezentacyjnego (mapowanie nie ukrywa oryginału).

### 2.3 Risk & Performance

| Funkcja UI | Endpoint / event | Typ danych | Właściciel | Status | Obsługa błędu | Test |
|---|---|---|---|---|---|---|
| Otwarte pozycje | WS `positions`, `state.positions`, `state.managed` | lista | MarketBridge / PositionManager | `EXISTS_VERIFIED` | – | `test_risk_execution` |
| Zlecenia / próby | WS `orders`, `state.attempts` (PREPARED / SENDING / DONE / UNKNOWN …) | lista | ExecutionGateway | `EXISTS_VERIFIED` | `UNKNOWN` widoczne jako niejednoznaczne | `test_risk_execution` |
| Ekspozycja łączna | `GET /api/v1/eval/exposure` | obiekt | evaluation/exposure | `EXISTS_VERIFIED` | – | `test_evaluation` |
| Equity / balance | WS `account`, `GET /api/v1/stats` (`equity`) | obiekt / seria | MarketBridge, stats | `EXISTS_VERIFIED` | brak rachunku → `UNKNOWN` | `test_stats_definitions` |
| Drawdown, ROI, statystyki | `GET /api/v1/stats?mode=PAPER|AUTO_DEMO|AUTO_LIVE` (z `definitions`, ROI Dietza) | obiekt | stats.py | `EXISTS_VERIFIED`; filtr dat: `MISSING` | `NO_DATA` / `SMALL_SAMPLE` jawnie | `test_stats_definitions`, `test_finish_plan` |
| Dziennik transakcji | `GET /api/v1/stats` (`bot.trades` …), WS `trade_settled` | lista | stats / PositionManager | `EXISTS_VERIFIED` (filtry: `MISSING`) | – | `test_finish_plan` |

### 2.4 Order Preview

| Krok specyfikacji | Istniejący mechanizm | Status |
|---|---|---|
| 1. Wybór sygnału | sygnał S01–S12 (`decision_id`) albo dowolny sygnał jako szablon dla ręcznego padu | `EXISTS_VERIFIED` |
| 2. Walidacja backendowa (uprawnienia, ryzyko, limity, instrument, wolumen, cena, SL/TP) | S01–S12: `GET /api/v1/decision` (decyzja z bramkami i wielkością pozycji); ręcznie: `POST /api/v1/manual/plan` (wyrównanie SL/TP do ticka, wolumen z ryzyka, koszty, TTL 5 s) | `EXISTS_VERIFIED` |
| 3. Podsumowanie w UI | – (nowy komponent) | `MISSING` (UI) |
| 4. Jawne potwierdzenie | S01–S12: `POST /api/v1/execute {decision_id}`; ręcznie: `POST /api/v1/manual/intents` → `POST /api/v1/manual/intents/{iid}/execute {action_revision}` | `EXISTS_VERIFIED` |
| 5. Ponowna walidacja tuż przed wysłaniem | gateway: ta sama decyzja, ALLOWED, nieprzeterminowana, ten sam rachunek i `session_epoch`, setup nadal CONFIRMED, świeże kwotowanie, dryf ceny ≤ deviation, `order_check`; pad: świeży plan | `EXISTS_VERIFIED` (`test_risk_execution`, `TestManualPadRuntime`) |
| 6. Wynik po potwierdzeniu backendu | odpowiedź `status` + WS `orders`, `positions`; timeout → `UNKNOWN` uzgadniany po tagu, **nigdy ponawiany** | `EXISTS_VERIFIED` |
| Idempotencja | gateway: UNIQUE (tryb, rachunek, setup) → `DUPLICATE`; pad: klucz idempotencji + PREPARED przed wywołaniem | `EXISTS_VERIFIED` |

Wniosek: **żadna nowa ścieżka wysyłania nie jest potrzebna** (D5). Order Preview to nowy widok na istniejące kontrakty.

## 3. AI Neural Lab – Etap 3

| Funkcja UI | Endpoint / event | Typ danych | Właściciel | Status | Obsługa błędu | Test |
|---|---|---|---|---|---|---|
| Katalog modeli z rolą i stanem | `GET /api/v1/training/models?instrument=` (jeden rejestr: rola, status, gotowość, blokery), `GET /api/v1/ml/status`, `GET /api/v1/mm/status`, `GET /api/v1/lab/models` | listy | training/panel, ML, MM, lab | `EXISTS_VERIFIED` | model niedostępny → `N/A` z powodem | `test_sh_training`, `test_ml`, `test_mm_integration` |
| Metryki walidacji, ostatni trening, liczba próbek | `GET /api/v1/ml/report`, `/ml/models`, `/training/runs`, `/training/runs/{rid}/report`, `/training/compare` | obiekty | ML, training | `EXISTS_VERIFIED` | brak → `Unavailable` | `test_ml`, `test_train_all` |
| Decision Tree – struktura i ścieżka | plik `tree_structure.json` w artefakcie modelu; ścieżka: `/api/v1/ml/explain` | drzewo | ML | struktura: **brak endpointu** → N3; ścieżka: `EXISTS_VERIFIED` | – | `test_ml` |
| XGBoost – kaskada drzew | wkład cech: `/api/v1/ml/explain`, `/api/v1/ml/scalp/explain`; drzewa: **brak** | – | ML / scalp ML | `MISSING` (N3) | – | nowy |
| Random Forest | – | – | – | `MISSING` (D4) | widok „model nie istnieje” | – |
| MLP | trening w `.venv_candles` (`MLPClassifier(64,32)`); struktura i wagi tylko w artefakcie procesu prognoz | – | gold_candles_runtime | `MISSING` w API (N3 – struktura zapisywana przy treningu) | – | `tests/gold_candles/test_scalp_train.py` |
| Sieć NSS (TCN) – struktura + **realna telemetria warstw** | `GET /api/v1/lab/neural`, WS `lab_neural` (warstwy: średnia, odchylenie, frakcja aktywnych, heatmapa) | obiekt | NeuralScalpService | `EXISTS_VERIFIED` | brak modelu → `NOT_TRAINED` | `test_nss` |
| Monte Carlo | `GET /api/v1/flow-context/markov` (`mc_paths`, kwantyle cen w horyzontach, ziarno) | obiekt | Flow Context | `EXISTS_VERIFIED`; pojedyncze trajektorie: `MISSING` (N4) | brak modelu → `N/A` | `test_markov_reward` |
| Czas inferencji | NSS `inference_ms`; ML/scalp: brak jednolitego pola | liczba | serwisy | częściowo | brak → `N/A` | `test_nss` |
| Trening / walidacja / rollback | `POST /api/v1/training/start`, `/cancel`, `/resume`, `/rollback`, `/training/sh/promote`, `/ml/train`, `/ml/rollback`, `/lab/neural/*` | zmiany stanu | training / ML / lab | `EXISTS_VERIFIED` | potwierdzenie w UI + walidacja backendu | `test_train_all`, `test_ml` |
| Replay (krok po kroku, bez przyszłości) | widoki „as of”: `/api/v1/zones/map?as_of=`; historia predykcji NSS `/lab/neural/history`; ledger `mm/ledger` | listy | serwisy | częściowo (`as_of` tylko strefy) | – | `test_zones` (no look-ahead) |

## 4. Proponowane nowe kontrakty (do akceptacji w swoich etapach – nic nie jest wdrażane w etapie 0 ani 1)

| ID | Metoda i trasa | Cel | Request / response | Autoryzacja i walidacja | Timeout / błędy | Testy | Zgodność |
|---|---|---|---|---|---|---|---|
| N1 | – | Kontekst aplikacji | **nie jest potrzebny** – wyprowadzany w kliencie ze `state` + WS | – | – | – | – |
| N2 (etap 2) | `GET /api/v1/ui/signals?instrument=&since=&limit=` | jedna lista sygnałów z trzech źródeł | `{items:[{source, source_id, instrument, tf, side, created_at, source_status, presentation_status, entry, sl, tp[], rr, risk, models[], evaluation, data_age_s}], generated_at}` | sesja; parametry walidowane (Pydantic), `limit ≤ 500` | odczyt tylko z pamięci/SQLite, < 200 ms; 400 przy złych parametrach | kontrakt + mapowanie statusów (tabela 2.3) | tylko nowa trasa |
| N3 (etap 3) | `GET /api/v1/ui/models/{family}/{model_id}/structure?max_trees=&max_depth=` | struktura do wizualizacji (DT z `tree_structure.json`, XGB z `get_dump(dump_format="json")` z limitem, NSS warstwy, MLP z JSON zapisanego przy treningu) | `{family, model_id, version, kind: TREE|ENSEMBLE|LAYERED, truncated, nodes|trees|layers, source_file_sha256}` | sesja; `family` z listy; plik tylko z rejestru (bez dowolnych ścieżek, bez wczytywania pickle z zewnątrz) | limity węzłów; 404 gdy brak artefaktu | struktura == artefakt (liczba węzłów, progi) | tylko nowa trasa |
| N4 (etap 3) | `GET /api/v1/flow-context/markov/paths?n=` | próbka trajektorii MC z rzeczywistego wykonania (to samo ziarno) | `{n_paths_total, sample:[[...]], quantiles, seed, as_of}` | sesja; `n ≤ 200` | 404 gdy model niegotowy | zgodność kwantyli próbki z pełną symulacją | rozszerzenie istniejącego modułu |
| N5 (etap 4, po D3) | `POST /api/v1/models/{family}/{model_id}/approve-live`, `POST …/reject` | ręczna akceptacja LIVE zamiast auto-promocji | `{confirm: "LIVE <model_id>"}` → `{status, previous, audit_id}` | sesja + CSRF + fraza; zapis w `settings_audit` | 409 gdy model nie przeszedł walidacji | brak auto-promocji po treningu; rollback | zmiana zachowania `ml` i `sh_tp_model` – osobna akceptacja |
| N6 (etap 4) | `GET /api/v1/ui/alerts`, `POST /api/v1/ui/alerts/{id}/ack` | alerty ze statusem (otwarty / potwierdzony / rozwiązany) na bazie `app_events` | lista + osobna tabela statusów | sesja + CSRF | – | brak wpływu na handel | nowa tabela (migracja) |

## 5. WebSocket – zasady dla nowych paneli

* Jedno istniejące połączenie (`LiveSocket` w `api.ts`), jeden store – nowe panele czytają `useStore()`; zdarzenia `sh`, `signal`, `zones`,
  `trade_settled` mogą zostać dodane do reducera (kompatybilnie – nieznane typy są dziś ignorowane).
* Duplikaty i luki już obsługiwane (`seq`, `boot_id`, `resync`). Nowe: walidacja kształtu payloadu przed zapisem do store
  (odrzucenie z wpisem diagnostycznym, bez wyjątku w UI).
* `stale`: po `ws ≠ OPEN` lub po przekroczeniu progu wieku danych; po ponownym połączeniu dane pozostają `stale` do pierwszego `resync`.
