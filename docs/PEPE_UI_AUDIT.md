# PEPE_UI_AUDIT – Etap 0 (audyt repozytorium) dla Trading Intelligence / AI Neural Lab / System Control Center

Specyfikacja nadrzędna: [PEPE_UI_IMPLEMENTATION_SPEC.md](PEPE_UI_IMPLEMENTATION_SPEC.md). Pozostałe dokumenty etapu 0:
[PEPE_UI_API_MAP.md](PEPE_UI_API_MAP.md), [PEPE_UI_IMPLEMENTATION_PLAN.md](PEPE_UI_IMPLEMENTATION_PLAN.md), [PEPE_UI_TEST_PLAN.md](PEPE_UI_TEST_PLAN.md).

Data audytu: 26.10.2026. Środowisko audytu: kontener Linux, terminal MT5 **niedostępny** – działanie sprawdzane w kodzie, testami offline
i na symulatorze terminala (`--demo`, dane syntetyczne). Żaden kod funkcjonalny nie został zmieniony w tym etapie.

**Legenda statusów** (zgodnie ze specyfikacją §1):
`EXISTS_VERIFIED` – kod + test, który go wykonuje; `EXISTS_UNVERIFIED` – kod istnieje, brak testu potwierdzającego działanie w tej
roli; `MISSING` – brak implementacji; `BLOCKED` – wymaga decyzji, danych lub infrastruktury.

---

## 1. Repozytorium

| Element | Stan |
|---|---|
| Branch | `claude/masterquo-ai-bot-mt5-f7uaht` |
| Commit bazowy | `161950b` (wersja 1.22.0) |
| Niezapisane zmiany na starcie | brak (czyste drzewo) |
| Katalog `data/` | lokalne dane uruchomieniowe, w `.gitignore` – nie trafiają do repo ani paczki |

## 2. Struktura i wersje

| Część | Ścieżka | Technologia (potwierdzona) |
|---|---|---|
| Backend bota | `backend/masterquo/` | Python 3.13 (Windows: 3.13, fallback 3.12), FastAPI + uvicorn, SQLite, numpy, scikit-learn, xgboost; zależności przypięte z hashami w `requirements/requirements-win.txt` |
| Izolowany runtime prognoz | `backend/gold_candles_runtime/` | osobne środowisko `.venv_candles` (`requirements/requirements-candles-win.txt`), uruchamiane jako proces potomny |
| Frontend | `frontend/` | React 19.3, Vite 8.2, TypeScript 6.0 (`strict`, `noUnusedLocals`, `noUnusedParameters`), lightweight-charts 5.2.1; **bez** biblioteki komponentów, bez biblioteki routingu, **bez Three.js / WebGL** |
| Narzędzia build | Node 22 / npm 10 (tylko do budowania) | paczka klienta zawiera zbudowany `frontend/dist` – klient nie potrzebuje Node |
| Launcher | `tools/launcher/` (Go) → `PepeMarketWizard.exe` | instalacja, trening, diagnostyka, start |
| MQL5 | `mql5/` | eksportery i wskaźniki referencyjne |

## 3. Uruchomienie, build, testy, lint

| Czynność | Polecenie | Status |
|---|---|---|
| Start bota | `03_START_MASTERQUO.bat` → `python -m masterquo serve` (port z `config.server.port`, domyślnie 8765, tylko 127.0.0.1) | `EXISTS_VERIFIED` (`test_app_process`) |
| Start na danych syntetycznych | `07_START_DEMO_DANE_SYNTETYCZNE.bat` → `serve --demo` | `EXISTS_VERIFIED` |
| Build frontendu | `cd frontend && npm run build` (`tsc -b && vite build`) | `EXISTS_VERIFIED` (wykonane w tym etapie: typecheck OK) |
| Typecheck | `npm run typecheck` | `EXISTS_VERIFIED` (exit 0) |
| Testy offline | `python tools/run_tests.py` (unittest discover `tests/test_*.py` + `tests/gold_candles` przez `.venv_candles`) | `EXISTS_VERIFIED` – ostatni pełny przebieg: 895 testów OK, 4 pominięte (ONNX, OpenCL, 2× brak `.venv_candles`) |
| Testy UI | `tests/test_ui_*.py`, `test_nc_panel.py` – Chromium (Playwright) na backendzie demo | `EXISTS_VERIFIED` (bazowy przebieg – §15) |
| **Lint** | brak ESLint / ruff / flake8 w repo; rolę statycznej kontroli pełni `tsc` w trybie strict | `MISSING` (decyzja D7) |

