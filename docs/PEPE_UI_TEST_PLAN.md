# PEPE_UI_TEST_PLAN – checklista testów nowych paneli (Etap 0)

Narzędzia – wyłącznie istniejące w projekcie (bez nowego frameworka testowego):
* **Frontend statycznie**: `cd frontend && npm run typecheck` (`tsc -b`, strict, `noUnusedLocals/Parameters`), `npm run build` (Vite).
* **UI w przeglądarce**: `unittest` + Playwright (Chromium) na backendzie demo (symulator terminala) – wzorzec `tests/test_ui_*.py`.
* **Backend / kontrakty**: `unittest` (`tests/test_*.py`), klient HTTP z sesją jak w `tests/test_app_process.py`.
* **Pełna regresja**: `python tools/run_tests.py` (z `MQ_CANDLES_PYTHON` wskazującym `.venv_candles`, żeby nie pominąć `tests/gold_candles`).
* **Lint**: brak w repo – decyzja D7 (domyślnie `tsc` strict jako bramka).

Zasady: test nieuruchomiony nie jest „zaliczony”; testy egzekucji tylko na symulatorze / mockach / PAPER – **nigdy rachunek LIVE**;
wartości testowe sekretów tylko z listy fikcyjnych wartości używanych już w testach.

Statusy w kolumnie „Stan”: `ISTNIEJE` (test już jest i przechodzi), `PLAN` (do napisania w podanym etapie), `OK (n)` (test napisany
w etapie n i uruchomiony z wynikiem pozytywnym), `CZĘŚCIOWO (n)` (pokryta tylko opisana część – reszta wskazana w kolumnie).

## 1. Bazowa regresja (przed każdym etapem i po nim)

| Sprawdzenie | Polecenie / test | Stan |
|---|---|---|
| typecheck | `npm run typecheck` | ISTNIEJE (exit 0 w etapie 0) |
| build | `npm run build` | ISTNIEJE |
| stare trasy renderują się | `test_ui_pages`, `test_ui_monitor`, `test_nc_panel`, `test_ui_lab`, `test_ui_analytics`, `test_ui_signal_card`, `test_ui_setup_panel`, `test_ui_scalp` | ISTNIEJE (wynik bazowy w PEPE_UI_AUDIT §15) |
| proces aplikacji, sesja, WS resync | `test_app_process` | ISTNIEJE |
| pełny zestaw | `tools/run_tests.py` | ISTNIEJE (895 OK / 4 pominięte w ostatnim pełnym przebiegu) |

## 2. Frontend – shell i routing (etap 1)

