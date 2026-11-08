# 1.36 – Main Menu V2 (8 wież) + wnętrza wież PEPE$WTC V4 i PEPE$SIGNAL V1: raport wdrożenia

Źródła zadania (kopie w `referencje/`): `MENU_V2_CLAUDE_CODE_PROMPT.md`, `PEPE_WTC_V4_MASTERPROMPT.md`, `PEPE_SIGNAL_V1_MASTERPROMPT.md`
oraz obrazy referencyjne (`*_referencja.webp`). Zrzuty działającej aplikacji (backend demo, symulator MT5): `zrzuty/`.

## 1. Mapa przed zmianami (audyt)

| Element | Stan przed 1.36 | Decyzja |
|---|---|---|
| Stack UI | React 19 + Vite, routing hash (`router.ts`), jeden WebSocket (`store.tsx`), wykresy `lightweight-charts` przez `ChartPanel` | bez zmian; nowe widoki jako leniwe chunki |
| Menu główne | Neural City V7 (7 wież, HUD Winratio/ROI/Equity, cytat, przyciski na dole) | zastąpione Menu V2 (8 wież), ten sam kontroler stanów i te same `data-testid` |
| PEPE$WTC | alias do Trading Intelligence | nowa wieża `#/pepe-wtc`; Trading Intelligence nadal pod `#/trading-intelligence` |
| PEPE$SIGNAL | alias do Wind Portal | nowa wieża `#/pepe-signal`; Wind Portal nadal pod `#/wind` |
| MT5 Bridge | `/api/v1/candles`, `/api/v1/markets/chart`, WebSocket | wykorzystany, bez nowego źródła cen |
| Kronos | `/api/v1/kronos`, `/kronos/forecast`, `/kronos/enable`, `/kronos/refresh` | wykorzystany |
| Strefy | `/api/v1/market-zones` (SR, DEMAND/SUPPLY, FVG, OB, EQH/EQL; compute + LIVE) | = AI Live Zones |
| Volume Profile | `/api/v1/svp/visible` (silnik PMW-SVP-1: POC, VAH/VAL, HVN, LVN) | = Volume Profile Auto Zones (bez nowego silnika) |
| Sygnały | `/api/v1/bot-signals`, `/api/v1/setups` (+ `/details`), `/api/v1/sh/signals` | jeden rejestr z deduplikacją po `signal_id` / `setup_id` |
| Modele | `/api/v1/models/predictions` (kontrakt PMW-PRED-2) | jedyne źródło ocen modeli |
| Execution Lock | wycofany w 1.24 (tryb wykonania + STOP + bramki ryzyka) | pokazywany uczciwie jako „wycofany”, nic nie jest zmieniane |

## 2. Zmienione / nowe pliki

| Plik | Zmiana |
|---|---|
| `frontend/src/features/neural-city/towers.ts` | 8 wież (identyfikatory z briefu), geometria sceny 1672×941, aliasy starych nazw |
| `frontend/src/features/neural-city/NeuralCityMenu.tsx`, `neural-city.css` | Menu V2: górny pasek z małym logo i 8 pozycjami, 8 wież-przycisków, 3 klikalnych Pepe, ścieżki neuronowe (bufor offscreen), portal; bez HUD i bez przycisków na dole |
| `frontend/src/features/towers/TowerFrame.tsx`, `towers.css` | wspólna rama wnętrz wież (nawigacja 8 wież, znacznik środowiska z terminala, zegar, pasek stanu) |
| `frontend/src/features/towers/WtcTower.tsx` | PEPE$WTC V4 |
| `frontend/src/features/towers/SignalTower.tsx`, `signals.ts`, `SignalChart.tsx` | PEPE$SIGNAL V1 |
| `frontend/src/features/towers/data.ts` | polling bez wyścigów, R:R, wiersze modeli, konsensus, MTF |
| `frontend/src/components/ChartPanel.tsx` | opcjonalne `overlay` (osobna warstwa linii/stref) i `layers` (sterowane warstwy 1.33); reakcja na zmianę filtrów warstw z zewnątrz – bez zmiany zachowania istniejących stron |
| `frontend/src/router.ts`, `App.tsx`, `features/cult/CultShell.tsx` | trasy `pepe-wtc` / `pepe-signal`, aliasy, mapa ekranów, menu boczne wież CULT |
| `frontend/public/assets/neural/neural-table-scene*.webp`, `assets/towers/*.webp` | grafiki z paczek (konwersja WebP bez zmiany kompozycji; sumy w `assets/neural/zrodla.json`) |
| `frontend/dist/` | przebudowany frontend |
| `tests/test_ui_neural_city.py` | dostosowany do 8 wież; test HUD zastąpiony testem „menu nie pobiera danych MT5” |
| `tests/test_ui_towers.py` | nowy: PEPE$WTC i PEPE$SIGNAL w przeglądarce |

Nowe zależności: brak. Backend: bez zmian.

## 3. Raport integracji – WORKING / PARTIAL / BLOCKED