## 4. Frontend: routing, shell, store, błędy

| Wymaganie | Implementacja | Status |
|---|---|---|
| Router | `frontend/src/router.ts` – routing hashem (`#/<strona>`), 22 strony w 7 grupach + `#/nc` (osobny panel Neural Cyberpunk, 12 ekranów); stare linki zachowane | `EXISTS_VERIFIED` (`test_ui_pages`) |
| AppShell | `components/layout/AppShell.tsx` – nagłówek, menu grupowe, panele boczne (Pozycje/Logi), baner awarii | `EXISTS_VERIFIED` |
| Globalny store | `store.tsx` – jeden `useReducer` + **jedno** połączenie WebSocket (`LiveSocket`), pełny refresh co 30 s i po powrocie karty | `EXISTS_VERIFIED` |
| Klient API | `api.ts` – sesja, CSRF w `X-MQ-CSRF` dla zmian stanu, `ApiError(status)` | `EXISTS_VERIFIED` |
| Obsługa błędów | ekran „Nie można połączyć się z backendem”, baner danych syntetycznych, `DemoFlag`, stany per panel (różne konwencje) | `EXISTS_UNVERIFIED` – brak wspólnego komponentu stanów loading/empty/error/stale/disconnected/permission |
| Motywy | `theme.tsx` – 5 presetów (gold – domyślny, matrix, dark, light, contrast) + edytor tokenów | `EXISTS_VERIFIED` |
| Dostępność | `focus-visible` (3 reguły), `prefers-reduced-motion` (1 reguła + `appearance.tsx`), ~100 atrybutów `aria-*`/`role` | `EXISTS_UNVERIFIED` – brak testów klawiatury/fokusu |

## 5. Backend: REST, WebSocket, uwierzytelnianie

| Wymaganie | Implementacja | Status |
|---|---|---|
| REST | 252 trasy `/api/v1/*` w `backend/masterquo/api/app.py`; wersja kontraktu `API_CONTRACT_VERSION` | `EXISTS_VERIFIED` (wiele testów API) |
| WebSocket | `/api/v1/ws` – ~44 typy zdarzeń (`quote`, `connection`, `account`, `positions`, `decision`, `analysis`, `log`, `bar_closed`, `mode`, `orders`, `execution_lock`, `zones`, `sh`, `signal` …); każde zdarzenie ma `seq` i `boot_id` | `EXISTS_VERIFIED` |
| Reconnect / duplikaty | klient odrzuca `seq <= last_seq`, przy luce żąda `resync`, ponawia połączenie z opóźnieniem | `EXISTS_VERIFIED` (`test_app_process` – resync z `last_seq`/`boot_id`) |
| Zdarzenia nieobsługiwane przez store | `sh`, `signal`, `zones`, `liquidity`, `structure_intelligence`, `trade_settled`, `extind`, `ml_scalp` – ekrany używają odpytywania REST | `EXISTS_UNVERIFIED` (działa, ale bez walidacji payloadu w kliencie) |
| Uwierzytelnianie | serwer tylko na 127.0.0.1; ciasteczko sesji + CSRF wymagane dla każdego `/api/v1/*` poza `/health`; kontrola `Host`/`Origin` dla WS; CSP; brak CORS | `EXISTS_VERIFIED` (`test_app_process`, testy API) |
| Autoryzacja / role | jeden lokalny użytkownik; brak ról | `MISSING` (zgodne z architekturą lokalną – stan „permission denied” = odpowiedzi 401/403/409 backendu) |
| Walidacja payloadów | modele Pydantic dla żądań POST/PUT; odpowiedzi bez schematu w kliencie | `EXISTS_UNVERIFIED` po stronie klienta |