| # | Przypadek | Test | Stan |
|---|---|---|---|
| F1 | `#/trading-intelligence`, `#/ai-neural-lab`, `#/system-control` renderują się w nowym shellu | `test_ui_terminal_shell` test_01 | OK (1) |
| F2 | wszystkie dotychczasowe trasy nadal renderują się w starym shellu; link „Istniejące widoki” działa | `test_ui_terminal_shell` test_02 + `test_ui_pages` | OK (1) |
| F3 | sidebar: zwijanie/rozwijanie, stan zapamiętany po przeładowaniu, `aria-expanded` | `test_ui_terminal_shell` test_05 | OK (1) |
| F4 | header: środowisko z backendu (demo → `SYNTHETIC`, brak rachunku → `UNKNOWN`), nigdy wartość domyślna z UI | `test_ui_terminal_shell` test_03 | CZĘŚCIOWO (1): `SYNTHETIC` i `HISTORY` (`as_of`) w przeglądarce; `LIVE` / `DEMO` / `UNKNOWN` tylko w kodzie `envOf` – backend demo zawsze zgłasza symulator, a w repo nie ma testów jednostkowych frontendu |
| F5 | status MT5 i panel szczegółów z `state.connection` (stan, heartbeat, epoka, błąd); bez połączenia z backendem MT5 = `UNKNOWN` | `test_ui_terminal_shell` test_03, test_04, test_10 | OK (1) |
| F6 | stany `loading / empty / error / stale / disconnected / permission denied` – każdy komponent wyświetla się dla odpowiedniego wejścia (wymuszenie przez przechwycenie żądań w Playwright: 500, 401, brak WS) | `test_ui_terminal_shell` test_01, test_10 | CZĘŚCIOWO (1): `empty` (sekcje „nie zintegrowane”) oraz `disconnected` / `stale` (brak WS → `data-stale=1`, ostrzeżenie, MT5 `UNKNOWN`); `loading / error / permission denied` – komponenty są, ale w etapie 1 panele nie pobierają danych, więc nie ma czego przechwycić (500 / 401) → **etap 2** |
| F7 | wartości nieznane jako `N/A` / `UNKNOWN`, nie `0` | `test_ui_terminal_shell` test_04, test_06 | OK (1) |
| F8 | klawiatura: skip-link jako pierwszy element, Enter przenosi fokus do treści; kolejność DOM: header → sidebar → treść; widoczny fokus | `test_ui_terminal_shell` test_07 | OK (1) |
| F9 | responsywność: 1600×1000, 1366×768, 760×900, 390×844 – brak poziomego przewijania strony, sidebar zwinięty na wąskim ekranie, nagłówek w jednym wierszu od 1366 px | `test_ui_terminal_shell` test_08 | OK (1) |
| F10 | brak błędów konsoli na nowych trasach | `test_ui_terminal_shell` test_01, test_09 | OK (1) |
| F11 | jedno połączenie WS po nawigacji między starymi i nowymi trasami (liczba otwartych WebSocket = 1) | `test_ui_terminal_shell` test_09 | OK (1) |

## 3. Integracja – kontrakty (etap 2 i dalej)

| # | Przypadek | Test | Stan |
|---|---|---|---|
| I1 | kontrakty REST używane przez nowe panele zwracają oczekiwane pola (candles, zones/map, sh, eval/assessments, stats, decision) | nowy `test_ui_contracts` (HTTP z sesją) | PLAN (2) |
| I2 | WS: obsługa duplikatów (`seq ≤ last`), luki → `resync`, ponowne połączenie; nieznany typ zdarzenia ignorowany | `test_app_process` (istnieje) + test reducera | ISTNIEJE / PLAN (2) |
| I3 | walidacja payloadu: niepoprawny kształt odrzucony z diagnostyką, UI bez wyjątku | `test_ui_terminal_shell` (wstrzyknięte zdarzenie) | PLAN (2) |
| I4 | timeouty i błędy: 500 / 401 / brak odpowiedzi → stany z §2 | Playwright route interception | PLAN (2) |
| I5 | zgodność timestampów: czasy na wykresach = czasy z backendu (strefa czasowa UI tylko prezentacyjna) | istniejące testy wykresów + nowy | ISTNIEJE / PLAN (2) |
| I6 | rozróżnienie LIVE / DEMO / SYNTHETIC / HISTORY (mapowanie D2) | test jednostkowy funkcji mapującej + UI | PLAN (1) |
| I7 | brak fikcyjnych wartości: przy braku źródła panel pokazuje stan, nie liczby (skan DOM pod kątem `0` w polach bez danych) | `test_ui_terminal_shell` | PLAN (1–2) |
| I8 | zmiana instrumentu aktualizuje wszystkie 4 wykresy (wg D1) | `test_ui_trading_intel` | PLAN (2) |
| I9 | statusy sygnałów: mapowanie z PEPE_UI_API_MAP §2.3, status źródłowy widoczny obok; `EXECUTED` tylko przy `execution_state = WYKONANO` | test jednostkowy N2 + UI | PLAN (2) |

## 4. AI Neural Lab (etap 3)