### Menu V2
| Wymaganie | Status | Dowód / uwaga |
|---|---|---|
| Brak dawnych paneli i przycisków na dole | WORKING | test_04 (brak `nc-hud`, brak przycisków w dolnych 10 % ekranu) |
| Małe logo w lewym górnym rogu, nawigacja na górze | WORKING | test_04, `zrzuty/menu_1672.webp` |
| Trzech Pepe przy okrągłym stole, dokładnie 8 wież z osobną interakcją | WORKING (2.5D) | 8 przycisków, środek każdej tabliczki trafia we własną wieżę |
| Wieża i pozycja w pasku → ta sama sekcja | WORKING | test_04: `data-page` wieży = `data-page` paska dla wszystkich 8; pełna sekwencja SELECTED→…→NAVIGATE |
| Powrót z sekcji, klawiatura, Esc, fokus, ograniczenie ruchu | WORKING | test_05, test_07 |
| Brak pobierania danych MT5 przez menu | WORKING | test_06 |
| Niezależne modele 3D wież z obrotem, Pepe z rigiem | BLOCKED (brak assetów) | brak glTF wież i modelu Pepe z rigiem; obrót = pierścienie hologramu u podstawy, impuls Pepe = efekt nakładki – opisane w panelu ⓘ |

Zgodność z grafiką: MAE obszaru pod paskiem względem czystej sceny = **6,97** (`data/logs/ui_neural_city/compare.json`; próg testu 14).
Pozostałe różnice: font nawigacji (Inter/Segoe UI zależnie od systemu), tabliczki rysowane na żywo zamiast napisów z grafiki (stare nazwy WTC PEPE / BRAIN SIGNAL są zakryte).

### PEPE$WTC V4
| Wymaganie | Status | Dowód / uwaga |
|---|---|---|
| Duży wykres główny + wybór TF | WORKING | ChartPanel (świece z MT5 Bridge), test_01 |
| Dodawanie / usuwanie wielu wykresów, niezależny TF, klik = wykres główny | WORKING | test_01; do 8 wykresów, układ 2/3/4 w rzędzie |
| Niezależny **symbol** na każdym wykresie | PARTIAL | MT5 Bridge buforuje tylko aktywny instrument bota; zmiana instrumentu = istniejący przepływ `/api/v1/assets/active` (z potwierdzeniem w AUTO_DEMO/AUTO_LIVE) |
| Wszystkie dostępne indykatory | WORKING | EMA, VWAP (AVWAP M1/M5), RSI, MACD, ATR (odczyt), BOS/CHoCH, OB/FVG, sesje/sweepy, strefy M1–M30, mapa stref + profil sesji, strefy SVP, walls, SAR, IQ/PAL, poziomy AI |
| Bollinger Bands | BLOCKED | bot nie ma silnika BB – chip „BB · N/A”, nic nie jest symulowane |
| Kronos OFF / AUTO / MANUAL, M1 i M5, prognoza na wykresie, realny status | PARTIAL | OFF/AUTO = `/kronos/enable`; MANUAL = przeliczenie na żądanie `/kronos/refresh`; w domyślnych ustawieniach Kronos ma skonfigurowane M5/M15 – M1 pokazany jako „nie skonfigurowany”; bez zainstalowanego `.venv_kronos` status NOT_INSTALLED (brak prognozy, brak confidence) |
| Strefy ręczne i automatyczne (AI Live Zones) | WORKING | AUTO = LIVE silnika stref (przeliczenie na zamkniętej świecy), MANUAL = „Wyznacz teraz”; filtr typów na wykresie (S/D, OB, FVG, EQH/EQL, S/R) |
| Ręczne rysowanie / edycja stref | PARTIAL | edycja stref istnieje w SVP (`#/svp`, strefy MANUAL) i jest widoczna w PEPE$WTC przez warstwę „Strefy SVP”; edycja bezpośrednio na wykresie WTC nie została dodana |
| **Volume Profile Auto Zones** (POC, VAH/VAL, HVN, LVN) | WORKING | `/api/v1/svp/visible` dla okna wykresu (100/200/500 świec), TF wykresu lub własny, AUTO/MANUAL, przełączniki typów, lista stref, warstwa na wykresie; NO_DATA z przyczyną i ponowienie co 15 s; test_01 |
| Setup Builder, R:R, Execution, brak zlecenia | WORKING | R:R = \|TP−Entry\|/\|Entry−SL\|; brak przycisku zlecenia; test_01 |
| Live Setup Checklist | WORKING | checklista silnika (`/setups/{id}/details`) albo bramki decyzji |
| Sygnały LIVE, Model Consensus, MTF Matrix | WORKING | bot-signals, predykcje modeli (stan, wynik ≠ P), `tf_overview` silnika |