## 6. Dane rynkowe

| Wymaganie | Implementacja | Status |
|---|---|---|
| OHLC M1–MN1 (w tym M30, H8) | `mt5/bridge.py` (bufory zamkniętych świec + świeca formująca się osobno), `GET /api/v1/candles?tf=` dla **aktywnego** instrumentu | `EXISTS_VERIFIED` (`test_bridge_engine`, `test_time_and_data`) |
| OHLC dowolnego symbolu (tylko podgląd) | `GET /api/v1/markets/chart?symbol=&tf=` (bez nakładek silnika) | `EXISTS_VERIFIED` (`test_markets_signals`) |
| Instrumenty | `XAUUSD` i `BTC` (identyfikator wewnętrzny; symbol brokera rozpoznawany z terminala, np. `BTCUSD`). Specyfikacja używa nazwy `BTCUSDT` – w bocie nie ma takiego identyfikatora | `EXISTS_VERIFIED` (decyzja D1: nazewnictwo w UI) |
| **Jeden aktywny instrument** | silnik, bufory i strategie pracują na jednym aktywnym instrumencie; `POST /api/v1/assets/active` przełącza go, **resetuje tryb wykonania** (`ACTIVE_ASSET_CHANGED`) i wymusza ponowne połączenie | `EXISTS_VERIFIED` – **konsekwencja dla „globalnego wyboru instrumentu” (D1)** |
| Ticki / kwotowanie | zdarzenie `quote` (bid, ask, czas, wiek); `ticks_range` (COPY_TICKS_INFO = kwotowania, bez strony agresora) | `EXISTS_VERIFIED` |
| Wolumen | tylko `tick_volume` (aktywność); `real_volume` = 0 dla CFD; order flow / footprint / arkusz = brak | `EXISTS_VERIFIED` (źródło jawnie oznaczane) |
| Sesje | `analytics/session_engine.py` (strefy IANA, DST), boksy sesji, sweepy | `EXISTS_VERIFIED` (`test_liquidity`, `test_zones`) |
| Strefy / S/R / płynność | mapa stref PMW 1.22 (`zones/`), S/R H1+ (`analysis/levels.py`), walls, heatmapa likwidacji (zewnętrzny dostawca, wymaga klucza) | `EXISTS_VERIFIED`; heatmapa: `BLOCKED` bez klucza dostawcy |
| Poziomy wejścia / SL / TP na wykresie | plan silnika S01–S12 i SH na wykresach (`ChartPanel`) | `EXISTS_VERIFIED` (`test_ui_monitor`) |

## 7. Sygnały, statusy, wyniki modeli, konsensus

| Wymaganie | Implementacja | Status |
|---|---|---|
| Silnik sygnałów S01–S12 | `engine/active.py`, tracker setupów (`strategies/tracker.py`; stany terminalne `INVALIDATED`, `EXPIRED`, `MISSED_ENTRY`, `CANCELLED`, `ENTERED`) | `EXISTS_VERIFIED` (`test_strategies`, `test_active_pipeline`) |
| Kontrakt sygnału | `engine/signal_contract.py` – `MQ-SIGNAL-1.0.0`: `status` OCZEKIWANIE / POTWIERDZONY / ZABLOKOWANY / UNIEWAŻNIONY / WYGASŁY / BRAK_DANYCH, osobno `execution_state` BRAK / WYSŁANO / WYKONANO / ODRZUCONO; `probability_win` tylko ze skalibrowanego czempiona | `EXISTS_VERIFIED` (`test_signal_contract`) |
| SCALPING / HEDGING | `sh/` – oceny WAIT / READY / BLOCKED, plany, sygnały SH | `EXISTS_VERIFIED` (`test_sh_*`) |
| Ocena setupów (SHADOW) | `evaluation/` – ACCEPT / REDUCE / DEFER / REJECT z powodami, `zone_context`, wynik dojrzały z M1 | `EXISTS_VERIFIED` (`test_evaluation`, `test_zones`); **niepokazywana w UI** |
| Wyniki poszczególnych modeli przy sygnale | ML (gate ASSIST, `/api/v1/ml/predict`), SH `sh_tp_model`, NSS, prognozy świec, master models | `EXISTS_VERIFIED` per model; brak jednego widoku per sygnał |
| Konsensus / konflikty | `mm/fusion.py` – tablica dowodów: wyniki obok siebie, bez łączenia w jedną liczbę, `independence = SAME_PRICE_FEED`; w ocenie setupu `model_agreement = NO_INDEPENDENT_EVIDENCE` | `EXISTS_VERIFIED` (`test_mm_core`); **jedna liczba „konsensusu” celowo nie istnieje** |
| Statusy prezentacyjne specyfikacji (NEW … UNKNOWN) | brak – istnieją statusy domenowe powyżej | `MISSING` – mapowanie do uzgodnienia (propozycja w API_MAP §2.3) |