| # | Przypadek | Test | Stan |
|---|---|---|---|
| A1 | struktura Decision Tree == `tree_structure.json` (liczba węzłów, cechy, progi, liście) | test N3 | PLAN (3) |
| A2 | XGBoost: liczba drzew / limit, węzły z `get_dump` zgodne z modelem | test N3 | PLAN (3) |
| A3 | Random Forest: widok `MISSING`, żadnej wygenerowanej struktury | UI | PLAN (3) |
| A4 | NSS: warstwy zgodne z manifestem; impulsy tylko z telemetrii; bez telemetrii – etykieta `Illustrative visualization` | UI + test jednostkowy | PLAN (3) |
| A5 | Monte Carlo: liczba ścieżek i kwantyle z odpowiedzi backendu (N4 zgodne z pełną symulacją) | test N4 | PLAN (3) |
| A6 | Replay nie pokazuje danych późniejszych niż wybrany czas | UI + `as_of` | PLAN (3) |
| A7 | limit węzłów, stabilność pamięci (10 przełączeń sceny bez wzrostu liczby kontekstów WebGL) | Playwright (`performance.memory`, liczba canvasów) | PLAN (3) |
| A8 | zwalnianie zasobów: po odmontowaniu brak aktywnego `requestAnimationFrame` i listenerów | Playwright | PLAN (3) |
| A9 | metryki z potwierdzonym źródłem (raport treningu, ID modelu) | UI | PLAN (3) |
| A10 | rozmiar chunku 3D mierzony; strony bez 3D nie ładują chunku | build + Playwright (lista żądań) | PLAN (3) |

## 5. Ryzyko i egzekucja (etapy 2 i 4)

| # | Przypadek | Test | Stan |
|---|---|---|---|
| R1 | UI nie omija walidacji backendu: wysłanie z pominięciem podglądu zwraca błąd backendu | `test_risk_execution` (gateway) + nowy UI | ISTNIEJE / PLAN (2) |
| R2 | otwarcie Order Preview **nie** wysyła zlecenia (brak POST `/execute` / `/manual/intents/*/execute` w ruchu sieciowym) | Playwright | PLAN (2) |
| R3 | LIVE wymaga osobnego potwierdzenia (`LIVE <login>` sprawdzane w backendzie) | `test_risk_execution` | ISTNIEJE |
| R4 | utrata MT5 blokuje nowe operacje (UI + backend) | `test_bridge_engine` / `test_risk_execution` + nowy UI | ISTNIEJE / PLAN (4) |
| R5 | reconnect wymaga ponownej walidacji (`session_epoch`) | `test_risk_execution` | ISTNIEJE |
| R6 | wynik UNKNOWN nie jest ponawiany; UI pokazuje „niejednoznaczny – uzgadnianie” | `test_risk_execution`, `test_sh_risk_state` + nowy UI | ISTNIEJE / PLAN (2) |
| R7 | testy na symulatorze / PAPER – zakaz rachunku LIVE (asercja `synthetic` w setUp nowych testów) | wszystkie nowe testy egzekucji | PLAN (2) |
| R8 | logi i decyzje bez sekretów | `test_agent`, `test_app_process` | ISTNIEJE |
| R9 | trening nie wdraża modelu LIVE bez zatwierdzenia | **obecnie niespełnione** dla `ml` i `sh_tp_model` (audyt §9) – test po decyzji D3 | PLAN (4) |
| R10 | idempotencja (podwójne kliknięcie → `DUPLICATE`) | `test_risk_execution` + nowy UI | ISTNIEJE / PLAN (2) |

## 6. Regresja końcowa (etap 5)

| # | Przypadek | Stan |
|---|---|---|
| G1 | wszystkie stare trasy i podstawowe funkcje | PLAN (5) |
| G2 | niezmienione kontrakty: porównanie listy tras i kształtu odpowiedzi przed/po (`app.routes` + próbki odpowiedzi) | PLAN (5) |
| G3 | migracje (jeśli N6) – nowa baza i baza z poprzedniej wersji | PLAN (4–5) |
| G4 | stary UI otwiera się niezależnie od nowego; rollback = revert commitów etapów | PLAN (5) |
| G5 | pełny `tools/run_tests.py` z `.venv_candles`, build produkcyjny, paczka | PLAN (5) |