### PEPE$SIGNAL V1
| Wymaganie | Status | Dowód / uwaga |
|---|---|---|
| Zakładki z realną akcją | WORKING | CENTER/LIVE/HISTORY = filtry, ALL STRATEGIES = rejestr strategii, AI EVALUATION = pełna tabela modeli, PERFORMANCE = wyniki w R, SETUP BUILDER = istniejący widok `#/warunki/<id>` (lub PEPE$WTC) |
| Strumień ze wszystkich strategii, deduplikacja | WORKING | S01–S12 (silnik + skaner), SCALPING/HEDGING, źródła SHADOW; dedup po `signal_id` / `setup_id` |
| Filtry, wyszukiwanie, sortowanie, wirtualizacja | WORKING | strategia, symbol, TF, kierunek, status, przedział, siła, szukaj; lista wirtualna |
| Wybór aktualizuje cały środek i prawą kolumnę; brak nadpisania wyboru | WORKING | test_02 (lista i tabela), wybór w URL (`?id=`), odpowiedzi dla innego wyboru są odrzucane |
| Wykres sygnału: crosshair, zoom, pan, wolumen, Entry/SL/TP, przewinięcie do czasu setupu | WORKING | `/api/v1/markets/chart` własnego symbolu i TF sygnału |
| OB / FVG / liquidity / S/D na wykresie sygnału | PARTIAL | na wykresie sygnału rysowane są poziomy planu i strefa wejścia; pełne warstwy struktury są w PEPE$WTC |
| ENTRY / TRIGGER / INVALIDATION z definicji strategii | WORKING | grupy checklisty silnika (MET / NOT_MET / PENDING / UNKNOWN / INVALIDATED) z dowodem i czasem; dla sygnałów skanera – zapis planu sygnału (oznaczone) |
| WAIT nigdy jako BUY/SELL | WORKING | kandydaci i WAIT pokazani jako WAIT (+ kierunek scenariusza osobno); test_02 |
| Narracja z faktów | WORKING | zbudowana wyłącznie z warunków, planu i stanu modeli |
| Tabela: sortowanie, paginacja, filtry, oś zdarzeń | WORKING | detected → evaluated → confirmed → closed/invalidated |
| Ocena modeli: wersja, stan, timestamp, kierunek, semantyka wyniku | WORKING / PARTIAL | dla instrumentów bota (XAUUSD/BTC); dla symboli ze skanera – UNAVAILABLE; wyniki nieskalibrowane nie są nazywane prawdopodobieństwem |
| Konsensus | WORKING | modele READY z kierunkiem, wagi równe (bot nie konfiguruje wag), konflikt oznaczony |
| Historyczna ocena modeli z chwili sygnału | BLOCKED | ledger ocen (`/api/v1/quant/assessment`) jest pusty bez wytrenowanego meta-modelu; panel oznacza oceny jako BIEŻĄCE dla sygnałów historycznych |
| Animacje (fala nowego potwierdzenia, alert unieważnienia, przejścia 150–250 ms, reduced motion) | WORKING | |

Brak żądań handlowych z obu wież: testy sprawdzają, że żadne żądanie inne niż GET nie dotyczy zleceń ani trybu (jedyne POST-y to Kronos enable/refresh, strefy compute/live i zmiana instrumentu – istniejące, analityczne).

## 4. Testy

| Zestaw | Wynik |
|---|---|
| `test_ui_neural_city` (menu V2) | 9/9 OK (2 przebiegi) |
| `test_ui_towers` (nowy) | 3/3 OK |
| `test_ui_cult`, `test_ui_wizard` | 12/12 OK |
| `test_ui_pmw133`, `test_ui_terminal_shell`, `test_ui_pages`, `test_ui_chart_prefs`, `test_ui_market_zones`, `test_ui_interface_129` | OK (po poprawce kolejności stron w grupach menu bocznego); `test_ui_terminal_shell.test_03` raz niestabilny czasowo (świeżość danych), w powtórkach OK |
| `test_ui_kronos`, `test_ui_lab`, `test_ui_scalp`, `test_ui_analytics`, `test_ui_monitor`, `test_ui_setup_panel`, `test_ui_signal_card`, `test_ui_control_center`, `test_ui_training_center`, `test_release_tools`, `test_launchers` | 65/65 OK |
| Rozdzielczości 1920×1080, 1672×941, 1366×768, 390×844 | brak poziomego przewijania (menu, PEPE$WTC, PEPE$SIGNAL) |
| `tsc -b`, `vite build` | bez błędów |

Środowisko: Linux, Chromium headless, backend `--demo` (symulator MT5). Nie testowano na prawdziwym terminalu MT5 ani z zainstalowanym Kronosem.

## 5. Ograniczenia i braki

* Brak modeli 3D (wieże, Pepe z rigiem) – menu jest 2.5D.
* Pixel-perfect 1:1 wnętrz wież nie jest deklarowany: układ kolumn, kolejność i treść kart odpowiadają referencjom, ale wysokości sekcji wynikają z prawdziwych danych (np. wykres z panelami RSI/MACD, lista modeli bota zamiast fikcyjnych Kronos/XGBoost/CatBoost/Decision Tree/Neural – CatBoost w bocie nie istnieje).
* Wersja aplikacji, paczki wydania, `MANIFEST_SHA256.txt` i `PepeMarketWizard.exe` nie zostały przebudowane w tym kroku.