## 8. Modele AI rzeczywiście obecne w repozytorium

| Model ze specyfikacji | Co jest w repo | Struktura dostępna do wizualizacji | Status |
|---|---|---|---|
| **Random Forest** | brak (`RandomForest*` nie występuje w kodzie) | – | `MISSING` |
| **XGBoost** | legacy ML (`ml/models.py: train_xgb`), scalp ML (`ml/scalp_task.py`), zadania lab | wkład cech TreeSHAP (`explain_xgb`, `pred_contribs`) – **tak**; zrzut drzew (`get_dump` / `trees_to_dataframe`) – **brak API** | `EXISTS_VERIFIED` (`test_ml`, `test_ml_scalp`); struktura drzew: `MISSING` (nowy endpoint, etap 3) |
| **Decision Tree** | legacy ML (`ml/models.py`), zapis `tree_structure.json` przy każdym modelu (`export_tree`), ścieżka decyzji (`explain_dt`) | węzły, progi, liście, udziały klas, ścieżka – **tak** (plik w artefakcie) | `EXISTS_VERIFIED` (`test_ml`); endpoint struktury: `MISSING` |
| **MLP** | `gold_candles_runtime/scalp_train.py` – `MLPClassifier(64, 32)` jako jeden z kandydatów prognoz scalp (proces `.venv_candles`) | warstwy z `coefs_` – tylko w procesie `.venv_candles`; brak API | `EXISTS_VERIFIED` w treningu (`tests/gold_candles/test_scalp_train.py`, wynik w §15); w UI: `MISSING` |
| **Sieci neuronowe (numpy)** | NSS `CAUSAL_MTF_TCN_V1` (`lab/nss.py`, `lab/scalp_net.py`) – zespół sieci TCN z **prawdziwą telemetrią warstw** z bieżącego przebiegu (średnia, odchylenie, frakcja aktywnych, heatmapa kanał × krok); ResNet1D i SEW-SNN (`lab/nets.py`); MiniRocket | warstwy + telemetria – **tak** (`/api/v1/lab/neural`, zdarzenie WS `lab_neural`) | `EXISTS_VERIFIED` (`test_nss`, `test_lab`, `test_minirocket`) |
| **Monte Carlo** | `lab/flow_context/markov.py` – symulacja ścieżek łańcucha Markowa (`n_paths` = 2048, ziarno stałe), kwantyle cen w horyzontach | liczba ścieżek, kwantyle – **tak** (`/api/v1/flow-context/markov`); trajektorie pojedyncze – brak w API | `EXISTS_VERIFIED` (`test_markov_reward`) |
| Inne | regresja logistyczna + GBR kwantylowe (gold_candles), HistGradientBoosting, GPR, HDC, Kalman, STE-FlowNet, S3CE/STFS (master models, SHADOW), modele Structure Intelligence | różnie | `EXISTS_VERIFIED` (testy modułów) |

## 9. Trening, walidacja, rejestr, wdrożenie

| Wymaganie | Implementacja | Status |
|---|---|---|
| Pipeline treningu | `training/` (runner: plan, statusy, checkpoint, raport), `ml/trainer.py` (walk-forward z embargo), `lab/protocol.py`, `sh/train_cli.py`, `gold_candles_runtime/` | `EXISTS_VERIFIED` (`test_train_all`, `test_ml`, `test_sh_training`) |
| Rejestr wersji | `ml/registry.py` (CANDIDATE / CHALLENGER / CHAMPION / RETIRED / REJECTED / RESEARCH_APPROX), rejestr SH (`training/panel.py`), rejestr lab, rejestr NSS | `EXISTS_VERIFIED` |
| Rollback | `/api/v1/ml/rollback`, `/api/v1/training/rollback`, `/api/v1/lab/neural/rollback`, `/api/v1/mm/rollback` | `EXISTS_VERIFIED` |
| „Środowisko testowe” | odpowiednik: tryb **SHADOW** (model liczy, nie wpływa na zlecenia) | `EXISTS_VERIFIED` |
| **Brak automatycznej podmiany modelu produkcyjnego** | **niespełnione dla 2 rodzin**: legacy ML – `ml/registry.py:111` automatycznie promuje CHAMPION po treningu, jeśli reguły są spełnione (wpływ na decyzje tylko w trybie ML ASSIST); `sh_tp_model` – `sh/tpmodel.py:136` promuje po treningu na danych rzeczywistych, a model **bezpośrednio** bramkuje READY strategii SCALPING/HEDGING (`sh/setup.py:238`). NSS i lab: aktywacja wyłącznie ręczna | `BLOCKED` – zmiana backendu wymaga osobnej akceptacji (decyzja D3) |
| Ręczna akceptacja LIVE dla modelu | nie istnieje jako osobny etap (promocja = od razu produkcja) | `MISSING` (kontrakt w etapie 4) |

## 10. MT5, tryby DEMO/LIVE, egzekucja, ryzyko

| Wymaganie | Implementacja | Status |
|---|---|---|
| Kanał MT5 | `mt5/worker.py` – jedyny kanał do terminala, kolejka priorytetów, Execution Lock na każde wywołanie handlowe | `EXISTS_VERIFIED` (`test_bridge_engine`) |
| Status połączenia | stan (CONNECTING / CONNECTED / RECONNECTING …), przyczyna, `last_heartbeat`, `connected_since`, `session_epoch`, liczba prób, ostatnie błędy, offset zegara serwera | `EXISTS_VERIFIED` |
| Opóźnienie | tylko wiek kwotowania (`quote.age_seconds`) i `busy_waits`; brak pomiaru opóźnienia zapytań do terminala | `EXISTS_UNVERIFIED` (częściowe) |
| Rachunek DEMO / LIVE | `account.trade_mode` z terminala: DEMO / CONTEST / REAL; dane syntetyczne: `synthetic=true` | `EXISTS_VERIFIED` |
| Tryby wykonania | SIGNALS / PAPER / AUTO_DEMO / AUTO_LIVE; przejście na AUTO_LIVE wymaga wpisania `LIVE <login>` **sprawdzanego w backendzie**; AUTO_LIVE blokowane, gdy rachunek nie jest REAL lub dane są syntetyczne | `EXISTS_VERIFIED` (`test_risk_execution`, `test_ui_monitor`) |
| Bramki | Execution Lock, STOP, ścieżka główna (O1), wspólny strażnik portfela (1.21), silnik ryzyka, limity ekspozycji | `EXISTS_VERIFIED` (`test_risk_execution`, `test_finish_plan`, `test_leverage_sizing`) |
| Idempotencja | gateway: jedno wejście na (tryb, rachunek, setup) – UNIQUE w SQLite; ręczny pad: klucz `mode|account|context|intent|action|revision`, zapis PREPARED przed wywołaniem, timeout → UNKNOWN uzgadniany po tagu, **nigdy ponownie wysyłany** | `EXISTS_VERIFIED` (`test_risk_execution`, `test_sh_risk_state`) |
| Podgląd zlecenia + ponowna walidacja | ręczny pad: plan z TTL 5 s, intencja z wersją, świeże sprawdzenie bezpośrednio przed wysłaniem, wspólne `common_checks` (tryb, Lock, STOP, uzgodnienie, kwotowanie) | `EXISTS_VERIFIED` (`test_structure_intelligence.TestManualPad`, `TestManualPadRuntime`, `test_ui_lab`) – **podstawa Order Preview** |
| Po rozłączeniu | `session_epoch`: plan/decyzja z poprzedniej epoki są nieważne; nowe zlecenia dopiero po uzgodnieniu pozycji w nowej epoce | `EXISTS_VERIFIED` (`test_risk_execution`, `test_bridge_engine`) |

## 11. Transakcje, pozycje, statystyki, baza

| Wymaganie | Implementacja | Status |
|---|---|---|
| Pozycje / zlecenia | `managed_positions`, `order_attempts`, `sh_plans`, zdarzenia `positions`, `orders`; transakcje z terminala (`deals`) | `EXISTS_VERIFIED` |
| Historia transakcji | `trades` (PAPER / AUTO_DEMO / AUTO_LIVE osobno), `paper_account`, `equity_snapshots` | `EXISTS_VERIFIED` |
| Statystyki | `stats.py` + `GET /api/v1/stats?mode=` – definicje w odpowiedzi; ROI metodą Dietza (wpłaty ≠ zysk), PF, expectancy w R z błędem standardowym, max DD, per strategia, per miesiąc | `EXISTS_VERIFIED` (`test_stats_definitions`, `test_finish_plan`) |
| Filtry zakresu dat / instrumentu | `equity_curve(days)`; brak filtrów dat w `/stats` | `MISSING` (częściowo) |
| Baza i migracje | SQLite, ~75 tabel, migracje plikowe `db/migrations` + `schema_migrations`; kopia konfiguracji przed migracją | `EXISTS_VERIFIED` |

## 12. Logi, metryki, health, odzyskiwanie

| Wymaganie | Implementacja | Status |
|---|---|---|
| Logi | `app_events` (poziom, kategoria, kod, komunikat, dane) + strumień WS `log`; `GET /api/v1/logs` (UI pokazuje tylko 120 ostatnich wpisów z WS) | `EXISTS_VERIFIED`; status alertu (otwarty/rozwiązany): `MISSING` |
| Sekrety w logach | maskowanie, testy, że klucze nie są zwracane ani logowane | `EXISTS_VERIFIED` (`test_agent`, `test_app_process`) |
| Health | `GET /api/v1/health` (bez sesji): wersja, kontrakt, `boot_id`, `synthetic`, stan MT5 | `EXISTS_VERIFIED` |
| Metryki | latencje modułów analitycznych (`/api/v1/analytics/diagnostics`), czasy cyklu, statusy serwisów | `EXISTS_VERIFIED` (częściowo) |
| Odzyskiwanie | auto-reconnect mostu, uzgodnienie pozycji per epoka, `resync` WS, idempotentne zdarzenia stref, wznawianie treningu z checkpointu | `EXISTS_VERIFIED` |

## 13. 3D i wykresy

| Wymaganie | Implementacja | Status |
|---|---|---|
| Biblioteka wykresów | lightweight-charts 5.2.1 + własne prymitywy (`zones.ts`: strefy, boksy ograniczone w czasie, markery) | `EXISTS_VERIFIED` |
| Komponenty 3D | **brak** (brak `three`, `@react-three/fiber`, WebGL). Jest Canvas 2D: `nc/NeuralBrain.tsx` (sieć dekoracyjna **oznaczona jako dekoracja** + neurony modułów z rzeczywistego rejestru), heatmapa płynności, wskaźniki kontekstowe | `MISSING` (3D) |

## 14. Wydajność i kompatybilność

* Bundle: jeden plik JS 975 KB (294 KB gzip), ostrzeżenie Vite > 900 KB. Biblioteki 3D (Three.js ≈ 600 KB min., React Three Fiber,
  drei) **muszą** być ładowane leniwie (osobny chunk tylko dla AI Neural Lab), inaczej spowolnią wszystkie strony.
* React 19 wymaga `@react-three/fiber` w wersji 9 (wersja 8 obsługuje React 18).
* Wiele paneli odpytuje REST niezależnie (np. 8 wykresów × mapa stref na każdy cykl analizy) – nowy pulpit 2×2 powinien współdzielić dane.
* Klient Windows otrzymuje gotowy `dist` – nowe zależności npm zwiększają tylko rozmiar paczki, nie wymagania instalacji.
* Dwa interfejsy już istnieją (klasyczny i Neural Cyberpunk); nowe panele dodają trzecią warstwę – stare trasy pozostają bez zmian.

## 15. Testy wykonane w etapie 0

| Polecenie | Wynik |
|---|---|
| `cd frontend && npm run typecheck` | exit 0 |
| testy UI i procesu aplikacji (`test_ui_pages`, `test_ui_monitor`, `test_nc_panel`, `test_ui_lab`, `test_ui_analytics`, `test_ui_signal_card`, `test_ui_setup_panel`, `test_ui_scalp`, `test_app_process`) | 64 testy: 61 OK, 3 niepowodzenia w przebiegu równoległym z dwoma innymi ciężkimi zestawami (brak świec M1 w chwili zapytania, zadanie lab > 600 s, panel FFT bez danych). **Powtórzone osobno w etapie 1:** `test_ui_lab` i `test_app_process` OK (przyczyna: obciążenie CPU); `test_ui_analytics` ujawnił rzeczywisty wyścig w bibliotece formacji (status `COMPLETED` zapisywany przed raportem, panel kończył odpytywanie i mógł nie pokazać raportu) – poprawka `854f611`, potem 4/4 OK |
| `tests/gold_candles` z `.venv_candles` (w tym trening MLP) | 39 testów: 38 OK, `test_scalp_train` – `setUpClass` przekroczył limit 1800 s przy równoległym obciążeniu; powtórzony osobno: 10/10 OK w 244 s |
| ostatni pełny `tools/run_tests.py` (commit `6bca89e`, kod jak w `161950b`) | 895 testów OK, 4 pominięte; gold_candles w tamtym przebiegu: `SKIPPED_NO_CANDLE_ENV` |

## 16. Decyzje wymagane przed implementacją

| ID | Decyzja | Etap |
|---|---|---|
| D1 | Globalny wybór instrumentu: (a) tylko podgląd (wykresy z `markets/chart`, bez zmiany pracy bota) czy (b) przełączenie aktywnego instrumentu bota (reset trybu, ponowne połączenie, potwierdzenie). Nazwa w UI: `BTC` (identyfikator bota) zamiast `BTCUSDT` | 1–2 |
| D2 | Mapowanie środowiska: LIVE = rachunek REAL, DEMO = DEMO/CONTEST, `SYNTHETIC` (symulator) jako jawny osobny stan, HISTORY = widoki „as of” / replay, w pozostałych przypadkach UNKNOWN | 1 |
| D3 | Auto-promocja `ml` i `sh_tp_model` sprzeczna ze specyfikacją §5.5 – czy zmienić backend na „kandydat → ręczna akceptacja” | 4 |
| D4 | Random Forest nie istnieje: pokazywać jako `MISSING` czy dodać model (nowy model = osobna decyzja, poza zakresem UI) | 3 |
| D5 | Order Preview: intencja ręcznego padu (źródło `MANUAL_USER`) wypełniona poziomami sygnału – bez nowej ścieżki wysyłania | 2 |
| D6 | Zależności 3D: `three` + `@react-three/fiber@9` + `@react-three/drei`, leniwie ładowane | 3 |
| D7 | Lint: `tsc` strict jako bramka czy dodanie ESLint (tylko narzędzie deweloperskie) | 1 |
| D8 | Motyw nowego shella (grafit/szmaragd) ograniczony do nowych tras; stary UI zachowuje swój motyw | 1 |
